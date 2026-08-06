"""Elementor and Bricks page-builder content: read and guarded point edits.

ACCESS STRATEGY
---------------
Neither Elementor (`_elementor_data`) nor Bricks (`_bricks_page_header_2` /
`_bricks_page_content_2` / `_bricks_page_footer_2`) registers its element-tree
meta with `register_post_meta()` / `show_in_rest`, so stock WordPress REST +
an Application Password cannot see or write it — reads come back empty and
writes are silently dropped. This mirrors the Rank Math situation exactly, so
a companion plugin (Imperal Bridge, builder section, `/wp-json/imperal/v1/builder*`)
is required. There is no fallback tier here: unlike SEO meta, no other
plugin registers these keys for REST, so a missing bridge is a hard stop.

POINT EDITING, NOT PAGE BUILDING
---------------------------------
Every write here changes exactly one field on exactly one existing element,
identified by its builder-native element_id. This is deliberate: the bridge
does not expose "replace the tree" or "create an element" because that risks
corrupting a working page. Reading first is not optional — every write needs
a `state_token` from a prior read of that same builder/zone, and the bridge
refuses the write with 409 if the page changed underneath it (same guard
pattern as the WooCommerce bulk/CSV tools already in this connector).

Elementor's tree is nested; Bricks' is flat with parent/children ids. Both
are flattened by the bridge into the same BuilderElement shape (element_id,
parent_id, el_type, widget_type, settings) so a caller only needs one mental
model for both builders.
"""

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (GetBuilderContentParams, UpdateBuilderFieldParams,
                    BuilderContent, BuilderElement, BuilderFieldUpdateResult,
                    BuilderScanItem, BuilderSupport, SiteIdParams)
from wp_client import wp_get, wp_post, wp_error_message, wp_error_code
import storage

BRIDGE_PATH = "/wp-json/imperal/v1/builder"
BRIDGE_FIELD_PATH = "/wp-json/imperal/v1/builder/field"
BRIDGE_STATUS_PATH = "/wp-json/imperal/v1/builder/status"
BRIDGE_SCAN_PATH = "/wp-json/imperal/v1/builder/scan"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin on the site (bridge/imperal-bridge "
    "in the connector repo) to read or edit Elementor/Bricks content."
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


def _target_error(post_id, slug):
    if post_id is None and not (slug or "").strip():
        return ActionResult.error(
            "Tell me which item: pass post_id, or slug (optionally with post_type).",
            retryable=False, code="BUILDER_TARGET_MISSING")
    return None


def _target_query(post_id, slug, post_type):
    q = {}
    if post_id is not None:
        q["id"] = post_id
    if slug:
        q["slug"] = slug.strip()
    if post_type:
        q["type"] = post_type.strip()
    return q


def _http_failure(status_code, body):
    """Map a Builder Bridge HTTP failure onto a structured ActionResult."""
    retry = status_code >= 500 or status_code == 429
    message = wp_error_message(status_code)
    code = wp_error_code(status_code)

    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        mapping = {
            "imperal_builder_not_found": ("BUILDER_ITEM_NOT_FOUND", "No post or page matched that id or slug."),
            "imperal_builder_ambiguous_slug": ("BUILDER_SLUG_AMBIGUOUS", "Several items share that slug — pass post_type or post_id."),
            "imperal_builder_forbidden": ("WP_FORBIDDEN", "That WordPress user cannot edit this item."),
            "imperal_builder_none_active": ("BUILDER_NONE_ACTIVE", "This item was not built with Elementor or Bricks."),
            "imperal_builder_not_active": ("BUILDER_NOT_ACTIVE", "That builder is not active on this item."),
            "imperal_builder_target_missing": ("BUILDER_TARGET_MISSING", "Pass id or slug."),
            "imperal_builder_element_missing": ("BUILDER_INVALID_REQUEST", "element_id is required."),
            "imperal_builder_field_missing": ("BUILDER_INVALID_REQUEST", "field is required."),
            "imperal_builder_value_missing": ("BUILDER_INVALID_REQUEST", "value is required."),
            "imperal_builder_state_token_missing": ("BUILDER_INVALID_REQUEST", "state_token is required — read the content first."),
            "imperal_builder_zone_missing": ("BUILDER_INVALID_REQUEST", "zone is required for Bricks and must be header, content, or footer."),
            "imperal_builder_ambiguous_builder": ("BUILDER_AMBIGUOUS", "Both Elementor and Bricks are active — pass builder to say which one."),
            "imperal_builder_element_not_found": ("BUILDER_ELEMENT_NOT_FOUND", "No element with that id in this builder/zone."),
            "imperal_builder_stale_state": ("BUILDER_STALE_STATE", "This page changed since you read it — read it again and retry with the fresh state_token."),
        }
        if wp_code in mapping:
            err_code, fallback = mapping[wp_code]
            return ActionResult.error(wp_message or fallback, retryable=False, code=err_code)
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal Bridge plugin installed. " + _INSTALL_HINT,
                retryable=False, code="BUILDER_BRIDGE_MISSING")

    return ActionResult.error(message, retryable=retry, code=code)


def _element_from_payload(row: dict) -> BuilderElement:
    return BuilderElement(
        element_id=str(row.get("id", "")),
        parent_id=(str(row["parent_id"]) if row.get("parent_id") not in (None, "") else None),
        el_type=str(row.get("el_type", "") or ""),
        widget_type=str(row.get("widget_type", "") or ""),
        settings=row.get("settings") if isinstance(row.get("settings"), dict) else {},
    )


def _content_rows(payload: dict) -> list[BuilderContent]:
    """Turn the bridge's GET /builder payload into one BuilderContent per
    builder/zone — each carries its own accurate state_token, since Elementor
    and each Bricks zone are stored (and guarded) independently."""
    post_id = int(payload.get("id", 0) or 0)
    slug = payload.get("slug", "") or ""
    post_type = payload.get("type", "") or ""
    link = payload.get("link", "") or ""
    builders = payload.get("builders") or {}

    rows: list[BuilderContent] = []

    elementor = builders.get("elementor")
    if isinstance(elementor, dict):
        elements = [_element_from_payload(r) for r in (elementor.get("elements") or []) if isinstance(r, dict)]
        rows.append(BuilderContent(
            id=f"{post_id}:elementor", title=f"{slug or post_id} — elementor", kind="wp_builder_content",
            post_id=post_id, slug=slug, post_type=post_type, link=link,
            builder="elementor", zone="", state_token=elementor.get("state_token", "") or "",
            element_count=int(elementor.get("element_count", len(elements)) or len(elements)),
            elements=elements,
        ))

    bricks = builders.get("bricks")
    if isinstance(bricks, dict):
        for zone, zone_payload in (bricks.get("zones") or {}).items():
            if not isinstance(zone_payload, dict):
                continue
            elements = [_element_from_payload(r) for r in (zone_payload.get("elements") or []) if isinstance(r, dict)]
            rows.append(BuilderContent(
                id=f"{post_id}:bricks:{zone}", title=f"{slug or post_id} — bricks {zone}", kind="wp_builder_content",
                post_id=post_id, slug=slug, post_type=post_type, link=link,
                builder="bricks", zone=str(zone), state_token=zone_payload.get("state_token", "") or "",
                element_count=len(elements),
                elements=elements,
            ))

    return rows


def _summarise_content(rows: list[BuilderContent]) -> str:
    if not rows:
        return "No builder content found."
    bits = []
    for row in rows:
        label = row.builder if not row.zone else f"{row.builder}/{row.zone}"
        bits.append(f"{label}: {row.element_count} element(s)")
    return f"Item #{rows[0].post_id}: " + ", ".join(bits)


@chat.function(
    "get_builder_content",
    description=("Read the Elementor and/or Bricks page-builder element tree of one post or "
                 "page on a connected WordPress site, flattened into a simple list of elements "
                 "with ids, types, and settings. Identify the item by post_id or by slug. "
                 "Each result row carries a state_token required to edit any of its elements."),
    action_type="read",
    data_model=sdl.EntityList[BuilderContent],
)
async def get_builder_content(ctx, params: GetBuilderContentParams) -> ActionResult:
    """Return the flattened builder element tree(s) for a single post or page."""
    bad_target = _target_error(params.post_id, params.slug)
    if bad_target:
        return bad_target

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    query = _target_query(params.post_id, params.slug, params.post_type)
    if params.builder:
        query["builder"] = params.builder.strip().lower()

    try:
        r = await wp_get(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw, params=query)
    except Exception as e:
        await ctx.log(f"get_builder_content request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    rows = _content_rows(r.body)
    if not rows:
        return ActionResult.error(
            "This item was not built with Elementor or Bricks — no builder content to read.",
            retryable=False, code="BUILDER_NONE_ACTIVE")

    return ActionResult.success(sdl.EntityList[BuilderContent](items=rows), summary=_summarise_content(rows))


@chat.function(
    "update_builder_field",
    description=("Change exactly ONE settings field on exactly ONE existing Elementor or Bricks "
                 "element, identified by element_id from a previous get_builder_content call. "
                 "Requires the exact state_token from that same read; the write is refused if the "
                 "page changed since. Cannot create elements or replace the page — point edits only."),
    action_type="write",
    data_model=BuilderFieldUpdateResult,
    effects=["wp.builder_field_update"],
    event="wp-site-connector.update_builder_field",
)
async def update_builder_field(ctx, params: UpdateBuilderFieldParams) -> ActionResult:
    """Set one field on one existing builder element, guarded by state_token."""
    bad_target = _target_error(params.post_id, params.slug)
    if bad_target:
        return bad_target

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = _target_query(params.post_id, params.slug, params.post_type)
    body.update({
        "element_id": params.element_id,
        "field": params.field,
        "value": params.value,
        "state_token": params.state_token,
    })
    if params.builder:
        body["builder"] = params.builder.strip().lower()
    if params.zone:
        body["zone"] = params.zone.strip().lower()

    try:
        r = await wp_post(ctx, base_url, BRIDGE_FIELD_PATH, username=username, app_password=pw, json=body)
    except Exception as e:
        await ctx.log(f"update_builder_field request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    payload = r.body
    result = BuilderFieldUpdateResult(
        id=f"{payload.get('id', 0)}:{payload.get('builder', '')}", title="builder field updated",
        kind="wp_builder_field_update",
        post_id=int(payload.get("id", 0) or 0),
        builder=str(payload.get("builder", "") or ""),
        zone=str(payload.get("zone", "") or ""),
        element_id=str(payload.get("element_id", "") or ""),
        field=str(payload.get("field", "") or ""),
        state_token=str(payload.get("state_token", "") or ""),
    )
    zone_bit = f"/{result.zone}" if result.zone else ""
    return ActionResult.success(
        result,
        summary=f"Updated '{result.field}' on element {result.element_id} ({result.builder}{zone_bit}).")


@chat.function(
    "check_builder_support",
    description=("Check whether a connected WordPress site can read/edit Elementor or Bricks "
                 "page-builder content — whether the Imperal Bridge plugin is installed "
                 "and which builder plugin(s) are active site-wide."),
    action_type="read",
    data_model=BuilderSupport,
)
async def check_builder_support(ctx, params: SiteIdParams) -> ActionResult:
    """Report Builder Bridge presence and active builder plugins for a site."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, BRIDGE_STATUS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"check_builder_support request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 404:
        return ActionResult.error(
            "This site does not have the Imperal Bridge plugin installed. " + _INSTALL_HINT,
            retryable=False, code="BUILDER_BRIDGE_MISSING")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    body = r.body
    support = BuilderSupport(
        id=params.site_id, title="Builder support", kind="wp_builder_support",
        bridge_version=str(body.get("bridge_version", "") or ""),
        elementor_active=bool(body.get("elementor_active", False)),
        elementor_version=str(body.get("elementor_version", "") or ""),
        bricks_active=bool(body.get("bricks_active", False)),
        bricks_version=str(body.get("bricks_version", "") or ""),
    )
    active = [name for name, on in (("Elementor", support.elementor_active), ("Bricks", support.bricks_active)) if on]
    summary = f"Builder bridge v{support.bridge_version} — active: {', '.join(active) if active else 'none'}"
    return ActionResult.success(support, summary=summary)


@chat.function(
    "scan_builder_content",
    description=("Diagnostic scan of a connected WordPress site's database for ANY post, page, "
                 "or template (including custom post types like bricks_template that list_pages/"
                 "list_posts never see, since they are not registered for the normal REST posts "
                 "endpoints) carrying non-empty Elementor or Bricks builder content. Use this when "
                 "get_builder_content reports BUILDER_NONE_ACTIVE on the items you tried, to find "
                 "where builder content actually lives on the site. Read-only; requires Builder "
                 "Bridge plugin v1.1.0 or later."),
    action_type="read",
    data_model=sdl.EntityList[BuilderScanItem],
)
async def scan_builder_content(ctx, params: SiteIdParams) -> ActionResult:
    """Scan postmeta directly for Elementor/Bricks content across all post types."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, BRIDGE_SCAN_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"scan_builder_content request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 404:
        return ActionResult.error(
            "This site's Imperal Bridge plugin does not support /builder/scan yet — "
            "update it to v1.1.0 or later.",
            retryable=False, code="BUILDER_BRIDGE_MISSING")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    items_raw = r.body.get("items_with_builder_content", [])
    if not isinstance(items_raw, list):
        items_raw = []

    items = [
        BuilderScanItem(
            id=str(it.get("id", "")), title=str(it.get("title", "") or "(untitled)"),
            kind="wp_builder_scan_item",
            post_id=int(it.get("id", 0) or 0),
            post_type=str(it.get("type", "") or ""),
            status=str(it.get("status", "") or ""),
            builders=list(it.get("builders", []) or []),
            meta_keys=list(it.get("meta_keys", []) or []),
        )
        for it in items_raw
    ]

    total = len(items)
    by_type = {}
    for it in items:
        by_type[it.post_type] = by_type.get(it.post_type, 0) + 1
    breakdown = ", ".join(f"{count} {ptype}" for ptype, count in sorted(by_type.items()))
    summary = (f"Found {total} item(s) with builder content" +
               (f" ({breakdown})" if breakdown else "") + "." if total else
               "No posts, pages, or templates on this site carry Elementor or Bricks content.")
    return ActionResult.success(sdl.EntityList(items=items, total=total), summary=summary)
