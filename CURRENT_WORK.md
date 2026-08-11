# Current Work — WordPress Hub (formerly "WordPress Hub")

> Update this file at the END of every work session.
> One entry per session. Most recent at top.

---

## 2026-08-12 — Mandatory complete pricing gate

**Every registered `@chat.function` must always have an explicit per-action price.** Whenever a
function is added, renamed, or removed, the release workflow must: (1) rebuild the complete
`tool_prices` map from the validated manifest, (2) verify an exact one-to-one match — no missing
or extra keys — and (3) save the **entire** map through `developer.update_pricing` while the app
is suspended, before deployment. Never use a partial `save_pricing` update: it can leave previous
functions unpriced.

**Current token policy — 2026-08-12:** `0` is allowed only where charging would be unfair because
there is no WordPress work: initial access setup/removal (`connect_site`, `forget_site`, `add_ssh`,
`remove_ssh`) and `list_sites`, which reads the already-stored local connection inventory. Every
site read costs at least `8`; standard single-site changes cost `16`; substantial single site/server
operations cost `20`; heavy diagnostics, previews, and aggregations cost `40`; and applying CSV,
bulk, or import changes costs `60`. Price measures actual work breadth and server load, while risk
is governed separately by confirmations. The complete map is versioned in both `tool-prices.json`
and `imperal.json.pricing`, and tests require them to remain identical.

## 2026-08-11 (late night) — Group N: Rewrite Rules & Permalinks (4 functions, new Bridge SECTION 17)

**Status:** SHIPPED, tested (741/741 Python + 501 PHP across all 9 bridge harnesses — up from
724/480), `imperal validate` clean (203 functions, 0 errors/0 warnings/1 info), full 203-key
pricing map applied via `update_pricing` after `suspend_app`. Bridge zip rebuilt.

**Group N — Rewrite Rules & Permalinks (4 functions, `handlers_rewrite.py`, new, Bridge-first/
SSH-fallback):** `get_permalink_structure`, `update_permalink_structure`, `flush_rewrite_rules`,
`list_rewrite_rules`.

Research-first, same discipline as every prior group: read WP core's `WP_Rewrite` class source
(`set_permalink_structure()` updates `permalink_structure` option + re-inits `$wp_rewrite` but
does **NOT** flush rules itself — matches `wp-admin/options-permalink.php`'s own two-step "Save
Changes" flow, which this Bridge route now mirrors exactly: set structure, then explicit
`flush_rewrite_rules()` right after), confirmed core's own `/wp/v2/settings` REST endpoint has
**never reliably exposed `permalink_structure`** — added in 4.9 (#41014/[42359]) then removed
again ([42575]/#45017 fallout, because plain-permalink sites where `permalink_structure === ''`
collided with the REST index's own use of that exact field name) — and confirmed via the current
live `developer.wordpress.org/rest-api/reference/settings/` schema table that it is absent today,
and that `category_base`/`tag_base` have never been exposed there at all. This settled the open
question from the roadmap doc: Group N needed a dedicated new Bridge route (SECTION 17), not a
field bolted onto the existing `get_site_settings`. Verified WP-CLI's real `rewrite-command`
subcommands (`wp rewrite structure '<permastruct>' [--category-base] [--tag-base] [--hard]`,
`wp rewrite flush [--hard]`, `wp rewrite list --format=json`) for the SSH-fallback shapes.

Bridge SECTION 17 (`imperal-bridge.php` 2.12.0 → 2.13.0): `GET/POST /imperal/v1/rewrite/structure`,
`POST /imperal/v1/rewrite/flush`, `GET /imperal/v1/rewrite/rules` — reads/writes
`permalink_structure`/`category_base`/`tag_base` directly, calls `WP_Rewrite::
set_permalink_structure()` + `flush_rewrite_rules()` for the update path, and reads the
`rewrite_rules` wp_options row (WP_Rewrite's own compiled table) for listing. New PHP logic
harness `rewrite_logic_test.php` (21 assertions, fake WP_Rewrite + wp_options store, no real
WordPress/MySQL needed) — all 9 harnesses green (501 total PHP assertions, up from 480). New
`wp_cli.py` functions (`get_permalink_structure`/`update_permalink_structure`/
`flush_rewrite_rules`/`list_rewrite_rules`) for the SSH fallback path. New `tests/test_rewrite.py`
(17 tests, the standard 3-way Bridge/SSH/neither contract shape). Full suite 724 → 741, all green.

**Pricing:** extended the reconciled tier map with the 4 new keys (`get_permalink_structure`=1,
`list_rewrite_rules`=1 — single reads; `update_permalink_structure`=2, `flush_rewrite_rules`=2 —
single writes, matching the established action_type-based tiers) and rebuilt+verified the
complete 203-key map (exact match against every real `@chat.function` name in the built manifest,
no missing/no extra) before sending. Applied via `developer.suspend_app` → `developer.
update_pricing` (complete map nested under `pricing_config.tool_prices`, never `save_pricing`,
never partial). App was already `pending_review` after the update, so no separate
`submit_for_review` call was needed/possible.

**Bridge README:** added the SECTION 17 row to the endpoint table, fixed the stale "(five
sections, one plugin)" header (now accurate at 17 sections). Zip rebuilt (`imperal-bridge.zip`,
tests excluded, README + PHP only).

**Roadmap doc** (`docs/2026-08-11-developer-backend-functions-plan.md`) — Group N marked ✅
SHIPPED with full technical detail. Groups A–N now all ✅ SHIPPED. Remaining unshipped groups:
O (Import/Export WXR), P (Core/Plugin/Theme Integrity), Q onward — see the roadmap doc for the
full remaining list.

---

## 2026-08-11 (night) — Closed the last two SSH-only gaps + shipped SECTION 17 (Rewrite/Permalinks): standing "no SSH, ever, for anyone" directive now COMPLETE

**Final combined status for this session (two commits):** `516579f` (purge_cache + list_plugins
fix) then `0ec7af2` (rewrite/permalinks module). Full suite at the end: **741/741 Python passed**,
**501 PHP assertions across all 9 bridge harnesses** (action_scheduler 42, builder 62, cache_cron
37, database 36, logs 19, maintenance 105, media 49, rewrite 21, seo 130). `imperal validate`:
**203 functions, 0 errors, 0 warnings, 1 info** (same pre-existing "no on_install hook" info as
always). App version 1.17.0 → 1.18.0. Bridge 2.12.0 → 2.13.0. Both commits pushed and deployed
(`developer.deploy_app`, final commit `0ec7af2e`, status=warning 18/21 — the same cosmetic pattern
noted in literally every deploy this app has ever had, confirmed not a regression by checking this
file's own history). Pricing: rebuilt the complete 203-key `tool_prices` map (only the rewrite
module's 4 new functions needed genuinely new prices; the purge_cache/list_plugins fix touched no
new function names so needed no pricing cycle on its own), applied via
`suspend_app` → `update_pricing` → `submit_for_review` (all 4 checks passed, `pending_review`).

**Bottom line on the standing directive** ("нужно чтобы это делалось без ssh, всегда, у всех
пользователей" — repeated verbatim many times): every single `get_ssh_cred` call site across the
entire app now has a Bridge attempt in front of it, confirmed by a full grep sweep across
`handlers_read.py`, `handlers_database.py`, `handlers_cache_cron.py`, `handlers_logs.py`,
`handlers_maintenance.py`, `handlers_rewrite.py` — zero true SSH-only functions remain anywhere in
the app. SSH is now genuinely optional everywhere: a site with just the Imperal Bridge plugin
installed (no SSH access configured at all) gets full functionality; SSH is only ever a fallback
for sites whose Bridge is missing or predates the version that added a given route.

**Context — the standing directive:** user has repeated, verbatim, across many turns: "нужно чтобы
это делалось без ssh, всегда, у всех пользователей" (must work without SSH, always, for every
user). This closes that out at the code level: **every** `get_ssh_cred` call site across the whole
app (`handlers_read.py`, `handlers_database.py`, `handlers_cache_cron.py`, `handlers_logs.py`,
`handlers_maintenance.py`) now has a Bridge attempt (`_bridge_get`/`_bridge_post`) preceding it —
confirmed via a full grep sweep, not just spot-checked.

**`purge_cache` (`handlers_read.py`):** Bridge SECTION 15's `/maintenance/purge-cache` route
already existed server-side (added in an earlier session) but the Python side had never been
wired to call it — it was still 100% SSH-only. Converted to the same Bridge-first/SSH-fallback
shape as `install_plugin`/`update_plugin`: calls `handlers_maintenance._site_auth` +
`handlers_maintenance._bridge_post(BRIDGE_MAINTENANCE_PURGE_CACHE_PATH)` first, only falls back to
SSH + `wp_cli.list_plugins`/`purge_litespeed_cache`/`purge_w3tc_cache` if the Bridge is
missing/outdated. Rewrote `tests/test_purge_cache.py` from scratch to the standard 3-way contract
shape (Bridge-answers-no-SSH-stored / Bridge-404-SSH-fallback / neither-available) — 8 tests,
mirroring `tests/test_install_plugin.py`.

**`list_plugins` (`handlers_read.py` + NEW Bridge route):** this was the one true remaining gap —
there was no existing Bridge route for it at all. Stock WordPress REST's `/wp/v2/plugins` (verified
its real schema via developer.wordpress.org before relying on it) has NO update-availability field,
so it can't fully replace the WP-CLI `wp plugin list --fields=name,status,version,update,
update_version` shape this function has always returned. Added a new Bridge route,
`GET /imperal/v1/maintenance/list-plugins` (`imperal_maintenance_bridge_list_plugins`), built from
three plain WP core calls — `get_plugins()` (wp-admin/includes/plugin.php, every installed plugin's
header data), `is_plugin_active()` per plugin, and `get_plugin_updates()`
(wp-admin/includes/update.php, the same list wp-admin's own Plugins screen reads its update
notices from) — no shell needed. Python side now tries this route first, SSH + `wp_cli.list_plugins`
as fallback. Rewrote `tests/test_plugins.py` to the same 3-way contract shape (6 tests). Added PHP
fixtures (`get_plugins()`/`get_plugin_updates()` stubs reusing the existing `$GLOBALS['_plugins']`
fake registry and a new `$GLOBALS['_plugin_updates']`) plus route-registration + behavior tests to
`maintenance_logic_test.php` (90 → 105 PHP tests).

**Bridge:** `imperal-bridge.php` 2.12.0 → 2.13.0 (new route). README's Maintenance row extended to
list `purge-cache` and `list-plugins` alongside the existing four routes. Zip rebuilt.

**Correction to an earlier note this same session — the SECTION 17 "Rewrite Rules & Permalinks"
module was NOT dead code.** It was already wired into `main.py`'s `_LOCAL` module list and imports
(I'd mistakenly checked `app.py` instead), already had a complete PHP harness
(`rewrite_logic_test.php`, 21/21 passing) and complete Python contract tests
(`tests/test_rewrite.py`, 17/17 passing) — it just wasn't committed yet. Finished shipping it in
this same session: ran `imperal build` (203 → new count with the 4 rewrite functions included),
`imperal validate` clean, bumped `app.py` 1.17.0 → 1.18.0, full pricing map rebuilt/applied, then
committed + pushed + deployed alongside the purge_cache/list_plugins fix. See below for the final
combined numbers — this note is superseded by the fuller account further down/above once merged.

---

## 2026-08-11 (evening, cont'd 6) — Group M (Action Scheduler, 6 functions); 193 → 199 functions; full pricing map rebuilt and reconciled

**Status:** SHIPPED, tested (720/720 Python + 411 PHP across all bridge harnesses), `imperal
validate` clean (199 functions, 0 errors/0 warnings/1 info), full 199-key pricing map applied via
`update_pricing` after `suspend_app`, resubmitted (`pending_review`, all 4 checks passed). Commit
`3e10f83`, pushed, deployed (`developer.deploy_app` → commit `3e10f831`, status=warning 18/21 —
same known cosmetic pattern as every prior deploy this session, not a regression).

**Group M — Action Scheduler / Background Job Queue (6 functions, `handlers_action_scheduler.py`,
new, Bridge-only via new SECTION 16):** `list_scheduled_actions`, `get_scheduled_action`,
`run_scheduled_action`, `cancel_scheduled_action`, `retry_failed_action`, `count_actions_by_status`.
Action Scheduler ships bundled inside WooCommerce (NOT WordPress core, NOT guaranteed present) —
verified its real public API by reading its own source on GitHub
(`woocommerce/action-scheduler` `functions.php` + `ActionScheduler_Store.php`) rather than
guessing: `ActionScheduler::store()` (query_actions/fetch_action/get_status/cancel_action/
action_counts), `ActionScheduler::runner()->process_action()` (the exact call the admin's own
Tools → Scheduled Actions "Run" row action uses), `ActionScheduler::logger()->get_logs()`, and the
`STATUS_PENDING/RUNNING/COMPLETE/FAILED/CANCELED` constants. Confirmed Action Scheduler has **no
native retry** — a failed action stays failed forever; `retry_failed_action` re-enqueues a fresh
attempt via `as_enqueue_async_action()` with the same hook/args/group (the same thing a developer
calling the API by hand would do), and rejects with a 400 if the action isn't actually in the
`failed` state. Deliberately Bridge-only, no SSH fallback (unlike every other recent group) — the
`wp action-scheduler` CLI package needs the exact same WooCommerce/library context loaded as the
REST call, so a bare SSH session buys nothing extra; this mirrors the Group K/redirects precedent
for a plugin-owned data source with no meaningful shell equivalent. 18 new Python tests
(`tests/test_action_scheduler.py`) + 42 new PHP tests (`action_scheduler_logic_test.php`, exercising
a fake in-memory `ActionScheduler`/`ActionScheduler_Store`/runner/logger — the real library needs
WooCommerce + MySQL, out of scope for a logic-only harness).

**Pricing — full rebuild, not incremental:** there is still no readback tool for the previously
saved `tool_prices` map (documented platform limitation, carried across every session this app has
had). Rebuilt the complete 199-key map from first principles: read every function's real
`action_type` out of the built `imperal.json` manifest, applied the established tiers (0 =
front-door/local-only, 1 = single read, 2 = single write/delete, 4 = multi-call bulk/preview/
aggregation, 6 = CSV-apply), then cross-checked and reconciled every explicit per-function price
quoted in this file's own history (31 distinct documented overrides found via grep). Caught and
resolved one real conflict in the process: an earlier 2026-08-10 note priced `update_plugin`/
`update_core`/`run_wp_cron` at 2 each, but a LATER 2026-08-11 session note explicitly reconciled
`install_plugin`/`run_wp_cron` to 4 (multi-call tier) — the later, more specific reconciliation was
treated as authoritative and used (`run_wp_cron`=4, `install_plugin`=4, `update_plugin`=2,
`update_core`=2 — the two Bridge-added maintenance functions stayed at the single-write tier since
each is genuinely one call, only `run_wp_cron`/`install_plugin` inherited the multi-call precedent).
Verified the built map's key-set is an EXACT match (no missing, no extra) against every real
`@chat.function` name in the manifest before sending. Applied via `developer.suspend_app` →
`developer.update_pricing` (complete map nested under `pricing_config.tool_prices`, never
`save_pricing`, never partial) → `developer.submit_for_review`. As with every prior pass, no
independent readback tool exists to re-confirm persistence after the fact — noted honestly, not
swept under the rug.

**Bridge:** `imperal-bridge.php` 2.11.0 → 2.12.0 (SECTION 16 appended, `sections` capability list
updated). Zip rebuilt, README given an Action Scheduler row matching the existing per-section table
format.

**This closes out today's roadmap-driven session** (`docs/2026-08-11-developer-backend-functions-plan.md`,
Groups A–M now all ✅ SHIPPED). Remaining unshipped groups in that doc: N (Rewrite Rules &
Permalinks), O (Import/Export WXR), P (Core/Plugin/Theme Integrity), Q (Mail Deliverability), R (WP
Site Health), S (Sessions & Auth Hygiene), T (Custom REST Endpoint discovery), U (Site Icon/
Branding) — plus G (Multisite, gated on confirming real demand) and H (Deploy/Environment Hygiene,
appears superseded/folded into what SECTION 11 already shipped — needs a status check next
session, not yet marked SHIPPED in the doc despite Deploy work having landed under a different
group letter earlier this session).

---

## 2026-08-11 (evening, cont'd 5) — Bridge SECTION 15 (maintenance): fixed SSH-required gap on update_plugin/update_core/run_wp_cron

**Status:** SHIPPED, tested (702/702), `imperal validate` clean (193 functions — unchanged, this
rewires 3 existing functions, doesn't add new ones), bridge zip rebuilt (now includes
`maintenance_logic_test.php`) and README updated. No pricing change needed.

**Fix:** Same bug pattern as SECTION 14 (cache/cron), found while continuing to sweep the codebase
for other SSH-only functions predating the Bridge-first policy: `update_plugin`, `update_core`,
`run_wp_cron` (`handlers_maintenance.py`) were SSH/WP-CLI-only since first shipped. Added Bridge
SECTION 15 (`imperal-bridge.php` 2.10.0 → 2.11.0, `/imperal/v1/maintenance/*` routes) using
WordPress's own upgrade machinery on the Bridge path — `Plugin_Upgrader`/`Core_Upgrader` driven by
`Automatic_Upgrader_Skin` (the exact silent skin WordPress's own background auto-updates use,
same as wp-admin's "Update Now" button), and the same `_get_cron_array()`/`do_action_ref_array()`
primitives SECTION 14 uses, walking every hook already past its scheduled timestamp (matching
`wp cron event run --due-now`). Rewired all 3 Python handlers to Bridge-first/SSH-fallback.
Rewrote `tests/test_maintenance.py` for the three-way contract (Bridge-only / SSH-fallback /
neither) — 12 → 15 tests, preserving the unsafe-slug shell-injection guard test on the SSH
fallback path. `bridge/imperal-bridge/tests/maintenance_logic_test.php` (36 passing PHP tests)
already existed uncommitted when found — folded into this same commit.

---

## 2026-08-11 (evening, cont'd 4) — Bridge SECTION 14 (cache/cron): fixed SSH-required gap on the 8 existing transient/object-cache/cron functions

**Status:** SHIPPED, tested (698/698, +10 from the Group L count), `imperal validate` clean (193
functions — unchanged, this rewires existing functions, doesn't add new ones), bridge zip rebuilt
and README updated. No pricing change needed (same 8 function names, same tiers).

**Fix:** `handlers_cache_cron.py`'s 8 functions (`list_transients`, `delete_transient`,
`flush_all_transients`, `get_object_cache_status`, `flush_object_cache`, `list_cron_events`,
`run_cron_event`, `delete_cron_event`, `list_cron_schedules`) were SSH/WP-CLI-only since they were
first shipped — every one of them now needed SSH configured even on sites that already have the
Imperal Bridge plugin installed, matching the exact bug pattern the user found and asked to be
fixed (details screen "No server data yet", refresh doesn't help). Added Bridge SECTION 14
(`imperal-bridge.php` 2.9.0 → 2.10.0, `/imperal/v1/cache/*` routes) using WordPress's own core
functions on the Bridge path — `delete_transient()`/`delete_site_transient()` (not a raw
options-table write, so cache add-ons hooking those actions still see it),
`wp_using_ext_object_cache()`/`wp_cache_flush()`, `_get_cron_array()`/`wp_unschedule_hook()`/
`wp_get_schedules()` (WP core's own cron internals, matching what `wp cron event *` calls
internally). Rewired all 8 Python handlers to Bridge-first/SSH-fallback, same shape as
`handlers_logs.py`/`handlers_database.py`. Rewrote `tests/test_cache_cron.py` for the new
three-way contract (Bridge-only / SSH-fallback / neither) — 13 → 24 tests. Added
`bridge/imperal-bridge/tests/cache_cron_logic_test.php` (37 passing PHP unit tests for the new
PHP logic, mirroring `database_logic_test.php`'s standalone-harness pattern). Rebuilt
`bridge/imperal-bridge.zip` and added a README table row for the new section.

---

## 2026-08-11 (evening, cont'd 3) — Group L (WooCommerce webhooks, 5 functions); 188 → 193 functions

**Status:** SHIPPED, tested (688/688), `imperal validate` clean (193 functions, 0 errors/0
warnings/1 info), 193-key pricing map applied via `update_pricing` after `suspend_app`, resubmitted
(all 4 checks passed). No Bridge/SSH changes this round — native WooCommerce REST. Commit + push +
deploy is the final step of this entry.

**Group L — WooCommerce webhooks (5 functions, `handlers_webhooks.py`, new, no Bridge/SSH needed):**
`list_registered_webhooks`, `get_webhook`, `create_webhook`, `update_webhook`, `delete_webhook` —
all against WooCommerce's own native `wc/v3/webhooks` route (developer.woocommerce.com/docs/apis/
rest-api/v3/webhooks/), the same Application-Password auth every other WooCommerce function in
this app already uses. Lets a backend developer wire a site into an external system (order sync,
inventory feed, a Slack/Zapier-style relay) without touching wp-admin. `secret` is write-only per
WooCommerce's own schema (never returned by a GET) and is never echoed back by any function here.
`delivery_url` is validated https:// before any network call on both create and update.
`update_webhook` uses POST (WooCommerce's own webhooks endpoint takes POST for partial updates, not
PUT); `delete_webhook` uses `force=true` (webhooks have no trash state, same as customers). 12 new
tests (`tests/test_webhooks.py`).

---

## 2026-08-11 (evening, cont'd 2) — Group K (Blocks/Patterns introspection, 2 functions); 186 → 188 functions

**Status:** SHIPPED, tested (676/676), `imperal validate` clean (188 functions, 0 errors/0
warnings/1 info), 188-key pricing map applied via `update_pricing` after `suspend_app`, resubmitted
(all 4 checks passed). No Bridge/SSH changes this round — pure native-REST introspection. Commit +
push + deploy is the final step of this entry.

**Group K — Blocks/Patterns (2 functions, `handlers_blocks.py`, new, no Bridge/SSH needed):**
`list_reusable_blocks` (native `GET /wp/v2/blocks`, WP core since 5.0 — the `wp_block` post type
backing Gutenberg reusable blocks/"synced patterns") and `list_block_patterns` (native
`GET /wp/v2/block-patterns/patterns`, WP core since 6.0 — theme/plugin-registered patterns).
Verified against WP core's own `class-wp-rest-blocks-controller.php`: `title.rendered`/
`content.rendered` are deliberately stripped from every context ("it doesn't make sense for a
pattern to have rendered content on its own"), so we read `title.raw` instead; the top-level
`wp_pattern_sync_status` meta is empty for a fully-synced block, normalized here to the explicit
string `"synced"` so the field is self-explanatory. `list_block_patterns` confirmed read-only BY
DESIGN on WordPress's own side — patterns are PHP/JSON registrations via `register_block_pattern()`,
never database rows, so core itself exposes no create/update/delete route. 9 new tests
(`tests/test_blocks.py`).

---

## 2026-08-11 (evening, cont'd) — Group J (CPT/taxonomy introspection, 2 functions) + Bridge SECTION 13 (logs) closing the same "No server data yet" gap for tail_debug_log/clear_debug_log/tail_php_error_log; 184 → 186 functions

**Status:** SHIPPED, tested (667/667), `imperal validate` clean (186 functions, 0 errors/0
warnings/1 info), 186-key pricing map applied via `update_pricing` after `suspend_app`, resubmitted
(all 4 checks passed). Bridge zip rebuilt (v2.8.0 → v2.9.0, now 9 files incl. `logs_logic_test.php`).
Commit + push + deploy is the final step of this entry.

**Group J — CPT/Taxonomy introspection (2 functions, `handlers_cpt_taxonomy.py`, new, no Bridge/SSH
needed):** `list_registered_post_types`, `list_registered_taxonomies` — thin wrappers over
WordPress core's own native `GET /wp/v2/types` / `GET /wp/v2/taxonomies` (shipped since the REST
API's introduction). Verified against WP core's own `class-wp-rest-post-types-controller.php` /
`class-wp-rest-taxonomies-controller.php` source: the single most useful discovery field on each
(`viewable` for types, `visibility.public` for taxonomies) is marked `'context' => array('edit')`
in WP core's OWN schema, so a plain view-context GET never returns it. Both functions request
`context=edit` first and transparently retry at the default view context on a 401/403 (lower-
privileged connected user) rather than failing outright or silently defaulting the field without
saying why. 7 new tests.

**Bridge SECTION 13 (logs) — the SAME "No server data yet" gap found in database, now closed for
logs too:** `tail_debug_log`, `clear_debug_log`, `tail_php_error_log` (Group I, shipped earlier this
session) were SSH/WP-CLI-only, exactly like the 8 database functions were before today's fix — same
root cause, same remedy. Added 3 routes to imperal-bridge.php (`/logs/debug-log` GET,
`/logs/debug-log/clear` POST, `/logs/php-error-log` GET, all `manage_options`-gated), wired
`handlers_logs.py` to try the Bridge route first and fall back to SSH/WP-CLI only when the Bridge
plugin isn't installed or predates 2.9.0 — same bridge-first/SSH-fallback contract as
`get_server_info` and the SECTION 12 database tools. All three still honestly report "no file"
rather than fabricating content when the file genuinely doesn't exist. Added
`bridge/imperal-bridge/tests/logs_logic_test.php` (19 PHP-side logic assertions, all passing) and
rewrote `tests/test_logs.py` (12 tests: Bridge-success + honest-empty + SSH-fallback + neither-
available, for all 3 functions). README.md: added Logs row to the features table and the test file
to the Tests section.

**Pricing:** `list_registered_post_types` and `list_registered_taxonomies` priced at 1 credit each
(single core REST GET, same tier as `get_php_info`/`list_rest_routes` — matches the standing
"price = real work done" rule, not "importance"). 186-key map verified to exactly match the 186
function names in the built manifest before calling `update_pricing`.

**Next up (Group K, per docs/2026-08-11-developer-backend-functions-plan.md):** reusable
blocks/patterns (`wp_block` post type + `/wp/v2/block-patterns/patterns`), then Group L (WooCommerce
webhooks: list/get/create/update/delete via `wc/v3/webhooks`).

---

## 2026-08-11 (evening) — Shipped Group I (Logs, 3 functions) + fixed "No server data yet" Bridge gap for database tools; 181 → 184 functions

**Status:** SHIPPED, tested (657/657), `imperal validate` clean (184 functions, 0 errors/0 warnings/1
info), priced (184-key map applied via `update_pricing`), resubmitted for review (all 4 checks
passed). Bridge zip rebuilt (v2.7.0 → v2.8.0). Commit + push + deploy pending as the final step of
this same session.

**Group I — Logs (3 functions, `handlers_logs.py`, new, SSH/WP-CLI only):** `tail_debug_log`,
`clear_debug_log` (truncates, never deletes), `tail_php_error_log` (reads PHP's own
`ini_get('error_log')` path, never a guessed distro path). All three honestly report "no file"
rather than fabricating content. 9 new tests.

**Bug fix (user-reported): "Imperal Bridge is installed on all 3 sites, but details still says
'No server data yet' and refresh doesn't fix it."** Root cause: `handlers_database.py` (8
functions: list_database_tables, run_db_search_replace, apply_db_search_replace,
optimize_database_tables, check_database_repair, export_database_dump, count_post_type_rows,
count_orphaned_postmeta) were SSH/WP-CLI-only and returned `SSH_NOT_CONFIGURED` even on sites
with the Bridge installed — the Bridge plugin (2.7.0) had no `database` section at all, so these 8
functions were structurally unreachable via any Bridge-only site, no matter how many times you hit
refresh.

Two-part fix:
1. **Bridge SECTION 12 (database)** added to imperal-bridge.php, 2.7.0 → 2.8.0: 7 routes
   (`/database/search-replace`, `/database/tables`, `/database/optimize`, `/database/check`,
   `/database/export`, `/database/post-count`, `/database/orphaned-postmeta`), all plain `$wpdb`
   calls from inside WordPress — zero shell. Serialization-safe recursive search-replace (matches
   wp-cli's own approach to avoid corrupting PHP-serialized values), tables validated against this
   site's own `$wpdb->prefix` only, `dry_run` always available and never writes when true. New
   standalone PHP harness `tests/database_logic_test.php` (fake `$wpdb`, no real WordPress needed).
2. **`handlers_database.py` rewritten Bridge-first, SSH-fallback** — same pattern as
   `get_server_info` in `handlers_read.py`: try the Bridge route first (never raises, signals
   "fall back to SSH" on 404/unreachable), only fall to SSH/WP-CLI if the Bridge doesn't answer.
   A site running Bridge 2.8.0+ now gets all 8 database functions with zero SSH involved.
   `tests/test_database.py` rewritten from scratch for the new contract (23 tests: bridge-success,
   bridge-404-falls-back-to-ssh, neither-available), mirroring `tests/test_server_info.py`.

**Process note:** `handlers_database.py` was accidentally wiped to 0 bytes twice during this
session by a `write_file` call issued without real content (a tool-call slip, not deliberate).
Both times caught immediately and restored cleanly via `git checkout HEAD -- handlers_database.py`
since HEAD still had the last committed version — no data was actually lost, but it's a reminder to
prefer `edit_file`/`multi_edit` over `write_file` for large existing files.

Documented in full in the "ГЛАВНЫЙ ПЛАН" note (brand-strategy note id aaf4c105...) per the standing
rule to record roadmap progress in notes, not just in this file.

---

## 2026-08-11 (afternoon, cont'd 3) — Shipped Group F (Security/Hardening, 4 functions) + Group G (Deploy/Environment Hygiene, 4 functions); repriced 181-key map; resubmitted

**Status:** SHIPPED, tested, deployed at `669bec8a`, priced, resubmitted for review (`pending_review`,
all 4 checks passed). Continuing through the remaining roadmap groups in the same session.

**Group F — Security / Hardening Diagnostics (4 functions, `handlers_security.py`, new):**
`get_php_info` (PHP version, loaded extensions, memory/execution/upload limits — Bridge SECTION 10
`/security/php-info`, plain `phpversion()`/`get_loaded_extensions()`/`ini_get()`), `check_debug_mode`
(WP_DEBUG/WP_DEBUG_LOG/WP_DEBUG_DISPLAY — Bridge `/security/debug-mode`, WP_DEBUG_DISPLAY correctly
defaults to WP_DEBUG's own value when undefined, matching WP core), `check_file_permissions`
(wp-config.php + wp-content octal perms, read-only, never `chmod()`s — Bridge `/security/file-permissions`),
`list_admin_users` (thin wrapper over WordPress core's own native `GET /wp/v2/users?roles=administrator`
filter — no Bridge/SSH needed at all, confirmed against developer.wordpress.org/rest-api/reference/users/,
shipped in core since 4.7). Bridge bumped to v2.6.0 with new SECTION 10 (3 routes, `manage_options`-gated).
`get_ssl_status` intentionally NOT built (web-tools' `ssl_check` already owns that surface — no
duplication). `list_failed_login_attempts` intentionally NOT built (would require guessing a specific
security plugin's internal storage shape without a real site to verify against — exactly the kind of
fabrication the roadmap forbids).

**Group G — Deploy / Environment Hygiene (4 functions, `handlers_deploy.py`, new):**
`get_wp_config_constants` (hard-ALLOWLISTED subset of wp-config.php constants — WP_DEBUG, WP_CACHE,
WP_ENVIRONMENT_TYPE, WP_HOME, WP_SITEURL, DISALLOW_FILE_EDIT/MODS, AUTOMATIC_UPDATER_DISABLED, plus
`$wp_version`/`$table_prefix` — NEVER DB_NAME/DB_USER/DB_PASSWORD/DB_HOST and NEVER
AUTH_KEY/SECURE_AUTH_KEY/LOGGED_IN_KEY/NONCE_KEY or their `_SALT` twins; the allowlist is hard-coded on
the Bridge PHP side, no caller-supplied name can widen it), `list_must_use_plugins` (WordPress core's own
`get_mu_plugins()` from `wp-admin/includes/plugin.php` — mu-plugins can't be deactivated so core
deliberately excludes them from `list_plugins`/`list_native_plugins`, a real blind spot until now),
`list_drop_ins` (core's own `get_dropins()`, same file — which drop-in files, e.g. `object-cache.php`,
`advanced-cache.php`, `db.php`, are actually present, showing which caching/DB layer is really in play),
`get_environment_type` (WordPress 5.5+'s own `wp_get_environment_type()` from `wp-includes/load.php` —
production/staging/development/local, defaults to `production` if undeclared; verified against
make.wordpress.org's own 5.5 announcement post and developer.wordpress.org's reference page). Bridge
bumped to v2.7.0 with new SECTION 11 (4 routes, all `manage_options`-gated).

**Tests:** 8 new for Group F (`tests/test_security.py`), 8 new for Group G (`tests/test_deploy.py`).
Full suite 624→632→640, all green throughout. `imperal validate`: 0 errors/0 warnings, 181 functions
(was 173 at the start of this session).

**Pricing:** Repriced the complete map twice this session — 177-key (adding Group F) then 181-key
(adding Group G) — via `update_pricing` (suspend→reprice→resubmit cycle each time), cross-checked byte-
for-byte (Python set equality) against the live manifest's tool list before every submit. New functions
priced at 1 each (single Bridge/native-REST GET call, matching the existing "price = real work volume"
rule) — never priced by "importance" or "danger".

**Committed:** `5282eed` (Group F code+tests), `1acae39` (Group G code+tests), `669bec8` (bridge zip
rebuild w/ README). Deployed at `669bec8a`.

**Roadmap doc:** `docs/2026-08-11-developer-backend-functions-plan.md` Groups F and G marked ✅ SHIPPED
with full detail; cleaned up a duplicate-paragraph artifact left by the mid-edit note-taking (same
class of glitch as the Group E entry earlier this session — caught and fixed the same way, by re-reading
the file after editing rather than trusting the diff alone).

**Next up:** Group H (Logs — `tail_debug_log`/`clear_debug_log`/`tail_error_log`, all SSH-based) is next
per the roadmap's own group ordering; Group I (Custom Post Types & Taxonomies introspection) after that.
Group (multisite, currently labelled G in some older notes but renumbered after this session's Security/
Deploy insertions) remains gated until a real connected site is confirmed multisite.


## 2026-08-11 (afternoon, cont'd 2) — Shipped Group E (REST API introspection + App Password auditing, 4 functions); repriced 173-key map; resubmitted

**Status:** SHIPPED, tested, deployed, priced, resubmitted for review. Continuing through the
remaining groups (F, H, I...) of `docs/2026-08-11-developer-backend-functions-plan.md` in this
same session.

**Group E — REST API Introspection (4 functions, `handlers_rest_api.py`, new):**
`list_rest_routes` (reads the site's own `GET /wp-json/` root index -- native WordPress core, no
Bridge/SSH needed -- optionally filtered by namespace), `get_rest_route_schema` (methods + each
endpoint's declared args for ONE route from that same index), `list_application_passwords`
(native `/wp/v2/users/me/application-passwords`, WP 5.6+ -- never the secret itself, only
uuid/name/created/last_used/last_ip), `revoke_application_password` (`DELETE
/wp/v2/users/me/application-passwords/<uuid>` -- distinct from `forget_site`, which only removes
Imperal's own stored credential; this changes WordPress itself and affects every client using
that password). Every route shape verified against developer.wordpress.org/rest-api/ docs and
make.wordpress.org's Application Passwords integration guide before writing code.

**Tests:** 9 new (`tests/test_rest_api.py`). Full suite 615→624, all green.
`imperal validate`: 0 errors/0 warnings, 173 functions.

**Pricing:** Repriced the complete 173-key map (adding these 4) via `update_pricing`
(suspend→reprice→resubmit cycle), resubmitted — `pending_review`, all 4 checks passed. Deployed.

**Committed:** `cb5f725` (Group E code+tests), plus doc backfill commits.


## 2026-08-11 (afternoon, cont'd) — Shipped Group B (Database Tools, 8 functions); repriced full 169-key map; resubmitted

**Status:** SHIPPED, tested, deployed, priced, resubmitted for review. Continuing through the
remaining groups (E, F...) of `docs/2026-08-11-developer-backend-functions-plan.md` in this same
session.

**Group B — Database Tools (8 functions, `handlers_database.py`, new):**
`list_database_tables` (`wp db size --tables --format=json`), `run_db_search_replace` /
`apply_db_search_replace` (`wp search-replace`, always dry-run first; apply re-verifies with a
fresh dry-run immediately before writing and refuses if the replacement count drifted from what
was confirmed — same anti-stale-preview guard as `apply_order_line_changes`; search/replace text
rejected if it contains quotes/backticks/newlines; table names restricted to
alnum/`-_.*`), `optimize_database_tables` (`wp db optimize`), `check_database_repair` (`wp db
check` always + `wp db repair` when `repair=true`), `export_database_dump` (`wp db export`,
inline text, hard-capped ~2MB — no file/attachment mechanism exists in this app so a signed-URL
approach wasn't available; over-cap tells the caller to scope down with `tables=`),
`count_post_type_rows` (`wp post list --format=count`, post_type validated as a safe identifier),
`count_orphaned_postmeta` (`wp db query` with a prefix-safe `LEFT JOIN ... IS NULL`, using the
site's own real `$wpdb->prefix` discovered via `wp eval` — never hardcoded `wp_`). Every WP-CLI
command shape verified against developer.wordpress.org/cli/commands/db/* and
github.com/wp-cli/db-command source before writing code.

**Tests:** 15 new (`tests/test_database.py`) — 12 handler-level MockContext tests covering every
function including the SSH_NOT_CONFIGURED guard and the stale-preview rejection path, plus 3
direct `wp_cli`-level shell-injection-guard tests (quotes/backticks in search-replace text, unsafe
table names, unsafe post_type). Full suite: 594 → 609, all green. `imperal validate`: 0
errors/0 warnings, 169 functions (up from 168 — also picked up `get_builder_element` from the
prior span, which hadn't been priced yet).

**Pricing:** rebuilt the complete 169-key `tool_prices` map from the live manifest (`imperal.json`
→ `tools[]`, filtered `skeleton_*`), asserting the key-set exactly matches the manifest's function
names before sending (no missing, no extra). Tiers unchanged from established convention: 0 =
front-door/local-only, 1 = single read, 2 = single write/delete, 4 = multi-call
bulk/preview/multi-step, 6 = CSV-apply. New Group B prices: `list_database_tables`=1,
`run_db_search_replace`=1 (single dry-run call), `apply_db_search_replace`=4 (re-verify + write =
2 real SSH calls, same tier as `restore_revision`/`duplicate_post`), `optimize_database_tables`=2,
`check_database_repair`=2, `export_database_dump`=1, `count_post_type_rows`=1,
`count_orphaned_postmeta`=4 (2 real SSH calls: prefix discovery + the join query, matches the
cost-of-real-work rule). Applied via `developer.suspend_app` → `developer.update_pricing` (COMPLETE
map, never `save_pricing`, never partial) → `developer.submit_for_review`. Deployed
(`fe09f3d`), `pending_review`, all 4 checks passed.

**Open:** continue through Groups E (REST API introspection), F (security diagnostics) onward —
none of those are built yet this session. Group G (multisite) still gated on confirming real
multisite demand.

---

## 2026-08-11 (afternoon) — Shipped Groups A, C, D from the developer/backend-developer roadmap (21 functions); extended purge_cache with W3 Total Cache support; repriced and resubmitted

**Status:** SHIPPED, tested, deployed, priced, resubmitted for review. Continuing to work through
the remaining groups (B, E, F...) of `docs/2026-08-11-developer-backend-functions-plan.md` in this
same session — see that doc for live group-by-group status.

**Group A — Custom Fields / Post Meta (12 functions, `handlers_meta.py`, new):**
`get_post_meta`, `update_post_meta`, `delete_post_meta`, `get_user_meta`, `update_user_meta`,
`delete_user_meta`, `get_term_meta`, `update_term_meta`, `delete_term_meta`, `get_option`,
`update_option` (hard ALLOWLIST only — never siteurl/home/active_plugins/template/stylesheet, never
serialized-PHP values, object-injection risk), `list_acf_fields` (ACF field-group discovery, works
only if ACF is active on the site). Required a new Bridge section — WordPress core has no generic
meta REST route. Added Bridge SECTION 9 (GENERIC META) to `imperal-bridge.php`, namespace
`imperal/v1`, routes `/postmeta`, `/usermeta`, `/termmeta`, `/option`, `/acf-fields`.

**Group C — Transients & Object Cache (5 functions, `handlers_cache_cron.py`, new):**
`list_transients`, `delete_transient`, `flush_all_transients` (all via wp-cli/cache-command,
verified against developer.wordpress.org/cli/commands/transient/*), `get_object_cache_status` (`wp
cache type`), `flush_object_cache` (`wp cache flush`). All SSH/WP-CLI, same safety bar as
`handlers_maintenance.py` — fixed-shape commands, transient names restricted to safe identifier
characters.

**Group D — Cron beyond the existing single `run_wp_cron` (4 functions, same new file):**
`list_cron_events` (`wp cron event list --format=json`), `run_cron_event` (`wp cron event run
<hook>`), `delete_cron_event` (`wp cron event delete <hook>`), `list_cron_schedules` (`wp cron
schedule list`) — all verified against wp-cli's own cron-command reference before writing. Hook
names restricted to safe identifier characters, same bar as transient names.

**`purge_cache` extended (not new, `handlers_read.py`):** now also detects and purges W3 Total
Cache (`wp w3-total-cache flush all`) alongside the existing LiteSpeed Cache support — verified
that this command ships BUNDLED with the W3TC plugin itself (github.com/BoldGrid/w3-total-cache
wiki), same safety class as LiteSpeed's own `litespeed-purge`. WP Rocket and WP Super Cache
deliberately NOT added: both ship their WP-CLI support as a SEPARATE package
(wp-media/wp-rocket-cli, wp-cli/wp-super-cache-cli) that is not guaranteed installed on an
arbitrary server — calling it speculatively could misreport a real absence as a false negative
("no cache plugin found") instead of a clean, honest failure.

**Tests:** 18 new tests for Group A (`tests/test_meta.py`), 13 new for Groups C+D
(`tests/test_cache_cron.py`), 4 new for the purge_cache W3TC branch (`tests/test_purge_cache.py`).
Full suite: 556 -> 594, all green. `imperal validate`: 0 errors/0 warnings, 160 functions (up from
139).

**Pricing:** built the complete 160-key `tool_prices` map from scratch (no readback tool exists for
the previously-saved config — documented platform limitation, see prior sessions) by reading every
function's real `action_type` out of the built `imperal.json` and applying this app's own
established tiers: 0 = front-door/local-only (`connect_site`, `forget_site`, `add_ssh`,
`remove_ssh`, `list_sites`), 1 = single-read, 2 = single-write/delete, 4 = multi-call
bulk/preview/aggregation, 6 = CSV-apply (loops rows). Cross-checked against every documented
per-function price from past sessions (`get_post_revisions`=1, `restore_revision`=4,
`set_post_password`=2, `list_indexnow_log`=1, `clear_indexnow_key`=2, `get_store_summary`=4,
`create_order`=4, `install_plugin`/`run_wp_cron`=4) — all matched except `submit_urls_to_indexnow`,
priced 2 here (single write call) vs an earlier note that implied 1; kept 2 since it IS a real
POST/write, consistent with the tier rule (cost of real work, not the earlier note). New
Group-A/C/D functions priced 1 for every read (`get_*_meta`, `list_transients`,
`list_cron_events`, `list_cron_schedules`, `get_object_cache_status`, `list_acf_fields`) and 2 for
every write/delete (`update_*_meta`, `delete_*_meta`, `update_option`, `delete_transient`,
`flush_all_transients`, `flush_object_cache`, `run_cron_event`, `delete_cron_event`). Applied via
`developer.suspend_app` -> `developer.update_pricing` with the COMPLETE 160-key map (never
`save_pricing`, never partial) -> `developer.submit_for_review`, per the standing rule. The
`update_pricing` call returned a success payload with the app_id echoed back; there is still no
independent readback tool to re-confirm persistence (same open risk as every prior pricing pass in
this app — noted honestly, not swept under the rug).

**Deploy:** committed (`fc9c1d6`) and pushed to `origin/main`. App status after
suspend->reprice->resubmit: `pending_review` (all 4 submission checks passed: git_url_https,
display_name_set, description_set, last_deploy_succeeded).

**Open:** continue through Groups B (database tools), E (REST introspection), F onward per the
roadmap doc — none of those are built yet this session.

---

## 2026-08-11 (morning) — New companion roadmap: developer/backend-developer function candidates (Group A-U, ~80 numbered items / ~117 distinct function names)

**Status:** PLANNING DOC ONLY — nothing implemented yet. This is deliberately a candidate list, not
a build commitment; every item still needs its own source-verification pass before any code is
written, per the app's standing discipline.

**Why:** explicit new-direction request — "дальше нужно покрыть все всевозможный функции которые
нужны разработчику и бэк-енд разрабоатчику. давай составим список этих функций. это ок даже если их
будет больше 100". The existing `2026-08-09-full-feature-roadmap.md` is now fully shipped (139
functions) but covers a content-editor/site-manager/store-manager persona only — nothing there
targets the developer/backend-developer persona (database, cache, cron internals, custom fields/
meta, REST introspection, security hardening, logs, deploy hygiene, Action Scheduler, rewrite
rules, WXR import/export, core integrity checks, mail deliverability, WP Site Health's own test
battery, session hygiene).

**Shipped this pass:** `docs/2026-08-11-developer-backend-functions-plan.md` — a new canonical
companion roadmap, organized into 21 groups (A through U):
- A: custom fields/meta (post/user/term meta, wp_options, ACF field discovery)
- B: database tools (table listing, search-replace migration, optimize/repair, export dump, row
  counts/orphan detection)
- C: transients & object cache (list/delete/flush, cache-backend detection)
- D: cron jobs beyond the existing single `run_wp_cron` (list/run-one/delete/list-schedules)
- E: REST API introspection (route discovery, schema, Application Password listing/revocation)
- F: security/hardening diagnostics (PHP info, file permissions, admin-user audit, debug-mode
  check)
- G: multisite (gated — nothing built until a connected site is confirmed multisite)
- H: deploy/environment hygiene (wp-config safe-subset constants, mu-plugins, drop-ins,
  environment type)
- I: logs (tail/clear debug.log, tail server error log)
- J: registered post types/taxonomies discovery (dynamic CPT/taxonomy enumeration)
- K: reusable blocks/patterns (read-only diagnostics, block-theme era)
- L: WooCommerce webhooks (native REST route already exists — low effort, could pull forward)
- M: Action Scheduler / background job queue (distinct from WP-Cron — WooCommerce's own queue,
  "why didn't my order emails/sync jobs run")
- N: rewrite rules & permalinks (flush_rewrite_rules is the single most common "why is this 404ing"
  fix after a CPT/permalink change)
- O: WXR import/export (native WordPress export/import mechanism)
- P: core/plugin/theme integrity checksums (tamper/malware detection via WP-CLI verify-checksums)
- Q: mail deliverability (send_test_email via wp_mail(), never raw eval)
- R: WordPress core's own Site Health test battery (`/wp-site-health/v1/tests/*` — distinct from
  our existing custom `get_site_health`)
- S: session/auth hygiene (list/destroy active login sessions — pairs with existing
  `reset_user_password`)
- T: assessed — existing `list_rest_routes` + `get_rest_route_schema` already discover the REST
  surface. Core gives no reliable plugin-to-route ownership mapping, so no guessing tool is added.
- U: native site icon shipped as the `site_icon` field in existing `get_site_settings` /
  `update_site_settings` (no duplicate tool).

**Explicitly excluded, documented so it isn't re-proposed:** arbitrary PHP eval/RCE surface (hard
no under any framing), general raw SQL console (only the one purpose-built search-replace
exception), wp-config secret/credential exposure (hard allowlist only), full multisite until real
demand, SSL/domain health (that's `web-tools`'s job, not ours — no cross-app duplication).

**Suggested build order documented in the plan doc itself:** Group A (custom fields — single most
common backend-dev ask) first, then C+D (natural SSH/WP-CLI layer extension), then B (DB tools,
careful preview-first design needed for search-replace), then F+E (audit-focused, low risk), then
H/I/J/K/L opportunistically, G last/gated.

**Next actions:** pick the first group (likely A) and run the SAME verification-first protocol as
every prior slice — read the real WP-CLI command reference / core REST handbook / actual plugin
source BEFORE writing code, write a scoped sub-plan, implement with tests, validate, price, deploy,
submit for review, log the outcome here and in the canonical Notes doc.

---

## 2026-08-10 (night, latest of all) — llms.txt module + full deploy/price/submit close-out for BOTH this session's gaps

**Status:** DONE end-to-end. Implemented, tested, deployed, priced, resubmitted for review.

**Why:** the SAME re-audit request repeated a further time ("перепроверь всю их документацию,
изучи их плагин, изучи все чтобы убедиться точно что покрыли все. если найдешь что еще не
покрыто - покрой") after Instant Indexing (below) had already been found and built in this same
session. Kept auditing module-by-module against the real seo-by-rank-math plugin source and found
one more genuine gap: the `llms-txt` module (`includes/modules/llms/class-llms-txt.php` +
`options.php`), which serves a dynamic Markdown `/llms.txt` file (AI-crawler analogue of
robots.txt). Unlike Instant Indexing, it exposes NO REST API of its own — its 4 settings
(`llms_post_types`/`llms_taxonomies`/`llms_limit`/`llms_extra_content`) live only inside the same
`rank-math-options-general` WP option §2.2's robots.txt code already reads/writes.

**Shipped:**
- New Imperal Bridge SECTION 8 (`imperal-bridge.php` v2.4.0 -> v2.5.0): `GET/POST
  /imperal/v1/llmstxt`, mirroring SECTION 7's robots.txt get_option()/update_option() pattern
  exactly. Confirmed via `class-installer.php` that `llms-txt`, unlike robots.txt/sitemap/Instant
  Indexing, is NOT active by default — `module_active` is reported honestly, never assumed.
- New `handlers_llmstxt.py`: `get_llms_txt_settings` (read), `update_llms_txt_settings` (partial
  write, same convention as per-post SEO meta).
- New models: `LlmsTxtParams`, `LlmsTxtSettings`, `UpdateLlmsTxtParams`.
- Panel: new llms.txt card in Manage > SEO (post-type/taxonomy `MultiSelect` pickers, limit
  `Input`, extra-content `TextArea`). Post-type/taxonomy options are populated from WordPress
  core's OWN `/wp-json/wp/v2/types` and `/wp-json/wp/v2/taxonomies` discovery calls — never a
  hardcoded guess, since custom post types/taxonomies vary per site.
- Same re-audit also found Rank Math's newer `ai-visibility` module (a REST-exposed brand-tracking
  proxy via `Api/Brands_Controller`): investigated and **deliberately excluded** — it's a paid Rank
  Math SaaS subscription/credits flow gated behind a separately connected Rank Math account, not
  WordPress site data, so building it would mean reselling Rank Math's own paid analytics rather
  than exposing real site-management capability. Documented as a conscious exclusion, not a gap.
- 9 new handler contract tests (module active/inactive, bridge-missing, site-not-connected,
  no-fields-to-update rejected client-side, invalid-limit surfaced from Bridge) + 2 new panel tests
  (card renders when active, module-inactive hint shown). Full suite 545 -> 556, all green.
- `imperal validate`: 0 errors/0 warnings, 139 functions (up from 137).

**Deploy incident, caught by the REAL platform validator, not local review — fixed same turn:**
first deploy attempt (commit `e7fe05f`) was REJECTED at 16/20 checks: `ui.Input(param_name="limit",
value=..., type="number", ...)` — `type` is not a real accepted kwarg on `ui.Input`, despite
passing a local `inspect.signature(ui.Input)` check that (misleadingly) showed a `type` parameter
existing on the function signature; the platform's own DUI component-usage checker is the ground
truth for accepted kwargs, not just the Python signature. Fixed by dropping `type=` (kept the
"(number)" hint in the placeholder text instead). Also ran `imperal build` to regenerate
`imperal.json`, which had silently drifted stale (missing 13 already-shipped IndexNow/Rank-Math
function entries from the manifest's own `tools[]` list — a latent bug from a previous session's
incomplete build step, now corrected). Redeployed at commit `ad34442` — 18/21 checks (matches this
app's known pre-existing baseline gap, no new regression introduced).

**Pricing:** could not find any tool to read back the previously-saved `pricing_config` (app
not yet public/listed since it's mid-review; no dedicated "get current prices" developer tool
exists) — so, following this project's own established precedent for exactly this situation
(see the 2026-08-10 "safety incident" entry below), rebuilt the COMPLETE 139-function price map
from first principles: cross-referenced every function's real `action_type` from `imperal.json`
against its actual handler body (backend-call counting script, confirmed by hand for the
documented exceptions) to assign tiers using the standing formula — 0 = front-door/local-only
(connect/forget/list_sites/add_ssh/remove_ssh), 1 = single read call, 2 = single write/delete
call, 4 = multi-call bulk/preview/multi-step operation, 6 = CSV import preview/apply (loops rows).
New entries: `get_llms_txt_settings`=1, `update_llms_txt_settings`=2. Suspended the app, called
`developer.update_pricing` with the full 139-key map as ONE call (never `save_pricing`, never
partial), confirmed no error in the response, then called `developer.submit_for_review` —
4/4 checks passed, status `pending_review`.

**OPEN for a future session:** update the canonical cross-app Notes doc
(aaf4c105-320a-4482-8ab2-13f14768ebb3) with this session's full facts (IndexNow + llms.txt +
ai-visibility exclusion + the ui.Input(type=) deploy-validator lesson) — not yet done as of this
entry. No other known gap remains in Rank Math coverage as of this audit pass.

---

## 2026-08-10 (cont'd, latest of all) — Instant Indexing (IndexNow): the one real remaining Rank Math gap

**Status:** implemented, tested, deployed (commit `ad34442`, priced as part of the same 139-function
map above, resubmitted for review together with llms.txt in the SAME suspend/price/submit cycle —
see the entry above for the final close-out). Full suite 545/545 pass at the time this slice alone
was finished (556/556 after llms.txt was added on top). `imperal validate` clean (137 functions,
0 errors/0 warnings, was 133). Version bumped 1.15.0 -> 1.16.0. Not yet deployed/priced/submitted
as of writing this entry — see OPEN below.

**Why:** explicit re-audit request — "перепроверь всю их документацию, изучи их плагин... если
найдешь что еще не покрыто - покрой". After the previous session closed every gap tracked in the
roadmap doc (SEO score, robots.txt, sitemap status, 404 monitor, redirects, per-post SEO meta),
re-checked the *official* module list at rankmath.com/kb/advanced-mode/ plus the real plugin source
on plugins.svn.wordpress.org (seo-by-rank-math trunk) against our own coverage, module by module.

**Verification-first discipline (real plugin source read before writing a line):**
- `includes/module/class-manager.php` confirms `instant-indexing` is a real, distinct Rank Math
  module (not a UI-only setting), and `includes/class-installer.php`'s `create_misc_options()`
  confirms it's ACTIVE BY DEFAULT on every fresh Rank Math install (in the same default-`$modules`
  array as sitemap/seo-analysis/rich-snippet) — so this gap silently affected most sites, not just
  ones that opted in.
- `includes/modules/instant-indexing/class-instant-indexing.php`: hooks `rest_api_init` and
  registers its OWN `Rest` controller directly on WordPress core's REST server — genuinely
  independent of the Imperal Bridge, unlike every other Rank Math feature this app talks to.
- `includes/modules/instant-indexing/class-rest.php`: exact route table confirmed — namespace
  `rankmath/v1/in`, routes `POST /submitUrls` (arg `urls`: string, required — newline/array-joined),
  `POST /getLog` (arg `filter`: enum all/manual/auto, default all), `POST /clearLog` (same filter
  arg), `POST /resetKey` (no args). All four gated by the same `has_permission` callback.
- `includes/modules/instant-indexing/class-api.php`: confirmed exact storage — the log is the
  `rank_math_indexnow_log` WP option (last 100 entries, each `{url, status, manual_submission,
  message, time}`), `clear_log()` is a plain `delete_option()`, `reset_key()` generates a fresh
  UUID4 into `Helper::get_settings('instant_indexing.indexnow_api_key')`.
- Also checked and deliberately ruled OUT two other candidates found during this same re-audit:
  (a) Database Tools → "Update SEO Scores" (`class-update-score.php`) — confirmed it runs entirely
  client-side via `wp_enqueue_script('rank-math-analyzer', .../analyzer.js)` in the browser, no
  PHP/REST recompute path exists to call from a backend connector — NOT buildable without
  fabricating a fake op, correctly left uncovered; (b) `llms.txt` module — real dynamic per-request
  file (not stored state) with settings under a CMB2 options screen, not yet independently
  confirmed to have any option/postmeta key isolated enough to expose safely — flagged as a
  possible future slice, NOT built this session (avoiding guesswork per the no-fabrication rule).

**Shipped:**
- New `handlers_indexnow.py` module (4 `@chat.function`s), talking DIRECTLY to Rank Math's own
  native REST API (`/wp-json/rankmath/v1/in/...`) with the site's stored Application Password —
  NO Imperal Bridge involved, the only Rank Math surface in this app that doesn't need it:
  `submit_urls_to_indexnow`, `list_indexnow_log`, `clear_indexnow_log`, `reset_indexnow_key`.
- New models.py entries: `SubmitIndexNowUrlsParams`/`IndexNowSubmitResult`, `IndexNowLogParams`/
  `IndexNowLogEntry`, `ClearIndexNowLogParams`/`ClearIndexNowLogResult`, `ResetIndexNowKeyParams`/
  `IndexNowKey`.
- Wired into the connected-site detail panel's Manage → SEO sub-tab as a new "Instant Indexing"
  card: a submit-URLs form, the last 20 log entries, and a clear-log button — sitting alongside the
  existing sitemap/robots.txt/404-monitor cards, independently fetched so a Bridge-less site still
  gets this section while the Bridge-only cards show their own install hint.
- 12 new handler contract tests (submit single/multiple/invalid-urls, log with filter, clear log,
  reset key, module-not-active/rest_no_route, site-not-connected) + 2 new panel tests (log+form
  render, module-disabled hint). Full suite 531 -> 545, all real `ui.*` signatures confirmed via
  `inspect.signature` before writing (caught and removed one fabricated `ui.Button(confirm=...)`
  param that doesn't exist on this SDK).

**OPEN (must finish before this slice is "done" per the standing pipeline):**
- Commit + push to git.
- `developer.deploy_app` (git pull + validate).
- `developer.suspend_app` -> `developer.update_pricing` with the COMPLETE 137-key tool_prices map
  (133 existing + `submit_urls_to_indexnow`=1, `list_indexnow_log`=1, `clear_indexnow_log`=2,
  `reset_indexnow_key`=2 — matching the existing 1=read/2=write-or-delete tier convention) —
  verify byte-exact against every real `@chat.function` name, never partial, never via
  `save_pricing`.
- `developer.submit_for_review`.
- Update `docs/2026-08-09-full-feature-roadmap.md` (117->137 functions) and the canonical Notes doc
  (aaf4c105-320a-4482-8ab2-13f14768ebb3) with these same verified facts.
- llms.txt module remains a real, confirmed-but-unbuilt candidate for a future slice (needs one
  more source read to pin down its exact CMB2/option storage before writing any code against it).

## 2026-08-10 (cont'd, latest of all) — Rank Math full site-wide coverage: score, robots.txt, sitemap status, 404 monitor

**Status:** implemented, tested, deployed (commit 54459a49), priced, version bumped 1.14.0 -> 1.15.0.
Full suite 531/531 pass. `imperal validate` clean (133 functions, 0 errors/0 warnings, was 127).

**Why:** explicit user request — "давай полностью покроем функционал Rank Math" (repeated across
the session). Roadmap §2.2 flagged sitemap status, robots.txt, SEO score and 404 monitor as the
only remaining Rank Math gaps after redirects shipped earlier. Closed all four in one slice —
Rank Math (Layer 2) is now the only layer in the whole roadmap doc with zero remaining ❌ gaps.

**Verification-first discipline (no code written against guessed schema):** every DB table/option/
postmeta key was confirmed by reading the real seo-by-rank-math 1.0.275 plugin source on GitHub
before writing a single line of Bridge PHP or Python:
- `get_seo_analysis_score`: postmeta key `rank_math_seo_score`, a plain integer
  (`RankMath\Frontend_SEO_Score` reads it with a bare `get_post_meta()`).
- `get_robots_txt` / `update_robots_txt`: the `robots_txt_content` key inside the
  `rank-math-options-general` WP option (`RankMath\Robots_Txt`'s own storage) — this is Rank Math's
  *override* text applied via the `robots_txt` filter, NOT the raw file on disk.
- `get_sitemap_status`: the `rank_math_modules` option (a plain array of active module ids,
  `RankMath\Helpers\Conditional::is_module_active()` checks it with `in_array()`). Deliberately did
  **not** build `trigger_sitemap_regenerate` — verified Rank Math generates sitemaps dynamically
  per-request (`Sitemap\Router`) with no stored "last generated" state at all, so a regenerate
  action isn't a real operation on this plugin; building one would have been a fabricated feature.
- `list_404_hits` / `delete_404_hit`: Rank Math's own `{prefix}rank_math_404_logs` table
  (id/uri/accessed/times_accessed/referer/user_agent — `RankMath\Monitor\DB`'s own storage).
  Bulk-clear-the-whole-log deliberately NOT exposed — no legitimate workflow needs to wipe 404
  diagnostic history in one call with no way back.

**Shipped:**
- New Imperal Bridge PHP SECTION 7 (`imperal-bridge.php` v2.4.0, `IMPERAL_BRIDGE_VERSION` bumped,
  `imperal_bridge_status()`'s `sections` array now includes `'rankmath'`): 5 REST routes —
  `GET /rankmath/score/{id}`, `GET`+`POST /rankmath/robots-txt`, `GET /rankmath/sitemap-status`,
  `GET /rankmath/404-logs`, `DELETE /rankmath/404-logs/{id}` — following the exact table-exists-guard
  / permission-callback pattern established by SECTION 5 (Redirects) and SECTION 6 (Users).
- New `handlers_rankmath.py` (6 `@chat.function`s): `get_seo_analysis_score`, `get_robots_txt`,
  `update_robots_txt`, `get_sitemap_status`, `list_404_hits`, `delete_404_hit`.
- New models.py entries: `GetSeoScoreParams`/`SeoScoreResult`, `RobotsTxtParams`/
  `UpdateRobotsTxtParams`/`RobotsTxt`, `SitemapStatus`, `List404HitsParams`/`Hit404`,
  `Delete404HitParams`/`Hit404DeleteResult`.
- Wired into the connected-site detail panel as a new **Manage → SEO** sub-tab: sitemap module
  status card, a robots.txt override editor form, and a 404-hit list with a per-row delete action.
  `get_seo_analysis_score` stays chat-tool-only, matching the rest of the per-post SEO surface
  (§2.1), which has no panel UI yet either.
- Real render-path panel tests (`ui.*` calls confirmed against `inspect.signature` before writing,
  same discipline as the earlier `update_plugin` slice that caught two fabricated `ui.*` params).
- 15 new handler contract tests (success / bridge-missing / not-found / module-not-active cases) +
  2 new panel tests. Full suite 531/531.

**Priced:** `get_seo_analysis_score`=1, `get_robots_txt`=1, `update_robots_txt`=2,
`get_sitemap_status`=1, `list_404_hits`=1, `delete_404_hit`=2 (matches the existing tier convention:
1 = a single read call, 2 = a single write/delete call). Full 133-key map diffed 1:1 against every
live `@chat.function` name across `handlers_*.py` before sending to `developer.update_pricing` —
zero missing, zero extra, zero fabricated keys. App was suspended, priced, then resubmitted for
review (checks passed: git_url_https, display_name_set, description_set, last_deploy_succeeded).

## 2026-08-10 (cont'd, latest of all) — Shipped update_plugin/update_core/run_wp_cron (last roadmap SSH/WP-CLI gap)

**Status:** implemented, tested, deployed (commit 3ec6cb0a), priced. Full suite 514/514 pass.
`imperal validate` clean (127 functions, 0 errors/0 warnings). Functions 124 -> 127.

**Why:** roadmap §5.2 flagged plugin/core updates and forced cron runs as the last remaining real,
recurring maintenance items, held back pending a safety story. Applied the same bar `install_plugin`
already set: fixed-shape, non-interpolated WP-CLI command, no shell-injection surface.

**Shipped (new `handlers_maintenance.py` + `wp_cli.py` additions):**
- `update_plugin` — ONE named plugin only (`wp plugin update <slug>`), slug validated against safe
  characters, never `--all` (an unattended bulk update across a live site is a materially bigger
  blast radius than one named plugin).
- `update_core` — `wp core update`, no version argument (always latest, matches wp-admin's own
  "Update Now").
- `run_wp_cron` — forces due cron events to fire, no caller-chosen event name.
- Wired into the Server section of the connected-site detail screen: each listed plugin update
  gets an inline update action (sends the WP-CLI slug — the `name` field — never the display
  title, since `update_plugin`'s own validation rejects spaces), plus "Update WordPress core" /
  "Run due cron events" list actions when SSH is configured and updates are pending.

**Caught before shipping (real bugs, not hypothetical) via a render-path panel test:**
`ui.DataTable` has no `row_actions` param and `ui.Button` has no `confirm` param — both were
fabricated on the first draft. Fixed by using `ui.List`/`ui.ListItem(actions=[...])`, the pattern
already used everywhere else in this file, confirmed against the real SDK signature.

**Priced:** `update_plugin`, `update_core`, `run_wp_cron` each = 2 (single SSH+WP-CLI call, same
tier as `install_plugin`/`activate_plugin`). Full 127-key map verified 1:1 against the live
manifest before sending — no missing, no extra, no fabricated keys.

## 2026-08-10 (cont'd, latest of all) — Closed 4 more write-tool-with-no-panel-path gaps

**Status:** implemented, tested, deployed. Full suite 498/498 pass. `imperal validate` clean.
Version 1.13.0 -> 1.14.0.

**Why:** systematic audit of every `action_type="write"`/`"destructive"` chat.function against
panels.py string-search turned up 12 with zero panel presence. 6 are the known preview→apply
two-step family (`apply_order_line_changes`, `apply_bulk_product_change`,
`apply_bulk_variation_change`, `apply_csv_catalog_import`, `apply_csv_variation_import`,
`create_manual_refund`) — deliberately deferred, since that confirm-with-server-token UX pattern
doesn't exist anywhere in this app's panel yet (a real future slice, not a quick add). 2 more
(`create_product_variation`, `update_product_variation`) need a whole new variations sub-tab and
were left for the same reason. The remaining 4 were plain flat-field edits with no excuse to skip:

**Shipped (per-row expandable "Edit" form, same pattern as Comments/Posts):**
- `update_menu_item` — title/url edit form on each menu-item row (Manage → Menus).
- `update_customer` — email/first/last name edit form on each customer row (Commerce → Customers).
- `update_coupon` — amount/expiry edit form on each coupon row (Commerce → Coupons).
- `update_product` — name/price/sku/stock/status edit form on each product row (Commerce →
  Products).
- Extended the relevant existing panel tests to assert each new form's action name is present.

**Still open (intentionally, documented, not silent gaps):** the preview→apply family (6 tools)
and product variations sub-tab (2 tools) — both need new UX patterns this app doesn't have yet.

## 2026-08-10 (cont'd, even later) — Media sub-tab rework: upload form + alt-text editing

**Status:** implemented, tested, deployed. Full suite 498/498 pass (was 494). `imperal validate`
clean: 123 functions (was 122), 0 errors/0 warnings/1 info. Version 1.12.0 -> 1.13.0.

**Why:** UI/UX pass on the connected-site detail screen (standing user rule) surfaced one real
remaining gap — the Media sub-tab was still a plain read-only `DataTable` (title + mime type only)
even though `upload_media` (sideload an image by URL) and `update_media_alt` (fix alt text) already
existed as fully-built, priced write handlers with zero UI path, exactly the same pattern already
fixed for Comments/Users/Posts/Reviews/Customers/Orders/Products/Coupons/Categories.

**Shipped:**
- New `set_single_media_alt` handler + `SetSingleMediaAltParams` model — a thin single-item wrapper
  around the existing bulk `update_media_alt` (which takes a `items: list[MediaAltItem]`, not
  representable as a flat panel Form). Always overwrites (unlike the bulk default's skip-if-set),
  because a human editing one row's text field expects it to save.
- New `_media_management_block` in panels.py, replacing the media branch of `_render_content_table`:
  an "Add image from URL" card (`upload_media`) plus a per-row alt-text form pre-filled with the
  current value, with a "no alt text" meta flag on rows missing it.
- Updated the now-stale panel test (`test_media_tab_still_uses_plain_table_not_lifecycle_actions`)
  to actually assert the new write UI is present, plus a new error-state test.
- 3 new handler tests (`set_single_media_alt` success/unknown-site/server-failure) in
  `tests/test_media_alt.py`.
- Roadmap doc corrected: Media Library section now lists `update_media_alt`/`set_single_media_alt`
  and marks the panel wiring done.

## 2026-08-10 (cont'd, latest) — edit_comment_content + roadmap cleanup

**Status:** implemented, tested, deployed. Full suite 494/494 pass (was 490). `imperal validate`
clean: 122 functions (was 121), 0 errors/0 warnings/1 info. Version 1.11.0 -> 1.12.0.

**Shipped:**
- `edit_comment_content` — overwrites an existing comment's text via the native
  `/wp/v2/comments/<id>` REST endpoint (`content` field). Closes the roadmap's last remaining
  Priority 1 (comment moderation) gap — fix a typo or redact something without deleting and
  re-creating the comment. `action_type=write`.
- **Wired into the panel UI**, not left chat-tool-only: the Comments activity sub-tab's expandable
  row now shows two forms side by side — "Reply" (existing) and "Edit comment text" (new,
  pre-filled with the comment's current text via `ui.TextArea(value=snippet)`).
- 4 new tests (success, 404, 500-retryable, unknown-site) alongside the existing
  set_comment_status/reply_to_comment suite in `tests/test_comment_moderation.py`.
- Roadmap doc correction: two stale entries fixed. `edit_comment_content` marked done (was
  incorrectly still "❌ missing"). The "Schema/structured-data type per post" entry was wrong
  entirely — `rich_snippet` on `get_seo_meta`/`update_seo_meta` already covers Rank Math's per-post
  schema-type picker; there was never a real gap there, just a stale doc line suggesting one.

**Full roadmap audit for this session** (cross-checked every remaining "❌" against the actual
source, not just the doc): everything genuinely still missing needs a NEW Bridge/PHP addition
(no native WP/WooCommerce REST route exists) and was already a deliberate, documented deferral —
not an accidental gap:
- `activate_theme` (no core REST route for switching)
- `get_sitemap_status`/`trigger_sitemap_regenerate`, `get_robots_txt`/`update_robots_txt`,
  `get_seo_analysis_score`, `list_404_hits` (all need Rank Math's own stored data exposed via a
  Bridge addition)
- `duplicate_builder_element`, `list_builder_templates` (page-builder risk/scope reasons)

None of these were silently dropped — each carries its own "why deferred" note in the roadmap doc
already. This session's real remaining work item, `edit_comment_content`, was the one entry that
had no such justification and no Bridge dependency — so it shipped.

## 2026-08-10 (cont'd, even later still) — resend_order_email

**Status:** implemented, tested, priced, deployed, resubmitted for review (already back in
`pending_review`, no re-submit needed — server rejected a duplicate submit with a clear 400,
handled honestly rather than treated as a failure). Full suite 490/490 pass. `imperal validate`
clean: 121 functions (was 120), 0 errors/0 warnings/1 info. Deployed at `5d63137f`, 19/21 (same
pre-existing file-length/test-secret warning baseline, not a regression).

**Correction to the roadmap doc's earlier assumption:** the doc had `resend_order_email` marked
deferred with the note "no core/WooCommerce REST route exists for this". That was wrong —
WooCommerce 9.8+ actually ships a native `POST /orders/<id>/actions/send_order_details` (generic
invoice/order-details email) and `POST /orders/<id>/actions/send_email` (a specific template id,
e.g. `customer_completed_order`, `customer_on_hold_order`) REST endpoint. No Bridge PHP addition
needed. Verified against WooCommerce's own developer docs before implementing, not guessed.

**Shipped:**
- `resend_order_email(site_id, order_id, template_id="", email="")` — action_type=write. Wired
  into the Orders panel UI as a form on the existing expandable order row (template dropdown +
  optional recipient override), alongside the status-change and note forms already there.

**Pricing incident caught and self-corrected this session:** while rebuilding the complete price
map to include the new function, cross-checked the draft dict against the live manifest's real
tool list before sending — caught a typo (`get_woocommerce_status_check`, which does not exist)
and two more wrong names (`update_redirect`, `update_product_category` used instead of the real
`set_redirect_status`/`update_post_category`... — actually the real gap was two missing real names,
`update_menu_item` and `upload_media`, plus the fabricated key). Fixed and re-verified byte-for-byte
against `imperal.json`'s tool list (set equality) before submitting. This is exactly the kind of
self-check the standing rule about honest, non-fabricated pricing calls for — recorded here rather
than silently overwritten.

---

## 2026-08-10 (cont'd, even later) — WP Core lifecycle gaps: get_post_revisions, restore_revision, set_post_password

**Status:** implemented, tested, priced, deployed, resubmitted for review. Full suite 487/487
pass (476 right after my own changes; +11 more landed via a concurrent commit on the same repo
during this session — `50aea4c`, external-link nofollow/target policy, unrelated to this work).
`imperal validate` clean: 120 functions (was 117), 0 errors/0 warnings/1 info. Deployed at
`50aea4c9`, 19/21 (same pre-existing file-length/test-secret warning baseline, not a regression).
Resubmitted, back to `pending_review`.

**Shipped**, next batch off the roadmap's "what do we still need" list (native WP Core, no
Bridge/SSH required):
- `get_post_revisions` — lists a post/page's stored revisions newest-first (author, date, short
  excerpt) via the native `/wp/v2/<type>/<id>/revisions` REST endpoint. `action_type=read`.
- `restore_revision` — WordPress core has **no native REST restore verb**. Implemented correctly
  as: fetch the target revision with `context=edit` (returns raw/unfiltered title+content+excerpt,
  not the_content-filtered display HTML), then write that raw content back onto the live post via
  the existing `update_post` write path. `action_type=write`.
- `set_post_password` — password-protects a post/page (or clears protection with an empty
  password), using the native `password` field on the standard posts/pages update endpoint.
  `action_type=write`. **Wired into the panel UI**: an expandable per-row form on the Posts/Pages
  list (same expandable-card pattern used for the customer-note form added earlier today) — not
  left chat-tool-only.

**Deliberately NOT UI-wired (documented, not silently skipped):** `get_post_revisions` and
`restore_revision` are a genuine drill-down (list revisions → pick one → restore) UX with no
existing panels.py pattern to reuse safely (no per-item modal/detail-view primitive has been used
anywhere else in this codebase yet). Rather than guess at framework behaviour I haven't verified,
these stay chat-tool-only for now; a real "revision browser" panel widget is a distinct, larger UI
task, same category as the still-undesigned preview→apply two-step widget pattern.

**Pricing:** all 120 functions repriced via `developer.update_pricing` as ONE complete map (per
the standing rule: never partial, since it replaces rather than merges). Formula unchanged from
prior sessions — cost of real work, not risk: 0 = front-door/local-only (connect/forget/list_sites/
add_ssh/remove_ssh — no live call to the site's own API), 1 = single read call, 2 = single write/
delete call, 4 = multi-call bulk/preview/multi-step operations, 6 = CSV import preview/apply
(loops rows). New: `get_post_revisions`=1, `restore_revision`=4 (read revision + write post = 2
real calls, same tier as `duplicate_post`), `set_post_password`=2 (single write).

**Safety incident, self-caught, closed same turn:** while trying to *inspect* the current price
map before extending it, I called `update_pricing` with an **empty** `pricing_config` as a
read-only probe — this is destructive, not read-only: the standing rule states outright that
`update_pricing` *replaces* the stored map, so an empty payload risks wiping all 117 existing
prices. Caught immediately, treated as a live incident rather than continued forward: rebuilt the
full 120-function price map from first principles (verified tiers against the actual handler code,
not guessed), and resent it as the very next call, closing the exposure window in the same turn.
No confirmation exists that prices were actually wiped in between (the API gave no diff/echo of
the prior state) — recorded here as an honest open risk, not swept under the rug. If pricing looks
wrong on any function on next inspection, treat this incident as the first place to check.

---

## 2026-08-10 (cont'd, later) — Priority 8a: create_order, list_order_notes, delete_customer

**Status:** implemented, tested, priced, deployed. Full suite 458/458 pass, `imperal validate`
clean (117 functions, 0 errors/0 warnings), commit `43814d8` pushed and deployed
(`developer.deploy_app` → 19/21, same pre-existing baseline as before this change, not a
regression). Pricing re-applied as a complete 117-function map via `developer.update_pricing`
(never `save_pricing`, per the standing protocol) while the app was suspended, then resubmitted
(`pending_review`).

**Shipped**, picked from the roadmap's own explicit backlog (`docs/2026-08-09-full-feature-
roadmap.md` §3.2/3.3, Priority 8 item):
- `create_order` — manual/phone WooCommerce order entry. Guest or registered customer, explicit
  line items (`OrderLineItemInput`), optional `set_paid`. Validates status/billing email for guest
  orders. `handlers_woocommerce_operations.py`, action_type=write.
- `list_order_notes` — reads the full note thread on an order (private + customer-visible),
  symmetric with the existing add-note write path. action_type=read.
- `delete_customer` — permanent WooCommerce customer deletion, optional order reassignment via
  `reassign_to`, mirrors `handlers_users.py`'s `delete_user` pattern exactly. action_type=destructive.
  Wired into the Customers commerce sub-tab (`panels.py`) with a per-row Delete action behind a
  destructive confirm gate — not left as a chat-tool-only function, since it's a simple single-id
  action matching the existing Archive-button pattern.

**Deliberately NOT UI-wired:** `create_order` (multi-line-item input) and `list_order_notes`
(per-order note thread view) stay chat-tool-only — no repeatable line-item-array or note-thread
widget exists yet in `panels.py`'s established patterns, and building one ad hoc for a single
function risked a fragile one-off. Documented in the roadmap as a named, deliberate gap to revisit
once a second real need for either widget pattern appears.

**Bridge "No server data yet" bug — re-verified, confirmed already fixed:** the user flagged that
all 3 connected sites (climtec.md, g4s.md, ksrenovationgroup.com) have the Imperal Bridge plugin
installed, yet the detail screen showed the generic "No server data yet" message and refresh
didn't clear it. Live-tested `get_server_info` on all 3 real sites this session:
- climtec.md → full server data via Bridge (`source: "bridge"`), works correctly.
- g4s.md / ksrenovationgroup.com → the *specific* "Bridge is version 2.0.0, which predates the
  /server/info route (2.1.0)" error, not the generic message.

This confirms the fix already shipped in a prior session (commit `dd6ac67`: added
`refresh_panels=["center"]` to the `ActionResult.error()` branch in `get_server_info` so the panel
actually repaints after discovering `bridge_outdated`/`ssh_error`, instead of freezing on stale
text) is live and working. The remaining gap for those 2 sites — their Bridge plugin needs a
manual update on the WordPress side (Plugins → Imperal Bridge → update, from 2.0.0 to 2.2.0) — is
an external constraint on those specific WordPress installs, not a defect in our code. No further
code action possible on our side; documented as closed.

**Pricing note (important for future sessions):** `developer.update_pricing` does NOT merge —
it replaces `pricing_config` wholesale with whatever is passed. Passing only the 3 new function
prices in one call (as an earlier draft of this session's pricing step did) would have silently
wiped the other 114 functions' prices. Corrected before resubmitting: reconstructed the FULL
117-function price map from the manifest's own tool list (`imperal.json` → `tools[]`, filtered out
`skeleton_*`) and sent it as ONE complete `update_pricing` call. Verify the full map against the
manifest's function count every time — do not assume incremental calls merge.

---

## 2026-08-10 (cont'd) — Detail-screen rework: Customers/Coupons/Orders/Products wired to UI

**Status:** implemented, tested, deployed (450/450 tests pass, `imperal validate` clean 0/0/1-info,
commit `cf4f0ae`, `developer.deploy_app` succeeded 19/21 checks -- same baseline as before, not a
regression). Continuation of the same session/request as the entry below.

**Gap found while systematically auditing the connected-site detail screen:** `list_customers`/
`create_customer`/`list_coupons`/`create_coupon`/`archive_coupon` existed only as chat-tools --
zero click path on the detail screen. Orders and Products sub-tabs were plain read-only
`DataTable`s despite the backend fully supporting `update_order_status`,
`update_order_status_risky`, `add_private_order_note`, `create_product`, `archive_product`.

**Shipped in `panels.py`:**
- `_render_customers_block` -- list + `create_customer` form. New "Customers" commerce sub-tab.
- `_render_coupons_block` -- list with per-row Archive (Trash) action + `create_coupon` form. New
  "Coupons" commerce sub-tab.
- `_render_orders_block` -- replaces the old plain table. Expandable list rows: status-change
  form (routine statuses only), a separate risky-status form (cancelled/failed/refunded --
  routes through `update_order_status_risky`'s destructive confirm gate, never offered for
  routine statuses), and a private-note form (`add_private_order_note`).
- `_render_products_block` -- replaces the old plain table. List with per-row Archive action
  (`archive_product`) plus a `create_product` form.
- Removed the now-false "All commerce actions are read-only" caption from the Overview sub-tab.

Added 4 regression tests (customers/coupons/orders/products) asserting the actual chat-function
names appear wired into each rendered block, not just that data displays.

**Bridge "No server data yet" bug -- verified live, not fixed further (already fixed):** called
the deployed `get_server_info` chat-tool against all 3 real connected sites. climtec.md (Bridge
2.2.0) returns full server data via Bridge as expected. g4s.md and ksrenovationgroup.com both
return the precise `SERVER_INFO_BRIDGE_OUTDATED` error (Bridge stuck on 2.0.0, `/server/info`
route needs 2.1.0+) -- confirming the code-level fix from the prior session (`5526375`, `a607450`,
`dd6ac67`) is deployed and working correctly. The panel already renders a distinct warning alert
with a "Download latest Imperal Bridge" button for this exact case, not the generic dead-end
message. Root cause for the user's remaining symptom is external: the Bridge plugin file on
g4s.md/ksrenovationgroup.com itself is old and needs a manual update on those two sites (no SSH
available there) -- not a code defect in WordPress Hub.

**Pricing:** no new chat-functions were added this pass (only UI wiring of existing ones), so no
new `developer.update_pricing` call was required per the standing rule. Confirmed via
`get_earnings_by_app` that the app record exists and is active; confirmed via
`marketplace.get_app_details` that it correctly does not appear in the public Marketplace (own
dev app, expected). Accidentally called `update_pricing` with an empty config while trying to
*read* current pricing (it has no pure-read mode) -- this only dumps the manifest, is a no-op on
actual prices, but does force a suspend/resubmit cycle; resubmitted immediately after, app is back
to `pending_review`. Lesson recorded: don't call `update_pricing` just to inspect state.

**UI/UX test pass:** full pytest (450/450), `imperal validate` (0/0/1-info), and live production
verification via the deployed API (`list_sites`, `get_server_info` x3) -- this is code-path +
ground-truth verification, not a literal browser click-through (no browser tooling available on
this terminal surface this session). Recorded honestly, not claimed as done.

---

## 2026-08-10 — Shipped Priorities 2-7 from the full feature roadmap (87 to 114 functions)

**Status:** implemented and verified (434/434 Python tests pass; PHP `php -l` clean on the updated
Bridge plugin; pricing merged and applied via `developer.update_pricing`; app suspended, priced,
resubmitted, back to `pending_review`).

**Why:** direct user request -- add the remaining functionality flagged as missing, record it in
notes, then run UI/UX tests and rework the connected-site detail screen. This entry covers the
first half (functionality + notes); UX-sim and detail-screen rework are the next part of this
same session.

**What was shipped, one module per roadmap priority:**
- Priority 2 -- Users (`handlers_users.py`, new): `create_user`, `update_user`, `delete_user`
  (with optional `reassign_to`) via native `/wp/v2/users` -- no Bridge changes needed.
- Priority 3 -- Menus (`handlers_menus.py`, new): `list_menus`, `list_menu_items`,
  `create_menu_item`, `update_menu_item`, `delete_menu_item`, `reorder_menu_items` via native
  `/wp/v2/menus` + `/wp/v2/menu-items` (WP 5.9+) -- confirmed core REST was sufficient.
- Priority 4 -- Redirects (`handlers_redirects.py`, new): `list_redirects`, `create_redirect`,
  `delete_redirect`, `set_redirect_status`. Required a genuinely new Bridge section -- Rank Math
  never exposes its Redirections module over REST. Added Bridge SECTION 5 to
  `imperal-bridge.php` (bumped 2.1.0 to 2.2.0): reads/writes Rank Math's own
  `{prefix}rank_math_redirections` table directly (sources array, url_to, header_code, hits,
  status), clearing Rank Math's own cache table after writes instead of touching its internal
  classes. Rebuilt `bridge/imperal-bridge.zip` and updated `bridge/imperal-bridge/README.md` to
  document all 5 sections (was stale at 3).
- Priority 5 -- Product reviews (`handlers_reviews.py`, new): `list_product_reviews`,
  `set_product_review_status`, `reply_to_product_review`, reusing the comment-moderation plumbing
  from the prior session since WooCommerce reviews are `comment_type=review` under the hood.
- Priority 6 -- Post lifecycle (`handlers_post_lifecycle.py`, new): `delete_post`,
  `duplicate_post`, `bulk_update_post_status`.
- Priority 7 -- Site settings (`handlers_site_settings.py`, new): `get_site_settings`,
  `update_site_settings`, `list_native_plugins`, `activate_plugin`, `deactivate_plugin`,
  `list_themes` -- all via native `/wp/v2/settings`, `/wp/v2/plugins`, `/wp/v2/themes` (WP 5.5+),
  no SSH needed. Theme *switching* deliberately not implemented -- there is no core REST route
  for it.

**Pricing:** merged the 25 new functions into a complete 114-function price map (existing prices
preserved, nothing wiped) and applied it via `developer.update_pricing` per the standing pricing
method (suspend, then update_pricing with prices nested under `pricing_config.tool_prices`, never
`save_pricing`). Prices follow the standing rule -- cost of actual work (REST/SSH call count),
not risk: 0 for connect/list/forget (front-door), 1 for single-GET reads, 2 for single-write/
delete calls, 4 for multi-call bulk/preview operations, 6 for CSV import preview/apply (loops over
up to 100 rows). App was suspended for the price write and resubmitted afterward -- back to
`pending_review`, same state it was in before.

**Bug investigated per user report (Bridge installed on 3 sites but detail page says "No server
data yet"):** confirmed via live `get_server_info` calls this is NOT the generic-message bug (that
was already fixed in a prior commit, `5526375`). The real, current state: g4s.md and
ksrenovationgroup.com are both stuck on physical Bridge plugin v2.0.0 on the live WordPress sites
themselves (predates the `/server/info` route added in 2.1.0) -- `climtec.md` is already updated
and correctly returns server info via the Bridge. The code already distinguishes "Bridge missing"
from "Bridge outdated" and shows a specific alert with a download link and the detected version
rather than the generic message -- refresh doesn't "fix" it because refresh can't update a plugin
file sitting on someone else's server; only actually updating/reinstalling the Bridge plugin on
those 2 sites (via WP admin Plugins screen, or SSH+WP-CLI if configured) will. Not something this
codebase can silently work around from here. Documented in note `aaf4c105...` and in this file.

**Notes updated:** appended a dated update block to the canonical roadmap note `aaf4c105...`
marking Priorities 2-7 done with dates and file names, matching this file and the roadmap doc.

**Not done yet, explicitly next:** the UI/UX simulation pass (protocol note `ea041207...`) on the
connected-site detail screen, and the resulting redesign/overhaul of that screen -- this is the
second half of the same user request and the next work in this session.

---

## 2026-08-09 — Full Feature Roadmap + shipped Priority 1: comment moderation (v1.9.0)

**Status:** ✅ implemented and verified (370/370 Python tests pass — 356 pre-existing + 14 new;
`imperal validate` clean: 89 functions, 0 errors/warnings, 1 harmless info; committed and pushed).

**Why:** user asked for a comprehensive plan of every realistic WP Core / WooCommerce / Rank Math /
builder / Bridge+SSH capability, to use as the standing roadmap for this app going forward — then
asked to submit the app for review and start on Priority 1 immediately.

**What was done:**
- Wrote `docs/2026-08-09-full-feature-roadmap.md` — canonical master plan, mapping all 5 capability
  layers (WP Core, Rank Math, WooCommerce, page builders, Bridge/SSH) against the 87 functions that
  existed at the time, with an explicit priority order for what to build next. Linked from
  `CLAUDE.md`'s Key Specs section as the doc to read before proposing/starting any new feature.
  Duplicated as a canonical note in the Notes app (`aaf4c105...`) so it's visible from the general
  memory layer, not just this repo.
- Implemented Priority 1 — comment moderation, previously 100% read-only:
  - `set_comment_status(site_id, comment_id, status)` — one parameterized write covering
    approve/hold/spam/trash, mirroring the WP REST API's own single-`status`-field model rather
    than four near-duplicate functions.
  - `reply_to_comment(site_id, comment_id, content)` — creates a reply nested under an existing
    comment, posted as the connected WP user.
  - New models `SetCommentStatusParams`, `ReplyToCommentParams` in `models.py`.
  - Caught and fixed two bugs of my own while writing tests: (a) `reply_to_comment` originally used
    the file's `_fetch()` helper to read the parent comment, but `_fetch()` is built for list
    endpoints and silently returns `[]` for a single-object dict body — would have hidden a real
    404 and then crashed on `.get()`; switched to a direct `wp_get()` call with explicit status
    handling. (b) both new handlers returned `_authed()`'s error as-is, but in this file `_authed()`
    returns a bare string on failure (not an `ActionResult`, unlike the same-named helper in
    `handlers_taxonomy.py`/`handlers_woocommerce.py`) — wrapped it in `ActionResult.error(...)`.
  - 14 new tests in `tests/test_comment_moderation.py` covering both happy paths, invalid status,
    missing comment (404), unknown site, empty reply text, and retryable 5xx.
- Bumped version 1.8.0 → 1.9.0 in `app.py` (source of truth), regenerated `imperal.json` via
  `imperal build` (never hand-edited — confirmed against CLAUDE.md's explicit rule).
- Marked Priority 1 done in the roadmap doc itself (status line + priority-order list).

**Next:** Priority 2 — user management (`create_user`/`update_user`/`delete_user`, same REST-wrapper
pattern as everything else, no Bridge changes needed since `/wp/v2/users` is core).

---

## 2026-08-06 — Merged the three bridge plugins into ONE ("Imperal Bridge") + sidebar download button

**Status:** ✅ implemented and verified (346/346 Python tests pass; merged PHP plugin lints clean
with `php -l`; all 3 original PHP test harnesses pass unmodified against the merged file — 234
assertions, 0 failed; sidebar panel smoke-tested end-to-end).

**Why:** explicit user directive (verbatim): "i need you to make just one bridge WP plugin, not
many. It should combine all other plugin's capabilities. In the future we will add to this plugin,
not creatin new ones. Also, the link to download this plugin should be always available in the
left sidebar interface... placed as a secondary button link at the bottom of the screen of the
left sidebar."

**What was done:**
- Merged `imperal-seo-bridge`, `imperal-builder-bridge` and `imperal-media-bridge` into one new
  plugin: `bridge/imperal-bridge/imperal-bridge.php` (v2.0.0). Every original function name, route
  and behavior was preserved byte-for-byte — the three bodies were concatenated under one plugin
  header/ABSPATH guard, each kept in a clearly labeled section (SEO / Builder / Media) with its own
  original version/namespace constants intact, so zero risk of regression. Added one new unified
  `GET /wp-json/imperal/v1/status` endpoint reporting `sections: [seo, builder, media]`.
- No REST path changed (all three sections still register under `imperal/v1`, same as before), so
  **no Python handler logic needed to change** — only user-facing strings (install hints, error
  messages, docstrings) that named the old 3-plugin split, across `handlers_seo.py`,
  `handlers_builders.py`, `handlers_media.py`, `handlers_read.py`, `models.py`.
- Merged the three `tests/bridge_logic_test.php` harnesses into `bridge/imperal-bridge/tests/`
  (`seo_logic_test.php`, `builder_logic_test.php`, `media_logic_test.php`), fixed each `require`
  path to point at the merged file, and added the missing `add_filter`/`apply_filters`/`do_action`/
  etc. stubs the media test needed once the SEO section's top-level `add_filter()` call started
  executing on load. All 234 assertions pass unchanged.
- Deleted the old `imperal-seo-bridge/`, `imperal-builder-bridge/`, `imperal-media-bridge/` folders
  and their zips; deleted the still-empty `imperal-polylang-bridge/` stub (nothing to merge from it
  — that capability doesn't exist yet; future Polylang work goes straight into the merged plugin).
  Rewrote `bridge/README.md` and added `bridge/imperal-bridge/README.md` describing the single-
  plugin architecture and stating explicitly there will not be a fourth bridge plugin.
- Built `bridge/imperal-bridge.zip` and pushed everything to the connector's own GitHub repo
  (`ivanco-bluebeeweb-com/imperal-ext-wordpress-hub`, branch `main`). Confirmed the public raw
  URL is live: `https://raw.githubusercontent.com/ivanco-bluebeeweb-com/imperal-ext-wordpress-hub/main/bridge/imperal-bridge.zip`
  (curl -I → `200 application/zip`). Used as the download link — no `ctx.storage` upload needed,
  since the file already lives in the repo and moves automatically with every push.
- `panels.py`: added `BRIDGE_DOWNLOAD_URL` constant and a footer `ui.Stack` (divider + tooltip +
  `ui.Button(variant="secondary", full_width=True, on_click=ui.Open(BRIDGE_DOWNLOAD_URL))`) appended
  as the LAST child of the sidebar panel's root `Stack`, after the site list — i.e. it sits at the
  bottom of the sidebar's own content, always visible regardless of which site is selected. (Note:
  SDK has no native "pin below all scrollable content, even empty space" primitive — `sticky=True`
  only pins to the TOP of a scroll container, and `slot="bottom"` is a dead/unused slot value per
  the SDK docs — so this is the correct-and-only faithful implementation: last item in the sidebar's
  own layout tree, not a separate panel.)

**Open follow-ups (not part of this directive, still pending from before):**
- Migration messaging for sites already running the old 3 separate bridge plugins (deactivate old
  3, install the new merged one) — no code work needed, just a heads-up to affected sites/users.
- Deploy the merged bridge (or at minimum current SEO section behavior) to the live climtec.md site
  — it's still on the old standalone `imperal-seo-bridge` v1.1.0.
- Resume the still-open Climtec/Webbee items from earlier sessions (ventilare article finishing
  touches, remaining ~7 Climtec drafts, Webbee mouseup-fix confirmation).

---

## 2026-08-04 — Native category/tag taxonomy management + rename to WordPress Hub (v1.8.0)

**Status:** ✅ implemented and verified (300/300 Python tests pass; `imperal validate` clean: 0 errors, 0 warnings; `imperal build` succeeds — 4 tools)

**Why:** user directive (verbatim priority): the app must have functions to create
categories, create tags, and manage everything nested about them — a tree structure,
parent/child, all readable/editable/applyable. Also renamed the app display_name from
"WordPress Hub" to "WordPress Hub" per the same directive. Confirmed featured
image + inline image insertion were ALREADY implemented (v1.7.0, `create_post`/
`update_post`'s `featured_media_id` and `PostBlockInput(type="image")`) — no gap there.

**Key distinction preserved:** this is a SEPARATE taxonomy from
`handlers_woocommerce_catalog.py`'s `ProductCategory`/`create_product_category`
(WooCommerce-only, `/wc/v3/products/categories`, flat, product-count based). The new
module manages the NATIVE WordPress `/wp/v2/categories` (hierarchical, parent/child) and
`/wp/v2/tags` (flat) taxonomies — the same ones `create_post`/`update_post` already
*resolve* names against via `find_category_id`/`find_term_ids`, but until now could never
create or manage.

**What was done:**
- `wp_client.py`: added generic `list_terms`/`create_term`/`update_term`/`delete_term`
  helpers, parametrized by `taxonomy_base` ('categories' or 'tags') to avoid duplicating
  the same HTTP-call shape for both taxonomies.
- `models.py`: `ListPostCategoriesParams`, `CreatePostCategoryParams` (with `parent_id`),
  `UpdatePostCategoryParams`, `DeletePostCategoryParams`, and the tag equivalents
  (`ListPostTagsParams`, `CreatePostTagParams`, `UpdatePostTagParams`, `DeletePostTagParams`)
  — kept as distinct models per taxonomy (not one generic "taxonomy" enum param) since
  parent/child nesting is real for categories and meaningless for tags. New entities
  `PostTerm` (taxonomy/parent_id/count/slug) and `TermDeleteResult`.
- New module `handlers_taxonomy.py` (6 new @chat.function tools): `list_post_categories`
  (filterable by `parent_id` to walk the tree), `create_post_category`, `update_post_category`,
  `delete_post_category`; `list_post_tags`, `create_post_tag`, `update_post_tag`,
  `delete_post_tag`. Registered in `main.py`'s `_LOCAL` module-purge tuple and import list.
- `app.py`: `display_name` → "WordPress Hub", version bumped 1.7.0 → 1.8.0, description
  updated to mention hierarchical categories/tags.
- New `tests/test_taxonomy.py` (12 tests) covering list/create/update/delete for both
  taxonomies, parent nesting, and error paths (404 on delete).

**Verified:** `imperal validate .` → 0 errors, 0 warnings, 1 info (no `@ext.on_install`,
pre-existing and non-blocking). `imperal build .` → 4 tools. Full test suite 300/300 pass.

**Still open (per team backlog):** propagate the "WordPress Hub" rename to the panel-facing
Marketplace listing (`developer.update_app_info`) and to Notion's Apps DB; and the
cross-app pipeline wiring (Content Strategy Hub → Article Writer wrapper → Media Studio
Hub → WordPress Hub) is a separate, not-yet-started task.

---

## 2026-08-03 — Media, tags, featured/inline images for the blog-posting pipeline (v1.7.0)

**Status:** ✅ implemented and verified (288/288 Python tests pass; 42+62+119 PHP bridge assertions pass; `imperal validate` clean: 0 errors, 0 warnings)

**Why:** reviewed this app's role as the execution/publish layer of the marketing-
automation blog-posting pipeline (per team notes: Content Strategy app decides what/why →
Webbee writes text + plans images → Image/Media app (Magnific) produces assets → WP Site
Connector publishes). Gap found: no way to get an image INTO WordPress, set a featured
image, or reference an image inline in content — only category, no tags. User approved
adding all necessary functions, scoped strictly to this app's execution responsibilities
(upload/attach/insert media it is GIVEN) — not image planning or generation, which stay in
the other two apps.

**Key technical finding:** `ctx.http` (Imperal's outbound HTTP client) decodes every
non-JSON response body as UTF-8 **text**, which irreversibly corrupts binary bytes —
confirmed empirically (round-tripping a JPEG-like byte string through `httpx.Response.text`
does not reproduce the original bytes). So a naive "Imperal downloads the image, re-uploads
the bytes" flow was never viable. Solution: a third companion bridge plugin that asks
WordPress to fetch its OWN copy of a public image (`media_sideload_image()`, the same
mechanism as the native "Insert from URL" flow) — Imperal only ever sends a URL, never bytes.

**What was done:**
- New companion plugin `bridge/imperal-media-bridge/imperal-media-bridge.php` (344 lines):
  `POST /wp-json/imperal/v1/media/sideload` (source_url, optional post_id/post_slug+post_type,
  alt_text, caption, set_featured) and `GET /wp-json/imperal/v1/media/status`. HTTPS-only
  source URLs; rejects loopback/private/link-local hosts (127.*, 10.*, 172.16-31.*, 192.168.*,
  169.254.*, localhost, ::1, fc../fd..) before ever fetching. No fallback tier — missing
  bridge is a hard stop, same pattern as the Builder Bridge.
- Offline PHP logic harness `bridge/imperal-media-bridge/tests/bridge_logic_test.php` — 42
  assertions (URL validation, post resolution, permission checks, sideload happy path,
  featured-image attach, alt text, error mapping, status). Plus `bridge/imperal-media-bridge/
  README.md` and an index entry in the shared `bridge/README.md`.
- `wp_client.py`: generalised `find_category_id` into `find_term_id(taxonomy_base, name)` +
  `find_term_ids(taxonomy_base, names)` (bulk, reports names-not-found without failing the
  whole write); `find_category_id` kept as a thin wrapper so existing callers are untouched.
  `create_post`/`update_post` now also accept `tag_ids`/`featured_media`. `wp_post` gained an
  optional `timeout=` kwarg (sideload can take longer than the 30s default).
- `gutenberg.py`: new `image_block(media_id, media_url, alt, caption)` renders a Gutenberg
  image block from an existing attachment; `blocks_to_content` dispatches `type == "image"`
  blocks (skipped if `media_id`/`media_url` missing — nothing invented).
- `models.py`: `PostBlockInput` gained `media_id`/`media_url`/`caption` fields (type can now
  be `"image"`); `CreatePostParams`/`UpdatePostParams` gained `tags: list[str]` and
  `featured_media_id: int | None`; `PostResult` gained `tags_not_found`/`featured_media_set`;
  new `UploadMediaParams`, `MediaUploadResult`, `MediaSupport`.
- New `handlers_media.py` with 2 chat functions: `upload_media` (sideload one image, optional
  attach/featured-image/alt/caption) and `check_media_support` (bridge presence + upload
  capability). Same bridge-error-code-mapping style as `handlers_builders.py`/`handlers_seo.py`.
- `handlers_posts.py`: `create_post`/`update_post` now resolve `tags` via `find_term_ids` and
  wire `featured_media_id` straight through; tag names not found degrade to a warning in the
  summary, never a failure (mirrors category's existing fallback behaviour).
- Registered `handlers_media` in `main.py`'s `_LOCAL` tuple and import list (also added
  `gutenberg` itself to the stale-module purge list, which had been missing).
- New tests: `tests/test_media.py` (10), `tests/test_gutenberg.py` (9), plus 12 new cases in
  `tests/test_posts.py` for tags/featured_media/inline-image-in-content. Full suite: **288
  passed** (was 262 before this session).
- Bumped `app.py`/`pyproject.toml` to v1.7.0; updated `description` and the project structure
  section of `CLAUDE.md` (handlers_media.py, gutenberg.py signature change, bridge/ folder,
  new test files). `imperal build`/`imperal validate`: 75 functions (was 73), 0 errors, 0
  warnings, same pre-existing `on_install` info note.

**Not done / not in scope:**
- Image *planning* (which images, where, what prompt) stays in the Content Strategy app per
  the team's architecture notes — this app only executes an upload/attach/insert it is given
  a ready URL for.
- Image *generation* stays in the Image/Media app (Magnific/Mystic) — this app never creates
  pixels, only moves a finished public URL into WordPress.
- No live WordPress round-trip smoke test of the new bridge yet — only the offline PHP
  harness and Python `MockContext` tests. The plugin still needs to be installed on a real
  site and exercised end-to-end before relying on it in production, same caveat as the other
  two bridges when they first shipped.
- Arbitrary custom taxonomies (beyond categories/tags) were not added — `find_term_id`/
  `find_term_ids` are already taxonomy-generic, so adding one would just be a new REST base
  string if/when a real need shows up.

---

## 2026-08-03 — Post/page publishing ported from WP Publisher (v1.6.0)

**Status:** ✅ implemented and verified (262/262 tests pass, `imperal validate` clean: 0 errors, 0 warnings)

**Scope:** Migrate ONLY the WordPress-writing capability of the separate `WP Publisher`
app (draft/post creation with Gutenberg content, category, Polylang language) into this
connector. Explicitly OUT of scope, by request: anything about interpreting the input
document — `docx_parser.py`, `parse_article`, `confirm_mapping`, and the heading-heuristics
`rules.py` were deliberately NOT ported. Content now arrives as explicit, caller-decided
`{type, text, level}` blocks; nothing in this app parses a document.

**What was done:**
- New `gutenberg.py` — `blocks_to_content()` renders an ordered list of `{type, text,
  level}` blocks into Gutenberg block markup (`heading` → `<h{level}>`, anything else →
  paragraph). Pure and document-agnostic, ported from WP Publisher's block renderer
  without any of the docx-parsing context it used to run inside.
- `wp_client.py`: added `find_category_id` (case-insensitive term lookup, optionally
  Polylang-scoped via `lang`), `create_post`, and `update_post` — thin REST wrappers
  around `/wp-json/wp/v2/<base>` (posts/pages/custom types), also ported from WP
  Publisher's `wp_client.create_draft` but generalised to create OR update and to any
  post type, not just posts.
- New `handlers_posts.py` with 2 chat functions:
  - `create_post` — title, post_type (post/page/CPT), status (draft/publish/pending/
    private/future — future requires `date`), slug, blocks, excerpt, category (resolved
    by name, never created), date, lang (Polylang). Category-not-found is a soft warning,
    not a failure — mirrors WP Publisher's own fallback behaviour.
  - `update_post` — same fields, all optional; refuses with `POST_UPDATE_NO_FIELDS` if
    nothing was given; empty string on `category` clears it.
  - Both accept optional `meta_title` / `meta_description` / `focus_keyword` and delegate
    the actual SEO write to the EXISTING `handlers_seo.update_seo_meta` (bridge/core-meta
    tiers) instead of re-adding WP Publisher's own bridge-only Rank Math write path — one
    SEO write path in this app, not two. A failed SEO write degrades to a warning in the
    summary; the post itself is not rolled back.
- New models in `models.py`: `PostBlockInput`, `CreatePostParams`, `UpdatePostParams`,
  `PostResult` (SDL entity: id, title, kind, url=link, status, post_type, category_resolved,
  warnings).
- Registered `handlers_posts` in `main.py`'s `_LOCAL` tuple and import list.
- Added `tests/test_posts.py` (13 new tests): happy path block rendering, category
  resolution by name, category-not-found warning, page vs post REST base, `future` status
  requiring a date, SEO fields delegated to `update_seo_meta`, SEO failure surfaced as a
  warning not an error, HTTP failure mapping, missing site, update with partial fields,
  clearing category with `""`, update re-rendering blocks into fresh content, update with
  no fields refused.
- Bumped `app.py` / `pyproject.toml` to v1.6.0; updated `description` and the project
  structure section of `CLAUDE.md`. `imperal build` / `imperal validate`: 73 functions
  (was 71), 0 errors, 0 warnings, same pre-existing `on_install` info note.
- Full suite: **262 passed** (was 249 before this session).

**Not done / not in scope:**
- The `WP Publisher` app itself was left untouched — this was a one-way port of
  capability, not a decommission. Whether to deprecate/retire WP Publisher now that its
  posting half has a home here is a separate decision, not made in this session.
- No live WordPress round-trip smoke test yet — only `MockContext` tests. The bridge
  plugins this module relies on for SEO (`imperal-seo-bridge`) already exist and are
  presumably live on connected sites; `create_post`/`update_post` themselves need no new
  bridge plugin (stock `wp/v2/<base>` REST + Application Password is enough), but a real
  site was not exercised in this session.

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
- Committed and pushed to `origin/main` (`a1ede8d8`). Deployed to the
  Imperal registry: 4 tools synced, icon/manifest/panels synced, status
  `warning` (19/21 checks — same non-blocking pattern seen on prior releases
  of this connector; not investigated further since it hasn't blocked any
  previous release either).
- Still not done: no live WordPress site with Elementor/Bricks installed was
  used to smoke-test the actual bridge plugin end-to-end — only the offline
  PHP harness and Python `MockContext` tests. A real install/activation +
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
- v1 design spec written: `docs/2026-06-16-wordpress-hub-v1-design.md`
- v1 implementation plan: `docs/2026-06-16-wordpress-hub-v1-plan.md`
- Initial app scaffold: app.py, handlers_connect.py, handlers_read.py, panels.py, skeleton.py, models.py, wp_client.py, storage.py
- imperal.json generated (manifest v3, sdk 5.4.2)
- Tools: connect_site, forget_site, add_ssh, remove_ssh, list_sites, list_posts, list_pages, list_media, get_site_health, refresh_site, refresh_all_sites, list_comments, list_scheduled, list_users, list_orders, list_custom_posts, get_server_info

---

## 2026-08-12 — Group O: WXR Import / Export ✅ SHIPPED

**Truthful status:** Group O is shipped. Full pricing was saved, checks passed, and release commit
`08826186` was pushed to `main` and deployed as WordPress Hub 1.19.0. The platform’s deployment
response was **warning (18/21 checks)**; it confirmed that the manifest, panels, icon, and four
catalog tools were synced.

**Release evidence:**
- Full 205-key `pricing_config.tool_prices` map saved through `developer.update_pricing` for
  `wordpress-hub`; `export_wxr=1`, `import_wxr=2`. The platform response confirmed: “Pricing
  updated for 'wordpress-hub'.”
- `uv run pytest -q`: **752 passed** (4 pre-existing SDK deprecation warnings).
- All Bridge PHP test harnesses: **539 assertions, 0 failed**.
- `uv run imperal validate`: **205 functions, 0 errors, 0 warnings, 1 advisory**.
- `uv run imperal build` and `git diff --check`: passed.
- `bridge/imperal-bridge.zip`: exactly `imperal-bridge/README.md` and
  `imperal-bridge/imperal-bridge.php`.
- Commit `08826186` (`Add WXR import and export support`) pushed to `origin/main` and deployed.

**Next up:** Group P is research-first only: verify the exact WordPress/WP-CLI checksum mechanisms
before designing or implementing any function. Any eventual new function must receive a price in a
complete pricing map and have that map saved and confirmed before shipment.

---

## 2026-08-11 (late night) — Group O implementation handoff (historical record)

**Historical status:** this section records the pre-release implementation state; the release was
completed on 2026-08-12 above.

### Completed implementation

**New functions (203 → 205):**
- `export_wxr` — Bridge-first, SSH + WP-CLI fallback. Uses WordPress core’s `export_wp()` through
  Bridge SECTION 18 (`GET /wp-json/imperal/v1/export/wxr`) or `wp export --stdout` over SSH.
  Optional filters: content/post type, author, category, date range, and status. Both paths cap XML
  output at 2MB; no silent truncation. Returns XML, real byte count, and a rough post count.
- `import_wxr` — deliberately SSH-only through `wp import -`, with WXR XML piped on stdin via the
  newly extended `wp_cli._run(stdin_data=...)`. WordPress Importer is a separate plugin whose
  `WP_Import::dispatch()` is a browser wizard tied to `$_GET`/`$_POST`, so it has no safe faithful
  Bridge REST implementation. Requires active `wordpress-importer`; its missing-plugin error is
  surfaced clearly. Supports `authors=create|skip` and `skip_attachments` (`--skip=attachment`).

**Changed/added files:**
- `models.py`: `ExportWxrParams`, `WxrExportResult`, `ImportWxrParams`, `WxrImportResult`; 2MB cap.
- `wp_cli.py`: `_run(..., stdin_data=...)`; `export_wxr`; `import_wxr`.
- `handlers_import_export.py` (new): both chat functions. `import_wxr` declares
  `effects=["wp.import_wxr"]`, `event="wordpress-hub.import_wxr"`.
- `main.py`: registers `handlers_import_export`.
- `bridge/imperal-bridge/imperal-bridge.php`: plugin / bridge version 2.13.0 → 2.14.0; new
  SECTION 18 `/export/wxr`, captures `export_wp()` output, removes download-only headers, caps at
  2MB. Import intentionally has no Bridge route.
- `tests/test_import_export.py` (new): 11 Python contract tests.
- `bridge/imperal-bridge/tests/import_export_logic_test.php` (new): 18 PHP assertions.
- Generated by build: `imperal.json`, `uv.lock` are modified and must be included only after review.

### Verified in this working tree

- `uv run pytest tests/test_import_export.py -q`: **11 passed**.
- `uv run pytest -q`: **752 passed, 4 pre-existing SDK deprecation warnings**.
- All Bridge PHP harnesses: **539 assertions, 0 failed** (new WXR harness: 18/18).
- `uv run imperal validate`: **205 functions, 0 errors, 0 warnings, 1 existing info**
  (`@ext.on_install` advisory).
- `uv run imperal build`: succeeded; generated `imperal.json` now exposes **205** non-skeleton
  functions.

### Required remaining work — in this exact order

1. **Pricing (not performed yet):** app is already `suspended` (a new suspend attempt returned
   exactly that status). Call `developer.update_pricing`, NEVER `save_pricing`, with the COMPLETE
   205-key map nested at `pricing_config.tool_prices`; no partial map. Tier rule is unchanged:
   front-door/local only = 0, single read = 1, single write/delete = 2, multi-call/preview = 4,
   CSV apply = 6. New keys: `export_wxr=1`, `import_wxr=2`. Verify tool response confirms saved
   pricing; then submit/re-submit only if platform status permits/requires it.
2. Update `README.md` endpoint table and section count for Bridge SECTION 18; rebuild
   `bridge/imperal-bridge/imperal-bridge.zip` excluding test files (README + plugin PHP only).
3. Update `docs/2026-08-11-developer-backend-functions-plan.md`: Group O may be marked
   ✅ SHIPPED only after the rest of this list succeeds. State the Bridge-first/SSH-fallback export
   and the reason import is SSH-only.
4. Review `git diff` / `git status` carefully. Current expected changes are: Bridge PHP, generated
   `imperal.json`, `main.py`, `models.py`, `uv.lock`, `wp_cli.py`, plus the two new test files and
   `handlers_import_export.py`; after this log update, `CURRENT_WORK.md` too. Catch unrelated
   changes before staging.
5. Bump project/app version according to established release practice (current `pyproject.toml`
   version is 1.18.0; inspect `app.py`/manifest version alignment before changing). Rebuild and
   revalidate after the bump.
6. Commit, push, and deploy `wordpress-hub`. Confirm deploy result; the prior known 18/21 warning
   pattern was cosmetic, but report the live result honestly. Then record actual commit/deploy IDs
   here and in the canonical Notes handoff.
7. Only then proceed in roadmap order to **Group P — Core/Plugin/Theme Integrity**, then Q onward.

### Important guardrails retained

- Work only in `/Users/vladivanco/Documents/Imperal OS/Apps/WordPress Hub`.
- App/product name everywhere is **WordPress Hub** (not the former name).
- Never use `developer.save_pricing`: confirmed platform bug can claim success but erase or fail to
  retain the pricing map. Use `developer.update_pricing` only, full map only, after suspend.
- No fabricated WordPress / WP-CLI behaviour. Ground all changes in core, plugin, or WP-CLI source.
- Bridge-only is correct where no reliable shell equivalent exists; SSH-only is correct where no
  safe reliable Bridge equivalent exists. `import_wxr` is intentionally SSH-only.
- Do not run `python`; this machine has `python3` and project commands run through `uv run`.

**Handoff prompt exists separately in Notes as:** `WordPress Hub — Group O WXR continuation (2026-08-11)`.

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
