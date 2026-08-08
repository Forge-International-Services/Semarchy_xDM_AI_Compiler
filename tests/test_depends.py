"""Dependency and execution order — step 1. The third way a model goes wrong.

Blocks decide the shape, decisions decide the values, and neither can see this: every
piece correct, running in the wrong order, or a piece that another piece needs simply
absent. Both are silent and both cost a live run to find.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.compile.blocks import check as shape_check  # noqa: E402
from agent.compile.emit import emit  # noqa: E402
from agent.ir.depends import (  # noqa: E402
    cycles, enricher_dependencies, execution_order, missing_prerequisites,
    order_violations, render)
from agent.ir.schema import IR  # noqa: E402
from agent.ir.validate import validate  # noqa: E402
from agent.tools.semql import check_ir  # noqa: E402

S3 = ROOT / "out/s3-three-sources/ir"


def _s3() -> IR:
    return IR.load(S3 / "model.yaml", S3 / "certify.yaml")


def _break_order(ir: IR) -> IR:
    """Exactly the bug that shipped: the consumer shares its producer's position."""
    for e in ir.certify.enrichers:
        if e.name == "PhoneticName":
            e.position = 1
    return ir


def test_the_shipped_bug_was_invisible_to_every_other_check():
    """The justification for this module. On the broken model: the IR validator is
    silent, SemQL is clean, and the shape conforms — while PhoneticNameToken is empty
    on every master record and both phonetic match rules are dead."""
    ir = _break_order(_s3())
    others = [f for f in validate(ir) if f.rule != "IR-021"]
    assert not [f for f in others if f.severity == "error"]
    assert check_ir(ir) == []
    xml = emit(ir.model_ir, platform_version="x", repository_version="y",
               certify=ir.certify)
    assert not [f for f in shape_check(xml) if f.kind in ("encoding", "unknown")]


def test_ir021_catches_it():
    assert "IR-021" in [f.rule for f in validate(_break_order(_s3()))]


def test_equal_positions_are_a_violation_not_a_tie():
    """xDM promises no order within a position. The single-record REST probe resolved
    the dependency and returned a populated token — a near-miss that made a per-record
    check look like proof. The batch job did not."""
    ir = _break_order(_s3())
    bad = order_violations(ir)
    assert bad and bad[0][1] == bad[0][2] == 1


def test_it_hands_back_the_right_positions_not_just_the_complaint():
    """Flagging a wrong order is useful; returning the right one makes it fixable."""
    ir = _break_order(_s3())
    want = execution_order(ir)
    assert want[("Party", "NormalizeName")] < want[("Party", "PhoneticName")]
    assert "suggested:" in render(ir)


def test_the_authored_scenarios_order_correctly():
    """`blocking_violations`, not `order_violations`: an IN-PLACE producer leaves the
    attribute populated with the publisher's value, so a consumer running first reads
    the RAW value rather than a null. The organization hub does that deliberately — its
    capture-the-inbound-address enricher runs first precisely so the normalizer at
    position 3 cannot rewrite what it was added to preserve."""
    from agent.ir.depends import blocking_violations
    for d in sorted((ROOT / "out").glob("s*/ir")):
        ir = IR.load(d / "model.yaml", d / "certify.yaml")
        assert not blocking_violations(ir), f"{d.parent.name}:\n{render(ir)}"
        assert not cycles(ir), d.parent.name


def test_a_mutual_dependency_is_reported_rather_than_ordered():
    """Two enrichers each reading what the other writes cannot be scheduled at all."""
    ir = _s3()
    ne = next(e for e in ir.certify.enrichers if e.name == "NormalizeName")
    ne.expressions[0].expression = "UPPER(TRIM(PhoneticNameToken))"
    assert cycles(ir)
    assert "IR-021" in [f.rule for f in validate(ir)]


def test_a_dups_manager_without_its_prerequisites_is_refused():
    """The designer's own dialog refuses to close without a Collection and a Form Tab.
    The compiler must not be MORE PERMISSIVE than the product — a generated one
    imports cleanly and renders an empty screen."""
    from agent.ir.schema import DupsManager
    ir = _s3()
    ir.app.dups_managers.append(DupsManager(entity="Party", name="Bare"))
    miss = missing_prerequisites(ir)
    assert {m.needs for m in miss} >= {"a collection", "a form tab"}
    assert "IR-022" in [f.rule for f in validate(ir) if f.severity == "error"]


def test_a_stewardship_action_needs_a_queue_to_act_on():
    from agent.ir.schema import Action, ActionSet
    ir = _s3()
    ir.app.action_sets.append(ActionSet(
        entity="Party", name="S",
        actions=[Action(kind="MergeOrSplit", name="Merge")]))
    assert any("duplicate manager" in m.needs for m in missing_prerequisites(ir))


def test_dependencies_follow_complex_members_not_just_bare_names():
    """Address.Zip5 is written and read by its dotted name; matching on the bare
    member would miss the dependency entirely."""
    ir = _s3()
    names = {d.attribute for d in enricher_dependencies(ir)}
    assert "NormalizedName" in names


# ------------------------------------------- in-place producers are not null producers
def _ir_with(enrichers):
    from agent.ir.schema import IR, CertifyIR, ModelIR
    return IR(
        model_ir=ModelIR(
            model={"name": "P", "target_technology": "postgresql"},
            complex_types=[{"name": "AddressType",
                            "members": [{"name": "AddrCity", "type": "String",
                                         "length": 120}]}],
            entities=[{"name": "Org", "type": "basic",
                       "attributes": [{"name": "Id", "type": "String", "length": 10,
                                       "pk": True, "mandatory": True}],
                       "complex_attributes": [
                           {"name": "InitialAddress", "type": "AddressType"},
                           {"name": "Address", "type": "AddressType"}]}]),
        certify=CertifyIR(enrichers=enrichers))


CAPTURE_THEN_NORMALIZE = [
    # The guide's ENR_CAPTURE_INITIAL_ADDRESS: runs FIRST, on purpose, so that the
    # inbound value is preserved before the normalizer standardizes it.
    {"entity": "Org", "name": "ENR_CAPTURE_INITIAL_ADDRESS", "scope": "PRE_CONSO",
     "position": 1, "condition": "InitialAddress.AddrCity IS NULL",
     "expressions": [{"attribute": "InitialAddress.AddrCity",
                      "expression": "Address.AddrCity"}]},
    {"entity": "Org", "name": "ENR_NORMALIZE_ADDRESS", "scope": "PRE_CONSO",
     "position": 3,
     "expressions": [{"attribute": "Address.AddrCity",
                      "expression": "UPPER(TRIM(Address.AddrCity))"}]},
]


def test_an_in_place_producer_is_flagged_but_never_blocks():
    """LESSONS §20 is about hashing a NULL. An enricher that rewrites an attribute IN
    PLACE leaves it populated, so a consumer running first reads the RAW value — which
    is exactly what a capture-the-evidence enricher is written to do."""
    from agent.ir import depends
    from agent.ir.validate import errors, validate

    ir = _ir_with(CAPTURE_THEN_NORMALIZE)
    viol = depends.order_violations(ir)
    assert len(viol) == 1 and viol[0][0].in_place is True
    assert depends.blocking_violations(ir) == []
    assert depends.cycles(ir) == []

    issues = [i for i in validate(ir) if i.rule == "IR-021"]
    assert [i.severity for i in issues] == ["warning"]
    assert "IR-021" not in {i.rule for i in errors(validate(ir))}
    assert "IN-PLACE" in depends.render(ir)


def test_a_derived_producer_out_of_order_still_blocks():
    """The regression guard: narrowing IR-021 must not blunt the case it exists for."""
    from agent.ir import depends
    from agent.ir.validate import errors, validate

    ir = _ir_with([
        {"entity": "Org", "name": "ENR_PHONETIC", "scope": "PRE_CONSO", "position": 1,
         "expressions": [{"attribute": "Address.AddrCity",
                          "expression": "METAPHONE(InitialAddress.AddrCity, 8)"}]},
        {"entity": "Org", "name": "ENR_DERIVE", "scope": "PRE_CONSO", "position": 2,
         "expressions": [{"attribute": "InitialAddress.AddrCity",
                          "expression": "UPPER(Id)"}]},
    ])
    viol = depends.order_violations(ir)
    assert len(viol) == 1 and viol[0][0].in_place is False
    assert len(depends.blocking_violations(ir)) == 1
    assert "IR-021" in {i.rule for i in errors(validate(ir))}


def test_reordering_clears_the_in_place_warning_too():
    """It is a report, not a permanent exemption: put the capture after the normalizer
    and the warning goes away — along with the evidence it was protecting."""
    from agent.ir.validate import validate

    swapped = [dict(CAPTURE_THEN_NORMALIZE[0], position=5),
               dict(CAPTURE_THEN_NORMALIZE[1], position=3)]
    assert [i for i in validate(_ir_with(swapped)) if i.rule == "IR-021"] == []
