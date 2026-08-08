# Scenario 2 — what a load WOULD produce

Written BEFORE any run, so `load.py verify` checks the model against a prediction
rather than a prediction being written to fit whatever the model returned (LESSONS
§13: five-out-of-six looks exactly like six-out-of-six until you say six in advance).

**Not yet run.** s2 has no data location on the lab and no free datasource, so this is
the offline prediction only. `certify.yaml`'s integration job (IR-030) and default
survivorship are offline-checked; nothing here has touched a live instance.

## Counts

| view | prediction | why |
|---|---|---|
| Customer MD | **6** | one master per source row; nothing is rejected |
| Customer GD | **4** | 1001 and 1002 each merge two masters; 1003 and 1004 are singletons |

A merge that failed would read as GD 6 (nobody merged) or GD 5 (one pair merged, one
did not). GD 4 is the only count consistent with both shared numbers merging.

## Golden values (the survivorship proof)

| CustomerNumber | FullName | Email | RegionCode | CreditLimit | UpdatedAt |
|---|---|---|---|---|---|
| 1001 | Isabelle Laurent | isabelle.laurent@example.eu | EU-W | **90000.00** | **2026-07-15** |
| 1002 | Marco Bianchi | marco.bianchi@example.eu | EU-S | **120000.00** | **2026-07-20** |
| 1003 | Sofia Alvarez | sofia.alvarez@example.eu | EU-W | 30000.00 | 2026-06-10 |
| 1004 | Derek Shaw | derek.shaw@example.us | US-E | 45000.00 | 2026-07-01 |

The two cells that would catch a wrong survivorship implementation:

- **1001 CreditLimit = 90000** (CrmUs's value) while **1001 FullName = Isabelle
  Laurent** (CrmEu's value). A golden that took CreditLimit from CrmEu (50000) is
  following the preferred publisher for a rule that is supposed to compare values.
- **1004 exists at all**, with CrmUs's own values. A missing or blank 1004 means the
  survivorship is discarding the non-preferred publisher rather than merely ranking it.

## To run, once a datasource is free

```bash
python out/s2-two-crms/data/load.py .env-lab <S2Location> dry     # payload check, nothing stored
python out/s2-two-crms/data/load.py .env-lab <S2Location> load    # persist + submit INTEGRATE_DATA
python out/s2-two-crms/data/load.py .env-lab <S2Location> verify  # counts, then the table above
```
