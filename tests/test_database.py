"""Contract tests for SSH/WP-CLI database tools: handlers_database.py."""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_database as hdb
import storage
from models import (
    ApplySearchReplaceParams,
    CheckDatabaseParams,
    CountPostTypeRowsParams,
    ExportDatabaseDumpParams,
    SearchReplaceParams,
    SiteIdParams,
)


async def _ssh_ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


# ─────────── list_database_tables ───────────

async def test_list_database_tables_requires_ssh():
    ctx = MockContext()
    await storage.save_site_record(ctx, {"id": "x-com", "name": "X", "status": "connected"})
    result = await hdb.list_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_list_database_tables_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_list_database_tables(cred):
        return [{"Name": "wp_options", "Size": "1.2 MB"}], None

    monkeypatch.setattr(hdb.wp_cli, "list_database_tables", fake_list_database_tables)
    result = await hdb.list_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].name == "wp_options"
    assert result.data[0].size == "1.2 MB"


# ─────────── run_db_search_replace (preview) ───────────

async def test_run_db_search_replace_is_always_dry_run(monkeypatch):
    ctx = await _ssh_ctx()
    seen = {}

    async def fake_run_db_search_replace(cred, old, new, *, dry_run, tables=None):
        seen["dry_run"] = dry_run
        return {"replacements": 42, "dry_run": dry_run}, None

    monkeypatch.setattr(hdb.wp_cli, "run_db_search_replace", fake_run_db_search_replace)
    result = await hdb.run_db_search_replace(
        ctx, SearchReplaceParams(site_id="x-com", old="http://staging.test", new="https://prod.test"))
    assert result.status == "success"
    assert seen["dry_run"] is True
    assert result.data.replacements == 42
    assert result.data.dry_run is True


# ─────────── apply_db_search_replace (stale-preview guard) ───────────

async def test_apply_db_search_replace_refuses_stale_preview(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_run_db_search_replace(cred, old, new, *, dry_run, tables=None):
        # Fresh recheck now finds a DIFFERENT count than what the caller confirmed.
        return {"replacements": 7, "dry_run": dry_run}, None

    monkeypatch.setattr(hdb.wp_cli, "run_db_search_replace", fake_run_db_search_replace)
    result = await hdb.apply_db_search_replace(
        ctx, ApplySearchReplaceParams(
            site_id="x-com", old="http://staging.test", new="https://prod.test",
            expected_replacements=42))
    assert result.status == "error"
    assert result.error_code == "SEARCH_REPLACE_STALE_PREVIEW"


async def test_apply_db_search_replace_runs_when_count_matches(monkeypatch):
    ctx = await _ssh_ctx()
    calls = []

    async def fake_run_db_search_replace(cred, old, new, *, dry_run, tables=None):
        calls.append(dry_run)
        return {"replacements": 42, "dry_run": dry_run}, None

    monkeypatch.setattr(hdb.wp_cli, "run_db_search_replace", fake_run_db_search_replace)
    result = await hdb.apply_db_search_replace(
        ctx, ApplySearchReplaceParams(
            site_id="x-com", old="http://staging.test", new="https://prod.test",
            expected_replacements=42))
    assert result.status == "success"
    assert result.data.replacements == 42
    assert result.data.dry_run is False
    # First call re-verifies (dry_run=True), second call actually writes (dry_run=False).
    assert calls == [True, False]


# ─────────── optimize / check / repair ───────────

async def test_optimize_database_tables_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_optimize(cred):
        return "Success: Optimized every table.", None

    monkeypatch.setattr(hdb.wp_cli, "optimize_database_tables", fake_optimize)
    result = await hdb.optimize_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


async def test_check_database_repair_defaults_to_check_only(monkeypatch):
    ctx = await _ssh_ctx()
    called = {}

    async def fake_check(cred):
        called["check"] = True
        return "Success: Database checked.", None

    async def fake_repair(cred):
        called["repair"] = True
        return "Success: Database repaired.", None

    monkeypatch.setattr(hdb.wp_cli, "check_database", fake_check)
    monkeypatch.setattr(hdb.wp_cli, "repair_database", fake_repair)
    result = await hdb.check_database_repair(ctx, CheckDatabaseParams(site_id="x-com"))
    assert result.status == "success"
    assert called == {"check": True}


async def test_check_database_repair_runs_repair_when_requested(monkeypatch):
    ctx = await _ssh_ctx()
    called = {}

    async def fake_check(cred):
        called["check"] = True
        return "Success: Database checked.", None

    async def fake_repair(cred):
        called["repair"] = True
        return "Success: Database repaired.", None

    monkeypatch.setattr(hdb.wp_cli, "check_database", fake_check)
    monkeypatch.setattr(hdb.wp_cli, "repair_database", fake_repair)
    result = await hdb.check_database_repair(ctx, CheckDatabaseParams(site_id="x-com", repair=True))
    assert result.status == "success"
    assert called == {"repair": True}


# ─────────── export_database_dump ───────────

async def test_export_database_dump_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_export(cred, *, tables=None):
        return {"sql": "-- dump --", "size_bytes": 10}, None

    monkeypatch.setattr(hdb.wp_cli, "export_database_dump", fake_export)
    result = await hdb.export_database_dump(ctx, ExportDatabaseDumpParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.sql == "-- dump --"
    assert result.data.size_bytes == 10


async def test_export_database_dump_surfaces_size_cap_error(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_export(cred, *, tables=None):
        return None, "Dump is larger than 2MB of SQL text — pass specific `tables` to scope the export down."

    monkeypatch.setattr(hdb.wp_cli, "export_database_dump", fake_export)
    result = await hdb.export_database_dump(ctx, ExportDatabaseDumpParams(site_id="x-com"))
    assert result.status == "error"


# ─────────── count_post_type_rows / count_orphaned_postmeta ───────────

async def test_count_post_type_rows_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_count(cred, post_type):
        assert post_type == "product"
        return 123, None

    monkeypatch.setattr(hdb.wp_cli, "count_post_type_rows", fake_count)
    result = await hdb.count_post_type_rows(
        ctx, CountPostTypeRowsParams(site_id="x-com", post_type="product"))
    assert result.status == "success"
    assert result.data.count == 123
    assert result.data.post_type == "product"


async def test_count_orphaned_postmeta_runs_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()

    async def fake_count(cred):
        return 5, None

    monkeypatch.setattr(hdb.wp_cli, "count_orphaned_postmeta", fake_count)
    result = await hdb.count_orphaned_postmeta(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.orphaned_rows == 5


# ─────────── wp_cli-level shell-injection guards ───────────

async def test_wp_cli_search_replace_rejects_quotes_and_backticks():
    cred = {"host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key"}
    result, error = await hdb.wp_cli.run_db_search_replace(cred, "foo'; DROP TABLE wp_users; --", "bar", dry_run=True)
    assert result is None
    assert error is not None

    result, error = await hdb.wp_cli.run_db_search_replace(cred, "foo", "bar`whoami`", dry_run=True)
    assert result is None
    assert error is not None


async def test_wp_cli_search_replace_rejects_unsafe_table_names():
    cred = {"host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key"}
    result, error = await hdb.wp_cli.run_db_search_replace(
        cred, "foo", "bar", dry_run=True, tables=["wp_options; rm -rf /"])
    assert result is None
    assert error is not None


async def test_wp_cli_count_post_type_rows_rejects_unsafe_post_type():
    cred = {"host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key"}
    result, error = await hdb.wp_cli.count_post_type_rows(cred, "post; rm -rf /")
    assert result is None
    assert error is not None

