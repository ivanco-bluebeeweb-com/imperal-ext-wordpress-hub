"""Contract tests for install_plugin (handlers_read.py) -- Bridge-first,
SSH-fallback, same 3-way shape as tests/test_maintenance.py: (1) the Bridge
answers and no SSH is stored, proving no shell is needed; (2) the Bridge is
missing (404) and SSH is configured, the classic fallback; (3) neither is
available, a clear actionable error. The unsafe-source rejection test
exercises the REAL wp_cli.install_plugin validation (no monkeypatch) on the
SSH fallback path.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_read as hr
import storage
from models import InstallPluginParams

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


async def test_install_plugin_requires_connected_site():
    result = await hr.install_plugin(MockContext(), InstallPluginParams(site_id="ghost", source="imperal-media-bridge"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_install_plugin_requires_source():
    ctx = await _ctx()
    result = await hr.install_plugin(ctx, InstallPluginParams(site_id="x-com", source=""))
    assert result.status == "error"
    assert "source is required" in result.error


async def test_install_plugin_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/maintenance/install-plugin")
    result = await hr.install_plugin(ctx, InstallPluginParams(site_id="x-com", source="imperal-media-bridge"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_wp_cli_install_plugin_rejects_shell_metacharacters():
    result, error = await hr.wp_cli.install_plugin(
        {"host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key"},
        "foo; rm -rf /", True,
    )
    assert result is None
    assert error is not None


# ─────────── via Bridge (no SSH needed) ───────────

async def test_install_plugin_via_bridge_from_slug():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/install-plugin", {
        "installed": True, "plugin": "imperal-media-bridge/imperal-media-bridge.php", "activated": True,
    }, 200)
    result = await hr.install_plugin(
        ctx, InstallPluginParams(site_id="x-com", source="imperal-media-bridge", activate=True)
    )
    assert result.status == "success"
    assert result.data.source == "imperal-media-bridge"
    assert result.data.activated is True


async def test_install_plugin_via_bridge_from_zip_url_without_activation():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/maintenance/install-plugin", {
        "installed": True, "plugin": "custom-plugin/custom-plugin.php", "activated": False,
    }, 200)
    result = await hr.install_plugin(
        ctx, InstallPluginParams(site_id="x-com", source="https://example.com/plugin.zip", activate=False)
    )
    assert result.status == "success"
    assert result.data.activated is False


# ─────────── SSH fallback (Bridge missing/404) ───────────

async def test_install_plugin_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/install-plugin")

    async def fake_install_plugin(credential, source, activate):
        assert credential["host"] == "ssh.x.com"
        assert source == "imperal-media-bridge"
        assert activate is True
        return {"raw": '{"name":"imperal-media-bridge","status":"active"}'}, None

    monkeypatch.setattr(hr.wp_cli, "install_plugin", fake_install_plugin)
    result = await hr.install_plugin(
        ctx, InstallPluginParams(site_id="x-com", source="imperal-media-bridge", activate=True)
    )
    assert result.status == "success"
    assert result.data.source == "imperal-media-bridge"


async def test_install_plugin_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/install-plugin")

    async def fake_install_plugin(_cred, _source, _activate):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "install_plugin", fake_install_plugin)
    result = await hr.install_plugin(ctx, InstallPluginParams(site_id="x-com", source="imperal-media-bridge"))
    assert result.status == "error"
    assert "SSH connection failed" in result.error
