"""Native plugin activation, theme inventory, and site settings.

WordPress core has exposed /wp/v2/plugins (list + PUT status) and
/wp/v2/settings since 5.5, and /wp/v2/themes (read-only) since 5.0 -- no
Bridge or SSH needed for any of it. This is a *stronger* alternative to the
SSH-based list_plugins/install_plugin path: activate/deactivate here works
on any WP 5.5+ site even without SSH configured, closing the "plugin
management always needs SSH" gap. Switching the *active* theme has no core
REST route (by design -- WordPress treats it as a higher-risk site change),
so that stays out of scope here rather than being faked with an SSH escape
hatch.
"""
import hashlib
import json

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    ApplyBulkPluginStatusParams,
    BulkPluginStatusParams,
    BulkPluginStatusResult,
    NativePlugin,
    SetPluginStatusParams,
    SiteIdParams,
    SiteSettings,
    Theme,
    UpdateSiteSettingsParams,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_request

WP_BASE = "/wp-json/wp/v2"


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
            "This site's WordPress version doesn't expose this REST route "
            "(needs WordPress 5.5+), or the plugin/theme was not found.",
            retryable=False, code="WP_ROUTE_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage plugins/settings on this site. "
            "Reconnect with an administrator Application Password.",
            retryable=False, code="WP_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _plugin_entity(item: dict) -> NativePlugin:
    plugin_id = item.get("plugin", "")
    name = item.get("name", plugin_id)
    if isinstance(name, dict):
        name = name.get("rendered", plugin_id)
    return NativePlugin(
        id=plugin_id, title=name or plugin_id, kind="wp_plugin",
        plugin=plugin_id, version=item.get("version", ""),
        status=item.get("status", ""), description=(item.get("description") or {}).get("raw", "")
        if isinstance(item.get("description"), dict) else str(item.get("description", "")),
    )


def _theme_entity(item: dict) -> Theme:
    stylesheet = item.get("stylesheet", "")
    name = item.get("name", {})
    title = name.get("rendered", stylesheet) if isinstance(name, dict) else stylesheet
    return Theme(
        id=stylesheet, title=title or stylesheet, kind="wp_theme",
        stylesheet=stylesheet, version=item.get("version", ""),
        status=item.get("status", ""),
        is_block_theme=bool(item.get("is_block_theme", False)),
    )


def _settings_entity(body: dict) -> SiteSettings:
    return SiteSettings(
        id="settings", title=body.get("title", ""), kind="wp_settings",
        description=body.get("description", ""), url=body.get("url", ""),
        timezone_string=body.get("timezone_string", ""),
        date_format=body.get("date_format", ""), time_format=body.get("time_format", ""),
        start_of_week=int(body.get("start_of_week", 0) or 0),
        language=body.get("language", ""),
        site_icon=int(body.get("site_icon", 0) or 0),
    )


@chat.function(
    "list_native_plugins",
    description=(
        "List installed plugins via WordPress's own REST API (needs WordPress 5.5+ and an "
        "administrator connection) — no SSH required. Use activate_plugin/deactivate_plugin "
        "with the returned plugin id to change status."
    ),
    action_type="read", data_model=sdl.EntityList[NativePlugin],
)
async def list_native_plugins(ctx, params: SiteIdParams) -> ActionResult:
    """GET /wp/v2/plugins."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{WP_BASE}/plugins", username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [_plugin_entity(item) for item in data]
    active = sum(1 for i in items if i.status == "active")
    return ActionResult.success(
        sdl.EntityList[NativePlugin](items=items),
        summary=f"{len(items)} plugin(s), {active} active")


async def _set_plugin_status(ctx, params: SetPluginStatusParams, status: str) -> ActionResult:
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_request(
            ctx, "post", base_url, f"{WP_BASE}/plugins/{params.plugin}",
            username=username, app_password=pw, json={"status": status})
    except Exception as e:
        await ctx.log(f"set_plugin_status request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = _plugin_entity(body) if body else NativePlugin(
        id=params.plugin, title=params.plugin, kind="wp_plugin", plugin=params.plugin, status=status)
    return ActionResult.success(result, summary=f"Plugin '{params.plugin}' is now {status}",
                                 refresh_panels=["center"])


def _plugin_state_token(plugins: list[dict]) -> str:
    state = [{"plugin": item.get("plugin", ""), "status": item.get("status", ""),
              "version": item.get("version", "")} for item in sorted(plugins, key=lambda value: value.get("plugin", ""))]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _bulk_plugin_targets(ctx, params: BulkPluginStatusParams):
    status = params.status.strip().lower()
    if status not in {"active", "inactive"}:
        return None, ActionResult.error("Plugin status must be active or inactive.", retryable=False,
                                        code="WP_PLUGIN_INVALID_STATUS")
    plugins = [plugin.strip() for plugin in params.plugins]
    if any(not plugin for plugin in plugins):
        return None, ActionResult.error("Plugin identifiers must not be blank.", retryable=False,
                                        code="WP_PLUGIN_INVALID_ID")
    if len(set(plugins)) != len(plugins):
        return None, ActionResult.error("Each plugin identifier may appear only once.", retryable=False,
                                        code="WP_PLUGIN_DUPLICATE_IDS")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, pw = auth
    current = []
    for plugin in plugins:
        response = await wp_get(ctx, base_url, f"{WP_BASE}/plugins/{plugin}",
                                username=username, app_password=pw)
        if response.status_code != 200 or not isinstance(response.body, dict):
            return None, _failure(response.status_code, response.body)
        current.append(response.body)
    return (base_url, username, pw, plugins, current, status), None


@chat.function(
    "preview_bulk_plugin_status",
    description="Preview activating or deactivating 1-100 explicit native WordPress plugins. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkPluginStatusResult,
)
async def preview_bulk_plugin_status(ctx, params: BulkPluginStatusParams) -> ActionResult:
    """Return a no-write plugin status batch diff and deterministic state token."""
    targets, err = await _bulk_plugin_targets(ctx, params)
    if err:
        return err
    _, _, _, plugins, current, status = targets
    changes = [f"{plugin}: {item.get('status', 'unknown')} → {status}" for plugin, item in zip(plugins, current)]
    return ActionResult.success(BulkPluginStatusResult(
        preview=True, requested=len(plugins), matched=len(current), state_token=_plugin_state_token(current),
        changes=changes), summary=f"Preview: {len(current)} plugin(s) would become {status}")


@chat.function(
    "apply_bulk_plugin_status",
    description="Apply a previously previewed plugin status change to 1-100 explicit plugins. Rechecks every plugin before writing and stops before all writes if any changed.",
    action_type="write", data_model=BulkPluginStatusResult,
    effects=["wp.plugin_bulk_status_update"], event="wordpress-hub.apply_bulk_plugin_status",
)
async def apply_bulk_plugin_status(ctx, params: ApplyBulkPluginStatusParams) -> ActionResult:
    """Recheck the plugin snapshot, then apply the reviewed activation state."""
    targets, err = await _bulk_plugin_targets(ctx, params)
    if err:
        return err
    base_url, username, pw, plugins, current, status = targets
    if _plugin_state_token(current) != params.expected_state_token:
        return ActionResult.error("One or more plugins changed after preview; no plugin status was changed. Preview again.",
                                  retryable=False, code="WP_PLUGIN_BULK_STATE_CHANGED")
    updated, failed = [], []
    for plugin in plugins:
        response = await wp_request(ctx, "post", base_url, f"{WP_BASE}/plugins/{plugin}",
                                    username=username, app_password=pw, json={"status": status})
        if 200 <= response.status_code < 300:
            updated.append(plugin)
        else:
            failed.append(plugin)
    result = BulkPluginStatusResult(preview=False, requested=len(plugins), matched=len(current),
                                    updated=len(updated), failed=len(failed), updated_ids=updated, failed_ids=failed)
    if failed:
        return ActionResult.error(f"Updated {len(updated)} plugin(s); {len(failed)} failed: {', '.join(failed)}.",
                                  retryable=False, code="WP_PLUGIN_BULK_PARTIAL_FAILURE")
    return ActionResult.success(result, summary=f"Updated {len(updated)} plugin(s) to {status}", refresh_panels=["center"])


@chat.function(
    "activate_plugin",
    description="Activate an installed WordPress plugin via the native REST API (WordPress 5.5+, no SSH needed).",
    action_type="write", data_model=NativePlugin,
    effects=["wp.plugin_activate"], event="wordpress-hub.activate_plugin",
)
async def activate_plugin(ctx, params: SetPluginStatusParams) -> ActionResult:
    """PUT-equivalent (POST with method override) status=active."""
    return await _set_plugin_status(ctx, params, "active")


@chat.function(
    "deactivate_plugin",
    description="Deactivate an installed WordPress plugin via the native REST API (WordPress 5.5+, no SSH needed).",
    action_type="write", data_model=NativePlugin,
    effects=["wp.plugin_deactivate"], event="wordpress-hub.deactivate_plugin",
)
async def deactivate_plugin(ctx, params: SetPluginStatusParams) -> ActionResult:
    """PUT-equivalent (POST with method override) status=inactive."""
    return await _set_plugin_status(ctx, params, "inactive")


@chat.function(
    "list_themes",
    description=(
        "List installed themes via WordPress's own REST API (needs an administrator "
        "connection) — shows which one is currently active. Read-only: WordPress core has "
        "no REST route to switch the active theme."
    ),
    action_type="read", data_model=sdl.EntityList[Theme],
)
async def list_themes(ctx, params: SiteIdParams) -> ActionResult:
    """GET /wp/v2/themes."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{WP_BASE}/themes", username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [_theme_entity(item) for item in data]
    active = next((i.title for i in items if i.status == "active"), "unknown")
    return ActionResult.success(
        sdl.EntityList[Theme](items=items), summary=f"{len(items)} theme(s) — active: {active}")


@chat.function(
    "get_site_settings",
    description="Read native WordPress site settings: title, tagline, timezone, date/time format, "
                "start of week, language, and the media-library site-icon attachment id.",
    action_type="read", data_model=SiteSettings,
)
async def get_site_settings(ctx, params: SiteIdParams) -> ActionResult:
    """GET /wp/v2/settings."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    r = await wp_get(ctx, base_url, f"{WP_BASE}/settings", username=username, app_password=pw)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    return ActionResult.success(_settings_entity(body), summary="Site settings")


@chat.function(
    "update_site_settings",
    description="Update native WordPress site settings: title, tagline, timezone, date/time format, "
                "start of week, or native site icon. Only the fields you pass are changed.",
    action_type="write", data_model=SiteSettings,
    effects=["wp.settings_update"], event="wordpress-hub.update_site_settings",
)
async def update_site_settings(ctx, params: UpdateSiteSettingsParams) -> ActionResult:
    """POST /wp/v2/settings with only the given fields."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    fields = {}
    if params.title is not None:
        fields["title"] = params.title
    if params.description is not None:
        fields["description"] = params.description
    if params.timezone_string is not None:
        fields["timezone_string"] = params.timezone_string
    if params.date_format is not None:
        fields["date_format"] = params.date_format
    if params.time_format is not None:
        fields["time_format"] = params.time_format
    if params.start_of_week is not None:
        fields["start_of_week"] = params.start_of_week
    if params.site_icon is not None:
        fields["site_icon"] = params.site_icon

    if not fields:
        return ActionResult.error(
            "No fields given to update.", retryable=False, code="NO_FIELDS_GIVEN")

    try:
        r = await wp_request(
            ctx, "post", base_url, f"{WP_BASE}/settings",
            username=username, app_password=pw, json=fields)
    except Exception as e:
        await ctx.log(f"update_site_settings request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    return ActionResult.success(_settings_entity(body), summary="Site settings updated",
                                 refresh_panels=["center"])
