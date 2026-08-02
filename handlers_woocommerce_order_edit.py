"""Guarded quantity edits for unpaid, editable WooCommerce orders.

Only quantities of existing line items may change. Adding/removing products,
overriding prices/taxes, and editing paid or non-editable orders are excluded.
Apply is confirmation-gated and rechecks an order-state token immediately before
writing, preventing a stale preview from changing a newer order.
"""

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from imperal_sdk import ActionResult

from app import chat
from handlers_woocommerce import WC_BASE, _authed, _failure, _request
from models import (
    ApplyOrderLineChangesParams,
    OrderLineChangeResult,
    PreviewOrderLineChangesParams,
)
from wp_client import wp_request

_CENTS = Decimal("0.01")


def _error(message, code="WOOCOMMERCE_INVALID_ORDER_EDIT", *, retryable=False):
    return ActionResult.error(message, retryable=retryable, code=code)


def _money(value):
    try:
        amount = Decimal(str(value or "0")).quantize(_CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0.00")
    return format(amount, "f")


def _state(order):
    lines = sorted(
        ({"id": int(item.get("id", 0)), "quantity": int(item.get("quantity", 0) or 0),
          "total": _money(item.get("total"))}
         for item in (order.get("line_items") or [])),
        key=lambda item: item["id"])
    state = {
        "id": int(order.get("id", 0)),
        "status": str(order.get("status", "")),
        "is_editable": bool(order.get("is_editable", False)),
        "date_modified": str(order.get("date_modified_gmt") or order.get("date_modified") or ""),
        "total": _money(order.get("total")),
        "refunds": sorted(int(item.get("id", 0)) for item in (order.get("refunds") or [])),
        "lines": lines,
    }
    token = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return state, token


def _plan(order, params):
    if not bool(order.get("is_editable", False)):
        return None, _error(
            "This order is not editable in WooCommerce. Paid, completed, or otherwise locked orders are not changed.",
            code="WOOCOMMERCE_ORDER_NOT_EDITABLE")
    if order.get("date_paid") or order.get("transaction_id"):
        return None, _error(
            "Paid orders cannot have their line quantities changed by this tool.",
            code="WOOCOMMERCE_PAID_ORDER_EDIT_BLOCKED")

    requested = {}
    for change in params.changes:
        if change.line_item_id in requested:
            return None, _error(
                f"Line item {change.line_item_id} was provided more than once.",
                code="WOOCOMMERCE_DUPLICATE_LINE_ITEM")
        requested[change.line_item_id] = change.quantity

    lines = {int(item.get("id", 0)): item for item in (order.get("line_items") or [])}
    missing = sorted(set(requested) - set(lines))
    if missing:
        return None, _error(
            f"Order does not contain line item id(s): {', '.join(map(str, missing))}.",
            code="WOOCOMMERCE_LINE_ITEM_NOT_FOUND")

    payload = []
    descriptions = []
    expected_total = Decimal(str(order.get("total") or "0"))
    for line_id, quantity in requested.items():
        item = lines[line_id]
        old_quantity = int(item.get("quantity", 0) or 0)
        if quantity == old_quantity:
            continue
        if old_quantity <= 0:
            return None, _error(f"Line item {line_id} has an invalid current quantity.")
        line_total = Decimal(str(item.get("total") or "0"))
        line_subtotal = Decimal(str(item.get("subtotal") or item.get("total") or "0"))
        new_total = (line_total / old_quantity) * quantity
        new_subtotal = (line_subtotal / old_quantity) * quantity
        expected_total += new_total - line_total
        payload.append({
            "id": line_id, "quantity": quantity,
            "subtotal": _money(new_subtotal), "total": _money(new_total),
        })
        descriptions.append(f"{item.get('name', 'Item')} (line {line_id}): {old_quantity} → {quantity}")

    if not payload:
        return None, _error("The requested quantities are already set.", code="WOOCOMMERCE_NO_CHANGES")
    state, token = _state(order)
    return {
        "payload": payload, "changes": descriptions, "state_token": token,
        "current_total": state["total"], "expected_total": _money(expected_total),
    }, None


def _entity(order, plan, *, preview):
    return OrderLineChangeResult(
        id=str(order.get("id", "")), title=f"Order #{order.get('number') or order.get('id', '')} line changes",
        kind="wc_order_line_change", order_id=int(order.get("id", 0)), preview=preview,
        status=str(order.get("status", "")), currency=str(order.get("currency", "")),
        current_total=_money(order.get("total")), expected_total=plan["expected_total"],
        state_token=plan["state_token"], changes=plan["changes"])


async def _read_plan(ctx, params):
    order, err = await _request(ctx, params.site_id, f"/orders/{params.order_id}", expected_type=dict)
    if err:
        return None, None, err
    plan, err = _plan(order, params)
    return order, plan, err


@chat.function(
    "preview_order_line_changes",
    description="Preview quantity changes for explicit existing line items on one unpaid editable WooCommerce order. Makes no changes and returns a state token required by apply.",
    action_type="read", data_model=OrderLineChangeResult)
async def preview_order_line_changes(ctx, params: PreviewOrderLineChangesParams) -> ActionResult:
    """Validate and preview an order quantity edit without writing."""
    order, plan, err = await _read_plan(ctx, params)
    if err:
        return err
    entity = _entity(order, plan, preview=True)
    return ActionResult.success(
        entity,
        summary=f"Preview for order #{params.order_id}: {len(plan['changes'])} line change(s), estimated total {entity.expected_total} {entity.currency}. No changes made.")


@chat.function(
    "apply_order_line_changes",
    description="Apply previously previewed quantity changes to existing line items on one unpaid editable WooCommerce order. Requires explicit confirmation and the exact state token from preview.",
    action_type="destructive", data_model=OrderLineChangeResult,
    effects=["wc.order_line_update"], event="wp-site-connector.apply_order_line_changes")
async def apply_order_line_changes(ctx, params: ApplyOrderLineChangesParams) -> ActionResult:
    """Recheck state, then change only explicit existing line quantities."""
    order, plan, err = await _read_plan(ctx, params)
    if err:
        return err
    if plan["state_token"] != params.expected_state_token.strip().lower():
        return _error(
            "Order state changed after preview. Run preview_order_line_changes again before applying.",
            code="WOOCOMMERCE_ORDER_STATE_CHANGED")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    try:
        response = await wp_request(
            ctx, "post", base_url, f"{WC_BASE}/orders/{params.order_id}",
            username=username, app_password=password,
            json={"line_items": plan["payload"]})
    except Exception as exc:
        await ctx.log(f"WooCommerce order line update failed: {exc}", level="error")
        return _error("Could not reach the site — try again.", code="WP_UNREACHABLE", retryable=True)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    if not isinstance(response.body, dict):
        return _error("WooCommerce returned an unexpected response.", code="WOOCOMMERCE_INVALID_RESPONSE")

    updated = response.body
    _, updated_token = _state(updated)
    result_plan = {**plan, "state_token": updated_token, "expected_total": _money(updated.get("total"))}
    entity = _entity(updated, result_plan, preview=False)
    return ActionResult.success(
        entity, summary=f"Updated {len(plan['changes'])} line item(s) on order #{params.order_id}; total is now {entity.current_total} {entity.currency}.",
        refresh_panels=["center"])
