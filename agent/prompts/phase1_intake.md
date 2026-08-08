# Phase 1 — Intake  → G1

Produce `01-intake.md`: a candidate inventory for the user to correct.

## Inputs

Run `schema_ingest()` over whatever the user uploaded. It returns *candidates*:
tables, columns, xDM datatypes, mandatory/PK flags, FK-derived references, and an
`unresolved` list. Treat every one as a proposal.

## Ask publishers FIRST

Publisher topology **determines entity type**, which then constrains matching,
survivorship and everything downstream. Per entity, ask:

1. How many source systems feed this? What are they called?
2. Do they share a truly unique identifier for the same real-world thing?
3. Is any source authoritative for particular attributes?
4. Will users also author records directly in the application?
5. Expected volume and growth?

Target **≤8 questions per entity**. Derive what is derivable; ask only what changes
the outcome.

## First ask whether it is an entity at all

Not every table becomes an entity. A code-and-label list belongs in a **list of values**,
and `schema_ingest` cannot tell the difference — it sees a table either way.

```
code + label only, no attributes of its own, <= 1,000 entries  → LOVType, NOT an entity
                                                                 otherwise, an entity
```

The threshold is not a rule of thumb: *"Lists of values are limited to 1,000 entries. If a
list of value needs to contain more than 1,000 entries, you should consider implementing in
the form of an entity instead."*
(`docs/Design/logical-model/list-of-values.md § Overview`)

So a country list, a gender list, a status list are **LOVs**. A product catalogue with
descriptions, lifecycle and its own references is an entity, however reference-like it feels.
Modelling a code list as a Basic entity is a common and expensive mistake: it buys a
certification process, physical tables and a deploy cycle for something that is two columns.

## Then DERIVE the entity type — do not ask for it

For everything that IS an entity:

```
1 source, no internal duplicates, or hub-authored only  → Basic
N sources + a truly unique shared ID                    → ID-matched
N sources, no shared ID                                 → Fuzzy
```

Present the derivation **with its reasoning and citation**, and let the user
override at G1. Overriding is legitimate — they may know a second source is coming —
but it must be deliberate.

## Say these unprompted

- Data authored in the generated application needs **no publisher**; xDM tags it as
  user-authored automatically. Teams routinely invent a "MANUAL" publisher that
  should not exist.
- Publisher **codes are uppercase** and are what the certification process sends.
  Changing one later means reloading data.
- A composite primary key only matters **if the entity becomes ID-matched** — that is the
  type whose PK must be a single attribute, so the columns have to be concatenated into one
  PK column. Basic and fuzzy entities are unaffected: fuzzy generates its own golden ID.
  Raise it when the type is ID-matched, not on every composite key you see.

## Output

Per candidate entity: proposed name, derived type + reasoning, publishers with
codes, attributes with xDM datatypes, and an explicit **Unresolved** section
carrying everything `schema_ingest` could not map. Do not quietly drop unresolved
items — they are the highest-leverage thing for a human to correct here, because a
wrong datatype propagates through every later phase.
