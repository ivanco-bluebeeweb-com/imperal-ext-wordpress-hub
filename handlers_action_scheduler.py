"""Action Scheduler -- WooCommerce's (and several other plugins') own
background job queue.

Action Scheduler is NOT WordPress core and NOT guaranteed present -- it
ships bundled inside WooCommerce, so it needs the Imperal Bridge plugin
(SECTION 16, 2.12.0+) to reach it at all; there is no meaningful SSH/WP-CLI
fallback (the bundled `wp action-scheduler` command itself requires the
Action Scheduler CLI package/WooCommerce loaded the exact same way, so a
bare SSH session gains nothing a plain REST call through the Bridge
doesn't already have -- this mirrors handlers_redirects.py's precedent for
Rank Math's own custom table). If the Bridge isn't installed, or Action
Scheduler isn't active on the site, the error says so plainly.

This is a first-class backend-dev diagnostic surface distinct from native
WP-Cron (handlers_cache_cron.py) -- WP-Cron only decides *when* Action
Scheduler's own runner next wakes up; this is "why didn't my order
emails/webhooks/sync jobs actually run".
"""
from imperal_sdk import ActionResult

from app import chat
from models import (
    ActionCountsResult,
    GetScheduledActionParams,
    ListScheduledActionsParams,
    ScheduledActionCancelResult,
    ScheduledActionDetail,
    ScheduledActionItem,
    ScheduledActionLogEntry,
    ScheduledActionRetryResult,
    ScheduledActionRunResult,
    SiteIdParams,
)
import storage
from wp_client import wp_get, wp_post

BRIDGE_AS_LIST_PATH = "/wp-json/imperal/v1/action-scheduler/actions"
BRIDGE_AS_COUNTS_PATH = "/wp-json/imperal/v1/action-scheduler/counts"


def _action_detail_path(action_id: int) -> str:
    return f"/wp-json/imperal/v1/action-scheduler/actions/{action_id}"


async def _site_auth(ctx, site_id):
    """Resolve (base_url, username, password) for the Bridge call, or an error."""
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], pw), None


def _bridge_error(status_code: int, body) -> ActionResult:
    if status_code == 404:
        code = ""
        if isinstance(body, dict):
            code = str(body.get("code", ""))
        if code == "imperal_action_scheduler_unavailable" or (
            isinstance(body, dict) and "not active" in str(body.get("message", "")).lower()
        ):
            return ActionResult.error(
                "Action Scheduler is not active on this site — it ships inside WooCommerce "
                "and some other plugins, but neither appears to have it loaded.",
                retryable=False, code="ACTION_SCHEDULER_UNAVAILABLE")
        return ActionResult.error(
            "The Imperal Bridge plugin on this site doesn't support Action Scheduler yet "
            "(needs Bridge 2.12.0+). Update the Bridge plugin, or reinstall it from the zip.",
            retryable=False, code="BRIDGE_TOO_OLD")
    message = "Could not reach the site."
    if isinstance(body, dict) and body.get("message"):
        message = str(body["message"])
    return ActionResult.error(message, retryable=True, code="BRIDGE_ERROR")


def _item_from_body(body: dict) -> ScheduledActionItem:
    return ScheduledActionItem(
        id=str(body.get("id", "")), title=body.get("hook", ""), kind="scheduled_action",
        hook=body.get("hook", ""), status=body.get("status", ""), group=body.get("group", ""),
        scheduled=body.get("scheduled"), args=body.get("args") or {},
    )


@chat.function(
    "list_scheduled_actions",
    description=(
        "List Action Scheduler jobs (WooCommerce's own background job queue) -- pending, "
        "in-progress, complete, failed, or canceled, filterable by status/hook/group. Reads "
        "through the Imperal Bridge plugin (needs 2.12.0+); Action Scheduler itself must be "
        "active on the site (ships inside WooCommerce)."
    ),
    action_type="read",
    data_model=ScheduledActionItem,
    effects=["wp.list_scheduled_actions"],
    event="wordpress-hub.list_scheduled_actions",
)
async def list_scheduled_actions(ctx, params: ListScheduledActionsParams) -> ActionResult:
    """List Action Scheduler jobs via the Bridge."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    query = {"per_page": params.per_page, "offset": params.offset}
    if params.status:
        query["status"] = params.status
    if params.hook:
        query["hook"] = params.hook
    if params.group:
        query["group"] = params.group

    try:
        r = await wp_get(ctx, base_url, BRIDGE_AS_LIST_PATH, username=username, app_password=pw, params=query)
    except Exception as e:
        await ctx.log(f"list_scheduled_actions: {e}", level="error")
        return ActionResult.error("Could not reach the site.", retryable=True)
    if r.status_code != 200:
        return _bridge_error(r.status_code, r.body)

    items = [_item_from_body(a) for a in (r.body or {}).get("actions", [])]
    return ActionResult.success(
        items, summary=f"{len(items)} scheduled action(s).",
    )


@chat.function(
    "get_scheduled_action",
    description=(
        "Read one Action Scheduler job in full detail -- hook, status, group, scheduled time, "
        "args, and its own execution log entries (started/completed/failed messages). Reads "
        "through the Imperal Bridge plugin (needs 2.12.0+)."
    ),
    action_type="read",
    data_model=ScheduledActionDetail,
    effects=["wp.get_scheduled_action"],
    event="wordpress-hub.get_scheduled_action",
)
async def get_scheduled_action(ctx, params: GetScheduledActionParams) -> ActionResult:
    """Read one Action Scheduler job's full detail via the Bridge."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, _action_detail_path(params.action_id), username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"get_scheduled_action: {e}", level="error")
        return ActionResult.error("Could not reach the site.", retryable=True)
    if r.status_code == 404 and isinstance(r.body, dict) and r.body.get("code") == "imperal_action_not_found":
        return ActionResult.error(
            f"No scheduled action with id {params.action_id} on this site.",
            retryable=False, code="ACTION_NOT_FOUND")
    if r.status_code != 200:
        return _bridge_error(r.status_code, r.body)

    body = r.body or {}
    logs = [ScheduledActionLogEntry(message=l.get("message", ""), date=l.get("date", "")) for l in body.get("logs", [])]
    detail = ScheduledActionDetail(
        id=str(params.action_id), title=body.get("hook", ""), kind="scheduled_action",
        hook=body.get("hook", ""), status=body.get("status", ""), group=body.get("group", ""),
        scheduled=body.get("scheduled"), args=body.get("args") or {}, logs=logs,
    )
    return ActionResult.success(detail, summary=f"Action {params.action_id}: {detail.hook} ({detail.status}).")


@chat.function(
    "run_scheduled_action",
    description=(
        "Force one Action Scheduler job to run right now, regardless of its scheduled time -- "
        "the exact same 'Run' row action the Scheduled Actions admin screen offers. Runs "
        "synchronously and surfaces whatever error the job itself raises. Reads through the "
        "Imperal Bridge plugin (needs 2.12.0+)."
    ),
    action_type="write",
    data_model=ScheduledActionRunResult,
    effects=["wp.run_scheduled_action"],
    event="wordpress-hub.run_scheduled_action",
)
async def run_scheduled_action(ctx, params: GetScheduledActionParams) -> ActionResult:
    """Force-run one Action Scheduler job now via the Bridge."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_post(ctx, base_url, f"{_action_detail_path(params.action_id)}/run", username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"run_scheduled_action: {e}", level="error")
        return ActionResult.error("Could not reach the site.", retryable=True)
    if r.status_code == 404 and isinstance(r.body, dict) and r.body.get("code") == "imperal_action_not_found":
        return ActionResult.error(
            f"No scheduled action with id {params.action_id} on this site.",
            retryable=False, code="ACTION_NOT_FOUND")
    if r.status_code != 200:
        return _bridge_error(r.status_code, r.body)

    body = r.body or {}
    failed = bool(body.get("failed"))
    result = ScheduledActionRunResult(
        id=str(params.action_id), title="run result", kind="scheduled_action_run",
        ran=bool(body.get("ran")), failed=failed, error=body.get("error", ""),
    )
    if failed:
        return ActionResult.success(result, summary=f"Action {params.action_id} ran but raised an error: {result.error}")
    return ActionResult.success(result, summary=f"Ran action {params.action_id} now.")


@chat.function(
    "cancel_scheduled_action",
    description=(
        "Cancel one pending Action Scheduler job so it never runs. Reads through the Imperal "
        "Bridge plugin (needs 2.12.0+)."
    ),
    action_type="write",
    data_model=ScheduledActionCancelResult,
    effects=["wp.cancel_scheduled_action"],
    event="wordpress-hub.cancel_scheduled_action",
)
async def cancel_scheduled_action(ctx, params: GetScheduledActionParams) -> ActionResult:
    """Cancel one pending Action Scheduler job via the Bridge."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_post(ctx, base_url, f"{_action_detail_path(params.action_id)}/cancel", username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"cancel_scheduled_action: {e}", level="error")
        return ActionResult.error("Could not reach the site.", retryable=True)
    if r.status_code == 404 and isinstance(r.body, dict) and r.body.get("code") == "imperal_action_not_found":
        return ActionResult.error(
            f"No scheduled action with id {params.action_id} on this site.",
            retryable=False, code="ACTION_NOT_FOUND")
    if r.status_code != 200:
        return _bridge_error(r.status_code, r.body)

    return ActionResult.success(
        ScheduledActionCancelResult(id=str(params.action_id), title="cancelled", kind="scheduled_action_cancel", cancelled=True),
        summary=f"Cancelled action {params.action_id}.",
    )


@chat.function(
    "retry_failed_action",
    description=(
        "Re-queue one FAILED Action Scheduler job for another attempt. Action Scheduler has no "
        "native retry, so this schedules a brand-new action with the same hook/args/group -- "
        "the same thing a developer calling its own public API by hand would do. Only actions "
        "already in the 'failed' status are eligible. Reads through the Imperal Bridge plugin "
        "(needs 2.12.0+)."
    ),
    action_type="write",
    data_model=ScheduledActionRetryResult,
    effects=["wp.retry_failed_action"],
    event="wordpress-hub.retry_failed_action",
)
async def retry_failed_action(ctx, params: GetScheduledActionParams) -> ActionResult:
    """Re-queue one failed Action Scheduler job via the Bridge."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_post(ctx, base_url, f"{_action_detail_path(params.action_id)}/retry", username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"retry_failed_action: {e}", level="error")
        return ActionResult.error("Could not reach the site.", retryable=True)
    if r.status_code == 404 and isinstance(r.body, dict) and r.body.get("code") == "imperal_action_not_found":
        return ActionResult.error(
            f"No scheduled action with id {params.action_id} on this site.",
            retryable=False, code="ACTION_NOT_FOUND")
    if r.status_code == 400 and isinstance(r.body, dict) and r.body.get("code") == "imperal_action_not_failed":
        return ActionResult.error(
            "Only a failed action can be retried; this action is not in the failed state.",
            retryable=False, code="ACTION_NOT_FAILED")
    if r.status_code != 200:
        return _bridge_error(r.status_code, r.body)

    body = r.body or {}
    new_action = body.get("new_action") or {}
    result = ScheduledActionRetryResult(
        id=str(params.action_id), title="retry result", kind="scheduled_action_retry",
        retried=bool(body.get("retried")), original_id=params.action_id,
        new_action_id=int(new_action.get("id", 0) or 0),
    )
    return ActionResult.success(result, summary=f"Re-queued action {params.action_id} as new action {result.new_action_id}.")


@chat.function(
    "count_actions_by_status",
    description=(
        "One-glance health snapshot of the Action Scheduler queue -- how many jobs are pending, "
        "in-progress, complete, failed, or canceled. The single most useful backend-dev "
        "diagnostic for this whole area ('47 failed, 3 pending'). Reads through the Imperal "
        "Bridge plugin (needs 2.12.0+)."
    ),
    action_type="read",
    data_model=ActionCountsResult,
    effects=["wp.count_actions_by_status"],
    event="wordpress-hub.count_actions_by_status",
)
async def count_actions_by_status(ctx, params: SiteIdParams) -> ActionResult:
    """Read the Action Scheduler queue's status counts via the Bridge."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, BRIDGE_AS_COUNTS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"count_actions_by_status: {e}", level="error")
        return ActionResult.error("Could not reach the site.", retryable=True)
    if r.status_code != 200:
        return _bridge_error(r.status_code, r.body)

    counts = (r.body or {}).get("counts") or {}
    result = ActionCountsResult(
        id=params.site_id, title="Action Scheduler queue", kind="action_counts",
        pending=int(counts.get("pending", 0) or 0),
        in_progress=int(counts.get("in-progress", 0) or 0),
        complete=int(counts.get("complete", 0) or 0),
        failed=int(counts.get("failed", 0) or 0),
        canceled=int(counts.get("canceled", 0) or 0),
    )
    summary = f"{result.pending} pending, {result.in_progress} in progress, {result.failed} failed, {result.complete} complete, {result.canceled} canceled."
    return ActionResult.success(result, summary=summary)
