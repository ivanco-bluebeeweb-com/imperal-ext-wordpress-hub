"""Security / hardening diagnostics (Group F of the developer/backend-developer
roadmap, docs/2026-08-11-developer-backend-functions-plan.md).

get_php_info / check_debug_mode / check_file_permissions all read plain PHP
runtime facts (phpversion(), get_loaded_extensions(), ini_get(), the
WP_DEBUG* constants, fileperms()) through the Imperal Bridge plugin's new
SECTION 10 (/imperal/v1/security/php-info|debug-mode|file-permissions) --
none of it needs a shell, so these are Bridge-only (no SSH fallback,
consistent with SECTION 7's Rank Math site-wide functions which are also
Bridge-only). A clear SECURITY_BRIDGE_MISSING error is returned if the site
doesn't have Bridge 2.6.0+ installed yet -- never a fabricated result.

list_admin_users is a thin, no-Bridge-needed wrapper over WordPress core's
own `GET /wp/v2/users?roles=administrator` filter, confirmed against
developer.wordpress.org/rest-api/reference/users/ (the `roles` request arg
accepts a list of role slugs and has shipped in WordPress core since 4.7).

get_ssl_status is intentionally NOT built here -- web-tools' ssl_check
already owns that surface; duplicating it here would fork one fact across
two apps. list_failed_login_attempts is intentionally NOT built here either
-- it would require guessing a specific security plugin's (Wordfence /
Limit Login Attempts Reloaded) internal storage shape, which is exactly the
kind of fabrication the roadmap forbids; revisit only if a concrete site's
plugin and schema can be verified first.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    DebugModeStatus,
    FilePermissionsStatus,
    ListAdminUsersParams,
    PhpInfo,
    SiteIdParams,
    WPUser,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get

BRIDGE_PHP_INFO_PATH = "/wp-json/imperal/v1/security/php-info"
BRIDGE_DEBUG_MODE_PATH = "/wp-json/imperal/v1/security/debug-mode"
BRIDGE_FILE_PERMS_PATH = "/wp-json/imperal/v1/security/file-permissions"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin (2.6.0+) on the site (bridge/imperal-bridge "
    "in the connector repo)."
)


async def _authed(ctx, site_id):
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


def _failure(status_code, body):
    if status_code == 404:
        return ActionResult.error(
            "The Imperal Bridge plugin (2.6.0+) is not installed on this site, or is on an "
            "older version that predates the security-diagnostics routes. " + _INSTALL_HINT,
            retryable=False, code="SECURITY_BRIDGE_MISSING")
    return ActionResult.error(wp_error_message(status_code), retryable=status_code >= 500,
                              code=wp_error_code(status_code))


@chat.function(
    "get_php_info",
    description=(
        "Get server information for a WordPress site: PHP version, loaded extensions, and "
        "memory_limit/max_execution_time/upload_max_filesize/post_max_size -- reads it through "
        "the Imperal Bridge plugin (2.6.0+). Feeds 'is this site tech-eligible for X' questions."
    ),
    action_type="read", data_model=PhpInfo,
)
async def get_php_info(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/security/php-info."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_PHP_INFO_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"get_php_info request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    db_size = body.get("db_size_mb")
    return ActionResult.success(
        PhpInfo(
            id=params.site_id, title=f"PHP info {params.site_id}", kind="wp_php_info",
            site_id=params.site_id, php_version=str(body.get("php_version", "")),
            extensions=[str(e) for e in (body.get("extensions") or [])],
            memory_limit=str(body.get("memory_limit", "")),
            max_execution_time=str(body.get("max_execution_time", "")),
            upload_max_filesize=str(body.get("upload_max_filesize", "")),
            post_max_size=str(body.get("post_max_size", "")),
            max_input_vars=str(body.get("max_input_vars", "")),
            server_software=str(body.get("server_software", "")),
            wp_version=str(body.get("wp_version", "")),
            opcache_enabled=bool(body.get("opcache_enabled")),
            opcache_hit_rate=str(body.get("opcache_hit_rate", "")),
            db_version=str(body.get("db_version", "")),
            db_server_info=str(body.get("db_server_info", "")),
            db_size_mb=(str(db_size) if db_size not in (None, "") else ""),
            source="bridge",
        ),
        summary=f"PHP {body.get('php_version', '?')}, {len(body.get('extensions') or [])} extension(s) loaded")


@chat.function(
    "check_debug_mode",
    description=(
        "Check whether WP_DEBUG / WP_DEBUG_LOG / WP_DEBUG_DISPLAY are on for a connected "
        "WordPress site -- these should normally be OFF in production, and WP_DEBUG_DISPLAY "
        "leaking PHP notices/warnings to visitors is a common, genuinely risky misconfiguration. "
        "Reads through the Imperal Bridge plugin (2.6.0+)."
    ),
    action_type="read", data_model=DebugModeStatus,
)
async def check_debug_mode(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/security/debug-mode."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_DEBUG_MODE_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"check_debug_mode request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    debug_on = bool(body.get("wp_debug"))
    display_on = bool(body.get("wp_debug_display"))
    summary = "WP_DEBUG is off." if not debug_on else "WP_DEBUG is ON"
    if debug_on and display_on:
        summary += " and errors are DISPLAYED to visitors — fix this on a production site."
    elif debug_on:
        summary += " (log-only, not displayed to visitors)."
    return ActionResult.success(
        DebugModeStatus(
            id=params.site_id, title=f"debug mode {params.site_id}", kind="wp_debug_mode",
            site_id=params.site_id, wp_debug=debug_on,
            wp_debug_log=bool(body.get("wp_debug_log")), wp_debug_display=display_on,
        ),
        summary=summary)


@chat.function(
    "check_file_permissions",
    description=(
        "Sanity-check wp-config.php and wp-content permissions on a connected WordPress site -- "
        "wp-config.php world-readable leaks database credentials; wp-content writable by "
        "everyone allows arbitrary file drops. Read-only: never changes any permission. "
        "Reads through the Imperal Bridge plugin (2.6.0+)."
    ),
    action_type="read", data_model=FilePermissionsStatus,
)
async def check_file_permissions(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/security/file-permissions."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_FILE_PERMS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"check_file_permissions request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    exists = bool(body.get("wp_config_exists"))
    wcp = body.get("wp_config_permissions")
    wtp = body.get("wp_content_permissions")
    return ActionResult.success(
        FilePermissionsStatus(
            id=params.site_id, title=f"file permissions {params.site_id}", kind="wp_file_permissions",
            site_id=params.site_id, wp_config_exists=exists,
            wp_config_permissions=str(wcp) if wcp is not None else None,
            wp_content_permissions=str(wtp) if wtp is not None else None,
        ),
        summary=(f"wp-config.php: {wcp or 'not found'}, wp-content: {wtp or 'unknown'}"))


@chat.function(
    "list_admin_users",
    description=(
        "List only the users with the administrator role on a connected WordPress site -- a "
        "common security audit ask ('who has admin on this site'). Native WordPress REST API "
        "filter, no Bridge or SSH needed."
    ),
    action_type="read", data_model=sdl.EntityList[WPUser],
)
async def list_admin_users(ctx, params: ListAdminUsersParams) -> ActionResult:
    """GET /wp/v2/users?roles=administrator."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(
            ctx, base_url, "/wp-json/wp/v2/users",
            username=username, app_password=pw,
            params={"roles": "administrator", "per_page": params.limit, "orderby": "registered_date", "order": "desc"})
    except Exception as e:
        await ctx.log(f"list_admin_users request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500,
                                  code=wp_error_code(r.status_code))
    data = r.body if isinstance(r.body, list) else []
    items = [
        WPUser(id=str(u["id"]), title=u.get("name", ""), kind="wp_admin_user",
               role=", ".join(u.get("roles", [])), registered=(u.get("registered_date", "") or "")[:10])
        for u in data
    ]
    return ActionResult.success(sdl.EntityList[WPUser](items=items),
                                summary=f"{len(items)} administrator(s)")
