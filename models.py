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
    missing_alt_only: bool = Field(
        default=False,
        description="Only return images whose alt text is empty — the accessibility/SEO gap")


# NOTE: list_orders deliberately keeps its own params model. It used to share
# ListMediaParams, so media-specific fields added there leaked into the orders
# tool's public schema. Separate models keep each tool's contract independent.
# Kept as a comment, not a docstring: pydantic publishes docstrings into the
# generated JSON schema, which would change the tool's public description.
class ListOrdersParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class MediaAltItem(BaseModel):
    """One alt-text assignment: which library item, and what its alt should say."""
    media_id: int = Field(description="WordPress media library attachment id")
    alt_text: str = Field(description="Alt text to store on that attachment")


class UpdateMediaAltParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    items: list[MediaAltItem] = Field(
        description="Alt text assignments to apply, up to 100 per call")
    overwrite: bool = Field(
        default=False,
        description=("By default an attachment that already has alt text is left alone, so a "
                     "human's wording is never clobbered. Set true to replace existing alt too."))


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


class GetTermSeoMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int | None = Field(default=None, description="Numeric id of the category/tag term. Give this OR slug.")
    slug: str | None = Field(default=None, description="Term slug, e.g. 'sisteme'. Used when term_id is not given.")
    taxonomy: str | None = Field(default=None, description="Optional taxonomy ('category', 'post_tag', or a custom taxonomy) to disambiguate a slug used by several taxonomies.")


class UpdateTermSeoMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int | None = Field(default=None, description="Numeric id of the category/tag term. Give this OR slug.")
    slug: str | None = Field(default=None, description="Term slug, e.g. 'sisteme'. Used when term_id is not given.")
    taxonomy: str | None = Field(default=None, description="Optional taxonomy ('category', 'post_tag', or a custom taxonomy) to disambiguate a slug used by several taxonomies.")
    meta_title: str | None = Field(default=None, description="New Rank Math SEO title for the term. Omit to leave unchanged; pass an empty string to clear it.")
    meta_description: str | None = Field(default=None, description="New Rank Math meta description for the term. Omit to leave unchanged; pass an empty string to clear it.")
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
    alt_text: str = ""


class MediaAltResult(sdl.Entity):
    """Outcome of one update_media_alt call: what changed, what was left alone."""
    updated: int = 0
    skipped_existing: int = 0
    failed: int = 0
    updated_ids: list[int] = Field(default_factory=list)
    skipped_ids: list[int] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


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
    # Terms (categories/tags) reuse this entity: object_type says which kind of
    # object the row describes, taxonomy carries the term's taxonomy. Declared
    # explicitly because pydantic silently DROPS values assigned to undeclared
    # fields — that is how start dates once vanished from Asana task rows.
    object_type: str = "post"
    taxonomy: str = ""
    # check_seo_support only: what the site as a whole supports.
    bridge_version: str = ""
    rank_math_version: str = ""
    post_types: list[str] = Field(default_factory=list)
    taxonomies: list[str] = Field(default_factory=list)
