"""Survivorship PROPOSALS — an answer sheet for CA-002. Sprint 12, deliverable 1.

CA-002 asks *"6 attributes have no survivorship rule — which value wins?"* and stops.
That is the right question and a poor deliverable: the designer still faces a blank
page and writes six rules by hand. This module answers it — one proposal per uncovered
attribute, from the attribute's datatype, its name, and the house policy on disk —
so the advisory becomes a REVIEW instead of an authoring task.

Three properties are architecture here, not style.

**Observed vocabulary only.** The legal strategy names are the ones the six-model
corpus actually writes on the wire (`OBSERVED_STRATEGIES` below, each with the export
it was counted in). The sprint file was harvested from a sibling project whose
vocabulary is a SEML dialect — `MostRecentTrue`, `ValidatedOnly`, `PublisherPriority`,
`LongestValue`. If a heuristic wants one of those, this module EMITS NOTHING for that
attribute and records a `Refusal` saying why. Same rule for a name that is documented
and never observed: `MOST_FREQUENT_VALUE` is a docs LABEL ("Most Frequent Value"), and
LESSONS §51.2 measured a docs label differing from the wire string it is supposed to
be (`START_FROM_EMPTY_SELECTION` -> `START_FROM_NOTHING`). Documented is not measured.

**Every proposal is tagged for review.** With the tag this repo already uses —
`[uncited — model judgement]`, from `agent.tools.citation.UNCITED` — one convention,
not two. `propose()` returns DATA. It never touches certify.yaml; the operator decides
what lands on disk, which is the whole point of Principle 2.1 applied to a suggestion.

**Proposals go through emit, not around it.** `splice()` returns an IR with the
proposed rules in it so the caller can compile them the normal way. A proposal that
cannot be compiled is not advice, it is a second dialect.

--------------------------------------------------------------------------- policy
House policy leads, the heuristic table follows. `agent/ir/policy.py` decides:

  * the OVERRIDE strategy on every proposal — `policy.override_strategy(computed=…)`,
    which is the operator's 2026-08-03 ruling that overrides are for values a PERSON
    types. Note the spelling: the forbidding value is `NO_OVERRIDE`. The sprint table
    says "override NEVER"; `NEVER` was an invention that survived every offline check
    until the live importer refused the whole payload (LESSONS §16, and the comment
    over `policy.OVERRIDE_STRATEGIES`).
  * the top of every publisher ranking — `policy.STEWARD_RANKS_FIRST` with
    `policy.STEWARD_PUBLISHER_CODES`. "Steward authored data should be more trustable."

Policy names no default per-attribute STRATEGY, so the strategy is where the heuristic
table applies. If policy ever grows one, it wins and the table becomes the fallback.

------------------------------------------------------------------- the open ranking
`PREFERRED_PUBLISHER` needs a ranking (IR-011), the ranking must name declared
publishers (IR-008), and the emitter resolves each name to a publisher UUID. So a
proposal cannot leave the list empty and still compile. It also must not GUESS an
authority order the operator has never stated. Both are true at once, so the ranking is
emitted in **declared order below the steward publisher** and every such proposal
carries that as an explicit `open_question`. A placeholder that announces itself is the
only shape that is both compilable and honest — the alternative, an invented ranking
that reads as a decision, is the §51 mistake with a reassuring name.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from agent.ir import policy
from agent.ir.schema import IR, CertifyIR, ModelIR, SurvivorshipRule
from agent.tools.citation import UNCITED

#: The consolidation strategies THE PRODUCT WRITES, with where each spelling was
#: counted. Product-authored exports only — `live/AccountHub.xml` and
#: `live/PartyHubProbe.xml` are xDM's re-export of this compiler's own output and would
#: attest our spelling back to us (`harvest_blocks.COMPILER_DERIVED`, LESSONS §2/§48).
#: Re-measure with:
#:     grep -o 'consolidationStrategy val="[A-Z_]*"' samples/*.xml live/*.xml \
#:          harvest/*.xml
OBSERVED_STRATEGIES: dict[str, str] = {
    "PREFERRED_PUBLISHER": "25 — corpus-a-org-mdm 5, gs-customerb2c 10, "
                           "harvest/CustomerB2CDemo.workflow 10",
    "LARGEST_VALUE": "1 — samples/corpus-a-org-mdm-0.1.xml "
                     "(plus 1 in samples/xdm-xml-authoring-guide.md)",
    "SMALLEST_VALUE": "1 — samples/corpus-a-org-mdm-0.1.xml",
    "CUSTOM_RANKING": "2 — live/PartyRoleModels.xml",
}
LEGAL_STRATEGIES: tuple[str, ...] = tuple(OBSERVED_STRATEGIES)

#: Names a heuristic might reach for and this module refuses, each with the reason.
#: A refusal names the way out, the same way `blocks.check` does: build it once in the
#: designer, export it, and the name becomes evidence instead of a guess.
REFUSED_STRATEGIES: dict[str, str] = {
    "MostRecentTrue": "sibling-project SEML dialect; no export writes it and no docs "
                      "page names it. There is no observed 'most recent true' strategy "
                      "— a Boolean gets PREFERRED_PUBLISHER instead.",
    "ValidatedOnly": "sibling-project SEML dialect; no observed equivalent at all.",
    "PublisherPriority": "the dialect's name for what the product spells "
                         "PREFERRED_PUBLISHER.",
    "LongestValue": "the dialect's name for what the product spells LARGEST_VALUE — "
                    "and note the two do not even mean the same thing: LARGEST_VALUE "
                    "sorts type-specific, it does not measure length.",
    "MOST_FREQUENT_VALUE": "DOCS-GRADE ONLY. docs/Design/matching/survivorship.md "
                           "§ Consolidation strategy lists the UI label 'Most Frequent "
                           "Value', and no export in samples/, live/ or harvest/ "
                           "carries a wire spelling for it. LESSONS §51.2 measured a "
                           "docs label differing from the wire string, so the "
                           "underscored guess is not evidence. Build one rule with it "
                           "in the designer, export into harvest/, and it becomes "
                           "legal.",
}

#: docs/Design/matching/survivorship.md § Consolidation strategy: "Only the Custom
#: Ranking and Preferred Publisher strategies work for consolidation rules involving
#: multiple attributes." So a LARGEST_VALUE proposal is always one rule, one attribute.
MULTI_ATTRIBUTE_STRATEGIES: tuple[str, ...] = ("CUSTOM_RANKING", "PREFERRED_PUBLISHER")

_SEE = "docs/Design/matching/survivorship.md § Consolidation strategy"
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")

# ------------------------------------------------------------------ the name patterns
#: `*_ID`, `*GoldenID`, `MDM_*` — identity, which survives via the golden ID rather
#: than via a value-comparing rule. DELIBERATELY NARROW: a bare `…Id` suffix is not
#: enough, because `TaxId` and `VatId` are publisher-supplied business values that
#: deserve a real rule, and mistaking one for an identifier silently hands it to the
#: default rule.
_IDENTITY = re.compile(r"(^MDM_|_[Ii][Dd]$|Golden[Ii][Dd]$)")
#: `FullName`, `DisplayName`, `Middle*`, `*Suffix` — keep the most complete value.
_COMPLETENESS = re.compile(r"(FullName|DisplayName|^Middle|Suffix$)", re.I)
#: `Email*`, `Phone*` — volatile contact detail; the authoritative source wins.
_CONTACT = re.compile(r"^(email|phone)", re.I)
_BOOLEAN_TYPES = ("Boolean",)


@dataclass(frozen=True)
class Proposal:
    """One proposed survivorship rule, with why it was proposed and what is still open.

    `rule` is a real `SurvivorshipRule`, ready to splice and compile. `tag` is on every
    instance and is not a formatting detail: it is what stops a proposal reading as a
    decision somebody made.
    """
    entity: str
    attributes: tuple[str, ...]
    rule: SurvivorshipRule
    why: str
    provenance: str                       # "policy" | "heuristic" | "corpus"
    open_questions: tuple[str, ...] = ()
    tag: str = UNCITED

    @property
    def strategy(self) -> str:
        return self.rule.strategy

    def render(self) -> str:
        who = ", ".join(self.attributes) or f"{self.entity} (whole entity)"
        head = f"  {self.entity}.{who} -> {self.rule.strategy}  {self.tag}"
        body = [f"      rule {self.rule.name} ({self.rule.kind})"]
        if self.rule.kind == "standard":
            body.append(f"      override {self.rule.override_strategy}")
        if self.rule.publisher_rankings:
            body.append("      ranking " + " > ".join(self.rule.publisher_rankings))
        body.append(f"      why  {self.why}  [{self.provenance}]")
        for q in self.open_questions:
            body.append(f"      OPEN {q}")
        return "\n".join([head, *body])


@dataclass(frozen=True)
class Refusal:
    """An attribute the proposer deliberately left alone, and the reason.

    A refusal is a first-class output, not a hole in the coverage. "No observed
    strategy fits" is information the designer needs; silently defaulting to
    PREFERRED_PUBLISHER because it is the common one would hide it.
    """
    entity: str
    attribute: str
    wanted: str                            # the strategy the heuristic reached for
    why: str

    def render(self) -> str:
        head = f"  {self.entity}.{self.attribute} -> NO PROPOSAL"
        if self.wanted:
            head += f" (wanted {self.wanted})"
        return f"{head}\n      {self.why}"


@dataclass(frozen=True)
class Proposals:
    proposals: tuple[Proposal, ...] = ()
    refusals: tuple[Refusal, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.proposals or self.refusals)

    def for_entity(self, entity: str) -> "Proposals":
        return Proposals(tuple(p for p in self.proposals if p.entity == entity),
                         tuple(r for r in self.refusals if r.entity == entity))

    def rules(self) -> list[SurvivorshipRule]:
        return [p.rule for p in self.proposals]

    def render(self) -> str:
        if not self:
            return "no uncovered attributes — nothing to propose"
        out = []
        if self.proposals:
            out.append(f"{len(self.proposals)} proposed survivorship rule(s), "
                       f"ALL tagged {UNCITED} — review, do not adopt:")
            out += [p.render() for p in self.proposals]
        if self.refusals:
            out.append(f"{len(self.refusals)} attribute(s) with no proposal:")
            out += [r.render() for r in self.refusals]
        out.append(f"  see: {_SEE}")
        return "\n".join(out)


# ------------------------------------------------------------------------- the inputs
ALL_SCOPES: tuple[str, ...] = ("PRE_CONSO", "POST_CONSO")


def computed_attributes(certify: CertifyIR, entity: str,
                        scopes: tuple[str, ...] = ALL_SCOPES) -> set[str]:
    """Attributes an enricher COMPUTES, as opposed to normalizing IN PLACE.

    The CA-012 predicate, lifted here so there is one copy: an expression that reads
    the attribute it writes (``Email <- LOWER(TRIM(Email))``) is still carrying a
    publisher's value, and survivorship very much applies to it. One that does not is
    produced by the pipeline, and "which source wins" is the wrong question about it.

    Widened past CA-002's PRE_CONSO by the `scopes` default, because a POST_CONSO
    enricher output is owned by the pipeline for exactly the same reason — and it is
    the case that actually reaches this module, since CA-002 already excludes the
    PRE_CONSO ones from its exposed set.
    """
    return {expr.attribute
            for en in certify.enrichers
            if en.entity == entity and (en.scope or "") in scopes
            for expr in en.expressions
            if expr.attribute not in _IDENT.findall(expr.expression)}


def uncovered(ir: IR, entity: str) -> list[str]:
    """The attributes CA-002 is asking about, in declaration order.

    Mirrors CA-002's exposed set exactly — non-PK, no survivorship rule scoping it, not
    computed in place PRE_CONSO — because a proposal for an attribute the advisory did
    not name would be answering a question nobody asked.
    """
    e = next((x for x in ir.model_ir.entities if x.name == entity), None)
    if e is None:
        return []
    covered = {name for s in ir.certify.survivorship if s.entity == entity
               for name in s.attributes}
    derived_here = computed_attributes(ir.certify, entity, scopes=("PRE_CONSO",))
    return [a.name for a in e.attributes
            if not a.pk and a.name not in covered and a.name not in derived_here]


def publisher_ranking(model_ir: ModelIR) -> tuple[list[str], tuple[str, ...]]:
    """A ranking by publisher NAME (IR-008 refuses codes), plus what is still open.

    Policy fixes the TOP of the list and nothing else: "Steward authored data should be
    more trustable... The REST of the ranking is engagement-specific and must be asked
    for". Everything below the steward publisher is declared order, which is a
    placeholder and is reported as one.
    """
    pubs = [p for p in model_ir.publishers]
    if not pubs:
        return [], ()
    stewards = [p for p in pubs if policy.is_steward_publisher(p.code)] \
        if policy.STEWARD_RANKS_FIRST else []
    rest = [p for p in pubs if p not in stewards]
    ranking = [p.name for p in stewards] + [p.name for p in rest]
    if len(rest) < 2:
        return ranking, ()
    order = " > ".join(p.name for p in rest)
    if stewards:
        return ranking, (
            f"ranking below the steward publisher(s) "
            f"{', '.join(p.name for p in stewards)} is DECLARED ORDER, not a decision "
            f"({order}) — which of those sources is more authoritative?",)
    return ranking, (
        f"no steward/manual publisher is declared, so the WHOLE ranking is declared "
        f"order, not a decision ({order}) — rank these by authority.",)


# ------------------------------------------------------------------- the rule factory
def _rule_name(entity: str, attribute: str, taken: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9]", "", attribute) or entity
    name = f"Proposed{stem}Rule"
    n = 2
    while name in taken:
        name, n = f"Proposed{stem}Rule{n}", n + 1
    taken.add(name)
    return name


def _standard(entity: str, attribute: str, strategy: str, *, taken: set[str],
              computed: bool, ranking: list[str]) -> SurvivorshipRule:
    if strategy not in LEGAL_STRATEGIES:                      # belt and braces
        raise ValueError(f"{strategy!r} is not an observed consolidation strategy; "
                         f"observed: {', '.join(LEGAL_STRATEGIES)}")
    return SurvivorshipRule(
        entity=entity,
        name=_rule_name(entity, attribute, taken),
        strategy=strategy,
        attributes=[attribute],
        kind="standard",
        # policy.override_strategy is the operator's ruling, not a heuristic.
        override_strategy=policy.override_strategy(computed=computed),
        publisher_rankings=list(ranking) if strategy == "PREFERRED_PUBLISHER" else [],
    )


# ------------------------------------------------------------------------ the proposer
def propose(ir: IR, entity: str | None = None) -> Proposals:
    """Propose one survivorship rule per uncovered attribute. Never mutates `ir`."""
    ranking, ranking_open = publisher_ranking(ir.model_ir)
    proposals: list[Proposal] = []
    refusals: list[Refusal] = []

    for e in ir.model_ir.entities:
        if entity is not None and e.name != entity:
            continue
        # A basic entity overwrites the golden record; nothing consolidates, and
        # IR-002 makes a survivorship rule on one an ERROR. Proposing there would be
        # proposing a defect.
        if e.type not in ("id_matched", "fuzzy"):
            continue
        names = uncovered(ir, e.name)
        if not names:
            continue
        taken = {s.name for s in ir.certify.survivorship if s.entity == e.name}
        computed = computed_attributes(ir.certify, e.name)
        types = {a.name: a.type for a in e.attributes}
        has_id_rule = any(s.entity == e.name and s.kind == "id"
                          for s in ir.certify.survivorship)

        for a in names:
            # ---- 1. identity: it survives via the golden ID, not via a value rule
            if _IDENTITY.search(a):
                if has_id_rule:
                    refusals.append(Refusal(
                        e.name, a, "",
                        "identity attribute: it survives via the golden ID, and this "
                        "entity already has a Master ID rule (IR-019 resolves exactly "
                        "one). MEASURED on all 4 IdSurvivorshipRule instances in the "
                        "corpus: an id rule carries publisher rankings and NO "
                        "attribute list, so it cannot be made to name this attribute. "
                        "Scope it with a standard rule only if it is a real "
                        "publisher-supplied value rather than an identifier."))
                    continue
                # Exactly one per matched entity, so it is proposed once and then the
                # rest of the identity attributes fall to the branch above.
                rule = SurvivorshipRule(
                    entity=e.name, name=_rule_name(e.name, "MasterId", taken),
                    strategy="PREFERRED_PUBLISHER", attributes=[], kind="id",
                    publisher_rankings=list(ranking))
                has_id_rule = True
                proposals.append(Proposal(
                    e.name, (), rule,
                    f"{a} is an identity attribute and this matched entity has no "
                    f"Master ID rule — the rule that decides WHICH matched master's ID "
                    f"becomes the golden ID. Without it the import returns 204 and the "
                    f"deploy dies in Entity.getIdSurvivorshipRule (IR-019).",
                    "corpus", ranking_open))
                continue

            # ---- 2. enricher output: the pipeline owns the value
            if a in computed:
                proposals.append(Proposal(
                    e.name, (a,),
                    _standard(e.name, a, "PREFERRED_PUBLISHER", taken=taken,
                              computed=True, ranking=ranking),
                    "computed by an enricher, so the pipeline owns it: override is "
                    f"{policy.OVERRIDE_FORBIDDEN} (policy, 2026-08-03 — a steward edit "
                    "here is a value the next certification run silently discards). "
                    "Note the spelling: NEVER is a dialect name the live importer "
                    "refused.",
                    "policy", ranking_open))
                continue

            # ---- 3. Boolean: no observed most-recent-true, and none is invented
            if types.get(a) in _BOOLEAN_TYPES:
                proposals.append(Proposal(
                    e.name, (a,),
                    _standard(e.name, a, "PREFERRED_PUBLISHER", taken=taken,
                              computed=False, ranking=ranking),
                    "Boolean. The sibling project proposes MostRecentTrue here; that "
                    "name appears in no export and in no docs page, so it is refused "
                    "and the authoritative source decides instead. LARGEST_VALUE is "
                    "not an option either — the docs say binary attributes do not "
                    "support it.",
                    "heuristic", ranking_open))
                continue

            # ---- 4. completeness: keep the fullest value
            if _COMPLETENESS.search(a):
                proposals.append(Proposal(
                    e.name, (a,),
                    _standard(e.name, a, "LARGEST_VALUE", taken=taken,
                              computed=False, ranking=ranking),
                    "a name part is more useful complete than short, and LARGEST_VALUE "
                    "sorts type-specific — for a string that is alphabetical, NOT by "
                    "length, so this is a proposal to review rather than a rule to "
                    "trust. One attribute per rule: the docs allow multi-attribute "
                    "rules only for CUSTOM_RANKING and PREFERRED_PUBLISHER.",
                    "heuristic"))
                continue

            # ---- 5. volatile contact detail
            if _CONTACT.search(a):
                proposals.append(Proposal(
                    e.name, (a,),
                    _standard(e.name, a, "PREFERRED_PUBLISHER", taken=taken,
                              computed=False, ranking=ranking),
                    "volatile contact detail — the authoritative source wins, not the "
                    "largest string.",
                    "heuristic", ranking_open))
                continue

            # ---- 6. everything else: ask for the ranking, do not guess it
            proposals.append(Proposal(
                e.name, (a,),
                _standard(e.name, a, "PREFERRED_PUBLISHER", taken=taken,
                          computed=False, ranking=ranking),
                "no name or type signal says the VALUES should decide, so the SOURCE "
                "does. This is the row that most needs the ranking answered.",
                "heuristic", ranking_open))

    # A PREFERRED_PUBLISHER rule with no ranking is IR-011, and the emitter has no
    # publisher to resolve. Refuse rather than emit something that cannot compile.
    if not ranking:
        keep, dropped = [], []
        for p in proposals:
            if p.strategy == "PREFERRED_PUBLISHER":
                dropped.append(Refusal(
                    p.entity, ", ".join(p.attributes) or "(id rule)", p.strategy,
                    "PREFERRED_PUBLISHER needs a publisher ranking (IR-011) and this "
                    "model declares no publishers. Declare them, or choose a "
                    "value-comparing strategy."))
            else:
                keep.append(p)
        proposals, refusals = keep, refusals + dropped

    return Proposals(tuple(proposals), tuple(refusals))


def splice(ir: IR, proposals: Proposals | None = None) -> IR:
    """A COPY of `ir` with the proposed rules in it, ready for `emit`.

    In memory only. Writing proposals to certify.yaml is the operator's call, and a
    tagged suggestion that adopts itself is not tagged.
    """
    proposals = propose(ir) if proposals is None else proposals
    out = ir.model_copy(deep=True)
    out.certify.survivorship.extend(copy.deepcopy(r) for r in proposals.rules())
    return out


def render(ir_or_proposals: IR | Proposals) -> str:
    p = (ir_or_proposals if isinstance(ir_or_proposals, Proposals)
         else propose(ir_or_proposals))
    return p.render()
