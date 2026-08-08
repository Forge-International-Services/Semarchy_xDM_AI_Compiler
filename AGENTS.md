# AGENTS.md — agent operating instructions

This repository is an agent pipeline that compiles natural-language MDM requirements
into a deployable Semarchy xDM model. If you are an AI agent working in this repo,
these are your operating rules. They are distilled from a live-instance measurement
campaign; every one of them exists because its absence cost a real defect.

**Harness-neutral by design.** The compiler is a plain Python package with CLI entry
points; nothing here depends on a particular coding agent. `AGENTS.md` is the single
canonical instruction file, read by Snowflake Cortex Code (CoCo), Claude Code, Cursor,
Codex and anything else honouring the convention. If your harness looks for a
different filename, symlink it to this one rather than keeping a second copy — two
instruction files that must agree are a place they will stop agreeing.

**The guardrails are in the CODE, not in these instructions.** The preflight refuses,
`blocks.check` refuses, and the emitter refuses unmeasured constructs — so a harness
that ignores this file still cannot deploy something unsafe. Read that as permission
to be strict rather than as a reason to relax.

## Running against a Snowflake-hosted hub (Cortex Code)

xDM on Snowpark Container Services needs two headers, and CoCo can fetch the first
input for you because it already knows the account:

```sql
CALL <native_app_name>.xdm_public.xdm_server_url();   -- the base for SEMARCHY_URL
```

Then `SEMARCHY_AUTHORIZATION=Snowflake Token="<PAT>"` plus `SEMARCHY_API_KEY=<key>` in
`.env` (see `.env.example` — the scheme is Snowflake's custom format, not Bearer). A
standard, non-SPCS xDM deployment needs the API key ONLY. Confirm with
`python3 -m agent.rest .env` before anything else; it names the failure precisely,
including the two that otherwise masquerade as bad tokens.

## 1. The one architectural rule

The model decides *what* — an entity is fuzzy-matched, a rule scores 90 — and
deterministic code decides *how* — UUID minting, reference wiring, element names,
encodings. **The LLM never writes XML.** If you find yourself editing emitted XML by
hand, stop: fix the emitter or the IR, then re-emit.

## 2. Claims are graded — never report a lower bar as a higher one

> round-trips ≠ importable ≠ exportable ≠ deployable ≠ submittable ≠ runnable —
> and **runnable is not valid**.

Round-trip fidelity compares the compiler against itself and proves nothing about
the product. An import can return 204 and cover five different outcomes — read your
claim back in the register where it lives (the export, the deploy status, the job
result, the Validation view, the data).

## 3. House rules

- **Refuse rather than guess.** Unknown component, unknown action kind, unknown
  datatype, unknown technology, unknown function — all refuse, and the refusal
  message names the way out.
- **Measure the shape; do not author it.** The wire format knowledge in
  `agent/compile/blocks.yaml` is harvested from real product exports. The way out of
  a refusal is to build the construct once in the product designer, export it, and
  re-harvest (`python -m agent.compile.harvest_blocks`) — never to relax the check.
- **Never harvest invariants from this compiler's own re-exported output.** A round
  trip through the product attests the spelling and hands your own values straight
  back — it would bless your own bugs. See `harvest_blocks.COMPILER_DERIVED`.
- **Absent ≠ null ≠ a value ≠ an empty container.** Enums, numbers and booleans use
  `val="…"`; free text uses element text. Both spellings import cleanly and the
  wrong one is stored as null — only the runtime tells you, unless `blocks.check`
  does first.
- **Vocabulary comes from the wire, not the docs.** Documented names and wire
  spellings differ (a start context documented as one name serialises as another;
  a registry message says NUMBER where every export writes DECIMAL). When they
  disagree, emit what the product exports.
- **Every design decision goes on disk** (`agent/ir/policy.py`), not into a chat log.
- **No in-code overrides of declared properties.** A script that patches
  `target_technology` creates a place where the model and the truth disagree
  indefinitely.

## 4. The three questions a compiled model must answer

| ask | module |
|---|---|
| is the SHAPE right? | `agent/compile/blocks.py` — `check()` / `render()` |
| are the VALUES justified? | `agent/ir/decisions.py` — `report()` |
| does it RUN in the right order? | `agent/ir/depends.py` |

Each layer is blind to the other two. Run all three before any import:

```bash
python3 -m agent.build <env-file> <ir-dir>          # stops at IMPORTABLE
python3 -m agent.build <env-file> <ir-dir> --location <loc> --datasource <ds>
```

The build refuses on a dirty working tree: the IR that produced an artefact must be
committed, or the output cannot be traced to a source.

## 5. Working against a live instance

- `python3 -m agent.rest <env-file>` is the doctor: configuration, connectivity,
  data locations, and a per-location runtime probe.
- Read the OpenAPI before calling anything:
  `GET /semarchy/api/rest/api-docs?domain=<domain>&format=JSON`. Never guess a path.
- The preflight (`agent/safety.py`) refuses, never warns. `verify_deploy()` is the
  post-condition — a deploy is not verified until the location returns to ready with
  an advanced deployment date.
- A 500 is not proof nothing happened; re-read before concluding, never retry blind.
- Run the product's own Validation view on every edition before calling it finished.

## 6. Advisory rules ask; validation rules block

`agent/ir/validate.py` fires on violation and blocks compilation.
`agent/ir/advise.py` fires on absence, asks a question, and never blocks —
`agent/ir/propose.py` attaches reviewable proposals (tagged, never silently
adopted) where a heuristic can offer one. Keep that separation: an advisory that
starts blocking, or a proposal that adopts itself, is a regression.

## 7. Tests

```bash
python3 -m pytest tests/ -q
```

Tests that need the private measurement corpus (raw product exports) skip cleanly
when it is absent. A skipped test is a statement that evidence is missing — do not
delete the test, and do not fake the evidence.
