"""Workflow emission — the layer that lives in NGModel, not the XML tree.

Key-for-key against `harvest/workflow-definition-valid.json`: the first definition the
product has exported for us that its own builder calls valid (operator present, D12,
2026-08-06).

`harvest/workflow-definition.json` — the invalid DRAFT — is still loaded here, and only
for the tests that need something invalid to point at. It attests every field spelling
while breaking four builder rules, which is §48, and the two step types it omits are
exactly the two this module got wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.compile.emit_workflow import (  # noqa: E402
    WorkflowEmitError, definition, ng_model)
from agent.compile.envelope import NG_MODEL_BODY  # noqa: E402
from agent.ir.schema import (  # noqa: E402
    Recipient, TaskTimeLimit, Transition, Workflow, WorkflowStep)
from agent.ir.validate import validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
#: The invalid draft. Kept for the §48 story and nothing else.
DRAFT = json.loads((ROOT / "harvest/workflow-definition.json").read_text())
#: The valid definition. THE ground truth for every shape.
VALID = json.loads((ROOT / "harvest/workflow-definition-valid.json").read_text())
WANT = VALID["workflowDefinitions"][0]
#: The hardening definition — a SECOND product export (operator-built in the Workflow
#: Builder, exported over REST, D12). THE ground truth for the four constructs the valid
#: file did not contain: Router, ParallelBlock, the SUBMIT automation, and the
#: START_FROM_SELECTION start context. This one is NOT compiler output, so it is safe to
#: harvest from — unlike harvest/PartyHubProbe.*, which is COMPILER_DERIVED.
#: A measurement file, not shipped in the public export (harvest/ ships only the two
#: workflow-definition JSONs). Absent there, so loaded guardedly and the tests that read
#: it skip — the same export discipline the rest of the suite uses: a missing private
#: witness is a skip, never a collection error.
_HARDENING_PATH = ROOT / "harvest/workflow-hardening-constructs.json"
HARDENING = (json.loads(_HARDENING_PATH.read_text())
             if _HARDENING_PATH.exists() else None)


def _step_of(doc, x_type):
    return next(s for s in doc["steps"] if s["x-type"] == x_type)


def _wf(**kw):
    base = dict(
        name="W", root_entities=["Party"],
        start_context="START_FROM_EMPTY_SELECTION",
        steps=[
            WorkflowStep(type="StartEvent", name="start",
                         transitions=[Transition(to_step="task")]),
            WorkflowStep(type="UserTask", name="task", entity="Party",
                         stepper="AuthorParty",
                         transitions=[Transition(to_step="done")]),
            WorkflowStep(type="EndEvent", name="done"),
        ])
    base.update(kw)
    return Workflow(**base)


def _rebuild_the_valid_definition() -> Workflow:
    """The harvested definition, expressed in the IR. If this drifts from the file the
    emitter has stopped reproducing the one document we know the product accepts."""
    return Workflow(
        name="test", label="Test", root_entities=["Person"],
        start_context="START_FROM_EMPTY_SELECTION",
        steps=[
            WorkflowStep(type="UserTask", name="assignment", label="Assignment",
                         application="CustomerB2C",
                         assignee_required_role="DataSteward",
                         entity="Person", stepper="AuthorPersons",
                         my_tasks_collection="PersonConfirmMatchesCollection",
                         transitions=[Transition(to_step="end", name="done",
                                                 label="Done")]),
            WorkflowStep(type="Automation", name="autoTest", label="Auto Test",
                         automation_type="EMAIL", application="CustomerB2C",
                         sender_name="test@claude.com", subject="urgent",
                         body="check this out",
                         to=[Recipient(name="receipient", role="DataSteward")],
                         transitions=[Transition(to_step="assignment")]),
            WorkflowStep(type="StartEvent", name="start", label="Start",
                         transitions=[Transition(to_step="autoTest")]),
            WorkflowStep(type="EndEvent", name="end"),
        ])


def _ir_with(w):
    from agent.ir.schema import IR
    ir = IR.load(ROOT / "out/s3-three-sources/ir/model.yaml",
                 ROOT / "out/s3-three-sources/ir/certify.yaml")
    ir.model_ir.workflows = [w] if w else []
    return ir


# ------------------------------------------------------------- the container
def test_no_workflows_is_byte_identical_to_the_old_constant():
    """The change must not touch the four scenarios that already deploy. `NGModel` was
    a hardcoded string for the whole life of the compiler; building it from an empty IR
    has to reproduce it exactly, or every existing model's envelope moves at once."""
    assert json.dumps(ng_model(), separators=(",", ":")) == NG_MODEL_BODY


def test_the_container_was_never_a_placeholder():
    """`workflowDefinitions: []` was read as "workflows are not exportable" twice. It is
    the container, and the harvested file proves it by having one in it."""
    assert DRAFT["workflowDefinitions"], "the harvested draft must contain a workflow"


# ------------------------------------------------- the shape, against the product's
def _diff(got, want, path=""):
    """Every structural disagreement, everywhere. Diagram coordinates excluded — the
    builder records where a human dragged a node and nothing downstream reads them."""
    out = []
    if isinstance(want, dict) and isinstance(got, dict):
        for k in sorted(set(got) | set(want)):
            if k not in got:
                out.append(f"MISSING {path}.{k}")
            elif k not in want:
                out.append(f"EXTRA   {path}.{k}")
            else:
                out += _diff(got[k], want[k], f"{path}.{k}")
    elif isinstance(want, list) and isinstance(got, list):
        if len(got) != len(want):
            out.append(f"LEN {path}: {len(got)} vs {len(want)}")
        for i, (a, b) in enumerate(zip(got, want)):
            out += _diff(a, b, f"{path}[{i}]")
    elif got != want and not path.endswith((".x", ".y")):
        out.append(f"VALUE   {path}: got {got!r} want {want!r}")
    return out


def test_the_emitter_reproduces_the_valid_definition_exactly():
    """THE test this module exists for, and it could not be written until 2026-08-06.

    Every earlier key-for-key test compared against the DRAFT, which contains no Start
    Event and no End Event — so the two step types the emitter invented were the two
    nothing checked. This compares the whole document, values included, against the one
    definition the product's own builder calls valid.
    """
    bad = _diff(definition(_rebuild_the_valid_definition()), WANT)
    assert bad == [], "\n".join(bad)


def test_a_definition_carries_every_key_the_product_writes():
    got = definition(_wf())
    assert set(got) == set(WANT), (
        f"missing {sorted(set(WANT) - set(got))}, extra {sorted(set(got) - set(WANT))}")


def test_a_user_task_carries_every_key_the_product_writes():
    got = _step_of(definition(_wf()), "UserTask")
    want = _step_of(WANT, "UserTask")
    assert set(got) == set(want), (
        f"missing {sorted(set(want) - set(got))}, extra {sorted(set(got) - set(want))}")


def test_an_automation_carries_every_key_the_product_writes():
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="mail")]),
        WorkflowStep(type="Automation", name="mail", automation_type="EMAIL",
                     to=[Recipient(name="r", role="DataSteward")],
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="EndEvent", name="done")])
    got = _step_of(definition(w), "Automation")
    want = _step_of(WANT, "Automation")
    assert set(got) == set(want), (
        f"missing {sorted(set(want) - set(got))}, extra {sorted(set(got) - set(want))}")


def test_a_start_event_carries_nine_keys_and_no_icon():
    """Every other step type has an `icon`. A StartEvent does not, and it carries a
    SINGULAR `transition` like an Automation rather than a list like a UserTask. All
    three were guessed wrong while the draft had nothing to say about it."""
    got = _step_of(definition(_wf()), "StartEvent")
    want = _step_of(WANT, "StartEvent")
    assert set(got) == set(want), (
        f"missing {sorted(set(want) - set(got))}, extra {sorted(set(got) - set(want))}")
    assert "icon" not in got
    assert "transitions" not in got and isinstance(got["transition"], dict)


def test_an_end_event_carries_exactly_three_keys():
    """Not "the common fields minus the inapplicable ones" — three. We emitted `label`,
    `icon` and `transitions` on it, none of which the product writes."""
    got = _step_of(definition(_wf()), "EndEvent")
    assert set(got) == {"x-type", "name", "position"}, sorted(got)
    assert set(got) == set(_step_of(WANT, "EndEvent"))


def test_there_is_no_common_step_shape_to_fall_back_on():
    """The reasoning that produced the bad Start and End events was "emit only the
    fields EVERY step carries". The valid file shows there is no such set: 9 keys
    against 3. That is why Router and ParallelBlock are refused, not approximated."""
    start = set(_step_of(WANT, "StartEvent"))
    end = set(_step_of(WANT, "EndEvent"))
    task = set(_step_of(WANT, "UserTask"))
    assert len(start) == 9 and len(end) == 3 and len(task) == 17
    assert start & end & task == {"x-type", "name", "position"}


def test_a_router_with_no_routes_is_refused():
    """A router chooses an outgoing edge by condition; with none it routes nowhere."""
    w = _wf(steps=[WorkflowStep(type="StartEvent", name="start",
                                transitions=[Transition(to_step="x")]),
                   WorkflowStep(type="Router", name="x"),
                   WorkflowStep(type="EndEvent", name="done")])
    with pytest.raises(WorkflowEmitError, match="no routes"):
        definition(w)


def test_a_parallel_block_with_no_branches_is_refused():
    w = _wf(steps=[WorkflowStep(type="StartEvent", name="start",
                                transitions=[Transition(to_step="x")]),
                   WorkflowStep(type="ParallelBlock", name="x",
                                transitions=[Transition(to_step="done")]),
                   WorkflowStep(type="EndEvent", name="done")])
    with pytest.raises(WorkflowEmitError, match="no branches"):
        definition(w)


def test_a_transition_is_a_different_document_depending_on_who_leaves_it():
    """Three shapes, not two. The list-vs-singular asymmetry was already known (§25);
    the INNER asymmetry is what the valid file added."""
    d = definition(_rebuild_the_valid_definition())
    start = _step_of(d, "StartEvent")["transition"]
    auto = _step_of(d, "Automation")["transition"]
    task = _step_of(d, "UserTask")["transitions"][0]
    assert set(start) == {"toStep", "labelDistance", "labelOffset", "bendPoints", "name"}
    assert set(auto) == set(start) | {"label"}
    assert set(task) == set(auto) | {
        "icon", "requiredRole", "userTaskCompletionRequired", "validations",
        "behaviorOnTransition", "showWaitDialog", "transitionParameters"}
    assert task["behaviorOnTransition"] == "KEEP_DATA"
    assert task["userTaskCompletionRequired"] is True


def test_the_docs_name_and_the_wire_string_are_not_the_same():
    """The whole argument for harvesting rather than reading. The builder and
    `docs/Design/workflows/` both call it "Start from Empty Selection"; the product
    writes `START_FROM_NOTHING`. Our literal came from the docs and was wrong."""
    got = _step_of(definition(_wf()), "StartEvent")
    assert got["startupContext"]["contextType"] == "START_FROM_NOTHING"
    assert got["startupContext"] == _step_of(WANT, "StartEvent")["startupContext"]


@pytest.mark.parametrize("ctx", ["START_FROM_COMPLETED_BATCH",
                                 "START_FROM_SELECTED_PARENT"])
def test_an_unmeasured_start_context_is_refused_not_guessed(ctx):
    """One measured disagreement between the docs' vocabulary and the wire's is enough
    to distrust the rest of the enum. Assuming the other three happen to match would be
    assuming the exception is the rule."""
    with pytest.raises(WorkflowEmitError, match="no MEASURED wire spelling"):
        definition(_wf(start_context=ctx))


def test_a_start_event_without_a_context_is_refused():
    """`start_context` sat on the IR unemitted for two days — settable, validated, and
    silently dropped on the way to the wire. Worse than refusing it."""
    with pytest.raises(WorkflowEmitError, match="no start_context"):
        definition(_wf(start_context=None))


def test_refs_are_name_paths_not_uuids():
    """The convention that makes this layer cheap. If a UUID ever appears here, D3's
    minting has leaked into a layer that does not use it."""
    got = definition(_wf(admin_role="DataSteward"))
    assert got["workflowAdminRole"] == {"ref": ["DataSteward"]}


def test_a_root_entity_is_an_object_not_a_ref():
    """`cardinality` and `semQLAlias` have no analogue in a bare ref, so the old
    `{"ref": [...]}` emission was never a near-miss."""
    got = definition(_wf(root_entities=["Party"]))["rootEntities"]
    assert got == [{"name": "Party", "entity": {"ref": ["Party"]},
                    "cardinality": "SINGLE_RECORD", "semQLAlias": "Party",
                    "displayCard": None, "childEntities": []}]
    assert set(got[0]) == set(WANT["rootEntities"][0])


def test_a_plain_entity_name_still_authors_a_root_entity():
    """`root_entities: [Party]` keeps working. Every field the object adds has a
    measured default, so making authors restate the name would be ceremony."""
    from agent.ir.schema import RootEntity
    a = definition(_wf(root_entities=["Party"]))["rootEntities"]
    b = definition(_wf(root_entities=[RootEntity(entity="Party")]))["rootEntities"]
    assert a == b


def test_a_stepper_ref_is_two_parts_because_the_entity_owns_it():
    w = _wf(steps=[WorkflowStep(type="UserTask", name="t", entity="Party",
                                stepper="AuthorParty",
                                my_tasks_collection="ReviewColl")])
    s = definition(w)["steps"][0]
    assert s["stepper"] == {"ref": ["Party", "AuthorParty"]}
    assert s["myTasksConfiguration"]["collection"] == {"ref": ["Party", "ReviewColl"]}


def test_a_partial_name_path_is_null_not_a_shorter_path():
    """MEASURED on the lab 2026-08-06, model WorkflowProbe2.

    `_ref` used to drop the falsy parts and keep the rest, so a UserTask with an entity
    and no My Tasks collection emitted `{"ref": ["Party"]}` — a COLLECTION ref pointing
    at an ENTITY. Nothing rejects it: the import returned 204 and the model then could
    not be EXPORTED at all, dying mid-document at `<NGModel` with "Unexpected Error"
    injected where the blob should be. That is the null-stepper failure mode exactly
    (LESSONS §48), reached by a different route.

    With the ref emitted as a proper `null` the same model round-trips, so the null
    collection was never the problem — the truncated path was.
    """
    w = _wf(steps=[WorkflowStep(type="UserTask", name="t", entity="Party",
                                stepper="AuthorParty", my_tasks_collection=None)])
    s = definition(w)["steps"][0]
    assert s["myTasksConfiguration"] == {"collection": None}, \
        "a missing tail must null the WHOLE ref, never shorten it"


def test_an_unset_ref_is_null_not_missing():
    """LESSONS §19 in a JSON register. The sample carries `workflowAdminRole: null`
    explicitly, and a dropped key is a different document from a null one."""
    got = definition(_wf())
    assert "workflowAdminRole" in got and got["workflowAdminRole"] is None


def test_the_transition_asymmetry_is_reproduced_not_normalised():
    """A UserTask carries `transitions` (list), an Automation carries `transition`
    (singular). It looks like an inconsistency and it is what the product wrote."""
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="mail")]),
        WorkflowStep(type="Automation", name="mail", automation_type="EMAIL",
                     to=[Recipient(name="r", role="DataSteward")],
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="UserTask", name="done", entity="Party", stepper="AuthorParty")])
    steps = {s["name"]: s for s in definition(w)["steps"]}
    assert "transition" in steps["mail"] and "transitions" not in steps["mail"]
    assert "transitions" in steps["done"] and "transition" not in steps["done"]


# ------------------------------------------------------------------ the SLA
def test_the_sla_lands_in_minutes_with_its_escalation():
    """The deadline and escalation behaviour that sat at "unverified" across the
    requirements until the builder was opened. Native, and configured."""
    w = _wf(steps=[WorkflowStep(
        type="UserTask", name="t", entity="Party", stepper="AuthorParty",
        time_limit=TaskTimeLimit(max_duration_minutes=2880, notify_admin=True,
                                 notify_role="DataSteward"))])
    tl = definition(w)["steps"][0]["taskTimeLimitNotifications"]
    assert tl["maxDurationMinutes"] == 2880          # 48h, stated in MINUTES
    assert tl["notifyAdmin"] is True
    assert tl["notifyRole"] == {"ref": ["DataSteward"]}


# --------------------------------------------------- refusals, not approximations
def test_an_automation_without_a_type_is_refused():
    w = _wf(steps=[WorkflowStep(type="Automation", name="a")])
    with pytest.raises(WorkflowEmitError, match="automation_type"):
        definition(w)


def test_an_email_with_no_recipients_is_refused():
    w = _wf(steps=[WorkflowStep(type="Automation", name="a", automation_type="EMAIL")])
    with pytest.raises(WorkflowEmitError, match="recipients"):
        definition(w)


def test_a_submit_automation_may_carry_a_null_integration_job():
    """The pre-harvest emitter REFUSED a SUBMIT_DATA with no integration job, on the
    reasoning that "which job it runs is the whole point". harvest/workflow-hardening-
    constructs.json refutes that: the product's own SUBMIT step carries `integrationJob`
    null and `submitUserExpression` set. Refusing a shape the product writes is authoring,
    not measuring — so it is emitted, null and all."""
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="a")]),
        WorkflowStep(type="Automation", name="a", automation_type="SUBMIT_DATA",
                     submit_user_expression="test",
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="EndEvent", name="done")])
    got = _step_of(definition(w), "Automation")
    assert got["type"] == "SUBMIT"                       # wire string, not "SUBMIT_DATA"
    assert got["integrationJob"] is None
    assert got["submitUserExpression"] == "test"
    assert got["rootEntity"] is None


def test_a_user_task_without_an_entity_is_refused():
    w = _wf(steps=[WorkflowStep(type="UserTask", name="t")])
    with pytest.raises(WorkflowEmitError, match="entity"):
        definition(w)


def test_a_user_task_without_a_stepper_is_refused():
    """MEASURED on the lab by bisection. A null `stepper` IMPORTS AT 204 and then makes
    the model UNEXPORTABLE — the re-export dies mid-document with "Unexpected Error"
    written where NGModel should be, leaving truncated XML that will not parse.

    Start/End events alone export fine and so does an EMAIL Automation, so the null
    stepper is the whole cause; with a real stepper the same workflow round-trips
    exactly. A task's purpose IS to open a stepper, so null is not a lesser version of
    one — it is a dangling dereference the export serializer walks into.
    """
    w = _wf(steps=[WorkflowStep(type="UserTask", name="t", entity="Party")])
    with pytest.raises(WorkflowEmitError, match="stepper"):
        definition(w)


def test_the_unattested_wire_spellings_are_labelled():
    """EMAIL and SUBMIT_DATA have been seen in exports. The other three are named for the
    fields the builder exposes, which is a guess — recorded in one place with a label
    rather than spread through the emitter and forgotten."""
    from agent.compile.emit_workflow import UNATTESTED_WIRE_TYPES, WIRE_TYPE
    assert "EMAIL" not in UNATTESTED_WIRE_TYPES
    assert "SUBMIT_DATA" not in UNATTESTED_WIRE_TYPES
    assert UNATTESTED_WIRE_TYPES == set(WIRE_TYPE) - {"EMAIL", "SUBMIT_DATA"}


# ================= the hardening constructs, key-for-key against the 2nd export ========
def _hstep(x_type):
    if HARDENING is None:
        pytest.skip("harvest/workflow-hardening-constructs.json not present "
                    "(measurement file, not shipped in the public export)")
    return next(s for s in HARDENING["steps"] if s["x-type"] == x_type)


def _rebuild_the_hardening_definition() -> Workflow:
    """The hardening export, expressed in the IR. If this drifts from the file the emitter
    has stopped reproducing the product's own Router / ParallelBlock / SUBMIT / SELECTION
    shapes. `initiatorRequiredRole` on the StartEvent is the ONE field this rebuild cannot
    carry (the emitter hardcodes it null, as the valid export had it) — so the StartEvent
    is compared at the `startupContext` granularity, which is the START_FROM_SELECTION
    construct itself, rather than whole."""
    from agent.ir.schema import Branch, RootEntity, Route
    return Workflow(
        name="Workflow_Hardening", label="Workflow_ Hardening",
        root_entities=[RootEntity(entity="Product",
                                  display_card="ProductDisplayCard")],
        start_context="START_FROM_SELECTION", selection_authored_entity="Product",
        steps=[
            WorkflowStep(type="StartEvent", name="StartEvent_step",
                         label="Start Event_step",
                         transitions=[Transition(to_step="Router_step")]),
            WorkflowStep(type="Router", name="Router_step", label="Router_step",
                         routes=[
                             Route(to_step="ParallelBlock_step", name="If_potato",
                                   label="If_potato", condition=':VAR_VEGGIE="potato"'),
                             Route(to_step="Automation_Step", name="if_tomato",
                                   label="If_tomato", condition=':VAR_VEGGIE="tomato"'),
                         ]),
            WorkflowStep(type="ParallelBlock", name="ParallelBlock_step",
                         label="Parallel Block_step",
                         branches=[
                             Branch(name="branch1", label="Branch1",
                                    icon="images://default/DOC.svg"),
                             Branch(name="branch2", label="Branch2",
                                    icon="images://default/PDF.svg"),
                         ],
                         transitions=[Transition(to_step="endEvent_step",
                                                 name="outgoing")]),
            WorkflowStep(type="Automation", name="Automation_Step",
                         label="Automation_ Step", automation_type="SUBMIT_DATA",
                         submit_user_expression="test",
                         transitions=[Transition(to_step="endEvent_step",
                                                 name="outgoing", label="Outgoing")]),
            WorkflowStep(type="EndEvent", name="endEvent_step"),
        ])


def _hemit(x_type):
    d = definition(_rebuild_the_hardening_definition())
    return next(s for s in d["steps"] if s["x-type"] == x_type)


def test_a_router_reproduces_the_harvested_shape_exactly():
    """A Router fans out through `routes`, each a conditional edge with a SemQL
    `condition` and the layout defaults every edge carries. NO `transition`."""
    bad = _diff(_hemit("Router"), _hstep("Router"))
    assert bad == [], "\n".join(bad)
    r = _hemit("Router")
    assert "transition" not in r and "transitions" not in r
    assert [rt["condition"] for rt in r["routes"]] == [
        rt["condition"] for rt in _hstep("Router")["routes"]]


def test_a_parallel_block_reproduces_the_harvested_shape_exactly():
    """Concurrent `branches`, each with its own icon and (possibly empty) `steps`, and a
    SINGULAR `transition` where they rejoin — the 5-key `_edge`, no label."""
    bad = _diff(_hemit("ParallelBlock"), _hstep("ParallelBlock"))
    assert bad == [], "\n".join(bad)
    pb = _hemit("ParallelBlock")
    assert "label" not in pb["transition"]            # a ParallelBlock edge is _edge
    assert [b["icon"] for b in pb["branches"]] == [
        "images://default/DOC.svg", "images://default/PDF.svg"]


def test_a_parallel_block_branch_with_nested_steps_is_refused():
    """The harvested branches are EMPTY, so an in-branch step's shape is unattested —
    refused rather than emitted with a guessed serialization."""
    from agent.ir.schema import Branch
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="pb")]),
        WorkflowStep(type="ParallelBlock", name="pb",
                     branches=[Branch(name="b1", steps=[
                         WorkflowStep(type="UserTask", name="nested", entity="Party",
                                      stepper="AuthorParty")])],
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="EndEvent", name="done")])
    with pytest.raises(WorkflowEmitError, match="nested step"):
        definition(w)


def test_a_submit_automation_reproduces_the_harvested_shape_exactly():
    """The §58 submit path. `type` is SUBMIT (not SUBMIT_DATA); `submitUserExpression`
    carries; the email-only fields are null, not the `""` an EMAIL automation writes."""
    bad = _diff(_hemit("Automation"), _hstep("Automation"))
    assert bad == [], "\n".join(bad)
    a = _hemit("Automation")
    assert a["type"] == "SUBMIT"
    assert a["submitUserExpression"] == "test"
    assert a["subject"] is None and a["replyTo"] is None and a["body"] is None


def test_start_from_selection_reproduces_the_harvested_startup_context():
    """The 'open the flagged record' start. It differs from START_FROM_NOTHING only in
    `contextType` and a set `authoredEntity`; here the wire string IS the docs' name,
    which is exactly why it had to be measured rather than assumed."""
    got = _hemit("StartEvent")["startupContext"]
    assert got == _hstep("StartEvent")["startupContext"]
    assert got["contextType"] == "START_FROM_SELECTION"
    assert got["authoredEntity"] == {"ref": ["Product"]}


def test_start_from_selection_carries_its_condition_and_source():
    """The filter that picks WHICH record, and the pool it selects from — both settable,
    both landing in `startupContext`."""
    w = _wf(start_context="START_FROM_SELECTION",
            selection_authored_entity="Party",
            condition_on_selection="HasSuggestedMerge = '1'",
            selection_source_type="GOLDEN_DATA")
    ctx = _step_of(definition(w), "StartEvent")["startupContext"]
    assert ctx["authoredEntity"] == {"ref": ["Party"]}
    assert ctx["conditionOnSelection"] == "HasSuggestedMerge = '1'"
    assert ctx["selectionSourceType"] == "GOLDEN_DATA"
    assert ctx["contextType"] == "START_FROM_SELECTION"


def test_start_from_selection_with_no_authored_entity_is_refused():
    """A selection context opens an EXISTING record; the harvested one carries
    `authoredEntity` set. With none there is nothing to select — refused, not emitted
    with a null the product never wrote for a SELECTION."""
    with pytest.raises(WorkflowEmitError, match="selection_authored_entity"):
        definition(_wf(start_context="START_FROM_SELECTION"))


@pytest.mark.parametrize("kind", ["CALL_PROCEDURE", "DELETE_DATA", "SET_METADATA"])
def test_an_unharvested_automation_type_is_refused_with_the_way_out(kind):
    """DELETE and DATABASE_PROCEDURE `type` strings are NOT in any export. SUBMIT_DATA
    proved the label and the wire differ ("Submit Data" -> SUBMIT), so the rest cannot be
    inferred from the builder's labels — refused, naming the D8 harvest loop."""
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="a")]),
        WorkflowStep(type="Automation", name="a", automation_type=kind,
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="EndEvent", name="done")])
    with pytest.raises(WorkflowEmitError, match="NEVER appeared in an export"):
        definition(w)


def test_a_router_workflow_validates_as_a_connected_graph():
    """IR-028 must see a Router's `routes` as edges, or every step downstream of one
    reports 'no path from any StartEvent' and the router itself 'no path to any
    EndEvent'."""
    from agent.ir.schema import Branch, Route
    w = Workflow(
        name="RW", root_entities=["Party"],
        start_context="START_FROM_EMPTY_SELECTION",
        steps=[
            WorkflowStep(type="StartEvent", name="start",
                         transitions=[Transition(to_step="router")]),
            WorkflowStep(type="Router", name="router", routes=[
                Route(to_step="pb", name="r1", condition="1=1"),
                Route(to_step="done", name="r2", condition="1=2")]),
            WorkflowStep(type="ParallelBlock", name="pb",
                         branches=[Branch(name="b1")],
                         transitions=[Transition(to_step="done")]),
            WorkflowStep(type="EndEvent", name="done")])
    assert not [i for i in validate(_ir_with(w)) if i.rule == "IR-028"]


def test_a_router_route_to_nowhere_is_a_dangling_edge():
    from agent.ir.schema import Route
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="router")]),
        WorkflowStep(type="Router", name="router", routes=[
            Route(to_step="ghost", name="r1", condition="1=1"),
            Route(to_step="done", name="r2", condition="1=2")]),
        WorkflowStep(type="EndEvent", name="done")])
    iss = [i for i in validate(_ir_with(w)) if i.rule == "IR-028"]
    assert any("not a step here" in i.message and "ghost" in i.message for i in iss)


# ---------------------------------------------- IR-028: a connected graph (the rule
# the sample could NOT supply, because the sample breaks it)
def test_the_harvested_sample_would_itself_be_refused():
    """The operator's draft has no Start and no End event, and the builder reports both
    as errors. So the file proves the FIELD grammar while being an invalid workflow —
    evidence about spelling is not evidence about validity, and treating it as a
    template would have shipped that defect into every generated workflow.
    """
    raw = DRAFT["workflowDefinitions"][0]
    kinds = {s["x-type"] for s in raw["steps"]}
    assert "StartEvent" not in kinds and "EndEvent" not in kinds
    w = _wf(steps=[WorkflowStep(type="UserTask", name="assignment", entity="Party",
                                stepper="AuthorParty"),
                   WorkflowStep(type="Automation", name="autoTest",
                                automation_type="EMAIL",
                                to=[Recipient(name="r", role="DataSteward")],
                                transitions=[Transition(to_step="assignment")])])
    rules = {i.rule for i in validate(_ir_with(w))}
    assert "IR-028" in rules


def test_a_well_formed_workflow_validates_silently():
    assert not [i for i in validate(_ir_with(_wf())) if i.rule == "IR-028"]


def test_an_unreachable_step_is_refused():
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="UserTask", name="orphan", entity="Party",
                     stepper="AuthorParty",
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="EndEvent", name="done")])
    iss = [i for i in validate(_ir_with(w)) if i.rule == "IR-028"]
    assert any("no path from any StartEvent" in i.message and "orphan" in i.where
               for i in iss)


def test_a_step_that_reaches_no_end_is_refused():
    """Fails differently from unreachable: the step DOES run, and the instance then
    never completes, so its tasks stay open forever."""
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="limbo")]),
        WorkflowStep(type="UserTask", name="limbo", entity="Party",
                     stepper="AuthorParty"),
        WorkflowStep(type="EndEvent", name="done")])
    iss = [i for i in validate(_ir_with(w)) if i.rule == "IR-028"]
    assert any("no path to any EndEvent" in i.message for i in iss)


def test_a_dangling_transition_is_refused():
    """Nothing resolves these at import — a name-path ref lands in the model intact and
    fails at runtime, which is the opposite of a UUID ref's failure mode."""
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="start",
                     transitions=[Transition(to_step="nowhere")]),
        WorkflowStep(type="EndEvent", name="done")])
    iss = [i for i in validate(_ir_with(w)) if i.rule == "IR-028"]
    assert any("not a step here" in i.message for i in iss)


def test_duplicate_step_names_are_refused():
    w = _wf(steps=[
        WorkflowStep(type="StartEvent", name="dup",
                     transitions=[Transition(to_step="done")]),
        WorkflowStep(type="EndEvent", name="dup"),
        WorkflowStep(type="EndEvent", name="done")])
    assert any("duplicate step name" in i.message
               for i in validate(_ir_with(w)) if i.rule == "IR-028")


def test_a_batch_started_workflow_needs_root_entities():
    """START_FROM_COMPLETED_BATCH is the context that needs nobody to click anything —
    it watches the ROOT ENTITIES. With none named there is nothing to watch."""
    w = _wf(start_context="START_FROM_COMPLETED_BATCH", root_entities=[])
    assert any("root entities" in i.message
               for i in validate(_ir_with(w)) if i.rule == "IR-028")
    ok = _wf(start_context="START_FROM_COMPLETED_BATCH", root_entities=["Party"])
    assert not [i for i in validate(_ir_with(ok)) if i.rule == "IR-028"]


# --------------------------------- the two rules the DRAFT could not teach (rules 3, 4)
def test_the_entities_section_may_not_be_empty():
    """IR-028 rule 3, straight off the builder's validation panel on 2026-08-06. NOT
    conditional on the start context — the draft had no context set at all and was still
    refused for this. `rootEntities` is what the workflow's dataset is made of."""
    w = _wf(root_entities=[])
    assert any("no root entities declared" in i.message
               for i in validate(_ir_with(w)) if i.rule == "IR-028")


def test_a_tasks_stepper_entity_must_be_declared_in_the_entities_section():
    """IR-028 rule 4, and the builder's own words:

        "The root entity and its child entities manipulated in the selected stepper
         must be declared in the Entities section"

    A constraint BETWEEN two sections that look independent — naming a stepper on a task
    silently obliges the Entities list, and nothing in the JSON hints at it. Caught here
    because the alternative is learning it from the builder, which is only reachable
    after an Import-Replace has already destroyed the edition.
    """
    w = _wf(root_entities=["Contact"])          # task authors Party, not Contact
    hits = [i for i in validate(_ir_with(w))
            if i.rule == "IR-028" and "root entities" in i.message]
    assert hits, [i.message for i in validate(_ir_with(w))]
    assert "Party" in hits[0].message


def test_a_root_entity_must_exist_in_the_model():
    w = _wf(root_entities=["NoSuchEntity"])
    assert any("not an entity of this model" in i.message
               for i in validate(_ir_with(w)) if i.rule == "IR-028")


# ------------------------------------------------------------- end to end
def test_a_workflow_reaches_the_emitted_xml():
    """The whole point: NGModel is built from the IR, so a workflow in the spec is a
    workflow in the file that gets imported."""
    from xml.etree import ElementTree as ET

    from agent.compile.emit import emit
    ir = _ir_with(_wf(name="ReviewQueue", admin_role="DataSteward"))
    root = ET.fromstring(emit(ir.model_ir, platform_version="x",
                              repository_version="y", certify=ir.certify))
    body = json.loads(root.find("NGModel").text)
    assert [d["name"] for d in body["workflowDefinitions"]] == ["ReviewQueue"]
    assert body["x-spec-version"] == "1.12"
