"""Sprint 12 acceptance: survivorship proposals.

The load-bearing test here is `test_the_proposer_cannot_emit_a_strategy_the_product_
never_wrote`, and it derives the legal set BY SCANNING THE CORPUS rather than by
importing the module's own constant. Asserting `LEGAL_STRATEGIES <= LEGAL_STRATEGIES`
is a check that could not fail (LESSONS §3); asserting it against what xDM actually
wrote is a check that fails the day somebody adds a plausible name from a docs page.
"""
from __future__ import annotations

import collections
import copy
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]

from agent.compile.blocks import check, render as render_findings  # noqa: E402
from agent.compile.emit import emit  # noqa: E402
from agent.compile.harvest_blocks import COMPILER_DERIVED  # noqa: E402
from agent.ir import policy, propose  # noqa: E402
from agent.ir.advise import advise  # noqa: E402
from agent.ir.schema import (IR, Attribute, Enricher, EnricherExpression,  # noqa: E402
                             Publisher, SurvivorshipRule)
from agent.ir.validate import validate  # noqa: E402
from agent.tools.citation import UNCITED  # noqa: E402

OUT = ROOT / "out"
_WIRE = re.compile(r'consolidationStrategy val="([A-Z_]+)"')


def load(name: str) -> IR:
    d = OUT / name / "ir"
    a = d / "app.yaml"
    return IR.load(d / "model.yaml", d / "certify.yaml", a if a.exists() else None)


def corpus_strategies() -> collections.Counter:
    """Every consolidation strategy spelling THE PRODUCT wrote, counted.

    `COMPILER_DERIVED` is excluded for the reason `harvest_blocks` states: xDM's
    re-export of this compiler's output hands our own strings back, so harvesting from
    it would certify whatever we already emit. Here that exclusion is not decorative —
    without it, `live/AccountHub.xml` alone would bless any strategy we shipped.
    """
    seen: collections.Counter = collections.Counter()
    for f in product_authored():
        seen.update(_WIRE.findall(f.read_text(errors="ignore")))
    return seen


def product_authored() -> list[Path]:
    """The exports the scan reads, minus this compiler's own round trips."""
    return [f for d in ("samples", "live", "harvest")
            for f in sorted((ROOT / d).glob("*.xml"))
            if f.name not in COMPILER_DERIVED]


#: The public export ships no product-authored model export at all: `samples/` holds a
#: production-sourced model and two vendor demos, `live/` and `harvest/` are the measurement
#: bench. With none of them on disk the scan measures nothing, and a vocabulary
#: assertion against an empty corpus passes vacuously — which is the exact failure
#: `test_the_corpus_scan_finds_something` exists to prevent. So the three tests whose
#: subject IS the corpus skip, and the thirty-odd heuristic rows below keep running.
requires_product_exports = pytest.mark.skipif(
    not product_authored(),
    reason="samples/, live/ and harvest/ product exports not present")

#: `docs/` is vendor documentation and is not in the public export either.
requires_docs = pytest.mark.skipif(
    not (ROOT / "docs/Design/matching/survivorship.md").exists(),
    reason="docs/Design/matching/survivorship.md not present")


@pytest.fixture
def s2_uncovered() -> IR:
    """s2 with its VALUE rules removed and its Master ID rule kept.

    Keeping the id rule matters: IR-019 makes a matched entity without one an error, so
    stripping everything would produce a fixture that is broken for a reason that has
    nothing to do with the proposals under test.
    """
    ir = load("s2-two-crms")
    ir.certify.survivorship = [s for s in ir.certify.survivorship if s.kind == "id"]
    return ir


# ---------------------------------------------------------------- the vocabulary gate
@requires_product_exports
def test_the_corpus_scan_finds_something():
    """Check the instrument before believing it. An empty scan would make every
    vocabulary assertion below pass vacuously."""
    seen = corpus_strategies()
    assert sum(seen.values()) >= 25, f"the corpus scan found {sum(seen.values())}"
    assert len(seen) >= 3, f"only {sorted(seen)} — the scan probably reads one file"


@requires_product_exports
def test_the_module_constant_is_what_the_corpus_says():
    assert set(propose.LEGAL_STRATEGIES) == set(corpus_strategies())


@requires_product_exports
def test_the_proposer_cannot_emit_a_strategy_the_product_never_wrote():
    """THE acceptance criterion. Drive the proposer over every heuristic row at once
    and assert each strategy it reaches for was measured in a product-authored export.
    """
    legal = set(corpus_strategies())
    ir = load("s2-two-crms")
    ir.certify.survivorship = [s for s in ir.certify.survivorship if s.kind == "id"]
    e = ir.model_ir.entities[0]
    e.attributes += [
        Attribute(name="DisplayName", type="String", length=100),
        Attribute(name="MiddleInitial", type="String", length=5),
        Attribute(name="NameSuffix", type="String", length=10),
        Attribute(name="PhoneMobile", type="String", length=40),
        Attribute(name="EmailAlt", type="String", length=120),
        Attribute(name="IsActive", type="Boolean"),
        Attribute(name="LegacyRef", type="String", length=40),
        Attribute(name="MDM_Batch", type="String", length=40, physical_name="MDM_BATCH"),
        Attribute(name="Source_ID", type="String", length=40, physical_name="SOURCE_ID"),
    ]
    result = propose.propose(ir)
    assert result.proposals, "the battery produced no proposals — fixture is wrong"
    for p in result.proposals:
        assert p.strategy in legal, (
            f"{p.entity}.{'/'.join(p.attributes)} proposes {p.strategy!r}, which no "
            f"product-authored export writes. Observed: {sorted(legal)}")


def test_a_dialect_name_is_refused_at_the_factory_not_translated():
    """The rule-builder is the last gate: even a future heuristic that reaches for a
    dialect name gets an exception rather than a silently-emitted rule."""
    for bad in propose.REFUSED_STRATEGIES:
        with pytest.raises(ValueError) as x:
            propose._standard("Customer", "Email", bad, taken=set(),
                              computed=False, ranking=["CrmEu"])
        assert "observed" in str(x.value)


def test_every_refused_name_really_is_absent_from_the_corpus():
    """A refusal list nobody re-measures becomes folklore. This is the check that turns
    "the dialect is wrong" into a fact with a date on it."""
    seen = set(corpus_strategies())
    for bad, why in propose.REFUSED_STRATEGIES.items():
        assert bad not in seen, f"{bad} IS in the corpus now — it is legal, not refused"
        assert why, f"{bad} is refused with no reason"


@requires_docs
@requires_product_exports
def test_most_frequent_value_is_documented_and_still_refused():
    """The one refusal that is NOT a foreign dialect — the docs name it and no export
    spells it. Both halves are measured here, because the whole argument for refusing a
    documented strategy is that a docs label is not a wire string (LESSONS §51.2)."""
    doc = (ROOT / "docs/Design/matching/survivorship.md").read_text()
    assert "Most Frequent Value" in doc
    assert "MOST_FREQUENT_VALUE" not in doc
    assert "MOST_FREQUENT_VALUE" not in corpus_strategies()
    assert "MOST_FREQUENT_VALUE" in propose.REFUSED_STRATEGIES
    assert "harvest" in propose.REFUSED_STRATEGIES["MOST_FREQUENT_VALUE"], \
        "a refusal must name the way out"


# ------------------------------------------------------------------- the heuristic rows
@pytest.mark.parametrize("attr,type_,strategy", [
    ("FullName", "String", "LARGEST_VALUE"),
    ("DisplayName", "String", "LARGEST_VALUE"),
    ("MiddleName", "String", "LARGEST_VALUE"),
    ("NameSuffix", "String", "LARGEST_VALUE"),
    ("EmailWork", "String", "PREFERRED_PUBLISHER"),
    ("PhoneMobile", "String", "PREFERRED_PUBLISHER"),
    ("IsActive", "Boolean", "PREFERRED_PUBLISHER"),
    ("RegionCode", "String", "PREFERRED_PUBLISHER"),
])
def test_each_heuristic_row(s2_uncovered, attr, type_, strategy):
    e = s2_uncovered.model_ir.entities[0]
    e.attributes = [a for a in e.attributes if a.pk] + [
        Attribute(name=attr, type=type_, length=(80 if type_ == "String" else None))]
    p = propose.propose(s2_uncovered).proposals
    assert [x.strategy for x in p] == [strategy], propose.render(s2_uncovered)


def test_a_boolean_never_gets_the_invented_most_recent_true(s2_uncovered):
    e = s2_uncovered.model_ir.entities[0]
    e.attributes = [a for a in e.attributes if a.pk] + [
        Attribute(name="IsActive", type="Boolean")]
    out = propose.propose(s2_uncovered)
    assert [p.strategy for p in out.proposals] == ["PREFERRED_PUBLISHER"]
    # The dialect name appears in the rendering only as the thing being REFUSED, which
    # is the point: a silent substitution teaches nobody why.
    why = out.proposals[0].why
    assert "MostRecentTrue" in why and "refused" in why


def test_an_enricher_output_is_owned_by_the_pipeline(s2_uncovered):
    """The CA-012 class. POST_CONSO, because CA-002 already excludes the PRE_CONSO
    computed attributes from the set it asks about — so this is the scope where the row
    actually fires."""
    e = s2_uncovered.model_ir.entities[0]
    e.attributes = [a for a in e.attributes if a.pk] + [
        Attribute(name="RiskBand", type="String", length=20),
        Attribute(name="Segment", type="String", length=20)]
    s2_uncovered.certify.enrichers.append(Enricher(
        entity=e.name, name="ScoreRisk", scope="POST_CONSO",
        expressions=[EnricherExpression(attribute="RiskBand",
                                        expression="CASE WHEN CreditLimit > 0 "
                                                   "THEN 'A' ELSE 'B' END")]))
    by_attr = {p.attributes[0]: p for p in propose.propose(s2_uncovered).proposals}
    assert by_attr["RiskBand"].rule.override_strategy == policy.OVERRIDE_FORBIDDEN
    assert by_attr["RiskBand"].provenance == "policy"
    # ...and an attribute no enricher writes keeps the editable default.
    assert by_attr["Segment"].rule.override_strategy == policy.OVERRIDE_ALLOWED


def test_the_override_spelling_is_the_measured_one_not_the_sprint_files(s2_uncovered):
    """The sprint table says "override NEVER". NEVER is the invention the live importer
    refused (LESSONS §16); the product's word is NO_OVERRIDE, and policy holds it."""
    e = s2_uncovered.model_ir.entities[0]
    e.attributes = [a for a in e.attributes if a.pk] + [
        Attribute(name="RiskBand", type="String", length=20)]
    s2_uncovered.certify.enrichers.append(Enricher(
        entity=e.name, name="ScoreRisk", scope="POST_CONSO",
        expressions=[EnricherExpression(attribute="RiskBand", expression="'A'")]))
    for p in propose.propose(s2_uncovered).proposals:
        assert p.rule.override_strategy in policy.OVERRIDE_STRATEGIES
        assert p.rule.override_strategy != "NEVER"


def test_an_identity_attribute_defers_to_the_golden_id(s2_uncovered):
    """Row 1: identity survives via the golden ID. The entity already has a Master ID
    rule, and an IdSurvivorshipRule carries no attribute list — so the honest output is
    a REFUSAL with the reason, not a standard rule pretending to cover it."""
    e = s2_uncovered.model_ir.entities[0]
    e.attributes = [a for a in e.attributes if a.pk] + [
        Attribute(name="Legacy_ID", type="String", length=40,
                  physical_name="LEGACY_ID")]
    out = propose.propose(s2_uncovered)
    assert not out.proposals
    assert [r.attribute for r in out.refusals] == ["Legacy_ID"]
    assert "golden ID" in out.refusals[0].why


def test_an_identity_attribute_with_no_master_id_rule_proposes_one(s2_uncovered):
    s2_uncovered.certify.survivorship = []
    e = s2_uncovered.model_ir.entities[0]
    e.attributes = [a for a in e.attributes if a.pk] + [
        Attribute(name="Legacy_ID", type="String", length=40,
                  physical_name="LEGACY_ID")]
    out = propose.propose(s2_uncovered)
    assert [p.rule.kind for p in out.proposals] == ["id"]
    assert out.proposals[0].rule.attributes == []      # measured: no attribute list
    assert out.proposals[0].rule.publisher_rankings


def test_a_basic_entity_is_left_alone():
    """IR-002 makes a survivorship rule on a basic entity an ERROR. Proposing one would
    be proposing a defect."""
    ir = load("s4-multi-source-ids")
    ir.certify.survivorship = [s for s in ir.certify.survivorship if s.kind == "id"]
    assert {p.entity for p in propose.propose(ir).proposals} == {"Customer"}


# ------------------------------------------------------------------------ house policy
def test_policy_puts_the_steward_publisher_first(s2_uncovered):
    s2_uncovered.model_ir.publishers.insert(
        1, Publisher(name="Stewardship", code="STEWARD"))
    ranking, open_qs = propose.publisher_ranking(s2_uncovered.model_ir)
    assert ranking[0] == "Stewardship", "policy.STEWARD_RANKS_FIRST is not applied"
    assert ranking[1:] == ["CrmEu", "CrmUs"]
    assert open_qs and "DECLARED ORDER" in open_qs[0]


def test_the_ranking_is_never_presented_as_a_decision(s2_uncovered):
    """It has to be filled — IR-011 refuses an empty one and the emitter resolves each
    name to a publisher UUID. So it is filled AND flagged, on every proposal that
    carries one."""
    for p in propose.propose(s2_uncovered).proposals:
        if p.strategy == "PREFERRED_PUBLISHER":
            assert p.rule.publisher_rankings
            assert p.open_questions, f"{p.rule.name} ranks publishers with no question"
            assert any("not a decision" in q for q in p.open_questions)


def test_the_ranking_names_publishers_the_model_declares(s2_uncovered):
    """IR-008: a ranking by CODE is a KeyError in the emitter, not a design error."""
    declared = {p.name for p in s2_uncovered.model_ir.publishers}
    for p in propose.propose(s2_uncovered).proposals:
        assert set(p.rule.publisher_rankings) <= declared


def test_a_model_with_no_publishers_refuses_rather_than_ranks(s2_uncovered):
    s2_uncovered.model_ir.publishers = []
    out = propose.propose(s2_uncovered)
    assert not out.proposals or all(
        p.strategy != "PREFERRED_PUBLISHER" for p in out.proposals)
    assert any("IR-011" in r.why for r in out.refusals)


# ----------------------------------------------------------------- tagged, not adopted
def test_every_proposal_carries_the_repos_own_tag(s2_uncovered):
    out = propose.propose(s2_uncovered)
    assert out.proposals
    for p in out.proposals:
        assert p.tag == UNCITED
        assert UNCITED in p.render()
    assert "review, do not adopt" in out.render()


def test_there_is_one_tag_convention_not_two():
    src = (ROOT / "agent/ir/propose.py").read_text()
    assert "AI_ASSUMED" not in src, "the sibling project's tag; this repo has one already"


def test_proposing_never_mutates_the_ir(s2_uncovered):
    before = s2_uncovered.model_dump()
    out = propose.propose(s2_uncovered)
    spliced = propose.splice(s2_uncovered, out)
    assert s2_uncovered.model_dump() == before, "propose/splice mutated the input IR"
    assert len(spliced.certify.survivorship) == \
        len(s2_uncovered.certify.survivorship) + len(out.proposals)


def test_nothing_writes_to_disk():
    """A proposal that adopts itself is not a proposal. The module must not know how to
    write certify.yaml at all."""
    src = (ROOT / "agent/ir/propose.py").read_text()
    for forbidden in ("open(", "write_text", "yaml.dump", "safe_dump"):
        assert forbidden not in src, f"propose.py contains {forbidden!r}"


# --------------------------------------------------------- proposals go through emit
def _findings(ir: IR):
    xml = emit(ir.model_ir, platform_version="x", repository_version="y",
               certify=ir.certify, app=ir.app)
    return xml, {(f.kind, f.obj, f.element) for f in check(xml)}


def test_the_proposals_compile(s2_uncovered):
    """Acceptance: "every proposed rule compiles — proposals go through emit, not
    around it". The bar is NO NEW shape findings against the same model without them,
    which is stricter than "the emitter did not crash"."""
    _, before = _findings(s2_uncovered)
    spliced = propose.splice(s2_uncovered)
    xml, after = _findings(spliced)
    new = after - before
    assert not new, f"the proposals introduced {sorted(new)}\n" + render_findings(
        [f for f in check(xml) if (f.kind, f.obj, f.element) in new])
    # And nothing invented or mis-encoded, in absolute terms — the two kinds that are
    # never acceptable debt.
    hard = [f for f in check(xml) if f.kind in ("encoding", "unknown")]
    assert not hard, render_findings(hard)


def test_the_proposals_reach_the_xml(s2_uncovered):
    """A compile test that never emitted the rules would pass for the wrong reason."""
    xml, _ = _findings(propose.splice(s2_uncovered))
    for p in propose.propose(s2_uncovered).proposals:
        assert f"<name>{p.rule.name}</name>" in xml
        assert f'<consolidationStrategy val="{p.rule.strategy}" />' in xml


def test_the_proposals_introduce_no_validation_errors(s2_uncovered):
    """They compile; they must also be a model the validator accepts. IR-011 (a ranking
    on every PREFERRED_PUBLISHER rule) and IR-008 (rank by name) both bite here."""
    before = {(f.rule, f.where) for f in validate(s2_uncovered) if f.severity == "error"}
    after = {(f.rule, f.where)
             for f in validate(propose.splice(s2_uncovered)) if f.severity == "error"}
    assert not (after - before), f"the proposals added {sorted(after - before)}"


def test_the_proposals_close_the_gap_they_answer(s2_uncovered):
    """The proof that the proposal set is COMPLETE for the question asked: splice it in
    and CA-002 has nothing left to ask about that entity."""
    assert any(g.rule == "CA-002" for g in advise(s2_uncovered))
    assert not any(g.rule == "CA-002" for g in advise(propose.splice(s2_uncovered)))


# ------------------------------------------------------------------- the CA-002 wiring
def test_ca002_now_carries_a_proposed_answer(s2_uncovered):
    g = next(x for x in advise(s2_uncovered) if x.rule == "CA-002")
    assert g.proposals, "CA-002 still asks with a blank page under it"
    body = g.render()
    assert UNCITED in body
    assert "PREFERRED_PUBLISHER" in body and "LARGEST_VALUE" in body


def test_the_fire_condition_is_unchanged():
    """Wiring an answer onto a question must not change WHEN the question is asked. The
    four authored scenarios raise exactly the gaps they raised before."""
    for name in ("s1-country-reference", "s2-two-crms", "s3-three-sources",
                 "s4-multi-source-ids"):
        ir = load(name)
        assert not any(g.rule == "CA-002" for g in advise(ir)), \
            f"{name} newly raises CA-002"


def test_advice_still_never_blocks(s2_uncovered):
    """CA rules ask; they do not block. Splicing proposals in or leaving them out, the
    model's ERROR set is the advisor's business either way."""
    gaps = advise(s2_uncovered)
    assert all(g.rule.startswith("CA-") for g in gaps)
    assert isinstance(gaps, list)


def test_an_acknowledged_gap_stays_closed_even_with_proposals(s2_uncovered):
    s2_uncovered.model_ir.acknowledged_gaps = ["CA-002:Customer"]
    assert not any(g.rule == "CA-002" for g in advise(s2_uncovered))
