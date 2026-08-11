# Imperal Bridge

The **single** companion WordPress plugin for Imperal / Webbee's WordPress Hub
connector. It replaces three previously-separate plugins — Imperal SEO
Bridge, Imperal Builder Bridge and Imperal Media Bridge — with one plugin,
one version number, one install/update step.

**Going forward, every new bridge capability Imperal adds lands in this
plugin as a new section. There will not be a fourth bridge plugin.**

## Why a bridge is needed at all

WordPress core only exposes post meta over the REST API when it is
registered with `show_in_rest`. Several things Imperal needs to read/write
never do that for their own data:

- Rank Math never calls `register_post_meta()`/`register_meta()` for its
  `rank_math_*` keys (verified against `seo-by-rank-math` 1.0.274.1), and
  marks them *protected* meta on top of that.
- Neither Elementor (`_elementor_data`) nor Bricks (`_bricks_page_*_2`) do it
  for their page-builder trees.
- WordPress has no REST endpoint for "fetch this external image URL into my
  own media library" — and Imperal's outbound HTTP client cannot safely
  proxy raw image bytes (it decodes non-JSON bodies as UTF-8 text, which
  corrupts binary data).

No Application Password can work around any of that. A companion plugin
that runs *inside* WordPress, with real capability checks, is the only fix.

## What's inside (five sections, one plugin)

| Section | Endpoints | Exposes |
|---|---|---|
| SEO | `GET/POST /wp-json/imperal/v1/seo`, `.../seo/term`, `GET .../seo/status` | Rank Math SEO fields — title, description, focus keyword, robots, canonical, schema/rich-snippet type — for posts, pages, CPTs and taxonomy terms (categories, tags) |
| Builder | `GET /wp-json/imperal/v1/builder`, `POST .../builder/field`, `GET .../builder/status`, `GET .../builder/scan` | Elementor and Bricks page-builder element trees, with guarded single-field point edits (never a whole-tree replace) |
| Media | `POST /wp-json/imperal/v1/media/sideload`, `GET .../media/status` | Sideloads a public HTTPS image URL into the media library, optionally as a post's featured image, via WordPress's own `media_sideload_image()` |
| Server | `GET /wp-json/imperal/v1/server/info` | WP-CLI-equivalent server diagnostics without a shell: core/PHP version, plugin/theme/core update lists, cron job count, database size in MB |
| Redirects | `GET/POST /wp-json/imperal/v1/redirects`, `DELETE .../redirects/{id}`, `POST .../redirects/{id}/status` | Rank Math's URL Redirections module — list/create/delete a redirect, activate/deactivate/trash one — read/written directly against Rank Math's own `{prefix}rank_math_redirections` table, since Rank Math itself never exposes this over REST |
| Security | `GET /wp-json/imperal/v1/security/php-info`, `.../security/debug-mode`, `.../security/file-permissions` | PHP runtime facts (version, loaded extensions, memory/upload/execution limits), whether WP_DEBUG/WP_DEBUG_LOG/WP_DEBUG_DISPLAY are on, and wp-config.php/wp-content permission bits — plain PHP built-ins, no shell needed |
| Deploy | `GET /wp-json/imperal/v1/deploy/config-constants`, `.../deploy/mu-plugins`, `.../deploy/drop-ins`, `.../deploy/environment-type` | A hard-allowlisted safe subset of wp-config.php constants (never DB credentials or auth keys/salts), must-use plugins, drop-in files (object-cache.php/advanced-cache.php/db.php), and WordPress's own declared environment type |
| Database | `POST /wp-json/imperal/v1/database/search-replace`, `GET .../database/tables`, `POST .../database/optimize`, `POST .../database/check`, `GET .../database/export`, `GET .../database/post-count`, `GET .../database/orphaned-postmeta` | Table listing/size, serialization-safe search-and-replace (dry-run always available), OPTIMIZE/CHECK/REPAIR TABLE, a capped SQL dump, and row-count/orphaned-postmeta diagnostics — all plain `$wpdb` calls that used to require SSH + WP-CLI's own `wp db *` commands |
| Logs | `GET /wp-json/imperal/v1/logs/debug-log`, `POST .../logs/debug-log/clear`, `GET .../logs/php-error-log` | Tail/truncate `wp-content/debug.log` and read PHP's own `ini_get('error_log')` path — plain filesystem calls from inside the WordPress process that used to require SSH + WP-CLI's `wp eval` |
| Cache & Cron | `GET /wp-json/imperal/v1/cache/transients`, `POST .../cache/transients/delete`, `POST .../cache/transients/flush-all`, `GET .../cache/object-cache-status`, `POST .../cache/object-cache/flush`, `GET .../cache/cron/events`, `POST .../cache/cron/events/run`, `POST .../cache/cron/events/delete`, `GET .../cache/cron/schedules` | Transients (list/delete/flush-all via the real `delete_transient()`/`delete_site_transient()` API, not a raw options-table write), persistent object-cache status/flush (`wp_using_ext_object_cache()`/`wp_cache_flush()`), and WP-Cron introspection (`_get_cron_array()`, `wp_unschedule_hook()`, `wp_get_schedules()`) — all plain WordPress core calls that used to require SSH + WP-CLI's `wp transient`/`wp cache`/`wp cron` commands |
| Maintenance | `POST /wp-json/imperal/v1/maintenance/update-plugin`, `.../maintenance/update-core`, `.../maintenance/run-due-cron`, `.../maintenance/install-plugin`, `.../maintenance/purge-cache`, `GET .../maintenance/list-plugins` | Update one plugin or WordPress core via the exact same `Plugin_Upgrader`/`Core_Upgrader` + `Automatic_Upgrader_Skin` classes wp-admin's own "Update Now" button and WordPress's background auto-updates use, force-run every past-due cron hook, install a new plugin from a WordPress.org slug (resolved via `plugins_api()`, same lookup the "Add New Plugin" screen uses) or a direct .zip URL, purge LiteSpeed Cache/W3 Total Cache by firing each plugin's own real purge hook (`litespeed_purge_all`/`w3tc_flush_all`), and list every installed plugin with real active-state and update-availability (`get_plugins()` + `is_plugin_active()` + `get_plugin_updates()`) — all plain core upgrade/cron/install/plugin-inventory APIs that used to require SSH + WP-CLI's `wp plugin update`/`wp core update`/`wp cron event run --due-now`/`wp plugin install`/`wp litespeed-purge`/`wp w3-total-cache flush all`/`wp plugin list` |
| Action Scheduler | `GET /wp-json/imperal/v1/action-scheduler/actions`, `GET .../action-scheduler/actions/{id}`, `POST .../action-scheduler/actions/{id}/run`, `POST .../action-scheduler/actions/{id}/cancel`, `POST .../action-scheduler/actions/{id}/retry`, `GET .../action-scheduler/counts` | List/inspect/force-run/cancel/retry jobs in WooCommerce's own background job queue (bundled Action Scheduler library, NOT WordPress core) via `ActionScheduler::store()`/`runner()`/`logger()` — the same calls the plugin's own Tools → Scheduled Actions admin screen uses. Retrying re-enqueues a fresh attempt with `as_enqueue_async_action()` since Action Scheduler has no native retry. Returns a clear 404 if Action Scheduler isn't active on the site — no SSH fallback exists worth building (WP-CLI needs the exact same WooCommerce/library context loaded) |

Sections beyond these (Users password-reset, Rank Math site-wide SEO score/
robots.txt/sitemap/404-log, llms.txt, and the generic post/user/term meta +
wp_options bridge) exist too — see the section header comments inside
`imperal-bridge.php` itself for the full, current list; this table covers
the earliest five plus the newest one added.

Plus one small addition from the merge itself: `GET /wp-json/imperal/v1/status`
— reports the bridge is installed and which sections are active, without
needing to know which specific route to probe first.

Each section keeps its original function names, hooks and REST routes
unchanged from when it shipped as a standalone plugin — the merge only
changed the plugin header and file layout, not the logic. That is also why
the per-section tests (`tests/seo_logic_test.php`, `tests/builder_logic_test.php`,
`tests/media_logic_test.php`) still exist as three files instead of one.

## Install

1. Download `imperal-bridge.zip` (the WordPress Hub app's `install_plugin`
   chat function can also install it directly from a `.zip` URL over WP-CLI).
2. WordPress admin → Plugins → Add New → Upload Plugin → pick the zip →
   Install Now → Activate.
3. Confirm from Imperal: `check_seo_support` / `check_builder_support` /
   the media-status check will report `bridge_version` once active.

## Migrating from the three old plugins

If a site still has Imperal SEO Bridge, Imperal Builder Bridge and/or
Imperal Media Bridge installed separately: deactivate and delete all three,
then install Imperal Bridge. All three sections' REST routes are identical
in shape and behaviour, so nothing on the Imperal side needs to change.

## Requirements

- WordPress 6.0+, PHP 8.0+
- Rank Math (for the SEO section), Elementor or Bricks (for the Builder
  section) — each section degrades gracefully and reports itself inactive
  when its target plugin is missing; it does not require all three.

## Tests

Standalone PHP logic harnesses — no WordPress install needed, core
functions are stubbed:

```
php tests/seo_logic_test.php
php tests/builder_logic_test.php
php tests/media_logic_test.php
php tests/database_logic_test.php
php tests/logs_logic_test.php
```
