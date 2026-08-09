import asyncio
from urllib.parse import urlparse

from imperal_sdk import ui
from app import ext
from wp_client import wp_get, wp_title
import storage

_BUILTIN_TYPES = {
    "post", "page", "attachment", "revision", "nav_menu_item",
    "custom_css", "customize_changeset", "oembed_cache", "user_request",
    "wp_block", "wp_template", "wp_template_part", "wp_navigation",
    "wp_global_styles",
}
_BUILTIN_TAXES = {"nav_menu", "link_category", "post_format"}

# Imperal Bridge is the ONE companion WordPress plugin this connector needs —
# it replaces the old separate SEO/Builder/Media bridge plugins. Its download
# link must always be reachable from the sidebar, so every site owner can
# grab the plugin (or its latest version) without hunting through docs.
# Hosted as a public raw file straight off the connector's own repo — no
# extra storage/CDN step needed, and it moves automatically with every push.
BRIDGE_DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/ivanco-bluebeeweb-com/"
    "imperal-ext-wordpress-hub/main/bridge/imperal-bridge.zip"
)


async def _sites_registry_installed(ctx) -> bool:
    """Best-effort probe: is Sites Registry installed and reachable right now?

    There is no ctx.extensions.is_installed() API on this platform -- the
    only way to find out is to call an exposed IPC method and see whether it
    raises. Uses Sites Registry's dedicated read-only `ping` surface (no
    ctx.store access, no side effects) rather than the write-only
    `upsert_site` surface, so this check can never create a stray site
    record just by running. Any failure (app not installed, not enabled,
    unreachable) is treated as "not installed" -- fail closed, so the Sync
    button only ever appears when it can actually do something.
    """
    try:
        result = await ctx.extensions.call("sites-registry", "ping")
    except Exception:
        return False
    return bool(result and result.get("ok"))


# ── Left sidebar ──────────────────────────────────────────────────────────────

def _site_subtitle(r: dict) -> str:
    """Build a rich subtitle for a site list item."""
    if r.get("ssh_host"):
        parts = []
        if r.get("wp_version"):
            parts.append(f"WP {r['wp_version']}")
        if r.get("php_version"):
            parts.append(f"PHP {r['php_version']}")
        updates = r.get("pending_updates", 0)
        if updates:
            parts.append(f"⚠️ {updates} update(s)")
        elif r.get("wp_version"):
            parts.append("✅ up to date")
        return " · ".join(parts) if parts else r.get("status", "connected")
    return r.get("status", "connected")


def _site_badge_color(r: dict) -> str:
    if r.get("status") == "error":
        return "red"
    if r.get("pending_updates", 0) > 0:
        return "yellow"
    return "green"


def _lamp(r: dict) -> ui.Badge:
    """Status indicator left of site name. ui.Html in avatar= doesn't render (BUG-002)."""
    return ui.Badge(color=_site_badge_color(r))


@ext.panel(
    "sidebar",
    slot="left",
    title="WP Sites",
    default_width=280,
    min_width=200,
    max_width=400,
    refresh="on_event:wordpress-hub.connect_site,wordpress-hub.forget_site,"
            "wordpress-hub.refresh_site,wordpress-hub.refresh_all_sites,"
            "wordpress-hub.add_ssh,wordpress-hub.remove_ssh,"
            "wordpress-hub.get_server_info",
)
async def sidebar(ctx, active_site_id="", **kwargs):
    rows = await storage.list_site_records(ctx)

    top_bar = ui.Stack(direction="h", gap=2, children=[
        ui.Button("Connect Site", icon="Plus", variant="primary",
                  on_click=ui.Call("__panel__center", view="connect", site_id="")),
        ui.Tooltip(
            content="Pings all connected sites in parallel, updates their stored status, and clears content caches so the next view fetches fresh data.",
            children=ui.Button("Refresh All", icon="RefreshCw", variant="secondary",
                               disabled=not rows,
                               on_click=ui.Call("refresh_all_sites")),
        ),
    ])

    if not rows:
        site_list = ui.Empty(message="No sites connected yet.")
    else:
        items = [
            ui.ListItem(
                id=r["id"],
                title=urlparse(r.get("url", "")).netloc or r.get("name", r["id"]),
                subtitle=_site_subtitle(r),
                avatar=_lamp(r),
                selected=(active_site_id == r["id"]),
                on_click=ui.Call("__panel__center", view="", site_id=r["id"]),
                actions=[
                    {"icon": "RefreshCw",
                     "on_click": ui.Call("refresh_site", site_id=r["id"])},
                    {"icon": "Trash2",
                     "on_click": ui.Call("forget_site", site_id=r["id"]),
                     "confirm": f"Remove {urlparse(r.get('url', '')).netloc or r['id']}?"},
                ],
            )
            for r in rows
        ]
        site_list = ui.List(items=items)

    footer_children = []
    if await _sites_registry_installed(ctx):
        footer_children.append(
            ui.Tooltip(
                content="Pushes every WordPress site connected here into Sites Registry -- the "
                        "platform-agnostic catalogue app. Fixes sites connected here before Sites "
                        "Registry existed, or any time the two drift out of sync. Refresh the Sites "
                        "Registry page after this to see them.",
                children=ui.Button(
                    "Sync sites to Sites Registry",
                    icon="RefreshCw",
                    variant="secondary",
                    full_width=True,
                    disabled=not rows,
                    on_click=ui.Call("sync_sites_to_registry"),
                ),
            )
        )
    footer_children.append(
        ui.Tooltip(
            content="Imperal Bridge is the one companion plugin this connector needs on a "
                    "WordPress site — Rank Math SEO fields, Elementor/Bricks builder content, "
                    "and image sideloading, all in a single install.",
            children=ui.Button(
                "Download Imperal Bridge plugin",
                icon="Download",
                variant="secondary",
                full_width=True,
                on_click=ui.Open(BRIDGE_DOWNLOAD_URL),
            ),
        )
    )
    bridge_footer = ui.Stack(children=[ui.Divider(), *footer_children], gap=2)

    root = ui.Stack(
        children=[top_bar, ui.Divider(), site_list, bridge_footer],
        gap=3,
    )

    if not active_site_id and rows:
        root.props["auto_action"] = ui.Call(
            "__panel__center", view="", site_id=rows[0]["id"]
        )
    return root


# ── Single center panel ────────────────────────────────────────────────────────

@ext.panel("center", slot="center", center_overlay=True, title="WordPress Hub")
async def center(ctx, view="", site_id="",
                 group_tab="standard",
                 std_tab="posts", act_tab="comments", commerce_tab="overview",
                 cpt_tab="", tax_tab="",
                 **kwargs):
    if view == "connect":
        return _render_connect_form()
    if view == "add_ssh" and site_id:
        if await storage.has_ssh(ctx, site_id):
            return await _render_detail(ctx, site_id, group_tab, std_tab, act_tab,
                                        commerce_tab, cpt_tab, tax_tab)
        await storage.set_pending_ssh_site(ctx, site_id)
        return _render_add_ssh_form(site_id)
    if site_id:
        return await _render_detail(ctx, site_id, group_tab, std_tab, act_tab,
                                    commerce_tab, cpt_tab, tax_tab)
    return ui.Empty(message="Select a site from the list to view its dashboard.")


# ── Connect form ──────────────────────────────────────────────────────────────

def _field(label, help_text, input_node):
    return ui.Stack(children=[
        ui.Tooltip(content=help_text, children=ui.Text(label)),
        input_node,
    ])


def _render_connect_form():
    return ui.Stack(children=[
        ui.Form(action="connect_site", submit_label="Connect", children=[
            _field("Site URL", "The site's full address, e.g. https://example.com",
                   ui.Input(param_name="url", placeholder="https://example.com")),
            _field("Username", "The WordPress username that created the Application Password",
                   ui.Input(param_name="username", placeholder="admin")),
            _field("Application Password",
                   "Create this under Users → Profile → Application Passwords in WordPress",
                   ui.Password(param_name="app_password")),
        ]),
        ui.Button("Cancel", variant="ghost",
                  on_click=ui.Call("__panel__center", view="", site_id="")),
    ], gap=4)


def _render_add_ssh_form(site_id):
    return ui.Stack(children=[
        ui.Form(action="add_ssh", submit_label="Connect via SSH", children=[
            _field("SSH Host", "Hostname or IP address, e.g. server1.webhostmost.com",
                   ui.Input(param_name="ssh_host", placeholder="mysite.com")),
            _field("SSH Port", "SSH port (default 22)",
                   ui.Input(param_name="ssh_port", placeholder="22")),
            _field("SSH User", "SSH username, e.g. root, ubuntu, deploy",
                   ui.Input(param_name="ssh_user", placeholder="ubuntu")),
            _field("WordPress Path", "Absolute path to WordPress on the server",
                   ui.Input(param_name="wp_path", placeholder="/var/www/html")),
            _field("Private Key",
                   "Paste your SSH private key (PEM format). Leave empty to use password.",
                   ui.TextArea(param_name="ssh_key",
                               placeholder="-----BEGIN OPENSSH PRIVATE KEY-----\n...", rows=6)),
            _field("SSH Password", "Leave empty if using a private key above.",
                   ui.Password(param_name="ssh_password")),
        ]),
        ui.Button("Cancel", variant="ghost",
                  on_click=ui.Call("__panel__center", view="", site_id=site_id)),
    ], gap=4)


# ── Content tables ────────────────────────────────────────────────────────────

def _render_content_table(items, tab):
    if items is None:
        if tab == "orders":
            return ui.Alert(message="WooCommerce not installed or insufficient permissions.",
                            type="info")
        return ui.Alert(message="Could not load — check the connection.", type="error")
    if not items:
        return ui.Empty(message=f"No {tab.replace('cpt:', '').replace('tax:', '')} found.")

    if tab.startswith("tax:"):
        cols = [ui.DataColumn("name", "Term", sortable=True),
                ui.DataColumn("count", "Posts", sortable=True),
                ui.DataColumn("slug", "Slug", sortable=True)]
        rows = [{"name": it.get("name", ""), "count": str(it.get("count", 0)),
                 "slug": it.get("slug", "")} for it in items]
        return ui.DataTable(columns=cols, rows=rows)

    if tab == "media":
        cols = [ui.DataColumn("title", "Title", sortable=True),
                ui.DataColumn("type",  "Type",  sortable=True)]
        rows = [{"title": wp_title(it), "type": it.get("mime_type", "")} for it in items]
        return ui.DataTable(columns=cols, rows=rows)

    if tab == "comments":
        cols = [ui.DataColumn("author",  "Author",  sortable=True),
                ui.DataColumn("snippet", "Comment", sortable=False),
                ui.DataColumn("status",  "Status",  sortable=True),
                ui.DataColumn("date",    "Date",    sortable=True)]
        rows = [{"author": it.get("author_name", ""),
                 "snippet": (it.get("content", {}).get("rendered", "") or "")
                             .replace("<p>", "").replace("</p>", "")[:60],
                 "status": it.get("status", ""),
                 "date": (it.get("date", "") or "")[:10]} for it in items]
        return ui.DataTable(columns=cols, rows=rows)

    if tab == "scheduled":
        cols = [ui.DataColumn("title", "Title", sortable=True),
                ui.DataColumn("date",  "Scheduled", sortable=True)]
        rows = [{"title": wp_title(it),
                 "date": (it.get("date", "") or "")[:16].replace("T", " ")} for it in items]
        return ui.DataTable(columns=cols, rows=rows)

    if tab == "users":
        cols = [ui.DataColumn("name",       "Name",       sortable=True),
                ui.DataColumn("role",        "Role",       sortable=True),
                ui.DataColumn("registered",  "Registered", sortable=True)]
        rows = [{"name": it.get("name", ""), "role": ", ".join(it.get("roles", [])),
                 "registered": (it.get("registered_date", "") or "")[:10]} for it in items]
        return ui.DataTable(columns=cols, rows=rows)

    if tab == "orders":
        cols = [ui.DataColumn("id",     "#",      sortable=True),
                ui.DataColumn("status", "Status", sortable=True),
                ui.DataColumn("total",  "Total",  sortable=True),
                ui.DataColumn("date",   "Date",   sortable=True)]
        rows = [{"id": str(it.get("id", "")), "status": it.get("status", ""),
                 "total": f"{it.get('total', '')} {it.get('currency', '')}".strip(),
                 "date": (it.get("date_created", "") or "")[:10]} for it in items]
        return ui.DataTable(columns=cols, rows=rows)

    # posts, pages, custom post types
    cols = [ui.DataColumn("title",  "Title",  sortable=True),
            ui.DataColumn("status", "Status", sortable=True),
            ui.DataColumn("date",   "Date",   sortable=True)]
    rows = [{"title": wp_title(it), "status": it.get("status", ""),
             "date": (it.get("date", "") or "")[:10]} for it in items]
    return ui.DataTable(columns=cols, rows=rows)


# ── Category / tag management (create · rename · delete) ─────────────────────
# Categories/tags are read-only in the taxonomy table above (DataTable has no
# per-row actions); this block is the write side, one real ui.Form per verb,
# submitting straight to the taxonomy tools -- no chat round-trip needed.

_TAX_TOOLS = {
    "category": {"create": "create_post_category", "update": "update_post_category",
                 "delete": "delete_post_category", "label": "category"},
    "post_tag": {"create": "create_post_tag", "update": "update_post_tag",
                 "delete": "delete_post_tag", "label": "tag"},
}


def _taxonomy_manage_block(items: list, site_id: str, tax_slug: str):
    tools = _TAX_TOOLS[tax_slug]
    label = tools["label"]
    term_options = [{"value": str(it.get("id", "")), "label": it.get("name", "")} for it in items]

    create_children = [
        ui.Input(param_name="name", placeholder=f"New {label} name"),
    ]
    if tax_slug == "category":
        parent_options = [{"value": "0", "label": "(top level)"}] + term_options
        create_children.append(
            ui.Select(param_name="parent_id", options=parent_options, value="0",
                      placeholder="Parent category")
        )
        create_children.append(
            ui.Input(param_name="description", placeholder="Description (optional)")
        )
    create_form = ui.Form(
        action=tools["create"], submit_label=f"Create {label}",
        defaults={"site_id": site_id},
        children=create_children,
    )

    if not term_options:
        return ui.Card(title=f"New {label}", content=create_form)

    rename_children = [
        ui.Select(param_name="term_id", options=term_options, placeholder=f"Choose a {label}"),
        ui.Input(param_name="name", placeholder="New name"),
    ]
    if tax_slug == "category":
        rename_children.append(
            ui.Select(param_name="parent_id",
                      options=[{"value": "0", "label": "(top level)"}] + term_options,
                      placeholder="New parent (optional)")
        )
    rename_form = ui.Form(
        action=tools["update"], submit_label=f"Rename {label}",
        defaults={"site_id": site_id},
        children=rename_children,
    )

    delete_form = ui.Form(
        action=tools["delete"], submit_label=f"Delete {label}",
        defaults={"site_id": site_id},
        children=[
            ui.Select(param_name="term_id", options=term_options, placeholder=f"Choose a {label}"),
        ],
    )

    return ui.Stack(direction="v", gap=3, children=[
        ui.Card(title=f"New {label}", content=create_form),
        ui.Card(title=f"Rename {label}", content=rename_form),
        ui.Card(title=f"Delete {label}", content=delete_form),
    ])


# ── Site detail ───────────────────────────────────────────────────────────────

async def _render_detail(ctx, site_id,
                         group_tab="standard",
                         std_tab="posts", act_tab="comments", commerce_tab="overview",
                         cpt_tab="", tax_tab=""):
    record = await storage.get_site_record(ctx, site_id) or {}
    if not record:
        return ui.Empty(message="Site not found — it may have been removed.")

    base_url = record.get("url", "")
    pw = await storage.get_credential(ctx, site_id)
    if not base_url or not pw:
        return ui.Alert(message="Credential missing — reconnect this site.", type="error")

    username = record.get("username", "")
    name = urlparse(base_url).netloc or record.get("name", site_id)

    reachable = record.get("status") == "connected"
    ssl_valid = base_url.startswith("https://")

    # has_ssh: prefer site record (fast), fall back to creds collection (backward compat)
    has_ssh = bool(record.get("ssh_host"))
    if not has_ssh:
        ssh_cred = await storage.get_ssh_cred(ctx, site_id)
        if ssh_cred:
            has_ssh = True
            # Migrate: write ssh_host into record so future renders are fast
            await storage.save_site_record(
                ctx, {**record, "ssh_host": ssh_cred.get("host", "legacy")}
            )

    # ── Zone 1: Health row ────────────────────────────
    ssh_btn = ui.Button(
        "Remove SSH" if has_ssh else "Add SSH",
        icon="Terminal", variant="ghost", size="sm",
        on_click=ui.Call("remove_ssh", site_id=site_id) if has_ssh
                 else ui.Call("__panel__center", view="add_ssh", site_id=site_id),
    )
    health_row = ui.Stack(direction="h", justify="between", align="center", children=[
        ui.Stats(columns=3, children=[
            ui.Stat(label="Reachable", value="Yes" if reachable else "No",
                    color="green" if reachable else "red"),
            ui.Stat(label="Auth",      value="OK" if reachable else "Failed",
                    color="green" if reachable else "red"),
            ui.Stat(label="SSL",       value="HTTPS" if ssl_valid else "HTTP",
                    color="green" if ssl_valid else "red"),
        ]),
        ssh_btn,
    ])

    # ── Zone 2: Server info (from record; refresh works via Bridge or SSH) ─
    server_section_children = []
    wp_ver    = record.get("wp_version")
    php_ver   = record.get("php_version")
    db_size   = record.get("db_size_mb")
    cron_cnt  = record.get("cron_count")
    n_updates = record.get("pending_updates", 0)
    plug_list = record.get("plugin_updates_list") or []
    theme_list = record.get("theme_updates_list") or []
    last_check = record.get("server_last_checked", "")
    server_source = record.get("server_source", "")

    refresh_server_btn = ui.Button(
        "Refresh server info", icon="RefreshCw", variant="ghost", size="sm",
        on_click=ui.Call("get_server_info", site_id=site_id),
    )

    ssh_error = record.get("ssh_error", "")
    if not wp_ver:
        msg = ssh_error if ssh_error else (
            "No server data yet — reads through the Imperal Bridge plugin if it's installed, "
            "or falls back to SSH."
        )
        server_section_children = [
            ui.Divider(label="Server"),
            ui.Stack(direction="h", align="center", gap=3, children=[
                ui.Text(msg),
                refresh_server_btn,
            ]),
        ]
    else:
        stat_items = [
            ui.Stat(label="WordPress", value=wp_ver, color="blue"),
            ui.Stat(label="PHP",       value=php_ver or "—", color="blue"),
        ]
        if db_size:
            stat_items.append(ui.Stat(label="Database", value=f"{db_size} MB", color="blue"))
        if cron_cnt is not None:
            stat_items.append(ui.Stat(label="Cron jobs", value=str(cron_cnt), color="blue"))

        update_items = []
        if n_updates == 0:
            update_items.append(
                ui.Alert(message="All plugins, themes and core are up to date.", type="success")
            )
        else:
            if plug_list:
                update_items += [
                    ui.Text("Plugin updates", variant="heading"),
                    ui.DataTable(
                        columns=[
                            ui.DataColumn("title",          "Plugin",    sortable=True),
                            ui.DataColumn("version",        "Current",   sortable=False),
                            ui.DataColumn("update_version", "Available", sortable=False),
                        ],
                        rows=[{"title": p.get("title") or p.get("name", ""),
                               "version": p.get("version", ""),
                               "update_version": p.get("update_version", "")}
                              for p in plug_list],
                    ),
                ]
            if theme_list:
                update_items += [
                    ui.Text("Theme updates", variant="heading"),
                    ui.DataTable(
                        columns=[
                            ui.DataColumn("title",          "Theme",     sortable=True),
                            ui.DataColumn("version",        "Current",   sortable=False),
                            ui.DataColumn("update_version", "Available", sortable=False),
                        ],
                        rows=[{"title": t.get("title") or t.get("name", ""),
                               "version": t.get("version", ""),
                               "update_version": t.get("update_version", "")}
                              for t in theme_list],
                    ),
                ]

        checked_text = f"Last checked: {last_check[:16].replace('T', ' ')}" if last_check else ""
        if server_source:
            via = "Imperal Bridge" if server_source == "bridge" else "SSH"
            checked_text = f"{checked_text} · via {via}" if checked_text else f"via {via}"
        server_section_children = [
            ui.Divider(label="Server"),
            ui.Stats(columns=len(stat_items), children=stat_items),
            *update_items,
            ui.Stack(direction="h", justify="between", align="center", children=[
                ui.Text(checked_text, variant="caption"),
                refresh_server_btn,
            ]),
        ]

    # ── Content cache + fetch ──────────────────────────
    async def _list(path, params=None):
        try:
            r = await wp_get(ctx, base_url, path, username=username, app_password=pw,
                             params=params or {"per_page": 20})
            return r.body if r.status_code == 200 and isinstance(r.body, list) else None
        except Exception:
            return None

    async def _dict(path):
        try:
            r = await wp_get(ctx, base_url, path, username=username, app_password=pw)
            if r.status_code != 200:
                return {}
            try:
                data = r.json()
                return data if isinstance(data, dict) else {}
            except Exception:
                return r.body if isinstance(r.body, dict) else {}
        except Exception:
            return {}

    async def _orders():
        try:
            r = await wp_get(ctx, base_url, "/wp-json/wc/v3/orders",
                             username=username, app_password=pw,
                             params={"per_page": 20, "orderby": "date", "order": "desc"})
            if r.status_code in (404, 401, 403):
                return None
            return r.body if r.status_code == 200 and isinstance(r.body, list) else None
        except Exception:
            return None

    cached = await storage.get_content_cache(ctx, site_id)
    cache_needs_discovery = cached is None or "_cpt_meta" not in cached.get("dynamic", {})

    if cached and not cache_needs_discovery:
        posts_data     = cached.get("posts")
        pages_data     = cached.get("pages")
        media_data     = cached.get("media")
        comments_data  = cached.get("comments")
        scheduled_data = cached.get("scheduled")
        users_data     = cached.get("users")
        orders_data    = cached.get("orders")
        dynamic        = cached.get("dynamic", {})
    elif cached and cache_needs_discovery:
        posts_data     = cached.get("posts")
        pages_data     = cached.get("pages")
        media_data     = cached.get("media")
        comments_data  = cached.get("comments")
        scheduled_data = cached.get("scheduled")
        users_data     = cached.get("users")
        orders_data    = cached.get("orders")

        types_dict, taxes_dict = await asyncio.gather(
            _dict("/wp-json/wp/v2/types"),
            _dict("/wp-json/wp/v2/taxonomies"),
        )
        custom_cpts  = {s: i for s, i in types_dict.items()
                        if s not in _BUILTIN_TYPES and i.get("rest_base")}
        custom_taxes = {s: i for s, i in taxes_dict.items()
                        if s not in _BUILTIN_TAXES and i.get("rest_base")}
        cpt_slugs  = list(custom_cpts.keys())
        tax_slugs  = list(custom_taxes.keys())

        if cpt_slugs or tax_slugs:
            cpt_results, tax_results = await asyncio.gather(
                asyncio.gather(*[_list(f"/wp-json/wp/v2/{custom_cpts[s]['rest_base']}")
                                 for s in cpt_slugs]),
                asyncio.gather(*[_list(f"/wp-json/wp/v2/{custom_taxes[s]['rest_base']}",
                                       {"per_page": 50, "orderby": "count", "order": "desc"})
                                 for s in tax_slugs]),
            )
        else:
            cpt_results, tax_results = [], []

        dynamic = {
            "_cpt_meta": {s: {"name": custom_cpts[s].get("name", s),
                               "rest_base": custom_cpts[s].get("rest_base")}
                          for s in cpt_slugs},
            "_tax_meta": {s: {"name": custom_taxes[s].get("name", s),
                               "rest_base": custom_taxes[s].get("rest_base")}
                          for s in tax_slugs},
        }
        for slug, items in zip(cpt_slugs, cpt_results):
            dynamic[f"cpt:{slug}"] = items or []
        for slug, items in zip(tax_slugs, tax_results):
            dynamic[f"tax:{slug}"] = items or []

        await storage.set_content_cache(
            ctx, site_id, posts=posts_data, pages=pages_data, media=media_data,
            comments=comments_data, scheduled=scheduled_data, users=users_data,
            orders=orders_data, dynamic=dynamic,
        )
    else:
        types_dict, taxes_dict = await asyncio.gather(
            _dict("/wp-json/wp/v2/types"),
            _dict("/wp-json/wp/v2/taxonomies"),
        )
        custom_cpts  = {s: i for s, i in types_dict.items()
                        if s not in _BUILTIN_TYPES and i.get("rest_base")}
        custom_taxes = {s: i for s, i in taxes_dict.items()
                        if s not in _BUILTIN_TAXES and i.get("rest_base")}
        cpt_slugs  = list(custom_cpts.keys())
        tax_slugs  = list(custom_taxes.keys())

        standard_tasks = [
            _list("/wp-json/wp/v2/posts"),
            _list("/wp-json/wp/v2/pages"),
            _list("/wp-json/wp/v2/media"),
            _list("/wp-json/wp/v2/comments",
                  {"per_page": 20, "orderby": "date", "order": "desc"}),
            _list("/wp-json/wp/v2/posts",
                  {"per_page": 20, "status": "future", "orderby": "date", "order": "asc"}),
            _list("/wp-json/wp/v2/users",
                  {"per_page": 20, "orderby": "registered", "order": "desc"}),
            _orders(),
        ]
        cpt_tasks = [_list(f"/wp-json/wp/v2/{custom_cpts[s]['rest_base']}") for s in cpt_slugs]
        tax_tasks = [_list(f"/wp-json/wp/v2/{custom_taxes[s]['rest_base']}",
                           {"per_page": 50, "orderby": "count", "order": "desc"})
                     for s in tax_slugs]

        results = await asyncio.gather(*standard_tasks, *cpt_tasks, *tax_tasks)

        (posts_data, pages_data, media_data,
         comments_data, scheduled_data, users_data, orders_data) = results[:7]
        cpt_results = results[7:7 + len(cpt_slugs)]
        tax_results = results[7 + len(cpt_slugs):]

        dynamic = {
            "_cpt_meta": {s: {"name": custom_cpts[s].get("name", s),
                               "rest_base": custom_cpts[s].get("rest_base")}
                          for s in cpt_slugs},
            "_tax_meta": {s: {"name": custom_taxes[s].get("name", s),
                               "rest_base": custom_taxes[s].get("rest_base")}
                          for s in tax_slugs},
        }
        for slug, items in zip(cpt_slugs, cpt_results):
            dynamic[f"cpt:{slug}"] = items or []
        for slug, items in zip(tax_slugs, tax_results):
            dynamic[f"tax:{slug}"] = items or []

        await storage.set_content_cache(
            ctx, site_id, posts=posts_data, pages=pages_data, media=media_data,
            comments=comments_data, scheduled=scheduled_data, users=users_data,
            orders=orders_data, dynamic=dynamic,
        )

    cpt_meta  = dynamic.get("_cpt_meta", {})
    tax_meta  = dynamic.get("_tax_meta", {})
    content_map = {
        "posts": posts_data, "pages": pages_data, "media": media_data,
        "comments": comments_data, "scheduled": scheduled_data,
        "users": users_data, "orders": orders_data,
    }
    for slug in cpt_meta:
        content_map[f"cpt:{slug}"] = dynamic.get(f"cpt:{slug}")
    for slug in tax_meta:
        content_map[f"tax:{slug}"] = dynamic.get(f"tax:{slug}")

    # ── Zone 3: Group tabs + active section ──────────────

    def _call(**override):
        kw = dict(view="", site_id=site_id,
                  group_tab=group_tab, std_tab=std_tab,
                  act_tab=act_tab, commerce_tab=commerce_tab,
                  cpt_tab=cpt_tab, tax_tab=tax_tab)
        kw.update(override)
        return ui.Call("__panel__center", **kw)

    def _group_btn(label, key):
        return ui.Button(label,
                         variant="secondary" if group_tab == key else "ghost",
                         size="sm",
                         on_click=_call(group_tab=key))

    def _item_btn(label, key, active, param):
        return ui.Button(label,
                         variant="secondary" if active == key else "ghost",
                         size="sm",
                         on_click=_call(**{param: key}))

    # Group-level tab bar
    group_btns = [
        _group_btn("Standard", "standard"),
        _group_btn("Activity", "activity"),
    ]
    if orders_data is not None:
        group_btns.append(_group_btn("Commerce", "commerce"))
    if cpt_meta:
        group_btns.append(_group_btn("Custom Types", "cpt"))
    if tax_meta:
        group_btns.append(_group_btn("Taxonomies", "tax"))

    group_nav = ui.Stack(direction="h", gap=1, sticky=True, children=group_btns)

    # Active section content
    if group_tab == "activity":
        act_btns = [
            _item_btn("Comments",  "comments",  act_tab, "act_tab"),
            _item_btn("Scheduled", "scheduled", act_tab, "act_tab"),
            _item_btn("Users",     "users",     act_tab, "act_tab"),
        ]
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, wrap=True, children=act_btns),
            _render_content_table(content_map.get(act_tab), act_tab),
        ])

    elif group_tab == "commerce" and orders_data is not None:
        commerce_btns = [
            _item_btn("Overview", "overview", commerce_tab, "commerce_tab"),
            _item_btn("Orders", "orders", commerce_tab, "commerce_tab"),
            _item_btn("Products", "products", commerce_tab, "commerce_tab"),
        ]
        if commerce_tab == "products":
            products_data = await _list(
                "/wp-json/wc/v3/products",
                {"per_page": 20, "orderby": "date", "order": "desc"},
            )
            if products_data is None:
                commerce_body = ui.Alert(
                    message="Could not load WooCommerce products — check the connected user's permissions.",
                    type="info",
                )
            elif not products_data:
                commerce_body = ui.Empty(message="No products found.")
            else:
                commerce_body = ui.DataTable(
                    columns=[
                        ui.DataColumn("name", "Product", sortable=True),
                        ui.DataColumn("sku", "SKU", sortable=True),
                        ui.DataColumn("price", "Price", sortable=True),
                        ui.DataColumn("stock", "Stock", sortable=True),
                        ui.DataColumn("quantity", "Quantity", sortable=True),
                    ],
                    rows=[{
                        "name": item.get("name", ""),
                        "sku": item.get("sku", ""),
                        "price": item.get("price", ""),
                        "stock": item.get("stock_status", ""),
                        "quantity": item.get("stock_quantity") if item.get("stock_quantity") is not None else "—",
                    } for item in products_data],
                )
        elif commerce_tab == "orders":
            commerce_body = _render_content_table(orders_data, "orders")
        else:
            report_data = await _list("/wp-json/wc/v3/reports/sales", {"period": "month"})
            if report_data is None:
                commerce_body = ui.Alert(
                    message="Store summary is unavailable, but orders and products can still be browsed.",
                    type="info",
                )
            else:
                report = report_data[0] if report_data else {}
                currency = report.get("currency", "")
                commerce_body = ui.Stack(gap=3, children=[
                    ui.Stats(columns=4, children=[
                        ui.Stat(label="Orders", value=str(report.get("total_orders", 0)), color="blue"),
                        ui.Stat(label="Net sales", value=f"{report.get('net_sales', '')} {currency}".strip(), color="green"),
                        ui.Stat(label="Average order", value=f"{report.get('average_sales', '')} {currency}".strip(), color="blue"),
                        ui.Stat(label="Refunds", value=f"{report.get('total_refunds', '')} {currency}".strip(), color="yellow"),
                    ]),
                    ui.Text("WooCommerce summary for the current month. All commerce actions are read-only.", variant="caption"),
                ])
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, wrap=True, children=commerce_btns),
            commerce_body,
        ])

    elif group_tab == "cpt" and cpt_meta:
        first_cpt = f"cpt:{list(cpt_meta.keys())[0]}"
        cpt_active = cpt_tab if cpt_tab else first_cpt
        cpt_btns = [_item_btn(m["name"], f"cpt:{s}", cpt_active, "cpt_tab")
                    for s, m in cpt_meta.items()]
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, wrap=True, children=cpt_btns),
            _render_content_table(content_map.get(cpt_active), cpt_active),
        ])

    elif group_tab == "tax" and tax_meta:
        first_tax = f"tax:{list(tax_meta.keys())[0]}"
        tax_active = tax_tab if tax_tab else first_tax
        tax_btns = [_item_btn(m["name"], f"tax:{s}", tax_active, "tax_tab")
                    for s, m in tax_meta.items()]
        tax_slug = tax_active[len("tax:"):]
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, wrap=True, children=tax_btns),
            _render_content_table(content_map.get(tax_active), tax_active),
        ])
        if tax_slug in ("category", "post_tag"):
            active_content = ui.Stack(gap=3, children=[
                active_content,
                _taxonomy_manage_block(content_map.get(tax_active) or [], site_id, tax_slug),
            ])

    else:  # standard (default)
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, children=[
                _item_btn("Posts", "posts", std_tab, "std_tab"),
                _item_btn("Pages", "pages", std_tab, "std_tab"),
                _item_btn("Media", "media", std_tab, "std_tab"),
            ]),
            _render_content_table(content_map.get(std_tab), std_tab),
        ])

    # ── Assemble page ─────────────────────────────────
    page_children = [
        health_row,
        *server_section_children,
        ui.Divider(label="Content"),
        group_nav,
        active_content,
    ]

    return ui.Page(title=name, subtitle=base_url, children=page_children)
