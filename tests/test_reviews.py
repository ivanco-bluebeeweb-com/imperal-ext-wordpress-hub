"""Contract tests for WooCommerce product review moderation."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_reviews as hr
import storage
from models import ListProductReviewsParams, ReplyToProductReviewParams, SetProductReviewStatusParams

WC_BASE = "https://shop.test/wp-json/wc/v3"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _review(rid=5, **over):
    data = {
        "id": rid, "product_id": 42, "reviewer": "Jane", "reviewer_email": "jane@x.com",
        "rating": 4, "status": "hold", "review": "<p>Great product!</p>",
        "date_created": "2026-01-01T10:00:00",
    }
    data.update(over)
    return data


async def test_list_product_reviews_maps_fields_and_counts_pending():
    ctx = await _ctx()
    ctx.http.mock_get(f"{WC_BASE}/products/reviews", [_review(), _review(rid=6, status="approved")])
    result = await hr.list_product_reviews(ctx, ListProductReviewsParams(site_id="shop-test"))
    assert result.status == "success"
    items = result.data.items
    assert len(items) == 2
    assert items[0].rating == 4
    assert items[0].product_id == 42
    assert "pending" in result.summary


async def test_list_product_reviews_reports_woocommerce_not_active():
    ctx = await _ctx()
    ctx.http.mock_get(f"{WC_BASE}/products/reviews", {"code": "rest_no_route"}, 404)
    result = await hr.list_product_reviews(ctx, ListProductReviewsParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "WOOCOMMERCE_NOT_FOUND"


async def test_set_product_review_status_approves():
    ctx = await _ctx()
    ctx.http.mock_post(f"{WC_BASE}/products/reviews/5", _review(rid=5, status="approved"), 200)
    # PUT isn't separately mocked in MockHTTP by default verb -- register under put too
    ctx.http._mocks.append(("PUT", f"{WC_BASE}/products/reviews/5", _review(rid=5, status="approved"), 200, {}))
    result = await hr.set_product_review_status(
        ctx, SetProductReviewStatusParams(site_id="shop-test", review_id=5, status="approved"))
    assert result.status == "success"
    assert result.data.status == "approved"


async def test_set_product_review_status_rejects_invalid_status():
    ctx = await _ctx()
    result = await hr.set_product_review_status(
        ctx, SetProductReviewStatusParams(site_id="shop-test", review_id=5, status="bogus"))
    assert result.status == "error"
    assert result.error_code == "WC_REVIEW_INVALID_STATUS"


async def test_reply_to_product_review_looks_up_parent_product_then_posts_comment():
    ctx = await _ctx()
    ctx.http.mock_get(f"{WC_BASE}/products/reviews/5", _review(rid=5, product_id=42))
    ctx.http.mock_post("https://shop.test/wp-json/wp/v2/comments", {
        "id": 99, "author_name": "Shop Admin", "status": "approved",
        "content": {"rendered": "<p>Thanks!</p>"}, "post": 42, "date": "2026-01-02T10:00:00",
    }, 201)
    result = await hr.reply_to_product_review(
        ctx, ReplyToProductReviewParams(site_id="shop-test", review_id=5, content="Thanks!"))
    assert result.status == "success"
    assert result.data.post_id == "42"


async def test_reply_to_product_review_surfaces_missing_parent():
    ctx = await _ctx()
    ctx.http.mock_get(f"{WC_BASE}/products/reviews/5", {"code": "rest_no_route"}, 404)
    result = await hr.reply_to_product_review(
        ctx, ReplyToProductReviewParams(site_id="shop-test", review_id=5, content="Thanks!"))
    assert result.status == "error"
