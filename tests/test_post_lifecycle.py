"""Contract tests for post/page lifecycle gaps: delete, duplicate, bulk status."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_post_lifecycle as hpl
import storage
from models import (
    ApplyBulkPostCommentStatusParams,
    ApplyBulkPostStatusParams,
    BulkPostCommentStatusParams,
    BulkPostStatusParams,
    DeletePostParams,
    DuplicatePostParams,
    GetPostRevisionsParams,
    RestoreRevisionParams,
    SetPostPasswordParams,
)

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


async def test_preview_and_apply_bulk_post_status_all_succeed():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/1", _post(1, modified_gmt="2026-01-01T10:00:00"))
    ctx.http.mock_get(f"{BASE}/posts/2", _post(2, modified_gmt="2026-01-01T10:00:00"))
    preview = await hpl.preview_bulk_post_status(ctx, BulkPostStatusParams(
        site_id="blog-test", post_ids=[1, 2], status="draft"))
    assert preview.status == "success"
    assert preview.data.preview is True
    assert len(preview.data.state_token) == 64

    ctx.http.mock_get(f"{BASE}/posts/1", _post(1, modified_gmt="2026-01-01T10:00:00"))
    ctx.http.mock_get(f"{BASE}/posts/2", _post(2, modified_gmt="2026-01-01T10:00:00"))
    ctx.http.mock_post(f"{BASE}/posts/1", {"id": 1, "status": "draft"})
    ctx.http.mock_post(f"{BASE}/posts/2", {"id": 2, "status": "draft"})
    result = await hpl.bulk_update_post_status(ctx, ApplyBulkPostStatusParams(
        site_id="blog-test", post_ids=[1, 2], status="draft", expected_state_token=preview.data.state_token))
    assert result.status == "success"
    assert result.data.updated_ids == [1, 2]
    assert result.data.failed_ids == []


async def test_apply_bulk_post_status_refuses_stale_token_before_writes():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/1", _post(1, modified_gmt="2026-01-01T10:00:00"))
    result = await hpl.bulk_update_post_status(ctx, ApplyBulkPostStatusParams(
        site_id="blog-test", post_ids=[1], status="draft", expected_state_token="0" * 64))
    assert result.status == "error"
    assert result.error_code == "POST_BULK_STATE_CHANGED"


async def test_preview_bulk_post_status_rejects_invalid_status():
    ctx = await _ctx()
    result = await hpl.preview_bulk_post_status(ctx, BulkPostStatusParams(
        site_id="blog-test", post_ids=[1], status="not-a-status"))
    assert result.status == "error"
    assert result.error_code == "POST_INVALID_STATUS"


async def test_preview_and_apply_bulk_post_comment_status_all_succeed():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/1", _post(1, comment_status="open", modified_gmt="2026-01-01T10:00:00"))
    ctx.http.mock_get(f"{BASE}/posts/2", _post(2, comment_status="open", modified_gmt="2026-01-01T10:00:00"))
    preview = await hpl.preview_bulk_post_comment_status(ctx, BulkPostCommentStatusParams(
        site_id="blog-test", post_ids=[1, 2], comment_status="closed"))
    assert preview.status == "success"
    assert preview.data.preview is True
    assert len(preview.data.state_token) == 64

    ctx.http.mock_get(f"{BASE}/posts/1", _post(1, comment_status="open", modified_gmt="2026-01-01T10:00:00"))
    ctx.http.mock_get(f"{BASE}/posts/2", _post(2, comment_status="open", modified_gmt="2026-01-01T10:00:00"))
    ctx.http.mock_post(f"{BASE}/posts/1", {"id": 1, "comment_status": "closed"})
    ctx.http.mock_post(f"{BASE}/posts/2", {"id": 2, "comment_status": "closed"})
    result = await hpl.apply_bulk_post_comment_status(ctx, ApplyBulkPostCommentStatusParams(
        site_id="blog-test", post_ids=[1, 2], comment_status="closed", expected_state_token=preview.data.state_token))
    assert result.status == "success"
    assert result.data.updated_ids == [1, 2]
    assert result.data.failed_ids == []


async def test_apply_bulk_post_comment_status_refuses_stale_token_before_writes():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/1", _post(1, comment_status="open", modified_gmt="2026-01-01T10:00:00"))
    result = await hpl.apply_bulk_post_comment_status(ctx, ApplyBulkPostCommentStatusParams(
        site_id="blog-test", post_ids=[1], comment_status="closed", expected_state_token="0" * 64))
    assert result.status == "error"
    assert result.error_code == "POST_COMMENT_BULK_STATE_CHANGED"


async def test_preview_bulk_post_comment_status_rejects_invalid_value():
    ctx = await _ctx()
    result = await hpl.preview_bulk_post_comment_status(ctx, BulkPostCommentStatusParams(
        site_id="blog-test", post_ids=[1], comment_status="maybe"))
    assert result.status == "error"
    assert result.error_code == "POST_INVALID_COMMENT_STATUS"


def _revision(rev_id=50, **over):
    data = {
        "id": rev_id, "parent": 7, "author": "3",
        "date": "2026-01-01T09:00:00",
        "title": {"rendered": "Older title", "raw": "Older title"},
        "content": {"rendered": "<p>Older body</p>", "raw": "<p>Older body</p>"},
        "excerpt": {"rendered": "Older excerpt", "raw": "Older excerpt"},
    }
    data.update(over)
    return data


async def test_get_post_revisions_lists_newest_first():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/7/revisions", [_revision(50), _revision(49)])
    result = await hpl.get_post_revisions(ctx, GetPostRevisionsParams(site_id="blog-test", post_id=7))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert result.data.items[0].id == "50"
    assert result.data.items[0].post_id == 7


async def test_get_post_revisions_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/999/revisions", {"code": "rest_post_invalid_id"}, 404)
    result = await hpl.get_post_revisions(ctx, GetPostRevisionsParams(site_id="blog-test", post_id=999))
    assert result.status == "error"
    assert result.error_code == "WP_POST_NOT_FOUND"


async def test_restore_revision_writes_revision_content_back_onto_live_post():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/7/revisions/50", _revision(50))
    ctx.http.mock_post(f"{BASE}/posts/7", _post(
        pid=7, title={"rendered": "Older title"}, content={"rendered": "<p>Older body</p>"},
        excerpt={"rendered": "Older excerpt"}))
    result = await hpl.restore_revision(ctx, RestoreRevisionParams(
        site_id="blog-test", post_id=7, revision_id=50))
    assert result.status == "success"
    assert result.data.title == "Older title"
    assert "50" in result.summary


async def test_restore_revision_missing_revision():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/posts/7/revisions/999", {"code": "rest_post_invalid_id"}, 404)
    result = await hpl.restore_revision(ctx, RestoreRevisionParams(
        site_id="blog-test", post_id=7, revision_id=999))
    assert result.status == "error"
    assert result.error_code == "WP_POST_NOT_FOUND"


async def test_set_post_password_protects_post():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/posts/7", _post(pid=7))
    result = await hpl.set_post_password(ctx, SetPostPasswordParams(
        site_id="blog-test", post_id=7, password="hunter2"))
    assert result.status == "success"
    assert "protected" in result.summary.lower()


async def test_set_post_password_empty_removes_protection():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/posts/7", _post(pid=7))
    result = await hpl.set_post_password(ctx, SetPostPasswordParams(
        site_id="blog-test", post_id=7, password=""))
    assert result.status == "success"
    assert "removed" in result.summary.lower()


async def test_set_post_password_not_found():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/posts/999", {"code": "rest_post_invalid_id"}, 404)
    result = await hpl.set_post_password(ctx, SetPostPasswordParams(
        site_id="blog-test", post_id=999, password="x"))
    assert result.status == "error"
    assert result.error_code == "WP_POST_NOT_FOUND"


# ── Part D2 (SCENARIO_TESTING_STANDARD.md): idempotency / double-invocation ─

async def test_d2_double_force_delete_second_call_fails_clean():
    """A retried force=true delete on a post already permanently gone must
    surface WordPress's own 404 cleanly, never crash or claim a second
    successful permanent deletion (which -- unlike the default trash path --
    would be actively misleading since force delete has no undo)."""
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/posts/7", {"deleted": True, "previous": {}}, 200)
    first = await hpl.delete_post(ctx, DeletePostParams(
        site_id="blog-test", post_id=7, force=True))
    assert first.status == "success", first.error

    # MockHTTP matches the FIRST registered entry for a pattern, not a queue --
    # clear it so the second call sees WordPress's own 404, not the stale 200.
    ctx.http._mocks.clear()
    _mock_delete(ctx, f"{BASE}/posts/7", {"code": "rest_post_invalid_id"}, 404)
    second = await hpl.delete_post(ctx, DeletePostParams(
        site_id="blog-test", post_id=7, force=True))
    assert second.status == "error"
    assert second.error_code == "WP_POST_NOT_FOUND"
