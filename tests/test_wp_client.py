import base64
import pytest
from imperal_sdk.testing import MockContext
import wp_client as wc


def test_basic_auth_header():
    h = wc.basic_auth_header("admin", "abcd efgh")
    token = base64.b64encode(b"admin:abcd efgh").decode()
    assert h["Authorization"] == f"Basic {token}"


def test_normalize_base_url_forces_https_and_strips_slash():
    assert wc.normalize_base_url("https://Example.com/") == "https://Example.com"


def test_normalize_base_url_upgrades_http_to_https():
    """A user pasting an http:// link should not be hard-rejected -- upgrade it,
    since WordPress's own Application Password auth requires https anyway."""
    assert wc.normalize_base_url("http://example.com") == "https://example.com"


def test_normalize_base_url_accepts_bare_domain():
    """The Connect Site dialog must accept a bare domain typed without any
    scheme at all -- the most natural thing a human types first."""
    assert wc.normalize_base_url("example.com") == "https://example.com"
    assert wc.normalize_base_url("example.com/wp-admin") == "https://example.com"
    assert wc.normalize_base_url("www.example.com") == "https://www.example.com"


def test_normalize_base_url_rejects_empty_or_garbage():
    with pytest.raises(ValueError):
        wc.normalize_base_url("")
    with pytest.raises(ValueError):
        wc.normalize_base_url("ftp://example.com")


def test_site_id_from_url():
    assert wc.site_id_from_url("https://Example.com/blog") == "example-com"


def test_error_messages_are_user_safe():
    assert "credential" in wc.wp_error_message(401).lower()
    assert "not found" in wc.wp_error_message(404).lower()
    assert "server" in wc.wp_error_message(500).lower()


async def test_wp_get_calls_http_with_auth():
    ctx = MockContext()
    ctx.http.mock_get("https://example.com/wp-json/wp/v2/users/me", {"name": "Admin"}, 200)
    r = await wc.wp_get(ctx, "https://example.com", "/wp-json/wp/v2/users/me",
                        username="admin", app_password="pw")
    assert r.status_code == 200 and r.json()["name"] == "Admin"


async def test_wp_get_with_params_matches_mock():
    ctx = MockContext()
    ctx.http.mock_get("https://example.com/wp-json/wp/v2/posts", [{"id": 1}], 200)
    r = await wc.wp_get(ctx, "https://example.com", "/wp-json/wp/v2/posts",
                        username="a", app_password="p", params={"per_page": 5})
    assert r.status_code == 200
