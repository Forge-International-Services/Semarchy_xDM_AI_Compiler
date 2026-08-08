"""Sprint 01 acceptance: the knowledge layer.

EVERY test here reads the corpus — that is what the knowledge layer is. The export
pack ships without it, so in a packed tree the whole module skips rather than failing.
The skip is not a softening of anything: none of these assertions changed, and they
all run in the full repository.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.corpus import FETCHER, have  # noqa: E402
from agent.tools.knowledge import Citation, docs_read, docs_search  # noqa: E402

pytestmark = pytest.mark.skipif(
    not have(),
    reason=f"knowledge corpus absent (export pack) — restore it with `{FETCHER}`")

GOLDEN = yaml.safe_load((Path(__file__).parent / "eval" / "retrieval.yaml").read_text())


@pytest.fixture(scope="session")
def results():
    """One search per golden question, reused across the recall assertions."""
    return [(c, [h.file for h in docs_search(c["q"], kind="docs", n=3)]) for c in GOLDEN]


def _recall(results, k: int) -> float:
    return sum(c["expect_file"] in files[:k] for c, files in results) / len(results)


def test_expected_files_all_exist():
    root = Path(__file__).resolve().parents[1]
    missing = [c["expect_file"] for c in GOLDEN if not (root / c["expect_file"]).is_file()]
    assert not missing, f"golden set references files that do not exist: {missing}"


def test_recall_at_3(results):
    r = _recall(results, 3)
    misses = [c["q"] for c, files in results if c["expect_file"] not in files[:3]]
    assert r >= 0.90, f"recall@3 = {r:.2f} < 0.90; missed: {misses}"


def test_recall_at_1(results):
    r = _recall(results, 1)
    assert r >= 0.70, f"recall@1 = {r:.2f} < 0.70"


def test_source_hierarchy_prefers_docs_within_the_similarity_band():
    """AGENT.md's hierarchy: among comparable hits, docs outranks a transcript.

    Verifies the post-filter actually fires — a docs hit is allowed to sit above a
    transcript that scored slightly higher, provided both are within the band.
    """
    hits = docs_search("how do I create a matcher", n=8)
    kinds = [h.kind for h in hits]
    assert "docs" in kinds and "transcript" in kinds, f"need both kinds; got {kinds}"
    assert kinds.index("docs") < kinds.index("transcript")

    from agent.rag import HIERARCHY_BAND
    promoted = [
        (a, b) for a, b in zip(hits, hits[1:])
        if a.kind == "docs" and b.kind != "docs" and a.score < b.score
    ]
    assert promoted, "hierarchy never reordered anything; band may be too narrow"
    for a, b in promoted:
        assert b.score - a.score <= HIERARCHY_BAND, "promoted across a real quality gap"


def test_kind_filter_is_respected():
    assert all(h.kind == "docs" for h in docs_search("how do I create a matcher", kind="docs"))


def test_docs_read_returns_admonitions():
    """The '> **NOTE**' blocks are where preconditions live; snippets drop them."""
    section = docs_read("docs/Design/data-certification/publishers.md", "Overview")
    assert "> **NOTE**" in section
    assert "Identifying clearly and declaring the publishers is important" in section


def test_docs_read_section_stops_at_next_heading():
    section = docs_read("docs/Design/data-certification/publishers.md", "Overview")
    assert section.startswith("## Overview")
    assert "## Create a publisher" not in section


def test_docs_read_unknown_section_raises():
    with pytest.raises(KeyError):
        docs_read("docs/Design/data-certification/publishers.md", "No Such Section")


def test_citation_renders_file_and_locator():
    c = Citation(file="docs/Design/matching/matching.md", locator="Match and merge")
    assert c.render() == "docs/Design/matching/matching.md § Match and merge"
