"""Contract tests for Group P checksum verification tools."""
from imperal_sdk.testing import MockContext

import handlers_integrity as hi
import storage
from models import PluginChecksumParams, SiteIdParams


async def _ctx(with_ssh: bool = False):
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    if with_ssh:
        await storage.set_ssh_cred(ctx, "x-com", {
            "host": "ssh.x.com", "port": 22, "user": "deploy",
            "wp_path": "/var/www/html", "key": "test-key",
        })
    return ctx


async def test_verify_core_checksums_requires_known_site():
    result = await hi.verify_core_checksums(MockContext(), SiteIdParams(site_id="missing"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_verify_core_checksums_requires_ssh():
    result = await hi.verify_core_checksums(await _ctx(), SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_verify_core_checksums_returns_mismatch_as_result(monkeypatch):
    async def fake_verify(cred):
        assert cred["host"] == "ssh.x.com"
        return {"verified": False, "output": "Warning: File doesn't verify against checksum"}, None

    monkeypatch.setattr(hi.wp_cli, "verify_core_checksums", fake_verify)
    result = await hi.verify_core_checksums(await _ctx(True), SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.verified is False
    assert "doesn't verify" in result.data.output


async def test_verify_plugin_checksums_uses_explicit_plugin(monkeypatch):
    async def fake_verify(cred, plugin):
        assert plugin == "woocommerce"
        return {"verified": True, "output": "Success: Verified 2 checksums."}, None

    monkeypatch.setattr(hi.wp_cli, "verify_plugin_checksums", fake_verify)
    result = await hi.verify_plugin_checksums(
        await _ctx(True), PluginChecksumParams(site_id="x-com", plugin="woocommerce"))
    assert result.status == "success"
    assert result.data.target == "plugin:woocommerce"
    assert result.data.verified is True


async def test_verify_plugin_checksums_surfaces_wordpress_org_unavailability(monkeypatch):
    async def fake_verify(cred, plugin):
        return {"verified": False, "output": "Error: No checksum data found on WordPress.org."}, None

    monkeypatch.setattr(hi.wp_cli, "verify_plugin_checksums", fake_verify)
    result = await hi.verify_plugin_checksums(
        await _ctx(True), PluginChecksumParams(site_id="x-com", plugin="premium-plugin"))
    assert result.status == "success"
    assert result.data.verified is False
    assert "WordPress.org" in result.data.output
