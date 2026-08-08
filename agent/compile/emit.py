"""IR -> metaDataExport XML, model core. Sprint 05.

Two passes, because references point both ways:

  1. walk the IR, mint every UUID, build a name -> uuid symbol table
  2. emit, resolving every ref= from that table

An unresolved name in pass 2 is a compiler bug, not a user error — ir_validate
already catches dangling names (rules 7 and 8), so we assert loudly rather than
emitting a dangling ref.

Value encoding follows the four shapes in the authoring guide §3, and getting them
wrong is the easiest mistake available, so they are helper functions rather than
inline string building:

    scalar   <mandatory val="true"/>      numbers, booleans, enums
    text     <name>BusinessID</name>         names, labels, SemQL, physical columns
    null     <x null="true"/>             explicitly unset, distinct from omitted
    ref      <abstractAtomicType ref=…/>  pointer to an internalID

null="true" and ref= never carry a text body.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from agent.compile import envelope
from agent.compile.mint import mint
from agent.compile.registry import PLATFORM_TYPES, UnharvestedType, type_uuid
from agent.ir.schema import ModelIR

ENTITY_TYPE = {"basic": "BASIC", "id_matched": "ID_MATCHED", "fuzzy": "FUZZY_MATCHED"}
TYPE_UUID = {name: uuid for uuid, name in PLATFORM_TYPES.items()}


class EmitError(RuntimeError):
    pass


# ------------------------------------------------------------- value encodings
def scalar(parent: ET.Element, tag: str, value) -> None:
    ET.SubElement(parent, tag, val=("true" if value is True else
                                    "false" if value is False else str(value)))


def text(parent: ET.Element, tag: str, value: str | None) -> None:
    if value is None:
        ET.SubElement(parent, tag, null="true")
    else:
        ET.SubElement(parent, tag).text = value


def ref(parent: ET.Element, tag: str, uuid: str) -> None:
    ET.SubElement(parent, tag, ref=uuid)


def physical(name: str) -> str:
    """CustomerId -> CUSTOMER_ID. Derived, so the IR need not carry it."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def complex_prefixes(attrs) -> dict[str, str]:
    """Unique 3-character physical prefixes, one per complex attribute of an entity.

    xDM expands a complex attribute into one physical column per member, all sharing
    this prefix, so TWO COMPLEX ATTRIBUTES CANNOT SHARE ONE — `Address` and
    `AddressBilling` would both want ADD and the model fails validation.

    The UI's convention on collision is to replace the last character with a counter:
    ADD, then AD2, AD3. Reproduced here rather than invented.

    Invisible from the corpus: every sample and every live model carries exactly ONE
    complex attribute per entity, always called Address, always ADD. Reported by the
    operator from using the product.
    """
    out: dict[str, str] = {}
    used: set[str] = set()
    for a in attrs:
        if a.physical_prefix:                     # author pinned it; respect and reserve
            out[a.name] = a.physical_prefix.upper()
            used.add(out[a.name])
            continue
        base = re.sub(r"[^A-Z0-9]", "", physical(a.name))[:3] or "CPX"
        cand = base
        n = 2
        while cand in used:
            cand = f"{base[:2]}{n}"
            n += 1
            if n > 9:                             # 2..9 exhausted; widen rather than clash
                cand = f"{base[:1]}{n:02d}"
        out[a.name] = cand
        used.add(cand)
    return out


# --------------------------------------------------------------------- emitter
def emit(ir: ModelIR, *, platform_version: str, repository_version: str,
         certify=None, app=None) -> str:
    symbols = _symbols(ir)
    root, model = envelope.build(
        ir.model.name, ir.model.label,
        platform_version=platform_version, repository_version=repository_version,
        technology=ir.model.target_technology, workflows=ir.workflows)

    if ir.lov_types:
        container = ET.SubElement(model, "LOVTypes")
        for lov in ir.lov_types:
            _lov_type(container, lov, symbols)
    if ir.user_defined_types:
        container = ET.SubElement(model, "userDefinedTypes")
        for u in ir.user_defined_types:
            _user_defined_type(container, u, symbols)
    if ir.sql_functions:
        container = ET.SubElement(model, "sqlFunctions")
        for fn in ir.sql_functions:
            _sql_function(container, fn, symbols)
    if ir.complex_types:
        container = ET.SubElement(model, "complexTypes")
        for ct in ir.complex_types:
            _complex_type(container, ct, symbols)
    if ir.publishers:
        container = ET.SubElement(model, "publishers")
        for p in ir.publishers:
            _publisher(container, p, symbols)
    if ir.entities:
        # child entity -> the reference role names landing on it. Only used to tell a
        # unique key over a REFERENCE ROLE (unmeasured ref target, refused with the
        # harvest step named) from a plain typo.
        roles: dict[str, set[str]] = {}
        for r in ir.references:
            roles.setdefault(r.from_entity, set()).add(r.to_role or r.to_entity)
        container = ET.SubElement(model, "entities")
        for e in ir.entities:
            _entity(container, e, symbols, certify, app,
                    role_names=lambda en: roles.get(en, set()))
    if ir.references:
        # The container is referenceRels, NOT references. extract.py uses .iter(),
        # which finds a Reference wherever it sits, so emit and extract agreed with
        # each other while both diverged from xDM — round-trip fidelity is not
        # correctness. tests/test_containers.py now pins every container name against
        # the samples.
        container = ET.SubElement(model, "referenceRels")
        # Nth reference LANDING ON the same child entity. Each Reference sits in its own
        # `foreignAttribute` holder, so the shape check's harvested scope for
        # ForeignAttribute is XML nesting and cannot see a collision. The product's own
        # set is wider: measured over 17 entities in the product-authored corpus, an
        # entity's PKAttribute / AtomicAttribute / ComplexAttribute / ForeignAttribute
        # positions are unique ACROSS all four types. A cross-type sweep is not a
        # general invariant — the product duplicates positions across types elsewhere,
        # 33 times in the same corpus — so this one is paid for here rather than
        # widened into the check.
        nth: dict[str, int] = {}
        for r in ir.references:
            i = nth[r.from_entity] = nth.get(r.from_entity, 0) + 1
            _reference(container, r, symbols, fk_position=200 + i)
    if app is not None and app.applications:
        # Last: every ref in an Application points at something an ENTITY owns.
        from agent.compile.emit_app import emit_applications
        emit_applications(model, app)
    if certify is not None and certify.jobs:
        from agent.compile.emit_certify import emit_model_jobs
        emit_model_jobs(model, certify.jobs, lambda n: symbols[f"entity/{n}"])
    _roles(model, ir, symbols)
    envelope.model_config(model, ir.model.name, ir.model.target_technology)

    # Fill in what the product always writes and the emitters did not say. The
    # emitters describe INTENT; the shape comes from measurement (see blocks.complete).
    from agent.compile.blocks import complete
    complete(root)

    # The XML DECLARATION is required. Every export the product writes begins with it,
    # and the importer rejects a document without one as "Unable to parse payload" —
    # a message that names neither the declaration nor the encoding. Omitting it was
    # invisible in every round-trip, because ElementTree parses a bare document
    # perfectly well.
    return envelope.XML_DECL + ET.tostring(root, encoding="unicode")


def _roles(model_el: ET.Element, ir: ModelIR, symbols: dict[str, str]) -> None:
    """ModelPrivGrant is a ROLE; the entity grants nest inside it.

    A role granted here is also the vocabulary the application layer's `required_role`
    fields draw from — an action gated on a role no grant defines is invisible to
    everyone, which the advisor checks separately.
    """
    if not ir.roles:
        return
    holder = ET.SubElement(model_el, "modelPrivGrants")
    for r in ir.roles:
        el = ET.SubElement(holder, "ModelPrivGrant")
        envelope.audit(el, mint("role", r.name))
        text(el, "name", r.name)
        text(el, "label", r.label)
        text(el, "description", r.description)
        text(el, "roleName", r.role_name)
        scalar(el, "dataAdminRole", r.data_admin)
        scalar(el, "integrationWsRole", r.integration_ws)
        scalar(el, "allowApiPublishingAsUser", r.api_publishing_as_user)
        scalar(el, "allowEnrichmentDocumentation", r.allow_enrichment_documentation)
        scalar(el, "allowDataQualityDocumentation", r.allow_data_quality_documentation)
        if not r.grants:
            continue
        gh = ET.SubElement(el, "entityPrivGrants")
        for g in r.grants:
            if f"entity/{g.entity}" not in symbols:
                raise EmitError(
                    f"role {r.name!r} grants access to entity {g.entity!r}, which the "
                    f"model does not declare")
            ge = ET.SubElement(gh, "EntityPrivGrant")
            envelope.audit(ge, mint("role", r.name, "grant", g.entity))
            text(ge, "name", g.entity)
            text(ge, "description", g.description)
            text(ge, "filter", g.filter)
            scalar(ge, "defaultAccessType", g.default_access)
            scalar(ge, "createAllowed", g.create)
            scalar(ge, "deleteAllowed", g.delete)
            scalar(ge, "removeAllowed", g.remove)
            scalar(ge, "exportAllowed", g.export)
            scalar(ge, "checkoutAllowed", g.checkout)
            ref(ge, "entity", symbols[f"entity/{g.entity}"])


def _symbols(ir: ModelIR) -> dict[str, str]:
    """Pass 1: name -> uuid for everything a ref= can point at."""
    s: dict[str, str] = {}
    for e in ir.entities:
        s[f"entity/{e.name}"] = mint("entity", e.name)
        for a in e.attributes:
            s[f"attr/{e.name}/{a.name}"] = mint("entity", e.name, "attr", a.name)
        for ca in e.complex_attributes:
            s[f"attr/{e.name}/{ca.name}"] = mint("entity", e.name, "attr", ca.name)
    for t in ir.complex_types:
        s[f"type/{t.name}"] = mint("complexType", t.name)
    for lov in ir.lov_types:
        s[f"type/{lov.name}"] = mint("lovType", lov.name)
    for u in ir.user_defined_types:
        s[f"type/{u.name}"] = mint("userDefinedType", u.name)
    for fn in ir.sql_functions:
        s[f"sqlfn/{fn.name}"] = mint("sqlFunction", fn.name)
        for a in fn.arguments:
            s[f"sqlfn/{fn.name}/arg/{a.name}"] = mint(
                "sqlFunction", fn.name, "arg", a.name)
    for p in ir.publishers:
        s[f"publisher/{p.name}"] = mint("publisher", p.name)
    for r in ir.references:
        s[f"reference/{r.name}"] = mint("reference", r.name)
        # The FK column is a distinct persisted object and needs its own identity.
        s[f"reference/{r.name}/fk"] = mint("reference", r.name, "fk")
    return s


def _datatype_ref(parent: ET.Element, type_name: str, symbols: dict[str, str]) -> None:
    """Point at a platform built-in, or at a type the model declares itself."""
    if f"type/{type_name}" in symbols:          # declared by the model itself
        ref(parent, "abstractAtomicType", symbols[f"type/{type_name}"])
        return
    try:
        ref(parent, "abstractAtomicType", type_uuid(type_name))
    except UnharvestedType as exc:
        raise EmitError(str(exc)) from None      # a lookup gap, with the fix in it
    except KeyError as exc:
        raise EmitError(
            f"{type_name!r} is neither an xDM datatype nor a type declared in this "
            f"model. {exc}") from None


def _attribute(parent: ET.Element, tag: str, a, entity: str,
               pos: int, symbols: dict[str, str], idgen=None) -> None:
    el = ET.SubElement(parent, tag)
    envelope.audit(el, symbols[f"attr/{entity}/{a.name}"])
    text(el, "name", a.name)
    text(el, "label", a.name)
    # The DECLARED name derives the physical one unless the author pinned it. Pinning
    # is not an escape hatch: the repository caps the GENERATED column at 25
    # characters, and derivation inserts `_` before every capital, so three names in a
    # faithfully-transcribed design already overflow.
    text(el, "physicalColName", a.physical_name or physical(a.name))
    scalar(el, "mandatory", a.mandatory)
    if tag != "PKAttribute":
        # No export carries either scope on a PKAttribute — a primary key is mandatory
        # by construction and has no LOV.
        scalar(el, "mandatoryValidationScope", a.mandatory_scope)
        scalar(el, "LOVValidationScope", a.lov_scope)
    scalar(el, "searchable", a.searchable)
    scalar(el, "goldenAttribute", True)
    scalar(el, "i18ned", False)
    scalar(el, "multiValued", False)
    text(el, "valueSeparator", ",")
    scalar(el, "length", a.length or 0)
    scalar(el, "precision", a.precision or 0)
    scalar(el, "scale", a.scale or 0)
    scalar(el, "posInParent", pos)
    if idgen is not None:
        # ID generation hangs off the PRIMARY KEY ATTRIBUTE, not the Entity. Emitting
        # it on the Entity is accepted by the importer and silently discarded; the
        # deploy then NPEs in LogicalModelFactory.createIdGenerationDescriptor with a
        # bare 500. OBSERVED 2026-08-04 — see LESSONS §19.
        scalar(el, "idGenerationType", idgen.id_generation)
        scalar(el, "idSequenceStartsWith", idgen.id_sequence_starts_with)
        text(el, "idExpression",
             idgen.id_expression if idgen.id_generation == "SEMQL" else None)
        scalar(el, "fuzzyMatchedEntityGoldenIdGenerationType",
               idgen.golden_id_generation)
        scalar(el, "fuzzyMatchedEntityGoldenIdSequenceStartsWith",
               idgen.golden_id_sequence_starts_with)
    _datatype_ref(el, a.type, symbols)


def _unique_keys(entity_el: ET.Element, e, symbols: dict[str, str],
                 role_names) -> None:
    """UniqueKey / KeyAttribute, inside the entity's `uniqueKeys` holder.

    MEASURED (harvest/CustomerB2CDemo.workflow.xml): name and label are element text,
    description and validationLabel explicit nulls, `validationScope` a `val` enum, and
    `keyAttributes` a holder of `KeyAttribute` objects carrying `posInKey` plus an
    `abstractAttribute` ref. `keyAttributes` is `never_empty`, so an empty key is a
    shape defect rather than a harmless no-op — hence the refusal below.

    ATOMIC ATTRIBUTES ONLY. A reference role is an attribute of the child entity in
    every sense the model cares about, so a key over one is expressible in the product
    — but every measured `KeyAttribute` points at an `AtomicAttribute`, so the ref
    TARGET is unattested even though the element SHAPE is measured. That is the exact
    gap `unknown` findings exist to protect (a shape check cannot see what a UUID
    resolves to), so it is refused with the harvest step named rather than emitted on
    the strength of the shape alone.
    """
    if not e.unique_keys:
        return
    holder = ET.SubElement(entity_el, "uniqueKeys")
    for k in e.unique_keys:
        if not k.attributes:
            raise EmitError(
                f"unique key {e.name}.{k.name!r} names no attributes. Every observed "
                f"UniqueKey populates `keyAttributes`, and an empty holder is the "
                f"shape that imports at 204 and dies in the deployer.")
        el = ET.SubElement(holder, "UniqueKey")
        envelope.audit(el, mint("entity", e.name, "uniqueKey", k.name))
        text(el, "description", None)
        text(el, "label", k.label or k.name)
        text(el, "name", k.name)
        text(el, "validationLabel", k.error_message)
        scalar(el, "validationScope", k.validation_scope)
        ka = ET.SubElement(el, "keyAttributes")
        for i, aname in enumerate(k.attributes, 1):
            target = symbols.get(f"attr/{e.name}/{aname}")
            if target is None and aname in role_names(e.name):
                raise EmitError(
                    f"unique key {e.name}.{k.name!r} names the REFERENCE ROLE "
                    f"{aname!r}. The element shape is measured but no export points a "
                    f"KeyAttribute at a ForeignAttribute, so the ref target is a "
                    f"guess. Build the key once in the designer, export into harvest/, "
                    f"re-run harvest_blocks — then this refusal can be lifted with "
                    f"evidence behind it.")
            if target is None:
                raise EmitError(
                    f"unique key {e.name}.{k.name!r} names {aname!r}, which is not an "
                    f"attribute of {e.name}")
            a_el = ET.SubElement(ka, "KeyAttribute")
            envelope.audit(a_el, mint("entity", e.name, "uniqueKey", k.name, aname))
            scalar(a_el, "posInKey", i)
            ref(a_el, "abstractAttribute", target)


def _entity(parent: ET.Element, e, symbols: dict[str, str], certify=None,
            app=None, role_names=None) -> None:
    el = ET.SubElement(parent, "Entity")
    envelope.audit(el, symbols[f"entity/{e.name}"])
    text(el, "name", e.name)
    text(el, "label", e.label or e.name)
    text(el, "pluralLabel", (e.label or e.name) + "s")
    text(el, "physicalTableName", physical(e.name))
    scalar(el, "entityType", ENTITY_TYPE[e.type])
    scalar(el, "dataEntryAllowed", True)
    scalar(el, "enableDelete", True)
    scalar(el, "historizeGolden", e.historize_golden)
    scalar(el, "historizeMaster", e.historize_master)

    pos = 1
    # PKAttribute and SubjectNameAttribute are distinct element types, not flavours
    # of AtomicAttribute (authoring guide §5.2).
    pks = [a for a in e.attributes if a.pk]
    if pks:
        holder = ET.SubElement(el, "PKAttributes")
        for a in pks:
            _attribute(holder, "PKAttribute", a, e.name, pos, symbols, idgen=e)
            pos += 1
    # `subject_name` is an IR-level concept with NO entity-level equivalent in xDM.
    # An Entity carries name/label/pluralLabel/displayCards and nothing else that names
    # a record — records are titled by a DISPLAY CARD, which is application layer.
    # SubjectNameAttribute exists but belongs to a ComplexType's name composition
    # (ComplexType > subjectName > ComplexTypeSubjectName > subjectNameAttributes) and
    # carries only posInName plus a ref, so emitting an attribute there was wrong in
    # both placement and shape. It is emitted as the entity's default display card in
    # sprint 07; until then subject_name is carried in the IR and not written.
    plain = [a for a in e.attributes if not a.pk]
    if plain:
        holder = ET.SubElement(el, "atomicAttributes")
        for a in plain:
            _attribute(holder, "AtomicAttribute", a, e.name, pos, symbols)
            pos += 1
    if e.complex_attributes:
        prefixes = complex_prefixes(e.complex_attributes)
        holder = ET.SubElement(el, "complexAttributes")
        for i, ca in enumerate(e.complex_attributes, pos):
            c = ET.SubElement(holder, "ComplexAttribute")
            envelope.audit(c, symbols[f"attr/{e.name}/{ca.name}"])
            text(c, "name", ca.name)
            text(c, "label", ca.name)
            text(c, "physicalPrefix", prefixes[ca.name])
            scalar(c, "mandatoryValidationScope", "NONE")
            scalar(c, "LOVValidationScope", "NONE")
            scalar(c, "posInParent", i)
            ref(c, "complexType", symbols[f"type/{ca.type}"])

    _unique_keys(el, e, symbols, role_names or (lambda _e: ()))

    if certify is not None:
        from agent.compile.emit_certify import emit_entity_certification
        emit_entity_certification(
            el, e.name, certify, lambda p: symbols[f"publisher/{p}"])
    # A default display card whenever the app layer declares none for this entity.
    #
    # This used to be an `elif app is None` fallback, and it was DEAD CODE. `IR.load`
    # always returns an AppIR — empty, but not None — so the guard was true for every
    # scenario and every build, and the fallback never ran once. The symptom was an
    # empty `displayCards` holder on every entity in s1, s2 and s4, which is the same
    # class as the FK container: a slot the deployer can dereference, and a record with
    # no title in any screen that shows one.
    #
    # The real condition was never "is there an app IR?" but "does this ENTITY have a
    # card?" — a model can carry a full application layer and still leave one entity
    # without one. Testing the object's existence instead of its contents is what made
    # the branch unreachable rather than merely wrong.
    #
    # `subject_name` is a G3 design decision ("which attribute names a record?") with no
    # entity-level equivalent in xDM, so the card is the only place it survives.
    from agent.compile.emit_app import default_card_for, emit_entity_app
    from agent.ir.schema import AppIR, DisplayCard

    eff = app if app is not None else AppIR()
    if not [c for c in eff.display_cards if c.entity == e.name]:
        default = default_card_for(e)
        if default:
            eff = eff.model_copy(update={
                "display_cards": list(eff.display_cards) + [DisplayCard(**default)]})

    # Only offer an enricher resolver when the certification IR is actually being
    # emitted. Otherwise a FormStepEnricher binding would mint a UUID for an
    # element that was never written — a dangling ref that imports cleanly.
    resolver = (lambda n: mint("entity", e.name, "enricher", n)) \
        if certify is not None else None
    jobs = {j.name for j in certify.jobs} if certify is not None else set()
    emit_entity_app(el, e.name, eff, resolver,
                    lambda p: symbols[f"publisher/{p}"],
                    (lambda n: mint("modelJob", n)) if jobs else None)


def _complex_type(parent: ET.Element, t, symbols: dict[str, str]) -> None:
    el = ET.SubElement(parent, "ComplexType")
    envelope.audit(el, symbols[f"type/{t.name}"])
    text(el, "name", t.name)
    text(el, "label", t.name)
    if not t.members:
        return
    # definitionAttributes / DefinitionAttribute, not atomicAttributes / AtomicAttribute.
    holder = ET.SubElement(el, "definitionAttributes")
    for i, m in enumerate(t.members, 1):
        a = ET.SubElement(holder, "DefinitionAttribute")
        envelope.audit(a, mint("complexType", t.name, "member", m.name))
        text(a, "name", m.name)
        text(a, "label", m.name)
        text(a, "physicalColName", m.physical_name or physical(m.name))
        text(a, "valueSeparator", ",")
        scalar(a, "mandatory", m.mandatory)
        scalar(a, "searchable", m.searchable)
        scalar(a, "goldenAttribute", True)
        scalar(a, "i18ned", False)
        scalar(a, "multiValued", False)
        scalar(a, "length", m.length or 0)
        scalar(a, "precision", m.precision or 0)
        scalar(a, "scale", m.scale or 0)
        scalar(a, "posInParent", i)
        _datatype_ref(a, m.type, symbols)


def _lov_type(parent: ET.Element, lov, symbols: dict[str, str]) -> None:
    el = ET.SubElement(parent, "LOVType")
    envelope.audit(el, symbols[f"type/{lov.name}"])
    text(el, "name", lov.name)
    text(el, "label", lov.name)
    holder = ET.SubElement(el, "LOVValues")
    for v in lov.values:
        item = ET.SubElement(holder, "LOVValue")
        envelope.audit(item, mint("lovType", lov.name, "value", v.code))
        # A LOVValue pairs <code> with <label>. There is NO <value> element, and no
        # posInParent either — values are ordered by DOCUMENT POSITION. Emitting one
        # was an invention that no export carries (found by blocks.check).
        text(item, "code", v.code)
        text(item, "label", v.label)
        text(item, "description", None)
        text(item, "imageUrl", None)


def _sql_function(parent: ET.Element, fn, symbols: dict[str, str]) -> None:
    """A declared database function. `categories` and `schema` are FREE TEXT; the two
    booleans are `val=` (LESSONS §20)."""
    el = ET.SubElement(parent, "SqlFunction")
    envelope.audit(el, symbols[f"sqlfn/{fn.name}"])
    scalar(el, "aggregateFunction", fn.aggregate)
    text(el, "categories", fn.categories)
    text(el, "description", fn.description)
    text(el, "name", fn.name)
    scalar(el, "procedure", fn.procedure)
    text(el, "schema", fn.schema_name)
    holder = ET.SubElement(el, "functionArguments")
    for a in fn.arguments:
        ae = ET.SubElement(holder, "FunctionArgument")
        envelope.audit(ae, symbols[f"sqlfn/{fn.name}/arg/{a.name}"])
        scalar(ae, "array", a.array)
        scalar(ae, "mandatory", a.mandatory)
        text(ae, "name", a.name)
        scalar(ae, "position", a.position)


def _user_defined_type(parent: ET.Element, u, symbols: dict[str, str]) -> None:
    el = ET.SubElement(parent, "UserDefinedType")
    envelope.audit(el, symbols[f"type/{u.name}"])
    text(el, "name", u.name)
    text(el, "label", u.name)
    scalar(el, "length", u.length or 0)
    scalar(el, "precision", u.precision or 0)
    scalar(el, "scale", u.scale or 0)
    for tag in ("lengthModifiable", "precisionModifiable", "scaleModifiable"):
        scalar(el, tag, False)
    if u.base_type not in TYPE_UUID:
        raise EmitError(f"user-defined type {u.name!r} has unknown base {u.base_type!r}")
    ref(el, "builtInType", TYPE_UUID[u.base_type])


def _publisher(parent: ET.Element, p, symbols: dict[str, str]) -> None:
    el = ET.SubElement(parent, "Publisher")
    envelope.audit(el, symbols[f"publisher/{p.name}"])
    text(el, "name", p.name)
    text(el, "code", p.code)
    text(el, "label", p.label or p.name)
    scalar(el, "active", p.active)


def _reference(parent: ET.Element, r, symbols: dict[str, str],
               fk_position: int = 201) -> None:
    el = ET.SubElement(parent, "Reference")
    envelope.audit(el, symbols[f"reference/{r.name}"])
    text(el, "name", r.name)
    for side, tag in ((r.from_entity, "fromEntity"), (r.to_entity, "toEntity")):
        key = f"entity/{side}"
        if key not in symbols:
            raise EmitError(f"reference {r.name!r} points at unknown entity {side!r}")
        ref(el, tag, symbols[key])
    text(el, "fromRoleName", r.from_role or r.name)
    text(el, "toRoleName", r.to_role or r.to_entity)
    text(el, "toRolePhysicalName",
         r.to_role_physical or physical(r.to_role or r.to_entity))
    text(el, "physicalName", r.physical_name or physical(r.name))
    scalar(el, "oneToMany", r.one_to_many)
    scalar(el, "deletePropagation", r.delete_propagation)
    scalar(el, "validationScope", r.validation_scope)
    scalar(el, "splitDuplicatePropagation", "NONE")

    # THE FOREIGN KEY COLUMN ITSELF. A Reference without one imports at 204 and then
    # kills the deploy with a bare "Unexpected Error" — the signature of a null the
    # deployer dereferences. OBSERVED 2026-08-05 on scenario 4, the first scenario with
    # any references at all.
    #
    # `blocks.complete()` was already emitting the `foreignAttribute` SLOT, because the
    # slot is an element and the block library knows Reference has one. What it cannot
    # do is put an OBJECT inside it: a generic post-pass has no minting context, and
    # `test_complete_never_creates_objects_only_elements` pins that deliberately. So
    # the model went out with an empty container, which is strictly worse than an
    # absent one — §19's ABSENT != null, one layer down, and the exact shape of the
    # ComponentProperty identity bug.
    #
    # MEASURED across 22 references in samples/, live/ and harvest/, zero exceptions:
    #   * exactly ONE ForeignAttribute per Reference
    #   * `entity` refs the FROM entity — the CHILD holds the FK column, not the target
    #   * `name` == `toRoleName` in all 22
    #   * `searchable` true in all 22
    # `label` equals `name` in 13 of 22; the other 9 are hand-edited labels, so name is
    # the right default and not a rule being broken. `physicalName` is UPPER_SNAKE of
    # the name in the majority; the exceptions (ITEM_SIZE, REPORTING_ORG_GOLDEN) are
    # hand-shortened by a modeller, which is a user choice rather than a derivation.
    role = r.to_role or r.to_entity
    holder = ET.SubElement(el, "foreignAttribute")
    fa = ET.SubElement(holder, "ForeignAttribute")
    envelope.audit(fa, symbols[f"reference/{r.name}/fk"])
    text(fa, "name", role)
    text(fa, "label", role)
    text(fa, "physicalName", physical(role))
    text(fa, "description", None)
    text(fa, "documentation", None)
    scalar(fa, "searchable", True)
    # Positions are ordered by document position rather than by absolute value, and the
    # FK is emitted after the entity's own attributes, so a high number keeps it last
    # without having to thread the child's attribute count through here. It was the bare
    # constant 200 until 2026-08-07, which made two references FROM THE SAME ENTITY
    # share a position — legal in every check we had, and "Duplicate Position: Position
    # \"200\" is already used in the set of objects" in the Application Builder.
    scalar(fa, "posInParent", fk_position)
    ref(fa, "entity", symbols[f"entity/{r.from_entity}"])
