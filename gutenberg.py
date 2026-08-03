"""Explicit block content -> Gutenberg block markup.

Ported from WP Publisher's content renderer. This module is deliberately
document-agnostic: it turns a list of {type, text, level} blocks the CALLER
already decided on into post_content — no heuristics, no document parsing.
Anything about interpreting an input file stays out of scope here.
"""

from __future__ import annotations

import html


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


def _block_fields(block) -> tuple[str, str, int, int | None, str | None, str | None]:
    """Read {type, text, level, media_id, media_url, caption} off a dict or pydantic model."""
    if isinstance(block, dict):
        return (block.get("type") or "paragraph", block.get("text") or "", block.get("level") or 2,
                block.get("media_id"), block.get("media_url"), block.get("caption"))
    return (getattr(block, "type", "paragraph") or "paragraph",
            getattr(block, "text", "") or "",
            getattr(block, "level", 2) or 2,
            getattr(block, "media_id", None),
            getattr(block, "media_url", None),
            getattr(block, "caption", None))


def blocks_to_content(blocks) -> str:
    """Render explicit blocks (list of {type, text, level, media_id, media_url, caption})
    into post_content.

    type == "heading" renders an <h{level}> block; type == "image" renders a
    Gutenberg image block from an existing attachment (media_id + media_url
    required — a block missing either is skipped, since there is nothing to
    render); anything else (including the default "paragraph") renders a
    plain paragraph block.
    """
    rendered = []
    for block in blocks or []:
        btype, text, level, media_id, media_url, caption = _block_fields(block)
        if btype == "image":
            if media_id and media_url:
                rendered.append(image_block(media_id, media_url, alt=text, caption=caption))
            continue
        if not text.strip():
            continue
        if btype == "heading":
            rendered.append(heading_block(text, level))
        else:
            rendered.append(paragraph_block(text))
    return "\n".join(rendered)
