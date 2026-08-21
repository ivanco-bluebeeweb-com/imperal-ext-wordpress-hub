# WordPress Hub — Claude Code Guide

## What this is

An **Imperal Cloud app** (Python extension) — NOT a WordPress plugin. Connects to WordPress sites
via WP REST API + Application Passwords and lets the user read content (posts, pages, media,
health, comments, scheduled posts, users, WooCommerce orders) from within Imperal OS.

Part of: `Imperal OS / Apps / WordPress Hub`

## Communication

- Respond to user in **Russian**
- All code, comments, docs, UI strings, commit messages stay in **English**

---

## Imperal SDK Rules — ОБЯЗАТЕЛЬНО

**Before writing any panel or handler code, read the Imperal OS CLAUDE.md in full:**
`/Users/vladivanco/Documents/Imperal OS/CLAUDE.md`

Key rules that apply here:
- Read `Imperal OS/Docs/imperal-docs/ui-components-reference.md` before using any UI component.
- Only use components listed there. Missing component → tell Vlad before writing code.
- **Write a component sketch (pseudocode tree) before every panel** — required, no exceptions.
- If `Docs/imperal-docs/.last-check` is stale (>24h), run `bash Docs/imperal-docs/refresh.sh` first.
- **Bricks detection gate — MANDATORY, every session, every user.** Whenever a connected
  site is detected running Bricks (`check_builder_support` returns `bricks_active: true`),
  follow `Imperal OS/Docs/BRICKS_DETECTION_STANDARD.md` in full before any further Bricks
  work: check `bricks_version` (need 2.4+ for the MCP Abilities API), and if 2.4+, verify
  MCP Adapter + Abilities API + an actual MCP server connection are configured before
  using the 142 real `bricks/*` abilities — never fall back to hand-authored raw
  `_bricks_page_content_2` postmeta writes once real abilities are reachable.

---

## Project Structure

```
Apps/WordPress Hub/
├── app.py                  ← Extension(...) + ChatExtension(...) + health_check
├── main.py                 ← CLI loader (imports app, registers handlers)
├── handlers_connect.py     ← connect_site, forget_site, add_ssh, remove_ssh, refresh_site, refresh_all_sites
├── handlers_read.py        ← list_sites, list_posts, list_pages, list_media, get_site_health,
│                               list_comments, list_scheduled, list_users, list_orders,
│                               list_custom_posts, get_server_info
├── handlers_seo.py         ← get/update_seo_meta, get/update_term_seo_meta, check_seo_support (Rank Math)
├── handlers_builders.py    ← check_builder_support, get_builder_content, update_builder_field (Elementor/Bricks)
├── handlers_posts.py       ← create_post, update_post — Gutenberg content (incl. inline image blocks),
│                               category, tags, featured_media, Polylang lang; SEO fields delegate to
│                               handlers_seo.update_seo_meta (ported from WP Publisher; document
│                               parsing/understanding was NOT ported — content arrives as explicit blocks)
├── handlers_media.py       ← upload_media, check_media_support — sideload a public image URL into the
│                               media library via the Imperal Bridge (WordPress fetches its own
│                               copy; ctx.http is never used to move image bytes, see module docstring)
├── gutenberg.py            ← blocks_to_content: {type,text,level,media_id,media_url,caption} blocks ->
│                               Gutenberg block markup, incl. image_block() for inline images
├── panels.py               ← dashboard panel (sites list + content detail + connection form)
├── skeleton.py             ← ambient sites count probe
├── models.py               ← Pydantic param models + SDL entities
├── wp_client.py            ← WP REST helper (auth, error mapping, timeouts, find_term_id/find_term_ids,
│                               find_category_id wrapper, create/update_post with tags/featured_media)
├── storage.py              ← ctx.store wrappers
├── wp_cli.py               ← SSH + WP-CLI helpers for get_server_info
├── icon.svg                ← app icon
├── imperal.json            ← generated manifest (do not edit manually — regenerate with `imperal build`)
├── pyproject.toml
├── requirements.txt
├── design/
│   └── wordpress-hub-panel.html  ← UI wireframe (source of truth for panel layout)
├── bridge/                 ← ONE companion WordPress plugin (see bridge/README.md) — do not add a second
│   └── imperal-bridge/           ← Imperal Bridge: Rank Math SEO fields + Elementor/Bricks element trees
│                                     (guarded point edits) + image sideload (media_sideload_image), all in
│                                     one plugin/one version. Future bridge capabilities are new sections in
│                                     this same file, never a new plugin.
├── docs/
│   ├── 2026-06-16-wordpress-hub-v1-design.md  ← v1 spec (approved)
│   ├── 2026-06-16-wordpress-hub-v1-plan.md    ← v1 plan
│   └── superpowers/plans/                         ← per-feature implementation plans
└── tests/
    ├── test_connect.py
    ├── test_forget.py
    ├── test_gutenberg.py
    ├── test_health.py
    ├── test_list_content.py
    ├── test_list_sites.py
    ├── test_media.py
    ├── test_models.py
    ├── test_panels.py
    ├── test_posts.py
    ├── test_skeleton.py
    ├── test_storage.py
    └── test_wp_client.py
```

---

## Key Specs

- **Full Feature Roadmap** — `docs/2026-08-09-full-feature-roadmap.md` — **THE canonical master plan
  for what to build next in this app.** Maps every WP Core / WooCommerce / Rank Math / builder /
  Bridge+SSH capability against what's implemented (87 functions) vs missing, with a priority
  order. Read this FIRST before proposing or starting any new feature — do not re-derive this list
  from memory.
- **v1 Design** — `docs/2026-06-16-wordpress-hub-v1-design.md` — approved spec, source of truth for architecture and security rules.
- **v1 Plan** — `docs/2026-06-16-wordpress-hub-v1-plan.md` — implementation plan.
- **Per-feature plans** — `docs/superpowers/plans/*.md`.
- **UI components reference** — `../../Docs/imperal-docs/ui-components-reference.md` (Imperal OS).

---

## Tech Stack

- Python 3.11+
- Imperal SDK (`imperal-sdk`) — `Extension`, `ChatExtension`, `@ext.panel`, `@ext.skeleton`, `@chat.function`, `MockContext`
- `ctx.store` — persistent per-user data (sites records)
- `ctx.secrets` — KMS-encrypted credentials (`wp_credentials` JSON map)
- `ctx.http` — outbound HTTP (WP REST API calls)
- pytest + pytest-asyncio — `asyncio_mode = "auto"`

---

## Running Tests

```bash
cd "Apps/WordPress Hub"
python -m pytest
```

All tests use `MockContext` from the SDK. No live WordPress site needed. Each `@chat.function` must have ≥1 test.

---

## Regenerating imperal.json

```bash
cd "Apps/WordPress Hub"
imperal build
```

Do NOT edit `imperal.json` manually. Always regenerate after changing tools, panels, or capabilities.

---

## Security (non-negotiable, from v1 design §5)

- **App password never flows through an LLM-visible `@chat.function` arg.** Captured only via panel form (`ui.Form` → form handler).
- Credentials only via `ctx.secrets` — never `os.environ`, logs, or `ActionResult.data`.
- All store/secret access scoped by `ctx.user.imperal_id`.
- Outbound HTTP only to user-declared site hosts via `ctx.http`.
- Refuse non-HTTPS site URLs.

---

## Data Model

**`ctx.store` collection `sites`** (per user):
```
{ id, name, url, username, status: "connected"|"error", last_checked, last_error?, health: {} }
```

**`ctx.secrets("wp_credentials")`** — JSON map `{ site_id: app_password }`. Single secret, updated on connect/forget.

---

## CURRENT_WORK.md

`CURRENT_WORK.md` — first thing to read at session start, last thing to update at session end.

---

## Процесс разработки

**Перед любой реализацией:**
1. `/brainstorming` — обсудить с Владом (если есть UI/UX решения)
2. `/writing-plans` — написать детальный план
3. `/subagent-driven-development` или `/executing-plans` — реализовать по плану

**Нельзя:** писать код без component sketch для панелей и без плана для фич.
