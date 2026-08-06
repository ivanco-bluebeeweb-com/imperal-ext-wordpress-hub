from imperal_sdk.testing import MockContext
import handlers_connect as hc
import storage
from models import ConnectSiteParams


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
