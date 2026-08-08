"""The gap ledger: an "I don't know" that survives the session.

Sprint 12, deliverable 3. `agent.tools.knowledge.docs_search` returns a weak hit and a
strong hit in the same shape, so a question the corpus cannot answer gets answered
anyway. That is the failure mode LESSONS keeps naming — silence read as absence (§1,
§5, §16) — and the instrument itself never says so out loud (§13: five out of six looks
exactly like six out of six).

This module records the misses. A retrieval whose best hit falls below the support
threshold appends an OPEN gap; the same question asked again increments `frequency`
rather than adding a row, because a gap seen repeatedly is a documentation ask and a
gap seen once is a footnote.

    from agent.knowledge.gaps import record_if_gap
    hits = docs_search(q)
    record_if_gap(q, hits)          # returns the Gap, or None when the corpus answered

    python -m agent.knowledge.gaps  # list open gaps, most frequent first


THE SUPPORT THRESHOLD IS MEASURED, NOT GUESSED
==============================================
Measured 2026-08-08 against the live pgvector store (bge-base-en-v1.5, 768d, cosine),
`docs_search(q, n=8)`, score = the best hit in the result set. Two populations:

**Answerable (n=35)** — the 27 confirmed-answerable questions of
`tests/eval/retrieval.yaml` (each with an `expect_file` verified to exist), plus
questions taken from real usage in CLAUDE.md/LESSONS: stepper steps, load statuses,
`persistOptions` fields, cancelling a job in the execution engine, duplicate managers,
business views.

    0.667 0.682 0.690 0.692 0.693 0.717 0.723 0.736 0.737 0.737 0.753 0.754
    0.754 0.756 0.776 0.776 0.776 0.782 0.795 0.797 0.803 0.803 0.816 0.816
    0.816 0.818 0.820 0.821 0.823 0.829 0.837 0.840 0.858 0.862 0.890
    min 0.667   median 0.776   max 0.890

**Unanswerable (n=7)** — invented product features, four absurd and three phrased
entirely in real product vocabulary (Kafka streaming publisher, GPU-accelerated match
rules, a `BLOCKCHAIN_ATTEST` SemQL function):

    0.617 0.620 0.627 0.637 | 0.669 0.689 0.712
    min 0.617   max 0.712

**The distributions overlap in [0.667, 0.712]** — three unanswerable questions score
above the weakest answerable one. No threshold separates them completely. But there is
a genuine empty interval below the answerable floor:

    ... 0.6369 (unanswerable) ___ EMPTY, width 0.030 ___ 0.6670 (answerable) ...

no measurement of either population lands in it. `SUPPORT_THRESHOLD = 0.65` sits near
its midpoint (0.652), with ~0.013 of margin on each side, and yields:

    false gaps  0 / 35 answerable   (a normal session logs nothing)
    real gaps   4 /  7 unanswerable (57%)

That asymmetry is the design, not a compromise: the sprint's own risk table says the
ledger's failure mode is noise, so the threshold is placed for specificity. Everything
the ledger logs is a real miss; it stays quiet about some real misses.

**The known limit, stated rather than hidden.** The three unanswerable questions above
the threshold are exactly the ones written in fluent product vocabulary. A score-only
test cannot catch a plausible question about a feature that does not exist, because the
retriever correctly finds the genuinely-nearby chunks — this is §11/§20 again, syntax is
not semantics. Closing that class needs a second signal (answer-grounding, or an
entailment check between the question and the returned text), which is out of scope
here. Do not read an empty ledger as "the corpus answered everything."

**Re-measuring.** The threshold is a property of the embedding model, the chunking and
the corpus, and it must be re-measured when any of the three changes. The script is
short enough to restate: run `docs_search(q, n=8)` over
`tests/eval/retrieval.yaml` plus a hand-written set of invented features, sort both
score lists, and place the threshold in the widest empty interval below the answerable
minimum. If no such interval exists, the ledger should be turned off rather than tuned
— a ledger that logs noise is worse than none.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

import yaml

ROOT = Path(__file__).resolve().parents[2]

#: Cosine similarity below which a retrieval counts as a MISS. See the module docstring
#: for the measurement this number comes from; it is not a guess and not a round number
#: chosen for looking tidy — 0.65 is the midpoint of the empty interval separating the
#: two measured populations.
SUPPORT_THRESHOLD = 0.65

#: Where the ledger lives. `agent/knowledge/gaps.yaml`, beside the module that owns it,
#: which is this repo's existing convention for durable YAML (`blocks.yaml` beside
#: `blocks.py`, `block_exceptions.yaml` beside its consumer).
#:
#: Why here and not under `out/`: a gap is a property of the CORPUS, not of a scenario.
#: `out/` is per-scenario workspace (`out/s1..s6`), so filing corpus-wide state there
#: would scatter it and hide it from whichever scenario is not currently open. And why
#: a tracked file at all rather than a cache: Principle 1, files over chat — a
#: documentation ask that is not in git before the turn ends did not happen.
#:
#: `SEMARCHY_GAPS_PATH` overrides it, so tests and export packs never write the tracked
#: copy. `pyproject.toml` excludes it from package-data: it is mutable state, and a
#: wheel shipping someone else's ledger — writable only in site-packages — is a bug.
DEFAULT_LEDGER = ROOT / "agent" / "knowledge" / "gaps.yaml"

OPEN = "OPEN"
ANSWERED = "ANSWERED"
WONTFIX = "WONTFIX"
STATUSES = (OPEN, ANSWERED, WONTFIX)

#: Why the retrieval counted as a miss. Two reasons, because they are two different
#: facts: the corpus returned nothing at all, or it returned something too weak.
NO_HITS = "no_hits"
BELOW_SUPPORT_THRESHOLD = "below_support_threshold"

_HEADER = (
    "# Questions the corpus could not answer. Appended by agent/knowledge/gaps.py.\n"
    "#\n"
    "# A row is a MISS, not a low-scoring hit: `top_score` fell below the measured\n"
    "# support threshold (see the module docstring for the measurement). A repeat of\n"
    "# the same question increments `frequency`; it never adds a row.\n"
    "#\n"
    "# `status` is the only field a human edits. OPEN means still unanswered;\n"
    "# ANSWERED means the corpus now covers it; WONTFIX means it never will. The\n"
    "# recorder never changes a status it did not set — a repeat of an ANSWERED gap\n"
    "# bumps frequency and last_seen and leaves the human's call alone, so the\n"
    "# regression is visible in `python -m agent.knowledge.gaps --all`.\n"
)


@runtime_checkable
class Scored(Protocol):
    """Anything with a cosine score — `knowledge.Hit`, `rag.Hit`, a test double.

    Deliberately structural. This module must not import `agent.tools.knowledge`:
    knowledge.py imports it back for the optional hook, and a real import both ways is
    a cycle. It also means the unit tests need no corpus and no database.
    """

    score: float


@dataclass(frozen=True)
class Gap:
    question: str
    top_score: float
    reason: str
    frequency: int
    status: str
    severity: str
    first_seen: str
    last_seen: str

    def to_row(self) -> dict:
        return {
            "question": self.question,
            "top_score": self.top_score,
            "reason": self.reason,
            "frequency": self.frequency,
            "status": self.status,
            "severity": self.severity,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Gap":
        return cls(
            question=row["question"],
            top_score=float(row.get("top_score") or 0.0),
            reason=row.get("reason") or BELOW_SUPPORT_THRESHOLD,
            frequency=int(row.get("frequency") or 1),
            status=row.get("status") or OPEN,
            severity=row.get("severity") or "low",
            first_seen=str(row.get("first_seen") or ""),
            last_seen=str(row.get("last_seen") or ""),
        )


def normalize(question: str) -> str:
    """The dedup key. Casing, whitespace and terminal punctuation only.

    Deliberately conservative. Two differently-worded questions about the same gap stay
    two rows, because merging them by meaning would need exactly the retrieval that just
    failed — and a dedup key that guesses is a ledger that quietly loses asks.

    Concretely: lowercase, strip surrounding quotes, collapse internal whitespace, drop
    trailing `?`, `!` and `.`.
    """
    q = question.strip().strip("\"'").lower()
    q = re.sub(r"\s+", " ", q)
    return q.rstrip("?!. ")


def severity_of(top_score: float, frequency: int, reason: str) -> str:
    """How loudly this gap should ask.

    Frequency dominates, because "asked five times and still unanswered" is a
    documentation ask and "asked once" is a footnote. Depth below the threshold is the
    tie-break: a retrieval that returned nothing, or landed far below support, is a
    subject the corpus does not cover at all rather than one it covers thinly.
    """
    if reason == NO_HITS or frequency >= 5 or top_score < SUPPORT_THRESHOLD - 0.10:
        return "high"
    if frequency >= 2:
        return "medium"
    return "low"


def ledger_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("SEMARCHY_GAPS_PATH") or DEFAULT_LEDGER)


def load(path: str | Path | None = None) -> list[Gap]:
    p = ledger_path(path)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text()) or {}
    return [Gap.from_row(r) for r in (data.get("gaps") or [])]


def save(gaps: Iterable[Gap], path: str | Path | None = None) -> Path:
    p = ledger_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"gaps": [g.to_row() for g in gaps]},
        sort_keys=False, allow_unicode=True, width=100,
    )
    p.write_text(_HEADER + body)
    return p


def is_gap(hits: Iterable[Scored], threshold: float = SUPPORT_THRESHOLD) -> tuple[bool, float, str]:
    """(missed, top_score, reason). The whole decision, with no I/O in it."""
    scores = [float(h.score) for h in hits]
    if not scores:
        return True, 0.0, NO_HITS
    top = max(scores)
    if top < threshold:
        return True, top, BELOW_SUPPORT_THRESHOLD
    return False, top, ""


def record_if_gap(
    question: str,
    hits: Iterable[Scored],
    *,
    threshold: float = SUPPORT_THRESHOLD,
    path: str | Path | None = None,
    today: str | None = None,
) -> Gap | None:
    """Record `question` as a gap if `hits` did not support it. Returns the Gap or None.

    The wire-in point for any `docs_search` caller. Writing is the exception, not the
    rule: on a supported retrieval this touches no file at all, which is what lets the
    library stay side-effect free for callers that never opt in.
    """
    missed, top, reason = is_gap(hits, threshold)
    if not missed:
        return None

    stamp = today or date.today().isoformat()
    key = normalize(question)
    gaps = load(path)

    for i, g in enumerate(gaps):
        if normalize(g.question) != key:
            continue
        # A repeat increments; it never adds a row, and it never overrides the human's
        # `status`. `top_score` keeps the WEAKEST support ever observed — the ledger is
        # a record of how badly the corpus missed, and a later lucky hit does not undo
        # the earlier one.
        freq = g.frequency + 1
        updated = replace(
            g,
            top_score=round(min(g.top_score, top), 4),
            reason=reason if reason == NO_HITS else g.reason,
            frequency=freq,
            severity=severity_of(min(g.top_score, top), freq, reason),
            last_seen=stamp,
        )
        gaps[i] = updated
        save(gaps, path)
        return updated

    fresh = Gap(
        question=question.strip(),
        top_score=round(top, 4),
        reason=reason,
        frequency=1,
        status=OPEN,
        severity=severity_of(top, 1, reason),
        first_seen=stamp,
        last_seen=stamp,
    )
    gaps.append(fresh)
    save(gaps, path)
    return fresh


def open_gaps(path: str | Path | None = None) -> list[Gap]:
    """Open gaps, most frequent first; ties broken by the weakest support."""
    return sorted(
        (g for g in load(path) if g.status == OPEN),
        key=lambda g: (-g.frequency, g.top_score),
    )


def render(gaps: list[Gap]) -> str:
    if not gaps:
        return ("no open gaps.\n"
                "This is not proof the corpus answered everything — the threshold is "
                "tuned for\nspecificity and misses questions phrased in fluent product "
                "vocabulary. See\nagent/knowledge/gaps.py's docstring for what it does "
                "and does not catch.")
    w = max(len(g.question) for g in gaps)
    lines = [f"{'freq':>4}  {'score':>5}  {'sev':<6}  {'question':<{w}}  reason"]
    for g in gaps:
        lines.append(f"{g.frequency:>4}  {g.top_score:>5.3f}  {g.severity:<6}  "
                     f"{g.question:<{w}}  {g.reason}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    show_all = "--all" in argv
    gaps = load() if show_all else open_gaps()
    if show_all:
        gaps = sorted(gaps, key=lambda g: (-g.frequency, g.top_score))
    print(render(gaps))
    if not show_all and gaps:
        print(f"\nledger: {ledger_path()}  ({len(load())} rows total; "
              f"--all to include ANSWERED/WONTFIX)")
    return 0


if __name__ == "__main__":                                          # pragma: no cover
    sys.exit(main(sys.argv[1:]))
