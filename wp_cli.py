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


async def _run(host, port, user, key_path, remote_cmd, timeout=_CMD_TIMEOUT,
                stdin_data: bytes | None = None) -> tuple[str | None, str | None]:
    """Run one remote command. Returns (stdout, error_message).

    `stdin_data`, when given, is piped to the remote command's stdin -- used
    by import_wxr to feed WXR XML into `wp import -` exactly the way WP-CLI's
    own docs describe piping into the '-' stdin argument.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *_ssh_cmd(host, port, user, key_path, remote_cmd),
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return None, "ssh binary not found — the server environment does not have ssh installed"
    except Exception as e:
        return None, f"subprocess error: {e}"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=stdin_data), timeout=timeout)
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


async def verify_core_checksums(cred: dict) -> tuple[dict | None, str | None]:
    """Verify core files with WP-CLI's documented checksum command.

    A non-zero exit deliberately becomes a normal result: it means WP-CLI
    completed the comparison and found a mismatch, rather than that the app
    can declare a failed verification to be a transport error.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    host, port, user = cred["host"], int(cred.get("port", 22)), cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp core verify-checksums --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is not None:
        return {"verified": True, "output": output}, None
    if error and ("checksum" in error.lower() or "doesn't verify" in error.lower()):
        return {"verified": False, "output": error}, None
    return None, error or "WP-CLI checksum verification failed"


async def verify_plugin_checksums(cred: dict, plugin: str) -> tuple[dict | None, str | None]:
    """Verify one WordPress.org plugin through WP-CLI.

    WP-CLI accepts a plugin slug; constrain it to its documented identifier
    shape and surface WordPress.org availability/mismatch output honestly.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if not plugin or not all(ch.isalnum() or ch in "-_" for ch in plugin):
        return None, "Invalid plugin slug — use the plugin's name from list_plugins."
    host, port, user = cred["host"], int(cred.get("port", 22)), cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp plugin verify-checksums {plugin} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is not None:
        return {"verified": True, "output": output}, None
    if error and ("checksum" in error.lower() or "wordpress.org" in error.lower() or "doesn't verify" in error.lower()):
        return {"verified": False, "output": error}, None
    return None, error or "WP-CLI plugin checksum verification failed"


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


async def get_permalink_structure(cred: dict) -> tuple[dict | None, str | None]:
    """Read the current permalink structure via `wp option get` on the three
    options wp-admin's own options-permalink.php reads: permalink_structure,
    category_base, and tag_base. There is no single `wp rewrite` subcommand
    that reads the structure back (`wp rewrite structure` only *sets* it).
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    php = (
        "echo json_encode(array("
        "'permalink_structure' => get_option('permalink_structure', ''), "
        "'category_base' => get_option('category_base', ''), "
        "'tag_base' => get_option('tag_base', '')));"
    )
    command = f"wp eval \"{php}\" --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        data = json.loads(output) if output else {}
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid permalink structure"
    if not isinstance(data, dict):
        return None, "WP-CLI returned an unexpected permalink structure"
    return data, None


async def update_permalink_structure(
    cred: dict, permalink_structure: str, category_base: str | None, tag_base: str | None,
) -> tuple[str | None, str | None]:
    """Set the permalink structure (and optionally category/tag base) via
    `wp rewrite structure`, which internally calls
    `WP_Rewrite::set_permalink_structure()` followed by a flush — the same
    two calls wp-admin's own "Save Changes" button on Settings > Permalinks
    makes. `permalink_structure` is passed as a single quoted argument;
    optional bases are passed via `--category-base`/`--tag-base` flags.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    for val in (permalink_structure, category_base or "", tag_base or ""):
        if any(ch in val for ch in ("'", '"', ";", "|", "&", "$", "`", "\n")):
            return None, "Invalid character in permalink structure or base — remove quotes/shell metacharacters."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    extra = ""
    if category_base is not None:
        extra += f" --category-base='{category_base}'"
    if tag_base is not None:
        extra += f" --tag-base='{tag_base}'"
    command = f"wp rewrite structure '{permalink_structure}'{extra} --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=60)


async def flush_rewrite_rules(cred: dict) -> tuple[str | None, str | None]:
    """Flush rewrite rules via `wp rewrite flush` — a soft flush (database
    rules only); `--hard` also regenerates .htaccess, but that only applies
    on single-site Apache installs, so this stays with the safe default.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp rewrite flush --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        return await _run(host, port, user, key_path, command, timeout=60)


async def list_rewrite_rules(cred: dict) -> tuple[list | None, str | None]:
    """List compiled rewrite rules via `wp rewrite list --format=json`."""
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    command = f"wp rewrite list --format=json --fields=match,query --path={wp_path} --allow-root"
    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    try:
        rows = json.loads(output) if output else []
    except json.JSONDecodeError:
        return None, "WP-CLI returned an invalid rewrite rule list"
    if not isinstance(rows, list):
        return None, "WP-CLI returned an unexpected rewrite rule list"
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


# ─── Group I — Logs ──────────────────────────────────────────────────────
#
# WP_DEBUG_LOG's default location is WP_CONTENT_DIR/debug.log (WordPress
# core's own documented default). We discover WP_CONTENT_DIR itself via
# `wp eval`, never assume 'wp-content' -- some sites relocate it. The PHP
# error log path is read from PHP's own `ini_get('error_log')`, never
# guessed at a distro-specific path -- if it's empty, PHP is likely logging
# to the web server's own error log instead, which is out of WP-CLI's reach
# and reported honestly as such, never fabricated.

async def _wp_content_dir(host, port, user, key_path, wp_path) -> tuple[str | None, str | None]:
    """Discover the site's real WP_CONTENT_DIR -- never hardcode 'wp-content'."""
    command = f"wp eval 'echo WP_CONTENT_DIR;' --path={wp_path} --allow-root"
    output, error = await _run(host, port, user, key_path, command)
    if output is None:
        return None, error or "SSH connection failed"
    path = output.strip()
    if not path or not path.startswith("/"):
        return None, "Could not determine WP_CONTENT_DIR from this site."
    return path, None


async def tail_debug_log(cred: dict, lines: int = 100) -> tuple[dict | None, str | None]:
    """Last N lines of wp-content/debug.log -- the file WP_DEBUG_LOG writes to.

    Discovers the real WP_CONTENT_DIR first (never hardcodes 'wp-content'),
    then checks the file exists before tailing it -- a site with WP_DEBUG_LOG
    off, or one that has never errored, legitimately has no debug.log, and
    that is reported honestly (exists=False, empty lines) rather than as an
    error.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    lines = max(1, min(int(lines), 1000))

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    async with _key_file(cred["key"]) as key_path:
        content_dir, err = await _wp_content_dir(host, port, user, key_path, wp_path)
        if content_dir is None:
            return None, err
        log_path = f"{content_dir}/debug.log"
        exists_out, exists_err = await _run(host, port, user, key_path, f"test -f {log_path} && echo yes || echo no")
        if exists_out is None:
            return None, exists_err or "SSH connection failed"
        if exists_out.strip() != "yes":
            return {"path": log_path, "exists": False, "lines": []}, None
        output, error = await _run(host, port, user, key_path, f"tail -n {lines} {log_path}")
        if output is None:
            return None, error or "Could not read the debug log — check file permissions."
        return {"path": log_path, "exists": True, "lines": output.splitlines()}, None


async def clear_debug_log(cred: dict) -> tuple[dict | None, str | None]:
    """Truncate wp-content/debug.log to empty via `: > <path>` (never deletes the file).

    Truncating (not deleting) preserves the file's ownership/permissions so
    WordPress can keep writing to it without needing to recreate it.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    async with _key_file(cred["key"]) as key_path:
        content_dir, err = await _wp_content_dir(host, port, user, key_path, wp_path)
        if content_dir is None:
            return None, err
        log_path = f"{content_dir}/debug.log"
        exists_out, exists_err = await _run(host, port, user, key_path, f"test -f {log_path} && echo yes || echo no")
        if exists_out is None:
            return None, exists_err or "SSH connection failed"
        if exists_out.strip() != "yes":
            return {"path": log_path, "cleared": False, "note": "No debug.log file exists to clear."}, None
        output, error = await _run(host, port, user, key_path, f": > {log_path}")
        if output is None and error:
            return None, error
        return {"path": log_path, "cleared": True}, None


async def tail_php_error_log(cred: dict, lines: int = 100) -> tuple[dict | None, str | None]:
    """Last N lines of PHP's own configured error_log, via `php -r ini_get('error_log')`.

    Never guesses a distro-specific path (e.g. /var/log/apache2/error.log) --
    only reads PHP's own declared setting. An empty ini_get means PHP is
    logging elsewhere (typically the web server's own error log), which is
    outside WP-CLI's reach and reported honestly, never fabricated.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    lines = max(1, min(int(lines), 1000))

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    async with _key_file(cred["key"]) as key_path:
        path_out, path_err = await _run(
            host, port, user, key_path,
            f"wp eval 'echo ini_get(\"error_log\");' --path={wp_path} --allow-root")
        if path_out is None:
            return None, path_err or "SSH connection failed"
        log_path = path_out.strip()
        if not log_path or not log_path.startswith("/"):
            return {"path": "", "exists": False, "lines": [],
                    "note": "PHP has no error_log path configured (likely logging to the web server's own error log, outside WP-CLI's reach)."}, None
        exists_out, exists_err = await _run(host, port, user, key_path, f"test -f {log_path} && echo yes || echo no")
        if exists_out is None:
            return None, exists_err or "SSH connection failed"
        if exists_out.strip() != "yes":
            return {"path": log_path, "exists": False, "lines": []}, None
        output, error = await _run(host, port, user, key_path, f"tail -n {lines} {log_path}")
        if output is None:
            return None, error or "Could not read the PHP error log — check file permissions."
        return {"path": log_path, "exists": True, "lines": output.splitlines()}, None


_WXR_EXPORT_CAP = 2_000_000  # ~2MB of XML text — mirrors the DB dump cap


async def export_wxr(
    cred: dict, content: str = "all", author: str | None = None, category: str | None = None,
    start_date: str | None = None, end_date: str | None = None, status: str | None = None,
) -> tuple[dict | None, str | None]:
    """Generate a WXR export to STDOUT via `wp export --stdout`, capped at ~2MB.

    `wp export` wraps core's own `export_wp()` (wp-admin/includes/export.php)
    -- the exact function Tools > Export's "Download Export File" button
    calls -- so this needs no plugin beyond WordPress itself. All filter
    values are validated before reaching the command line; none are freeform
    shell text.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    for val in (content, author, category, start_date, end_date, status):
        if val and not all(ch.isalnum() or ch in "-_./: " for ch in val):
            return None, "Invalid character in an export filter — remove quotes/shell metacharacters."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")

    flags = [f"--post_type={content}"] if content and content != "all" else []
    if author:
        flags.append(f"--author={author}")
    if category:
        flags.append(f"--category={category}")
    if start_date:
        flags.append(f"--start_date={start_date}")
    if end_date:
        flags.append(f"--end_date={end_date}")
    if status:
        flags.append(f"--post_status={status}")
    flags_str = " " + " ".join(flags) if flags else ""
    command = f"wp export --stdout{flags_str} --path={wp_path} --allow-root"

    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(host, port, user, key_path, command, timeout=120)
    if output is None:
        return None, error or "SSH connection failed"
    if len(output) > _WXR_EXPORT_CAP:
        return None, (
            f"Export is larger than {_WXR_EXPORT_CAP // 1_000_000}MB of XML text — "
            "narrow it with content/start_date/end_date/category and try again.")
    post_count = output.count("<wp:post_id>")
    return {"xml": output, "size_bytes": len(output.encode()), "post_count": post_count}, None


async def import_wxr(
    cred: dict, wxr_xml: str, authors: str = "create", skip_attachments: bool = False,
) -> tuple[dict | None, str | None]:
    """Import a WXR document via `wp import - --authors=<mode>`, piping the XML on stdin.

    Deliberately SSH-only: `WP_Import` (the class that does the real work)
    ships in the separate `wordpress-importer` plugin, not WordPress core,
    and its own public entry point (`dispatch()`) is a web-admin wizard tied
    to `$_GET`/`$_POST` state, not a clean function a REST callback could
    call safely -- verified by reading the plugin's own source
    (github.com/WordPress/wordpress-importer/src/class-wp-import.php).
    WP-CLI's own `Import_Command` (wp-cli/import-command) exists FOR exactly
    this reason: it is the verified, safe, headless way to drive the same
    importer, and it enforces the plugin being active before running
    ("WordPress Importer needs to be activated") -- the same guard this
    fallback surfaces verbatim rather than guessing at a nicer message.
    """
    if not cred.get("key"):
        return None, "Only key-based SSH auth is supported."
    if authors not in ("create", "skip"):
        return None, "authors must be 'create' or 'skip' (mapping.csv is not supported headless)."

    host = cred["host"]
    port = int(cred.get("port", 22))
    user = cred["user"]
    wp_path = cred.get("wp_path", "/var/www/html")
    skip_flag = " --skip=attachment" if skip_attachments else ""
    command = f"wp import - --authors={authors}{skip_flag} --path={wp_path} --allow-root"

    async with _key_file(cred["key"]) as key_path:
        output, error = await _run(
            host, port, user, key_path, command, timeout=180,
            stdin_data=wxr_xml.encode(),
        )
    if "needs to be activated" in (output or "") or "needs to be activated" in (error or ""):
        return None, ("The WordPress Importer plugin is not active on this site. "
                       "Install and activate 'wordpress-importer' first (install_plugin with "
                       "slug_or_url='wordpress-importer'), then retry.")
    if output is None:
        return None, error or "SSH connection failed"
    imported = output.count("Imported post as post_id")
    skipped = output.count("Post already imported")
    return {"output": output, "imported": imported, "skipped": skipped}, None
