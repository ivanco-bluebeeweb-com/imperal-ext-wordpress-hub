"""Site maintenance: update one plugin, update WordPress core, force-run
due cron events.

Bridge-first, SSH-fallback -- same pattern as handlers_cache_cron.py and
handlers_logs.py: every one of these is the exact same WP core upgrade API
the wp-admin "Update Now" button and WordPress's own background auto-updates
call (Bridge SECTION 15, /imperal/v1/maintenance/*, 2.11.0+), so a site with
the Imperal Bridge plugin installed needs no SSH at all: `Plugin_Upgrader` /
`Core_Upgrader` driven by `Automatic_Upgrader_Skin` (the silent skin
WordPress's own background auto-update cron job uses), and the same
`_get_cron_array()` + `do_action_ref_array()` primitives SECTION 14 uses for
a single hook, just walking every hook whose timestamp has already passed.

SSH + WP-CLI (wp_cli.py) remains the fallback for sites without the Bridge
or whose Bridge predates 2.11.0. These are the three items the roadmap
(docs/2026-08-09-full-feature-roadmap.md §5.2) explicitly flagged as real,
recurring maintenance needs but held back pending a strong preview/confirm
story -- since `install_plugin` already established that a fixed-shape,
non-interpolated WP-CLI command with no shell-injection surface IS an
acceptable safety bar on this app (see its own docstring), the same bar
applies here: no `--all` bulk plugin update, no version pinning, no
caller-chosen cron event name beyond what's already scheduled -- exactly
the one guarded shape each operation needs and nothing more.
"""
from imperal_sdk import ActionResult

from app import chat
from models import (
    CoreUpdateResult,
    PluginUpdateResult,
    RunWpCronParams,
    UpdateCoreParams,
    UpdatePluginParams,
    WpCronRunResult,
)
import storage
import wp_cli
from wp_client import wp_get, wp_post

BRIDGE_MAINTENANCE_UPDATE_PLUGIN_PATH = "/wp-json/imperal/v1/maintenance/update-plugin"
BRIDGE_MAINTENANCE_UPDATE_CORE_PATH = "/wp-json/imperal/v1/maintenance/update-core"
BRIDGE_MAINTENANCE_RUN_DUE_CRON_PATH = "/wp-json/imperal/v1/maintenance/run-due-cron"
BRIDGE_MAINTENANCE_INSTALL_PLUGIN_PATH = "/wp-json/imperal/v1/maintenance/install-plugin"
BRIDGE_MAINTENANCE_PURGE_CACHE_PATH = "/wp-json/imperal/v1/maintenance/purge-cache"
BRIDGE_MAINTENANCE_LIST_PLUGINS_PATH = "/wp-json/imperal/v1/maintenance/list-plugins"


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


async def _bridge_post(ctx, base_url, username, pw, path, json_body=None):
    """POST to a Bridge maintenance route. Returns the body dict on 200, else
    None to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_post(ctx, base_url, path, username=username, app_password=pw, json=json_body)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


async def _bridge_get(ctx, base_url, username, pw, path, params=None):
    """GET a Bridge maintenance route. Returns the body dict on 200, else
    None to signal "fall back to SSH" -- never raises, this is a probe."""
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
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


@chat.function(
    "update_plugin",
    description=(
        "Update ONE already-installed WordPress plugin to its latest version. Reads "
        "through the Imperal Bridge plugin if it's installed (the same WordPress "
        "upgrader wp-admin's own 'Update Now' link uses), or falls back to SSH + "
        "WP-CLI (`wp plugin update <slug>`) if SSH is configured with add_ssh. Pass a "
        "slug from list_plugins/list_native_plugins — never a guessed slug."
    ),
    action_type="write",
    data_model=PluginUpdateResult,
    effects=["wp.update_plugin"],
    event="wordpress-hub.update_plugin",
)
async def update_plugin(ctx, params: UpdatePluginParams) -> ActionResult:
    """Bridge-first (/maintenance/update-plugin), SSH-fallback (`wp plugin update`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(
        ctx, base_url, username, pw, BRIDGE_MAINTENANCE_UPDATE_PLUGIN_PATH,
        json_body={"slug": params.slug},
    )
    if body is not None:
        if body.get("updated"):
            output = f"Updated to {body.get('version', 'the latest version')}."
        else:
            output = body.get("message", "Already up to date.")
        return ActionResult.success(
            PluginUpdateResult(
                id=params.slug, title=params.slug, kind="wp_plugin_update",
                slug=params.slug, output=output,
            ),
            summary=output,
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        result, cli_error = await wp_cli.update_plugin(cred, params.slug)
    except Exception as e:
        await ctx.log(f"update_plugin: {e}", level="error")
        return ActionResult.error("Could not update the plugin over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"update_plugin: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    output = (result or {}).get("raw", "") if isinstance(result, dict) else (result or "")
    return ActionResult.success(
        PluginUpdateResult(
            id=params.slug, title=params.slug, kind="wp_plugin_update",
            slug=params.slug, output=output,
        ),
        summary=f"Updated plugin '{params.slug}'.",
    )


@chat.function(
    "update_core",
    description=(
        "Update WordPress core to the latest version. Reads through the Imperal "
        "Bridge plugin if it's installed (the same WordPress upgrader wp-admin's own "
        "'Update Now' link uses), or falls back to SSH + WP-CLI (`wp core update`) if "
        "SSH is configured with add_ssh. Runs the update immediately with no version "
        "pinning — always the latest available core release."
    ),
    action_type="write",
    data_model=CoreUpdateResult,
    effects=["wp.update_core"],
    event="wordpress-hub.update_core",
)
async def update_core(ctx, params: UpdateCoreParams) -> ActionResult:
    """Bridge-first (/maintenance/update-core), SSH-fallback (`wp core update`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_MAINTENANCE_UPDATE_CORE_PATH)
    if body is not None:
        if body.get("updated"):
            output = f"Updated WordPress core to {body.get('version', 'the latest version')}."
        else:
            output = body.get("message", "WordPress core is already up to date.")
        return ActionResult.success(
            CoreUpdateResult(
                id=params.site_id, title="WordPress core", kind="wp_core_update", output=output,
            ),
            summary=output,
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        result, cli_error = await wp_cli.update_core(cred)
    except Exception as e:
        await ctx.log(f"update_core: {e}", level="error")
        return ActionResult.error("Could not update WordPress core over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"update_core: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    output = (result or {}).get("raw", "") if isinstance(result, dict) else (result or "")
    return ActionResult.success(
        CoreUpdateResult(
            id=params.site_id, title="WordPress core", kind="wp_core_update", output=output,
        ),
        summary="Updated WordPress core.",
    )


@chat.function(
    "run_wp_cron",
    description=(
        "Force every due WordPress cron event to run now. Reads through the Imperal "
        "Bridge plugin if it's installed (the same _get_cron_array()/"
        "do_action_ref_array() WordPress core itself uses), or falls back to SSH + "
        "WP-CLI (`wp cron event run --due-now`) if SSH is configured with add_ssh. "
        "Only events already past their scheduled time are run — nothing is "
        "rescheduled early."
    ),
    action_type="write",
    data_model=WpCronRunResult,
    effects=["wp.run_cron"],
    event="wordpress-hub.run_wp_cron",
)
async def run_wp_cron(ctx, params: RunWpCronParams) -> ActionResult:
    """Bridge-first (/maintenance/run-due-cron), SSH-fallback (`wp cron event run --due-now`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_MAINTENANCE_RUN_DUE_CRON_PATH)
    if body is not None:
        ran = body.get("ran", [])
        count = body.get("ran_count", len(ran))
        output = f"Ran {count} due event(s): {', '.join(ran)}" if ran else "No due events to run."
        return ActionResult.success(
            WpCronRunResult(
                id=params.site_id, title="due cron events", kind="wp_cron_run", output=output,
            ),
            summary=f"Ran {count} due cron event(s).",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        output, cli_error = await wp_cli.run_wp_cron(cred)
    except Exception as e:
        await ctx.log(f"run_wp_cron: {e}", level="error")
        return ActionResult.error("Could not run cron over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"run_wp_cron: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        WpCronRunResult(
            id=params.site_id, title="due cron events", kind="wp_cron_run", output=output or "",
        ),
        summary="Ran due cron events.",
    )
