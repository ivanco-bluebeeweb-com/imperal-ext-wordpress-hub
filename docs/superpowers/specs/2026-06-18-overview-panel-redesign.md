# WordPress Hub — Overview Panel Redesign

**Date:** 2026-06-18  
**Scope:** Single-panel overview grid (State 1 only). Site detail (State 2) is deferred to next update.

---

## Goal

Replace the current left-panel list + center detail architecture with a single center panel that acts as a full-screen monitoring overview. The user manages 20+ WordPress sites and needs to see all of them at a glance, search instantly, and filter by status.

---

## User

Solo developer managing 20+ WordPress sites. Primary use: monitoring and overview. Read-only for now.

---

## Panel Architecture

**Single panel:** `@ext.panel("overview", slot="center", title="WP Sites")`  
**Removed:** `@ext.panel("dashboard", slot="left")` — deleted entirely.  
**Unchanged:** `connect_form` overlay, `detail` panel, all chat functions.

The `overview` panel has two rendering states controlled by its kwargs:

| kwarg | default | purpose |
|---|---|---|
| `search` | `""` | current search query (filters by site name) |
| `status_filter` | `""` | `""` = All, `"connected"`, `"error"` |

State transitions happen via `ui.Call("__panel__overview", search=..., status_filter=...)`.

---

## Layout

### Header row

`ui.Stack(direction="h", justify="between")`:
- Left: `ui.Text(f"{total} sites connected")` — total = all sites regardless of current filter
- Right: `ui.Button("+ Connect New Site", variant="primary", on_click=ui.Call("__panel__connect_form"))`

### Filter bar

`ui.Stack(direction="h", gap=2)`:
- `ui.Input(placeholder="Search sites… (Enter to filter)", param_name="search", on_submit=ui.Call("__panel__overview", search=<value>, status_filter=status_filter))`
- Status filter buttons in a `ui.Stack(direction="h", gap=1)`:
  - `ui.Button("All", variant="primary" if not status_filter else "secondary", on_click=ui.Call("__panel__overview", search=search, status_filter=""))`
  - `ui.Button("Connected", variant="primary" if status_filter=="connected" else "secondary", on_click=ui.Call("__panel__overview", search=search, status_filter="connected"))`
  - `ui.Button("Error", variant="primary" if status_filter=="error" else "secondary", on_click=ui.Call("__panel__overview", search=search, status_filter="error"))`

**Search note:** `ui.Input` fires `on_submit` on Enter only — real-time per-keystroke filtering is not supported by the SDK. Placeholder text communicates this to the user.

### Site grid

Sites are filtered in Python (not in the SDK) before rendering:

```python
filtered = [r for r in rows
            if (not search or search.lower() in r.get("name","").lower())
            and (not status_filter or r.get("status","") == status_filter)]
```

Grid is built as pairs of cards in horizontal stacks:

```python
rows_of_2 = [filtered[i:i+2] for i in range(0, len(filtered), 2)]
grid = ui.Stack(children=[
    ui.Stack(direction="h", gap=3, children=[_site_card(r) for r in row])
    for row in rows_of_2
])
```

If `filtered` is empty: `ui.Empty(message="No sites match your filter.")`.  
If `rows` is empty (no sites at all): `ui.Empty(message="No sites connected yet. Click + Connect New Site to get started.")`.

### Site card

`ui.Card(title=name, subtitle=url, content=status_badge, footer=view_button)`

- `name`: `record.get("name", site_id)`
- `url`: `record.get("url", "")`
- `status_badge`: `ui.Badge("Connected", color="green")` or `ui.Badge("Error", color="red")` based on `record.get("status")`
- `view_button`: `ui.Button("View", variant="secondary", on_click=ui.Call("__panel__detail", site_id=site_id))`

---

## Files Changed

| File | Change |
|---|---|
| `panels.py` | Delete `dashboard` handler. Add `overview` handler. Keep `detail`, `connect_form`, helpers untouched. |
| `app.py` | No change — `overview` registers via `import panels`. |
| `main.py` | No change. |
| `handlers_*.py` | No change. |
| `tests/test_panels.py` | Remove `test_dashboard_*`. Add `test_overview_renders_grid`, `test_overview_search_filter`, `test_overview_status_filter`, `test_overview_empty_state`. |

---

## Error States

| Situation | UI |
|---|---|
| No sites connected | `ui.Empty` with call-to-action text |
| Filter returns 0 results | `ui.Empty("No sites match your filter.")` |
| Storage error | `ui.Empty("Could not load sites — try refreshing.")` |

---

## Not In Scope (Next Update)

- Site detail screen redesign (State 2)
- Real-time per-keystroke search
- Sorting (by name, status, date)
- Bulk actions
- Status refresh button per card
