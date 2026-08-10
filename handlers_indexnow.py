"""Rank Math Instant Indexing (IndexNow): submit URLs, read/clear the
submission log, and reset the site's IndexNow key.

UNLIKE every other Rank Math integration in this app, Instant Indexing
registers its OWN REST routes directly on WordPress core's REST server --
verified against seo-by-rank-math trunk (includes/modules/instant-indexing/
class-rest.php, class-instant-indexing.php, class-api.php):

  RankMath\\Instant_Indexing\\Instant_Indexing::__construct() hooks
  'rest_api_init' -> init_rest_api() -> (new Rest())->register_routes(),
  independent of the Imperal Bridge. So this module talks straight to
  <site>/wp-json/rankmath/v1/in/... with the connected Application Password
  -- no Bridge plugin needed at all, the same way stock WordPress core
  endpoints work.

Routes (namespace 'rankmath/v1/in', confirmed in class-rest.php):
  POST /submitUrls  {urls: "<newline-joined string>"}  -> {success, message}
  POST /getLog      {filter: all|manual|auto}           -> {data: [...], total}
  POST /clearLog    {filter: all|manual|auto}           -> {status: "ok"}
  POST /resetKey    (no body)                            -> {status, key, location}

Each log entry (class-api.php log()/get_log()): url, status (int HTTP code),
manual_submission (bool), message, time (unix), plus timeFormatted /
timeHumanReadable added by the REST callback itself.

'rest_no_route' on any of these four means one of: Rank Math isn't installed,
the installed version predates Instant Indexing's REST routes (added
1.0.49), or the Instant Indexing module is switched off in Rank Math's own
module manager -- all three collapse to the same user-facing message since
this app cannot tell them apart without another round-trip.

Module activation itself is intentionally NOT exposed here: Instant
Indexing is one of the modules Rank Math turns on by default on a fresh
install (includes/class-installer.php's create_misc_options()), so this
gap is about the rare site that disabled it, not the common case.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ClearIndexNowLogParams,
    ClearIndexNowLogResult,
    IndexNowKey,
    IndexNowLogEntry,
    IndexNowLogParams,
    IndexNowSubmitResult,
    ResetIndexNowKeyParams,
    SubmitIndexNowUrlsParams,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_post

BASE_PATH = "/wp-json/rankmath/v1/in"

_NOT_AVAILABLE_MESSAGE = (
    "Rank Math's Instant Indexing isn't reachable on this site — either Rank Math "
    "isn't installed, it's older than the version that added Instant Indexing's "
    "REST API, or the Instant Indexing module has been switched off in Rank Math's "
    "own dashboard (Rank Math SEO → Instant Indexing)."
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
            return ActionResult.error(_NOT_AVAILABLE_MESSAGE, retryable=False,
                                       code="INDEXNOW_NOT_AVAILABLE")
        if wp_code in ("empty_urls", "invalid_urls"):
            return ActionResult.error(
                wp_message or "No valid https:// URLs were provided.",
                retryable=False, code="INDEXNOW_INVALID_URLS")
        if wp_code == "submit_failed":
            return ActionResult.error(
                wp_message or "Rank Math could not reach the IndexNow API — try again shortly.",
                retryable=True, code="INDEXNOW_SUBMIT_FAILED")
        if wp_message:
            return ActionResult.error(
                wp_message, retryable=status_code >= 500, code=wp_error_code(status_code))
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


@chat.function(
    "submit_urls_to_indexnow",
    description=(
        "Submit one or more of this site's own URLs to Rank Math's Instant Indexing "
        "(IndexNow) API so participating search engines (Bing, Yandex, and others on the "
        "IndexNow protocol) crawl and re-index them right away, instead of waiting for their "
        "next scheduled crawl. Use right after publishing or significantly updating a page. "
        "Does not affect Google directly (Google is not an IndexNow participant)."
    ),
    action_type="write", data_model=IndexNowSubmitResult,
    effects=["wp.indexnow_submit"], event="wordpress-hub.submit_urls_to_indexnow",
)
async def submit_urls_to_indexnow(ctx, params: SubmitIndexNowUrlsParams) -> ActionResult:
    """POST /wp-json/rankmath/v1/in/submitUrls."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    urls_field = "\n".join(u.strip() for u in params.urls if u.strip())
    if not urls_field:
        return ActionResult.error(
            "Pass at least one non-empty https:// URL.", retryable=False, code="INDEXNOW_NO_URLS")
    try:
        r = await wp_post(ctx, base_url, f"{BASE_PATH}/submitUrls", username=username,
                           app_password=pw, json={"urls": urls_field})
    except Exception as e:
        await ctx.log(f"submit_urls_to_indexnow request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = IndexNowSubmitResult(
        id=params.site_id, title="IndexNow submission", kind="rank_math_indexnow_submit",
        submitted_count=len(params.urls), message=body.get("message", ""))
    return ActionResult.success(result, summary=body.get("message") or f"Submitted {len(params.urls)} URL(s)")


@chat.function(
    "list_indexnow_log",
    description=(
        "List Rank Math's own IndexNow submission history for this site -- which URLs were "
        "submitted, when, whether manually or automatically (on publish/update/trash), the API "
        "response status, and the result message. Rank Math keeps the last 100 entries."
    ),
    action_type="read", data_model=sdl.EntityList[IndexNowLogEntry],
)
async def list_indexnow_log(ctx, params: IndexNowLogParams) -> ActionResult:
    """POST /wp-json/rankmath/v1/in/getLog."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_post(ctx, base_url, f"{BASE_PATH}/getLog", username=username, app_password=pw,
                       json={"filter": params.filter})
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    data = body.get("data", []) if isinstance(body.get("data"), list) else []
    items = [
        IndexNowLogEntry(
            id=f"{params.site_id}-{i}", title=item.get("url", ""), kind="rank_math_indexnow_log_entry",
            url=item.get("url", ""), status=int(item.get("status", 0) or 0),
            manual_submission=bool(item.get("manual_submission", False)),
            message=item.get("message", ""), time_formatted=item.get("timeFormatted", ""),
            time_human_readable=item.get("timeHumanReadable", ""),
        )
        for i, item in enumerate(data) if isinstance(item, dict)
    ]
    return ActionResult.success(
        sdl.EntityList[IndexNowLogEntry](items=items), summary=f"{len(items)} IndexNow log entr{'y' if len(items)==1 else 'ies'}")


@chat.function(
    "clear_indexnow_log",
    description="Clear Rank Math's IndexNow submission log on this site (all entries, or just "
                "the manual or automatic ones). This only clears the history record -- it does "
                "not resubmit or unsubmit any URL.",
    action_type="write", data_model=ClearIndexNowLogResult,
    effects=["wp.indexnow_log_clear"], event="wordpress-hub.clear_indexnow_log",
)
async def clear_indexnow_log(ctx, params: ClearIndexNowLogParams) -> ActionResult:
    """POST /wp-json/rankmath/v1/in/clearLog."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_post(ctx, base_url, f"{BASE_PATH}/clearLog", username=username, app_password=pw,
                       json={"filter": params.filter})
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    return ActionResult.success(
        ClearIndexNowLogResult(id=params.site_id, title="IndexNow log cleared",
                                kind="rank_math_indexnow_log_clear", cleared=True),
        summary="IndexNow log cleared", refresh_panels=["center"])


@chat.function(
    "reset_indexnow_key",
    description=(
        "Generate a fresh IndexNow API key for this site and discard the old one, then return "
        "the new key and where it's hosted (a <key>.txt file at the site root, verified by "
        "IndexNow-participating search engines). Use only if the key may have leaked -- every "
        "past submission stays valid, but the OLD key file stops matching, so pending "
        "verification by search engines using the old key will fail until they see the new one."
    ),
    action_type="write", data_model=IndexNowKey,
    effects=["wp.indexnow_key_reset"], event="wordpress-hub.reset_indexnow_key",
)
async def reset_indexnow_key(ctx, params: ResetIndexNowKeyParams) -> ActionResult:
    """POST /wp-json/rankmath/v1/in/resetKey."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_post(ctx, base_url, f"{BASE_PATH}/resetKey", username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = IndexNowKey(
        id=params.site_id, title="IndexNow key reset", kind="rank_math_indexnow_key_reset",
        key=body.get("key", ""), location=body.get("location", ""))
    return ActionResult.success(result, summary="New IndexNow key generated")
