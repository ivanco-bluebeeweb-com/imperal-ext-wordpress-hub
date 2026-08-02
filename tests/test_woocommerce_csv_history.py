"""Contract tests for CSV import audit history and safe failed-row retries."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_catalog as hc
import storage
from models import (
    ApplyCsvCatalogImportParams,
    CsvCatalogImportParams,
    GetCsvImportParams,
    ListCsvImportsParams,
    RetryCsvImportFailuresParams,
)

BASE = "https://shop.test/wp-json/wc/v3"
CSV = "SKU,regular_price,stock_status\nSKU-12,12.5,instock\nMISSING,9,outofstock\n"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _product():
    return {
        "id": 12, "name": "Mug", "type": "simple", "status": "draft", "sku": "SKU-12",
        "regular_price": "10.00", "sale_price": "", "manage_stock": True,
        "stock_quantity": 4, "stock_status": "instock", "categories": [],
    }


async def _mock_catalog(ctx):
    ctx.http.mock_get(f"{BASE}/products", [_product()], 200)


async def test_preview_records_hash_and_history_without_raw_csv():
    ctx = await _ctx()
    await _mock_catalog(ctx)
    preview = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV))
    assert preview.status == "success" and preview.data.import_id

    detail = await hc.get_csv_import(ctx, GetCsvImportParams(
        site_id="shop-test", import_id=preview.data.import_id))
    assert detail.status == "success"
    assert detail.data.status == "previewed"
    assert detail.data.csv_sha256 == hc._csv_hash(CSV)
    assert detail.data.failed == 1 and detail.data.failures == ["MISSING"]

    stored = await storage.get_csv_import_record(ctx, preview.data.import_id)
    assert "csv_text" not in stored
    assert CSV not in str(stored)

    history = await hc.list_csv_imports(ctx, ListCsvImportsParams(site_id="shop-test"))
    assert history.status == "success"
    assert [item.id for item in history.data.items] == [preview.data.import_id]


async def test_apply_updates_same_audit_run_with_outcome_and_failed_rows():
    ctx = await _ctx()
    await _mock_catalog(ctx)
    preview = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV))
    ctx.http.mock_post(f"{BASE}/products/12", _product(), 200)

    applied = await hc.apply_csv_catalog_import(ctx, ApplyCsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV, import_id=preview.data.import_id,
        expected_state_token=preview.data.state_token))
    assert applied.status == "success" and applied.data.import_id == preview.data.import_id

    record = await storage.get_csv_import_record(ctx, preview.data.import_id)
    assert record["status"] == "applied"
    assert record["updated"] == 1 and record["failed"] == 1
    assert record["failed_rows"] == [{"sku": "MISSING", "payload": {"regular_price": "9.00", "stock_status": "outofstock"}}]


async def test_retry_repreviews_only_persisted_failed_rows():
    ctx = await _ctx()
    await _mock_catalog(ctx)
    first = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV))

    retried = await hc.retry_csv_import_failures(ctx, RetryCsvImportFailuresParams(
        site_id="shop-test", import_id=first.data.import_id))
    assert retried.status == "success"
    assert retried.data.requested == 1 and retried.data.matched == 0
    assert retried.data.failures == ["MISSING"]
    assert retried.data.import_id != first.data.import_id


async def test_get_csv_import_does_not_cross_site_boundary():
    ctx = await _ctx()
    await _mock_catalog(ctx)
    preview = await hc.preview_csv_catalog_import(ctx, CsvCatalogImportParams(
        site_id="shop-test", csv_text=CSV))
    result = await hc.get_csv_import(ctx, GetCsvImportParams(
        site_id="another-site", import_id=preview.data.import_id))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_CSV_IMPORT_NOT_FOUND"
