"""Tests for Rank Math SEO meta on TERMS (categories, tags).

Terms are not posts: WordPress stores their meta in a different table, gates
editing through the `edit_term` meta capability, and the older WP Publisher
bridge registered post meta only — so there is no core-meta fallback tier for
terms at all. A missing term route must therefore say "update the bridge"
rather than silently degrade.

The fixture below uses the key names the bridge really emits for a term. Those
names are asserted against the PHP source in
test_bridge_payload_contract_matches_php, because an invented fixture is
exactly how the id/type vs post_id/post_type mismatch once hid: every test
passed while the real tool returned id 0 and an empty type.
"""

import re
from pathlib import Path

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_seo as hs
import storage
from models import GetTermSeoMetaParams, UpdateTermSeoMetaParams, SiteIdParams

TERM = "https://x.com/wp-json/imperal/v1/seo/term"
STATUS = "https://x.com/wp-json/imperal/v1/seo/status"

BRIDGE_PHP = (Path(__file__).resolve().parent.parent
              / "bridge" / "imperal-bridge" / "imperal-bridge.php")


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _spy_get(ctx):
    """Record outgoing GETs. MockHTTP discards kwargs, so a spy on the real
    method is the only way to prove what actually went out."""
    seen = []
    real = ctx.http.get

    async def spy(url, **kwargs):
        seen.append((url, kwargs.get("params") or {}))
        return await real(url, **kwargs)

    ctx.http.get = spy
    return seen


def _spy_post(ctx):
    """Record outgoing POST bodies."""
    seen = []
    real = ctx.http.post

    async def spy(url, **kwargs):
        seen.append((url, kwargs.get("json") or kwargs.get("data") or {}))
        return await real(url, **kwargs)

    ctx.http.post = spy
    return seen


def _term_payload(**over):
    """A bridge GET response for a term, in the bridge's own key names."""
    payload = {
        "id": 11,
        "slug": "sisteme",
        "type": "category",
        "taxonomy": "category",
        "object": "term",
        "status": "publish",
        "link": "https://x.com/category/sisteme/",
        "post_title": "Sisteme",
        "meta_title": "Cum functioneaza ventilatia | G4S",
        "meta_description": "Articole tehnice despre sisteme inginerest.",
        "og_image_url": "",
        "focus_keyword": "",
        "canonical_url": "",
        "robots": [],
        "rich_snippet": "",
        "rank_math_active": True,
    }
    payload.update(over)
    return payload


# ── reading ──────────────────────────────────────────────────────────────────

async def test_get_reads_term_title_and_description():
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(), 200)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    assert r.status == "success"
    assert r.data.meta_title == "Cum functioneaza ventilatia | G4S"
    assert r.data.meta_description == "Articole tehnice despre sisteme inginerest."


async def test_get_term_reports_it_is_a_term_not_a_post():
    """object_type/taxonomy must be filled, otherwise a category row is
    indistinguishable from a post row in any listing or automation."""
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(), 200)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    assert r.data.object_type == "term"
    assert r.data.taxonomy == "category"


async def test_get_term_keeps_the_real_id():
    """Regression guard for the id/post_id mismatch that produced '#0'."""
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(), 200)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    assert r.data.post_id == 11
    assert "#0" not in r.summary


async def test_get_term_by_slug_sends_slug_and_taxonomy():
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(), 200)
    seen = _spy_get(ctx)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(
        site_id="x-com", slug="sisteme", taxonomy="category"))
    assert r.status == "success"
    term_calls = [(u, prm) for u, prm in seen if "seo/term" in u]
    assert term_calls, f"no term request was made; saw {[u for u, _ in seen]}"
    params = term_calls[-1][1]
    assert params.get("slug") == "sisteme"
    assert params.get("taxonomy") == "category"


async def test_term_reads_are_cache_busted():
    """A page cache must not be able to answer a permission-gated read.

    Live finding: LiteSpeed stored an authenticated SEO payload and replayed it
    to an anonymous caller. The buster is what protects sites whose bridge is
    still older than the no-cache fix.
    """
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(), 200)
    seen = _spy_get(ctx)
    await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    term_calls = [(u, prm) for u, prm in seen if "seo/term" in u]
    assert term_calls, f"no term request was made; saw {[u for u, _ in seen]}"
    params = term_calls[-1][1]
    assert "_imperal_cb" in params, f"read went out with no cache-buster: {params}"
    assert params.get("id") == 11, "the real target must survive cache-busting"


async def test_empty_term_meta_is_success_not_error():
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(meta_title="", meta_description=""), 200)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    assert r.status == "success"
    assert "no Rank Math title" in r.summary


async def test_term_rank_math_absent_is_a_clear_error():
    """Reading with Rank Math off must not look like "this category has no SEO".

    Without this guard the fields come back as ordinary empty strings, which
    reads as "nothing set here" instead of "nothing here can work yet".
    """
    ctx = await _ctx()
    ctx.http.mock_get(TERM, _term_payload(rank_math_active=False), 200)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    assert r.status == "error"
    assert r.error_code == "SEO_PLUGIN_MISSING"
    assert "Rank Math" in r.error


async def test_term_write_with_rank_math_off_does_not_claim_a_rendered_change():
    """The meta rows ARE written, so this is a success -- but nothing renders
    them while Rank Math is inactive, and a bare "Updated ..." would overstate
    the outcome."""
    ctx = await _ctx()
    ctx.http.mock_post(TERM, _term_payload(meta_title="New", rank_math_active=False,
                                           updated=["meta_title"]), 200)
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, meta_title="New"))
    assert r.status == "success"
    assert "not active" in r.summary, r.summary


# ── the missing-target guard ─────────────────────────────────────────────────

async def test_no_term_id_and_no_slug_is_refused():
    ctx = await _ctx()
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com"))
    assert r.status == "error"
    assert r.error_code == "SEO_TARGET_MISSING"


async def test_update_without_a_target_is_refused():
    ctx = await _ctx()
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", meta_title="X"))
    assert r.status == "error"
    assert r.error_code == "SEO_TARGET_MISSING"


# ── writing ──────────────────────────────────────────────────────────────────

async def test_update_term_writes_title_and_description():
    ctx = await _ctx()
    ctx.http.mock_post(TERM, _term_payload(
        meta_title="New title", meta_description="New description",
        updated=["meta_title", "meta_description"]), 200)
    seen = _spy_post(ctx)
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11,
        meta_title="New title", meta_description="New description"))
    assert r.status == "success"
    assert seen, "no write request was made"
    body = seen[-1][1]
    assert body.get("meta_title") == "New title"
    assert body.get("meta_description") == "New description"


async def test_update_term_writes_rich_snippet():
    ctx = await _ctx()
    ctx.http.mock_post(TERM, _term_payload(rich_snippet="CollectionPage",
                                           updated=["rich_snippet"]), 200)
    seen = _spy_post(ctx)
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, rich_snippet="CollectionPage"))
    assert r.status == "success"
    assert r.data.rich_snippet == "CollectionPage"
    body = seen[-1][1]
    assert body.get("rich_snippet") == "CollectionPage"


async def test_update_term_omits_fields_not_given():
    """Partial update: a caller changing the description must not wipe the
    title. Sending None for untouched fields would clear them."""
    ctx = await _ctx()
    ctx.http.mock_post(TERM, _term_payload(updated=["meta_description"]), 200)
    seen = _spy_post(ctx)
    await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, meta_description="Only this"))
    assert seen, "no write request was made"
    body = seen[-1][1]
    assert "meta_description" in body
    assert "meta_title" not in body
    assert "canonical_url" not in body
    assert "robots" not in body


async def test_update_term_allows_explicit_clearing():
    """An empty string is a real instruction: clear the field."""
    ctx = await _ctx()
    ctx.http.mock_post(TERM, _term_payload(meta_title=""), 200)
    seen = _spy_post(ctx)
    await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, meta_title=""))
    assert seen, "no write request was made"
    assert seen[-1][1].get("meta_title") == ""


async def test_update_term_with_nothing_to_change_is_refused():
    ctx = await _ctx()
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11))
    assert r.status == "error"
    assert "nothing" in r.error.lower() or "no " in r.error.lower()


async def test_update_term_rejects_unknown_robots_value_before_sending():
    """Validate locally: a bad value must not reach the site at all."""
    ctx = await _ctx()
    posts = _spy_post(ctx)
    gets = _spy_get(ctx)
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, robots=["nosuchdirective"]))
    assert r.status == "error"
    assert not posts, "an invalid robots value was still sent to the site"
    assert not gets, "an invalid robots value still triggered a request"


async def test_update_term_accepts_valid_robots():
    ctx = await _ctx()
    ctx.http.mock_post(TERM, _term_payload(robots=["noindex"]), 200)
    seen = _spy_post(ctx)
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, robots=["noindex"]))
    assert r.status == "success"
    assert seen, "no write request was made"
    assert seen[-1][1].get("robots") == ["noindex"]


# ── failure paths that must be honest ────────────────────────────────────────

async def test_missing_term_route_says_update_the_bridge():
    """404 rest_no_route = bridge absent or older than 1.1.0.

    There is no core-meta fallback for terms, so the only correct answer is to
    name the fix — not to report empty SEO fields as if the term had none.
    """
    ctx = await _ctx()
    ctx.http.mock_get(TERM, {"code": "rest_no_route", "message": "No route"}, 404)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", term_id=11))
    assert r.status == "error"
    assert r.error_code == "SEO_BRIDGE_TERMS_UNSUPPORTED"
    assert "1.1" in r.error


async def test_ambiguous_term_slug_is_surfaced_not_guessed():
    ctx = await _ctx()
    ctx.http.mock_get(TERM, {"code": "imperal_seo_ambiguous_slug",
                             "message": "matches more than one"}, 409)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="x-com", slug="news"))
    assert r.status == "error"


async def test_forbidden_term_write_is_reported_as_permission():
    ctx = await _ctx()
    ctx.http.mock_post(TERM, {"code": "imperal_seo_cannot_edit",
                              "message": "not allowed"}, 403)
    r = await hs.update_term_seo_meta(ctx, UpdateTermSeoMetaParams(
        site_id="x-com", term_id=11, meta_title="X"))
    assert r.status == "error"


async def test_unknown_site_is_refused_before_any_request():
    ctx = await _ctx()
    gets = _spy_get(ctx)
    r = await hs.get_term_seo_meta(ctx, GetTermSeoMetaParams(site_id="nope", term_id=11))
    assert r.status == "error"
    assert not gets, "an unknown site still triggered a request"


# ── support reporting ────────────────────────────────────────────────────────

async def test_check_support_lists_taxonomies():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {
        "bridge": True, "bridge_version": "1.1.0", "rank_math_active": True,
        "rank_math_version": "1.0.274.1",
        "post_types": ["post", "page"],
        "taxonomies": ["category", "post_tag"],
        "robots_choices": list(hs.ROBOTS_CHOICES),
    }, 200)
    r = await hs.check_seo_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.taxonomies == ["category", "post_tag"]
    assert "category" in r.summary


async def test_check_support_flags_a_bridge_too_old_for_terms():
    """An old bridge omits `taxonomies` entirely. That must read as "cannot do
    categories yet", not as "this site has no taxonomies"."""
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {
        "bridge": True, "bridge_version": "1.0.1", "rank_math_active": True,
        "rank_math_version": "1.0.274.1",
        "post_types": ["post", "page"],
        "robots_choices": list(hs.ROBOTS_CHOICES),
    }, 200)
    r = await hs.check_seo_support(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.taxonomies == []
    assert "too old" in r.summary


# ── contract: the fixture must match the PHP the bridge actually runs ────────

def test_bridge_payload_contract_matches_php():
    """Cross-check the term fixture against the PHP source.

    Guards the exact bug class that once made every read return id 0: the two
    sides drifting on key names while both sets of tests stayed green.
    """
    php = BRIDGE_PHP.read_text(encoding="utf-8")
    m = re.search(r"function imperal_seo_bridge_term_payload\s*\([^)]*\)\s*\{(.*?)\n\}",
                  php, re.S)
    assert m, "term payload builder not found in the bridge PHP"
    keys = set(re.findall(r"'([a-z_]+)'\s*=>", m.group(1)))
    for required in ("id", "slug", "type", "taxonomy", "link", "post_title",
                     "meta_title", "meta_description", "focus_keyword",
                     "canonical_url", "robots"):
        assert required in keys, f"bridge no longer sends '{required}'"
    unexpected = keys - set(_term_payload())
    assert not unexpected, f"bridge sends keys the fixture does not model: {unexpected}"


def test_term_meta_keys_are_the_confirmed_rank_math_keys():
    """Keys confirmed in Rank Math 1.0.274.1: it switches update_post_meta ->
    update_term_meta for terms and keeps the same rank_math_* key names
    (includes/rest/class-post.php), and its Yoast importer maps wpseo_title ->
    rank_math_title / wpseo_desc -> rank_math_description for term meta.
    """
    php = BRIDGE_PHP.read_text(encoding="utf-8")
    m = re.search(r"function imperal_seo_bridge_term_payload\s*\([^)]*\)\s*\{(.*?)\n\}",
                  php, re.S)
    body = m.group(1)
    assert "get_term_meta( $term->term_id, 'rank_math_title'" in body
    assert "get_term_meta( $term->term_id, 'rank_math_description'" in body
    # It must read TERM meta, never post meta, or it would read a post that
    # happens to share the term's numeric id.
    assert "get_post_meta" not in body
