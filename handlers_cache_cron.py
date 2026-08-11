"""SSH/WP-CLI transients, persistent object cache, and cron introspection
beyond the existing run_wp_cron (which only force-runs due events).

Every command shape here was verified against wp-cli's own command reference
(developer.wordpress.org/cli/commands/transient|cache|cron/*) before writing
this file -- wp-cli/cache-command for transient/cache subcommands,
wp-cli/cron-command for cron subcommands. Same safety bar as
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


async def _ssh_cred(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    cred = await storage.get_ssh_cred(ctx, site_id)
    if not cred:
        return None, ActionResult.error(
            "SSH is not configured for this site. Add SSH access first.", retryable=False,
            code="SSH_NOT_CONFIGURED")
    return cred, None


# ─────────── Transients ───────────

@chat.function(
    "list_transients",
    description=(
        "List WordPress transients (temporary cached values plugins/themes store in "
        "wp_options) via WP-CLI (`wp transient list`). Requires SSH access configured "
        "with add_ssh. Shows name, value, and expiration — useful for diagnosing stale "
        "cached data or a bloated options table."
    ),
    action_type="read",
    data_model=sdl.EntityList[TransientItem],
)
async def list_transients(ctx, params: SiteIdParams) -> ActionResult:
    """List transients over SSH via `wp transient list --format=json`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "Delete one named transient via WP-CLI (`wp transient delete <name>`). Requires "
        "SSH access configured with add_ssh. Pass a name from list_transients — never a "
        "guessed name."
    ),
    action_type="write",
    data_model=TransientActionResult,
    effects=["wp.delete_transient"],
    event="wordpress-hub.delete_transient",
)
async def delete_transient(ctx, params: DeleteTransientParams) -> ActionResult:
    """Delete one transient over SSH via `wp transient delete <name>`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "Delete every transient on the site via WP-CLI (`wp transient delete --all`). "
        "Requires SSH access configured with add_ssh. More thorough than one plugin's own "
        "cache-clear button — clears every plugin's/theme's transient at once."
    ),
    action_type="write",
    data_model=TransientActionResult,
    effects=["wp.flush_transients"],
    event="wordpress-hub.flush_all_transients",
)
async def flush_all_transients(ctx, params: SiteIdParams) -> ActionResult:
    """Delete all transients over SSH via `wp transient delete --all`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "the site via WP-CLI (`wp cache type`). Requires SSH access configured with "
        "add_ssh. Returns 'Default' when no persistent object cache drop-in is installed "
        "(WordPress's built-in non-persistent cache only)."
    ),
    action_type="read",
    data_model=ObjectCacheStatus,
)
async def get_object_cache_status(ctx, params: SiteIdParams) -> ActionResult:
    """Read the active object cache backend over SSH via `wp cache type`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "Flush the persistent object cache (Redis/Memcached/etc., if active) via WP-CLI "
        "(`wp cache flush`). Requires SSH access configured with add_ssh. This is "
        "different from purge_cache (which purges a PAGE cache plugin) — this clears the "
        "object cache layer instead."
    ),
    action_type="write",
    data_model=TransientActionResult,
    effects=["wp.flush_object_cache"],
    event="wordpress-hub.flush_object_cache",
)
async def flush_object_cache(ctx, params: SiteIdParams) -> ActionResult:
    """Flush the object cache over SSH via `wp cache flush`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "List every scheduled WordPress cron event via WP-CLI (`wp cron event list`). "
        "Requires SSH access configured with add_ssh. Shows each event's hook name, next "
        "run time, and recurrence — use before run_cron_event or delete_cron_event to see "
        "real hook names, never invent one."
    ),
    action_type="read",
    data_model=sdl.EntityList[CronEventItem],
)
async def list_cron_events(ctx, params: SiteIdParams) -> ActionResult:
    """List scheduled cron events over SSH via `wp cron event list --format=json`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "Force one specific cron event to run right now via WP-CLI (`wp cron event run "
        "<hook>`), regardless of whether it's due. Requires SSH access configured with "
        "add_ssh. Pass a hook name from list_cron_events — never invent one. Use "
        "run_wp_cron instead when you just want every DUE event to fire."
    ),
    action_type="write",
    data_model=CronEventActionResult,
    effects=["wp.run_cron_event"],
    event="wordpress-hub.run_cron_event",
)
async def run_cron_event(ctx, params: CronEventActionParams) -> ActionResult:
    """Force-run one cron event over SSH via `wp cron event run <hook>`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "Unschedule one cron event via WP-CLI (`wp cron event delete <hook>`) — removes "
        "every scheduled occurrence of that hook. Requires SSH access configured with "
        "add_ssh. Use to fix a stuck or duplicated cron event. Pass a hook name from "
        "list_cron_events — never invent one."
    ),
    action_type="write",
    data_model=CronEventActionResult,
    effects=["wp.delete_cron_event"],
    event="wordpress-hub.delete_cron_event",
)
async def delete_cron_event(ctx, params: CronEventActionParams) -> ActionResult:
    """Unschedule one cron event over SSH via `wp cron event delete <hook>`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
        "any custom intervals plugins have added) via WP-CLI (`wp cron schedule list`). "
        "Requires SSH access configured with add_ssh. Useful for diagnosing 'why does "
        "this only run every N hours' when a plugin's own schedule choice is opaque."
    ),
    action_type="read",
    data_model=sdl.EntityList[CronScheduleItem],
)
async def list_cron_schedules(ctx, params: SiteIdParams) -> ActionResult:
    """List registered cron recurrence intervals over SSH via `wp cron schedule list`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
