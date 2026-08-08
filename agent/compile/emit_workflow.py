"""IR workflows -> the `workflowDefinitions` array inside NGModel.

The whole layer lives in a JSON blob hanging off the export root, not in the XML tree —
`<workflows>` and `<humanWorkflows>` are empty in all eight corpus exports, which is why
workflows were twice judged non-generatable. `envelope.py` has been emitting the
container hardcoded and empty since the first import:

    {"e2eTests": [], "workflowDefinitions": [], "x-spec-version": "1.12"}

That `[]` was never a placeholder. It is the container.

**Refs here are NAME-PATHS, not UUIDs** — `{"ref": ["Person", "AuthorPersons"]}` — so
D3's division of labour does not apply: there is nothing to mint and nothing to wire.
That is what makes this the cheapest layer in the model to generate, and it is why the
work is JSON assembly rather than compilation.

Every shape below is MEASURED from `harvest/workflow-definition-valid.json` — the first
definition the product has exported for us that its own builder calls valid (operator
present, D12, 2026-08-06). The earlier `harvest/workflow-definition.json` is the DRAFT
and is kept only as the evidence for §48: it attests every field spelling while being a
document the builder rejects with four errors.

WHAT THE DRAFT COST, because it is the argument for harvesting a VALID artefact rather
than any artefact. The draft contains no Start Event and no End Event — precisely the two
step types this module then invented — and the invention had a specific failure:

    StartEvent   emitted with label, icon and a transitions LIST.
                 Real shape: NO icon, a SINGULAR transition, and two objects nobody had
                 seen — `startupContext` (which is where the start context lives) and
                 `startupParameters`.
    EndEvent     emitted with label, icon and transitions.
                 Real shape: {x-type, name, position}. Three keys.
    rootEntities emitted as bare `{"ref": [...]}`.
                 Real shape: an OBJECT with cardinality and semQLAlias.

The fallback that produced those was `_plain()`, on the reasoning that "only the fields
EVERY step carries" must be safe. The valid file destroys that reasoning: a StartEvent
carries nine keys and an EndEvent carries three, so there is no common shape.

Router and ParallelBlock were refused for the same reason until a second product export —
`harvest/workflow-hardening-constructs.json` (operator-built in the Workflow Builder,
exported over REST, D12) — attested both, along with the SUBMIT automation and the
START_FROM_SELECTION start context. Each is now emitted key-for-key against that file;
what remains unharvested (the DELETE / DATABASE_PROCEDURE automation `type` strings,
START_FROM_COMPLETED_BATCH, START_FROM_SELECTED_PARENT) is still refused, each refusal
naming the same harvest loop as the way out.
"""
from __future__ import annotations

from agent.ir.schema import Workflow, WorkflowStep

#: The blob's own version, carried at both the envelope and the definition level.
SPEC_VERSION = "1.12"


class WorkflowEmitError(RuntimeError):
    """A construct the corpus does not attest. Refused rather than approximated."""


def _ref(*path: str | None) -> dict | None:
    """`{"ref": [...]}`, or None. A null ref is a SLOT, not an omission: the sample
    carries `"workflowAdminRole": null` explicitly, and dropping the key is a different
    document from setting it null (LESSONS §19).

    ALL OR NOTHING, and that is the whole point of this function. It used to filter the
    falsy parts out and keep whatever was left, so a two-part path with a missing tail —
    `_ref("Party", None)` for a UserTask whose My Tasks collection is unset — came out as
    `{"ref": ["Party"]}`: a collection ref pointing at an entity. Nothing rejects that.
    It imported at 204 and then killed the EXPORT, the model dying mid-document at
    `<NGModel` with "Unexpected Error" injected where the blob should be, exactly like
    the null stepper does (OBSERVED on the lab 2026-08-06, model WorkflowProbe2).

    So a partial path is never a lesser version of a path; it is a dangling ref wearing
    the costume of one. An unset part makes the WHOLE ref null.
    """
    if any(not p for p in path):
        return None
    return {"ref": [p for p in path if p]} if path else None


#: IR name (the DOCS' and the builder's name) -> the string the product writes.
#:
#: EXACTLY ONE is measured, and it is the one that proves the mapping is not the
#: identity: the builder's "Start from Empty Selection" goes on the wire as
#: `START_FROM_NOTHING`. Our literal came from `docs/Design/workflows/` and was wrong.
#:
#: The remaining two are `None` — deliberately, so that using one is a REFUSAL naming the
#: harvest loop rather than a plausible string that imports at 204 and fails later. One
#: measured disagreement between the docs' vocabulary and the wire's is enough to
#: distrust the rest of the doc-derived enum; guessing that the others happen to match
#: would be assuming the exception is the rule.
#:
#: START_FROM_SELECTION is now MEASURED (harvest/workflow-hardening-constructs.json) and,
#: unlike START_FROM_EMPTY_SELECTION, its wire spelling IS the docs' name — which is
#: exactly why it had to be harvested rather than assumed: EMPTY_SELECTION proved the
#: mapping is not the identity, so SELECTION matching had to be seen, not inferred.
START_CONTEXT_WIRE: dict[str, str | None] = {
    "START_FROM_EMPTY_SELECTION": "START_FROM_NOTHING",     # MEASURED 2026-08-06
    "START_FROM_SELECTION": "START_FROM_SELECTION",         # MEASURED (hardening harvest)
    "START_FROM_COMPLETED_BATCH": None,
    "START_FROM_SELECTED_PARENT": None,
}


def _position(i: int) -> dict:
    """Diagram coordinates. The builder lays steps out visually and the export records
    where they sit; nothing downstream reads them, but the key is present on every step
    in the sample, so it is emitted rather than omitted.

    A simple stagger keeps a generated diagram legible instead of stacking every node at
    the origin. These are floats in the sample and stay floats here.
    """
    return {"x": -130.0 + (i % 4) * 180.0, "y": -210.0 + (i // 4) * 130.0}


def _edge(t) -> dict:
    """The five keys every transition carries, whoever leaves it."""
    return {
        "toStep": _ref(t.to_step),
        "labelDistance": 0.5,
        "labelOffset": 0.0,
        "bendPoints": [],
        "name": t.name,
    }


def _labelled_edge(t) -> dict:
    """`_edge` + label. What an Automation writes."""
    return {**_edge(t), "label": t.label or t.name.replace("_", " ").title()}


def _task_transition(t) -> dict:
    """THIRTEEN keys, and this is where the outcome of a human decision is configured.

    A transition is a different document depending on which step it leaves, which the
    valid export settles and the draft could not:

        StartEvent.transition     5 keys, and NO label
        Automation.transition     6 keys
        UserTask.transitions[]    13

    The list-vs-singular asymmetry was already known (§25); this inner one was not.
    `behaviorOnTransition` and `userTaskCompletionRequired` have runtime meaning — a
    steward's "Done" either requires the task to be complete or it does not — and we
    were emitting neither, so the product was left to default them from nothing.
    """
    return {
        **_labelled_edge(t),
        "icon": None,
        "requiredRole": None,
        "userTaskCompletionRequired": True,
        "validations": [],
        "behaviorOnTransition": "KEEP_DATA",
        "showWaitDialog": True,
        "transitionParameters": {
            "nextTaskAssigneeSupported": False,
            "nextTaskAssigneeRequired": False,
            "descriptionParamSupported": False,
            "commentParamSupported": True,
            "commentParamRequired": False,
            "priorityParamSupported": False,
            "dueDateParamSupported": False,
            "dueDateParamRequired": False,
            "attachmentParamSupported": True,
            "attachmentParamRequired": False,
        },
    }


def _root_entity(re) -> dict:
    """One `rootEntities[]` entry. An OBJECT — we emitted a bare ref until 2026-08-06."""
    return {
        "name": re.name or re.entity,
        "entity": _ref(re.entity),
        "cardinality": re.cardinality,
        # The alias a SemQL expression uses to reach this entity's records. Defaulted to
        # the entity name, which is what the builder does.
        "semQLAlias": re.semql_alias or re.entity,
        "displayCard": _ref(re.display_card),
        # Children are a nesting this compiler does not build yet. Empty is the observed
        # value for a single-entity definition, not a placeholder for one.
        "childEntities": [],
    }


def _user_task(s: WorkflowStep, i: int) -> dict:
    if not s.entity:
        raise WorkflowEmitError(
            f"UserTask {s.name!r} names no entity. A task opens a stepper ON an entity; "
            f"every field of the sample's task is entity-scoped and there is no attested "
            f"shape for one without.")
    if not s.stepper:
        # MEASURED against the lab, 2026-08-06, by bisection. A UserTask with a null
        # `stepper` IMPORTS AT 204 and then makes the model UNEXPORTABLE: the re-export
        # dies mid-document with "Unexpected Error" injected where NGModel should be,
        # leaving truncated XML that will not parse. Start/End events alone export
        # fine, and so does an EMAIL Automation, so the null stepper is the whole cause
        # — with a real stepper the same workflow round-trips exactly.
        #
        # A task's entire purpose is to open a stepper; null is not a lesser version of
        # that, it is a dangling dereference the export serializer walks into. And the
        # 204 is worth noting on its own: it is the fourth time today that an import
        # status has said nothing about whether the model is sound.
        raise WorkflowEmitError(
            f"UserTask {s.name!r} names no stepper. A task opens a stepper on an "
            f"entity, and a null one imports at 204 and then makes the model "
            f"impossible to export at all (OBSERVED on the lab 2026-08-06).")
    return {
        "x-type": "UserTask",
        "name": s.name,
        "label": s.label or s.name,
        "icon": None,
        "position": _position(i),
        "application": _ref(s.application),
        "assigneeRequiredRole": _ref(s.assignee_required_role),
        "assigneeCondition": s.assignee_condition,
        "assigneeCanRelease": s.assignee_can_release,
        "taskType": s.task_type,
        "entity": _ref(s.entity),
        # Two-part name-paths: the stepper and the collection are owned BY the entity,
        # so the path is [entity, thing] and not [thing].
        "stepper": _ref(s.entity, s.stepper),
        "myTasksConfiguration": {"collection": _ref(s.entity, s.my_tasks_collection)},
        "transitions": [_task_transition(t) for t in s.transitions],
        "taskAssignmentNotifications": {
            "enableCandidateNotifications": s.enable_candidate_notifications,
            "enableAssigneeNotifications": s.enable_assignee_notifications,
        },
        # THE SLA. Minutes, and the escalation flags beside it.
        "taskTimeLimitNotifications": {
            "maxDurationMinutes": s.time_limit.max_duration_minutes,
            "notifyCandidatesOrAssignee": s.time_limit.notify_candidates_or_assignee,
            "notifyAdmin": s.time_limit.notify_admin,
            "notifyRole": _ref(s.time_limit.notify_role),
        },
        "taskWorkflowDueDateNotifications": {
            "notifyCandidatesOrAssignee": s.notify_on_due_date,
        },
    }


def _automation(s: WorkflowStep, i: int) -> dict:
    if s.automation_type is None:
        raise WorkflowEmitError(
            f"Automation {s.name!r} has no automation_type. The kinds differ by "
            f"which fields carry meaning, so there is no neutral default.")
    if s.automation_type in UNATTESTED_WIRE_TYPES:
        raise WorkflowEmitError(
            f"Automation {s.name!r} is type {s.automation_type!r}, whose `type` wire "
            f"spelling has NEVER appeared in an export. Only EMAIL (wire "
            f"{WIRE_TYPE['EMAIL']!r}) and SUBMIT_DATA (wire {WIRE_TYPE['SUBMIT_DATA']!r}) "
            f"are attested — and SUBMIT_DATA proves the label and the wire are not the "
            f"same string, so the rest cannot be inferred from the builder's labels.\n"
            f"The way out is the harvest loop, not a guess: build an automation of this "
            f"kind in the Workflow Builder (operator present, D12), export it into "
            f"harvest/, and read the `type` string off the file.")
    if s.automation_type == "EMAIL" and not s.to:
        raise WorkflowEmitError(
            f"EMAIL automation {s.name!r} has no recipients. `to[]` empty sends to "
            f"nobody and fails silently rather than at deploy.")

    # The email-only text fields are a MEASURED per-type shape difference: on the EMAIL
    # automation the product writes them as strings (an unset one is `""`, see
    # workflow-definition-valid.json's `replyTo`); on the SUBMIT automation it writes them
    # `null` (workflow-hardening-constructs.json), because they do not apply. Emitting
    # `""` on a SUBMIT would be a value the product has never written for one.
    is_email = s.automation_type == "EMAIL"

    # `type` goes on the wire via WIRE_TYPE. EMAIL is EMAIL; SUBMIT_DATA is SUBMIT (the
    # builder's label is "Submit Data" but the export writes SUBMIT — measured from
    # harvest/workflow-hardening-constructs.json, LESSONS §51.2 again).
    out = {
        "x-type": "Automation",
        "name": s.name,
        "label": s.label or s.name,
        "icon": None,
        "position": _position(i),
        "type": WIRE_TYPE[s.automation_type],
        "rootEntity": _ref(s.root_entity),
        "conditionForDeletion": s.condition_for_deletion,
        "deleteType": s.delete_type,
        "deleteAuthorExpression": None,
        "integrationJob": _ref(s.integration_job),
        "submitUserExpression": s.submit_user_expression,
        "application": _ref(s.application),
        "replyTo": s.reply_to if is_email else None,
        "senderName": s.sender_name if is_email else None,
        "to": [{"name": r.name, "sourceType": r.source_type,
                "roleValue": _ref(r.role), "semqlValue": r.semql} for r in s.to],
        "recipientMaxCount": s.recipient_max_count,
        "customParameters": [],
        "subject": s.subject if is_email else None,
        "contentType": s.content_type,
        "body": s.body if is_email else None,
        "failOnError": s.fail_on_error,
        "workflowMetadataChanges": [],
        "databaseProcedureName": s.database_procedure_name,
        "databaseProcedureArguments": [],
    }
    # SINGULAR on an Automation, a LIST on a UserTask. Reproduced, not normalised: an
    # automation has one outcome and a task has one per branch.
    if len(s.transitions) > 1:
        raise WorkflowEmitError(
            f"Automation {s.name!r} has {len(s.transitions)} transitions. The product "
            f"writes `transition` SINGULAR here — an automation has one outcome.")
    out["transition"] = _labelled_edge(s.transitions[0]) if s.transitions else None
    return out


#: IR name -> the value the product writes in `type`. Two are directly observed now —
#: EMAIL (workflow-definition-valid.json) and SUBMIT_DATA, whose wire string is SUBMIT
#: not SUBMIT_DATA (workflow-hardening-constructs.json). The other three are named for
#: the fields the builder exposes, and their wire values are GUESSES kept in ONE place
#: with a label rather than spread through the emitter — `_automation` refuses them.
WIRE_TYPE = {
    "EMAIL": "EMAIL",              # MEASURED (workflow-definition-valid.json)
    "SUBMIT_DATA": "SUBMIT",       # MEASURED (workflow-hardening-constructs.json)
    "CALL_PROCEDURE": "CALL_PROCEDURE",
    "DELETE_DATA": "DELETE_DATA",
    "SET_METADATA": "SET_METADATA",
}
#: The ones above whose wire spelling has NOT been seen in an export, and which the
#: emitter therefore refuses. Deploying a workflow using one of these is the experiment
#: that settles it — until then, the D8 harvest loop is the only way in.
UNATTESTED_WIRE_TYPES = frozenset(WIRE_TYPE) - {"EMAIL", "SUBMIT_DATA"}


def _start_event(s: WorkflowStep, i: int, w) -> dict:
    """NINE keys, and every one of them was wrong before the valid export.

    We emitted `label`, `icon` and a `transitions` LIST. The product writes no `icon` at
    all — the only step type that does not — a SINGULAR `transition`, and two objects we
    had never seen: `startupContext` and `startupParameters`.

    `startupContext.contextType` is where the start context lives. `Workflow.start_context`
    sat in the IR unemitted for two days: settable, validated by IR-028, and silently
    dropped on the way to the wire. That is worse than refusing it.
    """
    if len(s.transitions) > 1:
        raise WorkflowEmitError(
            f"StartEvent {s.name!r} has {len(s.transitions)} transitions. The product "
            f"writes `transition` SINGULAR on a start event — there is no attested "
            f"shape for a start that branches.")
    ctx = w.start_context
    if ctx is None:
        raise WorkflowEmitError(
            f"workflow {w.name!r} has a StartEvent but no start_context. "
            f"`startupContext.contextType` is a real value in the one valid definition "
            f"the product has exported; there is no attested null.")
    wire = START_CONTEXT_WIRE.get(ctx)
    if wire is None:
        raise WorkflowEmitError(
            f"start_context {ctx!r} has no MEASURED wire spelling. Only "
            f"START_FROM_EMPTY_SELECTION is attested, and it goes on the wire as "
            f"{START_CONTEXT_WIRE['START_FROM_EMPTY_SELECTION']!r} — the docs' name and "
            f"the product's string are NOT the same, so the other three cannot be "
            f"inferred from the docs either.\n"
            f"The way out is the harvest loop, not a guess: build a workflow with this "
            f"start context in the Workflow Builder (operator present, D12), export it "
            f"into harvest/, and read the spelling off the file.")
    if ctx == "START_FROM_SELECTION" and not w.selection_authored_entity:
        raise WorkflowEmitError(
            f"workflow {w.name!r} starts from a selection but names no "
            f"selection_authored_entity. START_FROM_SELECTION opens an EXISTING record "
            f"(the harvested one carries `authoredEntity` set); with none there is "
            f"nothing to select. Set selection_authored_entity, or use "
            f"START_FROM_EMPTY_SELECTION to author a new record instead.")
    return {
        "x-type": "StartEvent",
        "name": s.name,
        "position": _position(i),
        "label": s.label or s.name,
        "initiatorRequiredRole": None,
        "defaultPriority": "NORMAL",
        # START_FROM_NOTHING leaves `authoredEntity` null and `conditionOnSelection`
        # null, which these defaults reproduce; START_FROM_SELECTION sets both from the
        # workflow. Every other key is constant across both attested contexts.
        "startupContext": {
            "contextType": wire,
            "authoredEntity": _ref(w.selection_authored_entity),
            "selectionSourceType": w.selection_source_type,
            "conditionOnSelection": w.condition_on_selection,
            "integrationJob": None,
            "initiatedAs": None,
            "dataRecordOutputs": [],
            "referenceToParentName": None,
        },
        "startupParameters": {
            "descriptionParamSupported": True,
            "commentParamSupported": True,
            "commentParamRequired": False,
            "priorityParamSupported": True,
            "dueDateParamSupported": False,
            "dueDateParamRequired": False,
            "nextTaskAssigneeSupported": False,
            "nextTaskAssigneeRequired": False,
            "attachmentParamSupported": True,
            "attachmentParamRequired": False,
            "showWaitDialog": True,
        },
        "transition": _edge(s.transitions[0]) if s.transitions else None,
    }


def _end_event(s: WorkflowStep, i: int) -> dict:
    """THREE keys. Not "the common fields minus the ones that do not apply" — three.

    We emitted `label`, `icon` and `transitions` on it. An end event is the one step with
    nowhere to go, and the product does not write those keys at all. Emitting a plausible
    superset is the same mistake as emitting a plausible element name.
    """
    if s.transitions:
        raise WorkflowEmitError(
            f"EndEvent {s.name!r} has {len(s.transitions)} outgoing transition(s). An "
            f"end event terminates the instance and the product writes no transition "
            f"key on one at all.")
    return {"x-type": "EndEvent", "name": s.name, "position": _position(i)}


def _route(r) -> dict:
    """One `routes[]` entry on a Router. `_edge`'s five layout keys, plus `label` and the
    SemQL `condition` that gates the edge. Measured from
    harvest/workflow-hardening-constructs.json."""
    return {
        "toStep": _ref(r.to_step),
        "labelDistance": 0.5,
        "labelOffset": 0.0,
        "bendPoints": [],
        "name": r.name,
        "label": r.label or r.name,
        "condition": r.condition,
    }


def _router(s: WorkflowStep, i: int) -> dict:
    """Router — a conditional fan-out. NO `transition`: every outgoing edge is a `route`
    carrying its own SemQL `condition`. Attested by harvest/workflow-hardening-constructs
    .json; refused before that harvest because no export contained one."""
    if not s.routes:
        raise WorkflowEmitError(
            f"Router {s.name!r} has no routes. A router's whole purpose is to choose an "
            f"outgoing edge by condition; with none it routes nowhere.")
    return {
        "x-type": "Router",
        "name": s.name,
        "position": _position(i),
        "label": s.label or s.name,
        "routes": [_route(r) for r in s.routes],
    }


def _branch(b) -> dict:
    """One `branches[]` entry on a ParallelBlock. `icon` is a display glyph the builder
    always sets. The two harvested branches carry EMPTY `steps`, so the in-branch
    serialization of a populated branch is unattested — a step inside a branch may or may
    not carry the same shape it does at top level, and guessing which is exactly the
    mistake the harvest loop exists to avoid. A non-empty branch is therefore refused."""
    if b.steps:
        raise WorkflowEmitError(
            f"ParallelBlock branch {b.name!r} has {len(b.steps)} nested step(s), whose "
            f"in-branch shape has never appeared in an export (the harvested branches are "
            f"empty). Build one in the Workflow Builder (operator present, D12), export it "
            f"into harvest/, and read the shape off the file before generating it.")
    return {"name": b.name, "label": b.label or b.name, "icon": b.icon, "steps": []}


def _parallel_block(s: WorkflowStep, i: int) -> dict:
    """ParallelBlock — concurrent branches that rejoin at a SINGULAR `transition` (stored
    in `transitions`, like an Automation). Attested by
    harvest/workflow-hardening-constructs.json."""
    if not s.branches:
        raise WorkflowEmitError(
            f"ParallelBlock {s.name!r} has no branches. A parallel block with no lanes "
            f"has nothing to run in parallel.")
    if len(s.transitions) > 1:
        raise WorkflowEmitError(
            f"ParallelBlock {s.name!r} has {len(s.transitions)} transitions. The product "
            f"writes `transition` SINGULAR here — the block rejoins to one step.")
    return {
        "x-type": "ParallelBlock",
        "name": s.name,
        "position": _position(i),
        "label": s.label or s.name,
        "branches": [_branch(b) for b in s.branches],
        "transition": _edge(s.transitions[0]) if s.transitions else None,
    }


def _step(s: WorkflowStep, i: int, w) -> dict:
    if s.type == "UserTask":
        return _user_task(s, i)
    if s.type == "Automation":
        return _automation(s, i)
    if s.type == "StartEvent":
        return _start_event(s, i, w)
    if s.type == "EndEvent":
        return _end_event(s, i)
    if s.type == "Router":
        return _router(s, i)
    if s.type == "ParallelBlock":
        return _parallel_block(s, i)
    raise WorkflowEmitError(
        f"{s.type} {s.name!r} has no emitter. Build one in the Workflow Builder "
        f"(operator present, D12) and export it into harvest/ before generating it.")


def definition(w: Workflow) -> dict:
    """One `workflowDefinitions[]` entry."""
    return {
        "name": w.name,
        "label": w.label or w.name,
        "workflowAdminRole": _ref(w.admin_role),
        "rootEntities": [_root_entity(e) for e in w.root_entities],
        "steps": [_step(s, i, w) for i, s in enumerate(w.steps)],
        "generalProperties": {
            "attachmentMaxFileSize": w.attachment_max_file_size,
            "attachmentMaxFileCount": w.attachment_max_file_count,
            "attachmentMimeTypes": w.attachment_mime_types,
        },
        "retentionPolicy": {
            "retentionType": w.retention.retention_type,
            "retentionDuration": w.retention.duration,
            "retentionTimeUnit": w.retention.time_unit,
        },
        "notifications": {"notifyAdminOnWorkflowDueDate": w.notify_admin_on_due_date},
        "x-spec-version": SPEC_VERSION,
    }


def ng_model(workflows=()) -> dict:
    """The whole NGModel body. With no workflows this is byte-identical to the constant
    `envelope.py` emitted before, so a model without workflows is unchanged."""
    return {
        "e2eTests": [],
        "workflowDefinitions": [definition(w) for w in workflows],
        "x-spec-version": SPEC_VERSION,
    }
