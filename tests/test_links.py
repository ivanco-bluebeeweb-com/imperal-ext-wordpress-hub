"""Tests for handlers_links.extract_links — internal/external link + anchor
text audit over article content (either passed directly, or read live from
a connected site).
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_links as hl
import storage
from models import ExtractLinksParams

POSTS = "https://x.com/wp-json/wp/v2/posts"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_extract_links_classifies_internal_and_external():
    ctx = await _ctx()
    html = (
        '<p>See our <a href="https://x.com/servicii">services</a> and '
        '<a href="https://external.com/page">this external site</a>.</p>'
    )
    result = await hl.extract_links(ctx, ExtractLinksParams(
        content_html=html, site_id="x-com",
    ))
    assert result.status == "success"
    report = result.data
    assert report.total_links == 2
    assert report.internal_count == 1
    assert report.external_count == 1
    kinds = {l.href: l.link_type for l in report.links}
    assert kinds["https://x.com/servicii"] == "internal"
    assert kinds["https://external.com/page"] == "external"


async def test_extract_links_captures_anchor_text():
    ctx = await _ctx()
    html = '<a href="https://x.com/servicii">servicii de ventilare</a>'
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html=html, site_id="x-com"))
    assert result.data.links[0].anchor_text == "servicii de ventilare"


async def test_extract_links_flags_weak_anchor_text():
    ctx = await _ctx()
    html = '<a href="https://x.com/a">click here</a>'
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html=html, site_id="x-com"))
    assert result.data.links[0].weak_anchor is True
    assert result.data.weak_anchor_count == 1


async def test_extract_links_flags_missing_rel_on_external():
    ctx = await _ctx()
    html = '<a href="https://external.com/x">Detailed Report</a>'
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html=html, site_id="x-com"))
    link = result.data.links[0]
    assert link.link_type == "external"
    assert link.missing_rel_policy is True


async def test_extract_links_no_flag_when_rel_present():
    ctx = await _ctx()
    html = '<a href="https://external.com/x" rel="nofollow noopener">Detailed Report</a>'
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html=html, site_id="x-com"))
    assert result.data.links[0].missing_rel_policy is False


async def test_extract_links_ignores_anchor_only_hrefs():
    ctx = await _ctx()
    html = '<a href="#section-2">jump</a>'
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html=html, site_id="x-com"))
    assert result.data.total_links == 1
    assert result.data.links[0].link_type == "anchor"


async def test_extract_links_requires_content_or_post_id():
    ctx = await _ctx()
    result = await hl.extract_links(ctx, ExtractLinksParams(site_id="x-com"))
    assert result.status == "error"


async def test_extract_links_reads_live_post_when_post_id_given():
    ctx = await _ctx()
    ctx.http.mock_get(POSTS + "/42", {
        "id": 42, "content": {"rendered": '<a href="https://x.com/a">internal link</a>'},
    }, 200)
    result = await hl.extract_links(ctx, ExtractLinksParams(site_id="x-com", post_id=42))
    assert result.status == "success"
    assert result.data.internal_count == 1


async def test_extract_links_no_links_returns_empty_report():
    ctx = await _ctx()
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html="<p>No links here.</p>", site_id="x-com"))
    assert result.status == "success"
    assert result.data.total_links == 0


async def test_extract_links_warns_when_no_internal_links():
    ctx = await _ctx()
    html = '<a href="https://external.com/only">only external</a>'
    result = await hl.extract_links(ctx, ExtractLinksParams(content_html=html, site_id="x-com"))
    assert any("no internal links" in w for w in result.data.warnings)


# ─────────── check_sitemap_inclusion ───────────

from models import CheckSitemapParams

SITEMAP_INDEX = "https://x.com/sitemap_index.xml"
POST_SITEMAP = "https://x.com/post-sitemap.xml"
WP_SITEMAP = "https://x.com/wp-sitemap.xml"


async def test_check_sitemap_finds_url_directly_in_index():
    ctx = await _ctx()
    ctx.http.mock_get(SITEMAP_INDEX, (
        "<?xml version=\"1.0\"?><urlset>"
        "<url><loc>https://x.com/blog/hello-world</loc></url>"
        "</urlset>"
    ), 200)
    result = await hl.check_sitemap_inclusion(ctx, CheckSitemapParams(
        site_id="x-com", url="https://x.com/blog/hello-world",
    ))
    assert result.status == "success"
    assert result.data.found is True


async def test_check_sitemap_recurses_into_sub_sitemap():
    ctx = await _ctx()
    ctx.http.mock_get(SITEMAP_INDEX, (
        "<?xml version=\"1.0\"?><sitemapindex>"
        "<sitemap><loc>https://x.com/post-sitemap.xml</loc></sitemap>"
        "</sitemapindex>"
    ), 200)
    ctx.http.mock_get(POST_SITEMAP, (
        "<?xml version=\"1.0\"?><urlset>"
        "<url><loc>https://x.com/blog/hello-world</loc></url>"
        "</urlset>"
    ), 200)
    result = await hl.check_sitemap_inclusion(ctx, CheckSitemapParams(
        site_id="x-com", url="https://x.com/blog/hello-world",
    ))
    assert result.status == "success"
    assert result.data.found is True
    assert result.data.checked_sitemap_url == POST_SITEMAP


async def test_check_sitemap_falls_back_to_wp_core_sitemap():
    ctx = await _ctx()
    # sitemap_index.xml and sitemap.xml 404 (no SEO plugin) -> wp-sitemap.xml core fallback
    ctx.http.mock_get(WP_SITEMAP, (
        "<?xml version=\"1.0\"?><urlset>"
        "<url><loc>https://x.com/blog/hello-world</loc></url>"
        "</urlset>"
    ), 200)
    result = await hl.check_sitemap_inclusion(ctx, CheckSitemapParams(
        site_id="x-com", url="https://x.com/blog/hello-world",
    ))
    assert result.status == "success"
    assert result.data.found is True
    assert result.data.checked_sitemap_url == WP_SITEMAP


async def test_check_sitemap_reports_not_found_with_warning():
    ctx = await _ctx()
    ctx.http.mock_get(SITEMAP_INDEX, (
        "<?xml version=\"1.0\"?><urlset>"
        "<url><loc>https://x.com/blog/other-post</loc></url>"
        "</urlset>"
    ), 200)
    result = await hl.check_sitemap_inclusion(ctx, CheckSitemapParams(
        site_id="x-com", url="https://x.com/blog/hello-world",
    ))
    assert result.status == "success"
    assert result.data.found is False
    assert result.data.warnings


async def test_check_sitemap_unknown_site_errors():
    ctx = await _ctx()
    result = await hl.check_sitemap_inclusion(ctx, CheckSitemapParams(
        site_id="missing", url="https://x.com/blog/hello-world",
    ))
    assert result.status == "error"
