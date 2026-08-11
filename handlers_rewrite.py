"""Rewrite rules & permalinks: read/update the permalink structure, flush
rewrite rules, and list compiled rules.

Bridge-first, SSH-fallback -- same pattern as handlers_maintenance.py and
handlers_cache_cron.py. WordPress core's own /wp/v2/settings endpoint has
never reliably exposed permalink_structure across versions (added in 4.9
by #41014, then removed again over #45017 fallout because plain-permalink
sites collided with the REST index's own use of that field name), and it
has never round-tripped category_base/tag_base at all -- so this reads
through the Imperal Bridge plugin (SECTION 17, 2.13.0+), the same
WP_Rewrite::set_permalink_structure() + explicit flush_rewrite_rules()
wp-admin's own Settings > Permalinks "Save Changes" button performs, or
falls back to SSH + WP-CLI (`wp rewrite structure` / `wp rewrite flush` /
`wp rewrite list`) if SSH is configured with add_ssh.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    FlushRewriteRulesResult,
    ListRewriteRulesParams,
    PermalinkStructureResult,
    RewriteRuleItem,
    SiteIdParams,
    UpdatePermalinkStructureParams,
)
import storage
import wp_cli
from wp_client import wp_get, wp_post

BRIDGE_REWRITE_STRUCTURE_PATH = "/wp-json/imperal/v1/rewrite/structure"
BRIDGE_REWRITE_FLUSH_PATH = "/wp-json/imperal/v1/rewrite/flush"
BRIDGE_REWRITE_RULES_PATH = "/wp-json/imperal/v1/rewrite/rules"


async def _site_auth(ctx, site_id):
    """Resolve (base_url, username, password) for the Bridge probe, or an error."""
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], pw), None


async def _bridge_get(ctx, base_url, username, pw, path, params=None):
    try:
        r = await wp_get(ctx, base_url, path, username=username, app_password=pw, params=params)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


async def _bridge_post(ctx, base_url, username, pw, path, json_body=None):
    try:
        r = await wp_post(ctx, base_url, path, username=username, app_password=pw, json=json_body)
    except Exception:
        return None
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None
    return r.body


def _no_bridge_no_ssh_error():
    return ActionResult.error(
        "Neither the Imperal Bridge plugin nor SSH is available for this site. "
        "Install the Bridge plugin, or add SSH access with add_ssh.", retryable=False,
        code="SSH_NOT_CONFIGURED")


@chat.function(
    "get_permalink_structure",
    description=(
        "Read the site's current permalink structure plus its category/tag base slugs — "
        "the same three values wp-admin's Settings > Permalinks screen reads. Reads through "
        "the Imperal Bridge plugin if it's installed, or falls back to SSH + WP-CLI "
        "(`wp option get`) if SSH is configured with add_ssh. Native /wp/v2/settings is not "
        "used because permalink_structure exposure there is unreliable across WordPress "
        "versions and never included category_base/tag_base at all."
    ),
    action_type="read", data_model=PermalinkStructureResult,
)
async def get_permalink_structure(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/rewrite/structure GET), SSH-fallback (`wp option get` x3)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_REWRITE_STRUCTURE_PATH)
    if body is not None:
        return ActionResult.success(
            PermalinkStructureResult(
                id=params.site_id, title="Permalink structure", kind="wp_permalink_structure",
                permalink_structure=body.get("permalink_structure", ""),
                category_base=body.get("category_base", ""),
                tag_base=body.get("tag_base", ""),
            ),
            summary="Permalink structure",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        data, cli_error = await wp_cli.get_permalink_structure(cred)
    except Exception as e:
        await ctx.log(f"get_permalink_structure: {e}", level="error")
        return ActionResult.error("Could not read the permalink structure over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"get_permalink_structure: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    data = data or {}
    return ActionResult.success(
        PermalinkStructureResult(
            id=params.site_id, title="Permalink structure", kind="wp_permalink_structure",
            permalink_structure=data.get("permalink_structure", ""),
            category_base=data.get("category_base", ""),
            tag_base=data.get("tag_base", ""),
        ),
        summary="Permalink structure",
    )


@chat.function(
    "update_permalink_structure",
    description=(
        "Update the site's permalink structure and/or category/tag base slugs, then flush "
        "rewrite rules — the same two-step wp-admin's Settings > Permalinks 'Save Changes' "
        "button performs. Reads through the Imperal Bridge plugin if it's installed, or falls "
        "back to SSH + WP-CLI (`wp rewrite structure`) if SSH is configured with add_ssh. Pass "
        "an empty permalink_structure for plain '?p=123' links."
    ),
    action_type="write", data_model=PermalinkStructureResult,
    effects=["wp.update_permalink_structure"], event="wordpress-hub.update_permalink_structure",
)
async def update_permalink_structure(ctx, params: UpdatePermalinkStructureParams) -> ActionResult:
    """Bridge-first (/rewrite/structure POST), SSH-fallback (`wp rewrite structure`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    json_body = {"permalink_structure": params.permalink_structure}
    if params.category_base is not None:
        json_body["category_base"] = params.category_base
    if params.tag_base is not None:
        json_body["tag_base"] = params.tag_base

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_REWRITE_STRUCTURE_PATH, json_body=json_body)
    if body is not None:
        return ActionResult.success(
            PermalinkStructureResult(
                id=params.site_id, title="Permalink structure", kind="wp_permalink_structure",
                permalink_structure=body.get("permalink_structure", ""),
                category_base=body.get("category_base", ""),
                tag_base=body.get("tag_base", ""),
            ),
            summary="Updated permalink structure and flushed rewrite rules.",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        _, cli_error = await wp_cli.update_permalink_structure(
            cred, params.permalink_structure, params.category_base, params.tag_base,
        )
    except Exception as e:
        await ctx.log(f"update_permalink_structure: {e}", level="error")
        return ActionResult.error("Could not update the permalink structure over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"update_permalink_structure: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        PermalinkStructureResult(
            id=params.site_id, title="Permalink structure", kind="wp_permalink_structure",
            permalink_structure=params.permalink_structure,
            category_base=params.category_base or "",
            tag_base=params.tag_base or "",
        ),
        summary="Updated permalink structure and flushed rewrite rules.",
    )


@chat.function(
    "flush_rewrite_rules",
    description=(
        "Flush the site's rewrite rules — regenerates the compiled rules WordPress uses to "
        "match incoming URLs, without changing the permalink structure itself. Useful after "
        "a plugin/theme registers new post types or CPT rewrite rules and 404s appear on its "
        "own URLs. Reads through the Imperal Bridge plugin if it's installed, or falls back "
        "to SSH + WP-CLI (`wp rewrite flush`) if SSH is configured with add_ssh."
    ),
    action_type="write", data_model=FlushRewriteRulesResult,
    effects=["wp.flush_rewrite_rules"], event="wordpress-hub.flush_rewrite_rules",
)
async def flush_rewrite_rules(ctx, params: SiteIdParams) -> ActionResult:
    """Bridge-first (/rewrite/flush POST), SSH-fallback (`wp rewrite flush`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_post(ctx, base_url, username, pw, BRIDGE_REWRITE_FLUSH_PATH)
    if body is not None:
        return ActionResult.success(
            FlushRewriteRulesResult(
                id=params.site_id, title="Rewrite rules flushed", kind="wp_rewrite_flush",
                flushed=True, rule_count=int(body.get("rule_count", 0) or 0),
            ),
            summary=f"Flushed rewrite rules ({body.get('rule_count', 0)} rules compiled).",
        )

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        _, cli_error = await wp_cli.flush_rewrite_rules(cred)
    except Exception as e:
        await ctx.log(f"flush_rewrite_rules: {e}", level="error")
        return ActionResult.error("Could not flush rewrite rules over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"flush_rewrite_rules: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    return ActionResult.success(
        FlushRewriteRulesResult(
            id=params.site_id, title="Rewrite rules flushed", kind="wp_rewrite_flush",
            flushed=True, rule_count=0,
        ),
        summary="Flushed rewrite rules.",
    )


@chat.function(
    "list_rewrite_rules",
    description=(
        "List the site's compiled rewrite rules — each rule's regex match pattern and the "
        "query string it maps to, matching `wp rewrite list`. Useful for diagnosing why a "
        "custom post type or plugin URL 404s. Reads through the Imperal Bridge plugin if "
        "it's installed, or falls back to SSH + WP-CLI (`wp rewrite list`) if SSH is "
        "configured with add_ssh."
    ),
    action_type="read", data_model=sdl.EntityList[RewriteRuleItem],
)
async def list_rewrite_rules(ctx, params: ListRewriteRulesParams) -> ActionResult:
    """Bridge-first (/rewrite/rules GET), SSH-fallback (`wp rewrite list`)."""
    auth, err = await _site_auth(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    body = await _bridge_get(ctx, base_url, username, pw, BRIDGE_REWRITE_RULES_PATH)
    if body is not None:
        rows = body.get("rules", []) if isinstance(body, dict) else []
        items = [
            RewriteRuleItem(
                id=str(i), title=str(r.get("match", "")), kind="wp_rewrite_rule",
                match=r.get("match", ""), query=r.get("query", ""),
            )
            for i, r in enumerate(rows)
        ]
        return ActionResult.success(sdl.EntityList[RewriteRuleItem](items=items), summary=f"{len(items)} rewrite rule(s)")

    cred = await storage.get_ssh_cred(ctx, params.site_id)
    if not cred:
        return _no_bridge_no_ssh_error()
    try:
        rows, cli_error = await wp_cli.list_rewrite_rules(cred)
    except Exception as e:
        await ctx.log(f"list_rewrite_rules: {e}", level="error")
        return ActionResult.error("Could not list rewrite rules over SSH.", retryable=True)
    if cli_error:
        await ctx.log(f"list_rewrite_rules: {cli_error}", level="error")
        return ActionResult.error(cli_error, retryable=True)

    rows = rows or []
    items = [
        RewriteRuleItem(
            id=str(i), title=str(r.get("match", "")), kind="wp_rewrite_rule",
            match=r.get("match", ""), query=r.get("query", ""),
        )
        for i, r in enumerate(rows)
    ]
    return ActionResult.success(sdl.EntityList[RewriteRuleItem](items=items), summary=f"{len(items)} rewrite rule(s)")
