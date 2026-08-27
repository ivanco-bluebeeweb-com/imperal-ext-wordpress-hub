"""Contract tests for Group J CPT/taxonomy introspection: handlers_cpt_taxonomy.py.

Native WordPress REST (`GET /wp/v2/types`, `GET /wp/v2/taxonomies`) --
shipped in WP core since the REST API's introduction, so no Bridge or SSH
is ever needed here. The only real branch is the context=edit -> plain-view
fallback when the connected user's role can't see edit-context fields.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_cpt_taxonomy as hct
import storage
from models import AssignPostTaxonomyParams, SiteIdParams

BASE = "https://blog.test"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


# ─────────── list_registered_post_types ───────────

async def test_list_registered_post_types_reads_native_rest():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/types", {
        "post": {
            "name": "Posts", "rest_base": "posts", "hierarchical": False,
            "viewable": True, "has_archive": False, "taxonomies": ["category", "post_tag"],
        },
        "page": {
            "name": "Pages", "rest_base": "pages", "hierarchical": True,
            "viewable": True, "has_archive": False, "taxonomies": [],
        },
    }, 200)
    result = await hct.list_registered_post_types(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    slugs = sorted(item.slug for item in result.data.items)
    assert slugs == ["page", "post"]
    page = next(i for i in result.data.items if i.slug == "page")
    assert page.hierarchical is True
    assert page.rest_base == "pages"
    post = next(i for i in result.data.items if i.slug == "post")
    assert post.viewable is True
    assert post.taxonomies == ["category", "post_tag"]


async def test_list_registered_post_types_falls_back_on_permission_refusal(monkeypatch):
    """context=edit is refused (403) -> retries with the plain view context."""
    ctx = await _ctx()
    calls = []

    async def fake_wp_get(ctx, base_url, path, *, username, app_password, params=None):
        calls.append(params)
        if params and params.get("context") == "edit":
            return type("R", (), {"status_code": 403, "body": {"code": "rest_forbidden"}})()
        return type("R", (), {"status_code": 200, "body": {
            "post": {"name": "Posts", "rest_base": "posts", "hierarchical": False},
        }})()

    monkeypatch.setattr(hct, "wp_get", fake_wp_get)
    result = await hct.list_registered_post_types(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(calls) == 2  # edit-context attempt, then the plain-view retry
    assert len(result.data.items) == 1
    # viewable wasn't in the plain-view response -- honest default, not fabricated.
    assert result.data.items[0].viewable is False


async def test_list_registered_post_types_surfaces_hard_error(monkeypatch):
    ctx = await _ctx()

    async def fake_wp_get(ctx, base_url, path, *, username, app_password, params=None):
        if params and params.get("context") == "edit":
            return type("R", (), {"status_code": 403, "body": {"code": "rest_forbidden"}})()
        return type("R", (), {"status_code": 500, "body": {"code": "error"}})()

    monkeypatch.setattr(hct, "wp_get", fake_wp_get)
    result = await hct.list_registered_post_types(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.retryable is True


async def test_list_registered_post_types_requires_connected_site():
    ctx = MockContext()
    result = await hct.list_registered_post_types(ctx, SiteIdParams(site_id="nope"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


# ─────────── list_registered_taxonomies ───────────

async def test_list_registered_taxonomies_reads_native_rest():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies", {
        "category": {
            "name": "Categories", "rest_base": "categories", "hierarchical": True,
            "visibility": {"public": True}, "types": ["post"],
        },
        "post_tag": {
            "name": "Tags", "rest_base": "tags", "hierarchical": False,
            "visibility": {"public": True}, "types": ["post"],
        },
    }, 200)
    result = await hct.list_registered_taxonomies(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    slugs = sorted(item.slug for item in result.data.items)
    assert slugs == ["category", "post_tag"]
    cat = next(i for i in result.data.items if i.slug == "category")
    assert cat.hierarchical is True
    assert cat.public is True
    assert cat.types == ["post"]


async def test_list_registered_taxonomies_falls_back_on_permission_refusal(monkeypatch):
    """context=edit is refused (401) -> retries with the plain view context."""
    ctx = await _ctx()

    async def fake_wp_get(ctx, base_url, path, *, username, app_password, params=None):
        if params and params.get("context") == "edit":
            return type("R", (), {"status_code": 401, "body": {"code": "rest_forbidden"}})()
        return type("R", (), {"status_code": 200, "body": {
            "category": {"name": "Categories", "rest_base": "categories", "hierarchical": True},
        }})()

    monkeypatch.setattr(hct, "wp_get", fake_wp_get)
    result = await hct.list_registered_taxonomies(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(result.data.items) == 1
    assert result.data.items[0].public is False


async def test_list_registered_taxonomies_requires_credential():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": BASE, "username": "admin", "status": "connected",
    })
    result = await hct.list_registered_taxonomies(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "SITE_CREDENTIAL_MISSING"


# ─────────── assign_post_taxonomy (custom taxonomy gap -- climtec.md product-type) ───────────

def _product_type_taxonomy(rest_base="product-type"):
    return {
        "name": "Product Type", "rest_base": rest_base, "hierarchical": False,
        "visibility": {"public": True}, "types": ["product"],
    }


async def test_assign_post_taxonomy_resolves_existing_term_by_name():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies/product-type", _product_type_taxonomy(), 200)
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/product-type",
                       [{"id": 61, "name": "RD", "slug": "rd"}], 200)
    ctx.http.mock_post(f"{BASE}/wp-json/wp/v2/product/2776", {"id": 2776, "product-type": [61]}, 200)

    result = await hct.assign_post_taxonomy(ctx, AssignPostTaxonomyParams(
        site_id="blog-test", post_id=2776, post_type="product",
        taxonomy="product-type", terms=["RD"]))

    assert result.status == "success"
    assert result.data.term_ids == [61]
    assert result.data.rest_base == "product-type"
    assert result.data.created_terms == []
    assert result.data.terms_not_found == []


async def test_assign_post_taxonomy_accepts_numeric_term_id_without_lookup():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies/product-type", _product_type_taxonomy(), 200)
    ctx.http.mock_post(f"{BASE}/wp-json/wp/v2/product/2779", {"id": 2779, "product-type": [62]}, 200)

    result = await hct.assign_post_taxonomy(ctx, AssignPostTaxonomyParams(
        site_id="blog-test", post_id=2779, post_type="product",
        taxonomy="product-type", terms=["62"]))

    assert result.status == "success"
    assert result.data.term_ids == [62]


async def test_assign_post_taxonomy_creates_missing_term_by_default():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies/product-type", _product_type_taxonomy(), 200)
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/product-type", [], 200)  # no existing "RDC" term
    ctx.http.mock_post(f"{BASE}/wp-json/wp/v2/product-type", {"id": 70, "name": "RDC"}, 201)
    ctx.http.mock_post(f"{BASE}/wp-json/wp/v2/product/2900", {"id": 2900, "product-type": [70]}, 200)

    result = await hct.assign_post_taxonomy(ctx, AssignPostTaxonomyParams(
        site_id="blog-test", post_id=2900, post_type="product",
        taxonomy="product-type", terms=["RDC"]))

    assert result.status == "success"
    assert result.data.term_ids == [70]
    assert result.data.created_terms == ["RDC"]


async def test_assign_post_taxonomy_create_missing_false_leaves_unresolved():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies/product-type", _product_type_taxonomy(), 200)
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/product-type", [], 200)

    result = await hct.assign_post_taxonomy(ctx, AssignPostTaxonomyParams(
        site_id="blog-test", post_id=2900, post_type="product",
        taxonomy="product-type", terms=["Ghost"], create_missing=False))

    assert result.status == "error"
    assert result.error_code == "WP_TAXONOMY_TERMS_UNRESOLVED"


async def test_assign_post_taxonomy_unknown_taxonomy_slug():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies/nope", {"code": "rest_no_route"}, 404)

    result = await hct.assign_post_taxonomy(ctx, AssignPostTaxonomyParams(
        site_id="blog-test", post_id=2776, post_type="product",
        taxonomy="nope", terms=["RD"]))

    assert result.status == "error"
    assert result.error_code == "WP_TAXONOMY_NOT_FOUND"


async def test_assign_post_taxonomy_post_not_found():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/taxonomies/product-type", _product_type_taxonomy(), 200)
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/product-type",
                       [{"id": 61, "name": "RD", "slug": "rd"}], 200)
    ctx.http.mock_post(f"{BASE}/wp-json/wp/v2/product/999999", {"code": "rest_post_invalid_id"}, 404)

    result = await hct.assign_post_taxonomy(ctx, AssignPostTaxonomyParams(
        site_id="blog-test", post_id=999999, post_type="product",
        taxonomy="product-type", terms=["RD"]))

    assert result.status == "error"
    assert result.error_code == "WP_POST_NOT_FOUND"
