"""Native WordPress navigation menus: list menus, list/create/update/delete/
reorder menu items.

WordPress core has exposed /wp/v2/menus and /wp/v2/menu-items over REST
since 5.9 (part of the block-editor/FSE infrastructure, but present on
classic themes too) -- no Bridge or SSH needed. This closes the natural
next step after create_post: "the page exists, now put it in the menu."
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    CreateMenuItemParams,
    DeleteMenuItemParams,
    ListMenuItemsParams,
    Menu,
    MenuItem,
    MenuItemDeleteResult,
    ReorderMenuItemsParams,
    SiteIdParams,
    UpdateMenuItemParams,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post, wp_request


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    password = await storage.get_credential(ctx, site_id)
    if not password:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], password), None


def _failure(status_code, body):
    if status_code == 404:
        return ActionResult.error(
            "This site's WordPress version doesn't expose the menus REST API "
            "(needs WordPress 5.9+), or that menu/item does not exist.",
            retryable=False, code="WP_MENU_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage menus. Reconnect with an "
            "administrator or editor Application Password.",
            retryable=False, code="WP_MENU_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _menu_entity(item: dict) -> Menu:
    locations = item.get("locations", [])
    return Menu(
        id=str(item.get("id", "")), title=item.get("name", ""), kind="wp_menu",
        locations=", ".join(locations) if isinstance(locations, list) else "",
        item_count=int(item.get("count", 0) or 0),
    )


def _menu_item_entity(item: dict) -> MenuItem:
    title = item.get("title", "")
    if isinstance(title, dict):
        title = title.get("rendered", "")
    return MenuItem(
        id=str(item.get("id", "")), title=title or "", kind="wp_menu_item",
        menu_id=int(item.get("menus", 0) or 0),
        parent_id=int(item.get("parent", 0) or 0),
        url=item.get("url", "") or "",
        menu_order=int(item.get("menu_order", 0) or 0),
        object_type=item.get("type", "") or "",
    )


@chat.function(
    "list_menus",
    description="List navigation menus on a connected WordPress site (requires WordPress 5.9+).",
    action_type="read", data_model=sdl.EntityList[Menu])
async def list_menus(ctx, params: SiteIdParams) -> ActionResult:
    """List the site's nav_menu terms."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await wp_get(ctx, base_url, "/wp-json/wp/v2/menus",
                             username=username, app_password=password,
                             params={"per_page": 100})
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    items = response.body if isinstance(response.body, list) else []
    entities = [_menu_entity(item) for item in items]
    return ActionResult.success(sdl.EntityList[Menu](items=entities),
                                 summary=f"{len(entities)} menu(s)")


@chat.function(
    "list_menu_items",
    description="List the items inside one navigation menu, in their current order.",
    action_type="read", data_model=sdl.EntityList[MenuItem])
async def list_menu_items(ctx, params: ListMenuItemsParams) -> ActionResult:
    """List menu-item posts belonging to one menu."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await wp_get(ctx, base_url, "/wp-json/wp/v2/menu-items",
                             username=username, app_password=password,
                             params={"menus": params.menu_id, "per_page": 100, "orderby": "menu_order", "order": "asc"})
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    items = response.body if isinstance(response.body, list) else []
    entities = [_menu_item_entity(item) for item in items]
    return ActionResult.success(sdl.EntityList[MenuItem](items=entities),
                                 summary=f"{len(entities)} item(s) in menu {params.menu_id}")


@chat.function(
    "create_menu_item",
    description="Add a new link/item to an existing navigation menu.",
    action_type="write", data_model=MenuItem,
    effects=["wp.menu_item_create"], event="wordpress-hub.create_menu_item")
async def create_menu_item(ctx, params: CreateMenuItemParams) -> ActionResult:
    """Create one custom-link menu item under the given menu."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    payload: dict = {
        "title": params.title.strip(),
        "url": params.url.strip(),
        "menus": params.menu_id,
        "parent": params.parent_id,
        "status": "publish",
    }
    if params.menu_order is not None:
        payload["menu_order"] = params.menu_order
    response = await wp_post(ctx, base_url, "/wp-json/wp/v2/menu-items",
                              username=username, app_password=password, json=payload)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _menu_item_entity(response.body)
    return ActionResult.success(entity, summary=f"Added '{entity.title}' to menu {params.menu_id}",
                                 refresh_panels=["center"])


@chat.function(
    "update_menu_item",
    description="Update a menu item's title, URL, parent, or position.",
    action_type="write", data_model=MenuItem,
    effects=["wp.menu_item_update"], event="wordpress-hub.update_menu_item")
async def update_menu_item(ctx, params: UpdateMenuItemParams) -> ActionResult:
    """Update selected fields of an existing menu item."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    fields: dict = {}
    if params.title is not None:
        fields["title"] = params.title.strip()
    if params.url is not None:
        fields["url"] = params.url.strip()
    if params.parent_id is not None:
        fields["parent"] = params.parent_id
    if params.menu_order is not None:
        fields["menu_order"] = params.menu_order
    if not fields:
        return ActionResult.error("Nothing to update — pass at least one field.", retryable=False,
                                   code="WP_MENU_ITEM_NO_FIELDS")
    response = await wp_request(ctx, "post", base_url, f"/wp-json/wp/v2/menu-items/{params.menu_item_id}",
                                 username=username, app_password=password, json=fields)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _menu_item_entity(response.body)
    return ActionResult.success(entity, summary=f"Updated menu item '{entity.title}'",
                                 refresh_panels=["center"])


@chat.function(
    "delete_menu_item",
    description="Permanently remove one item from a navigation menu.",
    action_type="destructive", data_model=MenuItemDeleteResult,
    effects=["wp.menu_item_delete"], event="wordpress-hub.delete_menu_item")
async def delete_menu_item(ctx, params: DeleteMenuItemParams) -> ActionResult:
    """Delete a menu item (force=true — nav_menu_item posts have no trash)."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    response = await wp_request(ctx, "delete", base_url, f"/wp-json/wp/v2/menu-items/{params.menu_item_id}",
                                 username=username, app_password=password, params={"force": "true"})
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    return ActionResult.success(MenuItemDeleteResult(id=str(params.menu_item_id), title="", kind="wp_menu_item", deleted=True),
                                 summary="Menu item deleted", refresh_panels=["center"])


@chat.function(
    "reorder_menu_items",
    description=(
        "Reorder the top-level items of a menu by giving their ids in the desired "
        "top-to-bottom order. Pass ALL top-level item ids for this menu, not a subset."
    ),
    action_type="write", data_model=sdl.EntityList[MenuItem],
    effects=["wp.menu_item_reorder"], event="wordpress-hub.reorder_menu_items")
async def reorder_menu_items(ctx, params: ReorderMenuItemsParams) -> ActionResult:
    """Set menu_order on each item sequentially to match the given order."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, password = auth
    updated = []
    for position, item_id in enumerate(params.ordered_item_ids, start=1):
        response = await wp_request(ctx, "post", base_url, f"/wp-json/wp/v2/menu-items/{item_id}",
                                     username=username, app_password=password,
                                     json={"menu_order": position})
        if not 200 <= response.status_code < 300:
            return _failure(response.status_code, response.body)
        updated.append(_menu_item_entity(response.body))
    return ActionResult.success(sdl.EntityList[MenuItem](items=updated),
                                 summary=f"Reordered {len(updated)} item(s)", refresh_panels=["center"])
