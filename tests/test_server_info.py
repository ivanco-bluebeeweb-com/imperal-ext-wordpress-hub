"""Tests for get_server_info's bridge-first, SSH-fallback behaviour.

Every fact this returns (WP/PHP version, plugin/theme/core updates, cron
count, DB size) is plain WordPress core data, so a site with the Imperal
Bridge plugin installed should get it with zero SSH involved. SSH stays a
fallback for sites that haven't updated the plugin yet.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_read as hr
import storage
from models import SiteIdParams

BRIDGE = "https://x.com/wp-json/imperal/v1/server/info"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _bridge_payload(**over):
    payload = {
        "wp_version": "6.5.2",
        "php_version": "8.2.10",
        "plugin_updates": 1,
        "plugin_updates_list": [
            {"title": "WooCommerce", "version": "9.0.0", "update_version": "9.1.0"},
        ],
        "theme_updates": 0,
        "theme_updates_list": [],
        "core_update": False,
        "core_update_version": "",
        "cron_count": 12,
        "db_size_mb": 42.5,
    }
    payload.update(over)
    return payload


async def test_get_server_info_via_bridge_needs_no_ssh():
    """No SSH credential stored at all -- the bridge response alone must be
    enough, proving this data never actually required a shell."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(), 200)

    result = await hr.get_server_info(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "success"
    assert result.data.wp_version == "6.5.2"
    assert result.data.php_version == "8.2.10"
    assert result.data.source == "bridge"
    assert "via Bridge" in result.summary

    record = await storage.get_site_record(ctx, "x-com")
    assert record["server_source"] == "bridge"
    assert record["wp_version"] == "6.5.2"


async def test_get_server_info_falls_back_to_ssh_when_bridge_missing(monkeypatch):
    """Bridge answers 404 (not installed) but SSH is configured -- must fall
    back transparently and still succeed, tagged source='ssh'."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy",
        "wp_path": "/var/www/html", "key": "test-key",
    })

    async def fake_get_server_info(_cred):
        return {
            "wp_version": "6.4.0", "php_version": "8.1.0",
            "plugin_updates": 0, "plugin_updates_list": [],
            "theme_updates": 0, "theme_updates_list": [],
            "core_update": False, "core_update_version": "",
            "cron_count": 3, "db_size_mb": "10",
        }

    monkeypatch.setattr(hr.wp_cli, "get_server_info", fake_get_server_info)
    result = await hr.get_server_info(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "success"
    assert result.data.wp_version == "6.4.0"
    assert result.data.source == "ssh"
    assert "via SSH" in result.summary


async def test_get_server_info_errors_when_neither_bridge_nor_ssh_available():
    """Bridge missing and no SSH configured -- must fail with a clear,
    actionable error instead of a bare SSH-only message."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)

    result = await hr.get_server_info(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "error"
    assert "Bridge" in result.error
    assert "SSH" in result.error


async def test_get_server_info_ssh_failure_after_bridge_missing_is_reported(monkeypatch):
    """Bridge missing, SSH configured but the SSH call itself fails -- must
    surface the SSH error, not silently succeed."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy",
        "wp_path": "/var/www/html", "key": "test-key",
    })

    async def fake_get_server_info(_cred):
        return {"error": "Permission denied (publickey)."}

    monkeypatch.setattr(hr.wp_cli, "get_server_info", fake_get_server_info)
    result = await hr.get_server_info(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "error"
    assert "Permission denied" in result.error
