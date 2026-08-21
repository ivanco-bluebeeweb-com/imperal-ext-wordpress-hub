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

import json
import re

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (GetBuilderContentParams, UpdateBuilderFieldParams,
                    CreateBricksHeadingParams, BuilderHeadingCreateResult,
                    BulkBuilderFieldParams, ApplyBulkBuilderFieldParams, BulkBuilderFieldResult,
                    BuilderContent, BuilderElement, BuilderFieldUpdateResult,
                    BuilderScanItem, BuilderSupport, DetectedBuilder, SiteIdParams)
from wp_client import wp_get, wp_post, wp_error_message, wp_error_code
import storage

_TAG_RE = re.compile(r"<[^>]+>")

# Minimum Bricks version that ships the MCP Abilities API (142 bricks/*
# abilities: full page authoring, design-system reads, revisions). Betas of
# this line count (e.g. "2.4-beta2") -- only the major.minor matters here.
_BRICKS_ABILITIES_MIN_VERSION = (2, 4)
_WP_ABILITIES_PATH = "/wp-json/wp-abilities/v1/abilities?per_page=100&page=1"


def _parse_bricks_version(raw: str) -> tuple[int, int] | None:
    """Extract (major, minor) from a Bricks version string, tolerating betas
    like '2.4-beta2' or '2.4.1'. Returns None if nothing numeric is found."""
    if not raw:
        return None
    m = re.match(r"(\d+)\.(\d+)", raw.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _coerce_panel_value(value):
    """Turn a plain string typed into a panel form into the same JSON-shaped
    value chat callers already send natively.

    The panel's ui.Input always submits a plain string (the SDK's Form/Input
    contract has no JSON/object input widget), so a Bricks/Elementor field
    that needs a structured value (e.g. {"unit": "px", "size": 20} for
    spacing/typography) is unreachable from the panel unless a JSON-looking
    string is parsed back into a real dict/list/number/bool here. Chat
    callers are unaffected: they already pass a real dict/list/int/bool
    through `value: JsonValue`, so this only ever fires for `str` input, and
    a string that fails to parse as JSON is kept exactly as typed (e.g. a
    plain title stays a plain title, not silently mangled).
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    looks_like_json = (
        stripped[:1] in ("{", "[")
        or stripped in ("true", "false", "null")
        or bool(re.fullmatch(r"-?\d+(\.\d+)?", stripped))
    )
    if not stripped or not looks_like_json:
        return value
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        return value


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _heading_row(el: BuilderElement) -> tuple[str, str] | None:
    """If this element is a heading widget, return (tag, plain-text label).

    Elementor headings: el_type=='widget', widget_type=='heading', settings
    has header_size ('h1'..'h6', default 'h2') and title (plain text).
    Bricks headings: el_type=='heading' (the Bricks 'name'), settings has
    'tag' ('h1'..'h6', default 'h2') and 'text' (may carry inline HTML).
    """
    el_type = (el.el_type or "").strip().lower()
    widget_type = (el.widget_type or "").strip().lower()
    settings = el.settings or {}

    is_elementor_heading = el_type == "widget" and widget_type == "heading"
    is_bricks_heading = el_type == "heading"
    if not (is_elementor_heading or is_bricks_heading):
        return None

    tag = str(settings.get("header_size") or settings.get("tag") or "h2").strip().lower()
    if tag not in ("h1", "h2", "h3", "h4", "h5", "h6"):
        tag = "h2"
    raw_text = settings.get("title") or settings.get("text") or ""
    label = _strip_tags(str(raw_text)) or "(empty)"
    return tag, label


def _build_heading_outline(elements: list[BuilderElement]) -> str:
    lines = []
    for el in elements:
        found = _heading_row(el)
        if found:
            tag, label = found
            lines.append(f"{tag}: {label} (id={el.element_id})")
    return "\n".join(lines)

BRIDGE_PATH = "/wp-json/imperal/v1/builder"
BRIDGE_FIELD_PATH = "/wp-json/imperal/v1/builder/field"
BRIDGE_STATUS_PATH = "/wp-json/imperal/v1/builder/status"
BRIDGE_SCAN_PATH = "/wp-json/imperal/v1/builder/scan"
BRIDGE_HEADING_PATH = "/wp-json/imperal/v1/builder/heading"

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
            heading_outline=_build_heading_outline(elements),
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
                heading_outline=_build_heading_outline(elements),
            ))

    return rows


def _summarise_content(rows: list[BuilderContent]) -> str:
    if not rows:
        return "No builder content found."
    bits = []
    all_headings: list[str] = []
    for row in rows:
        label = row.builder if not row.zone else f"{row.builder}/{row.zone}"
        heading_lines = [l for l in row.heading_outline.split("\n") if l]
        bits.append(f"{label}: {row.element_count} element(s), {len(heading_lines)} heading(s)")
        all_headings.extend(f"{label} {l}" for l in heading_lines)
    header = f"Item #{rows[0].post_id}: " + ", ".join(bits)
    if not all_headings:
        return header + " — NO HEADINGS AT ALL (no H1..H6 widget found in any zone read)."
    return header + "\nHeadings in document order:\n" + "\n".join(all_headings)


async def _fetch_content_rows(ctx, params) -> tuple[list[BuilderContent] | None, ActionResult | None]:
    """Shared fetch+zone-filter logic for get_builder_content and get_builder_element.

    Returns (rows, None) on success or (None, error_result) on failure — callers
    just forward the error_result as-is, keeping both functions' error paths
    byte-identical without duplicating the HTTP/parsing logic.
    """
    bad_target = _target_error(params.post_id, params.slug)
    if bad_target:
        return None, bad_target

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, pw = auth

    query = _target_query(params.post_id, params.slug, params.post_type)
    if params.builder:
        query["builder"] = params.builder.strip().lower()

    try:
        r = await wp_get(ctx, base_url, BRIDGE_PATH, username=username, app_password=pw, params=query)
    except Exception as e:
        await ctx.log(f"get_builder_content request failed: {e}", level="error")
        return None, ActionResult.error("Could not reach the site — try again.",
                                        retryable=True, code="WP_UNREACHABLE")

    if r.status_code != 200 or not isinstance(r.body, dict):
        return None, _http_failure(r.status_code, r.body)

    rows = _content_rows(r.body)
    if not rows:
        return None, ActionResult.error(
            "This item was not built with Elementor or Bricks — no builder content to read.",
            retryable=False, code="BUILDER_NONE_ACTIVE")

    if params.zone:
        wanted = params.zone.strip().lower()
        zoned = [row for row in rows if row.zone.lower() == wanted]
        if not zoned:
            return None, ActionResult.error(
                f"No '{params.zone}' zone found on this item — it may not use Bricks, or that "
                "zone has no content. Call without `zone` to see all available rows.",
                retryable=False, code="BUILDER_ZONE_NOT_FOUND")
        rows = zoned

    return rows, None


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
    rows, error = await _fetch_content_rows(ctx, params)
    if error:
        return error
    return ActionResult.success(sdl.EntityList[BuilderContent](items=rows), summary=_summarise_content(rows))


@chat.function(
    "get_builder_element",
    description=("Read ONE builder/zone record in full — id, slug, builder, zone, state_token, "
                 "element_count, the full `elements` tree, and the never-compacted `heading_outline` "
                 "text. Unlike get_builder_content (which always returns a list, and a list gets "
                 "compacted to id/title/kind by display clients even with one row), this returns a "
                 "single record that is never compacted. For Bricks pages you MUST pass zone "
                 "('header', 'content', or 'footer'); Elementor items ignore zone. Use this whenever "
                 "you actually need to read heading_outline/elements, not just confirm a builder is "
                 "active."),
    action_type="read",
    data_model=BuilderContent,
)
async def get_builder_element(ctx, params: GetBuilderContentParams) -> ActionResult:
    """Return exactly one builder/zone record as a bare object, never list-compacted."""
    rows, error = await _fetch_content_rows(ctx, params)
    if error:
        return error
    if len(rows) > 1:
        zones = ", ".join(sorted({row.zone for row in rows if row.zone}))
        return ActionResult.error(
            f"This item has more than one builder/zone record ({zones or 'multiple builders'}) — "
            "pass `zone` (and/or `builder`) to pick exactly one.",
            retryable=False, code="BUILDER_AMBIGUOUS_TARGET")
    row = rows[0]
    return ActionResult.success(row, summary=_summarise_content(rows))


def _bulk_builder_key(change) -> str:
    return f"{change.element_id}:{change.field}"


async def _bulk_builder_targets(ctx, params: BulkBuilderFieldParams):
    if params.builder.strip().lower() not in {"elementor", "bricks"}:
        return None, ActionResult.error("builder must be elementor or bricks.", retryable=False,
                                        code="BUILDER_INVALID_REQUEST")
    if params.builder.strip().lower() == "bricks" and (params.zone or "").strip().lower() not in {"header", "content", "footer"}:
        return None, ActionResult.error("Bricks bulk edits require zone: header, content, or footer.", retryable=False,
                                        code="BUILDER_INVALID_REQUEST")
    keys = [_bulk_builder_key(change) for change in params.changes]
    if len(set(keys)) != len(keys):
        return None, ActionResult.error("Each element and field pair may appear only once.", retryable=False,
                                        code="BUILDER_DUPLICATE_CHANGES")
    rows, error = await _fetch_content_rows(ctx, params)
    if error:
        return None, error
    wanted_builder = params.builder.strip().lower()
    wanted_zone = (params.zone or "").strip().lower()
    rows = [row for row in rows if row.builder == wanted_builder and row.zone.lower() == wanted_zone]
    if len(rows) != 1:
        return None, ActionResult.error("The selected builder or zone was not found on this item.", retryable=False,
                                        code="BUILDER_NOT_ACTIVE")
    row = rows[0]
    elements = {element.element_id: element for element in row.elements}
    missing = [change.element_id for change in params.changes if change.element_id not in elements]
    if missing:
        return None, ActionResult.error("Unknown element id(s): " + ", ".join(sorted(set(missing))) + ".",
                                        retryable=False, code="BUILDER_ELEMENT_NOT_FOUND")
    fields = [f"{change.element_id}:{change.field}" for change in params.changes
              if change.field not in elements[change.element_id].settings]
    if fields:
        return None, ActionResult.error("Only existing builder settings may be changed; missing: " + ", ".join(fields) + ".",
                                        retryable=False, code="BUILDER_FIELD_NOT_FOUND")
    return row, None


@chat.function(
    "preview_bulk_builder_field",
    description="Preview 1-100 explicit field changes across existing Elementor or one Bricks zone. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkBuilderFieldResult,
)
async def preview_bulk_builder_field(ctx, params: BulkBuilderFieldParams) -> ActionResult:
    """Return an exact no-write builder field diff and current document token."""
    row, error = await _bulk_builder_targets(ctx, params)
    if error:
        return error
    current = {element.element_id: element for element in row.elements}
    changes = [f"{change.element_id}.{change.field}: {current[change.element_id].settings[change.field]!r} → {change.value!r}"
               for change in params.changes]
    result = BulkBuilderFieldResult(id=row.id, title=f"{row.title} bulk edit", preview=True,
                                    requested=len(params.changes), matched=len(params.changes),
                                    state_token=row.state_token, changes=changes)
    return ActionResult.success(result, summary=f"Previewed {len(changes)} builder field change(s); no writes made.")


@chat.function(
    "apply_bulk_builder_field",
    description="Apply a previewed 1-100 explicit Elementor/Bricks field batch. Re-reads the exact builder tree and refuses all writes if its token changed.",
    action_type="write", data_model=BulkBuilderFieldResult,
    effects=["wp.builder_field_update"], event="wordpress-hub.apply_bulk_builder_field",
)
async def apply_bulk_builder_field(ctx, params: ApplyBulkBuilderFieldParams) -> ActionResult:
    """Recheck a builder tree then apply the explicit reviewed point edits."""
    row, error = await _bulk_builder_targets(ctx, params)
    if error:
        return error
    if row.state_token != params.expected_state_token:
        return ActionResult.error("This builder content changed since preview; no fields were written. Read and preview it again.",
                                  retryable=False, code="BUILDER_BULK_STATE_CHANGED")
    updated_ids, failed_ids = [], []
    state_token = row.state_token
    for change in params.changes:
        result = await update_builder_field(ctx, UpdateBuilderFieldParams(
            site_id=params.site_id, post_id=params.post_id, slug=params.slug, post_type=params.post_type,
            builder=params.builder, zone=params.zone, element_id=change.element_id, field=change.field,
            value=change.value, state_token=state_token))
        key = _bulk_builder_key(change)
        if result.status == "success":
            updated_ids.append(key)
            state_token = result.data.state_token or state_token
        else:
            failed_ids.append(key)
    result = BulkBuilderFieldResult(id=row.id, title=f"{row.title} bulk edit", preview=False,
                                    requested=len(params.changes), matched=len(params.changes),
                                    updated=len(updated_ids), failed=len(failed_ids), state_token=state_token,
                                    updated_ids=updated_ids, failed_ids=failed_ids)
    summary = f"Updated {len(updated_ids)} builder field(s)"
    if failed_ids:
        summary += f"; {len(failed_ids)} failed"
    return ActionResult.success(result, summary=summary)


@chat.function(
    "update_builder_field",
    description=("Change exactly ONE settings field on exactly ONE existing Elementor or Bricks "
                 "element, identified by element_id from a previous get_builder_content call. "
                 "Requires the exact state_token from that same read; the write is refused if the "
                 "page changed since. Cannot create elements or replace the page — point edits only."),
    action_type="write",
    data_model=BuilderFieldUpdateResult,
    effects=["wp.builder_field_update"],
    event="wordpress-hub.update_builder_field",
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
        "value": _coerce_panel_value(params.value),
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
        summary=f"Updated '{result.field}' on element {result.element_id} ({result.builder}{zone_bit}).",
        refresh_panels=["center"])


@chat.function(
    "create_bricks_heading",
    description=("Create exactly one semantic Bricks heading in an existing page or template zone. "
                 "Use only after get_builder_element confirms a missing heading and provides the exact "
                 "parent_id and state_token. This cannot replace arbitrary builder JSON or create any other element."),
    action_type="write",
    data_model=BuilderHeadingCreateResult,
    effects=["wp.builder_heading_create"],
    event="wordpress-hub.create_bricks_heading",
)
async def create_bricks_heading(ctx, params: CreateBricksHeadingParams) -> ActionResult:
    """Create one constrained Bricks heading with optimistic concurrency protection."""
    bad_target = _target_error(params.post_id, params.slug)
    if bad_target:
        return bad_target
    zone = params.zone.strip().lower()
    if zone not in ("header", "content", "footer"):
        return ActionResult.error("zone must be header, content, or footer.", retryable=False,
                                  code="BUILDER_INVALID_ZONE")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    body = _target_query(params.post_id, params.slug, params.post_type)
    body.update({
        "builder": "bricks", "zone": zone, "parent_id": params.parent_id or "",
        "position": params.position, "tag": params.tag, "text": params.text,
        "state_token": params.state_token,
    })
    try:
        r = await wp_post(ctx, base_url, BRIDGE_HEADING_PATH, username=username,
                          app_password=pw, json=body)
    except Exception as e:
        await ctx.log(f"create_bricks_heading request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True,
                                  code="WP_UNREACHABLE")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)
    payload = r.body
    result = BuilderHeadingCreateResult(
        id=f"{payload.get('id', 0)}:bricks:{payload.get('element_id', '')}",
        title="Bricks heading created", kind="wp_builder_heading_create",
        post_id=int(payload.get("id", 0) or 0), builder="bricks",
        zone=str(payload.get("zone", "") or ""),
        element_id=str(payload.get("element_id", "") or ""),
        parent_id=payload.get("parent_id") or None, position=int(payload.get("position", 0) or 0),
        tag=str(payload.get("tag", "") or ""), text=str(payload.get("text", "") or ""),
        state_token=str(payload.get("state_token", "") or ""),
    )
    return ActionResult.success(result, summary=(f"Created {result.tag} heading on Bricks element "
                                f"{result.element_id} ({result.zone})."),
                                refresh_panels=["center"])


@chat.function(
    "check_builder_support",
    description=("Check whether a connected WordPress site can read/edit Elementor or Bricks "
                 "page-builder content, and — when Bricks is active — whether its real MCP "
                 "Abilities API (142 bricks/* abilities: full page authoring via set-page-elements/ "
                 "add-element/update-element, plus get-design-context, templates, revisions) is "
                 "actually usable right now. This is computed live on every call for every site: "
                 "read `bricks_readiness` ('not_installed' | 'needs_update' | 'needs_configuration' "
                 "| 'ready') and `bricks_readiness_message` for the exact next action — no local "
                 "docs or prior session memory needed, this works the same for every user. MANDATORY: "
                 "if bricks_readiness == 'ready', use the real bricks/* abilities for ALL page "
                 "authoring; NEVER hand-author raw _bricks_page_content_2 postmeta as a substitute "
                 "— that path can round-trip through get_builder_element while still rendering "
                 "empty in the real Bricks editor. If bricks_readiness is 'needs_update' or "
                 "'needs_configuration', relay bricks_readiness_message to the user verbatim and "
                 "fall back only to this connector's narrow point-edit tools (update_builder_field, "
                 "create_bricks_heading) until they've acted on it."),
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
    detected_raw = body.get("detected_builders", []) or []
    detected = [
        DetectedBuilder(
            slug=str(item.get("slug", "") or ""),
            label=str(item.get("label", "") or ""),
            active=bool(item.get("active", False)),
            confidence=str(item.get("confidence", "") or ""),
        )
        for item in detected_raw if isinstance(item, dict)
    ]
    support = BuilderSupport(
        id=params.site_id, title="Builder support", kind="wp_builder_support",
        bridge_version=str(body.get("bridge_version", "") or ""),
        elementor_active=bool(body.get("elementor_active", False)),
        elementor_version=str(body.get("elementor_version", "") or ""),
        bricks_active=bool(body.get("bricks_active", False)),
        bricks_version=str(body.get("bricks_version", "") or ""),
        detected_builders=detected,
    )

    # Real, deterministic Bricks Abilities API readiness gate -- computed live
    # on every call, for every site/user, no local docs or memory required.
    # See Imperal OS/Docs/BRICKS_DETECTION_STANDARD.md for the full rationale
    # (this exists because hand-authoring raw _bricks_page_content_2 postmeta
    # can round-trip through get_builder_content while still rendering empty
    # in the real Bricks editor -- the abilities API is the only supported
    # path to real page authoring, so callers must be told plainly whether
    # it's actually usable, not left to assume).
    if not support.bricks_active:
        support.bricks_readiness = "not_installed"
        support.bricks_readiness_message = (
            "Bricks is not active on this site — page-building abilities do not apply here."
        )
    else:
        parsed = _parse_bricks_version(support.bricks_version)
        support.bricks_min_version_met = bool(parsed and parsed >= _BRICKS_ABILITIES_MIN_VERSION)
        if not support.bricks_min_version_met:
            support.bricks_readiness = "needs_update"
            support.bricks_readiness_message = (
                f"Bricks {support.bricks_version or '(unknown version)'} is active, but the MCP "
                f"Abilities API (full page authoring: set/add/update elements, design-system reads, "
                f"revisions) needs Bricks {_BRICKS_ABILITIES_MIN_VERSION[0]}.{_BRICKS_ABILITIES_MIN_VERSION[1]}+ "
                f"— ask the site owner to update Bricks first. Until then, only narrow point-edits "
                f"(update_builder_field, create_bricks_heading) are available."
            )
        else:
            # Version is sufficient -- now check whether the abilities are
            # ACTUALLY reachable (MCP Adapter plugin installed + Bricks > AI
            # enabled), by hitting the site's own native wp-abilities route.
            # This is a real HTTP call, not an assumption from the version
            # number alone -- version 2.4+ does not imply the feature is on.
            count = 0
            reachable = False
            try:
                ar = await wp_get(ctx, base_url, _WP_ABILITIES_PATH, username=username, app_password=pw)
                if 200 <= ar.status_code < 300 and isinstance(ar.body, list):
                    reachable = True
                    count = sum(1 for item in ar.body
                                if isinstance(item, dict) and str(item.get("name", "")).startswith("bricks"))
            except Exception as e:
                await ctx.log(f"check_builder_support wp-abilities probe failed: {e}", level="warning")

            support.bricks_abilities_reachable = reachable
            support.bricks_abilities_count = count

            if not reachable:
                support.bricks_readiness = "needs_configuration"
                support.bricks_readiness_message = (
                    f"Bricks {support.bricks_version} meets the version requirement, but this site's "
                    f"own WordPress Abilities API route did not respond — the WordPress MCP Adapter "
                    f"plugin is likely not installed/active. Ask the site owner to install it."
                )
            elif count == 0:
                support.bricks_readiness = "needs_configuration"
                support.bricks_readiness_message = (
                    f"Bricks {support.bricks_version} and the MCP Adapter plugin are both present, "
                    f"but no bricks/* abilities are registered yet — ask the site owner to enable "
                    f"'Bricks > AI' (the Bricks Abilities API toggle) in the Bricks admin settings."
                )
            else:
                support.bricks_readiness = "ready"
                support.bricks_readiness_message = (
                    f"Bricks {support.bricks_version} is fully ready: {count} bricks/* abilities are "
                    f"registered and reachable. Use the real MCP Abilities API for all page authoring "
                    f"(bricks/get-design-context, bricks/set-page-elements, bricks/add-element, etc.) "
                    f"— do not hand-author raw _bricks_page_content_2 postmeta."
                )

    active = [name for name, on in (("Elementor", support.elementor_active), ("Bricks", support.bricks_active)) if on]
    active += [d.label for d in detected if d.active]
    summary = f"Builder bridge v{support.bridge_version} — active: {', '.join(active) if active else 'none'}"
    if detected:
        summary += f" (scanned {len(detected)} other builder(s))"
    if support.bricks_readiness:
        summary += f" | Bricks abilities: {support.bricks_readiness}"
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
