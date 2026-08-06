"""Tests for gutenberg.py — explicit block -> Gutenberg markup rendering.

Deliberately document-agnostic: every test passes blocks the CALLER already
decided on (no document parsing, no heuristics exercised here).
"""

import json

from models import FaqItemInput, PostBlockInput
import gutenberg


def test_paragraph_block_escapes_html():
    out = gutenberg.paragraph_block("A & B < C")
    assert "wp:paragraph" in out
    assert "A &amp; B &lt; C" in out


def test_heading_block_renders_level():
    out = gutenberg.heading_block("Title", level=3)
    assert '"level":3' in out
    assert "<h3" in out and "</h3>" in out


def test_paragraph_block_renders_inline_link():
    """[anchor](url) syntax becomes a real <a href>, not escaped literal text --
    this is the fix for internal/external/CTA links inside article body text."""
    out = gutenberg.paragraph_block("See our [heat recovery guide](https://climtec.md/ru/guide/) for details.")
    assert '<a href="https://climtec.md/ru/guide/">heat recovery guide</a>' in out
    assert "&lt;a" not in out
    assert "[heat recovery guide]" not in out


def test_paragraph_block_inline_link_escapes_surrounding_text():
    out = gutenberg.paragraph_block("A & B [link text](https://x.com/) C < D")
    assert "A &amp; B" in out
    assert '<a href="https://x.com/">link text</a>' in out
    assert "C &lt; D" in out


def test_paragraph_block_inline_link_escapes_url_and_anchor():
    out = gutenberg.paragraph_block('[<script>](https://x.com/?a=1&b=2)')
    assert "<script>" not in out
    assert "&amp;b=2" in out


def test_heading_block_renders_inline_link():
    out = gutenberg.heading_block("Read [more](https://climtec.md/)", level=2)
    assert '<a href="https://climtec.md/">more</a>' in out


def test_paragraph_block_without_brackets_unaffected():
    """Plain text with no [..](..) syntax renders exactly as before."""
    out = gutenberg.paragraph_block("Just a plain sentence, no links here.")
    assert "<a href" not in out
    assert "Just a plain sentence, no links here." in out


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


# ─────────── faq_block: FAQPage JSON-LD + visible Q&A ───────────

def test_faq_block_renders_visible_qa_and_jsonld():
    items = [
        {"question": "What is X?", "answer": "X is Y."},
        {"question": "How much does it cost?", "answer": "It depends."},
    ]
    out = gutenberg.faq_block(items)
    assert "What is X?" in out
    assert "X is Y." in out
    assert "How much does it cost?" in out
    assert 'application/ld+json' in out
    # extract the JSON-LD payload and validate it's real, well-formed FAQPage schema
    start = out.index("<script type=\"application/ld+json\">") + len("<script type=\"application/ld+json\">")
    end = out.index("</script>", start)
    payload = json.loads(out[start:end])
    assert payload["@type"] == "FAQPage"
    assert len(payload["mainEntity"]) == 2
    assert payload["mainEntity"][0]["@type"] == "Question"
    assert payload["mainEntity"][0]["name"] == "What is X?"
    assert payload["mainEntity"][0]["acceptedAnswer"]["@type"] == "Answer"
    assert payload["mainEntity"][0]["acceptedAnswer"]["text"] == "X is Y."


def test_faq_block_accepts_faqiteminput_models():
    items = [FaqItemInput(question="Q1", answer="A1")]
    out = gutenberg.faq_block(items)
    assert "Q1" in out and "A1" in out


def test_faq_block_escapes_html_in_question_and_answer():
    items = [{"question": "A & B?", "answer": "<script>bad</script>"}]
    out = gutenberg.faq_block(items)
    assert "<script>bad</script>" not in out.split("application/ld+json")[0]  # not raw in visible html
    assert "&amp;" in out


def test_faq_block_skips_incomplete_items():
    items = [{"question": "", "answer": "orphan answer"}, {"question": "Real Q", "answer": "Real A"}]
    out = gutenberg.faq_block(items)
    assert "orphan answer" not in out
    assert "Real Q" in out


def test_faq_block_empty_items_renders_nothing():
    assert gutenberg.faq_block([]) == ""


def test_faq_block_with_intro_text():
    out = gutenberg.faq_block([{"question": "Q", "answer": "A"}], intro_text="Common questions:")
    assert "Common questions:" in out


def test_blocks_to_content_renders_faq_block_from_model():
    blocks = [
        PostBlockInput(type="heading", text="FAQ", level=2),
        PostBlockInput(type="faq", faq_items=[FaqItemInput(question="Q1", answer="A1")]),
    ]
    content = gutenberg.blocks_to_content(blocks)
    assert "Q1" in content
    assert "FAQPage" in content
