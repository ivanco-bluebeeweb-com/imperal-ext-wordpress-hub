"""Contract tests for SSH/WP-CLI transients, object cache, and cron
introspection: handlers_cache_cron.py."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_cache_cron as hcc
import storage
from models import CronEventActionParams, DeleteTransientParams, SiteIdParams


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


# ─────────── transients ───────────

async def test_list_transients_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_list_transients_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_transients(cred):
        return [{"name": "_transient_foo", "value": "bar", "expiration": "1234567890"}], None

    monkeypatch.setattr(hcc.wp_cli, "list_transients", fake_list_transients)
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data) == 1
    assert result.data[0].name == "_transient_foo"


async def test_list_transients_surfaces_ssh_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_transients(_cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hcc.wp_cli, "list_transients", fake_list_transients)
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert "SSH connection failed" in result.error


async def test_delete_transient_rejects_unsafe_name():
    ctx = await _ssh_ctx()
    result = await hcc.delete_transient(ctx, DeleteTransientParams(site_id="x-com", name="foo; rm -rf /"))
    assert result.status == "error"


async def test_delete_transient_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_delete_transient(cred, name):
        return f"Deleted '{name}'.", None

    monkeypatch.setattr(hcc.wp_cli, "delete_transient", fake_delete_transient)
    result = await hcc.delete_transient(ctx, DeleteTransientParams(site_id="x-com", name="_transient_foo"))
    assert result.status == "success"
    assert "_transient_foo" in result.data.output


async def test_flush_all_transients_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_flush(cred):
        return "Success: All transients deleted.", None

    monkeypatch.setattr(hcc.wp_cli, "flush_all_transients", fake_flush)
    result = await hcc.flush_all_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


# ─────────── object cache ───────────

async def test_get_object_cache_status_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_get_cache_type(cred):
        return "redis", None

    monkeypatch.setattr(hcc.wp_cli, "get_cache_type", fake_get_cache_type)
    result = await hcc.get_object_cache_status(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cache_type == "redis"


async def test_flush_object_cache_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_flush_object_cache(cred):
        return "Success: The cache was flushed.", None

    monkeypatch.setattr(hcc.wp_cli, "flush_object_cache", fake_flush_object_cache)
    result = await hcc.flush_object_cache(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


# ─────────── cron ───────────

async def test_list_cron_events_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_cron_events(cred):
        return [{"hook": "wp_version_check", "next_run_gmt": "2026-08-11 12:00:00",
                  "next_run_relative": "1 hour", "recurrence": "twicedaily"}], None

    monkeypatch.setattr(hcc.wp_cli, "list_cron_events", fake_list_cron_events)
    result = await hcc.list_cron_events(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].hook == "wp_version_check"


async def test_run_cron_event_rejects_unsafe_hook():
    ctx = await _ssh_ctx()
    result = await hcc.run_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="foo; rm -rf /"))
    assert result.status == "error"


async def test_run_cron_event_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_run_cron_event(cred, hook):
        return f"Executed the cron event '{hook}'.", None

    monkeypatch.setattr(hcc.wp_cli, "run_cron_event", fake_run_cron_event)
    result = await hcc.run_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="wp_version_check"))
    assert result.status == "success"
    assert "wp_version_check" in result.data.output


async def test_delete_cron_event_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_delete_cron_event(cred, hook):
        return f"Deleted the cron event '{hook}'.", None

    monkeypatch.setattr(hcc.wp_cli, "delete_cron_event", fake_delete_cron_event)
    result = await hcc.delete_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="stuck_hook"))
    assert result.status == "success"


async def test_list_cron_schedules_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_cron_schedules(cred):
        return [{"name": "hourly", "display": "Once Hourly", "interval": 3600}], None

    monkeypatch.setattr(hcc.wp_cli, "list_cron_schedules", fake_list_cron_schedules)
    result = await hcc.list_cron_schedules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].name == "hourly"
    assert result.data[0].interval == 3600
