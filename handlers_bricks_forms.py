"""Bricks form completeness audit -- detect and nudge fixes for
half-configured Bricks form elements, site-wide, on connect and every 3
days after (`@ext.schedule`).

WHY THIS EXISTS. A Bricks "form" element can be dropped on any page fully
unwired: no name (submissions show as "[No name]" in wp-admin), no action
at all (submit silently does nothing), "Save submission" not selected --
or selected but the site-wide "Save form submissions in database" switch
in Bricks > Settings > General is off, in which case Bricks never even
creates the admin-sidebar Form Submissions screen -- and default/blank
success or error messages. None of this throws an error anywhere; it just
quietly loses leads. This module makes that impossible to miss: one audit
call sweeps every Bricks form on the whole site, and the same audit is the
body of a system-wide `@ext.schedule` tick.

DETECTION LIVES SERVER-SIDE (imperal_builder_bridge_form_audit(), Bridge
SECTION 22) for the same reason the site-wide builder scan does: this can
be hundreds of pages/templates, and sending every Bricks tree over HTTP to
grade it here would be needlessly heavy. The bridge already decodes each
tree once for imperal_builder_bridge_scan(); the form audit reuses the
exact same flatten/decode helpers, one call, one place forms are ever
graded -- so the panel prompt and the schedule tick can never disagree
about what "fully configured" means.
"""

from imperal_sdk import ActionResult

from app import chat, ext
from handlers_builders import _authed, _http_failure
from models import AuditBricksFormsResult, BricksFormIssue, SiteIdParams
from wp_client import wp_get
import storage

BRIDGE_FORMS_PATH = "/wp-json/imperal/v1/builder/forms"

_INSTALL_HINT = (
    "Install the Imperal Bridge plugin on the site (bridge/imperal-bridge "
    "in the connector repo) to audit Bricks forms."
)

ISSUE_LABELS = {
    "form_name": "no form name set (submissions will show as \"[No name]\")",
    "action": "no action selected -- submitting the form does nothing",
    "save_submission": "\"Save submission\" action not selected on this form",
    "save_submission_global": (
        "site-wide \"Save form submissions in database\" is OFF in "
        "Bricks > Settings > General -- no form on this site can save to "
        "the database or show up in the admin sidebar until this is on"
    ),
    "success_message": "no custom success message (visitors see Bricks' generic default)",
    "error_message": "no custom error message on any action that supports one",
}


def _issue_row(raw: dict) -> BricksFormIssue:
    return BricksFormIssue(
        id=f"{raw.get('post_id', 0)}:{raw.get('element_id', '')}",
        title=str(raw.get("form_name") or raw.get("post_title") or "Untitled form"),
        kind="wp_bricks_form_issue",
        post_id=int(raw.get("post_id", 0) or 0),
        post_title=str(raw.get("post_title", "") or ""),
        post_type=str(raw.get("post_type", "") or ""),
        zone=str(raw.get("zone", "") or ""),
        element_id=str(raw.get("element_id", "") or ""),
        form_name=str(raw.get("form_name", "") or ""),
        issues=[str(i) for i in (raw.get("issues") or [])],
    )


def _summarise(result: AuditBricksFormsResult) -> str:
    if result.total_forms_found == 0:
        return "No Bricks form elements found on this site."
    if result.all_complete:
        return (f"All {result.total_forms_found} Bricks form(s) on this site are fully "
                f"configured (name, action, save submission, success + error message).")
    n = len(result.incomplete_forms)
    lines = [f"{n} of {result.total_forms_found} Bricks form(s) need attention:"]
    for row in result.incomplete_forms[:10]:
        where = f"{row.post_title or row.post_type} (post {row.post_id}, {row.zone})"
        problems = "; ".join(ISSUE_LABELS.get(i, i) for i in row.issues)
        lines.append(f"- {where}: {problems}")
    if n > 10:
        lines.append(f"...and {n - 10} more.")
    return "\n".join(lines)


async def _run_audit(ctx, site_id: str) -> tuple[AuditBricksFormsResult | None, ActionResult | None]:
    """Shared body: calls the bridge, returns a built result or an error.
    Used by both the chat tool and the connect-hook / schedule tick, so
    they can never disagree about what counts as 'incomplete'."""
    auth, err = await _authed(ctx, site_id)
    if err:
        return None, err
    base_url, username, pw = auth

    try:
        r = await wp_get(ctx, base_url, BRIDGE_FORMS_PATH, username=username, app_password=pw)
    except Exception as e:
        await ctx.log(f"audit_bricks_forms request failed: {e}", level="error")
        return None, ActionResult.error("Could not reach the site — try again.",
                                        retryable=True, code="WP_UNREACHABLE")

    if r.status_code == 404:
        return None, ActionResult.error(
            "This site does not have the Imperal Bridge plugin installed, or it is older "
            "than 2.27.0 (Bricks form audit needs 2.27.0+). " + _INSTALL_HINT,
            retryable=False, code="BUILDER_BRIDGE_MISSING")
    if r.status_code != 200 or not isinstance(r.body, dict):
        return None, _http_failure(r.status_code, r.body)

    body = r.body
    incomplete_raw = [f for f in (body.get("forms") or []) if isinstance(f, dict) and not f.get("is_complete", True)]
    incomplete = [_issue_row(f) for f in incomplete_raw]
    result = AuditBricksFormsResult(
        id=site_id, title="Bricks form audit", kind="wp_bricks_form_audit",
        site_id=site_id,
        save_submissions_enabled_globally=bool(body.get("save_submissions_enabled_globally", False)),
        total_forms_found=int(body.get("total_found", 0) or 0),
        incomplete_forms=incomplete,
        all_complete=(len(incomplete) == 0),
    )
    return result, None


@chat.function(
    "audit_bricks_forms",
    description=(
        "Sweep every Bricks form element on a connected site (every page, post, "
        "template) and report which ones are incompletely configured: missing form "
        "name, no action selected, 'Save submission' not chosen, the site-wide "
        "'Save form submissions in database' switch off, missing success message, "
        "or missing error message. Call this after connecting a new site, or any "
        "time to re-check -- the same check also runs automatically every 3 days "
        "and nudges in chat when something is still incomplete."
    ),
    action_type="read",
    data_model=AuditBricksFormsResult,
)
async def audit_bricks_forms(ctx, params: SiteIdParams) -> ActionResult:
    """Report every incompletely-configured Bricks form on one site."""
    result, err = await _run_audit(ctx, params.site_id)
    if err:
        return err
    return ActionResult.success(result, summary=_summarise(result))


@ext.schedule("bricks_form_audit_nag", "0 9 * * *")
async def bricks_form_audit_nag(ctx) -> None:
    """Every-3-days nudge, system-wide, for every user with a connected site.

    Runs daily (cron ticks every day at 09:00 UTC) but only actually acts on
    a given site once its own last-nagged timestamp is >= 3 days old -- the
    same "ask every tick, act rarely" shape as Page Speed Insights' and SEO
    Audit Engine's own schedules. Fans out per-user via ctx.store.list_users
    / ctx.as_user, because a schedule tick runs in system context and cannot
    see any one user's own sites otherwise (see imperal_sdk's own schedule()
    docstring).
    """
    async for uid in ctx.store.list_users(storage.SITES_COLLECTION):
        user_ctx = ctx.as_user(uid)
        try:
            sites = await storage.list_site_records(user_ctx)
        except Exception as e:
            await ctx.log(f"bricks_form_audit_nag: could not list sites for {uid}: {e}", level="warning")
            continue

        for site in sites:
            site_id = site.get("id") or site.get("site_id")
            if not site_id:
                continue
            due = await storage.form_audit_is_due(user_ctx, site_id)
            if not due:
                continue

            result, err = await _run_audit(user_ctx, site_id)
            # Stamp "checked now" regardless of outcome -- a site with the bridge
            # missing or unreachable must not be re-tried every single tick until
            # it works; it gets the same 3-day cadence as a real finding.
            await storage.mark_form_audit_checked(user_ctx, site_id)
            if err is not None:
                continue
            if result.all_complete or result.total_forms_found == 0:
                continue

            name = site.get("title") or site.get("url") or site_id
            await user_ctx.deliver_chat_message(
                f"Heads up -- {name} has {len(result.incomplete_forms)} Bricks form(s) "
                f"that aren't fully configured yet (missing name, action, save-to-database, "
                f"success or error message). Run audit_bricks_forms for the details and I can "
                f"walk through fixing each one. I'll check back again in 3 days if it's still open.",
                msg_type="system",
            )
