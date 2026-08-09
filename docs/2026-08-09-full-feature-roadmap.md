# WordPress Hub — Full Feature Roadmap

Status: **canonical / living document — this is the master plan for what to build in this app.**
Date: 2026-08-09. Supersedes ad-hoc feature lists; update this file whenever scope changes.

## Purpose

WordPress Hub currently ships 87 functions covering sites, posts/pages, taxonomy, media, SEO
(Rank Math), page builders (Elementor/Bricks point-edits), WooCommerce, and SSH/WP-CLI server ops.
This document maps EVERY realistic capability across WordPress Core, WooCommerce, Rank Math, and
our own Bridge/SSH layer — what exists today, what's missing, and in what order to build it. Every
future "what should we add" conversation starts from this file, not from memory.

Coverage baseline verified against the actual codebase on 2026-08-09 (grep of all
`@chat.function`/`@ext.expose` decorators across `handlers_*.py` — 87 functions confirmed).

---

## Layer 1 — WordPress Core (native content & site management)

### 1.1 Posts & Pages — ✅ mostly covered
| Function | Status |
|---|---|
| `list_posts`, `list_pages`, `list_scheduled` | ✅ done |
| `create_post`, `update_post` (Gutenberg blocks, featured image, category, tags, Polylang lang) | ✅ done |
| `list_custom_posts` (generic CPT reader) | ✅ done |
| **`delete_post` / `archive_post` (trash a post/page)** | ❌ missing — WooCommerce has `archive_product`, native posts don't have the equivalent |
| **`duplicate_post`** | ❌ missing — common editorial workflow (clone a page as a template) |
| **`get_post_revisions` / `restore_revision`** | ❌ missing — recover from a bad edit without re-writing |
| **`set_post_password`** (password-protected post) | ❌ missing — low priority |
| **Bulk post status change** (publish/draft/trash N posts at once) | ❌ missing — same `apply_bulk_*` + preview pattern we already use for WooCommerce products |

### 1.2 Comments — ⚠️ read-only today, biggest real gap
| Function | Status |
|---|---|
| `list_comments` | ✅ done (read-only) |
| **`approve_comment` / `unapprove_comment`** | ❌ missing |
| **`mark_comment_spam`** | ❌ missing |
| **`trash_comment` / `delete_comment`** | ❌ missing |
| **`reply_to_comment`** (create a comment as site admin) | ❌ missing |
| **`edit_comment_content`** | ❌ missing (low priority) |

**Why this matters:** comment moderation is one of the most frequent daily WP admin tasks and is
currently 100% unsupported beyond viewing. This is Priority 1.

### 1.3 Users — ⚠️ read-only today
| Function | Status |
|---|---|
| `list_users` | ✅ done |
| **`create_user`** (role, email — WordPress emails the password reset link itself) | ❌ missing |
| **`update_user`** (role change, email, display name) | ❌ missing |
| **`delete_user`** (with reassign-content-to option) | ❌ missing |
| **`reset_user_password`** (trigger WP's own reset-link email) | ❌ missing |

**Why this matters:** "add my new copywriter as an Author" is a completely reasonable ask we can't
do today. Priority 2.

### 1.4 Categories & Tags (native posts) — ✅ fully covered
`list_post_categories`, `list_post_tags`, `create_post_category`, `create_post_tag`,
`update_post_category`, `update_post_tag`, `delete_post_category`, `delete_post_tag` — all done,
including parent/child tree for categories.

### 1.5 Menus & Navigation — ❌ entirely missing
| Function | Status |
|---|---|
| **`list_menus`** | ❌ missing |
| **`get_menu_items`** | ❌ missing |
| **`create_menu_item`** (link to post/page/custom URL, parent for dropdown) | ❌ missing |
| **`update_menu_item`** (label, target, position) | ❌ missing |
| **`delete_menu_item`** | ❌ missing |
| **`reorder_menu`** | ❌ missing |

**Why this matters:** every time we `create_post`/`create_page`, the natural follow-up is "now put
it in the nav" — and we currently have zero way to do that. Priority 3. Needs `wp-api-menus` or
core `/wp/v2/menu-items` (available since WP 5.9) — verify Bridge isn't needed for this one, core
REST may already expose it depending on WP version.

### 1.6 Widgets & Site Editor blocks (FSE themes) — ❌ not planned
Widgets are largely obsolete under block themes (Full Site Editing). Not worth building against a
shrinking surface. Explicitly **out of scope** unless a real user need appears.

### 1.7 Site Settings — ⚠️ partially covered via health/SEO
| Function | Status |
|---|---|
| `get_site_health` | ✅ done (reachability, auth, SSL, content counts) |
| **`get_site_settings` / `update_site_settings`** (site title, tagline, timezone, permalink structure) | ❌ missing — low-medium priority, rarely changed but occasionally needed after a migration |
| **`list_plugins`** (via SSH/WP-CLI) | ✅ done |
| **`activate_plugin` / `deactivate_plugin`** | ❌ missing — we can `install_plugin` but not toggle an existing one |
| **`list_themes` / `activate_theme`** | ❌ missing — low priority |

### 1.8 Media Library — ✅ covered for the write path we need
`upload_media` (sideload by URL), `check_media_support`. Missing but low priority:
**`delete_media`**, **`list_media` filters by mime type** (already returns all, filtering client-side
today is fine).

---

## Layer 2 — Rank Math SEO

### 2.1 Per-content SEO — ✅ covered
`get_seo_meta`, `update_seo_meta`, `get_term_seo_meta`, `update_term_seo_meta`,
`check_seo_support` — title, meta description, focus keyword, canonical URL. All via Bridge.

### 2.2 Site-wide SEO — ❌ entirely missing
| Function | Status |
|---|---|
| **`list_redirects` / `create_redirect` / `delete_redirect`** | ❌ missing — Rank Math's redirection manager has its own REST-adjacent surface; would need a small Bridge addition |
| **`get_sitemap_status` / `trigger_sitemap_regenerate`** | ❌ missing |
| **`get_robots_txt` / `update_robots_txt`** | ❌ missing (via Rank Math's robots editor, not the raw file) |
| **`get_seo_analysis_score`** (Rank Math's own on-page content-analysis score for a post) | ❌ missing — would need to read Rank Math's stored analysis meta, if exposed |
| **404 Monitor read (`list_404_hits`)** | ❌ missing — Rank Math logs real 404s; useful for `check_sitemap_inclusion` follow-ups |
| **Schema/structured-data type per post (`get_schema_type` / `update_schema_type`)** | ❌ missing — Rank Math lets you pick Article/Product/FAQ/etc. per post |

**Why this matters:** redirects are the single most requested SEO action after a URL/slug change,
and we currently have zero support. Priority 4 (right after Menus).

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
| **`create_order`** (manual/phone order entry) | ❌ missing — real gap for stores that take phone/in-person orders |
| **`list_order_notes`** (read the note thread back, not just add) | ❌ missing |
| **`resend_order_email`** (trigger WooCommerce's own "new order"/"invoice" email) | ❌ missing |

### 3.3 Customers — ✅ covered
`list_customers`, `get_customer`, `create_customer`, `update_customer`,
`list_customer_orders`. Missing: **`delete_customer`** (rare need, GDPR-adjacent — treat carefully
if ever built, likely needs an anonymize-not-delete pattern instead).

### 3.4 Coupons — ✅ covered
`list_coupons`, `create_coupon`, `update_coupon`, `archive_coupon`.

### 3.5 Refunds — ✅ covered
`list_refunds`, `preview_refund`, `create_manual_refund` (does not touch the payment gateway, by
design — documented limitation, not a gap).

### 3.6 Reviews — ❌ entirely missing
| Function | Status |
|---|---|
| **`list_product_reviews`** | ❌ missing |
| **`approve_review` / `trash_review`** | ❌ missing (product reviews are just comments with `comment_type=review` — likely shares plumbing with Layer 1.2 comment moderation once that's built) |
| **`respond_to_review`** | ❌ missing |

**Why this matters:** reviews drive conversion; approving a stuck 5-star review or flagging spam
should be as easy as WooCommerce's own admin screen. Natural pairing with comment moderation
(1.2) since the underlying WP object is the same. Priority 5.

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

1. **Comment moderation** (1.2) — `approve_comment`, `mark_comment_spam`, `trash_comment`,
   `reply_to_comment`. Highest daily-use value, zero coverage today, straightforward REST wrapper
   pattern identical to existing handlers.
2. **User management** (1.3) — `create_user`, `update_user`, `delete_user`. Same REST-wrapper
   pattern; no Bridge changes needed (`/wp/v2/users` is core).
3. **Menus & navigation** (1.5) — `list_menus`, `get_menu_items`, `create_menu_item`,
   `update_menu_item`, `delete_menu_item`, `reorder_menu`. Closes the loop on "I just created a
   page, now put it in the nav." Needs a version check: core `/wp/v2/menu-items` exists WP 5.9+;
   verify before assuming no Bridge work needed.
4. **Redirects** (2.2) — `list_redirects`, `create_redirect`, `delete_redirect`. Needs a new Bridge
   section (Rank Math redirects aren't core REST). Second-most-requested SEO action after per-post
   meta, which we already have.
5. **Product reviews** (3.6) — `list_product_reviews`, `approve_review`, `trash_review`,
   `respond_to_review`. Shares plumbing with #1 (reviews are `comment_type=review`) — build after
   comment moderation lands so the underlying helper can be reused, not duplicated.
6. **Post lifecycle gaps** (1.1) — `delete_post`/`archive_post`, bulk post status change (reuse the
   existing `apply_bulk_product_change`-style preview+token pattern), `duplicate_post`.
7. **Site settings** (1.7) — `get_site_settings`/`update_site_settings`, `activate_plugin`/
   `deactivate_plugin`. Lower frequency but rounds out "full site management."
8. **Everything explicitly deferred** (4.2, 3.7, plugin/core updates, revisions, reviews edit,
   theme switching) — revisit only when a real, recurring user need appears. Do not build
   speculatively — matches this app's existing discipline (see WooCommerce module plan: "read-only
   first, add write only with explicit scope").

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
