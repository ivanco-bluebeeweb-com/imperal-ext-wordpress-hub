# Imperal Builder Bridge

Companion WordPress plugin that exposes **Elementor** and **Bricks** page-builder
element trees to the REST API, with guarded single-field point edits, so
Imperal / Webbee can read and precisely edit builder content without touching
the rest of the page.

## Why it is required

- Elementor stores a page's whole element tree in one post meta key,
  `_elementor_data`, as JSON: a **nested** array (`elType` / `widgetType` /
  `settings` / `elements`).
- Bricks stores each template area in its own meta key — `_bricks_page_header_2`,
  `_bricks_page_content_2`, `_bricks_page_footer_2` — as JSON: a **flat** array
  of elements, each carrying `parent` / `children` ids instead of physical
  nesting (schema v2.3).

Neither plugin registers these keys with `register_post_meta()` /
`show_in_rest`, so stock REST + an Application Password cannot see or write
them — same root cause as Rank Math's `rank_math_*` meta before the SEO
bridge existed.

## Design: point editing, not page building

This bridge does **not** expose "replace the whole tree" or "create a new
element". Every write targets exactly **one existing element**, by its
builder-native id, and exactly **one field** inside that element's settings.
This mirrors the WooCommerce bulk-update pattern already used elsewhere in
this connector: **preview (read) → `state_token` → guarded write**. If the
page changed since the read, the write is refused with 409 rather than
silently overwriting someone else's edit.

## What it does

1. **`GET /wp-json/imperal/v1/builder`** — read the flattened element tree.
   Resolves the target post by `id` or `slug` (+ optional `type` to
   disambiguate), same contract as the SEO bridge. Optional `builder` param
   (`elementor` or `bricks`) restricts the response when both are active.

   Response shape:
   ```json
   {
     "id": 42, "slug": "home", "type": "page", "link": "https://…",
     "active_builders": ["elementor"],
     "builders": {
       "elementor": {
         "elements": [
           {"id": "3130e2cf", "parent_id": null, "el_type": "container",
            "widget_type": "", "settings": {"...": "..."}},
           {"id": "a1b2c3d4", "parent_id": "3130e2cf", "el_type": "widget",
            "widget_type": "heading", "settings": {"title": "Welcome"}}
         ],
         "state_token": "…sha256…",
         "element_count": 2
       },
       "bricks": {
         "zones": {
           "content": {
             "elements": [
               {"id": "abc123", "parent_id": null, "el_type": "container",
                "widget_type": "", "settings": {"...": "..."}, "zone": "content"}
             ],
             "state_token": "…sha256…"
           }
         }
       }
     }
   }
   ```

   Both builders return the **same flat shape** (`id`, `parent_id`, `el_type`,
   `widget_type`, `settings`) — Elementor's nested tree is flattened
   server-side so a client never has to handle two different data shapes.
   Bricks additionally carries `zone` per element since one post can have
   header/content/footer zones at once.

2. **`POST /wp-json/imperal/v1/builder/field`** — update one field on one
   element.

   Body: `{ id, element_id, field, value, state_token, builder?, zone? }`
   - `builder` is required only when both Elementor and Bricks are active on
     the same post (409 `imperal_builder_ambiguous_builder` otherwise).
   - `zone` (`header` | `content` | `footer`) is required for Bricks writes,
     since each zone is a separate meta key with its own `state_token`.
   - `value` can be a string, number, bool, or a nested object/array — both
     builders store compound fields that way (e.g. `{"unit": "px", "size": 20}`
     for a spacing control), so the bridge accepts whatever JSON value is sent
     and stores it verbatim in that one settings key. It does not interpret
     or validate builder-specific field semantics.
   - Stale `state_token` → `409 imperal_builder_stale_state`. Unknown
     `element_id` → `404 imperal_builder_element_not_found`.
   - Only the targeted element's `settings[field]` changes — the rest of the
     tree, including sibling and parent elements, is round-tripped byte-for-byte
     apart from the one edit.
   - After an Elementor write, its per-element CSS cache (`_elementor_css`
     meta) is cleared and, if Elementor's own file-cache manager is loaded,
     asked to clear too — otherwise the edit can be invisible until Elementor's
     own cache expires.

3. **`GET /wp-json/imperal/v1/builder/status`** — capability discovery:
   whether the bridge is present, and whether Elementor / Bricks are active
   site-wide (plugin activation is a site-wide fact, independent of any one
   post).

## Security

- Every request is checked with `current_user_can( 'edit_post', $post_id )` —
  the same per-object gate as content edits, not a blanket `edit_posts`.
- Both builders' full field maps are treated as opaque JSON with no built-in
  sanitisation beyond WordPress's own JSON round-trip, mirroring how each
  builder itself already stores this data. The bridge never changes post
  content, title, status, author or slug — only one settings key on one
  builder element.
- The `/imperal/v1/builder*` namespace is marked uncacheable on every request
  (`DONOTCACHEPAGE`, LiteSpeed's no-cache action, `nocache_headers()`, explicit
  `no-store` headers) so a page cache never serves a stale read right after a
  write, or answers a permission-gated route from a shared cache entry — the
  same fix already applied in the SEO bridge after it was observed live on a
  LiteSpeed site.

## Installation

1. Zip the `imperal-builder-bridge` folder.
2. WordPress admin → **Plugins → Add New → Upload Plugin** → choose the zip →
   **Install Now** → **Activate**.
3. Verify:

   ```
   curl -u USER:APP_PASSWORD \
     'https://example.com/wp-json/imperal/v1/builder/status'
   ```

   Expected: `"bridge": true` and `"elementor_active"` / `"bricks_active"`
   reflecting what is actually installed on the site.

## Uninstalling

Deactivating removes the REST exposure only. **No builder data is deleted** —
Elementor's and Bricks' own meta stays in the database and each builder keeps
rendering the page normally through its own (non-REST) code path.
