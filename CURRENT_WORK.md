# Current Work — WP Site Connector

> Update this file at the END of every work session.
> One entry per session. Most recent at top.

---

## 2026-08-03 — Elementor/Bricks builder point-editing (v1.4.0)

**Status:** ✅ implemented and verified (246/246 tests pass, `imperal validate` clean: 0 errors, 0 warnings)

**What was done:**
- New companion WordPress plugin `bridge/imperal-builder-bridge/imperal-builder-bridge.php`
  (710 lines). Elementor stores its whole page tree in one post meta key
  (`_elementor_data`, nested JSON); Bricks stores each template area
  (`_bricks_page_header_2` / `_content_2` / `_footer_2`) as flat JSON keyed by
  element id. Neither registers these keys for REST, so — same root cause as
  Rank Math before the SEO bridge — reads come back empty and writes are
  silently dropped without a companion plugin. No fallback tier exists here
  (unlike SEO meta): a missing bridge is a hard stop.
- The bridge exposes `GET /wp-json/imperal/v1/builder` (flattened element
  tree, by post id/slug, optional builder filter), `POST …/builder/field`
  (change exactly one settings field on exactly one existing element,
  guarded by a `state_token` — refuses with 409 if the page changed since the
  read), and `GET …/builder/status` (capability discovery: which builder
  plugins are active site-wide). Deliberately does NOT expose "replace the
  tree" or "create an element" — point edits only, to avoid corrupting a
  working page.
- Added a standalone offline PHP logic test harness
  (`bridge/imperal-builder-bridge/tests/bridge_logic_test.php`, stubs core
  WP functions) — 56 assertions, all passing (`php tests/bridge_logic_test.php`).
- Added `bridge/imperal-builder-bridge/README.md`; added a short pointer
  section at the top of the shared `bridge/README.md` indexing both companion
  plugins.
- Python side: new `handlers_builders.py` with 3 chat functions —
  `check_builder_support`, `get_builder_content`, `update_builder_field` — plus
  matching Pydantic/SDL models in `models.py` (`BuilderElement`,
  `BuilderContent`, `BuilderFieldUpdateResult`, `BuilderSupport`, params
  models, `JsonValue` union for arbitrary builder field values).
- Registered the new module in `main.py`; bumped `app.py` and
  `pyproject.toml` to v1.4.0.
- Added `tests/test_builders.py` (24 new tests: reading, per-zone Bricks
  results, slug resolution, missing bridge, ambiguous slug/builder, stale
  state_token, unknown element, missing zone, forbidden write). Full suite:
  **246 passed** (was 222 before this session — verified via
  `.venv/bin/python -m pytest`, not assumed).
- `imperal build` / `imperal validate`: manifest regenerated for v1.4.0
  (72 tools total, 3 new); validate came back with 2 warnings on the first
  pass (missing `event=` / `effects=` on `update_builder_field`), fixed, then
  re-validated clean (0 errors, 0 warnings, 1 info about no `on_install` hook
  — pre-existing, not new).
- Not yet done: git commit/push and deploy to the Imperal registry (next
  step); no live WordPress site with Elementor/Bricks installed was used to
  smoke-test the actual bridge plugin end-to-end — only the offline PHP
  harness and Python `MockContext` tests. A real install/activation +
  live-site round trip is recommended before relying on this in production.

---

## 2026-08-02 — WooCommerce read-only module

**Status:** ✅ implemented and verified

**What was done:**
- Added a shared WooCommerce REST layer over the existing WordPress Application Password connection.
- Added 9 read-only chat functions: status, orders, one order, products, one product, customers, coupons, refunds, and store summary.
- Expanded order context with line items, totals, customer identity, payment method, filters, and pagination.
- Kept list responses privacy-minimal: no postal addresses or phone numbers are exposed.
- Added a conditional Commerce panel group with Overview, Orders, and Products; non-store sites do not show it.
- Added structured errors for unavailable WooCommerce, insufficient permission, missing records, malformed responses, rate limiting, and server failures.
- Added a module plan and contract tests. Manifest regenerated for v0.2.0.

**Verification:**
- `146 passed`
- `imperal validate`: 0 errors, 0 warnings (one informational lifecycle suggestion)
- Generated manifest contains all 9 WooCommerce functions.

**Next steps:**
- Deploy v0.2.0 and smoke-test against a connected WooCommerce production or staging site.

---

## 2026-06-19 — UI: status lamp + icon + content layout

**Status:** in progress

**Что было сделано (git log):**
- Replaced placeholder icon with official app logo
- Added status lamp (pulsing ui.Badge dot) to site list — green/yellow/red with animation
- Attempted ui.Html for lamp avatar (BUG-002: ui.Html not supported in avatar= slot → reverted to ui.Badge)
- Grouped content layout: Standard / Activity / Custom Types / Taxonomies sections
- Tab switching experiments (ui.Html client-side → reverted, settled on server-side tabs)
- Refresh All tooltip

**Known issue (BUG-002):** `ui.Html` does not render in `avatar=` slot of `ui.ListItem`. Workaround: `ui.Badge` with color.

**Next steps:** (определить при следующей сессии)

---

## 2026-06-16 — v1 design approved + initial build

**Status:** ✅ design approved, implementation started

**Что было сделано:**
- v1 design spec written: `docs/2026-06-16-wp-site-connector-v1-design.md`
- v1 implementation plan: `docs/2026-06-16-wp-site-connector-v1-plan.md`
- Initial app scaffold: app.py, handlers_connect.py, handlers_read.py, panels.py, skeleton.py, models.py, wp_client.py, storage.py
- imperal.json generated (manifest v3, sdk 5.4.2)
- Tools: connect_site, forget_site, add_ssh, remove_ssh, list_sites, list_posts, list_pages, list_media, get_site_health, refresh_site, refresh_all_sites, list_comments, list_scheduled, list_users, list_orders, list_custom_posts, get_server_info
- Tests: 11 test files covering all handlers, panels, models, storage, wp_client

---

_Template:_

```
## YYYY-MM-DD — <short description>

**Status:** in progress | ✅ done

**Что было сделано:**
-

**Next steps:**
-
```
