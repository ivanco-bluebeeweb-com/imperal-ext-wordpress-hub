"""SSH/WP-CLI database tools: table listing, search-replace migration
(dry-run-first), optimize/check/repair, export dump, and row-count/orphan
diagnostics.

Every command shape here was verified against wp-cli's own command reference
(developer.wordpress.org/cli/commands/db/*) before writing this file --
wp-cli/db-command for db subcommands, wp-cli/post-command for post counts.
Same safety bar as handlers_cache_cron.py: fixed-shape, non-interpolated
commands, and any caller-supplied text (search/replace strings, table names,
post_type) is validated before being placed on the command line.

`run_db_search_replace` follows the same preview->apply pattern as the CSV
catalog import: a dry-run always runs first and returns a replacement count;
`apply_db_search_replace` re-runs a FRESH dry-run immediately before the real
run and refuses to proceed if the count no longer matches what the caller
confirmed -- the same anti-stale-preview guard as apply_order_line_changes.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ApplySearchReplaceParams,
    CheckDatabaseParams,
    CountPostTypeRowsParams,
    DatabaseDumpResult,
    DatabaseMaintenanceResult,
    DatabaseTableItem,
    ExportDatabaseDumpParams,
    OrphanedPostmetaResult,
    PostTypeCountResult,
    SearchReplaceParams,
    SearchReplaceResult,
    SiteIdParams,
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


@chat.function(
    "list_database_tables",
    description=(
        "List every table in the site's own database, with its size on disk, via WP-CLI "
        "(`wp db size --tables`). Requires SSH access configured with add_ssh. Use before "
        "run_db_search_replace or export_database_dump to see real table names/wildcards, "
        "never invent one."
    ),
    action_type="read",
    data_model=sdl.EntityList[DatabaseTableItem],
)
async def list_database_tables(ctx, params: SiteIdParams) -> ActionResult:
    """List tables + sizes over SSH via `wp db size --tables --format=json`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        rows, cli_error = await wp_cli.list_database_tables(cred)
    except Exception as e:
        await ctx.log(f"list_database_tables: {e}", level="error")
        return ActionResult.error("Could not list database tables over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"list_database_tables: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    items = [
        DatabaseTableItem(
            id=str(row.get("Name", row.get("name", ""))),
            title=str(row.get("Name", row.get("name", ""))), kind="wp_db_table",
            name=str(row.get("Name", row.get("name", ""))),
            size=str(row.get("Size", row.get("size", ""))),
        )
        for row in (rows or [])
    ]
    return ActionResult.success(items, summary=f"Found {len(items)} table(s).")


@chat.function(
    "run_db_search_replace",
    description=(
        "PREVIEW a database search-and-replace across the site's own tables via WP-CLI "
        "(`wp search-replace --dry-run`) -- the standard way to migrate a domain (staging "
        "to production, http to https) across serialized WordPress data. This ALWAYS runs "
        "as a dry-run and only reports how many rows WOULD change; nothing is written. "
        "Pass the returned replacement count to apply_db_search_replace to actually run it."
    ),
    action_type="read",
    data_model=SearchReplaceResult,
)
async def run_db_search_replace(ctx, params: SearchReplaceParams) -> ActionResult:
    """Dry-run search-replace over SSH via `wp search-replace <old> <new> --dry-run`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.run_db_search_replace(
            cred, params.old, params.new, dry_run=True, tables=params.tables)
    except Exception as e:
        await ctx.log(f"run_db_search_replace: {e}", level="error")
        return ActionResult.error("Could not run the search-replace preview over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"run_db_search_replace: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    count = result.get("replacements", 0)
    return ActionResult.success(
        SearchReplaceResult(
            id=params.site_id, title="search-replace preview", kind="wp_search_replace_preview",
            site_id=params.site_id, dry_run=True, replacements=count,
        ),
        summary=(
            f"Dry run: {count} replacement(s) would be made. Call apply_db_search_replace "
            f"with expected_replacements={count} to actually run it."
        ),
    )


@chat.function(
    "apply_db_search_replace",
    description=(
        "Actually run a database search-and-replace via WP-CLI (`wp search-replace`), "
        "after previewing it with run_db_search_replace. Re-checks a fresh dry-run "
        "immediately before writing and refuses to proceed if the replacement count no "
        "longer matches expected_replacements -- protects against a stale preview on a "
        "database that changed in between. This changes live data; there is no dry-run "
        "undo, so back up first if unsure."
    ),
    action_type="write",
    data_model=SearchReplaceResult,
    effects=["wp.db_search_replace"],
    event="wordpress-hub.apply_db_search_replace",
)
async def apply_db_search_replace(ctx, params: ApplySearchReplaceParams) -> ActionResult:
    """Re-verify via a fresh dry-run, then run the real search-replace over SSH."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        fresh, cli_error = await wp_cli.run_db_search_replace(
            cred, params.old, params.new, dry_run=True, tables=params.tables)
    except Exception as e:
        await ctx.log(f"apply_db_search_replace (recheck): {e}", level="error")
        return ActionResult.error("Could not re-verify the search-replace over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"apply_db_search_replace (recheck): {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    fresh_count = fresh.get("replacements", 0)
    if fresh_count != params.expected_replacements:
        return ActionResult.error(
            f"The database changed since your preview — a fresh check now finds "
            f"{fresh_count} replacement(s), not {params.expected_replacements}. Run "
            f"run_db_search_replace again and re-confirm.",
            retryable=False, code="SEARCH_REPLACE_STALE_PREVIEW")

    try:
        result, cli_error = await wp_cli.run_db_search_replace(
            cred, params.old, params.new, dry_run=False, tables=params.tables)
    except Exception as e:
        await ctx.log(f"apply_db_search_replace: {e}", level="error")
        return ActionResult.error("Could not run the search-replace over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"apply_db_search_replace: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    count = result.get("replacements", 0)
    return ActionResult.success(
        SearchReplaceResult(
            id=params.site_id, title="search-replace", kind="wp_search_replace_apply",
            site_id=params.site_id, dry_run=False, replacements=count,
        ),
        summary=f"Made {count} replacement(s).",
    )


@chat.function(
    "optimize_database_tables",
    description=(
        "Defragment and optimize every database table via WP-CLI (`wp db optimize`). "
        "Requires SSH access configured with add_ssh. Safe routine maintenance -- "
        "reclaims space after heavy deletes, does not change any data."
    ),
    action_type="write",
    data_model=DatabaseMaintenanceResult,
    effects=["wp.db_optimize"],
    event="wordpress-hub.optimize_database_tables",
)
async def optimize_database_tables(ctx, params: SiteIdParams) -> ActionResult:
    """Optimize every table over SSH via `wp db optimize`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        output, cli_error = await wp_cli.optimize_database_tables(cred)
    except Exception as e:
        await ctx.log(f"optimize_database_tables: {e}", level="error")
        return ActionResult.error("Could not optimize the database over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"optimize_database_tables: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        DatabaseMaintenanceResult(
            id=params.site_id, title="database optimize", kind="wp_db_optimize",
            site_id=params.site_id, output=output or "",
        ),
        summary="Optimized every database table.",
    )


@chat.function(
    "check_database_repair",
    description=(
        "Check every database table for corruption via WP-CLI (`wp db check`), and "
        "repair any that are damaged (`wp db repair`) if repair=true. Requires SSH "
        "access configured with add_ssh. Use check-only first (repair=false, the "
        "default) to see if anything is actually broken before repairing."
    ),
    action_type="write",
    data_model=DatabaseMaintenanceResult,
    effects=["wp.db_check_repair"],
    event="wordpress-hub.check_database_repair",
)
async def check_database_repair(ctx, params: CheckDatabaseParams) -> ActionResult:
    """Check (and optionally repair) every table over SSH via `wp db check`/`wp db repair`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        if params.repair:
            output, cli_error = await wp_cli.repair_database(cred)
        else:
            output, cli_error = await wp_cli.check_database(cred)
    except Exception as e:
        await ctx.log(f"check_database_repair: {e}", level="error")
        return ActionResult.error("Could not check/repair the database over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"check_database_repair: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        DatabaseMaintenanceResult(
            id=params.site_id, title="database repair" if params.repair else "database check",
            kind="wp_db_repair" if params.repair else "wp_db_check",
            site_id=params.site_id, output=output or "",
        ),
        summary="Repaired every damaged table." if params.repair else "Checked every table for corruption.",
    )


@chat.function(
    "export_database_dump",
    description=(
        "Export a SQL dump of the site's database via WP-CLI (`wp db export`), returned "
        "inline as text. Requires SSH access configured with add_ssh. Capped at roughly "
        "2MB of SQL text -- pass specific `tables` from list_database_tables to scope a "
        "large database down if the export is refused as too large."
    ),
    action_type="read",
    data_model=DatabaseDumpResult,
)
async def export_database_dump(ctx, params: ExportDatabaseDumpParams) -> ActionResult:
    """Export a SQL dump over SSH via `wp db export -` (stdout), capped inline."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.export_database_dump(cred, tables=params.tables)
    except Exception as e:
        await ctx.log(f"export_database_dump: {e}", level="error")
        return ActionResult.error("Could not export the database over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"export_database_dump: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        DatabaseDumpResult(
            id=params.site_id, title="database dump", kind="wp_db_export",
            site_id=params.site_id, sql=result.get("sql", ""),
            size_bytes=result.get("size_bytes", 0),
        ),
        summary=f"Exported {result.get('size_bytes', 0)} bytes of SQL.",
    )


@chat.function(
    "count_post_type_rows",
    description=(
        "Count how many rows of one post type exist (any status) via WP-CLI (`wp post "
        "list --format=count`). Requires SSH access configured with add_ssh. Pass a "
        "post_type slug from list_custom_posts or the site's own /wp/v2/types, e.g. "
        "post, page, product."
    ),
    action_type="read",
    data_model=PostTypeCountResult,
)
async def count_post_type_rows(ctx, params: CountPostTypeRowsParams) -> ActionResult:
    """Count rows of one post type over SSH via `wp post list --format=count`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        count, cli_error = await wp_cli.count_post_type_rows(cred, params.post_type)
    except Exception as e:
        await ctx.log(f"count_post_type_rows: {e}", level="error")
        return ActionResult.error("Could not count rows over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"count_post_type_rows: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        PostTypeCountResult(
            id=params.site_id, title=f"{params.post_type} count", kind="wp_post_type_count",
            site_id=params.site_id, post_type=params.post_type, count=count or 0,
        ),
        summary=f"{count} '{params.post_type}' row(s).",
    )


@chat.function(
    "count_orphaned_postmeta",
    description=(
        "Count wp_postmeta rows whose post no longer exists -- a common 'is my database "
        "clean' diagnostic, useful after bulk deletes or a messy plugin uninstall. "
        "Requires SSH access configured with add_ssh. Read-only; does not delete anything."
    ),
    action_type="read",
    data_model=OrphanedPostmetaResult,
)
async def count_orphaned_postmeta(ctx, params: SiteIdParams) -> ActionResult:
    """Count orphaned postmeta rows over SSH via a `wp db query` join."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        count, cli_error = await wp_cli.count_orphaned_postmeta(cred)
    except Exception as e:
        await ctx.log(f"count_orphaned_postmeta: {e}", level="error")
        return ActionResult.error("Could not count orphaned postmeta over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"count_orphaned_postmeta: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        OrphanedPostmetaResult(
            id=params.site_id, title="orphaned postmeta", kind="wp_orphaned_postmeta",
            site_id=params.site_id, orphaned_rows=count or 0,
        ),
        summary=f"{count} orphaned postmeta row(s).",
    )
