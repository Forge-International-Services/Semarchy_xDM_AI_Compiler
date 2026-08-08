# Phase prompts

`_shared.md` prepends every phase. Phases run in order and each ends at a gate
(`agent/gates.py`); re-opening a gate invalidates every gate after it.

| Phase | Prompt | Gate | Output |
|---|---|---|---|
| 1 Intake | `phase1_intake.md` | G1 | `01-intake.md` |
| 2 Certification | `phase2_certification.md` | G2 | `02-certification.md` |
| 3 Model plan | `phase3_model_plan.md` | G3 | `03-model-plan.md` |
| 4 Application plan | `phase4_application_plan.md` | G4 | `04-app-plan.md` |

Every output is checked by `agent.tools.citation.validate()` before it reaches the
user. A citation that does not resolve fails the phase — see that module for why
fabricated citations are treated as worse than uncited claims.
