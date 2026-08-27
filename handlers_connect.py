from urllib.parse import urlparse

from app import chat, ext
from imperal_sdk import ActionResult
from models import ConnectSiteParams, SiteIdParams, Site, AddSSHParams, _NoParams
from wp_client import normalize_base_url, site_id_from_url, wp_get, wp_error_message, now_iso
import storage
import wp_cli


async def _push_to_sites_registry(ctx, *, domain: str, name: str, connector_ref: str, status: str) -> None:
    """Best-effort push of this site's connection state into Sites Registry
    (a separate, platform-agnostic catalogue app). Wrapped defensively —
    Sites Registry may not be installed for every user, and this call must
    never block or fail a real WordPress connect/disconnect."""
    try:
        await ctx.extensions.call(
            "sites-registry", "upsert_site",
            domain=domain, name=name, platform="wordpress",
            connector_app="wordpress-hub", connector_ref=connector_ref,
            status=status,
        )
    except Exception as e:
        await ctx.log(f"sites-registry upsert skipped: {e}", level="info")


async def _do_connect_site(ctx, *, url: str, username: str, app_password: str) -> dict:
    """Shared connect logic used by both the connect_site chat tool and the
    connect_site_ipc inter-extension surface (Sites Registry calls this when
    the user adds a WordPress site there). Returns a plain dict:
    {"ok": True, "site_id", "name", "url"} or {"ok": False, "error", "retryable"}.
    """
    try:
        base_url = normalize_base_url(url)
    except ValueError as e:
        return {"ok": False, "error": str(e) or "Site URL is not valid.", "retryable": False}

    site_id = site_id_from_url(base_url)
    try:
        r = await wp_get(ctx, base_url, "/wp-json/wp/v2/users/me",
                         username=username, app_password=app_password)
    except Exception as e:
        await ctx.log(f"connect_site http error: {e}", level="error")
        return {"ok": False, "error": "Could not reach the site — check the URL and try again.", "retryable": True}

    if not (200 <= r.status_code < 300):
        return {"ok": False, "error": wp_error_message(r.status_code),
                "retryable": r.status_code >= 500 or r.status_code == 429}

    name = urlparse(base_url).netloc or base_url
    record = {"id": site_id, "name": name, "url": base_url, "username": username,
              "status": "connected", "last_checked": now_iso()}
    await storage.save_site_record(ctx, record)
    try:
        await storage.set_credential(ctx, site_id, app_password)
    except Exception as e:
        await ctx.log(f"connect_site: credential save failed: {e}", level="error")
        await storage.delete_site_record(ctx, site_id)
        return {"ok": False, "error": "Could not save credentials — try again.", "retryable": True}

    await _push_to_sites_registry(ctx, domain=name, name=name, connector_ref=site_id, status="connected")
    return {"ok": True, "site_id": site_id, "name": name, "url": base_url}


@chat.function(
    "connect_site",
    description="Connect a WordPress site by URL, username, and Application Password.",
    action_type="write",
    data_model=Site,
    effects=["wp.connect"],
    event="wordpress-hub.connect_site",
)
async def connect_site(ctx, params: ConnectSiteParams) -> ActionResult:
    """Validate WP credentials via /users/me, then persist the site record and Application Password."""
    result = await _do_connect_site(ctx, url=params.url, username=params.username, app_password=params.app_password)
    if not result["ok"]:
        return ActionResult.error(result["error"], retryable=result["retryable"])
    site = Site(id=result["site_id"], title=result["name"], kind="wp_site", url=result["url"],
                username=params.username, status="connected")
    await _nudge_bricks_forms_on_connect(ctx, site_id=result["site_id"], name=result["name"])
    return ActionResult.success(site, summary=f"Connected {result['name']}", refresh_panels=["sidebar"])


async def _nudge_bricks_forms_on_connect(ctx, *, site_id: str, name: str) -> None:
    """Best-effort: run the Bricks form completeness audit right after a new
    site connects, and say something in chat only if it actually found an
    incomplete form. Wrapped defensively -- the site may not run Bricks at
    all, or Imperal Bridge may be older than 2.27.0 -- neither should ever
    block or fail a real WordPress connect."""
    try:
        import handlers_bricks_forms as bf
        import storage as st
        result, err = await bf._run_audit(ctx, site_id)
        await st.mark_form_audit_checked(ctx, site_id)
        if err is not None or result is None:
            return
        if result.all_complete or result.total_forms_found == 0:
            return
        await ctx.deliver_chat_message(
            f"By the way -- {name} has {len(result.incomplete_forms)} Bricks form(s) that "
            f"aren't fully set up yet (missing form name, action, save-to-database, success "
            f"or error message). Want me to walk through fixing them? Run audit_bricks_forms "
            f"any time for the details.",
            msg_type="system",
        )
    except Exception as e:
        await ctx.log(f"bricks form connect-nudge skipped for {site_id}: {e}", level="info")


@chat.function(
    "sync_sites_to_registry",
    description=(
        "Push every WordPress site already connected here into Sites Registry -- the "
        "platform-agnostic catalogue app. Fixes sites that were connected here before "
        "Sites Registry existed, or any time the two drift out of sync."
    ),
    action_type="write",
    data_model=Site,
    effects=["wp.sync_registry"],
    event="wordpress-hub.sync_sites_to_registry",
)
async def sync_sites_to_registry(ctx, params: _NoParams) -> ActionResult:
    """Reads OUR own connected sites directly from local storage (no IPC needed
    for that part -- it's our own data) and pushes each one, one at a time,
    through the already-proven single-hop upsert_site IPC surface -- the exact
    same path a normal connect_site/forget_site call already uses successfully.
    Deliberately avoids a round-trip IPC call (WP Hub -> Sites Registry -> back
    to WP Hub) since @ext.expose cross-extension calls are an experimental
    platform surface with undocumented multi-hop behaviour."""
    rows = await storage.list_site_records(ctx)
    synced = 0
    failed = 0
    for r in rows:
        domain = urlparse(r.get("url", "")).netloc or r.get("name", r["id"])
        try:
            await ctx.extensions.call(
                "sites-registry", "upsert_site",
                domain=domain, name=r.get("name", domain), platform="wordpress",
                connector_app="wordpress-hub", connector_ref=r["id"],
                status=r.get("status", "connected"),
            )
            synced += 1
        except Exception as e:
            await ctx.log(f"sync_sites_to_registry: push failed for {domain}: {e}", level="error")
            failed += 1

    if synced == 0 and failed > 0:
        return ActionResult.error(
            "Could not reach Sites Registry -- make sure it's installed and try again.",
            retryable=True)
    summary = f"Synced {synced} site(s) into Sites Registry."
    if failed:
        summary += f" {failed} failed."
    return ActionResult.success(
        Site(id="sync", title="Sites Registry sync", kind="wp_site", status="connected"),
        summary=summary)


@ext.expose("connect_site_ipc", action_type="write")
async def expose_connect_site_ipc(ctx, url: str = "", username: str = "", app_password: str = "", **kwargs) -> dict:
    """Inter-extension IPC surface (ctx.extensions.call) for Sites Registry:
    lets a user add a WordPress site directly from the registry's own form
    (URL + username + Application Password) and have it connect here in the
    exact same way as the connect_site chat tool — same validation, same
    stored credential, one real connection either way.

    Returns a plain dict (never surfaced to the LLM/user directly):
    {"ok": True, "site_id", "name", "url"} or {"ok": False, "error", "retryable"}.
    """
    return await _do_connect_site(ctx, url=url, username=username, app_password=app_password)


# forget_site IS LLM-visible by design: takes only site_id (no credential in args).
# The web-kernel shows the KAV confirmation card automatically for action_type="destructive".
@chat.function(
    "forget_site",
    description="Disconnect a WordPress site and delete its stored credential.",
    action_type="destructive",
    data_model=Site,
    effects=["wp.disconnect"],
    event="wordpress-hub.forget_site",
)
async def forget_site(ctx, params: SiteIdParams) -> ActionResult:
    """Remove the site record and its stored Application Password after user confirmation."""
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error("No connected site with that id.", retryable=False)
    await storage.delete_site_record(ctx, params.site_id)
    await storage.clear_content_cache(ctx, params.site_id)
    try:
        await storage.delete_credential(ctx, params.site_id)
    except Exception as e:
        # Site record is already deleted — orphaned credential is harmless.
        await ctx.log(f"forget_site: credential cleanup failed: {e}", level="error")
    site = Site(id=params.site_id, title=record.get("name", params.site_id), kind="wp_site",
                url=record.get("url", ""), username=record.get("username", ""), status="disconnected")
    await storage.delete_ssh_cred(ctx, params.site_id)
    await _push_to_sites_registry(
        ctx, domain=record.get("name", params.site_id), name=record.get("name", params.site_id),
        connector_ref=params.site_id, status="disconnected",
    )
    return ActionResult.success(
        site, summary=f"Disconnected {record.get('name', params.site_id)}",
        refresh_panels=["sidebar", "center"])


@chat.function(
    "add_ssh",
    description="Add SSH access to a connected WordPress site to enable WP-CLI features: PHP version, plugin/theme/core update counts, cron jobs, database size.",
    action_type="write",
    data_model=Site,
    effects=["wp.ssh_connect"],
    event="wordpress-hub.add_ssh",
)
async def add_ssh(ctx, params: AddSSHParams) -> ActionResult:
    """Validate SSH connection + WP-CLI, then store credentials."""
    site_id = params.site_id or await storage.get_pending_ssh_site(ctx)
    if not site_id:
        return ActionResult.error("Could not determine which site to connect — open Add SSH from the site panel.", retryable=False)
    if not params.ssh_key and not params.ssh_password:
        return ActionResult.error("Provide either ssh_key or ssh_password.", retryable=False)

    cred = {
        "host": params.ssh_host,
        "port": params.ssh_port,
        "user": params.ssh_user,
        "wp_path": params.wp_path,
    }
    if params.ssh_key:
        cred["key"] = params.ssh_key
    else:
        cred["password"] = params.ssh_password

    ok, msg = await wp_cli.test_connection(cred)
    if not ok:
        return ActionResult.error(f"SSH connection failed: {msg}", retryable=True)

    await storage.set_ssh_cred(ctx, site_id, cred)
    await storage.clear_content_cache(ctx, site_id)

    record = await storage.get_site_record(ctx, site_id) or {}
    # Store ssh_host in the record so the sidebar can read SSH status without extra queries
    await storage.save_site_record(ctx, {**record, "ssh_host": params.ssh_host})

    site = Site(id=site_id, title=record.get("name", site_id),
                kind="wp_site", url=record.get("url", ""),
                username=record.get("username", ""), status="connected")
    return ActionResult.success(
        site,
        summary=f"SSH connected to {params.ssh_host} — WordPress {msg}",
        refresh_panels=["sidebar", "center"],
    )


@chat.function(
    "remove_ssh",
    description="Remove SSH access from a connected WordPress site.",
    action_type="write",
    data_model=Site,
    effects=["wp.ssh_disconnect"],
    event="wordpress-hub.remove_ssh",
)
async def remove_ssh(ctx, params: SiteIdParams) -> ActionResult:
    """Delete stored SSH credentials for the site."""
    await storage.delete_ssh_cred(ctx, params.site_id)
    await storage.clear_content_cache(ctx, params.site_id)
    record = await storage.get_site_record(ctx, params.site_id) or {}
    # NOTE: storage.save_site_record() goes through the platform store's
    # store.update(), which is documented PATCH semantics only (see
    # store_update.json: "set: Field values to apply (patch semantics)") --
    # there is no key-deletion primitive. Popping keys from this local dict
    # before saving is therefore a silent no-op: the stale SSH-derived
    # fields would survive in the stored record forever, so a site could
    # keep reporting an old wp_version/php_version/db_size/etc. as if SSH
    # were still connected. Explicitly clear each field to its empty
    # value instead so the "removal" actually takes effect on read.
    for field in ("ssh_host", "wp_version", "php_version", "cron_count",
                  "pending_updates", "server_last_checked"):
        record[field] = ""
    record["db_size_mb"] = ""
    record["plugin_updates_list"] = []
    record["theme_updates_list"] = []
    await storage.save_site_record(ctx, record)
    site = Site(id=params.site_id, title=record.get("name", params.site_id),
                kind="wp_site", url=record.get("url", ""),
                username=record.get("username", ""), status="connected")
    return ActionResult.success(site, summary="SSH access removed.",
                                refresh_panels=["center"])
