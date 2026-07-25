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

3. **Adds** `/wp-json/imperal/v1/seo/status` for capability discovery.

### Why robots is endpoint-only

Rank Math stores `rank_math_robots` as an **array**. Registering array meta on
the standard collection endpoints is risky: core requires an explicit
`show_in_rest.schema.items`, and any legacy row holding a scalar can make the
whole `/wp/v2/posts` response fail schema validation — which would break the
existing `list_posts` tool. The dedicated endpoint normalises such rows safely
(scalar → array) instead.

## Security

- Every request is checked with `current_user_can( 'edit_post', $post_id )` —
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
