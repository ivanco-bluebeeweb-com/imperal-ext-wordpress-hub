# WP Site Connector — companion bridge plugins

Two small WordPress plugins live under `bridge/`, each solving the same root
problem for a different kind of data: WordPress core only exposes post meta
over the REST API when it is registered with `show_in_rest`, and neither Rank
Math nor the page builders below do that for their own data. No Application
Password can work around that — a companion plugin is required.

| Plugin | Folder | Exposes |
|---|---|---|
| Imperal SEO Bridge | `imperal-seo-bridge/` | Rank Math SEO fields (posts, pages, CPTs, terms) |
| Imperal Builder Bridge | `imperal-builder-bridge/` | Elementor and Bricks page-builder element trees, with guarded single-field point edits |

See `imperal-builder-bridge/README.md` for the builder bridge. The rest of
this file covers the SEO bridge.

# Imperal SEO Bridge

Companion WordPress plugin that exposes **Rank Math** SEO fields to the REST API
so Imperal / Webbee can read and edit them.

## Why it is required

Rank Math never calls `register_post_meta()` / `register_meta()` anywhere in its
codebase (verified against `seo-by-rank-math` 1.0.274.1). WordPress core only
exposes post meta over the REST API when it is registered with `show_in_rest`.

Consequence: **without a companion plugin the `rank_math_*` fields are invisible
to the REST API** — reads return nothing and writes are silently dropped. This is
not a configuration problem and no Application Password can work around it.

On top of that, Rank Math marks every `rank_math_*` key as *protected* meta
(`includes/class-common.php` → `hide_rank_math_meta`). For protected keys core
falls back to `auth_callback = __return_false`, so an explicit `auth_callback`
is required or every write fails with `rest_cannot_update`.

## What it does

1. **Registers the string SEO fields** for every public post type that supports
   `custom-fields` — so `post`, `page` and eligible CPTs, not just posts:
   - `rank_math_title`
   - `rank_math_description`
   - `rank_math_focus_keyword`
   - `rank_math_canonical_url`

2. **Adds a dedicated endpoint** `/wp-json/imperal/v1/seo` (GET + POST) that
   additionally handles `rank_math_robots`, resolves items by `id` or `slug`,
   and reports which SEO plugin is active.

3. **Adds** `/wp-json/imperal/v1/seo/status` for capability discovery — including
   the `taxonomies` list, which is how a client can tell whether a site's bridge
   is new enough to handle categories.

4. **Registers the same fields for taxonomy terms** and adds
   `/wp-json/imperal/v1/seo/term` (GET + POST) — categories, tags and custom
   taxonomies. *(v1.1.0)*

### Terms: categories and tags (v1.1.0)

Rank Math stores term SEO under the **same** `rank_math_*` keys it uses for
posts — only the storage call differs. That is confirmed in Rank Math's own
code, not inferred: `includes/rest/class-post.php` switches
`update_term_meta` / `update_post_meta` by object type while keeping the key
names, its content-AI bulk editor does the same, and the Yoast importer maps
`wpseo_title` → `rank_math_title` via `update_term_meta`.

Two consequences worth knowing:

- **Term meta lives in a different table** (`termmeta`), so the post endpoint
  cannot reach it. Hence the separate `/seo/term` route.
- **There is no fallback tier for terms.** The older `wp-publisher-bridge`
  registers post meta only, so on a site without this bridge (or one older than
  1.1.0) category SEO is unreachable, and the connector says so explicitly
  rather than reporting empty fields as if the category had none set.

Editing is gated with `current_user_can( 'edit_term', $term_id )` — a
**per-term meta capability**, which WordPress maps through each taxonomy's own
capability set. A flat `manage_categories` check would be the wrong gate for
custom taxonomies that define their own capabilities, the term-side equivalent
of `post` and `page` having different `capability_type` values.

Menu and pattern plumbing (`nav_menu`, `link_category`, `wp_pattern_category`,
`post_format`) is deliberately skipped — those terms carry no SEO meaning. The
covered list is filterable via `imperal_seo_bridge_taxonomies`.

### Supporting Yoast later (extension path)

Nothing here is Rank-Math-specific except the key names and the sanitisers.
To add Yoast without disturbing this plugin:

1. Keep the routes and the payload shape exactly as they are — the client
   already reads `meta_title` / `meta_description` and reports which plugin
   answered via `seo_plugin`.
2. Swap the key map (`rank_math_title` → `_yoast_wpseo_title`,
   `rank_math_description` → `_yoast_wpseo_metadesc`, focus keyword →
   `_yoast_wpseo_focuskw`, canonical → `_yoast_wpseo_canonical`) behind a
   detector that checks which plugin is active, in one place: the `$map` array
   used by the update handlers plus the matching payload readers.
3. Yoast expresses robots as separate `noindex` / `nofollow` values rather than
   one array, so that field needs a translation layer, not a rename.

Because the field map is already the single source of truth for both posts and
terms, this stays a contained change rather than a second plugin.

### Page caches must not store these routes (v1.0.1)

The `/imperal/v1/*` routes are permission-gated and their bodies differ per
user, so a page cache that stores one response and replays it is an
access-control failure, not merely staleness.

This was observed live, not hypothetically: on a LiteSpeed site the bridge
route answered an **anonymous** request with `x-litespeed-cache: hit`, HTTP 200
and real SEO data, while the identical request with a cache-buster correctly
returned 403. The same cache entry also made a read immediately after a write
look empty.

Since 1.0.1 the plugin marks its own namespace uncacheable on every request:
`DONOTCACHEPAGE` (honoured by LiteSpeed, WP Super Cache, W3 Total Cache),
LiteSpeed's `litespeed_control_set_nocache` action, `nocache_headers()` and
explicit `no-store` headers. It is scoped to this namespace only — caching
everywhere else on the site is untouched.

**Upgrading from 1.0.0:** entries cached before the fix survive it. Purge the
site cache once after updating (LiteSpeed → Toolbox → Purge All, or
`wp litespeed-purge all`). Without that purge a stale response can still be
served for a while.

### Why robots is endpoint-only

Rank Math stores `rank_math_robots` as an **array**. Registering array meta on
the standard collection endpoints is risky: core requires an explicit
`show_in_rest.schema.items`, and any legacy row holding a scalar can make the
whole `/wp/v2/posts` response fail schema validation — which would break the
existing `list_posts` tool. The dedicated endpoint normalises such rows safely
(scalar → array) instead.

## Security

- Every post request is checked with `current_user_can( 'edit_post', $post_id )`
  and every term request with `current_user_can( 'edit_term', $term_id )` —
  a **per-object** check. This matters because `post` and `page` have different
  `capability_type` values, so a blanket `edit_posts` check is the wrong gate
  for pages.
- Values are sanitised the same way Rank Math sanitises them
  (`includes/rest/class-sanitize.php`): text through `wp_filter_nohtml_kses`,
  canonical through `esc_url_raw`, robots validated against Rank Math's own
  allowed list.
- Empty values **delete** the meta row rather than storing a blank string,
  matching Rank Math's own behaviour so its template fallback still applies.
- The plugin never changes post content, status, author or slug.

## Installation

1. Zip the `imperal-seo-bridge` folder (or use the prebuilt
   `imperal-seo-bridge.zip`).
2. WordPress admin → **Plugins → Add New → Upload Plugin** → choose the zip →
   **Install Now** → **Activate**.
3. Verify:

   ```
   curl -u USER:APP_PASSWORD \
     'https://example.com/wp-json/imperal/v1/seo/status'
   ```

   Expected: `"bridge": true` and `"seo_plugin": "rank-math"`.

## Relationship to the WP Publisher bridge

`wp-publisher-bridge` registers three Rank Math fields for the `'post'` type
only, which is why pages currently return no SEO fields at all. This plugin is a
superset and covers pages and CPTs.

Running both is harmless — WordPress lets a later `register_post_meta()` call
overwrite the earlier registration for the same key — but once this bridge is
active the older one is redundant and can be deactivated.

## Uninstalling

Deactivating removes the REST exposure only. **No SEO data is deleted** — the
`rank_math_*` meta stays in the database and Rank Math keeps using it.
