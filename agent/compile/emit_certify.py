"""Certification constructs, IR -> XML. Sprint 06.

These live INSIDE the Entity element, so emit.py calls in here while building each
entity rather than emitting a separate top-level container.

Ground truth is n=2. CORPUS_A and gs-customerb2c disagree on binning — every
probabilistic rule versus none — so reproducing both is evidence the grammar is not
over-fitted to either.
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

from agent.compile import envelope
from agent.compile.emit import ref, scalar, text
from agent.compile.mint import mint

ENRICHER_TAG = {"semql": "SemQLEnricher", "plugin": "PluginEnricher"}
IO_TAG = {"input": "PluginEnricherInput", "output": "PluginEnricherOutput",
          "param": "PluginEnricherParam"}


def rank(items) -> list[int]:
    """The authored order, serialized as the DISTINCT integers the product requires.

    The IR's `position` is an ordering INTENT, and equal positions are a real
    statement: `depends` reads them as "these two constrain nothing about each other",
    which is why s3 declares three normalizers at 1 and the phonetic enricher at 2.

    xDM cannot say that. The Application Builder's Validation view refuses it:

        Duplicate Position: Position "0" is already used in the set of objects.

    So the tie is resolved HERE — deterministic code deciding *how*, the model still
    deciding *what* (D3). Ranking is stable, so ties keep declaration order, and the
    result is 0-based and dense: `posInEntity` starts at 0 in all three product
    exports that carry enrichers, and `posInParent` at 0 for match rules in two of
    three (corpus-a starts at 2 because two rules were deleted — gaps are allowed,
    duplicates are not).

    ALREADY-DISTINCT POSITIONS ARE LEFT ALONE. Gaps are legal and meaningful — a
    modeller who deletes two of twenty enrichers gets 0..19 with two holes, and
    corpus model A's export carries exactly that — so renumbering a set the product would
    accept would rewrite an author's spacing for no reason, and would make every
    extract/emit round trip of a real export a diff. Ranking is the tie-break, and it
    fires only where xDM would refuse the document.

    Order-preserving rather than value-preserving when it does fire: 1,1,1,2 comes back
    from a round trip as 0,1,2,3 — the same execution plan, spelled the way the product
    spells it.
    """
    have = [x.position for x in items]
    if len(set(have)) == len(have):
        return have
    order = sorted(range(len(items)), key=lambda i: (items[i].position, i))
    out = [0] * len(items)
    for r, i in enumerate(order):
        out[i] = r
    return out


def emit_entity_certification(entity_el: ET.Element, ename: str, certify,
                              publisher_uuid) -> None:
    ours = lambda xs: [x for x in xs if x.entity == ename]          # noqa: E731
    _enrichers(entity_el, ename, ours(certify.enrichers))
    _validations(entity_el, ename, ours(certify.validations))
    _matcher(entity_el, ename, ours(certify.matchers))
    _survivorship(entity_el, ename, ours(certify.survivorship), publisher_uuid)


def _enrichers(parent: ET.Element, ename: str, items) -> None:
    if not items:
        return
    holder = ET.SubElement(parent, "enrichers")
    # Ranked over the enrichers actually EMITTED. A form_step enricher belongs to the
    # stepper and never lands here, so ranking before the filter would leave holes that
    # mean nothing — and `posInEntity` is one set shared by SemQLEnricher and
    # PluginEnricher alike (gs-customerb2c's Person interleaves them 0..7).
    items = [e for e in items if ENRICHER_TAG.get(e.kind) is not None]
    for e, pos in zip(items, rank(items)):
        tag = ENRICHER_TAG[e.kind]
        el = ET.SubElement(holder, tag)
        envelope.audit(el, mint("entity", ename, "enricher", e.name))
        text(el, "name", e.name)
        text(el, "label", e.name)
        text(el, "condition", e.condition)
        scalar(el, "enricherExecutionScope", e.scope or "PRE_CONSO")
        scalar(el, "posInEntity", pos)
        if e.kind == "semql":
            exprs = ET.SubElement(el, "semQLEnricherExpressions")
            for x in e.expressions:
                x_el = ET.SubElement(exprs, "SemQLEnricherExpression")
                envelope.audit(x_el, mint("entity", ename, "enricher", e.name, x.attribute))
                text(x_el, "attributeName", x.attribute)
                text(x_el, "expression", x.expression)
        else:
            text(el, "pluginID", e.plugin_id)
            scalar(el, "onErrorBehavior", e.on_error)
            scalar(el, "numberOfRetry", 0)
            scalar(el, "processingBatchSize", 1)
            scalar(el, "threadPoolSize", 1)
            for kind, container in (("input", "pluginInputs"), ("output", "pluginOutputs"),
                                    ("param", "pluginParams")):
                io = [i for i in e.plugin_io if i.kind == kind]
                if not io:
                    continue
                c = ET.SubElement(el, container)
                for i in io:
                    i_el = ET.SubElement(c, IO_TAG[kind])
                    envelope.audit(i_el, mint("entity", ename, "enricher", e.name, kind, i.name))
                    text(i_el, "name", i.name)
                    text(i_el, "value", i.value)


def _validations(parent: ET.Element, ename: str, items) -> None:
    """CheckConstraint, in abstractRowCheckConstraints. No severity — see the IR."""
    if not items:
        return
    holder = ET.SubElement(parent, "abstractRowCheckConstraints")
    for v in items:
        el = ET.SubElement(holder, "CheckConstraint")
        envelope.audit(el, mint("entity", ename, "validation", v.name))
        text(el, "name", v.name)
        text(el, "label", v.label or v.name)
        text(el, "description", v.description)
        text(el, "condition", v.condition)
        # The docs' "Error Message": custom text replacing the default on forms, in
        # error business views and in REST responses.
        text(el, "validationLabel", v.error_message)
        scalar(el, "validationScope", v.scope)


def _matcher(parent: ET.Element, ename: str, items) -> None:
    if not items:
        return
    holder = ET.SubElement(parent, "matcher")
    for m in items:
        el = ET.SubElement(holder, "SemQLMatcher")
        envelope.audit(el, mint("entity", ename, "matcher"))
        for name, value in m.resolved_thresholds().items():
            scalar(el, name, value)
        scalar(el, "autoConfirmSingletons", m.auto_confirm_singletons)
        scalar(el, "useMultiIterationGrouping", m.use_multi_iteration_grouping)
        scalar(el, "useTransitiveMatchScore", m.use_transitive_match_score)
        rules = ET.SubElement(el, "matchRules")
        for r, pos in zip(m.rules, rank(m.rules)):
            r_el = ET.SubElement(rules, "SemQLMatchRule")
            envelope.audit(r_el, mint("entity", ename, "matchRule", r.name))
            text(r_el, "name", r.name)
            text(r_el, "label", r.name)
            text(r_el, "condition", r.condition)
            scalar(r_el, "matchScore", r.score)
            scalar(r_el, "posInParent", pos)
            scalar(r_el, "usingMatchOn", False)
            # An EMPTY binningExpressions container is valid and meaningful — it means
            # full cartesian product within scope. gs-customerb2c does this for every
            # rule, so the container is always emitted, populated or not.
            b = ET.SubElement(r_el, "binningExpressions")
            for expr in r.binning:
                b_el = ET.SubElement(b, "SemQLMatchRuleBinningExpression")
                envelope.audit(b_el, mint("entity", ename, "matchRule", r.name, "bin", expr))
                text(b_el, "expression", expr)


def _survivorship(parent: ET.Element, ename: str, items, publisher_uuid) -> None:
    if not items:
        return
    holder = ET.SubElement(parent, "survivorshipRules")
    for s in items:
        tag = "IdSurvivorshipRule" if s.kind == "id" else "StandardSurvivorshipRule"
        el = ET.SubElement(holder, tag)
        envelope.audit(el, mint("entity", ename, "survivorship", s.name))
        text(el, "name", s.name)
        text(el, "label", s.name)
        # description and documentation are present on EVERY survivorship rule in
        # every export, as explicit nulls. Omitting them made the import refuse.
        text(el, "description", None)
        text(el, "documentation", None)
        text(el, "consolidationOrderByExpression", s.order_by)
        scalar(el, "consolidationStrategy", s.strategy)
        scalar(el, "consolidationSkipNulls", s.skip_nulls)
        if s.kind == "standard":
            # An IdSurvivorshipRule governs the golden key, so it carries neither a
            # defaultRule flag, an override policy, nor an attribute list.
            scalar(el, "defaultRule", s.default_rule)
            scalar(el, "overrideStrategy", s.override_strategy)
            # Always emitted, null when unset — an absent element is not the same as
            # an explicitly-null one to this importer.
            if s.override_decay_duration is not None:
                scalar(el, "overrideDecayTimeDuration", s.override_decay_duration)
            else:
                text(el, "overrideDecayTimeDuration", None)
            if s.override_decay_unit:
                scalar(el, "overrideDecayTimeUnit", s.override_decay_unit)
            else:
                text(el, "overrideDecayTimeUnit", None)
            attrs = ET.SubElement(el, "attributes")
            for a in s.attributes:
                a_el = ET.SubElement(attrs, "SurvivorshipRuleAttribute")
                envelope.audit(a_el, mint("entity", ename, "survivorship", s.name, a))
                text(a_el, "attributeName", a)
        ranks = ET.SubElement(el, "publisherRankings")
        for i, pub in enumerate(s.publisher_rankings, 1):
            r_el = ET.SubElement(ranks, "ConsoPublisherRanking")
            envelope.audit(r_el, mint("entity", ename, "survivorship", s.name, "rank", pub))
            scalar(r_el, "rank", i)
            ref(r_el, "publisher", publisher_uuid(pub))


def emit_model_jobs(model_el: ET.Element, jobs, entity_uuid) -> None:
    """Model-level, so emit.py calls this once rather than per entity.

    A job task is the switch that makes a certification phase actually run. Emitting
    the phases verbatim from the IR keeps that switch visible in the spec instead of
    buried in a batch definition nobody reads.
    """
    if not jobs:
        return
    holder = ET.SubElement(model_el, "modelJobs")
    for j in jobs:
        el = ET.SubElement(holder, "ModelJob")
        envelope.audit(el, mint("modelJob", j.name))
        text(el, "name", j.name)
        text(el, "description", j.description)
        scalar(el, "jobType", j.job_type)
        # queueName is FREE TEXT, not an enum: `<queueName>Default</queueName>`.
        # Emitting it as `val="Default"` is accepted by the importer and stored as
        # null, and the Execution Engine then shows the queue as `Q0.null`, SUSPENDED,
        # with REST refusing every action on the load: "No queue bound to load 112".
        # The rule this cost: enums and numbers use `val=`, free-text uses element text.
        text(el, "queueName", j.queue)
        if j.params:
            ph = ET.SubElement(el, "jobParams")
            for p in j.params:
                pe = ET.SubElement(ph, "ModelJobParam")
                envelope.audit(pe, mint("modelJob", j.name, "param", p.name))
                text(pe, "name", p.name)
                text(pe, "value", p.value)
        if j.tasks:
            th = ET.SubElement(el, "modelTasks")
            for t in j.tasks:
                te = ET.SubElement(th, "ModelJobTask")
                envelope.audit(te, mint("modelJob", j.name, "task", t.entity))
                text(te, "name", t.entity)
                scalar(te, "posInJob", t.position)
                scalar(te, "sourceValidationEnabled", t.source_validation)
                scalar(te, "sourceDataEnrichmentEnabled", t.source_enrichment)
                scalar(te, "matchEnabled", t.match)
                scalar(te, "consolidationEnabled", t.consolidation)
                scalar(te, "consolidatedDataEnrichmentEnabled",
                       t.consolidated_enrichment)
                scalar(te, "postConsoValidationEnabled", t.post_conso_validation)
                ref(te, "entity", entity_uuid(t.entity))
