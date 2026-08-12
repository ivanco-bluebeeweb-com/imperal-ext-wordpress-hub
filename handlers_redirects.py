"""Rank Math URL redirects: list, create, delete, and change status.

Rank Math never registers REST routes for its own Redirections module (the
admin UI talks to admin-ajax.php, not the REST API), so this is a genuine
gap the same way per-post SEO meta was before SECTION 1 of the Imperal
Bridge existed. This module talks exclusively to Imperal Bridge SECTION 5
(/wp-json/imperal/v1/redirects) -- there is no stock-WordPress fallback
tier, because there is no core concept of a redirect for us to fall back
onto.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ApplyBulkRedirectStatusParams,
    BulkRedirectStatusParams,
    BulkRedirectStatusResult,
    CreateRedirectParams,
    DeleteRedirectParams,
    ListRedirectsParams,
    Redirect,
    RedirectDeleteResult,
    RedirectSource,
    SetRedirectStatusParams,
)
import hashlib
import json

import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post, wp_request

BRIDGE_PATH = "/wp-json/imperal/v1/redirects"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin on the site (bridge/imperal-bridge "
    "in the connector repo) and make sure Rank Math's Redirections module is enabled."
)


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], pw), None


def _failure(status_code, body):
    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal Bridge plugin installed, or it is "
                "older than the version that adds redirects. " + _INSTALL_HINT,
                retryable=False, code="REDIRECTS_BRIDGE_MISSING")
        if wp_code == "imperal_redirects_not_found":
            return ActionResult.error(
                wp_message or "No Rank Math redirections table found — is Rank Math "
                "installed with the Redirections module enabled?",
                retryable=False, code="REDIRECTS_MODULE_MISSING")
        if wp_code == "imperal_redirects_item_not_found":
            return ActionResult.error(
                wp_message or "No redirect with that id.",
                retryable=False, code="REDIRECT_NOT_FOUND")
        if wp_code == "imperal_redirects_invalid":
            return ActionResult.error(
                wp_message or "Invalid redirect data.", retryable=False,
                code="REDIRECT_INVALID")
        if wp_message:
            return ActionResult.error(
                wp_message, retryable=status_code >= 500, code=wp_error_code(status_code))
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _redirect_entity(item: dict) -> Redirect:
    sources = [
        RedirectSource(pattern=s.get("pattern", ""), comparison=s.get("comparison", "exact"))
        for s in (item.get("sources") or []) if isinstance(s, dict)
    ]
    rid = item.get("id", 0)
    return Redirect(
        id=str(rid), title=item.get("url_to", ""), kind="wp_redirect",
        sources=sources, url_to=item.get("url_to", ""),
        header_code=int(item.get("header_code", 301) or 301),
        hits=int(item.get("hits", 0) or 0), status=item.get("status", ""),
        created=item.get("created", ""), updated=item.get("updated", ""),
    )


@chat.function(
    "list_redirects",
    description=(
        "List Rank Math URL redirects on a site — which old URLs redirect to which new ones, "
        "with hit counts. Requires the Imperal Bridge plugin and Rank Math's Redirections module."
    ),
    action_type="read", data_model=sdl.EntityList[Redirect],
)
async def list_redirects(ctx, params: ListRedirectsParams) -> ActionResult:
    """GET /imperal/v1/redirects."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    q = {} if params.status == "all" else {"status": params.status}
    r = await wp_get(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw, params=q)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else (r.body or {}).get("redirects", [])
    if not isinstance(data, list):
        data = []
    items = [_redirect_entity(item) for item in data]
    total_hits = sum(i.hits for i in items)
    return ActionResult.success(
        sdl.EntityList[Redirect](items=items),
        summary=f"{len(items)} redirect(s), {total_hits} total hit(s)")


@chat.function(
    "create_redirect",
    description=(
        "Create a Rank Math URL redirect: which URL to redirect FROM (source_pattern), where "
        "TO (url_to), and the HTTP status code (301 permanent, 302 temporary, 410 gone). "
        "Requires the Imperal Bridge plugin and Rank Math's Redirections module."
    ),
    action_type="write", data_model=Redirect,
    effects=["wp.redirect_create"], event="wordpress-hub.create_redirect",
)
async def create_redirect(ctx, params: CreateRedirectParams) -> ActionResult:
    """POST /imperal/v1/redirects."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    payload = {
        "sources": [{"pattern": params.source_pattern, "comparison": params.source_comparison}],
        "url_to": params.url_to,
        "header_code": params.header_code,
    }
    try:
        r = await wp_post(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw, json=payload)
    except Exception as e:
        await ctx.log(f"create_redirect request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    return ActionResult.success(
        _redirect_entity(body), summary=f"Redirect created: {params.source_pattern} → {params.url_to}",
        refresh_panels=["center"])


@chat.function(
    "delete_redirect",
    description="Permanently delete a Rank Math URL redirect by id, from list_redirects.",
    action_type="write", data_model=RedirectDeleteResult,
    effects=["wp.redirect_delete"], event="wordpress-hub.delete_redirect",
)
async def delete_redirect(ctx, params: DeleteRedirectParams) -> ActionResult:
    """DELETE /imperal/v1/redirects/{id}."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_request(
            ctx, "delete", base_url, f"{BRIDGE_PATH}/{params.redirect_id}",
            username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"delete_redirect request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    return ActionResult.success(
        RedirectDeleteResult(id=str(params.redirect_id), title=str(params.redirect_id),
                             kind="wp_redirect_delete", deleted=True),
        summary=f"Redirect {params.redirect_id} deleted", refresh_panels=["center"])


@chat.function(
    "set_redirect_status",
    description=(
        "Change a redirect's status: 'active' (live), 'inactive' (paused, does not redirect), "
        "or 'trashed'. Use list_redirects first to find the redirect_id."
    ),
    action_type="write", data_model=Redirect,
    effects=["wp.redirect_status_update"], event="wordpress-hub.set_redirect_status",
)
async def set_redirect_status(ctx, params: SetRedirectStatusParams) -> ActionResult:
    """POST /imperal/v1/redirects/{id}/status."""
    status = params.status.strip().lower()
    if status not in ("active", "inactive", "trashed"):
        return ActionResult.error(
            "status must be 'active', 'inactive', or 'trashed'.",
            retryable=False, code="REDIRECT_INVALID_STATUS")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_post(
            ctx, base_url, f"{BRIDGE_PATH}/{params.redirect_id}/status",
            username=username, app_password=pw, json={"status": status})
    except Exception as e:
        await ctx.log(f"set_redirect_status request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = _redirect_entity(body) if body else Redirect(
        id=str(params.redirect_id), title=str(params.redirect_id), kind="wp_redirect", status=status)
    return ActionResult.success(result, summary=f"Redirect {params.redirect_id} is now {status}",
                                 refresh_panels=["center"])


def _redirect_state_token(rows: list[dict]) -> str:
    state = [{"id": row.get("id"), "status": row.get("status", ""), "updated": row.get("updated", "")}
             for row in sorted(rows, key=lambda value: value.get("id", 0))]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_redirect_targets(ctx, params: BulkRedirectStatusParams):
    status = params.status.strip().lower()
    if status not in ("active", "inactive", "trashed"):
        return None, ActionResult.error(
            "status must be 'active', 'inactive', or 'trashed'.",
            retryable=False, code="REDIRECT_INVALID_STATUS")
    if len(set(params.redirect_ids)) != len(params.redirect_ids):
        return None, ActionResult.error("Each redirect id may appear only once.", retryable=False,
                                        code="REDIRECT_DUPLICATE_IDS")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw, params={"status": "all"})
    if not 200 <= r.status_code < 300:
        return None, _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else (r.body or {}).get("redirects", [])
    if not isinstance(data, list):
        data = []
    by_id = {int(row.get("id", 0)): row for row in data if isinstance(row, dict)}
    missing = [rid for rid in params.redirect_ids if rid not in by_id]
    if missing:
        return None, ActionResult.error(
            f"Redirect id(s) not found: {', '.join(str(m) for m in missing)}. Run list_redirects first.",
            retryable=False, code="REDIRECT_NOT_FOUND")
    rows = [by_id[rid] for rid in params.redirect_ids]
    return (base_url, username, pw, status, rows), None


@chat.function(
    "preview_bulk_redirect_status",
    description="Preview changing status ('active'/'inactive'/'trashed') for 1-100 explicit Rank Math redirects. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkRedirectStatusResult,
)
async def preview_bulk_redirect_status(ctx, params: BulkRedirectStatusParams) -> ActionResult:
    """Read every explicit redirect target and return a reviewed batch diff."""
    targets, err = await _bulk_redirect_targets(ctx, params)
    if err:
        return err
    _, _, _, status, rows = targets
    changes = [f"#{row.get('id')}: {row.get('status', '')} → {status}" for row in rows]
    return ActionResult.success(BulkRedirectStatusResult(
        id=params.site_id, title="Bulk redirect status preview", kind="wp_bulk_redirect_status", preview=True,
        requested=len(params.redirect_ids), matched=len(rows),
        state_token=_redirect_state_token(rows), changes=changes),
        summary=f"Preview: {len(rows)} redirect(s) would become '{status}'")


@chat.function(
    "apply_bulk_redirect_status",
    description="Apply a previewed status change to 1-100 explicit Rank Math redirects. Re-reads every target and stops before all writes if any redirect changed.",
    action_type="write", data_model=BulkRedirectStatusResult,
    effects=["wp.redirect_bulk_status_update"], event="wordpress-hub.apply_bulk_redirect_status",
)
async def apply_bulk_redirect_status(ctx, params: ApplyBulkRedirectStatusParams) -> ActionResult:
    """Recheck the redirect batch snapshot, then apply the reviewed status change."""
    targets, err = await _bulk_redirect_targets(ctx, params)
    if err:
        return err
    base_url, username, pw, status, rows = targets
    if _redirect_state_token(rows) != params.expected_state_token:
        return ActionResult.error("One or more redirects changed since preview; preview again before applying.",
                                  retryable=False, code="REDIRECT_BULK_STATE_CHANGED")
    updated_ids, failed_ids = [], []
    for row in rows:
        rid = int(row.get("id", 0))
        try:
            resp = await wp_post(ctx, base_url, f"{BRIDGE_PATH}/{rid}/status",
                                 username=username, app_password=pw, json={"status": status})
        except Exception as exc:
            await ctx.log(f"bulk redirect status #{rid} failed: {exc}", level="error")
            failed_ids.append(rid)
            continue
        if 200 <= resp.status_code < 300:
            updated_ids.append(rid)
        else:
            failed_ids.append(rid)
    result = BulkRedirectStatusResult(id=params.site_id, preview=False, requested=len(params.redirect_ids),
                                      matched=len(rows), updated=len(updated_ids), failed=len(failed_ids),
                                      updated_ids=updated_ids, failed_ids=failed_ids)
    if not updated_ids:
        return ActionResult.error("No redirects were updated.", retryable=True, code="REDIRECT_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Set {len(updated_ids)} redirect(s) to '{status}'; {len(failed_ids)} failed.",
                                refresh_panels=["center"])
