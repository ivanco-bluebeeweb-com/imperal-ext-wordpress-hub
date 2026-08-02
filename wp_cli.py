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
