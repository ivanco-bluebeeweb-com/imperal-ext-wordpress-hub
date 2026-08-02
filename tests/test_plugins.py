from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_read as hr
import storage
from models import SiteIdParams


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


async def test_list_plugins_requires_ssh():
    result = await hr.list_plugins(MockContext(), SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert "SSH" in result.error


async def test_list_plugins_maps_status_version_and_available_update(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(credential):
        assert credential["host"] == "ssh.x.com"
        return [
            {"name": "woocommerce", "status": "active", "version": "9.0.0",
             "update": "available", "update_version": "9.1.0"},
            {"name": "akismet", "status": "inactive", "version": "5.3",
             "update": "none", "update_version": ""},
        ], None

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    result = await hr.list_plugins(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "success"
    assert [(item.title, item.status, item.version, item.update_available) for item in result.data.items] == [
        ("woocommerce", "active", "9.0.0", "9.1.0"),
        ("akismet", "inactive", "5.3", ""),
    ]
    assert "1 update(s) available" in result.summary


async def test_list_plugins_exposes_ssh_failure_without_success(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_plugins(_credential):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    result = await hr.list_plugins(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "error"
    assert "SSH connection failed" in result.error
