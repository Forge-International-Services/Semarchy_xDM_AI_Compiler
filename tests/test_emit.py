"""Sprint 05 acceptance: IR -> XML, and the round-trip that closes the sprint.

The headline test is `extract(emit(extract(sample))) == extract(sample)` on both
samples. That is the strongest fidelity check available at this scope: a full-file
XML diff would fail on constructs the model-core emitter does not own yet
(certification is sprint 06, the application layer sprint 07), so comparing at the
IR level asks exactly the right question — does emit invert extract over everything
the IR represents?

The XML-level checks below cover what an IR comparison cannot: structural validity,
determinism, and that the output does not depend on UUID values.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile import mint as mint_mod  # noqa: E402
from agent.compile.emit import EmitError, emit, physical  # noqa: E402
from agent.compile.extract import extract  # noqa: E402
from agent.compile.normalize import normalize  # noqa: E402
from agent.ir.schema import IR  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Models whose datatypes fully resolve, so they can compile end to end.
# All three now fully resolve: Decimal was identified from Price's precision=20
# scale=2, which was the last UUID appearing in any published sample.
SAMPLES = {"gs-productretail": ROOT / "samples" / "gs-productretail-2025.1.0.xml",
           "corpus-a": ROOT / "samples" / "corpus-a-org-mdm-0.1.xml",
           "gs-customerb2c": ROOT / "samples" / "gs-customerb2c-2025.1.0.xml"}
VER = {"platform_version": "2025.1.0", "repository_version": "2025.1.2"}


def sample(name: str) -> Path:
    """A real product export, or a skip naming the file that is not here.

    `samples/` holds two vendor demo models and one production-sourced; the public export ships
    without it. Guarded per test rather than per module because the datatype refusals
    and the physical-name rules below need no sample and must keep running. No
    assertion changed — in the full repository every test here runs.
    """
    p = SAMPLES[name]
    if not p.exists():
        pytest.skip(f"{p.relative_to(ROOT)} not present")
    return p


def compile_ir(ir):
    return emit(ir, **VER)


def reparse(xml: str, tmp_path: Path):
    p = tmp_path / "m.xml"
    p.write_text(xml)
    return extract(p)


# ------------------------------------------------------- the closing round-trip
@pytest.mark.parametrize("name", list(SAMPLES), ids=list(SAMPLES))
def test_emit_inverts_extract_on_both_samples(name, tmp_path):
    ir, _ = extract(sample(name))
    back, unresolved = reparse(compile_ir(ir), tmp_path)
    assert unresolved == []
    assert back.model_dump() == ir.model_dump()


def test_round_trip_of_the_hand_authored_example(tmp_path):
    ir = IR.load(ROOT / "agent/ir/examples/customer_model.yaml",
                 ROOT / "agent/ir/examples/customer_certify.yaml").model_ir
    back, _ = reparse(compile_ir(ir), tmp_path)
    # Two fields are DERIVED by the compiler, so a hand-authored IR that leaves them
    # unset round-trips to the value the compiler chose. Compared explicitly rather
    # than silently dropped:
    #   subject_name     has no entity-level representation in xDM at all; it compiles
    #                    into a display card
    #   physical_prefix  is derived to be unique within the entity (ADD, AD2, …), so
    #                    None on the way in becomes the chosen prefix on the way out
    drop = {"entities": {"__all__": {
        "subject_name": True,
        "complex_attributes": {"__all__": {"physical_prefix"}},
    }}}
    assert back.model_dump(exclude=drop) == ir.model_dump(exclude=drop)
    assert all(e.subject_name is None for e in back.entities)
    assert all(c.physical_prefix and len(c.physical_prefix) == 3
               for e in back.entities for c in e.complex_attributes)


# ------------------------------------------------------------------ determinism
def test_compiling_twice_is_byte_identical():
    ir, _ = extract(sample("corpus-a"))
    assert compile_ir(ir) == compile_ir(ir)


def test_audit_fields_are_pinned_not_wall_clock():
    """R7: wall-clock stamps would break determinism silently."""
    xml = compile_ir(extract(sample("gs-productretail"))[0])
    stamps = set(re.findall(r'<internalCreationDate val="([^"]+)"', xml))
    assert len(stamps) == 1


def test_renaming_one_attribute_changes_exactly_one_uuid():
    ir, _ = extract(sample("gs-productretail"))
    before = set(re.findall(r'<internalID val="([^"]+)"', compile_ir(ir)))
    ir.entities[0].attributes[-1].name += "Renamed"
    after = set(re.findall(r'<internalID val="([^"]+)"', compile_ir(ir)))
    assert len(before - after) == 1 and len(after - before) == 1


def test_normalized_form_does_not_depend_on_uuid_values(monkeypatch):
    """Structure must be independent of the minting namespace."""
    ir, _ = extract(sample("gs-productretail"))
    first = normalize(compile_ir(ir))
    monkeypatch.setattr(mint_mod, "NAMESPACE", mint_mod.uuid.UUID(int=12345))
    assert normalize(compile_ir(ir)) == first


# ------------------------------------------------------------ structural checks
@pytest.mark.parametrize("name", list(SAMPLES), ids=list(SAMPLES))
def test_output_is_well_formed_and_every_ref_resolves(name):
    from agent.compile.registry import PLATFORM_TYPES
    xml = compile_ir(extract(sample(name))[0])
    root = ET.fromstring(xml)                       # raises if not well-formed
    ids = {e.attrib["val"] for e in root.iter("internalID")}
    refs = {e.attrib["ref"] for e in root.iter() if "ref" in e.attrib}
    dangling = refs - ids - set(PLATFORM_TYPES)
    assert not dangling, f"dangling refs: {sorted(dangling)[:3]}"


@pytest.mark.parametrize("name", list(SAMPLES), ids=list(SAMPLES))
def test_internal_ids_are_unique(name):
    """With ONE documented exception: RootModel, Model and exportInfo/modelUUID all
    carry the SAME uuid. Verified against a live export — this is what the product
    does, not a collision. The test asserted blanket uniqueness and was wrong."""
    root = ET.fromstring(compile_ir(extract(sample(name))[0]))
    shared = root.find("RootModel/internalID").attrib["val"]
    assert root.find("Model/internalID").attrib["val"] == shared
    assert root.find("exportInfo").attrib["modelUUID"] == shared
    ids = [e.attrib["val"] for e in root.iter("internalID")]
    ids.remove(shared)                      # drop one of the documented pair
    assert len(ids) == len(set(ids))


def test_null_and_ref_elements_carry_no_text_body():
    """Authoring guide §3: these two shapes never have a body."""
    root = ET.fromstring(compile_ir(extract(sample("corpus-a"))[0]))
    for el in root.iter():
        if el.attrib.get("null") == "true" or "ref" in el.attrib:
            assert not (el.text or "").strip(), el.tag


def test_lovvalue_pairs_code_with_label_and_has_no_value_element():
    root = ET.fromstring(compile_ir(extract(sample("corpus-a"))[0]))
    lov = next(root.iter("LOVValue"))
    assert lov.find("code") is not None and lov.find("label") is not None
    assert lov.find("value") is None


def test_version_stamps_come_from_the_target():
    xml = compile_ir(extract(sample("gs-productretail"))[0])
    info = ET.fromstring(xml).find("exportInfo")
    assert info.attrib["platformVersion"] == "2025.1.0"
    assert info.attrib["repositoryVersion"] == "2025.1.2"


def test_emit_refuses_without_an_explicit_target_version():
    ir, _ = extract(sample("gs-productretail"))
    with pytest.raises(ValueError, match="read from the target"):
        emit(ir, platform_version="", repository_version="2025.1.2")


def test_emit_refuses_a_name_that_is_not_a_datatype():
    ir, _ = extract(sample("gs-productretail"))
    ir.entities[0].attributes[-1].type = "NotAType"
    with pytest.raises(EmitError, match="is not an xDM datatype"):
        compile_ir(ir)


def test_emit_distinguishes_a_documented_type_missing_its_uuid(monkeypatch):
    """Timestamp is supported by xDM; the message must say so, or a designer reads
    'unsupported' and models a date as a String.

    All twelve UUIDs are mapped since the 2026-08-03 bootstrap, so the gap is
    simulated — which is the state any NEW platform version starts in."""
    import agent.compile.registry as reg
    monkeypatch.setattr(reg, "PLATFORM_TYPES",
                        {k: v for k, v in reg.PLATFORM_TYPES.items()
                         if v != "Timestamp"})
    ir, _ = extract(sample("gs-productretail"))
    ir.entities[0].attributes[-1].type = "Timestamp"
    with pytest.raises(EmitError, match="IS a documented xDM built-in"):
        compile_ir(ir)


def test_every_builtin_now_compiles():
    """The bootstrap's payoff: no model is blocked on a datatype any more."""
    from agent.tools.schema_ingest import XDM_TYPES
    ir, _ = extract(sample("gs-productretail"))
    for t in sorted(XDM_TYPES):
        ir.entities[0].attributes[-1].type = t
        assert compile_ir(ir)


def test_physical_names_are_derived_from_logical_ones():
    assert physical("CustomerId") == "CUSTOMER_ID"
    assert physical("Email") == "EMAIL"


def test_pk_is_emitted_as_its_own_element_type():
    """PKAttribute is a distinct element. SubjectNameAttribute is NOT emitted at entity
    level — it belongs to a ComplexType's name composition, and an entity names its
    records through a display card instead."""
    ir = IR.load(ROOT / "agent/ir/examples/customer_model.yaml").model_ir
    root = ET.fromstring(compile_ir(ir))
    assert root.find(".//PKAttribute") is not None
    assert root.find(".//SubjectNameAttribute") is None


# --------------------------------------------- unknown datatypes must be loud
def test_unknown_datatype_is_not_silently_coerced_to_string(tmp_path, monkeypatch):
    """The bug gs-customerb2c originally exposed: extract defaulted an unknown type to
    String, so a Decimal price became a String — and the round-trip test could not see
    it, because extract produced String on BOTH passes and emit->extract compared
    equal. Round-trip fidelity is not correctness.

    Decimal is now identified, so the case is reproduced by hiding it again."""
    import agent.compile.registry as reg
    from agent.ir.schema import IR as _IR
    from agent.ir.validate import errors as _errors, validate as _validate
    monkeypatch.setattr(reg, "PLATFORM_TYPES",
                        {k: v for k, v in reg.PLATFORM_TYPES.items() if v != "Decimal"})
    ir, unresolved = extract(sample("gs-customerb2c"))
    price = next(a for e in ir.entities for a in e.attributes if a.name == "Price")
    assert price.type.startswith("UNRESOLVED:")
    assert len(unresolved) == 1 and "Price" in unresolved[0]
    assert any(i.rule == "IR-013" and "Price" in i.where
               for i in _errors(_validate(_IR(model_ir=ir))))


def test_customerb2c_is_otherwise_extracted_correctly():
    """Everything except the one unknown datatype resolves cleanly."""
    ir, _ = extract(sample("gs-customerb2c"))
    assert {e.name for e in ir.entities} == {
        "Person", "Product", "Nickname", "CommChanPref", "PersonProduct"}
    assert {e.name for e in ir.entities if e.type == "fuzzy"} == {"Person", "CommChanPref"}
    assert all([a.name for a in e.attributes if a.pk] for e in ir.entities)
    assert len(ir.publishers) == 3
