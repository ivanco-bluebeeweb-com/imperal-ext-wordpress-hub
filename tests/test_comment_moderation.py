"""Tests for set_comment_status and reply_to_comment — Priority 1 of the Full
Feature Roadmap (docs/2026-08-09-full-feature-roadmap.md): comment moderation
had zero write coverage before this, only list_comments (read-only).
"""
from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_read as hr
import storage
from models import (
    ApplyBulkCommentStatusParams,
    BulkCommentStatusParams,
    EditCommentContentParams,
    ReplyToCommentParams,
    SetCommentStatusParams,
)


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


# --- set_comment_status --------------------------------------------------

async def test_approve_comment_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5",
                       {"id": 5, "author_name": "Jane", "status": "approved",
                        "content": {"rendered": "<p>nice post</p>"}, "post": 3, "date": "2026-08-09"},
                       200)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="approved"))
    assert r.status == "success"
    assert r.data.status == "approved"
    assert r.data.id == "5"


async def test_spam_comment_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5",
                       {"id": 5, "author_name": "Bot", "status": "spam",
                        "content": {"rendered": "buy now"}, "post": 3, "date": "2026-08-09"},
                       200)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="spam"))
    assert r.status == "success"
    assert r.data.status == "spam"


async def test_trash_comment_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5",
                       {"id": 5, "author_name": "Jane", "status": "trash",
                        "content": {"rendered": "x"}, "post": 3, "date": "2026-08-09"},
                       200)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="trash"))
    assert r.status == "success"
    assert r.data.status == "trash"


async def test_hold_comment_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5",
                       {"id": 5, "author_name": "Jane", "status": "hold",
                        "content": {"rendered": "x"}, "post": 3, "date": "2026-08-09"},
                       200)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="hold"))
    assert r.status == "success"
    assert r.data.status == "hold"


async def test_invalid_status_rejected_before_any_request():
    ctx = await _connected_ctx()
    # No HTTP mocked — if the handler tried to call out, this would fail with a mock miss.
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="deleted-forever"))
    assert r.status == "error"
    assert r.error_code == "COMMENT_INVALID_STATUS"


async def test_status_is_case_and_whitespace_insensitive():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5",
                       {"id": 5, "author_name": "Jane", "status": "approved",
                        "content": {"rendered": "x"}, "post": 3, "date": "2026-08-09"},
                       200)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="  APPROVED  "))
    assert r.status == "success"


async def test_comment_not_found():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/999", {}, 404)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=999, status="approved"))
    assert r.status == "error"
    assert r.error_code == "COMMENT_NOT_FOUND"


async def test_server_error_is_retryable():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5", {}, 500)
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="x-com", comment_id=5, status="approved"))
    assert r.status == "error"
    assert r.retryable is True


async def test_unknown_site_errors():
    ctx = await _connected_ctx()
    r = await hr.set_comment_status(ctx, SetCommentStatusParams(
        site_id="missing", comment_id=5, status="approved"))
    assert r.status == "error"


# --- guarded bulk comment moderation -------------------------------------


def _comment(comment_id, status="hold", date_gmt="2026-08-01T10:00:00"):
    return {"id": comment_id, "author_name": "Jane", "status": status,
            "date_gmt": date_gmt, "content": {"rendered": "<p>Text</p>"},
            "post": 3, "date": "2026-08-01"}


async def test_preview_and_apply_bulk_comment_status():
    ctx = await _connected_ctx()
    base = "https://x.com/wp-json/wp/v2/comments/"
    ctx.http.mock_get(base + "5", _comment(5))
    ctx.http.mock_get(base + "6", _comment(6))
    preview = await hr.preview_bulk_comment_status(ctx, BulkCommentStatusParams(
        site_id="x-com", comment_ids=[5, 6], status="approved"))
    assert preview.status == "success"
    assert preview.data.preview is True

    ctx.http.mock_get(base + "5", _comment(5))
    ctx.http.mock_get(base + "6", _comment(6))
    ctx.http.mock_post(base + "5", _comment(5, "approved"))
    ctx.http.mock_post(base + "6", _comment(6, "approved"))
    result = await hr.apply_bulk_comment_status(ctx, ApplyBulkCommentStatusParams(
        site_id="x-com", comment_ids=[5, 6], status="approved",
        expected_state_token=preview.data.state_token))
    assert result.status == "success"
    assert result.data.updated_ids == [5, 6]


async def test_apply_bulk_comment_status_refuses_stale_token():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/comments/5", _comment(5))
    result = await hr.apply_bulk_comment_status(ctx, ApplyBulkCommentStatusParams(
        site_id="x-com", comment_ids=[5], status="spam", expected_state_token="0" * 64))
    assert result.status == "error"
    assert result.error_code == "COMMENT_BULK_STATE_CHANGED"


# --- reply_to_comment -----------------------------------------------------

async def test_reply_to_comment_success():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/comments/5",
                      {"id": 5, "post": 3, "author_name": "Jane", "status": "approved",
                       "content": {"rendered": "nice"}, "date": "2026-08-09"}, 200)
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments",
                       {"id": 42, "author_name": "Site Admin", "status": "approved",
                        "content": {"rendered": "<p>Thanks for reading!</p>"},
                        "post": 3, "date": "2026-08-09", "parent": 5},
                       201)
    r = await hr.reply_to_comment(ctx, ReplyToCommentParams(
        site_id="x-com", comment_id=5, content="Thanks for reading!"))
    assert r.status == "success"
    assert r.data.id == "42"


async def test_reply_to_missing_comment_errors():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/comments/999", {}, 404)
    r = await hr.reply_to_comment(ctx, ReplyToCommentParams(
        site_id="x-com", comment_id=999, content="hi"))
    assert r.status == "error"
    assert r.error_code == "COMMENT_NOT_FOUND"


async def test_reply_blank_content_rejected_before_any_request():
    ctx = await _connected_ctx()
    # Pydantic min_length=1 on the model itself should already reject this upstream in real
    # dispatch, but the handler is defensive too — verify no HTTP call happens on whitespace-only.
    r = await hr.reply_to_comment(ctx, ReplyToCommentParams(
        site_id="x-com", comment_id=5, content="   "))
    assert r.status == "error"
    assert r.error_code == "COMMENT_EMPTY_REPLY"


async def test_reply_server_error_is_retryable():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/comments/5", {}, 503)
    r = await hr.reply_to_comment(ctx, ReplyToCommentParams(
        site_id="x-com", comment_id=5, content="hi"))
    assert r.status == "error"
    assert r.retryable is True


async def test_reply_unknown_site_errors():
    ctx = await _connected_ctx()
    r = await hr.reply_to_comment(ctx, ReplyToCommentParams(
        site_id="missing", comment_id=5, content="hi"))
    assert r.status == "error"


# --- edit_comment_content ---------------------------------------------------

async def test_edit_comment_content_success():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5",
                       {"id": 5, "author_name": "Jane", "status": "approved",
                        "content": {"rendered": "<p>corrected text</p>"}, "post": 3,
                        "date": "2026-08-09"},
                       200)
    r = await hr.edit_comment_content(ctx, EditCommentContentParams(
        site_id="x-com", comment_id=5, content="corrected text"))
    assert r.status == "success"
    assert r.data.id == "5"
    assert "corrected text" in r.data.snippet


async def test_edit_comment_content_not_found():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/999", {}, 404)
    r = await hr.edit_comment_content(ctx, EditCommentContentParams(
        site_id="x-com", comment_id=999, content="x"))
    assert r.status == "error"
    assert r.error_code == "COMMENT_NOT_FOUND"


async def test_edit_comment_content_server_error_is_retryable():
    ctx = await _connected_ctx()
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/comments/5", {}, 500)
    r = await hr.edit_comment_content(ctx, EditCommentContentParams(
        site_id="x-com", comment_id=5, content="x"))
    assert r.status == "error"
    assert r.retryable is True


async def test_edit_comment_content_unknown_site_errors():
    ctx = await _connected_ctx()
    r = await hr.edit_comment_content(ctx, EditCommentContentParams(
        site_id="missing", comment_id=5, content="x"))
    assert r.status == "error"
