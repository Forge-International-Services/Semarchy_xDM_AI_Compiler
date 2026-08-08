"""The agent's knowledge layer: query the corpus, read the source, cite it.

Sprint 01. Retrieval is dense — see agent/rag.py for the pgvector store and why the
FTS layer it replaced was insufficient.

The rule from AGENT.md this module exists to make enforceable: never act on a snippet.
docs_read() is the cheap way to comply, and it returns admonitions, which is what
snippets most often drop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent import corpus, rag

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Citation:
    file: str
    locator: str
    url: str | None = None

    def render(self) -> str:
        return f"{self.file} § {self.locator}" if self.locator else self.file


@dataclass(frozen=True)
class Hit:
    kind: str
    file: str
    locator: str
    lesson: str
    url: str | None
    text: str
    score: float          # cosine similarity in [0, 1]; higher is better

    def citation(self) -> Citation:
        return Citation(file=self.file, locator=self.locator, url=self.url)


def docs_search(query: str, kind: str | None = None, n: int = 8, *,
                record_gaps: bool = False) -> list[Hit]:
    """Search the corpus. `kind` narrows to one source; omit it to search everything.

    `record_gaps=True` also appends to the gap ledger when the best hit falls below the
    measured support threshold — see agent/knowledge/gaps.py. It defaults to OFF and
    must stay that way: this function is called from tests and from library code, and a
    retrieval that silently writes a file is a side effect nobody asked for. Callers
    that want the ledger opt in here, or call `gaps.record_if_gap(query, hits)`
    themselves.
    """
    hits = [
        Hit(kind=h.kind, file=h.file, locator=h.locator, lesson=h.lesson,
            url=h.url or None, text=h.text, score=h.score)
        for h in rag.search(query, kind=kind, n=n)
    ]
    if record_gaps:
        # Imported here, not at module scope: gaps.py has no runtime dependency on this
        # module (it types its input structurally), and a top-level import would make
        # the pair circular for no gain.
        from agent.knowledge.gaps import record_if_gap
        record_if_gap(query, hits)
    return hits


def docs_read(file: str, section: str | None = None) -> str:
    """Full text of a corpus file, or one heading section of it.

    `section` matches the `locator` a Hit already carries, so going from a hit to its
    full context needs nothing constructed. The returned section includes its
    admonitions — the '> **NOTE**' blocks holding the constraints snippets drop.

    In an export pack the corpus is absent and this refuses, naming the fetcher. It
    does not fall back to a summary: the whole point of the function is that a snippet
    is not the source.
    """
    text = corpus.require(file, f"docs_read({file!r})").read_text()
    if section is None:
        return text

    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m or m.group(2).strip() != section.strip():
            continue
        depth = len(m.group(1))
        for j in range(i + 1, len(lines)):
            nxt = re.match(r"^(#{1,6})\s", lines[j])
            if nxt and len(nxt.group(1)) <= depth:
                return "\n".join(lines[i:j]).rstrip()
        return "\n".join(lines[i:]).rstrip()

    raise KeyError(f"section {section!r} not found in {file}")
