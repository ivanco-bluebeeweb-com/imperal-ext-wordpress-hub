"""Tests for create_post / update_post — WordPress post/page publishing.

Ported capability from WP Publisher's publish_draft. Content is passed as
explicit {type, text, level} blocks — no document parsing is exercised or
expected here, by design.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_posts as hp
import storage
from models import CreatePostParams, PostBlockInput, UpdatePostParams

POSTS = "https://x.com/wp-json/wp/v2/posts"
PAGES = "https://x.com/wp-json/wp/v2/pages"
CATEGORIES = "https://x.com/wp-json/wp/v2/categories"
TAGS = "https://x.com/wp-json/wp/v2/tags"
SEO_BRIDGE = "https://x.com/wp-json/imperal/v1/seo"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _wp_post(pid=42, **over):
    data = {
        "id": pid, "title": {"rendered": "Hello"}, "slug": "hello",
        "status": "draft", "link": "https://x.com/?p=42", "date": "2026-08-03T10:00:00",
    }
    data.update(over)
    return data


async def test_create_post_happy_path_renders_blocks_and_defaults_draft():
    ctx = await _ctx()
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        blocks=[
            PostBlockInput(type="heading", text="Intro", level=2),
            PostBlockInput(type="paragraph", text="Body text"),
        ],
    ))
    assert result.status == "success"
    assert result.data.status == "draft"
    assert result.data.id == "42"
    assert "Created post" in result.summary


async def test_create_post_resolves_category_by_name():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", category="News",
    ))
    assert result.status == "success"
    assert result.data.category_resolved is True


async def test_create_post_warns_when_category_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", category="Nonexistent",
    ))
    assert result.status == "success"
    assert result.data.category_resolved is False
    assert "not found" in result.summary


async def test_create_post_uses_pages_base_for_page_type():
    ctx = await _ctx()
    ctx.http.mock_post(PAGES, _wp_post(pid=9), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="About", post_type="page",
    ))
    assert result.status == "success"
    assert result.data.post_type == "page"


async def test_create_post_scheduled_requires_date():
    ctx = await _ctx()
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", status="future",
    ))
    assert result.status == "error"
    assert result.error_code == "POST_SCHEDULE_DATE_MISSING"


async def test_create_post_writes_seo_fields_via_update_seo_meta():
    ctx = await _ctx()
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    ctx.http.mock_post(SEO_BRIDGE, {
        "id": 42, "type": "post", "meta_title": "SEO Title", "meta_description": "",
        "canonical_url": "", "robots": [], "focus_keyword": "", "rank_math_active": True,
    }, 200)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", meta_title="SEO Title",
    ))
    assert result.status == "success"
    assert "post was created, but SEO" not in result.summary


async def test_create_post_reports_seo_failure_as_warning_not_error():
    ctx = await _ctx()
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    ctx.http.mock_post(SEO_BRIDGE, {"code": "imperal_seo_forbidden", "message": "nope"}, 403)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", meta_title="SEO Title",
    ))
    # Bridge failed -> core-meta fallback also has no route registered in this
    # mock, so the write is expected to fail; the post itself still succeeds.
    assert result.status == "success"
    assert "SEO" in result.summary


async def test_create_post_reports_http_failure():
    ctx = await _ctx()
    ctx.http.mock_post(POSTS, {"code": "rest_cannot_create"}, 403)
    result = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hello"))
    assert result.status == "error"
    assert result.retryable is False


async def test_create_post_requires_connected_site():
    ctx = MockContext()
    result = await hp.create_post(ctx, CreatePostParams(site_id="missing", title="Hello"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_update_post_sends_only_given_fields():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(f"{POSTS}/42", _wp_post(status="publish"), 200)
    result = await hp.update_post(ctx, UpdatePostParams(
        site_id="x-com", post_id=42, status="publish",
    ))
    assert result.status == "success"
    assert result.data.status == "publish"
    _, kwargs = seen[0]
    assert kwargs["json"] == {"status": "publish"}


async def test_update_post_clears_category_with_empty_string():
    ctx = await _ctx()
    ctx.http.mock_post(f"{POSTS}/42", _wp_post(), 200)
    result = await hp.update_post(ctx, UpdatePostParams(
        site_id="x-com", post_id=42, category="",
    ))
    assert result.status == "success"


async def test_update_post_requires_at_least_one_field():
    ctx = await _ctx()
    result = await hp.update_post(ctx, UpdatePostParams(site_id="x-com", post_id=42))
    assert result.status == "error"
    assert result.error_code == "POST_NO_FIELDS"


async def test_update_post_renders_new_blocks_into_content():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(f"{POSTS}/42", _wp_post(), 200)
    result = await hp.update_post(ctx, UpdatePostParams(
        site_id="x-com", post_id=42,
        blocks=[PostBlockInput(type="paragraph", text="New body")],
    ))
    assert result.status == "success"
    _, kwargs = seen[0]
    assert "New body" in kwargs["json"]["content"]


# ─────────── tags ───────────

async def test_create_post_resolves_tags_by_name():
    ctx = await _ctx()
    ctx.http.mock_get(TAGS, [{"id": 3, "name": "Guides"}, {"id": 4, "name": "News"}], 200)
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", tags=["Guides", "News"],
    ))
    assert result.status == "success"
    assert result.data.tags_not_found == []
    _, kwargs = seen[0]
    assert sorted(kwargs["json"]["tags"]) == [3, 4]


async def test_create_post_reports_tags_not_found_without_failing():
    ctx = await _ctx()
    ctx.http.mock_get(TAGS, [{"id": 3, "name": "Guides"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", tags=["Guides", "Nonexistent"],
    ))
    assert result.status == "success"
    assert result.data.tags_not_found == ["Nonexistent"]
    assert "Nonexistent" in result.summary


async def test_update_post_replaces_tags():
    ctx = await _ctx()
    ctx.http.mock_get(TAGS, [{"id": 5, "name": "Guides"}], 200)
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(f"{POSTS}/42", _wp_post(), 200)
    result = await hp.update_post(ctx, UpdatePostParams(
        site_id="x-com", post_id=42, tags=["Guides"],
    ))
    assert result.status == "success"
    _, kwargs = seen[0]
    assert kwargs["json"]["tags"] == [5]


async def test_update_post_clears_tags_with_empty_list():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(f"{POSTS}/42", _wp_post(), 200)
    result = await hp.update_post(ctx, UpdatePostParams(
        site_id="x-com", post_id=42, tags=[],
    ))
    assert result.status == "success"
    _, kwargs = seen[0]
    assert kwargs["json"]["tags"] == []


# ─────────── featured_media ───────────

async def test_create_post_sets_featured_media():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", featured_media_id=99,
    ))
    assert result.status == "success"
    assert result.data.featured_media_set is True
    _, kwargs = seen[0]
    assert kwargs["json"]["featured_media"] == 99


async def test_update_post_sets_featured_media():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(f"{POSTS}/42", _wp_post(), 200)
    result = await hp.update_post(ctx, UpdatePostParams(
        site_id="x-com", post_id=42, featured_media_id=101,
    ))
    assert result.status == "success"
    assert result.data.featured_media_set is True
    _, kwargs = seen[0]
    assert kwargs["json"]["featured_media"] == 101


# ─────────── inline image blocks ───────────

async def test_create_post_renders_image_block_into_content():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        blocks=[
            PostBlockInput(type="paragraph", text="Intro"),
            PostBlockInput(type="image", text="A cat", media_id=55,
                          media_url="https://x.com/wp-content/uploads/cat.jpg",
                          caption="A very good cat"),
        ],
    ))
    assert result.status == "success"
    _, kwargs = seen[0]
    content = kwargs["json"]["content"]
    assert "wp:image" in content
    assert "wp-image-55" in content
    assert "cat.jpg" in content
    assert "A very good cat" in content
