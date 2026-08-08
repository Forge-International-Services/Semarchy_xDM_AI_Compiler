# Phase 3 — Model plan  → G3

Produce `03-model-plan.md`. Requires G2. This is the last phase before anything is
compiled, so it must be concrete enough to author the IR from.

## Settle

- Attribute datatypes, lengths, precision/scale, and validation **scopes**
  (`PRE_CONSO` on source data vs `POST_CONSO` on the golden record).
- LOV types and their codes. LOV reference data ships **inside** the model export,
  so LOV changes are model changes and go through the same deploy path.
- References: `deletePropagation`, `validationScope`, role names, and which side is
  the child (`fromEntity`) versus the parent (`toEntity`).
- Match rules, matcher thresholds, survivorship strategy per attribute.

## Force these two into the open

**Binning.** A match rule with no `binningExpressions` compares the full cartesian
product within scope — on real volume, the difference between minutes and hours.
Propose binning for every probabilistic rule, and give a written justification for
any rule you leave unbinned.

**Thresholds as a policy, not nine numbers.** The `mergeThreshold*` family interacts.
State the policy first — e.g. *auto-merge ≥95, steward review 80–94, no match <80* —
then derive the nine values and show them for confirmation.

## Naming is load-bearing

Names appear in SemQL, in the REST API and in error messages. CamelCase InitCap,
type suffixes on everything except entities and attributes, publisher codes
uppercase.

## Constraints to respect

- Exactly one matcher per entity.
- In match conditions, `Record1` and `Record2` go on **opposite sides** of each
  comparison.
- `PREFERRED_PUBLISHER` survivorship needs a publisher ranking list.
- Every fully-qualified external function referenced in SemQL must be declared, and
  will be verified against the target Snowflake account before import.


## Emit IR, not only prose

Alongside `03-model-plan.md`, write the machine-readable form:

```
out/<project>/ir/model.yaml     entities, attributes, LOVs, complex types, references, publishers
out/<project>/ir/certify.yaml   enrichers, matchers, match rules, survivorship
```

`agent/ir/examples/` holds a worked example. Then run:

```bash
python -c "from agent.advisory import check; print(check('out/<project>').render())"
```

This is not bookkeeping. It converts design decisions from claims into checks:

| Decision | Checked by |
|---|---|
| every probabilistic rule is binned | IR-010 |
| an enricher feeding a match rule is PRE_CONSO | IR-009 |
| a fuzzy entity has a matcher | IR-001 |
| an ID-matched entity has exactly one PK | IR-003 |
| publisher codes are uppercase | IR-006 |
| PREFERRED_PUBLISHER has a ranking | IR-011 |

A warning requires `acknowledged: true` with a written `justification` — that is the
mechanism for accepting an unbinned rule, not an omission.

The same IR is what the compiler consumes, so what the user approves at G4 is what gets
built. Do not restate the design in prose and leave the IR to be reconstructed later.
