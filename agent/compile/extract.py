"""metaDataExport XML -> IR. Sprint 05.

RED-TEAM R2: every compiler sprint's acceptance test is
`sample.xml -> IR -> compile -> normalize -> diff`, and that first arrow had no
owner. Without this the whole test strategy is unimplementable.

It is not test scaffolding. It is also:
  - how CORPUS_A gets migrated into the IR later
  - how sprint 09 reconciles a re-exported model against the IR
  - the engine of D8's demonstration-harvest loop: build an unsupported construct
    once in the UI, export, extract, and the emitter has learned its grammar

Model core only — entities, attributes, complex types, LOVs, references,
publishers. Certification and the application layer are sprints 06 and 07.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from agent.compile.registry import UnknownPlatformType, resolve
from agent.ir.schema import ModelIR

ENTITY_TYPE = {"BASIC": "basic", "ID_MATCHED": "id_matched", "FUZZY_MATCHED": "fuzzy"}
#: Technologies the IR can express; anything else keeps the IR default rather than
#: inventing a value the emitter would refuse.
TECHNOLOGY_NAMES = frozenset({"snowflake", "postgresql"})

# An unknown datatype must NOT silently become String. Defaulting made a Decimal
# price extract as a String, and the round-trip test could not see it: extract
# produced String on both passes, so emit -> extract compared equal while the model
# was wrong. Round-trip fidelity is not correctness. This sentinel fails IR-013 and
# is refused by emit, so the mis-type is loud instead.
UNRESOLVED_TYPE = "UNRESOLVED"


def unresolved_type(uuid: str) -> str:
    return f"{UNRESOLVED_TYPE}:{uuid}"


def _text(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None:
        return None
    return child.attrib.get("val", child.text)


def _id_generation(entity_el: ET.Element) -> dict:
    """ID generation, which hangs off the PKAttribute rather than the Entity.

    Defaults are the corpus majority, so a model extracted from an export that
    predates this (or one this compiler emitted before 2026-08-04) stays deployable
    instead of round-tripping a null straight back into an NPE.
    """
    pk = next(iter(entity_el.iter("PKAttribute")), None)
    if pk is None:
        pk = ET.Element("PKAttribute")
    return {
        "id_generation": _text(pk, "idGenerationType") or "MANUAL",
        "id_sequence_starts_with": _int(pk, "idSequenceStartsWith") or 1,
        "golden_id_generation": (
            _text(pk, "fuzzyMatchedEntityGoldenIdGenerationType") or "SEQUENCE"),
        "golden_id_sequence_starts_with": (
            _int(pk, "fuzzyMatchedEntityGoldenIdSequenceStartsWith") or 1),
        "id_expression": _text(pk, "idExpression"),
    }


def _bool(el: ET.Element, tag: str) -> bool:
    return _text(el, tag) == "true"


def _int(el: ET.Element, tag: str) -> int | None:
    v = _text(el, tag)
    if v is None or not v.strip().lstrip("-").isdigit():
        return None
    n = int(v)
    return n or None            # xDM writes 0 for "unset" on length/precision/scale


def _attr_names(entity_el: ET.Element) -> dict[str, str]:
    """internalID -> attribute name, for every attribute this entity owns.

    A unique key's members are refs, and resolving them is the only way back from the
    XML to the names the IR uses.
    """
    out: dict[str, str] = {}
    for tag in ("PKAttribute", "AtomicAttribute", "ComplexAttribute",
                "ForeignAttribute"):
        for a in entity_el.iter(tag):
            uid, nm = _text(a, "internalID"), _text(a, "name")
            if uid and nm:
                out[uid] = nm
    return out


def _key_attributes(key_el: ET.Element, names: dict[str, str]) -> list[str]:
    """A unique key's members, in `posInKey` order and resolved to names.

    Sorted rather than trusting document order: the key is a SEQUENCE and a composite
    key whose members come back transposed is a different constraint.
    """
    rows = []
    for k in key_el.iter("KeyAttribute"):
        ref_el = k.find("abstractAttribute")
        name = names.get(ref_el.get("ref")) if ref_el is not None else None
        if name:
            rows.append((_int(k, "posInKey") or 0, name))
    return [n for _, n in sorted(rows, key=lambda r: r[0])]


def _physical_override(el: ET.Element, name: str | None,
                       tag: str = "physicalColName") -> str | None:
    """The written physical name, or None when derivation already produces it."""
    from agent.compile.emit import physical
    got = _text(el, tag)
    if not got or not name or got == physical(name):
        return None
    return got


def _attribute(el: ET.Element, local_types: dict[str, str], unresolved: list[str]) -> dict:
    ref = el.find("abstractAtomicType")
    uuid = ref.attrib.get("ref") if ref is not None else None
    xdm = None
    if uuid in local_types:
        # Points at an in-model LOV or user-defined type rather than a built-in.
        xdm = local_types[uuid]
    elif uuid:
        try:
            xdm = resolve(uuid)
        except UnknownPlatformType as exc:
            unresolved.append(f"{_text(el, 'name')}: {exc}")
            xdm = unresolved_type(uuid)
    return {
        "name": _text(el, "name"),
        "type": xdm or unresolved_type("missing"),
        # Carried only when the product's column name is NOT what derivation would
        # produce. Dropping it entirely was lossy in the one direction that matters:
        # the real org-hub export hand-shortens `MELISSA_RESULT_CODE`, derivation
        # re-expands it to a 28-character column, and the re-emitted model breaks the
        # repository's 25-character limit (IR-029). A round trip agreed with itself
        # because both passes ignored the element.
        "physical_name": _physical_override(el, _text(el, "name")),
        "length": _int(el, "length"),
        "precision": _int(el, "precision"),
        "scale": _int(el, "scale"),
        "mandatory": _bool(el, "mandatory"),
        "mandatory_scope": _text(el, "mandatoryValidationScope") or "NONE",
        "lov_scope": _text(el, "LOVValidationScope") or "NONE",
        "searchable": _bool(el, "searchable"),
    }


def extract(path: str | Path) -> tuple[ModelIR, list[str]]:
    """Return (ModelIR, unresolved) — never raises on an unknown datatype."""
    root = ET.parse(path).getroot()
    model_el = root.find("Model")
    root_model = root.find("RootModel")
    unresolved: list[str] = []

    # LOV and user-defined types are model-local: build uuid -> name up front so
    # attributes pointing at them resolve without touching the platform registry.
    local_types: dict[str, str] = {}
    for tag in ("LOVType", "UserDefinedType", "ComplexType"):
        for t in model_el.iter(tag):
            uid = _text(t, "internalID")
            if uid:
                local_types[uid] = _text(t, "name") or "String"

    sql_functions = []
    for fn in model_el.iter("SqlFunction"):
        sql_functions.append({
            "name": _text(fn, "name"),
            "schema_name": _text(fn, "schema"),
            "categories": _text(fn, "categories"),
            "aggregate": _bool(fn, "aggregateFunction"),
            "procedure": _bool(fn, "procedure"),
            "description": _text(fn, "description"),
            "arguments": [
                {"name": _text(a, "name"),
                 "position": _int(a, "position") or 1,
                 "mandatory": _bool(a, "mandatory"),
                 "array": _bool(a, "array")}
                for a in fn.iter("FunctionArgument")
            ],
        })

    entities = []
    for e in model_el.iter("Entity"):
        # PKAttribute and SubjectNameAttribute are DISTINCT element types, not
        # flavours of AtomicAttribute (authoring guide §5.2). Iterating only
        # AtomicAttribute drops the primary key from the model entirely.
        attrs = []
        for a in e.iter("PKAttribute"):
            d = _attribute(a, local_types, unresolved)
            d["pk"], d["mandatory"] = True, True
            attrs.append(d)
        # SubjectNameAttribute is NOT read here: it belongs to a ComplexType's name
        # composition, not to an Entity. An entity names its records through a display
        # card, so subject_name is recovered in sprint 07 from the display card.
        for a in e.iter("AtomicAttribute"):
            attrs.append(_attribute(a, local_types, unresolved))
        entities.append({
            "name": _text(e, "name"),
            "type": ENTITY_TYPE.get(_text(e, "entityType") or "", "basic"),
            "label": _text(e, "label"),
            # Deploy-critical, and null in everything this compiler emitted before
            # 2026-08-04. Fall back to the corpus default rather than None so a model
            # extracted from an older export stays deployable.
            # ...read off the PK ATTRIBUTE, which is where xDM keeps them.
            **_id_generation(e),
            # Not back-fillable and needs a redeploy to change, so an extracted model
            # has to carry what the live one actually does — a default would silently
            # propose turning master history on for every basic entity.
            "historize_golden": _bool(e, "historizeGolden"),
            "historize_master": _bool(e, "historizeMaster"),
            "attributes": attrs,
            "complex_attributes": [
                {"name": _text(c, "name"),
                 "type": _ref_name(c, "complexType", local_types),
                 "physical_prefix": _text(c, "physicalPrefix")}
                for c in e.iter("ComplexAttribute")
            ],
            # A KeyAttribute points at an attribute BY UUID, so the name has to be
            # looked back up. Built per entity rather than model-wide: two entities may
            # legitimately carry attributes of the same name, and a model-wide map would
            # resolve to whichever was seen last.
            "unique_keys": [
                {"name": _text(u, "name"),
                 "label": _text(u, "label"),
                 "validation_scope": _text(u, "validationScope") or "POST_CONSO",
                 "error_message": _text(u, "validationLabel"),
                 "attributes": _key_attributes(u, _attr_names(e))}
                for u in e.iter("UniqueKey")
            ],
        })


    entity_names = {_text(e, "internalID"): _text(e, "name")
                    for e in model_el.iter("Entity")}
    roles = []
    for holder in model_el.findall("modelPrivGrants"):
        for r in holder.iter("ModelPrivGrant"):
            roles.append({
                "name": _text(r, "name"), "role_name": _text(r, "roleName") or "",
                "label": _text(r, "label"), "description": _text(r, "description"),
                "data_admin": _bool(r, "dataAdminRole"),
                "integration_ws": _bool(r, "integrationWsRole"),
                "api_publishing_as_user": _bool(r, "allowApiPublishingAsUser"),
                "allow_enrichment_documentation": _bool(
                    r, "allowEnrichmentDocumentation"),
                "allow_data_quality_documentation": _bool(
                    r, "allowDataQualityDocumentation"),
                "grants": [
                    {"entity": entity_names.get(
                        g.find("entity").attrib.get("ref")
                        if g.find("entity") is not None else ""),
                     "default_access": _text(g, "defaultAccessType") or "READ",
                     "create": _bool(g, "createAllowed"),
                     "delete": _bool(g, "deleteAllowed"),
                     "remove": _bool(g, "removeAllowed"),
                     "export": _bool(g, "exportAllowed"),
                     "checkout": _bool(g, "checkoutAllowed"),
                     "filter": _text(g, "filter"),
                     "description": _text(g, "description")}
                    for gh in r.findall("entityPrivGrants")
                    for g in gh.iter("EntityPrivGrant")],
            })

    # The target technology lives in ModelConfiguration.type, and NOT reading it made
    # every extracted model silently default to snowflake — which then flagged
    # METAPHONE, a PostgreSQL function, as unavailable. A round-trip loss that only
    # showed up once the function checker existed to notice it.
    _cfg = next(root.iter("ModelConfiguration"), None)
    _tech = (_text(_cfg, "type") or "").lower() if _cfg is not None else ""

    ir = ModelIR(
        model={"name": _text(root_model, "name") or "Unnamed",
               "label": _text(root_model, "label"),
               **({"target_technology": _tech} if _tech in TECHNOLOGY_NAMES else {})},
        roles=roles,
        publishers=[
            {"name": _text(p, "name"), "code": _text(p, "code") or "",
             "label": _text(p, "label"), "active": _bool(p, "active")}
            for p in model_el.iter("Publisher")
        ],
        entities=entities,
        sql_functions=sql_functions,
        user_defined_types=[
            {"name": _text(t, "name"),
             "base_type": _builtin_name(t, local_types),
             "length": _int(t, "length"), "precision": _int(t, "precision"),
             "scale": _int(t, "scale")}
            for t in model_el.iter("UserDefinedType") if _text(t, "name")
        ],
        # A ComplexType's fields are DefinitionAttribute, NOT AtomicAttribute. Reading
        # the wrong element name found nothing, so every complex type extracted with
        # ZERO members and emitted as an empty shell — an AddressType with no street,
        # city or postcode. The round-trip could not see it, because both passes agreed
        # on the same wrong name. Fourth instance of that failure mode, after the
        # referenceRels container, Stepper.modelJob and the export envelope.
        complex_types=[
            {"name": _text(t, "name"),
             "members": [{"name": _text(m, "name"),
                          "type": _attribute(m, local_types, unresolved)["type"],
                          "physical_name": _physical_override(m, _text(m, "name")),
                          "length": _int(m, "length"),
                          "precision": _int(m, "precision"),
                          "scale": _int(m, "scale"),
                          "mandatory": _bool(m, "mandatory"),
                          "searchable": _bool(m, "searchable")}
                         for m in t.iter("DefinitionAttribute")]}
            for t in model_el.iter("ComplexType")
        ],
        lov_types=[
            {"name": _text(t, "name"),
             "values": [{"code": _text(v, "code") or "",
                         "label": _text(v, "label") or _text(v, "code") or ""}
                        for v in t.iter("LOVValue")]}
            for t in model_el.iter("LOVType")
        ],
        references=[
            {"name": _text(r, "name"),
             "from_entity": _entity_name(model_el, r, "fromEntity"),
             "to_entity": _entity_name(model_el, r, "toEntity"),
             "from_role": _text(r, "fromRoleName"),
             "to_role": _text(r, "toRoleName"),
             # The product truncates both at 25 and its modellers shorten them by
             # hand, so re-deriving on the way out renames database columns — and for
             # `toRolePhysicalName` those columns are the F_/FP_/FS_ load contract.
             "physical_name": _physical_override(r, _text(r, "name"), "physicalName"),
             "to_role_physical": _physical_override(
                 r, _text(r, "toRoleName"), "toRolePhysicalName"),
             "one_to_many": _bool(r, "oneToMany"),
             "delete_propagation": _text(r, "deletePropagation") or "RESTRICT",
             "validation_scope": _text(r, "validationScope") or "PRE_CONSO"}
            for r in model_el.iter("Reference")
        ],
    )
    return ir, unresolved


def _builtin_name(t: ET.Element, local_types: dict[str, str]) -> str:
    """A UserDefinedType narrows a built-in, referenced as <builtInType ref=…/>."""
    ref = t.find("builtInType")
    if ref is None:
        return "String"
    uuid = ref.attrib.get("ref", "")
    if uuid in local_types:
        return local_types[uuid]
    try:
        return resolve(uuid)
    except UnknownPlatformType:
        return unresolved_type(uuid)


def _ref_name(el: ET.Element, tag: str, names: dict[str, str]) -> str:
    """Resolve a ref= to the referenced object's name.

    An ElementTree Element with no children is FALSY, so `el.find(t) or default`
    silently discards a found-but-childless element. Always test `is not None`.
    """
    ref = el.find(tag)
    return names.get(ref.attrib.get("ref", ""), "Unknown") if ref is not None else "Unknown"


def _entity_name(model_el: ET.Element, ref_holder: ET.Element, tag: str) -> str:
    ref = ref_holder.find(tag)
    if ref is None:
        return ""
    uuid = ref.attrib.get("ref")
    for e in model_el.iter("Entity"):
        if _text(e, "internalID") == uuid:
            return _text(e, "name") or ""
    return ""
