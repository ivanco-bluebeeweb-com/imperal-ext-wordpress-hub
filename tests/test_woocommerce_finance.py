"""Contract and safety tests for guarded manual refunds."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_finance as hf
import storage
from models import CreateRefundParams, PreviewRefundParams

BASE = "https://shop.test/wp-json/wc/v3"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _order(total="55.17"):
    return {"id": 15, "number": "15", "status": "processing", "total": total,
            "currency": "USD", "payment_method": "cod"}


def _refund(rid=7, amount="5.00", key=""):
    meta = [{"key": hf._IDEMPOTENCY_META_KEY, "value": key}] if key else []
    return {"id": rid, "amount": amount, "reason": "Adjustment",
            "date_created": "2026-08-02T12:00:00", "meta_data": meta}


def _mock_state(ctx, refunds=None, total="55.17"):
    # MockContext matches URL substrings, so register the specific route first.
    ctx.http.mock_get(f"{BASE}/orders/15/refunds", refunds or [], 200)
    ctx.http.mock_get(f"{BASE}/orders/15", _order(total), 200)


def _spy(ctx):
    calls = []
    original = ctx.http.post

    async def wrapped(*args, **kwargs):
        calls.append((args, kwargs))
        return await original(*args, **kwargs)

    ctx.http.post = wrapped
    return calls


async def test_preview_refund_is_read_only_and_calculates_remaining():
    ctx = await _ctx()
    _mock_state(ctx, [_refund(amount="5.00")])
    result = await hf.preview_refund(ctx, PreviewRefundParams(
        site_id="shop-test", order_id=15, amount="10", reason=" Courtesy "))
    assert result.status == "success" and result.data.preview is True
    assert result.data.order_total == "55.17"
    assert result.data.already_refunded == "5.00"
    assert result.data.remaining_refundable == "50.17"
    assert result.data.requested_amount == "10.00"
    assert result.data.gateway_refund is False and result.data.restock_items is False


async def test_preview_rejects_non_positive_and_excess_amounts():
    ctx = await _ctx()
    invalid = await hf.preview_refund(ctx, PreviewRefundParams(
        site_id="shop-test", order_id=15, amount="0"))
    _mock_state(ctx, [_refund(amount="50.00")])
    excess = await hf.preview_refund(ctx, PreviewRefundParams(
        site_id="shop-test", order_id=15, amount="6.00"))
    assert invalid.status == "error" and invalid.error_code == "WOOCOMMERCE_INVALID_REFUND"
    assert excess.status == "error" and excess.error_code == "WOOCOMMERCE_REFUND_EXCEEDS_REMAINING"


async def test_create_manual_refund_uses_no_gateway_and_no_restock():
    ctx = await _ctx()
    _mock_state(ctx)
    created = _refund(rid=8, amount="10.00", key="refund-key-0001")
    ctx.http.mock_post(f"{BASE}/orders/15/refunds", created, 201)
    seen = _spy(ctx)
    result = await hf.create_manual_refund(ctx, CreateRefundParams(
        site_id="shop-test", order_id=15, amount="10", reason=" Courtesy ",
        expected_remaining_amount="55.17", idempotency_key="refund-key-0001"))
    assert result.status == "success" and result.data.id == "8"
    assert result.data.remaining_refundable == "45.17"
    payload = seen[-1][1]["json"]
    assert payload == {
        "amount": "10.00", "reason": "Courtesy",
        "api_refund": False, "api_restock": False,
        "meta_data": [{"key": hf._IDEMPOTENCY_META_KEY, "value": "refund-key-0001"}],
    }


async def test_create_stops_when_preview_state_changed():
    ctx = await _ctx()
    _mock_state(ctx, [_refund(amount="1.00")])
    result = await hf.create_manual_refund(ctx, CreateRefundParams(
        site_id="shop-test", order_id=15, amount="10",
        expected_remaining_amount="55.17", idempotency_key="refund-key-0002"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_REFUND_STATE_CHANGED"


async def test_duplicate_idempotency_key_returns_existing_without_post():
    ctx = await _ctx()
    _mock_state(ctx, [_refund(rid=9, amount="10.00", key="refund-key-0003")])
    seen = _spy(ctx)
    result = await hf.create_manual_refund(ctx, CreateRefundParams(
        site_id="shop-test", order_id=15, amount="10",
        expected_remaining_amount="45.17", idempotency_key="refund-key-0003"))
    assert result.status == "success" and result.data.id == "9"
    assert result.data.requested_amount == "10.00"
    assert seen == []
