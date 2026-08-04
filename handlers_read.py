import asyncio

from imperal_sdk import ActionResult, sdl
from app import chat, ext
from models import (_NoParams, Site, ListContentParams, ListMediaParams,
                    Post, Page, MediaItem, SiteIdParams, SiteHealth, RefreshAllResult,
                    ListCommentsParams, ListCustomPostsParams, Comment, WPUser, Plugin,
                    PurgeCacheParams, CacheActionResult, InstallPluginParams, PluginInstallResult,
                    ServerInfo, UpdateMediaAltParams, MediaAltResult)
import wp_cli
from wp_client import wp_get, wp_post, wp_error_message, wp_error_code, wp_title, now_iso
import storage


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
    q = {"per_page": params.limit}
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
    q = {"per_page": params.limit}
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
    event="wp-site-connector.update_media_alt",
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
    event="wp-site-connector.refresh_site",
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
    event="wp-site-connector.refresh_all_sites",
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
                 "(currently LiteSpeed Cache) from the site's real, live plugin list — "
                 "if none is found, reports that clearly instead of silently doing nothing. "
                 "Requires SSH access configured with add_ssh."),
    action_type="write",
    data_model=CacheActionResult,
    effects=["wp.purge_cache"],
    event="wp-site-connector.purge_cache",
)
async def purge_cache(ctx, params: PurgeCacheParams) -> ActionResult:
    """Purge the site's cache via `wp litespeed-purge` over SSH.

    Detects LiteSpeed Cache from the site's own live plugin list rather than
    assuming it is installed — a purge command for a cache plugin that is not
    even active would silently do nothing, which is worse than refusing.
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
    if "litespeed-cache" not in active:
        await ctx.log(
            f"purge_cache: rejected — no known cache plugin active on site_id={params.site_id}",
            level="info",
        )
        return ActionResult.error(
            "No supported cache plugin (LiteSpeed Cache) is active on this site. "
            "Call list_plugins to see what's installed.", retryable=False
        )

    try:
        output, run_error = await wp_cli.purge_litespeed_cache(cred, scope)
    except Exception as error:
        await ctx.log(f"purge_cache: {error}", level="error")
        return ActionResult.error("Could not purge the cache over SSH.", retryable=True)
    if run_error:
        await ctx.log(f"purge_cache: SSH/WP-CLI error — {run_error}", level="error")
        return ActionResult.error(run_error, retryable=True)

    await ctx.log(f"purge_cache: executed — scope={scope} site_id={params.site_id}", level="info")
    return ActionResult.success(
        CacheActionResult(
            id=params.site_id, title="litespeed-cache purge", kind="wp_cache_action",
            scope=scope, cache_plugin="litespeed-cache", output=(output or "").strip(),
        ),
        summary=f"Purged litespeed-cache cache ({scope}).",
    )


@chat.function(
    "install_plugin",
    description=("Install a WordPress plugin via WP-CLI, from a WordPress.org slug "
                 "(e.g. 'imperal-media-bridge') or a direct https:// .zip URL, and optionally "
                 "activate it immediately. Requires SSH access configured with add_ssh. Use this "
                 "to install Imperal's own companion bridge plugins (Media Bridge, Builder Bridge, "
                 "SEO Bridge) or any third-party plugin the site needs."),
    action_type="write",
    data_model=PluginInstallResult,
    effects=["wp.install_plugin"],
    event="wp-site-connector.install_plugin",
)
async def install_plugin(ctx, params: InstallPluginParams) -> ActionResult:
    """Install (and optionally activate) a plugin over SSH via `wp plugin install`."""
    source = (params.source or "").strip()
    if not source:
        return ActionResult.error("source is required — a WordPress.org slug or a .zip URL.", retryable=False)

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "SSH is not configured for this site. Add SSH access first.", retryable=False
        )

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


@chat.function(
    "get_server_info",
    description="Get server information for a WordPress site via SSH + WP-CLI: PHP version, WordPress version, available plugin/theme/core updates, cron job count, database size. SSH must be configured first with add_ssh.",
    action_type="write",
    data_model=ServerInfo,
    effects=["wp.health_check"],
    event="wp-site-connector.get_server_info",
)
async def get_server_info(ctx, params: SiteIdParams) -> ActionResult:
    """Run WP-CLI commands via SSH and return server/site diagnostics."""
    record = await storage.get_site_record(ctx, params.site_id) or {}
    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return ActionResult.error(
            "SSH not configured for this site. Use add_ssh first.", retryable=False
        )
    try:
        info = await wp_cli.get_server_info(cred)
    except Exception as e:
        await ctx.log(f"get_server_info: {e}", level="error")
        return ActionResult.error("SSH connection failed — check credentials.", retryable=True)

    if "error" in info:
        await storage.save_site_record(ctx, {**record, "ssh_error": info["error"]})
        return ActionResult.error(f"SSH/WP-CLI error: {info['error']}", retryable=True,
                                  refresh_panels=["center"])

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
        db_size_mb=info["db_size_mb"],
    )
    updates = result.plugin_updates + result.theme_updates + (1 if result.core_update else 0)

    # Only persist if we actually got real data (SSH succeeded)
    if not result.wp_version:
        return ActionResult.error(
            "SSH connected but WP-CLI returned no data — check the WordPress path and WP-CLI installation.",
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
        "server_last_checked": now_iso(),
    })

    icon = "⚠️" if updates else "✅"
    summary = f"{icon} WP {result.wp_version} · PHP {result.php_version}"
    if updates:
        summary += f" · {updates} update(s) available"
    return ActionResult.success(result, summary=summary, refresh_panels=["sidebar", "center"])
