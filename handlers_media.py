"""Add an existing public image URL to a site's media library, and
optionally attach it as a post's featured image.

ACCESS STRATEGY
---------------
Imperal's outbound HTTP client (`ctx.http`) decodes every non-JSON response
body as UTF-8 text — correct for HTML/JSON APIs, but it corrupts arbitrary
binary bytes, so a naive "fetch the image with ctx.http, re-upload the
bytes" flow would silently produce a broken attachment every time. There is
no safe way to move image bytes through this connector's own HTTP client.

Instead, the Imperal Media Bridge companion plugin (`/wp-json/imperal/v1/
media/sideload`) asks WordPress to fetch its OWN copy of a public HTTPS
image via `media_sideload_image()` — the same mechanism behind the native
"Insert from URL" flow in the block editor. Imperal only ever sends a URL,
never bytes. There is no fallback tier: without the bridge there is no safe
way to add hosted external images at all, so a missing bridge is a hard
stop, same as the Builder Bridge.
"""

from imperal_sdk import ActionResult

from app import chat
from models import UploadMediaParams, MediaUploadResult, MediaSupport, SiteIdParams
from wp_client import wp_post, wp_get, wp_error_message, wp_error_code
import storage

BRIDGE_SIDELOAD_PATH = "/wp-json/imperal/v1/media/sideload"
BRIDGE_STATUS_PATH = "/wp-json/imperal/v1/media/status"

_INSTALL_HINT = (
    "Install the Imperal Media Bridge plugin on the site (bridge/imperal-media-bridge "
    "in the connector repo) to add hosted images to the media library."
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


def _http_failure(status_code, body):
    """Map a Media Bridge HTTP failure onto a structured ActionResult."""
    retry = status_code >= 500 or status_code == 429
    message = wp_error_message(status_code)
    code = wp_error_code(status_code)

    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        mapping = {
            "imperal_media_invalid_url": ("MEDIA_INVALID_URL", "source_url must be a well-formed URL."),
            "imperal_media_insecure_url": ("MEDIA_INSECURE_URL", "source_url must use https://."),
            "imperal_media_private_host": ("MEDIA_PRIVATE_HOST", "source_url points at a private/internal host, which is not allowed."),
            "imperal_media_post_not_found": ("MEDIA_POST_NOT_FOUND", "No post matched that id."),
            "imperal_media_ambiguous_slug": ("MEDIA_SLUG_AMBIGUOUS", "Several items share that slug — pass post_type or post_id."),
            "imperal_media_forbidden": ("WP_FORBIDDEN", "That WordPress user cannot upload media or edit this item."),
            "imperal_media_sideload_failed": ("MEDIA_SIDELOAD_FAILED", "WordPress could not fetch that image."),
        }
        if wp_code in mapping:
            err_code, fallback = mapping[wp_code]
            return ActionResult.error(wp_message or fallback, retryable=False, code=err_code)
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal Media Bridge plugin installed. " + _INSTALL_HINT,
                retryable=False, code="MEDIA_BRIDGE_MISSING")

    return ActionResult.error(message, retryable=retry, code=code)


@chat.function(
    "upload_media",
    description=("Add a publicly reachable https:// image URL to a connected WordPress site's "
                 "media library, and optionally set it as a post's featured image. WordPress "
                 "fetches the image itself (via the Imperal Media Bridge plugin) — Imperal never "
                 "downloads or re-uploads the image bytes. Use the returned attachment id/url as "
                 "featured_media_id, or in an 'image' content block, on create_post/update_post."),
    action_type="write",
    data_model=MediaUploadResult,
    effects=["wp.media_upload"],
    event="wp-site-connector.upload_media",
)
async def upload_media(ctx, params: UploadMediaParams) -> ActionResult:
    """Sideload one external image into the site's media library."""
    if params.set_featured and not params.post_id:
        return ActionResult.error(
            "set_featured requires post_id — tell me which post/page gets this featured image.",
            retryable=False, code="MEDIA_TARGET_MISSING")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = {"source_url": params.source_url}
    if params.post_id:
        body["post_id"] = params.post_id
    if params.alt_text:
        body["alt_text"] = params.alt_text
    if params.caption:
        body["caption"] = params.caption
    if params.set_featured:
        body["set_featured"] = True

    try:
        r = await wp_post(ctx, base_url, BRIDGE_SIDELOAD_PATH, username=username, app_password=pw,
                          json=body, timeout=60)
    except Exception as e:
        await ctx.log(f"upload_media request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code not in (200, 201) or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    payload = r.body
    attachment_id = int(payload.get("attachment_id", 0) or 0)
    result = MediaUploadResult(
        id=str(attachment_id), title=params.alt_text or params.source_url, kind="wp_media_upload",
        url=str(payload.get("url", "") or ""),
        width=payload.get("width"),
        height=payload.get("height"),
        attached_to=payload.get("attached_to"),
        featured_set=bool(payload.get("featured_set", False)),
    )
    bits = [f"Uploaded media #{attachment_id}"]
    if result.attached_to:
        bits.append(f"attached to post #{result.attached_to}")
    if result.featured_set:
        bits.append("set as featured image")
    return ActionResult.success(result, summary=", ".join(bits) + ".")


@chat.function(
    "check_media_support",
    description=("Check whether a connected WordPress site can add hosted images to its media "
                 "library via upload_media — whether the Imperal Media Bridge plugin is installed "
                 "and whether the connected user can upload files."),
    action_type="read",
    data_model=MediaSupport,
)
async def check_media_support(ctx, params: SiteIdParams) -> ActionResult:
    """Report Media Bridge presence and upload capability for a site."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, BRIDGE_STATUS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"check_media_support request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 404:
        return ActionResult.error(
            "This site does not have the Imperal Media Bridge plugin installed. " + _INSTALL_HINT,
            retryable=False, code="MEDIA_BRIDGE_MISSING")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    body = r.body
    bridge_version = str(body.get("bridge_version", "") or "")
    can_upload = bool(body.get("can_upload", False))
    result = MediaSupport(
        id=params.site_id, title="Media bridge support", kind="wp_media_support",
        bridge_version=bridge_version, can_upload=can_upload,
    )
    summary = (f"Media bridge v{bridge_version} — "
              f"{'this user can upload media' if can_upload else 'this user CANNOT upload media'}.")
    return ActionResult.success(result, summary=summary)
