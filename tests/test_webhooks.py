"""Contract tests for Group L WooCommerce webhooks: handlers_webhooks.py.

Native `wc/v3/webhooks` REST route (WooCommerce core, not WordPress core).
Same Application-Password auth as every other WooCommerce function.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_webhooks as hw
import storage
from models import (
    CreateWebhookParams,
    DeleteWebhookParams,
    ListWebhooksParams,
    UpdateWebhookParams,
    WebhookIdParams,
)

BASE = "https://shop.test/wp-json/wc/v3"


def _mock_delete(ctx, url_pattern, response, status=200):
    """No mock_delete helper exists on MockHTTP yet — append the DELETE tuple directly."""
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _webhook(id=1, status="active", topic="order.created", name="Order webhook"):
    return {
        "id": id, "name": name, "status": status, "topic": topic,
        "resource": topic.split(".")[0], "event": topic.split(".")[1],
        "delivery_url": "https://example.com/hook",
        "date_created": "2026-08-11T10:00:00", "date_modified": "2026-08-11T10:00:00",
    }


# ─────────── list_registered_webhooks ───────────

async def test_list_registered_webhooks_reads_native_rest():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/webhooks", [_webhook(1), _webhook(2, status="paused", topic="product.updated")], 200)
    result = await hw.list_registered_webhooks(ctx, ListWebhooksParams(site_id="shop-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    active = next(i for i in result.data.items if i.id == "1")
    assert active.status == "active"
    assert active.topic == "order.created"
    assert active.delivery_url == "https://example.com/hook"


async def test_list_registered_webhooks_unavailable_when_woocommerce_missing():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/webhooks", {"code": "rest_no_route"}, 404)
    result = await hw.list_registered_webhooks(ctx, ListWebhooksParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_UNAVAILABLE"


# ─────────── get_webhook ───────────

async def test_get_webhook_reads_one():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/webhooks/1", _webhook(1), 200)
    result = await hw.get_webhook(ctx, WebhookIdParams(site_id="shop-test", webhook_id=1))
    assert result.status == "success"
    assert result.data.id == "1"
    assert result.data.topic == "order.created"


async def test_get_webhook_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/webhooks/999", {"code": "woocommerce_rest_webhook_invalid_id"}, 404)
    result = await hw.get_webhook(ctx, WebhookIdParams(site_id="shop-test", webhook_id=999))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_ITEM_NOT_FOUND"


# ─────────── create_webhook ───────────

async def test_create_webhook_posts_expected_payload():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/webhooks", _webhook(5, topic="order.created"), 201)
    result = await hw.create_webhook(ctx, CreateWebhookParams(
        site_id="shop-test", topic="order.created", delivery_url="https://example.com/hook",
        name="Order webhook", secret="s3cr3t"))
    assert result.status == "success"
    assert result.data.id == "5"
    assert result.data.topic == "order.created"


async def test_create_webhook_rejects_missing_delivery_url():
    ctx = await _ctx()
    result = await hw.create_webhook(ctx, CreateWebhookParams(
        site_id="shop-test", topic="order.created", delivery_url=""))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_INVALID_OPERATION"


async def test_create_webhook_rejects_non_https_delivery_url():
    ctx = await _ctx()
    result = await hw.create_webhook(ctx, CreateWebhookParams(
        site_id="shop-test", topic="order.created", delivery_url="http://example.com/hook"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_INVALID_OPERATION"


# ─────────── update_webhook ───────────

async def test_update_webhook_patches_only_supplied_fields():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/webhooks/5", _webhook(5, status="paused"), 200)
    result = await hw.update_webhook(ctx, UpdateWebhookParams(
        site_id="shop-test", webhook_id=5, status="paused"))
    assert result.status == "success"
    assert result.data.status == "paused"


async def test_update_webhook_rejects_no_fields():
    ctx = await _ctx()
    result = await hw.update_webhook(ctx, UpdateWebhookParams(site_id="shop-test", webhook_id=5))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_NO_CHANGES"


async def test_update_webhook_rejects_invalid_status():
    ctx = await _ctx()
    result = await hw.update_webhook(ctx, UpdateWebhookParams(
        site_id="shop-test", webhook_id=5, status="bogus"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_INVALID_OPERATION"


# ─────────── delete_webhook ───────────

async def test_delete_webhook_success():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/webhooks/5", {"deleted": True, "previous": _webhook(5)}, 200)
    result = await hw.delete_webhook(ctx, DeleteWebhookParams(site_id="shop-test", webhook_id=5))
    assert result.status == "success"
    assert result.data.deleted is True


async def test_delete_webhook_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/webhooks/999", {"code": "woocommerce_rest_webhook_invalid_id"}, 404)
    result = await hw.delete_webhook(ctx, DeleteWebhookParams(site_id="shop-test", webhook_id=999))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_ITEM_NOT_FOUND"
