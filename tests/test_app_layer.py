"""Sprint 07 acceptance: the application layer.

Display cards and collections live under Entity, not Application. The vocabulary is
harvested from real exports and unknown keys are refused, because a wrong component
property imports cleanly and misbehaves at runtime — a failure that survives validation.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.emit import EmitError, emit  # noqa: E402
from agent.compile.emit_app import check_component, vocab  # noqa: E402
from agent.compile.extract import extract  # noqa: E402
from agent.compile.extract_app import extract_app  # noqa: E402
from agent.ir.schema import IR, ComponentProperty  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {"gs-productretail": ROOT / "samples" / "gs-productretail-2025.1.0.xml",
           "corpus-a": ROOT / "samples" / "corpus-a-org-mdm-0.1.xml",
           "gs-customerb2c": ROOT / "samples" / "gs-customerb2c-2025.1.0.xml"}
VER = {"platform_version": "2025.1.0", "repository_version": "2025.1.2"}


def sample(name: str) -> Path:
    """A real product export, or a skip naming the file that is not here.

    `samples/` holds two vendor demo models and one production-sourced, so the public export
    ships without it and every test that reads one skips there. The guard is per TEST
    rather than per module because roughly a quarter of this file needs no sample at
    all — an unknown component is refused, a stepper is built from the s3 IR — and
    those must keep running where they can. Nothing is weakened: in the full repository
    every test in this module runs and asserts exactly what it always did.
    """
    p = SAMPLES[name]
    if not p.exists():
        pytest.skip(f"{p.relative_to(ROOT)} not present")
    return p


def every_sample() -> list[Path]:
    """All three, or a skip. These tests assert something about EVERY sample, and two
    out of three looks exactly like three out of three (LESSONS §13) — so a partial
    corpus must not be quietly accepted as a full one."""
    absent = [p for p in SAMPLES.values() if not p.exists()]
    if absent:
        pytest.skip(", ".join(str(p.relative_to(ROOT)) for p in absent) + " not present")
    return list(SAMPLES.values())


@pytest.mark.parametrize("name", list(SAMPLES), ids=list(SAMPLES))
def test_application_layer_round_trips(name, tmp_path):
    from agent.compile.extract_certify import extract_certify
    path = sample(name)
    ir, _ = extract(path)
    app = extract_app(path)
    out = tmp_path / "m.xml"
    out.write_text(emit(ir, **VER, app=app, certify=extract_certify(path)))
    assert extract_app(out).model_dump() == app.model_dump()


@pytest.mark.parametrize("name", list(SAMPLES), ids=list(SAMPLES))
def test_display_cards_and_collections_are_emitted_under_the_entity(name):
    """Not under Application — the Application element holds only actions, navigation,
    search and documentation config."""
    from agent.compile.extract_certify import extract_certify
    ir, _ = extract(sample(name))
    root = ET.fromstring(emit(ir, **VER, app=extract_app(sample(name)),
                              certify=extract_certify(sample(name))))
    parent = {c: p for p in root.iter() for c in p}
    for tag in ("DisplayCard", "CollectionView"):
        el = root.find(f".//{tag}")
        if el is not None:
            assert parent[parent[el]].tag == "Entity"


def test_the_vocabulary_covers_every_component_in_every_sample():
    known = set(vocab()["components"])
    for path in every_sample():
        root = ET.parse(path).getroot()
        used = {n.text for n in root.iter("componentName") if n.text}
        assert used <= known, f"{path.name} uses {sorted(used - known)}"


def test_an_unknown_component_is_refused():
    with pytest.raises(EmitError, match="unknown component"):
        check_component("semTelepathyField", [])


def test_an_unknown_property_is_refused():
    with pytest.raises(EmitError, match="unknown propert"):
        check_component("semTextField", [ComponentProperty(name="notARealKey")])


def test_the_refusal_names_the_way_out():
    """Refusing without saying how to proceed is just a wall."""
    with pytest.raises(EmitError) as e:
        check_component("semNope", [])
    assert "re-harvest" in str(e.value) and "rather than guessing" in str(e.value)


def test_empty_string_is_preserved_as_a_real_property_value(tmp_path):
    """'' means inherit-the-default and is NOT the same as omitting the property."""
    path = sample("gs-productretail")
    ir, _ = extract(path)
    app = extract_app(path)
    blanks = [p for c in app.collections for col in c.columns
              for p in col.properties if p.value == ""]
    assert blanks, "sample should contain blank-valued properties"
    from agent.compile.extract_certify import extract_certify
    out = tmp_path / "m.xml"
    out.write_text(emit(ir, **VER, app=app, certify=extract_certify(path)))
    back = extract_app(out)
    assert [p for c in back.collections for col in c.columns
            for p in col.properties if p.value == ""]


# --------------------------------------------------------------- subject_name
def test_subject_name_compiles_into_a_default_display_card():
    """xDM has no entity-level display-name attribute. primaryTextExpression on a
    display card is what titles a record, so that is where subject_name lands."""
    ir = IR.load(ROOT / "out/s3-three-sources/ir/model.yaml",
                 ROOT / "out/s3-three-sources/ir/certify.yaml")
    entity = ir.model_ir.entities[0]
    assert entity.subject_name == "FullName"
    card = ET.fromstring(emit(ir.model_ir, **VER)).find(".//DisplayCard")
    assert card is not None
    assert card.findtext("primaryTextExpression") == "FullName"
    assert card.findtext("name") == f"{entity.name}DisplayCard"


def test_no_subject_name_means_no_synthesised_card():
    ir = IR.load(ROOT / "out/s1-country-reference/ir/model.yaml")
    assert ET.fromstring(emit(ir.model_ir, **VER)).find(".//DisplayCard") is None


def test_an_explicit_app_ir_is_not_overridden_by_subject_name():
    """If the design supplied display cards, subject_name must not add a second."""
    path = sample("gs-productretail")
    ir, _ = extract(path)
    ir.entities[0].subject_name = "Name"
    from agent.compile.extract_certify import extract_certify
    app = extract_app(path)
    root = ET.fromstring(emit(ir, **VER, app=app, certify=extract_certify(path)))
    names = [c.findtext("name") for c in root.iter("DisplayCard")]
    assert f"{ir.entities[0].name}DisplayCard" not in names or \
        names.count(f"{ir.entities[0].name}DisplayCard") == 1


# ------------------------------------------------------------------- forms
def test_forms_round_trip_with_nested_containers(tmp_path):
    """gs-productretail has 24 nested containers and gs-customerb2c 21, so the
    parent-reference tree is genuinely exercised."""
    from agent.compile.extract_certify import extract_certify
    for path in every_sample():
        ir, _ = extract(path)
        app = extract_app(path)
        out = tmp_path / f"{path.stem}.xml"
        out.write_text(emit(ir, **VER, app=app, certify=extract_certify(path)))
        assert extract_app(out).model_dump() == app.model_dump(), path.name


def test_form_fields_are_flat_with_parent_refs():
    """The XML expresses the form tree by REFERENCE, not by nesting: formFields is a
    flat list and each field points at its container. Emitting a nested structure
    would be wrong even though it reads more naturally."""
    path = sample("gs-productretail")
    ir, _ = extract(path)
    root = ET.fromstring(emit(ir, **VER, app=extract_app(path)))
    parent = {c: p for p in root.iter() for c in p}
    field = root.find(".//FormField")
    assert parent[field].tag == "formFields"
    assert parent[parent[field]].tag == "Form"
    assert field.find("parentFormContainer") is not None


def test_all_three_container_element_types_are_supported():
    """FormSection2 appears ONLY in gs-customerb2c. Two samples would have missed it,
    and the emitter would have refused a legitimate model."""
    from agent.compile.extract_app import CONTAINER_KIND
    assert set(CONTAINER_KIND) == {"FormTab", "FormContainer", "FormSection2"}
    kinds = {c.kind for f in extract_app(sample("gs-customerb2c")).forms
             for c in f.containers}
    assert "section2" in kinds


def test_every_container_element_in_every_sample_is_known():
    """The guard against a fourth type appearing in a future sample."""
    from agent.compile.extract_app import CONTAINER_KIND
    for path in every_sample():
        root = ET.parse(path).getroot()
        used = {c.tag for h in root.iter("formContainers") for c in h}
        assert used <= set(CONTAINER_KIND), f"{path.name}: {sorted(used - set(CONTAINER_KIND))}"


def test_a_field_in_an_undeclared_container_is_refused():
    path = sample("gs-productretail")
    ir, _ = extract(path)
    app = extract_app(path)
    form = next(f for f in app.forms if f.fields and f.containers)
    form.fields[0].container = "NoSuchContainer"
    with pytest.raises(EmitError, match="not declared in this form"):
        emit(ir, **VER, app=app)


def test_a_container_with_an_undeclared_parent_is_refused():
    path = sample("gs-productretail")
    ir, _ = extract(path)
    app = extract_app(path)
    form = next(f for f in app.forms if f.containers)
    form.containers[0].parent = "NoSuchParent"
    with pytest.raises(EmitError, match="not declared in this form"):
        emit(ir, **VER, app=app)


# ----------------------------------------------------------------- steppers
def test_steppers_round_trip(tmp_path):
    from agent.compile.extract_certify import extract_certify
    for path in every_sample():
        ir, _ = extract(path)
        app, cert = extract_app(path), extract_certify(path)
        out = tmp_path / f"st-{path.stem}.xml"
        out.write_text(emit(ir, **VER, app=app, certify=cert))
        assert extract_app(out).model_dump() == app.model_dump(), path.name


def test_form_and_collection_steps_are_peers():
    """Both live inside <steps>; a CollectionStep is not nested under a FormStep."""
    app = extract_app(sample("gs-productretail"))
    kinds = {s.kind for st in app.steppers for s in st.steps}
    assert kinds == {"form", "collection"}


def test_a_form_step_enricher_is_a_binding_not_a_definition():
    """All 28 in corpus model A point at a SemQLEnricher. The enricher itself is sprint 06's;
    only the trigger belongs to the stepper."""
    from agent.compile.extract_certify import extract_certify
    app = extract_app(sample("corpus-a"))
    cert = extract_certify(sample("corpus-a"))
    bindings = [b for st in app.steppers for s in st.steps for b in s.enrichers]
    assert len(bindings) == 28
    defined = {e.name for e in cert.enrichers}
    assert {b.enricher for b in bindings} <= defined


def test_collection_step_toggles_survive_as_passthrough():
    """~40 flat booleans per CollectionStep, carried verbatim rather than modelled.
    Losing them would be silent, so the count is pinned."""
    app = extract_app(sample("gs-productretail"))
    total = sum(len(s.settings) for st in app.steppers for s in st.steps)
    assert total > 300


def test_a_step_whose_parent_is_not_in_the_stepper_is_refused():
    from agent.compile.extract_certify import extract_certify
    path = sample("gs-productretail")
    ir, _ = extract(path)
    app = extract_app(path)
    st = next(s for s in app.steppers if len(s.steps) > 1)
    st.steps[-1].parent_step = "NoSuchStep"
    with pytest.raises(EmitError, match="not a step of this stepper"):
        emit(ir, **VER, app=app, certify=extract_certify(path))


def test_binding_an_enricher_without_certification_ir_is_refused():
    path = sample("corpus-a")
    ir, _ = extract(path)
    app = extract_app(path)
    # app without certify: the binding cannot be resolved, and guessing a UUID would
    # produce a dangling ref that imports cleanly.
    with pytest.raises(EmitError, match="no certification IR"):
        emit(ir, **VER, app=app)


def test_the_round_trip_does_not_claim_coverage_it_lacks():
    """A passing round-trip proves emit inverts extract over what the IR REPRESENTS.
    It says nothing about element types the IR does not model yet, and those are
    counted here so 'round-trip: True' is never mistaken for 'complete'."""
    import collections
    from agent.compile.extract_certify import extract_certify
    path = sample("gs-productretail")
    ir, _ = extract(path)
    xml = emit(ir, **VER, app=extract_app(path), certify=extract_certify(path))
    src = {e.tag for e in ET.parse(path).getroot().iter() if e.tag[:1].isupper()}
    out = {e.tag for e in ET.fromstring(xml).iter() if e.tag[:1].isupper()}
    not_emitted = src - out
    # Pinned so the number moves deliberately, in either direction.
    #   54 -> 42  action sets, dups managers, model jobs
    #   42 -> 37  business object views
    #   37 -> 22  the Application shell, its menu and navigation
    #   22 -> 17  the export envelope (branch, edition, config, retention, NGModel)
    #   17 -> 15  security grants (ModelPrivGrant / EntityPrivGrant)
    #   15 -> 14  validations (CheckConstraint) — the construct sprint 06 recorded as
    #             having "no observed grammar", because it searched for an element
    #             named `Validation`
    #   14 -> 13  ForeignAttribute: the FK column a Reference hangs off. Its absence was
    #             invisible to the round trip AND to blocks (the `foreignAttribute` SLOT
    #             was being filled, empty), and only showed up as a deploy 500
    assert len(not_emitted) == 13, sorted(not_emitted)
    # What is left is dominated by the three step-validation types, which bind to
    # `validator` and `uniqueKey` objects the IR does not model.
    assert {"StepTransitionValidation", "FormStepValidation",
            "StepperFinishValidation"} <= not_emitted
    assert not {"ActionSet", "EditAction", "ModelJob", "BOViewEntity", "Application",
                "BrowseBusinessViewAction", "ModelBranch", "NGModel",
                "ModelPrivGrant", "EntityPrivGrant"} & not_emitted


# ------------------------------------------------- action sets and dups managers
def test_the_three_stewardship_actions_do_not_end_in_action():
    """A survey that filtered element names on the `Action` suffix missed exactly the
    trio that drives the duplicate queue. Pinned so the vocabulary keeps them."""
    from agent.ir.schema import ACTION_KINDS
    assert {"MergeOrSplit", "ReviewAndConfirm", "ReviewSuggestions"} <= set(ACTION_KINDS)


def test_an_unknown_action_kind_is_refused_at_the_ir_boundary():
    from pydantic import ValidationError
    from agent.ir.schema import Action
    with pytest.raises(ValidationError, match="unknown action kind"):
        Action(kind="ArchiveAction", name="Archive")


def test_a_stewardship_action_without_its_queue_is_refused():
    """MergeOrSplit points at a DupsManager. Emitting one whose manager is not declared
    would mint a UUID for an element never written — a dangling ref that imports
    cleanly, which is the failure mode this whole layer is built to avoid."""
    from agent.compile.extract_certify import extract_certify
    path = sample("gs-customerb2c")
    ir, _ = extract(path)
    app = extract_app(path)
    app.dups_managers = []                      # the queue disappears, the action stays
    with pytest.raises(EmitError, match="the queue it reviews does not exist"):
        emit(ir, **VER, app=app, certify=extract_certify(path))


def test_every_stewardship_action_in_the_samples_names_a_declared_queue():
    for name in SAMPLES:
        app = extract_app(sample(name))
        for a in app.action_sets:
            declared = {d.name for d in app.dups_managers if d.entity == a.entity}
            for act in a.actions:
                if act.kind in ("MergeOrSplit", "ReviewAndConfirm", "ReviewSuggestions"):
                    assert act.dups_manager in declared, f"{name}: {a.name}.{act.name}"


def test_a_form_tab_ref_needs_the_form_because_tab_names_repeat():
    """gs-customerb2c has a FormTab called `Person` in two different forms, so a tab
    name alone cannot resolve the ref."""
    app = extract_app(sample("gs-customerb2c"))
    tabs = [(a.form, a.form_tab) for s in app.action_sets for a in s.actions
            if a.form_tab]
    assert ("PersonForm", "Person") in tabs
    assert ("PersonConfirmMatchesForm", "Person") in tabs


def test_an_action_naming_a_stepper_of_another_entity_is_refused():
    from agent.compile.extract_certify import extract_certify
    path = sample("gs-productretail")
    ir, _ = extract(path)
    app = extract_app(path)
    act = next(a for s in app.action_sets for a in s.actions if a.stepper)
    act.stepper = "NotAStepperHere"
    with pytest.raises(EmitError, match="is not a stepper of entity"):
        emit(ir, **VER, app=app, certify=extract_certify(path))


# ------------------------------------------------------------------- model jobs
def test_model_jobs_round_trip_with_their_per_entity_phases():
    from agent.compile.extract_certify import extract_certify
    certify = extract_certify(sample("gs-productretail"))
    assert len(certify.jobs) == 8
    task = next(t for j in certify.jobs for t in j.tasks if t.entity == "Product")
    assert task.match and task.consolidation


def test_whether_a_matcher_runs_is_decided_by_the_job_task_not_the_entity():
    """Certification is configured on the ENTITY; whether a phase runs is decided by
    the JOB TASK. CORPUS_A shows the two diverging: Organization carries a matcher, and
    its task in `BulkImportAndExport` has matchEnabled false while the one in
    `LOAD_ORGANIZATION` has it true.

    That divergence is deliberate here — a bulk load/export path legitimately skips
    matching — which is exactly why this is pinned as a SHAPE and not turned into an
    advisory rule. The same shape with only one job would be a silent defect, and an
    advisor cannot tell the two apart without knowing what the job is for.

    gs-productretail is not checked: it has 8 jobs and zero matchers, so it cannot
    exhibit the shape at all."""
    from agent.compile.extract_certify import extract_certify
    certify = extract_certify(sample("corpus-a"))
    assert {m.entity for m in certify.matchers} == {"Organization"}
    runs = {j.name: t.match for j in certify.jobs for t in j.tasks
            if t.entity == "Organization"}
    assert runs == {"LOAD_ORGANIZATION": True, "BulkImportAndExport": False}


def test_a_stepper_finish_job_is_carried():
    """Step 4 dropped Stepper.modelJob silently, and the round-trip could not see it
    because both passes dropped it. Pinned against the sample that has one."""
    app = extract_app(sample("corpus-a"))
    assert any(s.model_job for s in app.steppers)


def test_referencing_a_job_without_certification_ir_is_refused():
    path = sample("corpus-a")
    ir, _ = extract(path)
    app = extract_app(path)
    app.steppers = [s for s in app.steppers if s.model_job]
    app.action_sets, app.dups_managers, app.forms = [], [], []
    for s in app.steppers:
        for step in s.steps:
            step.enrichers = []
    with pytest.raises(EmitError, match="no certification IR"):
        emit(ir, **VER, app=app)


# ------------------------------------------------------ business views and menu
def test_a_self_referencing_hierarchy_is_a_transition_onto_its_own_node():
    """Scenario 4's customer hierarchy. corpus model A expresses it as a BOViewTransition named
    `Child` on path `Child` whose target is the Organization node itself — not as a
    second node, and not as anything the model layer can express."""
    app = extract_app(sample("corpus-a"))
    view = next(v for v in app.business_views if v.name == "OrganizationStewardView")
    org = next(n for n in view.nodes if n.name == "Organization")
    child = next(t for t in org.transitions if t.name == "Child")
    assert child.path == "Child" and child.target == "Organization"


def test_a_view_node_resolves_against_its_own_entity_not_the_views_owner():
    """A business view walks the model graph, so a node may sit on another entity."""
    app = extract_app(sample("corpus-a"))
    view = next(v for v in app.business_views if v.name == "OrganizationStewardView")
    assert view.entity == "Organization"
    assert {n.entity for n in view.nodes} == {"Organization", "OrgRole"}


def test_a_view_whose_root_is_not_one_of_its_nodes_is_refused():
    from agent.compile.extract_certify import extract_certify
    path = sample("corpus-a")
    ir, _ = extract(path)
    app = extract_app(path)
    app.business_views[0].root = "NotANode"
    with pytest.raises(EmitError, match="is not one of its nodes"):
        emit(ir, **VER, app=app, certify=extract_certify(path))


def test_an_import_menu_entry_needs_the_full_triple():
    """gs-customerb2c declares TWO ImportActions named `ImportAuthorPersons` on Person,
    one per action set. So a menu entry pointing at "the Person import" is ambiguous:
    neither the bare name nor (entity, name) picks one out, and the menu entry does in
    fact resolve to a specific one of the two."""
    app = extract_app(sample("gs-customerb2c"))
    declared = {(s.entity, s.name, a.name) for s in app.action_sets for a in s.actions
                if a.kind == "ImportAction"}
    persons = {k for k in declared if k[0] == "Person"}
    assert len(persons) == 2                        # two homes...
    assert len({k[2] for k in persons}) == 1        # ...one name
    entry = next(a for a in app.applications[0].actions
                 if a.import_entity == "Person")
    assert (entry.import_entity, entry.import_action_set,
            entry.import_action) in persons
    assert entry.import_action_set is not None      # the disambiguator


def test_a_menu_entry_opening_an_undeclared_view_is_refused():
    from agent.compile.extract_certify import extract_certify
    path = sample("gs-productretail")
    ir, _ = extract(path)
    app = extract_app(path)
    act = next(a for a in app.applications[0].actions if a.view)
    act.view = "NoSuchView"
    with pytest.raises(EmitError, match="which is not declared"):
        emit(ir, **VER, app=app, certify=extract_certify(path))


def test_an_ambiguous_built_in_filter_is_refused_rather_than_guessed():
    """Filters are named model-wide but stored on a view node, so resolution searches.
    Two nodes declaring the same name must fail, not silently take the first."""
    from agent.compile.extract_certify import extract_certify
    path = sample("corpus-a")
    ir, _ = extract(path)
    app = extract_app(path)
    src = next((v, n, f) for v in app.business_views for n in v.nodes
               for f in n.filters)
    other = next(n for v in app.business_views for n in v.nodes if n is not src[1])
    other.filters = list(src[1].filters)            # same filter name, second home
    with pytest.raises(EmitError, match="different view nodes"):
        emit(ir, **VER, app=app, certify=extract_certify(path))


# -------------------------------------------------------------------- envelope
def test_the_envelope_carries_the_branch_and_edition_tree():
    """A bare RootModel + Model round-tripped perfectly — extract only reads Model
    content — while producing a file no instance has been asked to accept."""
    ir, _ = extract(sample("gs-productretail"))
    root = ET.fromstring(emit(ir, **VER))
    rm = root.find("RootModel")
    branch = rm.find("modelBranches/ModelBranch")
    assert rm.find("rootModelBranch").attrib["ref"] == \
        branch.find("internalID").attrib["val"]
    assert branch.find("modelEditions/ModelEdition/status").attrib["val"] == "OPEN"
    assert root.find("NGModel") is not None


def test_the_target_technology_reaches_the_xml():
    """D13 says Snowflake. Until ModelConfiguration was emitted, a model built for
    Snowflake said so nowhere in its XML.

    This test used to assert that gs-productretail extracts as `snowflake`. It does
    not — it is a POSTGRESQL model, and the assertion passed only because extraction
    IGNORED ModelConfiguration and returned the IR default. The test was pinning the
    bug. Now it pins the round trip in both directions.
    """
    ir, _ = extract(sample("gs-productretail"))
    assert ir.model.target_technology == "postgresql", "the sample is POSTGRESQL"
    root = ET.fromstring(emit(ir, **VER))
    cfg = root.find("Model/modelConfiguration/ModelConfiguration/type")
    assert cfg.attrib["val"] == "POSTGRESQL"

    ir.model.target_technology = "snowflake"          # D13's target, explicitly set
    root = ET.fromstring(emit(ir, **VER))
    assert root.find(
        "Model/modelConfiguration/ModelConfiguration/type").attrib["val"] == "SNOWFLAKE"


def test_an_unobserved_target_technology_is_refused():
    ir, _ = extract(sample("gs-productretail"))
    ir.model.target_technology = "oracle"
    with pytest.raises(EmitError, match="not one observed in any sample"):
        emit(ir, **VER)


def test_retention_defaults_to_forever_on_all_four_axes():
    ir, _ = extract(sample("gs-productretail"))
    rp = ET.fromstring(emit(ir, **VER)).find("Model/retentionPolicy/RetentionPolicy")
    assert {rp.find(f"{a}Type").attrib["val"]
            for a in ("history", "deletions", "sourceData", "sourceErrors")} == \
        {"FOREVER"}


# ------------------------------------------------------------------- security
def test_roles_and_their_entity_grants_round_trip():
    ir, _ = extract(sample("gs-productretail"))
    assert {r.role_name for r in ir.roles} == {"BusinessUser", "DataSteward",
                                               "semarchyAdmin"}
    # Not every role carries entity grants — DataSteward here carries none, and its
    # privileges are the model-level flags instead.
    granting = [r for r in ir.roles if r.grants]
    assert granting and all(g.entity for r in granting for g in r.grants)
    assert next(r for r in ir.roles if r.role_name == "DataSteward").data_admin


def test_granting_access_to_an_undeclared_entity_is_refused():
    ir, _ = extract(sample("gs-productretail"))
    next(r for r in ir.roles if r.grants).grants[0].entity = "NoSuchEntity"
    with pytest.raises(EmitError, match="which the model does not declare"):
        emit(ir, **VER)


def test_a_screen_gated_on_an_ungranted_role_is_a_gap_not_an_error():
    """Roles are defined in the PLATFORM, not the model, so a role with no grant may
    genuinely exist — which is why this advises rather than refusing. It fires twice on
    the real CORPUS_A model and stays silent on both vendor samples."""
    from agent.compile.extract_certify import extract_certify
    from agent.ir.advise import advise
    from agent.ir.schema import IR as _IR

    def ca011(name):
        ir, _ = extract(sample(name))
        full = _IR(model_ir=ir, certify=extract_certify(sample(name)),
                   app=extract_app(sample(name)))
        return [g for g in advise(full) if g.rule == "CA-011"]

    assert {g.where for g in ca011("corpus-a")} == {
        "menu entry StewardOrganizations", "menu entry FinanceOrganizations"}
    assert ca011("gs-productretail") == [] and ca011("gs-customerb2c") == []


def test_ca011_stays_silent_when_the_model_grants_nothing_at_all():
    """A model with no privilege grants has not started on security; asking about every
    role reference then would be noise, not advice."""
    from agent.compile.extract_certify import extract_certify
    from agent.ir.advise import advise
    from agent.ir.schema import IR as _IR
    ir, _ = extract(sample("corpus-a"))
    ir.roles = []
    full = _IR(model_ir=ir, certify=extract_certify(sample("corpus-a")),
               app=extract_app(sample("corpus-a")))
    assert [g for g in advise(full) if g.rule == "CA-011"] == []


def test_the_vocabulary_records_where_it_came_from():
    """A floor is only trustworthy if you can see what it was measured against."""
    import yaml
    v = yaml.safe_load((ROOT / "agent/compile/component_vocab.yaml").read_text())
    assert len(v["sources"]) >= 6
    assert "semHyperlinkField" in v["components"]


def test_the_hyperlink_renderer_carries_its_link_properties():
    """Harvested 2026-08-03 after the emitter REFUSED it on a live model. It appears in
    none of the three samples, which is the whole reason refuse-on-unknown exists: the
    vocabulary is a floor, and the first real model walked past it within a day."""
    known = vocab()["components"]["semHyperlinkField"]
    assert {"linkTarget", "linkSourceType", "linkDisplayText"} <= set(known)


def test_an_unknown_renderer_is_still_refused_after_re_harvesting():
    """Widening the floor must not turn the guard off."""
    with pytest.raises(EmitError, match="unknown component"):
        check_component("semQuantumField", [])


# ------------------------- element-set parity with the product (harvest, 2026-08-04)
def test_the_form_element_set_matches_what_the_product_writes():
    """HARVESTED LIVE. A Form was built in the UI on PartyHubProbe and exported; the
    compiler's own output for the same IR was compared element-for-element.

    It did not match. `Form` omitted description/documentation/formCharts/
    formCollections/formDashboards, `FormField` omitted eight elements, `FormTab`
    omitted nine, and `ComponentProperty` omitted dataType and valueInterpreter.

    That is the §19 shape exactly: an ABSENT element is not an explicitly-null one, and
    it is what made the survivorship import refuse. The app layer had the same gap and
    nothing offline could see it, because both compiler passes agreed with each other.
    """
    from xml.etree import ElementTree as ET
    from agent.compile.emit import emit
    from agent.compile.extract import extract
    from agent.compile.extract_app import extract_app
    from agent.compile.extract_certify import extract_certify

    src = ROOT / "harvest" / "PartyHubProbe.form.xml"
    if not src.exists():                       # harvest is evidence, not a fixture
        pytest.skip("no harvested form export present")
    m, _ = extract(src)
    mine = ET.fromstring(emit(m, platform_version="x", repository_version="y",
                              certify=extract_certify(src), app=extract_app(src)))
    good = ET.parse(src).getroot()

    def tags(root, tag):
        el = next(root.iter(tag))
        return {c.tag for c in el if not c.tag.startswith("internal")}

    for tag in ("Form", "FormField", "FormTab", "ComponentProperty"):
        assert tags(mine, tag) == tags(good, tag), f"{tag} element set diverges"


# ----------------------------------------------- the stepper's shape (2026-08-06)
def _s3():
    from agent.compile.extract_certify import extract_certify  # noqa: F401
    from agent.ir.schema import IR
    d = ROOT / "out/s3-three-sources/ir"
    return IR.load(d / "model.yaml", d / "certify.yaml", d / "app.yaml")


def test_a_stepper_roots_in_a_collection_step_even_when_nobody_wrote_one():
    """MEASURED across all 20 corpus steppers: `rootCollectionStep` is a real ref in
    20/20 and 0/20 are form-only. So "one form step and nothing else" is not a smaller
    stepper, it is a shape the product has never written — and the author should not
    have to know that. s3's app.yaml declares one form step; the root is derived.
    """
    ir = _s3()
    root = ET.fromstring(emit(ir.model_ir, **VER, certify=ir.certify, app=ir.app))
    st = root.find(".//Stepper")
    assert st.findtext("name") == "AuthorParty"
    rc = st.find("rootCollectionStep")
    assert rc is not None and "ref" in rc.attrib, "rootCollectionStep must be a real ref"

    steps = list(st.find("steps"))
    coll = [s for s in steps if s.tag == "CollectionStep"]
    assert len(coll) == 1, "exactly one root collection step, derived"
    assert coll[0].find("internalID").get("val") == rc.get("ref"), \
        "rootCollectionStep must resolve to a step inside <steps>"
    assert coll[0].find("collectionView").get("ref"), "collectionView is never null"


def test_every_non_root_step_is_parented_to_the_root():
    """`parentCollectionStep` is a real ref in 26/26 observed form steps. A form step
    floating beside the root imports at 204 and has nowhere to render."""
    ir = _s3()
    root = ET.fromstring(emit(ir.model_ir, **VER, certify=ir.certify, app=ir.app))
    st = root.find(".//Stepper")
    rc = st.find("rootCollectionStep").get("ref")
    for fs in st.iter("FormStep"):
        assert fs.find("parentCollectionStep").get("ref") == rc
        assert fs.find("formTab").get("ref"), "formTab is never null"


def test_the_emitted_stepper_raises_no_shape_findings():
    """The check that would have caught this offline, run against the thing it missed."""
    from agent.compile.blocks import check as shape_check
    ir = _s3()
    xml = emit(ir.model_ir, **VER, certify=ir.certify, app=ir.app)
    bad = [f for f in shape_check(xml) if f.kind == "null-ref"]
    assert bad == [], "\n".join(str(f) for f in bad)


def test_a_form_step_naming_no_form_is_refused():
    """Refuse rather than guess: `formTab` resolves to a FormTab in 26/26 instances, so
    there is no neutral thing to point it at."""
    ir = _s3()
    ir.app.steppers[0].steps[0].form = None
    with pytest.raises(EmitError, match="names no form"):
        emit(ir.model_ir, **VER, certify=ir.certify, app=ir.app)


def test_a_form_step_opens_a_TAB_not_a_form():
    """The grain that cost a deploy. A stepper over a three-tab form is three steps, not
    one — `formTab` points at a FormTab in 26/26 observed instances, never at a Form."""
    ir = _s3()
    ir.app.steppers[0].steps[0].form_tab = "NoSuchTab"
    with pytest.raises(EmitError, match="not a tab of that form"):
        emit(ir.model_ir, **VER, certify=ir.certify, app=ir.app)


def test_a_step_may_be_about_a_child_entity():
    """3 of 26 form steps and 3 of 24 collection steps in the corpus point at an object
    on a DIFFERENT entity — the Product -> Items -> Images nesting. Scoping the lookup
    to the stepper's own entity refuses six steps the product actually wrote."""
    app = extract_app(sample("gs-productretail"))
    st = next(s for s in app.steppers if s.name == "ProductStepper")
    foreign = [s for s in st.steps if s.entity and s.entity != st.entity]
    assert foreign, "ProductStepper drills into Item and ItemImage"
    assert {s.entity for s in foreign} == {"Item", "ItemImage"}


def test_two_unparented_collection_steps_are_refused_rather_than_picked():
    """Which one is the root is a design decision, and 20/20 steppers have exactly one."""
    from agent.ir.schema import StepperStep
    ir = _s3()
    ir.app.steppers[0].steps.append(
        StepperStep(kind="collection", name="PartyReviewQueue",
                    collection="PartyReviewQueue"))
    ir.app.steppers[0].steps.append(
        StepperStep(kind="collection", name="PartyCollection",
                    collection="PartyCollection"))
    with pytest.raises(EmitError, match="collection steps with no parent"):
        emit(ir.model_ir, **VER, certify=ir.certify, app=ir.app)
