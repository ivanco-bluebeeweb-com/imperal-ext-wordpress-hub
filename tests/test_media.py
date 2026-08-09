"""Tests for upload_media / check_media_support — the Imperal Bridge media tier.

The bridge asks WordPress to fetch its own copy of a public image
(media_sideload_image) rather than Imperal fetching bytes itself, so these
tests exercise the sideload request/response shape and error mapping, not
any actual image transfer.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_media as hm
import storage
from models import SiteIdParams, UploadMediaParams

SIDELOAD = "https://x.com/wp-json/imperal/v1/media/sideload"
STATUS = "https://x.com/wp-json/imperal/v1/media/status"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def test_upload_media_happy_path():
    ctx = await _ctx()
    ctx.http.mock_post(SIDELOAD, {
        "attachment_id": 77, "url": "https://x.com/wp-content/uploads/pic.jpg",
        "width": 1200, "height": 800, "attached_to": None, "featured_set": False,
    }, 201)
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/pic.jpg", alt_text="A picture",
    ))
    assert result.status == "success"
    assert result.data.id == "77"
    assert result.data.url == "https://x.com/wp-content/uploads/pic.jpg"
    assert result.data.width == 1200
    assert "Uploaded media #77" in result.summary


async def test_upload_media_forwards_seo_aeo_filename_to_the_bridge():
    """A caller-supplied filename (e.g. Media Hub's own SEO/AEO-optimized
    slug) must reach the bridge request body -- that's what lets the actual
    on-site file name be meaningful instead of the provider's raw URL name."""
    ctx = await _ctx()
    captured = {}

    async def handler(url, *, json=None, **kwargs):
        captured.update(json or {})
        return type("R", (), {"status_code": 201, "body": {
            "attachment_id": 77, "url": "https://x.com/wp-content/uploads/pic.jpg",
            "width": 1200, "height": 800, "attached_to": None, "featured_set": False,
        }})()

    ctx.http.post = handler
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/result_abc123.jpg",
        filename="heat-recovery-ventilator-featured",
    ))
    assert result.status == "success"
    assert captured.get("filename") == "heat-recovery-ventilator-featured"


async def test_upload_media_without_filename_omits_it_from_the_request():
    ctx = await _ctx()
    captured = {}

    async def handler(url, *, json=None, **kwargs):
        captured.update(json or {})
        return type("R", (), {"status_code": 201, "body": {
            "attachment_id": 77, "url": "https://x.com/wp-content/uploads/pic.jpg",
            "width": 1200, "height": 800, "attached_to": None, "featured_set": False,
        }})()

    ctx.http.post = handler
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/pic.jpg",
    ))
    assert result.status == "success"
    assert "filename" not in captured


async def test_upload_media_with_featured_reports_attach_and_featured():
    ctx = await _ctx()
    ctx.http.mock_post(SIDELOAD, {
        "attachment_id": 88, "url": "https://x.com/x.jpg",
        "width": 800, "height": 600, "attached_to": 5, "featured_set": True,
    }, 201)
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/pic.jpg",
        post_id=5, set_featured=True,
    ))
    assert result.status == "success"
    assert result.data.attached_to == 5
    assert result.data.featured_set is True
    assert "attached to post #5" in result.summary
    assert "set as featured image" in result.summary


async def test_upload_media_set_featured_without_post_id_rejected_locally():
    ctx = await _ctx()
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/pic.jpg", set_featured=True,
    ))
    assert result.status == "error"
    assert result.error_code == "MEDIA_TARGET_MISSING"


async def test_upload_media_insecure_url_mapped_from_bridge_error():
    ctx = await _ctx()
    ctx.http.mock_post(SIDELOAD, {
        "code": "imperal_media_insecure_url", "message": "source_url must use https://.",
    }, 400)
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="http://cdn.example.com/pic.jpg",
    ))
    assert result.status == "error"
    assert result.error_code == "MEDIA_INSECURE_URL"


async def test_upload_media_private_host_mapped_from_bridge_error():
    ctx = await _ctx()
    ctx.http.mock_post(SIDELOAD, {
        "code": "imperal_media_private_host", "message": "private host",
    }, 400)
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://127.0.0.1/pic.jpg",
    ))
    assert result.status == "error"
    assert result.error_code == "MEDIA_PRIVATE_HOST"


async def test_upload_media_sideload_failure_mapped_502():
    ctx = await _ctx()
    ctx.http.mock_post(SIDELOAD, {
        "code": "imperal_media_sideload_failed", "message": "fetch failed",
    }, 502)
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/dead.jpg",
    ))
    assert result.status == "error"
    assert result.error_code == "MEDIA_SIDELOAD_FAILED"


async def test_upload_media_missing_bridge_404():
    ctx = await _ctx()
    ctx.http.mock_post(SIDELOAD, {}, 404)
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="x-com", source_url="https://cdn.example.com/pic.jpg",
    ))
    assert result.status == "error"


async def test_upload_media_unknown_site():
    ctx = MockContext()
    result = await hm.upload_media(ctx, UploadMediaParams(
        site_id="ghost", source_url="https://cdn.example.com/pic.jpg",
    ))
    assert result.status == "error"
    assert result.error_code == "SITE_NOT_CONNECTED"


async def test_check_media_support_reports_bridge_version_and_capability():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {
        "bridge": True, "bridge_version": "1.0.0", "can_upload": True,
    }, 200)
    result = await hm.check_media_support(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.bridge_version == "1.0.0"
    assert result.data.can_upload is True
    assert "can upload media" in result.summary


async def test_check_media_support_missing_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(STATUS, {}, 404)
    result = await hm.check_media_support(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "MEDIA_BRIDGE_MISSING"
