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
    status: str = Field(
        default="publish,draft,pending,future,private",
        description=(
            "Comma-separated WordPress post status(es) to include, e.g. "
            "'publish' or 'draft' or 'publish,draft'. WordPress's REST API "
            "returns ONLY 'publish' posts by default when this is omitted — "
            "so drafts/pending/scheduled/private posts silently disappear from "
            "list_posts/list_pages unless requested explicitly. Defaults to "
            "every common status so nothing is hidden by default; narrow it "
            "explicitly (e.g. status='draft') to see only drafts."
        ),
    )


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


class ListOrderNotesParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")


class OrderLineItemInput(BaseModel):
    product_id: int = Field(gt=0, description="Existing WooCommerce product id")
    quantity: int = Field(default=1, ge=1, le=10000, description="Quantity to order")


class CreateOrderParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    status: str = Field(default="pending", description="Initial order status, e.g. pending, processing, on-hold")
    customer_id: int | None = Field(default=None, description="Existing registered customer id; omit for a guest order")
    billing_email: str | None = Field(default=None, max_length=254, description="Billing email — REQUIRED for a guest order (customer_id omitted)")
    billing_first_name: str | None = Field(default=None, max_length=100, description="Optional billing first name")
    billing_last_name: str | None = Field(default=None, max_length=100, description="Optional billing last name")
    line_items: list[OrderLineItemInput] = Field(min_length=1, max_length=100, description="Products and quantities for this manual order")
    customer_note: str | None = Field(default=None, max_length=2000, description="Optional note visible to the customer on the order")
    set_paid: bool = Field(default=False, description="Mark the order as already paid (skips the payment step) — use for phone/in-person orders taken with payment already received")


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


class DeleteCustomerParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    customer_id: int = Field(gt=0, description="Numeric WooCommerce customer id to permanently delete")
    reassign_to: int | None = Field(
        default=None,
        description="Optional existing customer id to reassign this customer's past orders to; omitted orders keep their own stored billing snapshot and are not deleted",
    )


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


class VariationAttributeInput(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Existing parent product attribute name")
    option: str = Field(min_length=1, max_length=100, description="Existing option of that parent attribute")


class ListProductVariationsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int = Field(gt=0, description="Parent variable WooCommerce product id")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum variations to return")
    page: int = Field(default=1, ge=1, description="Result page, starting at 1")


class CreateProductVariationParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int = Field(gt=0, description="Parent variable WooCommerce product id")
    attributes: list[VariationAttributeInput] = Field(min_length=1, max_length=20, description="Explicit existing parent attribute options that identify this variation")
    sku: str | None = Field(default=None, max_length=100, description="Optional unique SKU")
    regular_price: str | None = Field(default=None, description="Optional non-negative regular price")
    sale_price: str | None = Field(default=None, description="Optional non-negative sale price")
    manage_stock: bool | None = Field(default=None, description="Enable or disable exact stock tracking")
    stock_quantity: int | None = Field(default=None, ge=0, description="New stock quantity; also enables stock tracking")
    stock_status: str | None = Field(default=None, description="New stock state: instock, outofstock, or onbackorder")
    status: str = Field(default="draft", description="Variation status; defaults to draft for safe review")


class UpdateProductVariationParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int = Field(gt=0, description="Parent variable WooCommerce product id")
    variation_id: int = Field(gt=0, description="Existing WooCommerce variation id")
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token returned by list_product_variations; execution stops if this variation changed")
    sku: str | None = Field(default=None, max_length=100, description="New SKU; empty string clears it")
    regular_price: str | None = Field(default=None, description="New non-negative regular price; empty string clears it")
    sale_price: str | None = Field(default=None, description="New non-negative sale price; empty string clears it")
    manage_stock: bool | None = Field(default=None, description="Enable or disable exact stock tracking")
    stock_quantity: int | None = Field(default=None, ge=0, description="New stock quantity; also enables stock tracking")
    stock_status: str | None = Field(default=None, description="New stock state: instock, outofstock, or onbackorder")
    status: str | None = Field(default=None, description="New status: draft, publish, pending, or private")


class BulkVariationChangeParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int = Field(gt=0, description="Parent variable WooCommerce product id")
    variation_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit variation ids; 1-100, never inferred")
    regular_price_percent: str | None = Field(default=None, description="Percentage change to regular price, e.g. 10 or -15")
    stock_status: str | None = Field(default=None, description="Set stock state on every explicit variation")
    status: str | None = Field(default=None, description="Set status on every explicit variation")


class ApplyBulkVariationChangeParams(BulkVariationChangeParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token returned by preview; execution stops before all writes if any variation changed")


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


class ApplyBulkProductChangeParams(BulkProductChangeParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact state token returned by preview; execution stops before all writes if any product changed")


class CsvCatalogImportParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    csv_text: str = Field(min_length=1, max_length=50000, description="CSV text with header SKU and optional regular_price, sale_price, stock_quantity, stock_status columns; maximum 100 data rows")


class ApplyCsvCatalogImportParams(CsvCatalogImportParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token returned by preview; execution stops before all writes if any matched SKU changed")
    import_id: str | None = Field(default=None, description="Optional import id returned by preview, used to record the apply result")


class CsvVariationImportParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    csv_text: str = Field(min_length=1, max_length=50000, description="CSV text with parent_sku, variation_sku and optional regular_price, sale_price, stock_quantity, stock_status columns; maximum 100 data rows")


class ApplyCsvVariationImportParams(CsvVariationImportParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token returned by preview; execution stops before all writes if any matched variation changed")
    import_id: str | None = Field(default=None, description="Optional import id returned by preview, used to record the apply result")


class ListCsvImportsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum import history rows to return")


class GetCsvImportParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    import_id: str = Field(min_length=1, description="Import id returned by preview_csv_catalog_import or preview_csv_variation_import")


class RetryCsvImportFailuresParams(GetCsvImportParams):
    pass


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


class SetCommentStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    comment_id: int = Field(gt=0, description="Numeric WordPress comment id from list_comments")
    status: str = Field(description="New status: 'approved' (publish), 'hold' (unapprove/pending), 'spam', or 'trash'")


class ReplyToCommentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    comment_id: int = Field(gt=0, description="Numeric WordPress comment id being replied to, from list_comments")
    content: str = Field(min_length=1, max_length=5000, description="Reply text, posted as the connected WordPress user")


class ListCustomPostsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_type: str = Field(description="REST base slug of the custom post type, e.g. 'products', 'events', 'portfolio'")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")
    search: str | None = Field(default=None, description="Optional search term")


# ─────────── native WordPress taxonomies (categories/tags for posts) ───────────
# Separate from ProductCategory/CreateProductCategoryParams above, which are
# WooCommerce-only (/wc/v3/products/categories, flat, product-count based).
# These hit the native /wp/v2/categories and /wp/v2/tags taxonomies that
# create_post/update_post already resolve names against, but never create.
# Categories and tags get their own distinct tool names/params (not one
# generic "taxonomy" enum) so the shape of each call matches what it actually
# supports — parent/child nesting is real for categories, meaningless for tags.

class ListPostCategoriesParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    parent_id: int | None = Field(default=None, ge=0, description="Only list children of this category id; 0 lists top-level categories; omit to list all")
    search: str | None = Field(default=None, description="Optional name search")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum categories to return")
    page: int = Field(default=1, ge=1, description="Result page, starting at 1")


class CreatePostCategoryParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, max_length=200, description="Category name")
    parent_id: int = Field(default=0, ge=0, description="Optional parent category id; 0 creates a top-level category")
    description: str = Field(default="", description="Optional category description")


class UpdatePostCategoryParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(gt=0, description="Existing category id, from list_post_categories")
    name: str | None = Field(default=None, min_length=1, max_length=200, description="New name; omit to keep it")
    parent_id: int | None = Field(default=None, ge=0, description="New parent category id; 0 moves it to top-level; omit to keep it")
    description: str | None = Field(default=None, description="New description; empty string clears it")


class DeletePostCategoryParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(gt=0, description="Existing category id to permanently delete")


class ListPostTagsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    search: str | None = Field(default=None, description="Optional name search")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum tags to return")
    page: int = Field(default=1, ge=1, description="Result page, starting at 1")


class CreatePostTagParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, max_length=200, description="Tag name")
    description: str = Field(default="", description="Optional tag description")


class UpdatePostTagParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(gt=0, description="Existing tag id, from list_post_tags")
    name: str | None = Field(default=None, min_length=1, max_length=200, description="New name; omit to keep it")
    description: str | None = Field(default=None, description="New description; empty string clears it")


class DeletePostTagParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(gt=0, description="Existing tag id to permanently delete")


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
    rich_snippet: str | None = Field(default=None, description="Optional Rank Math schema/rich-snippet type, e.g. 'Article', 'Product', 'Recipe', or 'off' to disable schema for this item. Rank Math accepts an open-ended set of schema.org type names here (including PRO schema templates and custom schema), so this is free text, not a fixed list — pass exactly what should appear in Rank Math's Schema type dropdown. Omit to leave unchanged; empty string clears it.")


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
    rich_snippet: str | None = Field(default=None, description="Optional Rank Math schema/rich-snippet type for the term archive, e.g. 'Article', 'CollectionPage', or 'off'. Free text — Rank Math accepts an open-ended set of schema.org type names. Omit to leave unchanged; empty string clears it.")


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


class CreateUserParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    username: str = Field(min_length=1, max_length=60, description="Login username")
    email: str = Field(min_length=3, max_length=254, description="User's email address")
    role: str = Field(
        default="subscriber",
        description="WordPress role: administrator, editor, author, contributor, or subscriber",
    )
    first_name: str = Field(default="", max_length=100, description="Optional first name")
    last_name: str = Field(default="", max_length=100, description="Optional last name")
    password: str | None = Field(
        default=None, min_length=8, max_length=200,
        description="Optional login password; a strong random one is generated and returned "
                     "once if omitted (WordPress core requires a password to create a user)",
    )


class UpdateUserParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(gt=0, description="Numeric WordPress user id from list_users")
    role: str | None = Field(default=None, description="New role: administrator, editor, author, contributor, or subscriber")
    email: str | None = Field(default=None, description="New email address")
    first_name: str | None = Field(default=None, description="New first name")
    last_name: str | None = Field(default=None, description="New last name")


class UserCreateResult(sdl.Entity):
    """Result of create_user -- carries the generated password ONCE, if one was generated."""
    role: str = ""
    email: str = ""
    generated_password: str = Field(
        default="", description="Only set when no password was supplied; shown once and never stored")


class UserDeleteResult(sdl.Entity):
    deleted: bool = False
    reassigned_to: str = ""


class DeleteUserParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(gt=0, description="Numeric WordPress user id to permanently delete")
    reassign_to: int | None = Field(
        default=None,
        description="Optional user id to reassign this user's posts to; omit to delete their posts too",
    )


# ─────────── native WordPress navigation menus (WP 5.9+ REST: /wp/v2/menus, /wp/v2/menu-items) ───────────

class Menu(sdl.Entity):
    """One nav_menu taxonomy term -- a named menu, e.g. 'Main Menu'."""
    locations: str = ""  # comma-separated theme location slugs this menu is assigned to
    item_count: int = 0


class MenuItem(sdl.Entity):
    """One item (link/page/category) inside a WordPress navigation menu."""
    menu_id: int = 0
    parent_id: int = 0
    url: str = ""
    menu_order: int = 0
    object_type: str = ""  # 'custom', 'post_type', 'taxonomy'


class ListMenuItemsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    menu_id: int = Field(gt=0, description="Numeric menu id from list_menus")


class CreateMenuItemParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    menu_id: int = Field(gt=0, description="Numeric menu id from list_menus to add this item to")
    title: str = Field(min_length=1, max_length=200, description="Link text shown in the menu")
    url: str = Field(description="Destination URL, e.g. an existing page/post URL or any external https:// link")
    parent_id: int = Field(default=0, description="Parent menu item id for a submenu item; 0 for top-level")
    menu_order: int | None = Field(default=None, description="Optional position within the menu (1-based); appended at the end if omitted")


class UpdateMenuItemParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    menu_item_id: int = Field(gt=0, description="Numeric menu item id from list_menu_items")
    title: str | None = Field(default=None, description="New link text")
    url: str | None = Field(default=None, description="New destination URL")
    parent_id: int | None = Field(default=None, description="New parent menu item id; 0 moves it to top-level")
    menu_order: int | None = Field(default=None, description="New position within the menu")


class DeleteMenuItemParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    menu_item_id: int = Field(gt=0, description="Numeric menu item id to permanently remove from the menu")


class ReorderMenuItemsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    menu_id: int = Field(gt=0, description="Numeric menu id whose items are being reordered")
    ordered_item_ids: list[int] = Field(
        min_length=1, max_length=200,
        description="ALL top-level menu item ids for this menu, in the desired top-to-bottom order")


class MenuItemDeleteResult(sdl.Entity):
    deleted: bool = False


class Plugin(sdl.Entity):
    """One WordPress plugin returned by the read-only WP-CLI inventory."""
    version: str = ""
    update_available: str = ""


class PurgeCacheParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    scope: str = Field(default="all", description="'all' (whole site cache) or 'front' (front page only)")


class CacheActionResult(sdl.Entity):
    """Result of a cache purge — which plugin ran it and what it printed."""
    scope: str = ""
    cache_plugin: str = ""
    output: str = ""


class InstallPluginParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    source: str = Field(
        description="WordPress.org plugin slug or a direct https:// .zip URL "
                    "(e.g. a GitHub release asset — use the Imperal Bridge zip for the companion plugin). "
                    "Never a shell command."
    )
    activate: bool = Field(default=True, description="Activate the plugin immediately after install")


class PluginInstallResult(sdl.Entity):
    """Result of installing a plugin over WP-CLI."""
    source: str = ""
    activated: bool = False
    output: str = ""


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


class PostTerm(sdl.Entity):
    """One native WordPress category or tag term (post taxonomy, not WooCommerce)."""
    taxonomy: str = ""  # 'category' or 'post_tag'
    parent_id: int = 0
    count: int = 0
    slug: str = ""


class TermDeleteResult(sdl.Entity):
    """Confirmation record for a deleted category/tag term."""
    deleted: bool = False


class ProductVariation(sdl.Entity):
    product_id: int = 0
    sku: str = ""
    regular_price: str = ""
    sale_price: str = ""
    stock_status: str = ""
    stock_quantity: int | None = None
    manage_stock: bool = False
    attributes: list[str] = Field(default_factory=list)
    state_token: str = ""


class ProductBulkResult(sdl.Entity):
    import_id: str = ""
    preview: bool = True
    state_token: str = ""
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class VariationBulkResult(ProductBulkResult):
    product_id: int = 0


class CsvImportRun(sdl.Entity):
    import_kind: str = ""
    status: str = "previewed"
    csv_sha256: str = ""
    created_at: str = ""
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
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


class CustomerDeleteResult(sdl.Entity):
    """Confirmation record for a permanently deleted WooCommerce customer."""
    deleted: bool = False
    reassigned_to: str = ""


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
    source: str = ""  # "bridge" (no SSH needed) or "ssh" (WP-CLI fallback)


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


# ── Builder (Elementor / Bricks) point editing ───────────────────────────────
#
# A JSON value as WordPress/PHP would send or accept it. Builder settings are
# sometimes a plain string ("My Title"), sometimes a structured value
# ({"unit": "px", "size": 20}), so the field cannot be a plain str — but it
# must still be a value pydantic can validate and turn into a clean JSON
# schema, so this is an explicit union rather than typing.Any.
JsonValue = dict | list | str | int | float | bool | None


class GetBuilderContentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int | None = Field(default=None, description="Numeric id of the post or page. Give this OR slug.")
    slug: str | None = Field(default=None, description="Slug of the post or page, e.g. 'home'. Used when post_id is not given.")
    post_type: str | None = Field(default=None, description="Optional post type ('post', 'page', or a custom type) to disambiguate a slug used by several items.")
    builder: str | None = Field(default=None, description="Optional: 'elementor' or 'bricks', to read only that builder when both are active on the item.")


class UpdateBuilderFieldParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int | None = Field(default=None, description="Numeric id of the post or page. Give this OR slug.")
    slug: str | None = Field(default=None, description="Slug of the post or page. Used when post_id is not given.")
    post_type: str | None = Field(default=None, description="Optional post type to disambiguate a slug used by several items.")
    element_id: str = Field(description="Builder-native id of the exact element to edit — from a previous get_builder_content call")
    field: str = Field(description="Name of the single settings field to change on that element, e.g. 'title' or '_typography'")
    value: JsonValue = Field(description="New value for the field — a plain string/number for simple fields, or an object for structured ones like {'unit': 'px', 'size': 20}")
    state_token: str = Field(description="Exact state_token from a previous get_builder_content call for this item/builder/zone — the write is refused if the page changed since")
    builder: str | None = Field(default=None, description="'elementor' or 'bricks' — required only when both are active on the same item")
    zone: str | None = Field(default=None, description="Bricks only: 'header', 'content', or 'footer' — which template area the element lives in")


class BuilderElement(BaseModel):
    """One flattened builder element row: a widget, section, column or container.

    Nesting is expressed by parent_id (this row's parent element_id), not by
    physical structure — both Elementor's tree and Bricks' flat array are
    flattened into this same shape so a caller doesn't need two mental models.
    """
    element_id: str = ""
    parent_id: str | None = None
    el_type: str = ""
    widget_type: str = ""
    settings: dict = Field(default_factory=dict)


class BuilderContent(sdl.Entity):
    """One builder's (or one Bricks zone's) element tree for a single post.

    state_token is required to call update_builder_field against any element
    in this exact tree — copy it from here, do not invent it.
    """
    post_id: int = 0
    slug: str = ""
    post_type: str = ""
    link: str = ""
    builder: str = ""
    zone: str = ""
    state_token: str = ""
    element_count: int = 0
    elements: list[BuilderElement] = Field(default_factory=list)


class BuilderFieldUpdateResult(sdl.Entity):
    post_id: int = 0
    builder: str = ""
    zone: str = ""
    element_id: str = ""
    field: str = ""
    state_token: str = ""


class BuilderSupport(sdl.Entity):
    bridge_version: str = ""
    elementor_active: bool = False
    elementor_version: str = ""
    bricks_active: bool = False
    bricks_version: str = ""


class BuilderScanItem(sdl.Entity):
    """One post/page/template found by the /builder/scan diagnostic to carry
    non-empty Elementor or Bricks meta — including custom post types like
    bricks_template that list_pages/list_posts never surface, since they are
    not registered for the normal REST posts endpoints."""
    post_id: int = 0
    post_type: str = ""
    status: str = ""
    builders: list[str] = Field(default_factory=list)
    meta_keys: list[str] = Field(default_factory=list)


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
    rich_snippet: str = ""
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


# ─────────── link extraction (internal/external + anchor text) ───────────

class ExtractLinksParams(BaseModel):
    content_html: str | None = Field(
        default=None,
        description="The article's HTML content to scan directly (e.g. straight from "
                    "Article Writer's export_article_text before the post even exists). "
                    "Give this OR post_id.")
    site_id: str | None = Field(
        default=None,
        description="Site id from a previous list_sites call — required with post_id, "
                    "optional with content_html (used only to tell internal vs external apart)")
    post_id: int | None = Field(
        default=None, description="Numeric id of an existing post/page to read live from the site. Give this OR content_html.")
    post_type: str | None = Field(
        default=None, description="REST base of the post_id target, e.g. 'posts' or 'pages'. Defaults to 'posts'.")


class LinkInfo(sdl.Entity):
    """One <a href> found in an article's content."""
    href: str = ""
    anchor_text: str = ""
    link_type: str = ""  # internal | external | anchor | other
    weak_anchor: bool = False
    rel: str = ""
    missing_rel_policy: bool = False


class LinkReport(sdl.Entity):
    """Full link audit for one article's content."""
    total_links: int = 0
    internal_count: int = 0
    external_count: int = 0
    weak_anchor_count: int = 0
    links: list[LinkInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ─────────── post-publish sitemap inclusion check ───────────

class CheckSitemapParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    url: str = Field(description="The published post/page URL to look for in the site's XML sitemap")


class SitemapCheckResult(sdl.Entity):
    """Whether one published URL was found in the site's XML sitemap."""
    url: str = ""
    found: bool = False
    sitemap_index_url: str = ""
    checked_sitemap_url: str = ""
    sitemaps_checked: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ─────────── post/page publishing ───────────

class FaqItemInput(BaseModel):
    """One question/answer pair inside a 'faq' block."""
    question: str = Field(min_length=1, description="The FAQ question, exactly as it should be shown and marked up")
    answer: str = Field(min_length=1, description="The plain-text answer (no HTML needed — it is escaped and wrapped automatically)")


class PostBlockInput(BaseModel):
    """One content block, already decided by the caller — no document parsing here.

    type == "heading" renders <h{level}>; type == "image" renders a Gutenberg
    image block from a media library attachment (id + url, both from a prior
    upload_media call); type == "faq" renders a visible Q&A list PLUS a
    FAQPage JSON-LD <script> block (schema.org) covering every item in
    faq_items -- this works on any WordPress site regardless of which SEO
    plugin is installed, since it is standard schema.org markup rather than
    a plugin-proprietary block; anything else renders a paragraph.
    """
    type: str = Field(default="paragraph", description="'paragraph', 'heading', 'image', or 'faq'")
    text: str = Field(default="", description="Block text (paragraph/heading); alt text for 'image'; optional intro text for 'faq'")
    level: int = Field(default=2, ge=1, le=6, description="Heading level, used only when type is 'heading'")
    media_id: int | None = Field(default=None, description="Attachment id from upload_media, used only when type is 'image'")
    media_url: str | None = Field(default=None, description="Attachment URL from upload_media, used only when type is 'image'")
    image_role: str | None = Field(
        default=None,
        description="Used only when type is 'image', as an ALTERNATIVE to media_id/media_url: a role "
                    "name (e.g. 'inline_1') matching one entry in this call's external_images -- lets "
                    "you place a Media Hub package asset inline without a separate upload_media call "
                    "and without knowing its attachment id in advance.")
    caption: str | None = Field(default=None, description="Optional caption, used only when type is 'image'")
    faq_items: list[FaqItemInput] = Field(default_factory=list, description="Question/answer pairs, used only when type is 'faq' -- rendered as visible content AND FAQPage JSON-LD schema")


class ExternalImageInput(BaseModel):
    """One not-yet-uploaded external image, keyed by role -- the exact shape
    a Media Hub `get_media_package`/`generate_media_package` asset already
    has (role, image_url, alt_text, caption, filename). Passing these on create_post/
    update_post sideloads each one into this site's media library and wires
    it up automatically: role == "featured" sets featured_media_id, any
    other role is resolved against a block whose image_role matches. This is
    the one-call bridge between an image-generation package and a published
    post -- no manual upload_media + attachment-id bookkeeping needed.
    """
    role: str = Field(description="'featured' or an inline role like 'inline_1' -- must match either "
                                   "this call's featured slot or a block's image_role")
    source_url: str = Field(description="Public https:// URL of the image, e.g. a Media Hub asset's image_url")
    alt_text: str = Field(default="", description="Alt text for the new media library attachment")
    caption: str = Field(default="", description="Optional caption for the new media library attachment")
    filename: str = Field(
        default="", description="SEO/AEO-optimized base file name (no extension) for the saved attachment, "
                     "e.g. a Media Hub asset's own `filename` field -- pass it through so the on-site file "
                     "name is never the image-generation provider's raw opaque id.")


class CreatePostParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    title: str = Field(min_length=1, max_length=300, description="Post/page title")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")
    status: str = Field(default="draft", description="Initial status: draft, publish, pending, private, or future")
    slug: str | None = Field(default=None, description="URL slug -- REQUIRED when post_type='post': a clean, human-readable slug for the article. Optional for pages/custom types, where WordPress derives one from the title if omitted")
    blocks: list[PostBlockInput] = Field(
        default_factory=list,
        description="Content as an ordered list of {type, text, level} blocks, rendered into Gutenberg block markup")
    body_markdown: str | None = Field(
        default=None,
        description="ALTERNATIVE to blocks: the full article as Markdown (e.g. straight from Article "
                    "Writer's read_full_article/export_article_text -- '# Title', '## Heading', "
                    "blank-line-separated paragraphs, '- ' bullets, inline [anchor text](https://url) "
                    "links). Converted into the same {type, text, level} blocks automatically -- this is "
                    "the safe path for internal/external/CTA links written as markdown in the source "
                    "article: it never requires manually retyping each line into blocks, which is what "
                    "previously let [anchor](url) syntax get silently flattened into plain 'anchor (url)' "
                    "text on the live page. Ignored if blocks is also given.")
    excerpt: str | None = Field(default=None, description="Excerpt -- REQUIRED when post_type='post': a short standalone summary Rank Math and social shares fall back to")
    category: str | None = Field(default=None, description="Category name -- REQUIRED when post_type='post'. Resolved to an existing term by name; if none matches, a new category with this name is created automatically so the post is never left uncategorised")
    tags: list[str] = Field(default_factory=list, description="Optional tag names (posts only); resolved to existing terms, never created — names not found are reported back, not silently dropped")
    featured_media_id: int | None = Field(default=None, description="Attachment id from a prior upload_media call -- REQUIRED when post_type='post' UNLESS external_images includes a 'featured' role entry: every article needs a featured image, set in the same call")
    external_images: list[ExternalImageInput] = Field(
        default_factory=list,
        description="Images not yet in this site's media library, e.g. straight from a Media Hub "
                    "package's get_media_package/generate_media_package output (role, image_url as "
                    "source_url, alt_text, caption). Each one is sideloaded into the media library in "
                    "this same call: role=='featured' becomes the post's featured image (no need to "
                    "also pass featured_media_id), any other role is matched against a block whose "
                    "image_role equals that role. This is the one-call path from 'images exist as a "
                    "generated package' to 'images are live in the published post' -- no manual "
                    "per-image upload_media + attachment-id bookkeeping.")
    date: str | None = Field(default=None, description="Optional publish/schedule date as YYYY-MM-DD or full ISO 8601; required when status='future'")
    lang: str | None = Field(default=None, description="Optional Polylang language code, e.g. 'en', 'ro' — requires Polylang on the site")
    meta_title: str | None = Field(default=None, description="Rank Math SEO title -- REQUIRED when post_type='post'")
    meta_description: str | None = Field(default=None, description="Optional Rank Math SEO meta description, set in the same call")
    focus_keyword: str | None = Field(default=None, description="Optional Rank Math focus keyword, set in the same call")
    canonical_url: str | None = Field(default=None, description="Optional Rank Math canonical URL, set in the same call — use when this article duplicates or supersedes another URL")


class UpdatePostParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric id of the post or page to update")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug — must match the item being updated")
    title: str | None = Field(default=None, min_length=1, max_length=300, description="New title; omit to keep it")
    status: str | None = Field(default=None, description="New status: draft, publish, pending, private, or future")
    slug: str | None = Field(default=None, description="New URL slug; omit to keep it")
    blocks: list[PostBlockInput] | None = Field(
        default=None,
        description="Replace the content with these ordered {type, text, level} blocks; omit to keep existing content")
    body_markdown: str | None = Field(
        default=None,
        description="ALTERNATIVE to blocks: replace the content with this full article Markdown "
                    "(same shape as create_post's body_markdown -- headings, paragraphs, bullets, "
                    "inline [anchor text](https://url) links), converted into blocks automatically. "
                    "Ignored if blocks is also given.")
    excerpt: str | None = Field(default=None, description="New excerpt; omit to keep it")
    category: str | None = Field(default=None, description="New category name (posts only); resolved to an existing term, never created")
    tags: list[str] | None = Field(default=None, description="Replace tag names (posts only); resolved to existing terms, never created; omit to keep existing tags")
    featured_media_id: int | None = Field(default=None, description="Attachment id from a prior upload_media call, set as the post's featured image")
    external_images: list[ExternalImageInput] = Field(
        default_factory=list,
        description="Images not yet in this site's media library, e.g. straight from a Media Hub "
                    "package's get_media_package output (role, image_url as source_url, alt_text, "
                    "caption). Sideloaded in this same call: role=='featured' becomes the post's "
                    "featured image, any other role is matched against a block (in the new blocks, "
                    "if provided) whose image_role equals that role.")
    date: str | None = Field(default=None, description="New publish/schedule date as YYYY-MM-DD or full ISO 8601")
    meta_title: str | None = Field(default=None, description="New Rank Math SEO title, set in the same call; omit to leave unchanged")
    meta_description: str | None = Field(default=None, description="New Rank Math meta description, set in the same call; omit to leave unchanged")
    focus_keyword: str | None = Field(default=None, description="New Rank Math focus keyword, set in the same call; omit to leave unchanged")
    canonical_url: str | None = Field(default=None, description="New Rank Math canonical URL, set in the same call; omit to leave unchanged")


class PostResult(sdl.Entity):
    """Outcome of create_post/update_post: the WordPress post/page that was written."""
    link: str = ""
    post_type: str = "post"
    slug: str = ""
    date: str | None = None
    category_resolved: bool = True
    tags_not_found: list[str] = Field(default_factory=list)
    featured_media_set: bool = False


class DeletePostParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id from list_posts/list_pages")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")
    force: bool = Field(
        default=False,
        description="False (default) moves it to Trash, recoverable in WordPress. "
                    "True permanently deletes it, bypassing Trash — cannot be undone.",
    )


class PostDeleteResult(sdl.Entity):
    deleted: bool = False
    trashed: bool = False


class DuplicatePostParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id to duplicate, from list_posts/list_pages")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")
    title_suffix: str = Field(default=" (Copy)", description="Text appended to the duplicated title")


class BulkUpdatePostStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_ids: list[int] = Field(min_length=1, max_length=50, description="Explicit post/page ids; 1-50, never inferred")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug — all ids must share this type")
    status: str = Field(description="New status for every listed post: publish, draft, pending, private, or trash")


class BulkPostStatusResult(sdl.Entity):
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class GetPostRevisionsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id from list_posts/list_pages")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum revisions to return, newest first")


class Revision(sdl.Entity):
    """One stored WordPress revision of a post/page."""
    post_id: int = 0
    author: str = ""
    date: str | None = None
    excerpt_preview: str = ""


class RestoreRevisionParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id the revision belongs to")
    revision_id: int = Field(gt=0, description="Revision id from get_post_revisions to restore")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")


class SetPostPasswordParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id from list_posts/list_pages")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")
    password: str = Field(default="", max_length=255, description="Password required to view the post; empty string removes password protection")


# ─────────── WooCommerce product reviews (/wc/v3/products/reviews) ───────────

class ProductReview(sdl.Entity):
    """One WooCommerce product review -- a comment on the 'product' content type."""
    product_id: int = 0
    reviewer: str = ""
    reviewer_email: str = ""
    rating: int = 0
    status: str = ""
    snippet: str = ""
    date: str = ""


class ListProductReviewsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    product_id: int | None = Field(default=None, description="Optional product id to filter reviews for one product only")
    status: str = Field(default="hold", description="Review status: 'hold' (pending moderation), 'approved', 'spam', or 'all'")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class SetProductReviewStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    review_id: int = Field(gt=0, description="Numeric review id from list_product_reviews")
    status: str = Field(description="New status: 'approved' (publish), 'hold' (unapprove/pending), 'spam', or 'trash'")


class ReplyToProductReviewParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    review_id: int = Field(gt=0, description="Numeric review id being replied to, from list_product_reviews")
    content: str = Field(min_length=1, max_length=5000, description="Reply text, posted as the connected WordPress user")


# ─────────── native plugin/theme/settings management (/wp/v2/plugins, /wp/v2/themes, /wp/v2/settings — WP 5.5+, no SSH) ───────────

class NativePlugin(sdl.Entity):
    """One plugin as reported by the native /wp/v2/plugins REST route (requires WP 5.5+)."""
    plugin: str = ""  # identifier used for activate/deactivate, e.g. 'hello-dolly/hello'
    version: str = ""
    status: str = ""  # 'active' or 'inactive'
    description: str = ""


class SetPluginStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    plugin: str = Field(
        min_length=1, description="Plugin identifier from list_native_plugins, e.g. 'hello-dolly/hello'")


class Theme(sdl.Entity):
    """One installed theme as reported by the native /wp/v2/themes REST route."""
    stylesheet: str = ""
    version: str = ""
    status: str = ""  # 'active' or 'inactive'
    is_block_theme: bool = False


class SiteSettings(sdl.Entity):
    """Native WordPress site settings (/wp/v2/settings)."""
    description: str = ""
    url: str = ""
    timezone_string: str = ""
    date_format: str = ""
    time_format: str = ""
    start_of_week: int = 0
    language: str = ""


# ─────────── Rank Math redirects (Bridge SECTION 5: /imperal/v1/redirects) ───────────

class RedirectSource(BaseModel):
    pattern: str = Field(description="URL path or regex pattern to match, e.g. '/old-page/'")
    comparison: str = Field(default="exact", description="'exact', 'contains', 'start', 'end', or 'regex'")


class Redirect(sdl.Entity):
    """One Rank Math URL redirection."""
    sources: list[RedirectSource] = Field(default_factory=list)
    url_to: str = ""
    header_code: int = 301
    hits: int = 0
    status: str = ""  # 'active', 'inactive', 'trashed'
    created: str = ""
    updated: str = ""


class ListRedirectsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    status: str = Field(default="active", description="'active', 'inactive', 'trashed', or 'all'")


class CreateRedirectParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    source_pattern: str = Field(min_length=1, description="URL path to redirect FROM, e.g. '/old-page/'")
    source_comparison: str = Field(
        default="exact", description="'exact', 'contains', 'start', 'end', or 'regex'")
    url_to: str = Field(min_length=1, description="Destination URL to redirect TO")
    header_code: int = Field(default=301, description="HTTP redirect status code: 301 (permanent), 302 (temporary), 307, or 410 (gone)")


class DeleteRedirectParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    redirect_id: int = Field(gt=0, description="Numeric redirect id from list_redirects")


class SetRedirectStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    redirect_id: int = Field(gt=0, description="Numeric redirect id from list_redirects")
    status: str = Field(description="New status: 'active', 'inactive', or 'trashed'")


class RedirectDeleteResult(sdl.Entity):
    deleted: bool = False


class UpdateSiteSettingsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    title: str | None = Field(default=None, description="New site title")
    description: str | None = Field(default=None, description="New site tagline/description")
    timezone_string: str | None = Field(default=None, description="New timezone, e.g. 'Europe/Chisinau'")
    date_format: str | None = Field(default=None, description="New PHP date() format string, e.g. 'F j, Y'")
    time_format: str | None = Field(default=None, description="New PHP date() time format string, e.g. 'g:i a'")
    start_of_week: int | None = Field(default=None, ge=0, le=6, description="New first day of the week: 0=Sunday .. 6=Saturday")


# ─────────── media upload (sideload via Imperal Bridge) ───────────

class UploadMediaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    source_url: str = Field(description="Public https:// URL of the image to add to the media library")
    post_id: int | None = Field(default=None, description="Optional post/page id to attach the uploaded image to")
    alt_text: str | None = Field(default=None, description="Optional alt text to set on the new attachment")
    caption: str | None = Field(default=None, description="Optional caption to set on the new attachment")
    filename: str | None = Field(
        default=None, description="Optional SEO/AEO-optimized base file name (no extension, e.g. "
                       "'heat-recovery-ventilator-featured') to save this attachment under on the site. "
                       "Omitting it falls back to deriving a name from source_url itself, which is often "
                       "an opaque provider-generated id -- always pass this when the source is a Media "
                       "Hub generated image (its `filename` field is already SEO/AEO-optimized).")
    set_featured: bool = Field(default=False, description="Set this image as the featured image of post_id (requires post_id)")


class MediaUploadResult(sdl.Entity):
    """Outcome of upload_media: the new media library attachment."""
    url: str = ""
    width: int | None = None
    height: int | None = None
    attached_to: int | None = None
    featured_set: bool = False


class MediaSupport(sdl.Entity):
    """Outcome of check_media_support: is the Media Bridge present, can this user upload."""
    bridge_version: str = ""
    can_upload: bool = False
