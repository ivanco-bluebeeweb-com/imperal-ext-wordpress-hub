"""Contract tests for the read-only WooCommerce module."""

import ast
import pathlib

import pytest
from imperal_sdk.testing import MockContext
from pydantic import ValidationError

import app  # noqa: F401
import handlers_woocommerce as hw
import storage
from models import (
    ListCouponsParams,
    ListCustomersParams,
    ListOrdersParams,
    ListProductsParams,
    ListRefundsParams,
    SiteIdParams,
    StoreSummaryParams,
    WooObjectParams,
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


def _order(**over):
    payload = {
        "id": 12, "number": "10012", "status": "processing",
        "date_created": "2026-08-01T12:00:00", "currency": "USD",
        "total": "125.50", "total_tax": "8.50", "shipping_total": "10.00",
        "discount_total": "5.00", "payment_method_title": "Card",
        "customer_note": "Leave at reception",
        "billing": {
            "first_name": "Ada", "last_name": "Lovelace",
            "email": "ada@example.com", "phone": "+100000000",
            "address_1": "Private street",
        },
        "shipping": {"address_1": "Private street"},
        "line_items": [
            {"name": "Blue mug", "quantity": 2, "subtotal": "100.00"},
            {"name": "Tea", "quantity": 1, "subtotal": "20.00"},
        ],
    }
    payload.update(over)
    return payload


def _spy_get(ctx):
    seen = []
    real_get = ctx.http.get

    async def spy(url, **kwargs):
        seen.append((url, kwargs.get("params") or {}))
        return await real_get(url, **kwargs)

    ctx.http.get = spy
    return seen


async def test_status_reads_system_status():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/system_status", {
        "environment": {"version": "10.1.0", "wp_version": "6.8"},
        "settings": {"currency": "USD"},
    }, 200)
    result = await hw.get_woocommerce_status(ctx, SiteIdParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.available is True
    assert result.data.version == "10.1.0" and result.data.currency == "USD"


async def test_list_orders_maps_context_and_forwards_filters():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders", [_order()], 200)
    seen = _spy_get(ctx)
    result = await hw.list_orders(ctx, ListOrdersParams(
        site_id="shop-test", limit=7, page=2, status="processing",
        after="2026-08-01T00:00:00", before="2026-08-02T00:00:00", search="Ada"))
    assert result.status == "success"
    order = result.data.items[0]
    assert order.title == "Order #10012"
    assert order.customer_name == "Ada Lovelace" and order.customer_email == "ada@example.com"
    assert order.item_count == 3 and order.items == ["Blue mug × 2", "Tea × 1"]
    assert order.subtotal == "120.00" and order.payment_method == "Card"
    sent = seen[-1][1]
    assert sent == {
        "per_page": 7, "page": 2, "orderby": "date", "order": "desc",
        "search": "Ada", "status": "processing",
        "after": "2026-08-01T00:00:00", "before": "2026-08-02T00:00:00",
    }


async def test_order_list_does_not_expose_addresses_phone_or_note():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders", [_order()], 200)
    result = await hw.list_orders(ctx, ListOrdersParams(site_id="shop-test"))
    dumped = result.data.items[0].model_dump()
    rendered = str(dumped)
    assert "Private street" not in rendered and "+100000000" not in rendered
    assert dumped["customer_note"] == ""


async def test_get_order_includes_customer_note_but_not_addresses_or_phone():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders/12", _order(), 200)
    result = await hw.get_order(ctx, WooObjectParams(site_id="shop-test", object_id=12))
    dumped = result.data.model_dump()
    assert dumped["customer_note"] == "Leave at reception"
    assert "Private street" not in str(dumped) and "+100000000" not in str(dumped)


async def test_products_map_catalog_and_stock_context():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products", [{
        "id": 8, "name": "Mug", "status": "publish", "permalink": "https://shop.test/mug",
        "short_description": "Ceramic", "sku": "MUG-1", "price": "20", "regular_price": "25",
        "sale_price": "20", "stock_status": "instock", "stock_quantity": 4,
        "catalog_visibility": "visible", "categories": [{"name": "Kitchen"}],
        "images": [{"src": "https://shop.test/mug.jpg"}],
        "attributes": [{"name": "Color"}], "variations": [81, 82],
    }], 200)
    seen = _spy_get(ctx)
    result = await hw.list_products(ctx, ListProductsParams(
        site_id="shop-test", search="Mug", status="publish", stock_status="instock"))
    product = result.data.items[0]
    assert product.sku == "MUG-1" and product.categories == ["Kitchen"]
    assert product.images == ["https://shop.test/mug.jpg"] and product.variations == [81, 82]
    assert seen[-1][1]["stock_status"] == "instock"


async def test_get_product_uses_numeric_path():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/8", {"id": 8, "name": "Mug", "price": "20"}, 200)
    result = await hw.get_product(ctx, WooObjectParams(site_id="shop-test", object_id=8))
    assert result.status == "success" and result.data.title == "Mug"


async def test_customers_omit_addresses_phone_and_use_supported_sorting():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/customers", [{
        "id": 3, "first_name": "Ada", "last_name": "Lovelace", "username": "ada",
        "email": "ada@example.com", "orders_count": 4, "total_spent": "500",
        "date_created": "2026-01-01", "billing": {"phone": "+100", "address_1": "Secret"},
    }], 200)
    seen = _spy_get(ctx)
    result = await hw.list_customers(ctx, ListCustomersParams(site_id="shop-test"))
    dumped = result.data.items[0].model_dump()
    assert dumped["orders_count"] == 4 and dumped["total_spent"] == "500"
    assert "+100" not in str(dumped) and "Secret" not in str(dumped)
    assert seen[-1][1]["orderby"] == "registered_date"


async def test_coupons_and_refunds_map_business_context():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/coupons", [{
        "id": 5, "code": "SAVE10", "discount_type": "percent", "amount": "10",
        "date_expires": "2026-12-31", "usage_count": 2, "usage_limit": 100,
    }], 200)
    coupon_result = await hw.list_coupons(ctx, ListCouponsParams(site_id="shop-test"))
    assert coupon_result.data.items[0].usage_limit == 100

    ctx.http.mock_get(f"{BASE}/orders/12/refunds", [{
        "id": 9, "amount": "20", "reason": "Damaged", "date_created": "2026-08-02",
        "refunded_by": 1,
    }], 200)
    refund_result = await hw.list_refunds(ctx, ListRefundsParams(
        site_id="shop-test", order_id=12))
    assert refund_result.data.items[0].order_id == 12
    assert refund_result.data.items[0].reason == "Damaged"


async def test_store_summary_uses_filtered_orders_for_woocommerce_10_compatibility():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders", [
        _order(id=12, total="120.00", total_refund="20.00", customer_id=7),
        _order(id=13, status="cancelled", total="40.00", customer_id=8),
    ], 200)
    seen = _spy_get(ctx)
    result = await hw.get_store_summary(ctx, StoreSummaryParams(
        site_id="shop-test", after="2026-07-01", before="2026-07-31"))
    assert result.data.orders == 1
    assert result.data.gross_sales == "120.00"
    assert result.data.net_sales == "120.00"
    assert result.data.refunds == "20.00"
    assert result.data.total_items == 3 and result.data.customers == 1
    assert seen[-1][0].endswith("/orders")
    assert seen[-1][1] == {
        "after": "2026-07-01", "before": "2026-07-31",
        "per_page": 100, "page": 1, "orderby": "date", "order": "desc",
    }


@pytest.mark.parametrize("status,body,code,retryable", [
    (404, {"code": "rest_no_route"}, "WOOCOMMERCE_UNAVAILABLE", False),
    (403, {"code": "woocommerce_rest_cannot_view"}, "WOOCOMMERCE_FORBIDDEN", False),
    (429, {}, "WP_RATE_LIMITED", True),
    (500, {}, "WP_SERVER_ERROR", True),
])
async def test_structured_http_errors(status, body, code, retryable):
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders", body, status)
    result = await hw.list_orders(ctx, ListOrdersParams(site_id="shop-test"))
    assert result.status == "error" and result.error_code == code
    assert result.retryable is retryable


async def test_unknown_site_and_missing_credential_have_distinct_codes():
    ctx = await _ctx()
    missing = await hw.list_orders(ctx, ListOrdersParams(site_id="nope"))
    assert missing.error_code == "SITE_NOT_CONNECTED"
    await storage.delete_credential(ctx, "shop-test")
    no_cred = await hw.list_orders(ctx, ListOrdersParams(site_id="shop-test"))
    assert no_cred.error_code == "SITE_CREDENTIAL_MISSING"


async def test_invalid_response_is_not_reported_as_empty_store():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/orders", {"unexpected": True}, 200)
    result = await hw.list_orders(ctx, ListOrdersParams(site_id="shop-test"))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_INVALID_RESPONSE"


def test_param_models_are_independent_and_bounded():
    assert "status" in ListOrdersParams.model_fields
    assert "stock_status" in ListProductsParams.model_fields
    assert "stock_status" not in ListCustomersParams.model_fields
    assert "order_id" in ListRefundsParams.model_fields
    with pytest.raises(ValidationError):
        ListProductsParams(site_id="shop-test", limit=101)
    with pytest.raises(ValidationError):
        WooObjectParams(site_id="shop-test", object_id=0)


def test_every_woocommerce_error_has_structural_code():
    tree = ast.parse(pathlib.Path(hw.__file__).read_text())
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "error"):
            continue
        if not any(keyword.arg == "code" for keyword in node.keywords):
            missing.append(node.lineno)
    assert not missing, f"ActionResult.error without code= at lines {missing}"
