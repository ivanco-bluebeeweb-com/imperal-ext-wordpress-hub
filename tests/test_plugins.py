"""Contract tests for list_plugins (handlers_read.py) -- Bridge-first,
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
from models import SiteIdParams

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


async def test_list_plugins_requires_connected_site():
    result = await hr.list_plugins(MockContext(), SiteIdParams(site_id="ghost"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


# ─────────── via Bridge (no SSH needed) ───────────

async def test_list_plugins_via_bridge_needs_no_ssh():
    """The Bridge answers and NO SSH credential is stored at all -- proves
    the whole operation genuinely needs no shell access."""
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/maintenance/list-plugins", {
        "plugins": [
            {"name": "woocommerce/woocommerce.php", "title": "WooCommerce", "status": "active",
             "version": "9.0.0", "update": "available", "update_version": "9.1.0"},
            {"name": "akismet/akismet.php", "title": "Akismet", "status": "inactive",
             "version": "5.3", "update": "none", "update_version": ""},
        ],
    }, 200)
    result = await hr.list_plugins(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "success"
    assert [(item.title, item.status, item.version, item.update_available) for item in result.data.items] == [
        ("WooCommerce", "active", "9.0.0", "9.1.0"),
        ("Akismet", "inactive", "5.3", ""),
    ]
    assert "1 update(s) available" in result.summary


async def test_list_plugins_via_bridge_empty_list():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/maintenance/list-plugins", {"plugins": []}, 200)
    result = await hr.list_plugins(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.items == []
    assert "0 plugin(s)" in result.summary


# ─────────── SSH fallback (Bridge missing) ───────────

async def test_list_plugins_falls_back_to_ssh_when_bridge_missing(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/list-plugins")

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


async def test_list_plugins_surfaces_ssh_failure_without_success(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/maintenance/list-plugins")

    async def fake_list_plugins(_credential):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "list_plugins", fake_list_plugins)
    result = await hr.list_plugins(ctx, SiteIdParams(site_id="x-com"))

    assert result.status == "error"
    assert "SSH connection failed" in result.error


# ─────────── neither Bridge nor SSH ───────────

async def test_list_plugins_neither_bridge_nor_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/maintenance/list-plugins")
    result = await hr.list_plugins(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"
