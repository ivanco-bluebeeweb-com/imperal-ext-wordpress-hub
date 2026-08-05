"""Explicit block content -> Gutenberg block markup.

Ported from WP Publisher's content renderer. This module is deliberately
document-agnostic: it turns a list of {type, text, level} blocks the CALLER
already decided on into post_content — no heuristics, no document parsing.
Anything about interpreting an input file stays out of scope here.
"""

from __future__ import annotations

import html
import json


def paragraph_block(text: str) -> str:
    return f"<!-- wp:paragraph --><p>{html.escape(text)}</p><!-- /wp:paragraph -->"


def heading_block(text: str, level: int = 2) -> str:
    escaped = html.escape(text)
    return (
        f'<!-- wp:heading {{"level":{level}}} -->'
        f'<h{level} class="wp-block-heading">{escaped}</h{level}>'
        f"<!-- /wp:heading -->"
    )


def image_block(media_id: int, media_url: str, alt: str = "", caption: str | None = None) -> str:
    """Gutenberg image block referencing an existing media library attachment.

    ``media_id``/``media_url`` come from a prior upload_media call — this
    function never fetches or uploads anything itself, it only renders markup
    that points at an attachment WordPress already has.
    """
    alt_attr = html.escape(alt, quote=True)
    figure = (
        f'<!-- wp:image {{"id":{media_id},"sizeSlug":"large","linkDestination":"none"}} -->'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{html.escape(media_url, quote=True)}" alt="{alt_attr}" class="wp-image-{media_id}"/>'
    )
    if caption and caption.strip():
        figure += f"<figcaption class=\"wp-element-caption\">{html.escape(caption)}</figcaption>"
    figure += "</figure><!-- /wp:image -->"
    return figure


def faq_block(items, intro_text: str = "") -> str:
    """Render a visible Q&A list PLUS a FAQPage JSON-LD <script> block.

    Deliberately NOT the Rank Math proprietary `wp:rank-math/faq-block` --
    that markup is undocumented and site-specific (depends on exact plugin
    version). Standard schema.org JSON-LD works identically on every
    WordPress site regardless of which SEO plugin (or none) is installed,
    and is exactly what Google's rich-result parser reads. ``items`` is a
    list of {question, answer} dicts or PostBlockInput-style objects.
    """
    def _fields(item):
        if isinstance(item, dict):
            return item.get("question") or "", item.get("answer") or ""
        return getattr(item, "question", "") or "", getattr(item, "answer", "") or ""

    pairs = [(_fields(i)[0].strip(), _fields(i)[1].strip()) for i in (items or [])]
    pairs = [(q, a) for q, a in pairs if q and a]
    if not pairs:
        return ""

    visible = []
    if intro_text and intro_text.strip():
        visible.append(f"<p>{html.escape(intro_text.strip())}</p>")
    for q, a in pairs:
        visible.append(
            f"<h3 class=\"wp-block-heading\">{html.escape(q)}</h3>"
            f"<p>{html.escape(a)}</p>"
        )
    visible_html = (
        '<!-- wp:html -->'
        f'<div class="imperal-faq">{"".join(visible)}</div>'
        '<!-- /wp:html -->'
    )

    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in pairs
        ],
    }
    schema_html = (
        '<!-- wp:html -->'
        f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
        '<!-- /wp:html -->'
    )
    return visible_html + schema_html


def _block_fields(block) -> tuple[str, str, int, int | None, str | None, str | None, list]:
    """Read {type, text, level, media_id, media_url, caption, faq_items} off a dict or pydantic model."""
    if isinstance(block, dict):
        return (block.get("type") or "paragraph", block.get("text") or "", block.get("level") or 2,
                block.get("media_id"), block.get("media_url"), block.get("caption"),
                block.get("faq_items") or [])
    return (getattr(block, "type", "paragraph") or "paragraph",
            getattr(block, "text", "") or "",
            getattr(block, "level", 2) or 2,
            getattr(block, "media_id", None),
            getattr(block, "media_url", None),
            getattr(block, "caption", None),
            getattr(block, "faq_items", None) or [])


def blocks_to_content(blocks) -> str:
    """Render explicit blocks (list of {type, text, level, media_id, media_url, caption, faq_items})
    into post_content.

    type == "heading" renders an <h{level}> block; type == "image" renders a
    Gutenberg image block from an existing attachment (media_id + media_url
    required — a block missing either is skipped, since there is nothing to
    render); type == "faq" renders a visible Q&A list plus FAQPage JSON-LD
    schema (skipped if faq_items is empty); anything else (including the
    default "paragraph") renders a plain paragraph block.

    NOTE on image_role: a block whose image_role names an external_images
    entry gets its media_id/media_url filled in by the caller (see
    handlers_posts.resolve_external_images) BEFORE this function runs -- this
    function only ever renders whatever media_id/media_url already sit on
    the block, regardless of how they got there.
    """
    rendered = []
    for block in blocks or []:
        btype, text, level, media_id, media_url, caption, faq_items = _block_fields(block)
        if btype == "image":
            if media_id and media_url:
                rendered.append(image_block(media_id, media_url, alt=text, caption=caption))
            continue
        if btype == "faq":
            rendered_faq = faq_block(faq_items, intro_text=text)
            if rendered_faq:
                rendered.append(rendered_faq)
            continue
        if not text.strip():
            continue
        if btype == "heading":
            rendered.append(heading_block(text, level))
        else:
            rendered.append(paragraph_block(text))
    return "\n".join(rendered)
