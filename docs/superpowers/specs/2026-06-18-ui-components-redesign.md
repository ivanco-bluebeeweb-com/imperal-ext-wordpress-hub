# WordPress Hub — UI Components Redesign

**Date:** 2026-06-18  
**Scope:** Replace improvised layout primitives in `overview` and `detail` panels with correct SDK components.

---

## Problem

Both panels were built using only ~10 of 40+ available SDK components — working around proper primitives with manual Stack pairs, Badge substitutes for metric cards, and List+ListItem for tabular data. Result: weak visual hierarchy, no real stats display, no sortable tables.

---

## Changes

### `overview` panel — one fix

| Before | After |
|---|---|
| `[filtered[i:i+2] for i in range(...)]` → manual `Stack(direction="h")` pairs | `ui.Grid(columns=2, gap=4)` |

Everything else in `overview` stays: `ui.Page` wrapper is NOT added (panel decorator already sets `title="WP Sites"`; a Page title would duplicate it). Header Row, filter bar, Input, filter buttons, Card — all unchanged.

### `detail` panel — full rebuild

| Before | After |
|---|---|
| `ui.Section(title=name)` wrapping everything | `ui.Page(title=name, subtitle=url)` |
| `ui.Badge("Reachable", color=...)` × 3 in a horizontal Stack | `ui.Stats(columns=3)` with `ui.Stat(label, value, color)` |
| `ui.Badge(f"{n}", value="posts", color="gray")` × 3 | second `ui.Stats(columns=3)` row |
| `ui.List` + `ui.ListItem` per tab | `ui.DataTable(columns=[...], rows=[...])` per tab |
| `ui.Card(title="Status", subtitle=url, content=...)` | removed — replaced by Page header + Stats rows |
| `ui.Button("Disconnect", ...)` | removed — out of scope for read-only monitoring |

---

## `detail` Component Spec

### Page wrapper
```python
ui.Page(title=name, subtitle=base_url, children=[...])
```

### Health Stats row
```python
ui.Stats(columns=3, children=[
    ui.Stat(label="Reachable", value="Yes" if reachable else "No",
            color="green" if reachable else "red"),
    ui.Stat(label="Auth",      value="OK" if auth_ok else "Failed",
            color="green" if auth_ok else "red"),
    ui.Stat(label="SSL",       value="HTTPS" if ssl_valid else "HTTP",
            color="green" if ssl_valid else "red"),
])
```

### Content counts row
```python
ui.Stats(columns=3, children=[
    ui.Stat(label="Posts", value=_n(posts), color="blue"),
    ui.Stat(label="Pages", value=_n(pages), color="blue"),
    ui.Stat(label="Media", value=_n(media), color="blue"),
])
```

Where `_n(lst)` returns `len(lst)` if list is not None else `"?"`.

### DataTable per tab

**Posts / Pages:**
```python
columns = [
    ui.DataColumn("title",  "Title",  sortable=True),
    ui.DataColumn("status", "Status", sortable=True),
    ui.DataColumn("date",   "Date",   sortable=True),
]
rows = [
    {"title": wp_title(p), "status": p.get("status", ""), "date": p.get("date", "")[:10] if p.get("date") else ""}
    for p in items
]
ui.DataTable(columns=columns, rows=rows)
```

**Media:**
```python
columns = [
    ui.DataColumn("title",     "Title",    sortable=True),
    ui.DataColumn("mime_type", "Type",     sortable=True),
]
rows = [
    {"title": wp_title(m), "mime_type": m.get("mime_type", "")}
    for m in items
]
ui.DataTable(columns=columns, rows=rows)
```

### Empty / error states per tab
- Items is None (fetch failed): `ui.Alert(message="Could not load — check the connection.", type="error")`  
  *(replacing `ui.Empty(message="Could not load...")`; real signature: `Alert(message, title='', type='info')`)*
- Items is `[]` (no content): `ui.Empty(message="No {label.lower()} found.")`

### Back button
`ui.Button("← All sites", variant="secondary", on_click=ui.Call("__panel__overview"))` — first child, unchanged position.

---

## Files Changed

| File | Change |
|---|---|
| `panels.py` | Replace grid pairs with `ui.Grid`; rebuild `detail` body |
| `tests/test_panels.py` | Update `test_detail_renders_site_content` assertions to match new component names |

`handlers_*.py`, `storage.py`, `models.py`, `app.py`, `main.py` — untouched.

---

## Not In Scope

- `ui.DataTable` row clicks (read-only monitoring, no drill-down into individual posts)
- Disconnect button (deferred)
- Search / filter on DataTable (platform handles client-side sorting)
- `ui.Chart` / `ui.Graph` (no analytics data available)
