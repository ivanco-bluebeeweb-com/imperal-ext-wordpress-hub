"""Tests for Rank Math SEO meta read/write.

Covers both access tiers:
  * bridge   — /wp-json/imperal/v1/seo (full fields, posts + pages + CPTs)
  * fallback — stock REST meta, which is what a site running only the older
               WP Publisher bridge exposes (posts, strings only)

and the failure paths that decide what the user is told: no bridge, no Rank
Math, ambiguous slug, bad robots value, nothing to update.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_seo as hs
import storage
from models import GetSeoMetaParams, UpdateSeoMetaParams, SiteIdParams

BRIDGE = "https://x.com/wp-json/imperal/v1/seo"
STATUS = "https://x.com/wp-json/imperal/v1/seo/status"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _bridge_payload(**over):
    """A bridge GET response, with the field names the bridge REALLY sends.

    Captured verbatim from a live site (page 4286 on test3), because an
    invented fixture is how a field-name mismatch hides: the first version of
    these tests used post_id/post_type/seo_plugin, the bridge sends id/type/
    rank_math_active, and every test still passed while the real tool returned
    id 0 and an empty type.
    """
    payload = {
        "id": 42,
        "type": "page",
        "status": "publish",
        "slug": "about-us",
        "post_title": "About us",
        "link": "https://x.com/about-us",
        "meta_title": "About us | X",
        "meta_description": "Who we are.",
        "focus_keyword": "about",
        "canonical_url": "",
        "robots": ["index"],
        "rank_math_active": True,
    }
    payload.update(over)
    return payload


# The exact payload the live bridge returned for page 4286 on test3, and the
# exact /seo/status body from the same site. Kept literal on purpose: these are
# the contract, and a future bridge change should break these tests loudly.
LIVE_PAGE_PAYLOAD = {
    "id": 4286,
    "slug": "legal-disclaimer",
    "type": "page",
    "status": "publish",
    "link": "https://test3.ksrenovationgroup.com/legal-disclaimer/",
    "post_title": "Legal Disclaimer",
    "meta_title": "Legal Disclaimer | KS Renovation Group",
    "meta_description": (
        "Read the KS Renovation Group legal disclaimer for website information, "
        "third-party links, warranties, liability, and use of site content."
    ),
    "focus_keyword": "",
    "canonical_url": "",
    "robots": [],
    "rank_math_active": True,
}

LIVE_STATUS_PAYLOAD = {
    "bridge": True,
    "bridge_version": "1.0.0",
    "rank_math_active": True,
    "rank_math_version": "1.0.272",
    "post_types": ["post", "page", "wp_block", "blog-post", "feature",
                   "inspiration", "partner", "project", "review", "test-607"],
    "robots_choices": ["index", "noindex", "nofollow", "noarchive",
                       "noimageindex", "nosnippet"],
}


# ── reading via the bridge ───────────────────────────────────────────────────

async def test_get_reads_title_and_description_from_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(), 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=42))
    assert r.status == "success"
    assert r.data.meta_title == "About us | X"
    assert r.data.meta_description == "Who we are."


async def test_get_works_for_a_page_not_just_a_post():
    """The old WP Publisher bridge registered meta for 'post' only — pages
    silently had no SEO fields. The new bridge must cover pages."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(post_type="page"), 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", slug="about-us"))
    assert r.status == "success"
    assert r.data.post_type == "page"


async def test_get_returns_robots_and_canonical():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(
        robots=["noindex", "nofollow"], canonical_url="https://x.com/canonical"), 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=42))
    assert r.data.robots == ["noindex", "nofollow"]
    assert r.data.canonical_url == "https://x.com/canonical"


async def test_get_reports_source_so_fidelity_is_never_guessed():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(), 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=42))
    assert r.data.source == "bridge"


async def test_empty_meta_is_success_not_error():
    """Graceful fallback: no SEO value set is normal — Rank Math uses its
    template. It must not read as a failure."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(meta_title="", meta_description="",
                                              focus_keyword="", robots=[]), 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=42))
    assert r.status == "success"
    assert r.data.meta_title == ""
    assert "no Rank Math title" in r.summary


async def test_rank_math_absent_is_a_clear_error():
    """Bridge installed but Rank Math switched off — say so, do not pretend.

    The bridge signals this with rank_math_active=false, not with a plugin
    name, so this guard only works if that flag is actually honoured.
    """
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, _bridge_payload(rank_math_active=False), 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=42))
    assert r.status == "error"
    assert r.error_code == "SEO_PLUGIN_MISSING"
    assert "Rank Math" in r.error


# ── contract: the field names the bridge really sends ────────────────────────

async def test_live_bridge_payload_maps_id_and_type():
    """Regression guard for the bug this suite originally missed.

    The bridge sends `id` and `type`; an earlier parser read `post_id` and
    `post_type`, so every real call returned post_id 0 and an empty type while
    the invented fixtures passed. This replays a captured live response.
    """
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, LIVE_PAGE_PAYLOAD, 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=4286))
    assert r.status == "success"
    assert r.data.post_id == 4286, "id must be read from the bridge's `id` field"
    assert r.data.post_type == "page", "type must be read from the bridge's `type` field"
    assert r.data.id == "4286"
    assert r.data.meta_title == "Legal Disclaimer | KS Renovation Group"
    # The summary must name the thing, not degrade to a generic "item #0".
    assert r.summary.startswith("page #4286")


async def test_bridge_payload_without_ids_does_not_silently_zero():
    """A payload using the post_id/post_type spelling still resolves."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"post_id": 7, "post_type": "post", "slug": "x",
                               "meta_title": "T", "meta_description": "",
                               "rank_math_active": True}, 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=7))
    assert r.status == "success"
    assert r.data.post_id == 7 and r.data.post_type == "post"


# ── cache-busting on reads ───────────────────────────────────────────────────

async def test_reads_carry_a_cache_buster():
    """A page cache must not be able to answer our read.

    Bridge >= 1.0.1 marks its routes uncacheable, but entries cached before
    that fix survive it and a site may still run 1.0.0. Observed live: a read
    straight after a successful write came back empty, served from cache.

    The SDK's MockHTTP throws kwargs away, so it cannot show what we sent.
    Wrap its .get with a spy and assert on the ACTUAL outbound request —
    checking the helper in isolation would not prove it is wired in.
    """
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, LIVE_PAGE_PAYLOAD, 200)

    seen = []
    real_get = ctx.http.get

    async def spy(url, **kwargs):
        seen.append((url, kwargs.get("params") or {}))
        return await real_get(url, **kwargs)

    ctx.http.get = spy

    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=4286))
    assert r.status == "success"

    bridge_calls = [(u, p) for u, p in seen if "imperal/v1/seo" in u]
    assert bridge_calls, f"no bridge request was made; saw {[u for u, _ in seen]}"
    url, sent = bridge_calls[0]
    assert "_imperal_cb" in sent, f"read went out with no cache-buster: {sent}"
    assert sent["id"] == 4286, "the real target must survive cache-busting"


def test_cache_buster_is_unique_per_call():
    a = hs._cache_busted({"id": 1})
    b = hs._cache_busted({"id": 1})
    assert a["_imperal_cb"] != b["_imperal_cb"], "a constant value would just be cached too"


def test_cache_buster_preserves_the_real_query():
    q = hs._cache_busted({"id": 7, "slug": "hello", "type": "page"})
    assert q["id"] == 7 and q["slug"] == "hello" and q["type"] == "page"
    assert len(q) == 4  # the three originals plus the buster


def test_cache_buster_does_not_mutate_its_input():
    original = {"id": 7}
    hs._cache_busted(original)
    assert original == {"id": 7}, "callers must not see their dict grow a param"


# ── target resolution ────────────────────────────────────────────────────────

async def test_no_id_and_no_slug_refuses_rather_than_guessing():
    ctx = await _ctx()
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com"))
    assert r.status == "error"
    assert r.error_code == "SEO_TARGET_MISSING"


async def test_ambiguous_slug_from_bridge_is_surfaced_faithfully():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "imperal_seo_ambiguous_slug",
                               "message": "Several items share that slug."}, 409)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", slug="dup"))
    assert r.status == "error"
    assert r.error_code == "SEO_SLUG_AMBIGUOUS"


async def test_item_not_found_is_its_own_code():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "imperal_seo_not_found",
                               "message": "Nothing matched."}, 404)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=999))
    assert r.status == "error"
    # 404 with a bridge error body means the bridge answered: item missing,
    # not plugin missing.
    assert r.error_code == "SEO_ITEM_NOT_FOUND"


# ── writing via the bridge ───────────────────────────────────────────────────

async def test_update_writes_title_and_description():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, _bridge_payload(
        meta_title="New title", meta_description="New description",
        updated_fields=["meta_title", "meta_description"]), 200)
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(
        site_id="x-com", post_id=42,
        meta_title="New title", meta_description="New description"))
    assert r.status == "success"
    assert r.data.meta_title == "New title"
    assert set(r.data.updated_fields) == {"meta_title", "meta_description"}


async def test_update_with_no_fields_is_refused():
    ctx = await _ctx()
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(site_id="x-com", post_id=42))
    assert r.status == "error"
    assert r.error_code == "SEO_NO_FIELDS"


async def test_invalid_robots_rejected_before_any_request():
    """Validation happens locally, so a bad value never reaches the site."""
    ctx = await _ctx()
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(
        site_id="x-com", post_id=42, robots=["nosuchdirective"]))
    assert r.status == "error"
    assert r.error_code == "SEO_INVALID_ROBOTS"
    assert "noindex" in r.error  # tells the user what IS allowed


async def test_valid_robots_accepted():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, _bridge_payload(robots=["noindex"],
                                               updated_fields=["robots"]), 200)
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(
        site_id="x-com", post_id=42, robots=["noindex"]))
    assert r.status == "success"
    assert r.data.robots == ["noindex"]


async def test_empty_string_clears_a_field_but_none_leaves_it_alone():
    """Distinguishing 'omitted' from 'set to empty' is the difference between
    leaving a title alone and wiping it."""
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, _bridge_payload(meta_title="",
                                               updated_fields=["meta_title"]), 200)
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(
        site_id="x-com", post_id=42, meta_title=""))
    assert r.status == "success"
    assert r.data.updated_fields == ["meta_title"]


async def test_forbidden_write_is_reported_as_permission_problem():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, {"code": "imperal_seo_forbidden",
                                "message": "That user cannot edit this item."}, 403)
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(
        site_id="x-com", post_id=42, meta_title="X"))
    assert r.status == "error"
    assert r.error_code == "WP_FORBIDDEN"


# ── fallback tier: stock REST meta ───────────────────────────────────────────

async def test_falls_back_to_core_meta_when_bridge_absent():
    """A site with only the older WP Publisher bridge still answers for posts."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts/7", {
        "id": 7, "slug": "hello", "type": "post",
        "title": {"rendered": "Hello"}, "link": "https://x.com/hello",
        "meta": {"rank_math_title": "Hello | X", "rank_math_description": "Hi there."},
    }, 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=7, post_type="post"))
    assert r.status == "success"
    assert r.data.meta_title == "Hello | X"
    assert r.data.source == "core-meta"
    assert "core meta" in r.summary  # fidelity is stated, not hidden


async def test_no_bridge_and_no_registered_meta_tells_user_to_install():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts/7", {
        "id": 7, "slug": "hello", "type": "post",
        "title": {"rendered": "Hello"}, "meta": {},
    }, 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=7, post_type="post"))
    assert r.status == "error"
    assert r.error_code == "SEO_BRIDGE_MISSING"
    assert "Bridge" in r.error


async def test_core_tier_resolves_a_slug_when_bridge_absent():
    """Slug lookup must work on the fallback tier too — that is today's climtec.md."""
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [{
        "id": 7, "slug": "hello", "type": "post",
        "title": {"rendered": "Hello"}, "link": "https://x.com/hello",
        "meta": {"rank_math_title": "Hello | X", "rank_math_description": ""},
    }], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", slug="hello"))
    assert r.status == "success"
    assert r.data.post_id == 7
    assert r.data.meta_title == "Hello | X"


async def test_core_tier_refuses_ambiguous_slug_instead_of_picking_one():
    """A slug shared by a post and a page must never resolve silently.

    Guessing here would edit the SEO of the wrong item — the failure would be
    invisible until someone noticed the wrong page's title had changed.
    """
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [{
        "id": 7, "slug": "contact", "type": "post",
        "title": {"rendered": "Contact"}, "meta": {"rank_math_title": "post one"},
    }], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [{
        "id": 9, "slug": "contact", "type": "page",
        "title": {"rendered": "Contact"}, "meta": {"rank_math_title": "page one"},
    }], 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", slug="contact"))
    assert r.status == "error"
    assert r.error_code == "SEO_SLUG_AMBIGUOUS"
    assert "post_type" in r.error  # tells the user how to disambiguate


async def test_core_tier_unknown_slug_is_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", slug="nope"))
    assert r.status == "error"
    assert r.error_code == "SEO_ITEM_NOT_FOUND"


async def test_robots_write_without_bridge_is_refused_not_silently_dropped():
    """Core meta cannot carry robots. Refusing beats pretending it worked."""
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, {"code": "rest_no_route"}, 404)
    r = await hs.update_seo_meta(ctx, UpdateSeoMetaParams(
        site_id="x-com", post_id=7, robots=["noindex"]))
    assert r.status == "error"
    assert r.error_code == "SEO_BRIDGE_MISSING"
    assert "robots" in r.error


# ── site / credential problems ───────────────────────────────────────────────

async def test_unknown_site_is_a_clear_error():
    ctx = await _ctx()
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="nope", post_id=1))
    assert r.status == "error"
    assert r.error_code == "SITE_NOT_CONNECTED"


async def test_auth_rejection_maps_to_credential_message():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {}, 401)
    r = await hs.get_seo_meta(ctx, GetSeoMetaParams(site_id="x-com", post_id=1))
    assert r.status == "error"
    assert r.error_code == "WP_AUTH_REJECTED"


# ── support check ────────────────────────────────────────────────────────────

async def test_check_reports_bridge_and_rank_math_active():
    """Status is reported from the real /seo/status body, field names included."""
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, LIVE_STATUS_PAYLOAD, 200)
    r = await hs.check_seo_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.seo_plugin == "rank-math"
    assert "page" in r.data.post_types  # pages covered — the original bug
    assert r.data.bridge_version == "1.0.0"  # bridge_version, not 'version'
    assert r.data.rank_math_version == "1.0.272"
    assert "1.0.0" in r.summary and "page" in r.summary


async def test_check_reports_missing_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {"code": "rest_no_route"}, 404)
    r = await hs.check_seo_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "error"
    assert r.error_code == "SEO_BRIDGE_MISSING"


async def test_check_reports_bridge_without_rank_math():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {"bridge": True, "version": "1.0.0",
                               "rank_math_active": False, "post_types": []}, 200)
    r = await hs.check_seo_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.seo_plugin == "none"
    assert "not active" in r.summary


# ── contract: every error carries a structural code ──────────────────────────

async def test_every_error_path_has_a_code():
    """A code-less error is stamped EXT_UNSTRUCTURED_ERROR by the kernel,
    leaving the narrator nothing stable to reason about."""
    import ast
    import pathlib

    src = pathlib.Path(hs.__file__).read_text()
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
