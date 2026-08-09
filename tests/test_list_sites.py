from imperal_sdk.testing import MockContext
import app  # noqa: F401
import handlers_read as hr
import storage
from models import _NoParams


async def test_list_sites_returns_connected_sites():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "a", "status": "connected"})
    r = await hr.list_sites(ctx, _NoParams())
    assert r.status == "success"
    assert "X" in [e.title for e in r.data.items]


async def test_list_sites_empty():
    ctx = MockContext()
    r = await hr.list_sites(ctx, _NoParams())
    assert r.status == "success" and r.data.items == []


# ── IPC expose surface for Brand/Content Strategy Hub Quick Add ─────────────

async def test_expose_list_connected_sites_returns_plain_dicts():
    ctx = MockContext()
    await storage.save_site_record(
        ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
              "username": "a", "status": "connected"})
    result = await hr.expose_list_connected_sites(ctx)
    assert result == [{"site_id": "x-com", "name": "X", "url": "https://x.com",
                        "status": "connected"}]


async def test_expose_list_connected_sites_empty():
    ctx = MockContext()
    result = await hr.expose_list_connected_sites(ctx)
    assert result == []


async def test_expose_list_connected_sites_registered_on_ext():
    """Pins the IPC contract: app.ext must expose 'list_connected_sites' with
    action_type='read', matching what Brand/Content Strategy Hub call via
    ctx.extensions.call('wordpress-hub', 'list_connected_sites')."""
    exposed = app.ext.exposed
    assert "list_connected_sites" in exposed
    assert exposed["list_connected_sites"].action_type == "read"
