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

## Group B — Database Tools

8. `get_database_size` — already covered by `get_server_info`, no new function needed (noted in
   main roadmap 5.2)
9. `list_database_tables` — table names + row counts + size on disk (WP-CLI `wp db size --tables`
   or Bridge querying `information_schema`)
10. `run_db_search_replace` — the single most common WP migration task (domain change, staging→prod
    URL swap) — WP-CLI `wp search-replace`, MUST be dry-run-first (preview count of replacements)
    before a real run, same preview→apply pattern as CSV import
11. `optimize_database_tables` — WP-CLI `wp db optimize` (defragment/repair tables)
12. `check_database_repair` — WP-CLI `wp db check` / `wp db repair`
13. `export_database_dump` — WP-CLI `wp db export`, returns a downloadable/streamed dump (needs
    size-limit handling — a full dump can be huge; likely needs to write to a known path and return
    a signed URL rather than inline content)
14. `count_post_type_rows` / `count_orphaned_postmeta` — common "is my DB clean" backend-dev
    diagnostic, WP-CLI `wp post list --format=count` / raw meta orphan query

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

## Group E — REST API Introspection

25. `list_rest_routes` — enumerate every registered REST route + namespace on the site
    (`/wp-json` root discovery document) — useful for "what can I actually call on this site,
    including from other plugins"
26. `get_rest_route_schema` — the args/schema for one specific route
27. `list_application_passwords` — list the currently-registered Application Passwords for a user
    (native `/wp/v2/users/<id>/application-passwords`, WP 5.6+) — NOT the secret itself, just
    name/created/last-used, for auditing "what has access to this site"
28. `revoke_application_password` — revoke one named Application Password by uuid (native route) —
    genuinely useful security hygiene function, distinct from `forget_site` which only removes our
    OWN stored credential

## Group F — Security / Hardening Diagnostics

29. `get_php_info` — PHP version, loaded extensions, memory_limit/max_execution_time/upload
    limits (WP-CLI `wp cli info` / `phpversion()` via Bridge) — feeds "is this site tech-eligible
    for X" questions
30. `check_file_permissions` — wp-config.php / wp-content permissions sanity check (Bridge/SSH)
31. `list_admin_users` — filter `list_users` by administrator role specifically, a common security
    audit ask ("who has admin on this site")
32. `check_debug_mode` — is WP_DEBUG / WP_DEBUG_LOG on (should usually be OFF in production) —
    Bridge reading the constant
33. `get_ssl_status` — already partially covered elsewhere (web-tools app's `ssl_check` is the
    proper home for this — do NOT duplicate; cross-reference instead of rebuilding)
34. `list_failed_login_attempts` — only if a security plugin (Wordfence/Limit Login Attempts) is
    active and exposes this; must degrade cleanly, never fabricate a log that isn't there

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

## Group I — Logs

43. `tail_debug_log` — last N lines of `wp-content/debug.log` (SSH-based; huge value for "why did
    that last save fail")
44. `clear_debug_log` — truncate the debug log file (SSH)
45. `tail_error_log` — server-level PHP error log if path is known/discoverable (SSH)

## Group J — Custom Post Types & Taxonomies (introspection, not content)

46. `list_registered_post_types` — every CPT the site has registered (not just the ones we already
    know to query via `list_custom_posts`), with `rest_base`, `public`, `hierarchical` flags — lets
    us discover CPTs dynamically instead of the user having to already know the slug
47. `list_registered_taxonomies` — same, for taxonomies (already partially needed internally for the
    llms.txt MultiSelect population — could become its own first-class function)

## Group K — Blocks / Patterns / Templates (block-theme era, read-only diagnostics only)

48. `list_reusable_blocks` — `wp_block` post type listing (Gutenberg reusable blocks / "synced
    patterns") — a real, common editorial-meets-dev question ("which pages use this reusable
    block")
49. `list_block_patterns` — registered block patterns (theme + plugin supplied)
- **Deliberately excluded:** full Site Editor template editing — matches existing Widgets/FSE
  exclusion decision in the main roadmap (1.6), same reasoning.

## Group L — Webhooks / Integrations

50. `list_registered_webhooks` — if WooCommerce is active, `wc/v3/webhooks` is a REAL native route
    already exposed by WooCommerce core — list configured webhooks (URL, topic, status)
51. `get_webhook` — read one webhook's full config + delivery log summary (native route)
52. `create_webhook` — same native WooCommerce route, write side — lets a backend dev wire this
    site into an external system without touching wp-admin
53. `update_webhook` — change URL/topic/status/secret on an existing webhook
54. `delete_webhook` — remove a webhook

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
