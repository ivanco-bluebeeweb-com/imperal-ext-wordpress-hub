"""Tests for the universal WordPress builder-ability dispatcher
(describe_builder_ability / call_builder_ability / call_builder_ability_risky).

Regression coverage for the WP_FORBIDDEN diagnosis fix: a 401/403 from
wp-abilities/v1/.../run is very often caused by an ability call that omitted
an explicit target id (postId/slug/path) rather than by a real credential or
role problem -- WordPress's own permission check for post/page-scoped
abilities resolves the target first and fails closed if it can't. The error
message must say so, so callers fix the actual cause (add postId) instead of
reconnecting with a different Application Password for nothing.
"""

from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_builder_abilities as hba
import storage
from models import CallBuilderAbilityParams, DescribeBuilderAbilityParams


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body


def _ability_meta(**over):
    meta = {
        "name": "bricks/add-element",
        "label": "Add element",
        "input_schema": {
            "type": "object",
            "properties": {
                "element": {"type": "object"},
                "parentId": {"type": "string"},
                "postId": {"type": "integer"},
            },
            "required": ["element"],
        },
        "output_schema": {"type": "object"},
        "meta": {"annotations": {"destructive": False, "readonly": False}},
    }
    meta.update(over)
    return meta


async def test_call_builder_ability_forbidden_mentions_missing_target(monkeypatch):
    """A 403 with no explicit postId in the call must be diagnosed as a likely
    missing-target problem, not just 'reconnect as administrator'."""
    ctx = await _ctx()

    async def fake_wp_get(*a, **kw):
        return _Resp(200, _ability_meta())

    async def fake_wp_request(*a, **kw):
        return _Resp(403, {"code": "rest_forbidden", "message": "Sorry, you are not allowed to do that."})

    monkeypatch.setattr(hba, "wp_get", fake_wp_get)
    monkeypatch.setattr(hba, "wp_request", fake_wp_request)

    params = CallBuilderAbilityParams(
        site_id="x-com",
        ability_name="bricks/add-element",
        input={"element": {"name": "block"}, "parentId": "zbmeky"},  # no postId
    )
    result = await hba.call_builder_ability(ctx, params)

    assert result.status == "error"
    assert result.error_code == "WP_FORBIDDEN"
    assert "postId" in result.error
    assert "target" in result.error.lower()


async def test_call_builder_ability_succeeds_with_explicit_post_id(monkeypatch):
    """Same ability, same site -- succeeds once postId is explicit (the fix's
    recommended remedy actually works end to end)."""
    ctx = await _ctx()

    async def fake_wp_get(*a, **kw):
        return _Resp(200, _ability_meta())

    async def fake_wp_request(*a, **kw):
        return _Resp(200, {"output": {"elementIds": ["4zka4z"], "revisionId": 2380}})

    monkeypatch.setattr(hba, "wp_get", fake_wp_get)
    monkeypatch.setattr(hba, "wp_request", fake_wp_request)

    params = CallBuilderAbilityParams(
        site_id="x-com",
        ability_name="bricks/add-element",
        input={"element": {"name": "block"}, "parentId": "0", "postId": 2282},
    )
    result = await hba.call_builder_ability(ctx, params)

    assert result.status == "success"
    assert result.data.output["elementIds"] == ["4zka4z"]


async def test_describe_builder_ability_schema_readback(monkeypatch):
    """describe_builder_ability surfaces the real input_schema so postId is
    visible before the first call_builder_ability attempt."""
    ctx = await _ctx()

    async def fake_wp_get(*a, **kw):
        return _Resp(200, _ability_meta())

    monkeypatch.setattr(hba, "wp_get", fake_wp_get)

    params = DescribeBuilderAbilityParams(site_id="x-com", ability_name="bricks/add-element")
    result = await hba.describe_builder_ability(ctx, params)

    assert result.status == "success"
    assert "postId" in result.data.input_schema["properties"]


async def test_call_builder_ability_not_found(monkeypatch):
    ctx = await _ctx()

    async def fake_wp_get(*a, **kw):
        return _Resp(404, {})

    monkeypatch.setattr(hba, "wp_get", fake_wp_get)

    params = CallBuilderAbilityParams(
        site_id="x-com", ability_name="bricks/does-not-exist", input={})
    result = await hba.call_builder_ability(ctx, params)

    assert result.status == "error"
    assert result.error_code == "WP_ABILITY_NOT_FOUND"
