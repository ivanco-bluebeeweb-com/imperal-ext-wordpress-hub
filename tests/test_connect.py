from imperal_sdk.testing import MockContext
import handlers_connect as hc
import storage
from models import ConnectSiteParams, _NoParams


async def _ctx():
    ctx = MockContext()
    return ctx


async def test_connect_rejects_non_https():
    ctx = await _ctx()
    r = await hc.connect_site(ctx, ConnectSiteParams(url="http://x.com", username="a", app_password="p"))
    assert r.status != "success"
    assert await storage.get_site_record(ctx, "x-com") is None


async def test_connect_success_stores_site_and_credential():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    r = await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="pw"))
    assert r.status == "success" and r.data.id == "x-com"
    assert (await storage.get_site_record(ctx, "x-com"))["status"] == "connected"
    assert await storage.get_credential(ctx, "x-com") == "pw"


async def test_connect_bad_credentials_returns_error_and_stores_nothing():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {}, 401)
    r = await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="bad"))
    assert r.status != "success"
    assert await storage.get_site_record(ctx, "x-com") is None
    assert await storage.get_credential(ctx, "x-com") is None


async def test_connect_site_ipc_mirrors_connect_site_and_stores_the_same_record():
    """Sites Registry calls this exposed method with the same three fields as
    the connect_site chat tool -- it must produce an identical connected
    site record, not a parallel/divergent one."""
    ctx = await _ctx()
    ctx.http.mock_get("https://y.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    result = await hc.expose_connect_site_ipc(ctx, url="https://y.com", username="admin", app_password="pw")
    assert result["ok"] is True
    assert result["site_id"] == "y-com"
    assert (await storage.get_site_record(ctx, "y-com"))["status"] == "connected"
    assert await storage.get_credential(ctx, "y-com") == "pw"


async def test_connect_site_ipc_bad_credentials_returns_error_dict():
    ctx = await _ctx()
    ctx.http.mock_get("https://y.com/wp-json/wp/v2/users/me", {}, 401)
    result = await hc.expose_connect_site_ipc(ctx, url="https://y.com", username="admin", app_password="bad")
    assert result["ok"] is False
    assert "error" in result
    assert await storage.get_site_record(ctx, "y-com") is None


async def test_sync_sites_to_registry_pushes_each_connected_site_via_upsert():
    """The button in WP Hub's sidebar reads OUR own connected sites locally
    (no IPC needed for that -- it's our own storage) and pushes each one via
    the already-proven single-hop upsert_site IPC surface -- the exact same
    path a normal connect_site call already uses successfully."""
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="pw"))

    calls = []

    async def fake_upsert(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "site_id": "reg-1"}

    ctx.extensions.register("sites-registry", "upsert_site", fake_upsert)
    r = await hc.sync_sites_to_registry(ctx, _NoParams())
    assert r.status == "success"
    assert len(calls) == 1
    assert calls[0]["domain"] == "x.com"
    assert calls[0]["platform"] == "wordpress"
    assert "1" in r.summary


async def test_sync_sites_to_registry_surfaces_ipc_failure():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="pw"))

    async def fake_upsert(**kwargs):
        raise RuntimeError("sites-registry not installed")

    ctx.extensions.register("sites-registry", "upsert_site", fake_upsert)
    r = await hc.sync_sites_to_registry(ctx, _NoParams())
    assert r.status != "success"


async def test_sync_sites_to_registry_with_no_connected_sites_reports_zero():
    ctx = await _ctx()
    r = await hc.sync_sites_to_registry(ctx, _NoParams())
    assert r.status == "success"
    assert "0" in r.summary
