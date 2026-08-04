# WP Site Connector v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only Imperal Cloud extension that connects WordPress sites (URL + Application Password) and lets a user browse their posts, pages, media, and health via a panel dashboard and chat.

**Architecture:** Plain Python Imperal extension (handlers run in-process on the ICNLI Worker — no HTTP server). Site metadata lives in `ctx.store`; all site Application Passwords live in one KMS-encrypted `wp_credentials` secret holding a `{site_id: app_password}` map. Outbound calls to the WordPress REST API go through `ctx.http` with HTTP Basic auth. UI is a master-detail panel; Webbee reaches read tools via `@chat.function`.

**Tech Stack:** Python 3.11+, `imperal-sdk[dev]` (v5.x — docs + PyPI are both at 5.4.2 as of 2026-06-16), Pydantic v2, pytest (`imperal_sdk.testing.MockContext`).

## Global Constraints

- **Python 3.11+** required (system `python3` is 3.9.6 — use a 3.11+ interpreter in a venv).
- **SDK is the source of truth.** Every SDK / test API in this plan follows the local docs mirror `Imperal OS/Docs/imperal-docs/` (`_digests/04-sdk-a.md`, `05-sdk-b.md`, `06-guides.md`). Before each task, confirm exact signatures (decorators, `ctx.*`, `sdl.*`, `ui.*`, `MockContext`) against the digest and the installed SDK; adjust code if the installed SDK differs.
- **Credentials never touch an LLM-visible arg.** The Application Password is captured only via the panel connection-form's direct submit action. LLM-facing tools are read-only + `forget_site(site_id)`. Never log/cache/return a password; never place it in `ActionResult.data` (feeds the fact-ledger).
- **Scope all `ctx.store` / `ctx.secrets` access by `ctx.user.imperal_id`** (multi-tenant, fail-closed).
- **HTTPS only.** Refuse non-HTTPS site URLs. Send `Authorization: Basic base64(username:app_password)`.
- **action_type discipline:** read tools declare `data_model=` (V23); `connect_site` is `write`; `forget_site` is `destructive` (KAV confirmation fires automatically — never roll your own confirm).
- **Return contract:** every `@chat.function` returns `ActionResult.success(<sdl.Entity|sdl.EntityList>, summary=...)` / `.error("user-safe msg", retryable=...)` — never bare dicts. `retryable=True` only for timeout/429/5xx. Never `error(str(e))`; `await ctx.log(...)` the detail, return a stable message.
- **Validation gate:** `imperal validate .` must exit with **0 ERRORs** (validators V14–V24 + V31). ≥1 test per `@chat.function`. `description` ≥ 40 chars and concrete.
- **Constants:** secret name `wp_credentials`; store collection `sites`; `app_id` `wp-site-connector`.

Spec: `Apps/WP Site Connector/docs/2026-06-16-wp-site-connector-v1-design.md`.

---

### Task 1: Scaffold, environment, and a validate-clean minimal extension

**Files:**
- Create: `Apps/WP Site Connector/src/main.py`
- Create: `Apps/WP Site Connector/src/app.py`
- Create: `Apps/WP Site Connector/src/icon.svg`
- Create: `Apps/WP Site Connector/src/pyproject.toml`
- Create: `Apps/WP Site Connector/src/.gitignore`
- Create: `Apps/WP Site Connector/src/tests/__init__.py`

**Interfaces:**
- Produces: module `app` exporting `ext` (`Extension`) and `chat` (`ChatExtension`); a temporary `ping` read tool returning a `sdl.Entity`. Later tasks register their handlers/panels on `ext`/`chat` and remove `ping`.

- [ ] **Step 1: Locate a Python 3.11+ interpreter and create the venv**

Run (try in order; use the first that prints 3.11+):
```bash
cd "Apps/WP Site Connector/src"
for p in python3.12 python3.11; do command -v $p && $p --version && break; done
# If none exist: `brew install python@3.12` then re-run.
python3.12 -m venv .venv || python3.11 -m venv .venv
. .venv/bin/activate
python --version   # expect 3.11.x or 3.12.x
```

- [ ] **Step 2: Install the SDK and verify it is the real Imperal SDK (v5.x)**

```bash
pip install --upgrade pip
pip install "imperal-sdk[dev]"
python -c "import imperal_sdk; print(imperal_sdk.__version__)"   # expect 5.x (docs changelog top entry is 5.4.2)
imperal --version
```
Expected: a `5.x` version and a working `imperal` CLI. **If the import fails or the version is far off from the docs changelog top entry (currently v5.4.2), STOP** — confirm the package is genuinely the Imperal Cloud SDK; report to Vlad before continuing. (Confirmed at plan time: PyPI `imperal-sdk` 5.4.2, author "Imperal, Inc.".)

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "wp-site-connector"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["imperal-sdk"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 4: Write `.gitignore` and init git in the app folder**

```bash
printf ".venv/\n__pycache__/\n*.pyc\nimperal.json\n" > .gitignore
cd "Apps/WP Site Connector" && git init && cd src
```

- [ ] **Step 5: Write a minimal `icon.svg`** (valid `viewBox`, ≤100 KB)

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>
```

- [ ] **Step 6: Write `app.py` — the minimal extension** (confirm `Extension`/`ChatExtension`/`@chat.function`/`sdl` signatures against `_digests/04-sdk-a.md`)

```python
from imperal_sdk import Extension, ChatExtension, ActionResult, sdl
from pydantic import BaseModel

ext = Extension(
    "wp-site-connector",
    version="0.1.0",
    display_name="WP Site Connector",
    description="Connect WordPress sites by URL and Application Password and read their posts, pages, media, and health.",
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(ext, tool_name="wp-site-connector", description="Browse connected WordPress sites")


class _PingResult(sdl.Entity):
    pass


class _PingParams(BaseModel):
    pass


@chat.function(description="Health check for the extension.", action_type="read", data_model=_PingResult)
async def ping(ctx, params: _PingParams):
    return ActionResult.success(_PingResult(id="ping", title="ok", kind="ping"), summary="ok")
```

- [ ] **Step 7: Write `main.py`** (thin loader — the CLI imports `main`)

```python
from app import ext, chat  # noqa: F401
```

- [ ] **Step 8: Validate**

Run:
```bash
python -m py_compile *.py
imperal validate .
```
Expected: `py_compile` silent; `imperal validate .` exits 0 with 0 ERRORs.

- [ ] **Step 9: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: scaffold wp-site-connector with validate-clean minimal extension"
```

---

### Task 2: Data models — Pydantic params + SDL entities

**Files:**
- Create: `Apps/WP Site Connector/src/models.py`
- Test: `Apps/WP Site Connector/src/tests/test_models.py`

**Interfaces:**
- Produces:
  - Params: `ConnectSiteParams{url:str, username:str, app_password:str}`, `SiteIdParams{site_id:str}`, `ListContentParams{site_id:str, limit:int=20, search:str|None=None}`, `ListMediaParams{site_id:str, limit:int=20}`.
  - Entities: `Site{id,title,kind="wp_site", url, username, status, last_checked}`, `Post{id,title,kind="wp_post", status, link, date}`, `Page{...kind="wp_page"}`, `MediaItem{id,title,kind="wp_media", url, mime_type}`, `SiteHealth{id,title,kind="wp_site_health", reachable, auth_ok, ssl_valid, content_counts:dict, plugin_updates_available, php_version}` (the last two are `str` markers, default `"requires companion plugin (vNext)"`).
- Note: SDL entities subclass `sdl.Entity` (required `id`/`title`/`kind`) with custom Pydantic fields (the docs' tutorial defines custom `TaskRecord`/`TaskList` the same way). Add semantic facet mixins from `_digests/05-sdk-b.md` only if a documented facet matches (optional for v1).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from models import (
    ConnectSiteParams, ListContentParams, Site, Post, MediaItem, SiteHealth,
)


def test_connect_params_require_fields():
    p = ConnectSiteParams(url="https://x.com", username="admin", app_password="abcd efgh")
    assert p.url == "https://x.com" and p.username == "admin"


def test_list_content_defaults():
    p = ListContentParams(site_id="x-com")
    assert p.limit == 20 and p.search is None


def test_site_entity_fields():
    s = Site(id="x-com", title="X", kind="wp_site", url="https://x.com", username="admin", status="connected", last_checked="2026-06-16T00:00:00Z")
    assert s.kind == "wp_site" and s.status == "connected"


def test_post_and_media_entities():
    post = Post(id="1", title="Hello", kind="wp_post", status="publish", link="https://x.com/hello", date="2026-06-16T00:00:00Z")
    media = MediaItem(id="9", title="img", kind="wp_media", url="https://x.com/img.png", mime_type="image/png")
    assert post.link.endswith("/hello") and media.mime_type == "image/png"


def test_site_health_marks_vnext_fields_unavailable():
    h = SiteHealth(id="x-com", title="X health", kind="wp_site_health", reachable=True, auth_ok=True, ssl_valid=True, content_counts={"posts": 3})
    assert "vNext" in h.plugin_updates_available and "vNext" in h.php_version
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "Apps/WP Site Connector/src" && . .venv/bin/activate && pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models'`.

- [ ] **Step 3: Write `models.py`**

```python
from pydantic import BaseModel, Field
from imperal_sdk import sdl

VNEXT = "requires companion plugin (vNext)"


class ConnectSiteParams(BaseModel):
    url: str = Field(description="Full https:// URL of the WordPress site, e.g. https://example.com")
    username: str = Field(description="WordPress username that owns the Application Password")
    app_password: str = Field(description="WordPress Application Password (entered via the connection form only)")


class SiteIdParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class ListContentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, description="Max items to return, 1-100")
    search: str | None = Field(default=None, description="Optional search term")


class ListMediaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, description="Max items to return, 1-100")


class Site(sdl.Entity):
    url: str
    username: str
    status: str
    last_checked: str | None = None


class Post(sdl.Entity):
    status: str
    link: str
    date: str | None = None


class Page(sdl.Entity):
    status: str
    link: str
    date: str | None = None


class MediaItem(sdl.Entity):
    url: str
    mime_type: str


class SiteHealth(sdl.Entity):
    reachable: bool
    auth_ok: bool
    ssl_valid: bool
    content_counts: dict = Field(default_factory=dict)
    plugin_updates_available: str = VNEXT
    php_version: str = VNEXT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 tests). If `sdl.Entity` rejects extra fields, consult `_digests/05-sdk-b.md` for the documented field/facet mechanism and adjust the entity definitions, then re-run.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add Pydantic params and SDL entities"
```

---

### Task 3: `wp_client.py` — auth, URL normalization, GET wrapper, error mapping

**Files:**
- Create: `Apps/WP Site Connector/src/wp_client.py`
- Test: `Apps/WP Site Connector/src/tests/test_wp_client.py`

**Interfaces:**
- Produces:
  - `basic_auth_header(username:str, app_password:str) -> dict[str,str]`
  - `normalize_base_url(url:str) -> str` (force https, strip trailing slash; raises `ValueError` on non-https)
  - `site_id_from_url(url:str) -> str` (host → slug, e.g. `https://Example.com/` → `example-com`)
  - `wp_error_message(status_code:int) -> str` (user-safe message)
  - `async def wp_get(ctx, base_url:str, path:str, *, username:str, app_password:str, params:dict|None=None)` → the `ctx.http` response object (`.status_code`, `.json()`, `.headers`).
- Consumes: `ctx.http` (confirm `get(url, headers=, params=)` shape + that response exposes `.status_code`/`.json()`/`.headers` against `_digests/02-concepts-a.md` + testing guide).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wp_client.py
import base64
import pytest
from imperal_sdk.testing import MockContext
import wp_client as wc


def test_basic_auth_header():
    h = wc.basic_auth_header("admin", "abcd efgh")
    token = base64.b64encode(b"admin:abcd efgh").decode()
    assert h["Authorization"] == f"Basic {token}"


def test_normalize_base_url_forces_https_and_strips_slash():
    assert wc.normalize_base_url("https://Example.com/") == "https://Example.com"
    with pytest.raises(ValueError):
        wc.normalize_base_url("http://example.com")


def test_site_id_from_url():
    assert wc.site_id_from_url("https://Example.com/blog") == "example-com"


def test_error_messages_are_user_safe():
    assert "credentials" in wc.wp_error_message(401).lower()
    assert "not found" in wc.wp_error_message(404).lower()


async def test_wp_get_calls_http_with_auth():
    ctx = MockContext()
    ctx.http.mock_get(
        "https://example.com/wp-json/wp/v2/posts",
        json=[{"id": 1}],
        status_code=200,
        headers={"X-WP-Total": "1"},
    )
    r = await wc.wp_get(ctx, "https://example.com", "/wp-json/wp/v2/posts", username="admin", app_password="pw")
    assert r.status_code == 200 and r.json()[0]["id"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wp_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wp_client'`. (If `MockContext.http.mock_get` has a different signature, fix the test to match the testing guide in `_digests/06-guides.md` first.)

- [ ] **Step 3: Write `wp_client.py`**

```python
import base64
import re
from urllib.parse import urlparse

_ERROR_MESSAGES = {
    401: "WordPress rejected the credentials — reconnect the site with a fresh Application Password.",
    403: "That WordPress user lacks permission for this request.",
    404: "WordPress REST API not found — is this a WordPress site and is the REST API enabled?",
    429: "WordPress is rate-limiting requests — try again shortly.",
}


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wp_client.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add WordPress REST client helpers"
```

---

### Task 4: `storage.py` — site records + credential map

**Files:**
- Create: `Apps/WP Site Connector/src/storage.py`
- Test: `Apps/WP Site Connector/src/tests/test_storage.py`

**Interfaces:**
- Produces (all async, all scoped by `ctx.user.imperal_id` via `ctx.store`):
  - `list_site_records(ctx) -> list[dict]`
  - `get_site_record(ctx, site_id) -> dict | None`
  - `save_site_record(ctx, record:dict) -> None` (record has `id`)
  - `delete_site_record(ctx, site_id) -> None`
  - `get_credential(ctx, site_id) -> str | None`
  - `set_credential(ctx, site_id, app_password) -> None`
  - `delete_credential(ctx, site_id) -> None`
  - constants `SITES_COLLECTION="sites"`, `SECRET_NAME="wp_credentials"`
- Consumes: `ctx.store.create/get/query/update/delete` and `ctx.secrets.get/set`. Confirm exact `ctx.store` method names against `_digests/02-concepts-a.md`; adjust if e.g. upsert differs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage.py
from imperal_sdk.testing import MockContext, MockSecretStore
import storage


async def test_save_and_list_site_records():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "url": "https://x.com", "status": "connected"})
    rows = await storage.list_site_records(ctx)
    assert any(r["id"] == "x-com" for r in rows)


async def test_credential_roundtrip_and_delete():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.set_credential(ctx, "x-com", "pw-1")
    assert await storage.get_credential(ctx, "x-com") == "pw-1"
    await storage.delete_credential(ctx, "x-com")
    assert await storage.get_credential(ctx, "x-com") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'storage'`.

- [ ] **Step 3: Write `storage.py`**

```python
import json

SITES_COLLECTION = "sites"
SECRET_NAME = "wp_credentials"


async def list_site_records(ctx):
    return await ctx.store.query(SITES_COLLECTION, limit=100)


async def get_site_record(ctx, site_id):
    return await ctx.store.get(SITES_COLLECTION, site_id)


async def save_site_record(ctx, record):
    existing = await ctx.store.get(SITES_COLLECTION, record["id"])
    if existing:
        await ctx.store.update(SITES_COLLECTION, record["id"], record)
    else:
        await ctx.store.create(SITES_COLLECTION, record, id=record["id"])


async def delete_site_record(ctx, site_id):
    await ctx.store.delete(SITES_COLLECTION, site_id)


async def _load_map(ctx):
    raw = await ctx.secrets.get(SECRET_NAME)
    return json.loads(raw) if raw else {}


async def _save_map(ctx, data):
    await ctx.secrets.set(SECRET_NAME, json.dumps(data))


async def get_credential(ctx, site_id):
    return (await _load_map(ctx)).get(site_id)


async def set_credential(ctx, site_id, app_password):
    data = await _load_map(ctx)
    data[site_id] = app_password
    await _save_map(ctx, data)


async def delete_credential(ctx, site_id):
    data = await _load_map(ctx)
    data.pop(site_id, None)
    await _save_map(ctx, data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (2 tests). If `ctx.store.create` signature differs (e.g. no `id=` kwarg), adjust per `_digests/02-concepts-a.md` and re-run.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add site-record and credential-map storage"
```

---

### Task 5: `connect_site` — connection-form action (write)

**Files:**
- Create: `Apps/WP Site Connector/src/handlers_connect.py`
- Modify: `Apps/WP Site Connector/src/app.py` (import handlers_connect so its decorators register; remove `ping`)
- Test: `Apps/WP Site Connector/src/tests/test_connect.py`

**Interfaces:**
- Produces: `connect_site` registered via `@chat.function(action_type="write", ...)` used only as the panel form action. Validates via `GET /wp-json/wp/v2/users/me`, then `save_site_record` + `set_credential`. Returns `ActionResult.success(Site, refresh_panels=["dashboard"])` or `.error(...)`.
- Consumes: Task 2 `ConnectSiteParams`, `Site`; Task 3 `normalize_base_url`, `site_id_from_url`, `wp_get`, `wp_error_message`; Task 4 `save_site_record`, `set_credential`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connect.py
from imperal_sdk.testing import MockContext, MockSecretStore
from app import chat  # registers handlers via import
import handlers_connect as hc
import storage
from models import ConnectSiteParams


async def _ctx():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    return ctx


async def test_connect_rejects_non_https():
    ctx = await _ctx()
    r = await hc.connect_site(ctx, ConnectSiteParams(url="http://x.com", username="a", app_password="p"))
    assert r.status != "success"


async def test_connect_success_stores_site_and_credential():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", json={"name": "Admin"}, status_code=200)
    r = await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="pw"))
    assert r.status == "success"
    assert (await storage.get_site_record(ctx, "x-com"))["status"] == "connected"
    assert await storage.get_credential(ctx, "x-com") == "pw"


async def test_connect_bad_credentials_returns_error_and_stores_nothing():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", json={}, status_code=401)
    r = await hc.connect_site(ctx, ConnectSiteParams(url="https://x.com", username="admin", app_password="bad"))
    assert r.status != "success"
    assert await storage.get_site_record(ctx, "x-com") is None
    assert await storage.get_credential(ctx, "x-com") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_connect.py -v`
Expected: FAIL — `No module named 'handlers_connect'`.

- [ ] **Step 3: Write `handlers_connect.py`** (the `connect_site` half)

```python
from app import chat
from models import ConnectSiteParams, Site
from wp_client import normalize_base_url, site_id_from_url, wp_get, wp_error_message
import storage


@chat.function(
    description="Connect a WordPress site using its URL and an Application Password. Used by the connection form only.",
    action_type="write",
    data_model=Site,
    effects=["wp.connect"],
)
async def connect_site(ctx, params: ConnectSiteParams):
    try:
        base_url = normalize_base_url(params.url)
    except ValueError:
        return ActionResult.error("Site URL must start with https://", retryable=False)

    site_id = site_id_from_url(base_url)
    try:
        r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                         username=params.username, app_password=params.app_password)
    except Exception as e:
        await ctx.log(f"connect_site http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — check the URL and try again.", retryable=True)

    if r.status_code != 200:
        return ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500 or r.status_code == 429)

    name = (r.json() or {}).get("name") or base_url
    record = {"id": site_id, "name": name, "url": base_url, "username": params.username,
              "status": "connected", "last_checked": await _now(ctx)}
    await storage.save_site_record(ctx, record)
    await storage.set_credential(ctx, site_id, params.app_password)

    site = Site(id=site_id, title=name, kind="wp_site", url=base_url,
                username=params.username, status="connected", last_checked=record["last_checked"])
    return ActionResult.success(site, summary=f"Connected {name}", refresh_panels=["dashboard"])


async def _now(ctx):
    try:
        return await ctx.time.now_iso()
    except Exception:
        return None
```

Add the missing import at the top: `from imperal_sdk import ActionResult`. (Confirm `ctx.time` API in `_digests/02-concepts-a.md`; `_now` degrades to `None` if unavailable.)

- [ ] **Step 4: Update `app.py`** — remove `ping` and import handlers so decorators run

Replace the `ping` block in `app.py` with:
```python
# Handlers register themselves on import (must come AFTER ext/chat are defined).
import handlers_connect  # noqa: E402,F401
```
And delete the `_PingResult`, `_PingParams`, and `ping` definitions.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_connect.py -v && imperal validate .`
Expected: 3 tests PASS; validate 0 ERRORs.

- [ ] **Step 6: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add connect_site form action with credential validation"
```

---

### Task 6: `forget_site` — disconnect (destructive)

**Files:**
- Modify: `Apps/WP Site Connector/src/handlers_connect.py`
- Test: `Apps/WP Site Connector/src/tests/test_forget.py`

**Interfaces:**
- Produces: `forget_site` via `@chat.function(action_type="destructive", ...)` taking only `SiteIdParams`. Removes the site record and its credential. The KAV confirmation card fires automatically — no manual confirm.
- Consumes: Task 2 `SiteIdParams`, `Site`; Task 4 `get_site_record`, `delete_site_record`, `delete_credential`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_forget.py
from imperal_sdk.testing import MockContext, MockSecretStore
import handlers_connect as hc
import storage
from models import SiteIdParams


async def test_forget_removes_record_and_credential():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")

    r = await hc.forget_site(ctx, SiteIdParams(site_id="x-com"))
    assert r.status == "success"
    assert await storage.get_site_record(ctx, "x-com") is None
    assert await storage.get_credential(ctx, "x-com") is None


async def test_forget_unknown_site_errors():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    r = await hc.forget_site(ctx, SiteIdParams(site_id="nope"))
    assert r.status != "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forget.py -v`
Expected: FAIL — `AttributeError: module 'handlers_connect' has no attribute 'forget_site'`.

- [ ] **Step 3: Append `forget_site` to `handlers_connect.py`**

```python
from models import SiteIdParams  # add to existing imports


@chat.function(
    description="Disconnect a WordPress site and delete its stored credential.",
    action_type="destructive",
    data_model=Site,
    effects=["wp.disconnect"],
)
async def forget_site(ctx, params: SiteIdParams):
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error("No connected site with that id.", retryable=False)
    await storage.delete_site_record(ctx, params.site_id)
    await storage.delete_credential(ctx, params.site_id)
    site = Site(id=params.site_id, title=record.get("name", params.site_id), kind="wp_site",
                url=record.get("url", ""), username=record.get("username", ""), status="disconnected")
    return ActionResult.success(site, summary=f"Disconnected {record.get('name', params.site_id)}", refresh_panels=["dashboard"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_forget.py -v && imperal validate .`
Expected: 2 tests PASS; validate 0 ERRORs.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add destructive forget_site disconnect"
```

---

### Task 7: `list_sites` (read)

**Files:**
- Create: `Apps/WP Site Connector/src/handlers_read.py`
- Modify: `Apps/WP Site Connector/src/app.py` (import handlers_read)
- Test: `Apps/WP Site Connector/src/tests/test_list_sites.py`

**Interfaces:**
- Produces: `list_sites` via `@chat.function(action_type="read", data_model=sdl.EntityList[Site])` → `ActionResult.success(EntityList[Site])`.
- Consumes: Task 2 `Site`; Task 4 `list_site_records`. Confirm `sdl.EntityList[T]` construction in `_digests/05-sdk-b.md`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_list_sites.py
from imperal_sdk.testing import MockContext
import handlers_read as hr
import storage
from models import _NoParams  # defined in this task


async def test_list_sites_returns_connected_sites():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "a", "status": "connected"})
    r = await hr.list_sites(ctx, _NoParams())
    assert r.status == "success"
    titles = [e.title for e in r.data.items]
    assert "X" in titles
```

- [ ] **Step 2: Add `_NoParams` to `models.py`**

```python
class _NoParams(BaseModel):
    pass
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_list_sites.py -v`
Expected: FAIL — `No module named 'handlers_read'`.

- [ ] **Step 4: Write `handlers_read.py`** (`list_sites` only)

```python
from imperal_sdk import ActionResult, sdl
from app import chat
from models import _NoParams, Site
import storage


@chat.function(description="List the WordPress sites the user has connected.",
               action_type="read", data_model=sdl.EntityList[Site])
async def list_sites(ctx, params: _NoParams):
    rows = await storage.list_site_records(ctx)
    sites = [Site(id=r["id"], title=r.get("name", r["id"]), kind="wp_site",
                  url=r.get("url", ""), username=r.get("username", ""),
                  status=r.get("status", "connected"), last_checked=r.get("last_checked"))
             for r in rows]
    return ActionResult.success(sdl.EntityList[Site](items=sites), summary=f"{len(sites)} site(s) connected")
```

(Confirm the `EntityList` field name — `items` vs `entities` — in `_digests/05-sdk-b.md`; align the test in Step 1 and the code here.)

- [ ] **Step 5: Update `app.py`** — add `import handlers_read  # noqa: E402,F401` after `handlers_connect`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_list_sites.py -v && imperal validate .`
Expected: PASS; validate 0 ERRORs.

- [ ] **Step 7: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add list_sites read tool"
```

---

### Task 8: `list_posts` / `list_pages` / `list_media` (read, shared helper)

**Files:**
- Modify: `Apps/WP Site Connector/src/handlers_read.py`
- Test: `Apps/WP Site Connector/src/tests/test_list_content.py`

**Interfaces:**
- Produces: `list_posts`/`list_pages` (`ListContentParams` → `EntityList[Post]`/`EntityList[Page]`), `list_media` (`ListMediaParams` → `EntityList[MediaItem]`). All `action_type="read"`. Internal helper `_authed(ctx, site_id)` → `(base_url, username, app_password)` or raises a handled error.
- Consumes: Task 2 entities/params; Task 3 `wp_get`, `wp_error_message`; Task 4 `get_site_record`, `get_credential`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_list_content.py
from imperal_sdk.testing import MockContext, MockSecretStore
import handlers_read as hr
import storage
from models import ListContentParams, ListMediaParams


async def _connected_ctx():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_list_posts_maps_rest_payload():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts",
                      json=[{"id": 1, "title": {"rendered": "Hello"}, "status": "publish", "link": "https://x.com/hello", "date": "2026-06-16T00:00:00"}],
                      status_code=200)
    r = await hr.list_posts(ctx, ListContentParams(site_id="x-com"))
    assert r.status == "success"
    assert r.data.items[0].title == "Hello" and r.data.items[0].link.endswith("/hello")


async def test_list_posts_unknown_site_errors():
    ctx = await _connected_ctx()
    r = await hr.list_posts(ctx, ListContentParams(site_id="missing"))
    assert r.status != "success"


async def test_list_media_maps_source_url():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media",
                      json=[{"id": 9, "title": {"rendered": "img"}, "source_url": "https://x.com/img.png", "mime_type": "image/png"}],
                      status_code=200)
    r = await hr.list_media(ctx, ListMediaParams(site_id="x-com"))
    assert r.data.items[0].url.endswith("img.png") and r.data.items[0].mime_type == "image/png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_list_content.py -v`
Expected: FAIL — `AttributeError: module 'handlers_read' has no attribute 'list_posts'`.

- [ ] **Step 3: Append to `handlers_read.py`**

```python
from models import ListContentParams, ListMediaParams, Post, Page, MediaItem
from wp_client import wp_get, wp_error_message


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, "No connected site with that id."
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return None, "Stored credential is missing — reconnect the site."
    return (record["url"], record["username"], pw), None


def _title(item):
    t = item.get("title")
    return t.get("rendered") if isinstance(t, dict) else (t or str(item.get("id")))


async def _fetch(ctx, site_id, path, params):
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, ActionResult.error(err, retryable=False)
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception as e:
        await ctx.log(f"{path} http error: {e}", level="error")
        return None, ActionResult.error("Could not reach the site — try again.", retryable=True)
    if r.status_code != 200:
        return None, ActionResult.error(wp_error_message(r.status_code), retryable=r.status_code >= 500 or r.status_code == 429)
    return r.json(), None


@chat.function(description="List recent posts on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[Post])
async def list_posts(ctx, params: ListContentParams):
    q = {"per_page": params.limit}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/posts", q)
    if err:
        return err
    items = [Post(id=str(p["id"]), title=_title(p), kind="wp_post",
                  status=p.get("status", ""), link=p.get("link", ""), date=p.get("date")) for p in data]
    return ActionResult.success(sdl.EntityList[Post](items=items), summary=f"{len(items)} post(s)")


@chat.function(description="List pages on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[Page])
async def list_pages(ctx, params: ListContentParams):
    q = {"per_page": params.limit}
    if params.search:
        q["search"] = params.search
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/pages", q)
    if err:
        return err
    items = [Page(id=str(p["id"]), title=_title(p), kind="wp_page",
                  status=p.get("status", ""), link=p.get("link", ""), date=p.get("date")) for p in data]
    return ActionResult.success(sdl.EntityList[Page](items=items), summary=f"{len(items)} page(s)")


@chat.function(description="List media library items on a connected WordPress site.",
               action_type="read", data_model=sdl.EntityList[MediaItem])
async def list_media(ctx, params: ListMediaParams):
    data, err = await _fetch(ctx, params.site_id, "/wp-json/wp/v2/media", {"per_page": params.limit})
    if err:
        return err
    items = [MediaItem(id=str(m["id"]), title=_title(m), kind="wp_media",
                       url=m.get("source_url", ""), mime_type=m.get("mime_type", "")) for m in data]
    return ActionResult.success(sdl.EntityList[MediaItem](items=items), summary=f"{len(items)} media item(s)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_list_content.py -v && imperal validate .`
Expected: 3 tests PASS; validate 0 ERRORs.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add list_posts/list_pages/list_media read tools"
```

---

### Task 9: `get_site_health` (read, best-effort + degradation)

**Files:**
- Modify: `Apps/WP Site Connector/src/handlers_read.py`
- Test: `Apps/WP Site Connector/src/tests/test_health.py`

**Interfaces:**
- Produces: `get_site_health(SiteIdParams) -> SiteHealth`. `reachable`/`auth_ok` from `GET /wp-json/wp/v2/users/me`; `content_counts` from `X-WP-Total` headers of posts/pages/media (`per_page=1`); `ssl_valid=True` (request reached over https); `plugin_updates_available`/`php_version` left at the `VNEXT` marker.
- Consumes: Task 2 `SiteIdParams`, `SiteHealth`, `VNEXT`; Task 8 `_authed`; Task 3 `wp_get`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_health.py
from imperal_sdk.testing import MockContext, MockSecretStore
import handlers_read as hr
import storage
from models import SiteIdParams


async def _ctx():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_health_reports_available_fields_and_marks_vnext():
    ctx = await _ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", json={"name": "Admin"}, status_code=200)
    for kind in ("posts", "pages", "media"):
        ctx.http.mock_get(f"https://x.com/wp-json/wp/v2/{kind}", json=[], status_code=200, headers={"X-WP-Total": "5"})
    r = await hr.get_site_health(ctx, SiteIdParams(site_id="x-com"))
    h = r.data
    assert h.reachable and h.auth_ok and h.ssl_valid
    assert h.content_counts["posts"] == 5
    assert "vNext" in h.plugin_updates_available and "vNext" in h.php_version
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`
Expected: FAIL — `AttributeError: ... 'get_site_health'`.

- [ ] **Step 3: Append `get_site_health` to `handlers_read.py`**

```python
from models import SiteIdParams, SiteHealth


def _total(r):
    try:
        return int(r.headers.get("X-WP-Total", 0))
    except (TypeError, ValueError):
        return 0


@chat.function(description="Report read-only health for a connected WordPress site.",
               action_type="read", data_model=SiteHealth)
async def get_site_health(ctx, params: SiteIdParams):
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth

    counts = {}
    auth_ok = False
    reachable = False
    try:
        me = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me", username=username, app_password=pw)
        reachable = True
        auth_ok = me.status_code == 200
        for kind in ("posts", "pages", "media"):
            cr = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{kind}", username=username, app_password=pw, params={"per_page": 1})
            counts[kind] = _total(cr)
    except Exception as e:
        await ctx.log(f"health http error: {e}", level="error")

    health = SiteHealth(id=params.site_id, title=f"Health for {params.site_id}", kind="wp_site_health",
                        reachable=reachable, auth_ok=auth_ok, ssl_valid=base_url.startswith("https://"),
                        content_counts=counts)
    return ActionResult.success(health, summary="Site health (read-only)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_health.py -v && imperal validate .`
Expected: PASS; validate 0 ERRORs.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add best-effort get_site_health with vNext degradation"
```

---

### Task 10: `skeleton.py` — ambient site counts

**Files:**
- Create: `Apps/WP Site Connector/src/skeleton.py`
- Modify: `Apps/WP Site Connector/src/app.py` (import skeleton)
- Test: `Apps/WP Site Connector/src/tests/test_skeleton.py`

**Interfaces:**
- Produces: an `@ext.skeleton` handler returning `{"response": {"sites_connected": int}}` (small ambient context). Confirm the exact skeleton return contract (`{"response": {...}}`) and decorator signature in `_digests/02-concepts-a.md` / tutorial.
- Consumes: Task 4 `list_site_records`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py
from imperal_sdk.testing import MockContext
import skeleton
import storage


async def test_skeleton_counts_connected_sites():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    out = await skeleton.sites_overview(ctx)
    assert out["response"]["sites_connected"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skeleton.py -v`
Expected: FAIL — `No module named 'skeleton'`.

- [ ] **Step 3: Write `skeleton.py`**

```python
from app import ext
import storage


@ext.skeleton("sites_overview")
async def sites_overview(ctx):
    rows = await storage.list_site_records(ctx)
    return {"response": {"sites_connected": len(rows)}}
```

(Confirm `@ext.skeleton` name/arg against `_digests/04-sdk-a.md`; some versions take `(name)`, some `(name, ttl=...)`.)

- [ ] **Step 4: Update `app.py`** — add `import skeleton  # noqa: E402,F401`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_skeleton.py -v && imperal validate .`
Expected: PASS; validate 0 ERRORs.

- [ ] **Step 6: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add ambient site-count skeleton"
```

---

### Task 11: `panels.py` — dashboard, detail, connection form

**Files:**
- Create: `Apps/WP Site Connector/src/panels.py`
- Modify: `Apps/WP Site Connector/src/app.py` (import panels)
- Test: `Apps/WP Site Connector/src/tests/test_panels.py`

**Interfaces:**
- Produces three `@ext.panel` handlers: `dashboard` (`slot="left"` — site list + "Connect site" button), `detail` (`slot="center", center_overlay=True` — header + `ui.Tabs` Posts/Pages/Media + health card; returns `ui.Empty()` when no `site_id`), `connect_form` (`slot="center", center_overlay=True` — `ui.Form` with `ui.Input(type="url")`, `ui.Input` username, `ui.Password`, `ui.Tooltip` on every label, submit → `connect_site`).
- Consumes: Task 4 `list_site_records`; the `ui.*` primitives (confirm names/props in `_digests/05-sdk-b.md`); `connect_site` / `detail` panel ids for `ui.Call`.

- [ ] **Step 1: Write the failing test** (structural invariants — panels must never return `None`, form must contain a Password field)

```python
# tests/test_panels.py
from imperal_sdk.testing import MockContext
import panels
import storage


def _has_node(node, type_name):
    found = [False]
    def walk(n):
        if found[0] or n is None:
            return
        if getattr(n, "type", getattr(type(n), "__name__", "")) == type_name or type(n).__name__ == type_name:
            found[0] = True
            return
        for child in getattr(n, "children", []) or []:
            walk(child)
    walk(node)
    return found[0]


async def test_dashboard_renders_node_not_none():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    node = await panels.dashboard(ctx)
    assert node is not None


async def test_detail_returns_empty_when_no_site():
    ctx = MockContext()
    node = await panels.detail(ctx, site_id=None)
    assert node is not None  # must be ui.Empty(), never None


async def test_connect_form_has_password_field():
    ctx = MockContext()
    node = await panels.connect_form(ctx)
    assert _has_node(node, "Password")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_panels.py -v`
Expected: FAIL — `No module named 'panels'`.

- [ ] **Step 3: Write `panels.py`** (align `ui.*` names + the `active_tab`/`on_click` wiring with `_digests/05-sdk-b.md`)

```python
from imperal_sdk import ui
from app import ext
import storage


@ext.panel("dashboard", slot="left")
async def dashboard(ctx):
    rows = await storage.list_site_records(ctx)
    items = [
        ui.ListItem(
            title=r.get("name", r["id"]),
            children=[ui.Badge(text=r.get("status", "connected"))],
            on_click=ui.Call("__panel__detail", site_id=r["id"]),
        )
        for r in rows
    ]
    return ui.Stack(children=[
        ui.Button(label="+ Connect site", on_click=ui.Call("__panel__connect_form")),
        ui.List(children=items) if items else ui.Empty(),
    ])


@ext.panel("detail", slot="center", center_overlay=True)
async def detail(ctx, site_id=None, active_tab="posts"):
    if not site_id:
        return ui.Empty()
    record = await storage.get_site_record(ctx, site_id) or {}
    return ui.Stack(children=[
        ui.Section(title=record.get("name", site_id)),
        ui.Tabs(active=active_tab, children=[
            ui.Tab(id="posts", title="Posts"),
            ui.Tab(id="pages", title="Pages"),
            ui.Tab(id="media", title="Media"),
        ]),
        ui.Card(title="Health", children=[ui.Button(label="Refresh health", on_click=ui.Call("get_site_health", site_id=site_id))]),
    ])


@ext.panel("connect_form", slot="center", center_overlay=True)
async def connect_form(ctx):
    return ui.Form(action="connect_site", submit_label="Connect", children=[
        ui.Tooltip(text="The site's full address, e.g. https://example.com",
                   children=[ui.Input(param_name="url", label="Site URL", type="url")]),
        ui.Tooltip(text="The WordPress username that created the Application Password",
                   children=[ui.Input(param_name="username", label="Username")]),
        ui.Tooltip(text="Create this under Users → Profile → Application Passwords in WordPress",
                   children=[ui.Password(param_name="app_password", label="Application Password")]),
    ])
```

- [ ] **Step 4: Update `app.py`** — add `import panels  # noqa: E402,F401`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_panels.py -v && imperal validate .`
Expected: 3 tests PASS; validate 0 ERRORs. (If `ui.*` prop names differ, fix per the digest and re-run — the test only asserts node presence so it is resilient to minor prop renames.)

- [ ] **Step 6: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: add dashboard, detail, and connection-form panels"
```

---

### Task 12: Wire-up, full validation, and build

**Files:**
- Modify: `Apps/WP Site Connector/src/app.py` (declare the `wp_credentials` secret; confirm final import order)
- Test: full suite

**Interfaces:**
- Produces: a buildable extension — `wp_credentials` secret declared, all handlers/panels/skeleton registered, `imperal.json` generated.
- Consumes: everything above. Confirm `@ext.secret` signature in `_digests/04-sdk-a.md`.

- [ ] **Step 1: Declare the credentials secret in `app.py`** (after `ext` is defined, before handler imports)

```python
ext.secret(
    "wp_credentials",
    "JSON map of {site_id: WordPress Application Password} for connected sites.",
    write_mode="both",
    max_bytes=16384,
)(lambda: None)
```

(If your SDK version uses the bare `@ext.secret(...)` decorator form, adapt — see the `handle-user-api-keys` recipe in `_digests/07-recipes.md`.)

- [ ] **Step 2: Verify final `app.py` import order** — `ext`/`chat` defined → secret declared → `import handlers_connect, handlers_read, skeleton, panels`. Open `app.py` and confirm.

- [ ] **Step 3: Run the full test suite**

Run: `cd "Apps/WP Site Connector/src" && . .venv/bin/activate && pytest -v`
Expected: every test from Tasks 2–11 PASSES (≥1 per `@chat.function`).

- [ ] **Step 4: Validate and build**

Run:
```bash
python -m py_compile *.py
imperal validate .
imperal build .
```
Expected: `validate` 0 ERRORs; `build` produces `imperal.json`. Open `imperal.json` and confirm it lists the 6 tools (`connect_site`, `forget_site`, `list_sites`, `list_posts`, `list_pages`, `list_media`, `get_site_health`), the `wp_credentials` secret, 3 panels, and the skeleton.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WP Site Connector" && git add -A && git commit -m "feat: declare wp_credentials secret and finalize buildable v1 extension"
```

---

## Self-Review

**Spec coverage** (spec §→task): §2 goals → Tasks 5–9, 11; §3 files → Task 1 + per-task creates; §4 store+secret → Task 4; §5 security (no-LLM-arg, scoping, https, no-log) → Global Constraints + Tasks 5/8; §6 read tools → Tasks 7–9; §7 connect flow → Task 5 + Task 11 form; §8 disconnect → Task 6; §9 panels → Task 11; §10 skeleton → Task 10; §11 health degradation → Task 9; §12 errors → Task 3 + per-handler; §13 manifest/validators → Tasks 1 & 12; §14 acceptance → covered by the test suite. No gaps.

**Placeholder scan:** No TBD/TODO; every code step has real code. The only deferred items are explicit "confirm signature against `_digests/...`" notes — intentional, because the SDK is the source of truth and is not installed at plan-writing time.

**Type consistency:** `EntityList[...]` accessed as `.items` in tests and code (Task 7 flags the one place to align if the SDK field name differs). `ActionResult` uses `.status == "success"` and `.data` consistently. `_authed` (Task 8) reused by Task 9. `Site/Post/Page/MediaItem/SiteHealth` fields match between `models.py` and every handler. Constants `SITES_COLLECTION`/`SECRET_NAME` defined once in `storage.py`.

## Known execution risk

The SDK is not installed locally and the system Python is 3.9.6. Task 1 Steps 1–2 are a hard gate: if `imperal-sdk` from PyPI is not the real v5.x Imperal SDK, or no 3.11+ interpreter is available, stop and report. (Resolved at execution: Homebrew `python@3.12` installed; PyPI `imperal-sdk` confirmed genuine, 5.4.2.) All `ctx.*` / `sdl.*` / `ui.*` / `MockContext` signatures used here are from the docs mirror and must be reconciled with the installed SDK as each task runs.
