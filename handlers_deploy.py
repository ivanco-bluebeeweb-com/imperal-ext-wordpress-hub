"""Deploy / Environment Hygiene diagnostics (Group H of the developer/backend
roadmap, docs/2026-08-11-developer-backend-functions-plan.md).

All 4 functions read plain PHP/WordPress-core facts through the Imperal
Bridge plugin's SECTION 11 (/imperal/v1/deploy/*) -- none of it needs SSH:

- get_wp_config_constants: a hard-ALLOWLISTED subset of wp-config.php
  constants (WP_DEBUG, WP_CACHE, WP_ENVIRONMENT_TYPE, WP_HOME, WP_SITEURL,
  DISALLOW_FILE_EDIT/MODS, AUTOMATIC_UPDATER_DISABLED, plus $wp_version/
  $table_prefix). NEVER DB_NAME/DB_USER/DB_PASSWORD/DB_HOST and NEVER
  AUTH_KEY/SECURE_AUTH_KEY/LOGGED_IN_KEY/NONCE_KEY (or their _SALT twins) --
  the Bridge PHP side hard-codes the allowlist; there is no name parameter
  a caller could widen it with.
- list_must_use_plugins: WordPress core's own get_mu_plugins()
  (wp-admin/includes/plugin.php) -- mu-plugins can't be deactivated, so core
  deliberately excludes them from list_plugins/list_native_plugins. A real
  blind spot today.
- list_drop_ins: WordPress core's own get_dropins() (same file) -- which
  drop-in files (object-cache.php, advanced-cache.php, db.php, etc.) are
  actually present, so it's clear which caching/DB layer is really in play.
- get_environment_type: WordPress 5.5+'s own wp_get_environment_type()
  (wp-includes/load.php) -- production/staging/development/local, defaults
  to 'production' if the site never declared WP_ENVIRONMENT_TYPE. Verified
  against make.wordpress.org/core/2020/07/24/new-wp_get_environment_type-
  function-in-wordpress-5-5/ and developer.wordpress.org's own reference.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import DropIn, EnvironmentType, MustUsePlugin, SiteIdParams, WpConfigConstants
import storage
from wp_client import wp_error_code, wp_error_message, wp_get

BRIDGE_CONFIG_CONSTANTS_PATH = "/wp-json/imperal/v1/deploy/config-constants"
BRIDGE_MU_PLUGINS_PATH = "/wp-json/imperal/v1/deploy/mu-plugins"
BRIDGE_DROP_INS_PATH = "/wp-json/imperal/v1/deploy/drop-ins"
BRIDGE_ENVIRONMENT_TYPE_PATH = "/wp-json/imperal/v1/deploy/environment-type"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin (2.7.0+) on the site (bridge/imperal-bridge "
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
            "The Imperal Bridge plugin (2.7.0+) is not installed on this site, or is on an "
            "older version that predates the deploy-hygiene routes. " + _INSTALL_HINT,
            retryable=False, code="DEPLOY_BRIDGE_MISSING")
    return ActionResult.error(wp_error_message(status_code), retryable=status_code >= 500,
                              code=wp_error_code(status_code))


@chat.function(
    "get_wp_config_constants",
    description=(
        "Read a SAFE, hard-allowlisted subset of a connected WordPress site's wp-config.php "
        "constants (WP_ENV/WP_DEBUG/WP_CACHE, WP_HOME/WP_SITEURL, table prefix, WP version pin, "
        "DISALLOW_FILE_EDIT/MODS, AUTOMATIC_UPDATER_DISABLED) -- NEVER database credentials or "
        "auth keys/salts. Reads through the Imperal Bridge plugin (2.7.0+)."
    ),
    action_type="read", data_model=WpConfigConstants,
)
async def get_wp_config_constants(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/deploy/config-constants."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_CONFIG_CONSTANTS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"get_wp_config_constants request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    return ActionResult.success(
        WpConfigConstants(
            id=params.site_id, title=f"wp-config constants {params.site_id}", kind="wp_config_constants",
            site_id=params.site_id,
            wp_version=str(body.get("wp_version", "")),
            table_prefix=str(body.get("table_prefix", "")),
            wp_debug=body.get("wp_debug"),
            wp_cache=body.get("wp_cache"),
            wp_environment_type=body.get("wp_environment_type"),
            wp_home=body.get("wp_home"),
            wp_siteurl=body.get("wp_siteurl"),
            disallow_file_edit=body.get("disallow_file_edit"),
            disallow_file_mods=body.get("disallow_file_mods"),
            automatic_updater_disabled=body.get("automatic_updater_disabled"),
        ),
        summary=f"WordPress {body.get('wp_version', '?')}, table prefix '{body.get('table_prefix', '')}'")


@chat.function(
    "list_must_use_plugins",
    description=(
        "List must-use (mu-) plugins on a connected WordPress site -- these are invisible to "
        "list_plugins/list_native_plugins because WordPress core excludes them from the regular "
        "plugins list (mu-plugins can't be deactivated). Reads through the Imperal Bridge plugin (2.7.0+)."
    ),
    action_type="read", data_model=sdl.EntityList[MustUsePlugin],
)
async def list_must_use_plugins(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/deploy/mu-plugins."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_MU_PLUGINS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"list_must_use_plugins request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [
        MustUsePlugin(id=str(p.get("file", "")), title=str(p.get("name", "")), kind="wp_mu_plugin",
                      file=str(p.get("file", "")), version=str(p.get("version", "")),
                      description=str(p.get("description", "")))
        for p in data
    ]
    return ActionResult.success(sdl.EntityList[MustUsePlugin](items=items),
                                summary=f"{len(items)} must-use plugin(s)")


@chat.function(
    "list_drop_ins",
    description=(
        "List WordPress core drop-in files present on a connected site (object-cache.php, "
        "advanced-cache.php, db.php, etc.) -- shows which caching/DB layer is actually in play. "
        "Reads through the Imperal Bridge plugin (2.7.0+)."
    ),
    action_type="read", data_model=sdl.EntityList[DropIn],
)
async def list_drop_ins(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/deploy/drop-ins."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_DROP_INS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"list_drop_ins request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [
        DropIn(id=str(d.get("file", "")), title=str(d.get("name", "")), kind="wp_drop_in",
               file=str(d.get("file", "")), description=str(d.get("description", "")))
        for d in data
    ]
    return ActionResult.success(sdl.EntityList[DropIn](items=items),
                                summary=f"{len(items)} drop-in file(s)")


@chat.function(
    "get_environment_type",
    description=(
        "Read WordPress 5.5+'s own declared environment type for a connected site: "
        "production, staging, development, or local (defaults to 'production' if the site "
        "never set WP_ENVIRONMENT_TYPE). Reads through the Imperal Bridge plugin (2.7.0+)."
    ),
    action_type="read", data_model=EnvironmentType,
)
async def get_environment_type(ctx, params: SiteIdParams) -> ActionResult:
    """GET /imperal/v1/deploy/environment-type."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, BRIDGE_ENVIRONMENT_TYPE_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"get_environment_type request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    env = str(body.get("environment_type", "production"))
    return ActionResult.success(
        EnvironmentType(id=params.site_id, title=f"Environment {params.site_id}", kind="wp_environment_type",
                        site_id=params.site_id, environment_type=env),
        summary=f"Environment: {env}")
