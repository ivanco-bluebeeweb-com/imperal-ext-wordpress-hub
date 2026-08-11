"""Contract tests for Import / Export (WXR): export_wxr (Bridge-first,
SSH-fallback) and import_wxr (SSH-only) (handlers_import_export.py).

export_wxr follows the same three-way shape as test_rewrite.py. import_wxr
has no Bridge path at all -- it is tested for the site/SSH guards, the
successful SSH round-trip, and the plugin-not-active error message WP-CLI's
own `wp import` surfaces verbatim.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_import_export as hie
import storage
from models import ExportWxrParams, ImportWxrParams, SiteIdParams

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


# ─────────── export_wxr ───────────

async def test_export_wxr_requires_connected_site():
    result = await hie.export_wxr(MockContext(), ExportWxrParams(site_id="ghost"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_export_wxr_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/export/wxr")
    result = await hie.export_wxr(ctx, ExportWxrParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_export_wxr_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/export/wxr", {
        "xml": "<rss><channel></channel></rss>", "size_bytes": 32, "post_count": 0,
    }, 200)
    result = await hie.export_wxr(ctx, ExportWxrParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.size_bytes == 32


async def test_export_wxr_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/export/wxr")

    async def fake_export(cred, content, author, category, start_date, end_date, status):
        return {"xml": "<rss></rss>", "size_bytes": 12, "post_count": 3}, None

    monkeypatch.setattr(hie.wp_cli, "export_wxr", fake_export)
    result = await hie.export_wxr(ctx, ExportWxrParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.post_count == 3


async def test_export_wxr_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/export/wxr")

    async def fake_export(cred, content, author, category, start_date, end_date, status):
        return None, "SSH connection failed"

    monkeypatch.setattr(hie.wp_cli, "export_wxr", fake_export)
    result = await hie.export_wxr(ctx, ExportWxrParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"


async def test_export_wxr_prefers_post_type_over_content(monkeypatch):
    ctx = await _ctx()
    seen = {}

    async def fake_get(ctx_, base_url, username, pw, path, params=None):
        seen.update(params or {})
        return {"xml": "<rss></rss>", "size_bytes": 12, "post_count": 0}

    monkeypatch.setattr(hie, "_bridge_get", fake_get)
    result = await hie.export_wxr(ctx, ExportWxrParams(site_id="x-com", content="all", post_type="product"))
    assert result.status == "success"
    assert seen["content"] == "product"


# ─────────── import_wxr ───────────

async def test_import_wxr_requires_connected_site():
    result = await hie.import_wxr(MockContext(), ImportWxrParams(site_id="ghost", wxr_xml="<rss></rss>"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_import_wxr_requires_ssh():
    ctx = await _ctx()
    result = await hie.import_wxr(ctx, ImportWxrParams(site_id="x-com", wxr_xml="<rss></rss>"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_import_wxr_succeeds_over_ssh(monkeypatch):
    ctx = await _ctx_with_ssh()

    async def fake_import(cred, wxr_xml, authors, skip_attachments):
        return {"output": "Imported post as post_id #1\nImported post as post_id #2",
                "imported": 2, "skipped": 0}, None

    monkeypatch.setattr(hie.wp_cli, "import_wxr", fake_import)
    result = await hie.import_wxr(
        ctx, ImportWxrParams(site_id="x-com", wxr_xml="<rss><channel></channel></rss>"))
    assert result.status == "success"
    assert result.data.imported_count == 2
    assert result.data.skipped_count == 0


async def test_import_wxr_surfaces_plugin_not_active_as_non_retryable(monkeypatch):
    ctx = await _ctx_with_ssh()

    async def fake_import(cred, wxr_xml, authors, skip_attachments):
        return None, "WordPress Importer needs to be activated. Try 'wp plugin activate wordpress-importer'. Plugin not active."

    monkeypatch.setattr(hie.wp_cli, "import_wxr", fake_import)
    result = await hie.import_wxr(
        ctx, ImportWxrParams(site_id="x-com", wxr_xml="<rss><channel></channel></rss>"))
    assert result.status == "error"
    assert "not active" in result.error


async def test_import_wxr_surfaces_generic_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()

    async def fake_import(cred, wxr_xml, authors, skip_attachments):
        return None, "SSH connection failed"

    monkeypatch.setattr(hie.wp_cli, "import_wxr", fake_import)
    result = await hie.import_wxr(
        ctx, ImportWxrParams(site_id="x-com", wxr_xml="<rss><channel></channel></rss>"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"
