"""Create and update WordPress posts/pages: Gutenberg content, category,
Polylang language, and Rank Math SEO fields set in the same call.

Ported from WP Publisher's publish_draft — everything about interpreting an
input document (docx parsing, heading heuristics, confirmation rules) stays
out of scope here. The caller decides the content blocks; this module only
turns them into a WordPress post.

SEO fields (meta_title, meta_description, focus_keyword) are written by
delegating to the existing update_seo_meta tier-based writer in
handlers_seo.py, instead of re-adding WP Publisher's own bridge-only SEO
write path — one write path for Rank Math meta, not two.
"""

from imperal_sdk import ActionResult

from app import chat
import gutenberg
import handlers_seo
import storage
from models import CreatePostParams, PostResult, UpdatePostParams, UpdateSeoMetaParams
from wp_client import (
    create_post as wp_create_post,
    create_term,
    find_category_id,
    find_term_ids,
    update_post as wp_update_post,
    wp_error_code,
    wp_error_message,
    wp_title,
)

# Regular blog posts are the content pipeline's main output -- for THIS post
# type, slug / meta_title / category are not nice-to-haves a caller might
# forget to pass: they are mandatory, checked here, so a post can never leave
# create_post without them. Pages and custom post types keep the old,
# permissive behaviour (they have very different, non-SEO-article needs).
_SEO_REQUIRED_POST_TYPE = "post"

_POST_TYPE_BASES = {"post": "posts", "page": "pages"}


def _rest_base(post_type: str) -> str:
    """Map a post type name onto its REST base — custom types are their own base."""
    return _POST_TYPE_BASES.get(post_type, post_type)


async def _authed(ctx, site_id):
    record = await storage.get_site_record(ctx, site_id)
    if not record:
        return None, ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    pw = await storage.get_credential(ctx, site_id)
    if not pw:
        return None, ActionResult.error(
            "Stored credential is missing — reconnect the site.",
            retryable=False, code="SITE_CREDENTIAL_MISSING")
    return (record["url"], record["username"], pw), None


def _post_result(item: dict, *, post_type: str, category_resolved: bool = True,
                  tags_not_found: list[str] | None = None, featured_media_set: bool = False) -> PostResult:
    link = item.get("link", "")
    return PostResult(
        id=str(item.get("id", "")), title=wp_title(item), kind=f"wp_{post_type}",
        url=link, link=link, post_type=post_type,
        slug=item.get("slug", ""), status=item.get("status"),
        date=item.get("date"), category_resolved=category_resolved,
        tags_not_found=tags_not_found or [], featured_media_set=featured_media_set,
    )


@chat.function(
    "create_post",
    description=(
        "Create a WordPress post or page with Gutenberg content, optional category, "
        "Polylang language, and Rank Math SEO fields (including canonical_url). "
        "Content is given as an ordered list of {type, text, level} blocks — "
        "'heading', 'paragraph', 'image', or 'faq' (renders a visible Q&A section "
        "plus FAQPage JSON-LD schema, works on any site regardless of SEO plugin) "
        "— which this tool renders into Gutenberg block markup. For post_type='post' "
        "slug, meta_title, category, excerpt, and featured_media_id are mandatory. "
        "Defaults to a draft."
    ),
    action_type="write",
    data_model=PostResult,
    effects=["wp.post_create"],
    event="wp-site-connector.create_post",
)
async def create_post(ctx, params: CreatePostParams) -> ActionResult:
    """Create one WordPress post/page, then best-effort write any given SEO fields."""
    if params.status == "future" and not params.date:
        return ActionResult.error(
            "A scheduled post needs a date — pass date (YYYY-MM-DD or full ISO 8601) with status='future'.",
            retryable=False, code="POST_SCHEDULE_DATE_MISSING")

    post_type = params.post_type.strip() or "post"

    # SEO-critical fields are mandatory for regular posts -- the content
    # pipeline's whole point is publishing findable, correctly-tagged,
    # properly-summarised articles, so a post can't leave create_post
    # missing any of these (category can be existing or newly created).
    if post_type == _SEO_REQUIRED_POST_TYPE:
        missing = []
        if not params.slug or not params.slug.strip():
            missing.append("slug")
        if not params.meta_title or not params.meta_title.strip():
            missing.append("meta_title")
        if not params.category or not params.category.strip():
            missing.append("category")
        if not params.excerpt or not params.excerpt.strip():
            missing.append("excerpt")
        if not params.featured_media_id:
            missing.append("featured_media_id")
        if missing:
            return ActionResult.error(
                "create_post for a 'post' requires " + ", ".join(missing) +
                " — pass a URL slug, an SEO meta_title, an existing-or-new "
                "category name, a standalone excerpt, and a featured image "
                "attachment id. This keeps every published article correctly "
                "findable and complete instead of relying on a follow-up fix.",
                retryable=False, code="POST_SEO_FIELDS_REQUIRED")

    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    rest_base = _rest_base(post_type)
    content = gutenberg.blocks_to_content(params.blocks)

    category_id = None
    category_resolved = True
    category_created = False
    if params.category:
        category_id = await find_category_id(ctx, base_url, username, pw, params.category, lang=params.lang)
        if category_id is None:
            # Don't just warn and publish uncategorised -- create the
            # category so the post always ends up correctly filed.
            try:
                create_resp = await create_term(ctx, base_url, username, pw, "categories",
                                                name=params.category.strip())
                if create_resp.status_code < 400 and isinstance(create_resp.body, dict):
                    category_id = create_resp.body.get("id")
                    category_created = category_id is not None
            except Exception as e:
                await ctx.log(f"create_post: category auto-create failed: {e}", level="error")
        category_resolved = category_id is not None

    tag_ids = []
    tags_not_found = []
    if params.tags:
        tag_ids, tags_not_found = await find_term_ids(ctx, base_url, username, pw, "tags", params.tags, lang=params.lang)

    try:
        resp = await wp_create_post(
            ctx, base_url, username, pw, post_type=rest_base, title=params.title,
            content=content, status=params.status, slug=params.slug,
            category_id=category_id, tag_ids=tag_ids, featured_media=params.featured_media_id,
            lang=params.lang, date=params.date, excerpt=params.excerpt,
        )
    except Exception as e:
        await ctx.log(f"create_post request failed: {e}", level="error")
        return ActionResult.error("Could not reach the site — try again.",
                                  retryable=True, code="WP_UNREACHABLE")

    if resp.status_code >= 400:
        return ActionResult.error(wp_error_message(resp.status_code),
                                  retryable=resp.status_code >= 500 or resp.status_code == 429,
                                  code=wp_error_code(resp.status_code))
    if not isinstance(resp.body, dict):
        return ActionResult.error("WordPress returned an unexpected response.",
                                  retryable=False, code="WP_RESPONSE_UNEXPECTED")

    post = resp.body
    warnings = []
    if params.category and category_created:
        warnings.append(f"category '{params.category}' didn't exist yet — created it")
    elif params.category and not category_resolved:
        warnings.append(f"category '{params.category}' could not be found or created — the post was created without one")
    if tags_not_found:
        warnings.append(f"tag(s) not found and skipped: {', '.join(tags_not_found)}")

    seo_fields = {}
    if params.meta_title is not None:
        seo_fields["meta_title"] = params.meta_title
    if params.meta_description is not None:
        seo_fields["meta_description"] = params.meta_description
    if params.focus_keyword is not None:
        seo_fields["focus_keyword"] = params.focus_keyword
    if params.canonical_url is not None:
        seo_fields["canonical_url"] = params.canonical_url
    if seo_fields:
        seo_result = await handlers_seo.update_seo_meta(ctx, UpdateSeoMetaParams(
            site_id=params.site_id, post_id=post.get("id"), post_type=post_type, **seo_fields,
        ))
        if seo_result.status != "success":
            warnings.append(f"post was created, but SEO fields were not saved: {seo_result.error}")

    result = _post_result(post, post_type=post_type, category_resolved=category_resolved,
                          tags_not_found=tags_not_found, featured_media_set=bool(params.featured_media_id))
    summary = f"Created {post_type} '{result.title}' ({params.status})"
    if warnings:
        summary += " — " + "; ".join(warnings)
    return ActionResult.success(result, summary=summary)


@chat.function(
    "update_post",
    description=(
        "Update selected fields of an existing WordPress post or page: title, status, "
        "slug, content (as {type, text, level} blocks), excerpt, category, or date. "
        "Omitted fields are left unchanged."
    ),
    action_type="write",
    data_model=PostResult,
    effects=["wp.post_update"],
    event="wp-site-connector.update_post",
)
async def update_post(ctx, params: UpdatePostParams) -> ActionResult:
    """Update one WordPress post/page. Only the fields the caller passed are sent."""
    auth, err = await _authed(ctx, params.site_id)
    if err:
        return err
    base_url, username, pw = auth

    post_type = params.post_type.strip() or "post"
    rest_base = _rest_base(post_type)

    fields = {}
    if params.title is not None:
        fields["title"] = params.title
    if params.status is not None:
        fields["status"] = params.status
    if params.slug is not None:
        fields["slug"] = params.slug
    if params.blocks is not None:
        fields["content"] = gutenberg.blocks_to_content(params.blocks)
    if params.excerpt is not None:
        fields["excerpt"] = params.excerpt
    if params.date is not None:
        fields["date"] = params.date if "T" in params.date else f"{params.date}T10:00:00"

    category_resolved = True
    if params.category is not None:
        if params.category == "":
            fields["categories"] = []
        else:
            category_id = await find_category_id(ctx, base_url, username, pw, params.category)
            category_resolved = category_id is not None
            if category_id:
                fields["categories"] = [category_id]

    tags_not_found = []
    if params.tags is not None:
        if not params.tags:
            fields["tags"] = []
        else:
            tag_ids, tags_not_found = await find_term_ids(ctx, base_url, username, pw, "tags", params.tags)
            fields["tags"] = tag_ids

    if params.featured_media_id is not None:
        fields["featured_media"] = params.featured_media_id

    seo_fields = {}
    if params.meta_title is not None:
        seo_fields["meta_title"] = params.meta_title
    if params.meta_description is not None:
        seo_fields["meta_description"] = params.meta_description
    if params.focus_keyword is not None:
        seo_fields["focus_keyword"] = params.focus_keyword
    if params.canonical_url is not None:
        seo_fields["canonical_url"] = params.canonical_url

    if not fields and params.category is None and not seo_fields:
        return ActionResult.error(
            "Nothing to update — pass at least one field to change.",
            retryable=False, code="POST_NO_FIELDS")

    resp = None
    if fields or params.category is not None:
        try:
            resp = await wp_update_post(ctx, base_url, username, pw, post_id=params.post_id,
                                        post_type=rest_base, **fields)
        except Exception as e:
            await ctx.log(f"update_post request failed: {e}", level="error")
            return ActionResult.error("Could not reach the site — try again.",
                                      retryable=True, code="WP_UNREACHABLE")

        if resp.status_code >= 400:
            return ActionResult.error(wp_error_message(resp.status_code),
                                      retryable=resp.status_code >= 500 or resp.status_code == 429,
                                      code=wp_error_code(resp.status_code))
        if not isinstance(resp.body, dict):
            return ActionResult.error("WordPress returned an unexpected response.",
                                      retryable=False, code="WP_RESPONSE_UNEXPECTED")

    warnings = []
    if seo_fields:
        seo_result = await handlers_seo.update_seo_meta(ctx, UpdateSeoMetaParams(
            site_id=params.site_id, post_id=params.post_id, post_type=post_type, **seo_fields,
        ))
        if seo_result.status != "success":
            warnings.append(f"SEO fields were not saved: {seo_result.error}")

    if resp is not None:
        result = _post_result(resp.body, post_type=post_type, category_resolved=category_resolved,
                              tags_not_found=tags_not_found, featured_media_set=params.featured_media_id is not None)
    else:
        # Nothing but SEO fields changed -- no post-fields write happened,
        # so report back using the caller-known id instead of a fetched body.
        result = PostResult(id=str(params.post_id), title="", kind=f"wp_{post_type}",
                            url="", link="", post_type=post_type, slug=params.slug or "",
                            status=params.status, category_resolved=category_resolved,
                            tags_not_found=tags_not_found, featured_media_set=params.featured_media_id is not None)
    summary = f"Updated {post_type} '{result.title}'" if result.title else f"Updated {post_type} #{params.post_id}"
    if params.category and not category_resolved:
        summary += f" — category '{params.category}' was not found, left unchanged"
    if warnings:
        summary += " — " + "; ".join(warnings)
    return ActionResult.success(result, summary=summary)
