"""Contract tests for native plugin activation, theme inventory, and site settings."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_site_settings as hss
import storage
from models import SetPluginStatusParams, SiteIdParams, UpdateSiteSettingsParams

BASE = "https://blog.test/wp-json/wp/v2"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


def _plugin(plugin_id="hello-dolly/hello", **over):
    data = {"plugin": plugin_id, "name": "Hello Dolly", "version": "1.7.2",
            "status": "inactive", "description": {"raw": "A famous plugin."}}
    data.update(over)
    return data


def _theme(stylesheet="twentytwentyfour", **over):
    data = {"stylesheet": stylesheet, "name": {"rendered": "Twenty Twenty-Four"},
            "version": "1.0", "status": "active", "is_block_theme": True}
    data.update(over)
    return data


async def test_list_native_plugins_maps_status_and_counts_active():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/plugins", [_plugin(), _plugin(plugin_id="akismet/akismet", status="active")])
    result = await hss.list_native_plugins(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert "1 active" in result.summary


async def test_list_native_plugins_reports_missing_route_on_old_wordpress():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/plugins", {"code": "rest_no_route"}, 404)
    result = await hss.list_native_plugins(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "WP_ROUTE_NOT_FOUND"


async def test_activate_plugin_posts_status_active():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/plugins/hello-dolly/hello", _plugin(status="active"), 200)
    result = await hss.activate_plugin(ctx, SetPluginStatusParams(site_id="blog-test", plugin="hello-dolly/hello"))
    assert result.status == "success"
    assert result.data.status == "active"


async def test_deactivate_plugin_posts_status_inactive():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/plugins/hello-dolly/hello", _plugin(status="inactive"), 200)
    result = await hss.deactivate_plugin(ctx, SetPluginStatusParams(site_id="blog-test", plugin="hello-dolly/hello"))
    assert result.status == "success"
    assert result.data.status == "inactive"


async def test_list_themes_reports_active_theme_in_summary():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/themes", [_theme(), _theme(stylesheet="twentytwentythree", status="inactive")])
    result = await hss.list_themes(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert "Twenty Twenty-Four" in result.summary


async def test_get_site_settings_maps_fields():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/settings", {
        "title": "My Blog", "description": "Just my thoughts", "url": "https://blog.test",
        "timezone_string": "Europe/Chisinau", "date_format": "F j, Y", "time_format": "g:i a",
        "start_of_week": 1, "language": "en_US", "site_icon": 34,
    })
    result = await hss.get_site_settings(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.timezone_string == "Europe/Chisinau"
    assert result.data.site_icon == 34


async def test_update_site_settings_sends_only_given_fields():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/settings", {"title": "New Title", "description": "", "url": "", "timezone_string": "",
                                            "date_format": "", "time_format": "", "start_of_week": 0, "language": "", "site_icon": 0}, 200)
    result = await hss.update_site_settings(ctx, UpdateSiteSettingsParams(site_id="blog-test", title="New Title"))
    assert result.status == "success"


async def test_update_site_settings_accepts_native_site_icon_id():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/settings", {"title": "", "description": "", "url": "", "timezone_string": "",
                                            "date_format": "", "time_format": "", "start_of_week": 0, "language": "", "site_icon": 34}, 200)
    result = await hss.update_site_settings(ctx, UpdateSiteSettingsParams(site_id="blog-test", site_icon=34))
    assert result.status == "success"
    assert result.data.site_icon == 34


async def test_update_site_settings_rejects_empty_call():
    ctx = await _ctx()
    result = await hss.update_site_settings(ctx, UpdateSiteSettingsParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "NO_FIELDS_GIVEN"
