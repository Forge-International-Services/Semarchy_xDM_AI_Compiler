"""Sprint 03 acceptance: the mechanical half — gate cascade and citation validity.

The other half (does the agent give advice a Semarchy consultant would sign off on?)
needs a human reviewer and is deliberately not asserted here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.corpus import FETCHER, have  # noqa: E402
from agent.gates import Gate, GateError, Gates  # noqa: E402
from agent.tools import citation  # noqa: E402

AT = "2026-08-02T12:00:00Z"

#: The citation half of this module asserts against REAL pages in the mirrored docs —
#: that `publishers.md § Overview` resolves and `no-such-page.md` does not. Both halves
#: of that need the pages. The export pack ships without them, so these skip there and
#: the gate cascade above keeps running, which needs nothing but tmp_path.
requires_corpus = pytest.mark.skipif(
    not have(),
    reason=f"knowledge corpus absent (export pack) — restore it with `{FETCHER}`")


@pytest.fixture
def art(tmp_path):
    p = tmp_path / "01-intake.md"
    p.write_text("# intake\n")
    return p


# ---------------------------------------------------------------------- gates
def test_require_blocks_until_earlier_gates_are_approved(tmp_path, art):
    g = Gates(tmp_path / "gates.json")
    with pytest.raises(GateError) as e:
        g.require(Gate.G3_MODEL_PLAN)
    assert "G1_INTAKE" in str(e.value) and "G2_CERTIFICATION" in str(e.value)
    g.approve(Gate.G1_INTAKE, art, AT)
    g.approve(Gate.G2_CERTIFICATION, art, AT)
    g.require(Gate.G3_MODEL_PLAN)          # no longer raises


def test_reopening_a_gate_invalidates_everything_downstream(tmp_path, art):
    """Changing an entity type at G1 makes the certification design meaningless."""
    g = Gates(tmp_path / "gates.json")
    for gate in (Gate.G1_INTAKE, Gate.G2_CERTIFICATION, Gate.G3_MODEL_PLAN,
                 Gate.G4_APPLICATION_PLAN):
        g.approve(gate, art, AT)
    lost = g.reopen(Gate.G2_CERTIFICATION)
    assert lost == [Gate.G2_CERTIFICATION, Gate.G3_MODEL_PLAN, Gate.G4_APPLICATION_PLAN]
    assert g.is_approved(Gate.G1_INTAKE)
    assert not g.is_approved(Gate.G3_MODEL_PLAN)


def test_reapproving_an_earlier_gate_also_cascades(tmp_path, art):
    g = Gates(tmp_path / "gates.json")
    g.approve(Gate.G1_INTAKE, art, AT)
    g.approve(Gate.G2_CERTIFICATION, art, AT)
    g.approve(Gate.G1_INTAKE, art, AT)     # re-approval, not a no-op
    assert not g.is_approved(Gate.G2_CERTIFICATION)


def test_edited_artifact_is_detected_as_stale(tmp_path, art):
    g = Gates(tmp_path / "gates.json")
    g.approve(Gate.G1_INTAKE, art, AT)
    assert not g.stale(Gate.G1_INTAKE, art)
    art.write_text("# intake\nchanged after approval\n")
    assert g.stale(Gate.G1_INTAKE, art)


def test_state_survives_reload(tmp_path, art):
    p = tmp_path / "gates.json"
    Gates(p).approve(Gate.G1_INTAKE, art, AT)
    assert Gates(p).is_approved(Gate.G1_INTAKE)


# ------------------------------------------------------------------ citations
@requires_corpus
def test_real_citations_validate_clean():
    text = ("- Publishers identify the source system "
            "(docs/Design/data-certification/publishers.md § Overview)\n"
            "- Validation exports a CSV "
            "(docs/Design/logical-model/validate-a-model.md § Validation report)\n")
    assert citation.validate(text) == []


@requires_corpus
def test_fabricated_file_is_caught():
    p = citation.validate("- see docs/Design/matching/no-such-page.md § Whatever")
    assert len(p) == 1 and p[0].reason == "file does not exist"


@requires_corpus
def test_fabricated_heading_in_a_real_file_is_caught():
    """The subtler failure: right page, invented section."""
    p = citation.validate(
        "- see docs/Design/data-certification/publishers.md § Invented Section")
    assert len(p) == 1 and "no heading" in p[0].reason


def test_coverage_counts_cited_and_unlabelled_claims():
    # Not marked: coverage() counts labels with a regex and never opens a file.
    text = ("- cited claim (docs/Design/data-certification/publishers.md § Overview)\n"
            f"- judgement call {citation.UNCITED}\n"
            "- bare assertion with no source at all\n")
    cited, unlabelled = citation.coverage(text)
    assert (cited, unlabelled) == (1, 1)


def test_operator_ruling_is_a_labelled_source_not_an_unlabelled_claim():
    """A product-owner or operator ruling is a recorded decision — the same first-class
    `operator` source the decisions register carries. It is neither corpus-citable nor
    the model's judgement, so it gets its own label rather than a borrowed one."""
    text = ("- the queue is named for what it holds [operator ruling — PO session 2026-08-06]\n"
            "- thresholds confirmed at ~95 [product-owner ruling 2026-08-06]\n"
            "- bare assertion with no source at all\n")
    cited, unlabelled = citation.coverage(text)
    assert (cited, unlabelled) == (0, 1)


@requires_corpus
def test_a_citation_wrapped_across_a_line_break_still_resolves():
    """Normal Markdown wrapping. Reporting the fragment before the break as a fake
    citation would be a false accusation, and a zero-tolerance rule that cries wolf
    gets ignored."""
    text = ("- see docs/Design/workflows/workflow-user-tasks.md § Configure\n"
            "  email notifications\n")
    assert citation.validate(text) == []


@requires_corpus
def test_two_citations_in_one_table_cell_both_resolve():
    """A heading never contains another corpus path, so the first citation's section
    must not swallow the second."""
    text = ("| x | docs/Design/workflows/workflow-user-tasks.md § Add a user task, "
            "docs/Admin/notification-servers.md § Create a notification server |\n")
    assert citation.validate(text) == []


@requires_corpus
def test_hardening_did_not_blind_the_check():
    """The false-positive fixes must not make a genuine fake pass."""
    assert citation.validate("- docs/Design/workflows/workflow-user-tasks.md § Not Real")
    assert citation.validate("- docs/Design/workflows/no-such-file.md § Add a user task")


@requires_corpus
def test_a_heading_containing_parentheses_resolves():
    """'References (mandatory)' — the ')' terminates the section match, so the capture
    is a PREFIX of the real heading rather than a superset of it."""
    assert citation.validate(
        "- docs/Integrate/publish-data-with-sql.md § References (mandatory)") == []


@requires_corpus
def test_an_unindented_paragraph_wrap_resolves():
    """Markdown paragraphs wrap at column 0, not just under indentation."""
    text = ("prose citing docs/Integrate/table-structures.md § Primary key\n"
            "columns and continuing.\n")
    assert citation.validate(text) == []


@requires_corpus
def test_a_wrap_does_not_swallow_the_next_block():
    """Un-wrapping must not merge a paragraph into the bullet that follows it, or a
    fabricated citation on the next line would inherit a valid heading."""
    text = ("docs/Integrate/table-structures.md § Primary key\n"
            "\n"
            "- docs/Integrate/table-structures.md § Invented Heading\n")
    assert len(citation.validate(text)) == 1
