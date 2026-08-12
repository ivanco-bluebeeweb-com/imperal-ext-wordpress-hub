"""Database tools: table listing, search-replace migration (dry-run-first),
optimize/check/repair, export dump, and row-count/orphan diagnostics.

Bridge-first, SSH-fallback -- same pattern as handlers_read.py's
get_server_info: every one of these operations is a plain $wpdb call from
INSIDE the WordPress process (Bridge SECTION 12, /imperal/v1/database/*,
2.8.0+), so a site with the Imperal Bridge plugin installed needs NO SSH at
all. SSH + WP-CLI (wp_cli.py) remains the fallback for sites that don't have
the Bridge yet, or whose Bridge predates 2.8.0. Every WP-CLI command shape
was verified against wp-cli's own command reference
(developer.wordpress.org/cli/commands/db/*) -- wp-cli/db-command for db
subcommands, wp-cli/post-command for post counts. Any caller-supplied text
(search/replace strings, table names, post_type) is validated before being
placed on the command line (SSH path) or sent to the Bridge (which itself
re-validates table names against this site's own $wpdb->prefix).

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
    BackupRestorabilityResult,
    CheckBackupRestorabilityParams,
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
from wp_client import wp_get, wp_post

BRIDGE_DB_SEARCH_REPLACE_PATH = "/wp-json/imperal/v1/database/search-replace"
BRIDGE_DB_TABLES_PATH = "/wp-json/imperal/v1/database/tables"
BRIDGE_DB_OPTIMIZE_PATH = "/wp-json/imperal/v1/database/optimize"
BRIDGE_DB_CHECK_PATH = "/wp-json/imperal/v1/database/check"
BRIDGE_DB_EXPORT_PATH = "/wp-json/imperal/v1/database/export"
BRIDGE_DB_POST_COUNT_PATH = "/wp-json/imperal/v1/database/post-count"
BRIDGE_DB_ORPHANED_POSTMETA_PATH = "/wp-json/imperal/v1/database/orphaned-postmeta"


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
    """GET a Bridge database route. Returns (body, None) on 200, else (None, None)
    to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


async def _bridge_post(ctx, base_url, username, pw, path, json_body=None):
    """POST to a Bridge database route. Returns the body dict on 200, else None
    to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_post(ctx, base_url, path, username=username, app_password=pw, json=json_body)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


@chat.function(
    "list_database_tables",
    description=(
        "List every table in the site's own database, with its size on disk. Reads through "
        "the Imperal Bridge plugin if it's installed (no SSH needed at all); falls back to "
        "SSH + WP-CLI (`wp db size --tables`) when the Bridge isn't there yet or doesn't "
        "answer. Use before run_db_search_replace or export_database_dump to see real table "
        "names/wildcards, never invent one."
    ),
    action_type="read",
    data_model=sdl.EntityList[DatabaseTableItem],
)
async def list_database_tables(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/database/tables), SSH-fallback (`wp db size --tables`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_DB_TABLES_PATH)
    if body is not None:
        rows = body.get("tables", [])
        items = [
            DatabaseTableItem(id=str(row.get("name", "")), title=str(row.get("name", "")),
                              kind="wp_db_table", name=str(row.get("name", "")),
                              size=str(row.get("size", "")))
            for row in rows
        ]
        return ActionResult.success(items, summary=f"Found {len(items)} table(s).")

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "PREVIEW a database search-and-replace across the site's own tables -- the standard "
        "way to migrate a domain (staging to production, http to https) across serialized "
        "WordPress data. Reads through the Imperal Bridge plugin if it's installed (no SSH "
        "needed at all); falls back to SSH + WP-CLI (`wp search-replace --dry-run`) otherwise. "
        "This ALWAYS runs as a dry-run and only reports how many rows WOULD change; nothing "
        "is written. Pass the returned replacement count to apply_db_search_replace to "
        "actually run it."
    ),
    action_type="read",
    data_model=SearchReplaceResult,
)
async def run_db_search_replace(ctx, params: SearchReplaceParams) -> ActionResult:
    """Bridge-first (/database/search-replace, dry_run=true), SSH-fallback (`wp search-replace --dry-run`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_DB_SEARCH_REPLACE_PATH, json_body={
        "old": params.old, "new": params.new, "dry_run": True, "tables": params.tables,
    })
    if body is not None:
        count = body.get("replacements", 0)
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

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Actually run a database search-and-replace, after previewing it with "
        "run_db_search_replace. Reads/writes through the Imperal Bridge plugin if it's "
        "installed (no SSH needed at all); falls back to SSH + WP-CLI (`wp search-replace`) "
        "otherwise. Re-checks a fresh dry-run immediately before writing and refuses to "
        "proceed if the replacement count no longer matches expected_replacements -- protects "
        "against a stale preview on a database that changed in between. This changes live "
        "data; there is no dry-run undo, so back up first if unsure."
    ),
    action_type="write",
    data_model=SearchReplaceResult,
    effects=["wp.db_search_replace"],
    event="wordpress-hub.apply_db_search_replace",
)
async def apply_db_search_replace(ctx, params: ApplySearchReplaceParams) -> ActionResult:
    """Bridge-first (/database/search-replace, dry_run=false after a fresh recheck), SSH-fallback."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    fresh_body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_DB_SEARCH_REPLACE_PATH, json_body={
        "old": params.old, "new": params.new, "dry_run": True, "tables": params.tables,
    })
    if fresh_body is not None:
        fresh_count = fresh_body.get("replacements", 0)
        if fresh_count != params.expected_replacements:
            return ActionResult.error(
                f"The database changed since your preview — a fresh check now finds "
                f"{fresh_count} replacement(s), not {params.expected_replacements}. Run "
                f"run_db_search_replace again and re-confirm.",
                retryable=False, code="SEARCH_REPLACE_STALE_PREVIEW")

        apply_body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_DB_SEARCH_REPLACE_PATH, json_body={
            "old": params.old, "new": params.new, "dry_run": False, "tables": params.tables,
        })
        if apply_body is not None:
            count = apply_body.get("replacements", 0)
            return ActionResult.success(
                SearchReplaceResult(
                    id=params.site_id, title="search-replace", kind="wp_search_replace_apply",
                    site_id=params.site_id, dry_run=False, replacements=count,
                ),
                summary=f"Made {count} replacement(s).",
            )
        # Bridge answered the dry-run but not the apply (very unlikely) --
        # fall through to SSH rather than silently doing nothing.

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Defragment and optimize every database table -- reclaims space after heavy deletes, "
        "does not change any data. Reads/writes through the Imperal Bridge plugin if it's "
        "installed (no SSH needed at all); falls back to SSH + WP-CLI (`wp db optimize`) "
        "otherwise. Safe routine maintenance."
    ),
    action_type="write",
    data_model=DatabaseMaintenanceResult,
    effects=["wp.db_optimize"],
    event="wordpress-hub.optimize_database_tables",
)
async def optimize_database_tables(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/database/optimize), SSH-fallback (`wp db optimize`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_DB_OPTIMIZE_PATH)
    if body is not None:
        return ActionResult.success(
            DatabaseMaintenanceResult(
                id=params.site_id, title="database optimize", kind="wp_db_optimize",
                site_id=params.site_id, output=body.get("output", ""),
            ),
            summary="Optimized every database table.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Check every database table for corruption, and repair any that are damaged if "
        "repair=true. Reads/writes through the Imperal Bridge plugin if it's installed (no "
        "SSH needed at all); falls back to SSH + WP-CLI (`wp db check`/`wp db repair`) "
        "otherwise. Use check-only first (repair=false, the default) to see if anything is "
        "actually broken before repairing."
    ),
    action_type="write",
    data_model=DatabaseMaintenanceResult,
    effects=["wp.db_check_repair"],
    event="wordpress-hub.check_database_repair",
)
async def check_database_repair(ctx, params: CheckDatabaseParams) -> ActionResult:
    """Bridge-first (/database/check), SSH-fallback (`wp db check`/`wp db repair`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_DB_CHECK_PATH,
                              json_body={"repair": params.repair})
    if body is not None:
        return ActionResult.success(
            DatabaseMaintenanceResult(
                id=params.site_id, title="database repair" if params.repair else "database check",
                kind="wp_db_repair" if params.repair else "wp_db_check",
                site_id=params.site_id, output=body.get("output", ""),
            ),
            summary="Repaired every damaged table." if params.repair else "Checked every table for corruption.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Export a SQL dump of the site's database, returned inline as text. Reads through "
        "the Imperal Bridge plugin if it's installed (no SSH needed at all); falls back to "
        "SSH + WP-CLI (`wp db export`) otherwise. Capped at roughly 2MB of SQL text -- pass "
        "specific `tables` from list_database_tables to scope a large database down if the "
        "export is refused as too large."
    ),
    action_type="read",
    data_model=DatabaseDumpResult,
)
async def export_database_dump(ctx, params: ExportDatabaseDumpParams) -> ActionResult:
    """Bridge-first (/database/export), SSH-fallback (`wp db export -`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_DB_EXPORT_PATH,
                             params={"tables": params.tables} if params.tables else None)
    if body is not None:
        return ActionResult.success(
            DatabaseDumpResult(
                id=params.site_id, title="database dump", kind="wp_db_export",
                site_id=params.site_id, sql=body.get("sql", ""),
                size_bytes=body.get("size_bytes", 0),
            ),
            summary=f"Exported {body.get('size_bytes', 0)} bytes of SQL.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Count how many rows of one post type exist (any status). Reads through the "
        "Imperal Bridge plugin if it's installed (no SSH needed at all); falls back to "
        "SSH + WP-CLI (`wp post list --format=count`) otherwise. Pass a post_type slug "
        "from list_custom_posts or the site's own /wp/v2/types, e.g. post, page, product."
    ),
    action_type="read",
    data_model=PostTypeCountResult,
)
async def count_post_type_rows(ctx, params: CountPostTypeRowsParams) -> ActionResult:
    """Bridge-first (/database/post-count), SSH-fallback (`wp post list --format=count`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_DB_POST_COUNT_PATH,
                             params={"post_type": params.post_type})
    if body is not None:
        count = body.get("count", 0)
        return ActionResult.success(
            PostTypeCountResult(
                id=params.site_id, title=f"{params.post_type} count", kind="wp_post_type_count",
                site_id=params.site_id, post_type=params.post_type, count=count,
            ),
            summary=f"{count} '{params.post_type}' row(s).",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "clean' diagnostic, useful after bulk deletes or a messy plugin uninstall. Reads "
        "through the Imperal Bridge plugin if it's installed (no SSH needed at all); falls "
        "back to SSH + WP-CLI otherwise. Read-only; does not delete anything."
    ),
    action_type="read",
    data_model=OrphanedPostmetaResult,
)
async def count_orphaned_postmeta(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/database/orphaned-postmeta), SSH-fallback (`wp db query` join)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_DB_ORPHANED_POSTMETA_PATH)
    if body is not None:
        count = body.get("orphaned_postmeta", 0)
        return ActionResult.success(
            OrphanedPostmetaResult(
                id=params.site_id, title="orphaned postmeta", kind="wp_orphaned_postmeta",
                site_id=params.site_id, orphaned_rows=count,
            ),
            summary=f"{count} orphaned postmeta row(s).",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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


_CORE_TABLE_SUFFIXES = (
    "options", "posts", "postmeta", "users", "usermeta", "terms", "termmeta",
    "term_taxonomy", "term_relationships", "comments", "commentmeta", "links",
)


def _table_names_from_dump(sql: str) -> set[str]:
    """Every table named in a CREATE TABLE statement in this dump."""
    import re
    return {m.group(1) for m in re.finditer(r"CREATE TABLE[^`]*`([^`]+)`", sql, re.IGNORECASE)}


def _dump_is_truncated(sql: str) -> bool:
    """A well-formed `wp db export`/Bridge dump ends with a terminated
    statement (`;`) or a trailing comment/blank line after one -- a dump cut
    off mid-INSERT (network drop, size cap) ends on an unterminated value
    list instead. This is a structural heuristic, not a SQL parser."""
    tail = sql.rstrip()
    if not tail:
        return True
    return not tail.endswith(";")


@chat.function(
    "check_backup_restorability",
    description=(
        "Check whether this site's own database backup is structurally sound enough to "
        "trust for a restore -- NOT a real test-restore (that needs a separate sandbox "
        "database this app does not provision). Exports the current dump via "
        "export_database_dump's same Bridge/SSH path, compares it against "
        "list_database_tables, and flags: a truncated/cut-off export, any WordPress core "
        "table missing entirely, and any table whose CREATE statement has zero data rows. "
        "Run this after every real backup job to catch a silently broken backup before you "
        "actually need it."
    ),
    action_type="read",
    data_model=BackupRestorabilityResult,
)
async def check_backup_restorability(ctx, params: CheckBackupRestorabilityParams) -> ActionResult:
    """Structural integrity check over one export_database_dump SQL text."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    # Reuse export_database_dump's own Bridge-first/SSH-fallback path so this
    # never duplicates -- and can drift from -- how a real dump is produced.
    dump_result = await export_database_dump(
        ctx, ExportDatabaseDumpParams(site_id=params.site_id, tables=params.tables)
    )
    if dump_result.status != "success":
        return dump_result
    sql = dump_result.data.sql
    size_bytes = dump_result.data.size_bytes

    tables_result = await list_database_tables(ctx, SiteIdParams(site_id=params.site_id))
    if tables_result.status != "success":
        return tables_result
    all_table_items = tables_result.data if isinstance(tables_result.data, list) else []
    expected_names = {item.name for item in all_table_items}
    if params.tables:
        # Scoped export: only judge the tables actually asked for.
        expected_names = {t for t in expected_names if any(
            t == want or t.endswith(want) for want in params.tables
        )} or expected_names

    found_names = _table_names_from_dump(sql)
    missing = sorted(
        t for t in expected_names
        if t not in found_names
        and any(t.endswith(f"_{suffix}") for suffix in _CORE_TABLE_SUFFIXES)
    )

    empty_tables = []
    for t in found_names:
        # A table with a CREATE statement but no matching INSERT INTO for
        # that exact table name has zero rows in this dump.
        if f"INSERT INTO `{t}`" not in sql and f"INSERT INTO {t} " not in sql:
            empty_tables.append(t)
    empty_tables.sort()

    truncated = _dump_is_truncated(sql)

    issues: list[str] = []
    if truncated:
        issues.append("Dump does not end in a terminated SQL statement -- likely cut off mid-export.")
    if missing:
        issues.append(f"{len(missing)} core table(s) missing from the dump entirely: {', '.join(missing[:10])}")
    if empty_tables:
        issues.append(f"{len(empty_tables)} table(s) have a CREATE statement but no data rows: {', '.join(empty_tables[:10])}")
    if size_bytes == 0 or not sql.strip():
        issues.append("Dump is empty.")
        truncated = True

    restorable = not truncated and not missing and bool(sql.strip())

    return ActionResult.success(
        BackupRestorabilityResult(
            id=params.site_id, title="backup restorability", kind="wp_backup_restorability",
            site_id=params.site_id, size_bytes=size_bytes,
            tables_expected=len(expected_names), tables_found_in_dump=len(found_names),
            missing_tables=missing, empty_tables=empty_tables, truncated=truncated,
            restorable=restorable, issues=issues,
        ),
        summary=(
            "Backup looks structurally restorable." if restorable
            else f"Backup has {len(issues)} integrity issue(s) -- do not trust it for a restore yet."
        ),
    )
