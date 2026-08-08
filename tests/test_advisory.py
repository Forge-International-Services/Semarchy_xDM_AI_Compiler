"""Sprint 03: the automated half of the acceptance criteria."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.advisory import CITATION_COVERAGE_MIN, NARRATIVE, check  # noqa: E402
from agent.corpus import FETCHER, have  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "agent" / "ir" / "examples"

#: `check()` runs two criteria that read the mirrored documentation — do these cited
#: pages exist, and are enough claims cited — and GOOD_PROSE below cites real ones. The
#: export pack ships without the corpus, so `check()` reports INCOMPLETE there rather
#: than a verdict, and any test whose assertion depends on that verdict skips.
#:
#: Deliberately NOT applied to the tests below that read out/*/ir/*.yaml directly: the
#: scenario IR ships in the pack, so what those assert is checkable there and does.
requires_corpus = pytest.mark.skipif(
    not have(),
    reason=f"knowledge corpus absent (export pack) — restore it with `{FETCHER}`")

GOOD_PROSE = """# Intake

- Publishers identify the source system
  (docs/Design/data-certification/publishers.md § Overview)
- A code-and-label list under 1,000 entries belongs in a LOV
  (docs/Design/logical-model/list-of-values.md § Overview)
- Thresholds are a policy, not nine numbers [uncited — model judgement]
"""


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "scenario"
    (d / "ir").mkdir(parents=True)
    for n in ("01-intake.md", "02-certification.md", "03-model-plan.md", "04-app-plan.md"):
        (d / n).write_text(GOOD_PROSE if n == "01-intake.md" else "# section\n")
    # A real narrative names what it builds; without this the divergence check fires,
    # which is the behaviour test_an_ir_object_the_narrative_never_mentions_fails pins.
    from agent.advisory import unexplained_objects
    from agent.ir.schema import IR as _IR
    shutil.copy(EX / "customer_model.yaml", d / "ir" / "model.yaml")
    shutil.copy(EX / "customer_certify.yaml", d / "ir" / "certify.yaml")
    ir = _IR.load(d / "ir" / "model.yaml", d / "ir" / "certify.yaml")
    named = " ".join(unexplained_objects(ir, ""))
    (d / "04-app-plan.md").write_text(f"# section\n\nObjects built: {named}\n")
    return d


@requires_corpus
def test_a_complete_scenario_passes_every_automated_check(project):
    rep = check(project)
    assert rep.ok, rep.render()
    assert rep.fabricated == [] and rep.coverage >= CITATION_COVERAGE_MIN


def test_missing_narrative_is_reported(project):
    (project / "03-model-plan.md").unlink()
    assert "03-model-plan.md" in check(project).missing


def test_missing_ir_is_reported(project):
    (project / "ir" / "model.yaml").unlink()
    rep = check(project)
    assert "ir/model.yaml" in rep.missing and not rep.ok


@requires_corpus
def test_a_fabricated_citation_fails(project):
    """Zero tolerance: a fake citation reads as sourced, an uncited claim does not."""
    (project / "02-certification.md").write_text(
        "- see docs/Design/matching/invented-page.md § Nope\n")
    rep = check(project)
    assert rep.fabricated and not rep.ok


@requires_corpus
def test_an_invented_heading_in_a_real_file_fails(project):
    (project / "02-certification.md").write_text(
        "- see docs/Design/data-certification/publishers.md § Not A Real Heading\n")
    assert not check(project).ok


@requires_corpus
def test_low_citation_coverage_fails(project):
    (project / "02-certification.md").write_text(
        "\n".join(f"- bare assertion {i}" for i in range(20)))
    rep = check(project)
    assert rep.coverage < CITATION_COVERAGE_MIN and not rep.ok


def test_ir_errors_fail_the_scenario(project):
    """IR-001: a fuzzy entity with no matcher. Previously a reading task."""
    (project / "ir" / "certify.yaml").write_text("enrichers: []\nmatchers: []\n")
    rep = check(project)
    assert any(i.rule == "IR-001" for i in rep.ir_issues) and not rep.ok


@requires_corpus
def test_unbinned_rule_is_a_warning_not_a_failure(project):
    """IR-010 warns; it does not block, because an acknowledged justification is valid."""
    y = (project / "ir" / "certify.yaml").read_text().replace(
        '        binning: ["Address.Zip5"]\n', "        binning: []\n")
    (project / "ir" / "certify.yaml").write_text(y)
    rep = check(project)
    assert any(i.rule == "IR-010" for i in rep.ir_issues)
    assert rep.ok, "a warning must not fail the scenario"


def test_no_claims_at_all_is_not_full_coverage(project):
    """An empty phase should not score 100%."""
    for n in ("01-intake.md", "02-certification.md", "03-model-plan.md", "04-app-plan.md"):
        (project / n).write_text("# nothing here\n")
    assert check(project).coverage == 0.0


def test_report_names_what_a_human_still_has_to_decide(project):
    text = check(project).render()
    assert "reasoning" in text and "I would build from this" in text


# ------------------------------------------------- the three generated scenarios
#: A scenario is COMPILED once it has an `ir/`. A directory holding only intake and
#: ontology is a live piece of work — the requirements exist, the model does not yet —
#: and the narrative gate has nothing to check it against. Including it would make the
#: suite red for the entire time a scenario is being understood, which is exactly when
#: nobody should be encouraged to skip the thinking.
SCENARIOS = sorted(d for d in (ROOT / "out").glob("s*-*")
                   if (d / "ir").is_dir()) if (ROOT / "out").is_dir() else []

#: The subset whose NARRATIVE artefacts are also on disk. The public export ships the
#: scenario IR but not the engagement's working narrative, and `unexplained_objects`
#: measures the IR against that prose — with no prose every object reads unexplained,
#: which is a fact about the tree rather than about the design.
NARRATED = [d for d in SCENARIOS if all((d / n).is_file() for n in NARRATIVE)]


@pytest.mark.parametrize("d", SCENARIOS, ids=[p.name for p in SCENARIOS])
@requires_corpus
def test_generated_scenario_passes_every_automated_check(d):
    assert check(d).ok, check(d).render()


def test_scenario_1_models_reference_data_as_a_lov_not_an_entity():
    """The expectation the operator corrected: a country list is a LOV. Getting a
    Basic entity here is a fail, not a stylistic difference."""
    import yaml
    ir = yaml.safe_load((ROOT / "out/s1-country-reference/ir/model.yaml").read_text())
    assert ir["entities"] == []
    assert [l["name"] for l in ir["lov_types"]] == ["Country"]


def test_scenario_2_is_id_matched_with_a_single_pk():
    import yaml
    ir = yaml.safe_load((ROOT / "out/s2-two-crms/ir/model.yaml").read_text())
    e = ir["entities"][0]
    assert e["type"] == "id_matched"
    assert len([a for a in e["attributes"] if a.get("pk")]) == 1


def test_scenario_4_distinguishes_identity_from_carried_ids():
    """The operator-authored guard scenario. Carried foreign IDs are ATTRIBUTES, not
    identity, and they are what make deterministic rules possible on a fuzzy entity."""
    import yaml
    model = yaml.safe_load((ROOT / "out/s4-multi-source-ids/ir/model.yaml").read_text())
    cert = yaml.safe_load((ROOT / "out/s4-multi-source-ids/ir/certify.yaml").read_text())
    customer = next(e for e in model["entities"] if e["name"] == "Customer")
    assert customer["type"] == "fuzzy"
    carried = {a["name"] for a in customer["attributes"]} & {"SfdcKey", "ErpKey", "BillingKey"}
    assert carried == {"SfdcKey", "ErpKey", "BillingKey"}
    # None of them is the PK: a carried ID is never identity.
    assert not any(a.get("pk") for a in customer["attributes"] if a["name"] in carried)
    # Two deterministic rules built on carried keys.
    rules = cert["matchers"][0]["rules"]
    assert sum(1 for r in rules if r["score"] == 100) == 2


def test_scenario_4_reference_targets_a_fuzzy_entity():
    """Which reference columns SD_OPPORTUNITY must load is decided by the REFERENCED
    entity's type: fuzzy means FP_ + FS_, never F_."""
    import yaml
    model = yaml.safe_load((ROOT / "out/s4-multi-source-ids/ir/model.yaml").read_text())
    ref = next(r for r in model["references"] if r["name"] == "OpportunityCustomer")
    target = next(e for e in model["entities"] if e["name"] == ref["to_entity"])
    assert ref["from_entity"] == "Opportunity" and target["type"] == "fuzzy"


def test_scenario_4_models_the_hierarchy_as_a_self_reference():
    """A self-reference on a FUZZY entity loads FP_/FS_ with the PARENT's publisher and
    source id. POST_CONSO because the parent may not be a golden record yet at source
    time — mirroring what CORPUS_A's OrganizationsOrganization does."""
    import yaml
    model = yaml.safe_load((ROOT / "out/s4-multi-source-ids/ir/model.yaml").read_text())
    ref = next(r for r in model["references"] if r["name"] == "CustomerParent")
    assert ref["from_entity"] == ref["to_entity"] == "Customer"
    assert (ref["from_role"], ref["to_role"]) == ("Child", "Parent")
    assert ref["validation_scope"] == "POST_CONSO"
    assert ref["delete_propagation"] == "RESTRICT"


def test_corpus_a_really_carries_three_self_references():
    """The claim the authoring guide correction rests on. If corpus model A is ever replaced,
    this fails rather than the guide quietly going stale."""
    from agent.compile.extract import extract
    src = ROOT / "samples" / "corpus-a-org-mdm-0.1.xml"
    if not src.exists():                    # not in the public export tree
        pytest.skip("samples/corpus-a-org-mdm-0.1.xml not present")
    ir, _ = extract(src)
    selfrefs = [r for r in ir.references if r.from_entity == r.to_entity]
    assert len(selfrefs) == 3
    on_org = [r for r in selfrefs if r.from_entity == "Organization"]
    assert len(on_org) == 2, "two self-references on the same pair, distinct roles"
    assert {r.to_role for r in on_org} == {"Parent", "ReportingOrganizationGoldenId"}


def test_scenario_3_is_fuzzy_with_every_probabilistic_rule_binned():
    import yaml
    model = yaml.safe_load((ROOT / "out/s3-three-sources/ir/model.yaml").read_text())
    cert = yaml.safe_load((ROOT / "out/s3-three-sources/ir/certify.yaml").read_text())
    assert model["entities"][0]["type"] == "fuzzy"
    rules = cert["matchers"][0]["rules"]
    assert rules and all(r["binning"] for r in rules if r["score"] < 100)
    assert all(e["scope"] == "PRE_CONSO" for e in cert["enrichers"])


@pytest.mark.parametrize("mutation,expected", [
    # PhoneticName's output IS read by a match rule, so this is the IR-009 case.
    ("name: PhoneticName\n    kind: semql\n    scope: PRE_CONSO|"
     "name: PhoneticName\n    kind: semql\n    scope: POST_CONSO", "IR-009"),
    # NormalizeName's output is read only by another enricher, so it is IR-016's case:
    # the same bug one step further back, which IR-009 alone cannot see.
    ("name: NormalizeName\n    kind: semql\n    scope: PRE_CONSO|"
     "name: NormalizeName\n    kind: semql\n    scope: POST_CONSO", "IR-016"),
    ('binning: ["Address.Zip5"]|binning: []', "IR-010"),
    ("publisher_rankings: [Support, Marketing, Events]|publisher_rankings: []", "IR-011"),
])
def test_the_checks_would_have_caught_the_classic_errors(tmp_path, mutation, expected):
    """A passing check is worthless if it could not have failed. Each mutation is a
    mistake a plausible design would actually make."""
    import shutil
    src = ROOT / "out/s3-three-sources"
    d = tmp_path / "s"
    shutil.copytree(src, d)
    old, new = mutation.split("|")
    f = d / "ir" / "certify.yaml"
    f.write_text(f.read_text().replace(old, new, 1))
    assert expected in {i.rule for i in check(d).ir_issues}


# ------------------------------------------- narrative / IR divergence
def test_an_ir_object_the_narrative_never_mentions_fails(project):
    """The gate approves the narrative; the compiler builds the IR. Something present
    in one and not the other was never really approved."""
    (project / "04-app-plan.md").write_text("# section\n")   # stop naming the objects
    rep = check(project)
    assert rep.unexplained and not rep.ok


def test_a_narrative_naming_every_object_is_clean(project):
    from agent.advisory import unexplained_objects
    from agent.ir.schema import IR as _IR
    ir = _IR.load(project / "ir" / "model.yaml", project / "ir" / "certify.yaml")
    names = unexplained_objects(ir, "")
    assert unexplained_objects(ir, " ".join(names)) == []


def test_the_generated_scenarios_explain_every_object_they_build():
    if not NARRATED:
        pytest.skip("scenario narrative artefacts (01-intake.md ...) not present")
    for d in NARRATED:
        assert check(d).unexplained == [], d.name


def test_every_scenario_actually_COMPILES_not_just_validates():
    """The gap this closes: for eight sprints the scenarios were checked with validate
    and advise but never emitted with their certification IR. Three of the four died in
    the compiler with KeyError: 'publisher/CRM_EU' while reporting 'clean'.

    A design that passes every check and cannot be built is not a design."""
    from agent.compile.emit import emit
    from agent.ir.schema import IR
    for d in sorted((ROOT / "out").glob("s*/ir")):
        c, a = d / "certify.yaml", d / "app.yaml"
        ir = IR.load(d / "model.yaml", c if c.exists() else None,
                     a if a.exists() else None)
        xml = emit(ir.model_ir, platform_version="2025.1.0",
                   repository_version="2025.1.2", certify=ir.certify, app=ir.app)
        # The XML DECLARATION is required by the importer, which rejects a document
        # without one as "Unable to parse payload".
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'), d.parent.name
        assert "<metaDataExport>" in xml[:80], d.parent.name


def test_a_ranking_by_publisher_CODE_is_caught_in_the_ir():
    """Rankings name publishers by NAME. gs-customerb2c ranks `Marketing`, whose code is
    `MKT` — so the two are genuinely different strings and the mistake is invisible
    until the emitter cannot resolve it."""
    from agent.ir.schema import IR
    from agent.ir.validate import validate
    ir = IR.load(ROOT / "out/s3-three-sources/ir/model.yaml",
                 ROOT / "out/s3-three-sources/ir/certify.yaml")
    assert [i for i in validate(ir) if i.rule == "IR-008"] == []
    rule = next(r for r in ir.certify.survivorship if r.publisher_rankings)
    rule.publisher_rankings = ["SUPPORT"]              # the code, not the name
    hit = [i for i in validate(ir) if i.rule == "IR-008"]
    assert hit and "CODE of publisher 'Support'" in hit[0].message


def test_the_samples_confirm_rankings_use_names():
    """Ground truth rather than assumption: gs-customerb2c's Marketing publisher has
    code MKT, and its rankings say Marketing."""
    from agent.compile.extract import extract
    from agent.compile.extract_certify import extract_certify
    path = ROOT / "samples" / "gs-customerb2c-2025.1.0.xml"
    if not path.exists():                   # vendor demo export; not in the public tree
        pytest.skip("samples/gs-customerb2c-2025.1.0.xml not present")
    model, _ = extract(path)
    names = {p.name for p in model.publishers}
    codes = {p.code for p in model.publishers}
    assert "Marketing" in names and "MKT" in codes
    ranked = {n for s in extract_certify(path).survivorship
              for n in s.publisher_rankings}
    assert ranked <= names
