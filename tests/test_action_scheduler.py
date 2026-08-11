"""Contract tests for handlers_action_scheduler.py -- Action Scheduler
(WooCommerce's own background job queue). Bridge-only, no SSH fallback:
the site must have the Imperal Bridge plugin (2.12.0+) AND Action
Scheduler active (bundled inside WooCommerce or another plugin).
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_action_scheduler as has
import storage
from models import GetScheduledActionParams, ListScheduledActionsParams, SiteIdParams

BASE = "https://x.com"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _mock_get(ctx, path, body, status=200):
    ctx.http.mock_get(f"{BASE}{path}", body, status)


def _mock_post(ctx, path, body, status=200):
    ctx.http.mock_post(f"{BASE}{path}", body, status)


ACTION_UNAVAILABLE_BODY = {
    "code": "imperal_action_scheduler_unavailable",
    "message": "Action Scheduler is not active on this site (it ships inside WooCommerce and some other plugins).",
}


# ─────────── list_scheduled_actions ───────────

async def test_list_scheduled_actions_requires_connected_site():
    result = await has.list_scheduled_actions(MockContext(), ListScheduledActionsParams(site_id="ghost"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_list_scheduled_actions_success():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/actions", {
        "actions": [
            {"id": 1, "hook": "woocommerce_deliver_webhook_async", "status": "failed", "group": "webhooks", "scheduled": 1700000000, "args": []},
            {"id": 2, "hook": "woocommerce_scheduled_sales", "status": "pending", "group": "", "scheduled": 1700000500, "args": []},
        ],
        "count": 2,
    })
    result = await has.list_scheduled_actions(ctx, ListScheduledActionsParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data) == 2
    assert result.data[0].hook == "woocommerce_deliver_webhook_async"
    assert result.data[0].status == "failed"


async def test_list_scheduled_actions_surfaces_unavailable():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/actions", ACTION_UNAVAILABLE_BODY, 404)
    result = await has.list_scheduled_actions(ctx, ListScheduledActionsParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "ACTION_SCHEDULER_UNAVAILABLE"


async def test_list_scheduled_actions_surfaces_bridge_too_old():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/actions", {"code": "rest_no_route"}, 404)
    result = await has.list_scheduled_actions(ctx, ListScheduledActionsParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "BRIDGE_TOO_OLD"


async def test_list_scheduled_actions_filters_pass_through():
    ctx = await _ctx()
    captured = {}

    async def fake_get(ctx_, base_url, path, *, username, app_password, params=None):
        captured["params"] = params
        class R:
            status_code = 200
            body = {"actions": [], "count": 0}
        return R()

    import handlers_action_scheduler as mod
    orig = mod.wp_get
    mod.wp_get = fake_get
    try:
        result = await has.list_scheduled_actions(
            ctx, ListScheduledActionsParams(site_id="x-com", status="failed", hook="my_hook", group="my_group"))
    finally:
        mod.wp_get = orig
    assert result.status == "success"
    assert captured["params"]["status"] == "failed"
    assert captured["params"]["hook"] == "my_hook"
    assert captured["params"]["group"] == "my_group"


# ─────────── get_scheduled_action ───────────

async def test_get_scheduled_action_success_with_logs():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/actions/42", {
        "id": 42, "hook": "woocommerce_deliver_webhook_async", "status": "failed",
        "group": "webhooks", "scheduled": 1700000000, "args": {"webhook_id": 7},
        "logs": [{"message": "action created", "date": "2026-08-01T00:00:00+00:00"},
                  {"message": "action failed: Timeout", "date": "2026-08-01T00:05:00+00:00"}],
    })
    result = await has.get_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=42))
    assert result.status == "success"
    assert result.data.hook == "woocommerce_deliver_webhook_async"
    assert len(result.data.logs) == 2
    assert "Timeout" in result.data.logs[1].message


async def test_get_scheduled_action_not_found():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/actions/999", {
        "code": "imperal_action_not_found", "message": "No scheduled action with that id.",
    }, 404)
    result = await has.get_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=999))
    assert result.status == "error"
    assert result.error_code == "ACTION_NOT_FOUND"


# ─────────── run_scheduled_action ───────────

async def test_run_scheduled_action_success():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/42/run", {
        "ran": True, "failed": False,
        "action": {"id": 42, "hook": "my_hook", "status": "complete", "group": "", "scheduled": None, "args": []},
    })
    result = await has.run_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=42))
    assert result.status == "success"
    assert result.data.ran is True
    assert result.data.failed is False


async def test_run_scheduled_action_surfaces_hook_failure():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/42/run", {
        "ran": True, "failed": True, "error": "Connection timed out",
        "action": {"id": 42, "hook": "my_hook", "status": "failed", "group": "", "scheduled": None, "args": []},
    })
    result = await has.run_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=42))
    assert result.status == "success"
    assert result.data.failed is True
    assert "timed out" in result.data.error.lower()
    assert "timed out" in result.summary.lower()


async def test_run_scheduled_action_not_found():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/999/run", {
        "code": "imperal_action_not_found", "message": "No scheduled action with that id.",
    }, 404)
    result = await has.run_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=999))
    assert result.status == "error"
    assert result.error_code == "ACTION_NOT_FOUND"


# ─────────── cancel_scheduled_action ───────────

async def test_cancel_scheduled_action_success():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/42/cancel", {
        "cancelled": True,
        "action": {"id": 42, "hook": "my_hook", "status": "canceled", "group": "", "scheduled": None, "args": []},
    })
    result = await has.cancel_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=42))
    assert result.status == "success"
    assert result.data.cancelled is True


async def test_cancel_scheduled_action_not_found():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/999/cancel", {
        "code": "imperal_action_not_found", "message": "No scheduled action with that id.",
    }, 404)
    result = await has.cancel_scheduled_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=999))
    assert result.status == "error"
    assert result.error_code == "ACTION_NOT_FOUND"


# ─────────── retry_failed_action ───────────

async def test_retry_failed_action_success():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/42/retry", {
        "retried": True, "original_id": 42,
        "new_action": {"id": 99, "hook": "my_hook", "status": "pending", "group": "", "scheduled": 1700001000, "args": []},
    })
    result = await has.retry_failed_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=42))
    assert result.status == "success"
    assert result.data.retried is True
    assert result.data.new_action_id == 99
    assert "99" in result.summary


async def test_retry_failed_action_rejects_non_failed():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/42/retry", {
        "code": "imperal_action_not_failed",
        "message": "Only a failed action can be retried; this action is not in the failed state.",
    }, 400)
    result = await has.retry_failed_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=42))
    assert result.status == "error"
    assert result.error_code == "ACTION_NOT_FAILED"


async def test_retry_failed_action_not_found():
    ctx = await _ctx()
    _mock_post(ctx, "/wp-json/imperal/v1/action-scheduler/actions/999/retry", {
        "code": "imperal_action_not_found", "message": "No scheduled action with that id.",
    }, 404)
    result = await has.retry_failed_action(ctx, GetScheduledActionParams(site_id="x-com", action_id=999))
    assert result.status == "error"
    assert result.error_code == "ACTION_NOT_FOUND"


# ─────────── count_actions_by_status ───────────

async def test_count_actions_by_status_success():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/counts", {
        "counts": {"pending": 3, "in-progress": 0, "complete": 1200, "failed": 47, "canceled": 5},
    })
    result = await has.count_actions_by_status(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.pending == 3
    assert result.data.failed == 47
    assert result.data.complete == 1200
    assert "47 failed" in result.summary


async def test_count_actions_by_status_surfaces_unavailable():
    ctx = await _ctx()
    _mock_get(ctx, "/wp-json/imperal/v1/action-scheduler/counts", ACTION_UNAVAILABLE_BODY, 404)
    result = await has.count_actions_by_status(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "ACTION_SCHEDULER_UNAVAILABLE"


async def test_count_actions_by_status_requires_connected_site():
    result = await has.count_actions_by_status(MockContext(), SiteIdParams(site_id="ghost"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"
