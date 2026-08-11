"""Contract tests for rewrite rules & permalinks: get_permalink_structure,
update_permalink_structure, flush_rewrite_rules, list_rewrite_rules
(handlers_rewrite.py).

Bridge-first, SSH-fallback -- same shape as tests/test_maintenance.py. Each
function is tested three ways: (1) the Bridge answers and NO SSH credential
is stored at all, proving the operation genuinely needs no shell; (2) the
Bridge is missing (404) and SSH is configured, the classic fallback; (3)
neither is available, a clear actionable error.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_rewrite as hr
import storage
from models import ListRewriteRulesParams, SiteIdParams, UpdatePermalinkStructureParams

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


# ─────────── site/credential guard ───────────

async def test_get_permalink_structure_requires_connected_site():
    result = await hr.get_permalink_structure(MockContext(), SiteIdParams(site_id="ghost"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_get_permalink_structure_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/rewrite/structure")
    result = await hr.get_permalink_structure(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


# ─────────── get_permalink_structure ───────────

async def test_get_permalink_structure_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/rewrite/structure", {
        "permalink_structure": "/%year%/%monthnum%/%postname%/",
        "category_base": "", "tag_base": "",
    }, 200)
    result = await hr.get_permalink_structure(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.permalink_structure == "/%year%/%monthnum%/%postname%/"


async def test_get_permalink_structure_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/structure")

    async def fake_get(cred):
        return {"permalink_structure": "/%postname%/", "category_base": "topics", "tag_base": "labels"}, None

    monkeypatch.setattr(hr.wp_cli, "get_permalink_structure", fake_get)
    result = await hr.get_permalink_structure(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.category_base == "topics"


async def test_get_permalink_structure_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/structure")

    async def fake_get(cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "get_permalink_structure", fake_get)
    result = await hr.get_permalink_structure(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"


# ─────────── update_permalink_structure ───────────

async def test_update_permalink_structure_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/rewrite/structure")
    result = await hr.update_permalink_structure(
        ctx, UpdatePermalinkStructureParams(site_id="x-com", permalink_structure="/%postname%/"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_update_permalink_structure_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/rewrite/structure", {
        "permalink_structure": "/%postname%/", "category_base": "", "tag_base": "",
    }, 200)
    result = await hr.update_permalink_structure(
        ctx, UpdatePermalinkStructureParams(site_id="x-com", permalink_structure="/%postname%/"))
    assert result.status == "success"
    assert result.data.permalink_structure == "/%postname%/"


async def test_update_permalink_structure_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/structure")

    async def fake_update(cred, permalink_structure, category_base, tag_base):
        return "Success: Rewrite structure set.", None

    monkeypatch.setattr(hr.wp_cli, "update_permalink_structure", fake_update)
    result = await hr.update_permalink_structure(
        ctx, UpdatePermalinkStructureParams(site_id="x-com", permalink_structure="/%postname%/", category_base="topics"))
    assert result.status == "success"
    assert result.data.permalink_structure == "/%postname%/"
    assert result.data.category_base == "topics"


async def test_update_permalink_structure_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/structure")

    async def fake_update(cred, permalink_structure, category_base, tag_base):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "update_permalink_structure", fake_update)
    result = await hr.update_permalink_structure(
        ctx, UpdatePermalinkStructureParams(site_id="x-com", permalink_structure="/%postname%/"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"


# ─────────── flush_rewrite_rules ───────────

async def test_flush_rewrite_rules_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/rewrite/flush")
    result = await hr.flush_rewrite_rules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_flush_rewrite_rules_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/rewrite/flush", {
        "flushed": True, "rule_count": 42,
    }, 200)
    result = await hr.flush_rewrite_rules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.rule_count == 42


async def test_flush_rewrite_rules_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/flush")

    async def fake_flush(cred):
        return "Success: Rewrite rules flushed.", None

    monkeypatch.setattr(hr.wp_cli, "flush_rewrite_rules", fake_flush)
    result = await hr.flush_rewrite_rules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.flushed is True


async def test_flush_rewrite_rules_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/flush")

    async def fake_flush(cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "flush_rewrite_rules", fake_flush)
    result = await hr.flush_rewrite_rules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"


# ─────────── list_rewrite_rules ───────────

async def test_list_rewrite_rules_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/rewrite/rules")
    result = await hr.list_rewrite_rules(ctx, ListRewriteRulesParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_list_rewrite_rules_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/rewrite/rules", {
        "rules": [
            {"match": "^wp-json/?$", "query": "index.php?rest_route=/"},
            {"match": "^category/(.+?)/?$", "query": "index.php?category_name=$matches[1]"},
        ],
    }, 200)
    result = await hr.list_rewrite_rules(ctx, ListRewriteRulesParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert result.data.items[0].match == "^wp-json/?$"


async def test_list_rewrite_rules_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/rules")

    async def fake_list(cred):
        return [{"match": "^wp-json/?$", "query": "index.php?rest_route=/"}], None

    monkeypatch.setattr(hr.wp_cli, "list_rewrite_rules", fake_list)
    result = await hr.list_rewrite_rules(ctx, ListRewriteRulesParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data.items) == 1


async def test_list_rewrite_rules_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/rewrite/rules")

    async def fake_list(cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hr.wp_cli, "list_rewrite_rules", fake_list)
    result = await hr.list_rewrite_rules(ctx, ListRewriteRulesParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error == "SSH connection failed"
