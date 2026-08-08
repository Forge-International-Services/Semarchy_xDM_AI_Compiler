"""Dense retrieval over the corpus, backed by Postgres + pgvector.

    python -m agent.rag build      # embed every chunk and load it into pgvector
    python -m agent.rag "query"    # search

Replaces the FTS layer in search/semarchy_search.py, which was a proof of concept:
it ANDs bare terms, so natural-language questions returned nothing, and it plateaued
at recall@3 0.85 / recall@1 0.63 on tests/eval/retrieval.yaml.

Embeddings run locally. The corpus contains Semarchy-confidential slide decks (see
README § Provenance), so the text is never sent to a third-party embedding API.

Chunks and their citation locators come from search/corpus.db, which stays the
chunking authority — this module adds vectors, it does not re-chunk.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from agent import corpus

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DB = ROOT / "search" / "corpus.db"
DSN = os.environ.get("SEMARCHY_RAG_DSN", "postgresql:///semarchy_corpus")

# bge-base-en-v1.5: 768 dims, strong on retrieval benchmarks, small enough to embed
# the whole corpus on-device in well under a minute.
MODEL = "BAAI/bge-base-en-v1.5"
DIM = 768

# bge models are trained with an asymmetric objective: queries carry this instruction,
# passages do not. Omitting it measurably degrades retrieval.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Changelogs answer "what changed in version X", not "how do I do X". The FTS layer
# filtered these and dense retrieval needs it just as much: release notes restate every
# feature in the product, so they are semantically near almost any how-to question.
_NOISE = ("docs/Install/release-notes", "docs/Install/upgrade", "license-information")
_HISTORY_WORDS = {"upgrade", "release", "version", "migrate", "migration",
                  "changelog", "deprecated", "new"}

# AGENT.md's source hierarchy. Applied as a post-filter over results of COMPARABLE
# similarity, never as a filter — cross-source corroboration is what makes this corpus
# worth more than the docs alone. Cosine similarity is calibrated and comparable across
# queries, so a fixed band means the same thing everywhere; bm25 scores were not.
KIND_RANK = {"docs": 0, "notes": 1, "transcript": 2, "labs": 3, "slides": 4}
HIERARCHY_BAND = 0.03

_model = None


def _encode(texts: list[str], is_query: bool = False):
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as e:                                # pragma: no cover
            raise corpus.CorpusMissing(
                "Dense retrieval needs a local embedding model, and\n"
                "sentence-transformers is not installed.\n"
                "    pip install -e '.[rag]'\n"
                "It is an optional extra — it pulls in torch — because the compiler\n"
                "never retrieves. Only the authoring phases do."
            ) from e

        _model = SentenceTransformer(MODEL, device="mps")
    if is_query:
        texts = [QUERY_PREFIX + t for t in texts]
    return _model.encode(texts, normalize_embeddings=True, batch_size=64,
                         show_progress_bar=not is_query)


@dataclass(frozen=True)
class Hit:
    kind: str
    file: str
    locator: str
    lesson: str
    url: str | None
    text: str
    score: float


def _connect():
    try:
        import psycopg
    except ModuleNotFoundError as e:                                    # pragma: no cover
        raise corpus.CorpusMissing(
            "Dense retrieval needs the pgvector store, and psycopg is not installed.\n"
            "    pip install -e '.[rag]'\n"
            "It is an optional extra because the compiler never retrieves — only the\n"
            "authoring phases do, and only when the corpus is present."
        ) from e
    return psycopg.connect(DSN)


def _require_corpus_db():
    """The chunk store search() reads. Absent in an export pack, by design.

    Checked BEFORE the model is loaded, because embedding a query takes seconds and
    downloads a model the first time — an expensive way to arrive at a missing file.
    """
    if not CORPUS_DB.is_file():
        raise corpus.missing(
            "Dense retrieval",
            f"{CORPUS_DB.relative_to(ROOT)} holds the chunked corpus and its citation\n"
            "locators. Rebuild it from the full repository with:\n"
            "    python search/semarchy_search.py index\n"
            "    python -m agent.rag build",
        )


SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
    id        bigserial PRIMARY KEY,
    kind      text NOT NULL,
    chapter   text,
    lesson    text,
    asset     text,
    file      text NOT NULL,
    locator   text,
    start_s   double precision,
    url       text,
    text      text NOT NULL,
    embedding vector({DIM}) NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_kind_idx ON chunks (kind);
"""


def build() -> None:
    """Embed every chunk in corpus.db and load it into pgvector."""
    _require_corpus_db()
    rows = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro", uri=True).execute(
        "SELECT kind, chapter, lesson, asset, file, locator, start_s, url, text FROM chunks"
    ).fetchall()
    print(f"embedding {len(rows)} chunks with {MODEL} ...", flush=True)
    vectors = _encode([r[-1] for r in rows])

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("TRUNCATE chunks RESTART IDENTITY;")
        with cur.copy(
            "COPY chunks (kind, chapter, lesson, asset, file, locator, start_s, url,"
            " text, embedding) FROM STDIN"
        ) as copy:
            for row, vec in zip(rows, vectors):
                copy.write_row([*row, "[" + ",".join(f"{x:.6f}" for x in vec) + "]"])
        # Exact search over a few thousand vectors is sub-millisecond, so no ANN index:
        # ivfflat/hnsw would only trade recall away for speed we do not need.
        cur.execute("ANALYZE chunks;")
        conn.commit()
    print(f"loaded {len(rows)} chunks into {DSN}")


def search(query: str, kind: str | None = None, n: int = 8) -> list[Hit]:
    _require_corpus_db()
    vec = "[" + ",".join(f"{x:.6f}" for x in _encode([query], is_query=True)[0]) + "]"

    where, params = [], [vec]
    if kind:
        where.append("kind = %s")
        params.append(kind)
    if not (_HISTORY_WORDS & set(re.findall(r"[a-z]+", query.lower()))):
        where += ["file NOT LIKE %s"] * len(_NOISE)
        params += [f"%{n_}%" for n_ in _NOISE]

    sql = (
        "SELECT kind, file, locator, lesson, url, text, 1 - (embedding <=> %s::vector)"
        " FROM chunks"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    # Over-fetch so the hierarchy has something to reorder: a docs hit just outside
    # the top n can still outrank a transcript inside it.
    params += [vec, max(n * 4, 20)]
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        hits = [Hit(*r[:5], text=r[5], score=r[6]) for r in cur.fetchall()]
    return _apply_hierarchy(hits)[:n]


def _apply_hierarchy(hits: list[Hit]) -> list[Hit]:
    """Prefer authoritative sources among hits of comparable similarity."""
    return sorted(
        hits,
        key=lambda h: (-round(h.score / HIERARCHY_BAND), KIND_RANK.get(h.kind, 9)),
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    elif len(sys.argv) > 1:
        for h in search(" ".join(sys.argv[1:])):
            print(f"{h.score:.3f}  {h.kind:10s} {h.file} § {h.locator}")
    else:
        sys.exit(__doc__)
