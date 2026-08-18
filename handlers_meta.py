"""Generic custom-field meta on posts/users/terms, plus a hard-allowlisted
subset of wp_options, and read-only ACF field-group discovery.

WordPress core only exposes post meta over the REST API when it is
registered with register_post_meta(..., show_in_rest=True). Almost no
real-world custom field is registered this way -- ACF fields, raw
update_post_meta() calls, and most plugin-added meta are all invisible to
/wp/v2/<type>/<id>?context=edit. This closes that gap through Imperal Bridge
SECTION 9 (/imperal/v1/postmeta|usermeta|termmeta|option|acf-fields),
verified against the Bridge plugin's own SECTION 9 source before writing
this file.

wp_options access is intentionally narrow: the Bridge enforces a hard
allowlist of known-safe option names (Rank Math's own settings, site
title/tagline, a few WooCommerce store-settings names) -- never
siteurl/home/active_plugins/template/stylesheet, and never a value that
looks like a serialized PHP object (rejected server-side as a PHP
object-injection risk). This handler does not maintain its own copy of the
allowlist -- the Bridge is the single source of truth and returns a 403 with
a clear message if a name isn't on it.
"""
import hashlib
import json

from imperal_sdk import ActionResult

from app import chat
from models import (
    AcfFieldsParams,
    AcfFieldsResult,
    ApplyBulkPostMetaParams,
    ApplyBulkTermMetaParams,
    BulkPostMetaParams,
    BulkPostMetaResult,
    BulkTermMetaParams,
    BulkTermMetaResult,
    DeletePostMetaParams,
    DeleteTermMetaParams,
    DeleteUserMetaParams,
    GetOptionParams,
    GetPostMetaParams,
    GetTermMetaParams,
    GetUserMetaParams,
    OptionValue,
    PostMetaDeleteResult,
    PostMetaSet,
    PostMetaUpdateResult,
    TermMetaDeleteResult,
    TermMetaSet,
    TermMetaUpdateResult,
    UpdateOptionParams,
    UpdatePostMetaParams,
    UpdateTermMetaParams,
    UpdateUserMetaParams,
    UserMetaDeleteResult,
    UserMetaSet,
    UserMetaUpdateResult,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_request

BRIDGE_BASE = "/wp-json/imperal/v1"


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


def _bridge_missing_error(resp):
    if resp.status_code == 404:
        return ActionResult.error(
            "The Imperal Bridge plugin isn't installed (or is an older version without generic "
            "meta support) on this site — install/update it to use this function.",
            retryable=False, code="BRIDGE_NOT_INSTALLED")
    return ActionResult.error(wp_error_message(resp.status_code), retryable=resp.status_code >= 500,
                               code=wp_error_code(resp.status_code))


# ─────────── Post meta ───────────

@chat.function(
    "get_post_meta",
    description=(
        "Read ALL custom-field meta on one post/page/CPT item, including meta keys WordPress's "
        "own REST API hides because they were never registered with show_in_rest (most ACF "
        "fields and plugin-added meta fall in this category). Requires the Imperal Bridge plugin."
    ),
    action_type="read",
    data_model=PostMetaSet,
)
async def get_post_meta(ctx, params: GetPostMetaParams) -> ActionResult:
    """Read all post meta via Bridge SECTION 9 (core REST hides unregistered keys)."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/postmeta/{params.post_id}",
                         username=username, app_password=app_password)
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    return ActionResult.success(
        PostMetaSet(id=str(params.post_id), title=f"post {params.post_id} meta", kind="post_meta",
                    post_id=body.get("post_id", params.post_id), meta=body.get("meta", {})),
        summary=f"Read {len(body.get('meta', {}))} meta key(s) on post {params.post_id}.",
    )


@chat.function(
    "update_post_meta",
    description=(
        "Set one or more arbitrary custom-field meta keys/values on a post/page/CPT item — the "
        "generic version of update_seo_meta for non-SEO custom fields. Requires the Imperal "
        "Bridge plugin. Values must be plain strings/numbers/booleans/arrays."
    ),
    action_type="write",
    data_model=PostMetaUpdateResult,
    effects=["wp.update_post_meta"],
    event="wordpress-hub.update_post_meta",
)
async def update_post_meta(ctx, params: UpdatePostMetaParams) -> ActionResult:
    """Set one or more post meta keys via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "post", base_url, f"{BRIDGE_BASE}/postmeta/{params.post_id}",
                             username=username, app_password=app_password, json={"meta": params.meta})
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    updated = body.get("updated", [])
    return ActionResult.success(
        PostMetaUpdateResult(id=str(params.post_id), title=f"post {params.post_id} meta update",
                              kind="post_meta_update", post_id=body.get("post_id", params.post_id),
                              updated=updated),
        summary=f"Updated {len(updated)} meta key(s) on post {params.post_id}.",
    )


def _bulk_post_meta_token(rows: list[tuple[int, dict]], keys: list[str]) -> str:
    state = [
        {"post_id": post_id, "meta": {key: meta.get(key) for key in sorted(keys)}}
        for post_id, meta in sorted(rows)
    ]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def _bulk_post_meta_targets(ctx, params: BulkPostMetaParams):
    if len(set(params.post_ids)) != len(params.post_ids):
        return None, ActionResult.error("Each post id may appear only once.", retryable=False, code="POST_META_DUPLICATE_IDS")
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, app_password = cred
    rows = []
    for post_id in params.post_ids:
        resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/postmeta/{post_id}",
                            username=username, app_password=app_password)
        if resp.status_code >= 400:
            return None, _bridge_missing_error(resp)
        body = resp.body or {}
        rows.append((post_id, body.get("meta", {})))
    return (base_url, username, app_password, rows), None


@chat.function(
    "preview_bulk_post_meta",
    description="Preview setting the same safe custom-meta key/value pairs on 1-100 explicit posts/pages/CPT items. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkPostMetaResult,
)
async def preview_bulk_post_meta(ctx, params: BulkPostMetaParams) -> ActionResult:
    """Read every explicit meta target and return a reviewed batch diff."""
    targets, err = await _bulk_post_meta_targets(ctx, params)
    if err:
        return err
    _, _, _, rows = targets
    changes = [f"#{post_id}: set {', '.join(sorted(params.meta))}" for post_id, _ in rows]
    return ActionResult.success(BulkPostMetaResult(
        id=params.site_id, title="Bulk post meta preview", kind="wp_bulk_post_meta", preview=True,
        requested=len(params.post_ids), matched=len(rows),
        state_token=_bulk_post_meta_token(rows, list(params.meta)), changes=changes),
        summary=f"Preview: set {len(params.meta)} meta key(s) on {len(rows)} item(s)")


@chat.function(
    "apply_bulk_post_meta",
    description="Apply a previewed safe custom-meta update to 1-100 explicit posts/pages/CPT items. Stops before all writes if any target's reviewed keys changed.",
    action_type="destructive", data_model=BulkPostMetaResult,
    effects=["wp.bulk_update_post_meta"], event="wordpress-hub.apply_bulk_post_meta",
)
async def apply_bulk_post_meta(ctx, params: ApplyBulkPostMetaParams) -> ActionResult:
    """Apply identical meta only if every target still matches the preview token."""
    targets, err = await _bulk_post_meta_targets(ctx, params)
    if err:
        return err
    base_url, username, app_password, rows = targets
    if _bulk_post_meta_token(rows, list(params.meta)) != params.expected_state_token:
        return ActionResult.error("One or more post meta values changed since preview. Run preview_bulk_post_meta again.", retryable=False, code="POST_META_BULK_STATE_CHANGED")
    updated_ids, failed_ids = [], []
    for post_id, _ in rows:
        resp = await wp_request(ctx, "post", base_url, f"{BRIDGE_BASE}/postmeta/{post_id}",
                                username=username, app_password=app_password, json={"meta": params.meta})
        (updated_ids if resp.status_code < 400 else failed_ids).append(post_id)
    result = BulkPostMetaResult(
        id=params.site_id, title="Bulk post meta result", kind="wp_bulk_post_meta", preview=False,
        requested=len(params.post_ids), matched=len(rows), updated=len(updated_ids), failed=len(failed_ids),
        updated_ids=updated_ids, failed_ids=failed_ids)
    if not updated_ids:
        return ActionResult.error("WordPress did not update any requested post meta.", retryable=True, code="POST_META_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Updated meta on {len(updated_ids)} item(s); {len(failed_ids)} failed", refresh_panels=["center"])


@chat.function(
    "delete_post_meta",
    description="Remove one custom-field meta key from a post/page/CPT item. Requires the Imperal Bridge plugin.",
    action_type="write",
    data_model=PostMetaDeleteResult,
    effects=["wp.delete_post_meta"],
    event="wordpress-hub.delete_post_meta",
)
async def delete_post_meta(ctx, params: DeletePostMetaParams) -> ActionResult:
    """Remove one post meta key via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "delete", base_url, f"{BRIDGE_BASE}/postmeta/{params.post_id}/{params.key}",
                             username=username, app_password=app_password)
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    return ActionResult.success(
        PostMetaDeleteResult(id=str(params.post_id), title=f"post {params.post_id} meta delete",
                              kind="post_meta_delete", post_id=params.post_id, deleted=params.key),
        summary=f"Deleted meta key '{params.key}' from post {params.post_id}.",
    )


# ─────────── User meta ───────────

@chat.function(
    "get_user_meta",
    description="Read ALL custom-field meta on one WordPress user account. Requires the Imperal Bridge plugin.",
    action_type="read",
    data_model=UserMetaSet,
)
async def get_user_meta(ctx, params: GetUserMetaParams) -> ActionResult:
    """Read all user meta via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/usermeta/{params.user_id}",
                         username=username, app_password=app_password)
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    return ActionResult.success(
        UserMetaSet(id=str(params.user_id), title=f"user {params.user_id} meta", kind="user_meta",
                    user_id=body.get("user_id", params.user_id), meta=body.get("meta", {})),
        summary=f"Read {len(body.get('meta', {}))} meta key(s) on user {params.user_id}.",
    )


@chat.function(
    "update_user_meta",
    description=(
        "Set one or more arbitrary custom-field meta keys/values on a WordPress user account. "
        "Requires the Imperal Bridge plugin."
    ),
    action_type="write",
    data_model=UserMetaUpdateResult,
    effects=["wp.update_user_meta"],
    event="wordpress-hub.update_user_meta",
)
async def update_user_meta(ctx, params: UpdateUserMetaParams) -> ActionResult:
    """Set one or more user meta keys via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "post", base_url, f"{BRIDGE_BASE}/usermeta/{params.user_id}",
                             username=username, app_password=app_password, json={"meta": params.meta})
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    updated = body.get("updated", [])
    return ActionResult.success(
        UserMetaUpdateResult(id=str(params.user_id), title=f"user {params.user_id} meta update",
                              kind="user_meta_update", user_id=body.get("user_id", params.user_id),
                              updated=updated),
        summary=f"Updated {len(updated)} meta key(s) on user {params.user_id}.",
    )


@chat.function(
    "delete_user_meta",
    description="Remove one custom-field meta key from a WordPress user account. Requires the Imperal Bridge plugin.",
    action_type="write",
    data_model=UserMetaDeleteResult,
    effects=["wp.delete_user_meta"],
    event="wordpress-hub.delete_user_meta",
)
async def delete_user_meta(ctx, params: DeleteUserMetaParams) -> ActionResult:
    """Remove one user meta key via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "delete", base_url, f"{BRIDGE_BASE}/usermeta/{params.user_id}/{params.key}",
                             username=username, app_password=app_password)
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    return ActionResult.success(
        UserMetaDeleteResult(id=str(params.user_id), title=f"user {params.user_id} meta delete",
                              kind="user_meta_delete", user_id=params.user_id, deleted=params.key),
        summary=f"Deleted meta key '{params.key}' from user {params.user_id}.",
    )


# ─────────── Term meta ───────────

@chat.function(
    "get_term_meta",
    description=(
        "Read ALL custom-field meta on one taxonomy term (category, tag, or custom taxonomy). "
        "Requires the Imperal Bridge plugin."
    ),
    action_type="read",
    data_model=TermMetaSet,
)
async def get_term_meta(ctx, params: GetTermMetaParams) -> ActionResult:
    """Read all term meta via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/termmeta/{params.term_id}",
                         username=username, app_password=app_password)
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    return ActionResult.success(
        TermMetaSet(id=str(params.term_id), title=f"term {params.term_id} meta", kind="term_meta",
                    term_id=body.get("term_id", params.term_id), meta=body.get("meta", {})),
        summary=f"Read {len(body.get('meta', {}))} meta key(s) on term {params.term_id}.",
    )


@chat.function(
    "update_term_meta",
    description=(
        "Set one or more arbitrary custom-field meta keys/values on a taxonomy term (category, "
        "tag, or custom taxonomy). Requires the Imperal Bridge plugin."
    ),
    action_type="write",
    data_model=TermMetaUpdateResult,
    effects=["wp.update_term_meta"],
    event="wordpress-hub.update_term_meta",
)
async def update_term_meta(ctx, params: UpdateTermMetaParams) -> ActionResult:
    """Set one or more term meta keys via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "post", base_url, f"{BRIDGE_BASE}/termmeta/{params.term_id}",
                             username=username, app_password=app_password, json={"meta": params.meta})
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    updated = body.get("updated", [])
    return ActionResult.success(
        TermMetaUpdateResult(id=str(params.term_id), title=f"term {params.term_id} meta update",
                              kind="term_meta_update", term_id=body.get("term_id", params.term_id),
                              updated=updated),
        summary=f"Updated {len(updated)} meta key(s) on term {params.term_id}.",
    )


def _bulk_term_meta_token(rows: list[tuple[int, dict]], keys: list[str]) -> str:
    state = [
        {"term_id": term_id, "meta": {key: meta.get(key) for key in sorted(keys)}}
        for term_id, meta in sorted(rows)
    ]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def _bulk_term_meta_targets(ctx, params: BulkTermMetaParams):
    if len(set(params.term_ids)) != len(params.term_ids):
        return None, ActionResult.error("Each term id may appear only once.", retryable=False, code="TERM_META_DUPLICATE_IDS")
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return None, err
    base_url, username, app_password = cred
    rows = []
    for term_id in params.term_ids:
        resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/termmeta/{term_id}",
                            username=username, app_password=app_password)
        if resp.status_code >= 400:
            return None, _bridge_missing_error(resp)
        body = resp.body or {}
        rows.append((term_id, body.get("meta", {})))
    return (base_url, username, app_password, rows), None


@chat.function(
    "preview_bulk_term_meta",
    description="Preview setting the same safe custom-meta key/value pairs on 1-100 explicit taxonomy terms. Makes no writes and returns the exact token required to apply.",
    action_type="read", data_model=BulkTermMetaResult,
)
async def preview_bulk_term_meta(ctx, params: BulkTermMetaParams) -> ActionResult:
    """Read every explicit term meta target and return a reviewed batch diff."""
    targets, err = await _bulk_term_meta_targets(ctx, params)
    if err:
        return err
    _, _, _, rows = targets
    changes = [f"#{term_id}: set {', '.join(sorted(params.meta))}" for term_id, _ in rows]
    return ActionResult.success(BulkTermMetaResult(
        id=params.site_id, title="Bulk term meta preview", kind="wp_bulk_term_meta", preview=True,
        requested=len(params.term_ids), matched=len(rows),
        state_token=_bulk_term_meta_token(rows, list(params.meta)), changes=changes),
        summary=f"Preview: set {len(params.meta)} meta key(s) on {len(rows)} term(s)")


@chat.function(
    "apply_bulk_term_meta",
    description="Apply a previewed safe custom-meta update to 1-100 explicit taxonomy terms. Stops before all writes if any target's reviewed keys changed.",
    action_type="destructive", data_model=BulkTermMetaResult,
    effects=["wp.bulk_update_term_meta"], event="wordpress-hub.apply_bulk_term_meta",
)
async def apply_bulk_term_meta(ctx, params: ApplyBulkTermMetaParams) -> ActionResult:
    """Apply identical term meta only if every target still matches the preview token."""
    targets, err = await _bulk_term_meta_targets(ctx, params)
    if err:
        return err
    base_url, username, app_password, rows = targets
    if _bulk_term_meta_token(rows, list(params.meta)) != params.expected_state_token:
        return ActionResult.error("One or more term meta values changed since preview. Run preview_bulk_term_meta again.", retryable=False, code="TERM_META_BULK_STATE_CHANGED")
    updated_ids, failed_ids = [], []
    for term_id, _ in rows:
        resp = await wp_request(ctx, "post", base_url, f"{BRIDGE_BASE}/termmeta/{term_id}",
                                username=username, app_password=app_password, json={"meta": params.meta})
        (updated_ids if resp.status_code < 400 else failed_ids).append(term_id)
    result = BulkTermMetaResult(
        id=params.site_id, title="Bulk term meta result", kind="wp_bulk_term_meta", preview=False,
        requested=len(params.term_ids), matched=len(rows), updated=len(updated_ids), failed=len(failed_ids),
        updated_ids=updated_ids, failed_ids=failed_ids)
    if not updated_ids:
        return ActionResult.error("WordPress did not update any requested term meta.", retryable=True, code="TERM_META_BULK_ALL_FAILED")
    return ActionResult.success(result, summary=f"Updated meta on {len(updated_ids)} term(s); {len(failed_ids)} failed", refresh_panels=["center"])


@chat.function(
    "delete_term_meta",
    description="Remove one custom-field meta key from a taxonomy term. Requires the Imperal Bridge plugin.",
    action_type="write",
    data_model=TermMetaDeleteResult,
    effects=["wp.delete_term_meta"],
    event="wordpress-hub.delete_term_meta",
)
async def delete_term_meta(ctx, params: DeleteTermMetaParams) -> ActionResult:
    """Remove one term meta key via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "delete", base_url, f"{BRIDGE_BASE}/termmeta/{params.term_id}/{params.key}",
                             username=username, app_password=app_password)
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    return ActionResult.success(
        TermMetaDeleteResult(id=str(params.term_id), title=f"term {params.term_id} meta delete",
                              kind="term_meta_delete", term_id=params.term_id, deleted=params.key),
        summary=f"Deleted meta key '{params.key}' from term {params.term_id}.",
    )


# ─────────── wp_options (hard allowlist enforced server-side by the Bridge) ───────────

@chat.function(
    "get_option",
    description=(
        "Read one named row from wp_options. Only option names on the Imperal Bridge's hard "
        "allowlist can be read (Rank Math's own settings, site title/tagline, a few WooCommerce "
        "store-settings names) — never siteurl/home/active_plugins/etc. Requires the Imperal "
        "Bridge plugin."
    ),
    action_type="read",
    data_model=OptionValue,
)
async def get_option(ctx, params: GetOptionParams) -> ActionResult:
    """Read one allowlisted wp_options row via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/option/{params.name}",
                         username=username, app_password=app_password)
    if resp.status_code == 403:
        return ActionResult.error(
            "That option name is not on the Bridge's allowed list — this is a safety boundary, "
            "not a bug.", retryable=False, code="OPTION_NOT_ALLOWED")
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    value = body.get("value")
    return ActionResult.success(
        OptionValue(id=params.name, title=params.name, kind="wp_option", name=params.name,
                    value=value, exists=bool(body.get("exists"))),
        summary=f"Read option '{params.name}'.",
    )


@chat.function(
    "update_option",
    description=(
        "Write one named row in wp_options. Only option names on the Imperal Bridge's hard "
        "allowlist can be written — never siteurl/home/active_plugins/etc, and never a value "
        "that looks like a serialized PHP object (refused server-side). Requires the Imperal "
        "Bridge plugin."
    ),
    action_type="write",
    data_model=OptionValue,
    effects=["wp.update_option"],
    event="wordpress-hub.update_option",
)
async def update_option(ctx, params: UpdateOptionParams) -> ActionResult:
    """Write one allowlisted wp_options row via Bridge SECTION 9."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_request(ctx, "post", base_url, f"{BRIDGE_BASE}/option/{params.name}",
                             username=username, app_password=app_password, json={"value": params.value})
    if resp.status_code == 403:
        return ActionResult.error(
            "That option name is not on the Bridge's allowed list — this is a safety boundary, "
            "not a bug.", retryable=False, code="OPTION_NOT_ALLOWED")
    if resp.status_code == 400:
        return ActionResult.error(
            "That value looks like a serialized PHP object and was refused for safety.",
            retryable=False, code="OPTION_VALUE_UNSAFE")
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    value = body.get("value")
    return ActionResult.success(
        OptionValue(id=params.name, title=params.name, kind="wp_option", name=params.name,
                    value=value, exists=True),
        summary=f"Updated option '{params.name}'.",
    )


# ─────────── ACF field discovery (read-only, degrades cleanly if ACF isn't active) ───────────

@chat.function(
    "list_acf_fields",
    description=(
        "List registered Advanced Custom Fields field groups/fields for a post type, if ACF is "
        "active on the site. Returns a clear not-found error (never a fabricated empty list) if "
        "ACF isn't installed/active. Requires the Imperal Bridge plugin."
    ),
    action_type="read",
    data_model=AcfFieldsResult,
)
async def list_acf_fields(ctx, params: AcfFieldsParams) -> ActionResult:
    """List ACF field groups for a post type via Bridge SECTION 9, if ACF is active."""
    cred, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, app_password = cred
    resp = await wp_get(ctx, base_url, f"{BRIDGE_BASE}/acf-fields",
                         username=username, app_password=app_password,
                         params={"post_type": params.post_type})
    if resp.status_code == 404 and isinstance(resp.body, dict) and \
            "acf" in str(resp.body.get("code", "")).lower():
        return ActionResult.error(
            "Advanced Custom Fields is not active on this site.", retryable=False,
            code="ACF_NOT_ACTIVE")
    if resp.status_code >= 400:
        return _bridge_missing_error(resp)
    body = resp.body or {}
    groups = body.get("field_groups", [])
    return ActionResult.success(
        AcfFieldsResult(id=params.post_type, title=f"ACF fields for {params.post_type}",
                         kind="acf_fields", post_type=body.get("post_type", params.post_type),
                         field_groups=groups),
        summary=f"Found {len(groups)} ACF field group(s) for post type '{params.post_type}'.",
    )
