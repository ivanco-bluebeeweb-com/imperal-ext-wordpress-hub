"""Tests for update_media_alt — writing alt text into the WP media library.

The risky parts of this handler are not the happy path: they are (a) never
clobbering alt text a human already wrote, (b) refusing to write blank alt
over a decorative image, and (c) not reporting success when WordPress did not
actually store the value. Each of those has a test here.
"""
from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_read as hr
import storage
from models import ListMediaParams, ListOrdersParams, UpdateMediaAltParams, MediaAltItem


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _item(mid=9, alt="a kitchen"):
    return UpdateMediaAltParams(site_id="x-com", items=[MediaAltItem(media_id=mid, alt_text=alt)])


async def test_writes_alt_when_currently_empty():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": ""}, 200)
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": "a kitchen"}, 200)
    r = await hr.update_media_alt(ctx, _item())
    assert r.status == "success"
    assert r.data.updated == 1 and r.data.updated_ids == [9]
    assert r.data.skipped_existing == 0 and r.data.failed == 0


async def test_existing_human_alt_is_left_alone():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/9",
                      {"id": 9, "alt_text": "wording a human chose"}, 200)
    # No POST is mocked: if the handler tried to write, the call would fail.
    r = await hr.update_media_alt(ctx, _item())
    assert r.status == "success"
    assert r.data.updated == 0 and r.data.skipped_existing == 1
    assert r.data.skipped_ids == [9]


async def test_overwrite_true_replaces_existing_alt():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": "old"}, 200)
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": "a kitchen"}, 200)
    p = _item()
    p.overwrite = True
    r = await hr.update_media_alt(ctx, p)
    assert r.status == "success" and r.data.updated == 1


async def test_blank_alt_is_refused_before_any_write():
    ctx = await _connected_ctx()
    r = await hr.update_media_alt(ctx, _item(alt="   "))
    assert r.status == "error" and r.error_code == "MEDIA_EMPTY_ALT"


async def test_empty_item_list_is_refused():
    ctx = await _connected_ctx()
    r = await hr.update_media_alt(ctx, UpdateMediaAltParams(site_id="x-com", items=[]))
    assert r.status == "error" and r.error_code == "MEDIA_NO_ITEMS"


async def test_more_than_100_items_refused():
    ctx = await _connected_ctx()
    items = [MediaAltItem(media_id=i, alt_text="x") for i in range(101)]
    r = await hr.update_media_alt(ctx, UpdateMediaAltParams(site_id="x-com", items=items))
    assert r.status == "error" and r.error_code == "MEDIA_TOO_MANY"


async def test_server_echoing_a_different_value_counts_as_failure():
    """WordPress returning 200 is not proof it stored what we sent."""
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": ""}, 200)
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": ""}, 200)
    r = await hr.update_media_alt(ctx, _item())
    assert r.status == "error" and r.error_code == "MEDIA_ALL_FAILED"


async def test_auth_rejected_reports_error():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/9", {}, 401)
    r = await hr.update_media_alt(ctx, _item())
    assert r.status == "error" and r.error_code == "MEDIA_ALL_FAILED"


async def test_partial_success_is_success_with_failures_listed():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": ""}, 200)
    ctx.http.mock_post("https://x.com/wp-json/wp/v2/media/9", {"id": 9, "alt_text": "ok one"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media/10", {}, 500)
    p = UpdateMediaAltParams(site_id="x-com", items=[
        MediaAltItem(media_id=9, alt_text="ok one"),
        MediaAltItem(media_id=10, alt_text="will fail"),
    ])
    r = await hr.update_media_alt(ctx, p)
    assert r.status == "success"
    assert r.data.updated == 1 and r.data.failed == 1
    assert r.data.failures and "#10" in r.data.failures[0]


async def test_unknown_site_errors():
    ctx = await _connected_ctx()
    p = _item()
    p.site_id = "missing"
    r = await hr.update_media_alt(ctx, p)
    assert r.status == "error"


async def test_list_media_missing_alt_only_filters():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [
        {"id": 1, "title": {"rendered": "has"}, "source_url": "https://x.com/a.png",
         "mime_type": "image/png", "alt_text": "described"},
        {"id": 2, "title": {"rendered": "bare"}, "source_url": "https://x.com/b.png",
         "mime_type": "image/png", "alt_text": ""},
    ], 200)
    r = await hr.list_media(ctx, ListMediaParams(site_id="x-com", missing_alt_only=True))
    assert [i.id for i in r.data.items] == ["2"]


async def test_list_media_exposes_alt_text():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [
        {"id": 1, "title": {"rendered": "has"}, "source_url": "https://x.com/a.png",
         "mime_type": "image/png", "alt_text": "described"},
    ], 200)
    r = await hr.list_media(ctx, ListMediaParams(site_id="x-com"))
    assert r.data.items[0].alt_text == "described"


async def test_list_orders_keeps_its_own_params_model():
    """Regression: orders once shared ListMediaParams and inherited media fields."""
    assert "missing_alt_only" not in ListOrdersParams.model_fields
    assert "missing_alt_only" in ListMediaParams.model_fields
