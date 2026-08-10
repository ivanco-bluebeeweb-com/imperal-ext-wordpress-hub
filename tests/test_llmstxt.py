"""Contract tests for Rank Math's llms.txt settings via Imperal Bridge SECTION 8.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_llmstxt as hlt
import storage
from models import LlmsTxtParams, UpdateLlmsTxtParams

BRIDGE = "https://blog.test/wp-json/imperal/v1/llmstxt"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


# ─────────── get_llms_txt_settings ───────────

async def test_get_llms_txt_settings_module_active():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {
        "module_active": True, "llms_txt_url": "https://blog.test/llms.txt",
        "post_types": ["post", "page"], "taxonomies": ["category"],
        "limit": 50, "extra_content": "## Notes\nSee our style guide.",
    })
    result = await hlt.get_llms_txt_settings(ctx, LlmsTxtParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.module_active is True
    assert result.data.post_types == ["post", "page"]
    assert result.data.limit == 50
    assert "llms.txt" in result.summary


async def test_get_llms_txt_settings_module_not_active():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {
        "module_active": False, "llms_txt_url": "https://blog.test/llms.txt",
        "post_types": [], "taxonomies": [], "limit": 100, "extra_content": "",
    })
    result = await hlt.get_llms_txt_settings(ctx, LlmsTxtParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.module_active is False
    assert "not active" in result.summary


async def test_get_llms_txt_settings_bridge_missing():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    result = await hlt.get_llms_txt_settings(ctx, LlmsTxtParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "LLMSTXT_BRIDGE_MISSING"
    assert "Imperal Bridge" in result.error


async def test_get_llms_txt_settings_site_not_connected():
    ctx = MockContext()
    result = await hlt.get_llms_txt_settings(ctx, LlmsTxtParams(site_id="nope"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


# ─────────── update_llms_txt_settings ───────────

async def test_update_llms_txt_settings_partial_update():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, {
        "module_active": False, "llms_txt_url": "https://blog.test/llms.txt",
        "post_types": ["post"], "taxonomies": [], "limit": 100, "extra_content": "",
        "updated": ["post_types"],
    })
    result = await hlt.update_llms_txt_settings(
        ctx, UpdateLlmsTxtParams(site_id="blog-test", post_types=["post"]))
    assert result.status == "success"
    assert result.data.post_types == ["post"]
    assert result.refresh_panels == ["center"]


async def test_update_llms_txt_settings_clears_extra_content():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, {
        "module_active": True, "llms_txt_url": "https://blog.test/llms.txt",
        "post_types": [], "taxonomies": [], "limit": 100, "extra_content": "",
        "updated": ["extra_content"],
    })
    result = await hlt.update_llms_txt_settings(
        ctx, UpdateLlmsTxtParams(site_id="blog-test", extra_content=""))
    assert result.status == "success"
    assert result.data.extra_content == ""


async def test_update_llms_txt_settings_no_fields_is_rejected_before_any_request():
    ctx = await _ctx()
    result = await hlt.update_llms_txt_settings(ctx, UpdateLlmsTxtParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "LLMSTXT_NO_FIELDS"


async def test_update_llms_txt_settings_invalid_limit_surfaces_wp_error():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, {
        "code": "imperal_llmstxt_invalid_limit", "message": "limit must be a positive integer.",
    }, 400)
    result = await hlt.update_llms_txt_settings(
        ctx, UpdateLlmsTxtParams(site_id="blog-test", limit=0))
    assert result.status == "error"
    assert result.error_code == "LLMSTXT_INVALID"


async def test_update_llms_txt_settings_bridge_missing():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, {"code": "rest_no_route"}, 404)
    result = await hlt.update_llms_txt_settings(
        ctx, UpdateLlmsTxtParams(site_id="blog-test", limit=10))
    assert result.status == "error"
    assert result.error_code == "LLMSTXT_BRIDGE_MISSING"
