"""Tests for create_post / update_post — WordPress post/page publishing.

Ported capability from WP Publisher's publish_draft. Content is passed as
explicit {type, text, level} blocks — no document parsing is exercised or
expected here, by design.

slug / meta_title / category are mandatory for post_type='post' (the
content pipeline's main output) — most tests below pass all three so they
exercise the rest of create_post's behaviour; the dedicated
test_create_post_requires_seo_fields_for_posts test covers the gate itself.
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

# Shared "already satisfies the mandatory SEO fields" kwargs so every test
# below that isn't specifically about the requirement gate doesn't have to
# repeat slug/meta_title/category by hand.
SEO_OK = dict(slug="hello", meta_title="Hello — SEO Title", category="News",
              excerpt="A short standalone summary of the article.", featured_media_id=99)


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


# ─────────── mandatory SEO fields for post_type='post' ───────────

async def test_create_post_requires_seo_fields_for_posts():
    ctx = await _ctx()
    result = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hello"))
    assert result.status == "error"
    assert result.error_code == "POST_SEO_FIELDS_REQUIRED"
    assert "slug" in result.error
    assert "meta_title" in result.error
    assert "category" in result.error


async def test_create_post_requires_seo_fields_reports_only_missing_ones():
    ctx = await _ctx()
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="Hello",
    ))
    assert result.status == "error"
    assert result.error_code == "POST_SEO_FIELDS_REQUIRED"
    assert "category" in result.error
    assert "requires category" in result.error


async def test_create_post_seo_fields_not_required_for_pages():
    ctx = await _ctx()
    ctx.http.mock_post(PAGES, _wp_post(pid=9), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="About", post_type="page",
    ))
    assert result.status == "success"
    assert result.data.post_type == "page"


# ─────────── happy path ───────────

async def test_create_post_happy_path_renders_blocks_and_defaults_draft():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    ctx.http.mock_post(SEO_BRIDGE, {
        "id": 42, "type": "post", "meta_title": SEO_OK["meta_title"], "meta_description": "",
        "canonical_url": "", "robots": [], "focus_keyword": "", "rank_math_active": True,
    }, 200)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", **SEO_OK,
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
        site_id="x-com", title="Hello", slug="hello", meta_title="Hello", category="News",
        excerpt="A short standalone summary.", featured_media_id=99,
    ))
    assert result.status == "success"
    assert result.data.category_resolved is True


async def test_create_post_creates_category_when_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [], 200)
    ctx.http.mock_post(CATEGORIES, {"id": 55, "name": "Brand New"}, 201)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="Hello", category="Brand New",
        excerpt="A short standalone summary.", featured_media_id=99,
    ))
    assert result.status == "success"
    assert result.data.category_resolved is True
    assert "created it" in result.summary


async def test_create_post_recovers_category_id_when_search_index_lags_a_just_created_term():
    """Task #1903: WordPress's own /wp/v2/categories search index can lag a
    just-created term. find_category_id's search finds nothing (as if the
    category doesn't exist yet), so create_post tries to auto-create it --
    but the category DOES already exist, so WordPress rejects the create
    with a 400 term_exists error. That error body carries the REAL term_id
    at data.term_id; create_post must use it instead of silently leaving
    the post uncategorised (category_resolved=False) with no visible error.
    Reproduced live on g4s.md."""
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [], 200)  # search index hasn't caught up yet
    ctx.http.mock_post(CATEGORIES, {
        "code": "term_exists", "message": "A term with the name provided already exists.",
        "data": {"term_id": 70},
    }, 400)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="Hello", category="Blog",
        excerpt="A short standalone summary.", featured_media_id=99,
    ))
    assert result.status == "success"
    assert result.data.category_resolved is True


async def test_create_post_forwards_lang_when_auto_creating_category():
    # Regression test: on a Polylang site, a category auto-created while
    # writing a post in language X must be created IN language X too --
    # otherwise Polylang silently files it under the site's default
    # language, and the next post written in language X can never find it
    # again via find_category_id(..., lang=X), even though the category
    # genuinely exists. Reproduced live on g4s.md: post #1760 (lang=ru)
    # auto-created "Blog" without a lang param; post #1762 (lang=ru) then
    # failed to find it ("could not be found or created") until a manual
    # update_post (which searches with no lang filter) resolved it.
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_get(CATEGORIES, [], 200)  # not found yet -> triggers auto-create
    ctx.http.mock_post(CATEGORIES, {"id": 55, "name": "Blog"}, 201)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="Hello", category="Blog",
        excerpt="A short standalone summary.", featured_media_id=99, lang="ru",
    ))
    assert result.status == "success"
    assert result.data.category_resolved is True
    category_create_calls = [c for c in seen if c[0] == CATEGORIES]
    assert category_create_calls, "expected a POST to /categories"
    assert category_create_calls[0][1].get("params") == {"lang": "ru"}, (
        "category auto-create must pass the same lang as the post, or Polylang "
        "files it under the default language and later lookups never find it"
    )


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
        site_id="x-com", title="Hello", status="future", **SEO_OK,
    ))
    assert result.status == "error"
    assert result.error_code == "POST_SCHEDULE_DATE_MISSING"


async def test_create_post_writes_seo_fields_via_update_seo_meta():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    ctx.http.mock_post(SEO_BRIDGE, {
        "id": 42, "type": "post", "meta_title": "SEO Title", "meta_description": "",
        "canonical_url": "", "robots": [], "focus_keyword": "", "rank_math_active": True,
    }, 200)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="SEO Title", category="News",
        excerpt="A short standalone summary.", featured_media_id=99,
    ))
    assert result.status == "success"
    assert "post was created, but SEO" not in result.summary


async def test_create_post_writes_canonical_url_via_update_seo_meta():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    ctx.http.mock_post(SEO_BRIDGE, {
        "id": 42, "type": "post", "meta_title": "SEO Title", "meta_description": "",
        "canonical_url": "https://x.com/canonical-target", "robots": [], "focus_keyword": "",
        "rank_math_active": True,
    }, 200)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="SEO Title", category="News",
        excerpt="A short standalone summary.", featured_media_id=99,
        canonical_url="https://x.com/canonical-target",
    ))
    assert result.status == "success"
    seo_calls = [c for c in seen if c[0] == SEO_BRIDGE]
    assert seo_calls, "expected a write to the SEO bridge"
    assert seo_calls[0][1]["json"]["canonical_url"] == "https://x.com/canonical-target"


async def test_create_post_reports_seo_failure_as_warning_not_error():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    ctx.http.mock_post(SEO_BRIDGE, {"code": "imperal_seo_forbidden", "message": "nope"}, 403)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", slug="hello", meta_title="SEO Title", category="News",
        excerpt="A short standalone summary.", featured_media_id=99,
    ))
    # Bridge failed -> core-meta fallback also has no route registered in this
    # mock, so the write is expected to fail; the post itself still succeeds.
    assert result.status == "success"
    assert "SEO" in result.summary


async def test_create_post_reports_http_failure():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, {"code": "rest_cannot_create"}, 403)
    result = await hp.create_post(ctx, CreatePostParams(site_id="x-com", title="Hello", **SEO_OK))
    assert result.status == "error"
    assert result.retryable is False


async def test_create_post_requires_connected_site():
    ctx = MockContext()
    result = await hp.create_post(ctx, CreatePostParams(site_id="missing", title="Hello", **SEO_OK))
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


# ─── body_markdown: the actual pipeline fix ───────────────────────────────
#
# Reproduces the real bug: an article's markdown [anchor](url) link, passed
# straight through instead of manually retyped into blocks, must become a
# real <a href> in the published content -- not plain "anchor (url)" text.

async def test_create_post_body_markdown_renders_real_links_not_plain_text():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    markdown = (
        "# Стоимость установки рекуператора тепла\n\n"
        "## Обслуживание\n\n"
        "Как часто менять фильтры — [читайте здесь](https://climtec.md/ru/filters/) "
        "и [шумит ли ночью](https://climtec.md/ru/noise/)."
    )
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", body_markdown=markdown, **SEO_OK,
    ))
    assert result.status == "success"
    post_call = next(c for c in seen if c[0] == POSTS)
    content = post_call[1]["json"]["content"]
    # site_id="x-com" connects https://x.com -- climtec.md is a DIFFERENT
    # domain, so both links are external and must be marked accordingly.
    assert '<a href="https://climtec.md/ru/filters/" target="_blank" rel="nofollow noopener noreferrer">читайте здесь</a>' in content
    assert '<a href="https://climtec.md/ru/noise/" target="_blank" rel="nofollow noopener noreferrer">шумит ли ночью</a>' in content
    # the raw markdown bracket/paren syntax must never leak through as plain text
    assert "(https://climtec.md/ru/filters/)" not in content
    assert "(https://climtec.md/ru/noise/)" not in content
    assert "<h2" in content  # ## heading survived, # title was dropped from content


async def test_create_post_explicit_blocks_win_over_body_markdown():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        blocks=[PostBlockInput(type="paragraph", text="Explicit wins")],
        body_markdown="Markdown text should be ignored.",
        **SEO_OK,
    ))
    assert result.status == "success"


async def test_update_post_body_markdown_renders_real_link():
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
        body_markdown="See [our guide](https://climtec.md/ru/guide/) for details.",
    ))
    assert result.status == "success"
    _, kwargs = seen[0]
    # climtec.md differs from the connected site's own domain (x.com) -- external
    assert '<a href="https://climtec.md/ru/guide/" target="_blank" rel="nofollow noopener noreferrer">our guide</a>' in kwargs["json"]["content"]
    assert "(https://climtec.md/ru/guide/)" not in kwargs["json"]["content"]


# ─── external-link policy: nofollow + new tab, automatically ─────────────
#
# The pipeline rule: every external link (different host than the connected
# site) gets target="_blank" rel="nofollow noopener noreferrer" without the
# article writer having to mark it by hand. A link back to the SAME site
# stays a normal, followed, same-tab link -- only external links are touched.

async def test_create_post_internal_link_stays_plain_no_nofollow():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        body_markdown="See our [other article](https://x.com/ru/other-article/) for more.",
        **SEO_OK,
    ))
    assert result.status == "success"
    post_call = next(c for c in seen if c[0] == POSTS)
    content = post_call[1]["json"]["content"]
    assert '<a href="https://x.com/ru/other-article/">other article</a>' in content
    assert "nofollow" not in content
    assert "target=" not in content


async def test_create_post_mixed_internal_and_external_links_marked_correctly():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    markdown = (
        "See our [internal guide](https://x.com/ru/guide/) and this "
        "[external source](https://en.wikipedia.org/wiki/Heat_recovery) too."
    )
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", body_markdown=markdown, **SEO_OK,
    ))
    assert result.status == "success"
    post_call = next(c for c in seen if c[0] == POSTS)
    content = post_call[1]["json"]["content"]
    assert '<a href="https://x.com/ru/guide/">internal guide</a>' in content
    assert '<a href="https://en.wikipedia.org/wiki/Heat_recovery" target="_blank" rel="nofollow noopener noreferrer">external source</a>' in content


async def test_create_post_www_prefix_still_counts_as_internal():
    ctx = await _ctx()
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        body_markdown="See [this page](https://www.x.com/ru/page/) for more.",
        **SEO_OK,
    ))
    assert result.status == "success"
    post_call = next(c for c in seen if c[0] == POSTS)
    content = post_call[1]["json"]["content"]
    assert '<a href="https://www.x.com/ru/page/">this page</a>' in content
    assert "nofollow" not in content


# ─────────── tags ───────────

async def test_create_post_resolves_tags_by_name():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_get(TAGS, [{"id": 3, "name": "Guides"}, {"id": 4, "name": "News"}], 200)
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", tags=["Guides", "News"], **SEO_OK,
    ))
    assert result.status == "success"
    assert result.data.tags_not_found == []
    _, kwargs = seen[0]
    assert sorted(kwargs["json"]["tags"]) == [3, 4]


async def test_create_post_reports_tags_not_found_without_failing():
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    ctx.http.mock_get(TAGS, [{"id": 3, "name": "Guides"}], 200)
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", tags=["Guides", "Nonexistent"], **SEO_OK,
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
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    seo_no_media = {k: v for k, v in SEO_OK.items() if k != "featured_media_id"}
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", featured_media_id=99, **seo_no_media,
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
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    seen = []
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs))
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(POSTS, _wp_post(), 201)
    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", **SEO_OK,
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


async def test_create_post_forwards_external_image_filename_to_the_bridge():
    """external_images' own `filename` (Media Hub's SEO/AEO-optimized slug)
    must reach the sideload request per-asset -- otherwise every image in
    a published post would keep the provider's raw generated name."""
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)
    captured = []

    async def handler(url, *, json=None, **kwargs):
        captured.append(dict(json or {}))
        return type("R", (), {"status_code": 201, "body": {
            "attachment_id": 101, "url": "https://x.com/wp-content/uploads/101.jpg",
            "width": 800, "height": 600, "attached_to": None, "featured_set": False,
        }})()

    ctx.http.post = handler
    ctx.http.mock_post(POSTS, _wp_post(), 201)

    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        slug="hello", meta_title="Hello — SEO Title", category="News",
        excerpt="A short standalone summary of the article.",
        external_images=[
            {"role": "featured", "source_url": "https://cdn.example/result_xyz.png",
             "filename": "heat-recovery-ventilator-featured"},
        ],
        blocks=[PostBlockInput(type="paragraph", text="Intro")],
    ))
    assert result.status == "success"
    sideload_calls = [c for c in captured if "source_url" in c]
    assert sideload_calls[0]["filename"] == "heat-recovery-ventilator-featured"


async def test_create_post_wires_up_media_hub_package_via_external_images():
    """The exact shape a Media Hub get_media_package call already returns
    (role/image_url/alt_text/caption) goes straight into external_images --
    no separate upload_media call, no manual attachment-id bookkeeping."""
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)

    def _sideload_response(role_to_id):
        async def handler(url, *, json=None, **kwargs):
            role = json.get("alt_text", "")
            aid = role_to_id.get(role, 1)
            return type("R", (), {"status_code": 201, "body": {
                "attachment_id": aid, "url": f"https://x.com/wp-content/uploads/{aid}.jpg",
                "width": 800, "height": 600, "attached_to": None, "featured_set": False,
            }})()
        return handler

    ctx.http.post = _sideload_response({
        "Featured alt": 101, "Inline one alt": 102,
    })
    ctx.http.mock_post(POSTS, _wp_post(), 201)

    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello",
        slug="hello", meta_title="Hello — SEO Title", category="News",
        excerpt="A short standalone summary of the article.",
        # NOTE: no featured_media_id -- it comes from external_images instead
        external_images=[
            {"role": "featured", "source_url": "https://cdn.example/featured.png",
             "alt_text": "Featured alt"},
            {"role": "inline_1", "source_url": "https://cdn.example/inline1.png",
             "alt_text": "Inline one alt", "caption": "Cap 1"},
        ],
        blocks=[
            PostBlockInput(type="paragraph", text="Intro"),
            PostBlockInput(type="image", image_role="inline_1"),
        ],
    ))
    assert result.status == "success"
    assert result.data.featured_media_set is True


async def test_create_post_reports_unmatched_external_image_role_as_warning():
    """An external image whose role matches no block must not vanish silently
    -- the caller (and the user) need to know it was uploaded but not placed."""
    ctx = await _ctx()
    ctx.http.mock_get(CATEGORIES, [{"id": 7, "name": "News"}], 200)

    async def handler(url, *, json=None, **kwargs):
        return type("R", (), {"status_code": 201, "body": {
            "attachment_id": 55, "url": "https://x.com/wp-content/uploads/55.jpg",
            "width": 800, "height": 600, "attached_to": None, "featured_set": False,
        }})()

    ctx.http.post = handler
    ctx.http.mock_post(POSTS, _wp_post(), 201)

    result = await hp.create_post(ctx, CreatePostParams(
        site_id="x-com", title="Hello", **SEO_OK,
        external_images=[
            {"role": "inline_1", "source_url": "https://cdn.example/orphan.png"},
        ],
        blocks=[PostBlockInput(type="paragraph", text="Intro")],
    ))
    assert result.status == "success"
    assert "inline_1" in result.summary
    assert "not inserted" in result.summary

