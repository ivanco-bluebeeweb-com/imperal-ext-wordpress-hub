# WordPress Hub — Card Redesign

**Date:** 2026-06-18
**Scope:** `_site_card` redesign + site name fix + "Connect new site" grid placeholder.
**Status:** approved (brainstorm)

---

## Goal

Replace the multi-row `ui.Card(title/subtitle/content/footer)` with a compact single-row card
matching the design mockup. Fix the site name showing the WP username instead of the domain.
Add a dashed "Connect new site" placeholder card at the end of the grid.

---

## Changes

### 1. `_site_card` — `panels.py`

Replace the current implementation entirely:

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

Key changes vs current:
- No `title=`, `subtitle=`, `footer=` — everything in `content=`
- Name derived from `urlparse(url).netloc` — fixes existing sites without reconnect
- Status dot: `ui.Badge(label="", color=...)` — empty label renders as colored chip/dot
- Single horizontal row layout

---

### 2. Site name fix in `connect_site` — `handlers_connect.py`

Change:
```python
name = body.get("name") or base_url
```
to:
```python
from urllib.parse import urlparse
name = urlparse(base_url).netloc or base_url
```

Fixes newly connected sites storing the WP user's display name instead of the domain.

---

### 3. "Connect new site" placeholder card — `panels.py`

Add after the grid in the `overview` handler, inside the `else` branch (when `filtered` is not empty):

```python
connect_card = ui.Card(
    content=ui.Stack(direction="v", align="center", justify="center", gap=2, children=[
        ui.Button("", icon="Plus", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__connect_form")),
        ui.Text("Connect new site"),
    ]),
    on_click=ui.Call("__panel__connect_form"),
)
grid = ui.Grid(columns=3, gap=4, children=[_site_card(r) for r in filtered] + [connect_card])
```

Note: SDK does not support dashed card borders — the card renders with a standard border.
The placeholder appears at the end of filtered results (not when filter returns 0 matches).

---

## Files Changed

| File | Change |
|---|---|
| `panels.py` | `_site_card`: full replacement. `overview`: add `connect_card` to grid. |
| `handlers_connect.py` | `connect_site`: use `urlparse(base_url).netloc` for `name`. |
| `tests/test_panels.py` | Update card assertions. Add `test_overview_grid_has_connect_placeholder`. |

---

## Out of Scope

- Dashed border on placeholder card (SDK limitation)
- Existing sites already stored with wrong name auto-migrate (fixed via `urlparse` in `_site_card` at render time — no store migration needed)
