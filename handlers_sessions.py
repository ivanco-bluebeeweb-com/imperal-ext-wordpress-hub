"""Native WordPress user-session hygiene through Imperal Bridge (Group S)."""
from imperal_sdk import ActionResult

from app import chat
from models import (
    DestroySessionsParams,
    DestroySessionsResult,
    UserSession,
    UserSessions,
    UserSessionsParams,
)
import storage
from wp_client import wp_get, wp_request

_PATH = "/wp-json/imperal/v1/users/{id}/sessions"


async def _auth(ctx, site_id: str):
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


def _failure(status_code: int, body):
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    message = str(body.get("message", "")) if isinstance(body, dict) else ""
    if code == "rest_no_route":
        return ActionResult.error(
            "This site needs Imperal Bridge 2.16.0 or newer for session hygiene.",
            retryable=False, code="SESSIONS_BRIDGE_MISSING")
    if code == "imperal_users_not_found" or status_code == 404:
        return ActionResult.error("That user does not exist.", retryable=False, code="WP_USER_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage users. Reconnect with an administrator Application Password.",
            retryable=False, code="WP_USER_FORBIDDEN")
    return ActionResult.error(message or "WordPress could not manage user sessions.",
                              retryable=status_code >= 500, code=code or "WP_SESSION_FAILED")


@chat.function(
    "list_active_sessions",
    description=(
        "List a WordPress user's active native login sessions: login time, expiry, IP address, and "
        "user-agent. Requires Imperal Bridge 2.16.0+ and an administrator Application Password."
    ),
    action_type="read", data_model=UserSessions,
)
async def list_active_sessions(ctx, params: UserSessionsParams) -> ActionResult:
    """Read non-secret metadata from WordPress's WP_Session_Tokens storage."""
    auth, error = await _auth(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth
    try:
        response = await wp_get(ctx, base_url, _PATH.format(id=params.user_id), username=username,
                                app_password=password)
    except Exception as exc:
        await ctx.log(f"list_active_sessions request failed: {exc}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    body = response.body if isinstance(response.body, dict) else {}
    session_items = [UserSession(
        id=f"{params.site_id}:user:{params.user_id}:session:{index}", title="Login session",
        kind="wp_user_session", login=int(item.get("login", 0)), expiration=int(item.get("expiration", 0)),
        ip=str(item.get("ip", "")), ua=str(item.get("ua", "")),
    ) for index, item in enumerate(body.get("sessions", []), start=1) if isinstance(item, dict)]
    return ActionResult.success(
        UserSessions(id=f"{params.site_id}:user:{params.user_id}:sessions", title="Active sessions",
                     kind="wp_user_sessions", site_id=params.site_id, user_id=params.user_id, sessions=session_items),
        summary=f"Found {len(session_items)} active session(s) for user {params.user_id}.",
    )


@chat.function(
    "destroy_user_sessions",
    description=(
        "Force-log out one WordPress user everywhere by destroying all of that user's native login "
        "sessions. Does not change their password or delete the account. Requires Imperal Bridge 2.16.0+."
    ),
    action_type="write", data_model=DestroySessionsResult, effects=["wp.user_sessions_destroyed"],
    event="wordpress-hub.destroy_user_sessions",
)
async def destroy_user_sessions(ctx, params: DestroySessionsParams) -> ActionResult:
    """Destroy every native WP_Session_Tokens session for one explicit user id."""
    auth, error = await _auth(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth
    try:
        response = await wp_request(ctx, "delete", base_url, _PATH.format(id=params.user_id),
                                    username=username, app_password=password)
    except Exception as exc:
        await ctx.log(f"destroy_user_sessions request failed: {exc}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return _failure(response.status_code, response.body)
    body = response.body if isinstance(response.body, dict) else {}
    destroyed = bool(body.get("destroyed", False))
    return ActionResult.success(
        DestroySessionsResult(id=f"{params.site_id}:user:{params.user_id}:sessions", title="Sessions ended",
                              kind="wp_destroy_sessions", site_id=params.site_id,
                              user_id=params.user_id, destroyed=destroyed),
        summary=(f"All login sessions for user {params.user_id} were ended." if destroyed
                 else f"WordPress did not confirm ending sessions for user {params.user_id}."),
    )
