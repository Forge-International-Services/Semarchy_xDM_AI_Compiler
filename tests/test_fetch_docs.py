"""Regression tests for the documentation mirror.

Both bugs here were found once, fixed once, and one of them was silently lost again
because nothing tested it. The corpus is what the agent reasons from, so a
conversion defect degrades every downstream phase.

Pure functions only — no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_docs import _image_path, html_to_markdown  # noqa: E402

BASE = "https://semarchy.com/doc/semarchy-xdm/xdm/latest/Design/matching/matching.html"


def md(html: str) -> str:
    return html_to_markdown(BeautifulSoup(f"<article>{html}</article>", "lxml").article, BASE)


# ------------------------------------------------- empty inline elements (guard)
def test_heading_anchor_does_not_leak_into_the_heading():
    """Antora puts an empty <a class="anchor"> in every heading. Decorating it
    emitted '## [](url#_overview)Overview' — on every heading of every page, which
    also put the anchor URL into the search index."""
    out = md('<h2 id="_overview"><a class="anchor" href="#_overview"></a>Overview</h2>')
    assert out.strip() == "## Overview"
    assert "[](" not in out


def test_callout_marker_does_not_emit_stray_bold():
    """<i class="conum"> is empty; decorating it produced '****1**'."""
    out = md('<table><tr><td><i class="conum" data-value="1"></i><b>1</b></td>'
             "<td>We select all columns.</td></tr></table>")
    assert "| **1** |" in out
    assert "****" not in out


@pytest.mark.parametrize("html", [
    '<p><a href="/x"></a>text</p>',
    "<p><strong></strong>text</p>",
    "<p><em></em>text</p>",
    "<p><code></code>text</p>",
])
def test_every_empty_inline_tag_is_dropped(html):
    assert md(html).strip() == "text"


def test_non_empty_inline_tags_still_render():
    out = md('<p><strong>bold</strong> <em>it</em> <code>c</code> '
             '<a href="/y">link</a></p>')
    assert "**bold**" in out and "*it*" in out and "`c`" in out and "[link](" in out


def test_admonitions_survive():
    out = md('<div class="admonitionblock note"><table><tr>'
             '<td class="icon">Note</td><td class="content">Preview only.</td>'
             "</tr></table></div>")
    assert "> **NOTE** Preview only." in out


def test_code_block_keeps_language_and_caption():
    out = md('<div class="listingblock"><div class="title">Query</div><pre>'
             '<code class="language-sql">select 1</code></pre></div>')
    assert "*Query*" in out and "```sql" in out and "select 1" in out


# ---------------------------------------------------- image path collisions
def test_same_basename_in_different_sections_does_not_collide():
    """menu.svg exists under both Design/ and Discovery/. Keying by basename made
    them one entry, and the download loop silently dropped the loser."""
    a = _image_path("https://x/doc/semarchy-xdm/xdm/latest/Design/_images/menu.svg")
    b = _image_path("https://x/doc/semarchy-xdm/xdm/latest/Discovery/_images/menu.svg")
    assert a != b
    assert a == "Design/menu.svg" and b == "Discovery/menu.svg"


def test_image_path_is_stable_for_the_same_source():
    src = "https://x/doc/semarchy-xdm/xdm/latest/Manage/_images/switch_model_button.png"
    assert _image_path(src) == _image_path(src) == "Manage/switch_model_button.png"


def test_image_outside_an_images_dir_still_gets_a_path():
    assert _image_path("https://x/whatever/logo.png") == "_root/logo.png"


# ------------------------------------------------- duplicate page title
def test_leading_h1_matching_the_title_is_dropped():
    """The file already opens with '# {title}'; the article's copy repeats it."""
    from fetch_docs import drop_leading_title
    body = "# Manage REST clients\n\nREST clients extend xDM."
    assert drop_leading_title(body, "Manage REST clients") == "REST clients extend xDM."


def test_nbsp_in_the_title_still_matches():
    """Titles routinely contain U+00A0, which _inline turns into a plain space, so
    the two forms are not equal as strings."""
    from fetch_docs import drop_leading_title
    assert drop_leading_title("# Manage REST clients\n\nBody.",
                              "Manage REST\xa0clients") == "Body."


def test_a_different_leading_h1_is_kept():
    from fetch_docs import drop_leading_title
    body = "# Something Else\n\nBody."
    assert drop_leading_title(body, "Manage REST clients") == body


def test_body_without_a_leading_heading_is_untouched():
    from fetch_docs import drop_leading_title
    assert drop_leading_title("Just prose.", "Title") == "Just prose."
