"""Contract and safety tests for WooCommerce operational controls."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_operations as ho
import storage
from models import (
    AddOrderNoteParams,
    ApplyBulkCouponUpdateParams,
    ApplyBulkCustomerUpdateParams,
    ArchiveCouponParams,
    BulkCouponUpdateParams,
    BulkCustomerUpdateParams,
    CreateCouponParams,
    CreateCustomerParams,
    CreateOrderParams,
    CustomerOrdersParams,
    DeleteCustomerParams,
    ListOrderNotesParams,
    OrderLineItemInput,
    ResendOrderEmailParams,
    UpdateCouponParams,
    UpdateCustomerParams,
    UpdateOrderStatusParams,
    WooObjectParams,
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


def _order(status="processing", oid=12):
    return {
        "id": oid, "number": str(oid), "status": status,
        "currency": "USD", "total": "25.00", "date_created": "2026-08-02T12:00:00",
        "billing": {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
        "line_items": [{"name": "Mug", "quantity": 1, "subtotal": "25.00"}],
    }


def _coupon(status="publish", cid=14, **over):
    data = {
        "id": cid, "code": "save10", "status": status, "discount_type": "percent",
        "amount": "10.00", "description": "Test", "date_expires": None,
        "usage_count": 0, "usage_limit": 5, "usage_limit_per_user": 1,
        "minimum_amount": "20.00", "maximum_amount": "100.00",
        "individual_use": True, "free_shipping": False, "exclude_sale_items": True,
        "product_ids": [11], "excluded_product_ids": [],
        "product_categories": [3], "excluded_product_categories": [],
        "email_restrictions": ["ada@example.com"],
    }
    data.update(over)
    return data


def _spy(ctx, method="post"):
    calls = []
    real = getattr(ctx.http, method)

    async def wrapper(url, **kwargs):
        calls.append((url, kwargs))
        return await real(url, **kwargs)

    setattr(ctx.http, method, wrapper)
    return calls


async def test_update_order_status_writes_allowed_status():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders/12", _order("pending"), 200)
    ctx.http.mock_post(f"{BASE}/orders/12", _order("processing"), 200)
    seen = _spy(ctx)
    result = await ho.update_order_status(ctx, UpdateOrderStatusParams(
        site_id="shop-test", order_id=12, status="processing"))
    assert result.status == "success" and result.data.status == "processing"
    assert seen[-1][1]["json"] == {"status": "processing"}


async def test_update_order_status_rejects_unknown_status_before_write():
    ctx = await _ctx()
    result = await ho.update_order_status(ctx, UpdateOrderStatusParams(
        site_id="shop-test", order_id=12, status="deleted"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_INVALID_ORDER_STATUS"


async def test_update_order_status_noop_does_not_write():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders/12", _order("processing"), 200)
    result = await ho.update_order_status(ctx, UpdateOrderStatusParams(
        site_id="shop-test", order_id=12, status="processing"))
    assert result.status == "success" and result.data.status == "processing"


async def test_private_order_note_stays_private():
    ctx = await _ctx()
    note = {"id": 9, "note": "Packed", "customer_note": False,
            "date_created": "2026-08-02T12:30:00", "author": "Manager"}
    ctx.http.mock_post(f"{BASE}/orders/12/notes", note, 201)
    seen = _spy(ctx)
    result = await ho.add_private_order_note(ctx, AddOrderNoteParams(
        site_id="shop-test", order_id=12, note=" Packed "))
    assert result.status == "success" and result.data.customer_visible is False
    assert seen[-1][1]["json"] == {"note": "Packed", "customer_note": False, "added_by_user": True}


async def test_customer_visible_note_is_explicit_in_payload():
    ctx = await _ctx()
    note = {"id": 10, "note": "Shipped", "customer_note": True,
            "date_created": "2026-08-02T12:30:00", "author": "Manager"}
    ctx.http.mock_post(f"{BASE}/orders/12/notes", note, 201)
    seen = _spy(ctx)
    result = await ho.add_customer_order_note(ctx, AddOrderNoteParams(
        site_id="shop-test", order_id=12, note="Shipped", customer_visible=True))
    assert result.status == "success" and result.data.customer_visible is True
    assert seen[-1][1]["json"]["customer_note"] is True


async def test_create_coupon_normalises_full_safe_payload():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/coupons", _coupon(), 201)
    seen = _spy(ctx)
    result = await ho.create_coupon(ctx, CreateCouponParams(
        site_id="shop-test", code=" SAVE10 ", amount="10", usage_limit=5,
        usage_limit_per_user=1, minimum_amount="20", maximum_amount="100",
        individual_use=True, exclude_sale_items=True, product_ids=[11, 11],
        category_ids=[3], email_restrictions=["ADA@EXAMPLE.COM"]))
    assert result.status == "success" and result.data.code == "save10"
    payload = seen[-1][1]["json"]
    assert payload["code"] == "save10" and payload["amount"] == "10.00"
    assert payload["product_ids"] == [11]
    assert payload["email_restrictions"] == ["ada@example.com"]


async def test_percent_coupon_refuses_amount_above_100():
    ctx = await _ctx()
    result = await ho.create_coupon(ctx, CreateCouponParams(
        site_id="shop-test", code="too-much", amount="101", discount_type="percent"))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_INVALID_OPERATION"


async def test_preview_and_apply_bulk_coupon_update():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/coupons/14", _coupon(14), 200)
    ctx.http.mock_get(f"{BASE}/coupons/15", _coupon(15), 200)
    preview = await ho.preview_bulk_coupon_update(ctx, BulkCouponUpdateParams(
        site_id="shop-test", coupon_ids=[14, 15], description="Seasonal"))
    assert preview.status == "success" and preview.data.preview is True

    ctx.http.mock_get(f"{BASE}/coupons/14", _coupon(14), 200)
    ctx.http.mock_get(f"{BASE}/coupons/15", _coupon(15), 200)
    ctx.http.mock_post(f"{BASE}/coupons/14", _coupon(14, description="Seasonal"), 200)
    ctx.http.mock_post(f"{BASE}/coupons/15", _coupon(15, description="Seasonal"), 200)
    result = await ho.apply_bulk_coupon_update(ctx, ApplyBulkCouponUpdateParams(
        site_id="shop-test", coupon_ids=[14, 15], description="Seasonal",
        expected_state_token=preview.data.state_token))
    assert result.status == "success"
    assert result.data.updated == 2 and len(result.data.updated_ids) == 2


async def test_apply_bulk_coupon_update_refuses_stale_token():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/coupons/14", _coupon(14), 200)
    result = await ho.apply_bulk_coupon_update(ctx, ApplyBulkCouponUpdateParams(
        site_id="shop-test", coupon_ids=[14], description="Seasonal", expected_state_token="0" * 64))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_BULK_STATE_CHANGED"


async def test_update_coupon_only_sends_explicit_fields():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/coupons/14", _coupon(description="New"), 200)
    seen = _spy(ctx)
    result = await ho.update_coupon(ctx, UpdateCouponParams(
        site_id="shop-test", coupon_id=14, description="New"))
    assert result.status == "success"
    assert seen[-1][1]["json"] == {"description": "New"}


async def test_update_coupon_refuses_empty_change_set():
    ctx = await _ctx()
    result = await ho.update_coupon(ctx, UpdateCouponParams(
        site_id="shop-test", coupon_id=14))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_NO_CHANGES"


async def test_archive_coupon_sets_trash_and_verifies_readback():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/coupons/14", _coupon(status="trash"), 200)
    ctx.http.mock_get(f"{BASE}/coupons/14", _coupon(status="trash"), 200)
    result = await ho.archive_coupon(ctx, ArchiveCouponParams(
        site_id="shop-test", coupon_id=14))
    assert result.status == "success" and result.data.status == "trash"


async def test_get_customer_omits_addresses_and_phone():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/customers/2", {
        "id": 2, "username": "ada", "first_name": "Ada", "last_name": "Lovelace",
        "email": "ada@example.com", "orders_count": 2, "total_spent": "50.00",
        "date_created": "2026-08-01", "billing": {"phone": "+100", "address_1": "Secret"},
    }, 200)
    result = await ho.get_customer(ctx, WooObjectParams(site_id="shop-test", object_id=2))
    dumped = result.data.model_dump()
    assert dumped["username"] == "ada" and dumped["first_name"] == "Ada"
    assert "+100" not in str(dumped) and "Secret" not in str(dumped)


async def test_list_customer_orders_uses_customer_filter():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders", [_order()], 200)
    seen = _spy(ctx, "get")
    result = await ho.list_customer_orders(ctx, CustomerOrdersParams(
        site_id="shop-test", customer_id=2, limit=10))
    assert result.status == "success" and len(result.data.items) == 1
    assert seen[-1][1]["params"]["customer"] == 2


async def test_create_customer_normalises_privacy_safe_fields():
    ctx = await _ctx()
    customer = {"id": 3, "email": "new@example.com", "username": "new_user",
                "first_name": "New", "last_name": "User", "orders_count": 0,
                "total_spent": "0.00", "date_created": "2026-08-02T13:00:00"}
    ctx.http.mock_post(f"{BASE}/customers", customer, 201)
    seen = _spy(ctx)
    result = await ho.create_customer(ctx, CreateCustomerParams(
        site_id="shop-test", email=" NEW@EXAMPLE.COM ", first_name=" New ",
        last_name=" User ", username=" new_user "))
    assert result.status == "success" and result.data.email == "new@example.com"
    assert seen[-1][1]["json"] == {
        "email": "new@example.com", "first_name": "New",
        "last_name": "User", "username": "new_user"}


async def test_preview_and_apply_bulk_customer_update():
    ctx = await _ctx()
    customers = [
        {"id": 3, "email": "one@example.com", "username": "one", "first_name": "Old", "last_name": "One", "date_modified": "2026-08-01T12:00:00"},
        {"id": 4, "email": "two@example.com", "username": "two", "first_name": "Old", "last_name": "Two", "date_modified": "2026-08-01T12:00:00"},
    ]
    for customer in customers:
        ctx.http.mock_get(f"{BASE}/customers/{customer['id']}", customer, 200)
    preview = await ho.preview_bulk_customer_update(ctx, BulkCustomerUpdateParams(
        site_id="shop-test", customer_ids=[3, 4], first_name="New"))
    assert preview.status == "success" and preview.data.preview is True

    for customer in customers:
        ctx.http.mock_get(f"{BASE}/customers/{customer['id']}", customer, 200)
        ctx.http.mock_post(f"{BASE}/customers/{customer['id']}", {**customer, "first_name": "New"}, 200)
    result = await ho.apply_bulk_customer_update(ctx, ApplyBulkCustomerUpdateParams(
        site_id="shop-test", customer_ids=[3, 4], first_name="New",
        expected_state_token=preview.data.state_token))
    assert result.status == "success" and result.data.updated == 2


async def test_apply_bulk_customer_update_refuses_stale_token():
    ctx = await _ctx()
    customer = {"id": 3, "email": "one@example.com", "username": "one", "first_name": "Old", "last_name": "One"}
    ctx.http.mock_get(f"{BASE}/customers/3", customer, 200)
    result = await ho.apply_bulk_customer_update(ctx, ApplyBulkCustomerUpdateParams(
        site_id="shop-test", customer_ids=[3], first_name="New", expected_state_token="0" * 64))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_BULK_STATE_CHANGED"


async def test_update_customer_sends_only_explicit_fields():
    ctx = await _ctx()
    customer = {"id": 3, "email": "new@example.com", "username": "new_user",
                "first_name": "Updated", "last_name": "User", "orders_count": 0,
                "total_spent": "0.00", "date_created": "2026-08-02T13:00:00"}
    ctx.http.mock_post(f"{BASE}/customers/3", customer, 200)
    seen = _spy(ctx)
    result = await ho.update_customer(ctx, UpdateCustomerParams(
        site_id="shop-test", customer_id=3, first_name=" Updated "))
    assert result.status == "success" and result.data.first_name == "Updated"
    assert seen[-1][1]["json"] == {"first_name": "Updated"}


async def test_customer_validation_rejects_bad_email_and_empty_update():
    ctx = await _ctx()
    bad = await ho.create_customer(ctx, CreateCustomerParams(
        site_id="shop-test", email="not-an-email"))
    empty = await ho.update_customer(ctx, UpdateCustomerParams(
        site_id="shop-test", customer_id=3))
    assert bad.status == "error" and bad.error_code == "WOOCOMMERCE_INVALID_CUSTOMER"
    assert empty.status == "error" and empty.error_code == "WOOCOMMERCE_NO_CHANGES"


async def test_delete_customer_without_reassign():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/customers/3", {"deleted": True, "previous": {"id": 3}}, 200)
    result = await ho.delete_customer(ctx, DeleteCustomerParams(site_id="shop-test", customer_id=3))
    assert result.status == "success"
    assert result.data.deleted is True
    assert result.data.reassigned_to == ""


async def test_delete_customer_with_reassign():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/customers/3", {"deleted": True, "previous": {"id": 3}}, 200)
    result = await ho.delete_customer(ctx, DeleteCustomerParams(
        site_id="shop-test", customer_id=3, reassign_to=7))
    assert result.status == "success"
    assert result.data.reassigned_to == "7"
    assert "7" in result.summary


async def test_delete_customer_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/customers/999", {"code": "woocommerce_rest_customer_invalid_id"}, 404)
    result = await ho.delete_customer(ctx, DeleteCustomerParams(site_id="shop-test", customer_id=999))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_ITEM_NOT_FOUND"


async def test_list_order_notes_returns_note_thread():
    ctx = await _ctx()
    notes = [
        {"id": 1, "note": "Packed", "customer_note": False,
         "date_created": "2026-08-02T12:00:00", "author": "Manager"},
        {"id": 2, "note": "Shipped, tracking sent", "customer_note": True,
         "date_created": "2026-08-02T13:00:00", "author": "Manager"},
    ]
    ctx.http.mock_get(f"{BASE}/orders/12/notes", notes, 200)
    result = await ho.list_order_notes(ctx, ListOrderNotesParams(site_id="shop-test", order_id=12))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert result.data.items[0].note == "Packed" and result.data.items[0].customer_visible is False
    assert result.data.items[1].customer_visible is True


async def test_resend_order_email_default_sends_order_details():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/orders/12/actions/send_order_details",
                       {"message": "Order details sent to ada@example.com, via REST API."}, 200)
    result = await ho.resend_order_email(ctx, ResendOrderEmailParams(site_id="shop-test", order_id=12))
    assert result.status == "success"
    assert result.data.template_id == "customer_invoice"
    assert "sent" in result.summary.lower()


async def test_resend_order_email_specific_template_uses_send_email_action():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(f"{BASE}/orders/12/actions/send_email", {"message": "Email sent."}, 200)
    result = await ho.resend_order_email(ctx, ResendOrderEmailParams(
        site_id="shop-test", order_id=12, template_id="customer_completed_order"))
    assert result.status == "success"
    assert result.data.template_id == "customer_completed_order"
    url, kwargs = seen[0]
    assert url == f"{BASE}/orders/12/actions/send_email"
    assert kwargs["json"]["template_id"] == "customer_completed_order"


async def test_resend_order_email_not_found():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/orders/999/actions/send_order_details",
                       {"code": "woocommerce_rest_shop_order_invalid_id"}, 404)
    result = await ho.resend_order_email(ctx, ResendOrderEmailParams(site_id="shop-test", order_id=999))
    assert result.status == "error"


async def test_create_order_registered_customer():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/orders", _order("pending", oid=50), 201)
    seen = _spy(ctx)
    result = await ho.create_order(ctx, CreateOrderParams(
        site_id="shop-test", customer_id=3,
        line_items=[OrderLineItemInput(product_id=11, quantity=2)]))
    assert result.status == "success"
    payload = seen[-1][1]["json"]
    assert payload["customer_id"] == 3
    assert payload["line_items"] == [{"product_id": 11, "quantity": 2}]
    assert payload["status"] == "pending"


async def test_create_order_guest_requires_billing_email():
    ctx = await _ctx()
    result = await ho.create_order(ctx, CreateOrderParams(
        site_id="shop-test", line_items=[OrderLineItemInput(product_id=11, quantity=1)]))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_ORDER_MISSING_BILLING_EMAIL"


async def test_create_order_guest_with_billing_email_succeeds():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/orders", _order("pending", oid=51), 201)
    seen = _spy(ctx)
    result = await ho.create_order(ctx, CreateOrderParams(
        site_id="shop-test", billing_email="guest@example.com", set_paid=True,
        line_items=[OrderLineItemInput(product_id=11, quantity=1)]))
    assert result.status == "success"
    payload = seen[-1][1]["json"]
    assert payload["billing"] == {"email": "guest@example.com"}
    assert payload["set_paid"] is True


async def test_create_order_rejects_unsupported_status():
    ctx = await _ctx()
    result = await ho.create_order(ctx, CreateOrderParams(
        site_id="shop-test", billing_email="guest@example.com", status="deleted",
        line_items=[OrderLineItemInput(product_id=11, quantity=1)]))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_INVALID_ORDER_STATUS"
