from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "wp-site-connector",
    version="1.2.0",
    display_name="WP Site Connector",
    description="Connect WordPress sites; manage WooCommerce catalogues, guarded order operations, customers, coupons, and manual refunds; and work with content, health, and SEO fields.",
    icon="icon.svg",
    actions_explicit=True,
    capabilities=["wp:read", "wp:write"],
)

chat = ChatExtension(ext, tool_name="wp-site-connector", description="Browse connected WordPress sites and WooCommerce stores")


@ext.health_check
async def health_check(ctx) -> dict:
    """Liveness probe for the extension."""
    return {"status": "ok"}


