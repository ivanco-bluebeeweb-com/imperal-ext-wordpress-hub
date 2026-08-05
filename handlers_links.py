"""Internal/external link + anchor text extraction for one published or
draft WordPress post/page.

Why this exists: SEO review needs to see, for one article, every link it
carries and how it is anchored -- internal links strengthen site architecture
and pass authority to the right pages only if the anchor text is meaningful;
external links need a deliberate rel policy. Nothing here writes anything --
this is a pure read/report tool over content the caller already has (either
fetched live from WordPress, or passed straight from the Article Writer
extension before a post even exists).
"""
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from imperal_sdk import ActionResult, sdl

from app import chat
from models import CheckSitemapParams, ExtractLinksParams, LinkInfo, LinkReport, SitemapCheckResult
from wp_client import wp_get, wp_error_message
import storage


class _AnchorParser(HTMLParser):
    """Collect every <a href=...>anchor text</a> pair, tolerant of nested tags
    inside the anchor (e.g. <a href="..."><strong>text</strong></a>).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._href: str | None = None
        self._rel: str = ""
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_d = dict(attrs)
            href = attrs_d.get("href")
            if href:
                self._href = href
                self._rel = attrs_d.get("rel", "") or ""
                self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            anchor_text = "".join(self._buf).strip()
            self.links.append({"href": self._href, "anchor_text": anchor_text, "rel": self._rel})
            self._href = None
            self._rel = ""
            self._buf = []


def _extract_from_html(content_html: str) -> list[dict]:
    parser = _AnchorParser()
    parser.feed(content_html or "")
    return parser.links


def _classify(href: str, site_host: str) -> str:
    """internal | external | anchor | other, based on the link target vs the site's own host."""
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return "anchor"
    if href.startswith("mailto:") or href.startswith("tel:"):
        return "other"
    parsed = urlparse(href)
    if not parsed.netloc:
        return "internal"  # relative path, e.g. /blog/some-post
    host = parsed.netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return "internal" if host == site_host else "external"


@chat.function(
    "extract_links",
    description=(
        "Extract every link inside one article's content, with its anchor text and "
        "whether it is internal (same site) or external -- the panel's SEO review "
        "of an article's link profile. Pass content_html directly (e.g. straight "
        "from Article Writer before publishing) OR post_id on a connected site to "
        "read a post already on WordPress. Flags anchor text that is generic "
        "('click here', 'read more', the bare URL) since that wastes the internal-"
        "linking SEO value, and flags external links missing rel=nofollow/sponsored."
    ),
    action_type="read",
    data_model=LinkReport,
)
async def extract_links(ctx, params: ExtractLinksParams) -> ActionResult:
    """Parse links out of given HTML or a live post, classify and audit each one."""
    content_html = params.content_html or ""
    site_host = ""

    if not content_html.strip():
        if params.post_id is None:
            return ActionResult.error(
                "Pass either content_html (the article body) or post_id (to read a "
                "post already on the connected site).",
                retryable=False, code="LINKS_NO_SOURCE")
        if not params.site_id:
            return ActionResult.error(
                "post_id needs site_id too — pass the site_id from list_sites.",
                retryable=False, code="LINKS_SITE_ID_MISSING")
        record = await storage.get_site_record(ctx, params.site_id)
        if not record:
            return ActionResult.error(
                "No connected site with that id — run list_sites to see the connected sites.",
                retryable=False, code="SITE_NOT_CONNECTED")
        pw = await storage.get_credential(ctx, params.site_id)
        if not pw:
            return ActionResult.error(
                "Stored credential is missing — reconnect the site.",
                retryable=False, code="SITE_CREDENTIAL_MISSING")
        base_url, username = record["url"], record["username"]
        rest_base = params.post_type or "posts"
        try:
            resp = await wp_get(ctx, base_url, f"/wp-json/wp/v2/{rest_base}/{params.post_id}",
                                username=username, app_password=pw)
        except Exception as e:
            await ctx.log(f"extract_links request failed: {e}", level="error")
            return ActionResult.error("Could not reach the site — try again.",
                                      retryable=True, code="WP_UNREACHABLE")
        if resp.status_code >= 400:
            return ActionResult.error(wp_error_message(resp.status_code),
                                      retryable=resp.status_code >= 500, code="WP_REQUEST_FAILED")
        body = resp.body if isinstance(resp.body, dict) else {}
        content_html = (body.get("content") or {}).get("rendered", "")
        site_host = re.sub(r"^www\.", "", urlparse(base_url).netloc.lower())
    elif params.site_id:
        record = await storage.get_site_record(ctx, params.site_id)
        if record:
            site_host = re.sub(r"^www\.", "", urlparse(record["url"]).netloc.lower())

    raw_links = _extract_from_html(content_html)
    generic_anchors = {"click here", "read more", "here", "this page", "link", "more", "learn more"}

    items = []
    internal_count = external_count = 0
    weak_anchor_count = 0
    for link in raw_links:
        kind = _classify(link["href"], site_host) if site_host else _classify(link["href"], "")
        anchor = link["anchor_text"]
        anchor_lower = anchor.lower().strip()
        is_weak = (not anchor) or anchor_lower in generic_anchors or anchor.strip() == link["href"].strip()
        if is_weak:
            weak_anchor_count += 1
        if kind == "internal":
            internal_count += 1
        elif kind == "external":
            external_count += 1
        rel = link["rel"] or ""
        missing_rel = kind == "external" and not any(t in rel for t in ("nofollow", "sponsored", "ugc"))
        items.append(LinkInfo(
            id=f"link-{len(items)+1}", title=anchor or link["href"], kind="link",
            href=link["href"], anchor_text=anchor, link_type=kind,
            weak_anchor=is_weak, rel=rel, missing_rel_policy=missing_rel,
        ))

    warnings = []
    if weak_anchor_count:
        warnings.append(f"{weak_anchor_count} link(s) have generic or empty anchor text — "
                        "rewrite with descriptive, keyword-relevant anchors")
    if internal_count == 0:
        warnings.append("no internal links found — every article should link to at least "
                        "one relevant existing page for SEO internal-linking value")
    missing_rel = sum(1 for i in items if i.missing_rel_policy)
    if missing_rel:
        warnings.append(f"{missing_rel} external link(s) have no rel=nofollow/sponsored/ugc policy")

    report = LinkReport(
        id="link-report", title="Link report", kind="link_report",
        total_links=len(items), internal_count=internal_count, external_count=external_count,
        weak_anchor_count=weak_anchor_count, links=items, warnings=warnings,
    )
    summary = f"{len(items)} link(s): {internal_count} internal, {external_count} external"
    if warnings:
        summary += " — " + "; ".join(warnings)
    return ActionResult.success(report, summary=summary)


# ─────────── post-publish sitemap inclusion check ───────────
#
# Rank Math (and WordPress core since 5.5) both publish a plain XML sitemap
# with no auth required -- this is a simple unauthenticated GET + XML scan,
# not a REST API capability, so it works on every WordPress site regardless
# of which SEO plugin is active. We check the most common locations in order
# and, for an index file, recurse one level into its listed sub-sitemaps.

_SITEMAP_CANDIDATES = (
    "/sitemap_index.xml",   # Rank Math, Yoast
    "/sitemap.xml",          # some configs alias this to the index
    "/wp-sitemap.xml",       # WordPress core (no SEO plugin)
)

_MAX_SUBSITEMAPS_TO_SCAN = 15


def _xml_locs(xml_text: str) -> list[str]:
    """Pull every <loc>...</loc> value out of a sitemap XML body."""
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text or "")


def _normalise(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
    return url.lower()


@chat.function(
    "check_sitemap_inclusion",
    description=(
        "Check whether a just-published post/page URL already appears in the site's "
        "XML sitemap -- the mandatory post-publish step that catches a page silently "
        "excluded from indexing (wrong Rank Math visibility setting, sitemap caching, "
        "an SEO plugin config the caller does not control). Tries sitemap_index.xml, "
        "sitemap.xml, then wp-sitemap.xml (WordPress core's own, when no SEO plugin "
        "publishes one), and recurses one level into an index's sub-sitemaps."
    ),
    action_type="read",
    data_model=SitemapCheckResult,
)
async def check_sitemap_inclusion(ctx, params: CheckSitemapParams) -> ActionResult:
    """Fetch the site's sitemap(s) with a plain unauthenticated GET and look for the URL."""
    record = await storage.get_site_record(ctx, params.site_id)
    if not record:
        return ActionResult.error(
            "No connected site with that id — run list_sites to see the connected sites.",
            retryable=False, code="SITE_NOT_CONNECTED")
    base_url = record["url"]
    target = _normalise(params.url)

    checked = []
    warnings = []
    for path in _SITEMAP_CANDIDATES:
        sitemap_url = f"{base_url}{path}"
        try:
            resp = await ctx.http.get(sitemap_url)
        except Exception as e:
            await ctx.log(f"check_sitemap_inclusion fetch failed for {sitemap_url}: {e}", level="error")
            continue
        checked.append(sitemap_url)
        if resp.status_code != 200:
            continue
        body = resp.body if isinstance(resp.body, str) else (resp.body.decode() if isinstance(resp.body, bytes) else "")
        if not body:
            continue
        locs = _xml_locs(body)
        if not locs:
            continue
        direct_hit = any(_normalise(loc) == target for loc in locs)
        if direct_hit:
            return ActionResult.success(
                SitemapCheckResult(
                    id="sitemap-check", title="Sitemap check", kind="sitemap_check",
                    url=params.url, found=True, sitemap_index_url=sitemap_url,
                    checked_sitemap_url=sitemap_url, sitemaps_checked=checked, warnings=[],
                ),
                summary=f"Found in {sitemap_url}")
        # This might be an index of sub-sitemaps (post-sitemap.xml, page-sitemap.xml, ...)
        # rather than a flat list of pages -- recurse one level into each entry that
        # itself looks like a sitemap file.
        sub_sitemaps = [loc for loc in locs if loc.lower().endswith(".xml")][:_MAX_SUBSITEMAPS_TO_SCAN]
        for sub_url in sub_sitemaps:
            try:
                sub_resp = await ctx.http.get(sub_url)
            except Exception as e:
                await ctx.log(f"check_sitemap_inclusion fetch failed for {sub_url}: {e}", level="error")
                continue
            checked.append(sub_url)
            if sub_resp.status_code != 200:
                continue
            sub_body = sub_resp.body if isinstance(sub_resp.body, str) else (
                sub_resp.body.decode() if isinstance(sub_resp.body, bytes) else "")
            sub_locs = _xml_locs(sub_body)
            if any(_normalise(loc) == target for loc in sub_locs):
                return ActionResult.success(
                    SitemapCheckResult(
                        id="sitemap-check", title="Sitemap check", kind="sitemap_check",
                        url=params.url, found=True, sitemap_index_url=sitemap_url,
                        checked_sitemap_url=sub_url, sitemaps_checked=checked, warnings=[],
                    ),
                    summary=f"Found in {sub_url}")

    warnings.append(
        "URL not found in any sitemap checked — it may be excluded by an SEO plugin "
        "visibility/noindex setting, or the sitemap cache has not refreshed yet.")
    return ActionResult.success(
        SitemapCheckResult(
            id="sitemap-check", title="Sitemap check", kind="sitemap_check",
            url=params.url, found=False, sitemaps_checked=checked, warnings=warnings,
        ),
        summary="Not found in any checked sitemap — " + warnings[0])
