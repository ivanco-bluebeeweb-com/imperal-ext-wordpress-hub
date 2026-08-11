from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_multisite as hm
import storage
from models import SiteIdParams

BASE = "https://x.com"
SITES = "/wp-json/imperal/v1/network/sites"
PLUGINS = "/wp-json/imperal/v1/network/plugins"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x", "name": "X", "url": BASE, "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x", "pw")
    return ctx


async def test_list_network_sites_returns_core_network_rows():
    ctx = await _ctx()
    ctx.http.mock_get(BASE + SITES, {"sites": [{"blog_id": 1, "domain": "example.com", "path": "/", "site_url": "https://example.com", "public": True}]}, 200)
    result = await hm.list_network_sites(ctx, SiteIdParams(site_id="x"))
    assert result.status == "success"
    assert result.data.items[0].blog_id == 1
    assert result.data.items[0].site_url == "https://example.com"


async def test_network_operations_refuse_single_site():
    ctx = await _ctx()
    ctx.http.mock_get(BASE + PLUGINS, {"code": "imperal_network_not_multisite"}, 400)
    result = await hm.list_network_plugins(ctx, SiteIdParams(site_id="x"))
    assert result.status == "error"
    assert result.error_code == "NOT_MULTISITE"
