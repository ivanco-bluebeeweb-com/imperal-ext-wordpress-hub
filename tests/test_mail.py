"""Contract tests for Group Q mail deliverability Bridge handlers."""
from imperal_sdk.testing import MockContext

import handlers_mail as hm
import storage
from models import SendTestEmailParams, SiteIdParams

BASE = "https://x.com"
TEST = f"{BASE}/wp-json/imperal/v1/mail/test"
CONFIG = f"{BASE}/wp-json/imperal/v1/mail/configuration"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": BASE,
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_send_test_email_requires_connected_site():
    result = await hm.send_test_email(MockContext(), SendTestEmailParams(site_id="none", to="a@x.com"))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_send_test_email_reports_acceptance_not_delivery():
    ctx = await _ctx()
    ctx.http.mock_post(TEST, {"recipient": "deliver@example.com", "accepted": True}, 200)
    result = await hm.send_test_email(ctx, SendTestEmailParams(site_id="x-com", to="deliver@example.com"))
    assert result.status == "success"
    assert result.data.accepted is True
    assert "inbox" in result.summary.lower()


async def test_send_test_email_reports_old_bridge():
    ctx = await _ctx()
    ctx.http.mock_post(TEST, {"code": "rest_no_route", "message": "No route"}, 404)
    result = await hm.send_test_email(ctx, SendTestEmailParams(site_id="x-com", to="a@x.com"))
    assert result.status == "error"
    assert result.error_code == "MAIL_BRIDGE_MISSING"


async def test_mail_configuration_reports_known_plugin_without_secrets():
    ctx = await _ctx()
    ctx.http.mock_get(CONFIG, {
        "mechanism": "plugin_managed", "provider": "smtpcom",
        "detected_plugin": "WP Mail SMTP", "notes": "Credentials hidden.",
    }, 200)
    result = await hm.get_mail_configuration(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.detected_plugin == "WP Mail SMTP"
    assert result.data.provider == "smtpcom"


async def test_mail_configuration_handles_native_or_undetermined():
    ctx = await _ctx()
    ctx.http.mock_get(CONFIG, {
        "mechanism": "native_or_undetermined", "provider": "",
        "detected_plugin": "", "notes": "No supported mail plugin.",
    }, 200)
    result = await hm.get_mail_configuration(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.mechanism == "native_or_undetermined"
