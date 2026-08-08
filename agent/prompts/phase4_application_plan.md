# Phase 4 — Application plan  → G4

Produce `04-app-plan.md`. Requires G3.

Describe the application to build, following the training's own sequence:

display cards → collections → forms → business views → search and filtering →
organizing and branding → steppers → action sets → duplicate managers

## State the deploy cost of every item

This drives the build order, so make it explicit per artifact:

| Change | Cost |
|---|---|
| Display cards, action sets | validate + **Refresh Application** |
| New entities, steppers, duplicate managers | full **Deploy Model Edition** |

## Field rendering

Form fields and collection columns each name a renderer and carry a flat property
list. Observed renderers: `semTextField`, `semIdField`, `semMenuField`,
`semDatepickerField`, `semCheckboxField`, `semReferenceField`, `semImageField`.

Two conventions that bite:
- Component-property booleans are `"0"` / `"1"` **strings**, not `val="true"`.
- Empty string is a real value meaning "inherit the default" — not the same as
  omitting the property.

## Output

The application structure, the build order implied by the deploy costs above, and
which artifacts can be iterated cheaply versus which force a full deploy.


## Emit IR

Extend `out/<project>/ir/` with the application layer as it becomes supported. Until the
emitter covers a construct, record it in the narrative and say plainly that it will be
built through the UI — do not invent IR shapes for it.
