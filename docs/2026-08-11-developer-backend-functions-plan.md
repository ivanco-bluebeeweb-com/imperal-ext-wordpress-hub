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
38. **Gate:** none of Group G should be built until we've confirmed at least one connected site is
    actually multisite — building against `is_multisite()===false` everywhere would be
    building for a persona we don't have yet.

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

## Group M — Action Scheduler / Background Job Queue

WooCommerce (and many other plugins) ship Action Scheduler, which stores every scheduled/queued
background job as real rows in `wp_actionscheduler_actions` (or as a dedicated custom table on
newer versions) and exposes an actual wp-admin screen (Tools → Scheduled Actions). This is a
first-class backend-dev diagnostic surface for "why didn't my order emails/webhooks/sync jobs run" —
distinct from native WP-Cron (Group D), which only decides *when* Action Scheduler's own runner
next wakes up.

55. `list_scheduled_actions` — pending/in-progress/complete/failed/canceled queue entries, filterable
    by status and by hook name (WP-CLI `wp action-scheduler list` if the Action Scheduler CLI
    package is present, else Bridge reading the table directly)
56. `get_scheduled_action` — full detail (args, group, scheduled date, log) for one action id
57. `run_scheduled_action` — force-run one pending action immediately (`wp action-scheduler run
    --hooks=<id>`)
58. `cancel_scheduled_action` — cancel one pending action
59. `retry_failed_action` — re-queue one failed action for another attempt
60. `count_actions_by_status` — quick health snapshot ("47 failed, 3 pending") — the single most
    useful one-glance backend-dev diagnostic for this whole group

## Group N — Rewrite Rules & Permalinks

61. `get_permalink_structure` — the site's current permalink structure string (native
    `/wp/v2/settings` already returns some of this — verify exact field before assuming a new
    Bridge route is needed)
62. `update_permalink_structure` — change it (Bridge; core has no REST route for
    `update_option('permalink_structure', ...)` + `flush_rewrite_rules()` as one atomic action)
63. `flush_rewrite_rules` — the single most common "why is this page 404ing" fix after a CPT/
    permalink change (Bridge calling `flush_rewrite_rules()` directly, or WP-CLI `wp rewrite flush`)
64. `list_rewrite_rules` — dump the actual compiled rewrite rule table for debugging routing
    conflicts between plugins (WP-CLI `wp rewrite list`)

## Group O — Import / Export (WXR)

65. `export_wxr` — trigger WordPress's own native WXR (WordPress eXtended RSS) export
    (`wp export` WP-CLI, or the core `/wp-admin/export.php` mechanism via Bridge) — full site or
    filtered by post type/date range/author; needs the same size-limit handling as
    `export_database_dump` (Group B) — write to a path, return a link, not inline content
66. `import_wxr` — import a WXR file into the site (`wp import` WP-CLI, requires the
    `wordpress-importer` plugin to be present — must detect and report cleanly if it's missing
    rather than fail silently)

## Group P — Core / Plugin / Theme Integrity (security-relevant)

67. `verify_core_checksums` — WP-CLI `wp core verify-checksums`: detects modified/added core files
    vs. the official WordPress.org checksums — a real, standard malware/tamper detection step
68. `verify_plugin_checksums` — WP-CLI `wp plugin verify-checksums`: same, for plugins hosted on
    wordpress.org (naturally skips premium/custom plugins not in that repo — must report that
    honestly, not as a false pass or fail)
69. `check_core_update_available` / `list_plugin_updates_available` / `list_theme_updates_available`
    — read-only "what's outdated" listing, distinct from the existing `update_plugin`/`update_core`
    (5.2) which already perform the update itself — useful as a lighter-weight audit-only call
70. `get_wp_version_support_status` — is the connected site's WP version still receiving security
    updates (cross-reference against WordPress.org's own supported-versions list)

## Group Q — Mail Deliverability

71. `send_test_email` — trigger `wp_mail()` with a known test payload to a given address (Bridge or
    WP-CLI `wp eval` is explicitly excluded per this doc's own scope rule, so this MUST go through
    a dedicated Bridge endpoint calling `wp_mail()` directly, never raw eval) — verifies SMTP/mail
    plugin configuration actually delivers
72. `get_mail_configuration` — which mail-sending mechanism is active (native `wp_mail` vs. an SMTP
    plugin like WP Mail SMTP) if discoverable via a known option/constant — must degrade honestly
    when no such plugin is present rather than guess

## Group R — WordPress Site Health (the plugin's own built-in diagnostics)

WordPress core itself (since 5.2) ships a Site Health screen backed by real REST routes
(`/wp-site-health/v1/tests/*`) — this is DIFFERENT from and complementary to this app's own
existing `get_site_health` (which is our own custom reachability/SSL/content-count check).

73. `run_site_health_tests` — call WordPress core's own `/wp-site-health/v1/tests/*` battery
    (background updates, HTTPS status, PHP version, scheduled events, loopback requests, etc.) and
    return WordPress's own pass/fail/critical verdicts — genuinely different data from our own
    `get_site_health`, not a duplicate
74. `get_site_health_info` — the accompanying `/wp-site-health/v1/directory-sizes` and environment
    info tab (server software, DB version/extension, active theme/plugins summary) — WordPress's
    own copy-pasteable "Info" tab, useful for support-ticket-style diagnostics

## Group S — Sessions & Auth Hygiene

75. `list_active_sessions` — a user's currently active login sessions (native
    `WP_Session_Tokens`, no direct REST route in core — would need a small Bridge read) — real
    security-audit value ("is this account logged in somewhere unexpected")
76. `destroy_user_sessions` — force-logout one user everywhere (`wp_destroy_all_sessions()` via
    Bridge) — useful after a suspected compromised account, pairs naturally with
    `reset_user_password` (already shipped, 1.3)
77. `list_nonce_lifetime` / security-header-adjacent settings — LOW priority, likely folds into
    Group F instead of its own function; listed here only for completeness, not a strong candidate

## Group T — Custom REST Endpoints & Plugin-Added Routes (discovery only)

78. `list_third_party_rest_namespaces` — beyond `list_rest_routes` (Group E), specifically surface
    which INSTALLED PLUGINS registered which namespaces, cross-referenced against
    `list_native_plugins` — answers "what API surface did installing this plugin actually add"

## Group U — Site Icon / Branding Assets

79. `get_site_icon` / `update_site_icon` — native `site_icon` field on `/wp/v2/settings` (already
    partially covered by `get_site_settings`/`update_site_settings` from 1.7 — verify the exact
    field is already returned before treating this as a new function; likely already free)

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
