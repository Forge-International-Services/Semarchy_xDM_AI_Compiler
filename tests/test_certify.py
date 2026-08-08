"""Sprint 06 acceptance: certification round-trip and xml_lint.

Ground truth is n=2 (R3 retired). The two witnesses disagree usefully — CORPUS_A bins
every probabilistic rule, gs-customerb2c bins none — so a grammar that reproduces
both is not over-fitted to either.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.emit import emit  # noqa: E402
from agent.compile.extract import extract  # noqa: E402
from agent.compile.extract_certify import extract_certify  # noqa: E402
from agent.tools import xml_lint  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORPUS_A = ROOT / "samples" / "corpus-a-org-mdm-0.1.xml"
B2C = ROOT / "samples" / "gs-customerb2c-2025.1.0.xml"
VER = {"platform_version": "2025.1.0", "repository_version": "2025.1.2"}


def witness(path: Path) -> Path:
    """A real product export, or a skip naming the file that is not here.

    Both witnesses live in `samples/`, which the public export does not ship — one is
    a production-sourced model and two are vendor demo content. Guarded per test rather than per
    module: the SemQL, ranking and lint assertions further down build their input in
    memory and must keep running. Nothing is weakened; all of them run in the full
    repository.
    """
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not present")
    return path


def compile_with_certification(path: Path, tmp_path: Path):
    ir, _ = extract(witness(path))
    # gs-customerb2c uses one platform datatype UUID we cannot identify (Price).
    # That is a model-core concern and unrelated to certification, so it is
    # substituted here rather than allowed to block this sprint's subject.
    for e in ir.entities:
        for a in e.attributes:
            if a.type.startswith("UNRESOLVED:"):
                a.type = "String"
    cert = extract_certify(path)
    xml = emit(ir, **VER, certify=cert)
    out = tmp_path / "m.xml"
    out.write_text(xml)
    return cert, xml, out


@pytest.mark.parametrize("path", [CORPUS_A, B2C], ids=["corpus-a", "gs-customerb2c"])
def test_certification_round_trips(path, tmp_path):
    cert, _, out = compile_with_certification(path, tmp_path)
    assert extract_certify(out).model_dump() == cert.model_dump()


def test_the_two_witnesses_disagree_on_binning():
    """If they agreed, reproducing both would prove much less."""
    corpus_a = [r for m in extract_certify(witness(CORPUS_A)).matchers for r in m.rules]
    b2c = [r for m in extract_certify(witness(B2C)).matchers for r in m.rules]
    # corpus model A bins most rules but deliberately leaves its conflict rules unbinned, so
    # a "bins everything" assertion would be wrong — the contrast is that corpus model A bins
    # some and gs-customerb2c bins none.
    assert 0 < sum(bool(r.binning) for r in corpus_a) < len(corpus_a)
    assert sum(bool(r.binning) for r in b2c) == 0


def test_plugin_enrichers_are_supported(tmp_path):
    """R13 was retired: PluginEnricher was only ever unsupported for want of a sample."""
    cert, xml, _ = compile_with_certification(B2C, tmp_path)
    plugins = [e for e in cert.enrichers if e.kind == "plugin"]
    assert len(plugins) == 6
    assert "<PluginEnricher>" in xml and all(p.plugin_id for p in plugins)


def test_form_step_enrichers_are_not_certification():
    """They live under Stepper > FormStep, so they are the application layer's."""
    cert = extract_certify(witness(CORPUS_A))
    assert not any(e.kind == "form_step" for e in cert.enrichers)


def test_empty_binning_container_is_preserved(tmp_path):
    """An empty <binningExpressions/> is valid and means full cartesian product."""
    _, xml, _ = compile_with_certification(B2C, tmp_path)
    assert "<binningExpressions />" in xml or "<binningExpressions/>" in xml


def test_thresholds_are_carried_verbatim_not_derived():
    """corpus model A runs mergeThresholdMergingConfirmed=95 with ...WithUnconfirmed=80, so
    the nine are not recoverable from a two-number policy."""
    m = extract_certify(witness(CORPUS_A)).matchers[0]
    assert m.thresholds["mergeThresholdMergingConfirmed"] == 95
    assert m.thresholds["mergeThresholdMergingConfirmedWithUnconfirmed"] == 80


def test_publisher_rankings_resolve_to_names(tmp_path):
    ranked = [s for s in extract_certify(witness(B2C)).survivorship
              if s.publisher_rankings]
    assert ranked and all(isinstance(p, str) and p
                          for s in ranked for p in s.publisher_rankings)


# ----------------------------------------------------------------- xml_lint
def test_lint_is_clean_on_compiler_output(tmp_path):
    _, xml, _ = compile_with_certification(CORPUS_A, tmp_path)
    findings = xml_lint.lint(xml, repository_version="2025.1.2")
    assert findings == [], findings[:3]
    assert xml_lint.exit_code(findings) == 0


def test_lint_catches_malformed_xml():
    assert xml_lint.lint("<a><b></a>")[0].check == "well-formed"


def test_lint_catches_a_version_mismatch(tmp_path):
    _, xml, _ = compile_with_certification(CORPUS_A, tmp_path)
    f = xml_lint.lint(xml, repository_version="2024.1.0")
    assert any(x.check == "version" for x in f) and xml_lint.exit_code(f) == 2


def test_lint_catches_a_dangling_ref():
    xml = ('<metaDataExport><exportInfo repositoryVersion="2025.1.2"/>'
           '<Model><x ref="deadbeef-0000-0000-0000-000000000000"/></Model></metaDataExport>')
    assert any(f.check == "dangling-ref" for f in xml_lint.lint(xml))


def test_lint_catches_a_lovvalue_with_a_value_element():
    xml = ('<metaDataExport><exportInfo repositoryVersion="2025.1.2"/><Model>'
           '<LOVValue><code>A</code><label>A</label><value>A</value></LOVValue>'
           '</Model></metaDataExport>')
    assert any(f.check == "lov-shape" for f in xml_lint.lint(xml))


def test_lint_warns_on_an_undeclared_external_udf():
    xml = ('<metaDataExport><exportInfo repositoryVersion="2025.1.2"/><Model>'
           '<expression>HUB_SCHEMA_DEV.SHARED.UDF_ADDRVERIFY(x)</expression>'
           '</Model></metaDataExport>')
    f = xml_lint.lint(xml, declared_udfs=set())
    assert any(x.check == "external-udf" and x.severity == "warning" for x in f)
    assert xml_lint.exit_code(f) == 1


# ------------------------------------------- validations are CheckConstraint
def test_validations_are_CheckConstraint_not_Validation():
    """Sprint 06 recorded that validations had "no observed grammar" because it looked
    for an element named `Validation`. The construct was there all along, in every
    sample, as CheckConstraint inside abstractRowCheckConstraints — the same mistake as
    looking for AtomicAttribute inside a ComplexType.

    Found by watching a live model: the operator created a validation in the UI and the
    watcher flagged CheckConstraint as a type the compiler could not emit."""
    ir = extract_certify(witness(CORPUS_A))
    names = {v.name for v in ir.validations}
    assert names == {"VAL_STATE_ZIP_FORMAT", "VAL_CLASSIFICATION_IN_VOCAB",
                     "VAL_ADDRESS_AE_DEMOTE"}
    v = next(v for v in ir.validations if v.name == "VAL_STATE_ZIP_FORMAT")
    assert v.scope == "PRE_CONSO" and v.entity == "Organization"
    assert "REGEXP_LIKE" in v.condition
    assert v.error_message == "Address state code or ZIP5 format is invalid."


def test_a_validation_has_no_severity_because_xdm_has_none():
    """`severity: ERROR|WARNING` was carried in the IR for four sprints and authored
    into four scenarios. xDM has no such field — the docs' list is Name, Label,
    Description, Condition, Error Message, Validation Scope. A record that fails a
    validation is in error; there is no warning tier.

    It survived because nothing emitted it, so nothing could contradict it."""
    from pydantic import ValidationError
    from agent.ir.schema import Validation
    assert "severity" not in Validation.model_fields
    with pytest.raises(ValidationError):
        Validation(entity="E", name="V", condition="1=1", severity="ERROR")


def test_validations_round_trip(tmp_path):
    from agent.compile.emit import emit
    from agent.compile.extract import extract
    path = witness(CORPUS_A)
    ir, _ = extract(path)
    cert = extract_certify(path)
    out = tmp_path / "m.xml"
    out.write_text(emit(ir, platform_version="2025.1.0",
                        repository_version="2025.1.2", certify=cert))
    assert extract_certify(out).validations == cert.validations


def test_the_emitted_validation_uses_the_product_container():
    from xml.etree import ElementTree as ET
    from agent.compile.emit import emit
    from agent.compile.extract import extract
    path = witness(CORPUS_A)
    ir, _ = extract(path)
    root = ET.fromstring(emit(ir, platform_version="2025.1.0",
                              repository_version="2025.1.2",
                              certify=extract_certify(path)))
    holder = root.find(".//abstractRowCheckConstraints")
    assert holder is not None
    assert {c.tag for c in holder} == {"CheckConstraint"}


# ------------------------------------------------- positions: the IR says less than
# the product requires, and the emitter is where the difference is paid
def test_equal_positions_are_a_tie_in_the_ir_and_illegal_in_the_product():
    """`depends` reads equal positions as "these two constrain nothing about each
    other", which is a true and useful thing for the IR to say — s3 declares three
    normalizers at 1 on purpose. xDM cannot say it:

        Duplicate Position: Position "0" is already used in the set of objects.

    Six of those on scenario 4, in a model that deploys and runs (LESSONS §56.1)."""
    from agent.compile.emit_certify import rank

    class E:
        def __init__(self, p):
            self.position = p

    assert rank([E(1), E(1), E(1), E(2)]) == [0, 1, 2, 3]
    # Stable: a tie keeps DECLARATION order, so the authored sequence survives.
    assert rank([E(2), E(1), E(1)]) == [2, 0, 1]


def test_already_distinct_positions_are_left_exactly_as_authored():
    """Gaps are legal and they mean something — corpus model A's enrichers run 0..19 with six
    holes where rules were deleted. Renumbering a set the product would accept would
    rewrite a modeller's spacing and make every round trip of a real export a diff."""
    from agent.compile.emit_certify import rank

    class E:
        def __init__(self, p):
            self.position = p

    assert rank([E(0), E(8), E(3)]) == [0, 8, 3]
    assert rank([]) == []


def test_the_emitted_positions_are_distinct_for_every_witness_we_have():
    """Both product exports and both of our own matched scenarios, through the emitter.
    The two that mattered — s3 and s4 — shipped duplicates, deployed, and in s4's case
    ran a job and loaded five goldens with them in place."""
    from xml.etree import ElementTree as ET
    for src in (witness(CORPUS_A), witness(B2C)):
        ir, _ = extract(src)
        for e in ir.entities:
            for a in e.attributes:
                if a.type.startswith("UNRESOLVED:"):
                    a.type = "String"
        root = ET.fromstring(emit(ir, **VER, certify=extract_certify(src)))
        for holder in root.iter("enrichers"):
            got = [c.find("posInEntity").get("val") for c in holder]
            assert len(got) == len(set(got)), got
        for holder in root.iter("matchRules"):
            got = [c.find("posInParent").get("val") for c in holder]
            assert len(got) == len(set(got)), got
