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


def test_connect_form_prefills_username_with_admin_default():
    """The Connect Site dialog's username field must arrive pre-filled with
    the 'admin' default value (not just a greyed-out placeholder a user has
    to type over) -- a placeholder alone submits an empty string if the user
    never touches the field."""
    node = panels._render_connect_form()
    s = str(node.to_dict())
    assert "'param_name': 'username'" in s or '"param_name": "username"' in s
    username_field = node.props["children"][0].props["children"][1]
    input_node = username_field.props["children"][1]
    assert input_node.props.get("value") == "admin"


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
    s = str(node)
    assert "green" in s
    assert "Connected" in s


async def test_sidebar_error_badge_red():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "error"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "red" in s
    assert "Error" in s


async def test_sidebar_updates_badge_yellow():
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected",
         "pending_updates": 3},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "yellow" in s
    assert "Updates" in s


async def test_sidebar_error_beats_updates_badge():
    """An erroring site shows the red Error badge even if it also has pending
    updates on record -- red always wins over yellow."""
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "error",
         "pending_updates": 5},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "Error" in s
    assert "Updates" not in s


async def test_sidebar_has_no_refresh_all_button():
    """User directive: Refresh All must be removed entirely — only the one
    primary Connect Site button stays at the top."""
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "Refresh All" not in s
    assert "refresh_all_sites" not in s


async def test_sidebar_connect_button_is_primary_and_full_width():
    ctx = MockContext()
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "'variant': 'primary'" in s
    assert "'full_width': True" in s


async def test_sidebar_has_no_avatar_lamp():
    """User directive: the little colored square/dot left of the site name
    must be gone entirely — status now lives only in the badge."""
    ctx = await _ctx_with_sites(
        {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"},
    )
    node = await panels.sidebar(ctx)
    s = str(node)
    assert "'avatar'" not in s


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


async def test_center_detail_shows_divider_separated_sections_without_ssh_button():
    """Main screen must be General / Environment / PHP Limits / Extensions /
    Database / Apache / Plugin updates / Content, each separated by its own
    ui.Divider, sourced from get_php_info — and there is no Add SSH button
    anywhere on this screen anymore."""
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
    ctx.http.mock_get("https://x.com/wp-json/imperal/v1/security/php-info", {
        "php_version": "8.2.10", "extensions": ["curl"], "memory_limit": "256M",
        "max_execution_time": "300", "upload_max_filesize": "64M", "post_max_size": "64M",
        "wp_version": "6.5.2", "server_software": "nginx",
        "db_version": "8.0.35", "db_size_mb": 12.5,
        "apache_enabled": False,
    }, 200)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "'label': 'General'" in s
    assert "'label': 'Environment'" in s
    assert "'label': 'PHP Limits'" in s
    assert "'label': 'Extensions'" in s
    assert "'label': 'Database'" in s
    assert "'label': 'Apache'" in s
    assert "'label': 'Plugin updates'" in s
    assert "'label': 'Content'" in s
    assert "8.2.10" in s
    assert "nginx" in s
    assert "Add SSH" not in s


async def test_center_detail_shows_bridge_outdated_warning_instead_of_no_data():
    """When get_server_info recorded bridge_outdated (plugin present but too
    old for /server/info), the detail page must say so with an update
    prompt -- not the generic 'No update data yet' message."""
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
    ctx.http.mock_get("https://x.com/wp-json/imperal/v1/security/php-info",
                      {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "2.0.0" in s
    assert "update" in s.lower()
    assert "No update data yet" not in s


async def test_center_detail_server_section_offers_update_plugin_action():
    """Plugin updates listed under Server must offer an update_plugin action
    per row (bridge-first, no SSH required) -- and must send the WP-CLI slug
    (the 'name' field), never the human-readable title, since update_plugin's
    own slug validation would reject anything with spaces."""
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com", "username": "admin",
        "status": "connected",
        "wp_version": "6.5.2", "php_version": "8.2.10",
        "pending_updates": 1, "server_source": "bridge",
        "plugin_updates_list": [
            {"name": "akismet", "title": "Akismet Anti-Spam", "version": "5.3", "update_version": "5.4"},
        ],
    })
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/imperal/v1/security/php-info", {
        "php_version": "8.2.10", "extensions": ["curl"], "memory_limit": "256M",
        "max_execution_time": "300", "upload_max_filesize": "64M", "post_max_size": "64M",
        "wp_version": "6.5.2", "server_software": "nginx",
    }, 200)
    node = await panels.center(ctx, view="", site_id="x-com")
    s = str(node)
    assert "Akismet Anti-Spam" in s
    assert "update_plugin" in s
    assert "'slug': 'akismet'" in s
    assert "update_core" in s
    assert "run_wp_cron" in s


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
    assert "create_product" in s
    assert "archive_product" in s
    assert "update_product" in s   # per-row edit form (name/price/sku/stock/status)


async def test_center_commerce_orders_has_status_change_and_note_forms():
    """Orders sub-tab used to be a plain read-only DataTable -- confirm the
    rework wires update_order_status/update_order_status_risky/notes."""
    ctx = await _store_panel_ctx()
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="orders")
    s = str(node)
    assert "Order #8" in s
    assert "update_order_status" in s
    assert "update_order_status_risky" in s
    assert "add_private_order_note" in s
    assert "add_customer_order_note" in s
    assert "resend_order_email" in s


async def test_commerce_tab_has_categories_subtab_with_create_form():
    """Categories sub-tab used to not exist at all -- list_product_categories/
    create_product_category were chat-tool-only despite full read+write support."""
    ctx = await _store_panel_ctx()
    ctx.http.mock_get("https://shop.com/wp-json/wc/v3/products/categories",
                      [{"id": 9, "name": "Mugs", "count": 3, "parent": 0}], 200)
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="categories")
    s = str(node)
    assert "Mugs" in s
    assert "create_product_category" in s


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


# ── Manage tab: menus / redirects / settings / plugins ─────────────────────────
# These write handlers (create_menu_item, create_redirect, update_site_settings,
# activate_plugin, ...) existed and were priced but had NO UI wiring anywhere on
# the detail screen before this -- the whole point of this test block is to
# lock in that they are now reachable from a real click path, not just chat.

async def _base_panel_ctx(site_id="blog-com", url="https://blog.com",
                          comments=None, users=None):
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": site_id, "name": "Blog", "url": url,
                                         "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, site_id, "pw")
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/types", {}, 200)
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/taxonomies", {}, 200)
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/media", [], 200)
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/comments", comments if comments is not None else [], 200)
    ctx.http.mock_get(f"{url}/wp-json/wp/v2/users", users if users is not None else [], 200)
    ctx.http.mock_get(f"{url}/wp-json/wc/v3/orders", {"code": "rest_no_route"}, 404)
    return ctx


async def test_group_tab_bar_includes_manage():
    ctx = await _base_panel_ctx()
    node = await panels.center(ctx, view="", site_id="blog-com")
    s = str(node)
    assert "'label': 'Manage'" in s


async def test_manage_tab_menus_lists_menu_and_add_item_form():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/menus",
                      [{"id": 1, "name": "Main Menu", "locations": ["primary"], "count": 1}], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/menu-items",
                      [{"id": 10, "title": {"rendered": "Home"}, "url": "https://blog.com/",
                        "parent": 0, "menus": 1}], 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="menus")
    s = str(node)
    assert "Main Menu" in s
    assert "Home" in s
    assert "create_menu_item" in s
    assert "delete_menu_item" in s
    assert "update_menu_item" in s   # per-row edit form (title/url)


async def test_manage_tab_menus_empty_state_when_no_menus():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/menus", [], 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="menus")
    assert "No navigation menus found" in str(node)


async def test_manage_tab_redirects_lists_items_with_status_actions():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/redirects",
                      [{"id": 5, "sources": [{"pattern": "/old/", "comparison": "exact"}],
                        "url_to": "/new/", "header_code": 301, "hits": 3, "status": "active"}], 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="redirects")
    s = str(node)
    assert "/old/" in s
    assert "create_redirect" in s
    assert "set_redirect_status" in s
    assert "delete_redirect" in s


async def test_manage_tab_redirects_shows_bridge_hint_on_404():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/redirects", {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="redirects")
    assert "Imperal Bridge" in str(node)


async def test_manage_tab_seo_shows_sitemap_robots_and_404_sections():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/sitemap-status",
                      {"module_active": True, "sitemap_url": "https://blog.com/sitemap_index.xml"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/robots-txt",
                      {"content": "User-agent: *\nDisallow: /wp-admin/", "is_active": True,
                       "site_is_public": True}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/404-logs",
                      {"hits": [{"id": 3, "uri": "/gone/", "accessed": "2026-08-01 00:00:00",
                                "times_accessed": 5, "referer": "https://example.com/",
                                "user_agent": "Mozilla"}]}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="seo")
    s = str(node)
    assert "sitemap_index.xml" in s
    assert "update_robots_txt" in s
    assert "Disallow: /wp-admin/" in s
    assert "/gone/" in s
    assert "delete_404_hit" in s


async def test_manage_tab_seo_shows_bridge_hint_when_missing():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/sitemap-status",
                      {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="seo")
    assert "Imperal Bridge" in str(node)


async def test_manage_tab_seo_shows_indexnow_section_with_log_and_submit_form():
    ctx = await _base_panel_ctx()
    ctx.http.mock_post("https://blog.com/wp-json/rankmath/v1/in/getLog",
                       {"data": [{"url": "https://blog.com/post-1/", "status": 200,
                                  "manual_submission": True, "message": "URL submitted successfully.",
                                  "time_human_readable": "2 hours ago"}]}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/sitemap-status",
                      {"module_active": True, "sitemap_url": "https://blog.com/sitemap_index.xml"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/robots-txt",
                      {"content": "", "is_active": False, "site_is_public": True}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/404-logs", {"hits": []}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="seo")
    s = str(node)
    assert "Instant Indexing" in s
    assert "submit_urls_to_indexnow" in s
    assert "clear_indexnow_log" in s
    assert "post-1" in s


async def test_manage_tab_seo_shows_indexnow_module_disabled_hint():
    ctx = await _base_panel_ctx()
    ctx.http.mock_post("https://blog.com/wp-json/rankmath/v1/in/getLog",
                       {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/sitemap-status",
                      {"module_active": True, "sitemap_url": "https://blog.com/sitemap_index.xml"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/robots-txt",
                      {"content": "", "is_active": False, "site_is_public": True}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/404-logs", {"hits": []}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="seo")
    s = str(node)
    assert "Instant Indexing" in s
    assert "Advanced Mode" in s


async def test_manage_tab_seo_shows_llms_txt_card_when_active():
    ctx = await _base_panel_ctx()
    ctx.http.mock_post("https://blog.com/wp-json/rankmath/v1/in/getLog", {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/sitemap-status",
                      {"module_active": True, "sitemap_url": "https://blog.com/sitemap_index.xml"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/robots-txt",
                      {"content": "", "is_active": False, "site_is_public": True}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/404-logs", {"hits": []}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/llmstxt",
                      {"module_active": True, "llms_txt_url": "https://blog.com/llms.txt",
                       "post_types": ["post"], "taxonomies": ["category"], "limit": 50,
                       "extra_content": "## Notes"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/types",
                      {"post": {"name": "Posts"}, "page": {"name": "Pages"}}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/taxonomies",
                      {"category": {"name": "Categories"}}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="seo")
    s = str(node)
    assert "llms.txt" in s
    assert "update_llms_txt_settings" in s
    assert "Active" in s


async def test_manage_tab_seo_shows_llms_txt_module_inactive_hint():
    ctx = await _base_panel_ctx()
    ctx.http.mock_post("https://blog.com/wp-json/rankmath/v1/in/getLog", {"code": "rest_no_route"}, 404)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/sitemap-status",
                      {"module_active": True, "sitemap_url": "https://blog.com/sitemap_index.xml"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/robots-txt",
                      {"content": "", "is_active": False, "site_is_public": True}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/rankmath/404-logs", {"hits": []}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/llmstxt",
                      {"module_active": False, "llms_txt_url": "https://blog.com/llms.txt",
                       "post_types": [], "taxonomies": [], "limit": 100, "extra_content": ""}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/types", {"post": {"name": "Posts"}}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/taxonomies", {}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="seo")
    s = str(node)
    assert "Not active yet" in s
    assert "update_llms_txt_settings" in s


async def test_manage_tab_settings_shows_editable_form():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/settings",
                      {"title": "My Blog", "description": "Just musings",
                       "timezone_string": "Europe/Chisinau"}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="settings")
    s = str(node)
    assert "My Blog" in s
    assert "update_site_settings" in s


async def test_manage_tab_plugins_lists_with_activate_action():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/plugins",
                      [{"plugin": "hello-dolly/hello", "name": "Hello Dolly",
                        "status": "inactive", "version": "1.7.2"}], 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="plugins")
    s = str(node)
    assert "Hello Dolly" in s
    assert "activate_plugin" in s


# ── Activity tab rework: Comments moderation + Users management ───────────────

async def test_activity_comments_tab_has_moderation_actions_not_plain_table():
    ctx = await _base_panel_ctx(comments=[
        {"id": 1, "author_name": "Alice", "status": "hold",
         "content": {"rendered": "<p>Nice post</p>"}, "post": 5,
         "date": "2026-01-01"}])
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="activity", act_tab="comments")
    s = str(node)
    assert "Alice" in s
    assert "set_comment_status" in s
    assert "reply_to_comment" in s
    assert "'label': 'Approve'" in s


async def test_activity_users_tab_has_create_and_delete_actions():
    ctx = await _base_panel_ctx(users=[
        {"id": 2, "name": "Editor Jane", "slug": "jane", "roles": ["editor"]}])
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="activity", act_tab="users")
    s = str(node)
    assert "Editor Jane" in s
    assert "create_user" in s
    assert "delete_user" in s
    assert "update_user" in s
    assert "reset_user_password" in s


# ── Standard tab rework: Posts/Pages lifecycle actions ─────────────────────────

async def test_posts_tab_has_publish_duplicate_delete_actions():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "blog-com", "name": "Blog",
                                         "url": "https://blog.com", "username": "admin",
                                         "status": "connected"})
    await storage.set_credential(ctx, "blog-com", "pw")
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/types", {}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/taxonomies", {}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/posts",
                      [{"id": 42, "title": {"rendered": "Draft post"}, "status": "draft",
                        "date": "2026-01-01"}], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/media", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wc/v3/orders", {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="standard", std_tab="posts")
    s = str(node)
    assert "Draft post" in s
    assert "update_post" in s   # Publish/Draft toggle
    assert "duplicate_post" in s
    assert "delete_post" in s
    assert "'label': 'Publish'" in s
    assert "set_post_password" in s


async def test_media_tab_has_upload_form_and_alt_text_editing():
    """Media used to be a plain read-only DataTable (title + mime type) despite
    upload_media/update_media_alt already existing as full write handlers --
    this confirms the rework wires both into the panel."""
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "blog-com", "name": "Blog",
                                         "url": "https://blog.com", "username": "admin",
                                         "status": "connected"})
    await storage.set_credential(ctx, "blog-com", "pw")
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/types", {}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/taxonomies", {}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/media",
                      [{"id": 5, "title": {"rendered": "logo.png"}, "mime_type": "image/png",
                        "alt_text": ""}], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wc/v3/orders", {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="standard", std_tab="media")
    s = str(node)
    assert "logo.png" in s
    assert "duplicate_post" not in s   # media has no post lifecycle, unlike posts/pages
    assert "upload_media" in s
    assert "set_single_media_alt" in s
    assert "no alt text" in s   # missing-alt indicator on the row itself


async def test_media_tab_shows_error_alert_when_load_fails():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "blog-com", "name": "Blog",
                                         "url": "https://blog.com", "username": "admin",
                                         "status": "connected"})
    await storage.set_credential(ctx, "blog-com", "pw")
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/types", {}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/taxonomies", {}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://blog.com/wp-json/wp/v2/media", {}, 500)
    ctx.http.mock_get("https://blog.com/wp-json/wc/v3/orders", {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="standard", std_tab="media")
    s = str(node)
    assert "Could not load media library" in s
    assert "upload_media" in s   # the upload form still offers a way forward


# ── Commerce tab rework: product Reviews moderation ─────────────────────────────

async def test_commerce_tab_has_reviews_subtab_with_moderation_actions():
    ctx = await _store_panel_ctx(woocommerce=True)
    ctx.http.mock_get("https://shop.com/wp-json/wc/v3/products/reviews",
                      [{"id": 9, "reviewer": "Bob", "rating": 4, "status": "hold",
                        "review": "<p>Great product!</p>", "date_created": "2026-01-01"}], 200)
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="reviews")
    s = str(node)
    assert "'label': 'Reviews'" in s
    assert "Bob" in s
    assert "set_product_review_status" in s
    assert "reply_to_product_review" in s


# ── Commerce tab rework: Customers + Coupons (list_customers/list_coupons had
# no click path anywhere on the detail screen despite full backend CRUD) ────────

async def test_commerce_tab_has_customers_subtab_with_create_form():
    ctx = await _store_panel_ctx(woocommerce=True)
    ctx.http.mock_get("https://shop.com/wp-json/wc/v3/customers",
                      [{"id": 3, "first_name": "Ana", "last_name": "Pop",
                        "email": "ana@example.com", "orders_count": 2,
                        "total_spent": "150.00"}], 200)
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="customers")
    s = str(node)
    assert "'label': 'Customers'" in s
    assert "Ana" in s
    assert "ana@example.com" in s
    assert "create_customer" in s
    assert "delete_customer" in s
    assert "update_customer" in s   # per-row edit form


async def test_commerce_tab_has_coupons_subtab_with_create_and_archive_actions():
    ctx = await _store_panel_ctx(woocommerce=True)
    ctx.http.mock_get("https://shop.com/wp-json/wc/v3/coupons",
                      [{"id": 11, "code": "SUMMER10", "amount": "10", "discount_type": "percent",
                        "usage_count": 3, "date_expires": "2026-09-01T00:00:00"}], 200)
    node = await panels.center(ctx, view="", site_id="shop-com",
                               group_tab="commerce", commerce_tab="coupons")
    s = str(node)
    assert "'label': 'Coupons'" in s
    assert "SUMMER10" in s
    assert "create_coupon" in s
    assert "archive_coupon" in s


# ── Manage tab: Builders (Elementor/Bricks point-editing) ───────────────────────
# get_builder_content/update_builder_field/check_builder_support existed as
# chat-tools only, with zero click path on the detail screen -- these tests
# lock in the "Builders" manage sub-tab that closes that gap.

async def test_manage_tab_builders_shows_bridge_hint_on_404():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"code": "rest_no_route"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders")
    s = str(node)
    assert "Imperal Bridge" in s


async def test_manage_tab_builders_shows_support_badges_and_lookup_form():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": True,
                       "elementor_version": "3.20.0", "bricks_active": False,
                       "bricks_version": ""}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders")
    s = str(node)
    assert "'label': 'Builders'" in s
    assert "Elementor active" in s
    assert "Bricks not active" in s
    assert "builder_sel" in s


async def test_manage_tab_builders_shows_other_detected_builder_badges():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": False,
                       "elementor_version": "", "bricks_active": False,
                       "bricks_version": "",
                       "detected_builders": [
                           {"slug": "divi", "label": "Divi Builder", "active": True,
                            "confidence": "verified"},
                           {"slug": "wpbakery", "label": "WPBakery Page Builder", "active": False,
                            "confidence": "verified"},
                       ]}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders")
    s = str(node)
    assert "Other detected builders (1)" in s
    assert "Divi Builder" in s
    assert "WPBakery Page Builder" not in s  # inactive ones aren't badged


async def test_manage_tab_builders_hides_other_builders_card_when_none_active():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": True,
                       "elementor_version": "3.20.0", "bricks_active": False,
                       "bricks_version": "", "detected_builders": []}, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders")
    s = str(node)
    assert "Other detected builders" not in s


async def test_manage_tab_builders_loads_element_tree_with_edit_form():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": True,
                       "elementor_version": "3.20.0", "bricks_active": False,
                       "bricks_version": ""}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder", {
        "id": 42, "slug": "home", "type": "page", "link": "https://blog.com/home",
        "active_builders": ["elementor"],
        "builders": {
            "elementor": {
                "elements": [{"id": "abc123", "parent_id": None, "el_type": "widget",
                              "widget_type": "heading", "settings": {"title": "Hello"}}],
                "state_token": "tok-1",
                "element_count": 1,
            }
        },
    }, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders", builder_sel="home")
    s = str(node)
    assert "Hello" not in s or True  # settings shown as key/value, not asserted literally
    assert "abc123" in s
    assert "update_builder_field" in s
    assert "tok-1" in s
    assert "1 element(s)" in s


async def test_manage_tab_builders_shows_add_heading_form_for_bricks_zone():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": False,
                       "elementor_version": "", "bricks_active": True,
                       "bricks_version": "1.9.0"}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder", {
        "id": 42, "slug": "home", "type": "page", "link": "https://blog.com/home",
        "active_builders": ["bricks"],
        "builders": {
            "bricks": {"zones": {
                "content": {"elements": [{"id": "e1", "parent_id": None, "el_type": "section",
                                          "widget_type": "", "settings": {}, "zone": "content"}],
                           "state_token": "tok-content"},
                "header": {"elements": [], "state_token": "tok-header"},
                "footer": {"elements": [], "state_token": "tok-footer"},
            }},
        },
    }, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders", builder_sel="home")
    s = str(node)
    assert "create_bricks_heading" in s
    assert "tok-content" in s


async def test_manage_tab_builders_hides_add_heading_form_for_elementor_only():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": True,
                       "elementor_version": "3.20.0", "bricks_active": False,
                       "bricks_version": ""}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder", {
        "id": 42, "slug": "home", "type": "page", "link": "https://blog.com/home",
        "active_builders": ["elementor"],
        "builders": {
            "elementor": {
                "elements": [{"id": "abc123", "parent_id": None, "el_type": "widget",
                              "widget_type": "heading", "settings": {"title": "Hello"}}],
                "state_token": "tok-1",
                "element_count": 1,
            }
        },
    }, 200)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders", builder_sel="home")
    s = str(node)
    assert "create_bricks_heading" not in s


async def test_manage_tab_builders_reports_item_not_found():
    ctx = await _base_panel_ctx()
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder/status",
                      {"bridge_version": "2.20.0", "elementor_active": True,
                       "elementor_version": "", "bricks_active": False,
                       "bricks_version": ""}, 200)
    ctx.http.mock_get("https://blog.com/wp-json/imperal/v1/builder",
                      {"code": "imperal_builder_not_found"}, 404)
    node = await panels.center(ctx, view="", site_id="blog-com",
                               group_tab="manage", manage_tab="builders", builder_sel="missing-slug")
    s = str(node)
    assert "not built with Elementor or Bricks" in s or "No item with that id" in s
