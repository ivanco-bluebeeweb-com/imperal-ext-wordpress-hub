# Imperal Media Bridge

Companion WordPress plugin that lets Imperal / Webbee add an existing public
image URL to the WordPress media library and optionally attach it to a post
as the featured image — without ever routing image bytes through Imperal's
own HTTP client.

## Why it is required

Imperal's outbound HTTP client (`ctx.http`) decodes every non-JSON response
body as UTF-8 **text** before handing it to extension code. That is correct
for HTML/XML/plain-text APIs, but it silently corrupts arbitrary binary
bytes: an image byte stream re-encoded through UTF-8 does not round-trip, so
a naive "download the image, then re-upload the bytes to WordPress" flow
would produce a broken attachment every time, with no error raised anywhere.

WordPress itself has no such problem. `media_sideload_image()` (built on
`download_url()`) fetches bytes straight to disk and hands them to the media
library — the exact mechanism behind the native "Insert from URL" flow in the
block editor. So this bridge asks WordPress to fetch its **own** copy of a
public image; Imperal only ever sends a URL, never bytes.

## What it does

1. **`POST /wp-json/imperal/v1/media/sideload`** — given a public `https://`
   image URL, downloads it server-side via `media_sideload_image()` and
   registers it as a normal media library attachment.

   Parameters:
   - `source_url` (required) — must be `https://` and resolve to a public
     hostname; loopback/private/link-local literals (`127.0.0.1`, `10.*`,
     `172.16-31.*`, `192.168.*`, `169.254.*`, `localhost`, `::1`, `fc../fd..`)
     are rejected before any fetch is attempted.
   - `post_id` / `post_slug` (+ optional `post_type` to disambiguate a shared
     slug) — optional. When given, the attachment is linked to that post
     (WordPress's own `post_parent` behaviour for sideloaded media).
   - `alt_text`, `caption` — optional metadata written onto the attachment.
   - `set_featured` (bool) — when true **and** a target post was given, sets
     the new attachment as that post's featured image via
     `set_post_thumbnail()`.

   Response: `attachment_id`, `url`, `width`, `height`, `attached_to` (post id
   or `null`), `featured_set` (bool — always `false` when no target post was
   given, even if `set_featured` was requested).

2. **`GET /wp-json/imperal/v1/media/status`** — capability discovery:
   `bridge: true`, `bridge_version`, `can_upload` (whether the authenticated
   user holds `upload_files`).

## Security

- `source_url` must be `https://` and a public host — checked with a
  conservative hostname denylist before any network fetch happens.
- Permission is checked with `current_user_can( 'upload_files' )` always, plus
  `current_user_can( 'edit_post', $post_id )` when a target post is given —
  the caller cannot attach media to a post they cannot edit even though they
  can upload files generally.
- The plugin never edits post content, status, or any field other than the
  attachment it just created and (optionally) the target post's featured
  image. It never deletes existing media.

## Installation

1. Zip the `imperal-media-bridge` folder.
2. WordPress admin → **Plugins → Add New → Upload Plugin** → choose the zip →
   **Install Now** → **Activate**.
3. Verify:

   ```
   curl -u USER:APP_PASSWORD \
     'https://example.com/wp-json/imperal/v1/media/status'
   ```

   Expected: `"bridge": true`.

## Relationship to WooCommerce product images

WooCommerce product images already work without this bridge — the
WooCommerce REST API accepts an `images: [{ src: "https://..." }]` array and
WooCommerce itself sideloads the URL server-side. This bridge exists because
the **core** WordPress REST API (`/wp/v2/posts`, `/wp/v2/pages`) has no
equivalent "attach by URL" capability — `featured_media` on those endpoints
only accepts an attachment id that must already exist in the media library.

## Uninstalling

Deactivating removes the sideload endpoint only. Attachments already created
through it are ordinary media library items and are unaffected.
