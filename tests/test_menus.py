"""Contract tests for native WordPress navigation menu management."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_menus as hm
import storage
from models import (
    ApplyBulkMenuOrderParams,
    BulkMenuOrderResult,
    CreateMenuItemParams,
    DeleteMenuItemParams,
    ListMenuItemsParams,
    ReorderMenuItemsParams,
    SiteIdParams,
    UpdateMenuItemParams,
)

BASE = "https://blog.test/wp-json/wp/v2"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "editor", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


def _menu(mid=3, **over):
    data = {"id": mid, "name": "Main Menu", "locations": ["primary"], "count": 2}
    data.update(over)
    return data


def _menu_item(iid=10, **over):
    data = {
        "id": iid, "title": {"rendered": "Home"}, "menus": 3, "parent": 0,
        "url": "https://blog.test/", "menu_order": 1, "type": "custom",
    }
    data.update(over)
    return data


async def test_list_menus_maps_locations_and_count():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/menus", [_menu()])
    result = await hm.list_menus(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "success"
    assert result.data.items[0].locations == "primary"
    assert result.data.items[0].item_count == 2


async def test_list_menus_reports_missing_rest_route_on_old_wordpress():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/menus", {"code": "rest_no_route"}, 404)
    result = await hm.list_menus(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "WP_MENU_NOT_FOUND"


async def test_list_menu_items_orders_by_menu_order():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/menu-items", [_menu_item(), _menu_item(iid=11, menu_order=2, title={"rendered": "About"})])
    result = await hm.list_menu_items(ctx, ListMenuItemsParams(site_id="blog-test", menu_id=3))
    assert result.status == "success"
    assert [i.title for i in result.data.items] == ["Home", "About"]


async def test_create_menu_item_posts_custom_link():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/menu-items", _menu_item(iid=12, title={"rendered": "Contact"}), 201)
    result = await hm.create_menu_item(ctx, CreateMenuItemParams(
        site_id="blog-test", menu_id=3, title="Contact", url="https://blog.test/contact"))
    assert result.status == "success"
    assert result.data.title == "Contact"


async def test_update_menu_item_requires_at_least_one_field():
    ctx = await _ctx()
    result = await hm.update_menu_item(ctx, UpdateMenuItemParams(site_id="blog-test", menu_item_id=10))
    assert result.status == "error"
    assert result.error_code == "WP_MENU_ITEM_NO_FIELDS"


async def test_update_menu_item_sends_only_given_fields():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/menu-items/10", _menu_item(title={"rendered": "New Title"}))
    result = await hm.update_menu_item(ctx, UpdateMenuItemParams(site_id="blog-test", menu_item_id=10, title="New Title"))
    assert result.status == "success"
    assert result.data.title == "New Title"


async def test_delete_menu_item_forces_permanent_removal():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/menu-items/10", {"deleted": True})
    result = await hm.delete_menu_item(ctx, DeleteMenuItemParams(site_id="blog-test", menu_item_id=10))
    assert result.status == "success"
    assert result.data.deleted is True


async def test_preview_and_apply_bulk_menu_order():
    ctx = await _ctx()
    items = [_menu_item(10, menu_order=1), _menu_item(11, menu_order=2, title={"rendered": "About"})]
    ctx.http.mock_get(f"{BASE}/menu-items", items)
    preview = await hm.preview_bulk_menu_order(ctx, ReorderMenuItemsParams(
        site_id="blog-test", menu_id=3, ordered_item_ids=[11, 10]))
    assert preview.status == "success" and preview.data.preview is True

    ctx.http.mock_get(f"{BASE}/menu-items", items)
    ctx.http.mock_post(f"{BASE}/menu-items/11", _menu_item(11, menu_order=1, title={"rendered": "About"}))
    ctx.http.mock_post(f"{BASE}/menu-items/10", _menu_item(10, menu_order=2))
    result = await hm.apply_bulk_menu_order(ctx, ApplyBulkMenuOrderParams(
        site_id="blog-test", menu_id=3, ordered_item_ids=[11, 10],
        expected_state_token=preview.data.state_token))
    assert result.status == "success" and result.data.updated == 2


async def test_apply_bulk_menu_order_refuses_stale_token():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/menu-items", [_menu_item(10)])
    result = await hm.apply_bulk_menu_order(ctx, ApplyBulkMenuOrderParams(
        site_id="blog-test", menu_id=3, ordered_item_ids=[10], expected_state_token="0" * 64))
    assert result.status == "error" and result.error_code == "WP_MENU_BULK_STATE_CHANGED"


async def test_reorder_menu_items_sets_sequential_menu_order():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/menu-items/11", _menu_item(iid=11, menu_order=1, title={"rendered": "About"}))
    ctx.http.mock_post(f"{BASE}/menu-items/10", _menu_item(iid=10, menu_order=2, title={"rendered": "Home"}))
    result = await hm.reorder_menu_items(ctx, ReorderMenuItemsParams(
        site_id="blog-test", menu_id=3, ordered_item_ids=[11, 10]))
    assert result.status == "success"
    assert len(result.data.items) == 2


async def test_menu_action_reports_forbidden_on_403():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/menus", {"code": "rest_forbidden"}, 403)
    result = await hm.list_menus(ctx, SiteIdParams(site_id="blog-test"))
    assert result.status == "error"
    assert result.error_code == "WP_MENU_FORBIDDEN"
