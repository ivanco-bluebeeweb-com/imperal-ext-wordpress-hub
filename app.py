from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "wp-site-connector",
    version="0.1.0",
    display_name="WP Site Connector",
    description="Connect WordPress sites by URL and Application Password and read their posts, pages, media, and health.",
    icon="icon.svg",
    actions_explicit=True,
    capabilities=["wp:read", "wp:write"],
)

chat = ChatExtension(ext, tool_name="wp-site-connector", description="Browse connected WordPress sites")


@ext.health_check
async def health_check(ctx) -> dict:
    """Liveness probe for the extension."""
    return {"status": "ok"}


