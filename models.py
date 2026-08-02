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
    page: int = Field(default=1, ge=1, description="Results page, starting at 1")
    status: str | None = Field(default=None, description="Optional WooCommerce order status, e.g. processing, completed, refunded")
    after: str | None = Field(default=None, description="Only orders created after this ISO-8601 date/time")
    before: str | None = Field(default=None, description="Only orders created before this ISO-8601 date/time")
    search: str | None = Field(default=None, description="Optional order number, customer name, or email search")


class WooListParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")
    page: int = Field(default=1, ge=1, description="Results page, starting at 1")
    search: str | None = Field(default=None, description="Optional name, SKU, email, or code search")


class ListProductsParams(WooListParams):
    status: str | None = Field(default=None, description="Optional product status: publish, draft, pending, private")
    stock_status: str | None = Field(default=None, description="Optional stock status: instock, outofstock, onbackorder")


class ListCustomersParams(WooListParams):
    pass


class ListCouponsParams(WooListParams):
    pass


class WooObjectParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    object_id: int = Field(gt=0, description="Numeric WooCommerce object id")


class ListRefundsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Order id whose refunds to list")
    limit: int = Field(default=20, ge=1, le=100, description="Max refunds to return, 1-100")


class StoreSummaryParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    after: str | None = Field(default=None, description="Start of the reporting period as ISO-8601 date/time")
    before: str | None = Field(default=None, description="End of the reporting period as ISO-8601 date/time")


class PreviewRefundParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")
    amount: str = Field(description="Positive refund amount as a decimal string")
    reason: str = Field(default="", max_length=1000, description="Optional internal refund reason")


class CreateRefundParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")
    amount: str = Field(description="Positive refund amount as a decimal string")
    reason: str = Field(default="", max_length=1000, description="Optional internal refund reason")
    expected_remaining_amount: str = Field(description="Exact refundable amount shown by preview; execution stops if it changed")
    idempotency_key: str = Field(min_length=8, max_length=100, description="Unique caller-generated key preventing duplicate refund execution")


class UpdateOrderStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")
    status: str = Field(description="Target status: pending, on-hold, processing, completed, cancelled, failed, or refunded")


class AddOrderNoteParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")
    note: str = Field(min_length=1, max_length=5000, description="Note text")
    customer_visible: bool = Field(default=False, description="True makes the note visible to the customer and may trigger a WooCommerce email")


class OrderLineQuantityChange(BaseModel):
    line_item_id: int = Field(gt=0, description="Existing WooCommerce order line item id")
    quantity: int = Field(ge=1, le=10000, description="New quantity; line removal is intentionally unsupported")


class PreviewOrderLineChangesParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")
    changes: list[OrderLineQuantityChange] = Field(min_length=1, max_length=100, description="New quantities for explicit existing line item ids")


class ApplyOrderLineChangesParams(PreviewOrderLineChangesParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact state token returned by preview; execution stops if the order changed")


class CustomerOrdersParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    customer_id: int = Field(gt=0, description="Numeric WooCommerce customer id")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum customer orders to return")
    page: int = Field(default=1, ge=1, description="Results page, starting at 1")


class CreateCustomerParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    email: str = Field(min_length=3, max_length=254, description="Customer email address")
    first_name: str = Field(default="", max_length=100, description="Optional first name")
    last_name: str = Field(default="", max_length=100, description="Optional last name")
    username: str | None = Field(default=None, min_length=1, max_length=100, description="Optional WordPress username; omit to let WooCommerce derive it")


class UpdateCustomerParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    customer_id: int = Field(gt=0, description="Numeric WooCommerce customer id")
    email: str | None = Field(default=None, min_length=3, max_length=254, description="New customer email address")
    first_name: str | None = Field(default=None, max_length=100, description="New first name; empty string clears it")
    last_name: str | None = Field(default=None, max_length=100, description="New last name; empty string clears it")
    username: str | None = Field(default=None, min_length=1, max_length=100, description="New WordPress username")


class CreateCouponParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    code: str = Field(min_length=1, max_length=100, description="Unique coupon code")
    discount_type: str = Field(default="percent", description="Discount type: percent, fixed_cart, or fixed_product")
    amount: str = Field(description="Non-negative discount amount as a decimal string")
    description: str = Field(default="", max_length=1000, description="Internal coupon description")
    date_expires: str | None = Field(default=None, description="Optional expiry date as YYYY-MM-DD")
    usage_limit: int | None = Field(default=None, ge=1, description="Optional total usage limit")
    usage_limit_per_user: int | None = Field(default=None, ge=1, description="Optional usage limit per customer")
    minimum_amount: str | None = Field(default=None, description="Optional minimum basket amount")
    maximum_amount: str | None = Field(default=None, description="Optional maximum basket amount")
    individual_use: bool = Field(default=False, description="Prevent combining this coupon with other coupons")
    free_shipping: bool = Field(default=False, description="Grant free shipping when a compatible method exists")
    exclude_sale_items: bool = Field(default=False, description="Exclude products already on sale")
    product_ids: list[int] = Field(default_factory=list, max_length=100, description="Optional included product ids")
    excluded_product_ids: list[int] = Field(default_factory=list, max_length=100, description="Optional excluded product ids")
    category_ids: list[int] = Field(default_factory=list, max_length=100, description="Optional included product category ids")
    excluded_category_ids: list[int] = Field(default_factory=list, max_length=100, description="Optional excluded product category ids")
    email_restrictions: list[str] = Field(default_factory=list, max_length=100, description="Optional customer email restrictions")


class UpdateCouponParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    coupon_id: int = Field(gt=0, description="Numeric WooCommerce coupon id")
    code: str | None = Field(default=None, min_length=1, max_length=100, description="New unique coupon code")
    discount_type: str | None = Field(default=None, description="Discount type: percent, fixed_cart, or fixed_product")
    amount: str | None = Field(default=None, description="Non-negative discount amount as a decimal string")
    description: str | None = Field(default=None, max_length=1000, description="Internal coupon description")
    date_expires: str | None = Field(default=None, description="Expiry date as YYYY-MM-DD; empty string clears it")
    usage_limit: int | None = Field(default=None, ge=1, description="New total usage limit")
    usage_limit_per_user: int | None = Field(default=None, ge=1, description="New usage limit per customer")
    minimum_amount: str | None = Field(default=None, description="Optional minimum basket amount")
    maximum_amount: str | None = Field(default=None, description="Optional maximum basket amount")
    individual_use: bool | None = Field(default=None, description="Prevent combining with other coupons")
    free_shipping: bool | None = Field(default=None, description="Grant free shipping")
    exclude_sale_items: bool | None = Field(default=None, description="Exclude products already on sale")
    product_ids: list[int] | None = Field(default=None, max_length=100, description="Replace included product ids")
    excluded_product_ids: list[int] | None = Field(default=None, max_length=100, description="Replace excluded product ids")
    category_ids: list[int] | None = Field(default=None, max_length=100, description="Replace included category ids")
    excluded_category_ids: list[int] | None = Field(default=None, max_length=100, description="Replace excluded category ids")
    email_restrictions: list[str] | None = Field(default=None, max_length=100, description="Replace customer email restrictions")


class ArchiveCouponParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    coupon_id: int = Field(gt=0, description="Numeric WooCommerce coupon id to move to Trash")


class CreateProductParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, max_length=200, description="Product name")
    product_type: str = Field(default="simple", description="Product type: simple, virtual, or downloadable")
    status: str = Field(default="draft", description="Initial status: draft, publish, pending, or private")
    sku: str | None = Field(default=None, max_length=100, description="Optional unique SKU")
    regular_price: str | None = Field(default=None, description="Optional non-negative regular price as a decimal string")
    sale_price: str | None = Field(default=None, description="Optional non-negative sale price as a decimal string")
    description: str | None = Field(default=None, description="Optional full product description")
    short_description: str | None = Field(default=None, description="Optional short product description")
    manage_stock: bool = Field(default=False, description="Track an exact stock quantity")
    stock_quantity: int | None = Field(default=None, ge=0, description="Stock quantity; enables stock management when set")
    stock_status: str = Field(default="instock", description="Stock state: instock, outofstock, or onbackorder")
    category_ids: list[int] = Field(default_factory=list, max_length=50, description="Existing WooCommerce product category ids")
    image_urls: list[str] = Field(default_factory=list, max_length=20, description="Public HTTPS image URLs to attach")


class UpdateProductParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int = Field(gt=0, description="Numeric WooCommerce product id")
    name: str | None = Field(default=None, min_length=1, max_length=200, description="New product name; omit to keep it")
    status: str | None = Field(default=None, description="New status: draft, publish, pending, or private")
    sku: str | None = Field(default=None, max_length=100, description="New SKU; empty string clears it")
    regular_price: str | None = Field(default=None, description="New non-negative regular price; empty string clears it")
    sale_price: str | None = Field(default=None, description="New non-negative sale price; empty string clears it")
    description: str | None = Field(default=None, description="New full description; empty string clears it")
    short_description: str | None = Field(default=None, description="New short description; empty string clears it")
    manage_stock: bool | None = Field(default=None, description="Enable or disable exact stock tracking")
    stock_quantity: int | None = Field(default=None, ge=0, description="New stock quantity; also enables stock tracking")
    stock_status: str | None = Field(default=None, description="New stock state: instock, outofstock, or onbackorder")
    category_ids: list[int] | None = Field(default=None, max_length=50, description="Replace categories with these existing category ids")
    image_urls: list[str] | None = Field(default=None, max_length=20, description="Replace images with these public HTTPS URLs")


class ArchiveProductParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int = Field(gt=0, description="Numeric WooCommerce product id to move to trash")


class ListProductCategoriesParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum categories to return")
    page: int = Field(default=1, ge=1, description="Result page, starting at 1")
    search: str | None = Field(default=None, description="Optional category name search")


class CreateProductCategoryParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, max_length=200, description="Category name")
    parent_id: int = Field(default=0, ge=0, description="Optional parent category id; 0 creates a top-level category")
    description: str = Field(default="", description="Optional category description")


class BulkProductChangeParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit product ids; 1-100, never inferred")
    status: str | None = Field(default=None, description="Set status on every product: draft, publish, pending, or private")
    regular_price_percent: str | None = Field(default=None, description="Percentage change to regular price, e.g. 10 or -15")
    stock_status: str | None = Field(default=None, description="Set stock state on every product")
    category_id_to_add: int | None = Field(default=None, gt=0, description="Add one existing category without removing current categories")


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
    date_created: str = ""
    customer_name: str = ""
    customer_email: str = ""
    item_count: int = 0
    items: list[str] = Field(default_factory=list)
    subtotal: str = ""
    tax_total: str = ""
    shipping_total: str = ""
    discount_total: str = ""
    payment_method: str = ""
    customer_note: str = ""


class WooStatus(sdl.Entity):
    available: bool = False
    version: str = ""
    currency: str = ""
    environment: str = ""


class Product(sdl.Entity):
    sku: str = ""
    price: str = ""
    regular_price: str = ""
    sale_price: str = ""
    stock_status: str = ""
    stock_quantity: int | None = None
    catalog_visibility: str = ""
    categories: list[str] = Field(default_factory=list)
    category_ids: list[int] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    variations: list[int] = Field(default_factory=list)


class ProductCategory(sdl.Entity):
    parent_id: int = 0
    product_count: int = 0


class ProductBulkResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class Customer(sdl.Entity):
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    orders_count: int = 0
    total_spent: str = ""
    date_created: str = ""


class Coupon(sdl.Entity):
    code: str = ""
    discount_type: str = ""
    amount: str = ""
    date_expires: str = ""
    usage_count: int = 0
    usage_limit: int | None = None
    usage_limit_per_user: int | None = None
    minimum_amount: str = ""
    maximum_amount: str = ""
    individual_use: bool = False
    free_shipping: bool = False
    exclude_sale_items: bool = False
    product_ids: list[int] = Field(default_factory=list)
    excluded_product_ids: list[int] = Field(default_factory=list)
    category_ids: list[int] = Field(default_factory=list)
    excluded_category_ids: list[int] = Field(default_factory=list)
    email_restrictions: list[str] = Field(default_factory=list)


class OrderNote(sdl.Entity):
    order_id: int = 0
    note: str = ""
    customer_visible: bool = False
    date_created: str = ""
    author: str = ""


class OrderLineChangeResult(sdl.Entity):
    order_id: int = 0
    preview: bool = True
    status: str = ""
    currency: str = ""
    current_total: str = ""
    expected_total: str = ""
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)


class Refund(sdl.Entity):
    order_id: int = 0
    amount: str = ""
    reason: str = ""
    date_created: str = ""
    refunded_by: int = 0


class RefundOperation(sdl.Entity):
    order_id: int = 0
    currency: str = ""
    order_total: str = ""
    already_refunded: str = ""
    remaining_refundable: str = ""
    requested_amount: str = ""
    reason: str = ""
    gateway_refund: bool = False
    restock_items: bool = False
    idempotency_key: str = ""
    preview: bool = True


class StoreSummary(sdl.Entity):
    period_after: str = ""
    period_before: str = ""
    currency: str = ""
    orders: int = 0
    gross_sales: str = ""
    net_sales: str = ""
    average_order_value: str = ""
    refunds: str = ""
    total_items: int = 0
    customers: int = 0


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
