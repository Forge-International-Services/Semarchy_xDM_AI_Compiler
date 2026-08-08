"""Semantic validation of the IR. Sprint 04.

Each rule is cheap here and expensive to discover at xDM validation time — or, in
the case of IR-009, expensive to discover *months* later as inexplicably bad match
rates. Every rule cites the source that justifies it.

Errors block compilation. Warnings require `acknowledged: true` in the IR, so an
author has to look at them rather than scroll past.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from agent.compile.emit import complex_prefixes, physical
from agent.ir.schema import IR, XDM_TYPES

RESERVED = frozenset({"and", "or", "not", "null", "like", "in", "between",
                      "record1", "record2", "select", "from", "where"})
#: Bare function-call names, for IR-027. Deliberately NOT the three-part form
#: _UDF matches — this rule is about calls that carry no qualification at all.
_CALLS = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\(")
_UDF = re.compile(r"\b([A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*)\s*\(")
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")


@dataclass(frozen=True)
class Issue:
    rule: str
    severity: Literal["error", "warning"]
    where: str
    message: str
    why: str = ""
    see: str = ""

    def render(self) -> str:
        tail = f"\n    {self.why}" if self.why else ""
        tail += f"\n    see: {self.see}" if self.see else ""
        return f"[{self.rule}] {self.severity.upper()} {self.where}: {self.message}{tail}"


def validate(ir: IR) -> list[Issue]:
    m, c = ir.model_ir, ir.certify
    out: list[Issue] = []
    ents = {e.name: e for e in m.entities}
    matchers = {x.entity: x for x in c.matchers}

    def add(rule, sev, where, msg, why="", see=""):
        out.append(Issue(rule, sev, where, msg, why, see))

    # 1 / 2 / 3 — entity type constrains everything downstream
    for e in m.entities:
        if e.type == "fuzzy" and e.name not in matchers:
            add("IR-001", "error", e.name, "fuzzy entity has no matcher",
                "Fuzzy matching needs match rules; without a matcher nothing merges.",
                "docs/Design/logical-model/entities.md")
        if e.type == "basic":
            if any(s.entity == e.name for s in c.survivorship):
                add("IR-002", "error", e.name,
                    "basic entity has survivorship rules",
                    "Basic entities overwrite the golden record; nothing consolidates.",
                    "docs/Design/logical-model/entities.md")
        pks = [a.name for a in e.attributes if a.pk]
        if e.type == "id_matched" and len(pks) != 1:
            add("IR-003", "error", e.name,
                f"ID-matched entity has {len(pks)} PK attributes, needs exactly 1",
                "A composite key must be concatenated into a single PK column.",
                "docs/Design/logical-model/entities.md")

        # IR-026 — the golden-ID generator must agree with the PK datatype.
        #
        # MEASURED, not authored: 26 PKAttributes across the 10 exports in samples/,
        # live/ and harvest/ carry `fuzzyMatchedEntityGoldenIdGenerationType`, and the
        # correspondence with the PK's datatype is a biconditional with no exceptions —
        #
        #     UUID PK        -> UUID       6/6
        #     String PK      -> SEQUENCE  11/11
        #     LongInteger PK -> SEQUENCE   9/9
        #
        # so a String or numeric key with SEQUENCE is attested, and only the UUID pair
        # is coupled in both directions.
        #
        # Neither half is caught by anything else. `decisions` checks the value against
        # the D-ID-GENERATION vocabulary one field at a time and reports `matches` —
        # this is a CROSS-FIELD constraint, and a per-field register is blind to it.
        # `blocks` sees a well-formed element. The failure is late and loud: the model
        # imports, deploys and persists, and the INTEGRATE_DATA job then dies on
        # "Handle Reset Matching" because SEQUENCE emits
        # `<ENTITY>_GOLDEN_ID = nextval('SEQ_<ENTITY>')` into a uuid column. That
        # suspends the queue, which in turn REFUSES the next redeploy. OBSERVED on
        # scenario 3, 2026-08-04; latent in scenario 4 until this rule was written.
        #
        # `observed` provenance, so a divergence is an error, not advice (§ decision
        # attribution: it does not make a different design, it makes a model that will
        # not run).
        pk_attrs = [a for a in e.attributes if a.pk]
        for a in pk_attrs:
            uuid_key = a.type == "UUID"
            uuid_gen = e.golden_id_generation == "UUID"
            if uuid_key and not uuid_gen:
                add("IR-026", "error", f"{e.name}.{a.name}",
                    f"PK is UUID but golden_id_generation is "
                    f"{e.golden_id_generation!r}",
                    "SEQUENCE emits nextval() into a uuid column: the model deploys "
                    "and loads, then INTEGRATE_DATA fails on Handle Reset Matching "
                    "and suspends the queue. Set golden_id_generation: UUID.",
                    "LESSONS.md §19")
            elif uuid_gen and not uuid_key:
                add("IR-026", "error", f"{e.name}.{a.name}",
                    f"golden_id_generation is UUID but the PK is {a.type!r}",
                    "No export pairs a UUID generator with a non-UUID key; the "
                    "generated value will not fit the column.",
                    "LESSONS.md §19")

    # 4 — one matcher per entity
    seen: set[str] = set()
    for x in c.matchers:
        if x.entity in seen:
            add("IR-004", "error", x.entity, "more than one matcher", "", "AGENT.md")
        seen.add(x.entity)
        if x.entity not in ents:
            add("IR-008", "error", x.entity, "matcher references unknown entity")

    # 5 — Record1/Record2 on opposite sides
    for x in c.matchers:
        for r in x.rules:
            for side in re.split(r"\bAND\b|\bOR\b", r.condition, flags=re.I):
                if "=" not in side:
                    continue
                lhs, rhs = (s.lower() for s in side.partition("=")[::2])
                l1, l2 = "record1" in lhs, "record2" in lhs
                r1, r2 = "record1" in rhs, "record2" in rhs
                # A comparison against a CONSTANT is a per-record predicate, not a
                # pair comparison — "this record's tax id is well formed" is a
                # perfectly good conjunct of a match rule. The earlier form of this
                # test only tolerated it on Record1: with `Record2.X = 9` neither side
                # mentioned Record1, the two halves compared equal, and a correct rule
                # was refused. An asymmetric check that passes one spelling and rejects
                # its mirror image is a bug in the check.
                if not (l1 or l2) or not (r1 or r2):
                    continue
                if not ((l1 and r2) or (l2 and r1)) or (l1 and r1) or (l2 and r2):
                    add("IR-005", "error", f"{x.entity}/{r.name}",
                        "Record1 and Record2 are not on opposite sides of a comparison",
                        "Comparing a record to itself matches everything or nothing.",
                        "AGENT.md")
                    break

    # 6 — naming
    for p in m.publishers:
        if p.code != p.code.upper():
            add("IR-006", "error", p.name, f"publisher code {p.code!r} is not uppercase",
                "", "docs/Design/data-certification/publishers.md")
    for e in m.entities:
        if not e.name[:1].isupper():
            add("IR-006", "error", e.name, "entity name is not InitCap", "", "AGENT.md")

    # 7 / 8 — references resolve
    lovs = {l.name for l in m.lov_types}
    ctypes = {t.name for t in m.complex_types}
    # An attribute's type may be a built-in, or a type the model itself declares —
    # an LOV type or a user-defined type. Both are legitimate.
    declared_types = lovs | ctypes | {u.name for u in m.user_defined_types}
    for e in m.entities:
        for a in e.attributes:
            if a.type not in XDM_TYPES and a.type not in declared_types:
                add("IR-013", "error", f"{e.name}.{a.name}",
                    f"{a.type!r} is neither an xDM built-in nor a declared "
                    f"LOV / user-defined type",
                    "", "docs/Design/logical-model/built-in-datatypes.md")
        for ca in e.complex_attributes:
            if ca.type not in ctypes:
                add("IR-007", "error", f"{e.name}.{ca.name}",
                    f"complex type {ca.type!r} is not declared")
    for r in m.references:
        for side in ("from_entity", "to_entity"):
            if getattr(r, side) not in ents:
                add("IR-008", "error", r.name,
                    f"{side} {getattr(r, side)!r} is not a declared entity")

    # 9 — the rule that earns its keep
    matched_attrs: dict[str, set[str]] = {}
    for x in c.matchers:
        refs: set[str] = set()
        for r in x.rules:
            refs |= {i.split(".")[-1] for i in _IDENT.findall(r.condition)}
            refs |= {b.split(".")[-1] for b in r.binning}
        matched_attrs[x.entity] = refs
    for en in c.enrichers:
        if en.kind != "semql" or en.scope != "POST_CONSO":
            continue
        used = matched_attrs.get(en.entity, set())
        for expr in en.expressions:
            if expr.attribute in used:
                add("IR-009", "error", f"{en.entity}/{en.name}",
                    f"POST_CONSO enricher writes {expr.attribute!r}, which a match rule reads",
                    "Matching runs on master records, so its inputs must be PRE_CONSO. "
                    "This is invisible at import and surfaces later as bad match rates.",
                    "AGENT_DESIGN.md §3.2")

    # 16 — scope ordering between enrichers
    # IR-009 only sees an enricher whose output a match rule reads DIRECTLY. A chain
    # hides the same bug: NormalizeName -> NormalizedName -> PhoneticName ->
    # PhoneticNameToken -> read by a match rule. Flipping the FIRST link to POST_CONSO
    # breaks matching just as thoroughly, and IR-009 does not see it because no rule
    # names NormalizedName. Found by asking whether the checks could have failed.
    writes: dict[str, tuple[str, str | None]] = {}
    for en in c.enrichers:
        for expr in en.expressions:
            writes[f"{en.entity}.{expr.attribute}"] = (en.name, en.scope)
    for en in c.enrichers:
        if en.scope != "PRE_CONSO":
            continue
        for expr in en.expressions:
            for ident in _IDENT.findall(expr.expression):
                key = f"{en.entity}.{ident.split('.')[-1]}"
                producer = writes.get(key)
                if producer and producer[1] == "POST_CONSO":
                    add("IR-016", "error", f"{en.entity}/{en.name}",
                        f"PRE_CONSO enricher reads {ident!r}, written by POST_CONSO "
                        f"enricher {producer[0]!r}",
                        "The producer runs after the consumer, so the value is not yet "
                        "computed. Chains like this hide the IR-009 failure one step "
                        "further back.")

    # 10 — unbinned probabilistic rules
    for x in c.matchers:
        for r in x.rules:
            if not r.binning and r.score < 100 and not (r.acknowledged and r.justification):
                add("IR-010", "warning", f"{x.entity}/{r.name}",
                    "probabilistic rule has no binning",
                    "An unbinned rule compares the full cartesian product within scope. "
                    "Set `acknowledged: true` with a `justification` to accept this.")

    # 11 — PREFERRED_PUBLISHER needs rankings
    for s in c.survivorship:
        if s.strategy.upper() == "PREFERRED_PUBLISHER" and not s.publisher_rankings:
            add("IR-011", "error", f"{s.entity}/{s.name}",
                "PREFERRED_PUBLISHER strategy has no publisher_rankings",
                "", "authoring guide §5.7")

    # 19 — a matched entity MUST have exactly one Master ID survivorship rule.
    # DEPLOY-CRITICAL and invisible everywhere upstream: the IR validates, the XML
    # compiles, the import returns 204, and the deploy dies with a bare 500 whose only
    # trace is `Entity.getIdSurvivorshipRule` -> `Optional.get() cannot be called on an
    # absent value`. OBSERVED 2026-08-04.
    # Scoped to entities whose certification is actually being authored here: a model
    # extracted without its certification layer has nothing for this rule to judge,
    # and firing there would make model-only validation permanently red.
    matched = {e.name for e in m.entities if e.type in ("fuzzy", "id_matched")}
    certified = ({s.entity for s in c.survivorship} | {x.entity for x in c.matchers})
    id_rules: dict[str, list[str]] = {n: [] for n in matched & certified}
    for s in c.survivorship:
        if s.kind == "id" and s.entity in id_rules:
            id_rules[s.entity].append(s.name)
    for ename, names in id_rules.items():
        if not names:
            add("IR-019", "error", ename,
                f"{ename} is a matched entity with no Master ID survivorship rule",
                "It decides WHICH matched master record's ID becomes the golden ID. "
                "Add a rule with `kind: id`; it takes publisher_rankings and no "
                "attributes or override strategy.",
                "docs/Design/matching/survivorship.md")
        elif len(names) > 1:
            add("IR-019", "error", ename,
                f"{ename} has {len(names)} Master ID survivorship rules: "
                f"{', '.join(names)}",
                "xDM resolves exactly one. Keep the intended rule and delete the rest.",
                "docs/Design/matching/survivorship.md")

    # 21 — an enricher must run AFTER whatever writes the value it reads.
    # IR-009 and IR-016 police the SCOPE boundary (PRE vs POST_CONSO). This is the
    # ordering INSIDE a scope, which is a different failure and a silent one: the
    # integration job runs enrichers in POSITION order, so a consumer sharing a
    # position with its producer hashes a null. It shipped exactly that way —
    # PhoneticNameToken was empty on every master record and both phonetic match
    # rules were dead, with nothing failing (LESSONS §20).
    #
    # EQUAL positions violate this too. xDM promises no order within a position, so
    # "it worked in the single-record probe" is not a property to rely on — and in the
    # batch job it did not work.
    from agent.ir.depends import cycles as _cycles, execution_order, order_violations
    _want = None
    for dep, ppos, cpos in order_violations(ir):
        # An IN-PLACE producer leaves the attribute populated with the publisher's
        # value, so running before it reads the RAW value and not a null. That is the
        # whole design of a capture-the-inbound-value enricher, so it is reported and
        # not refused — the two failures are different and only one of them is silent.
        if dep.in_place:
            add("IR-021", "warning", f"{dep.entity}/{dep.consumer}",
                f"reads {dep.attribute!r} at position {cpos}, before {dep.producer!r} "
                f"rewrites it IN PLACE at position {ppos}",
                "So this reads the RAW inbound value, not a null. Deliberate if the "
                "point is to preserve the value before it is standardized; a bug if "
                "this expected the standardized form. Say which — there is no way to "
                "tell from the IR.",
                "LESSONS.md §47")
            continue
        if _want is None:
            _want = execution_order(ir)
        add("IR-021", "error", f"{dep.entity}/{dep.consumer}",
            f"reads {dep.attribute!r}, written by {dep.producer!r} at position "
            f"{ppos}, but sits at position {cpos}",
            f"The integration job runs enrichers in position order, so this one reads "
            f"a NULL. Nothing fails — the value is simply empty, and anything matching "
            f"on it silently stops matching. Suggested: {dep.producer}="
            f"{_want[(dep.entity, dep.producer)]}, {dep.consumer}="
            f"{_want[(dep.entity, dep.consumer)]}.",
            "LESSONS.md §20")
    for entity, a, b in _cycles(ir):
        add("IR-021", "error", f"{entity}/{a}",
            f"enrichers {a!r} and {b!r} each read what the other writes",
            "No position order can satisfy both; one of them must read a "
            "publisher-supplied value instead.", "LESSONS.md §20")

    # 22 — the compiler must not be MORE PERMISSIVE than the designer. Each of these
    # is a dialog that refuses to close in the product; a generated model that skips
    # them imports cleanly and then renders an empty screen.
    from agent.ir.depends import missing_prerequisites
    for miss in missing_prerequisites(ir):
        add("IR-022", "error", miss.where,
            f"needs {miss.needs}", miss.detail, "harvest/FINDINGS.md")

    # 23 — a match rule that cannot reach the review band only does harm.
    # The group confidence score is the AVERAGE of its pair scores, so a weak rule both
    # manufactures pairs that drag that average down and pulls extra records into the
    # group transitively. A group holding two certain duplicates plus one 10-scoring
    # pair scores (100 + 100 + 10) / 3 = 70 and drops out of the review band entirely.
    # Warning rather than error: a deliberately low rule used purely for grouping is
    # conceivable, and `acknowledged: true` forces the author to say so out loud.
    from agent.ir.policy import MATCH_RULE_SCORE_FLOOR
    for x in c.matchers:
        floor = (x.policy.review_from if x.policy is not None
                 else MATCH_RULE_SCORE_FLOOR)
        for r in x.rules:
            if r.score < floor and not r.acknowledged:
                add("IR-023", "warning", f"{x.entity}/{r.name}",
                    f"scores {r.score}, below the {floor} review band",
                    "It can never on its own make a pair reviewable, and the group "
                    "confidence score is the AVERAGE of pair scores — so this rule "
                    "manufactures pairs that drag genuine duplicates BELOW the band "
                    "and pulls extra records in transitively. Raise it, delete it, or "
                    "acknowledge it.",
                    "agent/ir/policy.py § match rule scoring")

    # 24 — grid view needs an image to put in the grid.
    # `IllegalStateException: GridList requires DisplayCard primaryImage to be defined`,
    # raised by CollectionViewBuilder during DEPLOY. The import accepts it happily.
    cards = {(c.entity, c.name): c for c in ir.app.display_cards}
    for coll in ir.app.collections:
        if not coll.grid_allowed:
            continue
        card = cards.get((coll.entity, coll.display_card or ""))
        if card is None or not getattr(card, "primary_image", None):
            add("IR-024", "error", f"{coll.entity}/{coll.name}",
                "grid_allowed is true but its display card defines no primary_image",
                "The deployer refuses: 'GridList requires DisplayCard primaryImage to "
                "be defined'. Either set primary_image on the card, or leave grid "
                "view off — it is off in every collection in the corpus.",
                "harvest/FINDINGS.md")

    # 25 — an application needs EXACTLY ONE root folder, and everything under it.
    # "Missing root folder for: <app>", raised at DEPLOY time by the model-edition
    # deployer. The import accepts a rootless application without complaint.
    for a in ir.app.applications:
        roots = [x for x in a.actions if not x.parent_folder]
        folders = [x for x in roots if x.kind == "FolderAction"]
        if len(roots) != 1 or not folders:
            add("IR-025", "error", f"application {a.name}",
                f"{len(roots)} action(s) sit at the top level "
                f"({', '.join(x.name for x in roots) or 'none'}); an application needs "
                f"exactly one, and it must be a FolderAction",
                "The deployer refuses 'Missing root folder'. Every application in the "
                "corpus has a single root FolderAction with every other action "
                "parented beneath it.", "harvest/FINDINGS.md")

    # 20 — a value that contradicts something OBSERVED about the product is a bug.
    # The distinction comes straight off Decision.source and it is the whole point of
    # recording provenance: an `operator` decision is a PREFERENCE, and an engagement
    # that diverges is exercising judgement the operator explicitly reserved ("the
    # level of trust per publisher will vary on each company"). An `observed` decision
    # is EVIDENCE about what xDM accepts, and diverging from it does not produce a
    # different design — it produces a model that will not import.
    from agent.ir.decisions import DECISIONS, divergences
    _source = {d.id: d.source for d in DECISIONS}
    for a in divergences(ir):
        if _source.get(a.decision) != "observed":
            continue                      # advisory; advise.py surfaces it, not here
        d = next(x for x in DECISIONS if x.id == a.decision)
        add("IR-020", "error", f"{a.where}.{a.field_name}",
            f"{a.value!r} contradicts {a.decision}, which is OBSERVED behaviour of "
            f"the product, not house preference",
            f"{d.statement} Expected one of {d.expected()!r}.", d.see or "LESSONS.md")

    # 11b — a ranking must name a declared PUBLISHER, by NAME and not by code.
    # The distinction is invisible until compile time and easy to get backwards:
    # gs-customerb2c ranks `Marketing`, whose code is `MKT`. All four hand-authored
    # scenarios ranked by CODE, passed every validation, and then died in the emitter
    # with KeyError: 'publisher/CRM_EU'. A compiler KeyError is not a design error
    # message, so the check belongs here.
    pub_names = {p.name for p in m.publishers}
    pub_codes = {p.code: p.name for p in m.publishers}
    for s_ in c.survivorship:
        for name in s_.publisher_rankings:
            if name in pub_names:
                continue
            hint = (f" — that is the CODE of publisher {pub_codes[name]!r}; rank by "
                    f"NAME") if name in pub_codes else \
                   f" — declared publishers are {sorted(pub_names)}"
            add("IR-008", "error", f"{s_.entity}/{s_.name}",
                f"publisher_rankings names {name!r}, which is not a declared publisher"
                + hint,
                "Unresolvable at compile time, where it surfaces as a KeyError rather "
                "than as anything a designer can act on.")

    # 11c — two complex attributes cannot share a physical prefix.
    # xDM expands each into one physical column per member, all sharing the prefix, so
    # a collision is a duplicate column name. The compiler DERIVES unique prefixes, so
    # this fires only when an author pins them by hand — which is exactly when it is
    # easy to get wrong, and it is otherwise found by xDM's own validation after a
    # full compile and import.
    for e in m.entities:
        pinned: dict[str, str] = {}
        for ca in e.complex_attributes:
            if not ca.physical_prefix:
                continue
            key = ca.physical_prefix.upper()
            if key in pinned:
                add("IR-018", "error", f"{e.name}.{ca.name}",
                    f"physical_prefix {key!r} is already used by "
                    f"{pinned[key]!r} on the same entity",
                    "Both expand into physical columns with that prefix, so the "
                    "columns collide. The UI's convention is ADD then AD2.",
                    "docs/Design/logical-model/entities.md")
            pinned[key] = ca.name

    # IR-029 — the GENERATED physical column name is capped at 25 characters.
    #
    # A repository limit, and it is checked on the generated name rather than the
    # declared one — which is what makes it invisible while authoring. Two mechanisms
    # push a reasonable-looking name over:
    #
    #   derivation   `physical()` inserts `_` before EVERY capital, so a trailing `ID`
    #                becomes `_I_D` and `AccountClassificationCode` lands at 27.
    #   the prefix   a complex-type member is prefixed with its complex attribute's
    #                3-character prefix plus an underscore, so every member of every
    #                address structure pays four characters it cannot see from its own
    #                declaration. `AddrMelissaResultCode` is 24 alone and 28 as a column.
    #
    # An error rather than a warning: `physical_name` exists precisely so the author can
    # shorten it, so there is a fix that costs nothing and no reason to proceed without
    # it. The production org-hub export shortens these by hand (ADDRESS_LINE1_STD, ZIP4,
    # MELISSA_RESULT_CODE), which is the same decision reached in the designer.
    from agent.ir.policy import MAX_PHYSICAL_NAME
    for e in m.entities:
        for a in e.attributes:
            got = a.physical_name or physical(a.name)
            if len(got) > MAX_PHYSICAL_NAME:
                add("IR-029", "error", f"{e.name}.{a.name}",
                    f"generates physical column {got!r} ({len(got)} chars), over the "
                    f"{MAX_PHYSICAL_NAME}-character repository limit",
                    "Set `physical_name` to a shortened column name. The limit applies "
                    "to the GENERATED name, so it cannot be seen from the declared one.",
                    "the implementation guide § naming conventions")
        prefixes = complex_prefixes(e.complex_attributes)
        by_type = {t.name: t for t in m.complex_types}
        for ca in e.complex_attributes:
            ct = by_type.get(ca.type)
            if ct is None:
                continue                       # IR-007 already reports the dangling type
            for mem in ct.members:
                stem = mem.physical_name or physical(mem.name)
                got = f"{prefixes[ca.name]}_{stem}"
                if len(got) > MAX_PHYSICAL_NAME:
                    add("IR-029", "error", f"{e.name}.{ca.name}.{mem.name}",
                        f"generates physical column {got!r} ({len(got)} chars), over "
                        f"the {MAX_PHYSICAL_NAME}-character repository limit",
                        f"The complex attribute contributes the prefix "
                        f"{prefixes[ca.name]!r} plus an underscore, so the member has "
                        f"{MAX_PHYSICAL_NAME - len(prefixes[ca.name]) - 1} characters "
                        f"to work with. Set `physical_name` on the complex-type member "
                        f"— it is shared by every structure using this type.",
                        "the implementation guide § naming conventions")
    # A reference carries two physical names, and the SECOND one is an integration
    # contract rather than a cosmetic detail: the loader writes `F_`, `FP_` and `FS_`
    # onto `toRolePhysicalName`, so every publisher's file has to spell it. The product
    # truncates both at 25 (`ORGANIZATIONS_ORGANIZATIO` in the real org-hub export),
    # which means an over-long name does not fail — it silently becomes a different
    # column than the one the design named.
    for r in m.references:
        for field_, got in (("physical_name", r.physical_name or physical(r.name)),
                            ("to_role_physical",
                             r.to_role_physical
                             or physical(r.to_role or r.to_entity))):
            if len(got) > MAX_PHYSICAL_NAME:
                add("IR-029", "error", f"reference {r.name}",
                    f"{field_} generates {got!r} ({len(got)} chars), over the "
                    f"{MAX_PHYSICAL_NAME}-character repository limit",
                    "The product TRUNCATES rather than refusing, so the column that "
                    "ends up in the database is not the one this design named. Set "
                    f"`{field_}` explicitly — and keep the role short, because the "
                    "loader prefixes it with F_ / FP_ / FS_.",
                    "the implementation guide § naming conventions")

    # IR-030 — the model needs an INTEGRATION JOB, and the job's per-entity task is
    # what makes each certification phase actually run.
    #
    # OBSERVED on scenario 4, 2026-08-07. The model imported at 204, deployed, reached
    # DL_READY, accepted eight master records and four golden records over
    # PERSIST_DATA, echoed every enricher's output correctly — and then refused to
    # start:
    #
    #     HTTP 400  Cannot submit load [134] with job [INTEGRATE_DATA] and user [...]
    #               Job [INTEGRATE_DATA] does not exist. Known jobs are []
    #
    # Scenario 3 hit the same wall on 2026-08-04 and fixed it in its own certify.yaml.
    # That is precisely why this is a rule and not a comment: the fix lived in ONE
    # scenario's YAML, so s1, s2 and s4 were each free to rediscover it, and two of
    # them are sitting DEPLOYED right now having never been asked to run.
    #
    # Nothing else could have caught it. `blocks` compares the XML that WAS emitted
    # against the shapes the product writes, and a model with no <modelJobs> element
    # is shape-perfect — absence is not a malformed element. `decisions` reads values
    # out of fields that exist. `depends` owns execution order WITHIN an entity. The
    # missing thing here is a whole object, and only a rule that knows the object is
    # mandatory can miss it.
    #
    # This is the fifth bar, and it sits between deployable and runnable:
    #     round-trips != importable != exportable != deployable != SUBMITTABLE
    #                                                              != runnable
    #
    # SCOPED TO IRs THAT CARRY A CERTIFICATION DESIGN. A model-only IR — what `extract`
    # produces from a vendor export, and what a partial hand-authored spec looks like —
    # is a legitimate artefact with an empty `certify`, and demanding a job of it would
    # refuse the thing the extractor is FOR. The moment an IR declares a matcher, an
    # enricher, a validation or a survivorship rule it is describing a certification
    # process, and a certification process with no job to run it is not one.
    jobs = [j for j in c.jobs if (j.job_type or "INTEGRATION") == "INTEGRATION"]
    designs_certification = bool(c.matchers or c.enrichers or c.validations
                                 or c.survivorship or c.jobs)
    if not (m.entities and designs_certification):
        pass
    elif not jobs:
        add("IR-030", "error", m.model.name,
            "no INTEGRATION job declared",
            "The model imports, deploys and accepts records into a load, then every "
            "SUBMIT is refused with \"Job [INTEGRATE_DATA] does not exist. Known jobs "
            "are []\". Declare `jobs:` in certify.yaml with one task per entity.",
            "LESSONS.md §54")
    else:
        # Which task covers which entity, and the first job that claims it. A second
        # claim is not checked — the product allows an entity in several jobs, and
        # inventing a refusal for a shape no export shows is the §51 mistake.
        covered: dict[str, object] = {}
        for j in jobs:
            for t in j.tasks:
                covered.setdefault(t.entity, t)
                if t.entity not in ents:
                    add("IR-030", "error", f"job {j.name}/{t.entity}",
                        "task references unknown entity")
        for e in m.entities:
            t = covered.get(e.name)
            if t is None:
                add("IR-030", "error", e.name,
                    "no INTEGRATION job task covers this entity",
                    "An entity outside every job is never certified: its records land "
                    "in the load and the batch completes without touching them.",
                    "LESSONS.md §54")
                continue
            # A phase flag set false is the silent half. The model still HOLDS the
            # matcher and the validations; the job simply never runs them, and the
            # only visible symptom is a hub where nothing ever merges.
            matched = e.type in ("fuzzy", "id")
            if matched and e.name in matchers and not t.match:
                add("IR-030", "error", f"job task {e.name}",
                    "entity has a matcher but the job task sets match: false",
                    "The matcher is emitted, imported and never executed. Nothing "
                    "merges and no suggestion is ever raised.", "LESSONS.md §54")
            if matched and not t.consolidation:
                add("IR-030", "error", f"job task {e.name}",
                    f"{e.type}-matched entity with consolidation: false",
                    "Master records are certified and no golden record is produced.",
                    "LESSONS.md §54")
            if any(en.entity == e.name and en.scope in ("PRE_CONSO", "PRE_POST_CONSO")
                   for en in c.enrichers) and not t.source_enrichment:
                add("IR-030", "error", f"job task {e.name}",
                    "PRE_CONSO enrichers exist but source_enrichment is false",
                    "Every derived attribute stays null, which then silently defeats "
                    "any match rule or binning built on it.", "LESSONS.md §54")
            if any(v.entity == e.name and v.scope in ("POST_CONSO", "PRE_POST_CONSO")
                   for v in c.validations) and not t.post_conso_validation:
                add("IR-030", "error", f"job task {e.name}",
                    "POST_CONSO validations exist but post_conso_validation is false",
                    "The validation is in the model and never evaluated, so the hub "
                    "reports zero errors for a rule that was never applied.",
                    "LESSONS.md §54")

        # Task ORDER follows the references. A PRE_CONSO reference is validated against
        # the parent's certified data, so the parent's task has to run first. s4 is the
        # first scenario with references at all, which is why nothing needed this
        # before — and why the check exists before the shape has been through more than
        # one run.
        pos = {n: getattr(t, "position", 1) for n, t in covered.items()}
        for r in m.references:
            if r.from_entity == r.to_entity:
                continue                       # a self-reference is one task, always
            a, b = pos.get(r.to_entity), pos.get(r.from_entity)
            if a is not None and b is not None and a >= b:
                add("IR-030", "error", f"reference {r.name}",
                    f"{r.from_entity} (task position {b}) is certified at or before "
                    f"its parent {r.to_entity} (position {a})",
                    "The child's foreign key is resolved against the parent's "
                    "certified records. Give the parent the lower position.",
                    "LESSONS.md §54")

    # IR-031 — survivorship shapes the integration job's OVERRIDE machinery, and three
    # of its configurations crash the job generator rather than the model.
    #
    # All three were read out of the server log on 2026-08-07 after twelve blind deploys
    # had failed to separate them (LESSONS §55.4, §55.5). Each has its own sentence, and
    # the sentences are what make these rules rather than guesses.
    #
    # (a) A default-branch rule scoping a BARE COMPLEX ATTRIBUTE.
    #
    #     Failed to interpret script
    #       [Merge (update) source override values into GA table.sql]
    #     One or more expression should be provided to least().
    #
    #     The template does, per rule, `rule.ruleScope.findMatchingColumns(
    #     tableColumns("SF"))` and hands the result to `least()`. A complex attribute
    #     has no physical column of its own — only its definition attributes do — so
    #     `attributes: [Address]` resolves to zero SF flag columns and `least()` gets an
    #     empty list. NO_OVERRIDE and ALWAYS_AUTHORED_FROM_MDM take earlier branches and
    #     never reach it, which is why the strategy is part of the predicate.
    #
    #     INFERRED, not isolated. The sentence and the template are measured; that THIS
    #     rule was the trigger is the best explanation of fourteen deploys and was never
    #     confirmed on its own. What IS measured is that no export in the corpus scopes
    #     any rule to a bare complex attribute — corpus model A's AddressRule names all eight
    #     of its members, s3's DefaultRule all four of its.
    #
    # (b) NO default rule. Every working matched entity measured carries exactly one
    #     rule with `defaultRule` true: corpus model A's Organization (which also has two
    #     foreign attributes and a job, i.e. exactly s4's shape) and s3's Party. s4 had
    #     none, and its `Parent` foreign attribute was claimed by nothing.
    #
    # (c) EVERY rule NO_OVERRIDE. Measured directly, and manufactured by a probe that
    #     was trying to rule (a) out:
    #
    #     java.util.NoSuchElementException: No value present
    #       at java.util.Optional.get
    #       at PrepareOverridesTaskBuilder."convert to OVERRIDE Update GF flags"
    #
    #     An entity with nothing overridable is a configuration the override-prep
    #     builder does not handle. It is not a shape anyone would author on purpose,
    #     which is exactly why it is worth refusing: the only way to reach it is by
    #     switching strategies off one at a time to debug something else.
    COMPLEX_SCOPE_OK = {"NO_OVERRIDE", "ALWAYS_AUTHORED_FROM_MDM"}
    for e in m.entities:
        if e.type not in ("fuzzy", "id"):
            continue
        rules = [s for s in c.survivorship if s.entity == e.name and s.kind != "id"]
        if not rules:
            continue
        complex_names = {ca.name for ca in e.complex_attributes}
        for s in rules:
            if s.override_strategy in COMPLEX_SCOPE_OK:
                continue
            bare = [a for a in s.attributes if a in complex_names]
            if bare:
                add("IR-031", "error", f"{e.name}/{s.name}",
                    f"scopes the complex attribute(s) {', '.join(bare)} without naming "
                    f"their members",
                    "A complex attribute has no column of its own, so the scope "
                    "resolves to zero SF flag columns and the deploy dies with \"One or "
                    "more expression should be provided to least()\". Name the "
                    "definition attributes: Address.Zip5, not Address.",
                    "LESSONS.md §55.4")
        defaults = [s for s in rules if s.default_rule]
        if not defaults:
            add("IR-031", "error", e.name,
                "matched entity has no default survivorship rule",
                "Every working matched entity in the corpus carries exactly one rule "
                "with `default_rule: true`, and the attested shape has an EMPTY scope — "
                "the flag means \"every attribute no other rule claims\", which is what "
                "covers foreign attributes and anything added later.",
                "LESSONS.md §55.4")
        elif len(defaults) > 1:
            add("IR-031", "error", e.name,
                f"{len(defaults)} default survivorship rules: "
                f"{', '.join(s.name for s in defaults)}",
                "The catch-all cannot be ambiguous; no export has more than one.",
                "LESSONS.md §55.4")
        if all(s.override_strategy == "NO_OVERRIDE" for s in rules):
            add("IR-031", "error", e.name,
                "every survivorship rule is NO_OVERRIDE, so nothing is overridable",
                "PrepareOverridesTaskBuilder calls Optional.get() on the override set "
                "and throws NoSuchElementException while building \"convert to OVERRIDE "
                "Update GF flags\". Give at least the default rule a real override "
                "strategy.", "LESSONS.md §55.4")

    # IR-033 — a survivorship scope must name something that EXISTS.
    #
    #     Attribute Name on SurvivorshipRuleAttribute -
    #     {SurvivorshipRuleAttribute.InternalID=69f…}
    #
    # The Application Builder's Validation view, 2026-08-07, on the pre-fix edition of
    # scenario 4. It is IR-031(a) seen from the other side and it is a WIDER rule: (a)
    # refuses a name that resolves to a complex attribute, because that resolves to zero
    # COLUMNS and kills the job generator. This refuses a name that resolves to NOTHING —
    # a typo, a renamed attribute, a member spelled without its parent — which no
    # generator ever reaches because there is nothing to generate from.
    #
    # What resolves, measured over the 37 SurvivorshipRuleAttribute instances in the
    # product-authored corpus: an atomic attribute by bare name (`IsWatchList`), a
    # complex MEMBER dotted (`Address.AddrZip5`, 13 of them), and a reference ROLE by
    # bare name (`Person` and `Preference` on gs-customerb2c's CommChanPref). Never a
    # bare complex attribute, and never anything else.
    for e in m.entities:
        rules = [s for s in c.survivorship if s.entity == e.name and s.kind != "id"]
        if not rules:
            continue
        known = {a.name for a in e.attributes}
        known |= {ca.name for ca in e.complex_attributes}      # IR-031(a)'s business
        known |= {r.to_role or r.to_entity for r in m.references
                  if r.from_entity == e.name}
        for ca in e.complex_attributes:
            t = next((x for x in m.complex_types if x.name == ca.type), None)
            if t is not None:
                known |= {f"{ca.name}.{mem.name}" for mem in t.members}
        for s in rules:
            for a in s.attributes:
                if a in known:
                    continue
                add("IR-033", "error", f"{e.name}/{s.name}",
                    f"scopes {a!r}, which is not an attribute, complex member or "
                    f"reference role of {e.name}",
                    "\"Attribute Name on SurvivorshipRuleAttribute\" in the "
                    "Application Builder's Validation view — the register that names "
                    "this, and the one no REST call reaches. A scope that resolves to "
                    "nothing is silently no scope at all: the model imports, exports, "
                    "deploys and runs, and those attributes are consolidated by "
                    "whatever the default rule happens to say.",
                    "LESSONS.md §56")

    # IR-034 — a BASIC entity has no master records, so it cannot historize them.
    #
    #     Could not have Historize Master Records on Entity Opportunity because it is
    #     a Basic entity
    #
    # Measured: false on 16 of 16 BASIC entities in the product-authored corpus. The
    # schema DEFAULTS it to false on a basic entity, so reaching this rule means an
    # author wrote it out — and silently flipping a stated intention is worse than
    # refusing it. Cheap to fix, and the fix is deleting a line.
    for e in m.entities:
        if e.type == "basic" and e.historize_master:
            add("IR-034", "error", e.name,
                "historize_master is true on a BASIC entity",
                "A basic entity has no master records to historize. The model imports "
                "and deploys; the Application Builder's Validation view reports "
                "\"Could not have Historize Master Records on Entity "
                f"{e.name} because it is a Basic entity\".", "LESSONS.md §56")

    # IR-035 — a business-view node SORT resolves model attributes, not built-ins.
    #
    #     Sort Expression on CustomerNode is not a valid SemQL ORDER_BY_LIST : 1:1
    #     Invalid SemQLAttribute qualified name "ConfidenceScore"
    #
    # Collection COLUMNS see the matching built-ins — s3 renders Masters and Score
    # columns at runtime — and the view FILTER does too (HasSuggestedMerge = '1' is
    # runtime-proven). The node sort does NOT, and the product's own error enumerates
    # its whole scope: the entity's attributes, complex attributes, reference roles,
    # FID_/FDN_ columns, and the audit built-ins. Nothing from the matching vocabulary
    # (ConfidenceScore, MastersCount, ConfirmationStatus, ...) is in that list, and
    # the model deploys and runs before the Validation view says so (LESSONS §56).
    #
    # `DupsManager.checkout_sort_expression` is a different surface with an UNMEASURED
    # scope — not covered here; measure before extending.
    _SORT_SCOPE_EXTRAS = {"ClassName", "CreationDate", "UpdateDate", "Creator",
                          "Updator", "ViewType"}
    _SORT_KEYWORDS = {"ASC", "DESC", "NULLS", "FIRST", "LAST"}
    for v in ir.app.business_views:
        for n in v.nodes:
            if not n.sort_expression:
                continue
            e = ents.get(n.entity)
            if e is None:
                continue
            legal = ({a.name for a in e.attributes}
                     | {ca.name for ca in getattr(e, "complex_attributes", [])}
                     | _SORT_SCOPE_EXTRAS)
            for r in getattr(m, "references", []):
                if r.from_entity == e.name and r.to_role:
                    legal.add(r.to_role)
                if r.to_entity == e.name and r.from_role:
                    legal.add(r.from_role)
            for ident in _IDENT.findall(n.sort_expression):
                head = ident.split(".")[0]
                if head in _SORT_KEYWORDS or head in legal:
                    continue
                if head.startswith(("FID_", "FDN_")):
                    continue
                add("IR-035", "error", f"{v.name}/{n.name}",
                    f"sort_expression names {head!r}, which the node-sort scope "
                    f"cannot resolve",
                    "The sort scope is model attributes, roles and audit columns "
                    "only — the matching built-ins resolve in collection columns and "
                    "view filters, but NOT here. Imports at 204, deploys, runs; only "
                    "the Application Builder's Validation view names it.",
                    "LESSONS.md §56")

    # IR-032 — a reference ROLE is not a scalar, and only the job generator ever said so.
    #
    #     'Parent' is not valid here: Expression must be of type SCALAR but is of
    #     type TO_ONE_PATH
    #
    # `Parent IS NULL` sat in scenario 4's IR from 2026-08-03 to 2026-08-07. It parses
    # as SQL, so IR-017 passes it. It round-trips, imports at 204 and deploys — right up
    # until an integration job exists to generate validation SQL from it, at which point
    # CheckValidationSqlBuilder refuses the whole condition. Four days and a fourteen-
    # deploy bisect, for a construct the docs never use: the self-reference example in
    # docs/Design/matching/advanced-match-rules.md writes `PublisherID_ParentFolder is
    # null and SourceID_ParentFolder is null`, and names `FID_ParentFolder` for the
    # golden — never the bare role.
    #
    # The legal forms are all derived: `FID_<Role>`, `SourceID_<Role>`,
    # `PublisherID_<Role>` are scalars, and `<Role>.<Attribute>` is a traversal. Only
    # the role ALONE is the error, so the pattern requires that it not be followed by a
    # dot — and `\b` already excludes `FID_Parent`, because `_` is a word character.
    roles: set[str] = set()
    for r in m.references:
        roles.update(x for x in (r.to_role, r.from_role) if x)
    attr_names = {a.name for e in m.entities for a in e.attributes}
    attr_names |= {ca.name for e in m.entities for ca in e.complex_attributes}
    for role in sorted(roles - attr_names):
        bare = re.compile(
            r"\b%s\b\s*(?!\.)(IS\s+(NOT\s+)?NULL|=|<>|!=|<=|>=|<|>)" % re.escape(role),
            re.IGNORECASE)
        for where, expr in _semql_sites(c):
            if expr and bare.search(expr):
                add("IR-032", "error", where,
                    f"uses the reference role {role!r} as a scalar",
                    f"\"'{role}' is not valid here: Expression must be of type SCALAR "
                    f"but is of type TO_ONE_PATH\". A role is a path, not a value. Use "
                    f"FID_{role} for the referenced golden id, PublisherID_{role} / "
                    f"SourceID_{role} for the referenced master, or {role}.<Attribute> "
                    f"to traverse.", "LESSONS.md §55.4")

    # 12 — disabled rules are flagged, not silently accepted
    for x in c.matchers:
        for r in x.rules:
            if re.fullmatch(r"\s*1\s*=\s*0\s*", r.condition):
                add("IR-012", "warning", f"{x.entity}/{r.name}",
                    "rule is disabled via `1 = 0`",
                    "Valid, but invisible in a rule listing. Delete it or acknowledge it.")

    # 13 — name collisions and reserved words
    for scope, names in (("entity", [e.name for e in m.entities]),
                         ("publisher", [p.name for p in m.publishers]),
                         ("lov_type", [l.name for l in m.lov_types])):
        dupes = {n for n in names if names.count(n) > 1}
        for n in sorted(dupes):
            add("IR-013", "error", n, f"duplicate {scope} name")
    for e in m.entities:
        for a in e.attributes:
            if a.name.lower() in RESERVED:
                add("IR-013", "error", f"{e.name}.{a.name}",
                    "attribute name collides with a SemQL reserved word")

    # 14 — external UDFs must be declared
    declared = {d.upper() for d in m.external_dependencies}
    for x in c.matchers:
        for r in x.rules:
            _check_udfs(r.condition, f"matcher {x.entity}/{r.name}", declared, add)
    for en in c.enrichers:
        for expr in en.expressions:
            _check_udfs(expr.expression, f"enricher {en.entity}/{en.name}", declared, add)

    # IR-027 — a SqlFunction declares a schema and SemQL calls it UNQUALIFIED.
    #
    # This is the external-function path working as designed: xDM can call any function
    # the database offers, which is how a hub gets phonetic matching on Snowflake at all
    # (METAPHONE is PostgreSQL-only, so the equivalent is a UDF you build and declare).
    # The declaration is what makes the name legitimate to IR-017 — verified: declaring
    # a SqlFunction clears the refusal, external_dependencies does not, and the two are
    # different concerns rather than two doors to one room.
    #
    # What nothing checked is whether the CALL agrees with the DECLARATION. Declaring
    # `schema: HUB.SHARED` asserts the function lives there; calling it bare asks the
    # database to resolve it through the session search path, which is the data
    # location's schema and not the function's. The model records the first and depends
    # silently on the second.
    #
    # OBSERVED 2026-08-05 on a live hub: an integration job died with
    # `SQL compilation error: Unknown functions UDF_DOUBLE_METAPHONE` on generated SQL
    # calling it unqualified, while the model declared it with a schema. Whether the fix
    # is qualification, a grant, or a search-path setting is NOT established here — what
    # is established is that this shape reached a database and failed, and that every
    # offline check passed it.
    #
    # WARNING, not error, for exactly that reason: the failure is real, the mechanism is
    # not proven, and a blocking rule on an unproven mechanism refuses working models.
    schema_qualified = {f.name.upper(): f.schema_name
                        for f in m.sql_functions if f.schema_name}
    if schema_qualified:
        for where, text_ in _semql_sites(c):
            for call in _CALLS.findall(text_ or ""):
                bare = call.upper()
                if bare not in schema_qualified or "." in call:
                    continue
                if f"{schema_qualified[bare]}.{call}".upper() in (text_ or "").upper():
                    continue
                add("IR-027", "warning", where,
                    f"calls {call!r} unqualified, but it is declared in schema "
                    f"{schema_qualified[bare]!r}",
                    "An unqualified name resolves through the database session's search "
                    "path, which is the data location's schema — not the function's. A "
                    "live job failed with 'Unknown functions' on exactly this shape. "
                    f"Either call it {schema_qualified[bare]}.{call}(...) or record why "
                    "the search path makes the bare name resolvable.",
                    "LESSONS.md §21")

    # IR-028 — a workflow must be a CONNECTED GRAPH, not a bag of steps.
    #
    # The Workflow Builder validates that every step has a path FROM a Start Event and a
    # path TO an End Event, and reports each as an error. That is the one rule the
    # harvested sample could not supply, because the sample itself breaks it: the
    # operator's draft has neither event, so it attests the field grammar while being an
    # invalid workflow. Evidence about spelling is not evidence about validity.
    #
    # Checked here rather than discovered in the builder, because a workflow only
    # reaches the builder after an Import-Replace has already destroyed the edition.
    for w in m.workflows:
        names = [s.name for s in w.steps]
        if not w.steps:
            continue
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            add("IR-028", "error", f"workflow {w.name}",
                f"duplicate step name(s): {', '.join(sorted(dup))}",
                "Transitions address steps BY NAME, so a duplicate makes every edge "
                "pointing at it ambiguous.")
        by_name = {s.name: s for s in w.steps}
        for s in w.steps:
            for t in s.transitions:
                if t.to_step not in by_name:
                    add("IR-028", "error", f"workflow {w.name}/{s.name}",
                        f"transition targets {t.to_step!r}, which is not a step here",
                        "Refs inside NGModel are name-paths and nothing resolves them "
                        "at import — a dangling edge lands in the model intact.")

        starts = [s for s in w.steps if s.type == "StartEvent"]
        ends = {s.name for s in w.steps if s.type == "EndEvent"}
        if not starts:
            add("IR-028", "error", f"workflow {w.name}", "no StartEvent",
                "The builder refuses a definition no step can be entered from.")
        if not ends:
            add("IR-028", "error", f"workflow {w.name}", "no EndEvent",
                "The builder refuses a definition with no terminal step.")

        # Forward reachability from the starts, and backward reachability to an end.
        # Both directions are required and they fail differently: an unreachable step
        # never runs, while a step that reaches no end leaves the workflow instance
        # open forever.
        def _walk_from(seeds, edges):
            seen, stack = set(seeds), list(seeds)
            while stack:
                for nxt in edges.get(stack.pop(), ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            return seen

        fwd = {s.name: [t.to_step for t in s.transitions if t.to_step in by_name]
               for s in w.steps}
        back: dict[str, list[str]] = {s.name: [] for s in w.steps}
        for s in w.steps:
            for t in s.transitions:
                if t.to_step in back:
                    back[t.to_step].append(s.name)

        if starts:
            unreachable = set(by_name) - _walk_from([s.name for s in starts], fwd)
            for n in sorted(unreachable):
                add("IR-028", "error", f"workflow {w.name}/{n}",
                    "no path from any StartEvent",
                    "The step exists in the definition and can never execute.")
        if ends:
            stuck = set(by_name) - _walk_from(sorted(ends), back)
            for n in sorted(stuck):
                add("IR-028", "error", f"workflow {w.name}/{n}",
                    "no path to any EndEvent",
                    "A workflow instance reaching this step never completes, so its "
                    "tasks stay open and its retention policy never applies.")

        # Every name-path a step uses must resolve to something this model actually
        # emits. Nothing resolves them at import — a dangling ref lands in the model
        # intact, which is the OPPOSITE of a UUID ref's failure mode, where the importer
        # rejects the document. Here the model is accepted and the screen is empty.
        app_ir = getattr(ir, "app", None)
        steppers = {(s.entity, s.name) for s in getattr(app_ir, "steppers", ())}
        colls = {(c.entity, c.name) for c in getattr(app_ir, "collections", ())}
        apps = {a.name for a in getattr(app_ir, "applications", ())}
        roles = {r.role_name for r in m.roles} | {r.name for r in m.roles}
        for s in w.steps:
            if s.type != "UserTask":
                continue
            where = f"workflow {w.name}/{s.name}"
            if s.entity and s.entity not in ents:
                add("IR-028", "error", where, f"unknown entity {s.entity!r}")
            if s.stepper and steppers and (s.entity, s.stepper) not in steppers:
                add("IR-028", "error", where,
                    f"stepper {s.stepper!r} is not defined on {s.entity!r}",
                    "The task opens nothing and the ref survives the import intact.")
            if s.my_tasks_collection and colls and \
                    (s.entity, s.my_tasks_collection) not in colls:
                add("IR-028", "error", where,
                    f"My Tasks collection {s.my_tasks_collection!r} is not defined on "
                    f"{s.entity!r}")
            if s.application and apps and s.application not in apps:
                add("IR-028", "error", where,
                    f"unknown application {s.application!r}")
            if s.assignee_required_role and roles and \
                    s.assignee_required_role not in roles:
                add("IR-028", "warning", where,
                    f"assignee role {s.assignee_required_role!r} has no grant in this "
                    f"model",
                    "Roles are platform-defined, so this may be deliberate — but the "
                    "assignee then reaches the task and can open nothing behind it.")

        if w.start_context == "START_FROM_COMPLETED_BATCH" and not w.root_entities:
            add("IR-028", "error", f"workflow {w.name}",
                "START_FROM_COMPLETED_BATCH with no root entities",
                "That context fires when a batch on the ROOT ENTITIES finishes; with "
                "none named there is nothing to watch and the workflow never starts.")

        # RULE 3, from the builder's own validation panel on 2026-08-06: the Entities
        # section may not be empty. Not conditional on the start context — the draft
        # had no context set at all and was still refused for this.
        roots = {r.entity for r in w.root_entities}
        if w.steps and not roots:
            add("IR-028", "error", f"workflow {w.name}",
                "no root entities declared",
                "The builder refuses a definition whose Entities section is empty. "
                "`rootEntities` is what the workflow's dataset is made of; with none, "
                "there is nothing for a task to author.")
        else:
            for r in w.root_entities:
                if r.entity not in ents:
                    add("IR-028", "error", f"workflow {w.name}",
                        f"root entity {r.entity!r} is not an entity of this model")

        # RULE 4, and this one is a constraint BETWEEN two sections that look
        # independent — nothing in the JSON hints at it. The builder's words:
        #
        #   "The root entity and its child entities manipulated in the selected stepper
        #    must be declared in the Entities section"
        #
        # So naming a stepper on a UserTask silently obliges the Entities list. Caught
        # here because the alternative is finding out from the builder, which is only
        # reachable after an Import-Replace has already destroyed the edition.
        if roots:
            for s in w.steps:
                if s.type != "UserTask" or not s.entity or s.entity in roots:
                    continue
                add("IR-028", "error", f"workflow {w.name}/{s.name}",
                    f"task authors {s.entity!r} through stepper {s.stepper!r}, but "
                    f"{s.entity!r} is not in the workflow's root entities "
                    f"({', '.join(sorted(roots))})",
                    "The builder: \"The root entity and its child entities manipulated "
                    "in the selected stepper must be declared in the Entities "
                    "section\".")

    # 15 — form_step enrichers carry no execution scope
    for en in c.enrichers:
        if en.kind == "form_step" and en.scope is not None:
            add("IR-015", "error", f"{en.entity}/{en.name}",
                "form_step enricher must not set an execution scope",
                "enricherExecutionScope is absent on FormStepEnricher.",
                "authoring guide §5.5")
        if en.kind == "semql" and en.scope is None:
            add("IR-015", "error", f"{en.entity}/{en.name}",
                "semql enricher must state PRE_CONSO or POST_CONSO")
        if en.entity not in ents:
            add("IR-008", "error", en.name, f"unknown entity {en.entity!r}")

    # 17 — SemQL that will not parse.
    # docs/SemQL/semql-syntax.md: SemQL is "the equivalent of SQL expressions,
    # conditions or ORDER BY clauses". Measured across all three samples, 135 of 137
    # expressions parse as Snowflake SQL unmodified; the whole delta is the
    # ANY|ALL <role> HAVE (...) quantifier, which semql.py rewrites before parsing.
    # So a missing bracket is catchable HERE instead of costing a compile, import and
    # validate cycle to discover.
    #
    # SYNTAX ONLY. This cannot know that an attribute name is a typo or that a
    # function exists on the target database — xDM's own validation still owns that.
    from agent.tools.semql import check_ir
    for issue in check_ir(ir):
        add("IR-017", "error", issue.where, issue.message,
            "SemQL is checked offline because the alternative is discovering a typo "
            "after a full import.", "docs/SemQL/semql-syntax.md")

    return out


def _semql_sites(c):
    """(where, expression) for every place the IR holds SemQL. One list, so a new
    rule cannot silently cover matchers and forget enrichers."""
    for x in c.matchers:
        for r in x.rules:
            yield f"matcher {x.entity}/{r.name}", r.condition
    for en in c.enrichers:
        for expr in en.expressions:
            yield f"enricher {en.entity}/{en.name}", expr.expression
    for v in c.validations:
        yield f"validation {v.entity}/{v.name}", v.condition


def _check_udfs(sql: str, where: str, declared: set[str], add) -> None:
    for udf in _UDF.findall(sql or ""):
        if udf.upper() not in declared:
            add("IR-014", "warning", where,
                f"{udf} is not in external_dependencies",
                "Fully-qualified UDFs are a hard coupling — a rename breaks the model at "
                "runtime with no compile-time warning. Declared names are verified against "
                "the target Snowflake account before import.")


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]
