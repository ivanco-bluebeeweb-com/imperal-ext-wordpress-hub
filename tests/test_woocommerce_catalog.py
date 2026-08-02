"""Contract tests for controlled WooCommerce catalogue writes."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_catalog as hc
import storage
from models import (
    ArchiveProductParams,
    BulkProductChangeParams,
    CreateProductCategoryParams,
    CreateProductParams,
    ListProductCategoriesParams,
    UpdateProductParams,
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


def _product(pid=12, **over):
    data = {
        "id": pid, "name": f"Mug {pid}", "status": "draft", "sku": f"SKU-{pid}",
        "price": "10.00", "regular_price": "10.00", "sale_price": "",
        "stock_status": "instock", "stock_quantity": 4, "manage_stock": True,
        "catalog_visibility": "visible", "categories": [{"id": 3, "name": "Mugs"}],
        "images": [], "attributes": [], "variations": [],
    }
    data.update(over)
    return data


def _spy(ctx, method):
    calls = []
    real = getattr(ctx.http, method)

    async def wrapper(url, **kwargs):
        calls.append((url, kwargs))
        return await real(url, **kwargs)

    setattr(ctx.http, method, wrapper)
    return calls


async def test_create_product_defaults_draft_and_normalises_payload():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/products", _product(), 201)
    seen = _spy(ctx, "post")
    result = await hc.create_product(ctx, CreateProductParams(
        site_id="shop-test", name=" Mug ", regular_price="10", stock_quantity=4,
        category_ids=[3, 3]))
    assert result.status == "success" and result.data.id == "12"
    payload = seen[-1][1]["json"]
    assert payload["name"] == "Mug" and payload["status"] == "draft"
    assert payload["regular_price"] == "10.00"
    assert payload["manage_stock"] is True and payload["stock_quantity"] == 4
    assert payload["categories"] == [{"id": 3}]


async def test_create_downloadable_sets_woocommerce_flags():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/products", _product(), 201)
    seen = _spy(ctx, "post")
    await hc.create_product(ctx, CreateProductParams(
        site_id="shop-test", name="Guide", product_type="downloadable"))
    assert seen[-1][1]["json"]["type"] == "simple"
    assert seen[-1][1]["json"]["virtual"] is True
    assert seen[-1][1]["json"]["downloadable"] is True


async def test_create_rejects_negative_price_before_http():
    ctx = await _ctx()
    result = await hc.create_product(ctx, CreateProductParams(
        site_id="shop-test", name="Bad", regular_price="-1"))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_INVALID_PRODUCT"


async def test_create_rejects_non_https_image():
    ctx = await _ctx()
    result = await hc.create_product(ctx, CreateProductParams(
        site_id="shop-test", name="Bad", image_urls=["http://example.com/a.jpg"]))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_INVALID_IMAGE_URL"


async def test_update_sends_only_explicit_fields():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/products/12", _product(regular_price="12.50"), 200)
    seen = _spy(ctx, "post")
    result = await hc.update_product(ctx, UpdateProductParams(
        site_id="shop-test", product_id=12, regular_price="12.5"))
    assert result.status == "success"
    assert seen[-1][1]["json"] == {"regular_price": "12.50"}


async def test_update_refuses_empty_change():
    ctx = await _ctx()
    result = await hc.update_product(ctx, UpdateProductParams(
        site_id="shop-test", product_id=12))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_NO_CHANGES"


async def test_list_categories_exposes_ids_for_safe_writes():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/categories", [{
        "id": 8, "name": "Drinkware", "description": "Cups", "parent": 0, "count": 3,
    }], 200)
    result = await hc.list_product_categories(ctx, ListProductCategoriesParams(
        site_id="shop-test", search="Drink"))
    assert result.status == "success" and result.data.items[0].id == "8"
    assert result.data.items[0].product_count == 3


async def test_create_category_maps_result():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/products/categories", {
        "id": 8, "name": "Coffee", "description": "Beans", "parent": 0, "count": 0,
    }, 201)
    result = await hc.create_product_category(ctx, CreateProductCategoryParams(
        site_id="shop-test", name="Coffee", description="Beans"))
    assert result.status == "success" and result.data.id == "8"


async def test_bulk_preview_reads_explicit_ids_and_does_not_write():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/12", _product(12), 200)
    ctx.http.mock_get(f"{BASE}/products/13", _product(13, regular_price="20.00"), 200)
    result = await hc.preview_bulk_product_change(ctx, BulkProductChangeParams(
        site_id="shop-test", product_ids=[12, 13], regular_price_percent="10"))
    assert result.status == "success" and result.data.preview is True
    assert result.data.matched == 2
    assert any("11.00" in item for item in result.data.changes)
    assert any("22.00" in item for item in result.data.changes)


async def test_bulk_refuses_no_change():
    ctx = await _ctx()
    result = await hc.preview_bulk_product_change(ctx, BulkProductChangeParams(
        site_id="shop-test", product_ids=[12]))
    assert result.status == "error" and result.error_code == "WOOCOMMERCE_NO_CHANGES"


async def test_bulk_apply_preserves_existing_categories_and_reports_success():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/12", _product(12), 200)
    ctx.http.mock_post(f"{BASE}/products/12", _product(12), 200)
    seen = _spy(ctx, "post")
    result = await hc.apply_bulk_product_change(ctx, BulkProductChangeParams(
        site_id="shop-test", product_ids=[12], status="publish", category_id_to_add=7))
    assert result.status == "success" and result.data.updated_ids == [12]
    assert seen[-1][1]["json"] == {
        "id": 12, "status": "publish", "categories": [{"id": 3}, {"id": 7}],
    }


async def test_archive_sets_trash_status_and_verifies_read_back():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/products/12", _product(12, status="trash"), 200)
    ctx.http.mock_get(f"{BASE}/products/12", _product(12, status="trash"), 200)
    seen = _spy(ctx, "post")
    result = await hc.archive_product(ctx, ArchiveProductParams(
        site_id="shop-test", product_id=12))
    assert result.status == "success" and result.data.status == "trash"
    assert seen[-1][1]["json"] == {"status": "trash"}


async def test_archive_refuses_false_success_when_read_back_is_not_trash():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/products/12", _product(12, status="private"), 200)
    ctx.http.mock_get(f"{BASE}/products/12", _product(12, status="private"), 200)
    result = await hc.archive_product(ctx, ArchiveProductParams(
        site_id="shop-test", product_id=12))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_ARCHIVE_NOT_VERIFIED"
