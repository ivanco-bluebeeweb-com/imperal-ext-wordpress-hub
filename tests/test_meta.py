"""Contract tests for generic custom-field meta via Imperal Bridge SECTION 9:
post/user/term meta, allowlisted wp_options, ACF field discovery.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_meta as hm
import storage
from models import (
    AcfFieldsParams,
    DeletePostMetaParams,
    DeleteTermMetaParams,
    DeleteUserMetaParams,
    GetOptionParams,
    GetPostMetaParams,
    GetTermMetaParams,
    GetUserMetaParams,
    UpdateOptionParams,
    UpdatePostMetaParams,
    UpdateTermMetaParams,
    UpdateUserMetaParams,
)

BRIDGE = "https://blog.test/wp-json/imperal/v1"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


# ─────────── post meta ───────────

async def test_get_post_meta_returns_dict():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/postmeta/7", {"post_id": 7, "meta": {"color": "blue"}})
    result = await hm.get_post_meta(ctx, GetPostMetaParams(site_id="blog-test", post_id=7))
    assert result.status == "success"
    assert result.data.meta == {"color": "blue"}


async def test_get_post_meta_bridge_missing():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/postmeta/7", {"code": "rest_no_route"}, 404)
    result = await hm.get_post_meta(ctx, GetPostMetaParams(site_id="blog-test", post_id=7))
    assert result.status == "error"
    assert result.error_code == "BRIDGE_NOT_INSTALLED"


async def test_get_post_meta_site_not_connected():
    ctx = MockContext()
    result = await hm.get_post_meta(ctx, GetPostMetaParams(site_id="nope", post_id=1))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_update_post_meta_sets_keys():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/postmeta/7", {"post_id": 7, "updated": ["color"]})
    result = await hm.update_post_meta(
        ctx, UpdatePostMetaParams(site_id="blog-test", post_id=7, meta={"color": "red"}))
    assert result.status == "success"
    assert result.data.updated == ["color"]


async def test_delete_post_meta_removes_key():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/postmeta/7/color", {"deleted": True})
    result = await hm.delete_post_meta(
        ctx, DeletePostMetaParams(site_id="blog-test", post_id=7, key="color"))
    assert result.status == "success"
    assert result.data.deleted == "color"


# ─────────── user meta ───────────

async def test_get_user_meta_returns_dict():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/usermeta/3", {"user_id": 3, "meta": {"phone": "555"}})
    result = await hm.get_user_meta(ctx, GetUserMetaParams(site_id="blog-test", user_id=3))
    assert result.status == "success"
    assert result.data.meta == {"phone": "555"}


async def test_update_user_meta_sets_keys():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/usermeta/3", {"user_id": 3, "updated": ["phone"]})
    result = await hm.update_user_meta(
        ctx, UpdateUserMetaParams(site_id="blog-test", user_id=3, meta={"phone": "555"}))
    assert result.status == "success"
    assert result.data.updated == ["phone"]


async def test_delete_user_meta_removes_key():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/usermeta/3/phone", {"deleted": True})
    result = await hm.delete_user_meta(
        ctx, DeleteUserMetaParams(site_id="blog-test", user_id=3, key="phone"))
    assert result.status == "success"
    assert result.data.deleted == "phone"


# ─────────── term meta ───────────

async def test_get_term_meta_returns_dict():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/termmeta/9", {"term_id": 9, "meta": {"icon": "star"}})
    result = await hm.get_term_meta(ctx, GetTermMetaParams(site_id="blog-test", term_id=9))
    assert result.status == "success"
    assert result.data.meta == {"icon": "star"}


async def test_update_term_meta_sets_keys():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/termmeta/9", {"term_id": 9, "updated": ["icon"]})
    result = await hm.update_term_meta(
        ctx, UpdateTermMetaParams(site_id="blog-test", term_id=9, meta={"icon": "star"}))
    assert result.status == "success"
    assert result.data.updated == ["icon"]


async def test_delete_term_meta_removes_key():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/termmeta/9/icon", {"deleted": True})
    result = await hm.delete_term_meta(
        ctx, DeleteTermMetaParams(site_id="blog-test", term_id=9, key="icon"))
    assert result.status == "success"
    assert result.data.deleted == "icon"


# ─────────── wp_options (allowlist enforced server-side) ───────────

async def test_get_option_returns_value():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/option/blogname", {"value": "My Blog", "exists": True})
    result = await hm.get_option(ctx, GetOptionParams(site_id="blog-test", name="blogname"))
    assert result.status == "success"
    assert result.data.value == "My Blog"


async def test_get_option_rejected_when_not_allowlisted():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/option/siteurl", {"code": "imperal_meta_option_not_allowed"}, 403)
    result = await hm.get_option(ctx, GetOptionParams(site_id="blog-test", name="siteurl"))
    assert result.status == "error"
    assert result.error_code == "OPTION_NOT_ALLOWED"


async def test_update_option_writes_value():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/option/blogname", {"value": "New Name", "exists": True})
    result = await hm.update_option(
        ctx, UpdateOptionParams(site_id="blog-test", name="blogname", value="New Name"))
    assert result.status == "success"
    assert result.data.value == "New Name"


async def test_update_option_rejected_when_not_allowlisted():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/option/siteurl", {"code": "imperal_meta_option_not_allowed"}, 403)
    result = await hm.update_option(
        ctx, UpdateOptionParams(site_id="blog-test", name="siteurl", value="https://evil.test"))
    assert result.status == "error"
    assert result.error_code == "OPTION_NOT_ALLOWED"


async def test_update_option_rejected_when_value_unsafe():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/option/blogname", {"code": "imperal_meta_option_unsafe_value"}, 400)
    result = await hm.update_option(
        ctx, UpdateOptionParams(site_id="blog-test", name="blogname", value='O:8:"stdClass":0:{}'))
    assert result.status == "error"
    assert result.error_code == "OPTION_VALUE_UNSAFE"


# ─────────── ACF field discovery ───────────

async def test_list_acf_fields_returns_groups():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/acf-fields", {
        "post_type": "post", "field_groups": [{"key": "group_1", "title": "Extra Info"}],
    })
    result = await hm.list_acf_fields(ctx, AcfFieldsParams(site_id="blog-test", post_type="post"))
    assert result.status == "success"
    assert len(result.data.field_groups) == 1


async def test_list_acf_fields_not_active():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BRIDGE}/acf-fields", {"code": "imperal_meta_acf_not_active"}, 404)
    result = await hm.list_acf_fields(ctx, AcfFieldsParams(site_id="blog-test", post_type="post"))
    assert result.status == "error"
    assert result.error_code == "ACF_NOT_ACTIVE"
