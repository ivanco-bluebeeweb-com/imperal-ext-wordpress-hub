"""Log tools (Group I of the developer/backend roadmap,
docs/2026-08-11-developer-backend-functions-plan.md).

Bridge-first, SSH-fallback -- same pattern as handlers_database.py's
SECTION 12 database tools: every one of these operations is a plain PHP
filesystem call from INSIDE the WordPress process (Bridge SECTION 13,
/imperal/v1/logs/*, 2.9.0+), so a site with the Imperal Bridge plugin
installed needs NO SSH at all. tail_debug_log / clear_debug_log read/
truncate wp-content/debug.log (the file WP_DEBUG_LOG writes to) --
WP_CONTENT_DIR is a real WordPress core constant on the Bridge path, and
discovered live via `wp eval` on the SSH fallback -- never hardcoded as
'wp-content'. tail_php_error_log reads PHP's own `ini_get('error_log')`
path, never a guessed distro-specific path, on both paths.

All three honestly report "no file" rather than fabricating log content
when the file genuinely doesn't exist (WP_DEBUG_LOG off, or PHP logging
elsewhere e.g. the web server's own error log). SSH + WP-CLI (wp_cli.py)
remains the fallback for sites that don't have the Bridge yet, or whose
Bridge predates 2.9.0: fixed-shape commands, no caller-supplied text
placed unsanitized on the command line.
"""
from imperal_sdk import ActionResult

from app import chat
from models import ClearLogResult, LogTail, SiteIdParams, TailLogParams
import storage
import wp_cli
from wp_client import wp_get, wp_post

BRIDGE_LOGS_DEBUG_PATH = "/wp-json/imperal/v1/logs/debug-log"
BRIDGE_LOGS_DEBUG_CLEAR_PATH = "/wp-json/imperal/v1/logs/debug-log/clear"
BRIDGE_LOGS_PHP_ERROR_PATH = "/wp-json/imperal/v1/logs/php-error-log"


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
    """GET a Bridge logs route. Returns the body dict on 200, else None
    to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


async def _bridge_post(ctx, base_url, username, pw, path):
    """POST to a Bridge logs route. Returns the body dict on 200, else None
    to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_post(ctx, base_url, path, username=username, app_password=pw, json={})
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


@chat.function(
    "tail_debug_log",
    description=(
        "Read the last N lines of a connected WordPress site's wp-content/debug.log "
        "(the file WP_DEBUG_LOG writes to). Reads through the Imperal Bridge plugin if "
        "it's installed (no SSH needed at all); falls back to SSH + WP-CLI otherwise. "
        "If the site has WP_DEBUG_LOG off, or has never logged an error, there is "
        "honestly no file -- reported as exists=false, never fabricated content."
    ),
    action_type="read", data_model=LogTail,
)
async def tail_debug_log(ctx, params: TailLogParams) -> ActionResult:
    """Bridge-first (/logs/debug-log), SSH-fallback (`wp eval` + `tail`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_LOGS_DEBUG_PATH,
                             params={"lines": params.lines})
    if body is not None:
        entity = LogTail(id=params.site_id, title="debug.log", kind="wp_log_tail",
                          site_id=params.site_id, path=body.get("path", ""),
                          exists=body.get("exists", False), lines=body.get("lines", []))
        summary = f"{len(body.get('lines', []))} line(s)" if body.get("exists") else "No debug.log file exists."
        return ActionResult.success(entity, summary=summary)

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Truncate a connected WordPress site's wp-content/debug.log to empty (the file is "
        "truncated in place, never deleted, so WordPress can keep writing to it without "
        "recreating it). Reads/writes through the Imperal Bridge plugin if it's installed "
        "(no SSH needed at all); falls back to SSH + WP-CLI otherwise."
    ),
    action_type="write", data_model=ClearLogResult,
    effects=["wp.clear_debug_log"],
    event="wordpress-hub.clear_debug_log",
)
async def clear_debug_log(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/logs/debug-log/clear), SSH-fallback (`: > <path>`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_LOGS_DEBUG_CLEAR_PATH)
    if body is not None:
        entity = ClearLogResult(id=params.site_id, title="debug.log", kind="wp_log_clear",
                                site_id=params.site_id, path=body.get("path", ""),
                                cleared=body.get("cleared", False), note=body.get("note", ""))
        summary = "Cleared debug.log." if body.get("cleared") else (body.get("note") or "Nothing to clear.")
        return ActionResult.success(entity, summary=summary)

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
        "Reads through the Imperal Bridge plugin if it's installed (no SSH needed at all); "
        "falls back to SSH + WP-CLI otherwise. If PHP has no error_log configured (likely "
        "logging to the web server's own error log instead), this is reported honestly "
        "rather than fabricating a path."
    ),
    action_type="read", data_model=LogTail,
)
async def tail_php_error_log(ctx, params: TailLogParams) -> ActionResult:
    """Bridge-first (/logs/php-error-log), SSH-fallback (`wp eval` + `tail`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_LOGS_PHP_ERROR_PATH,
                             params={"lines": params.lines})
    if body is not None:
        entity = LogTail(id=params.site_id, title="php_error_log", kind="wp_log_tail",
                          site_id=params.site_id, path=body.get("path", ""),
                          exists=body.get("exists", False), lines=body.get("lines", []),
                          note=body.get("note", ""))
        if not body.get("path"):
            summary = body.get("note") or "PHP has no error_log configured."
        elif body.get("exists"):
            summary = f"{len(body.get('lines', []))} line(s)"
        else:
            summary = "No PHP error log file exists at that path."
        return ActionResult.success(entity, summary=summary)

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "Neither the Imperal Bridge plugin nor SSH is available for this site. "
            "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
            code="SSH_NOT_CONFIGURED")
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
