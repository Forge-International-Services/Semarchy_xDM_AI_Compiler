"""Certification constructs, XML -> IR. Sprint 06.

Enrichers, matchers, match rules with binning, and survivorship. Split from
extract.py because it reads the same Entity elements for a different purpose, and
keeping model core separable is what let sprint 05 close on its own.

Ground truth is n=2 — CORPUS_A and gs-customerb2c. They disagree usefully: CORPUS_A bins
every probabilistic rule, gs-customerb2c bins none, so a grammar that reproduces
both is not over-fitted to either.

Validations are NOT here. Neither sample contains a Validation element, so there is
no observed grammar for them — the same reason PluginEnricher was excluded until a
sample turned up.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from agent.ir.schema import THRESHOLDS, CertifyIR

# FormStepEnricher is NOT here. It lives under Stepper > FormStep > formStepEnrichers,
# i.e. it is stepper UI logic, not part of the certification pipeline. The authoring
# guide groups it with the enrichers by name; structurally it belongs to the
# application layer, so it is sprint 07's.
ENRICHER_TAGS = {"SemQLEnricher": "semql", "PluginEnricher": "plugin"}


def _text(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None:
        return None
    return child.attrib.get("val", child.text)


def _int(el: ET.Element, tag: str, default: int | None = None) -> int | None:
    v = _text(el, tag)
    return int(v) if v and v.lstrip("-").isdigit() else default


def _bool(el: ET.Element, tag: str) -> bool:
    return _text(el, tag) == "true"


def extract_certify(path: str | Path) -> CertifyIR:
    root = ET.parse(path).getroot()
    model = root.find("Model")
    publisher_names = {_text(p, "internalID"): _text(p, "name")
                       for p in model.iter("Publisher")}

    enrichers, matchers, survivorship, validations = [], [], [], []
    for entity in model.iter("Entity"):
        name = _text(entity, "name")
        enrichers += _enrichers(entity, name)
        matchers += _matchers(entity, name)
        survivorship += _survivorship(entity, name, publisher_names)
        validations += _validations(entity, name)
    entity_names = {_text(e, "internalID"): _text(e, "name")
                    for e in model.iter("Entity")}
    jobs = [_job(j, entity_names)
            for holder in model.findall("modelJobs") for j in holder.iter("ModelJob")]
    return CertifyIR(enrichers=enrichers, matchers=matchers,
                     survivorship=survivorship, validations=validations, jobs=jobs)


def _validations(entity: ET.Element, ename: str) -> list[dict]:
    """CheckConstraint, inside abstractRowCheckConstraints.

    Sprint 06 recorded that validations had "no observed grammar" because it searched
    for an element named `Validation`. The construct was there all along under another
    name — the same mistake as looking for AtomicAttribute inside a ComplexType.

    PluginValidator is a sibling in the same container and is NOT read here: it carries
    plugin inputs and params that the IR does not model.
    """
    return [{"entity": ename, "name": _text(c, "name"),
             "condition": _text(c, "condition") or "",
             "scope": _text(c, "validationScope") or "PRE_CONSO",
             "label": _text(c, "label"),
             "description": _text(c, "description"),
             "error_message": _text(c, "validationLabel")}
            for h in entity.findall("abstractRowCheckConstraints")
            for c in h.iter("CheckConstraint")]


def _job(j: ET.Element, entity_names: dict) -> dict:
    """An integration job and the per-entity phases it actually runs."""
    tasks = []
    for holder in j.findall("modelTasks"):
        for t in holder.iter("ModelJobTask"):
            e = t.find("entity")
            tasks.append({
                "entity": entity_names.get(e.attrib.get("ref")) if e is not None else None,
                "position": _int(t, "posInJob", 1),
                "source_validation": _bool(t, "sourceValidationEnabled"),
                "source_enrichment": _bool(t, "sourceDataEnrichmentEnabled"),
                "match": _bool(t, "matchEnabled"),
                "consolidation": _bool(t, "consolidationEnabled"),
                "consolidated_enrichment": _bool(t, "consolidatedDataEnrichmentEnabled"),
                "post_conso_validation": _bool(t, "postConsoValidationEnabled"),
            })
    params = [{"name": _text(x, "name"), "value": _text(x, "value")}
              for holder in j.findall("jobParams") for x in holder.iter("ModelJobParam")]
    return {"name": _text(j, "name"), "job_type": _text(j, "jobType") or "INTEGRATION",
            "queue": _text(j, "queueName") or "Default",
            "description": _text(j, "description"), "params": params, "tasks": tasks}


def _enrichers(entity: ET.Element, ename: str) -> list[dict]:
    out = []
    for holder in entity.findall("enrichers"):
        for el in holder:
            kind = ENRICHER_TAGS.get(el.tag)
            if kind is None:
                continue
            d = {
                "entity": ename, "name": _text(el, "name"), "kind": kind,
                # enricherExecutionScope is absent on FormStepEnricher, present on the
                # other two (authoring guide §5.5).
                "scope": _text(el, "enricherExecutionScope"),
                "condition": _text(el, "condition"),
                "position": _int(el, "posInEntity", 0),
                "expressions": [
                    {"attribute": _text(x, "attributeName") or "",
                     "expression": _text(x, "expression") or ""}
                    for x in el.iter("SemQLEnricherExpression")
                ],
            }
            if kind == "plugin":
                d["plugin_id"] = _text(el, "pluginID")
                d["on_error"] = _text(el, "onErrorBehavior") or "FAIL_JOB"
                d["plugin_io"] = [
                    {"kind": k, "name": _text(io, "name") or "",
                     "value": _text(io, "value") or _text(io, "attributeName")}
                    for tag, k in (("PluginEnricherInput", "input"),
                                   ("PluginEnricherOutput", "output"),
                                   ("PluginEnricherParam", "param"))
                    for io in el.iter(tag)
                ]
            out.append(d)
    return out


def _matchers(entity: ET.Element, ename: str) -> list[dict]:
    out = []
    for holder in entity.findall("matcher"):
        for el in holder.iter("SemQLMatcher"):
            out.append({
                "entity": ename,
                "thresholds": {t: _int(el, t, 0) for t in THRESHOLDS},
                "auto_confirm_singletons": _bool(el, "autoConfirmSingletons"),
                "use_multi_iteration_grouping": _bool(el, "useMultiIterationGrouping"),
                "use_transitive_match_score": _bool(el, "useTransitiveMatchScore"),
                "rules": [
                    {"name": _text(r, "name"), "score": _int(r, "matchScore", 0),
                     "condition": _text(r, "condition") or "",
                     "position": _int(r, "posInParent", 0),
                     "binning": [_text(b, "expression") or ""
                                 for b in r.iter("SemQLMatchRuleBinningExpression")],
                     # Extracted rules are recorded as-authored. Acknowledging an
                     # unbinned rule is an authoring decision, so extraction must not
                     # silently grant it — IR-010 should still fire on a real model.
                     "acknowledged": False}
                    for r in el.iter("SemQLMatchRule")
                ],
            })
    return out


def _survivorship(entity: ET.Element, ename: str, publishers: dict) -> list[dict]:
    out = []
    for holder in entity.findall("survivorshipRules"):
        for el in holder:
            if el.tag not in ("StandardSurvivorshipRule", "IdSurvivorshipRule"):
                continue
            # `r.find(tag) or default` is a trap: an Element with no children is
            # FALSY, so a found-but-childless <publisher ref=.../> takes the fallback
            # and every ranking silently resolves to None. Same bug as extract.py's
            # complex-type lookup — test `is not None`.
            rankings = []
            for r in el.iter("ConsoPublisherRanking"):
                pub = r.find("publisher")
                if pub is not None:
                    rankings.append(publishers.get(pub.attrib.get("ref", "")))
            out.append({
                "entity": ename, "name": _text(el, "name"),
                "kind": "id" if el.tag == "IdSurvivorshipRule" else "standard",
                "strategy": _text(el, "consolidationStrategy") or "",
                "attributes": [_text(a, "attributeName") or ""
                               for a in el.iter("SurvivorshipRuleAttribute")],
                "skip_nulls": _bool(el, "consolidationSkipNulls"),
                "default_rule": _bool(el, "defaultRule"),
                "override_strategy": _text(el, "overrideStrategy") or "UNTIL_NEXT_USER_CHANGE",
                "override_decay_duration": _int(el, "overrideDecayTimeDuration"),
                "override_decay_unit": _text(el, "overrideDecayTimeUnit"),
                "order_by": _text(el, "consolidationOrderByExpression"),
                "publisher_rankings": [r for r in rankings if r],
            })
    return out
