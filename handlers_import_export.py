"""Import / Export (WXR — WordPress eXtended RSS): export_wxr and import_wxr.

export_wxr is Bridge-first, SSH-fallback -- it wraps WordPress core's own
export_wp() (wp-admin/includes/export.php), the exact function Tools >
Export's "Download Export File" button calls, requiring no plugin beyond
WordPress itself (Bridge SECTION 18, /imperal/v1/export/wxr, 2.14.0+, or
`wp export --stdout` over SSH). Both paths are capped at ~2MB of XML text,
the same cap export_database_dump uses, with the same "scope the filters
down" guidance rather than a silent truncation.

import_wxr is SSH-ONLY, deliberately: the class that does the real import
work, WP_Import, ships in the separate `wordpress-importer` plugin (not
WordPress core), and its only public entry point (dispatch()) is a
web-admin wizard built entirely around $_GET/$_POST step state -- there is
no safe, faithful way to drive it from a REST callback. WP-CLI's own `wp
import` exists specifically to give that plugin a clean headless entry
point, so that is the one path used here. If the site has no SSH configured,
or the wordpress-importer plugin isn't active there, this returns a clear
error rather than a silent no-op -- never fabricating a fake success.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ExportWxrParams,
    ImportWxrParams,
    SiteIdParams,
    WxrExportResult,
    WxrImportResult,
)
import storage
import wp_cli
from wp_client import wp_get

BRIDGE_EXPORT_WXR_PATH = "/wp-json/imperal/v1/export/wxr"


class BridgeError:
    """Sentinel meaning: the Bridge answered (not absent, not unreachable) but
    explicitly refused the request with its own message -- see handlers_
    database.py's identical sentinel for the full rationale."""
    def __init__(self, message: str):
        self.message = message


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
            "No stored credential for this site — reconnect it with connect_site.",
            retryable=False, code="SITE_NOT_CONNECTED")
    return (record["url"], record["username"], pw), None


async def _bridge_get(ctx, base_url, username, pw, path, params=None):
    """GET a Bridge route. Returns the body dict on 200. On any other status,
    returns a BridgeError carrying the Bridge's own JSON error message (e.g.
    "export too large") if the body parsed as a dict -- that is the Bridge
    answering and explicitly refusing, NOT the Bridge being absent, so callers
    must surface it rather than silently falling back to SSH. Only a
    transport failure or a non-JSON body returns None, the real "fall back to
    SSH" signal."""
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception:
        return None
    if not isinstance(r.body, dict):
        return None
    if r.status_code != 200:
        if r.body.get("code") == "rest_no_route":
            return None  # Bridge doesn't register this route -- absent/outdated, fall back to SSH.
        return BridgeError(r.body.get("message") or f"Bridge request failed (HTTP {r.status_code}).")
    return r.body


def _no_bridge_no_ssh_error():
    return ActionResult.error(
        "Neither the Imperal Bridge plugin nor SSH is available for this site. "
        "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
        code="SSH_NOT_CONFIGURED")


@chat.function(
    "export_wxr",
    description=(
        "Export the site's content as a WXR (WordPress eXtended RSS) document — the same "
        "format Tools > Export produces, importable into any WordPress site. Optionally "
        "scoped by content/post type, author, category, date range, or status. Reads "
        "through the Imperal Bridge plugin if it's installed (core's own export_wp(), no "
        "extra plugin needed), or falls back to SSH + WP-CLI (`wp export --stdout`) if SSH "
        "is configured with add_ssh. Capped at ~2MB of XML text — narrow the filters if the "
        "export is refused as too large. WXR does not include site options/settings or the "
        "attachment FILES themselves, only their metadata."
    ),
    action_type="read", data_model=WxrExportResult,
)
async def export_wxr(ctx, params: ExportWxrParams) -> ActionResult:
    """Bridge-first (/export/wxr GET), SSH-fallback (`wp export --stdout`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    content = params.post_type or params.content or "all"

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_EXPORT_WXR_PATH, params={
        "content": content, "author": params.author, "category": params.category,
        "start_date": params.start_date, "end_date": params.end_date, "status": params.status,
    })
    if isinstance(body, BridgeError):
        return ActionResult.error(body.message, retryable=False, code="BRIDGE_REQUEST_FAILED")
    if body is not None:
        xml = body.get("xml", "")
        return ActionResult.success(
            WxrExportResult(
                id=params.site_id, title="WXR export", kind="wp_wxr_export",
                site_id=params.site_id, xml=xml, size_bytes=body.get("size_bytes", len(xml)),
                post_count=body.get("post_count", 0),
            ),
            summary=f"Exported WXR containing {body.get('post_count', 0)} items "
                    f"({body.get('size_bytes', len(xml))} bytes).",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        result, cli_error = await wp_cli.export_wxr(
            cred, content=content, author=params.author, category=params.category,
            start_date=params.start_date, end_date=params.end_date, status=params.status,
        )
    except Exception as e:
        await ctx.log(f"export_wxr: {e}", level="error")
        return ActionResult.error("Could not export WXR over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"export_wxr: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        WxrExportResult(
            id=params.site_id, title="WXR export", kind="wp_wxr_export",
            site_id=params.site_id, xml=result["xml"], size_bytes=result["size_bytes"],
            post_count=result.get("post_count", 0),
        ),
        summary=f"Exported WXR ({result['size_bytes']} bytes) over SSH.",
    )


@chat.function(
    "import_wxr",
    description=(
        "Import a WXR (WordPress eXtended RSS) document into the site — the same format "
        "Tools > Import's WordPress importer accepts. SSH-ONLY: this needs WP-CLI's own "
        "`wp import`, backed by the wordpress-importer plugin, which has no safe headless "
        "REST equivalent (its only entry point is a web-admin upload wizard). Requires SSH "
        "configured with add_ssh, AND the wordpress-importer plugin installed and active on "
        "the target site (install_plugin with slug_or_url='wordpress-importer' if it's "
        "missing) — reports a clear error rather than a silent no-op if either is missing."
    ),
    action_type="write", data_model=WxrImportResult,
    effects=["wp.import_wxr"], event="wordpress-hub.import_wxr",
)
async def import_wxr(ctx, params: ImportWxrParams) -> ActionResult:
    """SSH-only (`wp import -` fed the WXR over stdin) — no Bridge equivalent exists."""
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "import_wxr requires SSH access — WP_Import (from the wordpress-importer plugin) "
            "has no safe headless REST equivalent. Add SSH access with add_ssh, and make sure "
            "the wordpress-importer plugin is installed and active on the target site.",
            retryable=False, code="SSH_NOT_CONFIGURED")
    try:
        result, cli_error = await wp_cli.import_wxr(
            cred, wxr_xml=params.wxr_xml, authors=params.authors,
            skip_attachments=params.skip_attachments,
        )
    except Exception as e:
        await ctx.log(f"import_wxr: {e}", level="error")
        return ActionResult.error("Could not import WXR over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"import_wxr: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=False if "not active" in cli_error else True)

    return ActionResult.success(
        WxrImportResult(
            id=params.site_id, title="WXR import", kind="wp_wxr_import",
            site_id=params.site_id, imported_count=result["imported"],
            skipped_count=result["skipped"], output=result["output"],
        ),
        summary=f"Imported {result['imported']} item(s), skipped {result['skipped']} "
                f"already-imported item(s).",
    )
