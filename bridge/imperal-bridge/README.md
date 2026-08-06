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

## What's inside (three sections, one plugin)

| Section | Endpoints | Exposes |
|---|---|---|
| SEO | `GET/POST /wp-json/imperal/v1/seo`, `.../seo/term`, `GET .../seo/status` | Rank Math SEO fields — title, description, focus keyword, robots, canonical, schema/rich-snippet type — for posts, pages, CPTs and taxonomy terms (categories, tags) |
| Builder | `GET /wp-json/imperal/v1/builder`, `POST .../builder/field`, `GET .../builder/status`, `GET .../builder/scan` | Elementor and Bricks page-builder element trees, with guarded single-field point edits (never a whole-tree replace) |
| Media | `POST /wp-json/imperal/v1/media/sideload`, `GET .../media/status` | Sideloads a public HTTPS image URL into the media library, optionally as a post's featured image, via WordPress's own `media_sideload_image()` |

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
```
