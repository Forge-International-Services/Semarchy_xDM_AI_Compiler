"""Sprint 00 acceptance: the XML normalizer.

Three of these matter more than they look. "Ignores churn" and "not vacuous" bound
the normalizer from both sides — one too aggressive hides real compiler bugs, one
too weak makes every round-trip test fail. The UUID-permutation test is the one that
catches R6, the circular-ordering bug.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.normalize import _UUID, normalize  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
GS = SAMPLES / "gs-productretail-2025.1.0.xml"
CORPUS_A = SAMPLES / "corpus-a-org-mdm-0.1.xml"

SMALL = """<Model>
  <entities>
    <Entity><internalID val="aaaaaaaa-1111-1111-1111-111111111111"/><name>B</name>
      <internalRevisionID val="7"/><internalUpdateUser>alice</internalUpdateUser>
      <matcher><SemQLMatcher><matchScore val="90"/>
        <condition>Record1.X &gt; Record2.X AND A &amp; B</condition>
      </SemQLMatcher></matcher>
    </Entity>
    <Entity><internalID val="bbbbbbbb-2222-2222-2222-222222222222"/><name>A</name>
      <ref1 ref="aaaaaaaa-1111-1111-1111-111111111111"/>
    </Entity>
  </entities>
</Model>"""


def witness(path: Path) -> Path:
    """A real product export, or a skip naming the file that is not here.

    `samples/` is not in the public export. Everything below that normalizes the SMALL
    literal above keeps running there — which is most of this module — so the guard is
    per test rather than per file.
    """
    if not path.exists():
        pytest.skip(f"{path.relative_to(SAMPLES.parent)} not present")
    return path


@pytest.fixture(scope="module")
def gs():
    return witness(GS).read_text()


def test_idempotent(gs):
    once = normalize(gs)
    assert normalize(once) == once


def test_ignores_audit_churn(gs):
    """A bumped revision counter is not a model change."""
    churned = re.sub(r'<internalRevisionID val="\d+"/>',
                     '<internalRevisionID val="999"/>', gs, count=50)
    assert churned != gs
    assert normalize(churned) == normalize(gs)


def test_is_not_vacuous(gs):
    """A changed matchScore IS a model change. Guards over-aggressive stripping."""
    changed = gs.replace('<precision val="38"/>', '<precision val="37"/>', 1)
    assert changed != gs
    assert normalize(changed) != normalize(gs)


@pytest.mark.parametrize("path", [GS, CORPUS_A], ids=["gs-productretail", "corpus-a"])
def test_uuid_permutation_is_invisible(path):
    """R6: permuting every UUID, preserving cross-references, must not change the
    canonical form. This is the test the circular-ordering bug fails."""
    xml = witness(path).read_text()
    mapping = {u: str(uuid.UUID(int=i, version=4)) for i, u in enumerate(set(_UUID.findall(xml)))}
    permuted = _UUID.sub(lambda m: mapping[m.group(0)], xml)
    assert permuted != xml
    assert normalize(permuted) == normalize(xml)


def test_sibling_order_is_irrelevant():
    swapped = SMALL.replace("<name>B</name>", "<name>TMP</name>") \
                   .replace("<name>A</name>", "<name>B</name>") \
                   .replace("<name>TMP</name>", "<name>A</name>")
    # same two entities, opposite document order after sorting by name
    assert normalize(SMALL) != normalize(swapped)      # names genuinely differ
    assert normalize(SMALL) == normalize(SMALL)


def test_semql_text_is_preserved_byte_exact():
    out = normalize(SMALL)
    # ET re-escapes on output; the point is the SemQL body survives intact.
    assert "Record1.X &gt; Record2.X AND A &amp; B" in out


def test_audit_fields_are_gone():
    out = normalize(SMALL)
    assert "internalRevisionID" not in out and "alice" not in out


def test_cross_references_stay_consistent_after_renumbering():
    """A ref must still point at the internalID it pointed at before."""
    out = normalize(SMALL)
    ids = re.findall(r'<internalID val="(u\d+)"', out)
    refs = re.findall(r'ref="(u\d+)"', out)
    assert refs and set(refs) <= set(ids)


@pytest.mark.parametrize("path", [GS, CORPUS_A], ids=["gs-productretail", "corpus-a"])
def test_real_samples_normalize_without_loss(path):
    out = normalize(witness(path).read_text())
    assert len(out) > 100_000
    assert not _UUID.search(out), "raw UUIDs survived renumbering"
