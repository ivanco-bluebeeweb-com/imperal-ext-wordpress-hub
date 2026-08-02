"""Contract tests for guarded WooCommerce variation CSV imports."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_catalog as hc
import storage
from models import ApplyCsvVariationImportParams, CsvVariationImportParams

BASE = "https://shop.test/wp-json/wc/v3"
CSV = (
    "parent_sku,variation_sku,regular_price,stock_quantity,stock_status\n"
    "PARENT-12,VAR-RED,12.5,3,instock\n"
    "PARENT-12,VAR-BLUE,,0,outofstock\n"
    "MISSING,VAR-X,9,,\n"
)


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _parent(**over):
    data = {"id": 12, "type": "variable", "sku": "PARENT-12", "status": "draft"}
    data.update(over)
    return data


def _variation(vid, sku, **over):
    data = {
        "id": vid, "status": "draft", "sku": sku, "regular_price": "10.00",
        "sale_price": "", "manage_stock": True, "stock_quantity": 4,
        "stock_status": "instock", "attributes": [{"name": "Color", "option": sku}],
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


async def _mock_targets(ctx, red=None, blue=None):
    # MockContext resolves URLs by substring, therefore the specific variation
    # endpoint must be registered before the broader products search endpoint.
    ctx.http.mock_get(
        f"{BASE}/products/12/variations",
        [red or _variation(81, "VAR-RED"), blue or _variation(82, "VAR-BLUE")], 200)
    ctx.http.mock_get(f"{BASE}/products", [_parent()], 200)


async def test_csv_variation_preview_matches_pair_reports_missing_and_never_writes():
    ctx = await _ctx()
    await _mock_targets(ctx)
    seen = _spy(ctx, "post")
    result = await hc.preview_csv_variation_import(ctx, CsvVariationImportParams(
        site_id="shop-test", csv_text=CSV))
    assert result.status == "success" and result.data.preview is True
    assert result.data.requested == 3 and result.data.matched == 2
    assert result.data.failures == ["MISSING / VAR-X"]
    assert len(result.data.state_token) == 64
    assert seen == []


async def test_csv_variation_preview_rejects_duplicate_pair_before_http():
    ctx = await _ctx()
    result = await hc.preview_csv_variation_import(ctx, CsvVariationImportParams(
        site_id="shop-test", csv_text=(
            "parent_sku,variation_sku,stock_status\n"
            "PARENT-12,VAR-RED,instock\nparent-12,var-red,outofstock\n")))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_DUPLICATE_CSV_VARIATION"


async def test_csv_variation_apply_rechecks_all_targets_before_any_write():
    ctx = await _ctx()
    red, blue = _variation(81, "VAR-RED"), _variation(82, "VAR-BLUE")
    await _mock_targets(ctx, red, _variation(82, "VAR-BLUE", stock_quantity=1))
    seen = _spy(ctx, "post")
    result = await hc.apply_csv_variation_import(ctx, ApplyCsvVariationImportParams(
        site_id="shop-test", csv_text=CSV,
        expected_state_token=hc._csv_variation_state_token([
            {"variation": red}, {"variation": blue},
        ])))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_CSV_VARIATION_STATE_CHANGED"
    assert seen == []


async def test_csv_variation_apply_updates_matches_and_reports_partial_failure():
    ctx = await _ctx()
    red, blue = _variation(81, "VAR-RED"), _variation(82, "VAR-BLUE")
    await _mock_targets(ctx, red, blue)
    ctx.http.mock_post(f"{BASE}/products/12/variations/81", red, 200)
    ctx.http.mock_post(f"{BASE}/products/12/variations/82", {"code": "woocommerce_rest_cannot_edit"}, 403)
    result = await hc.apply_csv_variation_import(ctx, ApplyCsvVariationImportParams(
        site_id="shop-test", csv_text=CSV,
        expected_state_token=hc._csv_variation_state_token([
            {"variation": red}, {"variation": blue},
        ])))
    assert result.status == "success"
    assert result.data.updated_ids == [81]
    assert result.data.failed == 2
    assert result.data.failures[0] == "MISSING / VAR-X"
    assert "#12/#82" in result.data.failures[1]
