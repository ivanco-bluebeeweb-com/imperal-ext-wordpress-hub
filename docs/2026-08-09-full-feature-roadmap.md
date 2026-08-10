# WordPress Hub — Full Feature Roadmap

Status: **canonical / living document — this is the master plan for what to build in this app.**
Date: 2026-08-09, updated 2026-08-10. Supersedes ad-hoc feature lists; update this file whenever scope changes.

## Purpose

WordPress Hub now ships 117 functions covering sites, posts/pages (incl. delete/duplicate/bulk
status), taxonomy, media, SEO (Rank Math per-content + site-wide redirects), page builders
(Elementor/Bricks point-edits), WooCommerce (incl. product reviews, manual order entry, order note
thread, customer deletion), native user management, menus/navigation, site settings + native
plugin/theme listing, and SSH/WP-CLI + Bridge server ops. This document maps EVERY realistic
capability across WordPress Core, WooCommerce, Rank Math, and our own Bridge/SSH layer — what
exists today, what's missing, and in what order to build it. Every future "what should we add"
conversation starts from this file, not from memory.

Coverage baseline verified against the actual codebase on 2026-08-10 (grep of all
`@chat.function`/`@ext.expose` decorators across `handlers_*.py` — 117 functions confirmed, up from
87 on 2026-08-09 — Priorities 2 through 7 shipped 2026-08-10 morning, Priority 8a (create_order/
list_order_notes/delete_customer) shipped 2026-08-10 afternoon).

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
| **`edit_comment_content`** | ❌ missing (low priority — deferred) |

**Why this matters:** comment moderation is one of the most frequent daily WP admin tasks and is
currently 100% unsupported beyond viewing. This is Priority 1.

### 1.3 Users — ✅ shipped 2026-08-10
| Function | Status |
|---|---|
| `list_users` | ✅ done |
| **`create_user`** (role, email — WordPress emails the password reset link itself) | ✅ done |
| **`update_user`** (role change, email, display name) | ✅ done |
| **`delete_user`** (with reassign-content-to option) | ✅ done |
| **`reset_user_password`** (trigger WP's own reset-link email) | ❌ still missing — low priority, deferred (WordPress core has no REST trigger for this; would need a Bridge addition) |

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
| **`update_menu_item`** (label, target, position) | ✅ done |
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
`upload_media` (sideload by URL), `check_media_support`. Missing but low priority:
**`delete_media`**, **`list_media` filters by mime type** (already returns all, filtering client-side
today is fine).

---

## Layer 2 — Rank Math SEO

### 2.1 Per-content SEO — ✅ covered
`get_seo_meta`, `update_seo_meta`, `get_term_seo_meta`, `update_term_seo_meta`,
`check_seo_support` — title, meta description, focus keyword, canonical URL. All via Bridge.

### 2.2 Site-wide SEO — ⚠️ redirects shipped 2026-08-10, rest still missing
| Function | Status |
|---|---|
| **`list_redirects` / `create_redirect` / `delete_redirect` / `set_redirect_status`** | ✅ done — new Bridge SECTION 5 reads/writes Rank Math's own `{prefix}rank_math_redirections` table directly, since Rank Math never exposes this over REST |
| **`get_sitemap_status` / `trigger_sitemap_regenerate`** | ❌ missing |
| **`get_robots_txt` / `update_robots_txt`** | ❌ missing (via Rank Math's robots editor, not the raw file) |
| **`get_seo_analysis_score`** (Rank Math's own on-page content-analysis score for a post) | ❌ missing — would need to read Rank Math's stored analysis meta, if exposed |
| **404 Monitor read (`list_404_hits`)** | ❌ missing — Rank Math logs real 404s; useful for `check_sitemap_inclusion` follow-ups |
| **Schema/structured-data type per post (`get_schema_type` / `update_schema_type`)** | ❌ missing — Rank Math lets you pick Article/Product/FAQ/etc. per post |

**Why this mattered:** redirects were the single most requested SEO action after a URL/slug change.
Priority 4 — DONE for redirects; the sitemap/robots/score/404/schema items remain unbuilt and
unprioritized (no user demand yet).

---

## Layer 3 — WooCommerce

### 3.1 Catalog — ✅ strong coverage
`list_products`, `get_product`, `create_product`, `update_product`, `archive_product`,
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
`list_customers`, `get_customer`, `create_customer`, `update_customer`,
`list_customer_orders`, **`delete_customer`** (shipped 2026-08-10, Priority 8a — permanent delete
with optional order reassignment via `?reassign=`, mirrors `delete_user`'s pattern; wired into the
Customers UI sub-tab with a destructive confirm gate, not just a chat-tool).

### 3.4 Coupons — ✅ covered
`list_coupons`, `create_coupon`, `update_coupon`, `archive_coupon`.

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

### 5.1 Bridge plugin (`imperal-bridge.php`) — sections today
SEO (Rank Math fields) + Builder (Elementor/Bricks point-edits) + Media (sideload). Rule from
CLAUDE.md: **future bridge capabilities are new sections in this same file, never a new plugin.**
Menus (1.5) and Redirects (2.2) will likely need new Bridge sections if core REST doesn't already
expose them — verify per-feature before assuming a Bridge change is needed.

### 5.2 SSH / WP-CLI — ✅ covered, narrow scope by design
`add_ssh`, `remove_ssh`, `get_server_info`, `list_plugins`, `install_plugin`, `purge_cache`
(LiteSpeed-specific). Possible additions, low priority:
- **`update_plugin` / `update_core`** (WP-CLI has `wp plugin update`, `wp core update`) — real value
  for site maintenance, but higher blast radius than install; needs a strong preview/confirm story.
- **`run_wp_cron`** (trigger a stuck cron queue manually) — niche but occasionally useful for
  debugging a site that silently stopped sending emails.
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
11. **Everything still explicitly deferred**: reset_user_password, sitemap status/regenerate,
   robots.txt editor, SEO analysis score, 404 monitor, schema type per post, theme activation,
   4.2 (builder extensions), 3.7 (shipping/tax), plugin/core updates via
   WP-CLI. Revisit only when a real, recurring user need appears. Do not build speculatively —
   matches this app's existing discipline (see WooCommerce module plan: "read-only first, add
   write only with explicit scope").

All of Priorities 2–7 above: 114 functions total (up from 87); Priority 8a adds 3 more (117
total). Full pytest suite green (458/458) at every step, and every new function priced via
`developer.update_pricing` — merged into the existing price map each time rather than replacing
it, so no prior pricing was ever lost.

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
