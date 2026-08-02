"""Contract tests for guarded WooCommerce CSV catalogue imports."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_catalog as hc
import storage
from models import ApplyCsvCatalogImportParams, CsvCatalogImportParams

BASE = "https://shop.test/wp-json/wc/v3"
CSV = "SKU,regular_price,stock_quantity,stock_status\nSKU-12,12.5,3,instock\nSKU-13,,0,outofstock\nMISSING,9,,\n"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _product(pid, **over):
    data = {
        "id": pid, "name": f"Mug {pid}", "type": "simple", "status": "draft", "sku": f"SKU-{pid}",
        "regular_price": "10.00", "stock_status": "instock", "stock_quantity": 4,
        "manage_stock": True, "categories": [],
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


async def _mock_searches(ctx, first=None, second=None):
    first = first or _product(12)
    second = second or _product(13)
    # MockContext resolves the same endpoint URL by substring, so return a small
    # catalogue and let the production code's exact-SKU filter do its job.
    ctx.http.mock_get(f"{BASE}/products", [first, second], 200)


async def test_csv_preview_matches_exact_skus_reports_missing_and_never_writes():
    ctx = await _ctx()
    await _mock_searches(ctx)
    seen = _spy(ctx, "post")
    result = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV))
    assert result.status == "success" and result.data.preview is True
    assert result.data.requested == 3 and result.data.matched == 2
    assert result.data.failures == ["MISSING"] and len(result.data.state_token) == 64
    assert any("regular_price → 12.50" in item for item in result.data.changes)
    assert seen == []


async def test_csv_preview_rejects_duplicate_sku_before_http():
    ctx = await _ctx()
    result = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text="SKU,stock_status\nA,instock\na,outofstock\n"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_DUPLICATE_CSV_SKU"


async def test_csv_preview_skips_non_simple_product_sku():
    ctx = await _ctx()
    await _mock_searches(ctx, _product(12, type="variable"), _product(13))
    result = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text="SKU,stock_status\nSKU-12,outofstock\n"))
    assert result.status == "success"
    assert result.data.matched == 0 and result.data.failures == ["SKU-12"]


async def test_csv_apply_rechecks_token_before_any_write():
    ctx = await _ctx()
    first, second = _product(12), _product(13)
    changed_second = _product(13, stock_quantity=5)
    await _mock_searches(ctx, first, changed_second)
    seen = _spy(ctx, "post")
    result = await hc.apply_csv_catalog_import(ctx, ApplyCsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV,
        expected_state_token=hc._csv_state_token([
            {"product": first}, {"product": second},
        ])))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_CSV_STATE_CHANGED"
    assert seen == []


async def test_csv_apply_updates_matched_and_reports_missing_or_failed():
    ctx = await _ctx()
    first, second = _product(12), _product(13)
    await _mock_searches(ctx, first, second)
    ctx.http.mock_post(f"{BASE}/products/12", first, 200)
    ctx.http.mock_post(f"{BASE}/products/13", {"code": "woocommerce_rest_cannot_edit"}, 403)
    seen = _spy(ctx, "post")
    result = await hc.apply_csv_catalog_import(ctx, ApplyCsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV,
        expected_state_token=hc._csv_state_token([
            {"product": first}, {"product": second},
        ])))
    assert result.status == "success"
    assert result.data.updated_ids == [12]
    assert result.data.failed == 2 and "MISSING" in result.data.failures
    assert seen[0][1]["json"] == {
        "regular_price": "12.50", "stock_quantity": 3, "manage_stock": True,
        "stock_status": "instock",
    }
