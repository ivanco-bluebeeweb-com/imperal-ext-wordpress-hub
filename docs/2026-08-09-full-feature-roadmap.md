# WordPress Hub — Full Feature Roadmap

Status: **canonical / living document — this is the master plan for what to build in this app.**
Date: 2026-08-09, updated 2026-08-10. Supersedes ad-hoc feature lists; update this file whenever scope changes.

## Purpose

WordPress Hub now ships 139 functions covering sites, posts/pages (incl. delete/duplicate/bulk
status), taxonomy, media, SEO (Rank Math per-content + full site-wide coverage: redirects, robots.txt,
sitemap status, SEO score, 404 monitor, Instant Indexing/IndexNow, llms.txt), page builders
(Elementor/Bricks point-edits), WooCommerce (incl. product reviews, manual order entry, order note
thread, customer deletion), native user management, menus/navigation, site settings + native
plugin/theme listing, and SSH/WP-CLI + Bridge server ops. This document maps EVERY realistic
capability across WordPress Core, WooCommerce, Rank Math, and our own Bridge/SSH layer — what exists
today, what's missing, and in what order to build it. Every future "what should we add" conversation
starts from this file, not from memory.

Coverage baseline verified against the actual codebase on 2026-08-10 (grep of all
`@chat.function`/`@ext.expose` decorators across `handlers_*.py` — 139 functions confirmed, up from
87 on 2026-08-09 — Priorities 2 through 7 shipped 2026-08-10 morning, Priority 8a (create_order/
list_order_notes/delete_customer) shipped 2026-08-10 afternoon, Priority 13 (full Rank Math
site-wide coverage: robots.txt, sitemap status, SEO score, 404 monitor) shipped 2026-08-10 evening,
Priority 14 (Instant Indexing/IndexNow) and Priority 15 (llms.txt) — both found via the SAME full
doc+plugin-source re-audit — shipped 2026-08-10 night. That re-audit also turned up Rank Math's
newer `ai-visibility` module (brand-tracking against AI answer engines): investigated and
deliberately NOT built — it is a paid Rank Math SaaS proxy gated behind a separate connected Rank
Math account + trial/subscription, not WordPress site data, so covering it would mean reselling
Rank Math's own paid analytics subscription rather than exposing real site-management capability.
Rank Math is now confirmed FULLY covered against every real, callable, site-management module in the
actual plugin source, not just against our own prior assumptions).

---

## Layer 1 — WordPress Core (native content & site management)

### 1.1 Posts & Pages — ✅ lifecycle gaps closed 2026-08-10
| Function | Status |
|---|---|
| `list_posts`, `list_pages`, `list_scheduled` | ✅ done |
| `create_post`, `update_post` (Gutenberg blocks, featured image, category, tags, Polylang lang) | ✅ done |
| `list_custom_posts` (generic CPT reader) | ✅ done |
| **`delete_post`** (trash a post/page) | ✅ done |
| **`duplicate_post`** | ✅ done — common editorial workflow (clone a page as a template) |
| **`bulk_update_post_status`** (publish/draft/trash N posts at once) | ✅ done — same per-id independent-outcome pattern as WooCommerce bulk changes |
| **`get_post_revisions` / `restore_revision`** | ✅ done 2026-08-10 — restore has no native REST verb, implemented as read-revision(`context=edit`)-then-write-back via `update_post`'s existing path. Chat-tool only for now (no drill-down list-then-act UI pattern exists yet in panels.py). |
| **`set_post_password`** (password-protected post) | ✅ done 2026-08-10 — wired into the Posts/Pages panel UI as an expandable per-row form. |

### 1.2 Comments — ✅ moderation shipped 2026-08-09 (v1.9.0)
| Function | Status |
|---|---|
| `list_comments` | ✅ done (read-only) |
| **`set_comment_status`** (approve/hold/spam/trash — one parameterized function, matches the WP REST API's own single-field model) | ✅ done |
| **`reply_to_comment`** (create a comment as site admin) | ✅ done |
| **`edit_comment_content`** | ✅ done 2026-08-10 — wired into the Comments activity sub-tab as a second expandable form ("Edit comment text") alongside Reply, pre-filled with the current text. |

**Why this matters:** comment moderation is one of the most frequent daily WP admin tasks and is
currently 100% unsupported beyond viewing. This is Priority 1.

### 1.3 Users — ✅ shipped 2026-08-10
| Function | Status |
|---|---|
| `list_users` | ✅ done |
| **`create_user`** (role, email — WordPress emails the password reset link itself) | ✅ done |
| **`update_user`** (role change, email, display name) | ✅ done |
| **`delete_user`** (with reassign-content-to option) | ✅ done |
| **`reset_user_password`** (trigger WP's own reset-link email) | ✅ done 2026-08-10 — shipped via a new Imperal Bridge SECTION 6 (Users): `POST /imperal/v1/users/{id}/reset-password` calls WordPress's own `retrieve_password()` directly (bridge bumped to 2.3.0). Wired into the Users panel as a per-row action. |

**Why this mattered:** "add my new copywriter as an Author" is now a completely reasonable ask we
can do. Priority 2 — DONE.

### 1.4 Categories & Tags (native posts) — ✅ fully covered
`list_post_categories`, `list_post_tags`, `create_post_category`, `create_post_tag`,
`update_post_category`, `update_post_tag`, `delete_post_category`, `delete_post_tag` — all done,
including parent/child tree for categories.

### 1.5 Menus & Navigation — ✅ shipped 2026-08-10
| Function | Status |
|---|---|
| **`list_menus`** | ✅ done |
| **`list_menu_items`** | ✅ done |
| **`create_menu_item`** (link to post/page/custom URL, parent for dropdown) | ✅ done |
| **`update_menu_item`** (label, target, position) | ✅ done — panel-wired 2026-08-10 as a per-row expandable edit form on the Menus manage tab |
| **`delete_menu_item`** | ✅ done |
| **`reorder_menu_items`** | ✅ done |

**Why this mattered:** every time we `create_post`/`create_page`, the natural follow-up is "now put
it in the nav" — confirmed core `/wp/v2/menu-items` (WP 5.9+) was sufficient, no Bridge section
needed. Priority 3 — DONE.

### 1.6 Widgets & Site Editor blocks (FSE themes) — ❌ not planned
Widgets are largely obsolete under block themes (Full Site Editing). Not worth building against a
shrinking surface. Explicitly **out of scope** unless a real user need appears.

### 1.7 Site Settings — ✅ shipped 2026-08-10
| Function | Status |
|---|---|
| `get_site_health` | ✅ done (reachability, auth, SSL, content counts) |
| **`get_site_settings` / `update_site_settings`** (site title, tagline, timezone, date/time format) | ✅ done — native `/wp/v2/settings`, WP 5.5+, no SSH needed |
| **`list_plugins`** (via SSH/WP-CLI) | ✅ done |
| **`list_native_plugins` / `activate_plugin` / `deactivate_plugin`** | ✅ done — native `/wp/v2/plugins`, no SSH needed |
| **`list_themes`** | ✅ done — native `/wp/v2/themes` |
| **`activate_theme`** (switch the active theme) | ❌ still missing by design — no core REST route exists for this; would need a Bridge addition, deferred until real demand |

### 1.8 Media Library — ✅ covered for the write path we need
`upload_media` (sideload by URL), `check_media_support`, `update_media_alt`/`set_single_media_alt`
(alt text). ✅ done 2026-08-10 — the Media sub-tab was a plain read-only table despite full write
support already existing; it's now a list with an "Add image from URL" form and a per-row alt-text
form (missing alt flagged inline). Missing but low priority: **`delete_media`**, **`list_media`
filters by mime type** (already returns all, filtering client-side today is fine).

---

## Layer 2 — Rank Math SEO

### 2.1 Per-content SEO — ✅ covered
`get_seo_meta`, `update_seo_meta`, `get_term_seo_meta`, `update_term_seo_meta`,
`check_seo_support` — title, meta description, focus keyword, canonical URL. All via Bridge.

### 2.2 Site-wide SEO — ✅ FULLY COVERED 2026-08-10 — zero remaining gaps
| Function | Status |
|---|---|
| **`list_redirects` / `create_redirect` / `delete_redirect` / `set_redirect_status`** | ✅ done — Bridge SECTION 5 reads/writes Rank Math's own `{prefix}rank_math_redirections` table directly, since Rank Math never exposes this over REST |
| **`get_sitemap_status`** | ✅ done — Bridge SECTION 7, checks the `rank_math_modules` option (`Conditional::is_module_active()`'s own storage) for the Sitemap module and reports the sitemap index URL. No `trigger_sitemap_regenerate`: verified against Rank Math source that sitemaps are generated dynamically per-request (`Sitemap\Router`), never cached/stored — "regenerate" is not a real operation on this plugin, so it was deliberately NOT built (would have been fabricated). |
| **`get_robots_txt` / `update_robots_txt`** | ✅ done — Bridge SECTION 7, reads/writes the `robots_txt_content` key inside Rank Math's own `rank-math-options-general` option (`RankMath\Robots_Txt`'s own storage) — this is Rank Math's *override* text, not the raw file on disk |
| **`get_seo_analysis_score`** (Rank Math's own on-page content-analysis score for a post) | ✅ done — Bridge SECTION 7, reads the plain postmeta key `rank_math_seo_score` (`RankMath\Frontend_SEO_Score`'s own storage) |
| **404 Monitor (`list_404_hits` / `delete_404_hit`)** | ✅ done — Bridge SECTION 7, reads/deletes rows from Rank Math's own `{prefix}rank_math_404_logs` table (`RankMath\Monitor\DB`'s own storage). Bulk-clear-the-whole-log deliberately NOT exposed — no legitimate workflow needs to wipe 404 diagnostic history in one call with no way back. |
| **Schema/structured-data type per post** | ✅ already covered — the existing `rich_snippet` field on `get_seo_meta`/`update_seo_meta` IS Rank Math's per-post schema type picker (Article/Product/FAQ/etc., free text). No separate `get_schema_type`/`update_schema_type` needed; this roadmap entry was stale. |

**Why this mattered:** redirects were the single most requested SEO action after a URL/slug change
(Priority 4). The remaining site-wide items (sitemap/robots/score/404) were then explicitly
requested as "полностью покрыть функционал Rank Math" (Priority 13) — every fact above (table name,
column names, option name, postmeta key, module-check mechanism) was verified against the actual
seo-by-rank-math 1.0.275 plugin source before a single line of Bridge/handler code was written; see
Bridge SECTION 7's own header comment for the exact classes read. Wired into the site detail panel
as a new Manage > SEO sub-tab (sitemap status card, robots.txt editor form, 404 log list with a
per-row delete action); `get_seo_analysis_score` stays chat-tool-only since it is per-post like the
rest of §2.1 and none of that per-post SEO surface has panel UI yet either.

### 2.3 Instant Indexing (IndexNow) — ✅ FULLY COVERED 2026-08-10 night — the one real gap found on re-audit
| Function | Status |
|---|---|
| **`submit_urls_to_indexnow`** | ✅ done — POST `rankmath/v1/in/submitUrls` on Rank Math's OWN native REST controller (`RankMath\Instant_Indexing\Rest`), not the Imperal Bridge — this module hooks `rest_api_init` itself and needs no companion plugin at all |
| **`list_indexnow_log`** | ✅ done — POST `rankmath/v1/in/getLog`, filter all\|manual\|auto, reads the `rank_math_indexnow_log` WP option (last 100 entries, `RankMath\Instant_Indexing\Api::get_log()`'s own storage) |
| **`clear_indexnow_log`** | ✅ done — POST `rankmath/v1/in/clearLog`, deletes the same option |
| **`reset_indexnow_key`** | ✅ done — POST `rankmath/v1/in/resetKey`, regenerates the site's IndexNow verification key (`Api::reset_key()`) and returns the new key + its verification-file URL |

**Why this mattered:** found via the explicit re-audit request "перепроверь всю их документацию,
изучи их плагин... если найдешь что еще не покрыто - покрой" — re-checked the official module list
at rankmath.com/kb/advanced-mode/ and the real plugin source on plugins.svn.wordpress.org module by
module against our own coverage. Confirmed via `includes/class-installer.php`'s
`create_misc_options()` that Instant Indexing is ACTIVE BY DEFAULT on every fresh Rank Math install
(same default-`$modules` array as sitemap/seo-analysis), so this silently affected most connected
sites, not just ones that opted in. Architecturally distinct from every other Rank Math function in
this app: it talks straight to Rank Math's own REST namespace with the connected Application
Password, with NO Bridge plugin involved — verified route-by-route against
`includes/modules/instant-indexing/class-rest.php` before writing a line of Python. Wired into the
Manage > SEO sub-tab as its own card (submission log list, submit-URLs form, clear-log button).
Other candidate gaps investigated and deliberately NOT built: Database Tools' "Update SEO Scores"
bulk recompute (verified via `class-update-score.php` that it runs entirely client-side through a
bundled JS analyzer in wp-admin, with no PHP/REST/WP-CLI hook to call into — building this would
have meant fabricating a capability that doesn't exist server-side).

### 2.4 llms.txt (AI-crawler guidance file) — ✅ FULLY COVERED 2026-08-10 night — found on the SAME re-audit as §2.3
| Function | Status |
|---|---|
| **`get_llms_txt_settings`** | ✅ done — Imperal Bridge SECTION 8, GET `/imperal/v1/llmstxt`, reads `llms_post_types`/`llms_taxonomies`/`llms_limit`/`llms_extra_content` from the SAME `rank-math-options-general` option §2.2 already reads `robots_txt_content` from, plus whether the module is active and the file's live URL |
| **`update_llms_txt_settings`** | ✅ done — Imperal Bridge SECTION 8, POST `/imperal/v1/llmstxt`, partial-update (only fields present in the request are touched, same convention as per-post SEO in §2.1) |

**What it is:** Rank Math's `llms-txt` module (`RankMath\LLMS\LLMS_Txt`,
`includes/modules/llms/class-llms-txt.php`) serves a dynamic, Markdown-format `/llms.txt` file at
the site root via a rewrite rule + `template_redirect` — the AI-crawler analogue of robots.txt,
telling LLM crawlers which posts/pages/taxonomies matter most. It exposes NO REST API of its own
(unlike Instant Indexing) — its settings only exist as a WP option, so this had to go through the
Imperal Bridge (bumped to v2.5.0) rather than native REST, following §2.2's exact
get_option()/update_option() pattern. Confirmed via `includes/class-installer.php` that, UNLIKE
robots.txt/sitemap/seo-analysis, `llms-txt` is NOT in the default-active `$modules` array — so
`module_active` is reported honestly rather than assumed, and turning the module itself on/off is
left to Rank Math's own module-manager screen (no single-module REST toggle exists in the plugin to
build against). Wired into the Manage > SEO sub-tab as its own card — post types/taxonomies pulled
live from WordPress core's own `/wp/v2/types` and `/wp/v2/taxonomies` (never a hardcoded guess,
since custom post types vary per site), limit and extra-Markdown as plain form fields.

**Investigated on the same pass and deliberately NOT built — AI Visibility module:** Rank Math also
ships an `ai-visibility` module (`includes/modules/ai-visibility/`, active by default alongside
Instant Indexing) that DOES expose real REST routes (`/rankmath/v1/ai-visibility/overview`,
`/brands`, `/trial`, `/checkout`). Read its controllers before deciding: this module is a
cache-backed proxy to Rank Math's OWN paid SaaS backend — brand visibility tracking across AI
answer engines (ChatGPT etc.), gated behind a Rank Math account connection plus a trial/paid
subscription and Content AI credits it consumes from Rank Math's own servers, not from anything on
the WordPress site itself. Building this would mean reselling access to a third party's paid
subscription flow we don't control pricing, quota, or billing for — out of scope for a
site-management app, and a real fabrication risk if we guessed at behavior we can't verify without
paying for it ourselves. Correctly excluded, not a gap.

---

## Layer 3 — WooCommerce

### 3.1 Catalog — ✅ strong coverage
`list_products`, `get_product`, `create_product`, `update_product` (panel-wired 2026-08-10 as a
per-row edit form), `archive_product`,
`list_product_categories`, `create_product_category`, `list_product_variations`,
`create_product_variation`, `update_product_variation`, bulk change + CSV import/export for both
products and variations (preview-then-apply pattern with state tokens throughout).

### 3.2 Orders — ✅ good coverage, one real gap
| Function | Status |
|---|---|
| `list_orders`, `get_order`, `update_order_status`, `update_order_status_risky` | ✅ done |
| `apply_order_line_changes` (quantity changes, preview-gated) | ✅ done |
| `add_private_order_note`, `add_customer_order_note` | ✅ done |
| **`create_order`** (manual/phone order entry) | ✅ done — shipped 2026-08-10, Priority 8a |
| **`list_order_notes`** (read the note thread back, not just add) | ✅ done — shipped 2026-08-10, Priority 8a |
| **`resend_order_email`** (trigger WooCommerce's own "new order"/"invoice" email) | ✅ done 2026-08-10 — correction to the earlier note below: WooCommerce 9.8+ DOES expose a native `/orders/<id>/actions/send_order_details` (and `/actions/send_email` for a specific template) REST endpoint, no Bridge addition needed after all. Wired into the Orders panel UI. |

### 3.3 Customers — ✅ covered
`list_customers`, `get_customer`, `create_customer`, `update_customer` (panel-wired 2026-08-10),
`list_customer_orders`, **`delete_customer`** (shipped 2026-08-10, Priority 8a — permanent delete
with optional order reassignment via `?reassign=`, mirrors `delete_user`'s pattern; wired into the
Customers UI sub-tab with a destructive confirm gate, not just a chat-tool).

### 3.4 Coupons — ✅ covered
`list_coupons`, `create_coupon`, `update_coupon` (panel-wired 2026-08-10), `archive_coupon`.

### 3.5 Refunds — ✅ covered
`list_refunds`, `preview_refund`, `create_manual_refund` (does not touch the payment gateway, by
design — documented limitation, not a gap).

### 3.6 Reviews — ✅ shipped 2026-08-10
| Function | Status |
|---|---|
| **`list_product_reviews`** | ✅ done |
| **`set_product_review_status`** (approve/hold/spam/trash — one parameterized function, reused the comment-moderation plumbing from 1.2 since reviews are `comment_type=review`) | ✅ done |
| **`reply_to_product_review`** | ✅ done |

**Why this mattered:** reviews drive conversion; approving a stuck 5-star review or flagging spam
is now as easy as WooCommerce's own admin screen. Priority 5 — DONE.

### 3.7 Shipping & Tax — ❌ not currently planned
Shipping zones/methods and tax classes are typically set up once and rarely touched
programmatically. **Explicitly deferred** — revisit only if a real recurring need shows up (e.g. a
multi-store client asking to sync shipping rules).

### 3.8 Store-wide reporting — ✅ covered
`get_woocommerce_status`, `get_store_summary`.

---

## Layer 4 — Page Builders (Elementor / Bricks)

### 4.1 Current coverage — ✅ guarded point-edits
`check_builder_support`, `get_builder_content` (read the element tree),
`update_builder_field` (point-edit one field by element id, guarded/confirmed). This is a
deliberately narrow, safe surface — not a full visual editor.

### 4.2 Possible extensions — low priority, evaluate case by case
| Function | Status |
|---|---|
| **`duplicate_builder_element`** | ❌ not planned — real risk of corrupting a complex nested layout without a visual preview; would need strong guardrails first |
| **`list_builder_templates`** (saved Elementor/Bricks templates library) | ❌ not planned — nice-to-have only |

**Decision:** keep this layer narrow. A text-only agent editing a visual page builder's JSON tree
is inherently risky; expanding it should wait for explicit user demand plus a stronger preview/undo
story, not be built speculatively.

---

## Layer 5 — Imperal Bridge plugin & SSH/WP-CLI server layer

### 5.1 Bridge plugin (`imperal-bridge.php`) — sections today (v2.5.0, 8 sections)
SECTION 1 SEO (Rank Math per-post fields) · SECTION 2 Builder (Elementor/Bricks point-edits) ·
SECTION 3 Media (external-image sideload) · SECTION 4 Server (WP/PHP versions, updates, cron, DB
size) · SECTION 5 Redirects (Rank Math's own redirection table) · SECTION 6 Users (native
password-reset trigger) · SECTION 7 Rank Math site-wide (SEO score, robots.txt, sitemap status, 404
log) · SECTION 8 llms.txt (AI-crawler guidance file settings). Rule from CLAUDE.md: **future bridge
capabilities are new sections in this same file, never a new plugin.**

### 5.2 SSH / WP-CLI — ✅ fully covered
`add_ssh`, `remove_ssh`, `get_server_info`, `list_plugins`, `install_plugin`, `purge_cache`
(LiteSpeed-specific), **`update_plugin`** (ONE named plugin via `wp plugin update <slug>`, never
`--all`), **`update_core`** (`wp core update`, no version arg — always latest), **`run_wp_cron`**
(forces due cron events, no caller-chosen event name) — all shipped 2026-08-10, wired into the
Server section of the connected-site detail screen.
- **`get_database_size`** already returned by `get_server_info` per CLAUDE.md notes — no separate
  function needed.

### 5.3 Links / Sitemap — ✅ covered
`extract_links`, `check_sitemap_inclusion`.

---

## Priority order (what to actually build next, in sequence)

1. ✅ **Comment moderation** (1.2) — DONE 2026-08-09, v1.9.0. Shipped `set_comment_status`
   (approve/hold/spam/trash — one parameterized function, not four separate ones) and
   `reply_to_comment`. 14 new tests, full suite 370/370 passing, `imperal validate` clean (89
   functions, 0 errors/warnings).
2. ✅ **User management** (1.3) — DONE 2026-08-10. Shipped `create_user`, `update_user`,
   `delete_user` (with reassign-to option) via `handlers_users.py`. Same REST-wrapper pattern as
   posts; no Bridge changes needed (`/wp/v2/users` is core).
3. ✅ **Menus & navigation** (1.5) — DONE 2026-08-10. Shipped `list_menus`, `list_menu_items`,
   `create_menu_item`, `update_menu_item`, `delete_menu_item`, `reorder_menu_items` via
   `handlers_menus.py`. Confirmed core `/wp/v2/menu-items` (WP 5.9+) is sufficient — no Bridge work
   was needed.
4. ✅ **Redirects** (2.2) — DONE 2026-08-10. Shipped `list_redirects`, `create_redirect`,
   `delete_redirect`, `set_redirect_status` via `handlers_redirects.py`, backed by a new Bridge
   SECTION 5 (`imperal-bridge.php` v2.2.0) reading/writing Rank Math's own
   `{prefix}rank_math_redirections` table directly — Rank Math never exposes this over REST. The
   Bridge plugin zip was rebuilt; **still needs re-upload/update on live sites** to actually reach
   v2.2.0 there (see the open Bridge-outdated bug note for g4s.md / ksrenovationgroup.com, which are
   independently stuck on Bridge 2.0.0 — predates even the 2.1.0 server-info route).
5. ✅ **Product reviews** (3.6) — DONE 2026-08-10. Shipped `list_product_reviews`,
   `set_product_review_status`, `reply_to_product_review` via `handlers_reviews.py`, reusing the
   comment-moderation plumbing from #1 since WooCommerce reviews are `comment_type=review` under
   the hood.
6. ✅ **Post lifecycle gaps** (1.1) — DONE 2026-08-10. Shipped `delete_post`, `duplicate_post`,
   `bulk_update_post_status` via `handlers_post_lifecycle.py`.
7. ✅ **Site settings** (1.7) — DONE 2026-08-10. Shipped `get_site_settings`/`update_site_settings`,
   `list_native_plugins`/`activate_plugin`/`deactivate_plugin`, `list_themes` via
   `handlers_site_settings.py` — all native REST (`/wp/v2/settings`, `/wp/v2/plugins`,
   `/wp/v2/themes`, WP 5.5+), no SSH needed. Theme *switching* deliberately not implemented — no
   core REST route exists for it.
8. **Priority 8a — the real, recurring Orders/Customers gaps** — ✅ DONE 2026-08-10. Shipped
   `create_order` (manual/phone WooCommerce order entry, guest or registered customer, explicit
   line items, optional `set_paid`), `list_order_notes` (read the full private+customer-visible
   note thread on an order), and `delete_customer` (permanent delete with optional order
   reassignment, mirrors `delete_user`'s pattern) via `handlers_woocommerce_operations.py`.
   `delete_customer` wired into the Customers UI sub-tab with a destructive confirm gate;
   `create_order`/`list_order_notes` remain chat-tool-only for now (no established repeatable
   line-item-array form widget exists yet in `panels.py` — building one ad hoc for a single
   function risked a fragile one-off; revisit once a second multi-line-item UI need appears).
9. **Shipped 2026-08-10 (later session):** `get_post_revisions`/`restore_revision` (native
   `/wp/v2/<type>/<id>/revisions` list; restore has no native REST verb, implemented as
   read-with-`context=edit`-then-write-back via `update_post`), `set_post_password` (native
   `password` field, wired into the Posts/Pages panel UI as an expandable form). 120 functions
   total now.
10. **Shipped 2026-08-10 (even later session):** `resend_order_email` — turned out NOT to need a
   Bridge addition after all (WooCommerce 9.8+ has a native order-actions REST endpoint); the
   earlier deferral note above was simply wrong about that, corrected now that it shipped. Wired
   into the Orders panel UI. 121 functions total now.
11. **Shipped 2026-08-10 (later session still):** `reset_user_password` — new Bridge SECTION 6
   (Users), calls WordPress core's own `retrieve_password()` directly since core has no REST route
   for it (only the wp-login.php form does). Wired into the Users sub-tab as a per-row action.
   124 functions total now.
12. **Shipped 2026-08-10 (latest session):** `update_plugin`/`update_core`/`run_wp_cron` — closes
   §5.2, the last open SSH/WP-CLI gap. See CURRENT_WORK.md for the full writeup. 127 functions
   total now.
13. ✅ **Rank Math full site-wide coverage** (2.2) — DONE 2026-08-10, shipped on explicit user
   request ("давай полностью покроем функционал Rank Math"). New Bridge SECTION 7
   (`imperal-bridge.php` v2.4.0) + `handlers_rankmath.py` (6 functions): `get_seo_analysis_score`,
   `get_robots_txt`, `update_robots_txt`, `get_sitemap_status`, `list_404_hits`, `delete_404_hit`.
   Every DB table/option/postmeta key was verified against the real seo-by-rank-math 1.0.275 plugin
   source before writing any code (see SECTION 7's own header comment). No `trigger_sitemap_regenerate`
   was built — verified Rank Math generates sitemaps dynamically per-request with no stored state,
   so "regenerate" isn't a real operation on this plugin and building it would have been fabricated.
   Wired into the site detail panel as a new Manage > SEO sub-tab. 15 new handler tests + 2 new
   panel render-path tests, full suite 531/531 green, `imperal validate` 0 errors/0 warnings (133
   functions). Rank Math (Layer 2) is now the only layer in this whole document with zero
   remaining ❌ gaps.
14. ✅ **Instant Indexing / IndexNow** (2.3) — DONE 2026-08-10 night, found on an explicit re-audit
   request ("перепроверь всю их документацию, изучи их плагин... если найдешь что еще не покрыто -
   покрой") issued AFTER Priority 13 had already marked Rank Math "fully covered." Re-checking the
   real plugin source module-by-module turned up Instant Indexing — active by default, with its own
   REST namespace needing no Bridge at all. Shipped 4 functions in `handlers_indexnow.py`:
   `submit_urls_to_indexnow`, `list_indexnow_log`, `clear_indexnow_log`, `reset_indexnow_key`. 12 new
   handler tests + 3 new panel tests, full suite 545/545 green, `imperal validate` 0 errors/0
   warnings (137 functions). Wired into the Manage > SEO sub-tab.
15. ✅ **llms.txt** (2.4) — DONE 2026-08-10 night, found on the SAME re-audit as Priority 14 (module
   list at rankmath.com/kb/advanced-mode/ checked module-by-module against plugin source on
   plugins.svn.wordpress.org). Unlike Instant Indexing, this module exposes no REST API of its own —
   its 4 settings (`llms_post_types`/`llms_taxonomies`/`llms_limit`/`llms_extra_content`) live only
   as a WP option, so it needed a new Imperal Bridge SECTION 8 (`imperal-bridge.php` bumped to
   v2.5.0) mirroring §2.2's robots.txt get_option()/update_option() pattern exactly. Shipped
   `get_llms_txt_settings`/`update_llms_txt_settings` in `handlers_llmstxt.py`. Confirmed via
   `class-installer.php` that this module — unlike robots.txt/sitemap/Instant Indexing — is NOT
   active by default, so `module_active` is reported honestly rather than assumed. Post
   type/taxonomy pickers in the panel form are populated from WordPress core's own
   `/wp-json/wp/v2/types` and `/wp-json/wp/v2/taxonomies` discovery, never a hardcoded guess (custom
   post types vary per site). Same re-audit also surfaced Rank Math's newer `ai-visibility` module —
   investigated and deliberately excluded: it is a paid Rank Math SaaS brand-tracking proxy gated
   behind a separate account/subscription, not WordPress site data. 9 new handler tests + 2 new
   panel tests, full suite 556/556 green, `imperal validate` 0 errors/0 warnings (139 functions).
16. **Everything still explicitly deferred**: theme activation (1.7), 4.2 (builder extensions:
   duplicate element, template library), 3.7 (shipping/tax classes). Revisit only when a real,
   recurring user need appears. Do not build speculatively — matches this app's existing discipline
   (see WooCommerce module plan: "read-only first, add write only with explicit scope").

All of Priorities 2–7 above: 114 functions total (up from 87); Priority 8a adds 3 more (117
total); Priority 13 adds 6 more (133 total); Priority 14 adds 4 more (137 total); Priority 15 adds
2 more (139 total, current). Full pytest suite green (556/556) at every step, and every new function
priced via `developer.update_pricing` — the COMPLETE price map is always passed (never a partial
merge), verified against the live `@chat.function` name set after every pricing call so no function
is ever left unpriced or mispriced.

## Explicitly out of scope (documented so it isn't re-proposed later)

- Full block-theme Site Editor / widget management — obsolete surface, shrinking, not worth it.
- Full visual page-builder editing (drag/drop, layout structure changes) — `update_builder_field`
  point-edits are the deliberate ceiling for this app; a real visual editor is a different product.
- WooCommerce shipping zones / tax classes — one-time setup, not a recurring automatable need.
- Payment-gateway-touching refunds — `create_manual_refund` is WooCommerce-status-only by design
  (see existing tool description); actually moving money through a gateway is out of scope.

## Working rule for adding anything from this list

Same protocol as every past feature slice on this app (see `docs/2026-08-02-woocommerce-module-
plan.md` as the template): write a scoped plan doc for the slice, implement with tests
(`MockContext`, ≥1 test per `@chat.function`), run `imperal validate` + full pytest suite,
`imperal build` to regenerate the manifest, update `CURRENT_WORK.md`, commit, push, then
`developer.deploy_app` — and price new functions via `developer.update_pricing` per the pricing
note (`МЕТОД: как выставлять прайсинг по функциям приложения`), never `save_pricing`.
