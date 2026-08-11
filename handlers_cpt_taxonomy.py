"""Custom post type / taxonomy introspection (Group J of the developer/
backend roadmap, docs/2026-08-11-developer-backend-functions-plan.md).

list_registered_post_types / list_registered_taxonomies read the site's own
native `GET /wp/v2/types` and `GET /wp/v2/taxonomies` collection endpoints --
WordPress core routes shipped since the REST API's introduction, documented
at developer.wordpress.org/rest-api/reference/post-types/ and
.../reference/taxonomies/. No Bridge or SSH needed.

Both endpoints only expose their most useful discovery field --
`viewable` for post types, `visibility.public` for taxonomies -- under
`context=edit` (confirmed against WP core's own
class-wp-rest-post-types-controller.php / class-wp-rest-taxonomies-
controller.php: both fields are marked `'context' => array('edit')` in
their JSON schema, so a plain view-context GET never returns them). We
always request context=edit first; WordPress requires edit_posts /
assign_terms capability for that context, which the account this app
already connects as should have. If that's refused (a lower-privilege
connected user), we transparently retry with the default view context and
simply leave `viewable`/`public` at their default (false) rather than
fail outright -- discovery of slugs/rest_base/hierarchical still works.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import RegisteredPostType, RegisteredTaxonomy, SiteIdParams
import storage
from wp_client import wp_error_message, wp_get

TYPES_PATH = "/wp-json/wp/v2/types"
TAXONOMIES_PATH = "/wp-json/wp/v2/taxonomies"


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


async def _get_with_edit_fallback(ctx, base_url, username, pw, path):
    """GET path with context=edit; on a permission refusal, retry with the
    default view context instead of failing outright."""
    r = await wp_get(ctx, base_url, path, username=username, app_password=pw,
                      params={"context": "edit"})
    if r.status_code == 200 and isinstance(r.body, dict):
        return r.body, None
    if r.status_code in (401, 403):
        r2 = await wp_get(ctx, base_url, path, username=username, app_password=pw)
        if r2.status_code == 200 and isinstance(r2.body, dict):
            return r2.body, None
        return None, ActionResult.error(wp_error_message(r2.status_code), retryable=r2.status_code >= 500)
    return None, ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500)


@chat.function(
    "list_registered_post_types",
    description=(
        "List every post type registered on a connected WordPress site -- not just the ones "
        "already known, but every CPT a plugin or theme registered -- with its REST base slug, "
        "hierarchical/viewable flags, and which taxonomies it's associated with. Reads the "
        "site's own native `GET /wp/v2/types` (context=edit where the connected user's role "
        "allows it, otherwise a plain read). Use this before list_custom_posts to discover a "
        "CPT slug dynamically instead of already having to know it."
    ),
    action_type="read",
    data_model=sdl.EntityList[RegisteredPostType],
)
async def list_registered_post_types(ctx, params: SiteIdParams) -> ActionResult:
    """List registered post types via /wp/v2/types."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body, err = await _get_with_edit_fallback(ctx, base_url, username, pw, TYPES_PATH)
    if err:
        return err

    items = []
    for slug, t in body.items():
        if not isinstance(t, dict):
            continue
        items.append(RegisteredPostType(
            id=slug, title=t.get("name") or slug, slug=slug,
            rest_base=t.get("rest_base", slug),
            hierarchical=bool(t.get("hierarchical", False)),
            viewable=bool(t.get("viewable", False)),
            has_archive=bool(t.get("has_archive", False)),
            taxonomies=t.get("taxonomies", []) or [],
        ))
    items.sort(key=lambda p: p.slug)
    return ActionResult.success(
        sdl.EntityList[RegisteredPostType](items=items),
        summary=f"{len(items)} registered post type(s).",
    )


@chat.function(
    "list_registered_taxonomies",
    description=(
        "List every taxonomy registered on a connected WordPress site -- native categories/tags "
        "plus any custom taxonomy a plugin or theme registered -- with its REST base slug, "
        "hierarchical/public flags, and which post types it's attached to. Reads the site's own "
        "native `GET /wp/v2/taxonomies` (context=edit where the connected user's role allows "
        "it, otherwise a plain read). Useful for populating a taxonomy picker dynamically."
    ),
    action_type="read",
    data_model=sdl.EntityList[RegisteredTaxonomy],
)
async def list_registered_taxonomies(ctx, params: SiteIdParams) -> ActionResult:
    """List registered taxonomies via /wp/v2/taxonomies."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body, err = await _get_with_edit_fallback(ctx, base_url, username, pw, TAXONOMIES_PATH)
    if err:
        return err

    items = []
    for slug, t in body.items():
        if not isinstance(t, dict):
            continue
        visibility = t.get("visibility") or {}
        items.append(RegisteredTaxonomy(
            id=slug, title=t.get("name") or slug, slug=slug,
            rest_base=t.get("rest_base", slug),
            hierarchical=bool(t.get("hierarchical", False)),
            public=bool(visibility.get("public", False)),
            types=t.get("types", []) or [],
        ))
    items.sort(key=lambda p: p.slug)
    return ActionResult.success(
        sdl.EntityList[RegisteredTaxonomy](items=items),
        summary=f"{len(items)} registered taxonom{'y' if len(items) == 1 else 'ies'}.",
    )
