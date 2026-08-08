"""Sprint 12 deliverable 3: the gap ledger.

Every test here runs on synthetic `Scored` doubles and a tmp_path ledger. None of them
needs the corpus, the embedding model or the pgvector store — which is the point of
`gaps.Scored` being a structural Protocol. The THRESHOLD itself was measured against the
live store on 2026-08-08 and the numbers are pinned in the module docstring; what is
tested here is the behaviour that threshold drives.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.knowledge import gaps as G  # noqa: E402


@dataclass(frozen=True)
class FakeHit:
    """Structurally a `knowledge.Hit` as far as this module is concerned."""
    score: float


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "gaps.yaml"


def _rows(ledger):
    return (yaml.safe_load(ledger.read_text()) or {}).get("gaps") or []


# --------------------------------------------------------------------------- threshold

def test_threshold_is_the_measured_value():
    """Pinned, so a future edit to the constant has to face the docstring measurement."""
    assert G.SUPPORT_THRESHOLD == 0.65


def test_strong_support_is_not_a_gap_and_writes_nothing(ledger):
    hits = [FakeHit(0.82), FakeHit(0.74), FakeHit(0.71)]
    assert G.record_if_gap("how do I create a matcher?", hits, path=ledger) is None
    assert not ledger.exists(), "a supported retrieval must not touch the filesystem"


def test_weak_support_is_a_gap(ledger):
    g = G.record_if_gap("how do I enable the holographic lineage viewer?",
                        [FakeHit(0.62), FakeHit(0.61)], path=ledger)
    assert g is not None
    assert g.reason == G.BELOW_SUPPORT_THRESHOLD
    assert g.status == G.OPEN
    assert g.top_score == 0.62
    assert g.frequency == 1


def test_the_top_hit_decides_not_the_mean(ledger):
    """One strong hit answers the question even in a mostly-weak result set."""
    assert G.record_if_gap("q", [FakeHit(0.71), FakeHit(0.30), FakeHit(0.21)],
                           path=ledger) is None


def test_hierarchy_reordering_does_not_hide_support(ledger):
    """`rag._apply_hierarchy` can put a lower-scoring docs hit first. The gap test reads
    the MAX score, not hits[0], so a reordered result set is still counted as supported."""
    assert G.record_if_gap("q", [FakeHit(0.649), FakeHit(0.83)], path=ledger) is None


def test_empty_result_set_is_a_gap_with_its_own_reason(ledger):
    g = G.record_if_gap("what is the zebra-stripe pricing tier?", [], path=ledger)
    assert g.reason == G.NO_HITS
    assert g.top_score == 0.0
    assert g.severity == "high", "nothing at all is a stronger signal than a weak hit"


def test_exactly_at_the_threshold_is_supported(ledger):
    assert G.record_if_gap("q", [FakeHit(G.SUPPORT_THRESHOLD)], path=ledger) is None


def test_threshold_is_overridable_per_call(ledger):
    assert G.record_if_gap("q", [FakeHit(0.70)], path=ledger) is None
    assert G.record_if_gap("q", [FakeHit(0.70)], threshold=0.75, path=ledger) is not None


def test_is_gap_is_pure(ledger):
    assert G.is_gap([FakeHit(0.9)]) == (False, 0.9, "")
    assert G.is_gap([]) == (True, 0.0, G.NO_HITS)
    assert G.is_gap([FakeHit(0.5)]) == (True, 0.5, G.BELOW_SUPPORT_THRESHOLD)
    assert not ledger.exists()


# ------------------------------------------------------------------- append and dedup

def test_append_adds_one_row_per_distinct_question(ledger):
    G.record_if_gap("first invented feature?", [FakeHit(0.5)], path=ledger)
    G.record_if_gap("second invented feature?", [FakeHit(0.5)], path=ledger)
    assert len(_rows(ledger)) == 2


def test_a_repeat_increments_frequency_rather_than_adding_a_row(ledger):
    """The sprint's acceptance criterion, literally."""
    for _ in range(3):
        G.record_if_gap("how do I enable GPU-accelerated matching?",
                        [FakeHit(0.61)], path=ledger)
    rows = _rows(ledger)
    assert len(rows) == 1
    assert rows[0]["frequency"] == 3


def test_dedup_normalizes_case_whitespace_and_terminal_punctuation(ledger):
    for q in ("How do I enable X?",
              "how do i enable x",
              "  How   do I enable X?!  ",
              '"How do I enable X."'):
        G.record_if_gap(q, [FakeHit(0.5)], path=ledger)
    rows = _rows(ledger)
    assert len(rows) == 1, f"normalization failed to merge: {[r['question'] for r in rows]}"
    assert rows[0]["frequency"] == 4
    assert rows[0]["question"] == "How do I enable X?", "the FIRST wording is kept verbatim"


def test_normalization_does_not_merge_differently_worded_questions(ledger):
    """Conservative on purpose: merging by meaning needs the retrieval that just failed."""
    G.record_if_gap("how do I enable the lineage viewer?", [FakeHit(0.5)], path=ledger)
    G.record_if_gap("how is the lineage viewer enabled?", [FakeHit(0.5)], path=ledger)
    assert len(_rows(ledger)) == 2


def test_normalize_is_stated_and_stable():
    assert G.normalize('  "How   Do I?!. "') == "how do i"
    assert G.normalize("plain") == "plain"


# ------------------------------------------------------------------ dates and severity

def test_first_seen_is_pinned_and_last_seen_advances(ledger):
    G.record_if_gap("q?", [FakeHit(0.5)], path=ledger, today="2026-08-08")
    g = G.record_if_gap("q?", [FakeHit(0.5)], path=ledger, today="2026-09-01")
    assert g.first_seen == "2026-08-08"
    assert g.last_seen == "2026-09-01"


def test_repeat_keeps_the_weakest_support_ever_seen(ledger):
    G.record_if_gap("q?", [FakeHit(0.60)], path=ledger)
    g = G.record_if_gap("q?", [FakeHit(0.64)], path=ledger)
    assert g.top_score == 0.60


def test_severity_escalates_with_frequency(ledger):
    q, hits = "q?", [FakeHit(0.63)]
    assert G.record_if_gap(q, hits, path=ledger).severity == "low"
    assert G.record_if_gap(q, hits, path=ledger).severity == "medium"
    for _ in range(3):
        last = G.record_if_gap(q, hits, path=ledger)
    assert last.frequency == 5 and last.severity == "high"


def test_severity_escalates_with_depth_below_support(ledger):
    assert G.severity_of(0.63, 1, G.BELOW_SUPPORT_THRESHOLD) == "low"
    assert G.severity_of(0.40, 1, G.BELOW_SUPPORT_THRESHOLD) == "high"


# ------------------------------------------------------------------- status is human's

def test_a_repeat_never_overrides_a_human_set_status(ledger):
    G.record_if_gap("q?", [FakeHit(0.5)], path=ledger)
    rows = _rows(ledger)
    rows[0]["status"] = G.WONTFIX
    ledger.write_text(yaml.safe_dump({"gaps": rows}))

    g = G.record_if_gap("q?", [FakeHit(0.5)], path=ledger)
    assert g.status == G.WONTFIX
    assert g.frequency == 2, "the sighting is still counted"


def test_open_gaps_excludes_answered_and_sorts_most_frequent_first(ledger):
    G.record_if_gap("once?", [FakeHit(0.5)], path=ledger)
    for _ in range(3):
        G.record_if_gap("thrice?", [FakeHit(0.5)], path=ledger)
    G.record_if_gap("fixed?", [FakeHit(0.5)], path=ledger)
    rows = _rows(ledger)
    next(r for r in rows if r["question"] == "fixed?")["status"] = G.ANSWERED
    ledger.write_text(yaml.safe_dump({"gaps": rows}))

    got = G.open_gaps(ledger)
    assert [g.question for g in got] == ["thrice?", "once?"]


# ----------------------------------------------------------------- storage and round-trip

def test_ledger_round_trips_every_field(ledger):
    G.record_if_gap("q?", [FakeHit(0.62)], path=ledger, today="2026-08-08")
    (g,) = G.load(ledger)
    assert g.to_row() == {
        "question": "q?", "top_score": 0.62, "reason": G.BELOW_SUPPORT_THRESHOLD,
        "frequency": 1, "status": "OPEN", "severity": "low",
        "first_seen": "2026-08-08", "last_seen": "2026-08-08",
    }


def test_ledger_carries_its_own_header(ledger):
    G.record_if_gap("q?", [FakeHit(0.5)], path=ledger)
    assert ledger.read_text().startswith("# Questions the corpus could not answer")


def test_load_of_a_missing_ledger_is_empty_not_an_error(tmp_path):
    assert G.load(tmp_path / "nope.yaml") == []


def test_env_var_selects_the_ledger(tmp_path, monkeypatch):
    p = tmp_path / "env-gaps.yaml"
    monkeypatch.setenv("SEMARCHY_GAPS_PATH", str(p))
    G.record_if_gap("q?", [FakeHit(0.5)])
    assert p.is_file()


def test_default_ledger_is_beside_the_module_not_under_out(monkeypatch):
    monkeypatch.delenv("SEMARCHY_GAPS_PATH", raising=False)
    assert G.ledger_path() == G.ROOT / "agent" / "knowledge" / "gaps.yaml"


# ------------------------------------------------------------------------------- CLI

def test_cli_lists_open_gaps_most_frequent_first(ledger, monkeypatch, capsys):
    monkeypatch.setenv("SEMARCHY_GAPS_PATH", str(ledger))
    G.record_if_gap("rare question?", [FakeHit(0.5)], path=ledger)
    for _ in range(2):
        G.record_if_gap("common question?", [FakeHit(0.5)], path=ledger)

    assert G.main([]) == 0
    out = capsys.readouterr().out
    assert out.index("common question?") < out.index("rare question?")


def test_cli_on_an_empty_ledger_says_so_without_claiming_completeness(monkeypatch, capsys,
                                                                     tmp_path):
    monkeypatch.setenv("SEMARCHY_GAPS_PATH", str(tmp_path / "none.yaml"))
    G.main([])
    out = capsys.readouterr().out
    assert "no open gaps" in out
    assert "not proof" in out, "an empty ledger must not read as 'the corpus knows all'"


# ------------------------------------------------------------------------- the wire-in

def test_docs_search_does_not_record_by_default(monkeypatch, tmp_path):
    """The constraint that protects every existing caller: no silent writes."""
    import agent.tools.knowledge as K

    p = tmp_path / "gaps.yaml"
    monkeypatch.setenv("SEMARCHY_GAPS_PATH", str(p))
    monkeypatch.setattr(K.rag, "search", lambda *a, **k: [])

    K.docs_search("an unanswerable question?")
    assert not p.exists()

    K.docs_search("an unanswerable question?", record_gaps=True)
    assert p.is_file()
    assert G.load(p)[0].reason == G.NO_HITS
