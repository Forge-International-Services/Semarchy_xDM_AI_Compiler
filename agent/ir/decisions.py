"""The decision register — step 2 of the block design.

`policy.py` holds the VALUES the operator decided and why. What it cannot do is answer
the question that matters when reviewing a compiled model:

    this construct has this value — WHICH DECISION PUT IT THERE, and was it ours?

That question has three possible answers, and all three need to be visible:

    matches      the value is the house decision, applied
    diverges     the value contradicts the house decision, deliberately or not
    unattributed the field is one policy has an opinion about, and nothing says why

`diverges` is the interesting one and it is NOT an error. The operator was explicit
that house policy is a default, never a constraint: *"the level of trust per publisher
will vary on each company"*. So an engagement that sets a different threshold is doing
the right thing — as long as the divergence is VISIBLE rather than accidental. That
distinction is what this module exists to make.

NO VALUES LIVE HERE. Every expectation reads from `policy`, so there is exactly one
copy of each decided number and this file cannot drift from it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.ir import policy


@dataclass(frozen=True)
class Decision:
    """One recorded decision, and the constructs it governs.

    `source` is load-bearing. An `operator` decision is authority — it is what was
    asked for. An `observed` one is evidence — it is what the product does, and
    diverging from it is a bug rather than a preference. A `default` is neither: it is
    the agent's proposal until someone says otherwise.
    """
    id: str
    statement: str
    source: str                      # operator | observed | default
    closes: str | None = None        # the advisory gap it answers, e.g. "CA-008"
    see: str | None = None           # where the reasoning lives
    #: (construct kind, field) -> is this value the decision?
    governs: tuple[tuple[str, str], ...] = ()
    accepts: Callable[[object], bool] = field(default=lambda v: True, repr=False)
    expected: Callable[[], object] = field(default=lambda: None, repr=False)


DECISIONS: tuple[Decision, ...] = (
    Decision(
        id="D-MATCH-BANDS",
        statement="Three match bands: >=95 auto-merge, 80-94 steward review, "
                  "<80 not a match.",
        source="operator", closes="CA-008", see="agent/ir/policy.py § matching",
        governs=(("matcher", "auto_merge_at"), ("matcher", "review_from")),
        accepts=lambda v: v in (policy.HOUSE_THRESHOLDS.auto_merge_at,
                                policy.HOUSE_THRESHOLDS.review_from),
        expected=lambda: (policy.HOUSE_THRESHOLDS.auto_merge_at,
                          policy.HOUSE_THRESHOLDS.review_from),
    ),
    Decision(
        id="D-SINGLETON",
        statement="Singletons are auto-confirmed. A steward asked to confirm every "
                  "unmatched record confirms without reading, which manufactures an "
                  "audit trail and spends the attention the 80-94 band needs.",
        source="operator", closes="CA-014", see="agent/ir/policy.py § AUTO_CONFIRM",
        governs=(("matcher", "auto_confirm_singletons"),),
        accepts=lambda v: v == policy.AUTO_CONFIRM_SINGLETONS,
        expected=lambda: policy.AUTO_CONFIRM_SINGLETONS,
    ),
    Decision(
        id="D-OVERRIDE-PROVENANCE",
        statement="Whether a steward edit may override consolidation is a property of "
                  "the value's PROVENANCE, not its datatype: pipeline-computed values "
                  "are NO_OVERRIDE, human-authored ones UNTIL_NEXT_USER_CHANGE.",
        source="operator", closes="CA-002",
        see="agent/ir/policy.py § override_strategy",
        governs=(("survivorship", "override_strategy"),),
        accepts=lambda v: v in policy.OVERRIDE_STRATEGIES,
        expected=lambda: policy.OVERRIDE_STRATEGIES,
    ),
    Decision(
        id="D-OVERRIDE-VOCAB",
        statement="NO_OVERRIDE and UNTIL_NEXT_USER_CHANGE are the only strategies the "
                  "importer accepts. Probed one constant at a time; `NEVER` was an "
                  "invention that survived every offline check.",
        source="observed", see="LESSONS.md §16",
        governs=(("survivorship", "override_strategy"),),
        accepts=lambda v: v in policy.OVERRIDE_STRATEGIES,
        expected=lambda: policy.OVERRIDE_STRATEGIES,
    ),
    Decision(
        id="D-NORMALIZE-FIRST",
        statement="Every match input carries a PRE_CONSO normalizer. TRIM is the "
                  "floor, not the ceiling.",
        source="operator", closes="CA-004", see="agent/ir/policy.py § normalization",
        governs=(("enricher", "scope"),),
        accepts=lambda v: v in ("PRE_CONSO", "PRE_POST_CONSO"),
        expected=lambda: "PRE_CONSO",
    ),
    Decision(
        id="D-MASTER-VALUE-PICKING",
        statement="Stewards pick which value survives, from the matched records. Not "
                  "a survivorship strategy — a duplicate-manager setting the product "
                  "already defaults to true.",
        source="operator", closes="CA-002",
        see="agent/ir/policy.py § MASTER_VALUE_PICKING",
        governs=(("dups_manager", "enableMasterValuePicking"),),
        accepts=lambda v: str(v).lower() == str(policy.MASTER_VALUE_PICKING).lower(),
        expected=lambda: policy.MASTER_VALUE_PICKING,
    ),
    Decision(
        id="D-ID-GENERATION",
        statement="The source supplies the master ID (MANUAL); xDM generates the "
                  "golden ID. The generator must agree with the PK datatype — "
                  "SEQUENCE needs a numeric key, UUID a uuid one.",
        source="observed", see="LESSONS.md §19, §20",
        governs=(("entity", "id_generation"), ("entity", "golden_id_generation")),
        accepts=lambda v: v in ("MANUAL", "SEQUENCE", "UUID", "SEMQL"),
        expected=lambda: "MANUAL / SEQUENCE",
    ),
)

#: (kind, field) -> the decisions that speak to it. A field may have more than one:
#: D-OVERRIDE-PROVENANCE says WHICH value to pick, D-OVERRIDE-VOCAB says which values
#: exist at all. Both are real and they answer different questions.
GOVERNED: dict[tuple[str, str], list[Decision]] = {}
for _d in DECISIONS:
    for _key in _d.governs:
        GOVERNED.setdefault(_key, []).append(_d)


@dataclass(frozen=True)
class Attribution:
    where: str               # Party/NameRule
    kind: str                # survivorship
    field_name: str          # override_strategy
    value: object
    status: str              # matches | diverges | unattributed
    decision: str | None = None

    def __str__(self) -> str:
        d = f" [{self.decision}]" if self.decision else ""
        return (f"{self.status.upper():12} {self.where}.{self.field_name} = "
                f"{self.value!r}{d}")


_IDENT = __import__("re").compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")


def _match_feeders(ir) -> set[tuple[str, str]]:
    """(entity, enricher) for every enricher whose output reaches a match rule.

    TRANSITIVELY, because that is how the failure actually happens: a normalizer feeds
    a phonetic enricher feeds a rule, and only the last link is visible to a check that
    looks one step. Walked BACKWARDS from what the rules read, adding the inputs of
    every enricher already in the set until it stops growing.
    """
    wanted: dict[str, set[str]] = {}
    for m in ir.certify.matchers:
        seen = wanted.setdefault(m.entity, set())
        for r in m.rules:
            seen |= {i.split(".")[-1] for i in _IDENT.findall(r.condition or "")}
            seen |= {b.split(".")[-1] for b in r.binning}

    out: set[tuple[str, str]] = set()
    growing = True
    while growing:
        growing = False
        for en in ir.certify.enrichers:
            if (en.entity, en.name) in out:
                continue
            reads = wanted.get(en.entity, set())
            if not any(x.attribute.split(".")[-1] in reads for x in en.expressions):
                continue
            out.add((en.entity, en.name))
            for x in en.expressions:
                reads |= {i.split(".")[-1]
                          for i in _IDENT.findall(x.expression or "")}
            growing = True
    return out


def _walk(ir) -> list[tuple[str, str, str, object]]:
    """(kind, where, field, value) for every field a decision could speak to."""
    out = []
    for e in ir.model_ir.entities:
        for f in ("id_generation", "golden_id_generation"):
            out.append(("entity", e.name, f, getattr(e, f)))
    for m in ir.certify.matchers:
        # A matcher states its thresholds EITHER as the operator's two bands, OR as
        # nine explicit numbers. Extracted models always use the nine, so reading
        # `policy` unguarded crashed validate() on every real export.
        if m.policy is not None:
            out.append(("matcher", m.entity, "auto_merge_at", m.policy.auto_merge_at))
            out.append(("matcher", m.entity, "review_from", m.policy.review_from))
        elif m.thresholds:
            # Nine numbers is itself a divergence from the decision, which was
            # explicitly "then it will be 2 rules". Reported, never blocking — a
            # model extracted from someone else's export legitimately looks like this.
            out.append(("matcher", m.entity, "auto_merge_at", "<9 explicit numbers>"))
        out.append(("matcher", m.entity, "auto_confirm_singletons",
                    m.auto_confirm_singletons))
    for s in ir.certify.survivorship:
        if s.kind == "standard":
            out.append(("survivorship", f"{s.entity}/{s.name}", "override_strategy",
                        s.override_strategy))
    # ONLY the enrichers whose output reaches a match rule. D-NORMALIZE-FIRST says
    # "every MATCH INPUT carries a PRE_CONSO normalizer" — it has no opinion about an
    # enricher that mints an identifier on a confirmed golden or derives a territory,
    # and both of those are POST_CONSO by necessity rather than by choice.
    #
    # Reporting every enricher made the register call each of them a divergence, which
    # was invisible for as long as no scenario had a post-consolidation enricher at all.
    # A rule that has only ever been shown correct examples has not been tested.
    #
    # The pairing with IR-009 is exact: a POST_CONSO enricher that DOES feed matching
    # still appears here, and IR-009 refuses it outright.
    feeders = _match_feeders(ir)
    for en in ir.certify.enrichers:
        if (en.entity, en.name) in feeders:
            out.append(("enricher", f"{en.entity}/{en.name}", "scope", en.scope))
    for d in getattr(ir.app, "dups_managers", ()):
        v = d.settings.get("enableMasterValuePicking")
        if v is not None:
            out.append(("dups_manager", f"{d.entity}/{d.name}",
                        "enableMasterValuePicking", v))
    return out


def attribute(ir) -> list[Attribution]:
    """Every decidable value in an IR, and which decision put it there."""
    out = []
    for kind, where, fname, value in _walk(ir):
        governing = GOVERNED.get((kind, fname), [])
        if not governing:
            out.append(Attribution(where, kind, fname, value, "unattributed"))
            continue
        for d in governing:
            ok = d.accepts(value)
            out.append(Attribution(where, kind, fname, value,
                                   "matches" if ok else "diverges", d.id))
    return out


def divergences(ir) -> list[Attribution]:
    return [a for a in attribute(ir) if a.status == "diverges"]


def report(ir) -> str:
    rows = attribute(ir)
    counts = {k: sum(1 for a in rows if a.status == k)
              for k in ("matches", "diverges", "unattributed")}
    lines = [f"decision attribution: {counts['matches']} match, "
             f"{counts['diverges']} diverge, {counts['unattributed']} unattributed"]
    for a in rows:
        if a.status != "matches":
            lines.append(f"  {a}")
            if a.decision:
                d = next(x for x in DECISIONS if x.id == a.decision)
                lines.append(f"               {d.source}: {d.statement}")
                lines.append(f"               expected {d.expected()!r} — "
                             f"see {d.see}")
    if counts["diverges"]:
        lines.append("")
        lines.append("  A divergence is NOT an error. House policy is a default, and "
                     "the operator was explicit that trust varies per engagement. It "
                     "must be VISIBLE, not absent — record it in the narrative or "
                     "acknowledge it in the IR.")
    return "\n".join(lines)


# ------------------------------------------------------- what is NOT being looked at
#
# `_walk` is a hand-written list, and a hand-written list has one structural weakness:
# it cannot tell you what it OMITS. Every field it visits is visible in its output and
# every field it forgot is invisible in exactly the same way as a field that has
# nothing to say. "0 diverge" and "0 diverge, and 9 fields were never examined" render
# identically.
#
# That is the same failure shape as CA-011's hole at zero, and it is worth deriving
# rather than auditing by eye: ask the SCHEMA what the decidable surface is, then
# subtract what `_walk` reaches.
#
# A field is DECIDABLE when it has a closed vocabulary AND a default. Both halves
# matter:
#
#   closed vocabulary  there is a set of alternatives, so a choice exists at all. A
#                      free-text label is not a decision.
#   has a default      the value can end up in a compiled model WITHOUT anyone
#                      choosing it. A required Literal (Entity.type, StepperStep.kind)
#                      is always stated by the author, so it is a choice by
#                      construction and needs no register to make it visible.
#
# The second half is what keeps this from being a list of every enum in the IR.

#: kind string -> the schema class whose fields that kind describes. The link between
#: `_walk`'s vocabulary and the schema's, stated once instead of inferred.
KIND_TO_MODEL = {
    "entity": "Entity",
    "matcher": "Matcher",
    "survivorship": "SurvivorshipRule",
    "enricher": "Enricher",
    "validation": "Validation",
    "reference": "Reference",
    "attribute": "Attribute",
    "grant": "EntityGrant",
    "dups_manager": "DupsManager",
}

#: Decidable fields deliberately left out of the register, each with the reason. An
#: entry here is a RECORDED DECISION not to watch something — which is a different
#: thing from never having noticed it, and the difference is the whole point of
#: deriving the list. Anything not here and not walked is a genuine blind spot.
NOT_WATCHED: dict[tuple[str, str], str] = {
    ("Enricher", "kind"): "Names which emitter branch runs, not a policy choice. "
                          "IR-015 already refuses an unknown kind.",
    ("SurvivorshipRule", "kind"): "standard vs id is structural — the Master ID rule is "
                                  "mandatory and IR-011 refuses a matched entity "
                                  "without one. Nothing to prefer.",
    ("FormContainer", "kind"): "Application layout. A tab is not a data-certification "
                               "decision and the app plan states it per screen.",
    ("Attribute", "lov_scope"): "Follows the attribute's LOV binding; meaningless "
                                "without one, and IR-009 covers the binding itself.",
    ("EntityGrant", "default_access"): "Per-role authorisation, decided per engagement "
                                       "in the charter rather than by house policy.",
    ("Recipient", "source_type"): "Determined by which recipient field the author "
                                  "filled in — a role or a SemQL expression — so it "
                                  "restates the shape rather than choosing anything.",
    ("RetentionPolicy", "time_unit"): "Meaningless unless retention_type is DURATION, "
                                      "and then it is stated with the duration it "
                                      "qualifies. Watching it alone would ask about a "
                                      "field that is usually inert.",
    ("UniqueKey", "validation_scope"): "A uniqueness constraint is a statement about "
                                       "the GOLDEN record, and POST_CONSO is what the "
                                       "one measured instance carries and what the "
                                       "block library records as its default. "
                                       "Pre-consolidation would test source rows that "
                                       "have not been consolidated yet, which is not a "
                                       "different policy — it is the wrong rows.",
    ("RootEntity", "cardinality"): "There is nothing to decide: the literal admits ONE "
                                   "value, because one is what has been measured. The "
                                   "docs describe a Multi Record mode but give its UI "
                                   "label, and START_FROM_NOTHING is standing proof "
                                   "that a label is not a wire string. This becomes a "
                                   "real decision the day a multi-record definition is "
                                   "harvested — and then it needs a Decision, not this "
                                   "entry.",
}


def decidable_fields() -> list[tuple[str, str, object]]:
    """(model class name, field, default) for every closed-vocabulary field that has a
    default — derived from the schema, so a field ADDED to the IR shows up here without
    anyone remembering to add it anywhere."""
    import inspect
    import typing

    from pydantic import BaseModel
    from pydantic_core import PydanticUndefined

    from agent.ir import schema as S

    out = []
    for name, obj in vars(S).items():
        if not (inspect.isclass(obj) and issubclass(obj, BaseModel)
                and obj.__module__ == S.__name__):
            continue
        for fname, f in obj.model_fields.items():
            if typing.get_origin(f.annotation) is not typing.Literal:
                continue
            if f.default is PydanticUndefined:
                continue              # required: the author always states it
            out.append((name, fname, f.default))
    return sorted(out)


def unwatched(ir=None) -> list[tuple[str, str, object]]:
    """Decidable fields the register never examines and nothing has excused.

    Empty is the only acceptable answer; anything else is a value that can be chosen
    for you without appearing in any report. Takes an optional IR only so the signature
    matches the rest of this module — the answer is a property of the SCHEMA, not of
    any one model, which is precisely why it can be asked before a model exists.
    """
    walked = {(KIND_TO_MODEL.get(kind), fname)
              for kind, _, fname, _ in (_walk(ir) if ir is not None else [])}
    walked |= {(KIND_TO_MODEL.get(kind), fname) for kind, fname in GOVERNED}
    return [(m, f, d) for m, f, d in decidable_fields()
            if (m, f) not in walked and (m, f) not in NOT_WATCHED]
