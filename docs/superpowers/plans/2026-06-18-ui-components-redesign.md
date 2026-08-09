# UI Components Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace improvised layout primitives in `overview` and `detail` panels with correct SDK components — `ui.Grid`, `ui.Stats`/`ui.Stat`, `ui.DataTable`, `ui.Page`, `ui.Alert`.

**Architecture:** Single file change (`panels.py`). `overview` gets a one-liner grid fix. `detail` gets a full body rebuild: `ui.Page` wrapper, two `ui.Stats` rows (health + counts), `ui.DataTable` per content tab. `_health_card` helper is deleted. `_content_tab` is rewritten.

**Tech Stack:** Python 3.12, `imperal-sdk 5.4.2`, pytest. Venv at `src/.venv/`.

## Global Constraints

- Run all commands from `Apps/WordPress Hub/` (repo root for this extension).
- Use `src/.venv/bin/python` and `src/.venv/bin/imperal` — not system Python.
- `imperal validate .` must exit 0 errors before every commit.
- All tests must pass before every commit.
- Only `panels.py` and `tests/test_panels.py` change — no other files.

## Verified SDK signatures (from installed SDK 5.4.2 — use these verbatim)

```python
ui.Grid(children: list[UINode], columns: int = 2, gap: int = 3) -> UINode
ui.Stats(children: list[UINode], columns: int = 0) -> UINode
ui.Stat(label: str, value: Any, trend: str = '', icon: str = '', color: str = 'blue') -> UINode
ui.Page(children: list[UINode], title: str = '', subtitle: str = '') -> UINode
ui.DataTable(columns: list[dict], rows: list[dict], on_row_click=None, on_cell_edit=None) -> UINode
ui.DataColumn(key: str, label: str, sortable: bool = True, width: str = '', editable: bool = False, edit_type: str = 'text') -> dict  # returns dict, not UINode
ui.Alert(message: str, title: str = '', type: str = 'info') -> UINode
```

---

### Task 1: Update tests

**Files:**
- Modify: `tests/test_panels.py`

**Interfaces:**
- Produces: updated tests that FAIL until Tasks 2–3 implement the new components.

- [ ] **Step 1: Write the updated test file**

Open `tests/test_panels.py` and make these two changes:

**Change A** — update `test_overview_renders_site_cards` to assert `ui.Grid` is used:

```python
async def test_overview_renders_site_cards():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "a-com", "name": "Alpha", "url": "https://a.com", "status": "connected"})
    await storage.save_site_record(ctx, {"id": "b-com", "name": "Beta",  "url": "https://b.com", "status": "error"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "Alpha" in s
    assert "Beta" in s
    assert "Grid" in s  # ui.Grid(columns=2) must be used, not manual Stack pairs
```

**Change B** — replace `test_detail_renders_site_content` (the one that checked `"Status"` and `"Reachable"`):

```python
async def test_detail_renders_site_content():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "url": "https://x.com", "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "x-com", "pw")
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/posts",
                      [{"id": 1, "title": {"rendered": "Hello"}, "status": "publish", "date": "2026-06-15T00:00:00"}], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/pages", [], 200)
    ctx.http.mock_get("https://x.com/wp-json/wp/v2/media", [], 200)
    node = await panels.detail(ctx, site_id="x-com")
    s = str(node)
    assert "Page" in s        # ui.Page wrapper
    assert "Stats" in s       # ui.Stats for health + counts
    assert "Reachable" in s   # Stat label
    assert "DataTable" in s   # ui.DataTable for content tabs
    assert "Hello" in s       # post title appears in table rows
```

- [ ] **Step 2: Run tests — confirm only the two changed tests fail**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_panels.py -v 2>&1 | tail -20
```

Expected: `test_overview_renders_site_cards` FAILS (`AssertionError: assert 'Grid' in ...`), `test_detail_renders_site_content` FAILS (`assert 'Page' in ...`). All other tests PASS.

- [ ] **Step 3: Commit**

```bash
cd "Apps/WordPress Hub" && git add tests/test_panels.py && git commit -m "test: update panel tests to assert correct SDK components (Grid, Stats, DataTable, Page)"
```

---

### Task 2: Fix overview grid

**Files:**
- Modify: `panels.py` (overview handler only)

**Interfaces:**
- Consumes: `filtered` — `list[dict]` of site records after search/status filter
- Produces: `ui.Grid(columns=2)` wrapping flat list of `_site_card(r)` calls

- [ ] **Step 1: In `panels.py`, find and replace the grid-building block inside `overview`**

Find this block (inside the `else:` branch of the grid section):

```python
        pairs = [filtered[i:i + 2] for i in range(0, len(filtered), 2)]
        grid = ui.Stack(children=[
            ui.Stack(direction="h", gap=3, children=[_site_card(r) for r in pair])
            for pair in pairs
        ])
```

Replace with:

```python
        grid = ui.Grid(columns=2, gap=4, children=[_site_card(r) for r in filtered])
```

- [ ] **Step 2: Run the overview test**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_panels.py::test_overview_renders_site_cards -v 2>&1
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: `test_detail_renders_site_content` still fails (Task 3 not done yet), all others pass.

- [ ] **Step 4: Validate**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/imperal validate . 2>&1 | grep "RESULTS"
```

Expected: `RESULTS: 0 error(s)`.

- [ ] **Step 5: Commit**

```bash
cd "Apps/WordPress Hub" && git add panels.py && git commit -m "feat: replace manual grid pairs with ui.Grid(columns=2) in overview panel"
```

---

### Task 3: Rebuild detail panel

**Files:**
- Modify: `panels.py` (`_content_tab` helper + `detail` handler body; delete `_health_card`)

**Interfaces:**
- Consumes: `posts`, `pages`, `media` — each `list[dict] | None` from `_items_or_none(r)`. None means fetch failed, `[]` means empty, list means data.
- Consumes: `reachable: bool`, `auth_ok: bool`, `ssl_valid: bool`, `name: str`, `base_url: str`
- Produces: `ui.Page` as root node

- [ ] **Step 1: Delete `_health_card` function**

Find and delete the entire `_health_card` function from `panels.py`:

```python
def _health_card(reachable, auth_ok, ssl_valid, counts):
    lines = [...]
    return ui.Card(title="Health (read-only)", content=ui.Stack(children=lines))
```

(The function no longer exists — its logic moves inline into `detail` as `ui.Stats` calls.)

- [ ] **Step 2: Rewrite `_content_tab` helper**

Find the existing `_content_tab` function and replace it entirely:

```python
def _content_tab(label, items):
    if items is None:
        return {"label": label, "content": ui.Alert(
            message="Could not load — check the connection.", type="error")}
    if not items:
        return {"label": label, "content": ui.Empty(message=f"No {label.lower()} found.")}
    if label == "Media":
        columns = [
            ui.DataColumn("title",     "Title", sortable=True),
            ui.DataColumn("mime_type", "Type",  sortable=True),
        ]
        rows = [
            {"title": wp_title(it), "mime_type": it.get("mime_type", "")}
            for it in items
        ]
    else:
        columns = [
            ui.DataColumn("title",  "Title",  sortable=True),
            ui.DataColumn("status", "Status", sortable=True),
            ui.DataColumn("date",   "Date",   sortable=True),
        ]
        rows = [
            {
                "title":  wp_title(it),
                "status": it.get("status", ""),
                "date":   (it.get("date", "") or "")[:10],
            }
            for it in items
        ]
    return {"label": label, "content": ui.DataTable(columns=columns, rows=rows)}
```

- [ ] **Step 3: Rebuild `detail` handler body**

Inside `detail`, find everything after the `asyncio.gather(...)` call (the part that builds the return value) and replace it:

Find from `reachable = me is not None` to the closing `return ui.Stack(...)`:

```python
    reachable = me is not None
    auth_ok = me is not None and me.status_code == 200
    ssl_valid = base_url.startswith("https://")
    posts, pages, media = _items_or_none(posts_r), _items_or_none(pages_r), _items_or_none(media_r)

    def _n(lst): return len(lst) if lst is not None else "?"

    # Status badges row
    status_row = ui.Stack(direction="h", gap=2, children=[...])
    counts_row = ui.Stack(direction="h", gap=3, children=[...])
    health_card = ui.Card(...)

    tabs = [_content_tab("Posts", posts), _content_tab("Pages", pages), _content_tab("Media", media)]

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

Replace with:

```python
    reachable = me is not None
    auth_ok = me is not None and me.status_code == 200
    ssl_valid = base_url.startswith("https://")
    posts, pages, media = _items_or_none(posts_r), _items_or_none(pages_r), _items_or_none(media_r)

    def _n(lst): return len(lst) if lst is not None else "?"

    health_stats = ui.Stats(columns=3, children=[
        ui.Stat(label="Reachable", value="Yes" if reachable else "No",
                color="green" if reachable else "red"),
        ui.Stat(label="Auth",      value="OK" if auth_ok else "Failed",
                color="green" if auth_ok else "red"),
        ui.Stat(label="SSL",       value="HTTPS" if ssl_valid else "HTTP",
                color="green" if ssl_valid else "red"),
    ])
    count_stats = ui.Stats(columns=3, children=[
        ui.Stat(label="Posts", value=_n(posts), color="blue"),
        ui.Stat(label="Pages", value=_n(pages), color="blue"),
        ui.Stat(label="Media", value=_n(media), color="blue"),
    ])
    tabs = [_content_tab("Posts", posts), _content_tab("Pages", pages), _content_tab("Media", media)]
    back_btn = ui.Button("← All sites", variant="secondary",
                         on_click=ui.Call("__panel__overview"))
    return ui.Page(title=name, subtitle=base_url, children=[
        back_btn,
        health_stats,
        count_stats,
        ui.Tabs(tabs=tabs),
    ])
```

- [ ] **Step 4: Run the detail test**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_panels.py::test_detail_renders_site_content tests/test_panels.py::test_detail_has_back_button -v 2>&1
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: all 41 tests PASS.

- [ ] **Step 6: Validate and build**

```bash
cd "Apps/WordPress Hub" && src/.venv/bin/imperal build . && src/.venv/bin/imperal validate . 2>&1 | grep "RESULTS"
```

Expected: `RESULTS: 0 error(s)`.

- [ ] **Step 7: Commit**

```bash
cd "Apps/WordPress Hub" && git add panels.py && git commit -m "feat: rebuild detail panel with ui.Page, ui.Stats, ui.DataTable

- ui.Page(title=site_name, subtitle=url) replaces ui.Section wrapper
- ui.Stats + ui.Stat for health (Reachable/Auth/SSL) and content counts
- ui.DataTable + ui.DataColumn replaces ui.List + ui.ListItem per tab
- ui.Alert(type='error') for failed fetches
- Deleted _health_card helper (replaced by inline Stats)
- Disconnect button removed (read-only monitoring scope)"
```

---

### Task 4: Push

**Files:** none

- [ ] **Step 1: Push to origin**

```bash
cd "Apps/WordPress Hub" && git push origin main 2>&1 | tail -3
```

Expected: `main -> main`.

---

## Self-Review

**Spec coverage:**
- ✅ `overview`: `ui.Grid(columns=2)` — Task 2
- ✅ `detail`: `ui.Page(title, subtitle)` — Task 3
- ✅ `detail`: `ui.Stats` + `ui.Stat` for health (Reachable/Auth/SSL) — Task 3
- ✅ `detail`: `ui.Stats` + `ui.Stat` for content counts (Posts/Pages/Media) — Task 3
- ✅ `detail`: `ui.DataTable` per tab with correct columns — Task 3
- ✅ `detail`: `ui.Alert(type="error")` for failed fetches — Task 3
- ✅ `_health_card` deleted — Task 3 Step 1
- ✅ Disconnect button removed — Task 3 Step 3
- ✅ Tests updated — Task 1

**Placeholder scan:** none.

**Type consistency:**
- `_content_tab` returns `{"label": str, "content": UINode}` — consumed by `ui.Tabs(tabs=[...])` ✓
- `ui.DataColumn(...)` returns `dict` — passed to `ui.DataTable(columns=[dict, ...])` ✓
- `_n(lst)` returns `int | str` — consumed by `ui.Stat(value=Any)` ✓
- `ui.Page(children=[...], title=str, subtitle=str)` — children kwarg is list[UINode] ✓
