"""Native WordPress user management: create, update role/profile, delete.

Until now this connector could only list_users (read-only). The most common
follow-on tasks after listing users -- onboarding a new author, promoting a
contributor to editor, or offboarding someone -- had no path at all. These
hit the native /wp/v2/users REST endpoints directly (Application Password
auth, no Bridge/SSH needed).
"""
import hashlib
import json
import secrets
import string

from imperal_sdk import ActionResult

from app import chat
from models import (
    ApplyBulkUserRoleParams,
    BulkUserRoleParams,
    BulkUserRoleResult,
    CreateUserParams,
    DeleteUserParams,
    PasswordResetParams,
    PasswordResetResult,
    UpdateUserParams,
    UserCreateResult,
    UserDeleteResult,
    WPUser,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post, wp_request

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


def _user_state_token(users: list[dict]) -> str:
    state = [
        {"id": int(item.get("id", 0)), "roles": sorted(item.get("roles", [])),
         "email": item.get("email", ""), "modified": item.get("modified", "")}
        for item in sorted(users, key=lambda user: int(user.get("id", 0)))
    ]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_user_targets(ctx, params: BulkUserRoleParams):
    role = params.role.strip().lower()
    if role not in _VALID_ROLES:
        return None, ActionResult.error(
            f"Invalid role '{params.role}' — use one of: {', '.join(sorted(_VALID_ROLES))}.",
            retryable=False, code="WP_USER_INVALID_ROLE")
    if len(set(params.user_ids)) != len(params.user_ids):
        return None, ActionResult.error("Each user id may appear only once.", retryable=False,
                                        code="WP_USER_DUPLICATE_IDS")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, pw = auth
    users = []
    for user_id in params.user_ids:
        response = await wp_get(ctx, base_url, f"/wp-json/wp/v2/users/{user_id}",
                                username=username, app_password=pw, params={"context": "edit"})
        if response.status_code != 200 or not isinstance(response.body, dict):
            return None, _failure(response.status_code, response.body)
        users.append(response.body)
    return (base_url, username, pw, users), None


@chat.function(
    "preview_bulk_user_role",
    description="Preview changing the role for 1-100 explicit WordPress users. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkUserRoleResult,
)
async def preview_bulk_user_role(ctx, params: BulkUserRoleParams) -> ActionResult:
    """Read every explicit user and show the reviewed role change."""
    targets, err = await _bulk_user_targets(ctx, params)
    if err:
        return err
    _, _, _, users = targets
    role = params.role.strip().lower()
    return ActionResult.success(BulkUserRoleResult(
        id=params.site_id, title="Bulk user role preview", kind="wp_bulk_user_role",
        preview=True, requested=len(params.user_ids), matched=len(users), state_token=_user_state_token(users),
        changes=[f"#{item['id']}: {', '.join(item.get('roles', [])) or '(none)'} → {role}" for item in users],
    ), summary=f"Previewed {len(users)} user role change(s); no changes made.")


@chat.function(
    "apply_bulk_user_role",
    description="Apply a previously previewed role change to 1-100 explicit WordPress users. Stops before all writes if any user changed.",
    action_type="write", data_model=BulkUserRoleResult,
    effects=["wp.user_update"], event="wordpress-hub.apply_bulk_user_role",
)
async def apply_bulk_user_role(ctx, params: ApplyBulkUserRoleParams) -> ActionResult:
    """Recheck every user before applying a reviewed explicit role batch."""
    targets, err = await _bulk_user_targets(ctx, params)
    if err:
        return err
    base_url, username, pw, users = targets
    token = _user_state_token(users)
    if token != params.expected_state_token:
        return ActionResult.error("One or more users changed after preview; preview again before applying.",
                                  retryable=False, code="WP_USER_BULK_STATE_CHANGED")
    role = params.role.strip().lower()
    updated_ids, failed_ids = [], []
    for item in users:
        user_id = int(item["id"])
        response = await wp_request(ctx, "post", base_url, f"/wp-json/wp/v2/users/{user_id}",
                                    username=username, app_password=pw, json={"roles": [role]})
        (updated_ids if 200 <= response.status_code < 300 else failed_ids).append(user_id)
    result = BulkUserRoleResult(
        id=params.site_id, title="Bulk user role applied", kind="wp_bulk_user_role", preview=False,
        requested=len(params.user_ids), matched=len(users), updated=len(updated_ids), failed=len(failed_ids),
        state_token=token, updated_ids=updated_ids, failed_ids=failed_ids,
    )
    if not updated_ids:
        return ActionResult.error("No user role changes were applied.", retryable=True,
                                  code="WP_USER_BULK_ALL_FAILED")
    summary = f"Updated {len(updated_ids)} user role(s) to '{role}'"
    if failed_ids:
        summary += f"; {len(failed_ids)} failed"
    return ActionResult.success(result, summary=summary, refresh_panels=["center"])


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


BRIDGE_RESET_PASSWORD_PATH = "/wp-json/imperal/v1/users/{id}/reset-password"


def _reset_password_failure(status_code, body):
    wp_code = str(body.get("code", "")) if isinstance(body, dict) else ""
    wp_message = body.get("message", "") if isinstance(body, dict) else ""
    if wp_code == "rest_no_route":
        return ActionResult.error(
            "This site does not have the Imperal Bridge plugin installed, or it is older "
            "than the version that adds password reset. Install the Imperal Bridge plugin "
            "on the site (bridge/imperal-bridge in the connector repo).",
            retryable=False, code="USERS_BRIDGE_MISSING")
    if wp_code == "imperal_users_not_found":
        return ActionResult.error(
            wp_message or "That user does not exist.", retryable=False, code="WP_USER_NOT_FOUND")
    if wp_code == "imperal_users_reset_failed":
        return ActionResult.error(
            wp_message or "WordPress could not send the reset email — check that the site "
            "can send mail at all.", retryable=True, code="WP_USER_RESET_FAILED")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage users. Reconnect with an "
            "administrator Application Password.",
            retryable=False, code="WP_USER_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


@chat.function(
    "reset_user_password",
    description=(
        "Trigger WordPress's own native password-reset email for one user -- the same "
        "email wp-admin's Users list sends when an admin clicks 'Send password reset'. "
        "WordPress core has no REST route for this (only the wp-login.php form does), so "
        "this reads through the Imperal Bridge plugin -- install it on the site first."
    ),
    action_type="write", data_model=PasswordResetResult,
    effects=["wp.user_password_reset"], event="wordpress-hub.reset_user_password",
)
async def reset_user_password(ctx, params: PasswordResetParams) -> ActionResult:
    """POST /imperal/v1/users/{id}/reset-password via the Imperal Bridge plugin."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    path = BRIDGE_RESET_PASSWORD_PATH.format(id=params.user_id)
    try:
        r = await wp_post(ctx, base_url, path, username=username, app_password=pw, json={})
    except Exception as e:
        await ctx.log(f"reset_user_password request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _reset_password_failure(r.status_code, r.body)
    return ActionResult.success(
        PasswordResetResult(
            id=str(params.user_id), title=f"user #{params.user_id}", kind="wp_password_reset",
            email_sent=True,
        ),
        summary=f"Password-reset email sent to user #{params.user_id}",
    )
