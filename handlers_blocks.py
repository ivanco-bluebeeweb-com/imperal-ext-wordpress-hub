"""Blocks / Patterns introspection (Group K of the developer/backend
roadmap, docs/2026-08-11-developer-backend-functions-plan.md).

list_reusable_blocks reads the site's own native `GET /wp/v2/blocks` --
Gutenberg reusable blocks (now called "synced patterns") are real posts
with the `wp_block` post type, exposed by WP_REST_Blocks_Controller since
WordPress 5.0. That controller deliberately strips `title.rendered` /
`content.rendered` from every context (confirmed against WordPress core's
own class-wp-rest-blocks-controller.php: "It doesn't make sense for a
pattern to have rendered content on its own, since rendering a block
requires it to be inside a post or a page") and exposes `title.raw` /
`content.raw` at both view and edit context instead, plus a top-level
`wp_pattern_sync_status` field (added 6.3) telling you whether a block is
"fully synced" or a "partial"/unsynced pattern -- WP core leaves that meta
empty for a fully-synced block, which we normalize to the explicit string
"synced" so the field is self-explanatory rather than ambiguous. No Bridge
or SSH needed.

list_block_patterns reads the site's own native
`GET /wp/v2/block-patterns/patterns` -- registered block patterns (core,
theme, or plugin supplied via register_block_pattern()), documented at
developer.wordpress.org/rest-api/reference/block-patterns/. This is
READ-ONLY by design on WordPress's own side: patterns are PHP/JSON
registrations, not database rows, so WordPress core itself never exposes
a route to create/update/delete one via REST.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import BlockPattern, ReusableBlock, SiteIdParams
import storage
from wp_client import wp_error_message, wp_get

BLOCKS_PATH = "/wp-json/wp/v2/blocks"
BLOCK_PATTERNS_PATH = "/wp-json/wp/v2/block-patterns/patterns"


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


@chat.function(
    "list_reusable_blocks",
    description=(
        "List Gutenberg reusable blocks (WordPress now calls these 'synced patterns') on a "
        "connected site -- real posts stored under the `wp_block` post type, with each one's "
        "sync status (fully synced vs. an unsynced/partial pattern). Reads the site's own "
        "native `GET /wp/v2/blocks` (WordPress core since 5.0) -- no Bridge or SSH needed. "
        "Useful for a 'which reusable block should I edit / is this content actually synced "
        "everywhere it's used' question."
    ),
    action_type="read",
    data_model=sdl.EntityList[ReusableBlock],
)
async def list_reusable_blocks(ctx, params: SiteIdParams) -> ActionResult:
    """List wp_block posts (reusable blocks / synced patterns) via /wp/v2/blocks."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    r = await wp_get(ctx, base_url, BLOCKS_PATH, username=username, app_password=pw,
                      params={"per_page": 100, "status": "publish,draft"})
    if r.status_code != 200 or not isinstance(r.body, list):
        return ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500)

    items = []
    for b in r.body:
        if not isinstance(b, dict):
            continue
        title = (b.get("title") or {}).get("raw") or b.get("slug", "") or str(b.get("id", ""))
        items.append(ReusableBlock(
            id=str(b.get("id", "")), title=title, slug=b.get("slug", ""),
            status=b.get("status", ""), sync_status=b.get("wp_pattern_sync_status") or "synced",
        ))
    return ActionResult.success(
        sdl.EntityList[ReusableBlock](items=items),
        summary=f"{len(items)} reusable block(s).",
    )


@chat.function(
    "list_block_patterns",
    description=(
        "List every block pattern registered on a connected site -- core, theme, and "
        "plugin-supplied patterns available in the block inserter, with categories, keywords, "
        "which block types/post types it's restricted to, and its source (core/theme/plugin). "
        "Reads the site's own native `GET /wp/v2/block-patterns/patterns` (WordPress core since "
        "6.0) -- no Bridge or SSH needed. Read-only: patterns are PHP/JSON registrations, not "
        "database rows, so WordPress itself has no REST route to create/edit/delete one."
    ),
    action_type="read",
    data_model=sdl.EntityList[BlockPattern],
)
async def list_block_patterns(ctx, params: SiteIdParams) -> ActionResult:
    """List registered block patterns via /wp/v2/block-patterns/patterns."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    r = await wp_get(ctx, base_url, BLOCK_PATTERNS_PATH, username=username, app_password=pw, params={})
    if r.status_code != 200 or not isinstance(r.body, list):
        return ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500)

    items = []
    for i, p in enumerate(r.body):
        if not isinstance(p, dict):
            continue
        name = p.get("name", "") or f"pattern-{i}"
        items.append(BlockPattern(
            id=name, title=p.get("title", "") or name, name=name,
            categories=p.get("categories", []) or [],
            keywords=p.get("keywords", []) or [],
            block_types=p.get("block_types", []) or [],
            source=p.get("source", "") or "",
        ))
    return ActionResult.success(
        sdl.EntityList[BlockPattern](items=items),
        summary=f"{len(items)} block pattern(s).",
    )
