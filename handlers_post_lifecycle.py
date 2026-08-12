"""Post/page lifecycle gaps: delete (trash or permanent), duplicate, and
bulk status change.

create_post/update_post covered writing content; there was no way back out
(delete) and no way to fan a single status change across many items at once
(bulk), and no quick "clone this as a starting point" (duplicate) — all
three are common everyday WP Core actions on the native /wp/v2 REST API,
no Bridge/SSH needed.
"""
import hashlib
import json

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ApplyBulkPostStatusParams,
    BulkPostStatusParams,
    BulkPostStatusResult,
    DeletePostParams,
    DuplicatePostParams,
    GetPostRevisionsParams,
    PostDeleteResult,
    PostResult,
    RestoreRevisionParams,
    Revision,
    SetPostPasswordParams,
)
import storage
from wp_client import (
    create_post as wp_create_post,
    update_post as wp_update_post,
    wp_error_code,
    wp_error_message,
    wp_get,
    wp_request,
    wp_title,
)

_POST_TYPE_BASES = {"post": "posts", "page": "pages"}


def _rest_base(post_type: str) -> str:
    return _POST_TYPE_BASES.get(post_type, post_type)


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
    if status_code == 404:
        return ActionResult.error(
            "That post/page does not exist.", retryable=False, code="WP_POST_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage this content. Reconnect with an "
            "administrator or editor Application Password.",
            retryable=False, code="WP_POST_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


@chat.function(
    "delete_post",
    description=(
        "Delete a WordPress post or page. By default moves it to Trash (recoverable in "
        "WordPress); pass force=true to permanently delete it instead, bypassing Trash."
    ),
    action_type="destructive",
    data_model=PostDeleteResult,
    effects=["wp.post_delete"],
    event="wordpress-hub.delete_post",
)
async def delete_post(ctx, params: DeletePostParams) -> ActionResult:
    """DELETE the post/page via the WordPress REST API."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")

    try:
        r = await wp_request(
            ctx, "delete", base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}",
            username=username, app_password=pw,
            params={"force": "true"} if params.force else None)
    except Exception as e:
        await ctx.log(f"delete_post request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)

    trashed = not params.force
    entity = PostDeleteResult(
        id=str(params.post_id), title="", kind=f"wp_{params.post_type}",
        deleted=True, trashed=trashed,
    )
    verb = "moved to Trash" if trashed else "permanently deleted"
    return ActionResult.success(entity, summary=f"Post {params.post_id} {verb}",
                                 refresh_panels=["center"])


@chat.function(
    "duplicate_post",
    description=(
        "Duplicate an existing WordPress post or page as a new draft, copying its title "
        "(with a suffix), content, excerpt, and category. Useful as a starting point for "
        "a similar piece of content or a seasonal re-run of an old page."
    ),
    action_type="write",
    data_model=PostResult,
    effects=["wp.post_create"],
    event="wordpress-hub.duplicate_post",
)
async def duplicate_post(ctx, params: DuplicatePostParams) -> ActionResult:
    """Read the source post, then create a new draft copy of it."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")

    try:
        r = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}",
                         username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"duplicate_post fetch failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    source = r.body if isinstance(r.body, dict) else {}

    title = wp_title(source) + params.title_suffix
    content = source.get("content", {}).get("rendered", "") if isinstance(source.get("content"), dict) else ""
    excerpt = source.get("excerpt", {}).get("rendered", "") if isinstance(source.get("excerpt"), dict) else ""
    categories = source.get("categories") or []
    category_id = categories[0] if categories else None

    try:
        create_r = await wp_create_post(
            ctx, base_url, username, pw, post_type=rest_base, title=title, content=content,
            status="draft", excerpt=excerpt or None, category_id=category_id,
            tag_ids=source.get("tags") or None, featured_media=source.get("featured_media") or None,
        )
    except Exception as e:
        await ctx.log(f"duplicate_post create failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= create_r.status_code < 300:
        return _failure(create_r.status_code, create_r.body)

    new_item = create_r.body
    link = new_item.get("link", "")
    result = PostResult(
        id=str(new_item.get("id", "")), title=wp_title(new_item), kind=f"wp_{params.post_type}",
        url=link, link=link, post_type=params.post_type, slug=new_item.get("slug", ""),
        status=new_item.get("status"), date=new_item.get("date"),
    )
    return ActionResult.success(result, summary=f"Duplicated as draft '{result.title}' (id {result.id})",
                                 refresh_panels=["center"])


def _post_state_token(items: list[dict]) -> str:
    """Hash only mutable core fields that make a reviewed status change stale."""
    state = [
        {"id": int(item.get("id", 0)), "modified": item.get("modified_gmt", ""),
         "status": item.get("status", "")}
        for item in sorted(items, key=lambda row: int(row.get("id", 0)))
    ]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_post_targets(ctx, params: BulkPostStatusParams):
    valid_statuses = {"publish", "draft", "pending", "private", "trash"}
    status = params.status.strip().lower()
    if status not in valid_statuses:
        return None, ActionResult.error(
            f"Invalid status '{params.status}' — use one of {', '.join(sorted(valid_statuses))}.",
            retryable=False, code="POST_INVALID_STATUS")
    if len(set(params.post_ids)) != len(params.post_ids):
        return None, ActionResult.error("Each post id may appear only once.", retryable=False, code="POST_DUPLICATE_IDS")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")
    items = []
    for post_id in params.post_ids:
        try:
            response = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{post_id}",
                                    username=username, app_password=pw, params={"context": "edit"})
        except Exception as exc:
            await ctx.log(f"bulk post preview read #{post_id} failed: {exc}", level="error")
            return None, ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
        if not 200 <= response.status_code < 300 or not isinstance(response.body, dict):
            return None, _failure(response.status_code, response.body)
        items.append(response.body)
    return (base_url, username, pw, rest_base, status, items), None


@chat.function(
    "preview_bulk_post_status",
    description="Preview a status change for 1-100 explicit posts/pages/CPT items. Makes no writes and returns the exact state token required to apply.",
    action_type="read", data_model=BulkPostStatusResult,
)
async def preview_bulk_post_status(ctx, params: BulkPostStatusParams) -> ActionResult:
    """Read every explicit target and produce a non-mutating status-change diff."""
    targets, err = await _bulk_post_targets(ctx, params)
    if err:
        return err
    _, _, _, _, status, items = targets
    changes = [f"#{item['id']} {wp_title(item) or '(untitled)'}: {item.get('status', '')} → {status}" for item in items]
    result = BulkPostStatusResult(
        id=params.site_id, title="Bulk post status preview", kind="wp_bulk_post_status", preview=True,
        requested=len(params.post_ids), matched=len(items), state_token=_post_state_token(items), changes=changes,
    )
    return ActionResult.success(result, summary=f"Preview: {len(items)} item(s) → '{status}'")


@chat.function(
    "bulk_update_post_status",
    description="Apply a previewed status change to 1-100 explicit posts/pages/CPT items. Requires the exact state token and performs no writes if any item changed since preview.",
    action_type="destructive", data_model=BulkPostStatusResult,
    effects=["wp.post_bulk_status_update"], event="wordpress-hub.bulk_update_post_status",
)
async def bulk_update_post_status(ctx, params: ApplyBulkPostStatusParams) -> ActionResult:
    """Apply a reviewed status change only after all explicit targets still match preview."""
    targets, err = await _bulk_post_targets(ctx, params)
    if err:
        return err
    base_url, username, pw, rest_base, status, items = targets
    if _post_state_token(items) != params.expected_state_token:
        return ActionResult.error("One or more posts changed since preview. Run preview_bulk_post_status again.", retryable=False, code="POST_BULK_STATE_CHANGED")
    updated_ids, failed_ids = [], []
    for item in items:
        post_id = int(item["id"])
        try:
            response = await wp_update_post(ctx, base_url, username, pw, post_id=post_id, post_type=rest_base, status=status)
        except Exception as exc:
            await ctx.log(f"bulk post write #{post_id} failed: {exc}", level="error")
            failed_ids.append(post_id)
            continue
        (updated_ids if 200 <= response.status_code < 300 else failed_ids).append(post_id)
    result = BulkPostStatusResult(
        id=params.site_id, title="Bulk post status result", kind="wp_bulk_post_status", preview=False,
        requested=len(params.post_ids), matched=len(items), updated=len(updated_ids), failed=len(failed_ids),
        updated_ids=updated_ids, failed_ids=failed_ids,
    )
    if not updated_ids:
        return ActionResult.error("WordPress did not update any requested posts.", retryable=True, code="POST_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Updated {len(updated_ids)} item(s) to '{status}'; {len(failed_ids)} failed", refresh_panels=["center"])


@chat.function(
    "get_post_revisions",
    description=(
        "List the stored revisions of a post/page, newest first -- author, date, and a short "
        "excerpt preview of each. Native /wp/v2 revisions endpoint, no Bridge/SSH needed."
    ),
    action_type="read",
    data_model=sdl.EntityList[Revision],
)
async def get_post_revisions(ctx, params: GetPostRevisionsParams) -> ActionResult:
    """Read the revision history of one post/page."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")

    try:
        r = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}/revisions",
                         username=username, app_password=pw, params={"per_page": params.limit})
    except Exception as e:
        await ctx.log(f"get_post_revisions failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    if not isinstance(r.body, list):
        return ActionResult.error("WordPress returned an unexpected response.",
                                  retryable=False, code="WP_RESPONSE_UNEXPECTED")

    items = []
    for rev in r.body:
        excerpt = rev.get("excerpt", {}).get("rendered", "") if isinstance(rev.get("excerpt"), dict) else ""
        items.append(Revision(
            id=str(rev.get("id", "")), title=wp_title(rev), kind="wp_revision",
            post_id=params.post_id, author=str(rev.get("author", "")),
            date=rev.get("date"), excerpt_preview=excerpt[:200],
        ))
    return ActionResult.success(
        sdl.EntityList[Revision](items=items),
        summary=f"{len(items)} revision(s) for post #{params.post_id}")


@chat.function(
    "restore_revision",
    description=(
        "Restore a post/page's content and title to a previous revision. WordPress core has no "
        "native REST 'restore' verb, so this reads the chosen revision's content/title/excerpt "
        "and writes them back onto the live post as a normal update -- the live post's own "
        "revision history still records this as a new change, nothing is silently rewritten."
    ),
    action_type="write",
    data_model=PostResult,
    effects=["wp.post_update"],
    event="wordpress-hub.restore_revision",
)
async def restore_revision(ctx, params: RestoreRevisionParams) -> ActionResult:
    """Copy one stored revision's content/title/excerpt onto the live post."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")

    try:
        rev_r = await wp_get(
            ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}/revisions/{params.revision_id}",
            username=username, app_password=pw, params={"context": "edit"})
    except Exception as e:
        await ctx.log(f"restore_revision fetch failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= rev_r.status_code < 300:
        return _failure(rev_r.status_code, rev_r.body)
    revision = rev_r.body if isinstance(rev_r.body, dict) else {}

    # context=edit returns raw (unfiltered) fields -- the actual stored Gutenberg block
    # markup, not the_content-filtered display HTML. Falls back to rendered if a site's
    # edit-context response ever omits raw (shouldn't happen with a valid Application Password).
    def _raw_or_rendered(field):
        v = revision.get(field)
        if isinstance(v, dict):
            return v.get("raw", v.get("rendered", ""))
        return ""

    title = _raw_or_rendered("title")
    content = _raw_or_rendered("content")
    excerpt = _raw_or_rendered("excerpt")

    try:
        update_r = await wp_update_post(
            ctx, base_url, username, pw, post_id=params.post_id, post_type=rest_base,
            title=title, content=content, excerpt=excerpt)
    except Exception as e:
        await ctx.log(f"restore_revision update failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= update_r.status_code < 300:
        return _failure(update_r.status_code, update_r.body)

    updated = update_r.body if isinstance(update_r.body, dict) else {}
    link = updated.get("link", "")
    result = PostResult(
        id=str(params.post_id), title=wp_title(updated), kind=f"wp_{params.post_type}",
        url=link, link=link, post_type=params.post_type, slug=updated.get("slug", ""),
        status=updated.get("status"), date=updated.get("date"),
    )
    return ActionResult.success(
        result, summary=f"Restored post #{params.post_id} to revision #{params.revision_id}",
        refresh_panels=["center"])


@chat.function(
    "set_post_password",
    description=(
        "Password-protect a post/page (visitors must enter the password to view it), or remove "
        "protection by passing an empty password. Native WordPress core field, no Bridge needed."
    ),
    action_type="write",
    data_model=PostResult,
    effects=["wp.post_update"],
    event="wordpress-hub.set_post_password",
)
async def set_post_password(ctx, params: SetPostPasswordParams) -> ActionResult:
    """Set or clear a post/page's view password."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")

    try:
        r = await wp_update_post(ctx, base_url, username, pw, post_id=params.post_id,
                                 post_type=rest_base, password=params.password)
    except Exception as e:
        await ctx.log(f"set_post_password failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)

    updated = r.body if isinstance(r.body, dict) else {}
    link = updated.get("link", "")
    result = PostResult(
        id=str(params.post_id), title=wp_title(updated), kind=f"wp_{params.post_type}",
        url=link, link=link, post_type=params.post_type, slug=updated.get("slug", ""),
        status=updated.get("status"), date=updated.get("date"),
    )
    verb = "protected with a password" if params.password else "password protection removed"
    return ActionResult.success(result, summary=f"Post #{params.post_id} {verb}",
                                 refresh_panels=["center"])
