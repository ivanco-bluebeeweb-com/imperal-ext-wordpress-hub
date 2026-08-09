"""WooCommerce product reviews: list, moderate (approve/hold/spam/trash), and reply.

Product reviews are comments on the 'product' post type, exposed through
WooCommerce's own /wc/v3/products/reviews endpoint rather than the native
/wp/v2/comments one -- same shape as handlers_read.py's comment moderation,
but this was a WooCommerce-specific gap: store owners had list_comments
(which does NOT include product reviews) but no way to see or act on the
reviews actually driving purchase decisions on their catalogue.
"""
from imperal_sdk import ActionResult, sdl

from app import chat
from models import (
    Comment,
    ListProductReviewsParams,
    ProductReview,
    ReplyToProductReviewParams,
    SetProductReviewStatusParams,
)
import storage
from wp_client import wp_error_code, wp_error_message, wp_get, wp_request

WC_BASE = "/wp-json/wc/v3"


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    password = await storage.get_credential(ctx, site_id)
    if not password:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], password), None


def _body_code(body):
    return str(body.get("code", "")) if isinstance(body, dict) else ""


def _failure(status_code, body):
    wp_code = _body_code(body)
    if status_code == 404 and wp_code in ("rest_no_route", "woocommerce_rest_cannot_view"):
        return ActionResult.error(
            "WooCommerce doesn't appear to be active on this site, or that review does not exist.",
            retryable=False, code="WOOCOMMERCE_NOT_FOUND")
    if status_code == 404:
        return ActionResult.error(
            "That review does not exist.", retryable=False, code="WC_REVIEW_NOT_FOUND")
    if status_code in (401, 403):
        return ActionResult.error(
            "The connected WordPress user cannot manage product reviews. Reconnect with an "
            "administrator or shop-manager Application Password.",
            retryable=False, code="WC_REVIEW_FORBIDDEN")
    retryable = status_code == 429 or status_code >= 500
    return ActionResult.error(
        wp_error_message(status_code), retryable=retryable, code=wp_error_code(status_code))


def _review_entity(item: dict) -> ProductReview:
    return ProductReview(
        id=str(item.get("id", "")), title=item.get("reviewer", "Anonymous"), kind="wc_product_review",
        product_id=int(item.get("product_id", 0) or 0),
        reviewer=item.get("reviewer", ""),
        reviewer_email=item.get("reviewer_email", ""),
        rating=int(item.get("rating", 0) or 0),
        status=item.get("status", ""),
        snippet=(item.get("review", "") or "").replace("<p>", "").replace("</p>", "")[:160].strip(),
        date=item.get("date_created", ""),
    )


@chat.function(
    "list_product_reviews",
    description=(
        "List WooCommerce product reviews. Use status='hold' to see reviews pending "
        "moderation, 'approved' for published, 'spam' for spam. Optionally filter to one "
        "product_id."
    ),
    action_type="read",
    data_model=sdl.EntityList[ProductReview],
)
async def list_product_reviews(ctx, params: ListProductReviewsParams) -> ActionResult:
    """Return product reviews from the store's wc/v3 REST API."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth
    q: dict = {"per_page": params.limit, "orderby": "date", "order": "desc"}
    if params.status != "all":
        q["status"] = params.status
    if params.product_id:
        q["product"] = params.product_id
    r = await wp_get(ctx, base_url, f"{WC_BASE}/products/reviews",
                     username=username, app_password=pw, params=q)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)
    data = r.body if isinstance(r.body, list) else []
    items = [_review_entity(item) for item in data]
    pending = sum(1 for i in items if i.status == "hold")
    summary = f"{len(items)} review(s)"
    if pending:
        summary += f" — {pending} pending moderation"
    return ActionResult.success(sdl.EntityList[ProductReview](items=items), summary=summary)


@chat.function(
    "set_product_review_status",
    description=(
        "Change a product review's moderation status: 'approved' (publish it), 'hold' "
        "(send back to pending moderation), 'spam', or 'trash'. Use list_product_reviews "
        "first to find the review_id."
    ),
    action_type="write",
    data_model=ProductReview,
    effects=["wc.product_review_status_update"],
    event="wordpress-hub.set_product_review_status",
)
async def set_product_review_status(ctx, params: SetProductReviewStatusParams) -> ActionResult:
    """Set one product review's status via the wc/v3 REST API."""
    status = params.status.strip().lower()
    if status not in ("approved", "hold", "spam", "trash"):
        return ActionResult.error(
            f"Invalid status '{params.status}' — use 'approved', 'hold', 'spam', or 'trash'.",
            retryable=False, code="WC_REVIEW_INVALID_STATUS")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    try:
        r = await wp_request(
            ctx, "put", base_url, f"{WC_BASE}/products/reviews/{params.review_id}",
            username=username, app_password=pw, json={"status": status})
    except Exception as e:
        await ctx.log(f"set_product_review_status request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)

    entity = _review_entity(r.body if isinstance(r.body, dict) else {})
    return ActionResult.success(entity, summary=f"Review {params.review_id} set to '{status}'")


@chat.function(
    "reply_to_product_review",
    description=(
        "Reply to a WooCommerce product review, posted as the connected WordPress user. "
        "Use list_product_reviews first to find the review_id."
    ),
    action_type="write",
    data_model=Comment,
    effects=["wc.product_review_reply"],
    event="wordpress-hub.reply_to_product_review",
)
async def reply_to_product_review(ctx, params: ReplyToProductReviewParams) -> ActionResult:
    """Create a reply comment nested under one product review.

    WooCommerce reviews are comments under the hood, but wc/v3 has no reply
    endpoint of its own -- the native /wp/v2/comments endpoint accepts a
    parent id regardless of which REST surface created the parent comment,
    so this reuses that route rather than needing a WooCommerce-specific one.
    """
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    # Fetch the parent review first so we know which product/post it belongs to --
    # WordPress requires the reply's `post` field to match the parent's post id.
    parent_r = await wp_get(ctx, base_url, f"{WC_BASE}/products/reviews/{params.review_id}",
                            username=username, app_password=pw)
    if not 200 <= parent_r.status_code < 300:
        return _failure(parent_r.status_code, parent_r.body)
    parent = parent_r.body if isinstance(parent_r.body, dict) else {}
    product_id = parent.get("product_id")
    if not product_id:
        return ActionResult.error(
            "Could not determine which product this review belongs to.",
            retryable=False, code="WC_REVIEW_NOT_FOUND")

    try:
        r = await wp_request(
            ctx, "post", base_url, "/wp-json/wp/v2/comments",
            username=username, app_password=pw,
            json={"post": product_id, "parent": params.review_id, "content": params.content})
    except Exception as e:
        await ctx.log(f"reply_to_product_review request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.", retryable=True)
    if not 200 <= r.status_code < 300:
        return _failure(r.status_code, r.body)

    body = r.body if isinstance(r.body, dict) else {}
    entity = Comment(
        id=str(body.get("id", "")), title=body.get("author_name", ""), kind="wp_comment",
        status=body.get("status", ""), author=body.get("author_name", ""),
        snippet=(body.get("content", {}).get("rendered", "") or "")
                .replace("<p>", "").replace("</p>", "")[:120].strip(),
        post_id=str(body.get("post", "")), date=body.get("date", ""),
    )
    return ActionResult.success(entity, summary=f"Replied to review {params.review_id}")
