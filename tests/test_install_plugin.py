from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_read as hr
import storage
from models import InstallPluginParams


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


async def test_install_plugin_requires_ssh():
    result = await hr.install_plugin(MockContext(), InstallPluginParams(site_id="x-com", source="imperal-media-bridge"))
    assert result.status == "error"
    assert "SSH" in result.error


async def test_install_plugin_requires_source():
    ctx = await _ssh_ctx()
    result = await hr.install_plugin(ctx, InstallPluginParams(site_id="x-com", source=""))
    assert result.status == "error"
    assert "source is required" in result.error


async def test_wp_cli_install_plugin_rejects_shell_metacharacters():
    result, error = await hr.wp_cli.install_plugin(
        {"host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key"},
        "foo; rm -rf /", True,
    )
    assert result is None
    assert error is not None


async def test_install_plugin_success_from_slug(monkeypatch):
    ctx = await _ssh_ctx()

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
    assert result.data.activated is True
    assert "active" in result.data.output
    assert "Installed plugin" in result.summary


async def test_install_plugin_success_from_zip_url_without_activation(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_install_plugin(credential, source, activate):
        assert source == "https://example.com/plugin.zip"
        assert activate is False
        return {"raw": "Plugin installed successfully."}, None

    monkeypatch.setattr(hr.wp_cli, "install_plugin", fake_install_plugin)
    result = await hr.install_plugin(
        ctx, InstallPluginParams(site_id="x-com", source="https://example.com/plugin.zip", activate=False)
    )

    assert result.status == "success"
    assert result.data.activated is False
    assert result.summary.endswith(".")
    assert "and activated" not in result.summary


async def test_install_plugin_surfaces_wp_cli_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_install_plugin(_cred, _source, _activate):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "install_plugin", fake_install_plugin)
    result = await hr.install_plugin(ctx, InstallPluginParams(site_id="x-com", source="imperal-media-bridge"))

    assert result.status == "error"
    assert "SSH connection failed" in result.error
