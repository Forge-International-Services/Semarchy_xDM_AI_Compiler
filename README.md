# Semarchy xDM AI Compiler

An agent pipeline that turns natural-language MDM requirements into a working
**Semarchy xDM** application: requirements → YAML intermediate representation →
`metaDataExport` XML → import → deploy → run.

```
requirements (natural language)
   ↓  an LLM authors the IR, consulting the product documentation when unsure
agent/ir/schema.py          the IR — no UUIDs, names only
   ↓  validate (blocking rules) + advise (advisory questions, never blocking)
agent/compile/emit*.py      deterministic XML. The LLM NEVER writes XML.
   ↓  agent/safety.py preflight → agent/rest.py write paths
   ↓  deploy → integration job
a live xDM instance with data in it
```

## The one architectural rule

The model decides **what** — this entity matches fuzzily, this rule scores 90 — and
deterministic code decides **how** — UUID minting, reference wiring, element names,
encodings. Anything that blurs that line is treated as a bug.

## Claims are graded

A compiled model climbs six bars, and each was discovered by clearing the one
before it:

> round-trips ≠ importable ≠ exportable ≠ deployable ≠ submittable ≠ runnable

…and **runnable is not valid**: a model can import, deploy, run its integration job
and hold data while the Application Builder's Validation view still reports errors.
The pipeline never reports a lower bar as a higher one, and neither should you.

## What is measured, not authored

The emitter's knowledge of the wire format is **harvested from real product
exports**, never written from memory:

- `agent/compile/blocks.yaml` — per (object type, element) the encoding the product
  writes: 117 object types, 1200+ pairs, zero ambiguous encodings. Includes ordered-set
  position scopes and per-property-name component datatypes.
- `agent/compile/registry.py` — platform datatype UUIDs, read off a live instance.
- SemQL functions per hub technology are parsed from the product's own function
  table, so an invented function is refused offline instead of failing at runtime.

When the checker refuses a construct as unknown, the way out is to build it once in
the product's designer, export it, and re-harvest — never to relax the check.

## Layout

| Path | What |
|---|---|
| `agent/ir/` | The IR schema, validation rules, advisory rules, survivorship proposals, decision attribution, dependency ordering |
| `agent/compile/` | extract (XML→IR), emit (IR→XML), shape conformance (`blocks.py`), semantic diff |
| `agent/rest.py` | REST client: read, import, deploy, doctor (with per-location runtime probes) |
| `agent/safety.py` | Import preflight (refuses, never warns) and deploy post-condition |
| `agent/tools/` | Offline SemQL analysis, data profiling, validation-report parsing, documentation search |
| `agent/knowledge/` | The gap ledger — a retrieval the corpus cannot answer becomes a tracked gap, not an invented answer |
| `out/s1..s4` | Four worked example scenarios (synthetic data), from a LOV-only model to fuzzy matching with references and an application layer |
| `tests/` | The regression suite. Tests that need the private measurement corpus skip cleanly when it is absent |

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python3 -m pytest tests/ -q
```

To compile a scenario offline (stops before any network access):

```bash
python3 -m agent.build <env-file> out/s2-two-crms/ir
```

With a target instance configured (copy `.env.example` to `.env` and fill it in),
the same command with `--location` and `--datasource` runs the full gated path:
offline checks → preflight → import → deploy → verified deployment.

## The documentation corpus

The agent consults a local mirror of the official Semarchy xDM documentation at
authoring time. That mirror is **not** included in this repository — build your own
from the public documentation site:

```bash
python scripts/fetch_docs.py .
```

One factual page (the SemQL function table) is included as a documented exception
because offline SemQL validation is load-bearing without it.

## Status

This is a working research pipeline, not a supported product. The measured shape
library is a floor, not a ceiling: the product supports constructs no export in the
harvest corpus uses, and the pipeline refuses what it has not measured. Read the
refusal messages — every one names its way out.

## Trademark note

Semarchy and Semarchy xDM are trademarks of Semarchy SAS. This project is an
independent work and is not affiliated with, endorsed by, or supported by Semarchy.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
