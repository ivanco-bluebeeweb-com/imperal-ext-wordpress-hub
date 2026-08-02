"""Guarded WooCommerce financial operations.

Stage 2A intentionally supports manual refund records only. It never asks a
payment gateway to move money and never restocks line items automatically.
Every execution re-reads the order and its refunds, compares the remaining
amount with the reviewed preview, and requires a unique idempotency key.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from imperal_sdk import ActionResult

from app import chat
from handlers_woocommerce import WC_BASE, _authed, _failure, _request
from models import CreateRefundParams, PreviewRefundParams, RefundOperation
from wp_client import wp_request

_CENTS = Decimal("0.01")
_IDEMPOTENCY_META_KEY = "_imperal_refund_idempotency_key"


def _error(message, code="WOOCOMMERCE_INVALID_REFUND", *, retryable=False):
    return ActionResult.error(message, retryable=retryable, code=code)


def _amount(value, field, *, positive=False):
    try:
        amount = Decimal(str(value).strip()).quantize(_CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None, _error(f"{field} must be a decimal amount.")
    if amount < 0 or (positive and amount <= 0):
        rule = "positive" if positive else "non-negative"
        return None, _error(f"{field} must be a {rule} decimal amount.")
    return amount, None


def _money(value):
    return format(value.quantize(_CENTS, rounding=ROUND_HALF_UP), "f")


def _idempotency_value(refund):
    for item in refund.get("meta_data") or []:
        if item.get("key") == _IDEMPOTENCY_META_KEY:
            return str(item.get("value", ""))
    return ""


async def _refund_state(ctx, site_id, order_id):
    order, err = await _request(ctx, site_id, f"/orders/{order_id}", expected_type=dict)
    if err:
        return None, err
    refunds, err = await _request(
        ctx, site_id, f"/orders/{order_id}/refunds",
        {"per_page": 100, "orderby": "date", "order": "desc"})
    if err:
        return None, err
    total, total_err = _amount(order.get("total", ""), "order total")
    if total_err:
        return None, _error(
            "WooCommerce returned an invalid order total.",
            code="WOOCOMMERCE_INVALID_RESPONSE")
    refunded = Decimal("0")
    for refund in refunds:
        value, value_err = _amount(refund.get("amount", "0"), "refund amount")
        if value_err:
            return None, _error(
                "WooCommerce returned an invalid refund amount.",
                code="WOOCOMMERCE_INVALID_RESPONSE")
        refunded += value
    remaining = max(Decimal("0"), total - refunded)
    return (order, refunds, total, refunded, remaining), None


def _entity(order, total, refunded, remaining, requested, reason, *, preview, key="", refund=None):
    refund_id = str((refund or {}).get("id", ""))
    return RefundOperation(
        id=refund_id or f"{order.get('id', '')}-preview",
        title=(f"Refund #{refund_id}" if refund_id else f"Refund preview for order #{order.get('id', '')}"),
        kind="wc_refund_operation", status="recorded" if refund_id else "preview",
        order_id=int(order.get("id", 0) or 0), currency=str(order.get("currency", "") or ""),
        order_total=_money(total), already_refunded=_money(refunded),
        remaining_refundable=_money(remaining), requested_amount=_money(requested),
        reason=reason, gateway_refund=False, restock_items=False,
        idempotency_key=key, preview=preview,
    )


async def _post_refund(ctx, site_id, order_id, payload):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, err
    base_url, username, password = auth
    try:
        response = await wp_request(
            ctx, "post", base_url, f"{WC_BASE}/orders/{order_id}/refunds",
            username=username, app_password=password, json=payload)
    except Exception as exc:
        await ctx.log(f"WooCommerce POST refund for order {order_id} failed: {exc}", level="error")
        return None, ActionResult.error(
            "Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return None, _failure(response.status_code, response.body)
    if not isinstance(response.body, dict):
        return None, _error(
            "WooCommerce returned an unexpected refund response.",
            code="WOOCOMMERCE_INVALID_RESPONSE")
    return response.body, None


@chat.function(
    "preview_refund",
    description="Preview a manual WooCommerce refund record without changing the order or contacting the payment gateway. Shows total, already-refunded, remaining, and requested amounts.",
    action_type="read", data_model=RefundOperation)
async def preview_refund(ctx, params: PreviewRefundParams) -> ActionResult:
    """Calculate a refund preview from current order and refund data."""
    requested, err = _amount(params.amount, "amount", positive=True)
    if err:
        return err
    state, err = await _refund_state(ctx, params.site_id, params.order_id)
    if err:
        return err
    order, _, total, refunded, remaining = state
    if requested > remaining:
        return _error(
            f"Requested refund {_money(requested)} exceeds remaining refundable amount {_money(remaining)}.",
            code="WOOCOMMERCE_REFUND_EXCEEDS_REMAINING")
    entity = _entity(
        order, total, refunded, remaining, requested, params.reason.strip(), preview=True)
    return ActionResult.success(
        entity,
        summary=(f"Preview only: record {_money(requested)} {entity.currency} manually; "
                 f"{_money(remaining)} remains refundable before execution"))


@chat.function(
    "create_manual_refund",
    description="Record a previously previewed manual WooCommerce refund after explicit confirmation. This does NOT contact the payment gateway and does NOT restock items. Requires the exact remaining amount from preview and a unique idempotency key.",
    action_type="destructive", data_model=RefundOperation,
    effects=["wc.refund_manual_record"], event="wp-site-connector.create_manual_refund")
async def create_manual_refund(ctx, params: CreateRefundParams) -> ActionResult:
    """Record one confirmation-gated, idempotent manual refund."""
    requested, err = _amount(params.amount, "amount", positive=True)
    if err:
        return err
    expected, err = _amount(params.expected_remaining_amount, "expected_remaining_amount")
    if err:
        return err
    key = params.idempotency_key.strip()
    reason = params.reason.strip()
    state, err = await _refund_state(ctx, params.site_id, params.order_id)
    if err:
        return err
    order, refunds, total, refunded, remaining = state

    duplicate = next((item for item in refunds if _idempotency_value(item) == key), None)
    if duplicate:
        duplicate_amount, amount_err = _amount(duplicate.get("amount", "0"), "refund amount")
        if amount_err:
            return amount_err
        entity = _entity(
            order, total, refunded, remaining, duplicate_amount,
            str(duplicate.get("reason", "") or ""), preview=False, key=key, refund=duplicate)
        return ActionResult.success(
            entity, summary=f"Refund already recorded as #{entity.id}; no duplicate was created")

    if expected != remaining:
        return _error(
            f"Refund state changed since preview: expected {_money(expected)}, now {_money(remaining)} remains. Run preview_refund again.",
            code="WOOCOMMERCE_REFUND_STATE_CHANGED", retryable=True)
    if requested > remaining:
        return _error(
            f"Requested refund {_money(requested)} exceeds remaining refundable amount {_money(remaining)}.",
            code="WOOCOMMERCE_REFUND_EXCEEDS_REMAINING")

    payload = {
        "amount": _money(requested), "reason": reason,
        "api_refund": False, "api_restock": False,
        "meta_data": [{"key": _IDEMPOTENCY_META_KEY, "value": key}],
    }
    refund, err = await _post_refund(ctx, params.site_id, params.order_id, payload)
    if err:
        return err
    new_remaining = max(Decimal("0"), remaining - requested)
    entity = _entity(
        order, total, refunded + requested, new_remaining, requested, reason,
        preview=False, key=key, refund=refund)
    return ActionResult.success(
        entity,
        summary=(f"Recorded manual refund #{entity.id}: {_money(requested)} {entity.currency}; "
                 "payment gateway was not contacted and items were not restocked"),
        refresh_panels=["center"])
