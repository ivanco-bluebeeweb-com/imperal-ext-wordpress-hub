"""Contract tests for native WordPress user management (create/update/delete)."""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_users as hu
import storage
from models import CreateUserParams, DeleteUserParams, PasswordResetParams, UpdateUserParams

BASE = "https://blog.test/wp-json/wp/v2"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "blog-test", "name": "Blog", "url": "https://blog.test",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "blog-test", "pw")
    return ctx


def _mock_delete(ctx, url_pattern, response, status=200):
    """No mock_delete helper exists on MockHTTP yet — append the DELETE tuple directly."""
    ctx.http._mocks.append(("DELETE", url_pattern, response, status, {}))


def _user(uid=12, **over):
    data = {"id": uid, "name": "Jane Doe", "roles": ["author"], "registered_date": "2026-01-01T00:00:00"}
    data.update(over)
    return data


async def test_create_user_with_explicit_password_does_not_echo_it_back():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/users", _user(uid=20, name="newauthor"), 201)
    result = await hu.create_user(ctx, CreateUserParams(
        site_id="blog-test", username="newauthor", email="a@x.com",
        role="author", password="Sup3rSecret!"))
    assert result.status == "success"
    assert result.data.role == "author"
    assert result.data.generated_password == ""  # only shown when WE generated it
    assert "newauthor" in result.summary or "20" in result.summary


async def test_create_user_generates_password_when_omitted_and_returns_it_once():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/users", _user(uid=21, name="genuser"), 201)
    result = await hu.create_user(ctx, CreateUserParams(
        site_id="blog-test", username="genuser", email="b@x.com", role="subscriber"))
    assert result.status == "success"
    assert len(result.data.generated_password) >= 12
    assert "generated" in result.summary.lower()


async def test_create_user_rejects_invalid_role():
    ctx = await _ctx()
    result = await hu.create_user(ctx, CreateUserParams(
        site_id="blog-test", username="x", email="x@x.com", role="superadmin"))
    assert result.status == "error"
    assert result.error_code == "WP_USER_INVALID_ROLE"


async def test_create_user_surfaces_existing_login():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/users", {"code": "existing_user_login"}, 400)
    result = await hu.create_user(ctx, CreateUserParams(
        site_id="blog-test", username="taken", email="x@x.com"))
    assert result.status == "error"
    assert result.error_code == "WP_USER_LOGIN_EXISTS"


async def test_update_user_role():
    ctx = await _ctx()
    ctx.http.mock_post(f"{BASE}/users/12", _user(roles=["editor"]), 200)
    result = await hu.update_user(ctx, UpdateUserParams(site_id="blog-test", user_id=12, role="editor"))
    assert result.status == "success"
    assert result.data.role == "editor"


async def test_update_user_rejects_invalid_role():
    ctx = await _ctx()
    result = await hu.update_user(ctx, UpdateUserParams(site_id="blog-test", user_id=12, role="godmode"))
    assert result.status == "error"
    assert result.error_code == "WP_USER_INVALID_ROLE"


async def test_update_user_requires_at_least_one_field():
    ctx = await _ctx()
    result = await hu.update_user(ctx, UpdateUserParams(site_id="blog-test", user_id=12))
    assert result.status == "error"


async def test_delete_user_without_reassign():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/users/12", {"deleted": True, "previous": _user()}, 200)
    result = await hu.delete_user(ctx, DeleteUserParams(site_id="blog-test", user_id=12))
    assert result.status == "success"
    assert result.data.deleted is True
    assert result.data.reassigned_to == ""


async def test_delete_user_with_reassign():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/users/12", {"deleted": True, "previous": _user()}, 200)
    result = await hu.delete_user(ctx, DeleteUserParams(site_id="blog-test", user_id=12, reassign_to=3))
    assert result.status == "success"
    assert result.data.reassigned_to == "3"
    assert "3" in result.summary


async def test_delete_user_not_found():
    ctx = await _ctx()
    _mock_delete(ctx, f"{BASE}/users/999", {"code": "rest_user_invalid_id"}, 404)
    result = await hu.delete_user(ctx, DeleteUserParams(site_id="blog-test", user_id=999))
    assert result.status == "error"
    assert result.error_code == "WP_USER_NOT_FOUND"


async def test_user_actions_require_connected_site():
    ctx = MockContext()
    result = await hu.create_user(ctx, CreateUserParams(
        site_id="ghost", username="x", email="x@x.com"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_reset_user_password_sends_email_via_bridge():
    ctx = await _ctx()
    ctx.http.mock_post("https://blog.test/wp-json/imperal/v1/users/12/reset-password",
                       {"email_sent": True}, 200)
    result = await hu.reset_user_password(ctx, PasswordResetParams(site_id="blog-test", user_id=12))
    assert result.status == "success"
    assert result.data.email_sent is True
    assert "12" in result.summary


async def test_reset_user_password_missing_bridge():
    ctx = await _ctx()
    ctx.http.mock_post("https://blog.test/wp-json/imperal/v1/users/12/reset-password",
                       {"code": "rest_no_route"}, 404)
    result = await hu.reset_user_password(ctx, PasswordResetParams(site_id="blog-test", user_id=12))
    assert result.status == "error"
    assert result.error_code == "USERS_BRIDGE_MISSING"


async def test_reset_user_password_user_not_found():
    ctx = await _ctx()
    ctx.http.mock_post("https://blog.test/wp-json/imperal/v1/users/999/reset-password",
                       {"code": "imperal_users_not_found"}, 404)
    result = await hu.reset_user_password(ctx, PasswordResetParams(site_id="blog-test", user_id=999))
    assert result.status == "error"
    assert result.error_code == "WP_USER_NOT_FOUND"


async def test_reset_user_password_mail_send_failure():
    ctx = await _ctx()
    ctx.http.mock_post("https://blog.test/wp-json/imperal/v1/users/12/reset-password",
                       {"code": "imperal_users_reset_failed", "message": "wp_mail failed"}, 500)
    result = await hu.reset_user_password(ctx, PasswordResetParams(site_id="blog-test", user_id=12))
    assert result.status == "error"
    assert result.error_code == "WP_USER_RESET_FAILED"
    assert result.retryable is True
