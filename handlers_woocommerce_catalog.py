"""Controlled WooCommerce catalogue writes for products and categories.

Single reversible changes are audited writes. Moving a product to trash and
applying a bulk change are destructive tools so Imperal's KAV gate always
shows the byte-identical arguments before execution. Bulk operations accept
explicit ids only; they never infer a whole catalogue from a vague filter.
"""

import csv
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

from imperal_sdk import ActionResult, sdl

from app import chat
from handlers_woocommerce import WC_BASE, _authed, _failure, _product_entity, _request
from models import (
    ApplyBulkProductChangeParams,
    ApplyBulkVariationChangeParams,
    ApplyCsvCatalogImportParams,
    ApplyCsvVariationImportParams,
    ArchiveProductParams,
    BulkProductChangeParams,
    BulkVariationChangeParams,
    CsvCatalogImportParams,
    CsvVariationImportParams,
    CreateProductCategoryParams,
    CreateProductParams,
    ListProductCategoriesParams,
    Product,
    ProductBulkResult,
    ProductCategory,
    ProductVariation,
    VariationBulkResult,
    CreateProductVariationParams,
    ListProductVariationsParams,
    UpdateProductVariationParams,
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


def _bulk_state_token(products):
    state = []
    for product in sorted(products, key=lambda item: int(item["id"])):
        state.append({
            "id": int(product["id"]),
            "status": str(product.get("status", "")),
            "sku": str(product.get("sku", "") or ""),
            "regular_price": str(product.get("regular_price", "") or ""),
            "sale_price": str(product.get("sale_price", "") or ""),
            "manage_stock": bool(product.get("manage_stock", False)),
            "stock_quantity": product.get("stock_quantity"),
            "stock_status": str(product.get("stock_status", "")),
            "categories": sorted(
                int(item["id"]) for item in (product.get("categories") or []) if item.get("id")),
        })
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def _parse_csv_catalog(csv_text):
    try:
        rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    except csv.Error:
        return None, _validation_error("CSV could not be parsed. Use a comma-separated file with a header row.", code="WOOCOMMERCE_INVALID_CSV")
    if not rows or not rows[0].keys():
        return None, _validation_error("CSV must contain a header row and at least one data row.", code="WOOCOMMERCE_INVALID_CSV")
    headers = {str(key or "").strip().lower() for key in rows[0].keys()}
    allowed = {"sku", "regular_price", "sale_price", "stock_quantity", "stock_status"}
    if "sku" not in headers:
        return None, _validation_error("CSV must include a SKU column.", code="WOOCOMMERCE_INVALID_CSV")
    if not headers <= allowed:
        return None, _validation_error(
            "CSV supports only SKU, regular_price, sale_price, stock_quantity, and stock_status columns.",
            code="WOOCOMMERCE_INVALID_CSV")
    if len(rows) > 100:
        return None, _validation_error("CSV may contain at most 100 data rows per run.", code="WOOCOMMERCE_CSV_LIMIT")

    parsed, seen_skus = [], set()
    for row_number, row in enumerate(rows, start=2):
        normalized = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        sku = normalized.get("sku", "")
        key = sku.casefold()
        if not sku:
            return None, _validation_error(f"CSV row {row_number} has an empty SKU.", code="WOOCOMMERCE_INVALID_CSV")
        if key in seen_skus:
            return None, _validation_error(f"CSV contains duplicate SKU: {sku}.", code="WOOCOMMERCE_DUPLICATE_CSV_SKU")
        seen_skus.add(key)
        payload = {}
        for field in ("regular_price", "sale_price"):
            if normalized.get(field, ""):
                value, err = _decimal_string(normalized[field], field)
                if err:
                    return None, _validation_error(f"CSV row {row_number}: {field} must be a non-negative decimal.", code="WOOCOMMERCE_INVALID_CSV")
                payload[field] = value
        if normalized.get("stock_quantity", ""):
            try:
                quantity = int(normalized["stock_quantity"])
            except ValueError:
                return None, _validation_error(f"CSV row {row_number}: stock_quantity must be a non-negative integer.", code="WOOCOMMERCE_INVALID_CSV")
            if quantity < 0:
                return None, _validation_error(f"CSV row {row_number}: stock_quantity must be a non-negative integer.", code="WOOCOMMERCE_INVALID_CSV")
            payload["stock_quantity"] = quantity
            payload["manage_stock"] = True
        if normalized.get("stock_status", ""):
            if normalized["stock_status"] not in _STOCK_STATUSES:
                return None, _validation_error(f"CSV row {row_number}: invalid stock_status.", code="WOOCOMMERCE_INVALID_CSV")
            payload["stock_status"] = normalized["stock_status"]
        if not payload:
            return None, _validation_error(f"CSV row {row_number} has no fields to update.", code="WOOCOMMERCE_INVALID_CSV")
        parsed.append({"sku": sku, "payload": payload})
    return parsed, None


def _parse_csv_variations(csv_text):
    try:
        rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    except csv.Error:
        return None, _validation_error("CSV could not be parsed. Use a comma-separated file with a header row.", code="WOOCOMMERCE_INVALID_CSV")
    if not rows or not rows[0].keys():
        return None, _validation_error("CSV must contain a header row and at least one data row.", code="WOOCOMMERCE_INVALID_CSV")
    headers = {str(key or "").strip().lower() for key in rows[0].keys()}
    allowed = {"parent_sku", "variation_sku", "regular_price", "sale_price", "stock_quantity", "stock_status"}
    if not {"parent_sku", "variation_sku"} <= headers:
        return None, _validation_error("CSV must include parent_sku and variation_sku columns.", code="WOOCOMMERCE_INVALID_CSV")
    if not headers <= allowed:
        return None, _validation_error(
            "CSV supports only parent_sku, variation_sku, regular_price, sale_price, stock_quantity, and stock_status columns.",
            code="WOOCOMMERCE_INVALID_CSV")
    if len(rows) > 100:
        return None, _validation_error("CSV may contain at most 100 data rows per run.", code="WOOCOMMERCE_CSV_LIMIT")

    parsed, seen_pairs = [], set()
    for row_number, row in enumerate(rows, start=2):
        normalized = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        parent_sku, variation_sku = normalized.get("parent_sku", ""), normalized.get("variation_sku", "")
        pair = (parent_sku.casefold(), variation_sku.casefold())
        if not all(pair):
            return None, _validation_error(f"CSV row {row_number} needs parent_sku and variation_sku.", code="WOOCOMMERCE_INVALID_CSV")
        if pair in seen_pairs:
            return None, _validation_error(
                f"CSV contains duplicate parent_sku + variation_sku: {parent_sku} / {variation_sku}.",
                code="WOOCOMMERCE_DUPLICATE_CSV_VARIATION")
        seen_pairs.add(pair)
        payload = {}
        for field in ("regular_price", "sale_price"):
            if normalized.get(field, ""):
                value, err = _decimal_string(normalized[field], field)
                if err:
                    return None, _validation_error(f"CSV row {row_number}: {field} must be a non-negative decimal.", code="WOOCOMMERCE_INVALID_CSV")
                payload[field] = value
        if normalized.get("stock_quantity", ""):
            try:
                quantity = int(normalized["stock_quantity"])
            except ValueError:
                return None, _validation_error(f"CSV row {row_number}: stock_quantity must be a non-negative integer.", code="WOOCOMMERCE_INVALID_CSV")
            if quantity < 0:
                return None, _validation_error(f"CSV row {row_number}: stock_quantity must be a non-negative integer.", code="WOOCOMMERCE_INVALID_CSV")
            payload.update(stock_quantity=quantity, manage_stock=True)
        if normalized.get("stock_status", ""):
            if normalized["stock_status"] not in _STOCK_STATUSES:
                return None, _validation_error(f"CSV row {row_number}: invalid stock_status.", code="WOOCOMMERCE_INVALID_CSV")
            payload["stock_status"] = normalized["stock_status"]
        if not payload:
            return None, _validation_error(f"CSV row {row_number} has no fields to update.", code="WOOCOMMERCE_INVALID_CSV")
        parsed.append({"parent_sku": parent_sku, "variation_sku": variation_sku, "payload": payload})
    return parsed, None


async def _csv_catalog_targets(ctx, params):
    rows, err = _parse_csv_catalog(params.csv_text)
    if err:
        return None, err
    matched, missing = [], []
    for row in rows:
        data, read_err = await _request(
            ctx, params.site_id, "/products", {"sku": row["sku"], "per_page": 2})
        if read_err:
            return None, read_err
        exact = [item for item in data if str(item.get("sku", "")).casefold() == row["sku"].casefold()]
        if len(exact) != 1 or exact[0].get("type") != "simple":
            missing.append(row["sku"])
            continue
        matched.append({"product": exact[0], "payload": row["payload"]})
    return (rows, matched, missing), None


def _csv_state_token(matched):
    return _bulk_state_token([item["product"] for item in matched])


async def _csv_variation_targets(ctx, params):
    rows, err = _parse_csv_variations(params.csv_text)
    if err:
        return None, err
    matched, missing = [], []
    for row in rows:
        parents, read_err = await _request(
            ctx, params.site_id, "/products", {"sku": row["parent_sku"], "per_page": 2})
        if read_err:
            return None, read_err
        parents = [item for item in parents if (
            str(item.get("sku", "")).casefold() == row["parent_sku"].casefold()
            and item.get("type") == "variable")]
        if len(parents) != 1:
            missing.append(f"{row['parent_sku']} / {row['variation_sku']}")
            continue
        parent = parents[0]
        variations, read_err = await _request(
            ctx, params.site_id, f"/products/{parent['id']}/variations",
            {"sku": row["variation_sku"], "per_page": 2})
        if read_err:
            return None, read_err
        exact = [item for item in variations if str(item.get("sku", "")).casefold() == row["variation_sku"].casefold()]
        if len(exact) != 1:
            missing.append(f"{row['parent_sku']} / {row['variation_sku']}")
            continue
        matched.append({"parent": parent, "variation": exact[0], "payload": row["payload"]})
    return (rows, matched, missing), None


def _csv_variation_state_token(matched):
    return _bulk_variation_state_token([item["variation"] for item in matched])


def _variation_state_token(variation):
    state = {
        "id": int(variation.get("id", 0)),
        "status": str(variation.get("status", "")),
        "sku": str(variation.get("sku", "") or ""),
        "regular_price": str(variation.get("regular_price", "") or ""),
        "sale_price": str(variation.get("sale_price", "") or ""),
        "manage_stock": bool(variation.get("manage_stock", False)),
        "stock_quantity": variation.get("stock_quantity"),
        "stock_status": str(variation.get("stock_status", "")),
        "attributes": sorted(
            (str(item.get("name", "")), str(item.get("option", "")))
            for item in (variation.get("attributes") or [])),
    }
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bulk_variation_state_token(variations):
    return hashlib.sha256(json.dumps(
        sorted(_variation_state_token(item) for item in variations),
        separators=(",", ":")).encode()).hexdigest()


def _validate_bulk_variations(params):
    ids = list(dict.fromkeys(params.variation_ids))
    if len(ids) != len(params.variation_ids):
        return None, _validation_error(
            "Each variation id may be provided only once.",
            code="WOOCOMMERCE_DUPLICATE_VARIATION_ID")
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
    if params.stock_status is not None and params.stock_status not in _STOCK_STATUSES:
        return None, _validation_error("stock_status must be instock, outofstock, or onbackorder.")
    if params.status is not None and params.status not in _PRODUCT_STATUSES:
        return None, _validation_error("status must be draft, publish, pending, or private.")
    changes = []
    if percent is not None:
        changes.append(f"regular price {percent:+g}%")
    if params.stock_status is not None:
        changes.append(f"stock status → {params.stock_status}")
    if params.status is not None:
        changes.append(f"status → {params.status}")
    if not changes:
        return None, _validation_error(
            "Nothing to change — provide regular_price_percent, stock_status, or status.",
            code="WOOCOMMERCE_NO_CHANGES")
    return (ids, percent, changes), None


async def _bulk_variation_targets(ctx, params):
    validated, err = _validate_bulk_variations(params)
    if err:
        return None, err
    ids, percent, changes = validated
    variations = []
    for variation_id in ids:
        item, read_err = await _request(
            ctx, params.site_id,
            f"/products/{params.product_id}/variations/{variation_id}", expected_type=dict)
        if read_err:
            return None, read_err
        variations.append(item)
    return (variations, percent, changes), None


def _bulk_variation_payload(variation, params, percent):
    payload = {"id": int(variation["id"])}
    if percent is not None:
        current, err = _decimal_string(variation.get("regular_price"), "existing regular_price")
        if err:
            return None, err
        changed = Decimal(current or "0") * (Decimal("1") + percent / Decimal("100"))
        payload["regular_price"] = format(
            max(changed, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    if params.stock_status is not None:
        payload["stock_status"] = params.stock_status
    if params.status is not None:
        payload["status"] = params.status
    return payload, None


def _variation_entity(product_id, variation):
    attributes = [f"{item.get('name', '')}: {item.get('option', '')}".strip(": ")
                  for item in (variation.get("attributes") or [])]
    variation_id = int(variation.get("id", 0))
    title = " / ".join(attributes) or f"Variation #{variation_id}"
    return ProductVariation(
        id=str(variation_id), title=title, kind="wc_product_variation",
        status=str(variation.get("status", "")), product_id=product_id,
        sku=str(variation.get("sku", "") or ""),
        regular_price=str(variation.get("regular_price", "") or ""),
        sale_price=str(variation.get("sale_price", "") or ""),
        stock_status=str(variation.get("stock_status", "")),
        stock_quantity=variation.get("stock_quantity"),
        manage_stock=bool(variation.get("manage_stock", False)),
        attributes=attributes, state_token=_variation_state_token(variation))


def _variation_payload(params, *, creating=False):
    payload = {}
    for field in ("sku", "regular_price", "sale_price"):
        value = getattr(params, field, None)
        if value is not None:
            normalized, err = _decimal_string(value, field, allow_empty=True) if field != "sku" else (value.strip(), None)
            if err:
                return None, err
            payload[field] = normalized
    for field in ("manage_stock", "stock_quantity", "stock_status", "status"):
        value = getattr(params, field, None)
        if value is not None:
            payload[field] = value
    if payload.get("stock_status") is not None and payload["stock_status"] not in _STOCK_STATUSES:
        return None, _validation_error("stock_status must be instock, outofstock, or onbackorder.")
    if payload.get("status") is not None and payload["status"] not in _PRODUCT_STATUSES:
        return None, _validation_error("status must be draft, publish, pending, or private.")
    if params.stock_quantity is not None:
        payload["manage_stock"] = True
    if creating:
        attrs = []
        seen = set()
        for item in params.attributes:
            key = item.name.strip().casefold()
            if key in seen:
                return None, _validation_error("Each variation attribute may be provided only once.", code="WOOCOMMERCE_DUPLICATE_VARIATION_ATTRIBUTE")
            seen.add(key)
            attrs.append({"name": item.name.strip(), "option": item.option.strip()})
        payload["attributes"] = attrs
    return payload, None


@chat.function(
    "list_product_variations",
    description="List variants of one WooCommerce variable product, including attributes, SKU, prices, stock, and a state token for guarded updates.",
    action_type="read", data_model=sdl.EntityList[ProductVariation])
async def list_product_variations(ctx, params: ListProductVariationsParams) -> ActionResult:
    """Read paginated product variations; each item includes its update state token."""
    data, err = await _request(
        ctx, params.site_id, f"/products/{params.product_id}/variations",
        {"per_page": params.limit, "page": params.page, "orderby": "id", "order": "asc"})
    if err:
        return err
    items = [_variation_entity(params.product_id, item) for item in data]
    return ActionResult.success(
        sdl.EntityList[ProductVariation](items=items), summary=f"{len(items)} variation(s)")


@chat.function(
    "create_product_variation",
    description="Create a variation for an existing variable product using its existing attributes. Defaults to draft for safe review.",
    action_type="write", data_model=ProductVariation,
    effects=["wc.product_variation_create"], event="wp-site-connector.create_product_variation")
async def create_product_variation(ctx, params: CreateProductVariationParams) -> ActionResult:
    """Create a draft-first variation from explicit parent attribute options."""
    payload, err = _variation_payload(params, creating=True)
    if err:
        return err
    parent, err = await _request(ctx, params.site_id, f"/products/{params.product_id}", expected_type=dict)
    if err:
        return err
    if parent.get("type") != "variable":
        return _validation_error(
            "Variations can only be created under a variable product.",
            code="WOOCOMMERCE_PARENT_NOT_VARIABLE")
    allowed = {
        str(item.get("name", "")).strip().casefold(): {
            str(option).strip().casefold() for option in (item.get("options") or [])
        }
        for item in (parent.get("attributes") or []) if item.get("variation")
    }
    for item in payload["attributes"]:
        name, option = item["name"].casefold(), item["option"].casefold()
        if name not in allowed or option not in allowed[name]:
            return _validation_error(
                f"{item['name']}: {item['option']} is not an existing variation attribute of the parent product.",
                code="WOOCOMMERCE_INVALID_VARIATION_ATTRIBUTE")
    data, err = await _write(ctx, params.site_id, f"/products/{params.product_id}/variations", payload)
    if err:
        return err
    entity = _variation_entity(params.product_id, data)
    return ActionResult.success(entity, summary=f"Created draft variation #{entity.id}", refresh_panels=["center"])


@chat.function(
    "update_product_variation",
    description="Update selected price, SKU, stock, or status fields of one product variation only after its state token is rechecked.",
    action_type="write", data_model=ProductVariation,
    effects=["wc.product_variation_update"], event="wp-site-connector.update_product_variation")
async def update_product_variation(ctx, params: UpdateProductVariationParams) -> ActionResult:
    """Update one variation only if it still matches the reviewed variation state."""
    payload, err = _variation_payload(params)
    if err:
        return err
    if not payload:
        return _validation_error("Nothing to update — provide at least one variation field.", code="WOOCOMMERCE_NO_CHANGES")
    current, err = await _request(
        ctx, params.site_id, f"/products/{params.product_id}/variations/{params.variation_id}", expected_type=dict)
    if err:
        return err
    if _variation_state_token(current) != params.expected_state_token:
        return _validation_error(
            "This variation changed since it was listed. Run list_product_variations again.",
            code="WOOCOMMERCE_VARIATION_STATE_CHANGED")
    data, err = await _write(
        ctx, params.site_id, f"/products/{params.product_id}/variations/{params.variation_id}", payload)
    if err:
        return err
    entity = _variation_entity(params.product_id, data)
    return ActionResult.success(entity, summary=f"Updated variation #{entity.id}: {', '.join(payload.keys())}", refresh_panels=["center"])


@chat.function(
    "preview_bulk_variation_change",
    description="Preview a bulk change for 1-100 explicit WooCommerce variation ids. Reads current variations and returns a state token; makes no writes.",
    action_type="read", data_model=VariationBulkResult)
async def preview_bulk_variation_change(ctx, params: BulkVariationChangeParams) -> ActionResult:
    """Preview an explicit bulk variation update without mutating WooCommerce."""
    target_data, err = await _bulk_variation_targets(ctx, params)
    if err:
        return err
    variations, percent, changes = target_data
    details = []
    for variation in variations:
        payload, payload_err = _bulk_variation_payload(variation, params, percent)
        if payload_err:
            return payload_err
        details.append(f"#{variation['id']} {variation.get('sku') or 'no SKU'}" + (
            f" → {payload['regular_price']}" if "regular_price" in payload else ""))
    entity = VariationBulkResult(
        id=str(params.product_id), title="Bulk variation change preview", kind="wc_variation_bulk",
        product_id=params.product_id, preview=True,
        state_token=_bulk_variation_state_token(variations), requested=len(params.variation_ids),
        matched=len(variations), changes=changes + details)
    return ActionResult.success(
        entity, summary=f"Preview: {len(variations)} variation(s); {', '.join(changes)}")


@chat.function(
    "apply_bulk_variation_change",
    description="Apply a reviewed bulk change to 1-100 explicit WooCommerce variation ids. Requires the exact preview state token and stops before all writes if any variation changed.",
    action_type="destructive", data_model=VariationBulkResult,
    effects=["wc.product_variation_bulk_update"], event="wp-site-connector.apply_bulk_variation_change")
async def apply_bulk_variation_change(ctx, params: ApplyBulkVariationChangeParams) -> ActionResult:
    """Apply an explicit bulk variation update after fresh all-target state verification."""
    target_data, err = await _bulk_variation_targets(ctx, params)
    if err:
        return err
    variations, percent, changes = target_data
    if _bulk_variation_state_token(variations) != params.expected_state_token:
        return _validation_error(
            "One or more variations changed since preview. Run preview_bulk_variation_change again.",
            code="WOOCOMMERCE_VARIATION_BULK_STATE_CHANGED")

    updated_ids, failures = [], []
    for variation in variations:
        variation_id = int(variation["id"])
        payload, payload_err = _bulk_variation_payload(variation, params, percent)
        if payload_err:
            failures.append(f"#{variation_id}: {payload_err.error or 'invalid update'}")
            continue
        payload.pop("id", None)
        _, write_err = await _write(
            ctx, params.site_id,
            f"/products/{params.product_id}/variations/{variation_id}", payload)
        if write_err:
            failures.append(f"#{variation_id}: {write_err.error or 'update failed'}")
        else:
            updated_ids.append(variation_id)

    entity = VariationBulkResult(
        id=str(params.product_id), title="Bulk variation change result", kind="wc_variation_bulk",
        product_id=params.product_id, preview=False, requested=len(params.variation_ids),
        matched=len(variations), updated=len(updated_ids), failed=len(failures),
        changes=changes, updated_ids=updated_ids, failures=failures)
    if not updated_ids:
        return ActionResult.error(
            "WooCommerce did not update any requested variations.", retryable=any("try again" in item.lower() for item in failures),
            code="WOOCOMMERCE_VARIATION_BULK_ALL_FAILED")
    return ActionResult.success(
        entity, summary=f"Updated {len(updated_ids)} variation(s); {len(failures)} failed",
        refresh_panels=["center"])


@chat.function(
    "preview_csv_catalog_import",
    description="Preview a CSV import for simple WooCommerce products matched strictly by SKU. CSV columns: SKU plus regular_price, sale_price, stock_quantity, or stock_status. Returns unmatched SKUs and a state token; makes no writes.",
    action_type="read", data_model=ProductBulkResult)
async def preview_csv_catalog_import(ctx, params: CsvCatalogImportParams) -> ActionResult:
    """Parse a small CSV and show exact-SKU product changes without writing."""
    target_data, err = await _csv_catalog_targets(ctx, params)
    if err:
        return err
    rows, matched, missing = target_data
    details = [
        f"#{item['product']['id']} {item['product'].get('sku')}: "
        + ", ".join(f"{key} → {value}" for key, value in item["payload"].items())
        for item in matched
    ]
    if missing:
        details.append("Unmatched SKU(s): " + ", ".join(missing))
    entity = ProductBulkResult(
        id=params.site_id, title="CSV catalog import preview", kind="wc_catalog_csv",
        preview=True, state_token=_csv_state_token(matched), requested=len(rows),
        matched=len(matched), failed=len(missing), changes=details, failures=missing)
    return ActionResult.success(
        entity,
        summary=f"Preview: {len(matched)} matched; {len(missing)} SKU(s) not found")


@chat.function(
    "apply_csv_catalog_import",
    description="Apply a previously previewed CSV import to strictly SKU-matched WooCommerce products. Requires the exact state token and stops before all writes if any matched product changed.",
    action_type="destructive", data_model=ProductBulkResult,
    effects=["wc.product_csv_import"], event="wp-site-connector.apply_csv_catalog_import")
async def apply_csv_catalog_import(ctx, params: ApplyCsvCatalogImportParams) -> ActionResult:
    """Apply a reviewed simple-product CSV import after a fresh all-target check."""
    target_data, err = await _csv_catalog_targets(ctx, params)
    if err:
        return err
    rows, matched, missing = target_data
    if not matched:
        return _validation_error(
            "No CSV SKU matched a simple WooCommerce product; nothing was changed.",
            code="WOOCOMMERCE_CSV_NO_MATCHES")
    if _csv_state_token(matched) != params.expected_state_token:
        return _validation_error(
            "One or more matched products changed since preview. Run preview_csv_catalog_import again.",
            code="WOOCOMMERCE_CSV_STATE_CHANGED")

    updated_ids, failures = [], list(missing)
    for item in matched:
        product, payload = item["product"], item["payload"]
        product_id = int(product["id"])
        _, write_err = await _write(ctx, params.site_id, f"/products/{product_id}", payload)
        if write_err:
            failures.append(f"#{product_id}: {write_err.error or 'update failed'}")
        else:
            updated_ids.append(product_id)
    entity = ProductBulkResult(
        id=params.site_id, title="CSV catalog import result", kind="wc_catalog_csv",
        preview=False, requested=len(rows), matched=len(matched), updated=len(updated_ids),
        failed=len(failures), updated_ids=updated_ids, failures=failures)
    if not updated_ids:
        return ActionResult.error(
            "WooCommerce did not update any CSV-matched products.", retryable=False,
            code="WOOCOMMERCE_CSV_ALL_FAILED")
    return ActionResult.success(
        entity, summary=f"Updated {len(updated_ids)} product(s); {len(failures)} skipped or failed",
        refresh_panels=["center"])


@chat.function(
    "preview_csv_variation_import",
    description="Preview a CSV import for WooCommerce variations matched strictly by parent_sku plus variation_sku. CSV columns: parent_sku, variation_sku and optional regular_price, sale_price, stock_quantity, or stock_status. Returns unmatched pairs and a state token; makes no writes.",
    action_type="read", data_model=VariationBulkResult)
async def preview_csv_variation_import(ctx, params: CsvVariationImportParams) -> ActionResult:
    """Preview exact parent-SKU and variation-SKU updates without WooCommerce writes."""
    target_data, err = await _csv_variation_targets(ctx, params)
    if err:
        return err
    rows, matched, missing = target_data
    details = [
        f"#{item['parent']['id']}/#{item['variation']['id']} "
        f"{item['parent'].get('sku')} / {item['variation'].get('sku')}: "
        + ", ".join(f"{key} → {value}" for key, value in item["payload"].items())
        for item in matched
    ]
    if missing:
        details.append("Unmatched pair(s): " + ", ".join(missing))
    entity = VariationBulkResult(
        id=params.site_id, title="CSV variation import preview", kind="wc_variation_csv",
        preview=True, state_token=_csv_variation_state_token(matched), requested=len(rows),
        matched=len(matched), failed=len(missing), changes=details, failures=missing)
    return ActionResult.success(
        entity, summary=f"Preview: {len(matched)} matched; {len(missing)} pair(s) not found")


@chat.function(
    "apply_csv_variation_import",
    description="Apply a previously previewed CSV import to strictly matched WooCommerce variations. Requires the exact state token and stops before all writes if any matched variation changed.",
    action_type="destructive", data_model=VariationBulkResult,
    effects=["wc.variation_csv_import"], event="wp-site-connector.apply_csv_variation_import")
async def apply_csv_variation_import(ctx, params: ApplyCsvVariationImportParams) -> ActionResult:
    """Apply reviewed variation CSV rows after a fresh all-target state check."""
    target_data, err = await _csv_variation_targets(ctx, params)
    if err:
        return err
    rows, matched, missing = target_data
    if not matched:
        return _validation_error(
            "No CSV parent_sku + variation_sku pair matched; nothing was changed.",
            code="WOOCOMMERCE_CSV_VARIATION_NO_MATCHES")
    if _csv_variation_state_token(matched) != params.expected_state_token:
        return _validation_error(
            "One or more matched variations changed since preview. Run preview_csv_variation_import again.",
            code="WOOCOMMERCE_CSV_VARIATION_STATE_CHANGED")

    updated_ids, failures = [], list(missing)
    for item in matched:
        parent_id, variation = int(item["parent"]["id"]), item["variation"]
        variation_id = int(variation["id"])
        _, write_err = await _write(
            ctx, params.site_id, f"/products/{parent_id}/variations/{variation_id}", item["payload"])
        if write_err:
            failures.append(f"#{parent_id}/#{variation_id}: {write_err.error or 'update failed'}")
        else:
            updated_ids.append(variation_id)
    entity = VariationBulkResult(
        id=params.site_id, title="CSV variation import result", kind="wc_variation_csv",
        preview=False, requested=len(rows), matched=len(matched), updated=len(updated_ids),
        failed=len(failures), updated_ids=updated_ids, failures=failures)
    if not updated_ids:
        return ActionResult.error(
            "WooCommerce did not update any CSV-matched variations.", retryable=False,
            code="WOOCOMMERCE_CSV_VARIATION_ALL_FAILED")
    return ActionResult.success(
        entity, summary=f"Updated {len(updated_ids)} variation(s); {len(failures)} skipped or failed",
        refresh_panels=["center"])


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
        preview=True, state_token=_bulk_state_token(products),
        requested=len(params.product_ids), matched=len(products),
        changes=changes + details)
    return ActionResult.success(
        entity, summary=f"Preview: {len(products)} product(s); {', '.join(changes)}")


@chat.function(
    "apply_bulk_product_change",
    description="Apply a previously reviewed bulk change to 1-100 explicit WooCommerce product ids. Requires the exact state token returned by preview and stops before all writes if any product changed.",
    action_type="destructive", data_model=ProductBulkResult,
    effects=["wc.product_bulk_update"], event="wp-site-connector.apply_bulk_product_change")
async def apply_bulk_product_change(ctx, params: ApplyBulkProductChangeParams) -> ActionResult:
    """Apply a confirmation-gated bulk change only against the reviewed product state."""
    target_data, err = await _bulk_targets(ctx, params)
    if err:
        return err
    products, percent, changes = target_data
    state_token = _bulk_state_token(products)
    if state_token != params.expected_state_token:
        return ActionResult.error(
            "One or more products changed since preview. Run preview_bulk_product_change again.",
            retryable=False, code="WOOCOMMERCE_BULK_STATE_CHANGED")
    updated_ids = []
    failures = []
    for product in products:
        product_id = int(product["id"])
        payload = _bulk_payload(product, params, percent)
        _, write_err = await _write(ctx, params.site_id, f"/products/{product_id}", payload)
        if write_err:
            failures.append(f"#{product_id}: {write_err.error or 'update failed'}")
        else:
            updated_ids.append(product_id)
    entity = ProductBulkResult(
        id=params.site_id, title="Bulk product change result", kind="wc_product_bulk",
        preview=False, state_token=state_token,
        requested=len(params.product_ids), matched=len(products),
        updated=len(updated_ids), failed=len(failures), changes=changes,
        updated_ids=updated_ids, failures=failures)
    if not updated_ids:
        return ActionResult.error(
            "No products were updated.", retryable=False, code="WOOCOMMERCE_BULK_ALL_FAILED")
    return ActionResult.success(
        entity, summary=f"Updated {len(updated_ids)} product(s); {len(failures)} failed",
        refresh_panels=["center"])
