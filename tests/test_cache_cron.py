"""Contract tests for transients, object cache, and cron introspection:
handlers_cache_cron.py.

Bridge-first, SSH-fallback -- same shape as tests/test_logs.py. Each
function is tested three ways: (1) the Bridge answers and NO SSH credential
is stored at all, proving the operation genuinely needs no shell; (2) the
Bridge is missing (404) and SSH is configured, the classic fallback; (3)
neither is available, a clear actionable error.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_cache_cron as hcc
import storage
from models import CronEventActionParams, DeleteTransientParams, SiteIdParams

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
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/cache{path}", {"code": "rest_no_route"}, 404)
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/cache{path}", {"code": "rest_no_route"}, 404)


# ─────────── list_transients ───────────

async def test_list_transients_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/cache/transients", {
        "transients": [{"name": "_transient_foo", "value": "bar", "expiration": "2026-08-11 12:00:00 GMT"}],
    }, 200)
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data) == 1
    assert result.data[0].name == "_transient_foo"


async def test_list_transients_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/transients")

    async def fake_list_transients(cred):
        return [{"name": "_transient_foo", "value": "bar", "expiration": "1234567890"}], None

    monkeypatch.setattr(hcc.wp_cli, "list_transients", fake_list_transients)
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data) == 1
    assert result.data[0].name == "_transient_foo"


async def test_list_transients_surfaces_ssh_error(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/transients")

    async def fake_list_transients(_cred):
        return None, "SSH connection failed"

    monkeypatch.setattr(hcc.wp_cli, "list_transients", fake_list_transients)
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert "SSH connection failed" in result.error


async def test_list_transients_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/transients")
    result = await hcc.list_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


# ─────────── delete_transient ───────────

async def test_delete_transient_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/cache/transients/delete", {
        "name": "_transient_foo", "deleted": True,
    }, 200)
    result = await hcc.delete_transient(ctx, DeleteTransientParams(site_id="x-com", name="_transient_foo"))
    assert result.status == "success"
    assert "deleted" in result.data.output


async def test_delete_transient_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/transients/delete")

    async def fake_delete_transient(cred, name):
        return f"Deleted '{name}'.", None

    monkeypatch.setattr(hcc.wp_cli, "delete_transient", fake_delete_transient)
    result = await hcc.delete_transient(ctx, DeleteTransientParams(site_id="x-com", name="_transient_foo"))
    assert result.status == "success"
    assert "_transient_foo" in result.data.output


async def test_delete_transient_rejects_unsafe_name():
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/transients/delete")
    result = await hcc.delete_transient(ctx, DeleteTransientParams(site_id="x-com", name="foo; rm -rf /"))
    assert result.status == "error"


# ─────────── flush_all_transients ───────────

async def test_flush_all_transients_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/cache/transients/flush-all", {
        "deleted_count": 12,
    }, 200)
    result = await hcc.flush_all_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert "12" in result.data.output


async def test_flush_all_transients_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/transients/flush-all")

    async def fake_flush(cred):
        return "Success: All transients deleted.", None

    monkeypatch.setattr(hcc.wp_cli, "flush_all_transients", fake_flush)
    result = await hcc.flush_all_transients(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


# ─────────── get_object_cache_status ───────────

async def test_get_object_cache_status_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/cache/object-cache-status", {
        "cache_type": "redis",
    }, 200)
    result = await hcc.get_object_cache_status(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cache_type == "redis"


async def test_get_object_cache_status_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/object-cache-status")

    async def fake_get_cache_type(cred):
        return "redis", None

    monkeypatch.setattr(hcc.wp_cli, "get_cache_type", fake_get_cache_type)
    result = await hcc.get_object_cache_status(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.cache_type == "redis"


# ─────────── flush_object_cache ───────────

async def test_flush_object_cache_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/cache/object-cache/flush", {
        "flushed": True,
    }, 200)
    result = await hcc.flush_object_cache(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.output == "flushed"


async def test_flush_object_cache_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/object-cache/flush")

    async def fake_flush_object_cache(cred):
        return "Success: The cache was flushed.", None

    monkeypatch.setattr(hcc.wp_cli, "flush_object_cache", fake_flush_object_cache)
    result = await hcc.flush_object_cache(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


# ─────────── list_cron_events ───────────

async def test_list_cron_events_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/cache/cron/events", {
        "events": [{"hook": "wp_version_check", "next_run_gmt": "2026-08-11 12:00:00",
                    "next_run_relative": "1 hour", "recurrence": "twicedaily"}],
    }, 200)
    result = await hcc.list_cron_events(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].hook == "wp_version_check"


async def test_list_cron_events_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/cron/events")

    async def fake_list_cron_events(cred):
        return [{"hook": "wp_version_check", "next_run_gmt": "2026-08-11 12:00:00",
                  "next_run_relative": "1 hour", "recurrence": "twicedaily"}], None

    monkeypatch.setattr(hcc.wp_cli, "list_cron_events", fake_list_cron_events)
    result = await hcc.list_cron_events(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].hook == "wp_version_check"


# ─────────── run_cron_event ───────────

async def test_run_cron_event_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/cache/cron/events/run", {
        "hook": "wp_version_check", "ran": 1,
    }, 200)
    result = await hcc.run_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="wp_version_check"))
    assert result.status == "success"
    assert "1" in result.data.output


async def test_run_cron_event_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/cron/events/run")

    async def fake_run_cron_event(cred, hook):
        return f"Executed the cron event '{hook}'.", None

    monkeypatch.setattr(hcc.wp_cli, "run_cron_event", fake_run_cron_event)
    result = await hcc.run_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="wp_version_check"))
    assert result.status == "success"
    assert "wp_version_check" in result.data.output


async def test_run_cron_event_rejects_unsafe_hook():
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/cron/events/run")
    result = await hcc.run_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="foo; rm -rf /"))
    assert result.status == "error"


# ─────────── delete_cron_event ───────────

async def test_delete_cron_event_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/cache/cron/events/delete", {
        "hook": "stuck_hook", "deleted": True,
    }, 200)
    result = await hcc.delete_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="stuck_hook"))
    assert result.status == "success"
    assert result.data.output == "deleted"


async def test_delete_cron_event_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/cron/events/delete")

    async def fake_delete_cron_event(cred, hook):
        return f"Deleted the cron event '{hook}'.", None

    monkeypatch.setattr(hcc.wp_cli, "delete_cron_event", fake_delete_cron_event)
    result = await hcc.delete_cron_event(ctx, CronEventActionParams(site_id="x-com", hook="stuck_hook"))
    assert result.status == "success"


# ─────────── list_cron_schedules ───────────

async def test_list_cron_schedules_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/imperal/v1/cache/cron/schedules", {
        "schedules": [{"name": "hourly", "display": "Once Hourly", "interval": 3600}],
    }, 200)
    result = await hcc.list_cron_schedules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].name == "hourly"
    assert result.data[0].interval == 3600


async def test_list_cron_schedules_falls_back_to_ssh_when_no_bridge(monkeypatch):
    ctx = await _ctx_with_ssh()
    _bridge_404(ctx, "/cron/schedules")

    async def fake_list_cron_schedules(cred):
        return [{"name": "hourly", "display": "Once Hourly", "interval": 3600}], None

    monkeypatch.setattr(hcc.wp_cli, "list_cron_schedules", fake_list_cron_schedules)
    result = await hcc.list_cron_schedules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].name == "hourly"


async def test_list_cron_schedules_requires_bridge_or_ssh():
    ctx = await _ctx()
    _bridge_404(ctx, "/cron/schedules")
    result = await hcc.list_cron_schedules(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"
