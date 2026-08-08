"""Is the knowledge corpus on disk, and what to say when it is not.

The export pack (scripts/pack.py) ships the code and drops the corpus: 564 mirrored
documentation pages, 264 transcripts, the slide and lab text, the notes, and the
retrieval index. That is ~18 MB of material the compiler never reads at build time —
but five places DO read it at runtime, and each of them failed differently when it
was gone:

    agent/tools/semql.py       FileNotFoundError, and IR-017 then refuses every model
    agent/tools/knowledge.py   FileNotFoundError from docs_read, ModuleNotFound from search
    agent/tools/citation.py    NO error at all -- every citation reported as fabricated
    agent/advisory.py          a scenario that passes reported as FAIL
    scripts/build_index.py     FileNotFoundError at import time

The third and fourth are the reason this module exists. A stack trace is unpleasant;
a confident wrong answer is a defect. `citation.validate` cannot tell "this page was
invented" from "this tree has no pages in it", so with the corpus absent it must
REFUSE rather than answer -- the same house rule the compiler follows for an unknown
datatype.

ONE corpus file ships in the pack, and it is documented as an exception rather than
inherited as an accident:

    docs/SemQL/function-list.md

It is load-bearing for validation. `semql.builtins_for()` parses it into the set of
functions each hub technology offers, and `unknown_functions()` -- which IR-017 runs
over every enricher expression, validation condition and match rule -- subtracts that
set. Without the file the set is empty, so LOWER(), METAPHONE() and SOUNDEX() all read
as inventions and IR-017 refuses a model that is correct. It is also a factual function
table rather than prose, which is why shipping it is cheap.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories scripts/pack.py drops. It IMPORTS this tuple rather than restating it:
#: two lists that must agree are a place they will stop agreeing, and the failure
#: would be discovered by a recipient rather than by us.
CORPUS_DIRS = (
    "docs", "transcripts", "slides_text", "labs_text",
    "raw", "notes", "audio", "index", "search",
)

#: The single documented exception, relative to ROOT. See the module docstring.
SHIPPED = ("docs/SemQL/function-list.md",)

FETCHER = "python scripts/fetch_docs.py"

_WAY_BACK = (
    f"The product documentation is re-mirrored with:\n"
    f"    {FETCHER}\n"
    "The Academy-derived material (transcripts/, notes/, slides_text/, labs_text/) and\n"
    "the retrieval index (search/corpus.db) are NOT re-mirrorable from the export pack;\n"
    "they come from the full repository."
)


class CorpusMissing(FileNotFoundError):
    """The corpus this operation reads is not on disk.

    A FileNotFoundError subclass on purpose: callers that already handle a missing
    file keep working, and callers that want to say something better can catch this
    specifically.
    """


def have(*rel: str) -> bool:
    """True when every named path exists under the repository root.

    Called with no arguments it answers the question the tests ask: is the mirrored
    documentation here at all? A tree carrying only the shipped exception answers no,
    which is correct -- one function table is not a corpus.
    """
    if not rel:
        return _has_docs_beyond_the_exception()
    return all((ROOT / r).exists() for r in rel)


def _has_docs_beyond_the_exception() -> bool:
    d = ROOT / "docs"
    if not d.is_dir():
        return False
    shipped = {(ROOT / s).resolve() for s in SHIPPED}
    return any(p.resolve() not in shipped for p in d.rglob("*.md"))


def require(rel: str, what: str) -> Path:
    """Return `ROOT / rel`, or raise CorpusMissing naming the way back.

    `what` says what the caller wanted it for, because "docs/... is missing" alone
    does not tell a reader whether the run is ruined or merely narrower.
    """
    p = ROOT / rel
    if p.exists():
        return p
    raise CorpusMissing(
        f"{what} needs {rel}, which is not in this tree.\n"
        "This is an export pack: the knowledge corpus is deliberately excluded.\n"
        f"{_WAY_BACK}"
    )


def missing(what: str, detail: str = "") -> CorpusMissing:
    """Build the exception for a caller whose dependency is not a single path."""
    return CorpusMissing(
        f"{what} needs the knowledge corpus, which is not in this tree."
        + (f"\n{detail}" if detail else "")
        + "\nThis is an export pack: the corpus is deliberately excluded.\n"
        + _WAY_BACK
    )
