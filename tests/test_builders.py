"""Tests for Elementor/Bricks builder point-editing via the Imperal Builder
Bridge (/wp-json/imperal/v1/builder*).

There is no fallback tier here (unlike SEO meta) — a missing bridge is a
hard stop, so those paths get direct coverage too.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_builders as hb
import storage
from models import (ApplyBulkBuilderFieldParams, BuilderFieldAssignment, BulkBuilderFieldParams,
                    GetBuilderContentParams, UpdateBuilderFieldParams, SiteIdParams)

TREE = "https://x.com/wp-json/imperal/v1/builder"
FIELD = "https://x.com/wp-json/imperal/v1/builder/field"
STATUS = "https://x.com/wp-json/imperal/v1/builder/status"
SCAN = "https://x.com/wp-json/imperal/v1/builder/scan"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _elementor_row(**over):
    row = {"id": "abc123", "parent_id": None, "el_type": "widget",
           "widget_type": "heading", "settings": {"title": "Hello"}}
    row.update(over)
    return row


def _tree_payload(**over):
    payload = {
        "id": 42, "slug": "home", "type": "page", "link": "https://x.com/home",
        "active_builders": ["elementor"],
        "builders": {
            "elementor": {
                "elements": [_elementor_row()],
                "state_token": "tok-1",
                "element_count": 1,
            }
        },
    }
    payload.update(over)
    return payload


# ── reading content ──────────────────────────────────────────────────────────

async def test_get_reads_flattened_elementor_elements():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _tree_payload(), 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=42))
    assert r.status == "success"
    assert len(r.data.items) == 1
    row = r.data.items[0]
    assert row.builder == "elementor"
    assert row.element_count == 1
    assert row.state_token == "tok-1"
    assert row.elements[0].element_id == "abc123"
    assert row.elements[0].widget_type == "heading"
    assert row.elements[0].settings == {"title": "Hello"}


async def test_get_reports_one_row_per_bricks_zone():
    ctx = await _ctx()
    payload = {
        "id": 7, "slug": "landing", "type": "page", "link": "https://x.com/landing",
        "active_builders": ["bricks"],
        "builders": {
            "bricks": {
                "zones": {
                    "content": {
                        "elements": [{"id": "e1", "parent_id": None, "el_type": "section",
                                      "widget_type": "", "settings": {}, "zone": "content"}],
                        "state_token": "tok-content",
                    },
                    "header": {"elements": [], "state_token": "tok-header"},
                    "footer": {"elements": [], "state_token": "tok-footer"},
                }
            }
        },
    }
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=7))
    assert r.status == "success"
    zones = {row.zone: row for row in r.data.items}
    assert set(zones) == {"content", "header", "footer"}
    assert zones["content"].element_count == 1
    assert zones["content"].state_token == "tok-content"


# ── zone filter: return exactly one row, so display clients never compact it ─
#
# Bricks pages always have 3 zones (header/content/footer), so a caller who
# wants to actually SEE `heading_outline`/`elements` (rather than a compacted
# id/title/kind card) needs a way to get exactly one row back. `zone` does
# that — this is what makes the heading_skip/h1.missing investigation on
# g4s.md/climtec.md actually actionable in a live session.

async def test_zone_filter_returns_exactly_one_row():
    ctx = await _ctx()
    payload = {
        "id": 7, "slug": "landing", "type": "page", "link": "https://x.com/landing",
        "active_builders": ["bricks"],
        "builders": {
            "bricks": {
                "zones": {
                    "content": {
                        "elements": [{"id": "e1", "parent_id": None, "el_type": "heading",
                                      "widget_type": "", "settings": {"tag": "h3", "text": "Oops"},
                                      "zone": "content"}],
                        "state_token": "tok-content",
                    },
                    "header": {"elements": [], "state_token": "tok-header"},
                    "footer": {"elements": [], "state_token": "tok-footer"},
                }
            }
        },
    }
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(
        ctx, GetBuilderContentParams(site_id="x-com", post_id=7, zone="content"))
    assert r.status == "success"
    assert len(r.data.items) == 1
    assert r.data.items[0].zone == "content"
    assert r.data.items[0].heading_outline == "h3: Oops (id=e1)"


async def test_zone_filter_is_case_insensitive():
    ctx = await _ctx()
    payload = {
        "id": 7, "slug": "landing", "type": "page", "link": "https://x.com/landing",
        "active_builders": ["bricks"],
        "builders": {"bricks": {"zones": {
            "header": {"elements": [], "state_token": "tok-header"},
        }}},
    }
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(
        ctx, GetBuilderContentParams(site_id="x-com", post_id=7, zone="HEADER"))
    assert r.status == "success"
    assert len(r.data.items) == 1


async def test_zone_filter_reports_a_clear_error_when_zone_absent():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _tree_payload(), 200)  # elementor-only payload, no bricks zones
    r = await hb.get_builder_content(
        ctx, GetBuilderContentParams(site_id="x-com", post_id=42, zone="content"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_ZONE_NOT_FOUND"


# ── get_builder_element: a bare object, never compacted by display clients ──
#
# get_builder_content's data_model is always EntityList[BuilderContent] — an
# EntityList gets compacted to id/title/kind cards by display clients even
# when it holds exactly one row (confirmed live: zone='content' on a real
# Bricks page still rendered as a compact card, hiding heading_outline).
# get_builder_element's data_model is the bare BuilderContent — never a list —
# so its fields are always fully readable.

def _bricks_payload_with_heading_skip():
    return {
        "id": 723, "slug": "lapmol", "type": "page", "link": "https://x.com/lapmol",
        "active_builders": ["bricks"],
        "builders": {
            "bricks": {
                "zones": {
                    "content": {
                        "elements": [
                            {"id": "h1", "parent_id": None, "el_type": "heading",
                             "widget_type": "", "settings": {"tag": "h1", "text": "Lapmol"},
                             "zone": "content"},
                            {"id": "h3", "parent_id": None, "el_type": "heading",
                             "widget_type": "", "settings": {"tag": "h3", "text": "Skipped"},
                             "zone": "content"},
                        ],
                        "state_token": "tok-content",
                    },
                    "header": {"elements": [], "state_token": "tok-header"},
                    "footer": {"elements": [], "state_token": "tok-footer"},
                }
            }
        },
    }


async def test_get_builder_element_returns_bare_object_with_full_heading_outline():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _bricks_payload_with_heading_skip(), 200)
    r = await hb.get_builder_element(
        ctx, GetBuilderContentParams(site_id="x-com", post_id=723, zone="content"))
    assert r.status == "success"
    # Bare object, not a list — no .items, the row's own fields are top-level.
    assert not hasattr(r.data, "items")
    assert r.data.zone == "content"
    assert r.data.element_count == 2
    assert "h1: Lapmol (id=h1)" in r.data.heading_outline
    assert "h3: Skipped (id=h3)" in r.data.heading_outline


async def test_get_builder_element_demands_zone_when_result_is_ambiguous():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _bricks_payload_with_heading_skip(), 200)
    # No zone given — 3 Bricks zones come back, ambiguous for a bare-object result.
    r = await hb.get_builder_element(
        ctx, GetBuilderContentParams(site_id="x-com", post_id=723))
    assert r.status == "error"
    assert r.error_code == "BUILDER_AMBIGUOUS_TARGET"


async def test_get_builder_element_zone_not_found_error_matches_get_builder_content():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _tree_payload(), 200)  # elementor-only, no bricks zones
    r = await hb.get_builder_element(
        ctx, GetBuilderContentParams(site_id="x-com", post_id=42, zone="content"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_ZONE_NOT_FOUND"


async def test_get_resolves_by_slug():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _tree_payload(), 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", slug="home"))
    assert r.status == "success"


async def test_no_post_id_and_no_slug_is_refused_locally():
    ctx = await _ctx()
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_TARGET_MISSING"


async def test_optional_builder_param_is_forwarded_and_restricts_response():
    ctx = await _ctx()
    seen = {}
    real_get = ctx.http.get

    async def spy(url, **kwargs):
        if "imperal/v1/builder" in url and "field" not in url:
            seen["params"] = kwargs.get("params") or {}
        return await real_get(url, **kwargs)

    ctx.http.get = spy
    ctx.http.mock_get(TREE, _tree_payload(), 200)
    await hb.get_builder_content(ctx, GetBuilderContentParams(
        site_id="x-com", post_id=42, builder="elementor"))
    assert seen["params"].get("builder") == "elementor"


async def test_no_builder_content_on_item_is_a_clear_error():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, {"code": "imperal_builder_none_active",
                             "message": "This item was not built with Elementor or Bricks."}, 404)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=1))
    assert r.status == "error"
    assert r.error_code == "BUILDER_NONE_ACTIVE"


async def test_ambiguous_slug_is_surfaced_faithfully():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, {"code": "imperal_builder_ambiguous_slug",
                             "message": "Several items share that slug."}, 409)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", slug="dup"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_SLUG_AMBIGUOUS"


async def test_item_not_found_is_its_own_code():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, {"code": "imperal_builder_not_found",
                             "message": "Nothing matched."}, 404)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=999))
    assert r.status == "error"
    assert r.error_code == "BUILDER_ITEM_NOT_FOUND"


async def test_missing_bridge_tells_user_to_install_it():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, {"code": "rest_no_route"}, 404)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=1))
    assert r.status == "error"
    assert r.error_code == "BUILDER_BRIDGE_MISSING"
    assert "Bridge" in r.error


# ── updating a field ─────────────────────────────────────────────────────────

async def test_update_writes_one_field_on_one_element():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {
        "id": 42, "builder": "elementor", "element_id": "abc123",
        "field": "title", "state_token": "tok-2",
    }, 200)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=42, element_id="abc123", field="title",
        value="New heading", state_token="tok-1"))
    assert r.status == "success"
    assert r.data.element_id == "abc123"
    assert r.data.field == "title"
    assert r.data.state_token == "tok-2"
    assert "abc123" in r.summary


async def test_update_sends_zone_and_builder_when_given():
    ctx = await _ctx()
    sent = {}
    real_post = ctx.http.post

    async def spy(url, **kwargs):
        if url == FIELD:
            sent.update(kwargs.get("json") or {})
        return await real_post(url, **kwargs)

    ctx.http.post = spy
    ctx.http.mock_post(FIELD, {
        "id": 7, "builder": "bricks", "zone": "content",
        "element_id": "e1", "field": "text", "state_token": "tok-x",
    }, 200)
    await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=7, element_id="e1", field="text",
        value="hi", state_token="tok-content", builder="bricks", zone="content"))
    assert sent["builder"] == "bricks"
    assert sent["zone"] == "content"
    assert sent["element_id"] == "e1"
    assert sent["value"] == "hi"


async def test_update_accepts_structured_json_value():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {
        "id": 42, "builder": "elementor", "element_id": "abc123",
        "field": "_typography_font_size", "state_token": "tok-2",
    }, 200)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=42, element_id="abc123",
        field="_typography_font_size", value={"unit": "px", "size": 20},
        state_token="tok-1"))
    assert r.status == "success"


async def test_stale_state_token_is_rejected_with_its_own_code():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {"code": "imperal_builder_stale_state",
                               "message": "This page changed since you read it."}, 409)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=42, element_id="abc123", field="title",
        value="X", state_token="stale"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_STALE_STATE"


async def test_unknown_element_id_is_not_found():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {"code": "imperal_builder_element_not_found",
                               "message": "No element with that id."}, 404)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=42, element_id="nope", field="title",
        value="X", state_token="tok-1"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_ELEMENT_NOT_FOUND"


async def test_missing_zone_for_bricks_is_reported():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {"code": "imperal_builder_zone_missing",
                               "message": "zone is required for Bricks."}, 400)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=7, element_id="e1", field="text",
        value="hi", state_token="tok-content", builder="bricks"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_INVALID_REQUEST"


async def test_ambiguous_builder_when_both_active_is_reported():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {"code": "imperal_builder_ambiguous_builder",
                               "message": "Both Elementor and Bricks are active."}, 400)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=42, element_id="abc123", field="title",
        value="X", state_token="tok-1"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_AMBIGUOUS"


async def test_forbidden_write_is_a_permission_problem():
    ctx = await _ctx()
    ctx.http.mock_post(FIELD, {"code": "imperal_builder_forbidden",
                               "message": "That user cannot edit this item."}, 403)
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", post_id=42, element_id="abc123", field="title",
        value="X", state_token="tok-1"))
    assert r.status == "error"
    assert r.error_code == "WP_FORBIDDEN"


async def test_update_without_post_id_or_slug_is_refused_locally():
    ctx = await _ctx()
    r = await hb.update_builder_field(ctx, UpdateBuilderFieldParams(
        site_id="x-com", element_id="abc123", field="title", value="X", state_token="tok-1"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_TARGET_MISSING"


async def test_preview_and_apply_bulk_builder_fields():
    ctx = await _ctx()
    payload = _tree_payload()
    ctx.http.mock_get(TREE, payload, 200)
    preview = await hb.preview_bulk_builder_field(ctx, BulkBuilderFieldParams(
        site_id="x-com", post_id=42, builder="elementor", changes=[
            BuilderFieldAssignment(element_id="abc123", field="title", value="New title")]))
    assert preview.status == "success" and preview.data.preview is True

    ctx.http.mock_get(TREE, payload, 200)
    ctx.http.mock_post(FIELD, {"id": 42, "state_token": "tok-2", "element_id": "abc123",
                               "field": "title", "value": "New title"}, 200)
    result = await hb.apply_bulk_builder_field(ctx, ApplyBulkBuilderFieldParams(
        site_id="x-com", post_id=42, builder="elementor", changes=[
            BuilderFieldAssignment(element_id="abc123", field="title", value="New title")],
        expected_state_token=preview.data.state_token))
    assert result.status == "success" and result.data.updated == 1


async def test_apply_bulk_builder_fields_refuses_stale_token():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, _tree_payload(), 200)
    result = await hb.apply_bulk_builder_field(ctx, ApplyBulkBuilderFieldParams(
        site_id="x-com", post_id=42, builder="elementor", changes=[
            BuilderFieldAssignment(element_id="abc123", field="title", value="New title")],
        expected_state_token="wrong"))
    assert result.status == "error" and result.error_code == "BUILDER_BULK_STATE_CHANGED"


# ── support check ────────────────────────────────────────────────────────────

async def test_check_reports_both_builders_active():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {
        "bridge": True, "bridge_version": "1.0.0",
        "elementor_active": True, "elementor_version": "3.20.0",
        "bricks_active": True, "bricks_version": "1.9.9",
    }, 200)
    r = await hb.check_builder_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.elementor_active and r.data.bricks_active
    assert r.data.bridge_version == "1.0.0"
    assert "Elementor" in r.summary and "Bricks" in r.summary


async def test_check_reports_neither_builder_active():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {
        "bridge": True, "bridge_version": "1.0.0",
        "elementor_active": False, "bricks_active": False,
    }, 200)
    r = await hb.check_builder_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert not r.data.elementor_active and not r.data.bricks_active
    assert "none" in r.summary


async def test_check_reports_missing_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {"code": "rest_no_route"}, 404)
    r = await hb.check_builder_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_BRIDGE_MISSING"


# ── diagnostic scan ──────────────────────────────────────────────────────────

async def test_scan_reports_items_with_builder_content():
    ctx = await _ctx()
    ctx.http.mock_get(SCAN, {
        "items_with_builder_content": [
            {"id": 7, "title": "Header", "type": "bricks_template", "status": "publish",
             "builders": ["bricks"], "meta_keys": ["_bricks_page_content_2"]},
            {"id": 42, "title": "Home", "type": "page", "status": "publish",
             "builders": ["elementor"], "meta_keys": ["_elementor_data"]},
        ],
        "total_found": 2,
        "registered_post_types": ["post", "page", "bricks_template"],
    }, 200)
    r = await hb.scan_builder_content(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert len(r.data.items) == 2
    assert r.data.items[0].post_id == 7
    assert r.data.items[0].post_type == "bricks_template"
    assert r.data.items[0].builders == ["bricks"]
    assert r.data.items[1].builders == ["elementor"]


async def test_scan_reports_empty_when_nothing_found():
    ctx = await _ctx()
    ctx.http.mock_get(SCAN, {
        "items_with_builder_content": [], "total_found": 0,
        "registered_post_types": ["post", "page"],
    }, 200)
    r = await hb.scan_builder_content(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.items == []


async def test_scan_reports_missing_bridge_or_outdated_version():
    ctx = await _ctx()
    ctx.http.mock_get(SCAN, {"code": "rest_no_route"}, 404)
    r = await hb.scan_builder_content(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "error"
    assert r.error_code == "BUILDER_BRIDGE_MISSING"


# ── site / credential problems ───────────────────────────────────────────────

async def test_unknown_site_is_a_clear_error():
    ctx = await _ctx()
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="nope", post_id=1))
    assert r.status == "error"
    assert r.error_code == "SITE_NOT_CONNECTED"


async def test_auth_rejection_maps_to_credential_message():
    ctx = await _ctx()
    ctx.http.mock_get(TREE, {}, 401)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=1))
    assert r.status == "error"
    assert r.error_code == "WP_AUTH_REJECTED"


# ── contract: every error carries a structural code ──────────────────────────

# ── heading_outline: text-safe heading visibility, never compacted ──────────
#
# `elements` is a nested list, so display clients that compact EntityList
# rows down to id/title/kind can hide it from the user entirely. This is
# exactly what made g4s.md/climtec.md h1.missing and heading_skip findings
# look unreachable in a live session even though the bridge returns full
# data. heading_outline is a plain string field carrying the same
# information — strings are never compacted — so callers can always see
# heading structure without needing a raw dump of `elements`.

async def test_heading_outline_lists_elementor_heading_with_its_level():
    ctx = await _ctx()
    payload = _tree_payload(builders={
        "elementor": {
            "elements": [_elementor_row(
                id="abc123", settings={"title": "Welcome Home", "header_size": "h1"})],
            "state_token": "tok-1", "element_count": 1,
        }
    })
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=42))
    row = r.data.items[0]
    assert row.heading_outline == "h1: Welcome Home (id=abc123)"
    assert "1 heading(s)" in r.summary


async def test_heading_outline_lists_bricks_heading_with_its_tag():
    ctx = await _ctx()
    payload = {
        "id": 7, "slug": "landing", "type": "page", "link": "https://x.com/landing",
        "active_builders": ["bricks"],
        "builders": {
            "bricks": {
                "zones": {
                    "content": {
                        "elements": [
                            {"id": "e1", "parent_id": None, "el_type": "heading",
                             "widget_type": "", "settings": {"tag": "h3", "text": "Our Services"},
                             "zone": "content"},
                            {"id": "e2", "parent_id": None, "el_type": "section",
                             "widget_type": "", "settings": {}, "zone": "content"},
                        ],
                        "state_token": "tok-content",
                    },
                    "header": {"elements": [], "state_token": "tok-header"},
                    "footer": {"elements": [], "state_token": "tok-footer"},
                }
            }
        },
    }
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=7))
    zones = {row.zone: row for row in r.data.items}
    assert zones["content"].heading_outline == "h3: Our Services (id=e1)"
    assert zones["header"].heading_outline == ""


async def test_heading_outline_strips_inline_html_from_bricks_text():
    ctx = await _ctx()
    payload = {
        "id": 7, "slug": "landing", "type": "page", "link": "https://x.com/landing",
        "active_builders": ["bricks"],
        "builders": {
            "bricks": {
                "zones": {
                    "content": {
                        "elements": [
                            {"id": "e1", "parent_id": None, "el_type": "heading",
                             "widget_type": "", "settings": {"tag": "h2", "text": "<strong>Bold</strong> Title"},
                             "zone": "content"},
                        ],
                        "state_token": "tok-content",
                    },
                }
            }
        },
    }
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=7))
    assert r.data.items[0].heading_outline == "h2: Bold Title (id=e1)"


async def test_summary_flags_true_absence_of_any_heading():
    ctx = await _ctx()
    payload = _tree_payload(builders={
        "elementor": {
            "elements": [{"id": "e1", "parent_id": None, "el_type": "widget",
                          "widget_type": "text-editor", "settings": {}}],
            "state_token": "tok-1", "element_count": 1,
        }
    })
    ctx.http.mock_get(TREE, payload, 200)
    r = await hb.get_builder_content(ctx, GetBuilderContentParams(site_id="x-com", post_id=42))
    assert r.data.items[0].heading_outline == ""
    assert "NO HEADINGS AT ALL" in r.summary


async def test_every_error_path_has_a_code():
    import ast
    import pathlib

    src = pathlib.Path(hb.__file__).read_text()
    tree = ast.parse(src)
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "error"):
            continue
        if not (isinstance(func.value, ast.Attribute) and func.value.attr == "ActionResult"
                or isinstance(func.value, ast.Name) and func.value.id == "ActionResult"):
            continue
        if not any(kw.arg == "code" for kw in node.keywords):
            missing.append(node.lineno)
    assert not missing, f"ActionResult.error without code= at lines {missing}"
