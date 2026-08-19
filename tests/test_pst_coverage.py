"""PST (Plausible Scenario Testing) coverage pass — 2026-08-19.

Targets the 9 @chat.function tools that a systematic name-grep across the
whole test suite showed were never called directly by any existing test:
add_ssh, remove_ssh, create_network_site, refresh_all_sites, list_scheduled,
list_users, list_custom_posts, list_wp_abilities, update_order_status_risky.

Each scenario below actually calls the real handler through MockContext —
never asserts against mocked-out internals only.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_connect as hc
import handlers_multisite as hm
import handlers_read as hr
import handlers_rest_api as hra
import handlers_woocommerce_operations as ho
import storage
from models import (
    AddSSHParams,
    CreateNetworkSiteParams,
    ListContentParams,
    ListCustomPostsParams,
    SiteIdParams,
    UpdateOrderStatusParams,
)

BASE = "https://x.com"


async def _connected_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


# ─────────── add_ssh / remove_ssh ───────────

async def test_add_ssh_succeeds_and_stores_credential(monkeypatch):
    ctx = await _connected_ctx()

    async def fake_test_connection(cred):
        return True, "6.6.1"

    monkeypatch.setattr(hc.wp_cli, "test_connection", fake_test_connection)
    result = await hc.add_ssh(ctx, AddSSHParams(
        site_id="x-com", ssh_host="1.2.3.4", ssh_user="deploy",
        wp_path="/var/www/html", ssh_key="-----BEGIN KEY-----"))
    assert result.status == "success"
    assert "6.6.1" in result.summary
    cred = await storage.get_ssh_cred(ctx, "x-com")
    assert cred["host"] == "1.2.3.4" and cred["key"] == "-----BEGIN KEY-----"
    record = await storage.get_site_record(ctx, "x-com")
    assert record["ssh_host"] == "1.2.3.4"


async def test_add_ssh_rejects_missing_key_and_password():
    ctx = await _connected_ctx()
    result = await hc.add_ssh(ctx, AddSSHParams(
        site_id="x-com", ssh_host="1.2.3.4", ssh_user="deploy", wp_path="/var/www/html"))
    assert result.status == "error"
    assert await storage.get_ssh_cred(ctx, "x-com") is None


async def test_add_ssh_surfaces_failed_connection_without_storing_credential():
    ctx = await _connected_ctx()

    async def fake_test_connection(cred):
        return False, "Connection refused"

    import handlers_connect as hc2
    hc2.wp_cli.test_connection = fake_test_connection
    try:
        result = await hc2.add_ssh(ctx, AddSSHParams(
            site_id="x-com", ssh_host="1.2.3.4", ssh_user="deploy",
            wp_path="/var/www/html", ssh_key="key-data"))
        assert result.status == "error"
        assert "Connection refused" in result.error
        assert await storage.get_ssh_cred(ctx, "x-com") is None
    finally:
        # restore the real implementation for any test that runs after this one
        import importlib
        import wp_cli as real_wp_cli
        importlib.reload(real_wp_cli)
        hc2.wp_cli.test_connection = real_wp_cli.test_connection


async def test_add_ssh_falls_back_to_pending_site_when_site_id_omitted(monkeypatch):
    ctx = await _connected_ctx()
    await storage.set_pending_ssh_site(ctx, "x-com")

    async def fake_test_connection(cred):
        return True, "6.6.1"

    monkeypatch.setattr(hc.wp_cli, "test_connection", fake_test_connection)
    result = await hc.add_ssh(ctx, AddSSHParams(
        ssh_host="1.2.3.4", ssh_user="deploy", wp_path="/var/www/html", ssh_key="key-data"))
    assert result.status == "success"
    assert result.data.id == "x-com"


async def test_add_ssh_errors_when_no_site_can_be_determined():
    ctx = MockContext()
    result = await hc.add_ssh(ctx, AddSSHParams(
        ssh_host="1.2.3.4", ssh_user="deploy", wp_path="/var/www/html", ssh_key="key-data"))
    assert result.status == "error"


async def test_remove_ssh_deletes_credential_and_derived_fields():
    ctx = await _connected_ctx()
    await storage.set_ssh_cred(ctx, "x-com", {"host": "1.2.3.4", "key": "k"})
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE, "username": "admin",
        "status": "connected", "ssh_host": "1.2.3.4", "wp_version": "6.6.1",
    })
    result = await hc.remove_ssh(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert await storage.get_ssh_cred(ctx, "x-com") is None
    record = await storage.get_site_record(ctx, "x-com")
    # storage.save_site_record() goes through store.update() which is PATCH
    # semantics only (no key-deletion primitive on the real platform store),
    # so the derived fields must be explicitly cleared to empty rather than
    # simply absent from the dict -- this is what the real bug fix produces.
    assert record["ssh_host"] == "" and record["wp_version"] == ""


# ─────────── create_network_site ───────────

async def test_create_network_site_succeeds():
    ctx = await _connected_ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/network/sites", {
        "blog_id": 5, "domain": "shop.x.com", "path": "/", "site_url": "https://shop.x.com",
    }, 200)
    result = await hm.create_network_site(ctx, CreateNetworkSiteParams(
        site_id="x-com", domain="shop.x.com", path="/", title="Shop", owner_email="a@x.com"))
    assert result.status == "success"
    assert result.data.blog_id == 5
    assert result.data.site_url == "https://shop.x.com"


async def test_create_network_site_rejects_non_multisite():
    ctx = await _connected_ctx()
    ctx.http.mock_post(f"{BASE}/wp-json/imperal/v1/network/sites",
                        {"code": "imperal_network_not_multisite"}, 400)
    result = await hm.create_network_site(ctx, CreateNetworkSiteParams(
        site_id="x-com", domain="shop.x.com", path="/", title="Shop", owner_email="a@x.com"))
    assert result.status == "error"


async def test_create_network_site_unreachable_site_is_reported_not_faked():
    ctx = await _connected_ctx()
    # No mock registered -> MockContext http returns 404 by default, not a crash.
    result = await hm.create_network_site(ctx, CreateNetworkSiteParams(
        site_id="x-com", domain="shop.x.com", path="/", title="Shop", owner_email="a@x.com"))
    assert result.status == "error"


# ─────────── refresh_all_sites ───────────

async def test_refresh_all_sites_reports_mixed_results():
    ctx = await _connected_ctx()
    await storage.save_site_record(ctx, {
        "id": "y-com", "name": "Y", "url": "https://y.com", "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "y-com", "pw")
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://y.com/wp-json/wp/v2/users/me", {"code": "rest_forbidden"}, 401)
    result = await hr.refresh_all_sites(ctx, hr._NoParams())
    assert result.status == "success"
    assert "1/2" in result.data.title
    assert (await storage.get_site_record(ctx, "x-com"))["status"] == "connected"
    assert (await storage.get_site_record(ctx, "y-com"))["status"] == "error"


async def test_refresh_all_sites_with_no_connected_sites_errors():
    ctx = MockContext()
    result = await hr.refresh_all_sites(ctx, hr._NoParams())
    assert result.status == "error"


# ─────────── list_scheduled / list_users / list_custom_posts ───────────

async def test_list_scheduled_maps_future_posts():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/posts",
                      [{"id": 7, "title": {"rendered": "Launch"}, "link": f"{BASE}/launch",
                        "date": "2026-09-01T09:00:00"}], 200)
    result = await hr.list_scheduled(ctx, ListContentParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.items[0].status == "scheduled"
    assert result.data.items[0].title == "Launch"


async def test_list_scheduled_unknown_site_errors():
    ctx = await _connected_ctx()
    result = await hr.list_scheduled(ctx, ListContentParams(site_id="missing"))
    assert result.status == "error"


async def test_list_users_maps_rest_payload():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users",
                      [{"id": 3, "name": "Ada Lovelace", "slug": "ada", "email": "ada@x.com",
                        "roles": ["administrator"], "registered_date": "2026-01-01T00:00:00"}], 200)
    result = await hr.list_users(ctx, ListContentParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data.items) == 1


async def test_list_users_http_error_maps_to_error():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/users", {"code": "rest_forbidden"}, 403)
    result = await hr.list_users(ctx, ListContentParams(site_id="x-com"))
    assert result.status == "error"


async def test_list_custom_posts_maps_cpt_items_with_kind_prefix():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/products",
                      [{"id": 11, "title": {"rendered": "Widget"}, "status": "publish",
                        "link": f"{BASE}/product/widget", "date": "2026-06-01T00:00:00"}], 200)
    result = await hr.list_custom_posts(ctx, ListCustomPostsParams(site_id="x-com", post_type="products"))
    assert result.status == "success"
    assert result.data.items[0].kind == "wp_cpt_products"
    assert result.data.items[0].title == "Widget"


async def test_list_custom_posts_unknown_post_type_route_errors():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp/v2/nope", {"code": "rest_no_route"}, 404)
    result = await hr.list_custom_posts(ctx, ListCustomPostsParams(site_id="x-com", post_type="nope"))
    assert result.status == "error"


# ─────────── list_wp_abilities ───────────

async def test_list_wp_abilities_paginates_and_stops_on_short_page():
    ctx = await _connected_ctx()
    page1 = [{"id": f"plugin/ability-{i}", "label": f"Ability {i}", "description": ""} for i in range(100)]
    page2 = [{"id": "plugin/ability-100", "label": "Ability 100", "description": ""}]
    ctx.http.mock_get(f"{BASE}/wp-json/wp-abilities/v1/abilities?per_page=100&page=1", page1, 200)
    ctx.http.mock_get(f"{BASE}/wp-json/wp-abilities/v1/abilities?per_page=100&page=2", page2, 200)
    result = await hra.list_wp_abilities(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert len(result.data.items) == 101


async def test_list_wp_abilities_empty_list_means_no_plugin_registered_yet():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp-abilities/v1/abilities?per_page=100&page=1", [], 200)
    result = await hra.list_wp_abilities(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.items == []


async def test_list_wp_abilities_route_missing_is_reported_as_error():
    ctx = await _connected_ctx()
    ctx.http.mock_get(f"{BASE}/wp-json/wp-abilities/v1/abilities?per_page=100&page=1",
                      {"code": "rest_no_route"}, 404)
    result = await hra.list_wp_abilities(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"


# ─────────── update_order_status_risky ───────────

SHOP_BASE = "https://shop.test/wp-json/wc/v3"


async def _shop_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "shop-test", "name": "Shop", "url": "https://shop.test",
        "username": "manager", "status": "connected",
    })
    await storage.set_credential(ctx, "shop-test", "pw")
    return ctx


def _order(status="processing", oid=12):
    return {
        "id": oid, "number": str(oid), "status": status,
        "currency": "USD", "total": "25.00", "date_created": "2026-08-02T12:00:00",
        "billing": {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
        "line_items": [{"name": "Mug", "quantity": 1, "subtotal": "25.00"}],
    }


async def test_update_order_status_risky_allows_cancelled():
    ctx = await _shop_ctx()
    ctx.http.mock_get(f"{SHOP_BASE}/orders/12", _order("processing"), 200)
    ctx.http.mock_post(f"{SHOP_BASE}/orders/12", _order("cancelled"), 200)
    result = await ho.update_order_status_risky(ctx, UpdateOrderStatusParams(
        site_id="shop-test", order_id=12, status="cancelled"))
    assert result.status == "success"
    assert result.data.status == "cancelled"


async def test_update_order_status_risky_rejects_routine_status():
    """update_order_status_risky must refuse a routine status -- the whole point
    of splitting it from update_order_status is that 'processing' etc. must go
    through the non-gated path, not this one."""
    ctx = await _shop_ctx()
    result = await ho.update_order_status_risky(ctx, UpdateOrderStatusParams(
        site_id="shop-test", order_id=12, status="processing"))
    assert result.status == "error"


async def test_update_order_status_risky_rejects_unknown_status():
    ctx = await _shop_ctx()
    result = await ho.update_order_status_risky(ctx, UpdateOrderStatusParams(
        site_id="shop-test", order_id=12, status="deleted"))
    assert result.status == "error"
