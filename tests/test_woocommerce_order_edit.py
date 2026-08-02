"""Contract and safety tests for guarded WooCommerce order line edits."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_order_edit as he
import storage
from models import (
    ApplyOrderLineChangesParams,
    OrderLineQuantityChange,
    PreviewOrderLineChangesParams,
)

BASE = "https://shop.test/wp-json/wc/v3"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _order(*, editable=True, paid=False, quantity=1, total="19.90"):
    return {
        "id": 18, "number": "18", "status": "pending", "is_editable": editable,
        "date_modified": "2026-08-02T19:00:00", "date_modified_gmt": "2026-08-02T16:00:00",
        "date_paid": "2026-08-02T19:01:00" if paid else None,
        "transaction_id": "txn-1" if paid else "", "currency": "USD", "total": total,
        "refunds": [], "line_items": [{"id": 6, "name": "Mug", "product_id": 11,
                                        "quantity": quantity, "subtotal": total, "total": total}],
    }


def _params(quantity=2):
    return PreviewOrderLineChangesParams(
        site_id="shop-test", order_id=18,
        changes=[OrderLineQuantityChange(line_item_id=6, quantity=quantity)])


def _spy(ctx):
    calls = []
    original = ctx.http.post

    async def wrapped(*args, **kwargs):
        calls.append((args, kwargs))
        return await original(*args, **kwargs)

    ctx.http.post = wrapped
    return calls


async def test_preview_returns_state_token_and_estimate_without_post():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders/18", _order(), 200)
    seen = _spy(ctx)
    result = await he.preview_order_line_changes(ctx, _params())
    assert result.status == "success" and result.data.preview is True
    assert len(result.data.state_token) == 64
    assert result.data.current_total == "19.90" and result.data.expected_total == "39.80"
    assert result.data.changes == ["Mug (line 6): 1 → 2"]
    assert seen == []


async def test_apply_rechecks_token_and_sends_quantity_and_proportional_totals():
    ctx = await _ctx()
    order = _order()
    token = he._state(order)[1]
    ctx.http.mock_get(f"{BASE}/orders/18", order, 200)
    ctx.http.mock_post(f"{BASE}/orders/18", _order(quantity=2, total="39.80"), 200)
    seen = _spy(ctx)
    result = await he.apply_order_line_changes(ctx, ApplyOrderLineChangesParams(
        site_id="shop-test", order_id=18,
        changes=[OrderLineQuantityChange(line_item_id=6, quantity=2)],
        expected_state_token=token))
    assert result.status == "success" and result.data.preview is False
    assert result.data.current_total == "39.80"
    assert seen[-1][1]["json"] == {"line_items": [{
        "id": 6, "quantity": 2, "subtotal": "39.80", "total": "39.80"}]}


async def test_apply_blocks_stale_state_before_post():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders/18", _order(quantity=2, total="39.80"), 200)
    seen = _spy(ctx)
    result = await he.apply_order_line_changes(ctx, ApplyOrderLineChangesParams(
        site_id="shop-test", order_id=18,
        changes=[OrderLineQuantityChange(line_item_id=6, quantity=3)],
        expected_state_token="0" * 64))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_ORDER_STATE_CHANGED"
    assert seen == []


async def test_paid_and_non_editable_orders_are_blocked():
    paid_ctx = await _ctx()
    paid_ctx.http.mock_get(f"{BASE}/orders/18", _order(editable=True, paid=True), 200)
    paid = await he.preview_order_line_changes(paid_ctx, _params())
    locked_ctx = await _ctx()
    locked_ctx.http.mock_get(f"{BASE}/orders/18", _order(editable=False), 200)
    locked = await he.preview_order_line_changes(locked_ctx, _params())
    assert paid.status == "error" and paid.error_code == "WOOCOMMERCE_PAID_ORDER_EDIT_BLOCKED"
    assert locked.status == "error" and locked.error_code == "WOOCOMMERCE_ORDER_NOT_EDITABLE"


async def test_unknown_duplicate_and_noop_lines_are_rejected():
    ctx = await _ctx()
    order = _order()
    unknown = PreviewOrderLineChangesParams(
        site_id="shop-test", order_id=18,
        changes=[OrderLineQuantityChange(line_item_id=99, quantity=2)])
    duplicate = PreviewOrderLineChangesParams(
        site_id="shop-test", order_id=18,
        changes=[OrderLineQuantityChange(line_item_id=6, quantity=2),
                 OrderLineQuantityChange(line_item_id=6, quantity=3)])
    for _ in range(3):
        ctx.http.mock_get(f"{BASE}/orders/18", order, 200)
    missing = await he.preview_order_line_changes(ctx, unknown)
    repeated = await he.preview_order_line_changes(ctx, duplicate)
    noop = await he.preview_order_line_changes(ctx, _params(quantity=1))
    assert missing.error_code == "WOOCOMMERCE_LINE_ITEM_NOT_FOUND"
    assert repeated.error_code == "WOOCOMMERCE_DUPLICATE_LINE_ITEM"
    assert noop.error_code == "WOOCOMMERCE_NO_CHANGES"
