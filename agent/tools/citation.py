"""Validate that every citation in an agent-authored document actually resolves.

Sprint 03, zero-tolerance criterion: a FABRICATED citation is worse than none. An
uncited claim is visibly the model's judgement; a citation pointing at a file or
heading that does not exist reads as sourced and is not.

Citations use the form rendered by tools.knowledge.Citation:

    docs/Design/matching/create-a-matcher.md § Create a matcher
    notes/01-modeling-integration.md § Key concepts
    transcripts/04_...Demo_Discovery_EN.txt @3:41

Claims the agent cannot source must be labelled `[uncited — model judgement]`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent import corpus

ROOT = Path(__file__).resolve().parents[2]

# "<corpus path> § <heading>" or "<corpus path> @M:SS"
_CITE = re.compile(
    r"\b(?P<file>(?:docs|notes|transcripts|labs_text|slides_text)/[^\s,;)\]]+\.(?:md|txt))"
    # Section runs to a real terminator — ')', ']', '|' or end of line. A non-greedy
    # match stops at the first space and silently truncates multi-word headings
    # ("Validation report" -> "Validation"), which then fails as a fake citation.
    r"(?:\s*§\s*(?P<section>[^\n|)\]]+))?"
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
UNCITED = "[uncited — model judgement]"
# A third provenance class, added when product-owner rulings started landing in the
# narrative docs: a statement sourced from the operator or product owner is neither a
# corpus citation nor the model's judgement — it is a recorded decision, the same
# `operator` source the decisions register treats as first-class. The label carries the
# date so the ruling can be traced to its session.
_OPERATOR = re.compile(r"\[(?:operator|product-owner) ruling[^\]]*\]")


@dataclass(frozen=True)
class Problem:
    citation: str
    reason: str


def _headings(path: Path) -> set[str]:
    return {m.group(2).strip() for m in _HEADING.finditer(path.read_text())}


_CORPUS = r"(?:docs|notes|transcripts|labs_text|slides_text)/"
# A wrapped line continues its predecessor unless it starts a new block. Matching only
# INDENTED continuations missed the common case: Markdown paragraphs wrap at column 0.
_WRAP = re.compile(r"\n(?![ \t]*(?:$|#|[-*+] |\d+\. |\||>|```))[ \t]*")


def validate(text: str, root: Path = ROOT) -> list[Problem]:
    """Return every citation in `text` that does not resolve. Empty list means clean.

    Prose is un-wrapped first: a citation split across a line break is normal Markdown,
    and treating the fragment before the break as the whole heading would report a real
    citation as fabricated.

    RAISES CorpusMissing in an export pack. This check answers "does this page exist"
    by looking for the page, so with no pages on disk it answers "fabricated" to every
    citation in the repository — confidently, silently, and wrongly. That is a worse
    failure than any stack trace, and it is the one this guard exists for. A checker
    that cannot see its evidence must refuse, not guess.

    `root` is honoured as given: a caller that has built its own tree of pages is
    testing the matcher, not the corpus, and the guard stays out of its way.
    """
    text = _WRAP.sub(" ", text)
    if root == ROOT and _CITE.search(text) and not corpus.have():
        raise corpus.missing(
            "Citation validation",
            "Every cited page would be reported as fabricated, which is not an answer\n"
            "this check is entitled to give when it cannot see the pages.",
        )
    problems: list[Problem] = []
    for m in _CITE.finditer(text):
        rel, section = m.group("file"), (m.group("section") or "").strip()
        # Two citations in one table cell: the section runs to the cell boundary and
        # swallows the second. A heading never contains another corpus path, so cut
        # there.
        section = re.split(r",?\s*" + _CORPUS, section)[0].strip()
        path = root / rel
        shown = f"{rel} § {section}" if section else rel
        if not path.is_file():
            problems.append(Problem(shown, "file does not exist"))
            continue
        if not section:
            continue
        headings = _headings(path)
        if section in headings:
            continue
        # An undelimited citation at end of line swallows the prose that follows it,
        # so the captured "section" is a real heading plus a trailing sentence. Try
        # progressively shorter prefixes: if one is a real heading, the citation
        # resolves and the remainder was prose. Accusing it of being fabricated would
        # be a false positive, and a zero-tolerance rule that cries wolf is worthless.
        words = section.split()
        # Captured MORE than the heading: an undelimited citation swallowed the prose
        # after it. Some prefix of what we captured is the real heading.
        if any(" ".join(words[:n]) in headings for n in range(len(words), 0, -1)):
            continue
        # Captured LESS than the heading: a heading containing ')' — such as
        # "References (mandatory)" — is cut short by the terminator set. A citation
        # naming a real prefix of a heading is not fabricated.
        if any(h.startswith(section) for h in headings):
            continue
        problems.append(Problem(shown, f"no heading {section!r} in {rel}"))
    return problems


_BULLET = re.compile(r"\s*(?:[-*+]|\d+\.)\s+\S")


def claims(text: str) -> list[str]:
    """Bullets and numbered items, with their wrapped continuation lines attached.

    A citation routinely lands on the line after the claim it supports, because that
    is how prose wraps. Treating each physical line as a claim scored well-cited
    documents at 0%.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if _BULLET.match(line):
            out.append(line)
        elif out and line.strip() and not line.lstrip().startswith("#"):
            out[-1] += " " + line.strip()          # continuation of the current claim
    return [c for c in out if c]


def coverage(text: str) -> tuple[int, int]:
    """(cited, unlabelled) claim counts, for the >=90%-sourced criterion."""
    cs = claims(text)
    cited = sum(1 for c in cs if _CITE.search(c))
    labelled = sum(1 for c in cs
                   if (UNCITED in c or _OPERATOR.search(c)) and not _CITE.search(c))
    return cited, len(cs) - cited - labelled
