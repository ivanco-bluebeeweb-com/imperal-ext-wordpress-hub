"""Contract tests for SSH/WP-CLI log tools: handlers_logs.py."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_logs as hlogs
import storage
from models import SiteIdParams, TailLogParams


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


# ─────────── tail_debug_log ───────────

async def test_tail_debug_log_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_tail_debug_log_reads_existing_file(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_tail_debug_log(cred, lines=100):
        return {"path": "/var/www/html/wp-content/debug.log", "exists": True,
                "lines": ["PHP Warning: something", "PHP Notice: else"]}, None

    monkeypatch.setattr(hlogs.wp_cli, "tail_debug_log", fake_tail_debug_log)
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com", lines=50))
    assert result.status == "success"
    assert result.data.exists is True
    assert len(result.data.lines) == 2


async def test_tail_debug_log_honestly_reports_missing_file(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_tail_debug_log(cred, lines=100):
        return {"path": "/var/www/html/wp-content/debug.log", "exists": False, "lines": []}, None

    monkeypatch.setattr(hlogs.wp_cli, "tail_debug_log", fake_tail_debug_log)
    result = await hlogs.tail_debug_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is False
    assert result.data.lines == []


# ─────────── clear_debug_log ───────────

async def test_clear_debug_log_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_clear_debug_log_truncates_existing_file(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_clear_debug_log(cred):
        return {"path": "/var/www/html/wp-content/debug.log", "cleared": True}, None

    monkeypatch.setattr(hlogs.wp_cli, "clear_debug_log", fake_clear_debug_log)
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cleared is True


async def test_clear_debug_log_honest_when_nothing_to_clear(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_clear_debug_log(cred):
        return {"path": "/var/www/html/wp-content/debug.log", "cleared": False,
                "note": "No debug.log file exists to clear."}, None

    monkeypatch.setattr(hlogs.wp_cli, "clear_debug_log", fake_clear_debug_log)
    result = await hlogs.clear_debug_log(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cleared is False


# ─────────── tail_php_error_log ───────────

async def test_tail_php_error_log_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_tail_php_error_log_reads_existing_file(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_tail_php_error_log(cred, lines=100):
        return {"path": "/var/log/php/error.log", "exists": True,
                "lines": ["PHP Fatal error: something"]}, None

    monkeypatch.setattr(hlogs.wp_cli, "tail_php_error_log", fake_tail_php_error_log)
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is True
    assert len(result.data.lines) == 1


async def test_tail_php_error_log_honest_when_no_path_configured(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_tail_php_error_log(cred, lines=100):
        return {"path": "", "exists": False, "lines": [],
                "note": "PHP has no error_log path configured (likely logging to the web server's own error log, outside WP-CLI's reach)."}, None

    monkeypatch.setattr(hlogs.wp_cli, "tail_php_error_log", fake_tail_php_error_log)
    result = await hlogs.tail_php_error_log(ctx, TailLogParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.exists is False
    assert result.data.path == ""
    assert "no error_log" in result.data.note.lower() or "no error_log" in result.summary.lower()
