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

assign_post_taxonomy (added for the climtec.md custom-taxonomy gap) is the
generic write path this module was missing: create_post/update_post could
only ever resolve terms against the two native taxonomies (category,
post_tag) because they call find_category_id/find_term_ids, which are
hard-wired to /wp/v2/categories and /wp/v2/tags. A custom taxonomy like
climtec.md's own `product-type` (attached to its `product` CPT, REST field
name `product-type`, values are term ids not slugs) was reachable only by
hand-editing the WP admin. assign_post_taxonomy instead: (1) reads
/wp/v2/taxonomies/{taxonomy} to get the taxonomy's own rest_base, (2) tries
to resolve each given term against /wp/v2/{rest_base} by exact name/slug
match (case-insensitive) or by numeric id, (3) optionally creates any term
that doesn't already exist, then (4) PATCHes the post/page/CPT item's
{rest_base: [term_id, ...]} field -- the same shape WordPress itself uses
for taxonomy REST fields, whatever the taxonomy's own name.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    AssignPostTaxonomyParams,
    PostTaxonomyAssignResult,
    RegisteredPostType,
    RegisteredTaxonomy,
    SiteIdParams,
)
import storage
from wp_client import create_term, find_term_id, wp_error_code, wp_error_message, wp_get, wp_request

TYPES_PATH = "/wp-json/wp/v2/types"
TAXONOMIES_PATH = "/wp-json/wp/v2/taxonomies"

_POST_TYPE_BASES = {"post": "posts", "page": "pages"}


def _post_rest_base(post_type: str) -> str:
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


async def _resolve_taxonomy_rest_base(ctx, base_url, username, pw, taxonomy: str):
    """Look up one taxonomy's own REST base via /wp/v2/taxonomies/{taxonomy}.

    A taxonomy's REST *field* name on a post (e.g. 'product-type') and its
    REST *base* for listing/creating terms (e.g. also 'product-type', but
    WordPress lets a plugin register them differently) are not guaranteed
    to be the same string, so this is looked up rather than assumed to
    equal the taxonomy slug the caller passed.
    """
    r = await wp_get(ctx, base_url, f"{TAXONOMIES_PATH}/{taxonomy}",
                      username=username, app_password=pw, params={"context": "edit"})
    if r.status_code in (401, 403):
        r = await wp_get(ctx, base_url, f"{TAXONOMIES_PATH}/{taxonomy}",
                          username=username, app_password=pw)
    if r.status_code == 404:
        return None, ActionResult.error(
            f"No taxonomy named '{taxonomy}' is registered on this site — run "
            "list_registered_taxonomies to see the exact slugs this site actually has.",
            retryable=False, code="WP_TAXONOMY_NOT_FOUND")
    if r.status_code >= 400 or not isinstance(r.body, dict):
        return None, ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500)
    rest_base = r.body.get("rest_base") or taxonomy
    return rest_base, None


async def _resolve_or_create_terms(ctx, base_url, username, pw, rest_base: str,
                                    terms: list[str], create_missing: bool):
    """Resolve each given term (name or numeric id) within one taxonomy REST base.

    A bare digit string is treated as an existing term id and used as-is
    without a lookup (WordPress will 400 later if it's wrong) — this is
    what lets a caller pass an id straight from list_terms/the WP admin
    instead of always needing an exact name match.
    """
    resolved_ids: list[int] = []
    created: list[str] = []
    not_found: list[str] = []
    for raw in terms:
        name = raw.strip()
        if not name:
            continue
        if name.isdigit():
            resolved_ids.append(int(name))
            continue
        term_id = await find_term_id(ctx, base_url, username, pw, rest_base, name)
        if term_id:
            resolved_ids.append(term_id)
            continue
        if not create_missing:
            not_found.append(name)
            continue
        resp = await create_term(ctx, base_url, username, pw, rest_base, name=name)
        if resp.status_code in (200, 201) and isinstance(resp.body, dict) and resp.body.get("id"):
            resolved_ids.append(resp.body["id"])
            created.append(name)
        else:
            not_found.append(name)
    return resolved_ids, created, not_found


@chat.function(
    "assign_post_taxonomy",
    description=(
        "Assign terms of ANY registered taxonomy to a post/page/CPT item -- not just the "
        "native category/post_tag that create_post/update_post already handle, but a custom "
        "taxonomy a plugin or theme registered (e.g. a 'product' custom post type's own "
        "'product-type' taxonomy with terms like 'RD'/'Quattro'). Run list_registered_taxonomies "
        "first if you don't already know the exact taxonomy slug and its rest_base. Each entry "
        "in terms can be an existing term's exact name (case-insensitive) or its numeric id as "
        "a string; by default a name that doesn't match any existing term is created "
        "automatically (set create_missing=False to require an existing term instead). This "
        "REPLACES the post's current terms in that one taxonomy -- it does not touch any other "
        "taxonomy the post has terms in."
    ),
    action_type="write",
    data_model=PostTaxonomyAssignResult,
    effects=["wp.post_update"],
    event="wordpress-hub.assign_post_taxonomy",
)
async def assign_post_taxonomy(ctx, params: AssignPostTaxonomyParams) -> ActionResult:
    """Resolve terms in an arbitrary taxonomy, then PATCH them onto a post."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    rest_base, err = await _resolve_taxonomy_rest_base(ctx, base_url, username, pw, params.taxonomy)
    if err:
        return err

    term_ids, created, not_found = await _resolve_or_create_terms(
        ctx, base_url, username, pw, rest_base, params.terms, params.create_missing)

    if not term_ids:
        return ActionResult.error(
            f"None of the given terms ({', '.join(params.terms)}) could be resolved or created "
            f"in taxonomy '{params.taxonomy}' — nothing was changed on the post.",
            retryable=False, code="WP_TAXONOMY_TERMS_UNRESOLVED")

    post_rest_base = _post_rest_base(params.post_type.strip() or "post")
    resp = await wp_request(
        ctx, "post", base_url, f"/wp-json/wp/v2/{post_rest_base}/{params.post_id}",
        username=username, app_password=pw, json={rest_base: term_ids})
    if resp.status_code == 404:
        return ActionResult.error(
            f"No {params.post_type or 'post'} with id {params.post_id} was found — check the "
            "post_id and post_type match an existing item.",
            retryable=False, code="WP_POST_NOT_FOUND")
    if resp.status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot edit this post or assign this taxonomy's "
            "terms. Reconnect with an administrator or editor Application Password.",
            retryable=False, code="WP_TAXONOMY_FORBIDDEN")
    if resp.status_code >= 400:
        return ActionResult.error(wp_error_message(resp.status_code),
                                   retryable=resp.status_code >= 500, code=wp_error_code(resp.status_code))

    result = PostTaxonomyAssignResult(
        id=str(params.post_id), title=f"{params.taxonomy} on post #{params.post_id}",
        taxonomy=params.taxonomy, rest_base=rest_base, term_ids=term_ids,
        created_terms=created, terms_not_found=not_found,
    )
    summary = f"Assigned {len(term_ids)} term(s) in '{params.taxonomy}' to post #{params.post_id}."
    if created:
        summary += f" Created new term(s): {', '.join(created)}."
    if not_found:
        summary += f" Not resolved (create_missing=False): {', '.join(not_found)}."
    return ActionResult.success(result, summary=summary)
