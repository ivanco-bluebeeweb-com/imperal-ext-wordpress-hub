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


async def test_sidebar_hides_sync_button_when_sites_registry_not_installed():
    """No handler registered for sites-registry.ping -- MockExtensions.call
    raises, _sites_registry_installed must treat that as \"not installed\"
    and the Sync button must not render at all."""
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    assert "Sync sites to Sites Registry" not in str(node)


async def test_sidebar_shows_sync_button_when_sites_registry_installed():
    """A reachable sites-registry.ping IPC handler answering {"ok": True}
    is exactly what installing Sites Registry looks like from here -- the
    Sync button must render in that case."""
    ctx = MockContext()
    ctx.extensions.register("sites-registry", "ping", lambda **kw: {"ok": True})
    node = await panels.sidebar(ctx)
    assert "Sync sites to Sites Registry" in str(node)


async def test_sidebar_hides_sync_button_when_ping_answers_not_ok():
    """A reachable handler that answers ok=False must still hide the button --
    only an explicit ok=True counts as \"installed and usable\"."""
    ctx = MockContext()
    ctx.extensions.register("sites-registry", "ping", lambda **kw: {"ok": False})
    node = await panels.sidebar(ctx)
    assert "Sync sites to Sites Registry" not in str(node)


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


async def test_center_detail_shows_server_section_without_ssh_when_bridge_data_present():
    """Server info gathered via the Bridge (no SSH ever configured) must still
    render in the detail page — the Server section isn't gated on has_ssh."""
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com", "username": "admin",
        "status": "connected",
        "wp_version": "6.5.2", "php_version": "8.2.10",
        "pending_updates": 0, "server_source": "bridge",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "6.5.2" in s
    assert "8.2.10" in s
    assert "Add SSH" in s  # SSH button still offered, but not required for this data


async def test_center_detail_shows_bridge_outdated_warning_instead_of_no_data():
    """When get_server_info recorded bridge_outdated (plugin present but too
    old for /server/info), the detail page must say so with an update
    prompt -- not the generic 'No server data yet' message, which sends the
    user hunting for SSH on a site that already has the Bridge."""
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com", "username": "admin",
        "status": "connected", "bridge_outdated": "2.0.0",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "2.0.0" in s
    assert "update" in s.lower()
    assert "No server data yet" not in s


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


# ── category / tag management block ────────────────────────────────────────
# Requirement: "a UI I control that reaches every detail without talking in
# chat." Categories/tags were previously chat-only (create_post_category etc
# had no panel surface at all) even though the read-only taxonomy table
# already showed them. These tests pin the write side down as real ui.Form
# controls reachable straight from the Taxonomies tab.

async def _tax_panel_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "blog-com", "name": "Blog",
                                         "url": "https://blog.com", "username": "admin",
                                         "status": "connected"})
    await storage.set_credential(ctx, "blog-com", "pw")
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/types", {}, 200)
    ctx.http.mock_get(
        "https://blog.com/wp-json/wp/v2/taxonomies",
        {
            "category": {"name": "Categories", "rest_base": "categories"},
            "post_tag": {"name": "Tags", "rest_base": "tags"},
        },
        200,
    )
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/media", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/comments", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/users", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wc/v3/orders", {"code": "rest_no_route"}, 404)
    ctx.http.mock_get(
        "https://blog.com/wp-json/wp/v2/categories",
        [{"id": 5, "name": "Security News", "count": 3, "slug": "security-news"}],
        200,
    )
    ctx.http.mock_get(
        "https://blog.com/wp-json/wp/v2/tags",
        [{"id": 9, "name": "chisinau", "count": 1, "slug": "chisinau"}],
        200,
    )
    return ctx


async def test_taxonomies_tab_categories_has_create_rename_delete_forms():
    ctx = await _tax_panel_ctx()
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="tax", tax_tab="tax:category")
    s = str(node)
    assert "Security News" in s  # existing category still listed read-only
    assert "create_post_category" in s
    assert "update_post_category" in s
    assert "delete_post_category" in s


async def test_taxonomies_tab_tags_has_create_rename_delete_forms():
    ctx = await _tax_panel_ctx()
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="tax", tax_tab="tax:post_tag")
    s = str(node)
    assert "chisinau" in s
    assert "create_post_tag" in s
    assert "update_post_tag" in s
    assert "delete_post_tag" in s


async def test_taxonomy_manage_block_create_only_when_no_terms_yet():
    node = panels._taxonomy_manage_block([], "blog-com", "category")
    s = str(node)
    assert "create_post_category" in s
    # No terms yet -- nothing to rename or delete.
    assert "update_post_category" not in s
    assert "delete_post_category" not in s
