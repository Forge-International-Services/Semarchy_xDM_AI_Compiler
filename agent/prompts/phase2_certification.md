# Phase 2 — Certification design  → G2

Produce `02-certification.md`. Requires G1.

With entity types fixed, propose the certification pipeline per entity, in the order
the training teaches it:

**enrichers (PRE_CONSO) → validations → matching → consolidation → enrichers (POST_CONSO)**

## The rule that is most often wrong

> Anything whose output **matching depends on** — normalization, phonetic tokens,
> standardized address — must be **PRE_CONSO**, because matching runs on master
> records. Anything describing the **golden** record is **POST_CONSO**.

Get this wrong and it is invisible in the XML, invisible at import, and shows up
weeks later as inexplicably bad match rates. State the scope for every enricher and
justify any POST_CONSO one whose output is referenced by a match rule (it is a bug).

## Validation severity is a decision, not a default

Warnings still deploy and still certify. Errors reject the record into the
source-with-errors view. Proposing everything as an error is a common and expensive
default — say which each is, and why.

## Basic entities

No matcher-driven survivorship, no publishers. If you find yourself proposing
matching for a Basic entity, the entity type is wrong — go back to G1.

## Output

Per entity, an annotated pipeline: each element with its purpose, its scope, and the
doc page that justifies it.
