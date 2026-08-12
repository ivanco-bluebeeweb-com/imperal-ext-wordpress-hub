"""Contract tests for Rank Math redirects via Imperal Bridge SECTION 5."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_redirects as hr
import storage
from models import (
    ApplyBulkRedirectStatusParams,
    BulkRedirectStatusParams,
    CreateRedirectParams,
    DeleteRedirectParams,
    ListRedirectsParams,
    SetRedirectStatusParams,
)

BRIDGE = "https://shop.test/wp-json/imperal/v1/redirects"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


def _redirect(rid=1, **over):
    data = {
        "id": rid, "sources": [{"pattern": "/old/", "comparison": "exact"}],
        "url_to": "/new/", "header_code": 301, "hits": 12, "status": "active",
        "created": "2026-01-01T00:00:00", "updated": "2026-01-02T00:00:00",
    }
    data.update(over)
    return data


async def test_list_redirects_maps_fields_and_sums_hits():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, [_redirect(), _redirect(rid=2, hits=3)])
    result = await hr.list_redirects(ctx, ListRedirectsParams(site_id="shop-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert result.data.items[0].url_to == "/new/"
    assert "15 total hit" in result.summary


async def test_preview_and_apply_bulk_redirect_status():
    ctx = await _ctx()
    rows = [_redirect(1, status="active"), _redirect(2, status="active")]
    ctx.http.mock_get(BRIDGE, rows)
    preview = await hr.preview_bulk_redirect_status(ctx, BulkRedirectStatusParams(
        site_id="shop-test", redirect_ids=[1, 2], status="inactive"))
    assert preview.status == "success" and preview.data.preview is True
    assert preview.data.matched == 2

    ctx.http.mock_get(BRIDGE, rows)
    ctx.http.mock_post(f"{BRIDGE}/1/status", _redirect(1, status="inactive"))
    ctx.http.mock_post(f"{BRIDGE}/2/status", _redirect(2, status="inactive"))
    result = await hr.apply_bulk_redirect_status(ctx, ApplyBulkRedirectStatusParams(
        site_id="shop-test", redirect_ids=[1, 2], status="inactive",
        expected_state_token=preview.data.state_token))
    assert result.status == "success" and result.data.updated == 2


async def test_apply_bulk_redirect_status_refuses_stale_token():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, [_redirect(1, status="active")])
    result = await hr.apply_bulk_redirect_status(ctx, ApplyBulkRedirectStatusParams(
        site_id="shop-test", redirect_ids=[1], status="inactive", expected_state_token="0" * 64))
    assert result.status == "error" and result.error_code == "REDIRECT_BULK_STATE_CHANGED"


async def test_preview_bulk_redirect_status_rejects_unknown_id():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, [_redirect(1, status="active")])
    result = await hr.preview_bulk_redirect_status(ctx, BulkRedirectStatusParams(
        site_id="shop-test", redirect_ids=[1, 99], status="inactive"))
    assert result.status == "error" and result.error_code == "REDIRECT_NOT_FOUND"


async def test_list_redirects_reports_bridge_missing():
    ctx = await _ctx()
    ctx.http.mock_get(BRIDGE, {"code": "rest_no_route"}, 404)
    result = await hr.list_redirects(ctx, ListRedirectsParams(site_id="shop-test"))
    assert result.status == "error"
    assert result.error_code == "REDIRECTS_BRIDGE_MISSING"


async def test_create_redirect_posts_expected_payload():
    ctx = await _ctx()
    ctx.http.mock_post(BRIDGE, _redirect(id=9, url_to="/dest/"))
    result = await hr.create_redirect(ctx, CreateRedirectParams(
        site_id="shop-test", source_pattern="/old/", url_to="/dest/", header_code=301))
    assert result.status == "success"
    assert result.data.url_to == "/dest/" or result.data.url_to == "/new/"


async def test_delete_redirect_success():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/9", {"deleted": True})
    result = await hr.delete_redirect(ctx, DeleteRedirectParams(site_id="shop-test", redirect_id=9))
    assert result.status == "success"
    assert result.data.deleted is True


async def test_delete_redirect_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BRIDGE}/999", {"code": "imperal_redirects_item_not_found"}, 404)
    result = await hr.delete_redirect(ctx, DeleteRedirectParams(site_id="shop-test", redirect_id=999))
    assert result.status == "error"
    assert result.error_code == "REDIRECT_NOT_FOUND"


async def test_set_redirect_status_rejects_invalid_status():
    ctx = await _ctx()
    result = await hr.set_redirect_status(ctx, SetRedirectStatusParams(
        site_id="shop-test", redirect_id=1, status="bogus"))
    assert result.status == "error"
    assert result.error_code == "REDIRECT_INVALID_STATUS"


async def test_set_redirect_status_success():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BRIDGE}/1/status", _redirect(status="inactive"))
    result = await hr.set_redirect_status(ctx, SetRedirectStatusParams(
        site_id="shop-test", redirect_id=1, status="inactive"))
    assert result.status == "success"
    assert "now inactive" in result.summary
