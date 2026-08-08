"""Three model-core capabilities added for the organization-hub scenario (s6).

Each exists because the guide's own design could not be expressed without it, and each
is backed by a shape already in `blocks.yaml`:

    physical_name     `physicalColName` is text on AtomicAttribute and
                      DefinitionAttribute, and the real org-hub export HAND-SETS it
                      (ADDRESS_LINE1_STD, ZIP4, MELISSA_RESULT_CODE). Without the
                      override, derivation produces columns past the repository's
                      25-character limit.
    unique_keys       UniqueKey / KeyAttribute, measured once in harvest/. Atomic
                      attributes only — a KeyAttribute pointing at a ForeignAttribute
                      is an unmeasured REF TARGET and is refused, not guessed.
    historization     `historizeGolden` / `historizeMaster` were pinned true in the
                      emitter. Both spellings are attested; the choice is not
                      back-fillable, so it belongs in the IR.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.emit import EmitError, emit, physical  # noqa: E402
from agent.compile.extract import extract  # noqa: E402
from agent.ir.policy import MAX_PHYSICAL_NAME  # noqa: E402
from agent.ir.schema import IR, ModelIR  # noqa: E402
from agent.ir.validate import errors, validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
VER = {"platform_version": "2025.1.0", "repository_version": "2025.1.2"}
CORPUS_A = ROOT / "samples" / "corpus-a-org-mdm-0.1.xml"


def witness(path: Path) -> Path:
    """A real product export, or a skip naming the file that is not here.

    Four tests here measure against the one sample that carries hand-set physical
    names, historization and shortened reference names. `samples/` is not in the
    public export, so those four skip there; the thirteen that build a ModelIR in
    memory keep running.
    """
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not present")
    return path


def _model(**over) -> ModelIR:
    base = {
        "model": {"name": "PhysNameProbe", "target_technology": "postgresql"},
        "complex_types": [{
            "name": "AddressType",
            "members": [{"name": "AddrMelissaResultCode", "type": "String",
                         "length": 100}],
        }],
        "entities": [{
            "name": "Thing",
            "type": "basic",
            "attributes": [
                {"name": "ThingCode", "type": "String", "length": 30, "pk": True,
                 "mandatory": True},
                {"name": "AccountClassificationCode", "type": "String", "length": 50},
            ],
            "complex_attributes": [{"name": "Address", "type": "AddressType"}],
        }],
    }
    base.update(over)
    return ModelIR(**base)


def _find(xml: str, tag: str, name: str) -> ET.Element:
    for el in ET.fromstring(xml).iter(tag):
        n = el.find("name")
        if n is not None and n.text == name:
            return el
    raise AssertionError(f"no {tag} named {name}")


# --------------------------------------------------------------- physical_name
def test_derivation_alone_breaks_the_25_character_limit():
    """The rule has to be able to FAIL, and these are the names that make it fail —
    both transcribed straight from the guide, neither obviously too long."""
    assert len(physical("AccountClassificationCode")) > MAX_PHYSICAL_NAME
    # A member pays its complex attribute's 3-character prefix plus an underscore.
    assert len("ADD_" + physical("AddrMelissaResultCode")) > MAX_PHYSICAL_NAME


def test_ir_029_reports_both_the_plain_and_the_prefixed_overflow():
    issues = [i for i in validate(IR(model_ir=_model())) if i.rule == "IR-029"]
    where = {i.where for i in issues}
    assert where == {"Thing.AccountClassificationCode",
                     "Thing.Address.AddrMelissaResultCode"}
    assert all(i.severity == "error" for i in issues)
    # The message names the generated column, not the declared attribute — the whole
    # point is that the limit is invisible from the declaration.
    assert "ADD_ADDR_MELISSA_RESULT_CODE" in "".join(i.message for i in issues)


def test_physical_name_override_clears_it_and_reaches_the_xml():
    ir = _model()
    ir.entities[0].attributes[1].physical_name = "ACCOUNT_CLASS_CODE"
    ir.complex_types[0].members[0].physical_name = "MELISSA_RESULT_CODE"
    assert [i for i in validate(IR(model_ir=ir)) if i.rule == "IR-029"] == []

    xml = emit(ir, **VER)
    assert _find(xml, "AtomicAttribute", "AccountClassificationCode").find(
        "physicalColName").text == "ACCOUNT_CLASS_CODE"
    assert _find(xml, "DefinitionAttribute", "AddrMelissaResultCode").find(
        "physicalColName").text == "MELISSA_RESULT_CODE"


def test_extract_preserves_a_hand_set_physical_name_and_drops_a_derived_one():
    """The gap IR-029 exposed: the extractor ignored `physicalColName`, so a model the
    product wrote with short columns came back out with long ones — and the round trip
    agreed with itself because both passes ignored the same element."""
    ir, _ = extract(witness(CORPUS_A))
    members = {m.name: m for m in
               next(t for t in ir.complex_types if t.name == "AddressType").members}
    assert members["AddrAddrVerifyResultCode"].physical_name == "MELISSA_RESULT_CODE"
    assert members["AddrStreet"].physical_name == "ADDRESS_LINE1_STD"
    # A name the product spells exactly as derivation would is NOT pinned — otherwise
    # every extracted IR carries redundant overrides that hide the real ones.
    org = next(e for e in ir.entities if e.name == "Organization")
    derived = [a for a in org.attributes
               if a.physical_name is None and physical(a.name) == physical(a.name)]
    assert derived, "expected at least one attribute left to derivation"


def test_the_corpus_a_export_now_passes_ir_029():
    """It did not before the extractor learned `physicalColName`, and that failure was
    the evidence the rule was measuring something real rather than restating itself."""
    ir, _ = extract(witness(CORPUS_A))
    assert [i.where for i in validate(IR(model_ir=ir)) if i.rule == "IR-029"] == []


def test_reference_physical_names_are_length_checked_and_overridable():
    """The product TRUNCATES these rather than refusing — `ORGANIZATIONS_ORGANIZATIO`
    and `PARENT_ORGANIZATION_GOLDE` are both exactly 25 in the real org-hub export. A
    truncated `toRolePhysicalName` is worse than a refusal, because it silently renames
    the F_/FP_/FS_ columns every publisher's file has to carry."""
    base = {
        "model": {"name": "RefProbe", "target_technology": "postgresql"},
        "entities": [
            {"name": "Organization", "type": "basic",
             "attributes": [{"name": "Id", "type": "String", "length": 10,
                             "pk": True, "mandatory": True}]},
            {"name": "OrgHierarchy", "type": "basic",
             "attributes": [{"name": "Id", "type": "String", "length": 10,
                             "pk": True, "mandatory": True}]},
        ],
        "references": [{"name": "OrgCustomHierarchiesParentOrganization",
                        "from_entity": "OrgHierarchy", "to_entity": "Organization",
                        "from_role": "OrgCustomHierarchyChildren",
                        "to_role": "ParentOrganizationGoldenId"}],
    }
    issues = [i for i in validate(IR(model_ir=ModelIR(**base))) if i.rule == "IR-029"]
    assert {i.message.split()[0] for i in issues} == {"physical_name",
                                                      "to_role_physical"}

    base["references"][0]["physical_name"] = "ORG_CUST_HIER_PARENT_ORG"
    base["references"][0]["to_role_physical"] = "PARENT_ORG"
    ir = ModelIR(**base)
    assert [i for i in validate(IR(model_ir=ir)) if i.rule == "IR-029"] == []
    ref = ET.fromstring(emit(ir, **VER)).iter("Reference").__next__()
    assert ref.find("physicalName").text == "ORG_CUST_HIER_PARENT_ORG"
    assert ref.find("toRolePhysicalName").text == "PARENT_ORG"


def test_extract_preserves_hand_shortened_reference_physical_names():
    ir, _ = extract(witness(CORPUS_A))
    by_name = {r.name: r for r in ir.references}
    r = by_name["OrgCustomHierarchiesParentOrganization"]
    assert r.physical_name == "ORG_CUST_HIER_PARENT_ORG"
    assert r.to_role_physical == "PARENT_ORG_GOLDEN_ID"


# ----------------------------------------------------------------- unique_keys
def _keyed(attributes: list[str], **entity_over) -> ModelIR:
    ent = {
        "name": "Membership",
        "type": "basic",
        "attributes": [
            {"name": "MembershipId", "type": "String", "length": 30, "pk": True,
             "mandatory": True},
            {"name": "SourceCode", "type": "String", "length": 30},
        ],
        "unique_keys": [{"name": "U_MEMBERSHIP", "attributes": attributes}],
    }
    ent.update(entity_over)
    return ModelIR(model={"name": "KeyProbe", "target_technology": "postgresql"},
                   entities=[ent])


def test_unique_key_emits_the_measured_shape():
    xml = emit(_keyed(["MembershipId", "SourceCode"]), **VER)
    key = _find(xml, "UniqueKey", "U_MEMBERSHIP")
    # Encodings, straight off the one observed instance: name/label are element text,
    # validationScope is a `val` enum, description and validationLabel explicit nulls.
    assert key.find("label").text == "U_MEMBERSHIP"
    assert key.find("validationScope").get("val") == "POST_CONSO"
    assert key.find("description").get("null") == "true"
    assert key.find("validationLabel").get("null") == "true"

    members = key.find("keyAttributes").findall("KeyAttribute")
    assert [m.find("posInKey").get("val") for m in members] == ["1", "2"]
    # Every KeyAttribute carries a real ref; `abstractAttribute` is never null in any
    # observed instance, and a null ref slot is the shape that deploys to nothing.
    assert all(m.find("abstractAttribute").get("ref") for m in members)
    assert len({m.find("abstractAttribute").get("ref") for m in members}) == 2


def test_a_unique_key_survives_emit_then_extract():
    """An emitter without its extractor is a one-way door: the construct imports, and
    the next round trip through this compiler quietly drops it."""
    xml = emit(_keyed(["MembershipId", "SourceCode"]), **VER)
    tmp = Path(__file__).parent / "_uk_roundtrip.xml"
    try:
        tmp.write_text(xml)
        ir, _ = extract(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    keys = ir.entities[0].unique_keys
    assert len(keys) == 1
    assert keys[0].name == "U_MEMBERSHIP"
    assert keys[0].validation_scope == "POST_CONSO"
    # ORDER MATTERS — a composite key whose members come back transposed is a
    # different constraint, so posInKey is read rather than document order trusted.
    assert keys[0].attributes == ["MembershipId", "SourceCode"]


def test_unique_key_over_a_reference_role_is_refused_with_the_harvest_step():
    """MEASURED: 3 of 3 KeyAttributes point at an AtomicAttribute. The element shape
    would accept a ForeignAttribute ref happily — `blocks.check` cannot see what a UUID
    resolves to — which is exactly why this is refused rather than emitted."""
    ir = ModelIR(
        model={"name": "KeyProbe", "target_technology": "postgresql"},
        entities=[
            {"name": "Parent", "type": "basic",
             "attributes": [{"name": "ParentId", "type": "String", "length": 30,
                             "pk": True, "mandatory": True}]},
            {"name": "Membership", "type": "basic",
             "attributes": [{"name": "MembershipId", "type": "String", "length": 30,
                             "pk": True, "mandatory": True}],
             "unique_keys": [{"name": "U_MEMBERSHIP",
                              "attributes": ["MembershipId", "Parent"]}]},
        ],
        references=[{"name": "MembershipsParent", "from_entity": "Membership",
                     "to_entity": "Parent", "from_role": "Memberships",
                     "to_role": "Parent"}],
    )
    with pytest.raises(EmitError) as exc:
        emit(ir, **VER)
    assert "REFERENCE ROLE" in str(exc.value)
    assert "harvest" in str(exc.value)


def test_unique_key_naming_nothing_is_refused():
    """`keyAttributes` is `never_empty` in the block library, so an empty key is the
    empty-holder shape that imports at 204 and dies in the deployer."""
    with pytest.raises(EmitError, match="names no attributes"):
        emit(_keyed([]), **VER)


def test_an_entity_with_no_unique_keys_is_unchanged_apart_from_the_completed_slot():
    """`uniqueKeys` is in Entity's `always` slots, so `complete()` writes the empty
    holder whether or not anything populated it. Emitting nothing must not double it."""
    xml = emit(ModelIR(model={"name": "P", "target_technology": "postgresql"},
                       entities=[{"name": "Thing", "type": "basic",
                                  "attributes": [{"name": "Id", "type": "String",
                                                  "length": 10, "pk": True,
                                                  "mandatory": True}]}]), **VER)
    entity = _find(xml, "Entity", "Thing")
    assert len(entity.findall("uniqueKeys")) == 1
    assert list(entity.find("uniqueKeys")) == []


# --------------------------------------------------------------- historization
def test_historization_is_stated_by_the_entity_not_pinned_by_the_emitter():
    ir = ModelIR(
        model={"name": "HistProbe", "target_technology": "postgresql"},
        entities=[
            {"name": "Golden", "type": "basic", "historize_master": False,
             "attributes": [{"name": "Id", "type": "String", "length": 10,
                             "pk": True, "mandatory": True}]},
            {"name": "Neither", "type": "basic", "historize_golden": False,
             "historize_master": False,
             "attributes": [{"name": "Id", "type": "String", "length": 10,
                             "pk": True, "mandatory": True}]},
        ])
    xml = emit(ir, **VER)
    golden = _find(xml, "Entity", "Golden")
    assert golden.find("historizeGolden").get("val") == "true"
    assert golden.find("historizeMaster").get("val") == "false"
    neither = _find(xml, "Entity", "Neither")
    assert neither.find("historizeGolden").get("val") == "false"
    assert neither.find("historizeMaster").get("val") == "false"


def test_a_basic_entity_emits_no_master_historization():
    """The emitter side of IR-034, pinned where it is visible — in the XML.

        Could not have Historize Master Records on Entity Opportunity because it is
        a Basic entity

    Scenario 4 shipped this on `Opportunity`, deployed it, ran a job on it and loaded
    four goldens through it. Only the Application Builder's Validation view objected
    (LESSONS §56.2)."""
    xml = emit(ModelIR(model={"name": "H", "target_technology": "postgresql"},
                       entities=[
                           {"name": "Ref", "type": "basic",
                            "attributes": [{"name": "Id", "type": "String",
                                            "length": 10, "pk": True,
                                            "mandatory": True}]},
                           {"name": "Hub", "type": "fuzzy",
                            "attributes": [{"name": "Id", "type": "String",
                                            "length": 10, "pk": True,
                                            "mandatory": True}]}]), **VER)
    assert _find(xml, "Entity", "Ref").find("historizeMaster").get("val") == "false"
    assert _find(xml, "Entity", "Hub").find("historizeMaster").get("val") == "true"


def _one(kind: str) -> ModelIR:
    return ModelIR(model={"name": "D", "target_technology": "postgresql"},
                   entities=[{"name": "Thing", "type": kind,
                              "attributes": [{"name": "Id", "type": "String",
                                              "length": 10, "pk": True,
                                              "mandatory": True}]}])


def test_historization_defaults_stay_on_so_nothing_silently_loses_history():
    """It is not back-fillable. Defaulting either to false would mean a model authored
    without thinking about it loses history it can never recover.

    Master history is the exception, and only where there are no masters: a BASIC
    entity has none, so there is nothing to lose and the product refuses the setting
    outright (IR-034). Measured false on 16 of 16 basic entities in the corpus."""
    assert _one("basic").entities[0].historize_golden is True
    assert _one("fuzzy").entities[0].historize_golden is True
    assert _one("fuzzy").entities[0].historize_master is True
    assert _one("id_matched").entities[0].historize_master is True
    assert _one("basic").entities[0].historize_master is False


def test_an_explicit_master_historization_on_a_basic_entity_is_refused_not_flipped():
    """The default follows the type; a STATED intention is not quietly overwritten.
    Saying it out loud and being told no is the difference between a compiler and a
    compiler that disagrees with you in silence."""
    from agent.ir.validate import validate

    ir = ModelIR(model={"name": "D", "target_technology": "postgresql"},
                 entities=[{"name": "Thing", "type": "basic",
                            "historize_master": True,
                            "attributes": [{"name": "Id", "type": "String",
                                            "length": 10, "pk": True,
                                            "mandatory": True}]}])
    assert ir.entities[0].historize_master is True
    from agent.ir.schema import IR
    issues = validate(IR(model_ir=ir))
    assert "IR-034" in [i.rule for i in issues]


def test_extract_reads_historization_off_the_export():
    ir, _ = extract(witness(CORPUS_A))
    by_name = {e.name: e for e in ir.entities}
    # Measured in the export: the fuzzy entity historizes both, the basic ones golden
    # only. A hardcoded emitter reproduced the first and silently changed the others.
    assert by_name["Organization"].historize_golden is True
    assert by_name["Organization"].historize_master is True
    assert by_name["OrgHierarchy"].historize_golden is True
    assert by_name["OrgHierarchy"].historize_master is False
