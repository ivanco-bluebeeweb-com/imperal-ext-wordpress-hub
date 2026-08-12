"""WooCommerce webhooks (Group L of the developer/backend roadmap,
docs/2026-08-11-developer-backend-functions-plan.md).

Native `wc/v3/webhooks` REST route -- shipped by WooCommerce core itself
(not a WordPress core route), documented at
developer.woocommerce.com/docs/apis/rest-api/v3/webhooks/. Lets a backend
developer wire this site into an external system (order sync, inventory
feed, a Slack/Zapier-style relay) without ever touching wp-admin. No Bridge
or SSH needed -- same Application-Password auth as every other WooCommerce
function in this app.

`secret` is write-only per WooCommerce's own schema (never returned by a
GET), so it is never echoed back in any response entity here either.
"""
import hashlib
import json

from imperal_sdk import ActionResult, sdl

from app import chat
from handlers_woocommerce import WC_BASE, _authed, _failure, _request
from models import (
    ApplyBulkWebhookStatusParams,
    BulkWebhookStatusParams,
    BulkWebhookStatusResult,
    CreateWebhookParams,
    DeleteWebhookParams,
    ListWebhooksParams,
    UpdateWebhookParams,
    Webhook,
    WebhookDeleteResult,
    WebhookIdParams,
)
from wp_client import wp_request

_STATUSES = {"active", "paused", "disabled"}


def _error(message, code="WOOCOMMERCE_INVALID_OPERATION"):
    return ActionResult.error(message, retryable=False, code=code)


def _webhook_entity(w: dict) -> Webhook:
    return Webhook(
        id=str(w.get("id", "")), title=w.get("name", "") or f"Webhook #{w.get('id', '')}",
        kind="wc_webhook", status=w.get("status", ""), topic=w.get("topic", ""),
        resource=w.get("resource", ""), event=w.get("event", ""),
        delivery_url=w.get("delivery_url", ""),
        date_created=str(w.get("date_created", "") or ""),
        date_modified=str(w.get("date_modified", "") or ""),
    )


async def _write(ctx, method, site_id, path, payload):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, err
    base_url, username, password = auth
    try:
        response = await wp_request(
            ctx, method, base_url, f"{WC_BASE}{path}", username=username,
            app_password=password, json=payload)
    except Exception as exc:
        await ctx.log(f"WooCommerce {method.upper()} {path} failed: {exc}", level="error")
        return None, ActionResult.error(
            "Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return None, _failure(response.status_code, response.body)
    if not isinstance(response.body, dict):
        return None, ActionResult.error(
            "WooCommerce returned an unexpected response.", retryable=False,
            code="WOOCOMMERCE_INVALID_RESPONSE")
    return response.body, None


@chat.function(
    "list_registered_webhooks",
    description=(
        "List WooCommerce webhooks configured on a site -- URL, topic (e.g. order.created), "
        "and status (active/paused/disabled). Native `wc/v3/webhooks` -- requires WooCommerce."
    ),
    action_type="read", data_model=sdl.EntityList[Webhook],
)
async def list_registered_webhooks(ctx, params: ListWebhooksParams) -> ActionResult:
    """GET /wc/v3/webhooks."""
    query = {"per_page": params.limit, "orderby": "date", "order": "desc"}
    status = params.status.strip().lower()
    if status:
        if status not in _STATUSES:
            return _error("status must be 'active', 'paused', or 'disabled'.")
        query["status"] = status
    data, err = await _request(ctx, params.site_id, "/webhooks", query)
    if err:
        return err
    items = [_webhook_entity(w) for w in data]
    return ActionResult.success(sdl.EntityList[Webhook](items=items), summary=f"{len(items)} webhook(s)")


@chat.function(
    "get_webhook",
    description="Read one WooCommerce webhook's full configuration (topic, delivery URL, status, dates). Secret is never returned by WooCommerce.",
    action_type="read", data_model=Webhook,
)
async def get_webhook(ctx, params: WebhookIdParams) -> ActionResult:
    """GET /wc/v3/webhooks/{id}."""
    data, err = await _request(ctx, params.site_id, f"/webhooks/{params.webhook_id}", expected_type=dict)
    if err:
        return err
    entity = _webhook_entity(data)
    return ActionResult.success(entity, summary=f"Webhook {entity.title}: {entity.status}, {entity.topic}")


@chat.function(
    "create_webhook",
    description=(
        "Create a WooCommerce webhook: which topic to fire on (order.created, product.updated, "
        "etc.) and the HTTPS URL to deliver the payload to. Lets a backend developer wire this "
        "site into an external system without touching wp-admin."
    ),
    action_type="write", data_model=Webhook,
    effects=["wc.webhook_create"], event="wordpress-hub.create_webhook",
)
async def create_webhook(ctx, params: CreateWebhookParams) -> ActionResult:
    """POST /wc/v3/webhooks."""
    status = params.status.strip().lower()
    if status not in _STATUSES:
        return _error("status must be 'active', 'paused', or 'disabled'.")
    delivery_url = params.delivery_url.strip()
    if not delivery_url:
        return _error("delivery_url is required.")
    if not delivery_url.lower().startswith("https://"):
        return _error("delivery_url must be an https:// URL.")
    payload = {"topic": params.topic.strip(), "delivery_url": delivery_url, "status": status}
    if params.name.strip():
        payload["name"] = params.name.strip()
    if params.secret:
        payload["secret"] = params.secret
    data, err = await _write(ctx, "post", params.site_id, "/webhooks", payload)
    if err:
        return err
    entity = _webhook_entity(data)
    return ActionResult.success(
        entity, summary=f"Created webhook {entity.title} → {entity.topic}", refresh_panels=["center"])


@chat.function(
    "update_webhook",
    description="Change URL/topic/status/secret on an existing WooCommerce webhook without touching omitted fields.",
    action_type="write", data_model=Webhook,
    effects=["wc.webhook_update"], event="wordpress-hub.update_webhook",
)
async def update_webhook(ctx, params: UpdateWebhookParams) -> ActionResult:
    """POST /wc/v3/webhooks/{id} -- WooCommerce's own webhooks endpoint uses POST for partial updates, not PUT."""
    payload = {}
    if params.topic is not None:
        payload["topic"] = params.topic.strip()
    if params.delivery_url is not None:
        delivery_url = params.delivery_url.strip()
        if not delivery_url.lower().startswith("https://"):
            return _error("delivery_url must be an https:// URL.")
        payload["delivery_url"] = delivery_url
    if params.name is not None:
        payload["name"] = params.name.strip()
    if params.secret is not None:
        payload["secret"] = params.secret
    if params.status is not None:
        status = params.status.strip().lower()
        if status not in _STATUSES:
            return _error("status must be 'active', 'paused', or 'disabled'.")
        payload["status"] = status
    if not payload:
        return _error("No webhook fields were supplied.", code="WOOCOMMERCE_NO_CHANGES")
    data, err = await _write(ctx, "post", params.site_id, f"/webhooks/{params.webhook_id}", payload)
    if err:
        return err
    entity = _webhook_entity(data)
    return ActionResult.success(entity, summary=f"Updated webhook {entity.title}", refresh_panels=["center"])


@chat.function(
    "delete_webhook",
    description="Permanently remove a WooCommerce webhook. Use list_registered_webhooks first to find the webhook_id.",
    action_type="destructive", data_model=WebhookDeleteResult,
    effects=["wc.webhook_delete"], event="wordpress-hub.delete_webhook",
)
async def delete_webhook(ctx, params: DeleteWebhookParams) -> ActionResult:
    """DELETE /wc/v3/webhooks/{id}?force=true (WooCommerce's webhooks endpoint has no Trash -- force is mandatory)."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    try:
        response = await wp_request(
            ctx, "delete", base_url, f"{WC_BASE}/webhooks/{params.webhook_id}",
            username=username, app_password=password, params={"force": True})
    except Exception as exc:
        await ctx.log(f"WooCommerce DELETE /webhooks failed: {exc}", level="error")
        return ActionResult.error(
            "Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    return ActionResult.success(
        WebhookDeleteResult(id=str(params.webhook_id), title=str(params.webhook_id),
                             kind="wc_webhook_delete", deleted=True),
        summary=f"Webhook {params.webhook_id} deleted", refresh_panels=["center"])


def _webhook_state_token(rows: list[dict]) -> str:
    state = [{"id": row.get("id"), "status": row.get("status", ""), "date_modified": str(row.get("date_modified", ""))}
             for row in sorted(rows, key=lambda value: value.get("id", 0))]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_webhook_targets(ctx, params: BulkWebhookStatusParams):
    status = params.status.strip().lower()
    if status not in _STATUSES:
        return None, _error("status must be 'active', 'paused', or 'disabled'.")
    if len(set(params.webhook_ids)) != len(params.webhook_ids):
        return None, ActionResult.error("Each webhook id may appear only once.", retryable=False,
                                        code="WEBHOOK_DUPLICATE_IDS")
    rows = []
    for webhook_id in params.webhook_ids:
        data, err = await _request(ctx, params.site_id, f"/webhooks/{webhook_id}", expected_type=dict)
        if err:
            return None, err
        rows.append(data)
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, password = auth
    return (base_url, username, password, status, rows), None


@chat.function(
    "preview_bulk_webhook_status",
    description="Preview changing status for 1-100 explicit WooCommerce webhooks. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkWebhookStatusResult,
)
async def preview_bulk_webhook_status(ctx, params: BulkWebhookStatusParams) -> ActionResult:
    """Read every explicit webhook target and return a reviewed batch diff."""
    targets, err = await _bulk_webhook_targets(ctx, params)
    if err:
        return err
    _, _, _, status, rows = targets
    changes = [f"#{row.get('id')}: {row.get('status', '')} -> {status}" for row in rows]
    return ActionResult.success(BulkWebhookStatusResult(
        id=params.site_id, preview=True, requested=len(params.webhook_ids), matched=len(rows),
        state_token=_webhook_state_token(rows), changes=changes),
        summary=f"Preview: {len(rows)} webhook(s) would move to '{status}'; no changes made.")


@chat.function(
    "apply_bulk_webhook_status",
    description="Apply a previously previewed status change to 1-100 explicit WooCommerce webhooks. Re-reads every target and stops before all writes if any webhook changed.",
    action_type="write", data_model=BulkWebhookStatusResult,
    effects=["wc.webhook_bulk_status_update"], event="wordpress-hub.apply_bulk_webhook_status",
)
async def apply_bulk_webhook_status(ctx, params: ApplyBulkWebhookStatusParams) -> ActionResult:
    """Recheck the webhook batch snapshot, then apply the reviewed status change."""
    targets, err = await _bulk_webhook_targets(ctx, params)
    if err:
        return err
    base_url, username, password, status, rows = targets
    if _webhook_state_token(rows) != params.expected_state_token:
        return ActionResult.error("One or more webhooks changed since preview; preview again before applying.",
                                  retryable=False, code="WEBHOOK_BULK_STATE_CHANGED")
    updated_ids, failed_ids = [], []
    for row in rows:
        webhook_id = int(row.get("id", 0))
        data, werr = await _write(ctx, "post", params.site_id, f"/webhooks/{webhook_id}", {"status": status})
        if werr:
            failed_ids.append(webhook_id)
            continue
        updated_ids.append(webhook_id)
    result = BulkWebhookStatusResult(id=params.site_id, preview=False, requested=len(params.webhook_ids),
                                     matched=len(rows), updated=len(updated_ids), failed=len(failed_ids),
                                     updated_ids=updated_ids, failed_ids=failed_ids)
    if not updated_ids:
        return ActionResult.error("No webhooks were updated.", retryable=False, code="WEBHOOK_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Updated {len(updated_ids)} webhook(s) to '{status}'; {len(failed_ids)} failed.",
                                refresh_panels=["center"])
