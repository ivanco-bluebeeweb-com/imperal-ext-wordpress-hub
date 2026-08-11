"""Contract tests for WordPress core Site Health diagnostics (Group R)."""
from imperal_sdk.testing import MockContext

import handlers_core_site_health as health
import storage
from models import SiteIdParams

BASE = "https://x.com"
ROOT = f"{BASE}/wp-json/wp-site-health/v1"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


def _test_body(test, status="good"):
    return {
        "test": test, "label": test.replace("-", " ").title(), "status": status,
        "badge": {"label": "Performance"}, "description": "A diagnostic.", "actions": "",
    }


async def test_core_site_health_requires_known_site():
    result = await health.run_core_site_health_tests(MockContext(), SiteIdParams(site_id="none"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_core_site_health_returns_available_results_and_honest_gaps():
    ctx = await _ctx()
    for name in health._TESTS:
        url = f"{ROOT}/tests/{name}"
        if name == "loopback-requests":
            ctx.http.mock_get(url, {"code": "rest_forbidden"}, 403)
        else:
            ctx.http.mock_get(url, _test_body(name), 200)
    result = await health.run_core_site_health_tests(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data.tests) == 4
    assert result.data.unavailable_tests == ["loopback-requests (administrator permission required)"]


async def test_core_site_health_directory_sizes_maps_admin_denial():
    ctx = await _ctx()
    ctx.http.mock_get(f"{ROOT}/directory-sizes", {"code": "rest_forbidden"}, 403)
    result = await health.get_core_site_health_directory_sizes(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SITE_HEALTH_FORBIDDEN"


async def test_core_site_health_directory_sizes_returns_raw_core_fact_shape():
    ctx = await _ctx()
    ctx.http.mock_get(f"{ROOT}/directory-sizes", {"wordpress_size": {"size": 1234}}, 200)
    result = await health.get_core_site_health_directory_sizes(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.sizes["wordpress_size"]["size"] == 1234
