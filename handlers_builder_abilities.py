"""Universal dispatcher for WordPress's own Abilities API (wp-abilities/v1).

Why this exists (not one @chat.function per ability):
Bricks alone registers ~100-140 abilities once 'Bricks > AI' is on
(bricks/get-design-context, bricks/add-element, bricks/set-page-elements,
...). Every other page builder that adopts the same WordPress-core
Abilities API (Elementor, Divi, etc. as they ship support) will register
its own such set. Wiring one @chat.function per ability, per builder,
does not scale -- 10-15 builders x ~100-145 abilities each would push this
single connector toward 2000+ registered tools, which breaks tool
selection, per-tool pricing, and maintenance alike.

Instead: 3 fixed functions cover an UNBOUNDED number of builders and
abilities, because "which ability to run" becomes a runtime STRING
parameter instead of a compile-time tool name:

  - describe_builder_ability -- read one ability's own declared schema
    (what inputs/output it expects) before calling it
  - call_builder_ability     -- run any NON-destructive ability (safe or
    plain write) directly
  - call_builder_ability_risky -- run a DESTRUCTIVE ability only, gated by
    the platform's own action_type="destructive" 2-step confirmation

Every ability WordPress returns already self-declares
meta.annotations.readonly / .destructive (this is not our own guess --
it is the mechanism check_builder_support's bricks_readiness relies on
too). call_builder_ability reads that flag before running anything and
refuses destructive abilities with a clear pointer to the _risky twin --
the same shape as update_order_status / update_order_status_risky
elsewhere in this connector.

HTTP mapping straight from WordPress core's own Abilities REST API
(developer.wordpress.org/apis/abilities-api/rest-api-endpoints/,
WP_REST_Abilities_V1_Run_Controller):
  - GET    /wp-abilities/v1/{namespace}/{ability}       -- one ability's schema
  - GET    /wp-abilities/v1/{namespace}/{ability}/run   -- run a readonly ability
  - POST   /wp-abilities/v1/{namespace}/{ability}/run   -- run a write ability
  - DELETE /wp-abilities/v1/{namespace}/{ability}/run   -- run a destructive ability
Input is passed as the query param 'input' (GET/DELETE) or a JSON body
{"input": {...}} (POST). All authenticated with the site's own connected
Application Password -- no Bridge change, no MCP/JSON-RPC client needed.
"""
import json

from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    BuilderAbilityResult,
    CallBuilderAbilityParams,
    DescribeBuilderAbilityParams,
    WpAbility,
)
from wp_client import wp_error_code, wp_error_message, wp_get, wp_request
import storage

ABILITIES_BASE = "/wp-json/wp-abilities/v1/abilities"


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
            "That ability doesn't exist on this site — run list_wp_abilities to see what's "
            "actually registered (the builder may not be active, or its AI/abilities toggle "
            "may be off).",
            retryable=False, code="WP_ABILITY_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot run this ability. Reconnect with an "
            "administrator Application Password, or check the ability's own permission "
            "requirements.",
            retryable=False, code="WP_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _split_ability_name(ability_name: str):
    """'bricks/get-design-context' -> ('bricks', 'get-design-context')."""
    if "/" not in ability_name:
        return None
    namespace, _, ability = ability_name.partition("/")
    if not namespace or not ability:
        return None
    return namespace, ability


async def _fetch_ability_meta(ctx, base_url, username, pw, namespace, ability):
    """GET the ability's own schema+annotations. Returns (dict|None, ActionResult|None)."""
    r = await wp_get(
        ctx, base_url, f"{ABILITIES_BASE}/{namespace}/{ability}",
        username=username, app_password=pw)
    if r.status_code >= 400:
        return None, _failure(r.status_code, r.body)
    return r.body if isinstance(r.body, dict) else {}, None


def _annotations(meta: dict) -> dict:
    return ((meta.get("meta") or {}).get("annotations") or {}) if isinstance(meta, dict) else {}


@chat.function(
    "describe_builder_ability",
    description=(
        "Read ONE WordPress builder ability's own declared schema (input_schema, output_schema, "
        "and its readonly/destructive/idempotent annotations) before calling it -- e.g. "
        "'bricks/set-page-elements' or 'bricks/add-element'. Works for any builder that registers "
        "abilities via WordPress's own Abilities API, not just Bricks. Always call this before "
        "call_builder_ability for an ability you haven't used yet, so the input object you send "
        "actually matches what the ability expects."
    ),
    action_type="read", data_model=WpAbility,
)
async def describe_builder_ability(ctx, params: DescribeBuilderAbilityParams) -> ActionResult:
    """GET /wp-abilities/v1/{namespace}/{ability} -- one ability's full declared schema."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    split = _split_ability_name(params.ability_name)
    if not split:
        return ActionResult.error(
            "ability_name must be 'namespace/ability', e.g. 'bricks/get-design-context' -- "
            "run list_wp_abilities to see exact names.",
            retryable=False, code="WP_ABILITY_NAME_INVALID")
    namespace, ability = split
    meta, err = await _fetch_ability_meta(ctx, base_url, username, pw, namespace, ability)
    if err:
        return err
    name = meta.get("name", params.ability_name) or params.ability_name
    return ActionResult.success(
        WpAbility(
            id=name, title=meta.get("label", "") or name,
            name=name, label=meta.get("label", "") or "",
            description=meta.get("description", "") or "",
            category=meta.get("category", "") or "",
            input_schema=meta.get("input_schema") if isinstance(meta.get("input_schema"), dict) else {},
            output_schema=meta.get("output_schema") if isinstance(meta.get("output_schema"), dict) else {},
            meta=meta.get("meta") if isinstance(meta.get("meta"), dict) else {}),
        summary=f"{name}: {meta.get('description', '') or 'no description'}")


async def _run_ability(ctx, params: CallBuilderAbilityParams, *, allow_destructive: bool):
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    split = _split_ability_name(params.ability_name)
    if not split:
        return ActionResult.error(
            "ability_name must be 'namespace/ability', e.g. 'bricks/get-design-context' -- "
            "run list_wp_abilities to see exact names.",
            retryable=False, code="WP_ABILITY_NAME_INVALID")
    namespace, ability = split

    meta, err = await _fetch_ability_meta(ctx, base_url, username, pw, namespace, ability)
    if err:
        return err
    annotations = _annotations(meta)
    is_destructive = bool(annotations.get("destructive"))
    is_readonly = bool(annotations.get("readonly"))

    if is_destructive and not allow_destructive:
        return ActionResult.error(
            f"'{params.ability_name}' is marked destructive by the site itself -- use "
            "call_builder_ability_risky, which requires explicit confirmation.",
            retryable=False, code="WP_ABILITY_REQUIRES_CONFIRMATION")
    if not is_destructive and allow_destructive:
        return ActionResult.error(
            f"'{params.ability_name}' is not marked destructive -- use call_builder_ability "
            "for it instead.",
            retryable=False, code="WP_ABILITY_NOT_DESTRUCTIVE")

    run_path = f"{ABILITIES_BASE}/{namespace}/{ability}/run"
    if is_destructive:
        # Same query-param serialization fix as the GET path below --
        # DELETE also carries 'input' as a query param, not a JSON body.
        r = await wp_request(
            ctx, "delete", base_url, run_path, username=username, app_password=pw,
            params={"input": json.dumps(params.input)} if params.input else None)
    elif is_readonly:
        # GET query params must be flat strings -- httpx str()-ifies a raw
        # dict into Python repr (single-quoted), which WordPress's REST
        # input-schema validation rejects as invalid JSON (HTTP 400). The
        # ability's own 'input' argument must travel as a JSON-encoded
        # string in the query string instead.
        r = await wp_get(
            ctx, base_url, run_path, username=username, app_password=pw,
            params={"input": json.dumps(params.input)} if params.input else None)
    else:
        r = await wp_request(
            ctx, "post", base_url, run_path, username=username, app_password=pw,
            json={"input": params.input} if params.input else {})

    if r.status_code >= 400:
        return _failure(r.status_code, r.body)

    output = r.body.get("output") if isinstance(r.body, dict) and "output" in r.body else r.body
    return ActionResult.success(
        BuilderAbilityResult(ability_name=params.ability_name, output=output),
        summary=f"{params.ability_name}: ran successfully",
        refresh_panels=["center"])


@chat.function(
    "call_builder_ability",
    description=(
        "Run ONE non-destructive WordPress builder ability by exact name (e.g. "
        "'bricks/get-design-context', 'bricks/set-page-elements', 'bricks/add-element') -- the "
        "universal dispatcher that covers any builder registering abilities via WordPress's own "
        "Abilities API, without needing one tool per ability. Call describe_builder_ability first "
        "to see the expected 'input' shape. Once check_builder_support reports bricks_readiness "
        "'ready', use this for ALL real page authoring -- never hand-author raw "
        "_bricks_page_content_2 postmeta as a substitute; it can silently render empty in the "
        "real builder. Abilities the site itself marks destructive are refused here -- use "
        "call_builder_ability_risky for those."
    ),
    action_type="write", data_model=BuilderAbilityResult,
)
async def call_builder_ability(ctx, params: CallBuilderAbilityParams) -> ActionResult:
    """GET (readonly) or POST (write) /wp-abilities/v1/{namespace}/{ability}/run."""
    return await _run_ability(ctx, params, allow_destructive=False)


@chat.function(
    "call_builder_ability_risky",
    description=(
        "Run ONE ability the site itself marks destructive (e.g. an ability that deletes or "
        "irreversibly overwrites content) after explicit confirmation. Refuses any ability that "
        "is NOT marked destructive -- use call_builder_ability for those instead. Same universal "
        "dispatcher shape as call_builder_ability, covering any builder on WordPress's own "
        "Abilities API."
    ),
    action_type="destructive", data_model=BuilderAbilityResult,
)
async def call_builder_ability_risky(ctx, params: CallBuilderAbilityParams) -> ActionResult:
    """DELETE /wp-abilities/v1/{namespace}/{ability}/run -- destructive abilities only."""
    return await _run_ability(ctx, params, allow_destructive=True)
