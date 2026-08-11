"""Contract tests for WordPress native session hygiene (Group S)."""
from imperal_sdk.testing import MockContext

import handlers_sessions as sessions
import storage
from models import DestroySessionsParams, UserSessionsParams

BASE = "https://x.com"
PATH = f"{BASE}/wp-json/imperal/v1/users/12/sessions"


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_list_sessions_requires_known_site():
    result = await sessions.list_active_sessions(
        MockContext(), UserSessionsParams(site_id="none", user_id=12))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_list_sessions_returns_only_non_secret_metadata():
    ctx = await _ctx()
    ctx.http.mock_get(PATH, {"id": 12, "sessions": [{
        "login": 1700000000, "expiration": 1800000000,
        "ip": "203.0.113.4", "ua": "Browser/1",
    }]}, 200)
    result = await sessions.list_active_sessions(ctx, UserSessionsParams(site_id="x-com", user_id=12))
    assert result.status == "success"
    assert result.data.sessions[0].ip == "203.0.113.4"
    assert not hasattr(result.data.sessions[0], "token")


async def test_list_sessions_reports_outdated_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(PATH, {"code": "rest_no_route"}, 404)
    result = await sessions.list_active_sessions(ctx, UserSessionsParams(site_id="x-com", user_id=12))
    assert result.status == "error"
    assert result.error_code == "SESSIONS_BRIDGE_MISSING"


async def test_destroy_sessions_uses_delete_and_reports_completion():
    ctx = await _ctx()
    _mock_delete(ctx, PATH, {"id": 12, "destroyed": True}, 200)
    result = await sessions.destroy_user_sessions(
        ctx, DestroySessionsParams(site_id="x-com", user_id=12))
    assert result.status == "success"
    assert result.data.destroyed is True
