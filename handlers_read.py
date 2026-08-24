import asyncio
import hashlib
import json

from imperal_sdk import ActionResult, sdl
from app import chat, ext
from models import (_NoParams, Site, ListContentParams, ListMediaParams,
                    Post, Page, MediaItem, SiteIdParams, SiteHealth, RefreshAllResult,
                    ListCommentsParams, SetCommentStatusParams, BulkCommentStatusParams,
                    ApplyBulkCommentStatusParams, BulkCommentStatusResult, ReplyToCommentParams,
                    EditCommentContentParams,
                    ListCustomPostsParams, Comment, WPUser, Plugin,
                    PurgeCacheParams, CacheActionResult, InstallPluginParams, PluginInstallResult,
                    ServerInfo, UpdateMediaAltParams, MediaAltResult,
                    MediaAltItem, BulkMediaAltParams, ApplyBulkMediaAltParams,
                    BulkMediaAltResult, SetSingleMediaAltParams,
                    GetPostContentParams, PostContent,
                    ReplacePostContentTextParams, ReplaceTextResult)
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


@chat.function(
    "get_post_content",
    description=(
        "Read one post/page's raw rendered content (HTML), excerpt, and Polylang language "
        "(when exposed), straight from the site's native REST API -- no Bridge/SSH needed. "
        "Use to audit an already-published article, e.g. checking it for stray scaffolding "
        "headings ('Intro', 'CTA') or a wrong Polylang language before correcting it with "
        "update_post."
    ),
    action_type="read",
    data_model=PostContent,
)
async def get_post_content(ctx, params: GetPostContentParams) -> ActionResult:
    """Fetch one item's content/excerpt/lang via the item's own native REST endpoint."""
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, params.site_id)
    if not pw:
        return ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    base_url, username = record["url"], record["username"]
    post_type = (params.post_type or "post").strip() or "post"
    rest_base = {"post": "posts", "page": "pages"}.get(post_type, post_type)
    try:
        r = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}",
                         username=username, app_password=pw, params={"context": "edit"})
    except Exception as e:
        await ctx.log(f"get_post_content request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if r.status_code == 404:
        return ActionResult.error("That post/page does not exist.", retryable=False, code="POST_NOT_FOUND")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return ActionResult.error(wp_error_message(r.status_code),
                                  retryable=r.status_code >= 500, code=wp_error_code(r.status_code))
    body = r.body
    entity = PostContent(
        id=str(body.get("id", params.post_id)), title=wp_title(body), kind=f"wp_{post_type}",
        post_id=body.get("id", params.post_id), slug=body.get("slug", ""),
        content_html=(body.get("content") or {}).get("rendered", "") or (body.get("content") or {}).get("raw", ""),
        excerpt_html=(body.get("excerpt") or {}).get("rendered", ""),
        lang=str(body.get("lang", "") or ""),
    )
    return ActionResult.success(entity, summary=f"Read content for '{entity.title}' ({len(entity.content_html)} chars).")


@chat.function(
    "replace_post_content_text",
    description=(
        "Fix ONE exact substring inside a post/page's raw content -- e.g. a CTA link that "
        "wrongly points to the wrong-language contact page -- without touching anything else "
        "in the article (no rebuild of blocks, so existing images/structure are never at risk). "
        "'find' must match EXACTLY ONCE in the raw content; the call is rejected if it matches "
        "zero or multiple times, so you never guess which occurrence you meant."
    ),
    action_type="write",
    data_model=ReplaceTextResult,
    effects=["wp.post_update"],
    event="wordpress-hub.replace_post_content_text",
)
async def replace_post_content_text(ctx, params: ReplacePostContentTextParams) -> ActionResult:
    """Read raw content, replace an exact single-occurrence substring, write it back."""
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, params.site_id)
    if not pw:
        return ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    base_url, username = record["url"], record["username"]
    post_type = (params.post_type or "post").strip() or "post"
    rest_base = {"post": "posts", "page": "pages"}.get(post_type, post_type)
    try:
        r = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}",
                         username=username, app_password=pw, params={"context": "edit"})
    except Exception as e:
        await ctx.log(f"replace_post_content_text read failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if r.status_code == 404:
        return ActionResult.error("That post/page does not exist.", retryable=False, code="POST_NOT_FOUND")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return ActionResult.error(wp_error_message(r.status_code),
                                  retryable=r.status_code >= 500, code=wp_error_code(r.status_code))
    body = r.body
    raw_content = (body.get("content") or {}).get("raw", "") or (body.get("content") or {}).get("rendered", "")
    occurrences = raw_content.count(params.find)
    if occurrences == 0:
        return ActionResult.error(
            "That exact text was not found in the post's current content — nothing changed.",
            retryable=False, code="TEXT_NOT_FOUND")
    if occurrences > 1:
        return ActionResult.error(
            f"That text appears {occurrences} times in the post's content — give more surrounding "
            "context so it matches exactly once, to avoid changing the wrong occurrence.",
            retryable=False, code="TEXT_NOT_UNIQUE")
    new_content = raw_content.replace(params.find, params.replace, 1)
    try:
        wr = await wp_post(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}",
                           username=username, app_password=pw, json={"content": new_content})
    except Exception as e:
        await ctx.log(f"replace_post_content_text write failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if wr.status_code != 200:
        return ActionResult.error(wp_error_message(wr.status_code),
                                  retryable=wr.status_code >= 500, code=wp_error_code(wr.status_code))
    entity = ReplaceTextResult(
        id=str(params.post_id), title=wp_title(wr.body if isinstance(wr.body, dict) else body),
        kind=f"wp_{post_type}", post_id=params.post_id, occurrences_replaced=1,
    )
    return ActionResult.success(entity, summary=f"Replaced 1 occurrence in post #{params.post_id}.",
                                refresh_panels=["center"])


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


def _media_alt_state_token(media: list[dict]) -> str:
    state = [{"id": int(item.get("id", 0)), "alt_text": item.get("alt_text", ""),
              "modified": item.get("modified", "")} for item in sorted(media, key=lambda item: int(item.get("id", 0)))]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_media_alt_targets(ctx, params: BulkMediaAltParams):
    if len({item.media_id for item in params.items}) != len(params.items):
        return None, ActionResult.error("Each media id may appear only once.", retryable=False, code="MEDIA_DUPLICATE_IDS")
    blank = [item.media_id for item in params.items if not item.alt_text.strip()]
    if blank:
        return None, ActionResult.error("Alt text must not be empty in guarded batch updates.", retryable=False, code="MEDIA_EMPTY_ALT")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, ActionResult.error(err, retryable=False)
    base_url, username, pw = auth
    media = []
    for item in params.items:
        response = await wp_get(ctx, base_url, f"/wp-json/wp/v2/media/{item.media_id}",
                                username=username, app_password=pw, params={"_fields": "id,alt_text,modified"})
        if response.status_code != 200 or not isinstance(response.body, dict):
            return None, ActionResult.error(f"Could not read media #{item.media_id}: {wp_error_message(response.status_code)}.",
                                            retryable=response.status_code >= 500, code="MEDIA_TARGET_UNAVAILABLE")
        media.append(response.body)
    return (base_url, username, pw, media), None


@chat.function("preview_bulk_media_alt", description="Preview replacing alt text for 1-100 explicit media items. Makes no writes and returns the exact token required to apply.", action_type="read", data_model=BulkMediaAltResult)
async def preview_bulk_media_alt(ctx, params: BulkMediaAltParams) -> ActionResult:
    """Return an exact no-write alt-text batch diff and deterministic state token."""
    targets, err = await _bulk_media_alt_targets(ctx, params)
    if err:
        return err
    _, _, _, media = targets
    proposed = {item.media_id: item.alt_text.strip() for item in params.items}
    changes = [f"#{item['id']}: {(item.get('alt_text') or '(empty)')} → {proposed[int(item['id'])]}" for item in media]
    return ActionResult.success(BulkMediaAltResult(preview=True, requested=len(params.items), matched=len(media),
        state_token=_media_alt_state_token(media), changes=changes), summary=f"Previewed {len(media)} media alt-text change(s); no changes made.")


@chat.function("apply_bulk_media_alt", description="Apply a previously previewed alt-text change to 1-100 explicit media items. Rechecks every item before any write and stops if any changed.", action_type="write", data_model=BulkMediaAltResult, effects=["wp.media_bulk_update"], event="wordpress-hub.apply_bulk_media_alt")
async def apply_bulk_media_alt(ctx, params: ApplyBulkMediaAltParams) -> ActionResult:
    """Recheck every media item before applying the reviewed alt-text batch."""
    targets, err = await _bulk_media_alt_targets(ctx, params)
    if err:
        return err
    base_url, username, pw, media = targets
    if _media_alt_state_token(media) != params.expected_state_token:
        return ActionResult.error("One or more media items changed after preview; no alt text was written. Preview again.", retryable=False, code="MEDIA_BULK_STATE_CHANGED")
    proposed = {item.media_id: item.alt_text.strip() for item in params.items}
    updated, failed = [], []
    for media_id in params.items:
        response = await wp_post(ctx, base_url, f"/wp-json/wp/v2/media/{media_id.media_id}", username=username, app_password=pw,
                                 json={"alt_text": proposed[media_id.media_id]})
        if response.status_code == 200 and isinstance(response.body, dict) and (response.body.get("alt_text") or "").strip() == proposed[media_id.media_id]:
            updated.append(media_id.media_id)
        else:
            failed.append(media_id.media_id)
    result = BulkMediaAltResult(preview=False, requested=len(params.items), matched=len(media), updated=len(updated), failed=len(failed), updated_ids=updated, failed_ids=failed)
    if failed and not updated:
        return ActionResult.error("No media alt text was updated.", retryable=True, code="MEDIA_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Updated alt text on {len(updated)} media item(s); {len(failed)} failed.", refresh_panels=["center"])


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
    """Ping every connected site in parallel (bounded concurrency -- see
    task #2371: an unbounded fan-out here could overwhelm a weak self-hosted
    WordPress instance or trip a host's simultaneous-connection limit when
    many sites are connected), update stored statuses, clear content caches."""
    rows = await storage.list_site_records(ctx)
    if not rows:
        return ActionResult.error("No sites connected.", retryable=False)

    _REFRESH_CONCURRENCY = 5
    semaphore = asyncio.Semaphore(_REFRESH_CONCURRENCY)

    async def _check(record):
        async with semaphore:
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


def _comment_state_token(comments: list[dict]) -> str:
    state = [{"id": int(c.get("id", 0)), "status": c.get("status", ""),
              "modified": c.get("date_gmt", "")}
             for c in sorted(comments, key=lambda item: int(item.get("id", 0)))]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_comment_targets(ctx, params: BulkCommentStatusParams):
    status = params.status.strip().lower()
    if status not in {"approved", "hold", "spam", "trash"}:
        return None, ActionResult.error("Use approved, hold, spam, or trash.", retryable=False, code="COMMENT_INVALID_STATUS")
    if len(set(params.comment_ids)) != len(params.comment_ids):
        return None, ActionResult.error("Each comment id may appear only once.", retryable=False, code="COMMENT_DUPLICATE_IDS")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, ActionResult.error(err, retryable=False)
    base_url, username, pw = auth
    comments = []
    for comment_id in params.comment_ids:
        try:
            response = await wp_get(ctx, base_url, f"/wp-json/wp/v2/comments/{comment_id}",
                                    username=username, app_password=pw, params={"context": "edit"})
        except Exception as exc:
            await ctx.log(f"bulk comment read #{comment_id} failed: {exc}", level="error")
            return None, ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
        if response.status_code != 200 or not isinstance(response.body, dict):
            code = "COMMENT_NOT_FOUND" if response.status_code == 404 else wp_error_code(response.status_code)
            return None, ActionResult.error(wp_error_message(response.status_code), retryable=response.status_code >= 500,
                                            code=code)
        comments.append(response.body)
    return (base_url, username, pw, status, comments), None


@chat.function(
    "preview_bulk_comment_status",
    description="Preview changing moderation status for 1-100 explicit comments. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkCommentStatusResult,
)
async def preview_bulk_comment_status(ctx, params: BulkCommentStatusParams) -> ActionResult:
    """Read every explicit comment and produce its guarded bulk-status diff."""
    targets, err = await _bulk_comment_targets(ctx, params)
    if err:
        return err
    _, _, _, status, comments = targets
    return ActionResult.success(BulkCommentStatusResult(
        id=params.site_id, title="Bulk comment status preview", kind="wp_bulk_comment_status",
        preview=True, requested=len(params.comment_ids), matched=len(comments),
        state_token=_comment_state_token(comments),
        changes=[f"#{c['id']}: {c.get('status', '')} → {status}" for c in comments],
    ), summary=f"Previewed {len(comments)} comment status change(s); no changes made.")


@chat.function(
    "apply_bulk_comment_status",
    description="Apply a previously previewed comment moderation status change to 1-100 explicit comment ids. Stops before all writes if any comment changed.",
    action_type="destructive", data_model=BulkCommentStatusResult,
    effects=["wp.comment_status_update"], event="wordpress-hub.apply_bulk_comment_status",
)
async def apply_bulk_comment_status(ctx, params: ApplyBulkCommentStatusParams) -> ActionResult:
    """Revalidate every comment snapshot, then update the reviewed explicit targets."""
    targets, err = await _bulk_comment_targets(ctx, params)
    if err:
        return err
    base_url, username, pw, status, comments = targets
    if _comment_state_token(comments) != params.expected_state_token:
        return ActionResult.error("One or more comments changed since preview. Preview again before applying.", retryable=False, code="COMMENT_BULK_STATE_CHANGED")
    updated, failed = [], []
    for comment in comments:
        comment_id = int(comment["id"])
        try:
            response = await wp_request(ctx, "post", base_url, f"/wp-json/wp/v2/comments/{comment_id}",
                                        username=username, app_password=pw, json={"status": status})
        except Exception as exc:
            await ctx.log(f"bulk comment update #{comment_id} failed: {exc}", level="error")
            failed.append(comment_id)
            continue
        (updated if response.status_code == 200 else failed).append(comment_id)
    result = BulkCommentStatusResult(id=params.site_id, title="Bulk comment status result", kind="wp_bulk_comment_status",
        preview=False, requested=len(params.comment_ids), matched=len(comments), updated=len(updated), failed=len(failed),
        updated_ids=updated, failed_ids=failed)
    if not updated:
        return ActionResult.error("No comment statuses were changed.", retryable=bool(failed), code="COMMENT_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Changed {len(updated)} comment status(es); {len(failed)} failed.", refresh_panels=["center"])


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
                 "installed version, and an available update version. Reads through the "
                 "Imperal Bridge plugin if it's installed (no SSH needed at all -- built "
                 "from WordPress's own get_plugins()/is_plugin_active()/get_plugin_updates() "
                 "calls, the same data wp-admin's own Plugins screen reads its update "
                 "notices from), or falls back to SSH + WP-CLI (`wp plugin list`) if SSH is "
                 "configured with add_ssh. Read-only."),
    action_type="read",
    data_model=sdl.EntityList[Plugin],
)
async def list_plugins(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/maintenance/list-plugins), SSH-fallback (`wp plugin list`)."""
    auth, err = await handlers_maintenance._site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await handlers_maintenance._bridge_get(
        ctx, base_url, username, pw, handlers_maintenance.BRIDGE_MAINTENANCE_LIST_PLUGINS_PATH,
    )
    if body is not None:
        rows = body.get("plugins", [])
    else:
        cred = await storage.get_ssh_cred(ctx, params.site_id)
        if not cred:
            return handlers_maintenance._no_bridge_no_ssh_error()
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
            title=str(row.get("title") or row.get("name", "")),
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
                 "(LiteSpeed Cache or W3 Total Cache) — if none is found, reports that "
                 "clearly instead of silently doing nothing. Reads through the Imperal Bridge "
                 "plugin if it's installed (no SSH needed at all — fires the cache plugin's own "
                 "real purge hook, litespeed_purge_all / w3tc_flush_all), or falls back to "
                 "SSH + WP-CLI if SSH is configured with add_ssh instead."),
    action_type="write",
    data_model=CacheActionResult,
    effects=["wp.purge_cache"],
    event="wordpress-hub.purge_cache",
)
async def purge_cache(ctx, params: PurgeCacheParams) -> ActionResult:
    """Purge the site's cache -- Bridge-first (imperal/v1/maintenance/purge-cache,
    which fires litespeed_purge_all / w3tc_flush_all directly from inside the WP
    process), SSH-fallback (`wp litespeed-purge` / `wp w3-total-cache flush all`).

    Both tiers detect the active cache plugin themselves rather than assuming
    one is installed -- a purge for a cache plugin that is not even active
    would silently do nothing, which is worse than refusing. Covers LiteSpeed
    Cache and W3 Total Cache only; WP Rocket and WP Super Cache are
    deliberately NOT covered because their WP-CLI support ships as a
    SEPARATE package not guaranteed present, and their own PHP has no
    equally-standard single purge-everything hook confirmed the same way.
    """
    scope = (params.scope or "all").strip().lower()
    if scope not in ("all", "front"):
        return ActionResult.error(
            f"Invalid scope '{params.scope}' — use 'all' or 'front'.", retryable=False
        )

    auth, err = await handlers_maintenance._site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await handlers_maintenance._bridge_post(
        ctx, base_url, username, pw, handlers_maintenance.BRIDGE_MAINTENANCE_PURGE_CACHE_PATH,
        json_body={"scope": scope},
    )
    if body is not None:
        plugin_slug = body.get("cache_plugin", "")
        await ctx.log(f"purge_cache: executed via Bridge — scope={scope} plugin={plugin_slug} site_id={params.site_id}", level="info")
        return ActionResult.success(
            CacheActionResult(
                id=params.site_id, title=f"{plugin_slug} purge", kind="wp_cache_action",
                scope=scope, cache_plugin=plugin_slug, output="",
            ),
            summary=f"Purged {plugin_slug} cache ({scope}).",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return handlers_maintenance._no_bridge_no_ssh_error()

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

    await ctx.log(f"purge_cache: executed via SSH — scope={scope} plugin={plugin_slug} site_id={params.site_id}", level="info")
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
