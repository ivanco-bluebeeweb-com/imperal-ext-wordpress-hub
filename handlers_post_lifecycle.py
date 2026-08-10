"""Post/page lifecycle gaps: delete (trash or permanent), duplicate, and
bulk status change.

create_post/update_post covered writing content; there was no way back out
(delete) and no way to fan a single status change across many items at once
(bulk), and no quick "clone this as a starting point" (duplicate) — all
three are common everyday WP Core actions on the native /wp/v2 REST API,
no Bridge/SSH needed.
"""
from imperal_sdk import ActionResult

from app import chat
from models import (
    BulkPostStatusResult,
    BulkUpdatePostStatusParams,
    DeletePostParams,
    DuplicatePostParams,
    PostDeleteResult,
    PostResult,
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


@chat.function(
    "bulk_update_post_status",
    description=(
        "Change the status (publish, draft, pending, private, or trash) of several explicit "
        "posts/pages at once. All ids must be the same post_type. Partial failures are "
        "reported per id, not silently dropped."
    ),
    action_type="write",
    data_model=BulkPostStatusResult,
    effects=["wp.post_update"],
    event="wordpress-hub.bulk_update_post_status",
)
async def bulk_update_post_status(ctx, params: BulkUpdatePostStatusParams) -> ActionResult:
    """Apply a single status change to each listed post/page id independently."""
    valid_statuses = {"publish", "draft", "pending", "private", "trash"}
    status = params.status.strip().lower()
    if status not in valid_statuses:
        return ActionResult.error(
            f"Invalid status '{params.status}' — use one of {', '.join(sorted(valid_statuses))}.",
            retryable=False, code="POST_INVALID_STATUS")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    rest_base = _rest_base(params.post_type.strip() or "post")

    updated_ids: list[int] = []
    failed_ids: list[int] = []
    for post_id in params.post_ids:
        try:
            r = await wp_update_post(ctx, base_url, username, pw, post_id=post_id,
                                     post_type=rest_base, status=status)
        except Exception as e:
            await ctx.log(f"bulk_update_post_status failed for {post_id}: {e}", level="error")
            failed_ids.append(post_id)
            continue
        if 200 <= r.status_code < 300:
            updated_ids.append(post_id)
        else:
            failed_ids.append(post_id)

    result = BulkPostStatusResult(
        id=params.site_id, title="", kind="wp_bulk_post_status",
        updated_ids=updated_ids, failed_ids=failed_ids,
    )
    summary = f"{len(updated_ids)}/{len(params.post_ids)} updated to '{status}'"
    if failed_ids:
        summary += f" — {len(failed_ids)} failed: {failed_ids}"
    return ActionResult.success(result, summary=summary, refresh_panels=["center"])
