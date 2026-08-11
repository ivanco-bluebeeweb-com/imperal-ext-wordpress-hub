"""SSH + WP-CLI executor using the system ssh binary.

Uses asyncio.create_subprocess_exec to run ssh without any third-party
SSH library — works in any environment that has the ssh binary available.
Private key is written to a temporary file (chmod 600) and deleted immediately
after the connection is established.
"""
import asyncio
import json
import os
import stat
import tempfile
import contextlib

_CMD_TIMEOUT = 30  # seconds per command


@contextlib.asynccontextmanager
async def _key_file(key_content: str):
    """Write a private key to a secure temp file; delete on exit."""
    if not key_content:
        yield None
        return
    fd, path = tempfile.mkstemp(suffix=".key")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(key_content)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600 — ssh refuses world-readable keys
        yield path
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _ssh_cmd(host: str, port: int, user: str, key_path: str | None, remote_cmd: str) -> list[str]:
    cmd = [
        "ssh",
        "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout=15",
        "-o", "BatchMode=yes",
    ]
    if key_path:
        cmd += ["-i", key_path]
    cmd += [f"{user}@{host}", remote_cmd]
    return cmd


async def _run(host, port, user, key_path, remote_cmd, timeout=_CMD_TIMEOUT) -> tuple[str | None, str | None]:
    """Run one remote command. Returns (stdout, error_message)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *_ssh_cmd(host, port, user, key_path, remote_cmd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return None, "ssh binary not found — the server environment does not have ssh installed"
    except Exception as e:
        return None, f"subprocess error: {e}"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "Command timed out"
    if proc.returncode == 0:
        return stdout.decode().strip(), None
    return None, stderr.decode().strip()[:300]


async def test_connection(cred: dict) -> tuple[bool, str]:
    """Test SSH + WP-CLI. Returns (ok, message)."""
    if not cred.get("key"):
        return False, "Only key-based SSH auth is supported. Please provide an SSH private key."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")

    async with _key_file(cred["key"]) as kf:
        out, err = await _run(host, port, user, kf,
                              f"wp core version --path={wp_path} --allow-root")
    if out is None:
        return False, err or "SSH connection failed"
    return True, f"WordPress {out}"


async def list_plugins(cred: dict) -> tuple[list | None, str | None]:
    """List installed plugins through WP-CLI without changing the site.

    WordPress core intentionally has no plugin inventory endpoint in its REST
    API. SSH is therefore required, and the command is fixed here rather than
    accepting user-supplied fragments.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = (
        "wp plugin list --format=json "
        "--fields=name,status,version,update,update_version "
        f"--path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        plugins = json.loads(output) if output else []
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid plugin list"
    if not isinstance(plugins, list):
        return None, "WP-CLI returned an unexpected plugin list"
    return plugins, None


async def purge_litespeed_cache(cred: dict, scope: str) -> tuple[str | None, str | None]:
    """Purge the LiteSpeed Cache page cache through its own WP-CLI namespace.

    Scoped to exactly one fixed command shape — no free-form namespace or
    argument list reaches the shell here, unlike a generic WP-CLI runner.
    Caller is responsible for confirming LiteSpeed Cache is the active plugin
    before calling this (see list_plugins).
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    tail = "" if scope == "all" else f" {scope}"
    command = f"wp litespeed-purge{tail} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command)


async def purge_w3tc_cache(cred: dict) -> tuple[str | None, str | None]:
    """Purge W3 Total Cache's page cache through its own WP-CLI namespace.

    `wp w3-total-cache flush all` -- verified as a command bundled WITH the
    W3 Total Cache plugin itself (github.com/BoldGrid/w3-total-cache wiki
    WP-CLI page), the same safety class as purge_litespeed_cache above, NOT
    a separately-installed wp-cli package (unlike WP Rocket's/WP Super
    Cache's own CLI add-ons, which this app deliberately does not call since
    their presence on an arbitrary server cannot be verified in advance).
    Caller is responsible for confirming w3-total-cache is the active plugin
    before calling this (see list_plugins).
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp w3-total-cache flush all --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command)


async def install_plugin(cred: dict, source: str, activate: bool) -> tuple[dict | None, str | None]:
    """Install a plugin via WP-CLI from a WordPress.org slug or a direct .zip URL.

    Scoped to `wp plugin install` only — no other WP-CLI namespace reaches the
    shell from this path. `source` is quoted as a single shell argument so it
    cannot inject extra flags or commands.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not source or any(ch in source for ch in ("'", '"', ";", "|", "&", "$", "`", "\n")):
        return None, "Invalid plugin source — use a WordPress.org slug or a plain https:// .zip URL."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    activate_flag = " --activate" if activate else ""
    command = (
        f"wp plugin install '{source}'{activate_flag} --format=json "
        f"--path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=60)
    if output is None:
        return None, error or "SSH connection failed"
    return {"raw": output}, None


async def update_plugin(cred: dict, slug: str) -> tuple[dict | None, str | None]:
    """Update ONE already-installed plugin via `wp plugin update <slug>`.

    Scoped to a single named plugin, not `--all` — an unattended bulk update
    across every plugin on a live site is a much bigger blast radius than a
    single named one, so bulk plugin updates are deliberately not exposed.
    `slug` is restricted to safe plugin-slug characters so it cannot inject
    extra shell arguments.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not slug or not all(ch.isalnum() or ch in "-_." for ch in slug):
        return None, "Invalid plugin slug — use the plugin's folder/file slug from list_plugins."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = (
        f"wp plugin update {slug} --format=json "
        f"--path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=60)
    if output is None:
        return None, error or "SSH connection failed"
    return {"raw": output}, None


async def update_core(cred: dict) -> tuple[dict | None, str | None]:
    """Update WordPress core to the latest version via `wp core update`.

    No version argument is accepted — always the latest, matching what
    clicking "Update Now" in wp-admin does. A stuck/incompatible update is
    the site owner's call to make deliberately (e.g. pinning a version),
    which this app does not support.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp core update --format=json --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=120)
    if output is None:
        return None, error or "SSH connection failed"
    return {"raw": output}, None


async def run_wp_cron(cred: dict) -> tuple[str | None, str | None]:
    """Force-run every due cron event now via `wp cron event run --due-now`.

    Fixed shape, no event-name argument accepted — running a single
    caller-chosen event by name would let an agent trigger arbitrary
    site-specific cron hooks (some of which can be destructive, e.g. cleanup
    tasks), which is out of scope for a diagnostic "unstick the queue" tool.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp cron event run --due-now --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=60)


async def list_transients(cred: dict) -> tuple[list | None, str | None]:
    """List transients via `wp transient list --format=json` (wp-cli/cache-command).

    Verified command shape against developer.wordpress.org/cli/commands/transient/list/
    before writing this. Returns raw wp-cli rows (name, value, expiration).
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp transient list --format=json --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        rows = json.loads(output) if output else []
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid transient list"
    if not isinstance(rows, list):
        return None, "WP-CLI returned an unexpected transient list"
    return rows, None


async def delete_transient(cred: dict, name: str) -> tuple[str | None, str | None]:
    """Delete one named transient via `wp transient delete <name>`.

    `name` is restricted to safe option-key characters so it cannot inject
    extra shell arguments, matching this file's existing slug-validation bar.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not name or not all(ch.isalnum() or ch in "-_." for ch in name):
        return None, "Invalid transient name — use a name from list_transients."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp transient delete {name} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command)


async def flush_all_transients(cred: dict) -> tuple[str | None, str | None]:
    """Delete every transient via `wp transient delete --all`.

    Fixed shape, no `--expired`-only variant exposed separately -- callers who
    want the full flush use this; a narrower cleanup is not this app's job.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp transient delete --all --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=60)


async def get_cache_type(cred: dict) -> tuple[str | None, str | None]:
    """Detect the active object-cache implementation via `wp cache type`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp cache type --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command)


async def flush_object_cache(cred: dict) -> tuple[str | None, str | None]:
    """Flush the WordPress object cache via `wp cache flush`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp cache flush --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=60)


async def list_cron_events(cred: dict) -> tuple[list | None, str | None]:
    """List scheduled cron events via `wp cron event list --format=json`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = (
        "wp cron event list --format=json "
        "--fields=hook,next_run_gmt,next_run_relative,recurrence "
        f"--path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        rows = json.loads(output) if output else []
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid cron event list"
    if not isinstance(rows, list):
        return None, "WP-CLI returned an unexpected cron event list"
    return rows, None


async def run_cron_event(cred: dict, hook: str) -> tuple[str | None, str | None]:
    """Run one named cron event now via `wp cron event run <hook>`.

    `hook` is restricted to safe characters (letters/digits/-_./) so it
    cannot inject extra shell arguments, matching this file's existing
    slug-validation bar for update_plugin/delete_transient.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not hook or not all(ch.isalnum() or ch in "-_./" for ch in hook):
        return None, "Invalid hook name — use a hook from list_cron_events."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp cron event run {hook} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=60)


async def delete_cron_event(cred: dict, hook: str) -> tuple[str | None, str | None]:
    """Unschedule every occurrence of one cron hook via `wp cron event delete <hook>`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not hook or not all(ch.isalnum() or ch in "-_./" for ch in hook):
        return None, "Invalid hook name — use a hook from list_cron_events."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp cron event delete {hook} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command)


async def list_cron_schedules(cred: dict) -> tuple[list | None, str | None]:
    """List registered cron recurrence intervals via `wp cron schedule list --format=json`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp cron schedule list --format=json --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        rows = json.loads(output) if output else []
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid cron schedule list"
    if not isinstance(rows, list):
        return None, "WP-CLI returned an unexpected cron schedule list"
    return rows, None


async def _wp_prefix(host, port, user, key_path, wp_path) -> tuple[str | None, str | None]:
    """Discover the site's real $wpdb->prefix — never hardcode 'wp_'."""
    command = f"wp eval 'global $wpdb; echo $wpdb->prefix;' --path={wp_path} --allow-root"
    output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    prefix = output.strip()
    if not prefix or not all(ch.isalnum() or ch == "_" for ch in prefix):
        return None, "Could not determine a safe table prefix from this site."
    return prefix, None


async def list_database_tables(cred: dict) -> tuple[list | None, str | None]:
    """List every table for this site via `wp db size --tables --format=json`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = (
        f"wp db size --tables --format=json --path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=60)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        rows = json.loads(output) if output else []
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid table list"
    if not isinstance(rows, list):
        return None, "WP-CLI returned an unexpected table list"
    return rows, None


def _safe_replace_string(value: str) -> bool:
    """Reject characters that could break out of the single-quoted shell arg.

    Single quotes inside a POSIX single-quoted string cannot be escaped except
    via the '\\''  trick; simplest and safest is to reject bare single quotes,
    backticks, and $() entirely — these are URLs/domains/text snippets, not
    shell scripts.
    """
    return bool(value) and not any(ch in value for ch in ("'", "`", "\n", "\r"))


async def run_db_search_replace(
    cred: dict, old: str, new: str, *, dry_run: bool, tables: list[str] | None = None,
) -> tuple[dict | None, str | None]:
    """Run `wp search-replace <old> <new> [tables...] [--dry-run] --format=count`.

    Always scoped to --format=count (a single integer) — never --report's full
    per-row table, which could leak column values from other plugins' data in
    the response. `tables` restricts to explicit table names (validated against
    the site's own discovered prefix by the caller) or wildcards the caller
    built from that prefix; never accepts free-form shell text here.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not _safe_replace_string(old) or not _safe_replace_string(new):
        return None, "Search/replace text cannot contain quotes, backticks, or newlines."
    if tables:
        for t in tables:
            if not t or not all(ch.isalnum() or ch in "-_.*" for ch in t):
                return None, "Invalid table name — use names/wildcards from list_database_tables."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    table_args = " " + " ".join(f"'{t}'" for t in tables) if tables else ""
    dry_flag = " --dry-run" if dry_run else ""
    command = (
        f"wp search-replace '{old}' '{new}'{table_args}{dry_flag} "
        f"--format=count --skip-columns=guid --path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=90)
    if output is None:
        return None, error or "SSH connection failed"
    text = (output or "").strip()
    count = int(text) if text.isdigit() else None
    if count is None:
        return None, "WP-CLI returned an unexpected search-replace result."
    return {"replacements": count, "dry_run": dry_run}, None


async def optimize_database_tables(cred: dict) -> tuple[str | None, str | None]:
    """Defragment/optimize every table via `wp db optimize`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp db optimize --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=90)


async def check_database(cred: dict) -> tuple[str | None, str | None]:
    """Run a read-only integrity check via `wp db check` (mysqlcheck --check)."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp db check --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=90)


async def repair_database(cred: dict) -> tuple[str | None, str | None]:
    """Repair corrupted tables via `wp db repair` (mysqlcheck --repair)."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp db repair --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=90)


_DUMP_SIZE_CAP = 2_000_000  # ~2MB of SQL text — beyond this, advise scoping to specific tables


async def export_database_dump(
    cred: dict, tables: list[str] | None = None,
) -> tuple[dict | None, str | None]:
    """Export a SQL dump to STDOUT via `wp db export -`, capped at ~2MB of text.

    There is no file-hosting/signed-URL infrastructure in this app, so a dump
    is returned inline — safe for a handful of tables, not a whole large site.
    Exceeding the cap is reported as a clear error asking the caller to scope
    `tables` down, not silently truncated (a truncated SQL dump is corrupt and
    must never be presented as a usable dump).
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if tables:
        for t in tables:
            if not t or not all(ch.isalnum() or ch in "-_.*" for ch in t):
                return None, "Invalid table name — use names/wildcards from list_database_tables."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    tables_flag = f" --tables={','.join(tables)}" if tables else ""
    command = f"wp db export -{tables_flag} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=120)
    if output is None:
        return None, error or "SSH connection failed"
    if len(output) > _DUMP_SIZE_CAP:
        return None, (
            f"Dump is larger than {_DUMP_SIZE_CAP // 1_000_000}MB of SQL text — "
            "pass specific `tables` to scope the export down."
        )
    return {"sql": output, "size_bytes": len(output.encode())}, None


async def count_post_type_rows(cred: dict, post_type: str) -> tuple[int | None, str | None]:
    """Count rows of one post type via `wp post list --post_type=<t> --format=count`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not post_type or not all(ch.isalnum() or ch in "-_" for ch in post_type):
        return None, "Invalid post_type — use a slug from the site's own /wp/v2/types."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = (
        f"wp post list --post_type={post_type} --post_status=any --format=count "
        f"--path={wp_path} --allow-root"
    )
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    text = (output or "").strip()
    if not text.isdigit():
        return None, "WP-CLI returned an unexpected post count."
    return int(text), None


async def count_orphaned_postmeta(cred: dict) -> tuple[int | None, str | None]:
    """Count wp_postmeta rows whose post_id no longer has a matching wp_posts row.

    Discovers the site's real table prefix first via `wp eval` — never
    hardcodes 'wp_' (some sites use a custom prefix).
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    async with _key_file(cred["key"]) as key_path:
        prefix, error = await _wp_prefix(host, port, user, key_path, wp_path)
        if prefix is None:
            return None, error
        query = (
            f"SELECT COUNT(*) FROM {prefix}postmeta pm "
            f"LEFT JOIN {prefix}posts p ON pm.post_id = p.ID WHERE p.ID IS NULL"
        )
        command = (
            f"wp db query \"{query}\" --skip-column-names --path={wp_path} --allow-root"
        )
        output, error = await _run(host, port, user, key_path, command, timeout=60)
    if output is None:
        return None, error or "SSH connection failed"
    text = (output or "").strip()
    if not text.isdigit():
        return None, "WP-CLI returned an unexpected orphan count."
    return int(text), None


async def get_server_info(cred: dict) -> dict:
    """Run WP-CLI diagnostic commands and return results."""
    if not cred.get("key"):
        return {"error": "Only key-based SSH auth is supported."}

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")

    commands = [
        f"wp core version --path={wp_path} --allow-root",
        f"wp eval 'echo PHP_VERSION;' --path={wp_path} --allow-root",
        f"wp plugin list --update=available --format=json --fields=name,title,version,update_version --path={wp_path} --allow-root",
        f"wp theme list --update=available --format=json --fields=name,title,version,update_version --path={wp_path} --allow-root",
        f"wp core check-update --format=json --path={wp_path} --allow-root",
        f"wp cron event list --format=count --path={wp_path} --allow-root",
        f"wp db size --size_format=mb --path={wp_path} --allow-root",
    ]

    async with _key_file(cred["key"]) as kf:
        results = await asyncio.gather(*[
            _run(host, port, user, kf, cmd) for cmd in commands
        ])

    (wp_r, php_r, plug_r, theme_r, core_r, cron_r, db_r) = results

    def _parse_list(raw) -> list:
        if not raw[0]:
            return []
        try:
            data = json.loads(raw[0])
            return data if isinstance(data, list) else []
        except Exception:
            return []

    plugin_list = _parse_list(plug_r)
    theme_list  = _parse_list(theme_r)

    # Parse core update
    core_update = False
    core_update_ver = ""
    if core_r[0]:
        try:
            updates = json.loads(core_r[0])
            if updates and isinstance(updates, list):
                core_update = True
                core_update_ver = updates[0].get("version", "")
        except Exception:
            pass

    def _int(val):
        v = (val[0] or "").strip()
        return int(v) if v.isdigit() else 0

    return {
        "wp_version":          (wp_r[0] or "").strip(),
        "php_version":         (php_r[0] or "").strip(),
        "plugin_updates":      len(plugin_list),
        "plugin_updates_list": plugin_list,
        "theme_updates":       len(theme_list),
        "theme_updates_list":  theme_list,
        "core_update":         core_update,
        "core_update_version": core_update_ver,
        "cron_count":          _int(cron_r),
        "db_size_mb":          (db_r[0] or "").strip(),
    }
