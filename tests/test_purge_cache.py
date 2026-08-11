"""Contract tests for purge_cache (handlers_read.py) -- Bridge-first,
SSH-fallback, same 3-way shape as tests/test_maintenance.py and
tests/test_install_plugin.py: (1) the Bridge answers and no SSH is stored,
proving no shell is needed; (2) the Bridge is missing (404) and SSH is
configured, the classic fallback; (3) neither is available, a clear
actionable error.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_read as hr
import storage
from models import PurgeCacheParams

BASE = "https://x.com"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def _ctx_with_ssh():
    ctx = await _ctx()
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


def _bridge_404(ctx, path):
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1{path}", {"code": "rest_no_route"}, 404)
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1{path}", {"code": "rest_no_route"}, 404)


def _plugins(active_slugs):
    return [{"name": slug, "status": "active", "version": "1.0", "update": "none", "update_version": ""}
            for slug in active_slugs]


async def test_purge_cache_rejects_invalid_scope():
    result = await hr.purge_cache(MockContext(), PurgeCacheParams(site_id="x-com", scope="everything"))
    assert result.status == "error"
    assert "scope" in result.error.lower()


async def test_purge_cache_requires_connected_site():
    result = await hr.purge_cache(MockContext(), PurgeCacheParams(site_id="ghost"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_purge_cache_via_bridge_needs_no_ssh():
    """The Bridge answers and NO SSH credential is stored at all -- proves
    the whole operation genuinely needs no shell access."""
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/purge-cache", {
        "purged": True, "scope": "all", "cache_plugin": "litespeed-cache",
    }, 200)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cache_plugin == "litespeed-cache"
    assert result.data.scope == "all"


async def test_purge_cache_via_bridge_front_scope():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/purge-cache", {
        "purged": True, "scope": "front", "cache_plugin": "w3-total-cache",
    }, 200)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com", scope="front"))
    assert result.status == "success"
    assert result.data.cache_plugin == "w3-total-cache"
    assert result.data.scope == "front"


async def test_purge_cache_bridge_falls_back_to_ssh_when_missing():
    """Bridge route 404s (plugin absent/outdated) but SSH is configured --
    falls back to the classic wp-cli path."""
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/purge-cache")

    async def fake_list_plugins(_cred):
        return _plugins(["litespeed-cache"]), None

    async def fake_purge(cred, scope):
        return "Purged LiteSpeed.", None

    import wp_cli
    orig_list, orig_purge = wp_cli.list_plugins, wp_cli.purge_litespeed_cache
    wp_cli.list_plugins = fake_list_plugins
    wp_cli.purge_litespeed_cache = fake_purge
    try:
        result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))
    finally:
        wp_cli.list_plugins, wp_cli.purge_litespeed_cache = orig_list, orig_purge
    assert result.status == "success"
    assert result.data.cache_plugin == "litespeed-cache"


async def test_purge_cache_ssh_fallback_no_active_cache_plugin():
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/purge-cache")

    async def fake_list_plugins(_cred):
        return _plugins(["some-other-plugin"]), None

    import wp_cli
    orig = wp_cli.list_plugins
    wp_cli.list_plugins = fake_list_plugins
    try:
        result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))
    finally:
        wp_cli.list_plugins = orig
    assert result.status == "error"
    assert "no supported cache plugin" in result.error.lower() or "cache plugin" in result.error.lower()


async def test_purge_cache_ssh_fallback_surfaces_purge_error():
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/purge-cache")

    async def fake_list_plugins(_cred):
        return _plugins(["w3-total-cache"]), None

    async def fake_purge(_cred):
        return None, "SSH connection failed"

    import wp_cli
    orig_list, orig_purge = wp_cli.list_plugins, wp_cli.purge_w3tc_cache
    wp_cli.list_plugins = fake_list_plugins
    wp_cli.purge_w3tc_cache = fake_purge
    try:
        result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))
    finally:
        wp_cli.list_plugins, wp_cli.purge_w3tc_cache = orig_list, orig_purge
    assert result.status == "error"
    assert "SSH connection failed" in result.error


async def test_purge_cache_neither_bridge_nor_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/maintenance/purge-cache")
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"
