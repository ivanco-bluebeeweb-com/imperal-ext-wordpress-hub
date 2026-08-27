"""Polylang post language + translation linking (Bridge SECTION 20).

Polylang never registers REST routes for setting a post's language or for
linking two posts as translations of each other -- the admin editor's
"Languages" > "Translations" panel talks to admin-ajax.php, not the REST
API. This is the same kind of gap SECTION 1 solves for Rank Math SEO meta
and SECTION 5 solves for redirects. This module talks exclusively to
Imperal Bridge SECTION 20 (/wp-json/imperal/v1/polylang/*) -- there is no
stock-WordPress fallback tier, because there is no core concept of a
"translation link" for us to fall back onto.

Built as a generic capability: works on ANY post type Polylang manages, on
ANY connected WordPress site running Polylang -- not hardcoded to climtec.md
or to the 'product' post type.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    GetPostTranslationsParams,
    LinkPostTranslationsParams,
    LinkPostTranslationsResult,
    PolylangTranslations,
    PostLanguageResult,
    SetPostLanguageParams,
)

import storage
from wp_client import wp_error_code, wp_error_message, wp_post

BRIDGE_STATUS_PATH = "/wp-json/imperal/v1/polylang/status"
BRIDGE_TRANSLATIONS_PATH = "/wp-json/imperal/v1/polylang/translations"
BRIDGE_LANGUAGE_PATH = "/wp-json/imperal/v1/polylang/language"
BRIDGE_LINK_PATH = "/wp-json/imperal/v1/polylang/link-translations"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin (v2.25.0+) on the site (bridge/imperal-bridge "
    "in the connector repo) and make sure Polylang is active."
)


async def _authed(ctx, site_id):
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


def _failure(status_code, body):
    if isinstance(body, dict):
        wp_code = body.get("code", "")
        wp_message = body.get("message", "")
        if wp_code == "rest_no_route":
            return ActionResult.error(
                "This site does not have the Imperal Bridge plugin installed, or it is "
                "older than the version that adds Polylang translation linking. " + _INSTALL_HINT,
                retryable=False, code="POLYLANG_BRIDGE_MISSING")
        if wp_code == "imperal_polylang_inactive":
            return ActionResult.error(
                wp_message or "Polylang is not active on this site.",
                retryable=False, code="POLYLANG_NOT_ACTIVE")
        if wp_code == "imperal_polylang_not_found":
            return ActionResult.error(
                wp_message or "No post exists with that id.",
                retryable=False, code="POLYLANG_POST_NOT_FOUND")
        if wp_code == "imperal_polylang_unknown_language":
            return ActionResult.error(
                wp_message or "That language code is not configured on this site.",
                retryable=False, code="POLYLANG_UNKNOWN_LANGUAGE")
        if wp_code == "imperal_polylang_bad_id" or wp_code == "imperal_polylang_bad_translations":
            return ActionResult.error(
                wp_message or "Invalid request.", retryable=False, code="POLYLANG_INVALID")
        if wp_message:
            return ActionResult.error(
                wp_message, retryable=status_code >= 500, code=wp_error_code(status_code))
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


@chat.function(
    "get_post_translations",
    description=(
        "Read one post/page/CPT item's current Polylang language, plus every translation "
        "already linked to it (language code -> post id). Use this before link_post_translations "
        "to see what is already linked. Requires the Imperal Bridge plugin and Polylang active."
    ),
    action_type="read", data_model=PolylangTranslations,
)
async def get_post_translations(ctx, params: GetPostTranslationsParams) -> ActionResult:
    """GET /imperal/v1/polylang/translations?post_id=..."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    from wp_client import wp_get
    r = await wp_get(ctx, base_url, BRIDGE_TRANSLATIONS_PATH, username=username, app_password=pw,
                      params={"post_id": params.post_id})
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    translations = body.get("translations") or {}
    result = PolylangTranslations(
        post_id=int(body.get("post_id", params.post_id) or 0),
        post_type=body.get("post_type", ""),
        title=body.get("title", ""),
        language=body.get("language", ""),
        translations=translations,
    )
    summary = f"Post #{result.post_id} is language '{result.language or 'unset'}'"
    if translations:
        pairs = ", ".join(f"{lang}=#{pid}" for lang, pid in translations.items())
        summary += f", linked translations: {pairs}"
    else:
        summary += ", no translations linked yet"
    return ActionResult.success(result, summary=summary)


@chat.function(
    "set_post_language",
    description=(
        "Assign a Polylang language to one post/page/CPT item. Must be a language code the site "
        "already has configured (e.g. 'ru', 'ro', 'en') -- use get_post_translations or check the "
        "site's Languages settings first if unsure. Requires the Imperal Bridge plugin and Polylang active."
    ),
    action_type="write", data_model=PostLanguageResult,
    effects=["wp.polylang_language_set"], event="wordpress-hub.set_post_language",
)
async def set_post_language(ctx, params: SetPostLanguageParams) -> ActionResult:
    """POST /imperal/v1/polylang/language."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_post(ctx, base_url, BRIDGE_LANGUAGE_PATH, username=username, app_password=pw,
                           json={"post_id": params.post_id, "language": params.language})
    except Exception as e:
        await ctx.log(f"set_post_language request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    result = PostLanguageResult(post_id=int(body.get("post_id", params.post_id) or 0),
                                 language=body.get("language", params.language))
    return ActionResult.success(result, summary=f"Post #{result.post_id} language set to '{result.language}'",
                                 refresh_panels=["center"])


@chat.function(
    "link_post_translations",
    description=(
        "Link posts as Polylang translations of each other -- this is the exact operation behind "
        "the editor's Languages > Translations field. Pass a map of language code to post id, e.g. "
        "{'ru': 2551, 'ro': 2556}, and every listed post becomes a translation of every other one "
        "(each post is assigned the language it's mapped under, then Polylang's own "
        "pll_save_post_translations links them as a group). Works for any post type Polylang manages "
        "on any connected site with Polylang active -- not limited to one CPT or one site. "
        "Requires the Imperal Bridge plugin (v2.25.0+)."
    ),
    action_type="write", data_model=LinkPostTranslationsResult,
    effects=["wp.polylang_translations_link"], event="wordpress-hub.link_post_translations",
)
async def link_post_translations(ctx, params: LinkPostTranslationsParams) -> ActionResult:
    """POST /imperal/v1/polylang/link-translations."""
    if len(params.translations) < 2:
        return ActionResult.error(
            "Pass at least two language:post_id pairs to link as translations of each other.",
            retryable=False, code="POLYLANG_NEED_TWO")
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    try:
        r = await wp_post(ctx, base_url, BRIDGE_LINK_PATH, username=username, app_password=pw,
                           json={"translations": params.translations})
    except Exception as e:
        await ctx.log(f"link_post_translations request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True, code="WP_UNREACHABLE")
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    body = r.body if isinstance(r.body, dict) else {}
    translations = body.get("translations") or params.translations
    result = LinkPostTranslationsResult(site_id=params.site_id, translations=translations)
    pairs = ", ".join(f"{lang}=#{pid}" for lang, pid in translations.items())
    return ActionResult.success(result, summary=f"Linked as translations: {pairs}",
                                 refresh_panels=["center"])
