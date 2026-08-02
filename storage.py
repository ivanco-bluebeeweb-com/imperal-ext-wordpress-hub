import json

SITES_COLLECTION = "sites"
CREDS_COLLECTION = "creds"
CSV_IMPORTS_COLLECTION = "csv_imports"


# ── CSV import audit trail ───────────────────────────────────────────────────

async def save_csv_import_record(ctx, record):
    """Persist metadata and failed rows only; never store the full CSV text."""
    existing = await _find_doc(ctx, CSV_IMPORTS_COLLECTION, record["id"])
    if existing:
        await ctx.store.update(CSV_IMPORTS_COLLECTION, existing.id, record)
    else:
        await ctx.store.create(CSV_IMPORTS_COLLECTION, record)


async def get_csv_import_record(ctx, import_id):
    doc = await _find_doc(ctx, CSV_IMPORTS_COLLECTION, import_id)
    return doc.data if doc else None


async def list_csv_import_records(ctx, site_id, limit=20):
    page = await ctx.store.query(CSV_IMPORTS_COLLECTION, limit=100)
    records = [doc.data for doc in page.data if doc.data.get("site_id") == site_id]
    return sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)[:limit]


# ── Site records ──────────────────────────────────────────────────────────────



# ── Site records ──────────────────────────────────────────────────────────────

async def _find_doc(ctx, collection, site_id):
    page = await ctx.store.query(collection, limit=100)
    for doc in page.data:
        if doc.data.get("site_id") == site_id or doc.data.get("id") == site_id:
            return doc
    return None


async def list_site_records(ctx):
    page = await ctx.store.query(SITES_COLLECTION, limit=100)
    return [doc.data for doc in page.data]


async def get_site_record(ctx, site_id):
    doc = await _find_doc(ctx, SITES_COLLECTION, site_id)
    return doc.data if doc else None


async def save_site_record(ctx, record):
    doc = await _find_doc(ctx, SITES_COLLECTION, record["id"])
    if doc:
        await ctx.store.update(SITES_COLLECTION, doc.id, record)
    else:
        await ctx.store.create(SITES_COLLECTION, record)


async def delete_site_record(ctx, site_id):
    doc = await _find_doc(ctx, SITES_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(SITES_COLLECTION, doc.id)


# ── Credentials (stored in ctx.store — vault provisioning not required) ───────

async def get_credential(ctx, site_id):
    doc = await _find_doc(ctx, CREDS_COLLECTION, site_id)
    return doc.data.get("password") if doc else None


async def set_credential(ctx, site_id, app_password):
    doc = await _find_doc(ctx, CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.update(CREDS_COLLECTION, doc.id,
                               {"site_id": site_id, "password": app_password})
    else:
        await ctx.store.create(CREDS_COLLECTION,
                               {"site_id": site_id, "password": app_password})


async def delete_credential(ctx, site_id):
    doc = await _find_doc(ctx, CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(CREDS_COLLECTION, doc.id)


# ── Content cache (posts/pages/media fetched once, tabs switch from cache) ────

CACHE_COLLECTION = "wp_cache"
SSH_CREDS_COLLECTION = "ssh_creds"


async def get_content_cache(ctx, site_id):
    doc = await _find_doc(ctx, CACHE_COLLECTION, site_id)
    return doc.data if doc else None


async def set_content_cache(ctx, site_id, posts=None, pages=None, media=None,
                            comments=None, scheduled=None, users=None, orders=None,
                            dynamic=None):
    data = {
        "site_id":   site_id,
        "posts":     posts or [],
        "pages":     pages or [],
        "media":     media or [],
        "comments":  comments or [],
        "scheduled": scheduled or [],
        "users":     users or [],
        "orders":    orders,   # None = WC not installed; [] = installed but no orders
        "dynamic":   dynamic or {},  # CPTs, taxonomies, metadata
    }
    doc = await _find_doc(ctx, CACHE_COLLECTION, site_id)
    if doc:
        await ctx.store.update(CACHE_COLLECTION, doc.id, data)
    else:
        await ctx.store.create(CACHE_COLLECTION, data)


PENDING_SSH_COLLECTION = "pending_ssh"


async def set_pending_ssh_site(ctx, site_id):
    page = await ctx.store.query(PENDING_SSH_COLLECTION, limit=1)
    if page.data:
        await ctx.store.update(PENDING_SSH_COLLECTION, page.data[0].id, {"site_id": site_id})
    else:
        await ctx.store.create(PENDING_SSH_COLLECTION, {"site_id": site_id})


async def get_pending_ssh_site(ctx) -> str:
    page = await ctx.store.query(PENDING_SSH_COLLECTION, limit=1)
    return page.data[0].data.get("site_id", "") if page.data else ""


async def get_ssh_cred(ctx, site_id):
    doc = await _find_doc(ctx, SSH_CREDS_COLLECTION, site_id)
    return doc.data if doc else None


async def set_ssh_cred(ctx, site_id, cred: dict):
    data = {"site_id": site_id, **cred}
    doc = await _find_doc(ctx, SSH_CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.update(SSH_CREDS_COLLECTION, doc.id, data)
    else:
        await ctx.store.create(SSH_CREDS_COLLECTION, data)


async def delete_ssh_cred(ctx, site_id):
    doc = await _find_doc(ctx, SSH_CREDS_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(SSH_CREDS_COLLECTION, doc.id)


async def has_ssh(ctx, site_id) -> bool:
    return await get_ssh_cred(ctx, site_id) is not None


async def clear_content_cache(ctx, site_id):
    doc = await _find_doc(ctx, CACHE_COLLECTION, site_id)
    if doc:
        await ctx.store.delete(CACHE_COLLECTION, doc.id)
