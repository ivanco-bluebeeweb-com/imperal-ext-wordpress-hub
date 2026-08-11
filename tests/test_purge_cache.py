from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_read as hr
import storage
from models import PurgeCacheParams


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


def _plugins(active_slugs):
    return [{"name": slug, "status": "active", "version": "1.0", "update": "none", "update_version": ""}
            for slug in active_slugs]


async def test_purge_cache_rejects_invalid_scope():
    result = await hr.purge_cache(MockContext(), PurgeCacheParams(site_id="x-com", scope="everything"))
    assert result.status == "error"
    assert "scope" in result.error.lower()


async def test_purge_cache_requires_ssh():
    result = await hr.purge_cache(MockContext(), PurgeCacheParams(site_id="x-com"))
    assert result.status == "error"
    assert "SSH" in result.error


async def test_purge_cache_refuses_silently_when_no_known_cache_plugin_is_active(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return _plugins(["akismet"]), None

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))

    assert result.status == "error"
    assert "No supported cache plugin" in result.error


async def test_purge_cache_ignores_an_inactive_litespeed_install(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return [{"name": "litespeed-cache", "status": "inactive", "version": "1.0",
                 "update": "none", "update_version": ""}], None

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))

    assert result.status == "error"
    assert "No supported cache plugin" in result.error


async def test_purge_cache_runs_litespeed_purge_when_active(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return _plugins(["litespeed-cache"]), None

    calls = {}

    async def fake_purge(cred, scope):
        calls["cred"] = cred
        calls["scope"] = scope
        return "Purged all caches.", None

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    monkeypatch.setattr(hr.wp_cli, "purge_litespeed_cache", fake_purge)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com", scope="front"))

    assert result.status == "success"
    assert result.data.cache_plugin == "litespeed-cache"
    assert result.data.scope == "front"
    assert result.data.output == "Purged all caches."
    assert calls["scope"] == "front"
    assert calls["cred"]["host"] == "ssh.x.com"


async def test_purge_cache_surfaces_the_ssh_error_without_claiming_success(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return _plugins(["litespeed-cache"]), None

    async def fake_purge(_cred, _scope):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    monkeypatch.setattr(hr.wp_cli, "purge_litespeed_cache", fake_purge)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))

    assert result.status == "error"
    assert "SSH connection failed" in result.error


async def test_purge_cache_runs_w3tc_flush_when_active(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return _plugins(["w3-total-cache"]), None

    async def fake_purge(cred):
        return "Flushed all caches.", None

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    monkeypatch.setattr(hr.wp_cli, "purge_w3tc_cache", fake_purge)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))

    assert result.status == "success"
    assert result.data.cache_plugin == "w3-total-cache"
    assert result.data.output == "Flushed all caches."


async def test_purge_cache_prefers_litespeed_when_both_active(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return _plugins(["litespeed-cache", "w3-total-cache"]), None

    async def fake_ls_purge(cred, scope):
        return "Purged LiteSpeed.", None

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    monkeypatch.setattr(hr.wp_cli, "purge_litespeed_cache", fake_ls_purge)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))

    assert result.status == "success"
    assert result.data.cache_plugin == "litespeed-cache"


async def test_purge_cache_surfaces_w3tc_ssh_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_cred):
        return _plugins(["w3-total-cache"]), None

    async def fake_purge(_cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    monkeypatch.setattr(hr.wp_cli, "purge_w3tc_cache", fake_purge)
    result = await hr.purge_cache(ctx, PurgeCacheParams(site_id="x-com"))

    assert result.status == "error"
    assert "SSH connection failed" in result.error
