"""Contract tests for native WordPress category/tag taxonomy management."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_taxonomy as ht
import storage
from models import (
    CreatePostCategoryParams,
    CreatePostTagParams,
    DeletePostCategoryParams,
    DeletePostTagParams,
    ListPostCategoriesParams,
    ListPostTagsParams,
    UpdatePostCategoryParams,
    UpdatePostTagParams,
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
    """No mock_delete helper exists on MockHTTP yet — append the DELETE tuple directly."""
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


def _category(cid=5, **over):
    data = {"id": cid, "name": "News", "description": "", "parent": 0, "count": 3, "slug": "news"}
    data.update(over)
    return data


def _tag(tid=8, **over):
    data = {"id": tid, "name": "Launch", "description": "", "count": 1, "slug": "launch"}
    data.update(over)
    return data


async def test_list_post_categories_maps_parent_and_count():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/categories", [_category(), _category(cid=6, parent=5, name="Sub")])
    result = await ht.list_post_categories(ctx, ListPostCategoriesParams(site_id="blog-test"))
    assert result.status == "success"
    items = result.data.items
    assert len(items) == 2
    assert items[0].parent_id == 0
    assert items[1].parent_id == 5
    assert items[1].taxonomy == "category"


async def test_create_post_category_with_parent():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/categories", _category(cid=9, parent=5, name="Sub"), 201)
    result = await ht.create_post_category(ctx, CreatePostCategoryParams(
        site_id="blog-test", name="Sub", parent_id=5))
    assert result.status == "success"
    assert result.data.parent_id == 5
    assert result.data.title == "Sub"


async def test_create_post_category_requires_name():
    ctx = await _ctx()
    try:
        CreatePostCategoryParams(site_id="blog-test", name="")
        assert False, "expected validation error for empty name"
    except Exception:
        pass


async def test_update_post_category_renames_and_reparents():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/categories/6", _category(cid=6, parent=5, name="Renamed"), 200)
    result = await ht.update_post_category(ctx, UpdatePostCategoryParams(
        site_id="blog-test", term_id=6, name="Renamed", parent_id=5))
    assert result.status == "success"
    assert result.data.title == "Renamed"
    assert result.data.parent_id == 5


async def test_update_post_category_requires_at_least_one_field():
    ctx = await _ctx()
    result = await ht.update_post_category(ctx, UpdatePostCategoryParams(site_id="blog-test", term_id=6))
    assert result.status == "error"


async def test_delete_post_category_success():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/categories/6", {"deleted": True, "previous": _category(cid=6)}, 200)
    result = await ht.delete_post_category(ctx, DeletePostCategoryParams(site_id="blog-test", term_id=6))
    assert result.status == "success"
    assert result.data.deleted is True


async def test_delete_post_category_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/categories/999", {"code": "rest_term_invalid"}, 404)
    result = await ht.delete_post_category(ctx, DeletePostCategoryParams(site_id="blog-test", term_id=999))
    assert result.status == "error"


async def test_list_post_tags():
    ctx = await _ctx()
    ctx.http.mock_get(f"{BASE}/tags", [_tag(), _tag(tid=9, name="Sale")])
    result = await ht.list_post_tags(ctx, ListPostTagsParams(site_id="blog-test"))
    assert result.status == "success"
    assert len(result.data.items) == 2
    assert result.data.items[0].taxonomy == "post_tag"


async def test_create_post_tag():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/tags", _tag(tid=11, name="Launch"), 201)
    result = await ht.create_post_tag(ctx, CreatePostTagParams(site_id="blog-test", name="Launch"))
    assert result.status == "success"
    assert result.data.title == "Launch"


async def test_update_post_tag_description():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/tags/8", _tag(description="new desc"), 200)
    result = await ht.update_post_tag(ctx, UpdatePostTagParams(
        site_id="blog-test", term_id=8, description="new desc"))
    assert result.status == "success"
    assert result.data.description == "new desc"


async def test_delete_post_tag_success():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/tags/8", {"deleted": True, "previous": _tag()}, 200)
    result = await ht.delete_post_tag(ctx, DeletePostTagParams(site_id="blog-test", term_id=8))
    assert result.status == "success"
    assert result.data.deleted is True


async def test_create_post_category_site_not_connected():
    ctx = MockContext()
    result = await ht.create_post_category(ctx, CreatePostCategoryParams(site_id="ghost", name="X"))
    assert result.status == "error"
