# Card Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace multi-row site card with a compact single-row layout matching the design mockup, fix the site name showing WP username instead of domain, and add a "Connect new site" placeholder card to the grid.

**Architecture:** Two files change — `panels.py` (card + grid) and `handlers_connect.py` (name fix). Single task: all changes are tightly coupled around the card rendering and are fastest reviewed together.

**Tech Stack:** Python 3.12, `imperal-sdk 5.4.2`, pytest, venv at `src/.venv/`.

## Global Constraints

- Run all commands from `/Users/vladivanco/Documents/Imperal OS/Apps/WordPress Hub/`
- Use `src/.venv/bin/python` and `src/.venv/bin/imperal` — not system Python
- TDD: write failing tests first, then implement
- `imperal build .` + `imperal validate .` → `RESULTS: 0 error(s)` before committing
- `pytest -q` must pass (currently 49 tests) before committing
- Commit format: `feat: <description>`

---

### Task 1: Card redesign, name fix, connect placeholder

**Files:**
- Modify: `panels.py`
- Modify: `handlers_connect.py`
- Modify: `tests/test_panels.py`

**Interfaces:**
- `_site_card(record)` → `ui.Card` with `content=horizontal Stack`, no title/subtitle/footer
- `overview(ctx, search, status_filter)` → grid includes `connect_card` as last item when sites exist
- `connect_site(ctx, params)` → stores `urlparse(base_url).netloc` as `name`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_panels.py`:

```python
async def test_card_shows_domain_not_username():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "admin",
                                         "url": "https://x.com", "status": "connected"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "x.com" in s
    assert "admin" not in s


async def test_card_has_no_subtitle():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "admin",
                                         "url": "https://x.com", "status": "connected"})
    node = await panels.overview(ctx)
    s = str(node)
    # card should not pass url as subtitle= kwarg
    assert "'subtitle': 'https://x.com'" not in s


async def test_overview_grid_has_connect_placeholder():
    ctx = MockContext()
    ctx.secrets = MockSecretStore({})
    await storage.save_site_record(ctx, {"id": "x-com", "name": "admin",
                                         "url": "https://x.com", "status": "connected"})
    node = await panels.overview(ctx)
    s = str(node)
    assert "connect_form" in s   # connect placeholder calls __panel__connect_form
    assert "Connect new site" in s


async def test_connect_placeholder_absent_when_no_sites():
    ctx = MockContext()
    node = await panels.overview(ctx)
    s = str(node)
    # Empty state has no connect_card — only the Empty message CTA
    assert "Connect new site" not in s or "No sites" in s
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "/Users/vladivanco/Documents/Imperal OS/Apps/WordPress Hub" && src/.venv/bin/python -m pytest tests/test_panels.py -q 2>&1 | tail -5
```

Expected: 4 failures — assertions not yet satisfied.

- [ ] **Step 3: Replace `_site_card` in `panels.py`**

Find and replace the entire `_site_card` function (from `def _site_card(record):` through its closing `return` line):

```python
def _site_card(record):
    from urllib.parse import urlparse
    site_id = record.get("id", "")
    url = record.get("url", "")
    name = urlparse(url).netloc or record.get("name", site_id)
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
        content=ui.Stack(direction="h", justify="between", align="center", children=[
            ui.Stack(direction="h", gap=2, align="center", children=[
                ui.Badge(label="", color="green" if is_ok else "red"),
                ui.Text(name),
            ]),
            ui.Stack(direction="h", gap=1, children=[refresh_btn, menu]),
        ]),
        on_click=ui.Call("__panel__detail", site_id=site_id),
    )
```

- [ ] **Step 4: Add connect placeholder card to grid in `panels.py`**

In the `overview` handler, find the `else` branch that builds the grid:

```python
    else:
        grid = ui.Grid(columns=3, gap=4, children=[_site_card(r) for r in filtered])
```

Replace with:

```python
    else:
        connect_card = ui.Card(
            content=ui.Stack(direction="v", align="center", justify="center", gap=2, children=[
                ui.Button("", icon="Plus", variant="ghost", size="sm",
                          on_click=ui.Call("__panel__connect_form")),
                ui.Text("Connect new site"),
            ]),
            on_click=ui.Call("__panel__connect_form"),
        )
        grid = ui.Grid(columns=3, gap=4,
                       children=[_site_card(r) for r in filtered] + [connect_card])
```

- [ ] **Step 5: Fix site name in `handlers_connect.py`**

Find:
```python
    name = body.get("name") or base_url
```

Replace with:
```python
    from urllib.parse import urlparse
    name = urlparse(base_url).netloc or base_url
```

- [ ] **Step 6: Run all tests**

```bash
cd "/Users/vladivanco/Documents/Imperal OS/Apps/WordPress Hub" && src/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: `53 passed`.

- [ ] **Step 7: Build and validate**

```bash
cd "/Users/vladivanco/Documents/Imperal OS/Apps/WordPress Hub" && src/.venv/bin/imperal build . && src/.venv/bin/imperal validate . 2>&1 | grep -E "error|RESULTS"
```

Expected: `RESULTS: 0 error(s)`.

- [ ] **Step 8: Commit**

```bash
cd "/Users/vladivanco/Documents/Imperal OS/Apps/WordPress Hub" && git add panels.py handlers_connect.py tests/test_panels.py imperal.json && git commit -m "feat: redesign site card — compact single-row layout, domain name, connect placeholder"
```

---

## Self-Review

**Spec coverage:**
- ✅ Single-row card via `ui.Card(content=horizontal Stack)` — Step 3
- ✅ No title/subtitle/footer on card — Step 3 (`_site_card` has no `title=`, `subtitle=`, `footer=` kwargs)
- ✅ Status dot via `ui.Badge(label="", color=...)` — Step 3
- ✅ Domain name via `urlparse(url).netloc` in `_site_card` — Step 3 (fixes existing sites at render time)
- ✅ Domain name fix in `connect_site` — Step 5 (fixes newly connected sites in store)
- ✅ "Connect new site" placeholder card at end of grid — Step 4
- ✅ Placeholder absent when no sites (grid `else` branch only) — Step 4
- ✅ 4 new tests — Step 1

**Placeholder scan:** none.

**Type consistency:**
- `urlparse` imported locally in both `_site_card` and `connect_site` — no module-level import needed, avoids touching import blocks.
- `ui.Call("__panel__connect_form")` — matches existing panel registration in `panels.py`.
- `[_site_card(r) for r in filtered] + [connect_card]` — both are `ui.Card` nodes, valid `ui.Grid` children.
