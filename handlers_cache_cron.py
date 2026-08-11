"""Transients, persistent object cache, and cron introspection beyond the
existing run_wp_cron (which only force-runs due events).

Bridge-first, SSH-fallback -- same pattern as handlers_database.py and
handlers_logs.py: every one of these is a plain WordPress core call from
INSIDE the process (Bridge SECTION 14, /imperal/v1/cache/*, 2.10.0+), so a
site with the Imperal Bridge plugin installed needs no SSH at all. The real
core functions are used on the Bridge path (delete_transient(),
wp_using_ext_object_cache(), wp_cache_flush(), _get_cron_array(),
wp_unschedule_hook(), wp_get_schedules()) -- never a raw options-table
write that would bypass cache add-ons hooking those actions.

SSH + WP-CLI (wp_cli.py) remains the fallback for sites without the Bridge
or whose Bridge predates 2.10.0. Every command shape there was verified
against wp-cli's own command reference (developer.wordpress.org/cli/
commands/transient|cache|cron/*): wp-cli/cache-command for transient/cache
subcommands, wp-cli/cron-command for cron subcommands. Same safety bar as
handlers_maintenance.py: fixed-shape, non-interpolated commands, and any
caller-supplied name (transient name, cron hook) is restricted to safe
identifier characters before being placed on the command line.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    CronEventActionParams,
    CronEventActionResult,
    CronEventItem,
    CronScheduleItem,
    DeleteTransientParams,
    ObjectCacheStatus,
    SiteIdParams,
    TransientActionResult,
    TransientItem,
)
import storage
import wp_cli
from wp_client import wp_get, wp_post

BRIDGE_CACHE_TRANSIENTS_PATH = "/wp-json/imperal/v1/cache/transients"
BRIDGE_CACHE_TRANSIENTS_DELETE_PATH = "/wp-json/imperal/v1/cache/transients/delete"
BRIDGE_CACHE_TRANSIENTS_FLUSH_ALL_PATH = "/wp-json/imperal/v1/cache/transients/flush-all"
BRIDGE_CACHE_OBJECT_STATUS_PATH = "/wp-json/imperal/v1/cache/object-cache-status"
BRIDGE_CACHE_OBJECT_FLUSH_PATH = "/wp-json/imperal/v1/cache/object-cache/flush"
BRIDGE_CRON_EVENTS_PATH = "/wp-json/imperal/v1/cache/cron/events"
BRIDGE_CRON_EVENTS_RUN_PATH = "/wp-json/imperal/v1/cache/cron/events/run"
BRIDGE_CRON_EVENTS_DELETE_PATH = "/wp-json/imperal/v1/cache/cron/events/delete"
BRIDGE_CRON_SCHEDULES_PATH = "/wp-json/imperal/v1/cache/cron/schedules"


async def _site_auth(ctx, site_id):
    """Resolve (base_url, username, password) for the Bridge probe, or an error."""
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


async def _bridge_get(ctx, base_url, username, pw, path, params=None):
    """GET a Bridge cache/cron route. Returns the body dict on 200, else None
    to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


async def _bridge_post(ctx, base_url, username, pw, path, json_body=None):
    """POST to a Bridge cache/cron route. Returns the body dict on 200, else
    None to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_post(ctx, base_url, path, username=username, app_password=pw, json=json_body)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


def _no_bridge_no_ssh_error():
    return ActionResult.error(
        "Neither the Imperal Bridge plugin nor SSH is available for this site. "
        "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
        code="SSH_NOT_CONFIGURED")


# ─────────── Transients ───────────

@chat.function(
    "list_transients",
    description=(
        "List WordPress transients (temporary cached values plugins/themes store in "
        "wp_options). Reads through the Imperal Bridge plugin if it's installed, or "
        "falls back to SSH + WP-CLI (`wp transient list`) if SSH is configured with "
        "add_ssh. Shows name, value, and expiration — useful for diagnosing stale "
        "cached data or a bloated options table."
    ),
    action_type="read",
    data_model=sdl.EntityList[TransientItem],
)
async def list_transients(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/cache/transients), SSH-fallback (`wp transient list --format=json`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_CACHE_TRANSIENTS_PATH)
    if body is not None:
        rows = body.get("transients", [])
        items = [
            TransientItem(
                id=str(row.get("name", "")), title=str(row.get("name", "")), kind="wp_transient",
                name=str(row.get("name", "")), value=str(row.get("value", "")),
                expiration=str(row.get("expiration", "")),
            )
            for row in rows
        ]
        return ActionResult.success(items, summary=f"Found {len(items)} transient(s).")

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        rows, cli_error = await wp_cli.list_transients(cred)
    except Exception as e:
        await ctx.log(f"list_transients: {e}", level="error")
        return ActionResult.error("Could not list transients over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"list_transients: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    items = [
        TransientItem(
            id=str(row.get("name", "")), title=str(row.get("name", "")), kind="wp_transient",
            name=str(row.get("name", "")), value=str(row.get("value", "")),
            expiration=str(row.get("expiration", "")),
        )
        for row in (rows or [])
    ]
    return ActionResult.success(items, summary=f"Found {len(items)} transient(s).")


@chat.function(
    "delete_transient",
    description=(
        "Delete one named transient. Reads through the Imperal Bridge plugin if it's "
        "installed, or falls back to SSH + WP-CLI (`wp transient delete <name>`) if SSH "
        "is configured with add_ssh. Pass a name from list_transients — never a guessed "
        "name."
    ),
    action_type="write",
    data_model=TransientActionResult,
    effects=["wp.delete_transient"],
    event="wordpress-hub.delete_transient",
)
async def delete_transient(ctx, params: DeleteTransientParams) -> ActionResult:
    """Bridge-first (/cache/transients/delete), SSH-fallback (`wp transient delete <name>`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_CACHE_TRANSIENTS_DELETE_PATH,
                               json_body={"name": params.name})
    if body is not None:
        return ActionResult.success(
            TransientActionResult(
                id=params.site_id, title=f"transient {params.name}", kind="wp_transient_delete",
                site_id=params.site_id, output="deleted" if body.get("deleted") else "not found",
            ),
            summary=f"Deleted transient '{params.name}'.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        output, cli_error = await wp_cli.delete_transient(cred, params.name)
    except Exception as e:
        await ctx.log(f"delete_transient: {e}", level="error")
        return ActionResult.error("Could not delete the transient over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"delete_transient: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        TransientActionResult(
            id=params.site_id, title=f"transient {params.name}", kind="wp_transient_delete",
            site_id=params.site_id, output=output or "",
        ),
        summary=f"Deleted transient '{params.name}'.",
    )


@chat.function(
    "flush_all_transients",
    description=(
        "Delete every transient on the site. Reads through the Imperal Bridge plugin if "
        "it's installed, or falls back to SSH + WP-CLI (`wp transient delete --all`) if "
        "SSH is configured with add_ssh. More thorough than one plugin's own cache-clear "
        "button — clears every plugin's/theme's transient at once."
    ),
    action_type="write",
    data_model=TransientActionResult,
    effects=["wp.flush_transients"],
    event="wordpress-hub.flush_all_transients",
)
async def flush_all_transients(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/cache/transients/flush-all), SSH-fallback (`wp transient delete --all`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_CACHE_TRANSIENTS_FLUSH_ALL_PATH)
    if body is not None:
        count = body.get("deleted_count", 0)
        return ActionResult.success(
            TransientActionResult(
                id=params.site_id, title="all transients", kind="wp_transient_flush_all",
                site_id=params.site_id, output=f"Deleted {count} transient(s).",
            ),
            summary="Deleted all transients.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        output, cli_error = await wp_cli.flush_all_transients(cred)
    except Exception as e:
        await ctx.log(f"flush_all_transients: {e}", level="error")
        return ActionResult.error("Could not flush transients over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"flush_all_transients: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        TransientActionResult(
            id=params.site_id, title="all transients", kind="wp_transient_flush_all",
            site_id=params.site_id, output=output or "",
        ),
        summary="Deleted all transients.",
    )


# ─────────── Object cache ───────────

@chat.function(
    "get_object_cache_status",
    description=(
        "Check whether a persistent object cache (Redis, Memcached, etc.) is active on "
        "the site. Reads through the Imperal Bridge plugin if it's installed, or falls "
        "back to SSH + WP-CLI (`wp cache type`) if SSH is configured with add_ssh. "
        "Returns 'Default' when no persistent object cache drop-in is installed "
        "(WordPress's built-in non-persistent cache only)."
    ),
    action_type="read",
    data_model=ObjectCacheStatus,
)
async def get_object_cache_status(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/cache/object-cache-status), SSH-fallback (`wp cache type`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_CACHE_OBJECT_STATUS_PATH)
    if body is not None:
        cache_type = body.get("cache_type", "Default")
        return ActionResult.success(
            ObjectCacheStatus(
                id=params.site_id, title="object cache", kind="wp_object_cache_status",
                site_id=params.site_id, cache_type=cache_type,
            ),
            summary=f"Object cache: {cache_type}.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        cache_type, cli_error = await wp_cli.get_cache_type(cred)
    except Exception as e:
        await ctx.log(f"get_object_cache_status: {e}", level="error")
        return ActionResult.error("Could not read the object cache type over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"get_object_cache_status: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        ObjectCacheStatus(
            id=params.site_id, title="object cache", kind="wp_object_cache_status",
            site_id=params.site_id, cache_type=cache_type or "Default",
        ),
        summary=f"Object cache: {cache_type or 'Default'}.",
    )


@chat.function(
    "flush_object_cache",
    description=(
        "Flush the persistent object cache (Redis/Memcached/etc., if active). Reads "
        "through the Imperal Bridge plugin if it's installed, or falls back to SSH + "
        "WP-CLI (`wp cache flush`) if SSH is configured with add_ssh. This is different "
        "from purge_cache (which purges a PAGE cache plugin) — this clears the object "
        "cache layer instead."
    ),
    action_type="write",
    data_model=TransientActionResult,
    effects=["wp.flush_object_cache"],
    event="wordpress-hub.flush_object_cache",
)
async def flush_object_cache(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/cache/object-cache/flush), SSH-fallback (`wp cache flush`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_CACHE_OBJECT_FLUSH_PATH)
    if body is not None:
        return ActionResult.success(
            TransientActionResult(
                id=params.site_id, title="object cache", kind="wp_object_cache_flush",
                site_id=params.site_id, output="flushed" if body.get("flushed") else "not flushed",
            ),
            summary="Flushed the object cache.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        output, cli_error = await wp_cli.flush_object_cache(cred)
    except Exception as e:
        await ctx.log(f"flush_object_cache: {e}", level="error")
        return ActionResult.error("Could not flush the object cache over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"flush_object_cache: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        TransientActionResult(
            id=params.site_id, title="object cache", kind="wp_object_cache_flush",
            site_id=params.site_id, output=output or "",
        ),
        summary="Flushed the object cache.",
    )


# ─────────── Cron (beyond run_wp_cron) ───────────

@chat.function(
    "list_cron_events",
    description=(
        "List every scheduled WordPress cron event. Reads through the Imperal Bridge "
        "plugin if it's installed, or falls back to SSH + WP-CLI (`wp cron event list`) "
        "if SSH is configured with add_ssh. Shows each event's hook name, next run time, "
        "and recurrence — use before run_cron_event or delete_cron_event to see real hook "
        "names, never invent one."
    ),
    action_type="read",
    data_model=sdl.EntityList[CronEventItem],
)
async def list_cron_events(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/cache/cron/events), SSH-fallback (`wp cron event list --format=json`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_CRON_EVENTS_PATH)
    if body is not None:
        rows = body.get("events", [])
        items = [
            CronEventItem(
                id=str(row.get("hook", "")), title=str(row.get("hook", "")), kind="wp_cron_event",
                hook=str(row.get("hook", "")),
                next_run_gmt=str(row.get("next_run_gmt", "")),
                next_run_relative=str(row.get("next_run_relative", "")),
                recurrence=str(row.get("recurrence", "") or "Non-repeating"),
            )
            for row in rows
        ]
        return ActionResult.success(items, summary=f"Found {len(items)} scheduled cron event(s).")

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        rows, cli_error = await wp_cli.list_cron_events(cred)
    except Exception as e:
        await ctx.log(f"list_cron_events: {e}", level="error")
        return ActionResult.error("Could not list cron events over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"list_cron_events: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    items = [
        CronEventItem(
            id=str(row.get("hook", "")), title=str(row.get("hook", "")), kind="wp_cron_event",
            hook=str(row.get("hook", "")),
            next_run_gmt=str(row.get("next_run_gmt", "")),
            next_run_relative=str(row.get("next_run_relative", "")),
            recurrence=str(row.get("recurrence", "") or "Non-repeating"),
        )
        for row in (rows or [])
    ]
    return ActionResult.success(items, summary=f"Found {len(items)} scheduled cron event(s).")


@chat.function(
    "run_cron_event",
    description=(
        "Force one specific cron event to run right now, regardless of whether it's due. "
        "Reads through the Imperal Bridge plugin if it's installed, or falls back to SSH "
        "+ WP-CLI (`wp cron event run <hook>`) if SSH is configured with add_ssh. Pass a "
        "hook name from list_cron_events — never invent one. Use run_wp_cron instead when "
        "you just want every DUE event to fire."
    ),
    action_type="write",
    data_model=CronEventActionResult,
    effects=["wp.run_cron_event"],
    event="wordpress-hub.run_cron_event",
)
async def run_cron_event(ctx, params: CronEventActionParams) -> ActionResult:
    """Bridge-first (/cache/cron/events/run), SSH-fallback (`wp cron event run <hook>`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_CRON_EVENTS_RUN_PATH,
                               json_body={"hook": params.hook})
    if body is not None:
        ran = body.get("ran", 0)
        return ActionResult.success(
            CronEventActionResult(
                id=params.hook, title=params.hook, kind="wp_cron_event_run",
                site_id=params.site_id, hook=params.hook, output=f"Ran {ran} instance(s).",
            ),
            summary=f"Ran cron event '{params.hook}'.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        output, cli_error = await wp_cli.run_cron_event(cred, params.hook)
    except Exception as e:
        await ctx.log(f"run_cron_event: {e}", level="error")
        return ActionResult.error("Could not run the cron event over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"run_cron_event: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        CronEventActionResult(
            id=params.hook, title=params.hook, kind="wp_cron_event_run",
            site_id=params.site_id, hook=params.hook, output=output or "",
        ),
        summary=f"Ran cron event '{params.hook}'.",
    )


@chat.function(
    "delete_cron_event",
    description=(
        "Unschedule one cron event — removes every scheduled occurrence of that hook. "
        "Reads through the Imperal Bridge plugin if it's installed, or falls back to SSH "
        "+ WP-CLI (`wp cron event delete <hook>`) if SSH is configured with add_ssh. Use "
        "to fix a stuck or duplicated cron event. Pass a hook name from list_cron_events "
        "— never invent one."
    ),
    action_type="write",
    data_model=CronEventActionResult,
    effects=["wp.delete_cron_event"],
    event="wordpress-hub.delete_cron_event",
)
async def delete_cron_event(ctx, params: CronEventActionParams) -> ActionResult:
    """Bridge-first (/cache/cron/events/delete), SSH-fallback (`wp cron event delete <hook>`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_CRON_EVENTS_DELETE_PATH,
                               json_body={"hook": params.hook})
    if body is not None:
        return ActionResult.success(
            CronEventActionResult(
                id=params.hook, title=params.hook, kind="wp_cron_event_delete",
                site_id=params.site_id, hook=params.hook,
                output="deleted" if body.get("deleted") else "not found",
            ),
            summary=f"Deleted cron event '{params.hook}'.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        output, cli_error = await wp_cli.delete_cron_event(cred, params.hook)
    except Exception as e:
        await ctx.log(f"delete_cron_event: {e}", level="error")
        return ActionResult.error("Could not delete the cron event over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"delete_cron_event: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        CronEventActionResult(
            id=params.hook, title=params.hook, kind="wp_cron_event_delete",
            site_id=params.site_id, hook=params.hook, output=output or "",
        ),
        summary=f"Deleted cron event '{params.hook}'.",
    )


@chat.function(
    "list_cron_schedules",
    description=(
        "List every registered cron recurrence interval (hourly, twicedaily, daily, and "
        "any custom intervals plugins have added). Reads through the Imperal Bridge "
        "plugin if it's installed, or falls back to SSH + WP-CLI (`wp cron schedule "
        "list`) if SSH is configured with add_ssh. Useful for diagnosing 'why does this "
        "only run every N hours' when a plugin's own schedule choice is opaque."
    ),
    action_type="read",
    data_model=sdl.EntityList[CronScheduleItem],
)
async def list_cron_schedules(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/cache/cron/schedules), SSH-fallback (`wp cron schedule list`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_CRON_SCHEDULES_PATH)
    if body is not None:
        rows = body.get("schedules", [])
        items = [
            CronScheduleItem(
                id=str(row.get("name", "")), title=str(row.get("name", "")), kind="wp_cron_schedule",
                name=str(row.get("name", "")), display=str(row.get("display", "")),
                interval=int(row.get("interval", 0) or 0),
            )
            for row in rows
        ]
        return ActionResult.success(items, summary=f"Found {len(items)} cron schedule(s).")

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        rows, cli_error = await wp_cli.list_cron_schedules(cred)
    except Exception as e:
        await ctx.log(f"list_cron_schedules: {e}", level="error")
        return ActionResult.error("Could not list cron schedules over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"list_cron_schedules: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    items = [
        CronScheduleItem(
            id=str(row.get("name", "")), title=str(row.get("name", "")), kind="wp_cron_schedule",
            name=str(row.get("name", "")), display=str(row.get("display", "")),
            interval=int(row.get("interval", 0) or 0),
        )
        for row in (rows or [])
    ]
    return ActionResult.success(items, summary=f"Found {len(items)} cron schedule(s).")
