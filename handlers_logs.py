"""SSH/WP-CLI log tools (Group I of the developer/backend roadmap,
docs/2026-08-11-developer-backend-functions-plan.md).

tail_debug_log / clear_debug_log read/truncate wp-content/debug.log (the
file WP_DEBUG_LOG writes to) -- WP_CONTENT_DIR is discovered live via
`wp eval`, never hardcoded as 'wp-content'. tail_php_error_log reads PHP's
own `ini_get('error_log')` path, never a guessed distro-specific path.

All three honestly report "no file" rather than fabricating log content
when the file genuinely doesn't exist (WP_DEBUG_LOG off, or PHP logging
elsewhere e.g. the web server's own error log). SSH-based, same safety bar
as handlers_database.py/handlers_cache_cron.py: fixed-shape commands, no
caller-supplied text placed unsanitized on the command line.
"""
from imperal_sdk import ActionResult

from app import chat
from models import ClearLogResult, LogTail, SiteIdParams, TailLogParams
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
    "tail_debug_log",
    description=(
        "Read the last N lines of a connected WordPress site's wp-content/debug.log "
        "(the file WP_DEBUG_LOG writes to) via SSH/WP-CLI. Requires SSH access configured "
        "with add_ssh. If the site has WP_DEBUG_LOG off, or has never logged an error, "
        "there is honestly no file -- reported as exists=false, never fabricated content."
    ),
    action_type="read", data_model=LogTail,
)
async def tail_debug_log(ctx, params: TailLogParams) -> ActionResult:
    """Last N lines of wp-content/debug.log over SSH."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.tail_debug_log(cred, lines=params.lines)
    except Exception as e:
        await ctx.log(f"tail_debug_log: {e}", level="error")
        return ActionResult.error("Could not read the debug log over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"tail_debug_log: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)
    entity = LogTail(id=params.site_id, title="debug.log", kind="wp_log_tail",
                      site_id=params.site_id, path=result["path"], exists=result["exists"],
                      lines=result["lines"])
    summary = f"{len(result['lines'])} line(s)" if result["exists"] else "No debug.log file exists."
    return ActionResult.success(entity, summary=summary)


@chat.function(
    "clear_debug_log",
    description=(
        "Truncate a connected WordPress site's wp-content/debug.log to empty via SSH/WP-CLI "
        "(the file is truncated in place, never deleted, so WordPress can keep writing to it "
        "without recreating it). Requires SSH access configured with add_ssh."
    ),
    action_type="write", data_model=ClearLogResult,
    effects=["wp.clear_debug_log"],
    event="wordpress-hub.clear_debug_log",
)
async def clear_debug_log(ctx, params: SiteIdParams) -> ActionResult:
    """Truncate wp-content/debug.log over SSH."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.clear_debug_log(cred)
    except Exception as e:
        await ctx.log(f"clear_debug_log: {e}", level="error")
        return ActionResult.error("Could not clear the debug log over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"clear_debug_log: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)
    entity = ClearLogResult(id=params.site_id, title="debug.log", kind="wp_log_clear",
                            site_id=params.site_id, path=result["path"],
                            cleared=result["cleared"], note=result.get("note", ""))
    summary = "Cleared debug.log." if result["cleared"] else (result.get("note") or "Nothing to clear.")
    return ActionResult.success(entity, summary=summary)


@chat.function(
    "tail_php_error_log",
    description=(
        "Read the last N lines of a connected WordPress site's PHP error log, at the path "
        "PHP itself reports via ini_get('error_log') -- never a guessed distro-specific path. "
        "Requires SSH access configured with add_ssh. If PHP has no error_log configured "
        "(likely logging to the web server's own error log instead), this is reported "
        "honestly rather than fabricating a path."
    ),
    action_type="read", data_model=LogTail,
)
async def tail_php_error_log(ctx, params: TailLogParams) -> ActionResult:
    """Last N lines of PHP's own configured error_log over SSH."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.tail_php_error_log(cred, lines=params.lines)
    except Exception as e:
        await ctx.log(f"tail_php_error_log: {e}", level="error")
        return ActionResult.error("Could not read the PHP error log over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"tail_php_error_log: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)
    entity = LogTail(id=params.site_id, title="php_error_log", kind="wp_log_tail",
                      site_id=params.site_id, path=result["path"], exists=result["exists"],
                      lines=result["lines"], note=result.get("note", ""))
    if not result["path"]:
        summary = result.get("note") or "PHP has no error_log configured."
    elif result["exists"]:
        summary = f"{len(result['lines'])} line(s)"
    else:
        summary = "No PHP error log file exists at that path."
    return ActionResult.success(entity, summary=summary)
