"""Rank Math SEO meta: read and write for posts, pages and custom post types.

ACCESS STRATEGY
---------------
Rank Math never calls register_post_meta()/register_meta() anywhere in its
codebase (verified against seo-by-rank-math 1.0.274.1), and WordPress core only
exposes meta over REST when it is registered with show_in_rest. So a companion
plugin on the site is required — there is no way to reach these fields with
stock WordPress + Application Password alone.

Two tiers, tried in order:

  1. BRIDGE   /wp-json/imperal/v1/seo  (Imperal SEO Bridge)
     Full fidelity: posts, pages and CPTs; title, description, focus keyword,
     canonical and robots; slug lookup; per-object capability checks.

  2. CORE     /wp-json/wp/v2/<base>/<id>  with `meta`
     Works when only the older WP Publisher Bridge is installed. That plugin
     registers three string fields for the 'post' type only, so this tier is
     posts-only and cannot carry robots or canonical. Used read-only-ish: we
     still allow title/description writes through it because that is exactly
     what it registers, but we say plainly which tier answered.

Every result reports `source` ("bridge" or "core-meta") so the caller always
knows which fidelity it got, and never has to guess why robots came back empty.
"""

from imperal_sdk import ActionResult, sdl

from app import chat
from models import GetSeoMetaParams, UpdateSeoMetaParams, SeoMeta, SiteIdParams
from wp_client import wp_get, wp_post, wp_error_message, wp_error_code
import storage

BRIDGE_PATH = "/wp-json/imperal/v1/seo"
BRIDGE_STATUS_PATH = "/wp-json/imperal/v1/seo/status"

# Rank Math's own accepted values — mirrors Choices::choices_robots().
ROBOTS_CHOICES = ("index", "noindex", "nofollow", "noarchive", "noimageindex", "nosnippet")

# Meta keys, confirmed against the Rank Math source.
KEY_TITLE = "rank_math_title"
KEY_DESCRIPTION = "rank_math_description"
KEY_FOCUS = "rank_math_focus_keyword"
KEY_CANONICAL = "rank_math_canonical_url"
KEY_ROBOTS = "rank_math_robots"

_INSTALL_HINT = (
    "Install the Imperal SEO Bridge plugin on the site (bridge/imperal-seo-bridge "
    "in the connector repo) and make sure Rank Math is active."
)


async def _authed(ctx, site_id):
    """Resolve stored credentials for a site."""
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


def _target_error(params):
    """Neither id nor slug given — refuse rather than guess."""
    if params.post_id is None and not (params.slug or "").strip():
        return ActionResult.error(
            "Tell me which item: pass post_id, or slug (optionally with post_type).",
            retryable=False, code="SEO_TARGET_MISSING")
    return None


def _target_query(params):
    q = {}
    if params.post_id is not None:
        q["id"] = params.post_id
    if params.slug:
        q["slug"] = params.slug.strip()
    if params.post_type:
        q["type"] = params.post_type.strip()
    return q


def _http_failure(status_code, body):
    """Map a WordPress HTTP failure onto a structured ActionResult."""
    retry = status_code >= 500 or status_code == 429
    message = wp_error_message(status_code)
    code = wp_error_code(status_code)

    # The bridge speaks in its own error codes — surface them faithfully.
    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        if wp_code == "imperal_seo_not_found":
            return ActionResult.error(
                wp_message or "No post or page matched that id or slug.",
                retryable=False, code="SEO_ITEM_NOT_FOUND")
        if wp_code == "imperal_seo_ambiguous_slug":
            return ActionResult.error(
                wp_message or "Several items share that slug — pass post_type or post_id.",
                retryable=False, code="SEO_SLUG_AMBIGUOUS")
        if wp_code == "imperal_seo_forbidden":
            return ActionResult.error(
                wp_message or "That WordPress user cannot edit this item.",
                retryable=False, code="WP_FORBIDDEN")
        if wp_code in ("imperal_seo_invalid_robots", "imperal_seo_no_fields",
                       "imperal_seo_missing_target"):
            return ActionResult.error(wp_message or message, retryable=False,
                                      code="SEO_INVALID_REQUEST")
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal SEO Bridge plugin installed. " + _INSTALL_HINT,
                retryable=False, code="SEO_BRIDGE_MISSING")

    return ActionResult.error(message, retryable=retry, code=code)


def _bridge_plugin(payload) -> str:
    """Which SEO plugin the bridge reports as active.

    The bridge answers with a boolean `rank_math_active` flag, not a plugin
    name. Defaulting to "rank-math" when the flag is absent would make the
    "Rank Math is not active" guard unreachable, so the flag is honoured
    whenever it is present and only a missing flag falls back.
    """
    if isinstance(payload, dict) and "rank_math_active" in payload:
        return "rank-math" if payload.get("rank_math_active") else "none"
    return str(payload.get("seo_plugin", "rank-math") or "none")


def _entity_from_bridge(payload, site_url=""):
    """Build a SeoMeta entity from a bridge response.

    The bridge names the object fields `id` and `type` (it speaks WordPress,
    where a payload about a post does not prefix its own id). Accept the
    `post_id`/`post_type` spellings too so a future bridge revision, or a
    hand-rolled endpoint, cannot silently degrade to id 0 / empty type.
    """
    robots = payload.get("robots") or []
    if not isinstance(robots, list):
        robots = [str(robots)] if robots else []
    raw_id = payload.get("id", payload.get("post_id", 0))
    raw_type = payload.get("type", payload.get("post_type", ""))
    try:
        post_id = int(raw_id or 0)
    except (TypeError, ValueError):
        post_id = 0
    return SeoMeta(
        id=str(post_id or ""),
        title=payload.get("post_title", "") or payload.get("slug", ""),
        kind="wp_seo_meta",
        url=payload.get("link", "") or site_url,
        post_id=post_id,
        post_type=str(raw_type or ""),
        slug=payload.get("slug", ""),
        meta_title=payload.get("meta_title", "") or "",
        meta_description=payload.get("meta_description", "") or "",
        focus_keyword=payload.get("focus_keyword", "") or "",
        canonical_url=payload.get("canonical_url", "") or "",
        robots=[str(r) for r in robots],
        seo_plugin=_bridge_plugin(payload),
        source="bridge",
    )


def _entity_from_core(item, site_url=""):
    """Build a SeoMeta entity from a stock REST item carrying registered meta."""
    meta = item.get("meta") or {}
    title = item.get("title") or {}
    rendered = title.get("rendered", "") if isinstance(title, dict) else str(title)
    return SeoMeta(
        id=str(item.get("id", "")),
        title=rendered or item.get("slug", ""),
        kind="wp_seo_meta",
        url=item.get("link", "") or site_url,
        post_id=int(item.get("id", 0) or 0),
        post_type=item.get("type", ""),
        slug=item.get("slug", ""),
        meta_title=meta.get(KEY_TITLE, "") or "",
        meta_description=meta.get(KEY_DESCRIPTION, "") or "",
        focus_keyword=meta.get(KEY_FOCUS, "") or "",
        canonical_url=meta.get(KEY_CANONICAL, "") or "",
        robots=[],
        seo_plugin="rank-math",
        source="core-meta",
    )


def _summarise(entity: SeoMeta) -> str:
    if entity.meta_title or entity.meta_description:
        bits = []
        if entity.meta_title:
            bits.append(f'title "{entity.meta_title}" ({len(entity.meta_title)} chars)')
        else:
            bits.append("no SEO title set")
        if entity.meta_description:
            bits.append(f"description {len(entity.meta_description)} chars")
        else:
            bits.append("no meta description set")
        return f"{entity.post_type or 'item'} #{entity.post_id}: " + ", ".join(bits)
    return (f"{entity.post_type or 'item'} #{entity.post_id}: no Rank Math title or "
            "description set — Rank Math falls back to its template for this type.")


# ── Core-REST fallback helpers ───────────────────────────────────────────────

_CORE_BASES = {"post": "posts", "page": "pages"}


async def _core_lookup(ctx, base_url, username, pw, params):
    """Find an item through the stock REST API and read its registered meta.

    Returns (item, error). Only reaches items whose meta another bridge has
    registered; that is why robots/canonical are absent from this tier.
    """
    bases = []
    if params.post_type:
        bases.append(_CORE_BASES.get(params.post_type, params.post_type))
    else:
        bases = ["posts", "pages"]

    if params.post_id is not None:
        for base in bases:
            r = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{base}/{params.post_id}",
                             username=username, app_password=pw, params={"context": "edit"})
            if r.status_code == 200 and isinstance(r.body, dict):
                return r.body, None
        return None, ActionResult.error(
            "No post or page matched that id.", retryable=False, code="SEO_ITEM_NOT_FOUND")

    slug = (params.slug or "").strip()
    matches = []
    for base in bases:
        r = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{base}",
                         username=username, app_password=pw,
                         params={"slug": slug, "context": "edit", "per_page": 5})
        if r.status_code == 200 and isinstance(r.body, list):
            matches.extend(r.body)

    if not matches:
        return None, ActionResult.error(
            f"No post or page has the slug '{slug}'.", retryable=False, code="SEO_ITEM_NOT_FOUND")
    if len(matches) > 1:
        kinds = ", ".join(sorted({m.get("type", "?") for m in matches}))
        return None, ActionResult.error(
            f"Several items share the slug '{slug}' ({kinds}) — pass post_type or post_id.",
            retryable=False, code="SEO_SLUG_AMBIGUOUS")
    return matches[0], None


def _core_meta_absent(item) -> bool:
    """True when the stock item carries no Rank Math meta at all.

    Distinguishes "no companion plugin registered these fields" from "fields
    are registered but empty" — a distinction that decides whether we tell the
    user to install the bridge or that the SEO fields are simply blank.
    """
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return True
    return not any(k in meta for k in (KEY_TITLE, KEY_DESCRIPTION, KEY_FOCUS))


# ── Tools ────────────────────────────────────────────────────────────────────

@chat.function(
    "get_seo_meta",
    description=("Read the Rank Math SEO fields (meta title, meta description, focus keyword, "
                 "canonical, robots) of one post or page on a connected WordPress site. "
                 "Identify the item by post_id or by slug."),
    action_type="read",
    data_model=SeoMeta,
)
async def get_seo_meta(ctx, params: GetSeoMetaParams) -> ActionResult:
    """Return Rank Math SEO meta for a single post or page."""
    bad_target = _target_error(params)
    if bad_target:
        return bad_target

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    query = _target_query(params)

    # Tier 1 — the bridge.
    try:
        r = await wp_get(ctx, base_url, BRIDGE_PATH, username=username,
                         app_password=pw, params=query)
    except Exception as e:
        await ctx.log(f"get_seo_meta bridge request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 200 and isinstance(r.body, dict):
        entity = _entity_from_bridge(r.body, base_url)
        if not entity.seo_plugin or entity.seo_plugin == "none":
            return ActionResult.error(
                "Rank Math is not active on this site, so there are no Rank Math SEO fields to read.",
                retryable=False, code="SEO_PLUGIN_MISSING")
        return ActionResult.success(entity, summary=_summarise(entity))

    # 404 here means the route is absent, i.e. the bridge is not installed.
    if r.status_code != 404:
        return _http_failure(r.status_code, r.body)

    # Tier 2 — stock REST meta (works with the older WP Publisher bridge, posts only).
    item, core_err = await _core_lookup(ctx, base_url, username, pw, params)
    if core_err:
        return core_err

    if _core_meta_absent(item):
        return ActionResult.error(
            "This site does not expose Rank Math SEO fields to the REST API yet. " + _INSTALL_HINT,
            retryable=False, code="SEO_BRIDGE_MISSING")

    entity = _entity_from_core(item, base_url)
    summary = _summarise(entity) + " (read via core meta — install the Imperal SEO Bridge for robots/canonical)"
    return ActionResult.success(entity, summary=summary)


@chat.function(
    "update_seo_meta",
    description=("Update the Rank Math SEO fields of one post or page on a connected WordPress "
                 "site: meta title, meta description, and optionally focus keyword, canonical URL "
                 "and robots directives. Identify the item by post_id or by slug. "
                 "Omitted fields are left unchanged."),
    action_type="write",
    data_model=SeoMeta,
    effects=["wp.seo_update"],
    event="wp-site-connector.update_seo_meta",
)
async def update_seo_meta(ctx, params: UpdateSeoMetaParams) -> ActionResult:
    """Write Rank Math SEO meta for a single post or page."""
    bad_target = _target_error(params)
    if bad_target:
        return bad_target

    fields = {}
    if params.meta_title is not None:
        fields["meta_title"] = params.meta_title
    if params.meta_description is not None:
        fields["meta_description"] = params.meta_description
    if params.focus_keyword is not None:
        fields["focus_keyword"] = params.focus_keyword
    if params.canonical_url is not None:
        fields["canonical_url"] = params.canonical_url
    if params.robots is not None:
        invalid = [r for r in params.robots if r not in ROBOTS_CHOICES]
        if invalid:
            return ActionResult.error(
                f"Unsupported robots value(s): {', '.join(invalid)}. "
                f"Allowed: {', '.join(ROBOTS_CHOICES)}.",
                retryable=False, code="SEO_INVALID_ROBOTS")
        fields["robots"] = params.robots

    if not fields:
        return ActionResult.error(
            "Nothing to update — pass meta_title and/or meta_description "
            "(or focus_keyword, canonical_url, robots).",
            retryable=False, code="SEO_NO_FIELDS")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    payload = dict(fields)
    payload.update(_target_query(params))

    # Tier 1 — the bridge.
    try:
        r = await wp_post(ctx, base_url, BRIDGE_PATH, username=username,
                          app_password=pw, json=payload)
    except Exception as e:
        await ctx.log(f"update_seo_meta bridge request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 200 and isinstance(r.body, dict):
        entity = _entity_from_bridge(r.body, base_url)
        changed = r.body.get("updated_fields") or list(fields.keys())
        entity.updated_fields = [str(c) for c in changed]
        return ActionResult.success(
            entity,
            summary=f"Updated {', '.join(entity.updated_fields)} on {entity.post_type or 'item'} #{entity.post_id}",
            refresh_panels=["center"])

    if r.status_code != 404:
        return _http_failure(r.status_code, r.body)

    # Tier 2 — stock REST meta. Only the string fields the other bridge registers.
    unsupported = [k for k in ("robots", "canonical_url") if k in fields]
    if unsupported:
        return ActionResult.error(
            f"Cannot set {', '.join(unsupported)} without the Imperal SEO Bridge plugin. " + _INSTALL_HINT,
            retryable=False, code="SEO_BRIDGE_MISSING")

    item, core_err = await _core_lookup(ctx, base_url, username, pw, params)
    if core_err:
        return core_err
    if _core_meta_absent(item):
        return ActionResult.error(
            "This site does not expose Rank Math SEO fields to the REST API yet. " + _INSTALL_HINT,
            retryable=False, code="SEO_BRIDGE_MISSING")

    meta_payload = {}
    if "meta_title" in fields:
        meta_payload[KEY_TITLE] = fields["meta_title"]
    if "meta_description" in fields:
        meta_payload[KEY_DESCRIPTION] = fields["meta_description"]
    if "focus_keyword" in fields:
        meta_payload[KEY_FOCUS] = fields["focus_keyword"]

    base = _CORE_BASES.get(item.get("type", ""), (item.get("type", "") or "posts") + "s")
    post_id = item.get("id")
    try:
        w = await wp_post(ctx, base_url, f"/wp-json/wp/v2/{base}/{post_id}",
                          username=username, app_password=pw, json={"meta": meta_payload})
    except Exception as e:
        await ctx.log(f"update_seo_meta core write failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if not (200 <= w.status_code < 300):
        return _http_failure(w.status_code, w.body)

    entity = _entity_from_core(w.body if isinstance(w.body, dict) else item, base_url)
    entity.updated_fields = [k for k in ("meta_title", "meta_description", "focus_keyword") if k in fields]
    return ActionResult.success(
        entity,
        summary=(f"Updated {', '.join(entity.updated_fields)} on {entity.post_type or 'item'} "
                 f"#{entity.post_id} (via core meta — install the Imperal SEO Bridge for robots/canonical)"),
        refresh_panels=["center"])


@chat.function(
    "check_seo_support",
    description=("Check whether a connected WordPress site can expose Rank Math SEO fields: "
                 "is the Imperal SEO Bridge plugin installed, is Rank Math active, and which "
                 "post types are covered."),
    action_type="read",
    data_model=SeoMeta,
)
async def check_seo_support(ctx, params: SiteIdParams) -> ActionResult:
    """Report SEO bridge and Rank Math availability for a site."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, BRIDGE_STATUS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"check_seo_support request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 404:
        return ActionResult.error(
            "The Imperal SEO Bridge plugin is not installed on this site. " + _INSTALL_HINT,
            retryable=False, code="SEO_BRIDGE_MISSING")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return _http_failure(r.status_code, r.body)

    body = r.body
    plugin = "rank-math" if body.get("rank_math_active") else "none"
    types = [str(t) for t in (body.get("post_types") or [])]
    bridge_version = str(body.get("bridge_version", "") or "")
    entity = SeoMeta(
        id=params.site_id,
        title="SEO support",
        kind="wp_seo_support",
        url=base_url,
        post_types=types,
        bridge_version=bridge_version,
        rank_math_version=str(body.get("rank_math_version", "") or ""),
        seo_plugin=plugin,
        source="bridge",
    )
    if plugin == "none":
        return ActionResult.success(
            entity,
            summary=("Bridge installed, but Rank Math is not active — no Rank Math SEO fields "
                     "to read or write yet."))
    label = f"Bridge {bridge_version}".rstrip()
    return ActionResult.success(
        entity,
        summary=f"{label} active with Rank Math {entity.rank_math_version}".rstrip()
                + f"; covers {len(types)} post type(s): " + ", ".join(types) + ".")
