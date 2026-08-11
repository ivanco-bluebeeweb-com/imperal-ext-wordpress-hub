"""Contract tests for REST API introspection and Application Password auditing:
handlers_rest_api.py."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_rest_api as hra
import storage
from models import GetRestRouteSchemaParams, ListRestRoutesParams, RevokeApplicationPasswordParams, SiteIdParams

BASE = "https://blog.test"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


def _index(routes=None):
    return {
        "name": "Blog",
        "routes": routes or {
            "/wp/v2/posts": {
                "namespace": "wp/v2",
                "methods": ["GET", "POST"],
                "endpoints": [
                    {"methods": ["GET"], "args": {"page": {"type": "integer"}}},
                    {"methods": ["POST"], "args": {"title": {"type": "string", "required": True}}},
                ],
            },
            "/wp/v2/comments": {
                "namespace": "wp/v2",
                "methods": ["GET", "POST"],
                "endpoints": [{"methods": ["GET"], "args": {}}],
            },
            "/wc/v3/products": {
                "namespace": "wc/v3",
                "methods": ["GET"],
                "endpoints": [{"methods": ["GET"], "args": {}}],
            },
        },
    }


# ─────────── list_rest_routes ───────────

async def test_list_rest_routes_lists_every_route():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/", _index())
    result = await hra.list_rest_routes(ctx, ListRestRoutesParams(site_id="blog-test", namespace=None))
    assert result.status == "success"
    routes = {r.route for r in result.data.items}
    assert routes == {"/wp/v2/posts", "/wp/v2/comments", "/wc/v3/products"}


async def test_list_rest_routes_filters_by_namespace():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/", _index())
    result = await hra.list_rest_routes(ctx, ListRestRoutesParams(site_id="blog-test", namespace="wc/v3"))
    assert result.status == "success"
    assert len(result.data.items) == 1
    assert result.data.items[0].route == "/wc/v3/products"


async def test_list_rest_routes_unreachable_index_is_reported_not_faked():
    ctx = await _ctx()
    # No mock registered for /wp-json/ -> MockContext http returns 404 by default.
    result = await hra.list_rest_routes(ctx, ListRestRoutesParams(site_id="blog-test", namespace=None))
    assert result.status == "error"


# ─────────── get_rest_route_schema ───────────

async def test_get_rest_route_schema_returns_matching_route():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/", _index())
    result = await hra.get_rest_route_schema(
        ctx, GetRestRouteSchemaParams(site_id="blog-test", route="/wp/v2/posts"))
    assert result.status == "success"
    assert result.data.route == "/wp/v2/posts"
    assert result.data.namespace == "wp/v2"
    assert len(result.data.endpoints) == 2


async def test_get_rest_route_schema_unknown_route_is_error():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/", _index())
    result = await hra.get_rest_route_schema(
        ctx, GetRestRouteSchemaParams(site_id="blog-test", route="/does/not/exist"))
    assert result.status == "error"
    assert result.error_code == "WP_ROUTE_NOT_FOUND"


# ─────────── list_application_passwords ───────────

async def test_list_application_passwords_maps_fields_never_returns_secret():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users/me/application-passwords", [
        {"uuid": "abc-123", "app_id": "", "name": "Imperal", "created": "2026-01-01T00:00:00",
         "last_used": "2026-08-01T00:00:00", "last_ip": "1.2.3.4"},
    ])
    result = await hra.list_application_passwords(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    item = result.data.items[0]
    assert item.uuid == "abc-123"
    assert item.name == "Imperal"
    assert not hasattr(item, "password")


async def test_list_application_passwords_requires_wp_5_6(monkeypatch):
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users/me/application-passwords", {"code": "rest_no_route"}, status=404)
    result = await hra.list_application_passwords(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"


# ─────────── revoke_application_password ───────────

async def test_revoke_application_password_deletes_by_uuid():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/wp-json/wp/v2/users/me/application-passwords/abc-123",
                  {"deleted": True})
    result = await hra.revoke_application_password(
        ctx, RevokeApplicationPasswordParams(site_id="blog-test", uuid="abc-123"))
    assert result.status == "success"


async def test_revoke_application_password_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/wp-json/wp/v2/users/me/application-passwords/missing",
                 {"code": "rest_application_password_not_found"}, status=404)
    result = await hra.revoke_application_password(
        ctx, RevokeApplicationPasswordParams(site_id="blog-test", uuid="missing"))
    assert result.status == "error"
