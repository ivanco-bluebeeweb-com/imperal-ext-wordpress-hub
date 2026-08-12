"""Contract tests for database tools: handlers_database.py.

Bridge-first, SSH-fallback -- same shape as tests/test_server_info.py.
Every route here is a plain $wpdb call from inside WordPress (Bridge
SECTION 12, /imperal/v1/database/*), so a site with the Bridge plugin
installed needs zero SSH. SSH + WP-CLI stays the fallback for sites that
don't have the Bridge yet.
"""
from imperal_sdk.testing import MockContext

import app  # noqa: F401
import handlers_database as hdb
import storage
from models import (
    ApplySearchReplaceParams,
    CheckBackupRestorabilityParams,
    CheckDatabaseParams,
    CountPostTypeRowsParams,
    ExportDatabaseDumpParams,
    SearchReplaceParams,
    SiteIdParams,
)

BASE = "https://x.com"
TABLES = f"{BASE}/wp-json/imperal/v1/database/tables"
SEARCH_REPLACE = f"{BASE}/wp-json/imperal/v1/database/search-replace"
OPTIMIZE = f"{BASE}/wp-json/imperal/v1/database/optimize"
CHECK = f"{BASE}/wp-json/imperal/v1/database/check"
EXPORT = f"{BASE}/wp-json/imperal/v1/database/export"
POST_COUNT = f"{BASE}/wp-json/imperal/v1/database/post-count"
ORPHANED_POSTMETA = f"{BASE}/wp-json/imperal/v1/database/orphaned-postmeta"


async def _ctx():
    ctx = MockContext()
    await storage.save_site_record(ctx, {
        "id": "x-com", "name": "X", "url": "https://x.com",
        "username": "admin", "status": "connected",
    })
    await storage.set_credential(ctx, "x-com", "pw")
    return ctx


async def _ssh_ctx():
    """No Bridge response mocked at all (so every probe errors -> falls
    back), with an SSH credential stored."""
    ctx = await _ctx()
    await storage.set_ssh_cred(ctx, "x-com", {
        "host": "ssh.x.com", "port": 22, "user": "deploy", "wp_path": "/var/www/html", "key": "test-key",
    })
    return ctx


# ─────────── list_database_tables ───────────

async def test_list_database_tables_via_bridge_needs_no_ssh():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"tables": [{"name": "wp_options", "size": "1.2MB"}]}, 200)
    result = await hdb.list_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].name == "wp_options"
    assert result.data[0].size == "1.2MB"


async def test_list_database_tables_requires_ssh_when_bridge_missing():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"code": "rest_no_route"}, 404)
    result = await hdb.list_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"


async def test_list_database_tables_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_get(TABLES, {"code": "rest_no_route"}, 404)

    async def fake_list_database_tables(cred):
        return [{"Name": "wp_options", "Size": "1.2 MB"}], None

    monkeypatch.setattr(hdb.wp_cli, "list_database_tables", fake_list_database_tables)
    result = await hdb.list_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data[0].name == "wp_options"
    assert result.data[0].size == "1.2 MB"


# ─────────── run_db_search_replace (preview) ───────────

async def test_run_db_search_replace_via_bridge_is_always_dry_run():
    ctx = await _ctx()
    ctx.http.mock_post(SEARCH_REPLACE, {"replacements": 42, "dry_run": True, "tables": ["wp_options"]}, 200)
    result = await hdb.run_db_search_replace(
        ctx, SearchReplaceParams(site_id="x-com", old="http://staging.test", new="https://prod.test"))
    assert result.status == "success"
    assert result.data.replacements == 42
    assert result.data.dry_run is True


async def test_run_db_search_replace_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_post(SEARCH_REPLACE, {"code": "rest_no_route"}, 404)
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

async def test_apply_db_search_replace_refuses_stale_preview_via_bridge():
    ctx = await _ctx()
    # Fresh recheck now finds a DIFFERENT count than what the caller confirmed.
    ctx.http.mock_post(SEARCH_REPLACE, {"replacements": 7, "dry_run": True, "tables": ["wp_options"]}, 200)
    result = await hdb.apply_db_search_replace(
        ctx, ApplySearchReplaceParams(
            site_id="x-com", old="http://staging.test", new="https://prod.test",
            expected_replacements=42))
    assert result.status == "error"
    assert result.error_code == "SEARCH_REPLACE_STALE_PREVIEW"


async def test_apply_db_search_replace_refuses_stale_preview_via_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_post(SEARCH_REPLACE, {"code": "rest_no_route"}, 404)

    async def fake_run_db_search_replace(cred, old, new, *, dry_run, tables=None):
        return {"replacements": 7, "dry_run": dry_run}, None

    monkeypatch.setattr(hdb.wp_cli, "run_db_search_replace", fake_run_db_search_replace)
    result = await hdb.apply_db_search_replace(
        ctx, ApplySearchReplaceParams(
            site_id="x-com", old="http://staging.test", new="https://prod.test",
            expected_replacements=42))
    assert result.status == "error"
    assert result.error_code == "SEARCH_REPLACE_STALE_PREVIEW"


async def test_apply_db_search_replace_runs_when_count_matches_via_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_post(SEARCH_REPLACE, {"code": "rest_no_route"}, 404)
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

async def test_optimize_database_tables_via_bridge():
    ctx = await _ctx()
    ctx.http.mock_post(OPTIMIZE, {"output": "wp_options: OK"}, 200)
    result = await hdb.optimize_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


async def test_optimize_database_tables_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_post(OPTIMIZE, {"code": "rest_no_route"}, 404)

    async def fake_optimize(cred):
        return "Success: Optimized every table.", None

    monkeypatch.setattr(hdb.wp_cli, "optimize_database_tables", fake_optimize)
    result = await hdb.optimize_database_tables(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"


async def test_check_database_repair_defaults_to_check_only_via_bridge():
    ctx = await _ctx()
    ctx.http.mock_post(CHECK, {"output": "wp_options: OK"}, 200)
    result = await hdb.check_database_repair(ctx, CheckDatabaseParams(site_id="x-com"))
    assert result.status == "success"


async def test_check_database_repair_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_post(CHECK, {"code": "rest_no_route"}, 404)
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


async def test_check_database_repair_runs_repair_when_requested_via_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_post(CHECK, {"code": "rest_no_route"}, 404)
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

async def test_export_database_dump_via_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(EXPORT, {"sql": "-- dump --", "size_bytes": 10}, 200)
    result = await hdb.export_database_dump(ctx, ExportDatabaseDumpParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.sql == "-- dump --"
    assert result.data.size_bytes == 10


async def test_export_database_dump_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_get(EXPORT, {"code": "rest_no_route"}, 404)

    async def fake_export(cred, *, tables=None):
        return {"sql": "-- dump --", "size_bytes": 10}, None

    monkeypatch.setattr(hdb.wp_cli, "export_database_dump", fake_export)
    result = await hdb.export_database_dump(ctx, ExportDatabaseDumpParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.sql == "-- dump --"
    assert result.data.size_bytes == 10


async def test_export_database_dump_surfaces_size_cap_error_over_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_get(EXPORT, {"code": "rest_no_route"}, 404)

    async def fake_export(cred, *, tables=None):
        return None, "Dump is larger than 2MB of SQL text — pass specific `tables` to scope the export down."

    monkeypatch.setattr(hdb.wp_cli, "export_database_dump", fake_export)
    result = await hdb.export_database_dump(ctx, ExportDatabaseDumpParams(site_id="x-com"))
    assert result.status == "error"


# ─────────── count_post_type_rows / count_orphaned_postmeta ───────────

async def test_count_post_type_rows_via_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(POST_COUNT, {"post_type": "product", "count": 123}, 200)
    result = await hdb.count_post_type_rows(
        ctx, CountPostTypeRowsParams(site_id="x-com", post_type="product"))
    assert result.status == "success"
    assert result.data.count == 123
    assert result.data.post_type == "product"


async def test_count_post_type_rows_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_get(POST_COUNT, {"code": "rest_no_route"}, 404)

    async def fake_count(cred, post_type):
        assert post_type == "product"
        return 123, None

    monkeypatch.setattr(hdb.wp_cli, "count_post_type_rows", fake_count)
    result = await hdb.count_post_type_rows(
        ctx, CountPostTypeRowsParams(site_id="x-com", post_type="product"))
    assert result.status == "success"
    assert result.data.count == 123
    assert result.data.post_type == "product"


async def test_count_orphaned_postmeta_via_bridge():
    ctx = await _ctx()
    ctx.http.mock_get(ORPHANED_POSTMETA, {"orphaned_postmeta": 5}, 200)
    result = await hdb.count_orphaned_postmeta(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.orphaned_rows == 5


async def test_count_orphaned_postmeta_falls_back_to_ssh(monkeypatch):
    ctx = await _ssh_ctx()
    ctx.http.mock_get(ORPHANED_POSTMETA, {"code": "rest_no_route"}, 404)

    async def fake_count(cred):
        return 5, None

    monkeypatch.setattr(hdb.wp_cli, "count_orphaned_postmeta", fake_count)
    result = await hdb.count_orphaned_postmeta(ctx, SiteIdParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.orphaned_rows == 5


# ─────────── wp_cli-level shell-injection guards (SSH path only) ───────────

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


# ─────────── check_backup_restorability ───────────

_CORE_DUMP_SQL = (
    "CREATE TABLE `wp_options` (id INT);\n"
    "INSERT INTO `wp_options` VALUES (1);\n"
    "CREATE TABLE `wp_posts` (id INT);\n"
    "INSERT INTO `wp_posts` VALUES (1);\n"
)


async def test_check_backup_restorability_reports_restorable_for_a_sound_dump():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"tables": [
        {"name": "wp_options", "size": "1KB"}, {"name": "wp_posts", "size": "1KB"},
    ]}, 200)
    ctx.http.mock_get(EXPORT, {"sql": _CORE_DUMP_SQL, "size_bytes": len(_CORE_DUMP_SQL)}, 200)
    result = await hdb.check_backup_restorability(ctx, CheckBackupRestorabilityParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.restorable is True
    assert result.data.missing_tables == []
    assert result.data.truncated is False


async def test_check_backup_restorability_flags_missing_core_table():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"tables": [
        {"name": "wp_options", "size": "1KB"}, {"name": "wp_posts", "size": "1KB"},
    ]}, 200)
    # Dump is missing wp_posts entirely.
    sql = "CREATE TABLE `wp_options` (id INT);\nINSERT INTO `wp_options` VALUES (1);\n"
    ctx.http.mock_get(EXPORT, {"sql": sql, "size_bytes": len(sql)}, 200)
    result = await hdb.check_backup_restorability(ctx, CheckBackupRestorabilityParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.restorable is False
    assert "wp_posts" in result.data.missing_tables


async def test_check_backup_restorability_flags_truncated_dump():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"tables": [{"name": "wp_options", "size": "1KB"}]}, 200)
    # No trailing semicolon -- looks cut off mid-statement.
    sql = "CREATE TABLE `wp_options` (id INT)\nINSERT INTO `wp_options` VALUES (1"
    ctx.http.mock_get(EXPORT, {"sql": sql, "size_bytes": len(sql)}, 200)
    result = await hdb.check_backup_restorability(ctx, CheckBackupRestorabilityParams(site_id="x-com"))
    assert result.status == "success"
    assert result.data.truncated is True
    assert result.data.restorable is False


async def test_check_backup_restorability_flags_empty_table():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"tables": [{"name": "wp_options", "size": "1KB"}]}, 200)
    sql = "CREATE TABLE `wp_options` (id INT);\n"
    ctx.http.mock_get(EXPORT, {"sql": sql, "size_bytes": len(sql)}, 200)
    result = await hdb.check_backup_restorability(ctx, CheckBackupRestorabilityParams(site_id="x-com"))
    assert result.status == "success"
    assert "wp_options" in result.data.empty_tables


async def test_check_backup_restorability_surfaces_export_failure():
    ctx = await _ctx()
    ctx.http.mock_get(TABLES, {"tables": [{"name": "wp_options", "size": "1KB"}]}, 200)
    ctx.http.mock_get(EXPORT, {"code": "rest_no_route"}, 404)
    # No SSH configured either -> export_database_dump itself errors.
    result = await hdb.check_backup_restorability(ctx, CheckBackupRestorabilityParams(site_id="x-com"))
    assert result.status == "error"
    assert result.error_code == "SSH_NOT_CONFIGURED"
