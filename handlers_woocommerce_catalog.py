"""Controlled WooCommerce catalogue writes for products and categories.

Single reversible changes are audited writes. Moving a product to trash and
applying a bulk change are destructive tools so Imperal's KAV gate always
shows the byte-identical arguments before execution. Bulk operations accept
explicit ids only; they never infer a whole catalogue from a vague filter.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

from imperal_sdk import ActionResult, sdl

from app import chat
from handlers_woocommerce import WC_BASE, _authed, _failure, _product_entity, _request
from models import (
    ArchiveProductParams,
    BulkProductChangeParams,
    CreateProductCategoryParams,
    CreateProductParams,
    ListProductCategoriesParams,
    Product,
    ProductBulkResult,
    ProductCategory,
    UpdateProductParams,
)
from wp_client import wp_request

_PRODUCT_STATUSES = {"draft", "publish", "pending", "private"}
_STOCK_STATUSES = {"instock", "outofstock", "onbackorder"}
_PRODUCT_TYPES = {"simple", "virtual", "downloadable"}


def _validation_error(message, code="WOOCOMMERCE_INVALID_PRODUCT"):
    return ActionResult.error(message, retryable=False, code=code)


def _decimal_string(value, field, *, allow_empty=False):
    if value is None:
        return None, None
    text = str(value).strip()
    if allow_empty and text == "":
        return "", None
    try:
        amount = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None, _validation_error(f"{field} must be a non-negative decimal number.")
    if amount < 0:
        return None, _validation_error(f"{field} must be a non-negative decimal number.")
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"), None


def _https_images(urls):
    result = []
    for raw in urls or []:
        value = str(raw).strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            return None, _validation_error(
                f"Product image URL must be public HTTPS: {value or '(empty)'}.",
                code="WOOCOMMERCE_INVALID_IMAGE_URL")
        result.append({"src": value})
    return result, None


def _validate_status(value):
    if value is not None and value not in _PRODUCT_STATUSES:
        return _validation_error(
            f"Unsupported product status '{value}'. Allowed: {', '.join(sorted(_PRODUCT_STATUSES))}.")
    return None


def _validate_stock(value):
    if value is not None and value not in _STOCK_STATUSES:
        return _validation_error(
            f"Unsupported stock status '{value}'. Allowed: {', '.join(sorted(_STOCK_STATUSES))}.")
    return None


def _product_payload(params, *, creating=False):
    status_error = _validate_status(params.status)
    if status_error:
        return None, status_error
    stock_error = _validate_stock(params.stock_status)
    if stock_error:
        return None, stock_error

    payload = {}
    fields = (
        "name", "status", "sku", "description", "short_description",
        "manage_stock", "stock_quantity", "stock_status",
    )
    for field in fields:
        value = getattr(params, field)
        if value is not None:
            payload[field] = value.strip() if isinstance(value, str) else value

    for field in ("regular_price", "sale_price"):
        value, err = _decimal_string(getattr(params, field), field, allow_empty=not creating)
        if err:
            return None, err
        if value is not None:
            payload[field] = value

    categories = getattr(params, "category_ids", None)
    if categories is not None:
        payload["categories"] = [{"id": item} for item in dict.fromkeys(categories)]
    images = getattr(params, "image_urls", None)
    if images is not None:
        payload["images"], err = _https_images(images)
        if err:
            return None, err

    if getattr(params, "stock_quantity", None) is not None:
        payload["manage_stock"] = True

    if creating:
        product_type = params.product_type
        if product_type not in _PRODUCT_TYPES:
            return None, _validation_error(
                f"Unsupported product type '{product_type}'. Allowed: simple, virtual, downloadable.")
        payload["type"] = "simple"
        if product_type == "virtual":
            payload["virtual"] = True
        elif product_type == "downloadable":
            payload["virtual"] = True
            payload["downloadable"] = True
    return payload, None


async def _write(ctx, site_id, path, payload=None, *, method="post", params=None):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, err
    base_url, username, password = auth
    try:
        response = await wp_request(
            ctx, method, base_url, f"{WC_BASE}{path}", username=username,
            app_password=password, json=payload, params=params)
    except Exception as exc:
        await ctx.log(f"WooCommerce {method.upper()} {path} failed: {exc}", level="error")
        return None, ActionResult.error(
            "Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return None, _failure(response.status_code, response.body)
    if not isinstance(response.body, dict):
        return None, ActionResult.error(
            "WooCommerce returned an unexpected response.", retryable=False,
            code="WOOCOMMERCE_INVALID_RESPONSE")
    return response.body, None


def _category_entity(category):
    return ProductCategory(
        id=str(category.get("id", "")), title=str(category.get("name", "")),
        kind="wc_product_category", description=str(category.get("description", "") or ""),
        parent_id=int(category.get("parent", 0) or 0),
        product_count=int(category.get("count", 0) or 0),
    )


def _bulk_changes(params):
    changes = []
    if params.status is not None:
        changes.append(f"status → {params.status}")
    if params.regular_price_percent is not None:
        changes.append(f"regular price {params.regular_price_percent}%")
    if params.stock_status is not None:
        changes.append(f"stock status → {params.stock_status}")
    if params.category_id_to_add is not None:
        changes.append(f"add category #{params.category_id_to_add}")
    return changes


def _validate_bulk(params):
    status_error = _validate_status(params.status)
    if status_error:
        return None, status_error
    stock_error = _validate_stock(params.stock_status)
    if stock_error:
        return None, stock_error
    percent = None
    if params.regular_price_percent is not None:
        try:
            percent = Decimal(params.regular_price_percent.strip())
        except (InvalidOperation, AttributeError, ValueError):
            return None, _validation_error(
                "regular_price_percent must be a decimal number between -100 and 100.",
                code="WOOCOMMERCE_INVALID_PERCENT")
        if percent < -100 or percent > 100:
            return None, _validation_error(
                "regular_price_percent must be between -100 and 100.",
                code="WOOCOMMERCE_INVALID_PERCENT")
    changes = _bulk_changes(params)
    if not changes:
        return None, _validation_error(
            "Nothing to change — provide status, regular_price_percent, stock_status, or category_id_to_add.",
            code="WOOCOMMERCE_NO_CHANGES")
    unique_ids = list(dict.fromkeys(params.product_ids))
    return (unique_ids, percent, changes), None


async def _bulk_targets(ctx, params):
    validated, err = _validate_bulk(params)
    if err:
        return None, err
    unique_ids, percent, changes = validated
    products = []
    for product_id in unique_ids:
        product, read_err = await _request(
            ctx, params.site_id, f"/products/{product_id}", expected_type=dict)
        if read_err:
            return None, read_err
        products.append(product)
    return (products, percent, changes), None


def _bulk_payload(product, params, percent):
    payload = {"id": int(product["id"])}
    if params.status is not None:
        payload["status"] = params.status
    if params.stock_status is not None:
        payload["stock_status"] = params.stock_status
    if percent is not None:
        current = _decimal_string(product.get("regular_price"), "existing regular_price")[0]
        amount = Decimal(current or "0")
        changed = amount * (Decimal("1") + percent / Decimal("100"))
        payload["regular_price"] = format(
            max(changed, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    if params.category_id_to_add is not None:
        ids = [int(item.get("id")) for item in (product.get("categories") or []) if item.get("id")]
        if params.category_id_to_add not in ids:
            ids.append(params.category_id_to_add)
        payload["categories"] = [{"id": item} for item in ids]
    return payload


@chat.function(
    "create_product",
    description="Create a WooCommerce simple, virtual, or downloadable product. Defaults to draft; pass status='publish' explicitly to publish it.",
    action_type="write", data_model=Product,
    effects=["wc.product_create"], event="wp-site-connector.create_product")
async def create_product(ctx, params: CreateProductParams) -> ActionResult:
    """Create one WooCommerce product with validated price, stock, categories, and images."""
    payload, err = _product_payload(params, creating=True)
    if err:
        return err
    data, err = await _write(ctx, params.site_id, "/products", payload)
    if err:
        return err
    entity = _product_entity(data)
    return ActionResult.success(
        entity, summary=f"Created {entity.title} as {entity.status} (product #{entity.id})",
        refresh_panels=["center"])


@chat.function(
    "update_product",
    description="Update selected fields of one WooCommerce product: name, status, SKU, prices, descriptions, stock, categories, or images. Omitted fields stay unchanged.",
    action_type="write", data_model=Product,
    effects=["wc.product_update"], event="wp-site-connector.update_product")
async def update_product(ctx, params: UpdateProductParams) -> ActionResult:
    """Update one product without replacing fields the caller omitted."""
    payload, err = _product_payload(params)
    if err:
        return err
    if not payload:
        return _validation_error(
            "Nothing to update — provide at least one product field.", code="WOOCOMMERCE_NO_CHANGES")
    data, err = await _write(ctx, params.site_id, f"/products/{params.product_id}", payload)
    if err:
        return err
    entity = _product_entity(data)
    return ActionResult.success(
        entity, summary=f"Updated product #{entity.id}: {', '.join(payload.keys())}",
        refresh_panels=["center"])


@chat.function(
    "archive_product",
    description="Move one WooCommerce product to Trash without permanently deleting it. The product can be restored in WordPress.",
    action_type="destructive", data_model=Product,
    effects=["wc.product_trash"], event="wp-site-connector.archive_product")
async def archive_product(ctx, params: ArchiveProductParams) -> ActionResult:
    """Move a product to WooCommerce trash after the platform confirmation gate."""
    _, err = await _write(
        ctx, params.site_id, f"/products/{params.product_id}", {"status": "trash"})
    if err:
        return err
    data, err = await _request(
        ctx, params.site_id, f"/products/{params.product_id}", expected_type=dict)
    if err:
        return err
    if data.get("status") != "trash":
        return ActionResult.error(
            "WooCommerce accepted the archive request but the product is not in Trash.",
            retryable=True, code="WOOCOMMERCE_ARCHIVE_NOT_VERIFIED")
    entity = _product_entity(data)
    return ActionResult.success(
        entity, summary=f"Moved product #{params.product_id} to Trash",
        refresh_panels=["center"])


@chat.function(
    "list_product_categories",
    description="List WooCommerce product categories with ids, parent ids, and product counts.",
    action_type="read", data_model=sdl.EntityList[ProductCategory],
)
async def list_product_categories(ctx, params: ListProductCategoriesParams) -> ActionResult:
    """List product categories so write operations never need guessed ids."""
    query = {"per_page": params.limit, "page": params.page, "orderby": "name", "order": "asc"}
    if params.search:
        query["search"] = params.search.strip()
    data, err = await _request(ctx, params.site_id, "/products/categories", query)
    if err:
        return err
    items = [_category_entity(item) for item in data]
    return ActionResult.success(
        sdl.EntityList[ProductCategory](items=items),
        summary=f"{len(items)} product category(s)")


@chat.function(
    "create_product_category",
    description="Create a WooCommerce product category, optionally below an existing parent category.",
    action_type="write", data_model=ProductCategory,
    effects=["wc.product_category_create"], event="wp-site-connector.create_product_category")
async def create_product_category(ctx, params: CreateProductCategoryParams) -> ActionResult:
    """Create one WooCommerce product category."""
    payload = {"name": params.name.strip(), "parent": params.parent_id,
               "description": params.description.strip()}
    data, err = await _write(ctx, params.site_id, "/products/categories", payload)
    if err:
        return err
    entity = _category_entity(data)
    return ActionResult.success(
        entity, summary=f"Created product category {entity.title} (#{entity.id})",
        refresh_panels=["center"])


@chat.function(
    "preview_bulk_product_change",
    description="Preview a bulk WooCommerce product change for 1-100 explicit product ids. Reads current products and shows exactly what apply_bulk_product_change would change; makes no writes.",
    action_type="read", data_model=ProductBulkResult)
async def preview_bulk_product_change(ctx, params: BulkProductChangeParams) -> ActionResult:
    """Preview an explicit bulk product change without mutating WooCommerce."""
    target_data, err = await _bulk_targets(ctx, params)
    if err:
        return err
    products, percent, changes = target_data
    details = []
    for product in products:
        payload = _bulk_payload(product, params, percent)
        suffix = f" → {payload['regular_price']}" if "regular_price" in payload else ""
        details.append(f"#{product['id']} {product.get('name', '')}{suffix}")
    entity = ProductBulkResult(
        id=params.site_id, title="Bulk product change preview", kind="wc_product_bulk",
        preview=True, requested=len(params.product_ids), matched=len(products),
        changes=changes + details)
    return ActionResult.success(
        entity, summary=f"Preview: {len(products)} product(s); {', '.join(changes)}")


@chat.function(
    "apply_bulk_product_change",
    description="Apply a previously reviewed bulk change to 1-100 explicit WooCommerce product ids. This is always confirmation-gated; use preview_bulk_product_change first with identical arguments.",
    action_type="destructive", data_model=ProductBulkResult,
    effects=["wc.product_bulk_update"], event="wp-site-connector.apply_bulk_product_change")
async def apply_bulk_product_change(ctx, params: BulkProductChangeParams) -> ActionResult:
    """Apply a confirmation-gated bulk product change with per-product results."""
    target_data, err = await _bulk_targets(ctx, params)
    if err:
        return err
    products, percent, changes = target_data
    updated_ids = []
    failures = []
    for product in products:
        product_id = int(product["id"])
        payload = _bulk_payload(product, params, percent)
        _, write_err = await _write(ctx, params.site_id, f"/products/{product_id}", payload)
        if write_err:
            failures.append(f"#{product_id}: {write_err.message or 'update failed'}")
        else:
            updated_ids.append(product_id)
    entity = ProductBulkResult(
        id=params.site_id, title="Bulk product change result", kind="wc_product_bulk",
        preview=False, requested=len(params.product_ids), matched=len(products),
        updated=len(updated_ids), failed=len(failures), changes=changes,
        updated_ids=updated_ids, failures=failures)
    if not updated_ids:
        return ActionResult.error(
            "No products were updated.", retryable=False, code="WOOCOMMERCE_BULK_ALL_FAILED")
    return ActionResult.success(
        entity, summary=f"Updated {len(updated_ids)} product(s); {len(failures)} failed",
        refresh_panels=["center"])
