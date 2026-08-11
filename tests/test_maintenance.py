"""Contract tests for site maintenance: update_plugin, update_core,
run_wp_cron (handlers_maintenance.py).

Bridge-first, SSH-fallback -- same shape as tests/test_cache_cron.py and
tests/test_database.py. Each function is tested three ways: (1) the Bridge
answers and NO SSH credential is stored at all, proving the operation
genuinely needs no shell; (2) the Bridge is missing (404) and SSH is
configured, the classic fallback; (3) neither is available, a clear
actionable error. The unsafe-slug/unsafe-hook rejection test exercises the
REAL wp_cli validation (no monkeypatch) on the SSH fallback path.
"""
import re

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_maintenance as hm
import storage
from models import RunWpCronParams, UpdateCoreParams, UpdatePluginParams

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


async def _ssh_ctx():
    """Back-compat alias for the unsafe-input rejection test below."""
    return await _ctx_with_ssh()


def _bridge_404(ctx, path):
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1{path}", {"code": "rest_no_route"}, 404)
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1{path}", {"code": "rest_no_route"}, 404)


# ─────────── site/credential guard ───────────

async def test_update_plugin_requires_connected_site():
    result = await hm.update_plugin(MockContext(), UpdatePluginParams(site_id="ghost", slug="akismet"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_update_plugin_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/maintenance/update-plugin")
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_update_plugin_rejects_unsafe_slug():
    """Exercises the REAL wp_cli.update_plugin validation (no monkeypatch) --
    a slug with shell metacharacters must never reach the ssh command line."""
    ctx = await _ssh_ctx()
    _bridge_404(ctx, "/maintenance/update-plugin")
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet; rm -rf /"))
    assert result.status == "error"
    assert re.search(r"invalid|slug", result.error, re.I)


# ─────────── update_plugin ───────────

async def test_update_plugin_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/update-plugin", {
        "slug": "akismet", "version": "5.3", "updated": True,
    }, 200)
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))
    assert result.status == "success"
    assert result.data.slug == "akismet"
    assert "5.3" in result.data.output


async def test_update_plugin_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/update-plugin")

    async def fake_update_plugin(cred, slug):
        return {"raw": "Success: Updated 1 of 1 plugins."}, None

    monkeypatch.setattr(hm.wp_cli, "update_plugin", fake_update_plugin)
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))
    assert result.status == "success"
    assert result.data.slug == "akismet"
    assert "Success" in result.data.output


async def test_update_plugin_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/update-plugin")

    async def fake_update_plugin(cred, slug):
        return None, "SSH connection failed"

    monkeypatch.setattr(hm.wp_cli, "update_plugin", fake_update_plugin)
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"


# ─────────── update_core ───────────

async def test_update_core_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/maintenance/update-core")
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_update_core_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/update-core", {
        "updated": True, "version": "6.7",
    }, 200)
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "success"
    assert "6.7" in result.data.output


async def test_update_core_via_bridge_already_latest():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/update-core", {
        "updated": False, "version": "6.7", "message": "WordPress core is already at the latest version.",
    }, 200)
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "success"
    assert "already" in result.data.output.lower()


async def test_update_core_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/update-core")

    async def fake_update_core(cred):
        return {"raw": "Success: WordPress updated successfully."}, None

    monkeypatch.setattr(hm.wp_cli, "update_core", fake_update_core)
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "success"
    assert "Success" in result.data.output


async def test_update_core_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/update-core")

    async def fake_update_core(cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hm.wp_cli, "update_core", fake_update_core)
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"


# ─────────── run_wp_cron ───────────

async def test_run_wp_cron_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/maintenance/run-due-cron")
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_run_wp_cron_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/run-due-cron", {
        "ran": ["wp_version_check", "wp_scheduled_delete"], "ran_count": 2,
    }, 200)
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))
    assert result.status == "success"
    assert "2" in result.data.output


async def test_run_wp_cron_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/run-due-cron")

    async def fake_run_wp_cron(cred):
        return "Executed a total of 2 crons.", None

    monkeypatch.setattr(hm.wp_cli, "run_wp_cron", fake_run_wp_cron)
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))
    assert result.status == "success"
    assert "Executed" in result.data.output


async def test_run_wp_cron_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/run-due-cron")

    async def fake_run_wp_cron(cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hm.wp_cli, "run_wp_cron", fake_run_wp_cron)
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"
