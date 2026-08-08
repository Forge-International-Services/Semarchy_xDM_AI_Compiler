# s4 — what this dataset should do, written before it was loaded

Twelve records: 8 Customer masters across three publishers, 4 Opportunity rows. Small
enough that every golden can be read individually, which is the point — counts alone
cannot tell a merge from a coincidence, and this scenario exists to find out whether
three things that have never been dereferenced actually work.

## The three claims under test

| # | claim | why only a run can judge it |
|---|---|---|
| 1 | `golden_id_generation: UUID` produces UUID golden ids | IR-026 caught this offline, but scenario 3's version of the same defect **deployed fine** and died at `INTEGRATE_DATA` on *Handle Reset Matching*. `DL_READY` is the state s4 was in before this load, i.e. exactly the pre-failure state |
| 2 | `Reference.foreignAttribute` produces usable FK columns | The element was once emitted as an empty container. It now round-trips and deploys. No row has ever dereferenced it |
| 3 | The integration job has a correct ORDER | s3 has no references. Here `Opportunity → Customer` is PRE_CONSO and `Customer → Parent` is POST_CONSO, and both FKs point at masters that consolidate in the same batch |

## Groups and predicted outcome

| group | records | rule expected to fire | score | band | predicted goldens |
|---|---|---|---|---|---|
| **A** Northwind | `SFDC.SFDC-1001`, `ERP.ERP-7001` | `D_ERP_KEY` on `ErpKeyNorm='ERP-4410'` | 100 | ≥95 → **auto-merge** | **1** golden, 2 masters |
| **B** Cascade | `SFDC.SFDC-1002`, `BILLING.BILL-3001` | `D_BILLING_KEY` on `BillingKeyNorm='BILL-88231'` | 100 | ≥95 → **auto-merge** | **1** golden, 2 masters |
| **C** Rainier | `SFDC.SFDC-1003`, `ERP.ERP-7002` | `P_NAME_STATE_ZIP` | 88 | 80 ≤ 88 < 95 → **review** | **2** goldens, 2 masters, **1 suggestion** |
| **D** Sound Fab | `ERP.ERP-7003` | none | — | — | **1** golden, 1 master |
| **E** Northwind West | `SFDC.SFDC-1004` | none (`ERP-4411` ≠ `ERP-4410`) | — | — | **1** golden, 1 master |

```
Customer  MD = 8     Customer  GD = 6     Opportunity GD = 4     suggestions = 1
```

The `C` prediction is the load-bearing one. Two records that a human would merge, that
the model is configured NOT to merge, and that must come back as two goldens with a
suggestion attached. A model that merges them has an auto-merge threshold that is not
being read; a model that produces no suggestion has a review threshold that is not being
read. Both look like "it worked" if you only count goldens.

## Per-attribute predictions on the goldens

Survivorship is `PREFERRED_PUBLISHER` throughout, with two different rankings:

- `NameRule`, `DerivedRule`, `CrossRefRule`, `MasterIdRule` → `Erp, Billing, Sfdc`
- `AddressRule` → `Billing, Erp, Sfdc`

| golden | `Name` | `Address.StateCode` | `Address.Zip` | `Address.Zip5` | `ErpKey` / `ErpKeyNorm` |
|---|---|---|---|---|---|
| A | `Northwind Trading Company` (Erp) | `WA` (Erp) | `98101` (Erp) | `98101` | `ERP-4410` / `ERP-4410` |
| B | `Cascade Logistics` (Billing) | `OR` (Billing) | `97205-1122` (Billing) | **`97205`** | null / null |
| C₁ | `Rainier Medical Group` | `WA` | `98004` | `98004` | null |
| C₂ | `rainier medical group` | `wa` | `98004-0099` | `98004` | null |
| D | `Sound Fabrication Inc` | `WA` | `98188-2231` | **`98188`** | `ERP-9990` |
| E | `Northwind Trading West` | `WA` | `98101` | `98101` | `ERP-4411` |

**Golden B and golden D are the §47 evidence.** Both carry a ZIP+4 in `Address.Zip` and
a 5-digit `Address.Zip5` derived from it. Before 2026-08-05 `NormalizeAddress` read and
wrote `Zip5`, so the `+4` was destroyed on the first load and unrecoverable. If those two
goldens come back with `Zip = Zip5`, the raw value is gone again.

Golden C₂ is the second half of that: `Name` stays lowercase on the golden because
`NormalizedName` — not `Name` — is what the enricher writes. An upper-cased `Name` here
would mean an enricher overwriting its own input.

## Reference predictions

| row | loaded as | predicted `FID_Customer` |
|---|---|---|
| `OPP-001` | `PublisherID_Customer=ERP`, `SourceID_Customer=ERP-7001` | golden **A** |
| `OPP-002` | `SFDC` / `SFDC-1002` | golden **B** — resolved *through* the merge, from the lowest-ranked publisher's side |
| `OPP-003` | `SFDC` / `SFDC-1003` | golden **C₁**, NOT C₂ and not a merged C |
| `OPP-004` | `ERP` / `ERP-7003` | golden **D** |

| row | loaded as | predicted `FID_Parent` |
|---|---|---|
| `SFDC-1004` (group E) | `PublisherID_Parent=ERP`, `SourceID_Parent=ERP-7001` | golden **A** |

`OPP-002` and the group-E parent are the two that only an ordered job can get right. Both
name a master by `(publisher, source id)`, and both of those masters lose their identity
to a consolidation inside the same batch. If the FK is resolved before Customer
consolidates, there is no golden to point at yet; if it is resolved against the master
rather than the golden, `OPP-002` lands on the wrong record or on nothing.

## What is deliberately NOT being tested here

- Deletions, soft or hard.
- Re-loading the same source ids (the update path).
- The application layer — s4 has none, so nothing here is readable by a steward.
- `NoSelfParent`, which is POST_CONSO and cannot fire: nothing in this dataset points at
  itself. It is present in the model and unexercised, and saying so is cheaper than
  implying the run covered it.

## Load mechanics

`CREATE_LOAD`, then one `PERSIST_DATA` call per publisher so that `defaultPublisherId`
carries the publisher rather than each record repeating it, then `SUBMIT` with
`jobName: INTEGRATE_DATA` (the name the s3 loads on `PartyHubLocation` actually ran
under — there is no `Job` object in this model, so the job name is the platform default
and was read off a real load rather than assumed).

`persistMode: ALWAYS` and no persist-time match detection: the default
`IF_NO_ERROR_OR_MATCH` would silently refuse exactly the duplicate records this dataset
is made of, and running the matcher at persist time would answer the match question in
the wrong register. The integration job is the register that counts.

`missingIdBehavior: FAIL` — every id in this dataset is explicit, so `GENERATE` would be
a setting that could not have changed the outcome.

---

# What actually happened — 2026-08-07

**The dataset has never been submitted, so none of the predictions above has been
tested.** Everything below the persist boundary is unverified, and the table stays as
written rather than being quietly deleted: it is the experiment, and the experiment is
still queued.

## What the load DID establish

`PERSIST_DATA` with `persistMode: NEVER` (loads 131–133, all CANCELED) and then for real
(load 134, CANCELED after the submit was refused):

| claim | register | result |
|---|---|---|
| every attribute name in `records.yaml` is real | persist echo | **confirmed** — including `PublisherID_Parent` / `SourceID_Parent` on Customer and `PublisherID_Customer` / `SourceID_Customer` on the BASIC Opportunity, echoed back verbatim |
| the enrichers normalize the messy raw values | persist echo | **confirmed** — `erp-4410` → `ErpKeyNorm=ERP-4410`, `wa` → `StateCodeNorm=WA`, `98101-4471` → `Zip5=98101` |
| §47: the publisher's value survives | persist echo | **confirmed** — `Address.Zip=98101-4471` sits alongside `Address.Zip5=98101`, and `ErpKey=erp-4410` alongside `ErpKeyNorm=ERP-4410`. Neither derived value overwrote its input |
| `Amount` as a JSON string | wire | **rejected** — `expecting DECIMAL but got [25000.00]`. Fixed to a number |
| all 12 records persist | `persistSummary` | **confirmed** — 4 SFDC + 3 ERP + 1 BILLING + 4 Opportunity, `status: PERSISTED`, zero failed validations |

Note what the dry run could *not* see: with an empty hub there is nothing to match
against, so `recordsWithPotentialMatches` was 0 for every record and says nothing about
the match rules. The C-group prediction is untouched by any of this.

## Why it stopped

The model had no integration job — LESSONS §54, now refused offline by IR-030. Adding
the job made the model refuse to DEPLOY with a bare `"Unexpected Error"` 500, which
twelve controlled deploys narrowed to "a `ModelJobTask` whose entity is Customer" and no
further (LESSONS §55). The stack trace is in the server log, which is browser-only.

The location was left `DL_READY`, serving the pre-job model, with zero records and every
load this phase created cancelled. `live/AccountHub.xml` matches it, so D7 is coherent.

**s4's bar is unchanged: DEPLOYED. It reached SUBMITTABLE and was refused there.**

## Update — the server log named the mechanism

The operator read the log (D12). The deploy dies interpreting *Merge (update) source
override values into GA table.sql* with **`One or more expression should be provided to
least()`** — a survivorship rule in the `UNTIL_NEXT_USER_CHANGE` branch whose scope
resolves to zero `SF` flag columns. Confirmed mechanism, LESSONS §55.4.

Two further deploys, each testing a stated prediction, both **500**:

1. all four `StandardSurvivorshipRule`s → `NO_OVERRIDE`, so no authored rule can reach
   `least()` at all. **This exonerates every authored rule**, and the `IdSurvivorshipRule`
   is semantically identical to s3's, which deploys.
2. `AddressRule` as `defaultRule=true` with member-level scope — probes I and J together.

The untested intersection is *no `ForeignAttribute` on Customer* **and** *a default rule
with member-level scope*; every probe so far moved one variable off a baseline that still
held another offender (LESSONS §55.5). That is one deploy, and it is the next one.


---

# RUNNABLE — 2026-08-07T18:18, load 135, `INTEGRATE_DATA` DONE in 7.5s

Twelve records in, one batch, `loadStatus: DONE`, `numberOfJobExecutions: 1`. The
verification below is reads, not counts — counts cannot tell a merge from a coincidence.

## Predicted vs observed

| group | predicted | observed | |
|---|---|---|---|
| A Northwind | 1 golden, 2 masters, `D_ERP_KEY` | `5d43cb01…` over `ERP.ERP-7001` + `SFDC.SFDC-1001` | **ok** |
| B Cascade | 1 golden, 2 masters, `D_BILLING_KEY` | `d042daa4…` over `BILLING.BILL-3001` + `SFDC.SFDC-1002` | **ok** |
| C Rainier | **2 goldens + 1 suggestion** | **1 golden `e61aa16c…` over both masters, `ConfirmedGold` NULL** | **prediction wrong, model right — see below** |
| D Sound Fab | 1 golden, 1 master | `62efe236…`, confirmed | **ok** |
| E Northwind West | 1 golden, 1 master | `62efe237…`, confirmed | **ok** |
| counts | GD 6 / MD 8 / Opp 4 | **GD 5** / MD 8 / Opp 4 | MD and Opp exact; GD off by the C group |

## The C group: the prediction was wrong about the PRODUCT, not about the model

`review_from: 80` and `auto_merge_at: 95` are *our* names for two of the **six** merge
thresholds a `SemQLMatcher` actually carries. The deployed matcher reads:

```
autoConfirmGoldenThreshold                    95     <- auto_merge_at
mergeThresholdNewGroup                        80     <- review_from
mergeThresholdMergingUnconfirmed              80
mergeThresholdMergingConfirmedWithUnconfirmed 80
mergeThresholdMergingConfirmed                95
mergeThresholdRemergingPreviouslySplit       100
autoConfirmSingletons                       true
```

Every record here is new, so the governing threshold is `mergeThresholdNewGroup` = 80.
At 88 the pair **is** grouped — and then fails `autoConfirmGoldenThreshold` = 95, so the
group is left **unconfirmed**. The review band does not mean *kept apart with a
suggestion attached*; it means *merged, and a steward must confirm or split it*.

`ConfirmedGold_CustomerGoldenId` is the register that says so, and it discriminates
perfectly:

| master | `Gold_` | `ConfirmedGold_` | score |
|---|---|---|---|
| `ERP.ERP-7001`, `SFDC.SFDC-1001` | `5d43cb01…` | `5d43cb01…` | 100 → **confirmed** |
| `BILLING.BILL-3001`, `SFDC.SFDC-1002` | `d042daa4…` | `d042daa4…` | 100 → **confirmed** |
| `ERP.ERP-7002`, `SFDC.SFDC-1003` | `e61aa16c…` | **NULL** | 88 → **unconfirmed** |
| `ERP.ERP-7003` / `SFDC.SFDC-1004` | own | own | singleton → confirmed |

So the three bands the design wanted — auto-merge, steward review, leave alone — are all
present and all distinguishable. The design was right; the *vocabulary* encoded a wrong
mental model of what the middle band does, and only a run could show that.

## The three claims this scenario existed to test

**1. UUID golden IDs (IR-026).** Confirmed on real records:
`5d43cb01-3801-4905-b34e-ec24e751e960`, `d042daa4-0f32-4d98-b25b-c2219a1b5444`,
`e61aa16c-f6ba-4e09-8b19-dc076e37a26f`, `62efe236-928c-11f1-814d-06bff9d5886b`. UUIDs,
not sequence integers, and the job that scenario 3's version of this defect killed on
*Handle Reset Matching* completed in 7.5 seconds.

**2. `Reference.foreignAttribute` dereferenced by real rows.** All four Opportunity
goldens resolved, and two of them the hard way:

| row | loaded | `FID_Customer` | |
|---|---|---|---|
| `OPP-001` | `ERP` / `ERP-7001` | `5d43cb01…` = golden A | ok |
| `OPP-002` | `SFDC` / `SFDC-1002` | `d042daa4…` = golden B | **resolved through the merge, from the lowest-ranked publisher's side** |
| `OPP-003` | `SFDC` / `SFDC-1003` | `e61aa16c…` | the C group's golden |
| `OPP-004` | `ERP` / `ERP-7003` | `62efe236…` = golden D | ok |

And the self-reference: `SFDC.SFDC-1004` loaded `PublisherID_Parent=ERP`,
`SourceID_Parent=ERP-7001` and came back with **`FID_Parent = 5d43cb01…`** — the golden
of a master that lost its own identity to a consolidation *in the same batch*. That is
the POST_CONSO scope earning its name.

**3. Job ORDER.** `Customer` at position 1, `Opportunity` at 2. The job's task list
included *Compute Delete Restrictions from load records for OpportunityCustomer*, and
every child FK resolved on the first pass — no second execution, no orphan.

## §47, on goldens and on masters

| where | raw | derived |
|---|---|---|
| golden B | `Address.Zip = 97205-1122` | `Address.Zip5 = 97205` |
| golden D | `Address.Zip = 98188-2231` | `Address.Zip5 = 98188` |
| master `SFDC.SFDC-1001` | `ErpKey = erp-4410`, `Address.Zip = 98101-4471` | `ErpKeyNorm = ERP-4410`, `Zip5 = 98101` |
| master `SFDC.SFDC-1002` | `BillingKey = bill-88231` | `BillingKeyNorm = BILL-88231` |
| golden C | `Name = rainier medical group` (lowercase, ERP's) | `NormalizedName = RAINIER MEDICAL GROUP` |

Not one derived value overwrote its input. The publisher's ZIP+4 is still on the golden.

## Survivorship

Golden A took `Name = Northwind Trading Company` (Erp, ranked first) over SFDC's
*Northwind Trading Co*; golden B took `Name = Cascade Logistics` and its whole address
from Billing, which `AddressRule` ranks first and the other rules rank second. Both as
designed.

**s4 is RUNNABLE.**
