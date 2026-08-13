"""Contract tests for Group F security/hardening diagnostics: handlers_security.py."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_security as hsec
import storage
from models import ListAdminUsersParams, SiteIdParams

BASE = "https://blog.test"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


# ─────────── get_php_info ───────────

async def test_get_php_info_reads_bridge_data():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/php-info", {
        "php_version": "8.2.10",
        "extensions": ["curl", "mbstring", "gd"],
        "memory_limit": "256M",
        "max_execution_time": "300",
        "upload_max_filesize": "64M",
        "post_max_size": "64M",
    })
    result = await hsec.get_php_info(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.php_version == "8.2.10"
    assert "gd" in result.data.extensions
    assert result.data.memory_limit == "256M"
    assert result.data.source == "bridge"


async def test_get_php_info_reads_environment_fields():
    """Server software, opcache, database engine/version, max_input_vars — the
    fields this adds on top of the original PHP-only payload, for the
    WHM-style Server tab in the panel."""
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/php-info", {
        "php_version": "8.2.10",
        "extensions": ["curl", "mbstring"],
        "memory_limit": "256M",
        "max_execution_time": "300",
        "upload_max_filesize": "64M",
        "post_max_size": "64M",
        "max_input_vars": "3000",
        "server_software": "nginx/1.24.0",
        "wp_version": "6.7",
        "opcache_enabled": True,
        "opcache_hit_rate": "98.4%",
        "db_version": "8.0.35",
        "db_server_info": "8.0.35-0ubuntu0.22.04.1",
        "db_size_mb": 42.7,
    })
    result = await hsec.get_php_info(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    d = result.data
    assert d.max_input_vars == "3000"
    assert d.server_software == "nginx/1.24.0"
    assert d.wp_version == "6.7"
    assert d.opcache_enabled is True
    assert d.opcache_hit_rate == "98.4%"
    assert d.db_version == "8.0.35"
    assert d.db_server_info == "8.0.35-0ubuntu0.22.04.1"
    assert d.db_size_mb == "42.7"


async def test_get_php_info_bridge_missing_is_clear_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/php-info", {"code": "rest_no_route"}, status=404)
    result = await hsec.get_php_info(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "SECURITY_BRIDGE_MISSING"


# ─────────── check_debug_mode ───────────

async def test_check_debug_mode_off_in_production():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/debug-mode", {
        "wp_debug": False, "wp_debug_log": False, "wp_debug_display": False,
    })
    result = await hsec.check_debug_mode(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.wp_debug is False
    assert "off" in result.summary.lower()


async def test_check_debug_mode_flags_display_risk():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/debug-mode", {
        "wp_debug": True, "wp_debug_log": True, "wp_debug_display": True,
    })
    result = await hsec.check_debug_mode(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.wp_debug is True
    assert result.data.wp_debug_display is True
    assert "DISPLAYED" in result.summary


# ─────────── check_file_permissions ───────────

async def test_check_file_permissions_reads_bridge_data():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/file-permissions", {
        "wp_config_exists": True, "wp_config_permissions": "0644", "wp_content_permissions": "0755",
    })
    result = await hsec.check_file_permissions(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.wp_config_exists is True
    assert result.data.wp_config_permissions == "0644"
    assert result.data.wp_content_permissions == "0755"


async def test_check_file_permissions_bridge_missing_is_clear_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/security/file-permissions", {"code": "rest_no_route"}, status=404)
    result = await hsec.check_file_permissions(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "SECURITY_BRIDGE_MISSING"


# ─────────── list_admin_users ───────────

async def test_list_admin_users_filters_by_role_via_native_rest():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users", [
        {"id": 1, "name": "Admin One", "roles": ["administrator"], "registered_date": "2020-01-01T00:00:00"},
    ])
    result = await hsec.list_admin_users(ctx, ListAdminUsersParams(site_id="blog-test", limit=20))
    assert result.status == "success"
    assert len(result.data.items) == 1
    assert result.data.items[0].role == "administrator"


async def test_list_admin_users_empty_is_still_success():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users", [])
    result = await hsec.list_admin_users(ctx, ListAdminUsersParams(site_id="blog-test", limit=20))
    assert result.status == "success"
    assert result.data.items == []
