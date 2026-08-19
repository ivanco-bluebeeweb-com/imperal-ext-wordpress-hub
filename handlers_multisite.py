"""Narrow WordPress Multisite operations (Group G).

All network facts/actions go through Imperal Bridge SECTION 18. The Bridge
rejects single-site WordPress before doing work and requires WordPress's own
``manage_network_options`` super-admin capability. This module deliberately
covers only inventory plus creating one explicitly named subsite; it is not a
general network-admin console.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import CreateNetworkSiteParams, NetworkPlugin, NetworkSite, SiteIdParams
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post

NETWORK_SITES_PATH = "/wp-json/imperal/v1/network/sites"
NETWORK_PLUGINS_PATH = "/wp-json/imperal/v1/network/plugins"
NETWORK_CREATE_SITE_PATH = "/wp-json/imperal/v1/network/sites"


async def _authed(ctx, site_id: str):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED",
        )
    password = await storage.get_credential(ctx, site_id)
    if not password:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING",
        )
    return (record["url"], record["username"], password), None


def _network_failure(status_code: int, body) -> ActionResult:
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    code = code or wp_error_code(status_code)
    if code == "imperal_network_not_multisite":
        return ActionResult.error(
            "This connected WordPress installation is not a Multisite network.",
            retryable=False, code="NOT_MULTISITE",
        )
    if status_code == 404:
        return ActionResult.error(
            "This site needs Imperal Bridge 2.18.0+ for Multisite operations.",
            retryable=False, code="MULTISITE_BRIDGE_MISSING",
        )
    return ActionResult.error(wp_error_message(status_code), retryable=status_code >= 500, code=code)


async def _get(ctx, site_id: str, path: str):
    auth, error = await _authed(ctx, site_id)
    if error:
        return None, error
    base_url, username, password = auth
    try:
        response = await wp_get(ctx, base_url, path, username=username, app_password=password)
    except Exception as exc:
        await ctx.log(f"multisite GET failed: {exc}", level="error")
        return None, ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return None, _network_failure(response.status_code, response.body)
    return response.body, None


@chat.function(
    "list_network_sites",
    description=(
        "List subsites in a connected WordPress Multisite network: blog ID, domain, path, "
        "public/archived/spam/deleted state, and registered date. Requires Imperal Bridge "
        "2.18.0+ and a WordPress super-administrator; returns a clear result on a normal "
        "single-site installation."
    ),
    action_type="read", data_model=sdl.EntityList[NetworkSite],
)
async def list_network_sites(ctx, params: SiteIdParams) -> ActionResult:
    """Return the real subsite inventory of a verified Multisite network."""
    body, error = await _get(ctx, params.site_id, NETWORK_SITES_PATH)
    if error:
        return error
    rows = body.get("sites", []) if isinstance(body, dict) else []
    items = [
        NetworkSite(
            id=str(row.get("blog_id", "")), title=str(row.get("site_url", row.get("domain", ""))),
            kind="wp_network_site", blog_id=int(row.get("blog_id", 0)),
            domain=str(row.get("domain", "")), path=str(row.get("path", "")),
            site_url=str(row.get("site_url", "")), public=bool(row.get("public")),
            archived=bool(row.get("archived")), spam=bool(row.get("spam")),
            deleted=bool(row.get("deleted")), registered=str(row.get("registered", "")),
        )
        for row in rows if isinstance(row, dict)
    ]
    return ActionResult.success(sdl.EntityList[NetworkSite](items=items), summary=f"{len(items)} network site(s)")


@chat.function(
    "list_network_plugins",
    description=(
        "List installed plugins on a connected WordPress Multisite network, including each "
        "plugin's file, name, version, and network-wide activation state. Requires Imperal Bridge "
        "2.18.0+ and a WordPress super-administrator."
    ),
    action_type="read", data_model=sdl.EntityList[NetworkPlugin],
)
async def list_network_plugins(ctx, params: SiteIdParams) -> ActionResult:
    """Return installed plugins with their true network-wide activation state."""
    body, error = await _get(ctx, params.site_id, NETWORK_PLUGINS_PATH)
    if error:
        return error
    rows = body.get("plugins", []) if isinstance(body, dict) else []
    items = [
        NetworkPlugin(
            id=str(row.get("plugin_file", "")), title=str(row.get("name", row.get("plugin_file", ""))),
            kind="wp_network_plugin", plugin_file=str(row.get("plugin_file", "")),
            name=str(row.get("name", "")), version=str(row.get("version", "")),
            network_active=bool(row.get("network_active")),
        )
        for row in rows if isinstance(row, dict)
    ]
    return ActionResult.success(sdl.EntityList[NetworkPlugin](items=items), summary=f"{len(items)} network-activated plugin(s)")


@chat.function(
    "create_network_site",
    description=(
        "Create one new subsite in a connected WordPress Multisite network using its domain, "
        "path, title, and the existing owner user's email. Requires Imperal Bridge 2.18.0+ and "
        "a WordPress super-administrator. This does not create users, install plugins, or alter "
        "other network sites."
    ),
    action_type="write", data_model=NetworkSite, effects=["wp.create_network_site"],
    event="wordpress-hub.create_network_site",
)
async def create_network_site(ctx, params: CreateNetworkSiteParams) -> ActionResult:
    """Create one explicit subsite with WordPress core's wpmu_create_blog()."""
    auth, error = await _authed(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth
    payload = {"domain": params.domain, "path": params.path, "title": params.title, "owner_email": params.owner_email}
    try:
        response = await wp_post(ctx, base_url, NETWORK_CREATE_SITE_PATH, username=username, app_password=password, json=payload)
    except Exception as exc:
        await ctx.log(f"create_network_site failed: {exc}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return _network_failure(response.status_code, response.body)
    row = response.body if isinstance(response.body, dict) else {}
    item = NetworkSite(
        id=str(row.get("blog_id", "")), title=str(row.get("site_url", row.get("domain", ""))), kind="wp_network_site",
        blog_id=int(row.get("blog_id", 0)), domain=str(row.get("domain", "")), path=str(row.get("path", "")),
        site_url=str(row.get("site_url", "")), public=bool(row.get("public")), archived=bool(row.get("archived")),
        spam=bool(row.get("spam")), deleted=bool(row.get("deleted")), registered=str(row.get("registered", "")),
    )
    return ActionResult.success(item, summary=f"Created network site {item.site_url or item.domain}")
