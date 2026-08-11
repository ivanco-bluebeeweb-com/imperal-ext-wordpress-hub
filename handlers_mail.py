"""Mail deliverability checks (Group Q), through Imperal Bridge only.

`wp_mail()` returning true only confirms WordPress accepted the message for
sending; it does not prove inbox delivery. The test tool keeps that boundary
explicit. Configuration discovery never returns SMTP credentials and only
identifies WP Mail SMTP when its plugin file is active; any other mail setup
remains honestly undetermined.
"""
from imperal_sdk import ActionResult

from app import chat
from models import MailConfiguration, SendTestEmailParams, SiteIdParams, TestEmailResult
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_post

MAIL_TEST_PATH = "/wp-json/imperal/v1/mail/test"
MAIL_CONFIGURATION_PATH = "/wp-json/imperal/v1/mail/configuration"


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


def _bridge_failure(status_code, body):
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    message = str(body.get("message", "")) if isinstance(body, dict) else ""
    if code == "rest_no_route":
        return ActionResult.error(
            "This site needs Imperal Bridge 2.15.0 or newer for mail diagnostics.",
            retryable=False, code="MAIL_BRIDGE_MISSING")
    if code == "imperal_mail_invalid_recipient":
        return ActionResult.error(message or "Provide a valid recipient email address.",
                                  retryable=False, code="MAIL_INVALID_RECIPIENT")
    if code == "imperal_mail_not_accepted":
        return ActionResult.error(
            message or "WordPress did not accept the test message for sending.",
            retryable=True, code="MAIL_NOT_ACCEPTED")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user needs administrator permission for mail diagnostics.",
            retryable=False, code="MAIL_FORBIDDEN")
    return ActionResult.error(wp_error_message(status_code), retryable=status_code >= 500,
                              code=wp_error_code(status_code))


@chat.function(
    "send_test_email",
    description=(
        "Ask WordPress to send one fixed test message to an email address through its own wp_mail() "
        "path. Requires Imperal Bridge 2.15.0+ and an administrator Application Password. A success "
        "means WordPress accepted the message for sending — check the inbox/spam folder to confirm "
        "actual delivery."
    ),
    action_type="write", data_model=TestEmailResult,
    effects=["wp.mail_test"], event="wordpress-hub.send_test_email",
)
async def send_test_email(ctx, params: SendTestEmailParams) -> ActionResult:
    """Send a fixed, non-secret test message through Imperal Bridge's wp_mail wrapper."""
    auth, error = await _auth(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth
    try:
        response = await wp_post(ctx, base_url, MAIL_TEST_PATH, username=username,
                                 app_password=password, json={"to": params.to.strip()})
    except Exception as exc:
        await ctx.log(f"send_test_email request failed: {exc}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True,
                                  code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return _bridge_failure(response.status_code, response.body)
    body = response.body if isinstance(response.body, dict) else {}
    recipient = str(body.get("recipient", params.to.strip()))
    return ActionResult.success(
        TestEmailResult(id=f"{params.site_id}:mail-test", title="Test email accepted",
                        kind="wp_mail_test", site_id=params.site_id, recipient=recipient,
                        accepted=bool(body.get("accepted", False))),
        summary=("WordPress accepted the test message for sending. Check the recipient inbox "
                 "(and spam folder) to confirm actual delivery."),
    )


@chat.function(
    "get_mail_configuration",
    description=(
        "Identify the WordPress mail mechanism without exposing credentials: reports active WP "
        "Mail SMTP when its plugin is detected, otherwise reports native/undetermined wp_mail() "
        "handling. Requires Imperal Bridge 2.15.0+ and an administrator Application Password."
    ),
    action_type="read", data_model=MailConfiguration,
)
async def get_mail_configuration(ctx, params: SiteIdParams) -> ActionResult:
    """Read non-secret mail configuration facts from Imperal Bridge."""
    auth, error = await _auth(ctx, params.site_id)
    if error:
        return error
    base_url, username, password = auth
    try:
        response = await wp_get(ctx, base_url, MAIL_CONFIGURATION_PATH, username=username,
                                app_password=password)
    except Exception as exc:
        await ctx.log(f"get_mail_configuration request failed: {exc}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True,
                                  code="WP_UNREACHABLE")
    if not 200 <= response.status_code < 300:
        return _bridge_failure(response.status_code, response.body)
    body = response.body if isinstance(response.body, dict) else {}
    mechanism = str(body.get("mechanism", "native_or_undetermined"))
    return ActionResult.success(
        MailConfiguration(
            id=f"{params.site_id}:mail", title="Mail configuration", kind="wp_mail_configuration",
            site_id=params.site_id, mechanism=mechanism,
            provider=str(body.get("provider", "")), detected_plugin=str(body.get("detected_plugin", "")),
            notes=str(body.get("notes", "")),
        ),
        summary=f"Mail mechanism: {mechanism}.",
    )
