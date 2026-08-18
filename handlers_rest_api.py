"""REST API introspection and Application Password auditing.

Group E of the developer/backend-developer roadmap
(docs/2026-08-11-developer-backend-functions-plan.md).

list_rest_routes / get_rest_route_schema read the site's own REST API root
index document (GET /wp-json/), which WordPress core has served since the
REST API's introduction -- no Bridge or SSH needed. The index shape
({"routes": {"<path>": {"namespace", "methods", "endpoints": [...]}}}) is
documented at developer.wordpress.org/rest-api/extending-the-rest-api/
routes-and-endpoints/ and confirmed live by every real /wp-json/ response.

list_application_passwords / revoke_application_password use the native
/wp/v2/users/me/application-passwords routes WordPress core has shipped
since 5.6 (developer.wordpress.org/rest-api/reference/application-passwords/,
make.wordpress.org/core/2020/11/05/application-passwords-integration-guide).
"me" always resolves to whichever user this site's connected Application
Password authenticates as -- exactly the account connect_site already
validates via /wp/v2/users/me. The secret itself is never returned by this
route (WordPress only returns the plaintext password once, at creation
time, which happens outside of this app entirely).
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ApplicationPassword,
    ApplicationPasswordRevokeResult,
    GetRestRouteSchemaParams,
    ListRestRoutesParams,
    RestRoute,
    RestRouteSchema,
    RevokeApplicationPasswordParams,
    SiteIdParams,
    WpAbility,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_request

APP_PASSWORDS_BASE = "/wp-json/wp/v2/users/me/application-passwords"
WP_ABILITIES_BASE = "/wp-json/wp-abilities/v1/abilities"


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    password = await storage.get_credential(ctx, site_id)
    if not password:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], password), None


def _failure(status_code, body):
    if status_code == 404:
        return ActionResult.error(
            "That route or application password wasn't found on this site.",
            retryable=False, code="WP_ROUTE_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot read/manage this on this site. "
            "Reconnect with an administrator Application Password.",
            retryable=False, code="WP_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


async def _fetch_root_index(ctx, base_url, username, pw):
    """GET the site's own REST API root index document."""
    return await wp_get(ctx, base_url, "/wp-json/", username=username, app_password=pw)


@chat.function(
    "list_rest_routes",
    description=(
        "Enumerate every REST route/namespace registered on this WordPress site -- WordPress "
        "core's own routes plus every plugin's own routes (WooCommerce, Rank Math, page "
        "builders...). Reads the site's own REST API root index (GET /wp-json/) -- the exact "
        "discovery document any REST client uses to find out what a site actually exposes. "
        "Use to answer 'what can I actually call on this site' or to confirm a plugin's REST "
        "surface is really there before assuming it. Pass namespace to filter, e.g. 'wp/v2'."
    ),
    action_type="read", data_model=sdl.EntityList[RestRoute],
)
async def list_rest_routes(ctx, params: ListRestRoutesParams) -> ActionResult:
    """GET /wp-json/ (the site's own REST API root index), optionally filtered by namespace."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await _fetch_root_index(ctx, base_url, username, pw)
    except Exception as e:
        await ctx.log(f"list_rest_routes request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    routes = body.get("routes") if isinstance(body.get("routes"), dict) else {}
    ns_filter = (params.namespace or "").strip().strip("/")
    items = []
    for path, info in routes.items():
        if not isinstance(info, dict):
            continue
        namespace = info.get("namespace", "") or ""
        if ns_filter and namespace.strip("/") != ns_filter:
            continue
        endpoints = info.get("endpoints") if isinstance(info.get("endpoints"), list) else []
        methods: list[str] = []
        for ep in endpoints:
            if isinstance(ep, dict):
                for m in ep.get("methods", []) or []:
                    if m not in methods:
                        methods.append(m)
        items.append(RestRoute(id=path, title=path, route=path, namespace=namespace, methods=methods))
    namespaces = sorted({i.namespace for i in items if i.namespace})
    summary = f"{len(items)} route(s)"
    if ns_filter:
        summary += f" in namespace '{ns_filter}'"
    elif namespaces:
        summary += f" across {len(namespaces)} namespace(s)"
    return ActionResult.success(sdl.EntityList[RestRoute](items=items), summary=summary)


@chat.function(
    "get_rest_route_schema",
    description=(
        "Read the full endpoint detail for ONE REST route on this site -- its HTTP methods and "
        "each endpoint's declared args (required/type/default), straight from the site's own "
        "REST API root index. Pass the exact route path from list_rest_routes (e.g. "
        "'/wp/v2/posts/(?P<id>[\\d]+)')."
    ),
    action_type="read", data_model=RestRouteSchema,
)
async def get_rest_route_schema(ctx, params: GetRestRouteSchemaParams) -> ActionResult:
    """Return one route's methods and endpoint args from the site's own /wp-json/ root index."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await _fetch_root_index(ctx, base_url, username, pw)
    except Exception as e:
        await ctx.log(f"get_rest_route_schema request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    routes = body.get("routes") if isinstance(body.get("routes"), dict) else {}
    info = routes.get(params.route)
    if not isinstance(info, dict):
        return ActionResult.error(
            f"Route '{params.route}' is not registered on this site — run list_rest_routes to see the exact paths.",
            retryable=False, code="WP_ROUTE_NOT_FOUND")
    endpoints = info.get("endpoints") if isinstance(info.get("endpoints"), list) else []
    result = RestRouteSchema(
        id=params.route, title=params.route,
        route=params.route, namespace=info.get("namespace", "") or "",
        endpoints=[ep for ep in endpoints if isinstance(ep, dict)])
    return ActionResult.success(result, summary=f"{len(result.endpoints)} endpoint(s) on '{params.route}'")


def _app_password_entity(item: dict) -> ApplicationPassword:
    uuid = item.get("uuid", "") or ""
    return ApplicationPassword(
        id=uuid, title=item.get("name", "") or uuid,
        uuid=uuid, app_id=item.get("app_id", "") or "",
        name=item.get("name", "") or "",
        created=item.get("created", "") or "",
        last_used=item.get("last_used") or "",
        last_ip=item.get("last_ip") or "")


@chat.function(
    "list_application_passwords",
    description=(
        "List the Application Passwords currently registered for the WordPress user this site "
        "connects as -- name, created date, last used, last IP. Never the secret itself (WordPress "
        "only ever returns that once, at creation, outside this app). Requires WordPress 5.6+. Use "
        "for security auditing: 'what has access to this site' and to find the uuid to revoke."
    ),
    action_type="read", data_model=sdl.EntityList[ApplicationPassword],
)
async def list_application_passwords(ctx, params: SiteIdParams) -> ActionResult:
    """GET /wp/v2/users/me/application-passwords."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, APP_PASSWORDS_BASE, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"list_application_passwords request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [_app_password_entity(item) for item in data if isinstance(item, dict)]
    return ActionResult.success(sdl.EntityList[ApplicationPassword](items=items), summary=f"{len(items)} application password(s)")


@chat.function(
    "revoke_application_password",
    description=(
        "Permanently revoke ONE Application Password by its uuid (from list_application_passwords) "
        "-- immediately blocks whatever client was using it. Distinct from forget_site, which only "
        "removes Imperal's OWN stored credential; this changes WordPress itself and affects every "
        "client using that password, not just this connection. Requires WordPress 5.6+."
    ),
    action_type="destructive", data_model=ApplicationPasswordRevokeResult,
    effects=["wp.revoke_application_password"],
    event="wordpress-hub.revoke_application_password",
)
async def revoke_application_password(ctx, params: RevokeApplicationPasswordParams) -> ActionResult:
    """DELETE /wp/v2/users/me/application-passwords/{uuid}."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_request(
            ctx, "delete", base_url, f"{APP_PASSWORDS_BASE}/{params.uuid}",
            username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"revoke_application_password request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    return ActionResult.success(
        ApplicationPasswordRevokeResult(
            id=params.uuid, title=f"application password {params.uuid}",
            site_id=params.site_id, uuid=params.uuid, revoked=True),
        summary="Application password revoked.")


def _ability_entity(item: dict) -> WpAbility:
    name = item.get("name", "") or ""
    return WpAbility(
        id=name, title=item.get("label", "") or name,
        name=name, label=item.get("label", "") or "",
        description=item.get("description", "") or "",
        category=item.get("category", "") or "",
        input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
        output_schema=item.get("output_schema") if isinstance(item.get("output_schema"), dict) else {},
        meta=item.get("meta") if isinstance(item.get("meta"), dict) else {})


@chat.function(
    "list_wp_abilities",
    description=(
        "List every ability currently registered with WordPress's own Abilities API "
        "(wp-abilities/v1) on this site -- e.g. Bricks builder actions an MCP client (Claude, "
        "Cursor...) can run once 'Bricks > AI' has been enabled. Uses the site's own native "
        "REST route (registered by the WordPress MCP Adapter plugin), authenticated with the "
        "connected Application Password -- no Bridge change needed. An empty list means no "
        "plugin has registered abilities yet (e.g. Bricks AI has not been switched on)."
    ),
    action_type="read", data_model=sdl.EntityList[WpAbility],
)
async def list_wp_abilities(ctx, params: SiteIdParams) -> ActionResult:
    """GET /wp-json/wp-abilities/v1/abilities."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_get(ctx, base_url, WP_ABILITIES_BASE, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"list_wp_abilities request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [_ability_entity(item) for item in data if isinstance(item, dict)]
    return ActionResult.success(sdl.EntityList[WpAbility](items=items), summary=f"{len(items)} registered ability/abilities")
