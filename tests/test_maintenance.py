"""Contract tests for SSH/WP-CLI site maintenance: update_plugin, update_core,
run_wp_cron."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_maintenance as hm
import storage
from models import RunWpCronParams, UpdateCoreParams, UpdatePluginParams


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


async def test_update_plugin_requires_connected_site():
    result = await hm.update_plugin(MockContext(), UpdatePluginParams(site_id="ghost", slug="akismet"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_update_plugin_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_update_plugin_rejects_unsafe_slug():
    """Exercises the REAL wp_cli.update_plugin validation (no monkeypatch) --
    a slug with shell metacharacters must never reach the ssh command line."""
    ctx = await _ssh_ctx()
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet; rm -rf /"))
    assert result.status == "error"
    assert "slug" in result.error.lower()


async def test_update_plugin_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    calls = {}

    async def fake_update_plugin(cred, slug):
        calls["cred"] = cred
        calls["slug"] = slug
        return {"raw": '[{"name":"akismet","status":"Updated"}]'}, None

    monkeypatch.setattr(hm.wp_cli, "update_plugin", fake_update_plugin)
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))

    assert result.status == "success"
    assert result.data.slug == "akismet"
    assert "akismet" in result.data.output
    assert calls["slug"] == "akismet"
    assert calls["cred"]["host"] == "ssh.x.com"


async def test_update_plugin_surfaces_ssh_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_update_plugin(_cred, _slug):
        return None, "SSH connection failed"

    monkeypatch.setattr(hm.wp_cli, "update_plugin", fake_update_plugin)
    result = await hm.update_plugin(ctx, UpdatePluginParams(site_id="x-com", slug="akismet"))
    assert result.status == "error"
    assert "SSH connection failed" in result.error


async def test_update_core_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_update_core_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_update_core(cred):
        return {"raw": "Success: WordPress updated successfully."}, None

    monkeypatch.setattr(hm.wp_cli, "update_core", fake_update_core)
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))

    assert result.status == "success"
    assert "updated successfully" in result.data.output


async def test_update_core_surfaces_ssh_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_update_core(_cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hm.wp_cli, "update_core", fake_update_core)
    result = await hm.update_core(ctx, UpdateCoreParams(site_id="x-com"))
    assert result.status == "error"
    assert "SSH connection failed" in result.error


async def test_run_wp_cron_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_run_wp_cron_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_run_wp_cron(cred):
        return "Executed 3 events.", None

    monkeypatch.setattr(hm.wp_cli, "run_wp_cron", fake_run_wp_cron)
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))

    assert result.status == "success"
    assert "Executed 3 events." in result.data.output


async def test_run_wp_cron_surfaces_ssh_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_run_wp_cron(_cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hm.wp_cli, "run_wp_cron", fake_run_wp_cron)
    result = await hm.run_wp_cron(ctx, RunWpCronParams(site_id="x-com"))
    assert result.status == "error"
    assert "SSH connection failed" in result.error
