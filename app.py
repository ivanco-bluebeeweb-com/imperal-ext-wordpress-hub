from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "wordpress-hub",
    version="1.8.0",
    display_name="WordPress Hub",
    description="Connect WordPress sites; create and update posts/pages with Gutenberg content, hierarchical categories and tags (create/list/update/delete, full parent/child tree), featured/inline images, and SEO fields; manage WooCommerce catalogues, guarded order operations, customers, coupons, and manual refunds; and work with content, health, SEO fields, and guarded point edits to Elementor/Bricks page-builder content.",
    icon="icon.svg",
    actions_explicit=True,
    capabilities=["wp:read", "wp:write"],
)

chat = ChatExtension(ext, tool_name="wordpress-hub", description="Browse connected WordPress sites and WooCommerce stores")


@ext.health_check
async def health_check(ctx) -> dict:
    """Liveness probe for the extension."""
    return {"status": "ok"}


