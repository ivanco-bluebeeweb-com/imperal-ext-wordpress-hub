"""Contract tests for log tools: handlers_logs.py.

Bridge-first, SSH-fallback -- same shape as tests/test_database.py. Each
function is tested three ways: (1) the Bridge answers and NO SSH credential
is stored at all, proving the operation genuinely needs no shell; (2) the
Bridge is missing (404) and SSH is configured, the classic fallback; (3)
neither is available, a clear actionable error.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_logs as hlogs
import storage
from models import SiteIdParams, TailLogParams

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
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/logs{path}", {"code": "rest_no_route"}, 404)
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/logs{path}", {"code": "rest_no_route"}, 404)


# ─────────── tail_debug_log ───────────

async def test_tail_debug_log_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/logs/debug-log", {
        "path": "/var/www/html/wp-content/debug.log", "exists": True,
        "lines": ["PHP Warning: something", "PHP Notice: else"],
    }, 200)
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com", lines=50))
    assert result.status == "success"
    assert result.data.exists is True
    assert len(result.data.lines) == 2


async def test_tail_debug_log_via_bridge_honestly_reports_missing_file():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/logs/debug-log", {
        "path": "/var/www/html/wp-content/debug.log", "exists": False, "lines": [],
    }, 200)
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is False
    assert result.data.lines == []


async def test_tail_debug_log_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/debug-log")

    async def fake_tail_debug_log(cred, lines=100):
        return {"path": "/var/www/html/wp-content/debug.log", "exists": True,
                "lines": ["PHP Warning: something", "PHP Notice: else"]}, None

    monkeypatch.setattr(hlogs.wp_cli, "tail_debug_log", fake_tail_debug_log)
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com", lines=50))
    assert result.status == "success"
    assert result.data.exists is True
    assert len(result.data.lines) == 2


async def test_tail_debug_log_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/debug-log")
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


# ─────────── clear_debug_log ───────────

async def test_clear_debug_log_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/logs/debug-log/clear", {
        "path": "/var/www/html/wp-content/debug.log", "cleared": True,
    }, 200)
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cleared is True


async def test_clear_debug_log_via_bridge_honest_when_nothing_to_clear():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/logs/debug-log/clear", {
        "path": "/var/www/html/wp-content/debug.log", "cleared": False,
        "note": "No debug.log file exists to clear.",
    }, 200)
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cleared is False


async def test_clear_debug_log_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/debug-log/clear")

    async def fake_clear_debug_log(cred):
        return {"path": "/var/www/html/wp-content/debug.log", "cleared": True}, None

    monkeypatch.setattr(hlogs.wp_cli, "clear_debug_log", fake_clear_debug_log)
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cleared is True


async def test_clear_debug_log_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/debug-log/clear")
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


# ─────────── tail_php_error_log ───────────

async def test_tail_php_error_log_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/logs/php-error-log", {
        "path": "/var/log/php/error.log", "exists": True,
        "lines": ["PHP Fatal error: something"],
    }, 200)
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is True
    assert len(result.data.lines) == 1


async def test_tail_php_error_log_via_bridge_honest_when_no_path_configured():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/logs/php-error-log", {
        "path": "", "exists": False, "lines": [],
        "note": "PHP has no error_log path configured (likely logging to the web "
                "server's own error log, outside our reach).",
    }, 200)
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is False
    assert result.data.path == ""
    assert "no error_log" in result.data.note.lower() or "no error_log" in result.summary.lower()


async def test_tail_php_error_log_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/php-error-log")

    async def fake_tail_php_error_log(cred, lines=100):
        return {"path": "/var/log/php/error.log", "exists": True,
                "lines": ["PHP Fatal error: something"]}, None

    monkeypatch.setattr(hlogs.wp_cli, "tail_php_error_log", fake_tail_php_error_log)
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is True
    assert len(result.data.lines) == 1


async def test_tail_php_error_log_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/php-error-log")
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"
