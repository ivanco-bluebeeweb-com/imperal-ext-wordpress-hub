# WordPress Hub — Developer / Backend-Developer Function Roadmap

Status: **canonical / living document — companion to `2026-08-09-full-feature-roadmap.md`.**
Date: 2026-08-11.

## Purpose

The existing roadmap (`2026-08-09-full-feature-roadmap.md`) covers the **content-editor /
site-manager / store-manager** persona: posts, SEO, WooCommerce, comments, menus. It is now at 139
functions and every layer it tracks is fully covered.

This document covers a **different persona**: the developer or backend developer maintaining the
WordPress installation itself — someone who cares about database health, server environment, cron
jobs, transients/object cache, custom fields/meta, REST API surface, security posture, logs,
staging/deploy hygiene, multisite, and WP-CLI-level operations. None of that is "content
management" — it's infrastructure and code-level operations on the WordPress install, which is
exactly the layer Imperal Cloud (and this app specifically, as the one app in the workspace with a
real Bridge plugin + SSH access) is positioned to own.

Per the standing rule for this app: **nothing here gets built speculatively.** Every function below
must be verified against a real, callable mechanism (native WP REST route, WP-CLI command, or a new
Imperal Bridge section reading/writing a real, confirmed data source) before a line of code is
written. This doc is the candidate list + grouping; each slice still needs its own
source-verification pass exactly like every prior slice in the main roadmap.

Baseline: 139 functions today (`wordpress-hub` v1.17.0). Candidate list below is organized into 21
groups (A-U), 85 numbered items, **87 distinct new function names** (verified by diffing every
backtick-quoted identifier in this doc against the current shipped function list in `imperal.json`
and manually excluding non-function noise: DB table/column names, WP option keys, and one
cross-app tool name (`domain_full_check`) mentioned only as an explicit exclusion). Not everything
here will ship — case-by-case verification first, same discipline as always.

**Count correction (2026-08-11):** an earlier claim of "~117 candidate functions" for this doc was
wrong — that number was a raw count of every unique backtick-quoted token in the file, which
included 14 already-shipped function names mentioned for context/comparison and several non-function
tokens (table names, option keys, a foreign app's tool name). The real count of new candidate
function names is 87, confirmed by set-diffing against `imperal.json`'s actual tool list.

---

## Group A — Custom Fields / Post Meta (generic, not just SEO) — ✅ SHIPPED 2026-08-11

WordPress core exposes `meta` as a registered-field passthrough on `/wp/v2/<type>/<id>` but only for
meta keys explicitly registered with `register_post_meta(..., show_in_rest => true)` — most
real-world custom fields (ACF, raw `update_post_meta`, plugin-added meta) are NOT visible this way.
This is one of the single most common backend-dev asks ("read/write this custom field on this
post") and today we have zero generic answer for it beyond SEO-specific meta.

1. `get_post_meta` — read ALL post meta for a post/page/CPT item (needs Bridge: core REST hides
   unregistered meta keys entirely)
2. `update_post_meta` — set one or more arbitrary meta keys/values on a post (Bridge)
3. `delete_post_meta` — remove one meta key from a post (Bridge)
4. `get_user_meta` / `update_user_meta` / `delete_user_meta` — same, for users (Bridge)
5. `get_term_meta` / `update_term_meta` / `delete_term_meta` — same, for taxonomy terms (Bridge)
6. `get_option` / `update_option` — read/write an arbitrary named row in `wp_options` (Bridge;
   extremely powerful, needs a hard allowlist/denylist — never allow writing `siteurl`, `home`,
   `active_plugins`, `template`/`stylesheet` blind, no arbitrary serialized-PHP payloads)
7. `list_acf_fields` — if Advanced Custom Fields is active, list registered field groups/fields for
   a post type (Bridge, ACF's own `get_field_objects()`) — verify ACF presence before ever
   attempting this, must degrade cleanly when ACF isn't installed

## Group B — Database Tools — ✅ SHIPPED 2026-08-11

8. `get_database_size` — already covered by `get_server_info`, no new function needed (noted in
   main roadmap 5.2)
9. `list_database_tables` — ✅ table names + size on disk, WP-CLI `wp db size --tables --format=json`
10. `run_db_search_replace` / `apply_db_search_replace` — ✅ the single most common WP migration task
    (domain change, staging→prod URL swap) — WP-CLI `wp search-replace`, ALWAYS dry-run-first
    (`run_db_search_replace` reports the replacement count), `apply_db_search_replace` re-verifies
    with a fresh dry-run immediately before writing and refuses if the count drifted from what the
    caller confirmed (anti-stale-preview guard, same pattern as `apply_order_line_changes`).
    Search/replace strings are rejected if they contain quotes/backticks/newlines; table names are
    restricted to alnum/`-_.*` only — no shell injection surface.
11. `optimize_database_tables` — ✅ WP-CLI `wp db optimize` (defragment tables)
12. `check_database_repair` — ✅ WP-CLI `wp db check` (always) + `wp db repair` (when `repair=true`)
13. `export_database_dump` — ✅ WP-CLI `wp db export`, returned inline as text, hard-capped at ~2MB;
    over the cap the caller is told to scope down with `tables=` from `list_database_tables`
    (no file-write/attachment mechanism exists in this app, so streaming to a signed URL was not
    attempted — inline-with-a-cap is the honest, verified option)
14. `count_post_type_rows` — ✅ WP-CLI `wp post list --format=count`, post_type validated as a safe
    identifier before hitting the command line
    `count_orphaned_postmeta` — ✅ WP-CLI `wp db query` running a prefix-safe `LEFT JOIN ... IS NULL`
    against the site's own real `$wpdb->prefix` (discovered via `wp eval`, never hardcoded `wp_`)

All 8 functions in `handlers_database.py` (new), models in `models.py`, WP-CLI command builders in
`wp_cli.py`. 15 new tests in `tests/test_database.py` (12 handler-level MockContext tests + 3
`wp_cli`-level shell-injection-guard tests). Full suite 594→609, all green.
`imperal validate`: 0 errors/0 warnings, 169 functions. Repriced the complete 169-key map (adding
these 8 + the previously-unpriced `get_builder_element`) via `update_pricing`, resubmitted —
`pending_review`, all 4 checks passed.

## Group C — Transients & Object Cache — ✅ SHIPPED 2026-08-11

15. `list_transients` — read `wp_options` rows matching `_transient_%`/`_site_transient_%` with
    expiry (Bridge or WP-CLI `wp transient list` if the transient command is available)
16. `delete_transient` — remove one named transient
17. `flush_all_transients` — WP-CLI `wp transient delete --all`
18. `get_object_cache_status` — is a persistent object cache (Redis/Memcached) active, and basic
    stats if so (WP-CLI `wp cache type` / plugin-specific)
19. `flush_object_cache` — WP-CLI `wp cache flush`
20. `purge_cache` — ✅ EXTENDED 2026-08-11: now auto-detects W3 Total Cache in addition to
    LiteSpeed Cache (`wp w3-total-cache flush all`, verified bundled with the plugin itself, same
    safety class as LiteSpeed's own `litespeed-purge`). WP Rocket and WP Super Cache deliberately
    NOT added — their WP-CLI support ships as a separate package
    (wp-media/wp-rocket-cli, wp-cli/wp-super-cache-cli) not guaranteed present on an arbitrary
    server, so calling it could misreport a real absence as success/failure noise.

## Group D — Cron Jobs (beyond the existing single `run_wp_cron`) — ✅ SHIPPED 2026-08-11

21. `list_cron_events` — WP-CLI `wp cron event list`: every scheduled hook, next run time, recurrence
22. `run_cron_event` — trigger ONE named cron hook by name (`wp cron event run <hook>`), more
    precise than the existing "force all due events" `run_wp_cron`
23. `delete_cron_event` — unschedule a specific stuck/duplicate cron event
24. `list_cron_schedules` — the registered recurrence intervals (hourly/daily/custom plugin
    intervals) — useful for diagnosing "why does this only run every 6 hours"

## Group E — REST API Introspection — ✅ SHIPPED 2026-08-11

25. `list_rest_routes` — ✅ enumerates every registered REST route + namespace on the site,
    optional `namespace=` filter — reads the site's own `GET /wp-json/` root index (native
    WordPress core, no Bridge/SSH needed), verified against
    developer.wordpress.org/rest-api/extending-the-rest-api/routes-and-endpoints/
26. `get_rest_route_schema` — ✅ methods + each endpoint's declared args for ONE route, from the
    same root index (`WP_ROUTE_NOT_FOUND` if the exact route string doesn't exist)
27. `list_application_passwords` — ✅ list the currently-registered Application Passwords for the
    connected user (native `/wp/v2/users/me/application-passwords`, WP 5.6+) — NOT the secret
    itself, just uuid/name/created/last_used/last_ip, for auditing "what has access to this site".
    Verified against developer.wordpress.org/rest-api/reference/application-passwords/ and
    make.wordpress.org's Application Passwords integration guide (WP 5.6, Nov 2020).
28. `revoke_application_password` — ✅ revoke one named Application Password by uuid
    (`DELETE /wp/v2/users/me/application-passwords/<uuid>`) — distinct from `forget_site`, which
    only removes Imperal's own stored credential; this changes WordPress itself.

4 functions in `handlers_rest_api.py` (new), models in `models.py`. 9 new tests
(`tests/test_rest_api.py`). Full suite 615→624, all green. `imperal validate`: 0 errors/0
warnings, 173 functions. Repriced the complete 173-key map, resubmitted — `pending_review`, all 4
checks passed.

## Group F — Security / Hardening Diagnostics — ✅ SHIPPED 2026-08-11

29. `get_php_info` — ✅ PHP version, loaded extensions, memory_limit/max_execution_time/
    upload_max_filesize/post_max_size — reads Bridge SECTION 10's `/security/php-info` route
    (plain `phpversion()`/`get_loaded_extensions()`/`ini_get()`, no shell needed). Bridge-only
    (no SSH fallback, consistent with SECTION 7's Bridge-only Rank Math site-wide functions) —
    returns `SECURITY_BRIDGE_MISSING` if Bridge < 2.6.0.
30. `check_file_permissions` — ✅ octal permission bits for wp-config.php and wp-content, the two
    most commonly misconfigured paths (world-readable wp-config.php leaks DB credentials;
    world-writable wp-content allows arbitrary file drops) — Bridge SECTION 10
    `/security/file-permissions`, read-only (`fileperms()`, never `chmod()`s anything).
31. `list_admin_users` — ✅ thin wrapper over WordPress core's own
    `GET /wp/v2/users?roles=administrator` filter — no Bridge/SSH needed at all, confirmed
    against developer.wordpress.org/rest-api/reference/users/ (the `roles` request arg has
    shipped in WordPress core since 4.7).
32. `check_debug_mode` — ✅ WP_DEBUG / WP_DEBUG_LOG / WP_DEBUG_DISPLAY constants — Bridge
    SECTION 10 `/security/debug-mode` (`defined()`/constant reads, no shell). WP_DEBUG_DISPLAY
    correctly defaults to WP_DEBUG's own value when undefined, matching WordPress core's
    `wp-config-sample.php`/`load.php` default behaviour.
33. `get_ssl_status` — intentionally NOT built here — web-tools' `ssl_check` already owns this
    surface; duplicating it here would fork one fact across two apps.
34. `list_failed_login_attempts` — intentionally NOT built here — would require guessing a
    specific security plugin's (Wordfence / Limit Login Attempts Reloaded) internal storage
    shape without a concrete site to verify against, exactly the kind of fabrication this
    roadmap forbids. Revisit only if a real site running one of those plugins can be checked.

4 functions in `handlers_security.py` (new). Bridge plugin bumped to v2.6.0 with new SECTION 10
(3 routes, all gated `manage_options`). 8 new tests (`tests/test_security.py`). Full suite
624→632, all green. `imperal validate`: 0 errors/0 warnings, 177 functions. Repriced the complete
177-key map, resubmitted — `pending_review`, all 4 checks passed. Deployed at `5282eed9`.

## Group G — Multisite (only if real demand — currently unverified whether any connected site is multisite)

35. `list_network_sites` — `wp site list` equivalent, only meaningful on a multisite install
36. `create_network_site` — add a new site to a multisite network
37. `list_network_plugins` — network-activated plugins
38. **Gate — assessed 2026-08-12:** Group G remains deliberately unbuilt. The three connected
    sites (`ksrenovationgroup.com`, `g4s.md`, `climtec.md`) all report no Imperal Bridge 2.7.0+
    deploy-hygiene route, so Multisite cannot be verified without inventing an answer. Revisit only
    after the current Bridge ZIP is installed on a known Multisite site.

## Group H — Deploy / Environment Hygiene — ✅ ALREADY SHIPPED

39–42 are already implemented as `get_wp_config_constants`, `list_must_use_plugins`,
`list_drop_ins`, and `get_environment_type`. No duplicate work is required.

### Tomorrow — genuine site-owner prerequisites

1. Install or update `bridge/imperal-bridge.zip` on each connected production site; the currently
   connected three sites do not expose even Bridge 2.7.0+ routes, so their existing features cannot
   use the newly deployed mail, Site Health, session, or other Bridge capabilities.
2. If Multisite support is desired, connect or identify one confirmed WordPress Multisite network
   after its Bridge update. Only then can Group G be designed and tested against real network data.
3. In Imperal, open the **Developer → WordPress Hub → Deploy** details to inspect the recurring
   `18/21` deployment warning. The API returns the count but not the three underlying checks, so a
   cause would be speculation until those details are visible.

## Group H — Deploy / Environment Hygiene

39. `get_wp_config_constants` — read the SAFE subset of wp-config.php constants (WP_ENV,
    WP_DEBUG, WP_CACHE, table prefix, WP version pin) — never the DB credentials or auth keys/salts
40. `list_must_use_plugins` — mu-plugins are invisible to `list_plugins`/`list_native_plugins`
    (they can't be deactivated, so WP core deliberately excludes them from the plugins list) — a
    real backend-dev blind spot today
41. `list_drop_ins` — WP core drop-in files (`object-cache.php`, `advanced-cache.php`,
    `db.php`) — which caching/DB layer is actually in play
42. `get_environment_type` — WordPress 5.5+'s own `wp_get_environment_type()` (production / staging
    / development / local) if the site declares it

## Group I — Logs — ✅ SHIPPED 2026-08-11 (Bridge-first, SSH-fallback — no shell required)

43. `tail_debug_log` — ✅ last N lines of `wp-content/debug.log` ("why did that last save fail") —
    Bridge SECTION 13 (`GET /imperal/v1/logs/debug-log`) reads it with plain `file_get_contents()`
    from inside WordPress; SSH/WP-CLI `wp eval` is only the fallback for sites without the Bridge.
44. `clear_debug_log` — ✅ truncate (never delete) the debug log file — Bridge
    (`POST .../logs/debug-log/clear`, `fopen(..., 'w')`), SSH fallback otherwise.
45. `tail_php_error_log` — ✅ PHP's own `ini_get('error_log')` path — Bridge
    (`GET .../logs/php-error-log`), SSH fallback otherwise.

3 functions in `handlers_logs.py` (rewritten). 12 tests (`tests/test_logs.py`, 3-way: bridge-only/
ssh-fallback/neither). Bridge zip 2.8.0 → 2.9.0.

## Group J — Custom Post Types & Taxonomies (introspection, not content) — ✅ SHIPPED 2026-08-11

46. `list_registered_post_types` — ✅ every CPT the site has registered (not just the ones we
    already know to query via `list_custom_posts`), with `rest_base`, `hierarchical`, `viewable`,
    `has_archive`, `taxonomies` — native `GET /wp/v2/types`, no Bridge/SSH. `viewable` only exists
    under `context=edit` per WP core's own schema (`class-wp-rest-post-types-controller.php`
    marks it `'context' => array('edit')`) — requested edit-context first, falls back to view-only
    on a 401/403 from a lower-privileged connected user rather than silently defaulting it false.
47. `list_registered_taxonomies` — ✅ same, for taxonomies — native `GET /wp/v2/taxonomies`,
    same edit-context-then-fallback pattern for `visibility.public` (verified against
    `class-wp-rest-taxonomies-controller.php`).

2 functions in `handlers_cpt_taxonomy.py` (new). 7 new tests (`tests/test_cpt_taxonomy.py`). Full
suite 657→667, all green. `imperal validate`: 0 errors/0 warnings, 186 functions. Repriced the
complete 186-key map (1 credit each — single core REST GET), resubmitted — `pending_review`, all 4
checks passed. Deployed at `a0152c0d`.

## Group K — Blocks / Patterns / Templates (block-theme era, read-only diagnostics only)

48. `list_reusable_blocks` — `wp_block` post type listing (Gutenberg reusable blocks / "synced
    patterns") — a real, common editorial-meets-dev question ("which pages use this reusable
    block")
49. `list_block_patterns` — registered block patterns (theme + plugin supplied)
- **Deliberately excluded:** full Site Editor template editing — matches existing Widgets/FSE
  exclusion decision in the main roadmap (1.6), same reasoning.

## Group L — Webhooks / Integrations — ✅ SHIPPED 2026-08-11

50. `list_registered_webhooks` — ✅ WooCommerce's own native `wc/v3/webhooks` route (documented at
    developer.woocommerce.com/docs/apis/rest-api/v3/webhooks/) — list configured webhooks (URL,
    topic, status), optionally filtered by status.
51. `get_webhook` — ✅ read one webhook's full config (native route). `secret` is write-only per
    WooCommerce's own schema — never returned by any GET, and never echoed back by any function
    here either.
52. `create_webhook` — ✅ same native WooCommerce route, write side — lets a backend dev wire this
    site into an external system (order sync, inventory feed, a Slack/Zapier-style relay) without
    touching wp-admin. `delivery_url` is validated https:// before ever making a network call.
53. `update_webhook` — ✅ change topic/URL/status/secret on an existing webhook without touching
    omitted fields — WooCommerce's webhooks endpoint takes POST for partial updates, not PUT.
54. `delete_webhook` — ✅ permanently remove a webhook (`DELETE .../webhooks/{id}?force=true` —
    webhooks have no trash state, same as WooCommerce customers).

5 functions in `handlers_webhooks.py` (new). 12 new tests (`tests/test_webhooks.py`). Full suite
676→688, all green. `imperal validate`: 0 errors/0 warnings, 193 functions. Repriced the complete
193-key map (1 credit for reads, 2 for writes — matches the existing coupon/redirect tier),
resubmitted — `pending_review`, all 4 checks passed.

## Group M — Action Scheduler / Background Job Queue — ✅ SHIPPED 2026-08-11

WooCommerce (and many other plugins) ship Action Scheduler, which stores every scheduled/queued
background job and exposes an actual wp-admin screen (Tools → Scheduled Actions). This is a
first-class backend-dev diagnostic surface for "why didn't my order emails/webhooks/sync jobs run" —
distinct from native WP-Cron (Group D), which only decides *when* Action Scheduler's own runner
next wakes up.

Implemented Bridge-only (SECTION 16, `imperal-bridge.php` 2.11.0→2.12.0) — verified against Action
Scheduler's own real source (`functions.php`, `ActionScheduler_Store`): no reliable SSH/WP-CLI
fallback exists (the `wp action-scheduler` CLI command needs the exact same WooCommerce/library
context loaded as the REST call, so a bare SSH session buys nothing extra — same precedent as
Group K/redirects). Also verified Action Scheduler has NO native retry concept — a failed action
stays failed forever; the real, honest mechanism is `as_enqueue_async_action()` re-enqueuing a
fresh attempt with the same hook/args/group, exactly what `retry_failed_action` does.

55. `list_scheduled_actions` — ✅ pending/in-progress/complete/failed/canceled queue entries,
    filterable by status/hook/group, via `as_get_scheduled_actions()`.
56. `get_scheduled_action` — ✅ full detail (args, group, scheduled date, execution log) for one
    action id, via `ActionScheduler::store()->fetch_action()` + `ActionScheduler::logger()->get_logs()`.
57. `run_scheduled_action` — ✅ force-run one action immediately regardless of schedule, via
    `ActionScheduler::runner()->process_action()` — the exact call the admin list table's "Run" row
    action uses; surfaces the hook callback's own exception if it throws.
58. `cancel_scheduled_action` — ✅ cancel one pending action via `ActionScheduler_Store::cancel_action()`.
59. `retry_failed_action` — ✅ re-enqueue a fresh attempt for one FAILED action via
    `as_enqueue_async_action()` (rejects with 400 if the action isn't in the failed state).
60. `count_actions_by_status` — ✅ one-glance health snapshot via `ActionScheduler_Store::action_counts()`.

6 functions in `handlers_action_scheduler.py` (new). 18 new tests (`tests/test_action_scheduler.py`)
+ 42 new PHP tests (`bridge/imperal-bridge/tests/action_scheduler_logic_test.php`, fake in-memory
ActionScheduler/Store). Full suite 702→720, all green. `imperal validate`: 0 errors/0 warnings, 199
functions. Repriced the complete 199-key map (1 credit for reads, 2 for writes — matches the
existing tier convention), resubmitted — `pending_review`, all 4 checks passed.

## Group N — Rewrite Rules & Permalinks ✅ SHIPPED (2026-08-11)

61. `get_permalink_structure` ✅ — reads `permalink_structure`/`category_base`/`tag_base` from
    wp_options. Verified core's `/wp/v2/settings` has NEVER reliably exposed `permalink_structure`
    across versions (added 4.9 #41014/[42359], removed again over #45017 fallout — plain-permalink
    sites collided with the REST index's own field of the same name) and never exposed
    category/tag base at all — so this is a dedicated new Bridge route (SECTION 17), not a field
    on the existing `get_site_settings`.
62. `update_permalink_structure` ✅ — Bridge: `WP_Rewrite::set_permalink_structure()` (updates the
    option + re-inits `$wp_rewrite`, same call `wp-admin/options-permalink.php`'s "Save Changes"
    makes) followed by an explicit `flush_rewrite_rules()` — core's own method does NOT flush by
    itself. SSH fallback: `wp rewrite structure` with `--category-base`/`--tag-base`.
63. `flush_rewrite_rules` ✅ — Bridge calling `flush_rewrite_rules()` directly; SSH fallback
    `wp rewrite flush`.
64. `list_rewrite_rules` ✅ — Bridge reads the `rewrite_rules` wp_options row (WP_Rewrite's own
    compiled table); SSH fallback `wp rewrite list --format=json`.

New `handlers_rewrite.py`, Bridge SECTION 17 (`imperal-bridge.php` 2.12.0 → 2.13.0), 3 new
`wp_cli.py` functions, 21 new PHP harness assertions (`rewrite_logic_test.php`), 17 new Python
tests (`tests/test_rewrite.py`). Full suite 724→741, all green. `imperal validate`: 0 errors/0
warnings, 203 functions. Repriced the complete 203-key map (1 for the 2 reads, 2 for the 2
writes — matches the existing tier convention), resubmitted.

## Group O — Import / Export (WXR)

**Release gate:** mark this group ✅ SHIPPED only after the complete pricing map is successfully
persisted, all tests pass, and the release commit has been pushed and deployed.

65. `export_wxr` — implemented Bridge-first through SECTION 18's
    `GET /wp-json/imperal/v1/export/wxr`, which runs WordPress core's `export_wp()`; SSH +
    `wp export --stdout` is the fallback. Supports content/post type, author, category, date
    range, and status filters. The returned XML is capped at 2MB with an explicit refusal rather
    than silent truncation.
66. `import_wxr` — implemented deliberately SSH/WP-CLI-only through `wp import -`, with the WXR
    XML passed on stdin. The separate `wordpress-importer` plugin is required and its missing or
    inactive state is reported clearly. Import has no Bridge REST route because WordPress
    Importer's `WP_Import::dispatch()` is a browser wizard, not a safe headless REST API.

**✅ SHIPPED (2026-08-12):** complete 205-key pricing map persisted through
`developer.update_pricing` (`export_wxr=1`, `import_wxr=2`); 752 Python tests and all Bridge PHP
harnesses passed; `imperal validate` reported 205 functions, 0 errors, and 0 warnings; build and
`git diff --check` passed. Released as version 1.19.0 in commit `08826186`, pushed to `main` and
deployed. The platform reported deployment with warnings (`18/21` checks); manifest, panels, icon,
and four catalog tools were synced.

## Group P — Core / Plugin / Theme Integrity (security-relevant)

67. `verify_core_checksums` — WP-CLI `wp core verify-checksums`: detects modified/added core files
    vs. the official WordPress.org checksums — a real, standard malware/tamper detection step
68. `verify_plugin_checksums` — WP-CLI `wp plugin verify-checksums`: same, for plugins hosted on
    wordpress.org (naturally skips premium/custom plugins not in that repo — must report that
    honestly, not as a false pass or fail)
69. `check_core_update_available` / `list_plugin_updates_available` / `list_theme_updates_available`
    — **already covered, without duplicate tools**, by `get_server_info`: its Bridge-first and
    SSH/WP-CLI fallback response contains the read-only core/plugin/theme update lists alongside
    the installed WordPress version. The existing `update_plugin`/`update_core` remain separate
    write operations.
70. `get_wp_version_support_status` — is the connected site's WP version still receiving security
    updates (cross-reference against WordPress.org's own supported-versions list). **Research
    pending:** WordPress.org exposes the live `core/stable-check` source, but the exact support
    semantics and reliable per-version response need a dedicated contract before adding a tool.

**✅ SHIPPED (2026-08-12, v1.20.0):** `verify_core_checksums` and
`verify_plugin_checksums` are SSH/WP-CLI-only, using the documented WordPress.org checksum
commands. Theme verification is intentionally not added: the official WP-CLI command reference
provides core and plugin checksum commands, not a corresponding `wp theme verify-checksums`
command; inventing one would be misleading. Complete 207-key pricing was saved with both checksum
checks priced at 1; local verification passed. Released in `a35079ff`, pushed to `main`, and
deployed; the platform synced the manifest, panels, icon, and four catalog tools with warning
status (`18/21` checks).
## Group Q — Mail Deliverability

71. `send_test_email` — trigger `wp_mail()` with a known test payload to a given address (Bridge or
    WP-CLI `wp eval` is explicitly excluded per this doc's own scope rule, so this MUST go through
    a dedicated Bridge endpoint calling `wp_mail()` directly, never raw eval) — verifies SMTP/mail
    plugin configuration actually delivers
72. `get_mail_configuration` — identifies the active WP Mail SMTP plugin when present, otherwise
    reports native/undetermined `wp_mail()` handling. It never returns SMTP credentials, SMTP host,
    or secret plugin settings.

**Release candidate (v1.21.0):** `send_test_email` uses a dedicated Imperal Bridge route calling
WordPress core's `wp_mail()` directly — never raw `wp eval`. A successful result means WordPress
accepted the fixed test message for sending, **not** that it arrived in an inbox. Both tools require
Bridge 2.15.0+; the complete 209-key pricing map was saved (`send_test_email=2`,
`get_mail_configuration=1`). Mark shipped only after commit, push, and deployment.

## Group R — WordPress Site Health (the plugin's own built-in diagnostics)

WordPress core itself (since 5.2) ships a Site Health screen backed by real REST routes
(`/wp-site-health/v1/tests/*`) — this is DIFFERENT from and complementary to this app's own
existing `get_site_health` (which is our own custom reachability/SSL/content-count check).

73. `run_site_health_tests` — call WordPress core's own `/wp-site-health/v1/tests/*` battery
    (background updates, HTTPS status, PHP version, scheduled events, loopback requests, etc.) and
    return WordPress's own pass/fail/critical verdicts — genuinely different data from our own
    `get_site_health`, not a duplicate
74. `get_core_site_health_directory_sizes` — WordPress core's accompanying
    `/wp-site-health/v1/directory-sizes` report. The broader "Info" tab is not represented as one
    stable core REST response, so it is deliberately not fabricated; existing `get_server_info`,
    `get_php_info`, and plugin/theme list tools cover its grounded parts.

**Release candidate (v1.22.0):** `run_core_site_health_tests` calls WordPress core's five
fixed, documented Site Health routes (background updates, loopback requests, HTTPS status,
WordPress.org communication, and authorization headers), reporting unavailable routes or missing
admin permission honestly per test. `get_core_site_health_directory_sizes` returns WordPress's own
size data. Complete 211-key pricing is prepared (`1` each); mark shipped only after commit, push,
and deployment.

## Group S — Sessions & Auth Hygiene

75. `list_active_sessions` — a user's currently active login sessions (native
    `WP_Session_Tokens`, no direct REST route in core — would need a small Bridge read) — real
    security-audit value ("is this account logged in somewhere unexpected")
76. `destroy_user_sessions` — force-logout one user everywhere via the user's native
    `WP_Session_Tokens::destroy_all()` Bridge call — useful after a suspected compromised account,
    pairs naturally with `reset_user_password` (already shipped, 1.3).
77. `list_nonce_lifetime` / security-header-adjacent settings — LOW priority, likely folds into
    Group F instead of its own function; listed here only for completeness, not a strong candidate.

**Release candidate (v1.23.0):** `list_active_sessions` and `destroy_user_sessions` use narrow
Bridge routes backed by WordPress core's `WP_Session_Tokens`; they reveal only login/expiry/IP/
user-agent metadata and never session tokens. Destroying sessions logs the named user out everywhere
without changing their password or account. Both require Bridge 2.16.0+ and WordPress's
`edit_users` capability. Complete 213-key pricing is prepared (`1` for listing, `2` for session
destruction); mark shipped only after commit, push, and deployment.

## Group T — Custom REST Endpoints & Plugin-Added Routes (discovery only)

78. **Assessed, no duplicate tool added.** Existing `list_rest_routes` already discovers every
    namespace from the site's native REST index and filters by namespace; `get_rest_route_schema`
    exposes each route's declared methods/args. WordPress does not keep a reliable core mapping from
    a registered route or namespace to the plugin that registered it, so attributing it to an
    installed plugin would be guesswork and is deliberately excluded.

## Group U — Site Icon / Branding Assets

79. **Shipped as an extension of existing native settings (v1.24.0):** WordPress core's
    `/wp/v2/settings` `site_icon` attachment field is now returned by `get_site_settings` and can
    be changed with `update_site_settings(site_icon=<media id>)`, or cleared with `site_icon=0`.
    No duplicate icon-only function and no new price were needed; the existing 213-key pricing map
    remains exact. Mark released only after commit, push, and deployment.

---

## What's explicitly NOT in scope here (same discipline as main roadmap)

- Arbitrary PHP execution / eval — never, under any framing. `wp eval`/`wp eval-file` WP-CLI
  commands exist but exposing them would be an unbounded remote-code-execution surface. Hard no.
- Direct raw SQL execution against the database — `run_db_search_replace` above is the ONE
  narrow, purpose-built exception (a single well-known safe WP-CLI subcommand with dry-run), not a
  general SQL console.
- wp-config.php credential/secret exposure (DB password, auth keys/salts) — Group H's
  `get_wp_config_constants` must have a hard allowlist, never a raw file dump.
- Full multisite network management beyond basic listing, until real demand confirms at least one
  connected site is multisite.
- SSL/domain-health checks — that's `web-tools`' job (`ssl_check`/`domain_full_check`), don't
  duplicate cross-app.

## Verification-first build order (once this doc is approved for building)

Same protocol as every past slice: read the real mechanism first (WP-CLI command reference for
CLI-based items, core REST handbook for native routes, or actual plugin/core source for anything
going through the Bridge), write a scoped plan, implement with MockContext tests (≥1 per
`@chat.function`), `imperal validate` + full pytest, `imperal build`, commit, push, deploy, price
every new function via `developer.update_pricing` with the COMPLETE map, submit for review, and log
the outcome in `CURRENT_WORK.md` + the canonical Notes doc.

Suggested build order (highest-value / most-requested-pattern first):
1. Group A (custom fields/meta) — closes the single most common "read/write arbitrary data on a
   post" gap; needed by other apps in the workspace too (any future ACF-aware content tooling).
2. Group C (transients/cache) + Group D (cron introspection) — natural extension of the existing
   SSH/WP-CLI server layer (5.2), same trust boundary already established.
3. Group B (database tools) — `run_db_search_replace` specifically is a very common ask
   (staging→prod migrations) but needs careful preview-first design.
4. Group F (security diagnostics) + Group E (REST/app-password introspection) — audit-focused,
   read-heavy, lower risk to ship.
5. Group H/I/J/K/L — fill in as real demand appears; L (WooCommerce webhooks) is notably
   low-effort since it's already a native REST route, could be pulled forward.
6. Group G (multisite) — gated on confirming real multisite demand first.

## 2026-08-12 — Group G / Multisite — shipped (Bridge 2.18.0, Hub 1.26.0)

`list_network_sites`, `list_network_plugins`, and `create_network_site` are now
implemented through a deliberately narrow Bridge network section. Every route first rejects a
non-Multisite install and requires WordPress's `manage_network_options` capability; site creation
uses only core `wpmu_create_blog()` and requires an already-existing owner account. No arbitrary
network settings, user creation, plugin installation, or cross-site bulk mutation was added.

Groups **K**, **H**, and **T** were rechecked and were already covered by shipped functions:
`list_reusable_blocks`/`list_block_patterns`; `get_wp_config_constants`, `list_must_use_plugins`,
`list_drop_ins`, `get_environment_type`; and `list_rest_routes` plus `get_rest_route_schema`.

## Bulk safety foundation — ✅ SHIPPED 2026-08-12

The existing explicit-ID bulk product/variation and CSV flows are now joined by a
reusable guarded pattern for WordPress core operations: every new batch action
reads each explicitly supplied target, returns a no-write preview and deterministic
state token, then re-reads all targets before any write. A changed snapshot stops
the entire apply operation before it can write.

- `preview_bulk_post_status` + `bulk_update_post_status` — 1–100 post/page/CPT
  status changes, including trash, via native WordPress REST.
- `preview_bulk_post_meta` + `apply_bulk_post_meta` — same safe custom meta pairs
  on 1–100 explicit post/page/CPT ids, through Bridge section 9.
- `preview_bulk_comment_status` + `apply_bulk_comment_status` — comment moderation
  for 1–100 explicit ids via native WordPress REST.

Preview is 40 credits and guarded batch application is 60 credits. Reads are never
charged zero: zero remains reserved only for fair local connection/access actions
that perform no WordPress work. Broad, inferred, wildcard, arbitrary SQL/PHP, and
blind builder-tree batch writes remain deliberately excluded.
