from imperal_sdk.testing import MockContext
import app  # noqa: F401
import skeleton
import storage


async def test_skeleton_counts_connected_sites():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    out = await skeleton.sites_overview(ctx)
    assert out["response"]["sites_connected"] == 1


async def test_skeleton_zero_sites():
    ctx = MockContext()
    out = await skeleton.sites_overview(ctx)
    assert out["response"]["sites_connected"] == 0
    assert out["response"]["sites"] == []


async def test_skeleton_keeps_stable_site_ids_for_alert_diff():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "Example", "status": "connected"})
    out = await skeleton.sites_overview(ctx)
    assert out["response"]["sites"] == [{"id": "x-com", "title": "Example"}]


async def test_sites_alert_names_connected_and_disconnected_sites():
    result = await skeleton.skeleton_alert_sites_overview(
        MockContext(),
        old={"sites": [{"id": "old-com", "title": "Old Site"}]},
        new={"sites": [{"id": "new-com", "title": "New Site"}]},
    )
    assert result["response"] == "Connected: New Site; Disconnected: Old Site"


async def test_sites_alert_stays_silent_without_a_real_change():
    snapshot = {"sites": [{"id": "x-com", "title": "Example"}]}
    result = await skeleton.skeleton_alert_sites_overview(MockContext(), old=snapshot, new=snapshot)
    assert result["response"] == ""
