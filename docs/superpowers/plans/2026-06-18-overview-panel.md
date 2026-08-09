# Overview Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the left-panel site list with a single full-screen center panel that shows a searchable, filterable 2-column grid of site cards.

**Architecture:** Single `@ext.panel("overview", slot="center")` accepts `search` and `status_filter` kwargs; filters sites in Python before rendering; builds a grid as paired horizontal stacks of `ui.Card`. The existing `connect_form` overlay and `detail` panel are kept; `detail` gets a minimal back button so the user can return to the grid.

**Tech Stack:** Python 3.12, `imperal-sdk 5.4.2`, pytest, venv at `src/.venv/`.

## Global Constraints

- Run all commands from `Apps/WordPress Hub/` (repo root for this extension).
- Always use `src/.venv/bin/python` and `src/.venv/bin/imperal` — not system Python.
- `imperal validate .` must exit 0 errors before every commit.
- `pytest -q` must pass (35+ tests) before every commit.
- Commit message format: `feat: <description>` / `fix: <description>`.

---

### Task 1: Update tests — remove dashboard, add overview tests

**Files:**
- Modify: `tests/test_panels.py`

**Interfaces:**
- Consumes: `panels.overview(ctx, search="", status_filter="", **kwargs)` → `UINode`
- Produces: test suite that fails until Task 2 ships the implementation

- [ ] **Step 1: Replace test file contents**

Open `tests/test_panels.py` and replace it entirely with:

```python
from imperal_sdk.testing import MockContext, MockSecretStore
import app  # noqa: F401
import panels
import storage


# ── overview ────────────────────────────────────────────────────────────────

async def test_overview_empty_no_sites():
    ctx = MockContext()
    node = await panels.overview(ctx)
    s = str(node)
    assert "No sites connected" in s or "Connect New Site" in s


async def test_overview_renders_site_cards():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "b-com", "name": "Beta",  "url": "https://b.com", "status": "error"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "Alpha" in s
    assert "Beta" in s


async def test_overview_search_filter():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "b-com", "name": "Beta",  "url": "https://b.com", "status": "connected"})
    node = await panels.overview(ctx, search="Alpha")
    s = str(node)
    assert "Alpha" in s
    assert "Beta" not in s


async def test_overview_status_filter_connected():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "b-com", "name": "Beta",  "url": "https://b.com", "status": "error"})
    node = await panels.overview(ctx, status_filter="connected")
    s = str(node)
    assert "Alpha" in s
    assert "Beta" not in s


async def test_overview_status_filter_error():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "b-com", "name": "Beta",  "url": "https://b.com", "status": "error"})
    node = await panels.overview(ctx, status_filter="error")
    s = str(node)
    assert "Beta" in s
    assert "Alpha" not in s


async def test_overview_no_match_shows_empty():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    node = await panels.overview(ctx, search="zzz")
    s = str(node)
    assert "match" in s.lower() or "No sites" in s


async def test_overview_site_count_in_header():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "b-com", "name": "Beta",  "url": "https://b.com", "status": "connected"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "2" in s  # total count in header


# ── connect_form ─────────────────────────────────────────────────────────────

async def test_connect_form_has_password_field():
    ctx = MockContext()
    node = await panels.connect_form(ctx)
    s = str(node)
    assert "app_password" in s and "'type': 'password'" in s


# ── detail ───────────────────────────────────────────────────────────────────

async def test_detail_returns_empty_when_no_site():
    ctx = MockContext()
    node = await panels.detail(ctx, site_id=None)
    assert node is not None


async def test_detail_has_back_button():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    node = await panels.detail(ctx, site_id="x-com")
    s = str(node)
    assert "__panel__overview" in s  # back button points to overview
```

- [ ] **Step 2: Run tests to verify they fail as expected**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_panels.py -q 2>&1 | tail -10
```

Expected: `AttributeError: module 'panels' has no attribute 'overview'` and `__panel__overview` assertion failures.

---

### Task 2: Implement `overview` panel + back button in `detail`

**Files:**
- Modify: `panels.py`

**Interfaces:**
- Produces: `panels.overview(ctx, search="", status_filter="", **kwargs) -> UINode`
- Consumes: `storage.list_site_records(ctx) -> list[dict]` (each dict has `id`, `name`, `url`, `status`)
- Consumes: `ui.Stack`, `ui.Card`, `ui.Button`, `ui.Input`, `ui.Badge`, `ui.Text`, `ui.Empty`, `ui.Call` from `imperal_sdk.ui`

- [ ] **Step 1: Open `panels.py` and make these changes**

**A. Delete the entire `dashboard` handler** (lines roughly `@ext.panel("dashboard", ...)` through the closing `return root`). Remove it completely.

**B. Add `_site_card` helper and `overview` handler** — insert before `_field`:

```python
def _site_card(record):
    site_id = record.get("id", "")
    name = record.get("name", site_id)
    url = record.get("url", "")
    status = record.get("status", "connected")
    is_ok = status == "connected"
    return ui.Card(
        title=name,
        subtitle=url,
        content=ui.Badge("Connected" if is_ok else "Error",
                         color="green" if is_ok else "red"),
        footer=ui.Button("View", variant="secondary",
                         on_click=ui.Call("__panel__detail", site_id=site_id)),
    )


@ext.panel("overview", slot="center", title="WP Sites")
async def overview(ctx, search="", status_filter="", **kwargs):
    """Single-panel monitoring overview: searchable, filterable 2-column grid of site cards."""
    rows = await storage.list_site_records(ctx)
    total = len(rows)

    filtered = [
        r for r in rows
        if (not search or search.lower() in r.get("name", "").lower())
        and (not status_filter or r.get("status", "") == status_filter)
    ]

    # Header
    header = ui.Stack(direction="h", justify="between", children=[
        ui.Text(f"{total} site{'s' if total != 1 else ''} connected"),
        ui.Button("+ Connect New Site", variant="primary",
                  on_click=ui.Call("__panel__connect_form")),
    ])

    # Filter bar
    def _filter_btn(label, value):
        active = (value == "" and not status_filter) or (value and status_filter == value)
        return ui.Button(
            label,
            variant="primary" if active else "secondary",
            on_click=ui.Call("__panel__overview", search=search, status_filter=value),
        )

    filter_bar = ui.Stack(direction="h", gap=2, children=[
        ui.Input(
            placeholder="Search sites… (Enter to filter)",
            param_name="search",
            value=search,
            on_submit=ui.Call("__panel__overview", status_filter=status_filter),
        ),
        ui.Stack(direction="h", gap=1, children=[
            _filter_btn("All", ""),
            _filter_btn("Connected", "connected"),
            _filter_btn("Error", "error"),
        ]),
    ])

    # Grid
    if not rows:
        grid = ui.Empty(message="No sites connected yet. Click + Connect New Site to get started.")
    elif not filtered:
        grid = ui.Empty(message="No sites match your filter.")
    else:
        pairs = [filtered[i:i + 2] for i in range(0, len(filtered), 2)]
        grid = ui.Stack(children=[
            ui.Stack(direction="h", gap=3, children=[_site_card(r) for r in pair])
            for pair in pairs
        ])

    return ui.Stack(gap=4, children=[header, filter_bar, grid])
```

**C. Add back button to `detail` panel** — inside `detail`, find the final `return ui.Stack(...)` and prepend a back button as the first child:

```python
    back_btn = ui.Button("← All sites", variant="secondary",
                         on_click=ui.Call("__panel__overview"))
    return ui.Stack(children=[
        back_btn,
        ui.Section(title=name, children=[
            health_card,
            ui.Button("Disconnect", variant="secondary",
                      on_click=ui.Call("forget_site", site_id=site_id)),
        ]),
        ui.Tabs(tabs=tabs),
    ])
```

- [ ] **Step 2: Run tests**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 3: Build and validate**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/imperal build . && src/.venv/bin/imperal validate . 2>&1 | grep -E "error|RESULTS"
```

Expected: `RESULTS: 0 error(s)`.

- [ ] **Step 4: Commit**

```bash
cd "Apps/WordPress Hub" && git add panels.py tests/test_panels.py imperal.json && git commit -m "feat: replace dashboard with full-screen overview grid panel

- Single center panel: searchable, filterable 2-column card grid
- Header: site count + Connect New Site button
- Filter bar: text search (Enter) + All/Connected/Error status pills
- Site card: name, URL, status badge, View button → detail panel
- detail panel: added ← All sites back button
- Removed: left-panel dashboard handler"
```

---

### Task 3: Push and verify deploy

**Files:** none

- [ ] **Step 1: Push to origin**

```bash
cd "Apps/WordPress Hub" && git push origin main 2>&1 | tail -5
```

Expected: `main -> main` with the new commit hash.

- [ ] **Step 2: Confirm local state is clean**

```bash
cd "Apps/WordPress Hub" && git status -sb | head -2
```

Expected: `## main...origin/main` (no ahead/behind).

---

## Self-Review

**Spec coverage:**
- ✅ Single center panel `overview` — Task 2
- ✅ Header: count + Connect button — Task 2
- ✅ Search input (Enter to filter) — Task 2
- ✅ Status filter buttons (All / Connected / Error) — Task 2
- ✅ 2-column grid via paired horizontal stacks — Task 2
- ✅ Site card: name, URL, status badge, View button — Task 2
- ✅ View → existing `detail` panel — Task 2 (`ui.Call("__panel__detail", site_id=...)`)
- ✅ Remove left panel `dashboard` — Task 2
- ✅ Back navigation from detail → overview — Task 2 (back button)
- ✅ Empty states (no sites, no match) — Task 2
- ✅ Tests updated — Task 1

**Not in scope (confirmed):** detail panel redesign, real-time search, sorting, bulk actions.

**Placeholder scan:** none found.

**Type consistency:**
- `storage.list_site_records(ctx)` → `list[dict]` — used correctly throughout.
- `ui.Call("__panel__overview", search=search, status_filter=value)` — kwarg names match `overview` handler signature.
- `ui.Call("__panel__detail", site_id=site_id)` — matches existing `detail(ctx, site_id=None, **kwargs)`.
