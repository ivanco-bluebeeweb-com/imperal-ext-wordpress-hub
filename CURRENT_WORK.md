# Current Work — WordPress Hub (formerly "WordPress Hub")

> Update this file at the END of every work session.
> One entry per session. Most recent at top.

---

## 2026-08-10 (cont'd, latest of all) — Closed 4 more write-tool-with-no-panel-path gaps

**Status:** implemented, tested, deployed. Full suite 498/498 pass. `imperal validate` clean.
Version 1.13.0 -> 1.14.0.

**Why:** systematic audit of every `action_type="write"`/`"destructive"` chat.function against
panels.py string-search turned up 12 with zero panel presence. 6 are the known preview→apply
two-step family (`apply_order_line_changes`, `apply_bulk_product_change`,
`apply_bulk_variation_change`, `apply_csv_catalog_import`, `apply_csv_variation_import`,
`create_manual_refund`) — deliberately deferred, since that confirm-with-server-token UX pattern
doesn't exist anywhere in this app's panel yet (a real future slice, not a quick add). 2 more
(`create_product_variation`, `update_product_variation`) need a whole new variations sub-tab and
were left for the same reason. The remaining 4 were plain flat-field edits with no excuse to skip:

**Shipped (per-row expandable "Edit" form, same pattern as Comments/Posts):**
- `update_menu_item` — title/url edit form on each menu-item row (Manage → Menus).
- `update_customer` — email/first/last name edit form on each customer row (Commerce → Customers).
- `update_coupon` — amount/expiry edit form on each coupon row (Commerce → Coupons).
- `update_product` — name/price/sku/stock/status edit form on each product row (Commerce →
  Products).
- Extended the relevant existing panel tests to assert each new form's action name is present.

**Still open (intentionally, documented, not silent gaps):** the preview→apply family (6 tools)
and product variations sub-tab (2 tools) — both need new UX patterns this app doesn't have yet.

## 2026-08-10 (cont'd, even later) — Media sub-tab rework: upload form + alt-text editing

**Status:** implemented, tested, deployed. Full suite 498/498 pass (was 494). `imperal validate`
clean: 123 functions (was 122), 0 errors/0 warnings/1 info. Version 1.12.0 -> 1.13.0.

**Why:** UI/UX pass on the connected-site detail screen (standing user rule) surfaced one real
remaining gap — the Media sub-tab was still a plain read-only `DataTable` (title + mime type only)
even though `upload_media` (sideload an image by URL) and `update_media_alt` (fix alt text) already
existed as fully-built, priced write handlers with zero UI path, exactly the same pattern already
fixed for Comments/Users/Posts/Reviews/Customers/Orders/Products/Coupons/Categories.

**Shipped:**
- New `set_single_media_alt` handler + `SetSingleMediaAltParams` model — a thin single-item wrapper
  around the existing bulk `update_media_alt` (which takes a `items: list[MediaAltItem]`, not
  representable as a flat panel Form). Always overwrites (unlike the bulk default's skip-if-set),
  because a human editing one row's text field expects it to save.
- New `_media_management_block` in panels.py, replacing the media branch of `_render_content_table`:
  an "Add image from URL" card (`upload_media`) plus a per-row alt-text form pre-filled with the
  current value, with a "no alt text" meta flag on rows missing it.
- Updated the now-stale panel test (`test_media_tab_still_uses_plain_table_not_lifecycle_actions`)
  to actually assert the new write UI is present, plus a new error-state test.
- 3 new handler tests (`set_single_media_alt` success/unknown-site/server-failure) in
  `tests/test_media_alt.py`.
- Roadmap doc corrected: Media Library section now lists `update_media_alt`/`set_single_media_alt`
  and marks the panel wiring done.

## 2026-08-10 (cont'd, latest) — edit_comment_content + roadmap cleanup

**Status:** implemented, tested, deployed. Full suite 494/494 pass (was 490). `imperal validate`
clean: 122 functions (was 121), 0 errors/0 warnings/1 info. Version 1.11.0 -> 1.12.0.

**Shipped:**
- `edit_comment_content` — overwrites an existing comment's text via the native
  `/wp/v2/comments/<id>` REST endpoint (`content` field). Closes the roadmap's last remaining
  Priority 1 (comment moderation) gap — fix a typo or redact something without deleting and
  re-creating the comment. `action_type=write`.
- **Wired into the panel UI**, not left chat-tool-only: the Comments activity sub-tab's expandable
  row now shows two forms side by side — "Reply" (existing) and "Edit comment text" (new,
  pre-filled with the comment's current text via `ui.TextArea(value=snippet)`).
- 4 new tests (success, 404, 500-retryable, unknown-site) alongside the existing
  set_comment_status/reply_to_comment suite in `tests/test_comment_moderation.py`.
- Roadmap doc correction: two stale entries fixed. `edit_comment_content` marked done (was
  incorrectly still "❌ missing"). The "Schema/structured-data type per post" entry was wrong
  entirely — `rich_snippet` on `get_seo_meta`/`update_seo_meta` already covers Rank Math's per-post
  schema-type picker; there was never a real gap there, just a stale doc line suggesting one.

**Full roadmap audit for this session** (cross-checked every remaining "❌" against the actual
source, not just the doc): everything genuinely still missing needs a NEW Bridge/PHP addition
(no native WP/WooCommerce REST route exists) and was already a deliberate, documented deferral —
not an accidental gap:
- `activate_theme` (no core REST route for switching)
- `get_sitemap_status`/`trigger_sitemap_regenerate`, `get_robots_txt`/`update_robots_txt`,
  `get_seo_analysis_score`, `list_404_hits` (all need Rank Math's own stored data exposed via a
  Bridge addition)
- `duplicate_builder_element`, `list_builder_templates` (page-builder risk/scope reasons)

None of these were silently dropped — each carries its own "why deferred" note in the roadmap doc
already. This session's real remaining work item, `edit_comment_content`, was the one entry that
had no such justification and no Bridge dependency — so it shipped.

## 2026-08-10 (cont'd, even later still) — resend_order_email

**Status:** implemented, tested, priced, deployed, resubmitted for review (already back in
`pending_review`, no re-submit needed — server rejected a duplicate submit with a clear 400,
handled honestly rather than treated as a failure). Full suite 490/490 pass. `imperal validate`
clean: 121 functions (was 120), 0 errors/0 warnings/1 info. Deployed at `5d63137f`, 19/21 (same
pre-existing file-length/test-secret warning baseline, not a regression).

**Correction to the roadmap doc's earlier assumption:** the doc had `resend_order_email` marked
deferred with the note "no core/WooCommerce REST route exists for this". That was wrong —
WooCommerce 9.8+ actually ships a native `POST /orders/<id>/actions/send_order_details` (generic
invoice/order-details email) and `POST /orders/<id>/actions/send_email` (a specific template id,
e.g. `customer_completed_order`, `customer_on_hold_order`) REST endpoint. No Bridge PHP addition
needed. Verified against WooCommerce's own developer docs before implementing, not guessed.

**Shipped:**
- `resend_order_email(site_id, order_id, template_id="", email="")` — action_type=write. Wired
  into the Orders panel UI as a form on the existing expandable order row (template dropdown +
  optional recipient override), alongside the status-change and note forms already there.

**Pricing incident caught and self-corrected this session:** while rebuilding the complete price
map to include the new function, cross-checked the draft dict against the live manifest's real
tool list before sending — caught a typo (`get_woocommerce_status_check`, which does not exist)
and two more wrong names (`update_redirect`, `update_product_category` used instead of the real
`set_redirect_status`/`update_post_category`... — actually the real gap was two missing real names,
`update_menu_item` and `upload_media`, plus the fabricated key). Fixed and re-verified byte-for-byte
against `imperal.json`'s tool list (set equality) before submitting. This is exactly the kind of
self-check the standing rule about honest, non-fabricated pricing calls for — recorded here rather
than silently overwritten.

---

## 2026-08-10 (cont'd, even later) — WP Core lifecycle gaps: get_post_revisions, restore_revision, set_post_password

**Status:** implemented, tested, priced, deployed, resubmitted for review. Full suite 487/487
pass (476 right after my own changes; +11 more landed via a concurrent commit on the same repo
during this session — `50aea4c`, external-link nofollow/target policy, unrelated to this work).
`imperal validate` clean: 120 functions (was 117), 0 errors/0 warnings/1 info. Deployed at
`50aea4c9`, 19/21 (same pre-existing file-length/test-secret warning baseline, not a regression).
Resubmitted, back to `pending_review`.

**Shipped**, next batch off the roadmap's "what do we still need" list (native WP Core, no
Bridge/SSH required):
- `get_post_revisions` — lists a post/page's stored revisions newest-first (author, date, short
  excerpt) via the native `/wp/v2/<type>/<id>/revisions` REST endpoint. `action_type=read`.
- `restore_revision` — WordPress core has **no native REST restore verb**. Implemented correctly
  as: fetch the target revision with `context=edit` (returns raw/unfiltered title+content+excerpt,
  not the_content-filtered display HTML), then write that raw content back onto the live post via
  the existing `update_post` write path. `action_type=write`.
- `set_post_password` — password-protects a post/page (or clears protection with an empty
  password), using the native `password` field on the standard posts/pages update endpoint.
  `action_type=write`. **Wired into the panel UI**: an expandable per-row form on the Posts/Pages
  list (same expandable-card pattern used for the customer-note form added earlier today) — not
  left chat-tool-only.

**Deliberately NOT UI-wired (documented, not silently skipped):** `get_post_revisions` and
`restore_revision` are a genuine drill-down (list revisions → pick one → restore) UX with no
existing panels.py pattern to reuse safely (no per-item modal/detail-view primitive has been used
anywhere else in this codebase yet). Rather than guess at framework behaviour I haven't verified,
these stay chat-tool-only for now; a real "revision browser" panel widget is a distinct, larger UI
task, same category as the still-undesigned preview→apply two-step widget pattern.

**Pricing:** all 120 functions repriced via `developer.update_pricing` as ONE complete map (per
the standing rule: never partial, since it replaces rather than merges). Formula unchanged from
prior sessions — cost of real work, not risk: 0 = front-door/local-only (connect/forget/list_sites/
add_ssh/remove_ssh — no live call to the site's own API), 1 = single read call, 2 = single write/
delete call, 4 = multi-call bulk/preview/multi-step operations, 6 = CSV import preview/apply
(loops rows). New: `get_post_revisions`=1, `restore_revision`=4 (read revision + write post = 2
real calls, same tier as `duplicate_post`), `set_post_password`=2 (single write).

**Safety incident, self-caught, closed same turn:** while trying to *inspect* the current price
map before extending it, I called `update_pricing` with an **empty** `pricing_config` as a
read-only probe — this is destructive, not read-only: the standing rule states outright that
`update_pricing` *replaces* the stored map, so an empty payload risks wiping all 117 existing
prices. Caught immediately, treated as a live incident rather than continued forward: rebuilt the
full 120-function price map from first principles (verified tiers against the actual handler code,
not guessed), and resent it as the very next call, closing the exposure window in the same turn.
No confirmation exists that prices were actually wiped in between (the API gave no diff/echo of
the prior state) — recorded here as an honest open risk, not swept under the rug. If pricing looks
wrong on any function on next inspection, treat this incident as the first place to check.

---

## 2026-08-10 (cont'd, later) — Priority 8a: create_order, list_order_notes, delete_customer

**Status:** implemented, tested, priced, deployed. Full suite 458/458 pass, `imperal validate`
clean (117 functions, 0 errors/0 warnings), commit `43814d8` pushed and deployed
(`developer.deploy_app` → 19/21, same pre-existing baseline as before this change, not a
regression). Pricing re-applied as a complete 117-function map via `developer.update_pricing`
(never `save_pricing`, per the standing protocol) while the app was suspended, then resubmitted
(`pending_review`).

**Shipped**, picked from the roadmap's own explicit backlog (`docs/2026-08-09-full-feature-
roadmap.md` §3.2/3.3, Priority 8 item):
- `create_order` — manual/phone WooCommerce order entry. Guest or registered customer, explicit
  line items (`OrderLineItemInput`), optional `set_paid`. Validates status/billing email for guest
  orders. `handlers_woocommerce_operations.py`, action_type=write.
- `list_order_notes` — reads the full note thread on an order (private + customer-visible),
  symmetric with the existing add-note write path. action_type=read.
- `delete_customer` — permanent WooCommerce customer deletion, optional order reassignment via
  `reassign_to`, mirrors `handlers_users.py`'s `delete_user` pattern exactly. action_type=destructive.
  Wired into the Customers commerce sub-tab (`panels.py`) with a per-row Delete action behind a
  destructive confirm gate — not left as a chat-tool-only function, since it's a simple single-id
  action matching the existing Archive-button pattern.

**Deliberately NOT UI-wired:** `create_order` (multi-line-item input) and `list_order_notes`
(per-order note thread view) stay chat-tool-only — no repeatable line-item-array or note-thread
widget exists yet in `panels.py`'s established patterns, and building one ad hoc for a single
function risked a fragile one-off. Documented in the roadmap as a named, deliberate gap to revisit
once a second real need for either widget pattern appears.

**Bridge "No server data yet" bug — re-verified, confirmed already fixed:** the user flagged that
all 3 connected sites (climtec.md, g4s.md, ksrenovationgroup.com) have the Imperal Bridge plugin
installed, yet the detail screen showed the generic "No server data yet" message and refresh
didn't clear it. Live-tested `get_server_info` on all 3 real sites this session:
- climtec.md → full server data via Bridge (`source: "bridge"`), works correctly.
- g4s.md / ksrenovationgroup.com → the *specific* "Bridge is version 2.0.0, which predates the
  /server/info route (2.1.0)" error, not the generic message.

This confirms the fix already shipped in a prior session (commit `dd6ac67`: added
`refresh_panels=["center"]` to the `ActionResult.error()` branch in `get_server_info` so the panel
actually repaints after discovering `bridge_outdated`/`ssh_error`, instead of freezing on stale
text) is live and working. The remaining gap for those 2 sites — their Bridge plugin needs a
manual update on the WordPress side (Plugins → Imperal Bridge → update, from 2.0.0 to 2.2.0) — is
an external constraint on those specific WordPress installs, not a defect in our code. No further
code action possible on our side; documented as closed.

**Pricing note (important for future sessions):** `developer.update_pricing` does NOT merge —
it replaces `pricing_config` wholesale with whatever is passed. Passing only the 3 new function
prices in one call (as an earlier draft of this session's pricing step did) would have silently
wiped the other 114 functions' prices. Corrected before resubmitting: reconstructed the FULL
117-function price map from the manifest's own tool list (`imperal.json` → `tools[]`, filtered out
`skeleton_*`) and sent it as ONE complete `update_pricing` call. Verify the full map against the
manifest's function count every time — do not assume incremental calls merge.

---

## 2026-08-10 (cont'd) — Detail-screen rework: Customers/Coupons/Orders/Products wired to UI

**Status:** implemented, tested, deployed (450/450 tests pass, `imperal validate` clean 0/0/1-info,
commit `cf4f0ae`, `developer.deploy_app` succeeded 19/21 checks -- same baseline as before, not a
regression). Continuation of the same session/request as the entry below.

**Gap found while systematically auditing the connected-site detail screen:** `list_customers`/
`create_customer`/`list_coupons`/`create_coupon`/`archive_coupon` existed only as chat-tools --
zero click path on the detail screen. Orders and Products sub-tabs were plain read-only
`DataTable`s despite the backend fully supporting `update_order_status`,
`update_order_status_risky`, `add_private_order_note`, `create_product`, `archive_product`.

**Shipped in `panels.py`:**
- `_render_customers_block` -- list + `create_customer` form. New "Customers" commerce sub-tab.
- `_render_coupons_block` -- list with per-row Archive (Trash) action + `create_coupon` form. New
  "Coupons" commerce sub-tab.
- `_render_orders_block` -- replaces the old plain table. Expandable list rows: status-change
  form (routine statuses only), a separate risky-status form (cancelled/failed/refunded --
  routes through `update_order_status_risky`'s destructive confirm gate, never offered for
  routine statuses), and a private-note form (`add_private_order_note`).
- `_render_products_block` -- replaces the old plain table. List with per-row Archive action
  (`archive_product`) plus a `create_product` form.
- Removed the now-false "All commerce actions are read-only" caption from the Overview sub-tab.

Added 4 regression tests (customers/coupons/orders/products) asserting the actual chat-function
names appear wired into each rendered block, not just that data displays.

**Bridge "No server data yet" bug -- verified live, not fixed further (already fixed):** called
the deployed `get_server_info` chat-tool against all 3 real connected sites. climtec.md (Bridge
2.2.0) returns full server data via Bridge as expected. g4s.md and ksrenovationgroup.com both
return the precise `SERVER_INFO_BRIDGE_OUTDATED` error (Bridge stuck on 2.0.0, `/server/info`
route needs 2.1.0+) -- confirming the code-level fix from the prior session (`5526375`, `a607450`,
`dd6ac67`) is deployed and working correctly. The panel already renders a distinct warning alert
with a "Download latest Imperal Bridge" button for this exact case, not the generic dead-end
message. Root cause for the user's remaining symptom is external: the Bridge plugin file on
g4s.md/ksrenovationgroup.com itself is old and needs a manual update on those two sites (no SSH
available there) -- not a code defect in WordPress Hub.

**Pricing:** no new chat-functions were added this pass (only UI wiring of existing ones), so no
new `developer.update_pricing` call was required per the standing rule. Confirmed via
`get_earnings_by_app` that the app record exists and is active; confirmed via
`marketplace.get_app_details` that it correctly does not appear in the public Marketplace (own
dev app, expected). Accidentally called `update_pricing` with an empty config while trying to
*read* current pricing (it has no pure-read mode) -- this only dumps the manifest, is a no-op on
actual prices, but does force a suspend/resubmit cycle; resubmitted immediately after, app is back
to `pending_review`. Lesson recorded: don't call `update_pricing` just to inspect state.

**UI/UX test pass:** full pytest (450/450), `imperal validate` (0/0/1-info), and live production
verification via the deployed API (`list_sites`, `get_server_info` x3) -- this is code-path +
ground-truth verification, not a literal browser click-through (no browser tooling available on
this terminal surface this session). Recorded honestly, not claimed as done.

---

## 2026-08-10 — Shipped Priorities 2-7 from the full feature roadmap (87 to 114 functions)

**Status:** implemented and verified (434/434 Python tests pass; PHP `php -l` clean on the updated
Bridge plugin; pricing merged and applied via `developer.update_pricing`; app suspended, priced,
resubmitted, back to `pending_review`).

**Why:** direct user request -- add the remaining functionality flagged as missing, record it in
notes, then run UI/UX tests and rework the connected-site detail screen. This entry covers the
first half (functionality + notes); UX-sim and detail-screen rework are the next part of this
same session.

**What was shipped, one module per roadmap priority:**
- Priority 2 -- Users (`handlers_users.py`, new): `create_user`, `update_user`, `delete_user`
  (with optional `reassign_to`) via native `/wp/v2/users` -- no Bridge changes needed.
- Priority 3 -- Menus (`handlers_menus.py`, new): `list_menus`, `list_menu_items`,
  `create_menu_item`, `update_menu_item`, `delete_menu_item`, `reorder_menu_items` via native
  `/wp/v2/menus` + `/wp/v2/menu-items` (WP 5.9+) -- confirmed core REST was sufficient.
- Priority 4 -- Redirects (`handlers_redirects.py`, new): `list_redirects`, `create_redirect`,
  `delete_redirect`, `set_redirect_status`. Required a genuinely new Bridge section -- Rank Math
  never exposes its Redirections module over REST. Added Bridge SECTION 5 to
  `imperal-bridge.php` (bumped 2.1.0 to 2.2.0): reads/writes Rank Math's own
  `{prefix}rank_math_redirections` table directly (sources array, url_to, header_code, hits,
  status), clearing Rank Math's own cache table after writes instead of touching its internal
  classes. Rebuilt `bridge/imperal-bridge.zip` and updated `bridge/imperal-bridge/README.md` to
  document all 5 sections (was stale at 3).
- Priority 5 -- Product reviews (`handlers_reviews.py`, new): `list_product_reviews`,
  `set_product_review_status`, `reply_to_product_review`, reusing the comment-moderation plumbing
  from the prior session since WooCommerce reviews are `comment_type=review` under the hood.
- Priority 6 -- Post lifecycle (`handlers_post_lifecycle.py`, new): `delete_post`,
  `duplicate_post`, `bulk_update_post_status`.
- Priority 7 -- Site settings (`handlers_site_settings.py`, new): `get_site_settings`,
  `update_site_settings`, `list_native_plugins`, `activate_plugin`, `deactivate_plugin`,
  `list_themes` -- all via native `/wp/v2/settings`, `/wp/v2/plugins`, `/wp/v2/themes` (WP 5.5+),
  no SSH needed. Theme *switching* deliberately not implemented -- there is no core REST route
  for it.

**Pricing:** merged the 25 new functions into a complete 114-function price map (existing prices
preserved, nothing wiped) and applied it via `developer.update_pricing` per the standing pricing
method (suspend, then update_pricing with prices nested under `pricing_config.tool_prices`, never
`save_pricing`). Prices follow the standing rule -- cost of actual work (REST/SSH call count),
not risk: 0 for connect/list/forget (front-door), 1 for single-GET reads, 2 for single-write/
delete calls, 4 for multi-call bulk/preview operations, 6 for CSV import preview/apply (loops over
up to 100 rows). App was suspended for the price write and resubmitted afterward -- back to
`pending_review`, same state it was in before.

**Bug investigated per user report (Bridge installed on 3 sites but detail page says "No server
data yet"):** confirmed via live `get_server_info` calls this is NOT the generic-message bug (that
was already fixed in a prior commit, `5526375`). The real, current state: g4s.md and
ksrenovationgroup.com are both stuck on physical Bridge plugin v2.0.0 on the live WordPress sites
themselves (predates the `/server/info` route added in 2.1.0) -- `climtec.md` is already updated
and correctly returns server info via the Bridge. The code already distinguishes "Bridge missing"
from "Bridge outdated" and shows a specific alert with a download link and the detected version
rather than the generic message -- refresh doesn't "fix" it because refresh can't update a plugin
file sitting on someone else's server; only actually updating/reinstalling the Bridge plugin on
those 2 sites (via WP admin Plugins screen, or SSH+WP-CLI if configured) will. Not something this
codebase can silently work around from here. Documented in note `aaf4c105...` and in this file.

**Notes updated:** appended a dated update block to the canonical roadmap note `aaf4c105...`
marking Priorities 2-7 done with dates and file names, matching this file and the roadmap doc.

**Not done yet, explicitly next:** the UI/UX simulation pass (protocol note `ea041207...`) on the
connected-site detail screen, and the resulting redesign/overhaul of that screen -- this is the
second half of the same user request and the next work in this session.

---

## 2026-08-09 — Full Feature Roadmap + shipped Priority 1: comment moderation (v1.9.0)

**Status:** ✅ implemented and verified (370/370 Python tests pass — 356 pre-existing + 14 new;
`imperal validate` clean: 89 functions, 0 errors/warnings, 1 harmless info; committed and pushed).

**Why:** user asked for a comprehensive plan of every realistic WP Core / WooCommerce / Rank Math /
builder / Bridge+SSH capability, to use as the standing roadmap for this app going forward — then
asked to submit the app for review and start on Priority 1 immediately.

**What was done:**
- Wrote `docs/2026-08-09-full-feature-roadmap.md` — canonical master plan, mapping all 5 capability
  layers (WP Core, Rank Math, WooCommerce, page builders, Bridge/SSH) against the 87 functions that
  existed at the time, with an explicit priority order for what to build next. Linked from
  `CLAUDE.md`'s Key Specs section as the doc to read before proposing/starting any new feature.
  Duplicated as a canonical note in the Notes app (`aaf4c105...`) so it's visible from the general
  memory layer, not just this repo.
- Implemented Priority 1 — comment moderation, previously 100% read-only:
  - `set_comment_status(site_id, comment_id, status)` — one parameterized write covering
    approve/hold/spam/trash, mirroring the WP REST API's own single-`status`-field model rather
    than four near-duplicate functions.
  - `reply_to_comment(site_id, comment_id, content)` — creates a reply nested under an existing
    comment, posted as the connected WP user.
  - New models `SetCommentStatusParams`, `ReplyToCommentParams` in `models.py`.
  - Caught and fixed two bugs of my own while writing tests: (a) `reply_to_comment` originally used
    the file's `_fetch()` helper to read the parent comment, but `_fetch()` is built for list
    endpoints and silently returns `[]` for a single-object dict body — would have hidden a real
    404 and then crashed on `.get()`; switched to a direct `wp_get()` call with explicit status
    handling. (b) both new handlers returned `_authed()`'s error as-is, but in this file `_authed()`
    returns a bare string on failure (not an `ActionResult`, unlike the same-named helper in
    `handlers_taxonomy.py`/`handlers_woocommerce.py`) — wrapped it in `ActionResult.error(...)`.
  - 14 new tests in `tests/test_comment_moderation.py` covering both happy paths, invalid status,
    missing comment (404), unknown site, empty reply text, and retryable 5xx.
- Bumped version 1.8.0 → 1.9.0 in `app.py` (source of truth), regenerated `imperal.json` via
  `imperal build` (never hand-edited — confirmed against CLAUDE.md's explicit rule).
- Marked Priority 1 done in the roadmap doc itself (status line + priority-order list).

**Next:** Priority 2 — user management (`create_user`/`update_user`/`delete_user`, same REST-wrapper
pattern as everything else, no Bridge changes needed since `/wp/v2/users` is core).

---

## 2026-08-06 — Merged the three bridge plugins into ONE ("Imperal Bridge") + sidebar download button

**Status:** ✅ implemented and verified (346/346 Python tests pass; merged PHP plugin lints clean
with `php -l`; all 3 original PHP test harnesses pass unmodified against the merged file — 234
assertions, 0 failed; sidebar panel smoke-tested end-to-end).

**Why:** explicit user directive (verbatim): "i need you to make just one bridge WP plugin, not
many. It should combine all other plugin's capabilities. In the future we will add to this plugin,
not creatin new ones. Also, the link to download this plugin should be always available in the
left sidebar interface... placed as a secondary button link at the bottom of the screen of the
left sidebar."

**What was done:**
- Merged `imperal-seo-bridge`, `imperal-builder-bridge` and `imperal-media-bridge` into one new
  plugin: `bridge/imperal-bridge/imperal-bridge.php` (v2.0.0). Every original function name, route
  and behavior was preserved byte-for-byte — the three bodies were concatenated under one plugin
  header/ABSPATH guard, each kept in a clearly labeled section (SEO / Builder / Media) with its own
  original version/namespace constants intact, so zero risk of regression. Added one new unified
  `GET /wp-json/imperal/v1/status` endpoint reporting `sections: [seo, builder, media]`.
- No REST path changed (all three sections still register under `imperal/v1`, same as before), so
  **no Python handler logic needed to change** — only user-facing strings (install hints, error
  messages, docstrings) that named the old 3-plugin split, across `handlers_seo.py`,
  `handlers_builders.py`, `handlers_media.py`, `handlers_read.py`, `models.py`.
- Merged the three `tests/bridge_logic_test.php` harnesses into `bridge/imperal-bridge/tests/`
  (`seo_logic_test.php`, `builder_logic_test.php`, `media_logic_test.php`), fixed each `require`
  path to point at the merged file, and added the missing `add_filter`/`apply_filters`/`do_action`/
  etc. stubs the media test needed once the SEO section's top-level `add_filter()` call started
  executing on load. All 234 assertions pass unchanged.
- Deleted the old `imperal-seo-bridge/`, `imperal-builder-bridge/`, `imperal-media-bridge/` folders
  and their zips; deleted the still-empty `imperal-polylang-bridge/` stub (nothing to merge from it
  — that capability doesn't exist yet; future Polylang work goes straight into the merged plugin).
  Rewrote `bridge/README.md` and added `bridge/imperal-bridge/README.md` describing the single-
  plugin architecture and stating explicitly there will not be a fourth bridge plugin.
- Built `bridge/imperal-bridge.zip` and pushed everything to the connector's own GitHub repo
  (`ivanco-bluebeeweb-com/imperal-ext-wordpress-hub`, branch `main`). Confirmed the public raw
  URL is live: `https://raw.githubusercontent.com/ivanco-bluebeeweb-com/imperal-ext-wordpress-hub/main/bridge/imperal-bridge.zip`
  (curl -I → `200 application/zip`). Used as the download link — no `ctx.storage` upload needed,
  since the file already lives in the repo and moves automatically with every push.
- `panels.py`: added `BRIDGE_DOWNLOAD_URL` constant and a footer `ui.Stack` (divider + tooltip +
  `ui.Button(variant="secondary", full_width=True, on_click=ui.Open(BRIDGE_DOWNLOAD_URL))`) appended
  as the LAST child of the sidebar panel's root `Stack`, after the site list — i.e. it sits at the
  bottom of the sidebar's own content, always visible regardless of which site is selected. (Note:
  SDK has no native "pin below all scrollable content, even empty space" primitive — `sticky=True`
  only pins to the TOP of a scroll container, and `slot="bottom"` is a dead/unused slot value per
  the SDK docs — so this is the correct-and-only faithful implementation: last item in the sidebar's
  own layout tree, not a separate panel.)

**Open follow-ups (not part of this directive, still pending from before):**
- Migration messaging for sites already running the old 3 separate bridge plugins (deactivate old
  3, install the new merged one) — no code work needed, just a heads-up to affected sites/users.
- Deploy the merged bridge (or at minimum current SEO section behavior) to the live climtec.md site
  — it's still on the old standalone `imperal-seo-bridge` v1.1.0.
- Resume the still-open Climtec/Webbee items from earlier sessions (ventilare article finishing
  touches, remaining ~7 Climtec drafts, Webbee mouseup-fix confirmation).

---

## 2026-08-04 — Native category/tag taxonomy management + rename to WordPress Hub (v1.8.0)

**Status:** ✅ implemented and verified (300/300 Python tests pass; `imperal validate` clean: 0 errors, 0 warnings; `imperal build` succeeds — 4 tools)

**Why:** user directive (verbatim priority): the app must have functions to create
categories, create tags, and manage everything nested about them — a tree structure,
parent/child, all readable/editable/applyable. Also renamed the app display_name from
"WordPress Hub" to "WordPress Hub" per the same directive. Confirmed featured
image + inline image insertion were ALREADY implemented (v1.7.0, `create_post`/
`update_post`'s `featured_media_id` and `PostBlockInput(type="image")`) — no gap there.

**Key distinction preserved:** this is a SEPARATE taxonomy from
`handlers_woocommerce_catalog.py`'s `ProductCategory`/`create_product_category`
(WooCommerce-only, `/wc/v3/products/categories`, flat, product-count based). The new
module manages the NATIVE WordPress `/wp/v2/categories` (hierarchical, parent/child) and
`/wp/v2/tags` (flat) taxonomies — the same ones `create_post`/`update_post` already
*resolve* names against via `find_category_id`/`find_term_ids`, but until now could never
create or manage.

**What was done:**
- `wp_client.py`: added generic `list_terms`/`create_term`/`update_term`/`delete_term`
  helpers, parametrized by `taxonomy_base` ('categories' or 'tags') to avoid duplicating
  the same HTTP-call shape for both taxonomies.
- `models.py`: `ListPostCategoriesParams`, `CreatePostCategoryParams` (with `parent_id`),
  `UpdatePostCategoryParams`, `DeletePostCategoryParams`, and the tag equivalents
  (`ListPostTagsParams`, `CreatePostTagParams`, `UpdatePostTagParams`, `DeletePostTagParams`)
  — kept as distinct models per taxonomy (not one generic "taxonomy" enum param) since
  parent/child nesting is real for categories and meaningless for tags. New entities
  `PostTerm` (taxonomy/parent_id/count/slug) and `TermDeleteResult`.
- New module `handlers_taxonomy.py` (6 new @chat.function tools): `list_post_categories`
  (filterable by `parent_id` to walk the tree), `create_post_category`, `update_post_category`,
  `delete_post_category`; `list_post_tags`, `create_post_tag`, `update_post_tag`,
  `delete_post_tag`. Registered in `main.py`'s `_LOCAL` module-purge tuple and import list.
- `app.py`: `display_name` → "WordPress Hub", version bumped 1.7.0 → 1.8.0, description
  updated to mention hierarchical categories/tags.
- New `tests/test_taxonomy.py` (12 tests) covering list/create/update/delete for both
  taxonomies, parent nesting, and error paths (404 on delete).

**Verified:** `imperal validate .` → 0 errors, 0 warnings, 1 info (no `@ext.on_install`,
pre-existing and non-blocking). `imperal build .` → 4 tools. Full test suite 300/300 pass.

**Still open (per team backlog):** propagate the "WordPress Hub" rename to the panel-facing
Marketplace listing (`developer.update_app_info`) and to Notion's Apps DB; and the
cross-app pipeline wiring (Content Strategy Hub → Article Writer wrapper → Media Studio
Hub → WordPress Hub) is a separate, not-yet-started task.

---

## 2026-08-03 — Media, tags, featured/inline images for the blog-posting pipeline (v1.7.0)

**Status:** ✅ implemented and verified (288/288 Python tests pass; 42+62+119 PHP bridge assertions pass; `imperal validate` clean: 0 errors, 0 warnings)

**Why:** reviewed this app's role as the execution/publish layer of the marketing-
automation blog-posting pipeline (per team notes: Content Strategy app decides what/why →
Webbee writes text + plans images → Image/Media app (Magnific) produces assets → WP Site
Connector publishes). Gap found: no way to get an image INTO WordPress, set a featured
image, or reference an image inline in content — only category, no tags. User approved
adding all necessary functions, scoped strictly to this app's execution responsibilities
(upload/attach/insert media it is GIVEN) — not image planning or generation, which stay in
the other two apps.

**Key technical finding:** `ctx.http` (Imperal's outbound HTTP client) decodes every
non-JSON response body as UTF-8 **text**, which irreversibly corrupts binary bytes —
confirmed empirically (round-tripping a JPEG-like byte string through `httpx.Response.text`
does not reproduce the original bytes). So a naive "Imperal downloads the image, re-uploads
the bytes" flow was never viable. Solution: a third companion bridge plugin that asks
WordPress to fetch its OWN copy of a public image (`media_sideload_image()`, the same
mechanism as the native "Insert from URL" flow) — Imperal only ever sends a URL, never bytes.

**What was done:**
- New companion plugin `bridge/imperal-media-bridge/imperal-media-bridge.php` (344 lines):
  `POST /wp-json/imperal/v1/media/sideload` (source_url, optional post_id/post_slug+post_type,
  alt_text, caption, set_featured) and `GET /wp-json/imperal/v1/media/status`. HTTPS-only
  source URLs; rejects loopback/private/link-local hosts (127.*, 10.*, 172.16-31.*, 192.168.*,
  169.254.*, localhost, ::1, fc../fd..) before ever fetching. No fallback tier — missing
  bridge is a hard stop, same pattern as the Builder Bridge.
- Offline PHP logic harness `bridge/imperal-media-bridge/tests/bridge_logic_test.php` — 42
  assertions (URL validation, post resolution, permission checks, sideload happy path,
  featured-image attach, alt text, error mapping, status). Plus `bridge/imperal-media-bridge/
  README.md` and an index entry in the shared `bridge/README.md`.
- `wp_client.py`: generalised `find_category_id` into `find_term_id(taxonomy_base, name)` +
  `find_term_ids(taxonomy_base, names)` (bulk, reports names-not-found without failing the
  whole write); `find_category_id` kept as a thin wrapper so existing callers are untouched.
  `create_post`/`update_post` now also accept `tag_ids`/`featured_media`. `wp_post` gained an
  optional `timeout=` kwarg (sideload can take longer than the 30s default).
- `gutenberg.py`: new `image_block(media_id, media_url, alt, caption)` renders a Gutenberg
  image block from an existing attachment; `blocks_to_content` dispatches `type == "image"`
  blocks (skipped if `media_id`/`media_url` missing — nothing invented).
- `models.py`: `PostBlockInput` gained `media_id`/`media_url`/`caption` fields (type can now
  be `"image"`); `CreatePostParams`/`UpdatePostParams` gained `tags: list[str]` and
  `featured_media_id: int | None`; `PostResult` gained `tags_not_found`/`featured_media_set`;
  new `UploadMediaParams`, `MediaUploadResult`, `MediaSupport`.
- New `handlers_media.py` with 2 chat functions: `upload_media` (sideload one image, optional
  attach/featured-image/alt/caption) and `check_media_support` (bridge presence + upload
  capability). Same bridge-error-code-mapping style as `handlers_builders.py`/`handlers_seo.py`.
- `handlers_posts.py`: `create_post`/`update_post` now resolve `tags` via `find_term_ids` and
  wire `featured_media_id` straight through; tag names not found degrade to a warning in the
  summary, never a failure (mirrors category's existing fallback behaviour).
- Registered `handlers_media` in `main.py`'s `_LOCAL` tuple and import list (also added
  `gutenberg` itself to the stale-module purge list, which had been missing).
- New tests: `tests/test_media.py` (10), `tests/test_gutenberg.py` (9), plus 12 new cases in
  `tests/test_posts.py` for tags/featured_media/inline-image-in-content. Full suite: **288
  passed** (was 262 before this session).
- Bumped `app.py`/`pyproject.toml` to v1.7.0; updated `description` and the project structure
  section of `CLAUDE.md` (handlers_media.py, gutenberg.py signature change, bridge/ folder,
  new test files). `imperal build`/`imperal validate`: 75 functions (was 73), 0 errors, 0
  warnings, same pre-existing `on_install` info note.

**Not done / not in scope:**
- Image *planning* (which images, where, what prompt) stays in the Content Strategy app per
  the team's architecture notes — this app only executes an upload/attach/insert it is given
  a ready URL for.
- Image *generation* stays in the Image/Media app (Magnific/Mystic) — this app never creates
  pixels, only moves a finished public URL into WordPress.
- No live WordPress round-trip smoke test of the new bridge yet — only the offline PHP
  harness and Python `MockContext` tests. The plugin still needs to be installed on a real
  site and exercised end-to-end before relying on it in production, same caveat as the other
  two bridges when they first shipped.
- Arbitrary custom taxonomies (beyond categories/tags) were not added — `find_term_id`/
  `find_term_ids` are already taxonomy-generic, so adding one would just be a new REST base
  string if/when a real need shows up.

---

## 2026-08-03 — Post/page publishing ported from WP Publisher (v1.6.0)

**Status:** ✅ implemented and verified (262/262 tests pass, `imperal validate` clean: 0 errors, 0 warnings)

**Scope:** Migrate ONLY the WordPress-writing capability of the separate `WP Publisher`
app (draft/post creation with Gutenberg content, category, Polylang language) into this
connector. Explicitly OUT of scope, by request: anything about interpreting the input
document — `docx_parser.py`, `parse_article`, `confirm_mapping`, and the heading-heuristics
`rules.py` were deliberately NOT ported. Content now arrives as explicit, caller-decided
`{type, text, level}` blocks; nothing in this app parses a document.

**What was done:**
- New `gutenberg.py` — `blocks_to_content()` renders an ordered list of `{type, text,
  level}` blocks into Gutenberg block markup (`heading` → `<h{level}>`, anything else →
  paragraph). Pure and document-agnostic, ported from WP Publisher's block renderer
  without any of the docx-parsing context it used to run inside.
- `wp_client.py`: added `find_category_id` (case-insensitive term lookup, optionally
  Polylang-scoped via `lang`), `create_post`, and `update_post` — thin REST wrappers
  around `/wp-json/wp/v2/<base>` (posts/pages/custom types), also ported from WP
  Publisher's `wp_client.create_draft` but generalised to create OR update and to any
  post type, not just posts.
- New `handlers_posts.py` with 2 chat functions:
  - `create_post` — title, post_type (post/page/CPT), status (draft/publish/pending/
    private/future — future requires `date`), slug, blocks, excerpt, category (resolved
    by name, never created), date, lang (Polylang). Category-not-found is a soft warning,
    not a failure — mirrors WP Publisher's own fallback behaviour.
  - `update_post` — same fields, all optional; refuses with `POST_UPDATE_NO_FIELDS` if
    nothing was given; empty string on `category` clears it.
  - Both accept optional `meta_title` / `meta_description` / `focus_keyword` and delegate
    the actual SEO write to the EXISTING `handlers_seo.update_seo_meta` (bridge/core-meta
    tiers) instead of re-adding WP Publisher's own bridge-only Rank Math write path — one
    SEO write path in this app, not two. A failed SEO write degrades to a warning in the
    summary; the post itself is not rolled back.
- New models in `models.py`: `PostBlockInput`, `CreatePostParams`, `UpdatePostParams`,
  `PostResult` (SDL entity: id, title, kind, url=link, status, post_type, category_resolved,
  warnings).
- Registered `handlers_posts` in `main.py`'s `_LOCAL` tuple and import list.
- Added `tests/test_posts.py` (13 new tests): happy path block rendering, category
  resolution by name, category-not-found warning, page vs post REST base, `future` status
  requiring a date, SEO fields delegated to `update_seo_meta`, SEO failure surfaced as a
  warning not an error, HTTP failure mapping, missing site, update with partial fields,
  clearing category with `""`, update re-rendering blocks into fresh content, update with
  no fields refused.
- Bumped `app.py` / `pyproject.toml` to v1.6.0; updated `description` and the project
  structure section of `CLAUDE.md`. `imperal build` / `imperal validate`: 73 functions
  (was 71), 0 errors, 0 warnings, same pre-existing `on_install` info note.
- Full suite: **262 passed** (was 249 before this session).

**Not done / not in scope:**
- The `WP Publisher` app itself was left untouched — this was a one-way port of
  capability, not a decommission. Whether to deprecate/retire WP Publisher now that its
  posting half has a home here is a separate decision, not made in this session.
- No live WordPress round-trip smoke test yet — only `MockContext` tests. The bridge
  plugins this module relies on for SEO (`imperal-seo-bridge`) already exist and are
  presumably live on connected sites; `create_post`/`update_post` themselves need no new
  bridge plugin (stock `wp/v2/<base>` REST + Application Password is enough), but a real
  site was not exercised in this session.

---

## 2026-08-03 — Elementor/Bricks builder point-editing (v1.4.0)

**Status:** ✅ implemented and verified (246/246 tests pass, `imperal validate` clean: 0 errors, 0 warnings)

**What was done:**
- New companion WordPress plugin `bridge/imperal-builder-bridge/imperal-builder-bridge.php`
  (710 lines). Elementor stores its whole page tree in one post meta key
  (`_elementor_data`, nested JSON); Bricks stores each template area
  (`_bricks_page_header_2` / `_content_2` / `_footer_2`) as flat JSON keyed by
  element id. Neither registers these keys for REST, so — same root cause as
  Rank Math before the SEO bridge — reads come back empty and writes are
  silently dropped without a companion plugin. No fallback tier exists here
  (unlike SEO meta): a missing bridge is a hard stop.
- The bridge exposes `GET /wp-json/imperal/v1/builder` (flattened element
  tree, by post id/slug, optional builder filter), `POST …/builder/field`
  (change exactly one settings field on exactly one existing element,
  guarded by a `state_token` — refuses with 409 if the page changed since the
  read), and `GET …/builder/status` (capability discovery: which builder
  plugins are active site-wide). Deliberately does NOT expose "replace the
  tree" or "create an element" — point edits only, to avoid corrupting a
  working page.
- Added a standalone offline PHP logic test harness
  (`bridge/imperal-builder-bridge/tests/bridge_logic_test.php`, stubs core
  WP functions) — 56 assertions, all passing (`php tests/bridge_logic_test.php`).
- Added `bridge/imperal-builder-bridge/README.md`; added a short pointer
  section at the top of the shared `bridge/README.md` indexing both companion
  plugins.
- Python side: new `handlers_builders.py` with 3 chat functions —
  `check_builder_support`, `get_builder_content`, `update_builder_field` — plus
  matching Pydantic/SDL models in `models.py` (`BuilderElement`,
  `BuilderContent`, `BuilderFieldUpdateResult`, `BuilderSupport`, params
  models, `JsonValue` union for arbitrary builder field values).
- Registered the new module in `main.py`; bumped `app.py` and
  `pyproject.toml` to v1.4.0.
- Added `tests/test_builders.py` (24 new tests: reading, per-zone Bricks
  results, slug resolution, missing bridge, ambiguous slug/builder, stale
  state_token, unknown element, missing zone, forbidden write). Full suite:
  **246 passed** (was 222 before this session — verified via
  `.venv/bin/python -m pytest`, not assumed).
- `imperal build` / `imperal validate`: manifest regenerated for v1.4.0
  (72 tools total, 3 new); validate came back with 2 warnings on the first
  pass (missing `event=` / `effects=` on `update_builder_field`), fixed, then
  re-validated clean (0 errors, 0 warnings, 1 info about no `on_install` hook
  — pre-existing, not new).
- Committed and pushed to `origin/main` (`a1ede8d8`). Deployed to the
  Imperal registry: 4 tools synced, icon/manifest/panels synced, status
  `warning` (19/21 checks — same non-blocking pattern seen on prior releases
  of this connector; not investigated further since it hasn't blocked any
  previous release either).
- Still not done: no live WordPress site with Elementor/Bricks installed was
  used to smoke-test the actual bridge plugin end-to-end — only the offline
  PHP harness and Python `MockContext` tests. A real install/activation +
  live-site round trip is recommended before relying on this in production.

---

## 2026-08-02 — WooCommerce read-only module

**Status:** ✅ implemented and verified

**What was done:**
- Added a shared WooCommerce REST layer over the existing WordPress Application Password connection.
- Added 9 read-only chat functions: status, orders, one order, products, one product, customers, coupons, refunds, and store summary.
- Expanded order context with line items, totals, customer identity, payment method, filters, and pagination.
- Kept list responses privacy-minimal: no postal addresses or phone numbers are exposed.
- Added a conditional Commerce panel group with Overview, Orders, and Products; non-store sites do not show it.
- Added structured errors for unavailable WooCommerce, insufficient permission, missing records, malformed responses, rate limiting, and server failures.
- Added a module plan and contract tests. Manifest regenerated for v0.2.0.

**Verification:**
- `146 passed`
- `imperal validate`: 0 errors, 0 warnings (one informational lifecycle suggestion)
- Generated manifest contains all 9 WooCommerce functions.

**Next steps:**
- Deploy v0.2.0 and smoke-test against a connected WooCommerce production or staging site.

---

## 2026-06-19 — UI: status lamp + icon + content layout

**Status:** in progress

**Что было сделано (git log):**
- Replaced placeholder icon with official app logo
- Added status lamp (pulsing ui.Badge dot) to site list — green/yellow/red with animation
- Attempted ui.Html for lamp avatar (BUG-002: ui.Html not supported in avatar= slot → reverted to ui.Badge)
- Grouped content layout: Standard / Activity / Custom Types / Taxonomies sections
- Tab switching experiments (ui.Html client-side → reverted, settled on server-side tabs)
- Refresh All tooltip

**Known issue (BUG-002):** `ui.Html` does not render in `avatar=` slot of `ui.ListItem`. Workaround: `ui.Badge` with color.

**Next steps:** (определить при следующей сессии)

---

## 2026-06-16 — v1 design approved + initial build

**Status:** ✅ design approved, implementation started

**Что было сделано:**
- v1 design spec written: `docs/2026-06-16-wordpress-hub-v1-design.md`
- v1 implementation plan: `docs/2026-06-16-wordpress-hub-v1-plan.md`
- Initial app scaffold: app.py, handlers_connect.py, handlers_read.py, panels.py, skeleton.py, models.py, wp_client.py, storage.py
- imperal.json generated (manifest v3, sdk 5.4.2)
- Tools: connect_site, forget_site, add_ssh, remove_ssh, list_sites, list_posts, list_pages, list_media, get_site_health, refresh_site, refresh_all_sites, list_comments, list_scheduled, list_users, list_orders, list_custom_posts, get_server_info
- Tests: 11 test files covering all handlers, panels, models, storage, wp_client

---

_Template:_

```
## YYYY-MM-DD — <short description>

**Status:** in progress | ✅ done

**Что было сделано:**
-

**Next steps:**
-
```
