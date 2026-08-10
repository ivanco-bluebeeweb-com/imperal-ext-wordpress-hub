import asyncio
from urllib.parse import urlparse

from imperal_sdk import ui
from app import ext
from wp_client import wp_get, wp_post, wp_title
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
                 cpt_tab="", tax_tab="", manage_tab="menus", menu_sel="",
                 **kwargs):
    if view == "connect":
        return _render_connect_form()
    if view == "add_ssh" and site_id:
        if await storage.has_ssh(ctx, site_id):
            return await _render_detail(ctx, site_id, group_tab, std_tab, act_tab,
                                        commerce_tab, cpt_tab, tax_tab, manage_tab, menu_sel)
        await storage.set_pending_ssh_site(ctx, site_id)
        return _render_add_ssh_form(site_id)
    if site_id:
        return await _render_detail(ctx, site_id, group_tab, std_tab, act_tab,
                                    commerce_tab, cpt_tab, tax_tab, manage_tab, menu_sel)
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

def _comments_management_block(items, site_id):
    """Rich moderation view for comments: per-comment status actions + reply.

    Replaces the old plain DataTable for the Comments activity sub-tab so
    moderation (approve/hold/spam/trash) and replying are actually possible
    from the detail screen instead of read-only.
    """
    if items is None:
        return ui.Alert(message="Could not load comments — check the connection.", type="error")
    if not items:
        return ui.Empty(message="No comments found.")

    def _status_actions(comment_id, status):
        actions = []
        if status != "approved":
            actions.append({"icon": "Check", "label": "Approve",
                            "on_click": ui.Call("set_comment_status", site_id=site_id,
                                                comment_id=comment_id, status="approved")})
        if status != "hold":
            actions.append({"icon": "Clock", "label": "Hold",
                            "on_click": ui.Call("set_comment_status", site_id=site_id,
                                                comment_id=comment_id, status="hold")})
        if status != "spam":
            actions.append({"icon": "AlertTriangle", "label": "Spam",
                            "on_click": ui.Call("set_comment_status", site_id=site_id,
                                                comment_id=comment_id, status="spam"),
                            "confirm": "Mark this comment as spam?"})
        actions.append({"icon": "Trash2", "label": "Trash",
                        "on_click": ui.Call("set_comment_status", site_id=site_id,
                                            comment_id=comment_id, status="trash"),
                        "confirm": "Move this comment to trash?"})
        return actions

    rows = []
    for c in items:
        comment_id = c.get("id")
        status = c.get("status", "")
        snippet = (c.get("content", {}).get("rendered", "") or "") \
                  .replace("<p>", "").replace("</p>", "").strip()
        reply_form = ui.Form(
            action="reply_to_comment", submit_label="Reply",
            defaults={"site_id": site_id, "comment_id": comment_id},
            children=[ui.TextArea(param_name="content", placeholder="Write a reply…", rows=3)],
        )
        edit_form = ui.Form(
            action="edit_comment_content", submit_label="Save edit",
            defaults={"site_id": site_id, "comment_id": comment_id, "content": snippet},
            children=[ui.TextArea(param_name="content", value=snippet, rows=3)],
        )
        rows.append(ui.ListItem(
            id=str(comment_id),
            title=c.get("author_name", "Anonymous"),
            subtitle=snippet[:140],
            meta=f"{status} · {(c.get('date', '') or '')[:10]}",
            badge=ui.Badge(label=status, color=("green" if status == "approved"
                          else "yellow" if status == "hold" else "red")),
            actions=_status_actions(comment_id, status),
            expandable=True,
            expanded_content=[
                ui.Stack(gap=2, children=[
                    ui.Card(title="Reply", content=reply_form),
                    ui.Card(title="Edit comment text", content=edit_form),
                ]),
            ],
        ))
    return ui.List(items=rows)


def _users_management_block(items, site_id):
    """Rich management view for users: delete action + create-user form.

    Replaces the old plain DataTable for the Users activity sub-tab -- the
    connector already has create_user/update_user/delete_user, this just
    wires them into the screen the same way taxonomies are managed below
    their own read-only table.
    """
    role_options = [
        {"value": "administrator", "label": "Administrator"},
        {"value": "editor", "label": "Editor"},
        {"value": "author", "label": "Author"},
        {"value": "contributor", "label": "Contributor"},
        {"value": "subscriber", "label": "Subscriber"},
    ]
    create_form = ui.Card(title="New user", content=ui.Form(
        action="create_user", submit_label="Create user",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="username", placeholder="Username"),
            ui.Input(param_name="email", placeholder="Email"),
            ui.Select(param_name="role", options=role_options, value="subscriber",
                      placeholder="Role"),
            ui.Input(param_name="first_name", placeholder="First name (optional)"),
            ui.Input(param_name="last_name", placeholder="Last name (optional)"),
        ],
    ))

    if items is None:
        return ui.Stack(gap=3, children=[
            ui.Alert(message="Could not load users — check the connection.", type="error"),
            create_form,
        ])
    if not items:
        return ui.Stack(gap=3, children=[ui.Empty(message="No users found."), create_form])

    user_options = [{"value": str(u.get("id", "")), "label": u.get("name", "")} for u in items]
    role_update_form = ui.Card(title="Change role", content=ui.Form(
        action="update_user", submit_label="Update role",
        defaults={"site_id": site_id},
        children=[
            ui.Select(param_name="user_id", options=user_options, placeholder="Choose a user"),
            ui.Select(param_name="role", options=role_options, placeholder="New role"),
        ],
    ))

    rows = [
        ui.ListItem(
            id=str(u.get("id", "")),
            title=u.get("name", ""),
            subtitle=", ".join(u.get("roles", [])) or "no role",
            meta=(u.get("registered_date", "") or "")[:10],
            actions=[{
                "icon": "KeyRound",
                "on_click": ui.Call("reset_user_password", site_id=site_id, user_id=u.get("id")),
                "confirm": f"Send a password-reset email to '{u.get('name', '')}'? Requires the "
                          f"Imperal Bridge plugin on this site.",
            }, {
                "icon": "Trash2",
                "on_click": ui.Call("delete_user", site_id=site_id, user_id=u.get("id")),
                "confirm": f"Delete user '{u.get('name', '')}'? Their posts will be deleted too "
                          f"unless reassigned separately via chat.",
            }],
        )
        for u in items
    ]
    return ui.Stack(gap=3, children=[ui.List(items=rows), role_update_form, create_form])


# ── Post/page lifecycle management (publish/draft/duplicate/delete) ────────────
# update_post/duplicate_post/delete_post existed as chat-tools only, priced but
# never reachable from a click on the detail screen -- this closes that gap for
# the two content types that matter most day-to-day.

def _posts_management_block(items, tab, site_id):
    post_type = "page" if tab == "pages" else "post"
    if items is None:
        return ui.Alert(message="Could not load — check the connection.", type="error")
    if not items:
        return ui.Empty(message=f"No {tab} found.")

    def _row(it):
        pid = it.get("id")
        status = it.get("status", "")
        actions = []
        if status != "publish":
            actions.append({"icon": "Send", "label": "Publish",
                            "on_click": ui.Call("update_post", site_id=site_id, post_id=pid,
                                                post_type=post_type, status="publish")})
        if status != "draft":
            actions.append({"icon": "FileText", "label": "Draft",
                            "on_click": ui.Call("update_post", site_id=site_id, post_id=pid,
                                                post_type=post_type, status="draft")})
        actions.append({"icon": "Copy", "label": "Duplicate",
                        "on_click": ui.Call("duplicate_post", site_id=site_id, post_id=pid,
                                            post_type=post_type)})
        actions.append({"icon": "Trash2", "label": "Delete",
                        "on_click": ui.Call("delete_post", site_id=site_id, post_id=pid,
                                            post_type=post_type),
                        "confirm": f"Move \"{wp_title(it)}\" to Trash?"})
        password_form = ui.Form(
            action="set_post_password", submit_label="Set/clear password",
            defaults={"site_id": site_id, "post_id": pid, "post_type": post_type},
            children=[ui.Input(param_name="password",
                               placeholder="Password to view this — leave empty to remove protection")],
        )
        return ui.ListItem(
            id=str(pid), title=wp_title(it),
            subtitle=status, meta=(it.get("date", "") or "")[:10],
            actions=actions,
            expandable=True,
            expanded_content=[ui.Card(title="Password protection", content=password_form)],
        )

    return ui.List(items=[_row(it) for it in items])


# ── Media library (upload by URL + alt text) ────────────────────────────────────
# upload_media/update_media_alt existed as chat-tools only; the Media sub-tab
# was a plain read-only DataTable (title + mime type) despite full write
# support already being built and priced. set_single_media_alt is a thin
# per-row wrapper around update_media_alt's items[] shape, since a panel Form
# can only submit flat fields, not a nested list.

def _media_management_block(items, site_id):
    upload_form = ui.Card(title="Add image from URL", content=ui.Form(
        action="upload_media", submit_label="Add to media library",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="source_url", placeholder="https://example.com/image.jpg"),
            ui.Input(param_name="alt_text", placeholder="Alt text (optional)"),
            ui.Input(param_name="caption", placeholder="Caption (optional)"),
        ],
    ))
    if items is None:
        return ui.Stack(gap=3, children=[
            ui.Alert(message="Could not load media library — check the connection.", type="error"),
            upload_form,
        ])
    if not items:
        return ui.Stack(gap=3, children=[ui.Empty(message="No media found."), upload_form])

    def _row(it):
        mid = it.get("id")
        alt = it.get("alt_text") or ""
        alt_form = ui.Form(
            action="set_single_media_alt", submit_label="Save alt text",
            defaults={"site_id": site_id, "media_id": mid},
            children=[ui.Input(param_name="alt_text", value=alt,
                               placeholder="Describe this image for screen readers / Google Images")],
        )
        return ui.ListItem(
            id=str(mid), title=wp_title(it),
            subtitle=it.get("mime_type", ""),
            meta=("no alt text" if not alt.strip() else alt[:60]),
            badge=(ui.Badge(label="missing alt", color="yellow") if not alt.strip() else None),
            expandable=True,
            expanded_content=[ui.Card(title="Alt text", content=alt_form)],
        )

    return ui.Stack(gap=3, children=[
        ui.List(items=[_row(it) for it in items]),
        upload_form,
    ])


# ── Product reviews (WooCommerce) moderation ───────────────────────────────────
# list_product_reviews/set_product_review_status/reply_to_product_review existed
# as chat-tools only; store owners had no click path to moderate the reviews
# actually driving purchase decisions on their catalogue.

def _render_reviews_block(items, site_id):
    if items is None:
        return ui.Alert(message="Could not load product reviews — check the connected "
                                "user's permissions.", type="info")
    if not items:
        return ui.Empty(message="No product reviews found.")

    def _row(it):
        rid = it.get("id")
        status = it.get("status", "")
        rating = it.get("rating", 0) or 0
        stars = "★" * int(rating) + "☆" * (5 - int(rating))
        snippet = (it.get("review", "") or "").replace("<p>", "").replace("</p>", "")[:160].strip()
        actions = []
        if status != "approved":
            actions.append({"icon": "Check", "label": "Approve",
                            "on_click": ui.Call("set_product_review_status", site_id=site_id,
                                                review_id=rid, status="approved")})
        if status != "hold":
            actions.append({"icon": "Clock", "label": "Hold",
                            "on_click": ui.Call("set_product_review_status", site_id=site_id,
                                                review_id=rid, status="hold")})
        if status != "spam":
            actions.append({"icon": "AlertTriangle", "label": "Spam",
                            "on_click": ui.Call("set_product_review_status", site_id=site_id,
                                                review_id=rid, status="spam"),
                            "confirm": "Mark this review as spam?"})
        actions.append({"icon": "Trash2", "label": "Trash",
                        "on_click": ui.Call("set_product_review_status", site_id=site_id,
                                            review_id=rid, status="trash"),
                        "confirm": "Move this review to Trash?"})
        return ui.ListItem(
            id=str(rid), title=f"{it.get('reviewer', 'Anonymous')} — {stars}",
            subtitle=snippet, meta=f"{status} · product #{it.get('product_id', '')}",
            actions=actions,
        )

    reply_form = ui.Form(
        action="reply_to_product_review", submit_label="Send reply",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="review_id", placeholder="Review id"),
            ui.Input(param_name="content", placeholder="Reply text"),
        ],
    )
    return ui.Stack(gap=3, children=[
        ui.List(items=[_row(it) for it in items]),
        ui.Card(title="Reply to a review", content=reply_form),
    ])


# ── Customers (WooCommerce) ─────────────────────────────────────────────────────
# list_customers/create_customer existed as chat-tools only, priced but with no
# click path anywhere on the detail screen -- store owners had to know to ask
# for a customer list by name instead of just clicking a tab.

def _render_customers_block(items, site_id):
    if items is None:
        return ui.Alert(message="Could not load customers — check the connected "
                                "user's permissions.", type="info")
    create_form = ui.Card(title="New customer", content=ui.Form(
        action="create_customer", submit_label="Create customer",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="email", placeholder="Email"),
            ui.Input(param_name="first_name", placeholder="First name (optional)"),
            ui.Input(param_name="last_name", placeholder="Last name (optional)"),
        ],
    ))
    if not items:
        return ui.Stack(gap=3, children=[ui.Empty(message="No customers found."), create_form])

    def _row(it):
        cid = it.get("id")
        edit_form = ui.Form(
            action="update_customer", submit_label="Save",
            defaults={"site_id": site_id, "customer_id": cid},
            children=[
                ui.Input(param_name="email", value=it.get("email", ""), placeholder="Email"),
                ui.Input(param_name="first_name", value=it.get("first_name", ""), placeholder="First name"),
                ui.Input(param_name="last_name", value=it.get("last_name", ""), placeholder="Last name"),
            ],
        )
        return ui.ListItem(
            id=str(cid),
            title=" ".join(p for p in (it.get("first_name", ""), it.get("last_name", "")) if p)
                  or it.get("username", "Customer"),
            subtitle=it.get("email", ""),
            meta=f"{it.get('orders_count', 0)} order(s) · {it.get('total_spent', '')}",
            actions=[{"icon": "Trash2", "label": "Delete",
                      "on_click": ui.Call("delete_customer", site_id=site_id, customer_id=cid),
                      "confirm": f"Permanently delete customer '{it.get('email', cid)}'? "
                                 "Their past orders keep their own stored billing snapshot."}],
            expandable=True,
            expanded_content=[ui.Card(title="Edit customer", content=edit_form)],
        )

    return ui.Stack(gap=3, children=[ui.List(items=[_row(it) for it in items]), create_form])


# ── Orders (WooCommerce) ─────────────────────────────────────────────────────────
# update_order_status/update_order_status_risky/add_private_order_note/
# add_customer_order_note existed as chat-tools only -- the Orders sub-tab was
# a plain read-only DataTable despite full order-management write support.
# Risky statuses (cancelled/failed/refunded) route through the destructive
# confirmation gate automatically -- update_order_status_risky is only ever
# offered for those three, never for the routine ones.

_ORDER_STATUS_OPTIONS = [
    {"value": "pending", "label": "Pending payment"},
    {"value": "on-hold", "label": "On hold"},
    {"value": "processing", "label": "Processing"},
    {"value": "completed", "label": "Completed"},
    {"value": "cancelled", "label": "Cancelled"},
    {"value": "failed", "label": "Failed"},
    {"value": "refunded", "label": "Refunded"},
]
_RISKY_ORDER_STATUSES = {"cancelled", "failed", "refunded"}


def _render_orders_block(items, site_id):
    if items is None:
        return ui.Alert(message="Could not load WooCommerce orders — check the "
                                "connected user's permissions.", type="info")
    if not items:
        return ui.Empty(message="No orders found.")

    def _row(it):
        oid = it.get("id")
        status = it.get("status", "")
        status_form = ui.Form(
            action="update_order_status", submit_label="Update status",
            defaults={"site_id": site_id, "order_id": oid},
            children=[
                ui.Select(param_name="status", value=status, placeholder="New status",
                         options=[o for o in _ORDER_STATUS_OPTIONS
                                  if o["value"] not in _RISKY_ORDER_STATUSES]),
            ],
        )
        risky_form = ui.Form(
            action="update_order_status_risky", submit_label="Apply (confirm required)",
            defaults={"site_id": site_id, "order_id": oid},
            children=[
                ui.Select(param_name="status", placeholder="Cancel / fail / refund",
                         options=[o for o in _ORDER_STATUS_OPTIONS
                                  if o["value"] in _RISKY_ORDER_STATUSES]),
            ],
        )
        note_form = ui.Form(
            action="add_private_order_note", submit_label="Add note",
            defaults={"site_id": site_id, "order_id": oid},
            children=[ui.Input(param_name="note", placeholder="Internal note (not seen by customer)")],
        )
        customer_note_form = ui.Form(
            action="add_customer_order_note", submit_label="Send note to customer (confirm required)",
            defaults={"site_id": site_id, "order_id": oid, "customer_visible": True},
            children=[ui.Input(param_name="note", placeholder="Note visible to the customer — WooCommerce may email it")],
        )
        resend_email_form = ui.Form(
            action="resend_order_email", submit_label="Resend order email",
            defaults={"site_id": site_id, "order_id": oid},
            children=[
                ui.Select(param_name="template_id", placeholder="Order details (default)",
                          options=[
                              {"value": "", "label": "Order details (default)"},
                              {"value": "customer_processing_order", "label": "Processing order"},
                              {"value": "customer_completed_order", "label": "Completed order"},
                              {"value": "customer_on_hold_order", "label": "On-hold order"},
                              {"value": "customer_invoice", "label": "Invoice / order details"},
                          ]),
                ui.Input(param_name="email", placeholder="Send to a different address (optional)"),
            ],
        )
        return ui.ListItem(
            id=str(oid), title=f"Order #{oid}",
            subtitle=f"{it.get('total', '')} {it.get('currency', '')}".strip(),
            meta=f"{status} · {(it.get('date_created', '') or '')[:10]}",
            expandable=True,
            expanded_content=[
                ui.Stack(gap=2, children=[
                    ui.Card(title="Change status", content=status_form),
                    ui.Card(title="Cancel / fail / refund status", content=risky_form),
                    ui.Card(title="Add private note", content=note_form),
                    ui.Card(title="Add customer-visible note", content=customer_note_form),
                    ui.Card(title="Resend order email", content=resend_email_form),
                ]),
            ],
        )

    return ui.List(items=[_row(it) for it in items])


# ── Coupons (WooCommerce) ────────────────────────────────────────────────────────
# list_coupons/create_coupon/archive_coupon existed as chat-tools only -- same
# gap as customers above, closed the same way (list with a per-row action,
# create form underneath).

# ── Products (WooCommerce) ───────────────────────────────────────────────────────
# create_product/archive_product existed as chat-tools only -- the Products
# sub-tab was a plain read-only DataTable despite full catalogue write support.

def _render_products_block(items, site_id):
    if items is None:
        return ui.Alert(message="Could not load WooCommerce products — check the "
                                "connected user's permissions.", type="info")
    create_form = ui.Card(title="New product", content=ui.Form(
        action="create_product", submit_label="Create product",
        defaults={"site_id": site_id, "status": "draft"},
        children=[
            ui.Input(param_name="name", placeholder="Product name"),
            ui.Input(param_name="regular_price", placeholder="Regular price (optional)"),
            ui.Input(param_name="sku", placeholder="SKU (optional)"),
            ui.Select(param_name="status", placeholder="Status", value="draft", options=[
                {"value": "draft", "label": "Draft"},
                {"value": "publish", "label": "Publish"},
                {"value": "pending", "label": "Pending review"},
                {"value": "private", "label": "Private"},
            ]),
        ],
    ))
    if not items:
        return ui.Stack(gap=3, children=[ui.Empty(message="No products found."), create_form])

    def _row(it):
        pid = it.get("id")
        status = it.get("status", "")
        actions = []
        if status != "trash":
            actions.append({"icon": "Trash2", "label": "Archive",
                            "on_click": ui.Call("archive_product", site_id=site_id, product_id=pid),
                            "confirm": f"Move product '{it.get('name', '')}' to Trash?"})
        edit_form = ui.Form(
            action="update_product", submit_label="Save",
            defaults={"site_id": site_id, "product_id": pid},
            children=[
                ui.Input(param_name="name", value=it.get("name", ""), placeholder="Product name"),
                ui.Input(param_name="regular_price", value=it.get("regular_price", "") or "",
                         placeholder="Regular price"),
                ui.Input(param_name="sku", value=it.get("sku", "") or "", placeholder="SKU"),
                ui.Input(param_name="stock_quantity", value=str(it.get("stock_quantity", "") or ""),
                         placeholder="Stock quantity"),
                ui.Select(param_name="status", value=status or "draft", placeholder="Status", options=[
                    {"value": "draft", "label": "Draft"},
                    {"value": "publish", "label": "Publish"},
                    {"value": "pending", "label": "Pending review"},
                    {"value": "private", "label": "Private"},
                ]),
            ],
        )
        return ui.ListItem(
            id=str(pid), title=it.get("name", ""),
            subtitle=f"SKU {it.get('sku', '') or '—'} · {it.get('price', '')}",
            meta=f"{status} · {it.get('stock_status', '')} ({it.get('stock_quantity', 0) or 0})",
            actions=actions,
            expandable=True,
            expanded_content=[ui.Card(title="Edit product", content=edit_form)],
        )

    return ui.Stack(gap=3, children=[ui.List(items=[_row(it) for it in items]), create_form])


def _render_coupons_block(items, site_id):
    if items is None:
        return ui.Alert(message="Could not load coupons — check the connected "
                                "user's permissions.", type="info")
    create_form = ui.Card(title="New coupon", content=ui.Form(
        action="create_coupon", submit_label="Create coupon",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="code", placeholder="Coupon code, e.g. SUMMER10"),
            ui.Select(param_name="discount_type", options=[
                {"value": "percent", "label": "Percentage"},
                {"value": "fixed_cart", "label": "Fixed amount off cart"},
                {"value": "fixed_product", "label": "Fixed amount off product"},
            ], value="percent", placeholder="Discount type"),
            ui.Input(param_name="amount", placeholder="Amount, e.g. 10"),
        ],
    ))
    if not items:
        return ui.Stack(gap=3, children=[ui.Empty(message="No coupons found."), create_form])

    def _row(it):
        cid = it.get("id")
        status = it.get("status", "")
        discount = f"{it.get('amount', '')}"
        if it.get("discount_type") == "percent":
            discount += "%"
        actions = []
        if status != "trash":
            actions.append({"icon": "Trash2", "label": "Archive",
                            "on_click": ui.Call("archive_coupon", site_id=site_id, coupon_id=cid),
                            "confirm": f"Move coupon '{it.get('code', '')}' to Trash?"})
        edit_form = ui.Form(
            action="update_coupon", submit_label="Save",
            defaults={"site_id": site_id, "coupon_id": cid},
            children=[
                ui.Input(param_name="amount", value=it.get("amount", ""), placeholder="Amount"),
                ui.Input(param_name="date_expires", value=it.get("date_expires", "") or "",
                         placeholder="Expiry YYYY-MM-DD (empty clears it)"),
            ],
        )
        return ui.ListItem(
            id=str(cid), title=it.get("code", ""),
            subtitle=f"{discount} off · used {it.get('usage_count', 0)} time(s)",
            meta=(f"expires {it.get('date_expires', '')}" if it.get("date_expires") else status),
            actions=actions,
            expandable=True,
            expanded_content=[ui.Card(title="Edit coupon", content=edit_form)],
        )

    return ui.Stack(gap=3, children=[ui.List(items=[_row(it) for it in items]), create_form])


# ── Product categories (WooCommerce) ─────────────────────────────────────────────
# list_product_categories/create_product_category existed as chat-tools only --
# no click path anywhere on the detail screen despite full read+write support.

def _render_product_categories_block(items, site_id):
    if items is None:
        return ui.Alert(message="Could not load product categories — check the "
                                "connected user's permissions.", type="info")
    create_form = ui.Card(title="New category", content=ui.Form(
        action="create_product_category", submit_label="Create category",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="name", placeholder="Category name"),
            ui.Input(param_name="parent_id", placeholder="Parent category id (optional, 0 = top level)"),
        ],
    ))
    if not items:
        return ui.Stack(gap=3, children=[ui.Empty(message="No product categories found."), create_form])

    rows = [
        ui.ListItem(
            id=str(it.get("id", "")),
            title=it.get("name", ""),
            subtitle=f"{it.get('count', 0)} product(s)",
            meta=(f"parent #{it.get('parent')}" if it.get("parent") else "top level"),
        )
        for it in items
    ]
    return ui.Stack(gap=3, children=[ui.List(items=rows), create_form])


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


# ── Manage tab (menus / redirects / settings / plugins) ────────────────────────

async def _render_manage_tab(ctx, site_id, base_url, username, pw, manage_tab, menu_sel, call):
    """Site management: nav menus, Rank Math redirects, native settings, plugins.

    All four sections talk to write handlers that were built and priced but,
    until now, had no UI wiring anywhere on the detail screen — this closes
    that gap. Fetched live (low-traffic admin section, no cache needed).
    """
    async def _get(path, params=None):
        try:
            r = await wp_get(ctx, base_url, path, username=username, app_password=pw,
                             params=params or {})
            return r
        except Exception:
            return None

    def _manage_btn(label, key):
        return ui.Button(label, variant="secondary" if manage_tab == key else "ghost",
                         size="sm", on_click=call(manage_tab=key))

    manage_btns = [
        _manage_btn("Menus", "menus"),
        _manage_btn("Redirects", "redirects"),
        _manage_btn("SEO", "seo"),
        _manage_btn("Settings", "settings"),
        _manage_btn("Plugins", "plugins"),
    ]

    if manage_tab == "redirects":
        body = await _render_redirects_block(ctx, site_id, base_url, username, pw)
    elif manage_tab == "seo":
        body = await _render_rankmath_block(ctx, site_id, base_url, username, pw)
    elif manage_tab == "settings":
        body = await _render_settings_block(ctx, site_id, base_url, username, pw)
    elif manage_tab == "plugins":
        body = await _render_plugins_block(ctx, site_id, base_url, username, pw)
    else:
        body = await _render_menus_block(ctx, site_id, base_url, username, pw, menu_sel, call)

    return ui.Stack(gap=3, children=[
        ui.Stack(direction="h", gap=1, wrap=True, children=manage_btns),
        body,
    ])


async def _render_menus_block(ctx, site_id, base_url, username, pw, menu_sel, call):
    r = await wp_get(ctx, base_url, "/wp-json/wp/v2/menus", username=username, app_password=pw,
                     params={"per_page": 50})
    if r is None or r.status_code == 404:
        return ui.Alert(
            message="This site's WordPress version doesn't expose the menus REST API "
                    "(needs WordPress 5.9+).",
            type="info")
    if r.status_code in (401, 403):
        return ui.Alert(message="The connected user cannot manage menus.", type="error")
    if r.status_code != 200 or not isinstance(r.body, list):
        return ui.Alert(message="Could not load menus — check the connection.", type="error")
    menus = r.body
    if not menus:
        return ui.Empty(message="No navigation menus found on this site.")

    menu_options = [{"value": str(m.get("id", "")), "label": m.get("name", "")} for m in menus]
    active_menu_id = menu_sel or menu_options[0]["value"]

    menus_table = ui.DataTable(
        columns=[ui.DataColumn("name", "Menu", sortable=True),
                 ui.DataColumn("locations", "Locations", sortable=False),
                 ui.DataColumn("items", "Items", sortable=True)],
        rows=[{"name": m.get("name", ""),
               "locations": ", ".join(m.get("locations", []) or []) or "—",
               "items": str(m.get("count", 0))} for m in menus],
        on_row_click=None,
    )

    items_r = await wp_get(ctx, base_url, "/wp-json/wp/v2/menu-items",
                           username=username, app_password=pw,
                           params={"menus": active_menu_id, "per_page": 100})
    items = items_r.body if items_r and items_r.status_code == 200 and isinstance(items_r.body, list) else []

    item_rows = []
    for it in sorted(items, key=lambda x: x.get("menu_order", 0)):
        mi_id = it.get("id")
        mi_title = it.get("title", {}).get("rendered", "") if isinstance(it.get("title"), dict) else str(it.get("title", ""))
        edit_form = ui.Form(
            action="update_menu_item", submit_label="Save",
            defaults={"site_id": site_id, "menu_item_id": mi_id},
            children=[
                ui.Input(param_name="title", value=mi_title, placeholder="Link text"),
                ui.Input(param_name="url", value=it.get("url", ""), placeholder="Destination URL"),
            ],
        )
        item_rows.append(ui.ListItem(
            id=str(mi_id),
            title=mi_title,
            subtitle=it.get("url", ""),
            actions=[
                {"icon": "Trash2", "label": "Remove",
                 "on_click": ui.Call("delete_menu_item", site_id=site_id, menu_item_id=mi_id),
                 "confirm": "Remove this item from the menu?"},
            ],
            expandable=True,
            expanded_content=[ui.Card(title="Edit item", content=edit_form)],
        ))
    items_list = ui.List(items=item_rows) if item_rows else ui.Empty(message="This menu has no items yet.")

    add_item_form = ui.Form(
        action="create_menu_item", submit_label="Add item",
        defaults={"site_id": site_id, "menu_id": active_menu_id},
        children=[
            ui.Input(param_name="title", placeholder="Link text, e.g. Contact"),
            ui.Input(param_name="url", placeholder="https:// or existing page URL"),
        ],
    )

    return ui.Stack(gap=3, children=[
        menus_table,
        ui.Select(param_name="menu_sel", options=menu_options, value=active_menu_id,
                  placeholder="Choose a menu",
                  on_change=call(menu_sel="{{value}}")),
        ui.Card(title=f"Items in \"{next((o['label'] for o in menu_options if o['value'] == active_menu_id), '')}\"",
               content=items_list),
        ui.Card(title="Add menu item", content=add_item_form),
    ])


async def _render_redirects_block(ctx, site_id, base_url, username, pw):
    r = await wp_get(ctx, base_url, "/wp-json/imperal/v1/redirects", username=username,
                     app_password=pw, params={"status": "all"})
    if r is None or r.status_code == 404:
        return ui.Alert(
            message="Redirects need the Imperal Bridge plugin (with Rank Math's Redirections "
                    "module enabled) — install/update it on this site first.",
            type="info")
    if r.status_code in (401, 403):
        return ui.Alert(message="The connected user cannot manage redirects.", type="error")
    if r.status_code != 200:
        return ui.Alert(message="Could not load redirects — check the connection.", type="error")
    data = r.body if isinstance(r.body, list) else (r.body or {}).get("redirects", [])
    if not isinstance(data, list):
        data = []

    rows_ui = []
    for item in data:
        sources = item.get("sources", []) or []
        pattern = sources[0].get("pattern", "") if sources else ""
        status = item.get("status", "active")
        rid = item.get("id")
        rows_ui.append(ui.ListItem(
            id=str(rid),
            title=pattern or "(no pattern)",
            subtitle=f"→ {item.get('url_to', '')}  [{item.get('header_code', 301)}]",
            meta=f"{status} · {item.get('hits', 0)} hit(s)",
            actions=[
                {"icon": "Pause" if status == "active" else "Play",
                 "label": "Deactivate" if status == "active" else "Activate",
                 "on_click": ui.Call("set_redirect_status", site_id=site_id, redirect_id=rid,
                                     status="inactive" if status == "active" else "active")},
                {"icon": "Trash2", "label": "Delete",
                 "on_click": ui.Call("delete_redirect", site_id=site_id, redirect_id=rid),
                 "confirm": "Delete this redirect?"},
            ],
        ))
    redirects_list = ui.List(items=rows_ui) if rows_ui else ui.Empty(message="No redirects yet.")

    create_form = ui.Form(
        action="create_redirect", submit_label="Create redirect",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="source_pattern", placeholder="/old-page/"),
            ui.Input(param_name="url_to", placeholder="https://example.com/new-page/"),
            ui.Select(param_name="header_code",
                     options=[{"value": "301", "label": "301 Permanent"},
                              {"value": "302", "label": "302 Temporary"},
                              {"value": "410", "label": "410 Gone"}],
                     value="301"),
        ],
    )

    return ui.Stack(gap=3, children=[
        redirects_list,
        ui.Card(title="New redirect", content=create_form),
    ])


async def _render_rankmath_block(ctx, site_id, base_url, username, pw):
    """Rank Math site-wide: sitemap module status, robots.txt override editor,
    404 Monitor log (Imperal Bridge SECTION 7), and Instant Indexing / IndexNow
    (Rank Math's OWN native REST routes, no Bridge required). Per-post SEO
    fields (title/description/focus keyword/schema type) live on each post's
    own edit view via get_seo_meta/update_seo_meta, not here.
    """
    sections = []

    # ── Instant Indexing (IndexNow) — native Rank Math REST, works with or
    # without the Bridge plugin, so it is fetched and rendered independently.
    indexnow_r = await wp_post(ctx, base_url, "/wp-json/rankmath/v1/in/getLog",
                               username=username, app_password=pw, json={"filter": "all"})
    if indexnow_r is not None and indexnow_r.status_code == 200 and isinstance(indexnow_r.body, dict):
        entries = indexnow_r.body.get("data", [])
        submit_form = ui.Form(
            action="submit_urls_to_indexnow", submit_label="Submit URLs",
            defaults={"site_id": site_id},
            children=[
                ui.TextArea(param_name="urls", placeholder="https://example.com/page-1/\nhttps://example.com/page-2/",
                            rows=3),
            ],
        )
        if isinstance(entries, list) and entries:
            log_items = [
                ui.ListItem(
                    id=str(idx), title=e.get("url", ""),
                    subtitle=f"{'manual' if e.get('manual_submission') else 'auto'} · status {e.get('status', '')}",
                    meta=e.get("time_human_readable", "") or e.get("message", ""),
                )
                for idx, e in enumerate(entries[:20])
            ]
            log_body = ui.List(items=log_items)
        else:
            log_body = ui.Empty(message="No IndexNow submissions logged yet.")
        sections.append(ui.Card(
            title="Instant Indexing (IndexNow)",
            content=ui.Stack(gap=2, children=[
                ui.Text("Notify Bing, Yandex and other participating search engines the moment "
                        "a page changes.", variant="caption"),
                submit_form,
                ui.Button("Clear log", icon="Trash2", variant="ghost",
                          on_click=ui.Call("clear_indexnow_log", site_id=site_id, filter="all")),
                log_body,
            ]),
        ))
    elif indexnow_r is not None and indexnow_r.status_code == 404:
        sections.append(ui.Alert(
            message="Instant Indexing needs Rank Math's own Instant Indexing module enabled "
                    "on this site (Rank Math → Dashboard → Advanced Mode → Instant Indexing).",
            type="info"))

    sitemap_r = await wp_get(ctx, base_url, "/wp-json/imperal/v1/rankmath/sitemap-status",
                             username=username, app_password=pw)
    robots_r = await wp_get(ctx, base_url, "/wp-json/imperal/v1/rankmath/robots-txt",
                            username=username, app_password=pw)
    hits_r = await wp_get(ctx, base_url, "/wp-json/imperal/v1/rankmath/404-logs",
                          username=username, app_password=pw, params={"limit": 50})

    if sitemap_r is None or sitemap_r.status_code == 404:
        sections.append(ui.Alert(
            message="Sitemap/robots.txt/404 Monitor data needs the Imperal Bridge plugin "
                    "(version 2.4.0+) — install/update it on this site first.",
            type="info"))
        return ui.Stack(gap=3, children=sections) if sections else ui.Empty(
            message="Could not load Rank Math data — check the connection.")
    if sitemap_r.status_code in (401, 403):
        sections.append(ui.Alert(message="The connected user cannot read Rank Math settings.", type="error"))
        return ui.Stack(gap=3, children=sections)

    # ── Sitemap status ──
    if sitemap_r.status_code == 200 and isinstance(sitemap_r.body, dict):
        sm = sitemap_r.body
        active = bool(sm.get("module_active"))
        sections.append(ui.Card(
            title="Sitemap",
            content=ui.Stack(gap=2, children=[
                ui.Alert(
                    message=(f"Sitemap module is active — {sm.get('sitemap_url', '')}"
                              if active else
                              "Rank Math's Sitemap module is not active on this site."),
                    type="success" if active else "info"),
            ]),
        ))

    # ── robots.txt override ──
    if robots_r is not None and robots_r.status_code == 200 and isinstance(robots_r.body, dict):
        rb = robots_r.body
        robots_form = ui.Form(
            action="update_robots_txt", submit_label="Save robots.txt override",
            defaults={"site_id": site_id},
            children=[
                ui.TextArea(param_name="content", value=rb.get("content", ""), rows=8,
                            placeholder="User-agent: *\nDisallow: /wp-admin/"),
            ],
        )
        status_note = ("Active — served in place of WordPress's own robots.txt"
                        if rb.get("is_active") else
                        "Not active — WordPress's own default robots.txt is served instead "
                        "(save non-empty text here, or check the site is public, to activate it)")
        sections.append(ui.Card(
            title="robots.txt override",
            content=ui.Stack(gap=2, children=[
                ui.Text(status_note, variant="caption"),
                robots_form,
            ]),
        ))

    # ── 404 Monitor log ──
    if hits_r is not None and hits_r.status_code == 200 and isinstance(hits_r.body, dict):
        hits = hits_r.body.get("hits", [])
        if isinstance(hits, list) and hits:
            rows_ui = [
                ui.ListItem(
                    id=str(h.get("id", "")),
                    title=h.get("uri", ""),
                    subtitle=f"hit {h.get('times_accessed', 0)}x · last {h.get('accessed', '')}",
                    meta=h.get("referer", "") or "(no referer)",
                    actions=[
                        {"icon": "Trash2", "label": "Delete",
                         "on_click": ui.Call("delete_404_hit", site_id=site_id, hit_id=h.get("id")),
                         "confirm": "Delete this 404 log entry?"},
                    ],
                )
                for h in hits
            ]
            hits_body = ui.List(items=rows_ui)
        elif isinstance(hits, list):
            hits_body = ui.Empty(message="No 404 hits logged yet.")
        else:
            hits_body = ui.Alert(message="Rank Math's 404 Monitor module is not active on this site.",
                                 type="info")
        sections.append(ui.Card(title="404 Monitor", content=hits_body))
    elif hits_r is not None and hits_r.status_code == 404:
        sections.append(ui.Alert(
            message="Rank Math's 404 Monitor module is not active on this site.", type="info"))

    # ── llms.txt (AI-crawler guidance file) ──
    llms_r = await wp_get(ctx, base_url, "/wp-json/imperal/v1/llmstxt",
                          username=username, app_password=pw)
    if llms_r is not None and llms_r.status_code == 200 and isinstance(llms_r.body, dict):
        lb = llms_r.body
        active = bool(lb.get("module_active"))
        # Real post types/taxonomies from WordPress core's own REST discovery —
        # never a hardcoded guess, since custom post types/taxonomies vary per site.
        types_r, taxes_r = await asyncio.gather(
            wp_get(ctx, base_url, "/wp-json/wp/v2/types", username=username, app_password=pw),
            wp_get(ctx, base_url, "/wp-json/wp/v2/taxonomies", username=username, app_password=pw),
        )
        types_body = types_r.body if types_r.status_code == 200 and isinstance(types_r.body, dict) else {}
        taxes_body = taxes_r.body if taxes_r.status_code == 200 and isinstance(taxes_r.body, dict) else {}
        post_type_opts = [{"label": i.get("name", s), "value": s}
                          for s, i in types_body.items() if s != "attachment"]
        taxonomy_opts = [{"label": i.get("name", s), "value": s}
                         for s, i in taxes_body.items() if s not in ("nav_menu", "link_category", "post_format")]
        llms_form = ui.Form(
            action="update_llms_txt_settings", submit_label="Save llms.txt settings",
            defaults={"site_id": site_id},
            children=[
                ui.MultiSelect(param_name="post_types", options=post_type_opts,
                               values=lb.get("post_types", [])),
                ui.MultiSelect(param_name="taxonomies", options=taxonomy_opts,
                               values=lb.get("taxonomies", [])),
                ui.Input(param_name="limit", value=str(lb.get("limit", 100)),
                         placeholder="Max links per type (number)"),
                ui.TextArea(param_name="extra_content", value=lb.get("extra_content", ""),
                           rows=4, placeholder="Extra Markdown appended to llms.txt"),
            ],
        )
        sections.append(ui.Card(
            title="llms.txt (AI-crawler guidance file)",
            content=ui.Stack(gap=2, children=[
                ui.Alert(
                    message=(f"Active — served at {lb.get('llms_txt_url', '')}" if active else
                              "Not active yet — enable Rank Math's llms-txt module first "
                              "(Rank Math → Dashboard → Advanced Mode → LLMS Txt), settings "
                              "below are saved either way"),
                    type="success" if active else "info"),
                llms_form,
            ]),
        ))
    elif llms_r is not None and llms_r.status_code == 404:
        sections.append(ui.Alert(
            message="llms.txt settings need the Imperal Bridge plugin (version 2.5.0+) — "
                    "install/update it on this site first.",
            type="info"))

    return ui.Stack(gap=3, children=sections) if sections else ui.Empty(
        message="Could not load Rank Math data — check the connection.")


async def _render_settings_block(ctx, site_id, base_url, username, pw):
    r = await wp_get(ctx, base_url, "/wp-json/wp/v2/settings", username=username, app_password=pw)
    if r is None or r.status_code == 404:
        return ui.Alert(message="This site's WordPress version doesn't expose /wp/v2/settings "
                                "(needs WordPress 5.5+).", type="info")
    if r.status_code in (401, 403):
        return ui.Alert(message="The connected user cannot manage site settings — "
                                "reconnect with an administrator Application Password.", type="error")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return ui.Alert(message="Could not load site settings — check the connection.", type="error")
    s = r.body

    form = ui.Form(
        action="update_site_settings", submit_label="Save settings",
        defaults={"site_id": site_id},
        children=[
            ui.Input(param_name="title", value=s.get("title", ""), placeholder="Site title"),
            ui.Input(param_name="description", value=s.get("description", ""),
                     placeholder="Tagline"),
            ui.Input(param_name="timezone_string", value=s.get("timezone_string", ""),
                     placeholder="Europe/Chisinau"),
        ],
    )
    return ui.Card(title="Site settings", content=form)


async def _render_plugins_block(ctx, site_id, base_url, username, pw):
    r = await wp_get(ctx, base_url, "/wp-json/wp/v2/plugins", username=username, app_password=pw,
                     params={"per_page": 100})
    if r is None or r.status_code == 404:
        return ui.Alert(message="This site's WordPress version doesn't expose /wp/v2/plugins "
                                "(needs WordPress 5.5+).", type="info")
    if r.status_code in (401, 403):
        return ui.Alert(message="The connected user cannot manage plugins — "
                                "reconnect with an administrator Application Password.", type="error")
    if r.status_code != 200 or not isinstance(r.body, list):
        return ui.Alert(message="Could not load plugins — check the connection.", type="error")
    plugins = r.body
    if not plugins:
        return ui.Empty(message="No plugins found.")

    rows_ui = []
    for p in plugins:
        plugin_id = p.get("plugin", "")
        name = p.get("name", plugin_id)
        if isinstance(name, dict):
            name = name.get("rendered", plugin_id)
        status = p.get("status", "inactive")
        rows_ui.append(ui.ListItem(
            id=plugin_id, title=name or plugin_id,
            subtitle=f"v{p.get('version', '')}", meta=status,
            actions=[
                {"icon": "Power" if status != "active" else "PowerOff",
                 "label": "Activate" if status != "active" else "Deactivate",
                 "on_click": ui.Call("deactivate_plugin" if status == "active" else "activate_plugin",
                                     site_id=site_id, plugin=plugin_id)},
            ],
        ))
    return ui.List(items=rows_ui)


# ── Site detail ───────────────────────────────────────────────────────────────

async def _render_detail(ctx, site_id,
                         group_tab="standard",
                         std_tab="posts", act_tab="comments", commerce_tab="overview",
                         cpt_tab="", tax_tab="", manage_tab="menus", menu_sel=""):
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
    bridge_outdated = record.get("bridge_outdated", "")
    if not wp_ver:
        if bridge_outdated:
            server_section_children = [
                ui.Divider(label="Server"),
                ui.Alert(
                    message=(
                        f"Imperal Bridge on this site is version {bridge_outdated} — too old for "
                        "server info (added in 2.1.0). Update the plugin on the site (Plugins → "
                        "Imperal Bridge → update, or reinstall from the zip below); SSH is not "
                        "needed once it's updated."
                    ),
                    type="warning",
                ),
                ui.Stack(direction="h", align="center", gap=3, children=[
                    ui.Button("Download latest Imperal Bridge", icon="Download",
                              variant="ghost", size="sm", on_click=ui.Open(BRIDGE_DOWNLOAD_URL)),
                    refresh_server_btn,
                ]),
            ]
        else:
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
                    ui.List(items=[
                        ui.ListItem(
                            id=str(p.get("name", "")),
                            title=p.get("title") or p.get("name", ""),
                            subtitle=f"{p.get('version', '')} → {p.get('update_version', '')}",
                            actions=([{
                                "icon": "Download",
                                "on_click": ui.Call("update_plugin", site_id=site_id,
                                                    slug=p.get("name", "")),
                                "confirm": f"Update '{p.get('title') or p.get('name', '')}' "
                                          f"now over SSH?",
                            }] if has_ssh else None),
                        )
                        for p in plug_list
                    ]),
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
            if has_ssh and (record.get("core_update") or n_updates):
                update_items.append(ui.List(items=[
                    ui.ListItem(
                        id="update-core", title="Update WordPress core",
                        subtitle="Updates core to the latest version over SSH",
                        icon="ArrowUpCircle",
                        actions=[{
                            "icon": "ArrowUpCircle",
                            "on_click": ui.Call("update_core", site_id=site_id),
                            "confirm": "Update WordPress core to the latest version now over SSH?",
                        }],
                    ),
                    ui.ListItem(
                        id="run-cron", title="Run due cron events",
                        subtitle="Forces WP-Cron to fire any events that are overdue",
                        icon="Clock",
                        actions=[{
                            "icon": "Clock",
                            "on_click": ui.Call("run_wp_cron", site_id=site_id),
                        }],
                    ),
                ]))

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
                  {"per_page": 20, "orderby": "registered_date", "order": "desc"}),
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
                  cpt_tab=cpt_tab, tax_tab=tax_tab, manage_tab=manage_tab, menu_sel=menu_sel)
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
    group_btns.append(_group_btn("Manage", "manage"))

    group_nav = ui.Stack(direction="h", gap=1, sticky=True, children=group_btns)

    # Active section content
    if group_tab == "activity":
        act_btns = [
            _item_btn("Comments",  "comments",  act_tab, "act_tab"),
            _item_btn("Scheduled", "scheduled", act_tab, "act_tab"),
            _item_btn("Users",     "users",     act_tab, "act_tab"),
        ]
        if act_tab == "comments":
            act_body = _comments_management_block(content_map.get("comments"), site_id)
        elif act_tab == "users":
            act_body = _users_management_block(content_map.get("users"), site_id)
        else:
            act_body = _render_content_table(content_map.get(act_tab), act_tab)
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, wrap=True, children=act_btns),
            act_body,
        ])

    elif group_tab == "commerce" and orders_data is not None:
        commerce_btns = [
            _item_btn("Overview", "overview", commerce_tab, "commerce_tab"),
            _item_btn("Orders", "orders", commerce_tab, "commerce_tab"),
            _item_btn("Products", "products", commerce_tab, "commerce_tab"),
            _item_btn("Categories", "categories", commerce_tab, "commerce_tab"),
            _item_btn("Customers", "customers", commerce_tab, "commerce_tab"),
            _item_btn("Coupons", "coupons", commerce_tab, "commerce_tab"),
            _item_btn("Reviews", "reviews", commerce_tab, "commerce_tab"),
        ]
        if commerce_tab == "reviews":
            reviews_data = await _list(
                "/wp-json/wc/v3/products/reviews",
                {"per_page": 50, "orderby": "date", "order": "desc"},
            )
            commerce_body = _render_reviews_block(reviews_data, site_id)
        elif commerce_tab == "categories":
            categories_data = await _list(
                "/wp-json/wc/v3/products/categories",
                {"per_page": 50, "orderby": "name", "order": "asc"},
            )
            commerce_body = _render_product_categories_block(categories_data, site_id)
        elif commerce_tab == "customers":
            customers_data = await _list(
                "/wp-json/wc/v3/customers",
                {"per_page": 50, "orderby": "registered_date", "order": "desc"},
            )
            commerce_body = _render_customers_block(customers_data, site_id)
        elif commerce_tab == "coupons":
            coupons_data = await _list(
                "/wp-json/wc/v3/coupons",
                {"per_page": 50, "orderby": "date", "order": "desc"},
            )
            commerce_body = _render_coupons_block(coupons_data, site_id)
        elif commerce_tab == "products":
            products_data = await _list(
                "/wp-json/wc/v3/products",
                {"per_page": 20, "orderby": "date", "order": "desc"},
            )
            commerce_body = _render_products_block(products_data, site_id)
        elif commerce_tab == "orders":
            commerce_body = _render_orders_block(orders_data, site_id)
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
                    ui.Text("WooCommerce summary for the current month.", variant="caption"),
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
        if std_tab in ("posts", "pages"):
            std_body = _posts_management_block(content_map.get(std_tab), std_tab, site_id)
        elif std_tab == "media":
            std_body = _media_management_block(content_map.get("media"), site_id)
        else:
            std_body = _render_content_table(content_map.get(std_tab), std_tab)
        active_content = ui.Stack(gap=3, children=[
            ui.Stack(direction="h", gap=1, children=[
                _item_btn("Posts", "posts", std_tab, "std_tab"),
                _item_btn("Pages", "pages", std_tab, "std_tab"),
                _item_btn("Media", "media", std_tab, "std_tab"),
            ]),
            std_body,
        ])

    if group_tab == "manage":
        active_content = await _render_manage_tab(
            ctx, site_id, base_url, username, pw, manage_tab, menu_sel, _call)

    # ── Assemble page ─────────────────────────────────
    page_children = [
        health_row,
        *server_section_children,
        ui.Divider(label="Content"),
        group_nav,
        active_content,
    ]

    return ui.Page(title=name, subtitle=base_url, children=page_children)
