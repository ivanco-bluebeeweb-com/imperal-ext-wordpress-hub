"""WordPress core Site Health REST diagnostics (Group R).

This is intentionally separate from the app's reachability-oriented
``get_site_health``. It uses only WordPress core's five documented fixed
``/wp-site-health/v1/tests/*`` routes and its ``directory-sizes`` route;
there is no caller-supplied endpoint or arbitrary REST proxy.
"""
import asyncio

from imperal_sdk import ActionResult

from app import chat
from models import CoreSiteHealthReport, SiteHealthDirectorySizes, SiteHealthTest, SiteIdParams
import storage
from wp_client import wp_get

_HEALTH_BASE = "/wp-json/wp-site-health/v1"
_TESTS = (
    "background-updates",
    "loopback-requests",
    "https-status",
    "dotorg-communication",
    "authorization-header",
)


async def _auth(ctx, site_id: str):
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


def _unavailable(test: str, status_code: int) -> str:
    if status_code == 404:
        return f"{test} (not available on this WordPress version)"
    if status_code in (401, 403):
        return f"{test} (administrator permission required)"
    return f"{test} (WordPress returned HTTP {status_code})"


@chat.function(
    "run_core_site_health_tests",
    description=(
        "Run WordPress core's own fixed Site Health REST checks: background updates, loopback "
        "requests, HTTPS status, WordPress.org communication, and Authorization-header handling. "
        "This is read-only and distinct from get_site_health's connectivity/count check; requires "
        "an administrator Application Password."
    ),
    action_type="read", data_model=CoreSiteHealthReport,
)
async def run_core_site_health_tests(ctx, params: SiteIdParams) -> ActionResult:
    """Collect the fixed, documented Site Health tests without failing as a whole for one gap."""
    auth, error = await _auth(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth

    async def call(test: str):
        try:
            response = await wp_get(ctx, base_url, f"{_HEALTH_BASE}/tests/{test}",
                                    username=username, app_password=password)
            return test, response, None
        except Exception as exc:
            return test, None, exc

    responses = await asyncio.gather(*(call(test) for test in _TESTS))
    tests, unavailable = [], []
    for expected_name, response, exc in responses:
        if exc or response is None:
            unavailable.append(f"{expected_name} (site unreachable)")
            continue
        if not 200 <= response.status_code < 300 or not isinstance(response.body, dict):
            unavailable.append(_unavailable(expected_name, response.status_code))
            continue
        body = response.body
        badge = body.get("badge", "")
        if isinstance(badge, dict):
            badge = str(badge.get("label", badge.get("color", "")))
        tests.append(SiteHealthTest(
            id=f"{params.site_id}:health:{expected_name}", title=str(body.get("label", expected_name)),
            kind="wp_core_site_health_test", test=str(body.get("test", expected_name)),
            label=str(body.get("label", "")), status=str(body.get("status", "")), badge=str(badge),
            description=str(body.get("description", "")), actions=str(body.get("actions", "")),
        ))
    report = CoreSiteHealthReport(
        id=f"{params.site_id}:core-health", title="WordPress core Site Health", kind="wp_core_site_health",
        site_id=params.site_id, tests=tests, unavailable_tests=unavailable,
    )
    critical = sum(test.status == "critical" for test in tests)
    return ActionResult.success(
        report,
        summary=(f"WordPress core Site Health: {len(tests)} checks returned, {critical} critical"
                 f"{'; ' + str(len(unavailable)) + ' unavailable' if unavailable else ''}."),
    )


@chat.function(
    "get_core_site_health_directory_sizes",
    description=(
        "Read the directory and database size data calculated by WordPress core's Site Health "
        "API. Read-only; requires an administrator Application Password and WordPress 5.6+ for "
        "the documented directory-sizes REST endpoint."
    ),
    action_type="read", data_model=SiteHealthDirectorySizes,
)
async def get_core_site_health_directory_sizes(ctx, params: SiteIdParams) -> ActionResult:
    """Read only the documented core directory-size response, with no filesystem access of our own."""
    auth, error = await _auth(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth
    try:
        response = await wp_get(ctx, base_url, f"{_HEALTH_BASE}/directory-sizes",
                                username=username, app_password=password)
    except Exception as exc:
        await ctx.log(f"get_core_site_health_directory_sizes request failed: {exc}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True,
                                  code="WP_UNREACHABLE")
    if response.status_code == 404:
        return ActionResult.error(
            "This WordPress version does not expose the core Site Health directory-size route.",
            retryable=False, code="SITE_HEALTH_UNAVAILABLE")
    if response.status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user needs administrator permission for core Site Health.",
            retryable=False, code="SITE_HEALTH_FORBIDDEN")
    if not 200 <= response.status_code < 300 or not isinstance(response.body, dict):
        return ActionResult.error("WordPress could not return Site Health directory sizes.",
                                  retryable=response.status_code >= 500,
                                  code="SITE_HEALTH_FAILED")
    result = SiteHealthDirectorySizes(
        id=f"{params.site_id}:directory-sizes", title="WordPress Site Health sizes",
        kind="wp_core_site_health_sizes", site_id=params.site_id, sizes=response.body,
    )
    return ActionResult.success(result, summary="WordPress core Site Health directory sizes loaded.")
