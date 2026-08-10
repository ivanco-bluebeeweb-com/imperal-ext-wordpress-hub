"""Contract tests for Rank Math site-wide data via Imperal Bridge SECTION 7:
SEO score, robots.txt editor, sitemap module status, 404 Monitor log.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_rankmath as hrm
import storage
from models import (
    Delete404HitParams,
    GetSeoScoreParams,
    List404HitsParams,
    RobotsTxtParams,
    UpdateRobotsTxtParams,
)

BRIDGE = "https://shop.test/wp-json/imperal/v1/rankmath"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


# ─────────── get_seo_analysis_score ───────────

async def test_get_seo_analysis_score_returns_int():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/score/42", {"id": 42, "score": 87})
    result = await hrm.get_seo_analysis_score(ctx, GetSeoScoreParams(site_id="shop-test", post_id=42))
    assert result.status == "success"
    assert result.data.score == 87
    assert "87/100" in result.summary


async def test_get_seo_analysis_score_null_when_never_analyzed():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/score/42", {"id": 42, "score": None})
    result = await hrm.get_seo_analysis_score(ctx, GetSeoScoreParams(site_id="shop-test", post_id=42))
    assert result.status == "success"
    assert result.data.score is None
    assert "not been analyzed" in result.summary


async def test_get_seo_analysis_score_post_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/score/999", {"code": "imperal_rankmath_post_not_found"}, 404)
    result = await hrm.get_seo_analysis_score(ctx, GetSeoScoreParams(site_id="shop-test", post_id=999))
    assert result.status == "error"
    assert result.error_code == "POST_NOT_FOUND"


async def test_get_seo_analysis_score_bridge_missing():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/score/42", {"code": "rest_no_route"}, 404)
    result = await hrm.get_seo_analysis_score(ctx, GetSeoScoreParams(site_id="shop-test", post_id=42))
    assert result.status == "error"
    assert result.error_code == "RANKMATH_BRIDGE_MISSING"


# ─────────── get_robots_txt / update_robots_txt ───────────

async def test_get_robots_txt_active_override():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/robots-txt", {"content": "User-agent: *\nDisallow: /wp-admin/",
                                                "is_active": True, "site_is_public": True})
    result = await hrm.get_robots_txt(ctx, RobotsTxtParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.is_active is True
    assert "override is active" in result.summary


async def test_get_robots_txt_no_override():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/robots-txt", {"content": "", "is_active": False, "site_is_public": True})
    result = await hrm.get_robots_txt(ctx, RobotsTxtParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.is_active is False
    assert "default robots.txt" in result.summary


async def test_update_robots_txt_writes_content():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/robots-txt", {"content": "User-agent: *\nDisallow: /private/",
                                                 "is_active": True})
    result = await hrm.update_robots_txt(ctx, UpdateRobotsTxtParams(
        site_id="shop-test", content="User-agent: *\nDisallow: /private/"))
    assert result.status == "success"
    assert result.data.is_active is True
    assert result.refresh_panels == ["center"]


async def test_update_robots_txt_clear_reports_inactive():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/robots-txt", {"content": "", "is_active": False})
    result = await hrm.update_robots_txt(ctx, UpdateRobotsTxtParams(site_id="shop-test", content=""))
    assert result.status == "success"
    assert "cleared" in result.summary


# ─────────── get_sitemap_status ───────────

async def test_get_sitemap_status_active():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/sitemap-status",
                       {"module_active": True, "sitemap_url": "https://shop.test/sitemap_index.xml"})
    result = await hrm.get_sitemap_status(ctx, RobotsTxtParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.module_active is True
    assert "sitemap_index.xml" in result.summary


async def test_get_sitemap_status_inactive():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/sitemap-status", {"module_active": False, "sitemap_url": ""})
    result = await hrm.get_sitemap_status(ctx, RobotsTxtParams(site_id="shop-test"))
    assert result.status == "success"
    assert result.data.module_active is False
    assert "not active" in result.summary


# ─────────── list_404_hits / delete_404_hit ───────────

def _hit(hid=1, **over):
    data = {"id": hid, "uri": "/old-page/", "accessed": "2026-08-01 10:00:00",
            "times_accessed": 5, "referer": "https://google.com/", "user_agent": "Mozilla/5.0"}
    data.update(over)
    return data


async def test_list_404_hits_maps_fields():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/404-logs", [_hit(), _hit(hid=2, uri="/gone/")])
    result = await hrm.list_404_hits(ctx, List404HitsParams(site_id="shop-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert result.data.items[0].uri == "/old-page/"
    assert result.data.items[0].times_accessed == 5


async def test_list_404_hits_module_not_available():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/404-logs", {"code": "imperal_rankmath_404_not_available"}, 404)
    result = await hrm.list_404_hits(ctx, List404HitsParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "RANKMATH_MODULE_MISSING"


async def test_delete_404_hit_success():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/404-logs/7", {"deleted": True})
    result = await hrm.delete_404_hit(ctx, Delete404HitParams(site_id="shop-test", hit_id=7))
    assert result.status == "success"
    assert result.data.deleted is True
    assert result.refresh_panels == ["center"]


async def test_delete_404_hit_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/404-logs/999", {"code": "imperal_rankmath_404_not_found"}, 404)
    result = await hrm.delete_404_hit(ctx, Delete404HitParams(site_id="shop-test", hit_id=999))
    assert result.status == "error"
    assert result.error_code == "HIT_404_NOT_FOUND"


async def test_get_seo_analysis_score_site_not_connected():
    ctx = MockContext()
    result = await hrm.get_seo_analysis_score(ctx, GetSeoScoreParams(site_id="ghost", post_id=1))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"
