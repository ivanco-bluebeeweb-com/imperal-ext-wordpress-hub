"""Contract tests for Group K blocks/patterns introspection: handlers_blocks.py.

Native WordPress REST (`GET /wp/v2/blocks`, `GET /wp/v2/block-patterns/patterns`)
-- shipped in WP core since 5.0 / 6.0 respectively, so no Bridge or SSH needed.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_blocks as hb
import storage
from models import SiteIdParams

BASE = "https://blog.test"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


# ─────────── list_reusable_blocks ───────────

async def test_list_reusable_blocks_reads_native_rest():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/blocks", [
        {
            "id": 42, "slug": "footer-cta", "status": "publish",
            "title": {"raw": "Footer CTA"},
            "wp_pattern_sync_status": "",
        },
        {
            "id": 43, "slug": "hero-banner", "status": "draft",
            "title": {"raw": "Hero Banner"},
            "wp_pattern_sync_status": "unsynced",
        },
    ], 200)
    result = await hb.list_reusable_blocks(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    footer = next(i for i in result.data.items if i.id == "42")
    assert footer.title == "Footer CTA"
    assert footer.status == "publish"
    # WP core's own wp_pattern_sync_status meta is "" for a fully-synced block --
    # normalized to the explicit "synced" so the field is self-explanatory.
    assert footer.sync_status == "synced"
    hero = next(i for i in result.data.items if i.id == "43")
    assert hero.sync_status == "unsynced"


async def test_list_reusable_blocks_empty_site():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/blocks", [], 200)
    result = await hb.list_reusable_blocks(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.items == []


async def test_list_reusable_blocks_surfaces_hard_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/blocks", {"code": "error"}, 500)
    result = await hb.list_reusable_blocks(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.retryable is True


async def test_list_reusable_blocks_requires_connected_site():
    ctx = MockContext()
    result = await hb.list_reusable_blocks(ctx, SiteIdParams(site_id="nope"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_list_reusable_blocks_requires_credential():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": BASE, "username": "admin", "status": "connected",
    })
    result = await hb.list_reusable_blocks(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "SITE_CREDENTIAL_MISSING"


# ─────────── list_block_patterns ───────────

async def test_list_block_patterns_reads_native_rest():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/block-patterns/patterns", [
        {
            "name": "core/query-standard-posts",
            "title": "Standard",
            "categories": ["query"],
            "keywords": ["posts"],
            "block_types": ["core/query"],
            "source": "core",
        },
        {
            "name": "my-theme/hero",
            "title": "Hero",
            "categories": ["featured"],
            "keywords": [],
            "block_types": [],
            "source": "theme",
        },
    ], 200)
    result = await hb.list_block_patterns(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    core = next(i for i in result.data.items if i.name == "core/query-standard-posts")
    assert core.title == "Standard"
    assert core.categories == ["query"]
    assert core.source == "core"
    theme = next(i for i in result.data.items if i.name == "my-theme/hero")
    assert theme.source == "theme"


async def test_list_block_patterns_empty_site():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/block-patterns/patterns", [], 200)
    result = await hb.list_block_patterns(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.items == []


async def test_list_block_patterns_surfaces_hard_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/block-patterns/patterns", {"code": "error"}, 500)
    result = await hb.list_block_patterns(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.retryable is True


async def test_list_block_patterns_requires_connected_site():
    ctx = MockContext()
    result = await hb.list_block_patterns(ctx, SiteIdParams(site_id="nope"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"
