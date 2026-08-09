"""Contract tests for post/page lifecycle gaps: delete, duplicate, bulk status."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_post_lifecycle as hpl
import storage
from models import BulkUpdatePostStatusParams, DeletePostParams, DuplicatePostParams

BASE = "https://blog.test/wp-json/wp/v2"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "editor", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


def _post(pid=7, **over):
    data = {
        "id": pid, "title": {"rendered": "Original"}, "link": "https://blog.test/original",
        "slug": "original", "status": "publish", "date": "2026-01-01T10:00:00",
        "content": {"rendered": "<p>Body</p>"}, "excerpt": {"rendered": "Excerpt"},
        "categories": [4], "tags": [9], "featured_media": 3,
    }
    data.update(over)
    return data


async def test_delete_post_default_trashes_not_permanent():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/posts/7", {"id": 7, "status": "trash"}, 200)
    result = await hpl.delete_post(ctx, DeletePostParams(site_id="blog-test", post_id=7))
    assert result.status == "success"
    assert result.data.trashed is True
    assert result.data.deleted is True


async def test_delete_post_force_permanently_deletes():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/posts/7", {"deleted": True, "previous": {}}, 200)
    result = await hpl.delete_post(ctx, DeletePostParams(site_id="blog-test", post_id=7, force=True))
    assert result.status == "success"
    assert result.data.trashed is False
    assert "permanently" in result.summary.lower()


async def test_delete_post_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/posts/999", {"code": "rest_post_invalid_id"}, 404)
    result = await hpl.delete_post(ctx, DeletePostParams(site_id="blog-test", post_id=999))
    assert result.status == "error"
    assert result.error_code == "WP_POST_NOT_FOUND"


async def test_duplicate_post_copies_title_content_and_creates_draft():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/7", _post())
    ctx.http.mock_post(f"{BASE}/posts", _post(pid=8, title={"rendered": "Original (Copy)"},
                                               status="draft", link="https://blog.test/original-copy"))
    result = await hpl.duplicate_post(ctx, DuplicatePostParams(site_id="blog-test", post_id=7))
    assert result.status == "success"
    assert result.data.id == "8"
    assert "Copy" in result.data.title
    assert result.data.status == "draft"


async def test_duplicate_post_custom_suffix():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/7", _post())
    ctx.http.mock_post(f"{BASE}/posts", _post(pid=9, title={"rendered": "Original — 2026"}))
    result = await hpl.duplicate_post(ctx, DuplicatePostParams(
        site_id="blog-test", post_id=7, title_suffix=" — 2026"))
    assert result.status == "success"


async def test_duplicate_post_source_missing():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/404", {"code": "rest_post_invalid_id"}, 404)
    result = await hpl.duplicate_post(ctx, DuplicatePostParams(site_id="blog-test", post_id=404))
    assert result.status == "error"
    assert result.error_code == "WP_POST_NOT_FOUND"


async def test_bulk_update_post_status_all_succeed():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/posts/1", {"id": 1, "status": "publish"})
    ctx.http.mock_post(f"{BASE}/posts/2", {"id": 2, "status": "publish"})
    result = await hpl.bulk_update_post_status(ctx, BulkUpdatePostStatusParams(
        site_id="blog-test", post_ids=[1, 2], status="publish"))
    assert result.status == "success"
    assert result.data.updated_ids == [1, 2]
    assert result.data.failed_ids == []


async def test_bulk_update_post_status_partial_failure_reported_not_dropped():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/posts/1", {"id": 1, "status": "draft"})
    ctx.http.mock_post(f"{BASE}/posts/2", {"code": "rest_post_invalid_id"}, 404)
    result = await hpl.bulk_update_post_status(ctx, BulkUpdatePostStatusParams(
        site_id="blog-test", post_ids=[1, 2], status="draft"))
    assert result.status == "success"
    assert result.data.updated_ids == [1]
    assert result.data.failed_ids == [2]
    assert "1/2" in result.summary


async def test_bulk_update_post_status_rejects_invalid_status():
    ctx = await _ctx()
    result = await hpl.bulk_update_post_status(ctx, BulkUpdatePostStatusParams(
        site_id="blog-test", post_ids=[1], status="not-a-status"))
    assert result.status == "error"
    assert result.error_code == "POST_INVALID_STATUS"
