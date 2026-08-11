"""Contract tests for the fixed-source Imperal Bridge self-updater."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_maintenance as hm
import storage
from models import UpdateImperalBridgeParams

BASE = "https://x.com"
PATH = "/wp-json/imperal/v1/maintenance/update-imperal-bridge"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_update_imperal_bridge_requires_connected_site():
    result = await hm.update_imperal_bridge(
        MockContext(), UpdateImperalBridgeParams(site_id="ghost")
    )
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_update_imperal_bridge_uses_fixed_bridge_route():
    ctx = await _ctx()
    ctx.http.mock_post(BASE + PATH, {"updated": True, "version": "2.17.0"}, 200)

    result = await hm.update_imperal_bridge(ctx, UpdateImperalBridgeParams(site_id="x-com"))

    assert result.status == "success"
    assert result.data.updated is True
    assert result.data.version == "2.17.0"
    assert "2.17.0" in result.data.output


async def test_update_imperal_bridge_reports_one_time_manual_prerequisite():
    ctx = await _ctx()
    ctx.http.mock_post(BASE + PATH, {"code": "rest_no_route"}, 404)

    result = await hm.update_imperal_bridge(ctx, UpdateImperalBridgeParams(site_id="x-com"))

    assert result.status == "error"
    assert result.error_code == "IMPERAL_BRIDGE_SELF_UPDATE_UNAVAILABLE"
    assert "manually" in result.error.lower()
