# WP Site Connector — Overview Panel: Align to Mockup

**Date:** 2026-06-18
**Scope:** Overview panel UI alignment + `refresh_site` function + bug fix.
**Status:** approved (brainstorm)

---

## Goal

Bring the overview panel in line with the design mockup (`design/wp-site-connector-panel.html`):
3-column grid, clickable cards with per-card Refresh + Remove menu, stretched search input,
status select dropdown. Add a live `refresh_site` function triggered by the Refresh button.
Fix a pre-existing bug where connect/forget do not refresh the renamed panel.

---

## Changes

### 1. Site card — `_site_card` in `panels.py`

**Grid:** `ui.Grid(columns=2)` → `ui.Grid(columns=3)`.

**Card structure:**

```python
ui.Card(
    title=name,          # site display name
    subtitle=url,        # full URL
    content=ui.Badge("Connected" if is_ok else "Error",
                     color="green" if is_ok else "red"),
    footer=ui.Stack(direction="h", gap=2, children=[
        ui.Button("", icon="RefreshCw", variant="ghost", size="sm",
                  on_click=ui.Call("refresh_site", site_id=site_id)),
        ui.Menu(items=[
            {"label": "Remove site", "icon": "Trash2",
             "on_click": ui.Call("forget_site", site_id=site_id)},
        ]),
    ]),
    on_click=ui.Call("__panel__detail", site_id=site_id),
)
```

`on_click` on the card navigates to the detail panel. The Refresh button and Remove menu live in
the footer. Whether the platform isolates footer button clicks from the card's `on_click` is
untested — accepted risk per design decision.

---

### 2. Header — site count

```python
ui.Text(f"{total} site{'s' if total != 1 else ''} connected", variant="heading")
```

Matches the mockup's large bold count (22px weight-700). Currently rendered as `variant='body'` (default) — replace with `variant='heading'`.

---

### 3. Filter bar — `overview` handler in `panels.py`

Replace the three status buttons with a stretched search input and a reactive select dropdown:

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

`ui.Input` fills available horizontal space. `ui.Select` is fixed-width on the right.
`ui.Select(on_change=...)` is reactive — fires immediately on selection without Enter.
`param_name="status_filter"` ensures the selected value is merged into the `ui.Call` params
under the key the `overview` handler expects.

---

### 3. New `refresh_site` function — `handlers_read.py`

```python
@chat.function("refresh_site",
    description="Re-check connectivity and auth for a connected WordPress site and update its stored status.",
    action_type="write",
    data_model=Site,
    effects=["wp.health_check"],
    event="wp-site-connector.refresh_site",
)
async def refresh_site(ctx, params: SiteIdParams) -> ActionResult:
    """Ping the site REST API, update stored status, and refresh the overview panel."""
```

Logic:
1. Load credentials via `_authed(ctx, params.site_id)` — return error if missing.
2. `GET /wp-json/wp/v2/users/me` with Basic auth.
3. `status = "connected"` if response is 200, else `"error"`.
4. Update only `status` + `last_checked` fields in the existing store record via
   `storage.save_site_record(ctx, {**record, "status": status, "last_checked": _now()})`.
5. Return `ActionResult.success(site_entity, summary=..., refresh_panels=["overview"])`.

`_now()` helper already exists in `handlers_connect.py` — move it to `storage.py` or duplicate
minimally in `handlers_read.py`.

---

### 4. Bug fix — `handlers_connect.py`

Both `connect_site` and `forget_site` pass `refresh_panels=["dashboard"]`. The panel was renamed
to `"overview"` in a prior commit. Update both to `refresh_panels=["overview"]`.

---

## Files Changed

| File | Change |
|---|---|
| `panels.py` | `_site_card`: 3 cols, card `on_click`, footer with Refresh + menu. `overview`: header count → `variant="heading"`, filter bar with `ui.Input` + `ui.Select`. |
| `handlers_read.py` | Add `refresh_site` function. |
| `handlers_connect.py` | Fix `refresh_panels=["dashboard"]` → `["overview"]` in `connect_site` and `forget_site`. |
| `tests/test_panels.py` | Update grid-column assertions. Add footer assertions (Refresh button, menu). |
| `tests/test_list_content.py` | Add `test_refresh_site_updates_status` and `test_refresh_site_marks_error`. |

---

## Error States (unchanged)

| Situation | UI |
|---|---|
| No sites | `ui.Empty` with connect CTA |
| Filter returns 0 | `ui.Empty("No sites match your filter.")` |
| Storage error | `ui.Empty("Could not load sites — try refreshing.")` |

---

## Out of Scope

- "Share" menu item (deferred, no spec)
- Pulsing status lamps (not available in SDK — `ui.Badge` is the alternative)
- Real-time per-keystroke search (SDK limitation — `ui.Input` fires on Enter only)
- Detail panel redesign
