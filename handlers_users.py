"""Native WordPress user management: create, update role/profile, delete.

Until now this connector could only list_users (read-only). The most common
follow-on tasks after listing users -- onboarding a new author, promoting a
contributor to editor, or offboarding someone -- had no path at all. These
hit the native /wp/v2/users REST endpoints directly (Application Password
auth, no Bridge/SSH needed).
"""
import secrets
import string

from imperal_sdk import ActionResult

from app import chat
from models import (
    CreateUserParams,
    DeleteUserParams,
    UpdateUserParams,
    UserCreateResult,
    UserDeleteResult,
    WPUser,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_post, wp_request

_VALID_ROLES = {"administrator", "editor", "author", "contributor", "subscriber"}


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
    wp_code = str(body.get("code", "")) if isinstance(body, dict) else ""
    if status_code == 404:
        return ActionResult.error(
            "That user does not exist.", retryable=False, code="WP_USER_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage users. Reconnect with an "
            "administrator Application Password.",
            retryable=False, code="WP_USER_FORBIDDEN")
    if status_code == 400 and wp_code == "existing_user_login":
        return ActionResult.error(
            "That username is already taken on this site.",
            retryable=False, code="WP_USER_LOGIN_EXISTS")
    if status_code == 400 and wp_code == "existing_user_email":
        return ActionResult.error(
            "That email address is already registered on this site.",
            retryable=False, code="WP_USER_EMAIL_EXISTS")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _generate_password() -> str:
    """A strong 16-char random password — used only when the caller didn't supply one."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(16))


def _user_entity(item: dict) -> WPUser:
    return WPUser(
        id=str(item.get("id", "")), title=item.get("name", ""), kind="wp_user",
        role=", ".join(item.get("roles", [])),
        registered=(item.get("registered_date", "") or "")[:10],
    )


@chat.function(
    "create_user",
    description=(
        "Create a registered WordPress user with username, email, and role. Passwords are "
        "optional -- a strong random one is generated and returned once (WordPress core "
        "requires SOME password to create a user, but nothing forces sharing it: an admin "
        "can also just email the user a password-reset link)."
    ),
    action_type="write", data_model=UserCreateResult,
    effects=["wp.user_create"], event="wordpress-hub.create_user",
)
async def create_user(ctx, params: CreateUserParams) -> ActionResult:
    """Create one WordPress user via /wp/v2/users."""
    role = params.role.strip().lower()
    if role not in _VALID_ROLES:
        return ActionResult.error(
            f"Invalid role '{params.role}' — use one of: {', '.join(sorted(_VALID_ROLES))}.",
            retryable=False, code="WP_USER_INVALID_ROLE")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    generated = params.password is None
    plain_password = params.password or _generate_password()
    payload = {
        "username": params.username.strip(),
        "email": params.email.strip(),
        "password": plain_password,
        "roles": [role],
    }
    if params.first_name:
        payload["first_name"] = params.first_name.strip()
    if params.last_name:
        payload["last_name"] = params.last_name.strip()

    response = await wp_post(ctx, base_url, "/wp-json/wp/v2/users",
                              username=username, app_password=pw, json=payload)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)

    body = response.body if isinstance(response.body, dict) else {}
    entity = UserCreateResult(
        id=str(body.get("id", "")), title=body.get("name", params.username),
        kind="wp_user", role=role, email=params.email.strip(),
        generated_password=plain_password if generated else "",
    )
    summary = f"Created user {entity.title} (#{entity.id}) as {role}"
    if generated:
        summary += " — a password was generated, shown once above"
    return ActionResult.success(entity, summary=summary, refresh_panels=["center"])


@chat.function(
    "update_user",
    description="Update an existing WordPress user's role, email, first/last name.",
    action_type="write", data_model=WPUser,
    effects=["wp.user_update"], event="wordpress-hub.update_user",
)
async def update_user(ctx, params: UpdateUserParams) -> ActionResult:
    """Update selected fields of an existing WordPress user."""
    fields = {}
    if params.role is not None:
        role = params.role.strip().lower()
        if role not in _VALID_ROLES:
            return ActionResult.error(
                f"Invalid role '{params.role}' — use one of: {', '.join(sorted(_VALID_ROLES))}.",
                retryable=False, code="WP_USER_INVALID_ROLE")
        fields["roles"] = [role]
    if params.email is not None:
        fields["email"] = params.email.strip()
    if params.first_name is not None:
        fields["first_name"] = params.first_name.strip()
    if params.last_name is not None:
        fields["last_name"] = params.last_name.strip()
    if not fields:
        return ActionResult.error(
            "Nothing to update — pass role, email, first_name, and/or last_name.",
            retryable=False)

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    response = await wp_request(
        ctx, "post", base_url, f"/wp-json/wp/v2/users/{params.user_id}",
        username=username, app_password=pw, json=fields)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    entity = _user_entity(response.body if isinstance(response.body, dict) else {})
    return ActionResult.success(
        entity, summary=f"Updated user {entity.title} (#{entity.id})", refresh_panels=["center"])


@chat.function(
    "delete_user",
    description=(
        "Permanently delete a WordPress user. Optionally reassign their posts to another "
        "user id -- WordPress requires SOME disposition for the departing user's posts, "
        "so omitting reassign_to deletes their posts along with the account."
    ),
    action_type="destructive", data_model=UserDeleteResult,
    effects=["wp.user_delete"], event="wordpress-hub.delete_user",
)
async def delete_user(ctx, params: DeleteUserParams) -> ActionResult:
    """Delete one WordPress user via /wp/v2/users, with optional post reassignment."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    query = {"force": "true"}
    if params.reassign_to is not None:
        query["reassign"] = params.reassign_to
    response = await wp_request(
        ctx, "delete", base_url, f"/wp-json/wp/v2/users/{params.user_id}",
        username=username, app_password=pw, params=query)
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    return ActionResult.success(
        UserDeleteResult(
            id=str(params.user_id), title=f"user #{params.user_id}", kind="wp_user",
            deleted=True,
            reassigned_to=str(params.reassign_to) if params.reassign_to else "",
        ),
        summary=f"Deleted user #{params.user_id}"
                + (f", posts reassigned to #{params.reassign_to}" if params.reassign_to else ""),
        refresh_panels=["center"],
    )
