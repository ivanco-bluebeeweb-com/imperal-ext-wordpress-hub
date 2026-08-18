from pydantic import BaseModel, Field
from imperal_sdk import sdl

VNEXT = "requires companion plugin (vNext)"


class ConnectSiteParams(BaseModel):
    url: str = Field(description="Full https:// URL of the WordPress site, e.g. https://example.com")
    username: str = Field(description="WordPress username that created the Application Password")
    app_password: str = Field(description="WordPress Application Password (from Users → Profile → Application Passwords)")


class SiteIdParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class CreateNetworkSiteParams(BaseModel):
    site_id: str = Field(description="Multisite network id from a previous list_network_sites/list_sites call — never invent it")
    domain: str = Field(min_length=1, max_length=253, description="Domain for the new network site, e.g. shop.example.com")
    path: str = Field(min_length=1, max_length=255, description="Path for the new network site, e.g. /shop/")
    title: str = Field(min_length=1, max_length=200, description="Human-readable title for the new network site")
    owner_email: str = Field(min_length=3, max_length=254, description="Email of an existing network user who will own the new site")


class NetworkSite(sdl.Entity):
    """One WordPress Multisite subsite returned by WordPress core."""
    blog_id: int = 0
    domain: str = ""
    path: str = ""
    site_url: str = ""
    public: bool = False
    archived: bool = False
    spam: bool = False
    deleted: bool = False
    registered: str = ""


class NetworkPlugin(sdl.Entity):
    """One plugin and whether it is active across a WordPress Multisite network."""
    plugin_file: str = ""
    name: str = ""
    version: str = ""
    network_active: bool = False


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


class BulkOrderStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit WooCommerce order ids; 1-100, never inferred")
    status: str = Field(description="Routine status for every listed order: pending, on-hold, processing, or completed")


class ApplyBulkOrderStatusParams(BulkOrderStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any order changed")


class BulkOrderStatusResult(sdl.Entity):
    id: str = ""
    title: str = "Order status batch"
    kind: str = "wc_order_status_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


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


class BulkCustomerUpdateParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    customer_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit WooCommerce customer ids; 1-100, never inferred")
    first_name: str | None = Field(default=None, max_length=100, description="Same first name for every customer; empty string clears it")
    last_name: str | None = Field(default=None, max_length=100, description="Same last name for every customer; empty string clears it")


class ApplyBulkCustomerUpdateParams(BulkCustomerUpdateParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any customer changed")


class BulkCustomerUpdateResult(sdl.Entity):
    id: str = ""
    title: str = "Customer batch"
    kind: str = "wc_customer_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


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


class BulkCouponUpdateParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    coupon_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit WooCommerce coupon ids; 1-100, never inferred")
    discount_type: str | None = Field(default=None, description="Same discount type for every coupon: percent, fixed_cart, or fixed_product")
    amount: str | None = Field(default=None, description="Same non-negative discount amount for every coupon")
    description: str | None = Field(default=None, max_length=1000, description="Same internal description; empty string clears it")
    date_expires: str | None = Field(default=None, description="Same expiry date as YYYY-MM-DD; empty string clears it")
    usage_limit: int | None = Field(default=None, ge=1, description="Same total usage limit")
    usage_limit_per_user: int | None = Field(default=None, ge=1, description="Same usage limit per customer")
    minimum_amount: str | None = Field(default=None, description="Same minimum basket amount; empty string clears it")
    maximum_amount: str | None = Field(default=None, description="Same maximum basket amount; empty string clears it")
    individual_use: bool | None = Field(default=None, description="Set same combination restriction")
    free_shipping: bool | None = Field(default=None, description="Set same free-shipping setting")
    exclude_sale_items: bool | None = Field(default=None, description="Set same sale-item exclusion")


class ApplyBulkCouponUpdateParams(BulkCouponUpdateParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any coupon changed")


class BulkCouponUpdateResult(sdl.Entity):
    id: str = ""
    title: str = "Coupon batch"
    kind: str = "wc_coupon_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


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


class BulkMediaAltParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    items: list[MediaAltItem] = Field(min_length=1, max_length=100, description="Explicit media id and alt-text assignments; 1-100, never inferred")


class ApplyBulkMediaAltParams(BulkMediaAltParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any media alt changed")


class BulkMediaAltResult(sdl.Entity):
    id: str = ""
    title: str = "Media alt-text batch"
    kind: str = "wp_media_alt_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class SetSingleMediaAltParams(BaseModel):
    """Single-item convenience wrapper around update_media_alt — the panel UI can only submit a
    flat form per row, not a nested items[] list, so this feeds one {media_id, alt_text} through."""
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    media_id: int = Field(description="WordPress media library attachment id, from list_media")
    alt_text: str = Field(min_length=1, description="Alt text to store on this attachment — always overwrites")


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


class BulkCommentStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    comment_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit comment ids; 1-100, never inferred")
    status: str = Field(description="New status for every listed comment: approved, hold, spam, or trash")


class ApplyBulkCommentStatusParams(BulkCommentStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any comment changed")


class BulkCommentStatusResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class ReplyToCommentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    comment_id: int = Field(gt=0, description="Numeric WordPress comment id being replied to, from list_comments")
    content: str = Field(min_length=1, max_length=5000, description="Reply text, posted as the connected WordPress user")


class EditCommentContentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    comment_id: int = Field(gt=0, description="Numeric WordPress comment id to edit, from list_comments")
    content: str = Field(min_length=1, max_length=5000, description="Replacement text for the comment's content — overwrites the existing comment entirely")


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
    og_image_url: str | None = Field(default=None, description="HTTPS URL of the page's Rank Math Facebook/Open Graph image. Omit to leave unchanged; empty string clears the page-specific override so Rank Math can fall back to its global/default image.")


class BulkSeoMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit post/page/CPT ids; 1-100, never inferred")
    post_type: str | None = Field(default=None, description="Optional common post type to disambiguate all ids")
    meta_title: str | None = Field(default=None, description="Same Rank Math SEO title to set on every target; omit to leave unchanged")
    meta_description: str | None = Field(default=None, description="Same Rank Math description to set on every target; omit to leave unchanged")
    canonical_url: str | None = Field(default=None, description="Same canonical URL to set on every target; omit to leave unchanged")
    robots: list[str] | None = Field(default=None, description="Same allowed robots directives to set on every target; omit to leave unchanged")
    focus_keyword: str | None = Field(default=None, description="Same focus keyword to set on every target; omit to leave unchanged")
    rich_snippet: str | None = Field(default=None, description="Same Rank Math schema type to set on every target; omit to leave unchanged")


class ApplyBulkSeoMetaParams(BulkSeoMetaParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any SEO target changed")


class BulkSeoMetaResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class BulkTermSeoMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit taxonomy term ids; 1-100, never inferred")
    taxonomy: str | None = Field(default=None, description="Optional common taxonomy to disambiguate all term ids")
    meta_title: str | None = Field(default=None, description="Same Rank Math SEO title to set on every target term; omit to leave unchanged")
    meta_description: str | None = Field(default=None, description="Same Rank Math description to set on every target term; omit to leave unchanged")
    canonical_url: str | None = Field(default=None, description="Same canonical URL to set on every target term; omit to leave unchanged")
    robots: list[str] | None = Field(default=None, description="Same allowed robots directives to set on every target term; omit to leave unchanged")
    focus_keyword: str | None = Field(default=None, description="Same focus keyword to set on every target term; omit to leave unchanged")
    rich_snippet: str | None = Field(default=None, description="Same Rank Math schema type to set on every target term; omit to leave unchanged")


class ApplyBulkTermSeoMetaParams(BulkTermSeoMetaParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any term SEO target changed")


class BulkTermSeoMetaResult(sdl.Entity):
    id: str = ""
    title: str = "Term SEO batch"
    kind: str = "wp_bulk_term_seo"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


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


class GetPostContentParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id from list_posts/list_pages")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug")


class PostContent(sdl.Entity):
    """One post/page's raw rendered content, for auditing (e.g. checking for stray headings or the wrong Polylang language) without needing Bridge/SSH."""
    post_id: int = 0
    slug: str = ""
    content_html: str = ""
    excerpt_html: str = ""
    lang: str = ""


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


class BulkUserRoleParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit WordPress user ids; 1-100, never inferred")
    role: str = Field(description="New role for every listed user: administrator, editor, author, contributor, or subscriber")


class ApplyBulkUserRoleParams(BulkUserRoleParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any user changed")


class BulkUserRoleResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class BulkUserNameParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit WordPress user ids; 1-100, never inferred")
    first_name: str | None = Field(default=None, description="Same first name to set on every target user; omit to leave unchanged")
    last_name: str | None = Field(default=None, description="Same last name to set on every target user; omit to leave unchanged")


class ApplyBulkUserNameParams(BulkUserNameParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any user changed")


class BulkUserNameResult(sdl.Entity):
    id: str = ""
    title: str = "Bulk user name batch"
    kind: str = "wp_bulk_user_name"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class UserCreateResult(sdl.Entity):
    """Result of create_user -- carries the generated password ONCE, if one was generated."""
    role: str = ""
    email: str = ""
    generated_password: str = Field(
        default="", description="Only set when no password was supplied; shown once and never stored")


class PasswordResetParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(gt=0, description="Numeric WordPress user id from list_users")


class PasswordResetResult(sdl.Entity):
    email_sent: bool = False


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


class ApplyBulkMenuOrderParams(ReorderMenuItemsParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; no item is reordered if menu items changed")


class BulkMenuOrderResult(sdl.Entity):
    id: str = ""
    title: str = "Menu order batch"
    kind: str = "wp_menu_order_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


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


class UpdatePluginParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    slug: str = Field(
        min_length=1, max_length=200,
        description="Plugin folder/file slug from list_plugins, e.g. 'akismet' or 'akismet/akismet.php'",
    )


class PluginUpdateResult(sdl.Entity):
    """Result of updating one plugin over WP-CLI."""
    slug: str = ""
    output: str = ""


class ImperalBridgeUpdateResult(sdl.Entity):
    """Result of updating the companion Bridge from its fixed release ZIP."""
    version: str = ""
    updated: bool = False
    output: str = ""


class UpdateImperalBridgeParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class UpdateCoreParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class CoreUpdateResult(sdl.Entity):
    """Result of updating WordPress core over WP-CLI."""
    output: str = ""


class RunWpCronParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class WpCronRunResult(sdl.Entity):
    """Result of forcing due cron events to run over WP-CLI."""
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


class ResendOrderEmailParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    order_id: int = Field(gt=0, description="Numeric WooCommerce order id")
    template_id: str = Field(
        default="",
        description=(
            "Which email template to send, e.g. 'customer_invoice', 'customer_completed_order', "
            "'customer_on_hold_order'. Leave empty to send the generic order-details email "
            "(same as 'customer_invoice')."
        ),
    )
    email: str = Field(
        default="", description="Send to this address instead of the order's own billing email")


class OrderEmailResult(sdl.Entity):
    order_id: int = 0
    template_id: str = ""
    sent_to: str = ""
    message: str = ""


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
    zone: str | None = Field(
        default=None,
        description=(
            "Optional: 'header', 'content', or 'footer', to read only that one Bricks zone "
            "(ignored for Elementor, which has no zones). Bricks pages always have 3 zones, so "
            "without this the result has 3 rows and display clients may compact each one down "
            "to id/title/kind, hiding fields like `heading_outline`/`elements`. Narrowing to one "
            "zone returns exactly one row, which is never compacted."
        ),
    )


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


class CreateBricksHeadingParams(BaseModel):
    """Safely append one semantic heading to an existing Bricks zone.

    This deliberately does not accept arbitrary Bricks JSON. It exists for
    repairs such as a confirmed missing H1 in a category/archive template,
    while retaining an explicit parent, insertion position, and optimistic
    concurrency guard.
    """
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int | None = Field(default=None, description="Numeric page/template id; give this or slug")
    slug: str | None = Field(default=None, description="Slug of the target; give this or post_id")
    post_type: str | None = Field(default=None, description="Optional post type to disambiguate a slug")
    zone: str = Field(default="content", description="Bricks zone: header, content, or footer")
    parent_id: str | None = Field(default=None, description="Existing Bricks parent element id, or omit only to create a top-level heading")
    position: int = Field(default=0, ge=0, description="Zero-based position among the selected parent's direct children; 0 inserts first")
    tag: str = Field(default="h1", pattern="^h[1-6]$", description="Semantic HTML heading tag, h1 through h6")
    text: str = Field(min_length=1, max_length=500, description="Plain heading text; HTML is stripped by the Bridge")
    state_token: str = Field(min_length=1, description="Exact token from a preceding get_builder_element call for this Bricks zone")


class BuilderHeadingCreateResult(sdl.Entity):
    post_id: int = 0
    builder: str = "bricks"
    zone: str = ""
    element_id: str = ""
    parent_id: str | None = None
    position: int = 0
    tag: str = ""
    text: str = ""
    state_token: str = ""


class BuilderFieldAssignment(BaseModel):
    element_id: str = Field(min_length=1, description="Builder-native element id from get_builder_content")
    field: str = Field(min_length=1, description="Exact existing builder settings field to replace")
    value: JsonValue = Field(description="Replacement value for this one field")


class BulkBuilderFieldParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int | None = Field(default=None, description="Numeric post/page id; give this or slug")
    slug: str | None = Field(default=None, description="Slug of the target item; give this or post_id")
    post_type: str | None = Field(default=None, description="Optional post type when using slug")
    builder: str = Field(description="Exact active builder: elementor or bricks")
    zone: str | None = Field(default=None, description="Bricks only: header, content, or footer")
    changes: list[BuilderFieldAssignment] = Field(min_length=1, max_length=100, description="Explicit element-field assignments; 1-100")


class ApplyBulkBuilderFieldParams(BulkBuilderFieldParams):
    expected_state_token: str = Field(min_length=1, description="Exact state token from preview; no writes begin if document changed")


class BulkBuilderFieldResult(sdl.Entity):
    id: str = ""
    title: str = "Builder field batch"
    kind: str = "wp_builder_field_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[str] = Field(default_factory=list)
    failed_ids: list[str] = Field(default_factory=list)


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
    heading_outline: str = Field(
        default="",
        description=(
            "Plain-text outline of every heading widget/element found in this builder/zone, "
            "one per line as 'h2: Some Title (id=abc123)' in document order — always fully "
            "readable as text (unlike `elements`, which display clients may show as a compact "
            "summary card). Use this to check heading hierarchy (e.g. H1->H3 skips) or confirm "
            "a true absence of any H1 without needing to inspect `elements` directly."
        ),
    )


class BuilderFieldUpdateResult(sdl.Entity):
    post_id: int = 0
    builder: str = ""
    zone: str = ""
    element_id: str = ""
    field: str = ""
    state_token: str = ""


class DetectedBuilder(BaseModel):
    """One additional builder/block-library detected site-wide, beyond the
    Elementor/Bricks fields BuilderSupport already carries. Detection only --
    this bridge cannot read/write element trees for anything listed here."""
    slug: str = ""
    label: str = ""
    active: bool = False
    confidence: str = ""


class BuilderSupport(sdl.Entity):
    bridge_version: str = ""
    elementor_active: bool = False
    elementor_version: str = ""
    bricks_active: bool = False
    bricks_version: str = ""
    detected_builders: list[DetectedBuilder] = Field(default_factory=list)


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
    og_image_url: str = ""
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


class BulkPostStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit post/page ids; 1-100, never inferred")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug — all ids must share this type")
    status: str = Field(description="New status for every listed post: publish, draft, pending, private, or trash")


class ApplyBulkPostStatusParams(BulkPostStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token returned by preview; execution stops before all writes if any post changed")


class BulkUpdatePostStatusParams(ApplyBulkPostStatusParams):
    """Backward-compatible alias for the guarded bulk post-status apply payload."""


class BulkPostCommentStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit post/page ids; 1-100, never inferred")
    post_type: str = Field(default="post", description="'post', 'page', or a custom post type's slug — all ids must share this type")
    comment_status: str = Field(description="New comment status for every listed item: 'open' or 'closed'")


class ApplyBulkPostCommentStatusParams(BulkPostCommentStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any item changed")


class BulkPostCommentStatusResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class BulkPostStatusResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
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


class BulkProductReviewStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    review_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit WooCommerce product review ids; 1-100, never inferred")
    status: str = Field(description="New status for every listed review: approved, hold, spam, or trash")


class ApplyBulkProductReviewStatusParams(BulkProductReviewStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any review changed")


class BulkProductReviewStatusResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


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


class BulkPluginStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    plugins: list[str] = Field(min_length=1, max_length=100, description="Explicit plugin identifiers from list_native_plugins; 1-100, never inferred")
    status: str = Field(description="Status for every listed plugin: active or inactive")


class ApplyBulkPluginStatusParams(BulkPluginStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any plugin changed")


class BulkPluginStatusResult(sdl.Entity):
    id: str = ""
    title: str = "Plugin status batch"
    kind: str = "wp_plugin_batch"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[str] = Field(default_factory=list)
    failed_ids: list[str] = Field(default_factory=list)


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
    site_icon: int = 0


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


class BulkRedirectStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    redirect_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit redirect ids from list_redirects; 1-100, never inferred")
    status: str = Field(description="New status for every target redirect: 'active', 'inactive', or 'trashed'")


class ApplyBulkRedirectStatusParams(BulkRedirectStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any target redirect changed")


class BulkRedirectStatusResult(sdl.Entity):
    id: str = ""
    title: str = "Redirect status batch"
    kind: str = "wp_bulk_redirect_status"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class UpdateSiteSettingsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    title: str | None = Field(default=None, description="New site title")
    description: str | None = Field(default=None, description="New site tagline/description")
    timezone_string: str | None = Field(default=None, description="New timezone, e.g. 'Europe/Chisinau'")
    date_format: str | None = Field(default=None, description="New PHP date() format string, e.g. 'F j, Y'")
    time_format: str | None = Field(default=None, description="New PHP date() time format string, e.g. 'g:i a'")
    start_of_week: int | None = Field(default=None, ge=0, le=6, description="New first day of the week: 0=Sunday .. 6=Saturday")
    site_icon: int | None = Field(default=None, ge=0, description="Media library attachment id for the native WordPress site icon; use 0 to remove it")


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


# ─────────── Rank Math site-wide (SEO score, robots.txt, sitemap status, 404 log) ───────────

class GetSeoScoreParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(gt=0, description="Numeric post/page id from list_posts/list_pages")


class SeoScoreResult(sdl.Entity):
    """Rank Math's own content-analysis SEO score (0-100) for one post."""
    post_id: int = 0
    score: int | None = None  # None means Rank Math has never analyzed this post


class RobotsTxtParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class UpdateRobotsTxtParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    content: str = Field(description="New robots.txt override text — empty string clears the override, "
                          "reverting to WordPress's own default robots.txt")


class RobotsTxt(sdl.Entity):
    """Rank Math's robots.txt override — NOT the raw file on disk."""
    content: str = ""
    is_active: bool = False
    site_is_public: bool = True


class SitemapStatus(sdl.Entity):
    """Whether Rank Math's Sitemap module is active, and its index URL if so."""
    module_active: bool = False
    sitemap_url: str = ""


class List404HitsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=50, ge=1, le=100, description="Max hits to return, newest first")


class Hit404(sdl.Entity):
    """One logged 404 hit from Rank Math's 404 Monitor."""
    uri: str = ""
    accessed: str = ""
    times_accessed: int = 0
    referer: str = ""
    user_agent: str = ""


class Delete404HitParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    hit_id: int = Field(gt=0, description="Numeric 404-log entry id from list_404_hits")


class Hit404DeleteResult(sdl.Entity):
    deleted: bool = False


# ─────────── Rank Math Instant Indexing (IndexNow) — native REST, no Bridge ───────────

_INDEXNOW_FILTERS = {"all", "manual", "auto"}


class SubmitIndexNowUrlsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    urls: list[str] = Field(min_length=1, max_length=10000,
                             description="One or more full https:// URLs on this site to submit "
                             "to IndexNow (Bing, Yandex, and other participating search engines) "
                             "for instant crawling/indexing")


class IndexNowSubmitResult(sdl.Entity):
    """Outcome of submitting URLs to Rank Math's Instant Indexing (IndexNow) API."""
    submitted_count: int = 0
    message: str = ""


class IndexNowLogParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    filter: str = Field(default="all", description="Which submissions to show: 'all', "
                         "'manual' (submitted via this function or the Rank Math admin UI), "
                         "or 'auto' (submitted automatically on publish/update/trash)")


class IndexNowLogEntry(sdl.Entity):
    """One past IndexNow submission from Rank Math's own log (newest first, last 100 kept)."""
    url: str = ""
    status: int = 0
    manual_submission: bool = False
    message: str = ""
    time_formatted: str = ""
    time_human_readable: str = ""


class ClearIndexNowLogParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    filter: str = Field(default="all", description="Which submissions to clear: 'all', 'manual', or 'auto'")


class ClearIndexNowLogResult(sdl.Entity):
    cleared: bool = False


class ResetIndexNowKeyParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class IndexNowKey(sdl.Entity):
    """Rank Math's own IndexNow API key, hosted and served dynamically by the site itself."""
    key: str = ""
    location: str = ""


class LlmsTxtParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


class LlmsTxtSettings(sdl.Entity):
    """Rank Math's llms.txt settings -- which post types/taxonomies are listed in the
    dynamically-served /llms.txt file, how many links per type, and any extra Markdown
    appended to it. Requires the Imperal Bridge plugin (SECTION 8) and Rank Math's own
    llms-txt module active on the site (it is NOT active by default, unlike robots.txt)."""
    module_active: bool = False
    llms_txt_url: str = ""
    post_types: list[str] = Field(default_factory=list)
    taxonomies: list[str] = Field(default_factory=list)
    limit: int = 100
    extra_content: str = ""


class UpdateLlmsTxtParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_types: list[str] | None = Field(
        default=None, description="Post type slugs to list in llms.txt. Omit to leave unchanged.")
    taxonomies: list[str] | None = Field(
        default=None, description="Taxonomy slugs to list in llms.txt. Omit to leave unchanged.")
    limit: int | None = Field(
        default=None, description="Max links per post type/taxonomy. Omit to leave unchanged.")
    extra_content: str | None = Field(
        default=None,
        description="Free-text Markdown appended to the file. Pass an empty string to clear it, "
                    "omit to leave unchanged.")


# ─────────── Generic meta (Bridge SECTION 9: /imperal/v1/postmeta|usermeta|termmeta|option) ───────────

class GetPostMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(description="WordPress post/page/CPT item id")


class PostMetaSet(sdl.Entity):
    """All custom-field meta on one post/page/CPT item, including keys WordPress core's own \
REST API would hide because they were never registered with show_in_rest."""
    post_id: int = 0
    meta: dict = Field(default_factory=dict)


class UpdatePostMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(description="WordPress post/page/CPT item id")
    meta: dict = Field(min_length=1, description="One or more meta key/value pairs to set. "
                        "Values must be plain strings/numbers/booleans/arrays — never a "
                        "serialized PHP object, which is refused for safety.")


class PostMetaUpdateResult(sdl.Entity):
    post_id: int = 0
    updated: list[str] = Field(default_factory=list)


class BulkPostMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit post/page/CPT ids; 1-100, never inferred")
    meta: dict = Field(min_length=1, description="The same plain safe meta key/value pairs to set on every explicit target")


class ApplyBulkPostMetaParams(BulkPostMetaParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any target meta changed")


class BulkPostMetaResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class DeletePostMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_id: int = Field(description="WordPress post/page/CPT item id")
    key: str = Field(min_length=1, description="Meta key to remove")


class PostMetaDeleteResult(sdl.Entity):
    post_id: int = 0
    deleted: str = ""


class GetUserMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(description="WordPress user id")


class UserMetaSet(sdl.Entity):
    """All custom-field meta on one WordPress user account."""
    user_id: int = 0
    meta: dict = Field(default_factory=dict)


class UpdateUserMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(description="WordPress user id")
    meta: dict = Field(min_length=1, description="One or more meta key/value pairs to set. "
                        "Values must be plain strings/numbers/booleans/arrays — never a "
                        "serialized PHP object, which is refused for safety.")


class UserMetaUpdateResult(sdl.Entity):
    user_id: int = 0
    updated: list[str] = Field(default_factory=list)


class DeleteUserMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(description="WordPress user id")
    key: str = Field(min_length=1, description="Meta key to remove")


class UserMetaDeleteResult(sdl.Entity):
    user_id: int = 0
    deleted: str = ""


class GetTermMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(description="Taxonomy term id (category, tag, or custom taxonomy term)")


class TermMetaSet(sdl.Entity):
    """All custom-field meta on one taxonomy term (category, tag, or custom taxonomy)."""
    term_id: int = 0
    meta: dict = Field(default_factory=dict)


class UpdateTermMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(description="Taxonomy term id (category, tag, or custom taxonomy term)")
    meta: dict = Field(min_length=1, description="One or more meta key/value pairs to set. "
                        "Values must be plain strings/numbers/booleans/arrays — never a "
                        "serialized PHP object, which is refused for safety.")


class TermMetaUpdateResult(sdl.Entity):
    term_id: int = 0
    updated: list[str] = Field(default_factory=list)


class BulkTermMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit taxonomy term ids; 1-100, never inferred")
    meta: dict = Field(min_length=1, description="The same plain safe meta key/value pairs to set on every explicit target")


class ApplyBulkTermMetaParams(BulkTermMetaParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any target meta changed")


class BulkTermMetaResult(sdl.Entity):
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class DeleteTermMetaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    term_id: int = Field(description="Taxonomy term id (category, tag, or custom taxonomy term)")
    key: str = Field(min_length=1, description="Meta key to remove")


class TermMetaDeleteResult(sdl.Entity):
    term_id: int = 0
    deleted: str = ""


class GetOptionParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, description="Option name to read — must be on the Bridge's "
                       "hard allowlist (Rank Math's own settings, site title/tagline, and a few "
                       "WooCommerce store-settings names). Never siteurl/home/active_plugins/etc.")


class OptionValue(sdl.Entity):
    """One named row from wp_options — only names on the Bridge's hard allowlist are readable/writable."""
    name: str = ""
    value: str = ""
    exists: bool = False


class UpdateOptionParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, description="Option name to write — must be on the Bridge's "
                       "hard allowlist. Never siteurl/home/active_plugins/etc.")
    value: str = Field(description="New value. Must not be a serialized PHP object — refused for safety.")


class AcfFieldsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_type: str = Field(default="post", description="Post type to list ACF field groups for")


class AcfField(BaseModel):
    key: str = ""
    name: str = ""
    label: str = ""
    type: str = ""


class AcfFieldGroup(BaseModel):
    group_key: str = ""
    group_title: str = ""
    fields: list[AcfField] = Field(default_factory=list)


class AcfFieldsResult(sdl.Entity):
    """Registered Advanced Custom Fields field groups for one post type, if ACF is active on the site."""
    post_type: str = ""
    field_groups: list[AcfFieldGroup] = Field(default_factory=list)


# ─────────── Transients & Object Cache (SSH/WP-CLI) ───────────

class TransientItem(sdl.Entity):
    """One transient row from `wp transient list`."""
    name: str = ""
    value: str = ""
    expiration: str = ""


class DeleteTransientParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    name: str = Field(min_length=1, description="Transient name from list_transients")


class TransientActionResult(sdl.Entity):
    site_id: str = ""
    output: str = ""


class ObjectCacheStatus(sdl.Entity):
    """Whether a persistent object cache (Redis/Memcached/etc.) is active, per `wp cache type`."""
    site_id: str = ""
    cache_type: str = ""


# ─────────── Cron (SSH/WP-CLI, beyond the existing run_wp_cron) ───────────

class CronEventItem(sdl.Entity):
    """One scheduled WP-Cron event from `wp cron event list`."""
    hook: str = ""
    next_run_gmt: str = ""
    next_run_relative: str = ""
    recurrence: str = ""


class CronEventActionParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    hook: str = Field(min_length=1, description="Cron hook name from list_cron_events")


class CronEventActionResult(sdl.Entity):
    site_id: str = ""
    hook: str = ""
    output: str = ""


class CronScheduleItem(sdl.Entity):
    """One registered cron recurrence interval from `wp cron schedule list`."""
    name: str = ""
    display: str = ""
    interval: int = 0


# ─────────── Database Tools (SSH/WP-CLI) ───────────

class DatabaseTableItem(sdl.Entity):
    """One table on the site's own database, from `wp db size --tables`."""
    name: str = ""
    size: str = ""


class SearchReplaceParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    old: str = Field(min_length=1, description="Text to search for (e.g. an old domain)")
    new: str = Field(min_length=1, description="Replacement text (e.g. the new domain)")
    tables: list[str] | None = Field(
        default=None,
        description="Explicit table names/wildcards from list_database_tables to restrict to; omit for every registered table")


class ApplySearchReplaceParams(SearchReplaceParams):
    expected_replacements: int = Field(
        ge=0, description="Exact replacement count returned by the dry-run preview; execution is refused if it does not match a fresh dry-run")


class SearchReplaceResult(sdl.Entity):
    site_id: str = ""
    dry_run: bool = True
    replacements: int = 0


class DatabaseMaintenanceResult(sdl.Entity):
    """Result of optimize_database_tables / check_database_repair."""
    site_id: str = ""
    output: str = ""


class CheckDatabaseParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    repair: bool = Field(default=False, description="If true, repair any damaged tables found (wp db repair); if false (default), only check for corruption (wp db check)")


class ExportDatabaseDumpParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    tables: list[str] | None = Field(
        default=None,
        description="Explicit table names/wildcards from list_database_tables; omit to export every registered table (capped at ~2MB of SQL text — scope down if the export is refused as too large)")


class DatabaseDumpResult(sdl.Entity):
    site_id: str = ""
    sql: str = ""
    size_bytes: int = 0


class CountPostTypeRowsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    post_type: str = Field(min_length=1, description="Post type slug from list_custom_posts / the site's own /wp/v2/types, e.g. post, page, product")


class PostTypeCountResult(sdl.Entity):
    site_id: str = ""
    post_type: str = ""
    count: int = 0


class OrphanedPostmetaResult(sdl.Entity):
    """Count of wp_postmeta rows whose post no longer exists — a common DB-hygiene diagnostic."""
    site_id: str = ""
    orphaned_rows: int = 0


class CheckBackupRestorabilityParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    tables: list[str] | None = Field(
        default=None,
        description="Explicit table names/wildcards from list_database_tables to scope the check to; omit to check the full export")


class BackupRestorabilityResult(sdl.Entity):
    """Structural integrity verdict for one export_database_dump SQL text --
    NOT a real test-restore (that needs a separate sandbox DB this app does
    not provision). Catches the failure modes that make a backup silently
    useless: a truncated/cut-off dump, a missing core table, or a table with
    a CREATE statement but zero rows of data."""
    site_id: str = ""
    size_bytes: int = 0
    tables_expected: int = 0
    tables_found_in_dump: int = 0
    missing_tables: list[str] = Field(default_factory=list)
    empty_tables: list[str] = Field(default_factory=list)  # has CREATE TABLE but no INSERT
    truncated: bool = False  # dump does not end in a complete, terminated SQL statement
    restorable: bool = False
    issues: list[str] = Field(default_factory=list)


class ListRestRoutesParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    namespace: str | None = Field(
        default=None,
        description="Optional namespace filter, e.g. 'wp/v2' or 'wc/v3' — omit to list every registered route on the site")


class RestRoute(sdl.Entity):
    """One registered REST route from the site's own root index (GET /wp-json/)."""
    route: str = ""
    namespace: str = ""
    methods: list[str] = Field(default_factory=list)


class GetRestRouteSchemaParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    route: str = Field(min_length=1, description="Exact route path from list_rest_routes, e.g. '/wp/v2/posts/(?P<id>[\\d]+)'")


class RestRouteSchema(sdl.Entity):
    """Full endpoint detail for one REST route — methods and each endpoint's declared args, from the site's own root index."""
    route: str = ""
    namespace: str = ""
    endpoints: list[dict] = Field(default_factory=list)


class ApplicationPassword(sdl.Entity):
    """One registered Application Password for the connected WordPress user (never the secret itself)."""
    uuid: str = ""
    app_id: str = ""
    name: str = ""
    created: str = ""
    last_used: str = ""
    last_ip: str = ""


class RevokeApplicationPasswordParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    uuid: str = Field(min_length=1, description="Application password uuid from list_application_passwords")


class ApplicationPasswordRevokeResult(sdl.Entity):
    site_id: str = ""
    uuid: str = ""
    revoked: bool = False


class PhpInfo(sdl.Entity):
    """PHP runtime facts read via the Imperal Bridge plugin (no SSH needed) — Group F."""
    site_id: str = ""
    php_version: str = ""
    extensions: list[str] = Field(default_factory=list)
    memory_limit: str = ""
    max_execution_time: str = ""
    upload_max_filesize: str = ""
    post_max_size: str = ""
    max_input_vars: str = ""
    server_software: str = ""
    wp_version: str = ""
    opcache_enabled: bool = False
    opcache_hit_rate: str = ""
    db_version: str = ""
    db_server_info: str = ""
    db_size_mb: str = ""
    apache_enabled: bool = False
    apache_modules: list[str] = Field(default_factory=list)
    source: str = ""  # "bridge" or "ssh"


class DebugModeStatus(sdl.Entity):
    """WP_DEBUG / WP_DEBUG_LOG / WP_DEBUG_DISPLAY constants — should normally be off in production."""
    site_id: str = ""
    wp_debug: bool = False
    wp_debug_log: bool = False
    wp_debug_display: bool = False


class ListAdminUsersParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    limit: int = Field(default=20, ge=1, le=100, description="Max items to return, 1-100")


class FilePermissionsStatus(sdl.Entity):
    """Octal permission bits for wp-config.php and wp-content — the two most commonly misconfigured paths."""
    site_id: str = ""
    wp_config_exists: bool = False
    wp_config_permissions: str | None = None
    wp_content_permissions: str | None = None


class WpConfigConstants(sdl.Entity):
    """A hard-allowlisted safe subset of wp-config.php constants — never DB credentials or auth keys/salts."""
    site_id: str = ""
    wp_version: str = ""
    table_prefix: str = ""
    wp_debug: bool | None = None
    wp_cache: bool | None = None
    wp_environment_type: str | None = None
    wp_home: str | None = None
    wp_siteurl: str | None = None
    disallow_file_edit: bool | None = None
    disallow_file_mods: bool | None = None
    automatic_updater_disabled: bool | None = None


class MustUsePlugin(sdl.Entity):
    file: str = ""
    version: str = ""
    description: str = ""


class DropIn(sdl.Entity):
    file: str = ""
    description: str = ""


class EnvironmentType(sdl.Entity):
    site_id: str = ""
    environment_type: str = ""


class TailLogParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    lines: int = Field(default=100, ge=1, le=1000, description="How many trailing lines to read (1-1000)")


class LogTail(sdl.Entity):
    """The last N lines of a log file on the server, read via SSH/WP-CLI."""
    site_id: str = ""
    path: str = ""
    exists: bool = False
    lines: list[str] = Field(default_factory=list)
    note: str = ""


class ClearLogResult(sdl.Entity):
    site_id: str = ""
    path: str = ""
    cleared: bool = False
    note: str = ""


class RegisteredPostType(sdl.Entity):
    """One registered post type from the site's own /wp/v2/types index
    (fetched with context=edit, since `viewable` is an edit-context-only
    field in WordPress core's own REST schema)."""
    slug: str = ""
    rest_base: str = ""
    hierarchical: bool = False
    viewable: bool = False
    has_archive: bool = False
    taxonomies: list[str] = Field(default_factory=list)


class RegisteredTaxonomy(sdl.Entity):
    """One registered taxonomy from the site's own /wp/v2/taxonomies index
    (fetched with context=edit, since `public` lives inside the
    edit-context-only `visibility` object in WordPress core's own REST
    schema)."""
    slug: str = ""
    rest_base: str = ""
    hierarchical: bool = False
    public: bool = False
    types: list[str] = Field(default_factory=list)


class ReusableBlock(sdl.Entity):
    """One Gutenberg reusable block / synced pattern -- a real post with the
    `wp_block` post type, read via native `GET /wp/v2/blocks`. `sync_status`
    is normalized from WP core's own `wp_pattern_sync_status` meta: an empty
    string there means fully synced, so this field reports the explicit
    'synced' instead of leaving callers to interpret emptiness."""
    slug: str = ""
    status: str = ""
    sync_status: str = ""


class Webhook(sdl.Entity):
    """One WooCommerce webhook (native `wc/v3/webhooks`)."""
    status: str = ""  # active, paused, disabled
    topic: str = ""  # e.g. order.created
    resource: str = ""  # read-only, derived from topic
    event: str = ""  # read-only, derived from topic
    delivery_url: str = ""
    date_created: str = ""
    date_modified: str = ""


class ListWebhooksParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    status: str = Field(default="", description="Optional filter: 'active', 'paused', or 'disabled'. Empty returns every status.")
    limit: int = Field(default=20, ge=1, le=100, description="Max webhooks to return, 1-100")


class WebhookIdParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    webhook_id: int = Field(gt=0, description="Numeric webhook id from list_registered_webhooks")


class CreateWebhookParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    topic: str = Field(min_length=1, description=(
        "Webhook topic: a core topic like 'order.created'/'order.updated'/'order.deleted', "
        "'product.created'/'product.updated'/'product.deleted', 'customer.created'/"
        "'customer.updated'/'customer.deleted', 'coupon.created'/'coupon.updated'/"
        "'coupon.deleted' -- or a custom topic 'action.<hook_name>' bound to any WooCommerce "
        "action hook"))
    delivery_url: str = Field(default="", description="HTTPS URL where the webhook payload will be POSTed")
    name: str = Field(default="", description="Friendly name; WooCommerce defaults to 'Webhook created on <date>' if left empty")
    secret: str = Field(default="", description=(
        "Secret used to HMAC-SHA256-sign the delivered payload so the receiver can verify "
        "authenticity. WooCommerce defaults to an MD5 hash of the current user's ID/username "
        "if left empty -- pass an explicit secret for anything security-sensitive."))
    status: str = Field(default="active", description="'active' (delivers), 'paused' (does not deliver), or 'disabled'")


class UpdateWebhookParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    webhook_id: int = Field(gt=0, description="Numeric webhook id from list_registered_webhooks")
    topic: str | None = Field(default=None, description="New topic, if changing it")
    delivery_url: str | None = Field(default=None, description="New delivery URL, if changing it")
    name: str | None = Field(default=None, description="New friendly name, if changing it")
    secret: str | None = Field(default=None, description="New secret, if rotating it")
    status: str | None = Field(default=None, description="New status: 'active', 'paused', or 'disabled'")


class DeleteWebhookParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    webhook_id: int = Field(gt=0, description="Numeric webhook id from list_registered_webhooks")


class WebhookDeleteResult(sdl.Entity):
    deleted: bool = False


class BulkWebhookStatusParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    webhook_ids: list[int] = Field(min_length=1, max_length=100, description="Explicit webhook ids from list_registered_webhooks; 1-100, never inferred")
    status: str = Field(description="New status for every target webhook: 'active', 'paused', or 'disabled'")


class ApplyBulkWebhookStatusParams(BulkWebhookStatusParams):
    expected_state_token: str = Field(min_length=64, max_length=64, description="Exact token from preview; execution stops before all writes if any target webhook changed")


class BulkWebhookStatusResult(sdl.Entity):
    id: str = ""
    title: str = "Webhook status batch"
    kind: str = "wc_bulk_webhook_status"
    preview: bool = True
    requested: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    state_token: str = ""
    changes: list[str] = Field(default_factory=list)
    updated_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class BlockPattern(sdl.Entity):
    """One registered block pattern (theme/plugin supplied), read via
    native `GET /wp/v2/block-patterns/patterns`. Read-only: patterns are
    PHP/JSON registrations, not database rows -- there is no REST route to
    create/edit/delete one."""
    name: str = ""
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    block_types: list[str] = Field(default_factory=list)
    source: str = ""


# ─────────── Action Scheduler (WooCommerce's background job queue, Bridge-only) ───────────

class ListScheduledActionsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    status: str = Field(default="", description="Filter by status: pending, in-progress, complete, failed, canceled. Empty = all.")
    hook: str = Field(default="", description="Filter by exact hook name")
    group: str = Field(default="", description="Filter by group (usually the plugin that scheduled it, e.g. 'woocommerce')")
    per_page: int = Field(default=20, ge=1, le=100, description="Max actions to return, 1-100")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class ScheduledActionItem(sdl.Entity):
    """One Action Scheduler job — id, hook, status, group, scheduled time, args."""
    hook: str = ""
    status: str = ""
    group: str = ""
    scheduled: int | None = None
    args: dict = Field(default_factory=dict)


class GetScheduledActionParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    action_id: int = Field(gt=0, description="Action id from list_scheduled_actions")


class ScheduledActionLogEntry(BaseModel):
    """A nested log line inside ScheduledActionDetail.logs — never returned as a
    top-level ActionResult on its own, so it does not need sdl.Entity's id/title."""
    message: str = ""
    date: str = ""


class ScheduledActionDetail(sdl.Entity):
    """One Action Scheduler job in full, including its execution log."""
    hook: str = ""
    status: str = ""
    group: str = ""
    scheduled: int | None = None
    args: dict = Field(default_factory=dict)
    logs: list[ScheduledActionLogEntry] = Field(default_factory=list)


class ScheduledActionRunResult(sdl.Entity):
    ran: bool = False
    failed: bool = False
    error: str = ""


class ScheduledActionCancelResult(sdl.Entity):
    cancelled: bool = False


class ScheduledActionRetryResult(sdl.Entity):
    retried: bool = False
    original_id: int = 0
    new_action_id: int = 0


class ActionCountsResult(sdl.Entity):
    """One-glance health snapshot of the queue, grouped by status."""
    pending: int = 0
    in_progress: int = 0
    complete: int = 0
    failed: int = 0
    canceled: int = 0


# ─────────── Rewrite rules & permalinks (Bridge SECTION 17: /imperal/v1/rewrite) ───────────

class PermalinkStructureResult(sdl.Entity):
    """The site's current permalink structure and related base slugs."""
    permalink_structure: str = ""
    category_base: str = ""
    tag_base: str = ""


class UpdatePermalinkStructureParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    permalink_structure: str = Field(
        description="New permalink structure, e.g. '/%year%/%monthnum%/%postname%/' or '' for plain "
                    "'?p=123' links. Use the exact WordPress permastruct tag syntax."
    )
    category_base: str | None = Field(default=None, description="New base for category permalinks, e.g. 'topics' (without slashes)")
    tag_base: str | None = Field(default=None, description="New base for tag permalinks, e.g. 'labels' (without slashes)")


class FlushRewriteRulesResult(sdl.Entity):
    flushed: bool = False
    rule_count: int = 0


class RewriteRuleItem(sdl.Entity):
    """One compiled rewrite rule, from the site's rewrite_rules option."""
    match: str = ""
    query: str = ""


class ListRewriteRulesParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")


# ─────────── Import / Export (WXR) ───────────

_WXR_EXPORT_CAP = 2_000_000  # ~2MB of XML text — mirrors the DB dump cap; scope down if refused


class ExportWxrParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    content: str = Field(
        default="all",
        description="Type of content to export: 'all', 'post', 'page', 'attachment', or a custom "
                    "post type slug. 'all' exports every post type with can_export enabled.")
    post_type: str | None = Field(
        default=None,
        description="Alias for content when you already know the exact post type slug (e.g. 'product')")
    author: str | None = Field(default=None, description="Only export content by this author (WordPress user ID as a string)")
    category: str | None = Field(default=None, description="Only export posts assigned to this category slug (content='post' only)")
    start_date: str | None = Field(default=None, description="Only export content published on/after this date, format YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="Only export content published on/before this date, format YYYY-MM-DD")
    status: str | None = Field(default=None, description="Only export posts/pages with this status, e.g. 'publish', 'draft', 'private'")


class WxrExportResult(sdl.Entity):
    """A generated WXR (WordPress eXtended RSS) export document."""
    site_id: str = ""
    xml: str = ""
    size_bytes: int = 0
    post_count: int = 0


class ImportWxrParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    wxr_xml: str = Field(
        min_length=1, max_length=_WXR_EXPORT_CAP,
        description="The full WXR (.xml) file content to import — e.g. from export_wxr's own xml field, "
                    "or a file the user pasted/uploaded elsewhere. Capped at ~2MB of text.")
    authors: str = Field(
        default="create",
        description="How to handle author mapping: 'create' makes any missing users from the WXR file "
                    "(matches wp-cli's own default), or 'skip' to skip author mapping and attribute "
                    "everything to the connected user")
    skip_attachments: bool = Field(
        default=False,
        description="Skip importing file attachments (images etc.) referenced in the WXR file — matches "
                    "wp-cli's own `--skip=attachment`. By default attachments ARE imported.")


class WxrImportResult(sdl.Entity):
    """Outcome of importing a WXR file via WP-CLI's own Importer_Command (`wp import`)."""
    site_id: str = ""
    imported_count: int = 0
    skipped_count: int = 0
    output: str = ""


# ─────────── Core / plugin integrity (SSH/WP-CLI) ───────────

class PluginChecksumParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    plugin: str = Field(
        min_length=1, max_length=200,
        description="Exact WordPress.org plugin slug from list_plugins, e.g. 'akismet' or 'woocommerce'")


class ChecksumVerificationResult(sdl.Entity):
    """Result of a WP-CLI checksum verification against WordPress.org's manifest."""
    site_id: str = ""
    target: str = ""
    verified: bool = False
    output: str = ""


# ─────────── Mail deliverability (Bridge) ───────────

class SendTestEmailParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    to: str = Field(min_length=3, max_length=320, description="Recipient email address for this one test message")


class TestEmailResult(sdl.Entity):
    """Acknowledgement that WordPress accepted a fixed test message for delivery."""
    site_id: str = ""
    recipient: str = ""
    accepted: bool = False


class MailConfiguration(sdl.Entity):
    """Mail mechanism that WordPress/known active mail plugins expose without secrets."""
    site_id: str = ""
    mechanism: str = ""
    provider: str = ""
    detected_plugin: str = ""
    notes: str = ""


# ─────────── WordPress core Site Health ───────────

class SiteHealthTest(sdl.Entity):
    """One result directly returned by WordPress core's Site Health REST API."""
    test: str = ""
    label: str = ""
    status: str = ""
    badge: str = ""
    description: str = ""
    actions: str = ""


class CoreSiteHealthReport(sdl.Entity):
    """Fixed, documented WordPress core Site Health test battery."""
    site_id: str = ""
    tests: list[SiteHealthTest] = []
    unavailable_tests: list[str] = []


class SiteHealthDirectorySizes(sdl.Entity):
    """Directory-size facts reported by WordPress core Site Health."""
    site_id: str = ""
    sizes: dict = {}


# ─────────── User sessions (Bridge) ───────────

class UserSession(sdl.Entity):
    """Non-secret WordPress login-session metadata."""
    login: int = 0
    expiration: int = 0
    ip: str = ""
    ua: str = ""


class UserSessions(sdl.Entity):
    site_id: str = ""
    user_id: int = 0
    sessions: list[UserSession] = []


class UserSessionsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(gt=0, description="WordPress user id whose login sessions to inspect")


class DestroySessionsParams(BaseModel):
    site_id: str = Field(description="Site id from a previous list_sites call — never invent it")
    user_id: int = Field(gt=0, description="WordPress user id whose login sessions will be ended")


class DestroySessionsResult(sdl.Entity):
    site_id: str = ""
    user_id: int = 0
    destroyed: bool = False
