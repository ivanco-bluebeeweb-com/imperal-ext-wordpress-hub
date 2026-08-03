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


def _block_fields(block) -> tuple[str, str, int]:
    """Read {type, text, level} off either a dict or a pydantic model instance."""
    if isinstance(block, dict):
        return (block.get("type") or "paragraph", block.get("text") or "", block.get("level") or 2)
    return (getattr(block, "type", "paragraph") or "paragraph",
            getattr(block, "text", "") or "",
            getattr(block, "level", 2) or 2)


def blocks_to_content(blocks) -> str:
    """Render explicit blocks (list of {type, text, level}) into post_content.

    type == "heading" renders an <h{level}> block; anything else (including
    the default "paragraph") renders a plain paragraph block.
    """
    rendered = []
    for block in blocks or []:
        btype, text, level = _block_fields(block)
        if not text.strip():
            continue
        if btype == "heading":
            rendered.append(heading_block(text, level))
        else:
            rendered.append(paragraph_block(text))
    return "\n".join(rendered)
