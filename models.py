from pydantic import BaseModel, Field
from imperal_sdk import sdl

VNEXT = "requires companion plugin (vNext)"


class ConnectSiteParams(BaseModel):
    url: str = Field(description="Full https:// URL of the WordPress site, e.g. https://example.com")
    username: str = Field(description="WordPress username that created the Application Password")
    app_password: str = Field(description="WordPress Application Password (from Users → Profile → Application Passwords)")


class SiteIdParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class ListContentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")
    search: str | None = Field(default=None, description="Optional search term")


class ListMediaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class _NoParams(BaseModel):
    pass


class AddSSHParams(BaseModel):
    site_id: str = Field(default="", description="Site id — set automatically by the panel form")
    ssh_host: str = Field(description="SSH hostname or IP address of the server")
    ssh_port: int = Field(default=22, description="SSH port (default 22)")
    ssh_user: str = Field(description="SSH username")
    wp_path: str = Field(description="Absolute path to the WordPress installation on the server, e.g. /var/www/html")
    ssh_key: str = Field(default="", description="SSH private key in PEM format. Use this OR ssh_password.")
    ssh_password: str = Field(default="", description="SSH password. Use this OR ssh_key.")


class ListCommentsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    status: str = Field(default="hold", description="Comment status: 'hold' (pending moderation), 'approved', 'spam', or 'all'")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class ListCustomPostsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_type: str = Field(description="REST base slug of the custom post type, e.g. 'products', 'events', 'portfolio'")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")
    search: str | None = Field(default=None, description="Optional search term")


class GetSeoMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int | None = Field(default=None, description="Numeric id of the post or page. Give this OR slug.")
    slug: str | None = Field(default=None, description="Slug of the post or page, e.g. 'about-us'. Used when post_id is not given.")
    post_type: str | None = Field(default=None, description="Optional post type ('post', 'page', or a custom type) to disambiguate a slug used by several items.")


class UpdateSeoMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int | None = Field(default=None, description="Numeric id of the post or page. Give this OR slug.")
    slug: str | None = Field(default=None, description="Slug of the post or page, e.g. 'about-us'. Used when post_id is not given.")
    post_type: str | None = Field(default=None, description="Optional post type ('post', 'page', or a custom type) to disambiguate a slug used by several items.")
    meta_title: str | None = Field(default=None, description="New Rank Math SEO title. Omit to leave unchanged; pass an empty string to clear it.")
    meta_description: str | None = Field(default=None, description="New Rank Math meta description. Omit to leave unchanged; pass an empty string to clear it.")
    canonical_url: str | None = Field(default=None, description="Optional canonical URL. Omit to leave unchanged; empty string clears it.")
    robots: list[str] | None = Field(default=None, description="Optional robots directives, e.g. ['noindex','nofollow']. Allowed: index, noindex, nofollow, noarchive, noimageindex, nosnippet. Omit to leave unchanged.")
    focus_keyword: str | None = Field(default=None, description="Optional Rank Math focus keyword. Omit to leave unchanged.")


# SDL entities. sdl.Entity already provides: id, title, kind, subtitle, description, status, url.
class Site(sdl.Entity):
    username: str = ""
    last_checked: str | None = None


class Post(sdl.Entity):
    link: str = ""
    date: str | None = None


class Page(sdl.Entity):
    link: str = ""
    date: str | None = None


class MediaItem(sdl.Entity):
    mime_type: str = ""


class Comment(sdl.Entity):
    author: str = ""
    snippet: str = ""
    post_id: str = ""


class WPUser(sdl.Entity):
    role: str = ""
    registered: str = ""


class Order(sdl.Entity):
    total: str = ""
    currency: str = ""


class ServerInfo(sdl.Entity):
    wp_version: str = ""
    php_version: str = ""
    plugin_updates: int = 0
    plugin_updates_list: list = Field(default_factory=list)
    theme_updates: int = 0
    theme_updates_list: list = Field(default_factory=list)
    core_update: bool = False
    core_update_version: str = ""
    cron_count: int = 0
    db_size_mb: str = ""


class RefreshAllResult(sdl.Entity):
    connected: int = 0
    total: int = 0


class SiteHealth(sdl.Entity):
    reachable: bool = False
    auth_ok: bool = False
    ssl_valid: bool = False
    content_counts: dict = Field(default_factory=dict)
    plugin_updates_available: str = VNEXT
    php_version: str = VNEXT


class SeoMeta(sdl.Entity):
    """Rank Math SEO fields for a single post or page.

    Empty strings mean "no SEO value set" — Rank Math then falls back to its
    own template for that post type, so an empty meta_title is normal, not a
    failure. robots is a list because Rank Math stores it as an array.
    """
    post_id: int = 0
    post_type: str = ""
    slug: str = ""
    meta_title: str = ""
    meta_description: str = ""
    focus_keyword: str = ""
    canonical_url: str = ""
    robots: list[str] = Field(default_factory=list)
    seo_plugin: str = ""
    source: str = ""
    updated_fields: list[str] = Field(default_factory=list)
