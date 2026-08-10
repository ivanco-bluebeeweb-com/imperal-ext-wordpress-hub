"""Contract tests for Rank Math Instant Indexing (IndexNow) -- Rank Math's OWN
native REST routes at rankmath/v1/in/*, no Imperal Bridge involved.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_indexnow as hin
import storage
from models import (
    ClearIndexNowLogParams,
    IndexNowLogParams,
    ResetIndexNowKeyParams,
    SubmitIndexNowUrlsParams,
)

BASE = "https://shop.test/wp-json/rankmath/v1/in"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


# ─────────── submit_urls_to_indexnow ───────────

async def test_submit_urls_to_indexnow_success():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/submitUrls", {"success": True, "message": "1 URL submitted."})
    result = await hin.submit_urls_to_indexnow(
        ctx, SubmitIndexNowUrlsParams(site_id="shop-test", urls=["https://shop.test/new-post/"]))
    assert result.status == "success"
    assert result.data.submitted_count == 1
    assert "submitted" in result.summary.lower()


async def test_submit_urls_to_indexnow_multiple():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/submitUrls", {"success": True, "message": "2 URLs submitted."})
    result = await hin.submit_urls_to_indexnow(
        ctx, SubmitIndexNowUrlsParams(
            site_id="shop-test",
            urls=["https://shop.test/a/", "https://shop.test/b/"]))
    assert result.status == "success"
    assert result.data.submitted_count == 2


async def test_submit_urls_to_indexnow_invalid_urls():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/submitUrls", {"code": "invalid_urls", "message": "Invalid URLs provided."}, 400)
    result = await hin.submit_urls_to_indexnow(
        ctx, SubmitIndexNowUrlsParams(site_id="shop-test", urls=["not-a-url"]))
    assert result.status == "error"
    assert result.error_code == "INDEXNOW_INVALID_URLS"


async def test_submit_urls_to_indexnow_module_not_available():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/submitUrls", {"code": "rest_no_route"}, 404)
    result = await hin.submit_urls_to_indexnow(
        ctx, SubmitIndexNowUrlsParams(site_id="shop-test", urls=["https://shop.test/x/"]))
    assert result.status == "error"
    assert result.error_code == "INDEXNOW_NOT_AVAILABLE"


async def test_submit_urls_to_indexnow_site_not_connected():
    ctx = MockContext()
    result = await hin.submit_urls_to_indexnow(
        ctx, SubmitIndexNowUrlsParams(site_id="ghost", urls=["https://ghost.test/x/"]))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


# ─────────── list_indexnow_log ───────────

async def test_list_indexnow_log_maps_entries():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/getLog", {"data": [
        {"url": "https://shop.test/a/", "status": 200, "manual_submission": True,
         "message": "URL submitted successfully.", "timeFormatted": "2026-08-10 10:00:00",
         "timeHumanReadable": "2 hours ago"},
    ], "total": 1})
    result = await hin.list_indexnow_log(ctx, IndexNowLogParams(site_id="shop-test"))
    assert result.status == "success"
    assert len(result.data.items) == 1
    assert result.data.items[0].url == "https://shop.test/a/"
    assert result.data.items[0].manual_submission is True


async def test_list_indexnow_log_empty():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/getLog", {"data": [], "total": 0})
    result = await hin.list_indexnow_log(ctx, IndexNowLogParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.items == []


async def test_list_indexnow_log_not_available():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/getLog", {"code": "rest_no_route"}, 404)
    result = await hin.list_indexnow_log(ctx, IndexNowLogParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "INDEXNOW_NOT_AVAILABLE"


# ─────────── clear_indexnow_log ───────────

async def test_clear_indexnow_log_success():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/clearLog", {"status": "ok"})
    result = await hin.clear_indexnow_log(ctx, ClearIndexNowLogParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.cleared is True
    assert result.refresh_panels == ["center"]


async def test_clear_indexnow_log_not_available():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/clearLog", {"code": "rest_no_route"}, 404)
    result = await hin.clear_indexnow_log(ctx, ClearIndexNowLogParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "INDEXNOW_NOT_AVAILABLE"


# ─────────── reset_indexnow_key ───────────

async def test_reset_indexnow_key_success():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/resetKey", {
        "status": "ok", "key": "abc123def456", "location": "https://shop.test/abc123def456.txt"})
    result = await hin.reset_indexnow_key(ctx, ResetIndexNowKeyParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.key == "abc123def456"
    assert result.data.location == "https://shop.test/abc123def456.txt"


async def test_reset_indexnow_key_not_available():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/resetKey", {"code": "rest_no_route"}, 404)
    result = await hin.reset_indexnow_key(ctx, ResetIndexNowKeyParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "INDEXNOW_NOT_AVAILABLE"
