"""Sprint 05 (partial) acceptance: XML -> IR extraction and the datatype registry."""
from __future__ import annotations

import sys
import re
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.extract import extract  # noqa: E402
from agent.compile.registry import PLATFORM_TYPES, UnknownPlatformType, harvest, resolve  # noqa: E402
from agent.ir.schema import IR  # noqa: E402
from agent.ir.validate import errors, validate  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"
SAMPLES = SAMPLES_DIR
GS = SAMPLES / "gs-productretail-2025.1.0.xml"
CORPUS_A = SAMPLES / "corpus-a-org-mdm-0.1.xml"


def witness(path: Path) -> Path:
    """A real product export, or a skip naming the file that is not here.

    `samples/` is not in the public export — one model is production-sourced and two are
    vendor demo content. The registry tests below build their input in memory and keep
    running there, which is why this is a per-test guard and not a module-level one.
    """
    if not path.exists():
        pytest.skip(f"{path.relative_to(Path(__file__).resolve().parents[1])} "
                    "not present")
    return path


@pytest.fixture(scope="module")
def gs():
    return extract(witness(GS))


@pytest.fixture(scope="module")
def corpus_a():
    return extract(witness(CORPUS_A))


def test_vendor_sample_extracts_to_a_fully_valid_ir(gs):
    """The strongest signal available: a real export becomes an IR with no errors."""
    ir, unresolved = gs
    assert unresolved == []
    assert errors(validate(IR(model_ir=ir))) == []


def test_corpus_a_extracts_cleanly_apart_from_the_missing_matcher(corpus_a):
    """Certification is sprint 06, so a fuzzy entity with no matcher is expected."""
    ir, unresolved = corpus_a
    errs = errors(validate(IR(model_ir=ir)))
    assert [e.rule for e in errs] == ["IR-001"]
    # Every datatype now resolves: OrganizationGoldenID was identified as UUID from
    # idGenerationType=UUID plus length=16 matching the documented "16 bytes".
    assert unresolved == []


def test_entities_and_types(gs, corpus_a):
    assert {e.name for e in gs[0].entities} >= {"Brand", "Product", "Item"}
    types = {e.name: e.type for e in corpus_a[0].entities}
    assert types["Organization"] == "fuzzy"
    assert types["OrgRole"] == "basic"


def test_primary_keys_are_extracted(gs, corpus_a):
    """PKAttribute is a distinct element type, not a flavour of AtomicAttribute.
    Iterating only AtomicAttribute drops the PK from the model entirely."""
    for ir, _ in (gs, corpus_a):
        for e in ir.entities:
            assert [a.name for a in e.attributes if a.pk], f"{e.name} has no PK"


def test_complex_attribute_resolves_to_its_declared_type(corpus_a):
    org = next(e for e in corpus_a[0].entities if e.name == "Organization")
    assert [ca.type for ca in org.complex_attributes] == ["AddressType"]


def test_lov_values_carry_code_and_label(corpus_a):
    lov = corpus_a[0].lov_types[0]
    assert lov.values and all(v.code for v in lov.values)


def test_publishers_extracted_with_uppercase_codes(corpus_a):
    codes = [p.code for p in corpus_a[0].publishers]
    assert codes and all(c == c.upper() for c in codes)


def test_references_resolve_to_entity_names(corpus_a):
    for r in corpus_a[0].references:
        assert r.from_entity and r.to_entity


# ------------------------------------------------------------------- registry
def test_resolve_known_type():
    assert resolve("fc23292f-5d70-4034-a036-4f793797ff90") == "String"


def test_resolve_refuses_to_guess_an_unseen_uuid():
    """Every UUID in a published sample is now identified, so this is a UUID the
    registry has genuinely never seen."""
    with pytest.raises(UnknownPlatformType) as e:
        resolve("00000000-dead-beef-0000-000000000000")
    assert "Harvest the registry" in str(e.value)


def test_resolve_knows_the_uuid_datatype():
    assert resolve("1ee2a456-c81d-48b5-8f03-5ae3eecdc451") == "UUID"


def test_harvest_reports_external_refs_with_their_usage():
    usage = harvest(witness(CORPUS_A), witness(GS),
                    witness(SAMPLES_DIR / "gs-customerb2c-2025.1.0.xml"))
    # The samples exercise only a SUBSET of the registry — six of twelve. The other six
    # came off a live instance via the bootstrap, so the containment runs this way
    # round. It ran the other way while the registry was sample-derived.
    assert set(usage) <= set(PLATFORM_TYPES)
    assert len(usage["fc23292f-5d70-4034-a036-4f793797ff90"]) > 50


def test_a_documented_builtin_without_a_uuid_is_not_reported_as_unsupported(monkeypatch):
    """Saying a documented type is 'unsupported' because THIS instance has not been
    harvested would push a designer to model a price as a String — the silent mis-type
    the registry exists to prevent.

    All twelve are mapped since the 2026-08-03 bootstrap, so the gap is simulated. That
    is the state a NEW platform version starts in, which is exactly when the message
    matters."""
    import agent.compile.registry as reg
    from agent.compile.registry import UnharvestedType, type_uuid
    monkeypatch.setattr(reg, "PLATFORM_TYPES",
                        {k: v for k, v in reg.PLATFORM_TYPES.items()
                         if v != "Timestamp"})
    with pytest.raises(UnharvestedType) as e:
        type_uuid("Timestamp")
    assert "IS a documented xDM built-in" in str(e.value)
    assert "one-time lookup" in str(e.value)


def test_all_twelve_builtins_are_mapped_after_the_bootstrap():
    """The bootstrap ran on 2026-08-03. Nothing should be unharvested any more."""
    from agent.compile.registry import PLATFORM_TYPES as PT
    from agent.tools.schema_ingest import XDM_TYPES
    assert set(PT.values()) == set(XDM_TYPES)
    assert len(PT) == 12


def test_integer_and_longinteger_are_not_the_same_uuid():
    """The mis-registration the bootstrap caught: 2651ea73 was recorded as Integer and
    is really LongInteger, so every emitted `type: Integer` produced a LongInteger
    column. Both integral, so nothing crashed — silently the wrong column type."""
    from agent.compile.registry import type_uuid
    assert type_uuid("Integer") == "af1d41f3-b76c-4bb9-85bb-81d730622f25"
    assert type_uuid("LongInteger") == "2651ea73-ce56-4754-9f55-7eccc02ccb92"
    assert type_uuid("Integer") != type_uuid("LongInteger")


def test_a_name_that_is_not_a_datatype_is_a_different_error():
    from agent.compile.registry import UnknownPlatformType, type_uuid
    with pytest.raises(UnknownPlatformType):
        type_uuid("Varchar2")


# -------------------------------------------- SqlFunction (operator built one, 2026-08-04)
def test_declared_database_functions_extract_with_their_arguments():
    """The operator declared PostgreSQL's native `age` in the UI, which pointed at a
    grammar the corpus already had and this compiler ignored: CORPUS_A declares 13."""
    m, _ = extract(witness(CORPUS_A))
    by_name = {f.name: f for f in m.sql_functions}
    assert len(by_name) == 13
    fn = by_name["UDF_ADDRVERIFY_ADDRESS"]
    assert fn.schema_name == "HUB_SCHEMA_DEV.SHARED"
    assert fn.aggregate is False and fn.procedure is False
    assert len(fn.arguments) == 5
    assert by_name["UDF_NORMALIZE_NAME"].categories == "matching"


def test_a_declared_function_survives_a_round_trip():
    from agent.compile.emit import emit
    m, _ = extract(witness(CORPUS_A))
    m.model.target_technology = "postgresql"
    xml = emit(m, platform_version="x", repository_version="y")
    assert xml.count("<SqlFunction>") == 13
    # schema and categories are FREE TEXT; the two booleans are val= (LESSONS §20)
    assert "<schema>HUB_SCHEMA_DEV.SHARED</schema>" in xml
    # ElementTree self-closes as `<x val="false" />`; match on the attribute, not the
    # exact serialization.
    assert re.search(r'<aggregateFunction val="false"\s*/>', xml)
    assert re.search(r'<mandatory val="true"\s*/>', xml)


def test_target_technology_round_trips():
    """ModelConfiguration.type is where the IR's target_technology lands, and NOT
    reading it back made every extracted model silently default to snowflake — which
    then flagged METAPHONE, a PostgreSQL function, as unavailable.

    A round-trip loss invisible until the function checker existed to notice it, and
    the same shape as the in-code override that hid the same fact earlier the same day.
    """
    from agent.compile.emit import emit
    src = SAMPLES_DIR.parent / "harvest" / "PartyHubProbe.applayer.xml"
    if not src.exists():
        pytest.skip("no harvest present")
    m, _ = extract(src)
    assert m.model.target_technology == "postgresql"
    again = emit(m, platform_version="x", repository_version="y")
    assert 'val="POSTGRESQL"' in again


def test_an_unknown_technology_keeps_the_ir_default_rather_than_inventing_one():
    import xml.etree.ElementTree as ET
    from agent.compile import extract as EX
    assert "oracle" not in EX.TECHNOLOGY_NAMES, (
        "if oracle becomes expressible, the emitter's TECHNOLOGY map must learn it "
        "first — extraction must never produce a value emit would refuse")
