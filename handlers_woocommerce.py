"""Read-only WooCommerce context for connected WordPress sites.

WooCommerce's authenticated wc/v3 routes accept WordPress Application
Passwords for a user with the required capabilities. This module deliberately
contains no write handlers: orders, products, customers, coupons and refunds
are business records, so the first module version only observes them.
"""

from decimal import Decimal, InvalidOperation

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    Coupon,
    Customer,
    ListCouponsParams,
    ListCustomersParams,
    ListOrdersParams,
    ListProductsParams,
    ListRefundsParams,
    Order,
    Product,
    Refund,
    SiteIdParams,
    StoreSummary,
    StoreSummaryParams,
    WooObjectParams,
    WooStatus,
)
from wp_client import wp_get, wp_error_code, wp_error_message
import storage

WC_BASE = "/wp-json/wc/v3"


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    password = await storage.get_credential(ctx, site_id)
    if not password:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], password), None


def _body_code(body):
    return str(body.get("code", "")) if isinstance(body, dict) else ""


def _failure(status_code, body):
    wp_code = _body_code(body)
    if status_code == 404 and wp_code in ("rest_no_route", "woocommerce_rest_cannot_view"):
        return ActionResult.error(
            "WooCommerce is not installed or its REST API is unavailable on this site.",
            retryable=False, code="WOOCOMMERCE_UNAVAILABLE")
    if status_code == 404:
        return ActionResult.error(
            "That WooCommerce item does not exist.",
            retryable=False, code="WOOCOMMERCE_ITEM_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot read WooCommerce data. Reconnect with an "
            "administrator or shop manager Application Password.",
            retryable=False, code="WOOCOMMERCE_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable,
        code=wp_error_code(status_code))


async def _request(ctx, site_id, path, params=None, expected_type=list):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, err
    base_url, username, password = auth
    try:
        response = await wp_get(
            ctx, base_url, f"{WC_BASE}{path}", username=username,
            app_password=password, params=params or {})
    except Exception as exc:
        await ctx.log(f"WooCommerce GET {path} failed: {exc}", level="error")
        return None, ActionResult.error(
            "Could not reach the site — try again.", retryable=True,
            code="WP_UNREACHABLE")
    if response.status_code != 200:
        return None, _failure(response.status_code, response.body)
    if not isinstance(response.body, expected_type):
        return None, ActionResult.error(
            "WooCommerce returned an unexpected response.", retryable=False,
            code="WOOCOMMERCE_INVALID_RESPONSE")
    return response.body, None


def _list_query(params):
    query = {"per_page": params.limit, "page": params.page, "orderby": "date", "order": "desc"}
    if params.search:
        query["search"] = params.search.strip()
    return query


def _money(value):
    return str(value or "")


def _decimal(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _customer_name(order):
    billing = order.get("billing") or {}
    return " ".join(p for p in (billing.get("first_name", ""), billing.get("last_name", "")) if p).strip()


def _order_entity(order, detailed=False):
    line_items = order.get("line_items") or []
    items = [f"{item.get('name', 'Item')} × {item.get('quantity', 0)}" for item in line_items]
    entity = Order(
        id=str(order.get("id", "")),
        title=f"Order #{order.get('number') or order.get('id', '')}",
        kind="wc_order",
        status=str(order.get("status", "")),
        url=str(order.get("permalink", "") or ""),
        total=_money(order.get("total")),
        currency=str(order.get("currency", "")),
        date_created=str(order.get("date_created", "") or ""),
        customer_name=_customer_name(order),
        customer_email=str((order.get("billing") or {}).get("email", "") or ""),
        item_count=sum(int(item.get("quantity", 0) or 0) for item in line_items),
        items=items,
        subtotal=_money(sum((_decimal(item.get("subtotal")) for item in line_items), Decimal("0"))),
        tax_total=_money(order.get("total_tax")),
        shipping_total=_money(order.get("shipping_total")),
        discount_total=_money(order.get("discount_total")),
        payment_method=str(order.get("payment_method_title", "") or order.get("payment_method", "") or ""),
    )
    if detailed:
        entity.customer_note = str(order.get("customer_note", "") or "")
    return entity


def _product_entity(product):
    return Product(
        id=str(product.get("id", "")),
        title=str(product.get("name", "")),
        kind="wc_product",
        status=str(product.get("status", "")),
        url=str(product.get("permalink", "") or ""),
        description=str(product.get("short_description", "") or ""),
        sku=str(product.get("sku", "") or ""),
        price=_money(product.get("price")),
        regular_price=_money(product.get("regular_price")),
        sale_price=_money(product.get("sale_price")),
        stock_status=str(product.get("stock_status", "") or ""),
        stock_quantity=product.get("stock_quantity"),
        catalog_visibility=str(product.get("catalog_visibility", "") or ""),
        categories=[str(c.get("name", "")) for c in (product.get("categories") or []) if c.get("name")],
        images=[str(i.get("src", "")) for i in (product.get("images") or []) if i.get("src")],
        attributes=[str(a.get("name", "")) for a in (product.get("attributes") or []) if a.get("name")],
        variations=[int(v) for v in (product.get("variations") or [])],
    )


def _customer_entity(customer):
    name = " ".join(p for p in (customer.get("first_name", ""), customer.get("last_name", "")) if p).strip()
    return Customer(
        id=str(customer.get("id", "")), title=name or customer.get("username", "Customer"),
        kind="wc_customer", email=str(customer.get("email", "") or ""),
        orders_count=int(customer.get("orders_count", 0) or 0),
        total_spent=_money(customer.get("total_spent")),
        date_created=str(customer.get("date_created", "") or ""),
    )


def _coupon_entity(coupon):
    return Coupon(
        id=str(coupon.get("id", "")), title=str(coupon.get("code", "")),
        kind="wc_coupon", code=str(coupon.get("code", "")),
        description=str(coupon.get("description", "") or ""),
        discount_type=str(coupon.get("discount_type", "") or ""),
        amount=_money(coupon.get("amount")),
        date_expires=str(coupon.get("date_expires", "") or ""),
        usage_count=int(coupon.get("usage_count", 0) or 0),
        usage_limit=coupon.get("usage_limit"),
    )


def _refund_entity(refund, order_id):
    return Refund(
        id=str(refund.get("id", "")), title=f"Refund #{refund.get('id', '')}",
        kind="wc_refund", order_id=order_id, amount=_money(refund.get("amount")),
        reason=str(refund.get("reason", "") or ""),
        date_created=str(refund.get("date_created", "") or ""),
        refunded_by=int(refund.get("refunded_by", 0) or 0),
    )


@chat.function(
    "get_woocommerce_status",
    description="Check whether WooCommerce and its authenticated REST API are available on a connected WordPress site.",
    action_type="read", data_model=WooStatus)
async def get_woocommerce_status(ctx, params: SiteIdParams) -> ActionResult:
    """Check whether WooCommerce and its authenticated REST API are available."""
    data, err = await _request(ctx, params.site_id, "/system_status", expected_type=dict)
    if err:
        return err
    environment = data.get("environment") or {}
    settings = data.get("settings") or {}
    entity = WooStatus(
        id=params.site_id, title="WooCommerce", kind="wc_status", available=True,
        version=str(environment.get("version", "") or ""),
        currency=str(settings.get("currency", "") or ""),
        environment=str(environment.get("wp_version", "") or ""),
    )
    return ActionResult.success(entity, summary="WooCommerce REST API is available.")


@chat.function(
    "list_orders",
    description="List WooCommerce orders with optional status, date, page, and customer/order search filters.",
    action_type="read", data_model=sdl.EntityList[Order])
async def list_orders(ctx, params: ListOrdersParams) -> ActionResult:
    """List recent WooCommerce orders with filters and privacy-safe customer details."""
    query = _list_query(params)
    for name in ("status", "after", "before"):
        value = getattr(params, name)
        if value:
            query[name] = value.strip()
    data, err = await _request(ctx, params.site_id, "/orders", query)
    if err:
        return err
    items = [_order_entity(order) for order in data]
    return ActionResult.success(sdl.EntityList[Order](items=items), summary=f"{len(items)} order(s)")


@chat.function(
    "get_order",
    description="Read one WooCommerce order in detail, including line items, totals, payment method, and customer note.",
    action_type="read", data_model=Order)
async def get_order(ctx, params: WooObjectParams) -> ActionResult:
    """Read one WooCommerce order by its numeric id."""
    data, err = await _request(ctx, params.site_id, f"/orders/{params.object_id}", expected_type=dict)
    if err:
        return err
    entity = _order_entity(data, detailed=True)
    return ActionResult.success(entity, summary=f"Order #{data.get('number') or params.object_id}: {entity.status}, {entity.total} {entity.currency}".strip())


@chat.function(
    "list_products",
    description="List WooCommerce products with prices, SKU, stock state, visibility, and optional search/status filters.",
    action_type="read", data_model=sdl.EntityList[Product])
async def list_products(ctx, params: ListProductsParams) -> ActionResult:
    """List WooCommerce products with price, SKU, publication, and stock context."""
    query = _list_query(params)
    for name in ("status", "stock_status"):
        value = getattr(params, name)
        if value:
            query[name] = value.strip()
    data, err = await _request(ctx, params.site_id, "/products", query)
    if err:
        return err
    items = [_product_entity(product) for product in data]
    return ActionResult.success(sdl.EntityList[Product](items=items), summary=f"{len(items)} product(s)")


@chat.function(
    "get_product",
    description="Read one WooCommerce product in detail, including images, categories, attributes, variations, price, and stock.",
    action_type="read", data_model=Product)
async def get_product(ctx, params: WooObjectParams) -> ActionResult:
    """Read one WooCommerce product by its numeric id."""
    data, err = await _request(ctx, params.site_id, f"/products/{params.object_id}", expected_type=dict)
    if err:
        return err
    entity = _product_entity(data)
    return ActionResult.success(entity, summary=f"{entity.title}: {entity.price}, {entity.stock_status}".strip(", "))


@chat.function(
    "list_customers",
    description="List WooCommerce customers with email, order count, and total spend; addresses and phone numbers are omitted.",
    action_type="read", data_model=sdl.EntityList[Customer])
async def list_customers(ctx, params: ListCustomersParams) -> ActionResult:
    """List WooCommerce customers without postal addresses or phone numbers."""
    data, err = await _request(ctx, params.site_id, "/customers", _list_query(params))
    if err:
        return err
    items = [_customer_entity(customer) for customer in data]
    return ActionResult.success(sdl.EntityList[Customer](items=items), summary=f"{len(items)} customer(s)")


@chat.function(
    "list_coupons",
    description="List WooCommerce coupon codes with discount type, amount, expiry, and usage limits.",
    action_type="read", data_model=sdl.EntityList[Coupon])
async def list_coupons(ctx, params: ListCouponsParams) -> ActionResult:
    """List WooCommerce coupons with discount, expiry, limits, and usage context."""
    data, err = await _request(ctx, params.site_id, "/coupons", _list_query(params))
    if err:
        return err
    items = [_coupon_entity(coupon) for coupon in data]
    return ActionResult.success(sdl.EntityList[Coupon](items=items), summary=f"{len(items)} coupon(s)")


@chat.function(
    "list_refunds",
    description="List refunds recorded against one WooCommerce order, including amount, date, and reason.",
    action_type="read", data_model=sdl.EntityList[Refund])
async def list_refunds(ctx, params: ListRefundsParams) -> ActionResult:
    """List refunds for one WooCommerce order with amount, date, and reason."""
    query = {"per_page": params.limit, "orderby": "date", "order": "desc"}
    data, err = await _request(ctx, params.site_id, f"/orders/{params.order_id}/refunds", query)
    if err:
        return err
    items = [_refund_entity(refund, params.order_id) for refund in data]
    return ActionResult.success(sdl.EntityList[Refund](items=items), summary=f"{len(items)} refund(s) for order #{params.order_id}")


@chat.function(
    "get_store_summary",
    description="Summarise WooCommerce orders, sales, refunds, items, and customers for an optional ISO-8601 date range.",
    action_type="read", data_model=StoreSummary)
async def get_store_summary(ctx, params: StoreSummaryParams) -> ActionResult:
    """Return WooCommerce sales, order, refund, item, and customer metrics for a period."""
    query = {"period": "custom"}
    if params.after:
        query["date_min"] = params.after.strip()
    if params.before:
        query["date_max"] = params.before.strip()
    data, err = await _request(ctx, params.site_id, "/reports/sales", query)
    if err:
        return err
    report = data[0] if data else {}
    entity = StoreSummary(
        id=params.site_id, title="Store summary", kind="wc_store_summary",
        period_after=params.after or "", period_before=params.before or "",
        currency=str(report.get("currency", "") or ""),
        orders=int(report.get("total_orders", 0) or 0),
        gross_sales=_money(report.get("gross_sales")),
        net_sales=_money(report.get("net_sales")),
        average_order_value=_money(report.get("average_sales")),
        refunds=_money(report.get("total_refunds")),
        total_items=int(report.get("total_items", 0) or 0),
        customers=int(report.get("total_customers", 0) or 0),
    )
    return ActionResult.success(entity, summary=f"{entity.orders} order(s), net sales {entity.net_sales} {entity.currency}".strip())
