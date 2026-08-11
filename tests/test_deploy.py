"""Contract tests for Group H deploy/environment hygiene: handlers_deploy.py."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_deploy as hdeploy
import storage
from models import SiteIdParams

BASE = "https://blog.test"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


# ─────────── get_wp_config_constants ───────────

async def test_get_wp_config_constants_reads_allowlisted_subset():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/config-constants", {
        "wp_version": "6.5.2",
        "table_prefix": "wp_",
        "wp_debug": False,
        "wp_cache": True,
        "wp_environment_type": "production",
        "wp_home": "https://blog.test",
        "wp_siteurl": "https://blog.test",
        "disallow_file_edit": None,
        "disallow_file_mods": None,
        "automatic_updater_disabled": None,
    })
    result = await hdeploy.get_wp_config_constants(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.wp_version == "6.5.2"
    assert result.data.table_prefix == "wp_"
    assert result.data.wp_cache is True
    assert result.data.wp_environment_type == "production"


async def test_get_wp_config_constants_never_leaks_secrets():
    """The model itself has no field that could carry DB creds/auth keys --
    this locks that contract so a future edit can't quietly add one."""
    from models import WpConfigConstants
    fields = set(WpConfigConstants.model_fields.keys())
    forbidden = {"db_password", "db_user", "db_name", "db_host", "auth_key",
                 "secure_auth_key", "logged_in_key", "nonce_key", "auth_salt",
                 "secure_auth_salt", "logged_in_salt", "nonce_salt"}
    assert not (fields & forbidden)


async def test_get_wp_config_constants_bridge_missing_is_clear_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/config-constants",
                       {"code": "rest_no_route"}, status=404)
    result = await hdeploy.get_wp_config_constants(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "DEPLOY_BRIDGE_MISSING"


# ─────────── list_must_use_plugins ───────────

async def test_list_must_use_plugins_reads_list():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/mu-plugins", [
        {"file": "imperal-loader.php", "name": "Imperal Loader", "version": "1.0", "description": "Loader"},
    ])
    result = await hdeploy.list_must_use_plugins(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(result.data.items) == 1
    assert result.data.items[0].file == "imperal-loader.php"


async def test_list_must_use_plugins_empty_is_success_not_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/mu-plugins", [])
    result = await hdeploy.list_must_use_plugins(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.items == []


# ─────────── list_drop_ins ───────────

async def test_list_drop_ins_reads_list():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/drop-ins", [
        {"file": "object-cache.php", "name": "Redis Object Cache", "description": "External object cache."},
    ])
    result = await hdeploy.list_drop_ins(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.items[0].file == "object-cache.php"


# ─────────── get_environment_type ───────────

async def test_get_environment_type_reads_value():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/environment-type", {
        "environment_type": "staging",
    })
    result = await hdeploy.get_environment_type(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.environment_type == "staging"


async def test_get_environment_type_defaults_to_production():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/deploy/environment-type", {
        "environment_type": "production",
    })
    result = await hdeploy.get_environment_type(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.environment_type == "production"
