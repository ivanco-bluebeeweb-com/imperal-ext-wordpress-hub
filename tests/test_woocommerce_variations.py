"""Contract tests for guarded WooCommerce product variations."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_woocommerce_catalog as hc
import storage
from models import (
    CreateProductVariationParams,
    ListProductVariationsParams,
    UpdateProductVariationParams,
    VariationAttributeInput,
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


def _parent_product(**over):
    data = {
        "id": 12, "type": "variable", "attributes": [{
            "name": "Color", "variation": True, "options": ["Red", "Blue"],
        }],
    }
    data.update(over)
    return data


def _variation(**over):
    data = {
        "id": 81, "status": "draft", "sku": "MUG-RED-S", "regular_price": "12.00",
        "sale_price": "", "manage_stock": True, "stock_quantity": 4,
        "stock_status": "instock", "attributes": [
            {"id": 0, "name": "Color", "option": "Red"},
            {"id": 0, "name": "Size", "option": "Small"},
        ],
    }
    data.update(over)
    return data


def _spy(ctx, method):
    seen = []
    real = getattr(ctx.http, method)

    async def wrapper(url, **kwargs):
        seen.append((url, kwargs))
        return await real(url, **kwargs)

    setattr(ctx.http, method, wrapper)
    return seen


async def test_list_variations_exposes_attributes_and_state_token():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/12/variations", [_variation()], 200)
    result = await hc.list_product_variations(ctx, ListProductVariationsParams(
        site_id="shop-test", product_id=12))
    item = result.data.items[0]
    assert result.status == "success" and item.id == "81"
    assert item.attributes == ["Color: Red", "Size: Small"]
    assert len(item.state_token) == 64


async def test_create_variation_defaults_to_draft_and_normalizes_stock():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/12", _parent_product(), 200)
    ctx.http.mock_post(f"{BASE}/products/12/variations", _variation(), 201)
    seen = _spy(ctx, "post")
    result = await hc.create_product_variation(ctx, CreateProductVariationParams(
        site_id="shop-test", product_id=12,
        attributes=[VariationAttributeInput(name=" Color ", option=" Red ")],
        regular_price="12", stock_quantity=4))
    assert result.status == "success" and result.data.status == "draft"
    assert seen[-1][1]["json"] == {
        "regular_price": "12.00", "stock_quantity": 4, "status": "draft",
        "manage_stock": True, "attributes": [{"name": "Color", "option": "Red"}],
    }


async def test_create_rejects_duplicate_attributes_before_http():
    ctx = await _ctx()
    result = await hc.create_product_variation(ctx, CreateProductVariationParams(
        site_id="shop-test", product_id=12, attributes=[
            VariationAttributeInput(name="Color", option="Red"),
            VariationAttributeInput(name="color", option="Blue"),
        ]))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_DUPLICATE_VARIATION_ATTRIBUTE"


async def test_create_rejects_attribute_option_not_on_parent_before_post():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/products/12", _parent_product(), 200)
    seen = _spy(ctx, "post")
    result = await hc.create_product_variation(ctx, CreateProductVariationParams(
        site_id="shop-test", product_id=12,
        attributes=[VariationAttributeInput(name="Color", option="Green")]))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_INVALID_VARIATION_ATTRIBUTE"
    assert seen == []


async def test_update_rechecks_token_and_sends_only_explicit_fields():
    ctx = await _ctx()
    variation = _variation()
    ctx.http.mock_get(f"{BASE}/products/12/variations/81", variation, 200)
    ctx.http.mock_post(f"{BASE}/products/12/variations/81", _variation(regular_price="14.50"), 200)
    seen = _spy(ctx, "post")
    result = await hc.update_product_variation(ctx, UpdateProductVariationParams(
        site_id="shop-test", product_id=12, variation_id=81,
        expected_state_token=hc._variation_state_token(variation), regular_price="14.5"))
    assert result.status == "success" and result.data.regular_price == "14.50"
    assert seen[-1][1]["json"] == {"regular_price": "14.50"}


async def test_update_blocks_stale_state_before_write():
    ctx = await _ctx()
    preview = _variation()
    changed = _variation(stock_quantity=3)
    ctx.http.mock_get(f"{BASE}/products/12/variations/81", changed, 200)
    seen = _spy(ctx, "post")
    result = await hc.update_product_variation(ctx, UpdateProductVariationParams(
        site_id="shop-test", product_id=12, variation_id=81,
        expected_state_token=hc._variation_state_token(preview), stock_quantity=2))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_VARIATION_STATE_CHANGED"
    assert seen == []
