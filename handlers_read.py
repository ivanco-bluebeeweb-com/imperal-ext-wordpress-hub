import asyncio

from imperal_sdk import ActionResult, sdl
from app import chat, ext
from models import (_NoParams, Site, ListContentParams, ListMediaParams,
                    Post, Page, MediaItem, SiteIdParams, SiteHealth, RefreshAllResult,
                    ListCommentsParams, SetCommentStatusParams, ReplyToCommentParams,
                    EditCommentContentParams,
                    ListCustomPostsParams, Comment, WPUser, Plugin,
                    PurgeCacheParams, CacheActionResult, InstallPluginParams, PluginInstallResult,
                    ServerInfo, UpdateMediaAltParams, MediaAltResult,
                    MediaAltItem, SetSingleMediaAltParams)
import wp_cli
from wp_client import wp_get, wp_post, wp_request, wp_error_message, wp_error_code, wp_title, now_iso
import storage
import handlers_maintenance


@chat.function("list_sites", description="List the WordPress sites the user has connected.",
               action_type="read", data_model=sdl.EntityList[Site])
async def list_sites(ctx, params: _NoParams) -> ActionResult:
    """Return all connected WordPress sites as an entity list."""
    rows = await storage.list_site_records(ctx)
    sites = [
        Site(id=r["id"], title=r.get("name", r["id"]), kind="wp_site",
             url=r.get("url", ""), username=r.get("username", ""),
             status=r.get("status", "connected"), last_checked=r.get("last_checked"))
        for r in rows
    ]
    return ActionResult.success(sdl.EntityList[Site](items=sites), summary=f"{len(sites)} site(s) connected")


@ext.expose("list_connected_sites", action_type="read")
async def expose_list_connected_sites(ctx, **kwargs):
    """Inter-extension IPC surface (ctx.extensions.call) for other Marketing
    Suite hubs -- Brand Strategy Hub and Content Strategy Hub read this to
    populate their 'Quick Add' lists with real connected sites, no chat
    round-trip and no manual site_id typing needed on either side.

    Returns plain dicts (not an ActionResult -- this is direct extension-to-
    extension data, never surfaced to the LLM or the user directly):
    [{"site_id", "name", "url", "status"}, ...]
    """
    rows = await storage.list_site_records(ctx)
    return [
        {"site_id": r["id"], "name": r.get("name", r["id"]),
         "url": r.get("url", ""), "status": r.get("status", "connected")}
        for r in rows
    ]


@ext.expose("list_posts_full", action_type="read")
async def expose_list_posts_full(ctx, site_id: str = "", limit: int = 200, **kwargs):
    """Inter-extension IPC surface for the Content Strategy Hub's mandatory
    pre-strategy content audit + keyword-cannibalization check. A chat tool
    cannot give Content Strategy Hub what it needs here -- it needs every
    existing post's title/slug/link/excerpt/content/categories in one call,
    not a paginated summary meant for a human to read.

    Returns plain dicts (never surfaced to the LLM/user directly):
    [{"id", "title", "slug", "link", "excerpt", "content", "date",
      "categories", "lang"}, ...]
    lang is best-effort: only populated when the Imperal Bridge (or a
    Polylang REST exposure) reports it; empty string otherwise, never guessed.
    """
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return []
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return []
    base_url, username = record["url"], record["username"]
    out = []
    page_num = 1
    remaining = max(1, min(limit, 500))
    while remaining > 0:
        per_page = min(remaining, 100)
        try:
            r = await wp_get(ctx, base_url, "/wp-json/wp/v2/posts", username=username,
                              app_password=pw, params={"per_page": per_page, "page": page_num,
                                                        "_fields": "id,slug,link,date,title,excerpt,content,categories,lang"})
        except Exception as e:
            await ctx.log(f"list_posts_full http error: {e}", level="error")
            break
        if r.status_code != 200:
            break
        rows = r.body if isinstance(r.body, list) else []
        if not rows:
            break
        for p in rows:
            out.append({
                "id": p.get("id"),
                "title": wp_title(p),
                "slug": p.get("slug", ""),
                "link": p.get("link", ""),
                "excerpt": (p.get("excerpt") or {}).get("rendered", ""),
                "content": (p.get("content") or {}).get("rendered", ""),
                "date": p.get("date"),
                "categories": p.get("categories", []),
                "lang": p.get("lang", ""),
            })
        remaining -= len(rows)
        page_num += 1
        if len(rows) < per_page:
            break
    return out


@ext.expose("list_pages_full", action_type="read")
async def expose_list_pages_full(ctx, site_id: str = "", limit: int = 200, **kwargs):
    """Inter-extension page inventory for Content Strategy's key-action-page
    resolver. Returns only factual published page fields; selection remains in
    the consuming pipeline so the same algorithm serves every client/language.
    """
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return []
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return []
    base_url, username = record["url"], record["username"]
    out = []
    page_num = 1
    remaining = max(1, min(limit, 500))
    while remaining > 0:
        per_page = min(remaining, 100)
        try:
            response = await wp_get(
                ctx, base_url, "/wp-json/wp/v2/pages", username=username,
                app_password=pw,
                params={"per_page": per_page, "page": page_num, "status": "publish",
                        "_fields": "id,slug,link,title,excerpt,content,lang"},
            )
        except Exception as exc:
            await ctx.log(f"list_pages_full http error: {exc}", level="error")
            break
        if response.status_code != 200:
            break
        rows = response.body if isinstance(response.body, list) else []
        if not rows:
            break
        for page in rows:
            out.append({
                "id": page.get("id"), "title": wp_title(page),
                "slug": page.get("slug", ""), "link": page.get("link", ""),
                "excerpt": (page.get("excerpt") or {}).get("rendered", ""),
                "content": (page.get("content") or {}).get("rendered", ""),
                "lang": page.get("lang", ""),
            })
        remaining -= len(rows)
        page_num += 1
        if len(rows) < per_page:
            break
    return out


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, "No connected site with that id."
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return None, "Stored credential is missing — reconnect the site."
    return (record["url"], record["username"], pw), None


async def _fetch(ctx, site_id, path, params):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, ActionResult.error(err, retryable=False)
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception as e:
        await ctx.log(f"{path} http error: {e}", level="error")
        return None, ActionResult.error("Could not reach the site — try again.", retryable=True)
    if r.status_code != 200:
        retry = r.status_code >= 500 or r.status_code == 429
        return None, ActionResult.error(wp_error_message(r.status_code), retryable=retry)
    # HTTPResponse.body is already-parsed JSON (list for WP collection endpoints).
    # HTTPResponse.json() raises on list bodies, so read .body directly.
    return (r.body if isinstance(r.body, list) else []), None


@chat.function("list_posts", description="List recent posts on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[Post])
async def list_posts(ctx, params: ListContentParams) -> ActionResult:
    """Return recent posts from the site's REST API as an entity list."""
    q = {"per_page": params.limit, "status": params.status}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/posts", q)
    if err:
        return err
    items = [Post(id=str(p["id"]), title=wp_title(p), kind="wp_post",
                  status=p.get("status", ""), link=p.get("link", ""), date=p.get("date")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items), summary=f"{len(items)} post(s)")


@chat.function("list_pages", description="List pages on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[Page])
async def list_pages(ctx, params: ListContentParams) -> ActionResult:
    """Return pages from the site's REST API as an entity list."""
    q = {"per_page": params.limit, "status": params.status}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/pages", q)
    if err:
        return err
    items = [Page(id=str(p["id"]), title=wp_title(p), kind="wp_page",
                  status=p.get("status", ""), link=p.get("link", ""), date=p.get("date")) for p in data]
    return ActionResult.success(sdl.EntityList[Page](items=items), summary=f"{len(items)} page(s)")


@chat.function("list_media", description="List media library items on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[MediaItem])
async def list_media(ctx, params: ListMediaParams) -> ActionResult:
    """Return media items from the site's REST API as an entity list."""
    query = {"per_page": params.limit}
    if params.missing_alt_only:
        # No REST filter exists for "empty alt", so widen the page and filter here.
        query["per_page"] = min(100, max(params.limit, 100))
        query["media_type"] = "image"
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/media", query)
    if err:
        return err
    if params.missing_alt_only:
        data = [m for m in data if not (m.get("alt_text") or "").strip()][:params.limit]
    items = [MediaItem(id=str(m["id"]), title=wp_title(m), kind="wp_media",
                       url=m.get("source_url", ""), mime_type=m.get("mime_type", ""),
                       alt_text=(m.get("alt_text") or "")) for m in data]
    gap = " missing alt text" if params.missing_alt_only else ""
    return ActionResult.success(sdl.EntityList[MediaItem](items=items),
                                summary=f"{len(items)} media item(s){gap}")


@chat.function(
    "update_media_alt",
    description=("Set the alt text of media library images on a connected WordPress site. "
                 "Alt text is what screen readers announce and what Google Images indexes. "
                 "Pass a list of {media_id, alt_text}. By default an image that already has "
                 "alt text is skipped so existing wording is never overwritten."),
    action_type="write",
    data_model=MediaAltResult,
    effects=["wp.media_update"],
    event="wordpress-hub.update_media_alt",
)
async def update_media_alt(ctx, params: UpdateMediaAltParams) -> ActionResult:
    """Write alt_text onto media library attachments, one REST call per item.

    alt_text is a first-class field of the core wp/v2/media endpoint, so this
    needs no plugin — only the Application Password the site is already
    connected with.
    """
    if not params.items:
        return ActionResult.error("Nothing to update — pass at least one {media_id, alt_text}.",
                                  retryable=False, code="MEDIA_NO_ITEMS")
    if len(params.items) > 100:
        return ActionResult.error(
            f"Too many items ({len(params.items)}) — send at most 100 per call.",
            retryable=False, code="MEDIA_TOO_MANY")

    blank = [i.media_id for i in params.items if not i.alt_text.strip()]
    if blank:
        return ActionResult.error(
            f"Empty alt_text for media id(s): {', '.join(str(b) for b in blank)}. "
            "Decorative images should keep their empty alt rather than be written blank.",
            retryable=False, code="MEDIA_EMPTY_ALT")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth

    updated, skipped, failures = [], [], []

    for item in params.items:
        path = f"/wp-json/wp/v2/media/{item.media_id}"

        if not params.overwrite:
            try:
                cur = await wp_get(ctx, base_url, path, username=username, app_password=pw,
                                   params={"_fields": "id,alt_text"})
            except Exception as e:
                await ctx.log(f"update_media_alt read #{item.media_id} failed: {e}", level="error")
                failures.append(f"#{item.media_id}: could not read current alt")
                continue
            if cur.status_code != 200:
                failures.append(f"#{item.media_id}: {wp_error_message(cur.status_code)}")
                continue
            existing = (cur.body or {}).get("alt_text") if isinstance(cur.body, dict) else ""
            if (existing or "").strip():
                skipped.append(item.media_id)
                continue

        try:
            w = await wp_post(ctx, base_url, path, username=username, app_password=pw,
                              json={"alt_text": item.alt_text})
        except Exception as e:
            await ctx.log(f"update_media_alt write #{item.media_id} failed: {e}", level="error")
            failures.append(f"#{item.media_id}: could not reach the site")
            continue

        if w.status_code != 200:
            failures.append(f"#{item.media_id}: {wp_error_message(w.status_code)}")
            continue

        # Trust the echo, not the request: confirm WordPress really stored it.
        stored = (w.body or {}).get("alt_text") if isinstance(w.body, dict) else ""
        if (stored or "").strip() != item.alt_text.strip():
            failures.append(f"#{item.media_id}: server did not store the new alt text")
            continue
        updated.append(item.media_id)

    result = MediaAltResult(
        id=params.site_id, title="Media alt text", kind="wp_media_alt_result",
        updated=len(updated), skipped_existing=len(skipped), failed=len(failures),
        updated_ids=updated, skipped_ids=skipped, failures=failures[:20])

    bits = [f"{len(updated)} image(s) updated"]
    if skipped:
        bits.append(f"{len(skipped)} left alone (already had alt)")
    if failures:
        bits.append(f"{len(failures)} failed")

    # Every single item failing is an error, not a success with a sad summary.
    if failures and not updated:
        return ActionResult.error(
            "No images were updated. " + "; ".join(failures[:3]),
            retryable=True, code="MEDIA_ALL_FAILED")

    return ActionResult.success(result, summary=", ".join(bits), refresh_panels=["center"])


@chat.function(
    "set_single_media_alt",
    description=(
        "Set the alt text of ONE media library image — a single-item convenience "
        "wrapper around update_media_alt for cases with just one attachment to fix "
        "(e.g. a form on the Media panel). Always overwrites, unlike the bulk "
        "version's default skip-if-already-set behaviour."
    ),
    action_type="write",
    data_model=MediaAltResult,
    effects=["wp.media_update"],
    event="wordpress-hub.set_single_media_alt",
)
async def set_single_media_alt(ctx, params: SetSingleMediaAltParams) -> ActionResult:
    """Thin wrapper: reuse update_media_alt's single-item, overwrite=True path."""
    return await update_media_alt(ctx, UpdateMediaAltParams(
        site_id=params.site_id,
        items=[MediaAltItem(media_id=params.media_id, alt_text=params.alt_text)],
        overwrite=True,
    ))


@chat.function("get_site_health", description="Report read-only health for a connected WordPress site.",
               action_type="read", data_model=SiteHealth)
async def get_site_health(ctx, params: SiteIdParams) -> ActionResult:
    """Report best-effort read-only health: reachability, auth, SSL, and content counts."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth

    async def _call(path, per_page=1):
        try:
            return await wp_get(ctx, base_url, path, username=username, app_password=pw,
                                params={"per_page": per_page})
        except Exception:
            return None

    me, posts_r, pages_r, media_r = await asyncio.gather(
        _call("/wp-json/wp/v2/users/me"),
        _call("/wp-json/wp/v2/posts", 100),
        _call("/wp-json/wp/v2/pages", 100),
        _call("/wp-json/wp/v2/media", 100),
    )

    def _count(r):
        return len(r.body) if r and r.status_code == 200 and isinstance(r.body, list) else 0

    reachable = me is not None
    auth_ok = me is not None and me.status_code == 200
    counts = {"posts": _count(posts_r), "pages": _count(pages_r), "media": _count(media_r)}
    health = SiteHealth(
        id=params.site_id, title=params.site_id, kind="wp_site_health",
        reachable=reachable, auth_ok=auth_ok, ssl_valid=base_url.startswith("https://"),
        content_counts=counts,
    )
    status = "✅" if auth_ok else ("⚠️" if reachable else "❌")
    return ActionResult.success(
        health,
        summary=f"{status} {params.site_id}: {counts['posts']} posts · {counts['pages']} pages · {counts['media']} media",
    )


@chat.function(
    "refresh_site",
    description="Re-check connectivity and auth for a connected WordPress site and update its stored status.",
    action_type="write",
    data_model=Site,
    effects=["wp.health_check"],
    event="wordpress-hub.refresh_site",
)
async def refresh_site(ctx, params: SiteIdParams) -> ActionResult:
    """Ping the site REST API, update stored status, and refresh the overview panel."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                         username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"refresh_site http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    status = "connected" if 200 <= r.status_code < 300 else "error"
    record = await storage.get_site_record(ctx, params.site_id) or {}
    await storage.save_site_record(ctx, {**record, "status": status, "last_checked": now_iso()})
    await storage.clear_content_cache(ctx, params.site_id)

    name = record.get("name", params.site_id)
    site = Site(id=params.site_id, title=name, kind="wp_site",
                url=base_url, username=username, status=status)
    icon = "✅" if status == "connected" else "❌"
    return ActionResult.success(
        site,
        summary=f"{icon} {name}: {status}",
        refresh_panels=["sidebar", "center"],
    )


@chat.function(
    "refresh_all_sites",
    description="Re-check connectivity for all connected WordPress sites at once.",
    action_type="write",
    data_model=RefreshAllResult,
    effects=["wp.health_check"],
    event="wordpress-hub.refresh_all_sites",
)
async def refresh_all_sites(ctx, params: _NoParams) -> ActionResult:
    """Ping every connected site in parallel, update stored statuses, clear content caches."""
    rows = await storage.list_site_records(ctx)
    if not rows:
        return ActionResult.error("No sites connected.", retryable=False)

    async def _check(record):
        site_id = record["id"]
        auth, err = await _authed(ctx, site_id)
        if err:
            updated = {**record, "status": "error", "last_checked": now_iso()}
        else:
            base_url, username, pw = auth
            try:
                r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                                 username=username, app_password=pw)
                status = "connected" if 200 <= r.status_code < 300 else "error"
            except Exception:
                status = "error"
            updated = {**record, "status": status, "last_checked": now_iso()}
        await storage.save_site_record(ctx, updated)
        await storage.clear_content_cache(ctx, site_id)
        return updated

    results = await asyncio.gather(*[_check(r) for r in rows])
    connected = sum(1 for r in results if r.get("status") == "connected")
    total = len(results)
    result = RefreshAllResult(
        id="refresh_all", title=f"{connected}/{total} sites connected",
        kind="refresh_all", connected=connected, total=total,
    )
    icon = "✅" if connected == total else ("⚠️" if connected > 0 else "❌")
    return ActionResult.success(
        result,
        summary=f"{icon} {connected}/{total} sites connected",
        refresh_panels=["sidebar"],
    )


@chat.function(
    "list_comments",
    description="List comments on a connected WordPress site. Use status='hold' to see comments pending moderation, 'approved' for published, 'spam' for spam.",
    action_type="read",
    data_model=sdl.EntityList[Comment],
)
async def list_comments(ctx, params: ListCommentsParams) -> ActionResult:
    """Return comments from the site's REST API."""
    q: dict = {"per_page": params.limit, "orderby": "date", "order": "desc"}
    if params.status != "all":
        q["status"] = params.status
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/comments", q)
    if err:
        return err
    items = [
        Comment(
            id=str(c["id"]),
            title=c.get("author_name", "Anonymous"),
            kind="wp_comment",
            status=c.get("status", ""),
            author=c.get("author_name", ""),
            snippet=(c.get("content", {}).get("rendered", "") or "")
                    .replace("<p>", "").replace("</p>", "")[:120].strip(),
            post_id=str(c.get("post", "")),
            date=c.get("date", ""),
        )
        for c in data
    ]
    pending = sum(1 for i in items if i.status == "hold")
    summary = f"{len(items)} comment(s)"
    if pending:
        summary += f" — {pending} pending moderation"
    return ActionResult.success(sdl.EntityList[Comment](items=items), summary=summary)


@chat.function(
    "set_comment_status",
    description=(
        "Change a comment's moderation status: 'approved' (publish it), 'hold' "
        "(send back to pending moderation), 'spam', or 'trash'. Use list_comments "
        "first to find the comment_id."
    ),
    action_type="write",
    data_model=Comment,
    effects=["wp.comment_status_update"],
    event="wordpress-hub.set_comment_status",
)
async def set_comment_status(ctx, params: SetCommentStatusParams) -> ActionResult:
    """Set one comment's status via the WordPress REST API."""
    status = params.status.strip().lower()
    if status not in ("approved", "hold", "spam", "trash"):
        return ActionResult.error(
            f"Invalid status '{params.status}' — use 'approved', 'hold', 'spam', or 'trash'.",
            retryable=False, code="COMMENT_INVALID_STATUS")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth

    try:
        r = await wp_request(
            ctx, "post", base_url, f"/wp-json/wp/v2/comments/{params.comment_id}",
            username=username, app_password=pw, json={"status": status})
    except Exception as e:
        await ctx.log(f"set_comment_status request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if r.status_code == 404:
        return ActionResult.error("That comment does not exist.", retryable=False,
                                  code="COMMENT_NOT_FOUND")
    if r.status_code != 200 or not isinstance(r.body, dict):
        retry = r.status_code >= 500 or r.status_code == 429
        return ActionResult.error(wp_error_message(r.status_code), retryable=retry,
                                  code=wp_error_code(r.status_code))

    c = r.body
    entity = Comment(
        id=str(c["id"]), title=c.get("author_name", "Anonymous"), kind="wp_comment",
        status=c.get("status", ""), author=c.get("author_name", ""),
        snippet=(c.get("content", {}).get("rendered", "") or "")
                .replace("<p>", "").replace("</p>", "")[:120].strip(),
        post_id=str(c.get("post", "")), date=c.get("date", ""),
    )
    return ActionResult.success(
        entity, summary=f"Comment #{entity.id} set to '{status}'.",
        refresh_panels=["center"])


@chat.function(
    "reply_to_comment",
    description=(
        "Post a reply to an existing comment, as the connected WordPress user. "
        "The reply is automatically attached to the same post and nested under "
        "the original comment. Use list_comments first to find the comment_id."
    ),
    action_type="write",
    data_model=Comment,
    effects=["wp.comment_reply"],
    event="wordpress-hub.reply_to_comment",
)
async def reply_to_comment(ctx, params: ReplyToCommentParams) -> ActionResult:
    """Create a reply comment nested under an existing comment."""
    if not params.content.strip():
        return ActionResult.error(
            "Reply text cannot be empty.", retryable=False, code="COMMENT_EMPTY_REPLY")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth

    # Fetch the parent comment directly — _fetch() is built for list endpoints
    # and would silently return [] for this single-object body, hiding a real
    # 404 and crashing on the next .get() call.
    try:
        parent_r = await wp_get(
            ctx, base_url, f"/wp-json/wp/v2/comments/{params.comment_id}",
            username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"reply_to_comment parent lookup failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if parent_r.status_code == 404:
        return ActionResult.error("That comment does not exist.", retryable=False,
                                  code="COMMENT_NOT_FOUND")
    if parent_r.status_code != 200 or not isinstance(parent_r.body, dict):
        retry = parent_r.status_code >= 500 or parent_r.status_code == 429
        return ActionResult.error(wp_error_message(parent_r.status_code), retryable=retry,
                                  code=wp_error_code(parent_r.status_code))
    post_id = parent_r.body.get("post")
    if not post_id:
        return ActionResult.error(
            "Could not determine which post that comment belongs to.",
            retryable=False, code="COMMENT_POST_UNKNOWN")

    try:
        r = await wp_post(
            ctx, base_url, "/wp-json/wp/v2/comments", username=username, app_password=pw,
            json={"post": post_id, "parent": params.comment_id, "content": params.content})
    except Exception as e:
        await ctx.log(f"reply_to_comment request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if r.status_code not in (200, 201) or not isinstance(r.body, dict):
        retry = r.status_code >= 500 or r.status_code == 429
        return ActionResult.error(wp_error_message(r.status_code), retryable=retry,
                                  code=wp_error_code(r.status_code))

    c = r.body
    entity = Comment(
        id=str(c["id"]), title=c.get("author_name", "Anonymous"), kind="wp_comment",
        status=c.get("status", ""), author=c.get("author_name", ""),
        snippet=(c.get("content", {}).get("rendered", "") or "")
                .replace("<p>", "").replace("</p>", "")[:120].strip(),
        post_id=str(c.get("post", "")), date=c.get("date", ""),
    )
    return ActionResult.success(
        entity, summary=f"Replied to comment #{params.comment_id} (new comment #{entity.id}).",
        refresh_panels=["center"])


@chat.function(
    "edit_comment_content",
    description=(
        "Overwrite the text of an existing comment — fixes a typo, redacts "
        "something, or corrects a misattributed comment without deleting and "
        "re-creating it. Use list_comments first to find the comment_id."
    ),
    action_type="write",
    data_model=Comment,
    effects=["wp.comment_edit"],
    event="wordpress-hub.edit_comment_content",
)
async def edit_comment_content(ctx, params: EditCommentContentParams) -> ActionResult:
    """Overwrite one comment's content via the native WordPress REST API."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth

    try:
        r = await wp_request(
            ctx, "post", base_url, f"/wp-json/wp/v2/comments/{params.comment_id}",
            username=username, app_password=pw, json={"content": params.content})
    except Exception as e:
        await ctx.log(f"edit_comment_content request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if r.status_code == 404:
        return ActionResult.error("That comment does not exist.", retryable=False,
                                  code="COMMENT_NOT_FOUND")
    if r.status_code != 200 or not isinstance(r.body, dict):
        retry = r.status_code >= 500 or r.status_code == 429
        return ActionResult.error(wp_error_message(r.status_code), retryable=retry,
                                  code=wp_error_code(r.status_code))

    c = r.body
    entity = Comment(
        id=str(c["id"]), title=c.get("author_name", "Anonymous"), kind="wp_comment",
        status=c.get("status", ""), author=c.get("author_name", ""),
        snippet=(c.get("content", {}).get("rendered", "") or "")
                .replace("<p>", "").replace("</p>", "")[:120].strip(),
        post_id=str(c.get("post", "")), date=c.get("date", ""),
    )
    return ActionResult.success(
        entity, summary=f"Comment #{entity.id} content updated.",
        refresh_panels=["center"])


@chat.function(
    "list_scheduled",
    description="List posts scheduled for future publication on a connected WordPress site.",
    action_type="read",
    data_model=sdl.EntityList[Post],
)
async def list_scheduled(ctx, params: ListContentParams) -> ActionResult:
    """Return scheduled (future) posts from the site's REST API."""
    q: dict = {"per_page": params.limit, "status": "future", "orderby": "date", "order": "asc"}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/posts", q)
    if err:
        return err
    items = [Post(id=str(p["id"]), title=wp_title(p), kind="wp_post",
                  status="scheduled", link=p.get("link", ""),
                  date=p.get("date", "")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items),
                                summary=f"{len(items)} scheduled post(s)")


@chat.function(
    "list_users",
    description="List recently registered users on a connected WordPress site.",
    action_type="read",
    data_model=sdl.EntityList[WPUser],
)
async def list_users(ctx, params: ListContentParams) -> ActionResult:
    """Return users from the site's REST API ordered by registration date."""
    q: dict = {"per_page": params.limit, "orderby": "registered_date", "order": "desc"}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/users", q)
    if err:
        return err
    items = [
        WPUser(
            id=str(u["id"]),
            title=u.get("name", ""),
            kind="wp_user",
            role=", ".join(u.get("roles", [])),
            registered=(u.get("registered_date", "") or "")[:10],
        )
        for u in data
    ]
    return ActionResult.success(sdl.EntityList[WPUser](items=items),
                                summary=f"{len(items)} user(s)")


@chat.function(
    "list_plugins",
    description=("List plugins installed on a WordPress site: active/inactive status, "
                 "installed version, and an available update version. Requires SSH access "
                 "configured with add_ssh; this function is read-only."),
    action_type="read",
    data_model=sdl.EntityList[Plugin],
)
async def list_plugins(ctx, params: SiteIdParams) -> ActionResult:
    """Return the WP-CLI plugin inventory without making any changes."""
    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "SSH is not configured for this site. Add SSH access first.", retryable=False
        )

    try:
        rows, cli_error = await wp_cli.list_plugins(cred)
    except Exception as error:
        await ctx.log(f"list_plugins: {error}", level="error")
        return ActionResult.error("Could not read the plugin list over SSH.", retryable=True)
    if cli_error:
        return ActionResult.error(f"Could not read the plugin list: {cli_error}", retryable=True)

    items = [
        Plugin(
            id=str(row.get("name", "")),
            title=str(row.get("name", "")),
            kind="wp_plugin",
            status=str(row.get("status", "")),
            version=str(row.get("version", "")),
            update_available=(str(row.get("update_version", ""))
                              if row.get("update") == "available" else ""),
        )
        for row in rows
        if row.get("name")
    ]
    updates = sum(1 for item in items if item.update_available)
    summary = f"{len(items)} plugin(s)"
    if updates:
        summary += f" — {updates} update(s) available"
    return ActionResult.success(sdl.EntityList[Plugin](items=items), summary=summary)


@chat.function(
    "purge_cache",
    description=("Purge the site's page cache. Auto-detects an active cache plugin "
                 "(LiteSpeed Cache or W3 Total Cache) from the site's real, live plugin list — "
                 "if none is found, reports that clearly instead of silently doing nothing. "
                 "Requires SSH access configured with add_ssh."),
    action_type="write",
    data_model=CacheActionResult,
    effects=["wp.purge_cache"],
    event="wordpress-hub.purge_cache",
)
async def purge_cache(ctx, params: PurgeCacheParams) -> ActionResult:
    """Purge the site's cache via `wp litespeed-purge` or `wp w3-total-cache flush all` over SSH.

    Detects the active cache plugin from the site's own live plugin list
    rather than assuming one is installed -- a purge command for a cache
    plugin that is not even active would silently do nothing, which is
    worse than refusing. Covers LiteSpeed Cache and W3 Total Cache, whose
    WP-CLI purge commands are both bundled with the plugin itself (verified
    against each plugin's own docs before writing this) -- WP Rocket and WP
    Super Cache are deliberately NOT covered here because their WP-CLI
    support ships as a SEPARATE package that may not be installed on an
    arbitrary server, so silently trying it could misreport a real failure
    as "no cache plugin found".
    """
    scope = (params.scope or "all").strip().lower()
    if scope not in ("all", "front"):
        return ActionResult.error(
            f"Invalid scope '{params.scope}' — use 'all' or 'front'.", retryable=False
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "SSH is not configured for this site. Add SSH access first.", retryable=False
        )

    try:
        rows, cli_error = await wp_cli.list_plugins(cred)
    except Exception as error:
        await ctx.log(f"purge_cache: {error}", level="error")
        return ActionResult.error("Could not read the plugin list over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"purge_cache: rejected — could not read plugin list: {cli_error}", level="warning")
        return ActionResult.error(f"Could not read the plugin list: {cli_error}", retryable=True)

    active = {str(row.get("name", "")) for row in rows if row.get("status") == "active"}

    if "litespeed-cache" in active:
        plugin_slug = "litespeed-cache"
        try:
            output, run_error = await wp_cli.purge_litespeed_cache(cred, scope)
        except Exception as error:
            await ctx.log(f"purge_cache: {error}", level="error")
            return ActionResult.error("Could not purge the cache over SSH.", retryable=True)
    elif "w3-total-cache" in active:
        plugin_slug = "w3-total-cache"
        try:
            output, run_error = await wp_cli.purge_w3tc_cache(cred)
        except Exception as error:
            await ctx.log(f"purge_cache: {error}", level="error")
            return ActionResult.error("Could not purge the cache over SSH.", retryable=True)
    else:
        await ctx.log(
            f"purge_cache: rejected — no known cache plugin active on site_id={params.site_id}",
            level="info",
        )
        return ActionResult.error(
            "No supported cache plugin (LiteSpeed Cache or W3 Total Cache) is active on this "
            "site. Call list_plugins to see what's installed.", retryable=False
        )

    if run_error:
        await ctx.log(f"purge_cache: SSH/WP-CLI error — {run_error}", level="error")
        return ActionResult.error(run_error, retryable=True)

    await ctx.log(f"purge_cache: executed — scope={scope} plugin={plugin_slug} site_id={params.site_id}", level="info")
    return ActionResult.success(
        CacheActionResult(
            id=params.site_id, title=f"{plugin_slug} purge", kind="wp_cache_action",
            scope=scope, cache_plugin=plugin_slug, output=(output or "").strip(),
        ),
        summary=f"Purged {plugin_slug} cache ({scope}).",
    )


@chat.function(
    "install_plugin",
    description=("Install a WordPress plugin from a WordPress.org slug or a direct https:// "
                 ".zip URL, and optionally activate it immediately. Reads through the Imperal "
                 "Bridge plugin if it's installed (no SSH needed at all — uses the same "
                 "Plugin_Upgrader API wp-admin's own 'Add New Plugin' screen uses), or falls "
                 "back to SSH + WP-CLI (`wp plugin install`) if SSH is configured instead. Use "
                 "this to install Imperal's own companion bridge plugin (Imperal Bridge — SEO + "
                 "builder + media in one) or any third-party plugin the site needs."),
    action_type="write",
    data_model=PluginInstallResult,
    effects=["wp.install_plugin"],
    event="wordpress-hub.install_plugin",
)
async def install_plugin(ctx, params: InstallPluginParams) -> ActionResult:
    """Install (and optionally activate) a plugin — Bridge-first, SSH-fallback."""
    source = (params.source or "").strip()
    if not source:
        return ActionResult.error("source is required — a WordPress.org slug or a .zip URL.", retryable=False)

    auth, err = await handlers_maintenance._site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await handlers_maintenance._bridge_post(
        ctx, base_url, username, pw, handlers_maintenance.BRIDGE_MAINTENANCE_INSTALL_PLUGIN_PATH,
        json_body={"source": source, "activate": params.activate},
    )
    if body is not None:
        plugin_file = body.get("plugin", "") or source
        activated = bool(body.get("activated"))
        output = f"Installed as {plugin_file}." if plugin_file else "Installed."
        await ctx.log(
            f"install_plugin: executed via Bridge — source={source} activate={params.activate} "
            f"site_id={params.site_id}",
            level="info",
        )
        return ActionResult.success(
            PluginInstallResult(
                id=params.site_id, title=f"install {source}", kind="wp_plugin_install",
                source=source, activated=activated, output=output,
            ),
            summary=f"Installed plugin '{source}'" + (" and activated it." if activated else "."),
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return handlers_maintenance._no_bridge_no_ssh_error()

    try:
        result, cli_error = await wp_cli.install_plugin(cred, source, params.activate)
    except Exception as error:
        await ctx.log(f"install_plugin: {error}", level="error")
        return ActionResult.error("Could not install the plugin over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"install_plugin: rejected — {cli_error}", level="warning")
        return ActionResult.error(cli_error, retryable=False)

    output = (result or {}).get("raw", "") if result else ""
    await ctx.log(
        f"install_plugin: executed — source={source} activate={params.activate} site_id={params.site_id}",
        level="info",
    )
    return ActionResult.success(
        PluginInstallResult(
            id=params.site_id, title=f"install {source}", kind="wp_plugin_install",
            source=source, activated=params.activate, output=output.strip(),
        ),
        summary=f"Installed plugin '{source}'" + (" and activated it." if params.activate else "."),
    )


@chat.function(
    "list_custom_posts",
    description="List items of a custom post type on a connected WordPress site. Use post_type= with the REST base slug (e.g. 'products', 'events', 'portfolio'). Check the site's panel to see available post types.",
    action_type="read",
    data_model=sdl.EntityList[Post],
)
async def list_custom_posts(ctx, params: ListCustomPostsParams) -> ActionResult:
    """Return items of the given custom post type from the site's REST API."""
    q: dict = {"per_page": params.limit, "orderby": "date", "order": "desc"}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, f"/wp-json/wp/v2/{params.post_type}", q)
    if err:
        return err
    items = [Post(id=str(p["id"]), title=wp_title(p), kind=f"wp_cpt_{params.post_type}",
                  status=p.get("status", ""), link=p.get("link", ""),
                  date=p.get("date", "")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items),
                                summary=f"{len(items)} {params.post_type} item(s)")


BRIDGE_SERVER_INFO_PATH = "/wp-json/imperal/v1/server/info"
BRIDGE_WHOLE_STATUS_PATH = "/wp-json/imperal/v1/status"


async def _server_info_via_bridge(ctx, base_url: str, username: str, pw: str) -> dict | None:
    """Try the Imperal Bridge server-info route first -- every fact it returns
    (core/PHP version, plugin/theme/core updates, cron count, DB size) is
    plain WordPress core data, so a site with the Bridge installed needs no
    SSH at all to see it. Returns None (never raises) on 404/unreachable/bad
    response so the caller can fall back to SSH -- this is a probe, not the
    only path.
    """
    try:
        r = await wp_get(ctx, base_url, BRIDGE_SERVER_INFO_PATH,
                         username=username, app_password=pw, params={"_": now_iso()})
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


async def _bridge_present_but_outdated(ctx, base_url: str, username: str, pw: str) -> str | None:
    """Distinguish "no Bridge at all" from "Bridge installed, just an older
    version that predates the /server/info route" -- the /server/info 404
    alone can't tell them apart, and conflating them sends the user hunting
    for SSH credentials on a site that already has the plugin.

    Probes the whole-plugin /status route (present since Bridge 2.0.0, which
    added the /server/info route in 2.1.0). Returns the installed
    bridge_version string when the plugin answers, or None if it's genuinely
    not installed/unreachable.
    """
    try:
        r = await wp_get(ctx, base_url, BRIDGE_WHOLE_STATUS_PATH,
                         username=username, app_password=pw, params={"_": now_iso()})
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return str(r.body.get("bridge_version", "")) or "unknown"


@chat.function(
    "get_server_info",
    description=(
        "Get server information for a WordPress site: PHP version, WordPress version, "
        "available plugin/theme/core updates, cron job count, database size. Reads it "
        "through the Imperal Bridge plugin when installed (no SSH needed at all); falls "
        "back to SSH + WP-CLI when the Bridge isn't there yet or doesn't answer."
    ),
    action_type="write",
    data_model=ServerInfo,
    effects=["wp.health_check"],
    event="wordpress-hub.get_server_info",
)
async def get_server_info(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first, SSH-fallback: this data never actually required a shell."""
    record = await storage.get_site_record(ctx, params.site_id) or {}
    if not record:
        return ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, params.site_id)
    if not pw:
        return ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")

    info = await _server_info_via_bridge(ctx, record["url"], record["username"], pw)
    source = "bridge"

    if info is None:
        cred = await storage.get_ssh_cred(ctx, params.site_id)
        if not cred:
            bridge_version = await _bridge_present_but_outdated(
                ctx, record["url"], record["username"], pw)
            if bridge_version:
                await storage.save_site_record(ctx, {
                    **record, "bridge_outdated": bridge_version, "ssh_error": "",
                })
                # ActionResult.error() has no refresh_panels param, but the
                # detail screen's "Server" section reads bridge_outdated from
                # storage — without forcing a repaint here, clicking "Refresh
                # server info" on an outdated-Bridge site silently persists
                # the fix while the panel keeps showing the stale generic
                # "No server data yet" text until some unrelated action
                # refreshes it. Construct ActionResult directly to carry it.
                return ActionResult(
                    status="error", data={}, summary="",
                    error=(
                        f"The Imperal Bridge plugin on this site is version {bridge_version}, "
                        "which predates the /server/info route (added in 2.1.0). Update the "
                        "plugin to the latest Imperal Bridge build on the site (Plugins → "
                        "Imperal Bridge → update, or reinstall from the Bridge zip) — SSH is "
                        "not needed once it's updated."
                    ),
                    retryable=False, error_code="SERVER_INFO_BRIDGE_OUTDATED",
                    refresh_panels=["center"],
                )
            return ActionResult.error(
                "Server info needs either the Imperal Bridge plugin installed on the site, "
                "or SSH configured with add_ssh — neither is available for this site yet.",
                retryable=False, code="SERVER_INFO_UNAVAILABLE")
        try:
            info = await wp_cli.get_server_info(cred)
        except Exception as e:
            await ctx.log(f"get_server_info: {e}", level="error")
            return ActionResult.error("SSH connection failed — check credentials.", retryable=True)

        if "error" in info:
            await storage.save_site_record(ctx, {**record, "ssh_error": info["error"]})
            # Same reasoning as the bridge_outdated branch above: this path
            # persists ssh_error to storage (which the Server section reads),
            # so the panel needs an explicit refresh_panels to show it.
            return ActionResult(
                status="error", data={}, summary="",
                error=f"SSH/WP-CLI error: {info['error']}",
                retryable=True, refresh_panels=["center"],
            )
        source = "ssh"

    result = ServerInfo(
        id=params.site_id,
        title=f"Server: {params.site_id}",
        kind="server_info",
        wp_version=info["wp_version"],
        php_version=info["php_version"],
        plugin_updates=info["plugin_updates"],
        plugin_updates_list=info["plugin_updates_list"],
        theme_updates=info["theme_updates"],
        theme_updates_list=info["theme_updates_list"],
        core_update=info["core_update"],
        core_update_version=info["core_update_version"],
        cron_count=info["cron_count"],
        db_size_mb=str(info["db_size_mb"]) if info["db_size_mb"] not in (None, "") else "",
        source=source,
    )
    updates = result.plugin_updates + result.theme_updates + (1 if result.core_update else 0)

    if not result.wp_version:
        return ActionResult.error(
            "Server info answered but returned no WordPress version — check the plugin/WP-CLI response.",
            retryable=True,
        )

    await storage.save_site_record(ctx, {
        **record,
        "wp_version":          result.wp_version,
        "php_version":         result.php_version,
        "db_size_mb":          result.db_size_mb,
        "cron_count":          result.cron_count,
        "pending_updates":     updates,
        "plugin_updates_list": info["plugin_updates_list"],
        "theme_updates_list":  info["theme_updates_list"],
        "server_source":       source,
        "server_last_checked": now_iso(),
        "ssh_error":           "",
    })

    icon = "⚠️" if updates else "✅"
    via = "Bridge" if source == "bridge" else "SSH"
    summary = f"{icon} WP {result.wp_version} · PHP {result.php_version} (via {via})"
    if updates:
        summary += f" · {updates} update(s) available"
    return ActionResult.success(result, summary=summary, refresh_panels=["sidebar", "center"])
