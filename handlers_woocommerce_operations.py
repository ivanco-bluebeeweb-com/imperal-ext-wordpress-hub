"""Controlled WooCommerce order, customer, and coupon operations.

Refund creation and payment-gateway actions are intentionally excluded. Risky
order transitions, customer-visible notes, and coupon archival use Imperal's
destructive confirmation gate; routine reversible writes remain audited writes.
"""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from imperal_sdk import ActionResult, sdl

from app import chat
from handlers_woocommerce import (
    WC_BASE, _authed, _coupon_entity, _customer_entity, _failure,
    _order_entity, _request,
)
from models import (
    AddOrderNoteParams,
    ArchiveCouponParams,
    Coupon,
    CreateCouponParams,
    CreateCustomerParams,
    CreateOrderParams,
    Customer,
    CustomerDeleteResult,
    CustomerOrdersParams,
    DeleteCustomerParams,
    ListOrderNotesParams,
    Order,
    OrderEmailResult,
    OrderNote,
    ResendOrderEmailParams,
    UpdateCouponParams,
    UpdateCustomerParams,
    UpdateOrderStatusParams,
    WooObjectParams,
)
from wp_client import wp_request

_ORDER_STATUSES = {"pending", "on-hold", "processing", "completed", "cancelled", "failed", "refunded"}
_RISKY_ORDER_STATUSES = {"cancelled", "failed", "refunded"}
_DISCOUNT_TYPES = {"percent", "fixed_cart", "fixed_product"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _error(message, code="WOOCOMMERCE_INVALID_OPERATION"):
    return ActionResult.error(message, retryable=False, code=code)


async def _write(ctx, site_id, path, payload):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, err
    base_url, username, password = auth
    try:
        response = await wp_request(
            ctx, "post", base_url, f"{WC_BASE}{path}", username=username,
            app_password=password, json=payload)
    except Exception as exc:
        await ctx.log(f"WooCommerce POST {path} failed: {exc}", level="error")
        return None, ActionResult.error(
            "Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return None, _failure(response.status_code, response.body)
    if not isinstance(response.body, dict):
        return None, ActionResult.error(
            "WooCommerce returned an unexpected response.", retryable=False,
            code="WOOCOMMERCE_INVALID_RESPONSE")
    return response.body, None


def _money(value, field, *, allow_empty=False):
    if value is None:
        return None, None
    text = str(value).strip()
    if allow_empty and text == "":
        return "", None
    try:
        amount = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None, _error(f"{field} must be a non-negative decimal number.")
    if amount < 0:
        return None, _error(f"{field} must be a non-negative decimal number.")
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"), None


def _coupon_payload(params, *, creating=False):
    payload = {}
    supplied = set(params.model_fields_set) if not creating else set(type(params).model_fields)

    def present(field):
        return creating or field in supplied

    code = getattr(params, "code", None)
    if present("code") and code is not None:
        code = code.strip().lower()
        if not code or any(ch.isspace() for ch in code):
            return None, _error("Coupon code must be non-empty and contain no whitespace.")
        payload["code"] = code

    discount_type = getattr(params, "discount_type", None)
    if present("discount_type") and discount_type is not None:
        if discount_type not in _DISCOUNT_TYPES:
            return None, _error("discount_type must be percent, fixed_cart, or fixed_product.")
        payload["discount_type"] = discount_type

    for field in ("amount", "minimum_amount", "maximum_amount"):
        if not present(field):
            continue
        raw = getattr(params, field, None)
        value, err = _money(raw, field, allow_empty=not creating)
        if err:
            return None, err
        if value is not None:
            payload[field] = value
    if payload.get("discount_type") == "percent" and Decimal(payload.get("amount", "0") or "0") > 100:
        return None, _error("Percent coupon amount cannot exceed 100.")
    if payload.get("minimum_amount") not in (None, "") and payload.get("maximum_amount") not in (None, ""):
        if Decimal(payload["minimum_amount"]) > Decimal(payload["maximum_amount"]):
            return None, _error("minimum_amount cannot exceed maximum_amount.")

    expires = getattr(params, "date_expires", None)
    if present("date_expires") and expires is not None:
        expires = expires.strip()
        if expires:
            try:
                date.fromisoformat(expires)
            except ValueError:
                return None, _error("date_expires must use YYYY-MM-DD.")
        payload["date_expires"] = expires or None

    direct = ("description", "usage_limit", "usage_limit_per_user", "individual_use",
              "free_shipping", "exclude_sale_items")
    for field in direct:
        if not present(field):
            continue
        value = getattr(params, field, None)
        if value is not None:
            payload[field] = value.strip() if isinstance(value, str) else value

    mappings = {
        "product_ids": "product_ids",
        "excluded_product_ids": "excluded_product_ids",
        "category_ids": "product_categories",
        "excluded_category_ids": "excluded_product_categories",
    }
    for source, target in mappings.items():
        if not present(source):
            continue
        value = getattr(params, source, None)
        if value is not None:
            payload[target] = list(dict.fromkeys(value))
    emails = getattr(params, "email_restrictions", None)
    if present("email_restrictions") and emails is not None:
        normalised = []
        for raw in emails:
            email = raw.strip().lower()
            if not _EMAIL_RE.match(email):
                return None, _error(f"Invalid email restriction: {raw}")
            if email not in normalised:
                normalised.append(email)
        payload["email_restrictions"] = normalised

    if not creating:
        payload.pop("coupon_id", None)
        payload.pop("site_id", None)
    return payload, None


def _customer_payload(params, *, creating=False):
    payload = {}
    supplied = set(params.model_fields_set) if not creating else set(type(params).model_fields)

    email = getattr(params, "email", None)
    if creating or "email" in supplied:
        email = (email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            return None, _error("Customer email address is invalid.", code="WOOCOMMERCE_INVALID_CUSTOMER")
        payload["email"] = email

    for field in ("first_name", "last_name", "username"):
        if not creating and field not in supplied:
            continue
        value = getattr(params, field, None)
        if value is not None:
            value = value.strip()
            if field == "username" and not value:
                return None, _error("Customer username cannot be empty.", code="WOOCOMMERCE_INVALID_CUSTOMER")
            payload[field] = value

    if not creating and not payload:
        return None, _error("No customer changes were provided.", code="WOOCOMMERCE_NO_CHANGES")
    return payload, None


def _note_entity(note, order_id):
    text = str(note.get("note", "") or "")
    return OrderNote(
        id=str(note.get("id", "")), title=f"Order #{order_id} note",
        kind="wc_order_note", order_id=order_id, note=text,
        description=text, customer_visible=bool(note.get("customer_note", False)),
        date_created=str(note.get("date_created", "") or ""),
        author=str(note.get("author", "") or ""),
    )


@chat.function(
    "create_order",
    description=(
        "Create a WooCommerce order manually -- for a phone/in-person sale, or any purchase "
        "taken outside the store's own checkout. Supports an existing registered customer or a "
        "guest order (billing_email required for guests)."
    ),
    action_type="write", data_model=Order,
    effects=["wc.order_create"], event="wordpress-hub.create_order")
async def create_order(ctx, params: CreateOrderParams) -> ActionResult:
    """Create one order with explicit line items; WooCommerce computes totals/tax itself."""
    status = params.status.strip().lower()
    if status not in _ORDER_STATUSES:
        return _error(f"Unsupported order status '{status}'.", code="WOOCOMMERCE_INVALID_ORDER_STATUS")
    if params.customer_id is None and not (params.billing_email or "").strip():
        return _error(
            "billing_email is required for a guest order (customer_id omitted).",
            code="WOOCOMMERCE_ORDER_MISSING_BILLING_EMAIL")
    payload = {
        "status": status,
        "line_items": [
            {"product_id": item.product_id, "quantity": item.quantity} for item in params.line_items
        ],
        "set_paid": params.set_paid,
    }
    if params.customer_id is not None:
        payload["customer_id"] = params.customer_id
    billing = {}
    if params.billing_email:
        billing["email"] = params.billing_email.strip()
    if params.billing_first_name:
        billing["first_name"] = params.billing_first_name.strip()
    if params.billing_last_name:
        billing["last_name"] = params.billing_last_name.strip()
    if billing:
        payload["billing"] = billing
    if params.customer_note:
        payload["customer_note"] = params.customer_note.strip()
    data, err = await _write(ctx, params.site_id, "/orders", payload)
    if err:
        return err
    entity = _order_entity(data, detailed=True)
    return ActionResult.success(
        entity, summary=f"Created order #{entity.id} ({status})", refresh_panels=["center"])


async def _set_order_status(ctx, params):
    status = params.status.strip().lower()
    if status not in _ORDER_STATUSES:
        return _error(
            f"Unsupported order status '{status}'.",
            code="WOOCOMMERCE_INVALID_ORDER_STATUS")
    current, err = await _request(ctx, params.site_id, f"/orders/{params.order_id}", expected_type=dict)
    if err:
        return err
    if current.get("status") == status:
        return ActionResult.success(
            _order_entity(current, detailed=True),
            summary=f"Order #{params.order_id} is already {status}")
    data, err = await _write(ctx, params.site_id, f"/orders/{params.order_id}", {"status": status})
    if err:
        return err
    if data.get("status") != status:
        return ActionResult.error(
            "WooCommerce accepted the update but returned a different order status.",
            retryable=True, code="WOOCOMMERCE_ORDER_STATUS_NOT_VERIFIED")
    return ActionResult.success(
        _order_entity(data, detailed=True),
        summary=f"Order #{params.order_id}: {current.get('status')} → {status}",
        refresh_panels=["center"])


@chat.function(
    "update_order_status",
    description="Change one WooCommerce order status. Financial refunds are not created by this tool.",
    action_type="write", data_model=Order,
    effects=["wc.order_status_update"], event="wordpress-hub.update_order_status")
async def update_order_status(ctx, params: UpdateOrderStatusParams) -> ActionResult:
    """Perform routine order transitions; risky target statuses are rejected here."""
    if params.status.strip().lower() in _RISKY_ORDER_STATUSES:
        return _error(
            "Cancelled, failed, and refunded statuses require update_order_status_risky.",
            code="WOOCOMMERCE_RISKY_STATUS_REQUIRES_CONFIRMATION")
    return await _set_order_status(ctx, params)


@chat.function(
    "update_order_status_risky",
    description="Change one order to cancelled, failed, or refunded after explicit confirmation. This changes WooCommerce status only and never sends money through a payment gateway.",
    action_type="destructive", data_model=Order,
    effects=["wc.order_status_risky"], event="wordpress-hub.update_order_status_risky")
async def update_order_status_risky(ctx, params: UpdateOrderStatusParams) -> ActionResult:
    """Gate status transitions with operational or financial meaning."""
    if params.status.strip().lower() not in _RISKY_ORDER_STATUSES:
        return _error("Use update_order_status for routine target statuses.")
    return await _set_order_status(ctx, params)


async def _add_note(ctx, params):
    note = params.note.strip()
    if not note:
        return _error("Order note cannot be blank.")
    data, err = await _write(ctx, params.site_id, f"/orders/{params.order_id}/notes", {
        "note": note, "customer_note": params.customer_visible, "added_by_user": True,
    })
    if err:
        return err
    entity = _note_entity(data, params.order_id)
    if entity.customer_visible != params.customer_visible:
        return ActionResult.error(
            "WooCommerce created the note with unexpected visibility.", retryable=True,
            code="WOOCOMMERCE_NOTE_VISIBILITY_NOT_VERIFIED")
    return ActionResult.success(entity, summary=(
        f"Added {'customer-visible' if params.customer_visible else 'private'} note to order #{params.order_id}"))


@chat.function(
    "add_private_order_note",
    description="Add a private internal note to one WooCommerce order.",
    action_type="write", data_model=OrderNote,
    effects=["wc.order_note_private"], event="wordpress-hub.add_private_order_note")
async def add_private_order_note(ctx, params: AddOrderNoteParams) -> ActionResult:
    """Add an internal note that is not visible to the customer."""
    if params.customer_visible:
        return _error("Use add_customer_order_note for a customer-visible note.")
    return await _add_note(ctx, params)


@chat.function(
    "add_customer_order_note",
    description="Add a customer-visible order note after explicit confirmation; WooCommerce may email the customer.",
    action_type="destructive", data_model=OrderNote,
    effects=["wc.order_note_customer"], event="wordpress-hub.add_customer_order_note")
async def add_customer_order_note(ctx, params: AddOrderNoteParams) -> ActionResult:
    """Gate notes that may notify the customer."""
    if not params.customer_visible:
        return _error("Set customer_visible=true for this tool.")
    return await _add_note(ctx, params)


@chat.function(
    "list_order_notes",
    description="Read the note thread on one WooCommerce order -- both private internal notes and customer-visible ones.",
    action_type="read", data_model=sdl.EntityList[OrderNote])
async def list_order_notes(ctx, params: ListOrderNotesParams) -> ActionResult:
    """List every note recorded against one order, newest first (WooCommerce's own order)."""
    data, err = await _request(ctx, params.site_id, f"/orders/{params.order_id}/notes")
    if err:
        return err
    items = [_note_entity(note, params.order_id) for note in data]
    return ActionResult.success(
        sdl.EntityList[OrderNote](items=items), summary=f"{len(items)} note(s) on order #{params.order_id}")


@chat.function(
    "resend_order_email",
    description=(
        "Re-send a WooCommerce order notification email to the customer -- the invoice/order-"
        "details email by default, or a specific template (e.g. 'customer_completed_order', "
        "'customer_on_hold_order') if given. Optionally redirect it to a different address than "
        "the order's own billing email. Uses WooCommerce's native order-actions REST endpoint "
        "(WooCommerce 9.8+); older WooCommerce versions don't expose it."
    ),
    action_type="write",
    data_model=OrderEmailResult,
    effects=["wc.order_email_sent"],
    event="wordpress-hub.resend_order_email",
)
async def resend_order_email(ctx, params: ResendOrderEmailParams) -> ActionResult:
    """Trigger a customer order email via WooCommerce's order-actions endpoint."""
    payload = {}
    if params.email:
        payload["email"] = params.email
        payload["force_email_update"] = False
    template = params.template_id.strip()
    path = (f"/orders/{params.order_id}/actions/send_email" if template
            else f"/orders/{params.order_id}/actions/send_order_details")
    if template:
        payload["template_id"] = template

    data, err = await _write(ctx, params.site_id, path, payload)
    if err:
        return err
    message = data.get("message", "") if isinstance(data, dict) else ""
    result = OrderEmailResult(
        id=str(params.order_id), title=f"Order #{params.order_id}", kind="wc_order_email",
        order_id=params.order_id, template_id=template or "customer_invoice",
        sent_to=params.email, message=message,
    )
    return ActionResult.success(result, summary=message or f"Email sent for order #{params.order_id}")


@chat.function(
    "get_customer",
    description="Read one WooCommerce customer profile without postal addresses or phone numbers.",
    action_type="read", data_model=Customer)
async def get_customer(ctx, params: WooObjectParams) -> ActionResult:
    """Read privacy-minimised details for one registered customer."""
    data, err = await _request(ctx, params.site_id, f"/customers/{params.object_id}", expected_type=dict)
    if err:
        return err
    entity = _customer_entity(data)
    return ActionResult.success(entity, summary=f"{entity.title}: {entity.orders_count} order(s), {entity.total_spent} spent")


@chat.function(
    "create_customer",
    description="Create a registered WooCommerce customer with email and optional name/username. Passwords, addresses, and phone numbers are intentionally excluded.",
    action_type="write", data_model=Customer,
    effects=["wc.customer_create"], event="wordpress-hub.create_customer")
async def create_customer(ctx, params: CreateCustomerParams) -> ActionResult:
    """Create one privacy-safe customer record without handling credentials or addresses."""
    payload, err = _customer_payload(params, creating=True)
    if err:
        return err
    data, err = await _write(ctx, params.site_id, "/customers", payload)
    if err:
        return err
    entity = _customer_entity(data)
    return ActionResult.success(entity, summary=f"Created customer #{entity.id}", refresh_panels=["center"])


@chat.function(
    "update_customer",
    description="Update email, first name, last name, or username of one registered WooCommerce customer. Addresses, phone numbers, and passwords are not exposed.",
    action_type="write", data_model=Customer,
    effects=["wc.customer_update"], event="wordpress-hub.update_customer")
async def update_customer(ctx, params: UpdateCustomerParams) -> ActionResult:
    """Update only explicitly supplied privacy-safe customer fields."""
    payload, err = _customer_payload(params)
    if err:
        return err
    data, err = await _write(ctx, params.site_id, f"/customers/{params.customer_id}", payload)
    if err:
        return err
    entity = _customer_entity(data)
    return ActionResult.success(entity, summary=f"Updated customer #{entity.id}", refresh_panels=["center"])


@chat.function(
    "delete_customer",
    description=(
        "Permanently delete a WooCommerce customer. Optionally reassign their past orders to "
        "another existing customer id -- WooCommerce requires SOME disposition for the "
        "departing customer's orders, so omitting reassign_to leaves those orders with their "
        "own stored billing snapshot (they are not deleted)."
    ),
    action_type="destructive", data_model=CustomerDeleteResult,
    effects=["wc.customer_delete"], event="wordpress-hub.delete_customer")
async def delete_customer(ctx, params: DeleteCustomerParams) -> ActionResult:
    """Delete one WooCommerce customer via /wc/v3/customers, with optional order reassignment."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    query = {"force": "true"}
    if params.reassign_to is not None:
        query["reassign"] = params.reassign_to
    response = await wp_request(
        ctx, "delete", base_url, f"{WC_BASE}/customers/{params.customer_id}",
        username=username, app_password=pw, params=query)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = CustomerDeleteResult(
        id=str(params.customer_id), title=f"Customer #{params.customer_id}", kind="wc_customer_delete",
        deleted=True, reassigned_to=str(params.reassign_to) if params.reassign_to is not None else "")
    return ActionResult.success(
        entity,
        summary=f"Deleted customer #{params.customer_id}"
                + (f", orders reassigned to #{params.reassign_to}" if params.reassign_to is not None else ""),
        refresh_panels=["center"])


@chat.function(
    "list_customer_orders",
    description="List orders belonging to one registered WooCommerce customer.",
    action_type="read", data_model=sdl.EntityList[Order])
async def list_customer_orders(ctx, params: CustomerOrdersParams) -> ActionResult:
    """Read paginated order history for an explicit customer id."""
    query = {"customer": params.customer_id, "per_page": params.limit, "page": params.page,
             "orderby": "date", "order": "desc"}
    data, err = await _request(ctx, params.site_id, "/orders", query)
    if err:
        return err
    items = [_order_entity(item) for item in data]
    return ActionResult.success(sdl.EntityList[Order](items=items), summary=f"{len(items)} order(s) for customer #{params.customer_id}")


@chat.function(
    "create_coupon",
    description="Create a WooCommerce coupon with amount, limits, expiry, product/category rules, and email restrictions.",
    action_type="write", data_model=Coupon,
    effects=["wc.coupon_create"], event="wordpress-hub.create_coupon")
async def create_coupon(ctx, params: CreateCouponParams) -> ActionResult:
    """Create one validated coupon."""
    payload, err = _coupon_payload(params, creating=True)
    if err:
        return err
    data, err = await _write(ctx, params.site_id, "/coupons", payload)
    if err:
        return err
    entity = _coupon_entity(data)
    return ActionResult.success(entity, summary=f"Created coupon {entity.code}", refresh_panels=["center"])


@chat.function(
    "update_coupon",
    description="Update selected fields of one WooCommerce coupon without changing omitted fields.",
    action_type="write", data_model=Coupon,
    effects=["wc.coupon_update"], event="wordpress-hub.update_coupon")
async def update_coupon(ctx, params: UpdateCouponParams) -> ActionResult:
    """Patch only explicitly supplied coupon fields."""
    payload, err = _coupon_payload(params)
    if err:
        return err
    supplied = params.model_fields_set - {"site_id", "coupon_id"}
    allowed = set(payload)
    payload = {key: value for key, value in payload.items() if key in allowed}
    if not supplied or not payload:
        return _error("No coupon fields were supplied.", code="WOOCOMMERCE_NO_CHANGES")
    data, err = await _write(ctx, params.site_id, f"/coupons/{params.coupon_id}", payload)
    if err:
        return err
    entity = _coupon_entity(data)
    return ActionResult.success(entity, summary=f"Updated coupon {entity.code}", refresh_panels=["center"])


@chat.function(
    "archive_coupon",
    description="Move one WooCommerce coupon to Trash without permanently deleting it.",
    action_type="destructive", data_model=Coupon,
    effects=["wc.coupon_trash"], event="wordpress-hub.archive_coupon")
async def archive_coupon(ctx, params: ArchiveCouponParams) -> ActionResult:
    """Archive and verify one coupon after confirmation."""
    _, err = await _write(ctx, params.site_id, f"/coupons/{params.coupon_id}", {"status": "trash"})
    if err:
        return err
    data, err = await _request(ctx, params.site_id, f"/coupons/{params.coupon_id}", expected_type=dict)
    if err:
        return err
    if data.get("status") != "trash":
        return ActionResult.error(
            "WooCommerce accepted the archive request but the coupon is not in Trash.",
            retryable=True, code="WOOCOMMERCE_ARCHIVE_NOT_VERIFIED")
    entity = _coupon_entity(data)
    return ActionResult.success(entity, summary=f"Moved coupon {entity.code} to Trash", refresh_panels=["center"])
