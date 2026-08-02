from imperal_sdk.testing import MockContext
import app  # noqa: F401 — registers ext/chat
import panels
import storage


async def _ctx_with_sites(*site_records):
    ctx = MockContext()
    for r in site_records:
        await storage.save_site_record(ctx, r)
    return ctx


# ── sidebar ───────────────────────────────────────────────────────────────────

async def test_sidebar_empty_state():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "Connect Site" in s
    assert "Divider" in s
    assert "No sites" in s


async def test_sidebar_renders_site_list():
    ctx = await _ctx_with_sites(
        {"id": "a-com", "name": "A", "url": "https://a.com", "status": "connected"},
        {"id": "b-com", "name": "B", "url": "https://b.com", "status": "error"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "a.com" in s
    assert "b.com" in s
    assert "List" in s


async def test_sidebar_connect_button_at_top():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert s.index("Connect Site") < s.index("Divider")


async def test_sidebar_divider_present():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    assert "Divider" in str(node)


async def test_sidebar_connect_button_calls_center_with_connect_view():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "__panel__center" in s
    assert "connect" in s


async def test_sidebar_site_click_calls_center_with_site_id():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "__panel__center" in s
    assert "x-com" in s


async def test_sidebar_auto_action_set_when_sites_exist():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    assert hasattr(node, "props") and "auto_action" in node.props


async def test_sidebar_no_auto_action_when_active_site():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx, active_site_id="x-com")
    assert not (hasattr(node, "props") and "auto_action" in node.props)


async def test_sidebar_no_auto_action_when_no_sites():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    assert not (hasattr(node, "props") and "auto_action" in node.props)


async def test_sidebar_item_has_refresh_and_remove_actions():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "refresh_site" in s
    assert "forget_site" in s


async def test_sidebar_shows_domain_not_name():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "admin", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "x.com" in s


async def test_sidebar_connected_badge_green():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    assert "green" in str(node)


async def test_sidebar_error_badge_red():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "error"},
    )
    node = await panels.sidebar(ctx)
    assert "red" in str(node)


# ── center panel ──────────────────────────────────────────────────────────────

async def test_center_empty_when_no_args():
    ctx = MockContext()
    node = await panels.center(ctx)
    assert node is not None
    assert "Empty" in str(node) or "Select" in str(node)


async def test_center_shows_connect_form_when_view_connect():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="")
    s = str(node)
    assert "app_password" in s and "'type': 'password'" in s


async def test_center_connect_form_has_cancel_pointing_to_center():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="")
    s = str(node)
    assert "Cancel" in s
    assert "__panel__center" in s


async def test_center_connect_form_has_url_and_username():
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="")
    s = str(node)
    assert "url" in s
    assert "username" in s


async def test_center_shows_detail_when_site_id():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X",
                                         "url": "https://x.com", "username": "admin",
                                         "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts",
                      [{"id": 1, "title": {"rendered": "Hello"}, "status": "publish",
                        "date": "2026-06-01T00:00:00"}], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "x.com" in s
    assert "Stats" in s
    assert "Hello" in s
    assert "Standard" in s and "Activity" in s  # group tab buttons


async def _store_panel_ctx(woocommerce=True):
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "shop-com", "name": "Shop",
                                         "url": "https://shop.com", "username": "manager",
                                         "status": "connected"})
    await storage.set_credential(ctx, "shop-com", "pw")
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/types", {}, 200)
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/taxonomies", {}, 200)
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/media", [], 200)
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/comments", [], 200)
    ctx.http.mock_get("https://shop.com/wp-json/wp/v2/users", [], 200)
    if woocommerce:
        ctx.http.mock_get("https://shop.com/wp-json/wc/v3/orders",
                          [{"id": 8, "number": "1008", "status": "processing",
                            "total": "49.00", "currency": "USD",
                            "date_created": "2026-08-01T10:00:00"}], 200)
    else:
        ctx.http.mock_get("https://shop.com/wp-json/wc/v3/orders",
                          {"code": "rest_no_route"}, 404)
    return ctx


async def test_center_store_has_separate_commerce_group():
    ctx = await _store_panel_ctx()
    node = await panels.center(ctx, view="", site_id="shop-com")
    s = str(node)
    assert "Commerce" in s
    assert "Orders" not in s  # orders no longer leak into Activity


async def test_center_non_store_hides_commerce_group():
    ctx = await _store_panel_ctx(woocommerce=False)
    node = await panels.center(ctx, view="", site_id="shop-com")
    assert "Commerce" not in str(node)


async def test_center_commerce_overview_renders_store_stats():
    ctx = await _store_panel_ctx()
    ctx.http.mock_get("https://shop.com/wp-json/wc/v3/reports/sales",
                      [{"total_orders": 7, "net_sales": "350.00",
                        "average_sales": "50.00", "total_refunds": "10.00",
                        "currency": "USD"}], 200)
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="overview")
    s = str(node)
    assert "Net sales" in s and "350.00 USD" in s
    assert "read-only" in s


async def test_center_commerce_products_renders_stock_table():
    ctx = await _store_panel_ctx()
    ctx.http.mock_get("https://shop.com/wp-json/wc/v3/products",
                      [{"id": 3, "name": "Blue mug", "sku": "MUG-B",
                        "price": "20.00", "stock_status": "instock",
                        "stock_quantity": 4}], 200)
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="products")
    s = str(node)
    assert "Blue mug" in s and "MUG-B" in s and "instock" in s


async def test_center_detail_shows_alert_on_missing_credential():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X",
                                         "url": "https://x.com", "username": "admin",
                                         "status": "connected"})
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "Alert" in s or "credential" in s.lower()


async def test_center_connect_view_overrides_site_id():
    """view=connect takes priority even if site_id is set (accumulated params scenario)."""
    ctx = MockContext()
    node = await panels.center(ctx, view="connect", site_id="x-com")
    s = str(node)
    assert "app_password" in s
