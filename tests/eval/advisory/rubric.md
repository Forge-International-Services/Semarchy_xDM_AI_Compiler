# Reviewer rubric — sprint 03

The automated checks decide five of the six acceptance criteria. This rubric is the
other two: **is the reasoning correct**, and **would you build from this**.

It is organised by the *classes of defect that automation cannot see*. Each class is
here because an instance of it was actually found — three of them in work that had
already passed every automated check.

Score each scenario per class: **OK** / **QUERY** / **WRONG**. Any WRONG blocks the
gate. A QUERY is answered in the review conversation, not silently accepted.

---

## Class 1 · Narrative says one thing, IR says another

The gate approves the *narrative*; the compiler builds the *IR*. Divergence between
them means the thing approved is not the thing built.

Automated coverage is **partial**: `unexplained_objects` catches an IR object the
narrative never names, but not a rule whose *attributes* differ from the table.

> **Found in scenario 2:** the narrative gave `CreditLimitRule → CreditLimit /
> LARGEST_VALUE`; the IR applied `LARGEST_VALUE` to `RegionCode`. Valid IR, satisfied
> CA-002, meaningless design.

**Check:** for each table row in `02-certification.md` and `03-model-plan.md`, find the
same object in `ir/*.yaml` and confirm the attributes and strategy match.

## Class 2 · A strategy that is valid but nonsensical for its attribute

`ir_validate` checks a strategy exists and is spelled correctly. Nothing checks it
*means* anything for the attribute it governs.

**Check:** read each survivorship rule aloud as a sentence. "Take the largest region
code" should sound wrong. "Take the largest credit limit" should not.

## Class 3 · A business fact the agent invented

The agent cannot know which source is authoritative, which system is freshest, or what
the volumes are. Where it needed one of those, it should have asked — and where it
assumed, it must have said so.

> **Found in scenario 3:** the survivorship ranking `SUPPORT > MARKETING > EVENTS` is
> an assumption about which system is freshest. Plausible, and not mine to make.

**Check:** every `[uncited — model judgement]` label. Is the judgement one the agent was
entitled to make, or a business fact it should have asked about?

## Class 4 · An assumption that decides the entity type

Entity type constrains matching, survivorship and the whole application, and cannot be
changed later without a rebuild. An assumption at this level is the highest-consequence
thing in the document.

> **Found in scenario 2:** whether `CUSTOMER_NUMBER` is globally unique or unique
> per region decides ID-matched versus fuzzy. Both readings were presented; one was
> taken on the operator's statement.

**Check:** is every entity-type derivation traceable to something *you* said, rather
than to something the agent found convenient?

## Class 5 · The counter-argument was not addressed

A recommendation that only cites what supports it is advocacy, not analysis.

> **Found in scenario 1:** `entities.md` calls Basic entities "suitable for … simple
> reference data entities", which reads as an argument *against* the LOV
> recommendation. The scenario originally cited only the supporting page.

**Check:** for each significant choice, does the document name the strongest argument
against it and answer it?

## Class 6 · Silence where a question was due

The completeness advisor covers the ten known cases. It does not know what it does not
know.

**Check:** having read the design, what would you have asked that nothing asked?
Anything found here becomes a new CA rule.

---

## Per-scenario expected verdicts

| Scenario | Must land on | A wrong answer looks like |
|---|---|---|
| 1 · country reference data | **LOV**, no entity, no publishers | a Basic entity — buys a certification process and physical tables for two columns |
| 2 · two CRMs, shared ID | **ID-matched**, 2 publishers, single PK, composite key raised *because* the type is ID-matched | fuzzy (throws away a deterministic join); or raising the composite key as a universal rule |
| 3 · three sources, no key | **Fuzzy**, matcher, binned probabilistic rules, PRE_CONSO enrichers feeding them | ID-matched via concatenated local keys — three local keys are not one shared key |

## Sign-off

- [ ] Class 1–6 scored for all three scenarios, no WRONG outstanding
- [ ] Open CA questions answered or acknowledged
- [ ] **"I would build from this"**

## The guard this rubric cannot supply

All three scenarios were written by the agent that is being assessed. A fourth,
authored by the reviewer and unseen, is the only real check on whether the three were
tuned to the agent's own expectations.
