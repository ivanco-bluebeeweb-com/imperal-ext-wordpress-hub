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
    """Accept whatever a human actually types in the Connect Site dialog --
    a bare domain ("example.com"), an http:// URL, or a proper https:// one
    -- and always resolve to a clean https:// base URL.

    A bare domain has no scheme, so urlparse puts the whole string in
    .path instead of .netloc (e.g. urlparse("example.com").netloc == "").
    That case is detected and the domain is re-parsed with "https://"
    prepended. An explicit "http://" is upgraded rather than rejected --
    WordPress's own REST API requires https for Application Passwords
    anyway, so upgrading silently is strictly more permissive than the
    old hard rejection, never less safe.
    """
    raw = url.strip()
    if not raw:
        raise ValueError("Site URL is required")
    parsed = urlparse(raw)
    if not parsed.netloc:
        # No scheme at all ("example.com", "example.com/wp-admin") --
        # urlparse treated the whole thing as a path. Re-parse with a
        # scheme so netloc/path split correctly.
        parsed = urlparse(f"https://{raw}")
    elif parsed.scheme not in ("http", "https"):
        raise ValueError("Site URL must be a web address (http:// or https://)")
    if not parsed.netloc:
        raise ValueError("Site URL is not a valid address")
    return f"https://{parsed.netloc}".rstrip("/")


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


async def wp_post(ctx, base_url, path, *, username, app_password, json=None, params=None, timeout=None):
    """POST to the WordPress REST API with Application Password auth."""
    headers = basic_auth_header(username, app_password)
    kwargs = {"headers": headers, "json": json, "params": params}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return await ctx.http.post(f"{base_url}{path}", **kwargs)


_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")
_LATIN_RE = re.compile(r"[a-zA-Z]")

# Polylang's own REST namespace for listing configured site languages. This
# has shipped since Polylang 3.7 (both free and Pro) at this exact path --
# see polylang.pro/documentation/support/developers/languages-rest-api/.
# Older Polylang installs (pre-3.7) don't expose it: callers MUST treat a
# 404/error here as "unknown", never as "Polylang has no languages".
_POLYLANG_LANGUAGES_PATH = "/wp-json/pll/v1/languages"


async def list_polylang_languages(ctx, base_url: str, username: str, app_password: str) -> list[str] | None:
    """Best-effort read of the site's OWN configured Polylang language codes
    (e.g. ["ro", "ru"]), so a caller can pick a real, already-configured
    language instead of guessing or hard-coding one.

    Returns None (never an empty list standing in for "no languages") when
    Polylang isn't active, this Polylang version doesn't expose the REST
    endpoint, or the site is unreachable -- callers must treat None as
    "could not determine", not as "Polylang has no languages configured".
    """
    try:
        resp = await wp_get(ctx, base_url, _POLYLANG_LANGUAGES_PATH,
                            username=username, app_password=app_password)
    except Exception:
        return None
    if resp.status_code >= 400 or not isinstance(resp.body, list):
        return None
    codes = []
    for item in resp.body:
        if isinstance(item, dict):
            code = item.get("slug") or item.get("locale") or item.get("code")
            if code:
                codes.append(str(code).lower())
    return codes or None


def detect_script_language(title: str, content: str) -> str:
    """Best-effort Cyrillic-vs-Latin script guess, used ONLY to pick between
    a site's OWN already-configured Polylang languages when no explicit
    ``lang`` was given or the given one doesn't match any configured code.
    Deterministic, no fabrication, no external calls -- distinguishes ru
    (Cyrillic) from a Latin-script language but cannot tell two Latin-script
    languages apart (e.g. ro vs en), so it returns 'ru' or 'latin' only.
    """
    text = f"{title} {content}"
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    if cyr == 0 and lat == 0:
        return "unknown"
    return "ru" if cyr > lat else "latin"


async def resolve_post_language(ctx, base_url: str, username: str, app_password: str, *,
                                 requested_lang: str | None, title: str, content: str) -> tuple[str | None, str | None]:
    """Reconcile a caller-requested Polylang language against the site's OWN
    real configured languages before create_post/update_post ever writes it.

    This is the fix for a whole class of silent mistakes: a caller passing
    'ru' when the site's own Polylang setup actually uses 'rus', or leaving
    ``lang`` empty and letting a Russian article land in the site's default
    (often Romanian) language. The rule, in order:

    1. Polylang not detected on this site (list_polylang_languages -> None):
       pass ``requested_lang`` through unchanged -- nothing to reconcile
       against, and this must never block a non-Polylang site.
    2. Polylang IS configured and ``requested_lang`` matches one of its real
       codes (case-insensitive): use it as-is.
    3. Polylang IS configured but ``requested_lang`` is missing or doesn't
       match any configured code: detect the article's own script
       (Cyrillic vs Latin) and pick whichever configured language's code
       starts with 'ru'/'rus' for Cyrillic content, or the first
       non-Russian configured language for Latin content. Never invents a
       language code that isn't one of the site's own.

    Returns (resolved_lang, warning) -- warning is None unless the requested
    language had to be corrected, so the caller can surface that to the user
    instead of silently overriding it.
    """
    configured = await list_polylang_languages(ctx, base_url, username, app_password)
    if not configured:
        return requested_lang, None

    normalized_requested = (requested_lang or "").strip().lower()
    if normalized_requested and normalized_requested in configured:
        return normalized_requested, None

    script = detect_script_language(title, content)
    russian_codes = [c for c in configured if c.startswith("ru")]
    other_codes = [c for c in configured if not c.startswith("ru")]
    if script == "ru" and russian_codes:
        resolved = russian_codes[0]
    elif script != "unknown" and other_codes:
        resolved = other_codes[0]
    else:
        resolved = configured[0]

    if normalized_requested and normalized_requested != resolved:
        return resolved, (
            f"requested language '{requested_lang}' isn't one of this site's configured "
            f"Polylang languages ({', '.join(configured)}) -- used '{resolved}' instead, "
            f"matched from the article's own script."
        )
    if not normalized_requested:
        return resolved, None
    return resolved, None


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


async def find_term_id(ctx, base_url: str, username: str, app_password: str,
                        taxonomy_base: str, name: str, lang: str | None = None) -> int | None:
    """Resolve a term name to its id within one taxonomy (case-insensitive exact match).

    ``taxonomy_base`` is the taxonomy's REST base, e.g. 'categories' or 'tags'.
    Unreachable site / network errors are treated the same as "not found" —
    the caller falls back to writing the post without that term rather than
    failing the whole write over an optional lookup. Never creates a term.
    """
    params = {"search": name, "per_page": 100}
    if lang:
        params["lang"] = lang
    try:
        resp = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{taxonomy_base}",
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


async def find_category_id(ctx, base_url: str, username: str, app_password: str,
                            name: str, lang: str | None = None) -> int | None:
    """Resolve a category name to its term id. Thin wrapper over find_term_id."""
    return await find_term_id(ctx, base_url, username, app_password, "categories", name, lang=lang)


async def find_term_ids(ctx, base_url: str, username: str, app_password: str,
                         taxonomy_base: str, names: list[str],
                         lang: str | None = None) -> tuple[list[int], list[str]]:
    """Resolve several term names within one taxonomy. Never creates a term.

    Returns (resolved_ids, names_not_found) — a name that doesn't match any
    existing term is reported back rather than silently dropped or created.
    """
    resolved: list[int] = []
    missing: list[str] = []
    for name in names:
        term_id = await find_term_id(ctx, base_url, username, app_password, taxonomy_base, name, lang=lang)
        if term_id:
            resolved.append(term_id)
        else:
            missing.append(name)
    return resolved, missing


async def list_terms(ctx, base_url: str, username: str, app_password: str,
                      taxonomy_base: str, *, parent: int | None = None,
                      search: str | None = None, per_page: int = 100, page: int = 1):
    """List terms in one taxonomy ('categories' or 'tags'). Returns the raw HTTPResponse."""
    params: dict = {"per_page": per_page, "page": page}
    if parent is not None:
        params["parent"] = parent
    if search:
        params["search"] = search
    return await wp_get(ctx, base_url, f"/wp-json/wp/v2/{taxonomy_base}",
                        username=username, app_password=app_password, params=params)


async def create_term(ctx, base_url: str, username: str, app_password: str,
                       taxonomy_base: str, *, name: str, description: str = "",
                       parent: int | None = None, lang: str | None = None):
    """Create one term in a taxonomy. ``parent`` only applies to hierarchical
    taxonomies (categories) — WordPress ignores it for flat ones (tags).

    ``lang`` must be passed on a Polylang site whenever the term is being
    created to satisfy a specific post's language (e.g. auto-created by
    create_post): Polylang reads the language from the query string on
    creation same as it does for posts, and assigns a *default*-language
    term when it's omitted. Without this, a term auto-created while writing
    a post in language A silently lands in the site's default language, so
    a later find_term_id(..., lang=A) never matches it again -- the exact
    bug this parameter fixes.
    """
    payload: dict = {"name": name, "description": description}
    if parent is not None:
        payload["parent"] = parent
    params = {"lang": lang} if lang else None
    return await wp_post(ctx, base_url, f"/wp-json/wp/v2/{taxonomy_base}",
                         username=username, app_password=app_password, json=payload, params=params)


async def update_term(ctx, base_url: str, username: str, app_password: str,
                       taxonomy_base: str, term_id: int, **fields):
    """Update selected fields of an existing term. Only keys present in ``fields`` are sent."""
    return await wp_request(ctx, "post", base_url, f"/wp-json/wp/v2/{taxonomy_base}/{term_id}",
                            username=username, app_password=app_password, json=fields)


async def delete_term(ctx, base_url: str, username: str, app_password: str,
                       taxonomy_base: str, term_id: int):
    """Permanently delete a term — WordPress requires force=true since terms have no trash."""
    return await wp_request(ctx, "delete", base_url, f"/wp-json/wp/v2/{taxonomy_base}/{term_id}",
                            username=username, app_password=app_password, params={"force": "true"})


async def create_post(ctx, base_url: str, username: str, app_password: str, *,
                      post_type: str = "posts", title: str, content: str,
                      status: str = "draft", slug: str | None = None,
                      category_id: int | None = None, tag_ids: list[int] | None = None,
                      featured_media: int | None = None, lang: str | None = None,
                      date: str | None = None, excerpt: str | None = None):
    """Create a WordPress post/page. Returns the raw HTTPResponse.

    ``post_type`` is the REST base ('posts', 'pages', or a custom type's own
    base) — categories/tags/featured_media only apply to types that support
    them; passing them for a type without that support is silently ignored
    by WordPress itself, not by this helper.
    """
    payload: dict = {"title": title, "content": content, "status": status}
    if slug:
        payload["slug"] = slug
    if excerpt is not None:
        payload["excerpt"] = excerpt
    if category_id:
        payload["categories"] = [category_id]
    if tag_ids:
        payload["tags"] = tag_ids
    if featured_media:
        payload["featured_media"] = featured_media
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
