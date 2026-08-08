"""Completeness advice. Sprint 11.

`ir_validate` answers *is this wrong?* — every rule there describes a violation, and
errors block compilation. Nothing answered *is this thorough?*. A model with no
validations at all, no survivorship on attributes that will certainly conflict, and
nothing searchable is **perfectly valid and a poor data hub**.

The two mechanisms are deliberately different:

    ir_validate   fires on VIOLATION   -> error/warning -> fix the IR
    advise        fires on ABSENCE     -> question      -> answer, or acknowledge

A gap is a question because the agent cannot know the answer. "You have three
publishers and no survivorship rule on Email — which source wins?" is a design
conversation, not a defect. Emitting it as an error would be false; emitting it as a
warning would train the reader to scroll past.

Gaps NEVER block compilation. An acknowledged gap stays closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.ir import policy, propose
from agent.ir.schema import IR

_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")
MATCHED = ("id_matched", "fuzzy")


@dataclass(frozen=True)
class Gap:
    rule: str
    where: str
    question: str
    consequence: str          # what happens if it is left as-is
    see: str = ""
    #: A PROPOSED ANSWER, rendered. Sprint 12: a question with a blank page under it is
    #: still work; a question with a tagged proposal under it is a review. Optional and
    #: last, so a gap rule with no proposer stays exactly what it was — and carrying it
    #: never turns a question into an instruction. Nothing here blocks anything.
    proposals: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.rule}:{self.where}"

    def render(self) -> str:
        out = f"[{self.rule}] {self.where}: {self.question}\n    {self.consequence}"
        if self.see:
            out += f"\n    see: {self.see}"
        for line in self.proposals:
            out += f"\n    {line}"
        return out


def _has_steward_queue(ir: IR, entity: str) -> bool:
    """MVP for CA-003, per the operator on 2026-08-03: "a screen (App business view)
    presenting the pending items for confirmation". A duplicate manager also counts —
    it is the fuller shape of the same answer."""
    if any(d.entity == entity for d in ir.app.dups_managers):
        return True
    return any(
        v.entity == entity and (v.filter or any(n.filters for n in v.nodes))
        and any(k.lower() in ((v.filter or "") + "".join(
            f.condition for n in v.nodes for f in n.filters)).lower()
            for k in policy.STEWARD_QUEUE_FILTERS)
        for v in ir.app.business_views)


def advise(ir: IR) -> list[Gap]:
    """Open design questions, minus anything already acknowledged."""
    m, c = ir.model_ir, ir.certify
    gaps: list[Gap] = []

    def ask(rule, where, question, consequence, see="", proposals=()):
        gaps.append(Gap(rule, where, question, consequence, see, tuple(proposals)))

    declared_types = ({l.name for l in m.lov_types}
                      | {t.name for t in m.complex_types}
                      | {u.name for u in m.user_defined_types})
    lov_names = {l.name for l in m.lov_types}
    matchers = {x.entity: x for x in c.matchers}
    multi_source = len(m.publishers) > 1

    # An LOV-only model has no certification process, so no gap rule may misfire on it.
    for e in m.entities:
        # Attributes COMPUTED from other attributes, as opposed to normalized IN PLACE
        # (Email <- LOWER(TRIM(Email)) still carries a publisher's value).
        # Defined once at the top of the loop: CA-002 and CA-012 both need it, and
        # defining it inside the "multi-source and matched" branch made CA-012 crash on
        # a basic entity — a variable scoped to a conditional and used outside it, for
        # the second time in this function.
        # ONE copy of the predicate: propose.computed_attributes is the same set for
        # the same scope, and sprint 12 needs it too. Two copies of "is this value
        # computed?" is how CA-012 and its proposal would drift apart.
        derived_here = propose.computed_attributes(c, e.name, scopes=("PRE_CONSO",))

        # CA-001 — nothing constrains incoming data
        if not any(v.entity == e.name for v in c.validations):
            ask("CA-001", e.name,
                "Nothing constrains incoming data on this entity — is every source trusted "
                "to send well-formed records?",
                "Bad values reach golden records unchallenged; there is no "
                "source-with-errors view to inspect because nothing rejects anything.",
                "docs/Design/data-quality/validations.md § Validations")

        # CA-005 / CA-006 — the record is unnameable or unfindable
        if not e.subject_name:
            ask("CA-005", e.name,
                "No subject-name attribute — which attribute names a record?",
                "Records display by identifier in every collection, form and match group.")
        if not any(a.searchable for a in e.attributes):
            ask("CA-006", e.name,
                "No attribute is searchable — what will users search by?",
                "The application ships with no way to find a record.")

        for a in e.attributes:
            # CA-009 — an LOV that constrains nothing
            if a.type in lov_names and a.lov_scope == "NONE":
                ask("CA-009", f"{e.name}.{a.name}",
                    f"Typed by LOV {a.type!r} but its validation scope is NONE — should a "
                    f"value outside the list be rejected?",
                    "An unlisted code is accepted silently and lands in a golden record.",
                    "docs/Design/logical-model/list-of-values.md § Overview")
            # CA-010 — mandatory that enforces nothing
            # A fuzzy entity's golden ID is generated by xDM, so a scope on it would
            # constrain nothing. Asking about it is noise, and advice fatigue is this
            # sprint's stated risk.
            if a.mandatory and a.mandatory_scope == "NONE" and not (
                    a.pk and e.type == "fuzzy"):
                ask("CA-010", f"{e.name}.{a.name}",
                    "Marked mandatory with validation scope NONE — enforce it PRE_CONSO "
                    "on the source record, or POST_CONSO on the golden record?",
                    "`mandatory` with no scope enforces nothing at certification time.")

        # CA-002 — publishers will disagree and nothing decides
        if multi_source and e.type in MATCHED:
            covered = {name for s in c.survivorship if s.entity == e.name
                       for name in s.attributes}
            # An attribute COMPUTED from others is not publisher-supplied, so "which
            # source wins" is the wrong question — it follows whatever its inputs
            # consolidated to. But an enricher that normalises IN PLACE
            # (Email <- LOWER(TRIM(Email))) is still carrying a publisher's value, and
            # survivorship very much applies. Distinguish by whether the expression
            # reads the attribute it writes.
            exposed = [a.name for a in e.attributes
                       if not a.pk and a.name not in covered
                       and a.name not in derived_here]
            if exposed:
                shown = ", ".join(exposed[:4]) + ("…" if len(exposed) > 4 else "")
                # The FIRE CONDITION is unchanged — `exposed` decides, exactly as it
                # did. What is new is that the question now arrives with a proposed
                # answer per attribute, each tagged for review (sprint 12 §1). The
                # proposals are text on the gap; nothing adopts them and nothing blocks.
                ask("CA-002", e.name,
                    f"{len(exposed)} attribute(s) have no survivorship rule ({shown}) — "
                    f"when publishers disagree, which value wins?",
                    "Consolidation falls back to a default the design never chose.",
                    "docs/Design/matching/survivorship.md § Consolidation strategy",
                    propose.propose(ir, e.name).render().splitlines())

        # CA-012 — a computed value that a steward edit can silently override.
        # House policy: overrides are for values a PERSON types. An enriched ID, an
        # API result or any calculated column is owned by the pipeline, so an override
        # there is a value the next run discards without telling anyone.
        for s_ in (r for r in c.survivorship if r.entity == e.name):
            if s_.override_strategy == policy.OVERRIDE_FORBIDDEN:
                continue
            hit = sorted(set(s_.attributes) & derived_here)
            if hit:
                ask("CA-012", f"{e.name}/{s_.name}",
                    f"{', '.join(hit)} is computed, but this rule lets a user edit "
                    f"override it ({s_.override_strategy}). Should it be "
                    f"{policy.OVERRIDE_FORBIDDEN} instead?",
                    "The next certification run recomputes the value and silently "
                    "discards the steward's edit.",
                    "docs/Design/matching/survivorship.md § Consolidation strategy")

        # CA-003 / CA-004 / CA-008 — a matcher that exists but is incomplete.
        # These say nothing when the matcher is ABSENT: that is IR-001's job, and a gap
        # rule must never restate a validation error.
        x = matchers.get(e.name)
        if x is None:
            continue
        # Computed for BOTH branches: CA-004 is fuzzy-only, but CA-013 applies to any
        # entity with a matcher — an ID-matched entity bins too, and binning on a raw
        # key fails there for exactly the same reason.
        derived = {expr.attribute for en in c.enrichers
                   if en.entity == e.name and en.scope == "PRE_CONSO"
                   for expr in en.expressions}
        if e.type == "fuzzy" and not _has_steward_queue(ir, e.name):
            ask("CA-003", e.name,
                "Fuzzy matching produces match groups below the auto-merge threshold — "
                "where do stewards see the pending ones? MVP is a business view over "
                "items awaiting confirmation; a duplicate manager is the fuller shape.",
                "Probable duplicates accumulate with nobody assigned to resolve them.",
                "docs/Design/matching/matching.md § Capabilities per entity type")

            reads = {i.split(".")[-1] for r in x.rules
                     for i in _IDENT.findall(r.condition)} | {
                     b.split(".")[-1] for r in x.rules for b in r.binning}
            if not (reads & derived):
                ask("CA-004", e.name,
                    "Match rules compare raw source values — no PRE_CONSO enricher feeds "
                    "them. Is exact matching on unnormalized data intended?",
                    "Case, whitespace and formatting differences between sources will "
                    "read as different people.",
                    "docs/Design/data-quality/enrichers.md § Overview")

        # CA-013 — a BINNING key that nothing normalizes.
        # CA-004 asks whether ANY match input is normalized, so one normalized
        # attribute hides every unnormalized one behind it. Binning deserves its own
        # check because it fails differently and worse: an unnormalized comparison key
        # produces a wrong score, but an unnormalized BINNING key stops the two records
        # from ever being compared. Found in scenarios 3 and 4, where the narrative
        # promised a NormalizeAddress enricher that the IR never contained, while
        # NormalizedName kept CA-004 quiet.
        # Compare on the LAST segment on both sides: a binning key is written
        # `Address.Zip5` and the enricher writing it targets `Address.Zip5` too, but a
        # plain attribute is bare. Stripping one side only makes the rule fire on every
        # complex attribute forever.
        binned = {b.split(".")[-1] for r in x.rules for b in r.binning}
        derived_last = {d.split(".")[-1] for d in derived}
        raw_bins = sorted(binned - derived_last - {a.name for a in e.attributes if a.pk})
        if raw_bins:
            ask("CA-013", e.name,
                f"Match rules bin on {', '.join(raw_bins)}, which no PRE_CONSO enricher "
                f"normalizes. Are those values already consistent across every source?",
                "Records that should share a bin do not, and records in different bins "
                "are never compared — the match silently never happens.",
                "docs/Design/matching/match-rules.md § Binning")

        # CA-014 — singletons auto-confirmed into a process with nothing to catch a
        # bad record.
        #
        # This rule deliberately does NOT ask "should you auto-confirm?". Auto-confirm
        # is the house default (policy.AUTO_CONFIRM_SINGLETONS) because a steward
        # clicking through every unmatched record is a rubber stamp, not review, and it
        # spends the attention that belongs on the review band. What it asks is whether
        # the certification process has EARNED that trust.
        if x.auto_confirm_singletons:
            weak = []
            if not any(v.entity == e.name and v.scope == "PRE_CONSO"
                       for v in c.validations):
                weak.append("no PRE_CONSO validation rejects a malformed record")
            # Same exclusion CA-010 already carries: a fuzzy entity's PK is the golden
            # ID, generated by xDM rather than supplied by a publisher, so "mandatory
            # with no scope" is correct there and not a gap. Missing it made this rule
            # fire on both fuzzy scenarios that had done nothing wrong.
            unenforced = [a.name for a in e.attributes
                          if a.mandatory and a.mandatory_scope == "NONE"
                          and not (a.pk and e.type == "fuzzy")]
            if unenforced:
                weak.append(f"{', '.join(unenforced)} mandatory but enforced at no "
                            f"scope")
            if raw_bins:
                weak.append(f"binning keys {', '.join(raw_bins)} are not normalized")
            if weak:
                ask("CA-014", e.name,
                    f"Singletons are auto-confirmed, but {'; '.join(weak)}. A record "
                    f"nothing matched goes straight to confirmed golden — what stops a "
                    f"bad one?",
                    "Auto-confirm is the right default only where the certification "
                    "process earns it. Here nothing would catch the record a steward "
                    "was no longer asked to look at.",
                    "docs/Design/data-quality/validations.md § Validations")

        # CA-015 — a merge threshold of 0 merges everything.
        #
        # docs/Design/matching/automate-merge-and-confirmation.md: the threshold is the
        # score "above which the match group is automatically merged". Zero therefore
        # means merge regardless of score, so nothing lands in the review band and no
        # suggestion is ever raised — the steward queue stays empty because nothing is
        # ever sent to it, not because there is nothing to review.
        #
        # This is the DEFAULT state of a new matcher, which is what makes it worth a
        # rule: it is reached by not deciding, and it looks identical to a deliberate
        # "merge aggressively" policy.
        wide = sorted(k for k, v in x.resolved_thresholds().items()
                      if k.startswith("mergeThreshold") and v == 0)
        if wide:
            lo = policy.HOUSE_THRESHOLDS.review_from
            ask("CA-015", e.name,
                f"{len(wide)} merge threshold(s) are 0, so a match group merges at ANY "
                f"score ({', '.join(w.replace('mergeThreshold', '') for w in wide[:3])}"
                f"{'…' if len(wide) > 3 else ''}). House policy sends {lo}-"
                f"{policy.HOUSE_THRESHOLDS.auto_merge_at - 1} to a steward. Is "
                f"merge-everything intended?",
                "Every match auto-merges, so nothing is ever suggested for review and "
                "a wrong merge is only discoverable after the fact — by unmerging.",
                "docs/Design/matching/automate-merge-and-confirmation.md")

        if x.rules and all(r.score >= 100 for r in x.rules):
            lo, hi = policy.HOUSE_THRESHOLDS.review_from, \
                policy.HOUSE_THRESHOLDS.auto_merge_at
            ask("CA-008", e.name,
                f"Every match rule scores 100 — only exact matches merge. House policy "
                f"is auto-promote at {hi}+, steward-confirm {lo}–{hi - 1}, no match "
                f"below {lo}. Is there genuinely nothing in the middle band?",
                "Nothing lands in the review band, so probabilistic duplicates are "
                "silently kept apart rather than surfaced.")

    # CA-007 — several sources and none is ever preferred
    if multi_source and c.survivorship and not any(
            s.strategy.upper() == "PREFERRED_PUBLISHER" for s in c.survivorship):
        ask("CA-007", m.model.name,
            f"{len(m.publishers)} publishers but no rule ranks one above another — is "
            f"most-recent/largest genuinely the policy for every attribute?",
            "Source authority is never expressed, so the freshest write wins by accident.",
            "docs/Design/matching/survivorship.md § Consolidation strategy")

    # CA-016 — a menu entry opens a view in a mode the entity cannot have.
    # Master records only exist for ID- and fuzzy-matched entities, so MD and GDWE are
    # meaningless on a Basic one. Documented twice, and it fails as an empty screen
    # rather than as an error.
    entity_type = {e.name: e.type for e in m.entities}
    view_owner = {(v.entity, v.name): v for v in ir.app.business_views}
    for a in ir.app.applications:
        for act in a.actions:
            vt = act.settings.get("viewType")
            if not act.view or vt not in policy.VIEW_TYPES_NEEDING_MATCHING:
                continue
            v = view_owner.get((act.view_entity, act.view))
            root = next((n for n in v.nodes if n.name == v.root), None) if v else None
            if root and entity_type.get(root.entity) == "basic":
                ask("CA-016", f"{a.name}/{act.name}",
                    f"opens {act.view!r} as {vt} ({policy.VIEW_TYPES[vt]}), but its root "
                    f"entity {root.entity!r} is BASIC and has no master records. Should "
                    f"this be GD?",
                    "The screen opens empty rather than failing, so it reads as 'no "
                    "data' instead of 'wrong view type'.",
                    "docs/Design/applications/application-actions-and-folders.md")

    # CA-011 — a screen is gated on a role the model grants nothing to.
    #
    # NOT an error: roles are defined in the PLATFORM by an administrator, not in the
    # model (docs/Design/security/data-hub-security.md § "Privileges are granted to
    # roles defined in Semarchy xDM"), so a role with no ModelPrivGrant may well exist.
    # It is a gap because the two halves have to be true together: users holding the
    # role reach the menu entry and then have no privilege on the data behind it.
    # CA-018 — an enricher normalizes an attribute IN PLACE, so the inbound value is
    # gone the moment the record lands.
    #
    # LESSONS §47. The source's value and a derived value are DIFFERENT FACTS and belong
    # in different attributes. Writing the derived one over the source is not reversible:
    # LOWER(TRIM(Email)) cannot be un-lowered, and once a load has run there is no
    # recovery path short of a genuine reload from the source system.
    #
    # A gap and not an error, because in-place normalization is a legitimate call when
    # the raw form genuinely carries no information — and the operator is the one who
    # knows that. What it must not be is ACCIDENTAL, which is what it was in all three
    # scenarios carrying an enricher: eight expressions, none of them a decision anyone
    # had made out loud. Scenario 3 makes the contradiction visible in its own comments,
    # where the address members are sized "for the RAW inbound value" and then
    # overwritten by the enricher that follows.
    #
    # The tell §47 names is a vendor-only field sitting populated in an attribute the
    # source never sent. By then the evidence of the overwrite is the only evidence left.
    for en in c.enrichers:
        for ex in en.expressions:
            if ex.attribute not in _IDENT.findall(ex.expression):
                continue
            ask("CA-018", f"{en.entity}/{en.name}.{ex.attribute}",
                f"This writes a derived value back over {ex.attribute!r}, its own "
                f"input. Should the derived value have its own attribute, leaving the "
                f"inbound one intact?",
                "The value the publisher actually sent is unrecoverable after the "
                "first load — there is no un-TRIM — so any later question about what "
                "the source said can only be answered by reloading it.",
                "docs/Design/data-certification/enrichers.md")

    granted = {r.role_name for r in m.roles}

    # CA-017 — the model grants NOTHING to anyone.
    #
    # The complement of CA-011, and the reason CA-011 could not catch it: CA-011 asks
    # its question only once `granted` is non-empty, so the emptiest possible model —
    # the one where every read is refused — was the single case that produced no gap at
    # all. An advisor whose coverage has a hole exactly at zero is the hand-enumeration
    # failure mode in miniature.
    #
    # Grants are per-model ("You can only define a single privilege grant for each role
    # in a model", docs/Design/security/data-hub-security.md § Model privilege grants),
    # so no other model can supply this one's privileges. With no grant the model still
    # creates, imports, deploys and certifies — and then refuses every read.
    #
    # A gap and not an error, because absence is the trigger and a headless model whose
    # data is only ever read through another route is a decision the operator is allowed
    # to make. It has to be VISIBLE, not forbidden. Acknowledge with "CA-017" in
    # `acknowledged_gaps` to say so on disk.
    #
    # The consequence line is worth its length: this failure is silent in the register
    # that matters. `POST certify/...` answers HTTP 200 with `enrichedRecord: {}` rather
    # than a 403, so the model reads as inert rather than as refusing. `GET /query/...`
    # is the only call that says "Permission Denied" out loud. OBSERVED on scenario 3,
    # 2026-08-04.
    if m.entities and not m.roles:
        ask("CA-017", m.model.name,
            "This model defines no privilege grant, so no role can read any entity in "
            "it. Which role should hold data administration and integration access?",
            "The model deploys and certifies normally and then refuses every read. "
            "The certify endpoint reports this as HTTP 200 with an empty "
            "enrichedRecord, so it looks like the model is doing nothing rather than "
            "like it is denying permission.",
            "docs/Design/security/model-privileges.md")

    if granted:                                  # only ask once the model grants at all
        for where, role in _gated(ir):
            if role not in granted:
                ask("CA-011", where,
                    f"This is restricted to role {role!r}, which has no privilege grant "
                    f"in this model. Is the grant missing, or is the role granted "
                    f"privileges by another model?",
                    f"Users with {role!r} see the entry and can open nothing behind it; "
                    f"users without it see nothing at all.",
                    "docs/Design/security/model-privileges.md")

    # CA-019 — a workflow whose task authors data that goes NOWHERE at completion.
    #
    # Measured twice on 2026-08-08 (LESSONS §58): a steward claimed the task, the
    # stepper rendered, the form was filled, the OUTGOING transition fired, the
    # instance completed through its end event — and no load of any type was minted.
    # The workflow's dataset is DISCARDED at completion unless something submits it,
    # and the IR cannot express a submit path yet (unharvested grammar), so the only
    # honest options are: acknowledge the discard as intended (a review-only surface),
    # or hold the workflow until the submit-path harvest lands. Both runs — one with a
    # synthetic key, one with a real source id, one with and one without the formal
    # Start — produced byte-identical discards, so this is a property of the
    # DEFINITION, not of the record or the lifecycle.
    steppers = {(s.entity, s.name): s for s in ir.app.steppers}
    for w in m.workflows:
        # The submit path is no longer unharvested: a SUBMIT automation
        # (workflow-hardening-constructs.json, wire `type` SUBMIT) runs an integration
        # job on the workflow's authored dataset, so a decision made in a task becomes
        # golden instead of being discarded at completion. A workflow that carries one
        # HAS a submit path, so the §58 discard cannot happen — do not ask.
        wf_submits = any(st.type == "Automation" and st.automation_type == "SUBMIT_DATA"
                         for st in w.steps)
        for st in w.steps:
            if getattr(st, "stepper", None) is None:
                continue
            sp = steppers.get((st.entity, st.stepper))
            authors = sp is not None and any(x.kind == "form" for x in sp.steps)
            has_job = sp is not None and getattr(sp, "model_job", None)
            if authors and not has_job and not wf_submits:
                ask("CA-019", f"workflow {w.name}/{st.name}",
                    f"Task {st.name!r} opens stepper {st.stepper!r}, which authors "
                    f"records — and nothing submits the workflow's dataset, so every "
                    f"steward edit is discarded when the instance completes. Is a "
                    f"review-only surface intended, or does this workflow need a "
                    f"submit path (a SUBMIT automation naming an integration job)?",
                    "Measured twice on a live instance: instance COMPLETED, no load "
                    "minted, golden and master counts unchanged. The steward gets no "
                    "error and no artifact — the quietest possible data loss.",
                    "LESSONS.md §58")

    # CA-020 — a user-facing transition with no label becomes a button named after
    # the wire. The steward's primary action on the first human-worked task was a
    # button reading OUTGOING, because `Transition.name` defaults to "outgoing" and
    # nothing set a label (§58). Only USER_TASK outgoing transitions ask: those are
    # the ones a human sees as buttons; system-step edges render for nobody.
    for w in m.workflows:
        for st in w.steps:
            if st.type != "UserTask":
                continue
            for tr in st.transitions:
                if not tr.label:
                    ask("CA-020", f"workflow {w.name}/{st.name}",
                        f"The transition {tr.name!r} out of task {st.name!r} has no "
                        f"label, so the steward's action button reads "
                        f"{tr.name.upper()!r}. What should the button say?",
                        "The raw transition name leaks straight into the task UI as "
                        "the primary action. Rendered exactly so on the first "
                        "human-worked task (2026-08-08).",
                        "LESSONS.md §58")

    acknowledged = set(m.acknowledged_gaps)
    return [g for g in gaps if g.key not in acknowledged and g.rule not in acknowledged]


def _gated(ir: IR) -> list[tuple[str, str]]:
    """Every place the application layer names a required role, with where it is."""
    out = []
    for a in ir.app.applications:
        if a.required_role:
            out.append((f"application {a.name}", a.required_role))
        for x in a.actions:
            if x.required_role:
                out.append((f"menu entry {x.name}", x.required_role))
    for v in ir.app.business_views:
        if v.required_role:
            out.append((f"business view {v.name}", v.required_role))
    for st in ir.app.action_sets:
        for x in st.actions:
            if x.required_role:
                out.append((f"action {st.name}.{x.name}", x.required_role))
    return out
