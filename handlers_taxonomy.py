"""Native WordPress post taxonomies: categories (hierarchical, parent/child)
and tags (flat) — create, list, update, delete.

Distinct from handlers_woocommerce_catalog.py's product categories, which
are a separate WooCommerce taxonomy (/wc/v3/products/categories). These
hit the native /wp/v2/categories and /wp/v2/tags that create_post/update_post
already resolve names against via find_category_id/find_term_ids — but until
now this connector could only resolve existing terms, never create or
manage them. That gap blocked any hands-off publishing pipeline that needs
to introduce a brand-new category or tag for a piece of content.
"""

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    CreatePostCategoryParams,
    CreatePostTagParams,
    DeletePostCategoryParams,
    DeletePostTagParams,
    ListPostCategoriesParams,
    ListPostTagsParams,
    PostTerm,
    TermDeleteResult,
    UpdatePostCategoryParams,
    UpdatePostTagParams,
)
import storage
from wp_client import (
    create_term,
    delete_term,
    list_terms,
    update_term,
    wp_error_code,
    wp_error_message,
)

_CATEGORY_BASE = "categories"
_TAG_BASE = "tags"


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    password = await storage.get_credential(ctx, site_id)
    if not password:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], password), None


def _failure(status_code, body):
    wp_code = str(body.get("code", "")) if isinstance(body, dict) else ""
    if status_code == 404:
        return ActionResult.error(
            "That term does not exist.", retryable=False, code="WP_TERM_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage categories/tags. Reconnect with "
            "an administrator or editor Application Password.",
            retryable=False, code="WP_TAXONOMY_FORBIDDEN")
    if status_code == 400 and wp_code == "term_exists":
        return ActionResult.error(
            "A term with that name already exists in this taxonomy.",
            retryable=False, code="WP_TERM_EXISTS")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _term_entity(item: dict, taxonomy: str) -> PostTerm:
    name = item.get("name") or ""
    return PostTerm(
        id=str(item.get("id", "")), title=str(name), kind=f"wp_{taxonomy}",
        taxonomy=taxonomy, slug=str(item.get("slug", "") or ""),
        description=str(item.get("description", "") or ""),
        parent_id=int(item.get("parent", 0) or 0),
        count=int(item.get("count", 0) or 0),
    )


# ─────────────────────────── categories (hierarchical) ───────────────────────────

@chat.function(
    "list_post_categories",
    description=(
        "List native WordPress post categories (not WooCommerce product categories). "
        "Hierarchical — filter by parent_id to walk the tree: omit parent_id for every "
        "category, or pass parent_id=0 for only top-level ones, or a category id to see "
        "its children."),
    action_type="read", data_model=sdl.EntityList[PostTerm])
async def list_post_categories(ctx, params: ListPostCategoriesParams) -> ActionResult:
    """List categories in the native WordPress category taxonomy."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await list_terms(
        ctx, base_url, username, password, _CATEGORY_BASE,
        parent=params.parent_id, search=params.search,
        per_page=params.limit, page=params.page)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    items = response.body if isinstance(response.body, list) else []
    entities = [_term_entity(item, "category") for item in items]
    return ActionResult.success(
        sdl.EntityList[PostTerm](items=entities),
        summary=f"{len(entities)} categor{'y' if len(entities) == 1 else 'ies'}")


@chat.function(
    "create_post_category",
    description=(
        "Create a new native WordPress post category, optionally nested under an "
        "existing parent category (parent_id) to build a category tree."),
    action_type="write", data_model=PostTerm,
    effects=["wp.post_category_create"], event="wp-site-connector.create_post_category")
async def create_post_category(ctx, params: CreatePostCategoryParams) -> ActionResult:
    """Create one category in the native WordPress category taxonomy."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await create_term(
        ctx, base_url, username, password, _CATEGORY_BASE,
        name=params.name.strip(), description=params.description.strip(),
        parent=params.parent_id)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _term_entity(response.body, "category")
    return ActionResult.success(
        entity, summary=f"Created category {entity.title} (#{entity.id})",
        refresh_panels=["center"])


@chat.function(
    "update_post_category",
    description="Rename a category, change its description, or move it under a different parent.",
    action_type="write", data_model=PostTerm,
    effects=["wp.post_category_update"], event="wp-site-connector.update_post_category")
async def update_post_category(ctx, params: UpdatePostCategoryParams) -> ActionResult:
    """Update selected fields of an existing category."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    fields = {}
    if params.name is not None:
        fields["name"] = params.name.strip()
    if params.description is not None:
        fields["description"] = params.description.strip()
    if params.parent_id is not None:
        fields["parent"] = params.parent_id
    if not fields:
        return ActionResult.error(
            "Nothing to update — pass name, description, and/or parent_id.", retryable=False)
    response = await update_term(
        ctx, base_url, username, password, _CATEGORY_BASE, params.term_id, **fields)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _term_entity(response.body, "category")
    return ActionResult.success(
        entity, summary=f"Updated category {entity.title} (#{entity.id})",
        refresh_panels=["center"])


@chat.function(
    "delete_post_category",
    description=(
        "Permanently delete a native WordPress post category. Posts in it are not "
        "deleted — they simply lose that category. Children of the deleted category "
        "become top-level (WordPress does not cascade-delete a category tree)."),
    action_type="destructive", data_model=TermDeleteResult,
    effects=["wp.post_category_delete"], event="wp-site-connector.delete_post_category")
async def delete_post_category(ctx, params: DeletePostCategoryParams) -> ActionResult:
    """Delete one category from the native WordPress category taxonomy."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await delete_term(ctx, base_url, username, password, _CATEGORY_BASE, params.term_id)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    return ActionResult.success(
        TermDeleteResult(id=str(params.term_id), title=f"category #{params.term_id}", deleted=True),
        summary=f"Deleted category #{params.term_id}", refresh_panels=["center"])


# ───────────────────────────────── tags (flat) ─────────────────────────────────

@chat.function(
    "list_post_tags",
    description="List native WordPress post tags (flat — tags have no parent/child nesting).",
    action_type="read", data_model=sdl.EntityList[PostTerm])
async def list_post_tags(ctx, params: ListPostTagsParams) -> ActionResult:
    """List tags in the native WordPress tag taxonomy."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await list_terms(
        ctx, base_url, username, password, _TAG_BASE,
        search=params.search, per_page=params.limit, page=params.page)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    items = response.body if isinstance(response.body, list) else []
    entities = [_term_entity(item, "post_tag") for item in items]
    return ActionResult.success(
        sdl.EntityList[PostTerm](items=entities),
        summary=f"{len(entities)} tag(s)")


@chat.function(
    "create_post_tag",
    description="Create a new native WordPress post tag.",
    action_type="write", data_model=PostTerm,
    effects=["wp.post_tag_create"], event="wp-site-connector.create_post_tag")
async def create_post_tag(ctx, params: CreatePostTagParams) -> ActionResult:
    """Create one tag in the native WordPress tag taxonomy."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await create_term(
        ctx, base_url, username, password, _TAG_BASE,
        name=params.name.strip(), description=params.description.strip())
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _term_entity(response.body, "post_tag")
    return ActionResult.success(
        entity, summary=f"Created tag {entity.title} (#{entity.id})", refresh_panels=["center"])


@chat.function(
    "update_post_tag",
    description="Rename a tag or change its description.",
    action_type="write", data_model=PostTerm,
    effects=["wp.post_tag_update"], event="wp-site-connector.update_post_tag")
async def update_post_tag(ctx, params: UpdatePostTagParams) -> ActionResult:
    """Update selected fields of an existing tag."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    fields = {}
    if params.name is not None:
        fields["name"] = params.name.strip()
    if params.description is not None:
        fields["description"] = params.description.strip()
    if not fields:
        return ActionResult.error(
            "Nothing to update — pass name and/or description.", retryable=False)
    response = await update_term(ctx, base_url, username, password, _TAG_BASE, params.term_id, **fields)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _term_entity(response.body, "post_tag")
    return ActionResult.success(
        entity, summary=f"Updated tag {entity.title} (#{entity.id})", refresh_panels=["center"])


@chat.function(
    "delete_post_tag",
    description="Permanently delete a native WordPress post tag. Posts using it simply lose that tag.",
    action_type="destructive", data_model=TermDeleteResult,
    effects=["wp.post_tag_delete"], event="wp-site-connector.delete_post_tag")
async def delete_post_tag(ctx, params: DeletePostTagParams) -> ActionResult:
    """Delete one tag from the native WordPress tag taxonomy."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await delete_term(ctx, base_url, username, password, _TAG_BASE, params.term_id)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    return ActionResult.success(
        TermDeleteResult(id=str(params.term_id), title=f"tag #{params.term_id}", deleted=True),
        summary=f"Deleted tag #{params.term_id}", refresh_panels=["center"])
