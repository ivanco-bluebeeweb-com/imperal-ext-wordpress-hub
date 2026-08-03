"""Tests for gutenberg.py — explicit block -> Gutenberg markup rendering.

Deliberately document-agnostic: every test passes blocks the CALLER already
decided on (no document parsing, no heuristics exercised here).
"""

from models import PostBlockInput
import gutenberg


def test_paragraph_block_escapes_html():
    out = gutenberg.paragraph_block("A & B < C")
    assert "wp:paragraph" in out
    assert "A &amp; B &lt; C" in out


def test_heading_block_renders_level():
    out = gutenberg.heading_block("Title", level=3)
    assert '"level":3' in out
    assert "<h3" in out and "</h3>" in out


def test_image_block_renders_id_url_alt():
    out = gutenberg.image_block(42, "https://x.com/pic.jpg", alt="A cat")
    assert "wp:image" in out
    assert '"id":42' in out
    assert 'src="https://x.com/pic.jpg"' in out
    assert 'alt="A cat"' in out
    assert "wp-image-42" in out


def test_image_block_with_caption():
    out = gutenberg.image_block(7, "https://x.com/pic.jpg", caption="A caption")
    assert "figcaption" in out
    assert "A caption" in out


def test_image_block_without_caption_omits_figcaption():
    out = gutenberg.image_block(7, "https://x.com/pic.jpg")
    assert "figcaption" not in out


def test_image_block_escapes_alt_and_url():
    out = gutenberg.image_block(1, 'https://x.com/pic.jpg?a=1&b=2', alt='"quoted" & <tag>')
    assert "&amp;" in out
    assert "<tag>" not in out


def test_blocks_to_content_renders_image_block_from_model():
    blocks = [
        PostBlockInput(type="heading", text="Intro", level=2),
        PostBlockInput(type="image", media_id=9, media_url="https://x.com/pic.jpg", text="Alt text"),
        PostBlockInput(type="paragraph", text="Body"),
    ]
    content = gutenberg.blocks_to_content(blocks)
    assert "wp:heading" in content
    assert "wp:image" in content
    assert 'alt="Alt text"' in content
    assert "wp-image-9" in content
    assert "Body" in content


def test_blocks_to_content_skips_image_block_without_media_id():
    """An image block with no media_id can't render anything meaningful —
    it is skipped rather than emitting a broken <img> with no src."""
    blocks = [PostBlockInput(type="image", text="orphan")]
    content = gutenberg.blocks_to_content(blocks)
    assert content == ""


def test_blocks_to_content_accepts_plain_dicts_too():
    blocks = [{"type": "image", "media_id": 3, "media_url": "https://x.com/a.jpg", "text": "alt"}]
    content = gutenberg.blocks_to_content(blocks)
    assert "wp-image-3" in content
