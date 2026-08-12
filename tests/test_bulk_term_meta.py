from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_meta as hm
import storage
from models import ApplyBulkTermMetaParams, BulkTermMetaParams

BASE = "https://blog.test"
PATH = "/wp-json/imperal/v1/termmeta"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "site", "name": "Site", "url": BASE, "username": "admin", "status": "connected"})
    await storage.set_credential(ctx, "site", "pw")
    return ctx


async def test_preview_and_apply_bulk_term_meta():
    ctx = await _ctx()
    ctx.http.mock_get(BASE + PATH + "/1", {"term_id": 1, "meta": {"flag": "old"}})
    ctx.http.mock_get(BASE + PATH + "/2", {"term_id": 2, "meta": {"flag": "old"}})
    preview = await hm.preview_bulk_term_meta(ctx, BulkTermMetaParams(site_id="site", term_ids=[1, 2], meta={"flag": "new"}))
    assert preview.status == "success"
    assert preview.data.preview is True

    ctx.http.mock_get(BASE + PATH + "/1", {"term_id": 1, "meta": {"flag": "old"}})
    ctx.http.mock_get(BASE + PATH + "/2", {"term_id": 2, "meta": {"flag": "old"}})
    ctx.http.mock_post(BASE + PATH + "/1", {"updated": ["flag"]})
    ctx.http.mock_post(BASE + PATH + "/2", {"updated": ["flag"]})
    result = await hm.apply_bulk_term_meta(ctx, ApplyBulkTermMetaParams(site_id="site", term_ids=[1, 2], meta={"flag": "new"}, expected_state_token=preview.data.state_token))
    assert result.status == "success"
    assert result.data.updated_ids == [1, 2]


async def test_apply_bulk_term_meta_refuses_stale_token():
    ctx = await _ctx()
    ctx.http.mock_get(BASE + PATH + "/1", {"term_id": 1, "meta": {"flag": "old"}})
    result = await hm.apply_bulk_term_meta(ctx, ApplyBulkTermMetaParams(site_id="site", term_ids=[1], meta={"flag": "new"}, expected_state_token="0" * 64))
    assert result.status == "error"
    assert result.error_code == "TERM_META_BULK_STATE_CHANGED"
