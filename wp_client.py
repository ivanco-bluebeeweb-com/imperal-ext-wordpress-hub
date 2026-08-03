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


async def find_category_id(ctx, base_url: str, username: str, app_password: str,
                            name: str, lang: str | None = None) -> int | None:
    """Resolve a category name to its term id (case-insensitive exact match).

    Unreachable site / network errors are treated the same as "not found" —
    the caller falls back to creating/updating the post without a category
    rather than failing the whole write over an optional lookup.
    """
    params = {"search": name, "per_page": 100}
    if lang:
        params["lang"] = lang
    try:
        resp = await wp_get(ctx, base_url, "/wp-json/wp/v2/categories",
                            username=username, app_password=app_password, params=params)
    except Exception:
        return None
    if resp.status_code >= 400 or not isinstance(resp.body, list):
        return None
    wanted = name.strip().lower()
    for term in resp.body:
        if str(term.get("name", "")).strip().lower() == wanted:
            return term.get("id")
    return None


async def create_post(ctx, base_url: str, username: str, app_password: str, *,
                      post_type: str = "posts", title: str, content: str,
                      status: str = "draft", slug: str | None = None,
                      category_id: int | None = None, lang: str | None = None,
                      date: str | None = None, excerpt: str | None = None):
    """Create a WordPress post/page. Returns the raw HTTPResponse.

    ``post_type`` is the REST base ('posts', 'pages', or a custom type's own
    base) — categories only apply to types that support them; passing
    category_id for a type without taxonomy support is silently ignored by
    WordPress itself, not by this helper.
    """
    payload: dict = {"title": title, "content": content, "status": status}
    if slug:
        payload["slug"] = slug
    if excerpt is not None:
        payload["excerpt"] = excerpt
    if category_id:
        payload["categories"] = [category_id]
    if date:
        payload["date"] = date if "T" in date else f"{date}T10:00:00"
    path = f"/wp-json/wp/v2/{post_type}"
    params = {"lang": lang} if lang else None  # Polylang reads language from the query string on create
    return await wp_post(ctx, base_url, path, username=username, app_password=app_password,
                         json=payload, params=params)


async def update_post(ctx, base_url: str, username: str, app_password: str, *,
                      post_id: int, post_type: str = "posts", **fields):
    """Update selected fields of an existing post/page. Returns the raw HTTPResponse.

    Only keys present in ``fields`` are sent — WordPress leaves everything
    else untouched, so omitted fields are never clobbered.
    """
    path = f"/wp-json/wp/v2/{post_type}/{post_id}"
    return await wp_post(ctx, base_url, path, username=username, app_password=app_password, json=fields)
