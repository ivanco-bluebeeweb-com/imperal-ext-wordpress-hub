"""Rank Math site-wide data: SEO score, robots.txt editor, sitemap module
status, and the 404 Monitor log.

These are distinct from per-post SEO meta (handlers_seo.py, Bridge SECTION 1)
and from the Redirections module (handlers_redirects.py, Bridge SECTION 5) --
all four pieces here live in different storage (postmeta for the score, a WP
option for robots.txt, another WP option for the sitemap module flag, and
Rank Math's own 404-logs table), verified against seo-by-rank-math 1.0.275
source before writing a single line here (see Bridge SECTION 7's own comment
for the exact classes/keys checked). This module talks exclusively to
Imperal Bridge SECTION 7 (/wp-json/imperal/v1/rankmath/...) -- there is no
stock-WordPress fallback tier for any of these, since none of it is exposed
by WordPress core or by Rank Math's own REST API.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    Delete404HitParams,
    GetSeoScoreParams,
    Hit404,
    Hit404DeleteResult,
    List404HitsParams,
    RobotsTxt,
    RobotsTxtParams,
    SeoScoreResult,
    SitemapStatus,
    UpdateRobotsTxtParams,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post, wp_request

BRIDGE_PATH = "/wp-json/imperal/v1/rankmath"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin on the site (bridge/imperal-bridge "
    "in the connector repo), version 2.4.0 or later."
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


def _failure(status_code, body, *, not_available_code="", not_available_hint=""):
    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal Bridge plugin installed, or it is "
                "older than the version that adds Rank Math site-wide data. " + _INSTALL_HINT,
                retryable=False, code="RANKMATH_BRIDGE_MISSING")
        if not_available_code and wp_code == not_available_code:
            return ActionResult.error(
                wp_message or not_available_hint, retryable=False, code="RANKMATH_MODULE_MISSING")
        if wp_code == "imperal_rankmath_post_not_found":
            return ActionResult.error(
                wp_message or "No post with that id.", retryable=False, code="POST_NOT_FOUND")
        if wp_code == "imperal_rankmath_404_not_found":
            return ActionResult.error(
                wp_message or "No 404 log entry with that id.", retryable=False, code="HIT_404_NOT_FOUND")
        if wp_code == "imperal_rankmath_invalid_content":
            return ActionResult.error(
                wp_message or "Invalid robots.txt content.", retryable=False, code="ROBOTS_TXT_INVALID")
        if wp_message:
            return ActionResult.error(
                wp_message, retryable=status_code >= 500, code=wp_error_code(status_code))
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


@chat.function(
    "get_seo_analysis_score",
    description=(
        "Read Rank Math's own on-page SEO analysis score (0-100) for one post/page -- the same "
        "score Rank Math shows in its content-analysis panel in the editor. Returns null if Rank "
        "Math has never analyzed that post. Requires the Imperal Bridge plugin."
    ),
    action_type="read", data_model=SeoScoreResult,
)
async def get_seo_analysis_score(ctx, params: GetSeoScoreParams) -> ActionResult:
    """GET /imperal/v1/rankmath/score/{id}."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{BRIDGE_PATH}/score/{params.post_id}",
                      username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    score = body.get("score")
    result = SeoScoreResult(id=str(params.post_id), title=f"post {params.post_id}",
                             kind="rank_math_seo_score", post_id=params.post_id,
                             score=int(score) if score is not None else None)
    summary = (f"SEO score for post {params.post_id}: {score}/100" if score is not None
               else f"Post {params.post_id} has not been analyzed by Rank Math yet")
    return ActionResult.success(result, summary=summary)


@chat.function(
    "get_robots_txt",
    description=(
        "Read Rank Math's robots.txt override text (the content its own robots.txt editor writes) "
        "-- NOT the raw file on disk. Empty content means no override is active and WordPress's "
        "own default robots.txt is served. Requires the Imperal Bridge plugin."
    ),
    action_type="read", data_model=RobotsTxt,
)
async def get_robots_txt(ctx, params: RobotsTxtParams) -> ActionResult:
    """GET /imperal/v1/rankmath/robots-txt."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{BRIDGE_PATH}/robots-txt", username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = RobotsTxt(id=params.site_id, title="robots.txt", kind="rank_math_robots_txt",
                        content=body.get("content", "") or "",
                        is_active=bool(body.get("is_active", False)),
                        site_is_public=bool(body.get("site_is_public", True)))
    summary = "Custom robots.txt override is active" if result.is_active else \
        "No robots.txt override set — WordPress's default robots.txt is served"
    return ActionResult.success(result, summary=summary)


@chat.function(
    "update_robots_txt",
    description=(
        "Write Rank Math's robots.txt override text. Pass an empty string to clear the override "
        "and revert to WordPress's default robots.txt. Only takes effect while the site's own "
        "'Search engine visibility' setting allows indexing. Requires the Imperal Bridge plugin."
    ),
    action_type="write", data_model=RobotsTxt,
    effects=["wp.robots_txt_update"], event="wordpress-hub.update_robots_txt",
)
async def update_robots_txt(ctx, params: UpdateRobotsTxtParams) -> ActionResult:
    """POST /imperal/v1/rankmath/robots-txt."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_post(ctx, base_url, f"{BRIDGE_PATH}/robots-txt", username=username,
                           app_password=pw, json={"content": params.content})
    except Exception as e:
        await ctx.log(f"update_robots_txt request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = RobotsTxt(id=params.site_id, title="robots.txt", kind="rank_math_robots_txt",
                        content=body.get("content", "") or "",
                        is_active=bool(body.get("is_active", False)))
    summary = "robots.txt override updated" if result.is_active else "robots.txt override cleared"
    return ActionResult.success(result, summary=summary, refresh_panels=["center"])


@chat.function(
    "get_sitemap_status",
    description=(
        "Check whether Rank Math's Sitemap module is active on a site, and get the sitemap index "
        "URL if so. Rank Math generates sitemaps dynamically on request -- there is no separate "
        "'regenerate' action, this just reports the module's on/off state. Requires the Imperal "
        "Bridge plugin."
    ),
    action_type="read", data_model=SitemapStatus,
)
async def get_sitemap_status(ctx, params: RobotsTxtParams) -> ActionResult:
    """GET /imperal/v1/rankmath/sitemap-status. Reuses RobotsTxtParams — same shape (site_id only)."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{BRIDGE_PATH}/sitemap-status", username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    active = bool(body.get("module_active", False))
    result = SitemapStatus(id=params.site_id, title="sitemap status", kind="rank_math_sitemap_status",
                            module_active=active, sitemap_url=body.get("sitemap_url", "") or "")
    summary = f"Sitemap module active — {result.sitemap_url}" if active else \
        "Sitemap module is not active on this site"
    return ActionResult.success(result, summary=summary)


@chat.function(
    "list_404_hits",
    description=(
        "List real 404 (page-not-found) hits logged by Rank Math's own 404 Monitor -- URL, when, "
        "how many times, referer, and user agent. Useful for finding broken links to fix or "
        "redirect (pair with create_redirect). Requires the Imperal Bridge plugin and Rank Math's "
        "404 Monitor module enabled."
    ),
    action_type="read", data_model=sdl.EntityList[Hit404],
)
async def list_404_hits(ctx, params: List404HitsParams) -> ActionResult:
    """GET /imperal/v1/rankmath/404-logs."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{BRIDGE_PATH}/404-logs", username=username, app_password=pw,
                      params={"limit": params.limit})
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body,
                         not_available_code="imperal_rankmath_404_not_available",
                         not_available_hint="Rank Math's 404 Monitor module does not appear to be "
                                            "enabled on this site.")
    data = r.body if isinstance(r.body, list) else []
    items = [
        Hit404(id=str(item.get("id", "")), title=item.get("uri", ""), kind="rank_math_404_hit",
                uri=item.get("uri", ""), accessed=item.get("accessed", ""),
                times_accessed=int(item.get("times_accessed", 0) or 0),
                referer=item.get("referer", ""), user_agent=item.get("user_agent", ""))
        for item in data if isinstance(item, dict)
    ]
    return ActionResult.success(
        sdl.EntityList[Hit404](items=items), summary=f"{len(items)} logged 404 hit(s)")


@chat.function(
    "delete_404_hit",
    description="Remove one logged 404 hit from Rank Math's 404 Monitor by id, from list_404_hits.",
    action_type="write", data_model=Hit404DeleteResult,
    effects=["wp.404_hit_delete"], event="wordpress-hub.delete_404_hit",
)
async def delete_404_hit(ctx, params: Delete404HitParams) -> ActionResult:
    """DELETE /imperal/v1/rankmath/404-logs/{id}."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_request(ctx, "delete", base_url, f"{BRIDGE_PATH}/404-logs/{params.hit_id}",
                              username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"delete_404_hit request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body,
                         not_available_code="imperal_rankmath_404_not_available",
                         not_available_hint="Rank Math's 404 Monitor module does not appear to be "
                                            "enabled on this site.")
    return ActionResult.success(
        Hit404DeleteResult(id=str(params.hit_id), title=str(params.hit_id),
                            kind="rank_math_404_hit_delete", deleted=True),
        summary=f"404 log entry {params.hit_id} deleted", refresh_panels=["center"])
