# Overview Panel — Mockup Align Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the overview panel with the design mockup: 3-column grid, clickable cards with per-card Refresh + Remove menu, heading-variant site count, stretched search + status select dropdown, and a new live `refresh_site` function.

**Architecture:** Three isolated changes — a 2-line bug fix in `handlers_connect.py`, a new `@chat.function` in `handlers_read.py`, and UI changes in `panels.py`. Each task is independently testable and committed separately.

**Tech Stack:** Python 3.12, `imperal-sdk 5.4.2`, pytest, venv at `src/.venv/`.

## Global Constraints

- Run all commands from `Apps/WordPress Hub/` (the extension root).
- Always use `src/.venv/bin/python` and `src/.venv/bin/imperal` — not system Python.
- `imperal validate .` must exit 0 errors before every commit.
- `pytest -q` must pass (currently 42 tests) before every commit.
- Commit message format: `feat: <description>` / `fix: <description>`.

---

### Task 1: Fix `refresh_panels` bug in `handlers_connect.py`

**Files:**
- Modify: `handlers_connect.py`

**Interfaces:**
- No new interfaces. Existing `connect_site` and `forget_site` produce `refresh_panels=["overview"]` instead of `["dashboard"]`.

- [ ] **Step 1: Apply the fix**

In `handlers_connect.py`, find both occurrences of `refresh_panels=["dashboard"]` and change each to `refresh_panels=["overview"]`. There are exactly two — one in `connect_site` and one in `forget_site`.

- [ ] **Step 2: Run tests**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: `42 passed`.

- [ ] **Step 3: Commit**

```bash
cd "Apps/WordPress Hub" && git add handlers_connect.py && git commit -m "fix: refresh overview panel (not dashboard) after connect/forget"
```

---

### Task 2: Add `refresh_site` function

**Files:**
- Modify: `handlers_read.py`
- Modify: `tests/test_list_content.py`

**Interfaces:**
- Produces: `handlers_read.refresh_site(ctx, params: SiteIdParams) -> ActionResult`
  - On 200 from `/wp-json/wp/v2/users/me`: sets `status="connected"`, returns `ActionResult.success(site, summary=..., refresh_panels=["overview"])`
  - On non-200: sets `status="error"`, still returns `ActionResult.success(...)` (status update succeeded)
  - On missing site/credential: returns `ActionResult.error(...)`
- Consumes: `_authed(ctx, site_id)`, `wp_get(...)`, `storage.get_site_record(...)`, `storage.save_site_record(...)`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_list_content.py`:

```python
from models import SiteIdParams


async def test_refresh_site_sets_connected_on_200():
    ctx = await _connected_ctx()
    # site starts as "error"
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com",
                                         "username": "admin", "status": "error"})
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    result = await hr.refresh_site(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    record = await storage.get_site_record(ctx, "x-com")
    assert record["status"] == "connected"


async def test_refresh_site_sets_error_on_401():
    ctx = await _connected_ctx()
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"code": "rest_forbidden"}, 401)
    result = await hr.refresh_site(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"  # function itself succeeded — status was updated
    record = await storage.get_site_record(ctx, "x-com")
    assert record["status"] == "error"


async def test_refresh_site_errors_on_missing_site():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    result = await hr.refresh_site(ctx, SiteIdParams(site_id="no-such-site"))
    assert result.status == "error"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_list_content.py -q 2>&1 | tail -5
```

Expected: `3 failed` — `AttributeError: module 'handlers_read' has no attribute 'refresh_site'`.

- [ ] **Step 3: Implement `refresh_site`**

At the top of `handlers_read.py`, add the datetime import (after the existing `import asyncio` line):

```python
from datetime import datetime, timezone
```

Add this helper function directly above `refresh_site` (after the existing `get_site_health` function):

```python
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@chat.function(
    "refresh_site",
    description="Re-check connectivity and auth for a connected WordPress site and update its stored status.",
    action_type="write",
    data_model=Site,
    effects=["wp.health_check"],
    event="wordpress-hub.refresh_site",
)
async def refresh_site(ctx, params: SiteIdParams) -> ActionResult:
    """Ping the site REST API, update stored status, and refresh the overview panel."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return ActionResult.error(err, retryable=False)
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                         username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"refresh_site http error: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    status = "connected" if r.status_code == 200 else "error"
    record = await storage.get_site_record(ctx, params.site_id) or {}
    await storage.save_site_record(ctx, {**record, "status": status, "last_checked": _now()})
    name = record.get("name", params.site_id)
    site = Site(id=params.site_id, title=name, kind="wp_site",
                url=base_url, username=username, status=status)
    icon = "✅" if status == "connected" else "❌"
    return ActionResult.success(
        site,
        summary=f"{icon} {name}: {status}",
        refresh_panels=["overview"],
    )
```

- [ ] **Step 4: Run all tests**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: `45 passed`.

- [ ] **Step 5: Build and validate**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/imperal build . && src/.venv/bin/imperal validate . 2>&1 | grep -E "error|RESULTS"
```

Expected: `RESULTS: 0 error(s)`.

- [ ] **Step 6: Commit**

```bash
cd "Apps/WordPress Hub" && git add handlers_read.py tests/test_list_content.py imperal.json && git commit -m "feat: add refresh_site — live health check with store update and panel refresh"
```

---

### Task 3: Update overview panel UI

**Files:**
- Modify: `panels.py`
- Modify: `tests/test_panels.py`

**Interfaces:**
- `panels.overview(ctx, search="", status_filter="", **kwargs) -> UINode` — signature unchanged
- `_site_card(record) -> ui.Card` — new shape: `on_click` → detail, footer with Refresh button + Remove menu

- [ ] **Step 1: Write failing tests**

Append to `tests/test_panels.py`:

```python
async def test_overview_card_calls_refresh_site():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha",
                                         "url": "https://a.com", "status": "connected"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "refresh_site" in s


async def test_overview_card_has_remove_menu():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha",
                                         "url": "https://a.com", "status": "connected"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "forget_site" in s


async def test_overview_header_uses_heading_variant():
    ctx = MockContext()
    node = await panels.overview(ctx)
    s = str(node)
    assert "heading" in s


async def test_overview_filter_bar_has_status_select():
    ctx = MockContext()
    node = await panels.overview(ctx)
    s = str(node)
    assert "status_filter" in s
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_panels.py -q 2>&1 | tail -5
```

Expected: `4 failed` — the new assertions are not yet satisfied by the current panel code.

- [ ] **Step 3: Replace `_site_card` in `panels.py`**

Find and replace the entire `_site_card` function (from `def _site_card(record):` through its closing `return` line) with:

```python
def _site_card(record):
    site_id = record.get("id", "")
    name = record.get("name", site_id)
    url = record.get("url", "")
    status = record.get("status", "connected")
    is_ok = status == "connected"
    refresh_btn = ui.Button(
        "", icon="RefreshCw", variant="ghost", size="sm",
        on_click=ui.Call("refresh_site", site_id=site_id),
    )
    menu = ui.Menu(items=[
        {"label": "Remove site", "icon": "Trash2",
         "on_click": ui.Call("forget_site", site_id=site_id)},
    ])
    return ui.Card(
        title=name,
        subtitle=url,
        content=ui.Badge("Connected" if is_ok else "Error",
                         color="green" if is_ok else "red"),
        footer=ui.Stack(direction="h", gap=2, children=[refresh_btn, menu]),
        on_click=ui.Call("__panel__detail", site_id=site_id),
    )
```

- [ ] **Step 4: Update the `overview` handler in `panels.py`**

Inside the `overview` function, make three changes:

**A. Header** — replace:
```python
        ui.Text(f"{total} site{'s' if total != 1 else ''} connected"),
```
with:
```python
        ui.Text(f"{total} site{'s' if total != 1 else ''} connected", variant="heading"),
```

**B. Filter bar** — replace the entire `def _filter_btn(...)` helper and the `filter_bar = ui.Stack(...)` block (from `def _filter_btn` through the closing `])` of `filter_bar`) with:

```python
    filter_bar = ui.Stack(direction="h", gap=2, children=[
        ui.Input(
            placeholder="Search sites… (Enter to filter)",
            param_name="search",
            value=search,
            on_submit=ui.Call("__panel__overview", status_filter=status_filter),
        ),
        ui.Select(
            options=[
                {"value": "",          "label": "All"},
                {"value": "connected", "label": "Connected"},
                {"value": "error",     "label": "Error"},
            ],
            value=status_filter,
            placeholder="All",
            param_name="status_filter",
            on_change=ui.Call("__panel__overview", search=search),
        ),
    ])
```

**C. Grid** — replace `columns=2` with `columns=3`:
```python
        grid = ui.Grid(columns=3, gap=4, children=[_site_card(r) for r in filtered])
```

- [ ] **Step 5: Run all tests**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: `49 passed`.

- [ ] **Step 6: Build and validate**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/imperal build . && src/.venv/bin/imperal validate . 2>&1 | grep -E "error|RESULTS"
```

Expected: `RESULTS: 0 error(s)`.

- [ ] **Step 7: Commit**

```bash
cd "Apps/WordPress Hub" && git add panels.py tests/test_panels.py imperal.json && git commit -m "feat: align overview panel with mockup — 3-col grid, card on_click, refresh+menu footer, heading count, status select"
```

---

## Self-Review

**Spec coverage:**
- ✅ 3-column grid — Task 3, Step 4C
- ✅ Card `on_click` → detail — Task 3, Step 3
- ✅ Refresh button → `refresh_site` — Task 3, Step 3
- ✅ Remove menu → `forget_site` — Task 3, Step 3
- ✅ Header `variant="heading"` — Task 3, Step 4A
- ✅ Filter bar: `ui.Input` + `ui.Select(param_name="status_filter")` — Task 3, Step 4B
- ✅ `refresh_site` function — Task 2
- ✅ Bug fix `refresh_panels` — Task 1

**Placeholder scan:** none found.

**Type consistency:**
- `SiteIdParams` used in Task 2 tests matches the import already in `handlers_read.py` and `models.py`.
- `_authed(ctx, site_id)` called in `refresh_site` matches the existing private helper in `handlers_read.py`.
- `storage.save_site_record(ctx, {**record, ...})` — `save_site_record` accepts a dict with an `"id"` key; spreading `record` preserves the `id`. ✅
- `ui.Call("refresh_site", ...)` in `_site_card` matches the function name registered by `@chat.function("refresh_site", ...)`. ✅
- `ui.Call("__panel__overview", search=search)` in the Select `on_change` — `overview` handler accepts `search` kwarg. ✅
- `ui.Call("__panel__overview", status_filter=status_filter)` in Input `on_submit` — `overview` accepts `status_filter` kwarg. ✅
