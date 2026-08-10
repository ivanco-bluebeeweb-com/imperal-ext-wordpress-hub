"""Rank Math llms.txt settings -- which post types/taxonomies are listed in the
dynamically-served /llms.txt file (Rank Math's AI-crawler guidance file, the
AI-era analogue of robots.txt), plus a link-count limit and free-text extra
Markdown appended to it.

Verified against seo-by-rank-math trunk (includes/modules/llms/class-llms-txt.php,
options.php) before writing a single line: the llms-txt module hooks 'init' to add
a rewrite rule for /llms.txt and 'template_redirect' to serve it dynamically -- it
is NOT exposed by Rank Math's own REST API at all (unlike Instant Indexing), so
this goes through Imperal Bridge SECTION 8 (/wp-json/imperal/v1/llmstxt), the same
way SECTION 7 handles robots.txt. The four settings (llms_post_types,
llms_taxonomies, llms_limit, llms_extra_content) live in the SAME
`rank-math-options-general` WP option that robots_txt_content lives in.

Unlike robots.txt, the llms-txt module is NOT active by default on a fresh Rank
Math install (confirmed absent from class-installer.php's create_misc_options()
default $modules array) -- module_active in the response reflects that, and a
404-style "not found" response from the Bridge here means either the Bridge is
missing/outdated, or Rank Math itself isn't installed; module_active=false in a
successful response just means the site owner hasn't turned the module on yet
(activating a Rank Math module happens on Rank Math's own module-manager screen,
which has no single-module REST toggle, so that step is intentionally not
exposed here).
"""
from imperal_sdk import ActionResult

from app import chat
from models import LlmsTxtParams, LlmsTxtSettings, UpdateLlmsTxtParams
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post

BRIDGE_PATH = "/wp-json/imperal/v1/llmstxt"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin on the site (bridge/imperal-bridge "
    "in the connector repo), version 2.5.0 or later."
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
    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal Bridge plugin installed, or it is "
                "older than the version that adds llms.txt settings. " + _INSTALL_HINT,
                retryable=False, code="LLMSTXT_BRIDGE_MISSING")
        if wp_code.startswith("imperal_llmstxt_invalid_") or wp_code == "imperal_llmstxt_nothing_to_update":
            return ActionResult.error(
                wp_message or "Invalid llms.txt settings.", retryable=False, code="LLMSTXT_INVALID")
        if wp_message:
            return ActionResult.error(
                wp_message, retryable=status_code >= 500, code=wp_error_code(status_code))
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _to_settings(site_id, body):
    return LlmsTxtSettings(
        id=site_id, title="llms.txt", kind="rank_math_llms_txt",
        module_active=bool(body.get("module_active", False)),
        llms_txt_url=body.get("llms_txt_url", "") or "",
        post_types=list(body.get("post_types", []) or []),
        taxonomies=list(body.get("taxonomies", []) or []),
        limit=int(body.get("limit", 100) or 100),
        extra_content=body.get("extra_content", "") or "",
    )


@chat.function(
    "get_llms_txt_settings",
    description=(
        "Read Rank Math's llms.txt settings -- which post types and taxonomies are listed in "
        "the dynamically-served /llms.txt file (the AI-crawler guidance file, an analogue of "
        "robots.txt aimed at LLMs), the per-type link limit, extra Markdown appended to the "
        "file, whether Rank Math's llms-txt module is active (it is NOT active by default), "
        "and the file's live URL. Requires the Imperal Bridge plugin."
    ),
    action_type="read", data_model=LlmsTxtSettings,
)
async def get_llms_txt_settings(ctx, params: LlmsTxtParams) -> ActionResult:
    """GET /imperal/v1/llmstxt."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = _to_settings(params.site_id, body)
    summary = (
        f"llms.txt is active at {result.llms_txt_url}" if result.module_active
        else "Rank Math's llms-txt module is not active on this site — its settings are "
             "stored but /llms.txt is not being served"
    )
    return ActionResult.success(result, summary=summary)


@chat.function(
    "update_llms_txt_settings",
    description=(
        "Update Rank Math's llms.txt settings: which post types/taxonomies to list, the "
        "per-type link limit, and/or extra Markdown appended to the file. Only the fields you "
        "pass are changed -- omit a field to leave it as-is. Pass an empty string for "
        "extra_content to clear it. Does not turn the llms-txt module itself on or off -- that "
        "is a Rank Math module-manager setting with no single-module REST toggle. Requires the "
        "Imperal Bridge plugin."
    ),
    action_type="write", data_model=LlmsTxtSettings,
    effects=["wp.llms_txt_settings_update"], event="wordpress-hub.update_llms_txt_settings",
)
async def update_llms_txt_settings(ctx, params: UpdateLlmsTxtParams) -> ActionResult:
    """POST /imperal/v1/llmstxt."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    payload = {}
    if params.post_types is not None:
        payload["post_types"] = params.post_types
    if params.taxonomies is not None:
        payload["taxonomies"] = params.taxonomies
    if params.limit is not None:
        payload["limit"] = params.limit
    if params.extra_content is not None:
        payload["extra_content"] = params.extra_content
    if not payload:
        return ActionResult.error(
            "Pass at least one field to update (post_types, taxonomies, limit, extra_content).",
            retryable=False, code="LLMSTXT_NO_FIELDS")
    try:
        r = await wp_post(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw,
                           json=payload)
    except Exception as e:
        await ctx.log(f"update_llms_txt_settings request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True,
                                   code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = _to_settings(params.site_id, body)
    return ActionResult.success(result, summary="llms.txt settings updated",
                                 refresh_panels=["center"])
