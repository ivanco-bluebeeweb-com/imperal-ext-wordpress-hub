import base64
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

_ERROR_MESSAGES = {
    401: "WordPress rejected the credentials — reconnect the site with a fresh Application Password.",
    403: "That WordPress user lacks permission for this request.",
    404: "WordPress REST API not found — is this a WordPress site and is the REST API enabled?",
    429: "WordPress is rate-limiting requests — try again shortly.",
}

# Structural error codes. An error emitted without one is stamped
# EXT_UNSTRUCTURED_ERROR by the kernel, which leaves the narrator no stable
# facts to reason about — so every error path here carries a code.
_ERROR_CODES = {
    401: "WP_AUTH_REJECTED",
    403: "WP_FORBIDDEN",
    404: "WP_REST_NOT_FOUND",
    429: "WP_RATE_LIMITED",
}


def wp_error_code(status_code: int) -> str:
    """Stable machine-readable code for a WordPress HTTP status."""
    if status_code in _ERROR_CODES:
        return _ERROR_CODES[status_code]
    if 500 <= status_code < 600:
        return "WP_SERVER_ERROR"
    return "WP_REQUEST_FAILED"


def basic_auth_header(username: str, app_password: str) -> dict:
    token = base64.b64encode(f"{username}:{app_password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def normalize_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise ValueError("Site URL must use https://")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def site_id_from_url(url: str) -> str:
    host = urlparse(url.strip()).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return re.sub(r"[^a-z0-9]+", "-", host).strip("-")


def wp_error_message(status_code: int) -> str:
    if status_code in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[status_code]
    if 500 <= status_code < 600:
        return "WordPress returned a server error — try again shortly."
    return f"WordPress request failed (HTTP {status_code})."


async def wp_get(ctx, base_url, path, *, username, app_password, params=None):
    headers = basic_auth_header(username, app_password)
    return await ctx.http.get(f"{base_url}{path}", headers=headers, params=params)


async def wp_post(ctx, base_url, path, *, username, app_password, json=None, params=None):
    """POST to the WordPress REST API with Application Password auth."""
    headers = basic_auth_header(username, app_password)
    return await ctx.http.post(f"{base_url}{path}", headers=headers, json=json, params=params)


async def wp_request(ctx, method, base_url, path, *, username, app_password, json=None, params=None):
    """Send an authenticated WordPress REST request using a supported HTTP verb."""
    verb = method.lower().strip()
    if verb not in {"post", "put", "delete"}:
        raise ValueError(f"Unsupported WordPress HTTP method: {method}")
    sender = getattr(ctx.http, verb)
    kwargs = {"headers": basic_auth_header(username, app_password), "params": params}
    if verb != "delete":
        kwargs["json"] = json
    return await sender(f"{base_url}{path}", **kwargs)


def now_iso() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def wp_title(item: dict) -> str:
    """WordPress entities carry title as {"rendered": "..."}; fall back to id, then empty string."""
    t = item.get("title")
    if isinstance(t, dict):
        return t.get("rendered") or str(item.get("id", "")) or ""
    return t or str(item.get("id", "")) or ""
