"""Conformance against the shape the PRODUCT writes. Step 3 of the block design.

Fourteen of the twenty defects on the road to a running model were SHAPE defects — an
element missing, misplaced, or encoded the wrong way. None was visible offline, because
emit and extract agreed with each other (LESSONS §2). All fourteen are decidable from
the corpus: 117 object types, 1205 (object, element) pairs, ZERO ambiguous encodings.

`blocks.yaml` is that measurement. These tests are what makes it load-bearing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.compile.blocks import check, library, render  # noqa: E402
from agent.compile.emit import emit  # noqa: E402
from agent.compile.extract import extract  # noqa: E402
from agent.compile.extract_app import extract_app  # noqa: E402
from agent.compile.extract_certify import extract_certify  # noqa: E402
from agent.ir.schema import IR  # noqa: E402

#: Retired. It was 45 — model-core objects omitting description/documentation, which
#: import and run but do not match what the product writes. `blocks.complete()` now
#: fills every `always` element in from the library as a final emit pass, so the debt
#: is ZERO and the emitters no longer have to know about fields they never set.
#:
#: The pin stays at 0 rather than being deleted: a regression here is silent, and this
#: is the class that made the survivorship import refuse (LESSONS §19).
KNOWN_MISSING = 0


def _emit_harvest() -> str:
    src = ROOT / "harvest" / "PartyHubProbe.applayer.xml"
    # `harvest/` is evidence built in the designer, not a fixture, and the public
    # export does not ship it. Same idiom as the skips further down this file.
    if not src.exists():
        pytest.skip("harvest/PartyHubProbe.applayer.xml not present")
    m, _ = extract(src)
    return emit(m, platform_version="x", repository_version="y",
                certify=extract_certify(src), app=extract_app(src))


def test_the_library_measured_a_deterministic_grammar():
    """The licence for the whole approach: if encoding varied by context, a lookup
    table would be unsound and every emitter would need to know its own shape."""
    lib = library()
    assert len(lib) >= 100
    ambiguous = [(o, t) for o, b in lib.items()
                 for t, e in b["elements"].items() if e == "AMBIGUOUS"]
    assert not ambiguous, f"encoding is not deterministic for {ambiguous}"


#: Exports built in the designer from nothing. Everything in `harvest/` used to count
#: as this; `PartyHubProbe.*` does not, because its model core is s3 imported and then
#: extended by hand — see `harvest_blocks.COMPILER_DERIVED`.
PRODUCT_AUTHORED = ["samples/corpus-a-org-mdm-0.1.xml",
                    "samples/gs-customerb2c-2025.1.0.xml",
                    "samples/gs-productretail-2025.1.0.xml",
                    "live/PartyRoleModels.xml",
                    "harvest/CustomerB2CDemo.workflow.xml"]


@pytest.mark.parametrize("rel", PRODUCT_AUTHORED)
def test_a_real_export_conforms_to_the_library_harvested_from_it(rel):
    """Sanity, and the ratchet: if the product's own output failed this, the checker is
    wrong. Run over every product-authored export rather than one, because a check that
    only ever sees one witness is a check that agrees with one witness."""
    src = ROOT / rel
    if not src.exists():
        pytest.skip(f"{rel} not present")
    assert check(src.read_bytes()) == [], render(check(src.read_bytes()))


def test_the_hand_extended_harvest_is_evidence_about_spelling_not_about_positions():
    """`harvest/PartyHubProbe.applayer.xml` is scenario 3 imported and then extended in
    the designer. The product rewrote its SERIALIZATION on export — which is why it is
    still ground truth for element shapes — and handed our `posInEntity` values straight
    back. So it carries this compiler's own duplicate positions, and harvesting a
    positional invariant from it would have certified the defect the invariant exists
    to find.

    Pinned as a POSITIVE assertion rather than an exclusion: the day this file stops
    carrying our duplicates is the day it was rebuilt or re-exported, and that is worth
    noticing rather than silently passing."""
    src = ROOT / "harvest" / "PartyHubProbe.applayer.xml"
    if not src.exists():
        pytest.skip("no harvest present")
    found = check(src.read_bytes())
    assert {f.kind for f in found} == {"duplicate-position"}, render(found)
    assert {f.obj for f in found} == {"SemQLEnricher", "SemQLMatchRule"}


def test_the_position_invariant_is_measured_and_not_vacuous():
    """A scope for every position-bearing type the corpus contains, and enough grouping
    to have teeth on the two that were broken. `instances`/`groups` are recorded so a
    scope that groups nothing is visible as such rather than passing for a check."""
    from agent.compile.blocks import positions
    spec = positions()
    assert len(spec) >= 50, sorted(spec)
    # Only these need a ref; every other type is ordered by XML nesting. If this set
    # grows, the corpus grew a new flattened collection and that is worth reading.
    by_ref = {k: v["scope"] for k, v in spec.items() if v["scope"] != "__enclosing__"}
    assert by_ref == {"BrowseBusinessViewAction": "parentFolder",
                      "FolderAction": "parentFolder",
                      "FormContainer": "parentFormContainer",
                      "FormField": "parentFormContainer",
                      "FormStep": "parentCollectionStep"}, by_ref
    for tag in ("SemQLEnricher", "SemQLMatchRule"):
        assert spec[tag]["instances"] / spec[tag]["groups"] > 3, spec[tag]


def test_a_duplicate_position_is_a_finding_about_a_set():
    """The class the Application Builder found and every offline check missed:

        Duplicate Position: Position "0" is already used in the set of objects.

    Six of them on a model that imports, exports, deploys and runs a job. Constructed
    here rather than fixtured, because the point is that the document is otherwise
    perfectly well-formed — nothing is null, nothing is missing, nothing is invented."""
    from xml.etree import ElementTree as ET

    from agent.compile.blocks import duplicate_positions

    def enricher(name: str, pos: int) -> str:
        return (f"<SemQLEnricher><internalID val='{name}'/><name>{name}</name>"
                f"<posInEntity val='{pos}'/></SemQLEnricher>")

    def entity(*kids: str) -> str:
        return ("<Entity><internalID val='e'/><name>E</name><enrichers>"
                + "".join(kids) + "</enrichers></Entity>")

    ok = ET.fromstring(f"<m>{entity(enricher('A', 0), enricher('B', 7))}</m>")
    assert duplicate_positions(ok) == []

    bad = ET.fromstring(f"<m>{entity(enricher('A', 0), enricher('B', 0))}</m>")
    found = duplicate_positions(bad)
    assert [f.kind for f in found] == ["duplicate-position"]
    assert "A, B" in found[0].detail

    # Two entities, same position, DIFFERENT sets. The whole difficulty of the check is
    # here: "the set of objects" is not "everything with this tag".
    two = ET.fromstring("<m>" + entity(enricher("A", 0)) + entity(enricher("B", 0))
                        + "</m>")
    assert duplicate_positions(two) == []


def test_every_authored_scenario_positions_its_objects_uniquely():
    """The regression guard for the fix. s3 and s4 both shipped duplicates and both
    deployed; s4 ran a job and loaded goldens with them in place."""
    from agent.ir.schema import IR
    from agent.ir.validate import errors, validate
    for d in sorted((ROOT / "out").glob("s*/ir*")):
        if not (d / "model.yaml").exists():
            continue
        cert, app = d / "certify.yaml", d / "app.yaml"
        ir = IR.load(d / "model.yaml", cert if cert.exists() else None,
                     app if app.exists() else None)
        if errors(validate(ir)):
            continue                     # a scenario refused offline emits nothing
        xml = emit(ir.model_ir, platform_version="x", repository_version="y",
                   certify=ir.certify, app=ir.app)
        bad = [f for f in check(xml) if f.kind == "duplicate-position"]
        assert not bad, f"{d.parent.name}:\n" + render(bad)


def test_no_element_is_encoded_the_wrong_way():
    """The `queueName` class. `<queueName val="Default"/>` imports at 204 and stores
    null; the Execution Engine then shows `Q0.null` and refuses every load action.

    This check found five more the same day: Application.logoUrl, favIcon,
    avatarImageUrl, coverImageUrl and FolderAction.icon were all emitted as `val=`
    where the product writes text — an application with silently no branding.
    """
    bad = [f for f in check(_emit_harvest()) if f.kind == "encoding"]
    assert not bad, render(bad)


def test_no_element_is_invented():
    """`NEVER` was invented and survived every offline check (LESSONS §16). An element
    no export contains is the same shape of claim."""
    bad = [f for f in check(_emit_harvest()) if f.kind == "unknown"]
    assert not bad, render(bad)


def test_the_missing_element_debt_only_shrinks():
    n = len([f for f in check(_emit_harvest()) if f.kind == "missing"])
    assert n <= KNOWN_MISSING, (
        f"{n} missing-element findings, was {KNOWN_MISSING}. New shape debt:\n"
        + render(check(_emit_harvest())))
    assert n == KNOWN_MISSING, (
        f"{n} findings — better than the pinned {KNOWN_MISSING}. Lower the pin.")


def test_completion_never_touches_what_the_product_itself_wrote():
    """`complete()` fills gaps; it must not have an opinion about a real export. If it
    adds anything to one, either the library is wrong or the pass is overreaching."""
    from xml.etree import ElementTree as ET

    from agent.compile.blocks import complete
    for d in ("samples", "live", "harvest"):
        for f in sorted((ROOT / d).glob("*.xml")):
            root = ET.parse(f).getroot()
            assert complete(root) == 0, f"{f.name}: complete() added elements"


def test_an_authored_model_conforms_without_the_author_knowing_the_shape():
    """The point of the assembler. app.yaml says WHAT the screens are; nobody writing
    it should have to know that every FormField carries a documentationInterpreter."""
    from agent.ir.schema import IR
    d = ROOT / "out/s3-three-sources/ir"
    if not (d / "app.yaml").exists():
        pytest.skip("no authored app layer")
    ir = IR.load(d / "model.yaml", d / "certify.yaml", d / "app.yaml")
    xml = emit(ir.model_ir, platform_version="x", repository_version="y",
               certify=ir.certify, app=ir.app)
    # `empty-holder` is excluded here and pinned separately below. It is a real class of
    # shape debt — it is how the scenario-4 deploy died — but it is NOT always fatal,
    # and this model is the proof: s3 is deployed and RUNNING on the lab with
    # DupsManager.checkoutSearchConfigs empty, and its steward queue works. Evidence
    # from the live system outranks the corpus's silence about a shape it never built.
    hard = [f for f in check(xml) if f.kind != "empty-holder"]
    assert hard == [], render(hard)


def test_every_authored_scenario_is_shape_clean_where_it_counts():
    """The scenarios are the deliverable. They must not carry encoding or invented
    elements even though they still carry the model-core description debt."""
    for d in sorted((ROOT / "out").glob("s*/ir")):
        ir = IR.load(d / "model.yaml", d / "certify.yaml")
        xml = emit(ir.model_ir, platform_version="x", repository_version="y",
                   certify=ir.certify)
        bad = [f for f in check(xml) if f.kind in ("encoding", "unknown")]
        assert not bad, f"{d.parent.name}:\n{render(bad)}"


# ------------------------------------------- the ratchet, and the way out of a refusal
def test_the_library_is_not_stale():
    """THE RATCHET. `unknown` keeps its sharp meaning of "invented" only if every shape
    the product has ever written is already in the table.

    So the product's OWN exports must raise zero unknowns. If this fails, the library
    is behind the evidence and the fix is mechanical — re-harvest — with no judgement
    involved. That is what lets the floor rise every time a real export lands.
    """
    from agent.compile.blocks import stale_sources
    stale = stale_sources()
    assert not stale, (
        f"{len(stale)} shape(s) the product writes are missing from blocks.yaml:\n"
        + render(stale)
        + "\n\nRe-harvest: python -m agent.compile.harvest_blocks "
          "samples/*.xml live/*.xml harvest/*.xml > agent/compile/blocks.yaml")


def test_a_refusal_names_the_way_out():
    """A check that refuses without saying what to do next is an obstacle, not a guard
    — and the way out here is the D8 loop, which is the only thing that has ever
    actually worked: build it once in the product, export, re-harvest."""
    from agent.compile.blocks import Finding
    text = render([Finding("unknown", "X", "y", "no export contains this element")])
    assert "harvest_blocks" in text
    assert "model designer" in text
    assert "block_exceptions.yaml" in text
    # An encoding finding names the helper to use, because that is the actual fix.
    enc = render([Finding("encoding", "Form", "name", "emitted as val, product writes text")])
    assert "text()" in enc


def test_the_exception_hatch_requires_a_citation_not_a_flag():
    """The escape valve for "documented but never built" is a RECORDED DECISION with a
    citation, on disk. A severity toggle would be a chat log with worse ergonomics."""
    import yaml
    from agent.compile.blocks import EXCEPTIONS_YAML
    raw = yaml.safe_load(EXCEPTIONS_YAML.read_text()) or {}
    for e in raw.get("accepted", []):
        assert {"object", "element", "why", "see"} <= set(e), (
            f"exception {e} must name object, element, why and a docs/ citation")
        assert e["see"].startswith("docs/"), f"{e['see']} is not a docs/ citation"


def test_an_exception_actually_suppresses_that_one_finding(tmp_path, monkeypatch):
    """And nothing else — an exception is per (object, element), never a blanket."""
    import agent.compile.blocks as B
    f = tmp_path / "exc.yaml"
    f.write_text("accepted:\n  - object: LOVValue\n    element: posInParent\n"
                 "    why: test\n    see: docs/x.md\n")
    monkeypatch.setattr(B, "EXCEPTIONS_YAML", f)
    B.exceptions.cache_clear()
    try:
        xml = ('<root><LOVValue><posInParent val="1"/><invented val="1"/>'
               '</LOVValue></root>')
        kinds = {(x.obj, x.element) for x in B.check(xml) if x.kind == "unknown"}
        assert ("LOVValue", "posInParent") not in kinds
        assert ("LOVValue", "invented") in kinds
    finally:
        B.exceptions.cache_clear()


def test_every_generated_component_property_has_an_identity():
    """The 204 -> 500 regression, pinned.

    Filling component-property defaults was first done in `blocks.complete()`, a generic
    post-pass with no minting context. It produced ComponentProperty elements with NO
    internalID — objects with no identity — and the import went from 204 to
    "Unexpected Error" the moment they were added. Same defect as the very first import
    of the day (LESSONS §16), one layer down.

    The fill now lives in the emitter, which knows the path and can mint.
    """
    from xml.etree import ElementTree as ET

    from agent.ir.schema import IR
    d = ROOT / "out/s3-three-sources/ir"
    if not (d / "app.yaml").exists():
        pytest.skip("no authored app layer")
    ir = IR.load(d / "model.yaml", d / "certify.yaml", d / "app.yaml")
    root = ET.fromstring(emit(ir.model_ir, platform_version="x", repository_version="y",
                              certify=ir.certify, app=ir.app))
    cps = list(root.iter("ComponentProperty"))
    assert cps, "the app layer should emit component properties"
    orphans = [c for c in cps if c.find("internalID") is None]
    assert not orphans, f"{len(orphans)} ComponentProperty without an internalID"


def test_complete_never_creates_objects_only_elements():
    """`complete()` fills SLOTS. Creating child OBJECTS there is how the identity bug
    happened, because the post-pass cannot mint. If this ever needs to add an object,
    it belongs in the emitter instead."""
    import inspect

    from agent.compile import blocks
    src = inspect.getsource(blocks.complete)
    assert "ComponentProperty" not in src, (
        "complete() is creating objects again — objects need identities, and this "
        "function has no minting context")


#: Holders emitted empty that every product export populates. A RATCHET — may shrink,
#: never grow. Each is a place `complete()` filled the slot and no emitter minted the
#: object; the one that was FATAL, Reference.foreignAttribute, is fixed and therefore
#: absent from this list.
KNOWN_EMPTY_HOLDERS = {
    ("Model", "entities"),            # s1 is LOV-only. It DEPLOYED with this empty.
    ("Model", "modelPrivGrants"),     # s1 grants nothing and has nothing to grant on.
    ("DupsManager", "checkoutSearchConfigs"),   # s3 runs with this empty
}


def test_the_empty_holder_debt_only_shrinks():
    """The check that would have caught the scenario-4 deploy failure offline.

    An empty holder passes every element-SET check, because the element is present. The
    deployer then dereferences into it. Reference.foreignAttribute empty was a 204
    import and an "Unexpected Error" deploy — LESSONS §19 one nesting level down.
    """
    from agent.ir.schema import IR
    found = set()
    for d in sorted((ROOT / "out").glob("s*/ir")):
        c, a = d / "certify.yaml", d / "app.yaml"
        ir = IR.load(d / "model.yaml", c if c.exists() else None,
                     a if a.exists() else None)
        xml = emit(ir.model_ir, platform_version="x", repository_version="y",
                   certify=ir.certify, app=ir.app)
        found |= {(f.obj, f.element) for f in check(xml) if f.kind == "empty-holder"}
    new = found - KNOWN_EMPTY_HOLDERS
    assert not new, (
        f"{len(new)} holder(s) newly emitted empty: {sorted(new)}\n"
        "complete() can fill the slot but cannot mint the object — populate it in the "
        "emitter, as _reference does for foreignAttribute.")
    # A ratchet that only checks one direction is a high-water mark, not a ratchet: the
    # pin silently keeps naming holders that were fixed, and the next real regression
    # hides inside a stale allowance.
    gone = KNOWN_EMPTY_HOLDERS - found
    assert not gone, (
        f"{sorted(gone)} no longer emit empty — delete them from KNOWN_EMPTY_HOLDERS "
        "so the pin keeps meaning what it says.")


def test_the_fatal_one_is_actually_fixed():
    """Reference.foreignAttribute is the FK column. Pinned by name, because this is the
    one whose absence was measured against a live deploy rather than a corpus."""
    from agent.ir.schema import IR
    d = ROOT / "out/s4-multi-source-ids/ir"
    ir = IR.load(d / "model.yaml", d / "certify.yaml")
    root = ET.fromstring(emit(ir.model_ir, platform_version="x",
                              repository_version="y", certify=ir.certify))
    refs = list(root.iter("Reference"))
    assert refs, "scenario 4 is the reference scenario"
    for r in refs:
        fa = r.findall("foreignAttribute/ForeignAttribute")
        assert len(fa) == 1, f"{r.findtext('name')}: {len(fa)} ForeignAttribute, want 1"
        assert fa[0].find("internalID") is not None, "the FK column needs an identity"
        assert fa[0].find("entity").get("ref"), "the FK must name the entity holding it"


# --------------------------------------------------- never-null REF slots (2026-08-06)
def test_ref_slots_the_product_never_leaves_null_are_now_measured():
    """The class that was invisible to every offline check until it broke a deploy.

    `never_null` needs a modal VALUE to record and a ref's value is a per-model UUID, so
    the harvest excluded refs entirely — the exclusion was an argument about `complete()`
    being unable to fill them, silently reused as an argument that they need not be
    checked. Three such slots on the s3 stepper were emitted null: the document passed
    validate, advise, depends and blocks.check, imported at 204, re-exported as a
    well-formed model, and the deploy died with a bare "Unexpected Error".
    """
    lib = library()
    assert lib["Stepper"]["never_null_refs"] == ["rootCollectionStep"]
    assert lib["FormStep"]["never_null_refs"] == ["formTab", "parentCollectionStep"]
    assert lib["CollectionStep"]["never_null_refs"] == ["collectionView"]


def test_a_null_never_null_ref_is_a_finding_with_its_own_remedy():
    """Separate from `null-not-allowed` because the REMEDY differs: there is no value to
    fill in, so the emitter has to mint and wire something."""
    from xml.etree import ElementTree as ET
    xml = ('<metaDataExport><Stepper><name>X</name>'
           '<rootCollectionStep null="true"/></Stepper></metaDataExport>')
    findings = check(ET.fromstring(xml), require_always=False)
    hit = [f for f in findings if f.kind == "null-ref"]
    assert len(hit) == 1, render(findings)
    assert hit[0].element == "rootCollectionStep"
    assert "mint" in hit[0].remedy.lower()


def test_the_product_own_exports_raise_no_null_ref_findings():
    """The ratchet, extended. If a real export tripped this the library would be wrong,
    not the export — the same argument that keeps `unknown` meaning "invented".

    `live/PartyHubProbe.xml` is deliberately NOT harvested from and is skipped here: it
    is the product's re-export of THIS COMPILER's output, so treating it as evidence
    about what the product writes would teach the library our own mistakes (LESSONS §2).
    """
    for d in ("samples", "harvest"):
        for f in sorted((ROOT / d).glob("*.xml")):
            bad = [x for x in check(f.read_bytes()) if x.kind == "null-ref"]
            assert bad == [], f"{f.name}: {render(bad)}"


# ------------------------------------- ComponentProperty dataType (2026-08-08, §56)
def test_the_datatype_table_is_measured_and_unambiguous():
    """The licence for the lookup, same shape as the encoding table's: if a property
    name carried different dataTypes in different contexts, the harvest would refuse
    (`harvest_blocks.ConflictingEvidence`) rather than pick a winner. 46 names over
    8536 product-authored instances, zero conflicts."""
    from agent.compile.blocks import component_property_datatypes
    t = component_property_datatypes()
    assert len(t) >= 40, sorted(t)
    assert t["isMultiline"]["dataType"] == "BOOLEAN"
    assert t["isLabelVisible"]["dataType"] == "BOOLEAN"
    # The WIRE spelling. The Validation view's message says NUMBER, which is the
    # REGISTRY's vocabulary — every export writes DECIMAL (§51.2, again).
    assert t["multilineMinLines"]["dataType"] == "DECIMAL"
    assert t["multilineMaxLines"]["dataType"] == "DECIMAL"
    assert t["authoringMode"]["dataType"] == "STRING"


def test_a_wrong_component_property_datatype_is_a_finding():
    """The 60-error class from the s4 Validation run: dataType STRING on a property
    the registry types BOOLEAN. Imports at 204, deploys, runs a job — only the
    Application Builder's Validation view names it, so it must be an OFFLINE finding."""
    from agent.compile.blocks import component_datatypes
    wrong = ET.fromstring('<X><ComponentProperty><name>isMultiline</name>'
                          '<dataType val="STRING"/></ComponentProperty></X>')
    found = component_datatypes(wrong)
    assert [f.kind for f in found] == ["datatype"], render(found)
    assert "BOOLEAN" in found[0].detail
    assert "look it up" in found[0].remedy
    right = ET.fromstring('<X><ComponentProperty><name>isMultiline</name>'
                          '<dataType val="BOOLEAN"/></ComponentProperty></X>')
    assert component_datatypes(right) == []


def test_an_unharvested_property_name_is_a_gap_not_a_finding():
    """A floor, not a ceiling: a name the corpus has never seen is a gap in evidence,
    and refusing it would block every component the samples never used."""
    from agent.compile.blocks import component_datatypes
    root = ET.fromstring('<X><ComponentProperty><name>neverHarvestedProp</name>'
                         '<dataType val="STRING"/></ComponentProperty></X>')
    assert component_datatypes(root) == []


def test_the_sixty_error_class_is_caught_offline_and_fixed_in_the_emitter():
    """End to end: the fixed emitter writes the harvested dataType, and the OLD
    emitter's output (every dataType STRING) is reconstructed and fails the check —
    proving the finding would have caught the defect before the operator's
    Validation click did."""
    from agent.ir.schema import IR
    d = ROOT / "out/s4-multi-source-ids/ir"
    if not (d / "app.yaml").exists():
        pytest.skip("no authored app layer")
    ir = IR.load(d / "model.yaml", d / "certify.yaml", d / "app.yaml")
    xml = emit(ir.model_ir, platform_version="x", repository_version="y",
               certify=ir.certify, app=ir.app)
    assert [f for f in check(xml) if f.kind == "datatype"] == [], \
        render([f for f in check(xml) if f.kind == "datatype"])
    assert '<dataType val="BOOLEAN" />' in xml, \
        "the fix is not in the output; this regression test is checking nothing"
    old = xml.replace('<dataType val="BOOLEAN" />', '<dataType val="STRING" />') \
             .replace('<dataType val="DECIMAL" />', '<dataType val="STRING" />')
    found = [f for f in check(old) if f.kind == "datatype"]
    assert found, "the reconstructed old output should fail"
    named = {f.element for f in found}
    assert "isMultiline" in named and "multilineMinLines" in named, named
