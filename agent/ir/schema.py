"""The IR the LLM actually authors. Sprint 04.

No UUIDs anywhere — objects reference each other by name and the compiler resolves
names to minted UUIDs. That is the whole point of the IR (AGENT_DESIGN.md §0): the
model decides that an entity is fuzzy-matched and that a rule scores 90, while UUID
minting and ref wiring stay in deterministic code.

Structural rules come free from pydantic. The semantic ones — the expensive-to-
discover ones — live in validate.py.
"""
from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.tools.schema_ingest import XDM_TYPES

EntityType = Literal["basic", "id_matched", "fuzzy"]
# OBSERVED across all six models. MANUAL 12, SEMQL 8, UUID 2, SEQUENCE 2 — and the
# golden-ID generator is only ever SEQUENCE (22) or UUID (2).
IdGeneration = Literal["MANUAL", "SEQUENCE", "UUID", "SEMQL"]
GoldenIdGeneration = Literal["SEQUENCE", "UUID"]
Scope = Literal["NONE", "PRE_CONSO", "POST_CONSO"]
EnricherKind = Literal["semql", "form_step", "plugin"]   # plugin observed in gs-customerb2c
DeletePropagation = Literal["RESTRICT", "CASCADE", "SET_NULL", "NONE"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")          # a typo is an error, not a silent drop


class Attribute(_Base):
    name: str
    type: str
    #: Overrides the derived `physicalColName`. Derivation inserts `_` before every
    #: capital, so `AccountClassificationCode` becomes a 27-character column and
    #: `ParentHierarchySourceID` a 27-character one — both past the repository's
    #: 25-CHARACTER LIMIT, which is checked on the GENERATED name and not the declared
    #: one. MEASURED: the real org-hub export hand-sets these (`ADDRESS_LINE1_STD` for
    #: `AddrStreet`, `MELISSA_RESULT_CODE` for the result code), so a shortened physical
    #: name is what the product's own modellers write, not a workaround.
    physical_name: str | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    mandatory: bool = False
    mandatory_scope: Scope = "NONE"
    # An LOV-typed attribute sets `type` to the LOV type's name. xDM has one way to
    # say this — the attribute's datatype ref points at the LOVType — so the IR must
    # not offer a second, unemittable one.
    lov_scope: Scope = "NONE"
    searchable: bool = False
    pk: bool = False


class ComplexTypeMember(_Base):
    """One field of a complex type. Serialized as `DefinitionAttribute`, NOT
    `AtomicAttribute` — see extract.py for what that cost."""
    name: str
    type: str
    #: Same override as `Attribute.physical_name`, and it BITES HARDER here: the
    #: generated column is `<complex attribute prefix>_<this>`, so every member pays
    #: four extra characters. `AddrMelissaResultCode` derives to a 24-character name and
    #: therefore a 28-character column under any of the three address prefixes.
    #: (Melissa here is the product's own address-verification integration — the
    #: Melissa Global Address enricher, docs/Plugins/melissa-global-address-enricher.md
    #: — which is why a result-code member is the natural worked example.)
    physical_name: str | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    mandatory: bool = False
    searchable: bool = True


class ComplexType(_Base):
    name: str
    members: list[ComplexTypeMember]


class ComplexAttribute(_Base):
    name: str
    type: str                                          # -> ComplexType.name
    # The 3-character prefix xDM puts on every physical column this attribute expands
    # into. MUST BE UNIQUE WITHIN THE ENTITY — two complex attributes both starting
    # "Add" cannot both be ADD, and the UI generates ADD then AD2. Derived when unset;
    # set it explicitly to control the physical column names.
    physical_prefix: str | None = None


class LOVValue(_Base):
    code: str
    label: str                                         # there is NO <value> element


class LOVType(_Base):
    name: str
    values: list[LOVValue]


class UserDefinedType(_Base):
    """A model-declared type narrowing a built-in, e.g. URLString = String(2000)."""
    name: str
    base_type: str
    length: int | None = None
    precision: int | None = None
    scale: int | None = None


class FunctionArgument(_Base):
    name: str
    position: int = 1
    mandatory: bool = True
    array: bool = False


class SqlFunction(_Base):
    """A database function declared to the model so SemQL will accept it.

    SemQL passes UNKNOWN function names straight through to the database — the editor
    warns and compiles anyway (LESSONS §6). Declaring a function here is what makes it
    legitimate, and what lets `agent/tools/semql.py` tell a real custom function from
    a fabricated one like `SEM_METAPHONE`.

    `schema` qualifies the function (`HUB_SCHEMA_DEV.SHARED`); leave it null for a
    native database function such as PostgreSQL's `age`.
    """
    name: str
    schema_name: str | None = None
    categories: str | None = None
    aggregate: bool = False
    procedure: bool = False
    description: str | None = None
    arguments: list[FunctionArgument] = Field(default_factory=list)


class Publisher(_Base):
    name: str
    code: str                                          # uppercase; see rule 6
    label: str | None = None
    active: bool = True


class UniqueKey(_Base):
    """A post-consolidation uniqueness constraint over one or more attributes.

    MEASURED from `harvest/CustomerB2CDemo.workflow.xml`: one `UniqueKey` with three
    `KeyAttribute` children, each carrying `posInKey` plus an `abstractAttribute` ref.
    `validationScope` is POST_CONSO there and the block library records that as its
    default — the constraint is about the GOLDEN record, so a pre-consolidation scope
    would test the wrong rows.

    `attributes` names entity attributes. A REFERENCE ROLE is also nameable — the FK
    column is a real attribute of the child entity — but every measured `KeyAttribute`
    points at an `AtomicAttribute`, so a role-valued member is an unmeasured REF TARGET
    inside a measured element shape. Flagged rather than assumed.
    """
    name: str
    attributes: list[str]
    label: str | None = None
    validation_scope: Scope = "POST_CONSO"
    error_message: str | None = None


class Entity(_Base):
    name: str
    type: EntityType
    label: str | None = None
    # No entity-level equivalent in xDM: records are titled by a DISPLAY CARD. Carried
    # here as the design intent ("which attribute names a record?") and compiled into
    # the entity's default display card in sprint 07. Do NOT emit it as an attribute.
    subject_name: str | None = None
    attributes: list[Attribute] = Field(default_factory=list)
    complex_attributes: list[ComplexAttribute] = Field(default_factory=list)
    unique_keys: list[UniqueKey] = Field(default_factory=list)

    # --- ID generation. MANDATORY at deploy time, and invisible until then.
    # The importer accepts an entity with these null; `LogicalModelFactory
    # .createIdGenerationDescriptor` then NPEs on `IdGenerationType.ordinal()` and the
    # deploy dies with a bare 500. OBSERVED 2026-08-04.
    #
    # Both are set on EVERY entity in all six models, including BASIC ones that have
    # no golden ID of their own. Defaults are the corpus majority: the source supplies
    # the master ID, xDM sequences the golden ID.
    id_generation: IdGeneration = "MANUAL"
    id_sequence_starts_with: int = 1
    golden_id_generation: GoldenIdGeneration = "SEQUENCE"
    golden_id_sequence_starts_with: int = 1
    #: Required when `id_generation == "SEMQL"`, and must be absent otherwise.
    id_expression: str | None = None

    # --- Historization. Per-entity change history, and it is NOT BACK-FILLABLE:
    # it records from the moment it is enabled, and changing it needs a redeploy. So it
    # is a decision taken BEFORE the first production load or not at all, which is
    # exactly the kind of thing that must be stated in the IR rather than hardcoded.
    # Both were pinned true in the emitter until 2026-08-06; the corpus attests
    # `historizeMaster` false (blocks.yaml records false as its modal value), and a
    # basic reference-data entity carrying full master history is volume nobody chose.
    #
    # On a BASIC entity it is not a preference at all — it is undefined. A basic entity
    # has no master records to historize, and the Application Builder's Validation view
    # says so as an ERROR:
    #
    #     Could not have Historize Master Records on Entity Opportunity because it is
    #     a Basic entity
    #
    # Measured: `historizeMaster` is false on 16 of 16 BASIC entities in the
    # product-authored corpus, and true on 5 of 6 FUZZY_MATCHED ones. So the DEFAULT is
    # type-dependent, and only the default — an author who writes `historize_master:
    # true` on a basic entity has said something wrong rather than said nothing, and
    # IR-034 refuses it instead of this quietly disagreeing with them.
    historize_golden: bool = True
    historize_master: bool = True

    @model_validator(mode="after")
    def _historize_master_default_follows_the_type(self):
        if self.type == "basic" and "historize_master" not in self.model_fields_set:
            object.__setattr__(self, "historize_master", False)
        return self


class Reference(_Base):
    name: str
    from_entity: str                                   # child
    to_entity: str                                     # parent
    from_role: str | None = None
    to_role: str | None = None
    #: Overrides the derived `physicalName` / `toRolePhysicalName`. MEASURED in the real
    #: org-hub export, where the product itself truncates at 25 characters
    #: (`ORGANIZATIONS_ORGANIZATIO`, `PARENT_ORGANIZATION_GOLDE`) and its modellers
    #: shorten by hand (`ORG_CUST_HIER_PARENT_ORG`, `PARENT_ORG_GOLDEN_ID`).
    #:
    #: `to_role_physical` is the one that reaches the INTEGRATION CONTRACT: the loader
    #: writes `F_`, `FP_` and `FS_` prefixed onto it, so it is what a source file's
    #: column headers have to say. Deriving it from a long role name silently changes
    #: the columns every publisher must send.
    physical_name: str | None = None
    to_role_physical: str | None = None
    one_to_many: bool = False
    delete_propagation: DeletePropagation = "RESTRICT"
    validation_scope: Scope = "PRE_CONSO"


class EntityGrant(_Base):
    """What a role may do to one entity."""
    entity: str
    default_access: Literal["READ", "READ_WRITE"] = "READ"
    create: bool = False
    delete: bool = False
    remove: bool = False
    export: bool = False
    checkout: bool = False
    filter: str | None = None                          # SemQL row filter
    description: str | None = None


class Role(_Base):
    """A ModelPrivGrant: a named role and everything it may do.

    `role_name` is the string the application layer's `required_role` fields point at,
    so a role granted here is the vocabulary those fields draw from.
    """
    name: str
    role_name: str
    label: str | None = None
    description: str | None = None
    data_admin: bool = False
    integration_ws: bool = False
    api_publishing_as_user: bool = False
    allow_enrichment_documentation: bool = False
    allow_data_quality_documentation: bool = False
    grants: list[EntityGrant] = Field(default_factory=list)


class Model(_Base):
    name: str
    label: str | None = None
    target_technology: str = "snowflake"               # D13


# ------------------------------------------------------------------- workflows
# MEASURED from harvest/workflow-definition.json — a definition the operator drafted in
# the Workflow Builder specifically so this could be read rather than guessed, plus the
# builder exploration in harvest/WORKFLOWS.md.
#
# Workflows do NOT live in the XML tree. `<workflows>` and `<humanWorkflows>` are empty
# in all eight corpus exports, which is why they were twice judged non-generatable. They
# live in the `NGModel` JSON blob, whose container `envelope.py` has been emitting empty
# and hardcoded since the first import.
#
# Refs there are NAME-PATHS, not UUIDs: {"ref": ["Person", "AuthorPersons"]}. So D3's
# "deterministic code mints the UUIDs" simply does not apply to this layer — the IR is
# already name-based and the emit is JSON assembly.

#: The builder's palette, exactly six.
StepType = Literal["StartEvent", "EndEvent", "UserTask", "Automation",
                   "Router", "ParallelBlock"]
#: The five automation kinds, each evidenced by the fields it carries.
AutomationType = Literal["EMAIL", "SUBMIT_DATA", "CALL_PROCEDURE",
                         "DELETE_DATA", "SET_METADATA"]
#: How a workflow begins. These are the DOCS' names, kept because they are what a person
#: writing an IR would reach for — the builder and `docs/Design/workflows/` both use them.
#: Exactly ONE of them has a measured wire spelling, and it is not the same string:
#: "Start from Empty Selection" goes on the wire as `START_FROM_NOTHING`
#: (harvest/workflow-definition-valid.json, 2026-08-06). `emit_workflow.START_CONTEXT_WIRE`
#: owns the translation and REFUSES the three that have never been exported.
StartContext = Literal["START_FROM_COMPLETED_BATCH", "START_FROM_EMPTY_SELECTION",
                       "START_FROM_SELECTED_PARENT", "START_FROM_SELECTION"]


class RootEntity(_Base):
    """One entry in a definition's `rootEntities` — the builder's **Entities** section.

    An OBJECT, not a ref, and the difference is not cosmetic: `cardinality` and
    `semQLAlias` have no analogue in a bare `{"ref": [...]}`. We emitted the bare form
    until the valid export showed otherwise.

    It is also load-bearing in a way nothing in the JSON hints at. The builder refuses:
    *"The root entity and its child entities manipulated in the selected stepper must be
    declared in the Entities section"* — so a UserTask's stepper entity has to appear
    here, a constraint between two sections that look independent (IR-028 rule 4).
    """
    entity: str
    name: str | None = None                  # defaults to the entity name
    #: ONE value, because one value is what has been measured. The docs describe a second
    #: mode — "Multi Record", authoring a *basket* of records per instance, which also
    #: forces every user task to open on a collection step
    #: (docs/Design/workflows/workflow-create.md) — but they give the UI LABEL, and the
    #: wire string for it has never been exported. `START_FROM_NOTHING` is the standing
    #: proof that a label and a wire string are different things here, so widening this
    #: to a guessed `MULTIPLE_RECORDS` would repeat that mistake with a straight face.
    #: Harvest a multi-record definition and the literal grows.
    cardinality: Literal["SINGLE_RECORD"] = "SINGLE_RECORD"
    semql_alias: str | None = None           # defaults to the entity name
    display_card: str | None = None


class Recipient(_Base):
    """One `to[]` entry on an EMAIL automation."""
    name: str
    source_type: Literal["USERS_FROM_ROLE", "SEMQL"] = "USERS_FROM_ROLE"
    role: str | None = None
    semql: str = ""


class TaskTimeLimit(_Base):
    """The SLA, and it is CONFIGURED rather than built. `maxDurationMinutes` plus the
    notify flags are the deadline badge and the escalation behaviour that were parked as
    unverified across the requirements until the builder was opened. The unit is
    MINUTES — an SLA stated in days has to be converted here, not in prose."""
    max_duration_minutes: int | None = None
    notify_candidates_or_assignee: bool = False
    notify_admin: bool = False
    notify_role: str | None = None


class Transition(_Base):
    """An edge. `to_step` is a step NAME in the same definition."""
    to_step: str
    name: str = "outgoing"
    label: str | None = None


class WorkflowStep(_Base):
    """One node. `type` decides which fields are meaningful, and the emitter refuses a
    combination the corpus does not attest rather than emitting a plausible shape."""
    type: StepType
    name: str
    label: str | None = None

    # --- UserTask. Everything here points at something this compiler already emits,
    # which is what makes a task concrete: it opens a named stepper on a named entity
    # inside a named application, and surfaces through a named collection in My Tasks.
    application: str | None = None
    assignee_required_role: str | None = None
    assignee_condition: str = ""
    assignee_can_release: bool = True
    task_type: str = "DATA_AUTHORING"
    entity: str | None = None
    stepper: str | None = None                 # resolved as [entity, stepper]
    my_tasks_collection: str | None = None     # resolved as [entity, collection]
    enable_candidate_notifications: bool = True
    enable_assignee_notifications: bool = True
    time_limit: TaskTimeLimit = Field(default_factory=TaskTimeLimit)
    notify_on_due_date: bool = False

    # --- Automation
    automation_type: AutomationType | None = None
    reply_to: str = ""
    sender_name: str = ""
    to: list[Recipient] = Field(default_factory=list)
    recipient_max_count: int = 1000
    subject: str = ""
    content_type: str = "HTML_PREFORMATTED"
    body: str = ""
    fail_on_error: bool = True
    integration_job: str | None = None
    database_procedure_name: str | None = None
    delete_type: str = "SOFT_DELETE"
    condition_for_deletion: str | None = None

    #: A UserTask carries `transitions` (a LIST — one per outcome); an Automation
    #: carries `transition` (SINGULAR). That asymmetry is what the product wrote and it
    #: is reproduced rather than normalised.
    transitions: list[Transition] = Field(default_factory=list)


class RetentionPolicy(_Base):
    retention_type: Literal["FOREVER", "DURATION"] = "FOREVER"
    duration: int | None = None
    time_unit: Literal["DAYS", "HOURS", "MINUTES"] = "DAYS"


class Workflow(_Base):
    """One workflow definition.

    `root_entities` is what START_FROM_COMPLETED_BATCH watches, so a batch-started
    workflow with no root entity can never fire.
    """
    name: str
    label: str | None = None
    admin_role: str | None = None
    #: Plain entity names are accepted and widened to `RootEntity` on load, because that
    #: is what every existing IR wrote and the extra fields have measured defaults.
    root_entities: list[RootEntity] = Field(default_factory=list)
    #: Applied to the definition's single StartEvent, where the product actually keeps
    #: it — `startupContext.contextType`. It sat here unused and unemitted until
    #: 2026-08-06: a field the operator could set and the compiler silently dropped.
    start_context: StartContext | None = None
    steps: list[WorkflowStep] = Field(default_factory=list)
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    notify_admin_on_due_date: bool = False
    attachment_max_file_size: int = 10000
    attachment_max_file_count: int = 5
    attachment_mime_types: str = "*"

    @field_validator("root_entities", mode="before")
    @classmethod
    def _widen_names(cls, v):
        """`root_entities: [Party]` keeps working. The list was plain names before the
        valid export showed the wire form is an object, and every field the object adds
        has a measured default — so requiring authors to restate the entity name twice
        would be ceremony, not safety."""
        if isinstance(v, list):
            return [{"entity": x} if isinstance(x, str) else x for x in v]
        return v


class ModelIR(_Base):
    model: Model
    publishers: list[Publisher] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    complex_types: list[ComplexType] = Field(default_factory=list)
    lov_types: list[LOVType] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    # Types the model declares itself. An attribute may be typed by one of these
    # instead of a built-in.
    user_defined_types: list[UserDefinedType] = Field(default_factory=list)
    # Database functions declared to the model. Without a declaration SemQL still
    # passes the name through to the database, so this is the ONLY place the compiler
    # can learn that a non-built-in function is intentional.
    sql_functions: list[SqlFunction] = Field(default_factory=list)
    # Completeness gaps the designer has considered and declined, as "CA-00N:where"
    # keys (see agent/ir/advise.py). A considered "no" must stay closed, or the
    # advisor becomes noise that gets scrolled past.
    acknowledged_gaps: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    #: Workflow definitions. Emitted into NGModel, not into the XML tree.
    workflows: list[Workflow] = Field(default_factory=list)


# --------------------------------------------------------------------- app.yaml
class ComponentProperty(_Base):
    name: str
    value: str = ""          # "" is a real value meaning "inherit the default"
    #: Always accompanies the value in the XML. STRING in every observed instance.
    data_type: str = "STRING"


class DisplayCard(_Base):
    """How a record is TITLED. This is what `Entity.subject_name` compiles into —
    xDM has no entity-level display-name attribute."""
    entity: str
    name: str
    default: bool = True
    primary_text: str                       # SemQL; the record's title
    secondary_text: str | None = None
    supporting_text: str | None = None
    avatar_image: str | None = None
    #: Required when any collection using this card enables grid view — the deployer
    #: refuses "GridList requires DisplayCard primaryImage to be defined" (IR-024).
    primary_image: str | None = None


class TableColumn(_Base):
    name: str
    value: str                              # SemQL expression or attribute name
    component: str                           # semTextField, semIdField, …
    label: str | None = None
    data_type: str = "STRING"
    align: str = "LEFT"
    visible: bool = True
    position: int = 0
    #: Null means "let the grid size it", which is what the product writes by default.
    default_width: str | None = None
    properties: list[ComponentProperty] = Field(default_factory=list)


class Collection(_Base):
    entity: str
    name: str
    default: bool = True
    description: str | None = None
    display_card: str | None = None          # -> DisplayCard.name
    table_allowed: bool = True
    list_allowed: bool = True
    # FALSE by default, matching every collection in the corpus. Grid view is not a
    # free extra: `GridList requires DisplayCard primaryImage to be defined`, and a
    # display card without one fails the DEPLOY, not the import. Enable it only
    # alongside a display card that defines primary_image.
    grid_allowed: bool = False
    #: gridColumns / gridTextPosition / gridTileHeight / gridTileLines / listItemLines
    settings: dict[str, str | None] = Field(default_factory=dict)
    columns: list[TableColumn] = Field(default_factory=list)


class FormContainer(_Base):
    """A tab or a section. Both live in the same `formContainers` container in the XML
    and are distinguished by element name, so `kind` carries that."""
    name: str
    kind: Literal["tab", "section", "section2"] = "tab"
    label: str | None = None
    parent: str | None = None               # -> another container's name
    position: int = 0
    #: How the tab presents itself. LABEL in every observed instance.
    display_as: str = "LABEL"
    #: A SemQL condition gating visibility. "1" — always visible — is the default the
    #: product writes, NOT null.
    visible_value: str = "1"


class FormField(_Base):
    name: str
    value: str                              # SemQL or attribute name
    component: str
    container: str | None = None            # -> FormContainer.name
    label: str | None = None
    data_type: str = "STRING"
    position: int = 0
    relative_width: str | None = None
    #: SemQL gating field visibility; "1" is always-visible, which is what the product
    #: writes by default.
    visible_value: str = "1"
    properties: list[ComponentProperty] = Field(default_factory=list)


class Form(_Base):
    """Containers and fields are FLAT lists joined by name, mirroring the XML: fields
    carry a `parentFormContainer` ref rather than being nested inside one."""
    entity: str
    name: str
    default: bool = False
    description: str | None = None
    documentation: str | None = None
    containers: list[FormContainer] = Field(default_factory=list)
    fields: list[FormField] = Field(default_factory=list)


class EnricherBinding(_Base):
    """A FormStepEnricher is NOT an enricher definition — it is a BINDING that runs an
    existing SemQLEnricher at a form event. All 28 in CORPUS_A point at a SemQLEnricher,
    which sprint 06 already captures; only the trigger belongs here."""
    enricher: str                            # -> Enricher.name on the same entity
    on_form_open: bool = False
    on_data_change: bool = False
    on_button_click: bool = False


class StepperStep(_Base):
    """A step is either a form or a child collection; both are peers inside <steps>.

    `settings` is a deliberate passthrough for CollectionStep's ~40 flat scalar
    toggles (enableChildCopyOnParentEdit and friends). Modelling each as an IR field
    would be brittle invention for no gain — the same reasoning that lets a matcher
    carry explicit thresholds rather than deriving nine numbers. Extraction preserves
    them verbatim; a hand-authored IR simply omits them and gets xDM's defaults.
    """
    kind: Literal["form", "collection"]
    name: str
    label: str | None = None
    position: int = 0
    parent_step: str | None = None           # -> another step's name
    settings: dict[str, str | None] = Field(default_factory=dict)
    enrichers: list[EnricherBinding] = Field(default_factory=list)

    # THE REFS, and they are not optional decoration. MEASURED across all 20 corpus
    # steppers: `FormStep.formTab` is a real ref in 26/26 instances and
    # `CollectionStep.collectionView` in 24/24 — neither is ever null. A step emitted
    # with them null imports at 204 and the model still EXPORTS; only the deploy
    # notices (§50).
    #
    # A FormStep shows ONE TAB of a form, not a whole form. That is the product's grain
    # and it was worth getting wrong once to learn: `formTab` resolves to a `FormTab`
    # object in 26/26, never to a `Form`.
    #: The entity this step is ABOUT. Defaults to the stepper's own entity and differs
    #: only when the step drills into a CHILD — measured at 3/26 form steps and 3/24
    #: collection steps, all of them the product-retail Product -> Items -> Images
    #: nesting. Without it the refs below cannot be resolved for those six.
    entity: str | None = None
    form: str | None = None                  # kind=form -> Form.name owning the tab
    form_tab: str | None = None              # kind=form -> FormContainer(tab) in `form`
    collection: str | None = None            # kind=collection -> Collection.name


class Stepper(_Base):
    entity: str
    name: str
    label: str | None = None
    model_job: str | None = None             # -> ModelJob.name; runs on finish
    #: The collection the ROOT collection step lists. Only consulted when the author
    #: declared no collection step of their own — see `emit_app._stepper`, which derives
    #: the root rather than making every author know that a stepper cannot be a bare
    #: form. Defaults to the entity's default collection.
    collection: str | None = None
    steps: list[StepperStep] = Field(default_factory=list)


class SearchTypeConfig(_Base):
    """Which search modes a steward gets in a checkout queue, and in what order."""
    search_type: str                         # TEXT, SEMQL, BY_FORM, ADVANCED, CUSTOM_FORM
    enabled: bool = False
    position: int = 0
    custom_form: str | None = None           # -> Form.name, required by CUSTOM_FORM


class DupsManager(_Base):
    """The steward's duplicate queue for an entity.

    This is the answer to "nothing should be left silently invisible": without a dups
    manager, suggested merges accumulate with no surface that shows them. The three
    stewardship actions (ReviewAndConfirm, MergeOrSplit, ReviewSuggestions) all point
    at one, so it is the thing they operate on, not an optional decoration.
    """
    entity: str
    name: str
    label: str | None = None
    description: str | None = None
    collection: str | None = None            # -> Collection.name; the queue's list
    table_collection: str | None = None      # -> Collection.name; its table view
    checkout_sort_expression: str | None = None
    display_card: str | None = None
    form: str | None = None                  # -> Form.name, for `form_tab`
    form_tab: str | None = None              # -> FormContainer.name inside `form`
    model_job: str | None = None             # -> ModelJob.name
    settings: dict[str, str | None] = Field(default_factory=dict)
    search_configs: list[SearchTypeConfig] = Field(default_factory=list)


# The ten action element types observed inside an ActionSet. This is the vocabulary,
# not a guess: an unlisted `kind` is refused rather than emitted, on the same reasoning
# as component properties — a wrong element name imports and then misbehaves.
# NOTE three of these do not end in "Action". A survey that filtered on that suffix
# missed exactly the stewardship trio — the ones that drive the duplicate queue.
ACTION_KINDS = ("BrowseGraphAction", "CopyAction", "CreateAction", "DeleteAction",
                "DirectConfirmDupsAction", "EditAction", "ExplainRecordAction",
                "ExportAction", "ImportAction", "MassUpdateAction",
                "MergeOrSplit", "ReviewAndConfirm", "ReviewSuggestions")


class Action(_Base):
    """A record-level action offered on an entity — Create, Edit, Import, Merge…

    Same passthrough call as `StepperStep`: `kind` and the four fields below are the
    structure, and the type-specific scalars (`createdRecordType`, `deleteType`,
    `importMode`, `availableForMasterData`, …) ride in `settings`. Ten action types
    with mostly disjoint field sets would otherwise mean ~35 optional IR fields, all
    but a handful null on any given action.

    The REFS are explicit, because they are the only parts that need UUID resolution
    and the only parts that can dangle.
    """
    kind: str
    name: str
    label: str | None = None
    position: int = 0
    required_role: str | None = None         # security-relevant; advisory reads it
    icon_url: str | None = None
    condition: str | None = None             # SemQL gating the action
    items_limit: str | None = None
    settings: dict[str, str | None] = Field(default_factory=dict)
    stepper: str | None = None               # -> Stepper.name, same entity
    publisher: str | None = None             # -> Publisher.name, model-level
    display_card: str | None = None          # -> DisplayCard.name, same entity
    form: str | None = None                  # -> Form.name, same entity
    form_tab: str | None = None              # -> FormContainer.name inside `form`
    dups_manager: str | None = None          # -> DupsManager.name, same entity
    model_job: str | None = None             # -> ModelJob.name

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in ACTION_KINDS:
            raise ValueError(f"unknown action kind {v!r}; observed: {list(ACTION_KINDS)}")
        return v


class ActionSet(_Base):
    """A named bundle of actions attached to an entity. A business view node picks one,
    which is how the same entity offers different actions in different views —
    gs-productretail has both `ItemActions` and `ItemActionsNoCreate`."""
    entity: str
    name: str
    label: str | None = None
    description: str | None = None
    default: bool = False
    actions: list[Action] = Field(default_factory=list)


class BOViewTransition(_Base):
    """A navigable hop from one node of a business view to another, along a reference
    role path. `path` is a SemQL role path (`Items.Images`, `Child`,
    `IntegrationMasterRecords.MasterRecord`), which is how a self-referencing hierarchy
    is expressed — CORPUS_A's customer hierarchy is a transition named `Child` on path
    `Child` whose target is the Organization node itself."""
    name: str
    path: str
    target: str                              # -> BOViewNode.name in the same view
    position: int = 0
    settings: dict[str, str | None] = Field(default_factory=dict)


class BOViewNode(_Base):
    """One entity's appearance inside a business view.

    `entity` need NOT be the view's owning entity — that is the whole point of a
    business view, which walks the model graph. So `collection`, `form`, `action_set`
    and `display_card` all resolve against THIS node's entity, not the view's.
    """
    name: str
    entity: str
    collection: str | None = None
    # THREE distinct form refs, all present on every BOViewEntity in every sample:
    # `form` browses, `formView` renders the record, `dataEntryFormView` authors it.
    form: str | None = None
    form_view: str | None = None
    data_entry_form: str | None = None
    action_set: str | None = None
    display_card: str | None = None          # recordNodeDisplayCard
    sort_expression: str | None = None
    settings: dict[str, str | None] = Field(default_factory=dict)
    transitions: list[BOViewTransition] = Field(default_factory=list)
    search_configs: list[SearchTypeConfig] = Field(default_factory=list)
    filters: list["BuiltInFilter"] = Field(default_factory=list)


class BuiltInFilter(_Base):
    """A named SemQL filter offered on a view node, and pickable by a menu action."""
    name: str
    label: str | None = None
    description: str | None = None
    condition: str
    visible: bool = True


class BusinessView(_Base):
    """A navigable tree over the model graph — the thing a menu entry actually opens.

    Entity-owned in the XML, like everything else in the application layer.
    """
    entity: str
    name: str
    label: str | None = None
    root: str                                # -> BOViewNode.name
    root_label: str | None = None
    root_plural_label: str | None = None
    root_description: str | None = None
    description: str | None = None
    filter: str | None = None                # SemQL, applied to the root
    required_role: str | None = None
    settings: dict[str, str | None] = Field(default_factory=dict)
    nodes: list[BOViewNode] = Field(default_factory=list)


# The eight menu-entry types observed on an Application. Refused if unlisted, same
# reasoning as ACTION_KINDS.
APP_ACTION_KINDS = ("FolderAction", "BrowseBusinessViewAction", "GlobalSearchAction",
                    "MyTasksAction", "BrowseEntitiesFolderAction", "ImportDataAppAction",
                    "OpenDashboardAction", "StartWorkflowAction")


class AppAction(_Base):
    """One entry in the application's navigation menu.

    `parent_folder` names a FolderAction, so the menu is a tree expressed by name —
    the same flat-list-joined-by-name shape as form containers.
    """
    kind: str
    name: str
    label: str | None = None
    position: int = 0
    parent_folder: str | None = None         # -> AppAction.name of a FolderAction
    required_role: str | None = None
    settings: dict[str, str | None] = Field(default_factory=dict)
    # BrowseBusinessViewAction
    view_entity: str | None = None           # -> Entity.name owning `view`
    view: str | None = None                  # -> BusinessView.name
    applied_filter: str | None = None        # -> BuiltInFilter.name, resolved model-wide
    # ImportDataAppAction. The full triple is REQUIRED: gs-customerb2c has two action
    # sets on Person that each contain an ImportAction named `ImportAuthorPersons`, so
    # neither the bare name nor (entity, name) identifies one.
    import_entity: str | None = None
    import_action_set: str | None = None
    import_action: str | None = None

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in APP_ACTION_KINDS:
            raise ValueError(
                f"unknown app action kind {v!r}; observed: {list(APP_ACTION_KINDS)}")
        return v


class NavigationItem(_Base):
    action: str                              # -> AppAction.name
    position: int = 0


class NavigationGroup(_Base):
    """A block in the left navigation. Either it wraps a folder (`folder` set) or it
    lists actions explicitly (`items`) — the XML uses two element types for that, so
    `kind` carries which."""
    kind: Literal["group", "folder"]
    name: str
    label: str | None = None
    position: int = 0
    label_visible: bool = False
    divider_visible: bool = False
    folder: str | None = None                # -> AppAction.name, kind="folder"
    items: list[NavigationItem] = Field(default_factory=list)


class GlobalSearchEntry(_Base):
    name: str
    view_entity: str
    view: str
    search_type: str                         # -> the node's SearchTypeConfig
    search_node: str                         # -> BOViewNode.name holding that config
    label: str | None = None
    max_results: int = 5
    position: int = 0
    view_type: str = "GD"


class Application(_Base):
    """The navigation shell. Thin by design — every screen it opens lives on an entity.

    The ~40 theming scalars (titleBar*, titleNavBar*, primaryColor, …) ride in
    `settings`; naming each would be forty IR fields that are null in all three samples.
    """
    name: str
    label: str | None = None
    title: str | None = None
    description: str | None = None
    required_role: str | None = None
    #: Per-area role gates, keyed by their XML element name
    #: (certificationQueueRequiredRoleName, dashboardRequiredRoleName, …). Every
    #: Application in every sample carries all six, null when the area is ungated.
    area_roles: dict[str, str] = Field(default_factory=dict)
    default_action: str | None = None        # -> AppAction.name
    documentation: str | None = None
    settings: dict[str, str | None] = Field(default_factory=dict)
    actions: list[AppAction] = Field(default_factory=list)
    navigation: list[NavigationGroup] = Field(default_factory=list)
    search_dropdown: bool = True
    search_sort_alphabetically: bool = False
    search_entries: list[GlobalSearchEntry] = Field(default_factory=list)


class AppIR(_Base):
    applications: list[Application] = Field(default_factory=list)
    display_cards: list[DisplayCard] = Field(default_factory=list)
    collections: list[Collection] = Field(default_factory=list)
    forms: list[Form] = Field(default_factory=list)
    steppers: list[Stepper] = Field(default_factory=list)
    action_sets: list[ActionSet] = Field(default_factory=list)
    dups_managers: list[DupsManager] = Field(default_factory=list)
    business_views: list[BusinessView] = Field(default_factory=list)


# ------------------------------------------------------------------ certify.yaml
class EnricherExpression(_Base):
    attribute: str
    expression: str


class PluginIO(_Base):
    """A PluginEnricher's inputs / outputs / params, as name-value pairs."""
    kind: Literal["input", "output", "param"]
    name: str
    value: str | None = None


class Enricher(_Base):
    entity: str
    name: str
    kind: EnricherKind = "semql"
    scope: Scope | None = None                         # absent on form_step; rule 15
    condition: str | None = None
    position: int = 0
    expressions: list[EnricherExpression] = Field(default_factory=list)
    # plugin only
    plugin_id: str | None = None
    plugin_io: list[PluginIO] = Field(default_factory=list)
    on_error: str = "FAIL_JOB"


class Validation(_Base):
    """A row-level rule the record must satisfy. Serialized as `CheckConstraint`.

    THERE IS NO SEVERITY. This class carried `severity: ERROR|WARNING` for four
    sprints; xDM has no such field, and the docs' field list — Name, Label,
    Description, Condition, Error Message, Validation Scope — has no room for one
    (docs/Design/data-quality/validations.md). A record that fails a validation is in
    error; there is no warning tier. The field was invented, authored into four
    scenarios, and never emitted, so nothing ever contradicted it.

    `error_message` is the docs' "Error Message": the custom text shown on forms, in
    error business views and in REST responses, replacing the default.
    """
    entity: str
    name: str
    condition: str                                     # SemQL; true means VALID
    scope: Scope = "PRE_CONSO"
    label: str | None = None
    description: str | None = None
    error_message: str | None = None


class MatchRule(_Base):
    name: str
    score: int = Field(ge=0, le=100)
    condition: str
    binning: list[str] = Field(default_factory=list)
    position: int = 0
    justification: str | None = None                   # required when binning is empty
    acknowledged: bool = False


class ThresholdPolicy(_Base):
    """Stated as a policy, not nine independent numbers (sprint 03, phase 3)."""
    auto_merge_at: int = Field(ge=0, le=100)
    review_from: int = Field(ge=0, le=100)


# The nine mergeThreshold* settings. A hand-authored IR states a `policy` and lets
# the compiler derive these; an extracted IR carries them verbatim, because the two
# samples show they are NOT derivable from two numbers (CORPUS_A runs
# mergeThresholdMergingConfirmed=95 alongside ...ConfirmedWithUnconfirmed=80).
THRESHOLDS = ("autoConfirmGoldenThreshold", "mergeThresholdMergingConfirmed",
              "mergeThresholdMergingConfirmedWithNewMasters",
              "mergeThresholdMergingConfirmedWithUnconfirmed",
              "mergeThresholdMergingUnconfirmed",
              "mergeThresholdMergingUnconfirmedWithNewMasters",
              "mergeThresholdNewGroup", "mergeThresholdRemergingPreviouslySplit")


class Matcher(_Base):
    entity: str
    policy: ThresholdPolicy | None = None
    thresholds: dict[str, int] = Field(default_factory=dict)
    auto_confirm_singletons: bool = True
    use_multi_iteration_grouping: bool = True
    use_transitive_match_score: bool = True
    rules: list[MatchRule] = Field(default_factory=list)

    def resolved_thresholds(self) -> dict[str, int]:
        """Explicit values win; otherwise derive the nine from the stated policy."""
        if self.thresholds:
            return self.thresholds
        if self.policy is None:
            raise ValueError(f"matcher for {self.entity} has neither policy nor thresholds")
        hi, lo = self.policy.auto_merge_at, self.policy.review_from
        return {"autoConfirmGoldenThreshold": hi,
                "mergeThresholdMergingConfirmed": hi,
                "mergeThresholdMergingConfirmedWithNewMasters": hi,
                "mergeThresholdMergingConfirmedWithUnconfirmed": lo,
                "mergeThresholdMergingUnconfirmed": lo,
                "mergeThresholdMergingUnconfirmedWithNewMasters": lo,
                "mergeThresholdNewGroup": lo,
                "mergeThresholdRemergingPreviouslySplit": 100}


class SurvivorshipRule(_Base):
    entity: str
    name: str
    strategy: str
    attributes: list[str]
    kind: Literal["standard", "id"] = "standard"
    skip_nulls: bool = False
    default_rule: bool = False
    override_strategy: str = "UNTIL_NEXT_USER_CHANGE"
    override_decay_duration: int | None = None
    override_decay_unit: str | None = None
    order_by: str | None = None
    publisher_rankings: list[str] = Field(default_factory=list)
    acknowledged: bool = False


class ModelJobTask(_Base):
    """One entity's slot in an integration job, with the certification phases it runs.

    This is where the certification process becomes EXECUTABLE. An entity can carry a
    matcher and six validations and still never be matched, because the job task that
    would run them has `matchEnabled` false — a silent, correctness-shaped gap that
    nothing in the model itself reveals.
    """
    entity: str
    position: int = 1
    source_validation: bool = True
    source_enrichment: bool = False
    match: bool = False
    consolidation: bool = False
    consolidated_enrichment: bool = False
    post_conso_validation: bool = False


class ModelJobParam(_Base):
    name: str
    value: str | None = None


class ModelJob(_Base):
    """A named integration job — the batch that loads and certifies a set of entities.

    Model-level, and referenced from steppers, dups managers and delete actions, which
    is why it is foundational rather than a tail item.
    """
    name: str
    job_type: str = "INTEGRATION"
    queue: str = "Default"
    description: str | None = None
    params: list[ModelJobParam] = Field(default_factory=list)
    tasks: list[ModelJobTask] = Field(default_factory=list)


class CertifyIR(_Base):
    enrichers: list[Enricher] = Field(default_factory=list)
    validations: list[Validation] = Field(default_factory=list)
    matchers: list[Matcher] = Field(default_factory=list)
    survivorship: list[SurvivorshipRule] = Field(default_factory=list)
    jobs: list[ModelJob] = Field(default_factory=list)


class IR(_Base):
    """The whole spec. `certify` and `app` are optional so partial IRs are expressible."""
    model_ir: ModelIR
    certify: CertifyIR = Field(default_factory=CertifyIR)
    app: AppIR = Field(default_factory=AppIR)

    @classmethod
    def load(cls, model_path, certify_path=None, app_path=None) -> "IR":
        model_ir = ModelIR(**yaml.safe_load(open(model_path)))
        certify = CertifyIR(**yaml.safe_load(open(certify_path))) if certify_path \
            else CertifyIR()
        app = AppIR(**yaml.safe_load(open(app_path))) if app_path else AppIR()
        return cls(model_ir=model_ir, certify=certify, app=app)


__all__ = [n for n in dir() if n[0].isupper()] + ["XDM_TYPES"]
