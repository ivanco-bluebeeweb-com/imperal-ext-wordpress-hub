"""Core and plugin integrity checks (Group P).

WP-CLI's documented `wp core verify-checksums` downloads the official
WordPress.org checksum manifest without loading WordPress, then compares it
with the local core files. `wp plugin verify-checksums <plugin>` verifies one
explicit WordPress.org plugin. These are SSH/WP-CLI-only deliberately: core
REST does not offer equivalent file checks and a Bridge route would run inside
the potentially modified WordPress process. Plugin checksums are requested for
one plugin name returned by list_plugins; premium/custom plugins may not have
WordPress.org checksums, and WP-CLI's own response is surfaced unchanged.
"""
from imperal_sdk import ActionResult

from app import chat
from models import PluginChecksumParams, SiteIdParams, ChecksumVerificationResult
import storage
import wp_cli


async def _ssh_credential(ctx, site_id: str):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    cred = await storage.get_ssh_cred(ctx, site_id)
    if not cred:
        return None, ActionResult.error(
            "This integrity check needs SSH access because WP-CLI verifies files against "
            "WordPress.org checksums. Add SSH access with add_ssh.",
            retryable=False, code="SSH_NOT_CONFIGURED")
    return cred, None


def _verification_result(site_id: str, target: str, result: dict) -> ActionResult:
    verified = bool(result.get("verified"))
    output = str(result.get("output", ""))
    return ActionResult.success(
        ChecksumVerificationResult(
            id=f"{site_id}:{target}", title=f"Checksum verification: {target}",
            kind="wp_checksum_verification", site_id=site_id, target=target,
            verified=verified, output=output,
        ),
        summary=(f"{target}: checksums verify." if verified else
                 f"{target}: checksum verification found differences."),
    )


@chat.function(
    "verify_core_checksums",
    description=(
        "Verify WordPress core files against the official WordPress.org checksums via "
        "WP-CLI (`wp core verify-checksums`). Read-only and SSH-only: it does not load "
        "WordPress during verification, which makes it useful when checking for modified "
        "core files. A mismatch is reported as a finding, never silently treated as a pass."
    ),
    action_type="read", data_model=ChecksumVerificationResult,
)
async def verify_core_checksums(ctx, params: SiteIdParams) -> ActionResult:
    """Compare installed WordPress core files against WordPress.org checksums."""
    cred, err = await _ssh_credential(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.verify_core_checksums(cred)
    except Exception as exc:
        await ctx.log(f"verify_core_checksums: {exc}", level="error")
        return ActionResult.error("Could not verify core checksums over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"verify_core_checksums: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)
    return _verification_result(params.site_id, "core", result)


@chat.function(
    "verify_plugin_checksums",
    description=(
        "Verify one installed WordPress.org plugin's files against its official checksums via "
        "WP-CLI (`wp plugin verify-checksums <plugin>`). Pass an exact plugin slug from "
        "list_plugins. Premium, custom, or non-WordPress.org plugins may have no official "
        "checksum manifest; that response is reported honestly, not as a pass or a failure."
    ),
    action_type="read", data_model=ChecksumVerificationResult,
)
async def verify_plugin_checksums(ctx, params: PluginChecksumParams) -> ActionResult:
    """Compare one named WordPress.org plugin against its published checksums."""
    cred, err = await _ssh_credential(ctx, params.site_id)
    if err:
        return err
    try:
        result, cli_error = await wp_cli.verify_plugin_checksums(cred, params.plugin)
    except Exception as exc:
        await ctx.log(f"verify_plugin_checksums: {exc}", level="error")
        return ActionResult.error("Could not verify plugin checksums over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"verify_plugin_checksums: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=False)
    return _verification_result(params.site_id, f"plugin:{params.plugin}", result)
