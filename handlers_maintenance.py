"""SSH/WP-CLI site maintenance: update one plugin, update WordPress core,
force-run due cron events.

These are the three items the roadmap (docs/2026-08-09-full-feature-roadmap.md
§5.2) explicitly flagged as real, recurring maintenance needs but held back
pending a strong preview/confirm story -- since `install_plugin` already
established that a fixed-shape, non-interpolated WP-CLI command with no
shell-injection surface IS an acceptable safety bar on this app (see its own
docstring), the same bar applies here: no `--all` bulk plugin update, no
version pinning, no caller-chosen cron event name -- exactly the one
guarded shape each operation needs and nothing more.
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
    "update_plugin",
    description=(
        "Update ONE already-installed WordPress plugin to its latest version via "
        "WP-CLI (`wp plugin update <slug>`). Requires SSH access configured with add_ssh. "
        "Updates exactly one named plugin, never all plugins at once — call list_plugins "
        "first to see which ones have an update available."
    ),
    action_type="write",
    data_model=PluginUpdateResult,
    effects=["wp.update_plugin"],
    event="wordpress-hub.update_plugin",
)
async def update_plugin(ctx, params: UpdatePluginParams) -> ActionResult:
    """Update one plugin over SSH via `wp plugin update <slug>`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.update_plugin(cred, params.slug)
    except Exception as e:
        await ctx.log(f"update_plugin: {e}", level="error")
        return ActionResult.error("Could not update the plugin over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"update_plugin: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    output = (result or {}).get("raw", "")
    return ActionResult.success(
        PluginUpdateResult(
            id=params.slug, title=f"plugin {params.slug}", kind="wp_plugin_update",
            slug=params.slug, output=output,
        ),
        summary=f"Updated plugin '{params.slug}'.",
    )


@chat.function(
    "update_core",
    description=(
        "Update WordPress core to the latest version via WP-CLI (`wp core update`). "
        "Requires SSH access configured with add_ssh. Always updates to the latest "
        "release, matching wp-admin's own 'Update Now' button — no version pinning."
    ),
    action_type="write",
    data_model=CoreUpdateResult,
    effects=["wp.update_core"],
    event="wordpress-hub.update_core",
)
async def update_core(ctx, params: UpdateCoreParams) -> ActionResult:
    """Update WordPress core over SSH via `wp core update`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.update_core(cred)
    except Exception as e:
        await ctx.log(f"update_core: {e}", level="error")
        return ActionResult.error("Could not update WordPress core over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"update_core: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    output = (result or {}).get("raw", "")
    return ActionResult.success(
        CoreUpdateResult(
            id=params.site_id, title="WordPress core", kind="wp_core_update", output=output,
        ),
        summary="Updated WordPress core to the latest version.",
    )


@chat.function(
    "run_wp_cron",
    description=(
        "Force every due WordPress cron event to run now via WP-CLI "
        "(`wp cron event run --due-now`). Requires SSH access configured with add_ssh. "
        "Use this to unstick a site whose scheduled tasks (emails, publish-at-time posts, "
        "plugin housekeeping) have silently stopped firing on their own. Runs only events "
        "already due — never a single caller-chosen event by name."
    ),
    action_type="write",
    data_model=WpCronRunResult,
    effects=["wp.run_cron"],
    event="wordpress-hub.run_wp_cron",
)
async def run_wp_cron(ctx, params: RunWpCronParams) -> ActionResult:
    """Force-run due cron events over SSH via `wp cron event run --due-now`."""
    cred, err = await _ssh_cred(ctx, params.site_id)
    if err:
        return err
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
            id=params.site_id, title="WP cron run", kind="wp_cron_run", output=output or "",
        ),
        summary="Ran all due cron events.",
    )
