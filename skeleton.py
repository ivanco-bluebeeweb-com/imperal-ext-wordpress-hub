from app import ext
import storage


@ext.skeleton("sites_overview", description="Connected WordPress sites: count and stable IDs.")
async def sites_overview(ctx):
    """Ambient context and a stable snapshot for site-change alerts."""
    rows = await storage.list_site_records(ctx)
    sites = [
        {"id": row["id"], "title": row.get("name", row["id"])}
        for row in rows
        if row.get("id")
    ]
    return {"response": {"sites_connected": len(sites), "sites": sites}}


@ext.tool(
    "skeleton_alert_sites_overview",
    description="Report when a WordPress site is connected or disconnected.",
)
async def skeleton_alert_sites_overview(ctx, old: dict | None = None,
                                        new: dict | None = None) -> dict:
    """Turn a sites_overview snapshot change into a concise notification."""
    if not old or not new:
        return {"response": ""}

    old_sites = {site["id"]: site.get("title", site["id"])
                 for site in old.get("sites", []) if site.get("id")}
    new_sites = {site["id"]: site.get("title", site["id"])
                 for site in new.get("sites", []) if site.get("id")}
    added = [new_sites[site_id] for site_id in sorted(new_sites.keys() - old_sites.keys())]
    removed = [old_sites[site_id] for site_id in sorted(old_sites.keys() - new_sites.keys())]
    if not added and not removed:
        return {"response": ""}

    parts = []
    if added:
        parts.append("Connected: " + ", ".join(added))
    if removed:
        parts.append("Disconnected: " + ", ".join(removed))
    return {"response": "; ".join(parts)}
