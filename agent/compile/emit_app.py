"""Application layer, IR -> XML. Sprint 07.

Display cards and collections are emitted INSIDE their Entity, which is where xDM keeps
them — the Application element holds only actions, navigation, search and documentation
config.

Unknown components and properties are REFUSED, not guessed. The vocabulary in
component_vocab.yaml is harvested from real exports and is a floor, not a ceiling; a
wrong property key imports cleanly and misbehaves at runtime, which is worse than
failing the build.
"""
from __future__ import annotations

import functools
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from agent.compile import envelope
from agent.compile.emit import EmitError, ref, scalar, text


def _property_datatype(name: str, declared: str = "STRING") -> str:
    """The dataType the product writes for this property NAME.

    A property of the name, not of the value: 46 names, 8536 product-authored
    instances, zero ambiguity (`blocks.component_property_datatypes`). Hardcoding
    STRING here imported at 204, deployed and ran — and was 60 errors in the
    Application Builder's Validation view, the only register that reads the component
    registry (OBSERVED 2026-08-07, scenario 4). An IR declaration is honored only for
    a name the corpus has never seen; for a harvested name the lookup wins, because
    the encoding is the product's decision, not the author's (D3).

    Wire spelling note: the registry's error message says NUMBER; every export writes
    DECIMAL. Emit the export's spelling (§51.2).
    """
    from agent.compile.blocks import component_property_datatypes
    spec = component_property_datatypes().get(name)
    return spec["dataType"] if spec else declared


def fill_component_properties(holder, component, declared, uid, *, host) -> None:
    """Add the properties the product writes on EVERY instance of this component.

    Not in `blocks.complete()`, where it was first tried: that post-pass has no minting
    context, so it produced ComponentProperty elements with NO internalID — objects with
    no identity, which is precisely the defect that broke the very first import of the
    day (LESSONS §16). The import went 204 -> 500 the moment they were added.

    Here the emitter knows the path, so every property gets a deterministic UUID.

    `host` is load-bearing: the same componentName carries a different property set on
    a FormField than on a TableColumn — 20 versus 3 for semTextField — so the defaults
    are keyed by both. Reading them by component alone yielded the INTERSECTION, which
    is 2, and a form field that rendered essentially unconfigured.
    """
    from agent.compile.blocks import component_defaults
    spec = component_defaults().get(host, {}).get(component or "", {})
    for name in sorted(spec):
        if name in declared:
            continue
        cp = ET.SubElement(holder, "ComponentProperty")
        envelope.audit(cp, uid(name))
        text(cp, "name", name)
        text(cp, "value", spec[name])
        scalar(cp, "dataType", _property_datatype(name))
        scalar(cp, "valueInterpreter", "LITERAL")


def setting(el, tag, value) -> None:
    """A passthrough setting, encoded the way the PRODUCT encodes it.

    Assuming `val=` here was wrong for five elements — `Application.logoUrl`,
    `favIcon`, `avatarImageUrl`, `coverImageUrl` and `FolderAction.icon` are free text.
    Each would have imported at 204 and stored null, leaving an application with no
    branding and no icons, silently. Found by `blocks.check`, not by a deploy.

    None is an EXPLICIT null, which is not the same as the element being absent.
    """
    from agent.compile.blocks import library
    if value is None:
        text(el, tag, None)
    elif library().get(el.tag, {}).get("elements", {}).get(tag) == "text":
        text(el, tag, str(value))
    else:
        scalar(el, tag, value)
from agent.compile.mint import mint

VOCAB_PATH = Path(__file__).with_name("component_vocab.yaml")


@functools.lru_cache(maxsize=1)
def vocab() -> dict:
    return yaml.safe_load(VOCAB_PATH.read_text())


def check_component(component: str, properties) -> None:
    known = vocab()["components"]
    if component not in known:
        raise EmitError(
            f"unknown component {component!r}. Observed renderers: {sorted(known)}. "
            f"The vocabulary is harvested from real exports and is a floor — if this "
            f"one is genuine, build it once in the UI, export, and re-harvest "
            f"(agent/compile/harvest_vocab.py) rather than guessing its properties.")
    unknown = sorted({p.name for p in properties} - set(known[component]))
    if unknown:
        raise EmitError(
            f"unknown propert{'y' if len(unknown) == 1 else 'ies'} {unknown} on "
            f"{component!r}. A wrong key imports cleanly and misbehaves at runtime, so "
            f"it is refused rather than guessed.")


def default_card_for(entity) -> dict | None:
    """`subject_name` -> the entity's default display card.

    This is where the IR's "which attribute names a record?" finally lands. xDM has no
    entity-level display-name attribute; `primaryTextExpression` on a display card is
    what titles a record. One-way by design: extraction does NOT recover subject_name
    from a card, because primaryTextExpression is arbitrary SemQL (one sample uses a
    five-branch CASE) and guessing an attribute name back out of it would be invention.
    """
    if not entity.subject_name:
        return None
    return {"entity": entity.name, "name": f"{entity.name}DisplayCard",
            "default": True, "primary_text": entity.subject_name}


def emit_entity_app(entity_el: ET.Element, ename: str, app, enricher_uuid=None,
                    publisher_uuid=None, job_uuid=None) -> None:
    cards = [c for c in app.display_cards if c.entity == ename]
    colls = [c for c in app.collections if c.entity == ename]
    if cards:
        holder = ET.SubElement(entity_el, "displayCards")
        for c in cards:
            _display_card(holder, ename, c)
    if colls:
        holder = ET.SubElement(entity_el, "collections")
        for c in colls:
            _collection(holder, ename, c)
    steppers = [s for s in app.steppers if s.entity == ename]
    if steppers:
        holder = ET.SubElement(entity_el, "steppers")
        for st in steppers:
            _stepper(holder, ename, st, app, enricher_uuid, job_uuid)
    forms = [f for f in app.forms if f.entity == ename]
    if forms:
        holder = ET.SubElement(entity_el, "forms")
        for f in forms:
            _form(holder, ename, f)
    # Dups managers BEFORE action sets: the stewardship actions point at one, so the
    # validity check below needs the set of declared managers.
    dups = [d for d in app.dups_managers if d.entity == ename]
    if dups:
        holder = ET.SubElement(entity_el, "dupsManagers")
        for d in dups:
            _dups_manager(holder, ename, d, app, job_uuid)
    sets = [a for a in app.action_sets if a.entity == ename]
    if sets:
        holder = ET.SubElement(entity_el, "actionSets")
        for a in sets:
            _action_set(holder, ename, a, app, publisher_uuid, job_uuid)
    views = [v for v in app.business_views if v.entity == ename]
    if views:
        holder = ET.SubElement(entity_el, "businessObjectViews")
        for v in views:
            _business_view(holder, ename, v, app)


def emit_applications(model_el: ET.Element, app) -> None:
    """Model-level, so emit.py calls this once after the entities are built.

    Every ref here points at something an ENTITY owns — a business view, an import
    action, a built-in filter — which is why the applications are emitted last.
    """
    if not app.applications:
        return
    holder = ET.SubElement(model_el, "applications")
    for a in app.applications:
        _application(holder, a, app)


def _resolve_filter(app, name: str, where: str) -> str:
    """A built-in filter is named model-wide but STORED on a view node, so resolution
    searches. Ambiguity is refused rather than silently taking the first."""
    hits = [(v, n, f) for v in app.business_views for n in v.nodes for f in n.filters
            if f.name == name]
    if not hits:
        raise EmitError(
            f"{where} applies filter {name!r}, which is not declared on any business "
            f"view node")
    if len(hits) > 1:
        raise EmitError(
            f"{where} applies filter {name!r}, which is declared on "
            f"{len(hits)} different view nodes — qualify it or rename")
    v, n, f = hits[0]
    return mint("entity", v.entity, "boView", v.name, "node", n.name, "filter", f.name)


def _application(parent: ET.Element, a, app) -> None:
    el = ET.SubElement(parent, "Application")
    envelope.audit(el, mint("application", a.name))
    text(el, "name", a.name)
    text(el, "label", a.label)
    text(el, "applicationTitle", a.title)
    text(el, "description", a.description)
    text(el, "requiredRoleName", a.required_role)
    # Per-area role gates. All present on every Application in every sample, null when
    # ungated — and a null here means "no extra role required", not "absent".
    for tag in ("certificationQueueRequiredRoleName", "dashboardRequiredRoleName",
                "entitiesListRequiredRoleName", "errorsNavigationRequiredRoleName",
                "historyBrowsingRequiredRole", "lineageRequiredRoleName"):
        text(el, tag, a.area_roles.get(tag))
    text(el, "errorColor", None)
    ET.SubElement(el, "humanWorkflows")
    for k, v in a.settings.items():
        setting(el, k, v)

    def auid(name: str) -> str:
        return mint("application", a.name, "action", name)

    known = {x.name for x in a.actions}
    folders = {x.name for x in a.actions if x.kind == "FolderAction"}
    views = {(v.entity, v.name) for v in app.business_views}
    imports = {(s.entity, s.name, x.name) for s in app.action_sets for x in s.actions
               if x.kind == "ImportAction"}
    if a.default_action:
        if a.default_action not in known:
            raise EmitError(
                f"application {a.name!r}: defaultAction {a.default_action!r} is not one "
                f"of its actions")
        ref(el, "defaultAction", auid(a.default_action))
    if a.actions:
        ah = ET.SubElement(el, "abstractAppActions")
        for x in a.actions:
            _app_action(ah, a, x, auid, folders, views, imports, app)
    dh = ET.SubElement(el, "documentationConfig")
    dc = ET.SubElement(dh, "DocumentationConfig")
    envelope.audit(dc, mint("application", a.name, "documentationConfig"))
    text(dc, "documentation", a.documentation)
    ET.SubElement(dc, "documentationConfigDiagrams")
    gh = ET.SubElement(el, "globalSearchConfig")
    gc = ET.SubElement(gh, "GlobalSearchConfig")
    envelope.audit(gc, mint("application", a.name, "globalSearchConfig"))
    scalar(gc, "displaySearchForDropdown", a.search_dropdown)
    scalar(gc, "sortBOViewsAlphabetically", a.search_sort_alphabetically)
    if not a.search_entries:
        ET.SubElement(gc, "globalSearchBoViews")
    if a.search_entries:
        bh = ET.SubElement(gc, "globalSearchBoViews")
        for e in a.search_entries:
            if (e.view_entity, e.view) not in views:
                raise EmitError(
                    f"application {a.name!r}: global search entry {e.name!r} names "
                    f"business view {e.view!r} on {e.view_entity!r}, which is not "
                    f"declared")
            be = ET.SubElement(bh, "GlobalSearchBoView")
            envelope.audit(be, mint("application", a.name, "search", e.name))
            text(be, "name", e.name)
            text(be, "label", e.label)
            scalar(be, "maxResults", e.max_results)
            scalar(be, "position", e.position)
            scalar(be, "viewType", e.view_type)
            ref(be, "businessObjectView",
                mint("entity", e.view_entity, "boView", e.view))
            ref(be, "searchTypeConfig",
                mint("entity", e.view_entity, "boView", e.view, "node", e.search_node,
                     "search", e.search_type))
    if a.navigation:
        nh = ET.SubElement(el, "navigationConfig")
        nc = ET.SubElement(nh, "NavigationConfig")
        envelope.audit(nc, mint("application", a.name, "navigationConfig"))
        gph = ET.SubElement(nc, "navigationGroups")
        for g in a.navigation:
            ge = ET.SubElement(gph, "FolderNavigationGroup" if g.kind == "folder"
                               else "NavigationGroup")
            envelope.audit(ge, mint("application", a.name, "navGroup", g.name))
            text(ge, "name", g.name)
            if g.kind == "group":
                text(ge, "label", g.label)
            scalar(ge, "position", g.position)
            scalar(ge, "labelVisible", g.label_visible)
            scalar(ge, "dividerVisible", g.divider_visible)
            if g.folder:
                if g.folder not in folders:
                    raise EmitError(
                        f"application {a.name!r}: navigation group {g.name!r} wraps "
                        f"folder {g.folder!r}, which is not a FolderAction")
                ref(ge, "underlyingFolder", auid(g.folder))
            if g.items:
                ih = ET.SubElement(ge, "navigationItems")
                for i in g.items:
                    if i.action not in known:
                        raise EmitError(
                            f"application {a.name!r}: navigation group {g.name!r} "
                            f"lists action {i.action!r}, which it does not declare")
                    ie = ET.SubElement(ih, "NavigationItem")
                    envelope.audit(ie, mint("application", a.name, "navGroup", g.name,
                                            "item", i.action))
                    scalar(ie, "position", i.position)
                    ref(ie, "appAction", auid(i.action))


def _app_action(parent: ET.Element, a, x, auid, folders, views, imports, app) -> None:
    el = ET.SubElement(parent, x.kind)
    envelope.audit(el, auid(x.name))
    text(el, "name", x.name)
    text(el, "label", x.label)
    text(el, "requiredRole", x.required_role)
    scalar(el, "posInFolder", x.position)
    for k, v in x.settings.items():
        setting(el, k, v)
    where = f"application {a.name!r} action {x.name!r}"
    if x.parent_folder:
        if x.parent_folder not in folders:
            raise EmitError(
                f"{where} sits in folder {x.parent_folder!r}, which is not a "
                f"FolderAction of this application")
        ref(el, "parentFolder", auid(x.parent_folder))
    else:
        text(el, "parentFolder", None)
    if x.view:
        if (x.view_entity, x.view) not in views:
            raise EmitError(
                f"{where} opens business view {x.view!r} on entity {x.view_entity!r}, "
                f"which is not declared")
        ref(el, "businessObjectView", mint("entity", x.view_entity, "boView", x.view))
    if x.applied_filter:
        ref(el, "appliedFilter", _resolve_filter(app, x.applied_filter, where))
    if x.import_action:
        key = (x.import_entity, x.import_action_set, x.import_action)
        if key not in imports:
            raise EmitError(
                f"{where} runs import action {'.'.join(str(k) for k in key)}, which is "
                f"not declared")
        ref(el, "importAction",
            mint("entity", x.import_entity, "actionSet", x.import_action_set,
                 "action", x.import_action))


def _display_card(parent: ET.Element, ename: str, c) -> None:
    el = ET.SubElement(parent, "DisplayCard")
    envelope.audit(el, mint("entity", ename, "displayCard", c.name))
    text(el, "name", c.name)
    scalar(el, "default", c.default)
    # primaryTextExpression is what titles a record — the real home of subject_name.
    text(el, "primaryTextExpression", c.primary_text)
    text(el, "secondaryTextExpression", c.secondary_text)
    text(el, "supportingTextExpression", c.supporting_text)
    text(el, "avatarImageValue", c.avatar_image)
    text(el, "description", None)
    text(el, "primaryImageValue", c.primary_image)
    text(el, "primaryImageFallbackValue", None)
    scalar(el, "primaryImageFallbackSourceType", "URL")
    scalar(el, "primaryImageFallbackValueInterpreter", "LITERAL")
    for tag, v in (("avatarImageAlign", "MIDDLE_CENTER"), ("avatarImageMode", "FIT"),
                   ("avatarImageSourceType", "URL"),
                   ("avatarImageValueInterpreter", "LITERAL"),
                   ("primaryImageAlign", "MIDDLE_CENTER"), ("primaryImageMode", "FIT"),
                   ("primaryImageSourceType", "URL"),
                   ("primaryImageValueInterpreter", "LITERAL")):
        scalar(el, tag, v)


def _collection(parent: ET.Element, ename: str, c) -> None:
    el = ET.SubElement(parent, "CollectionView")
    envelope.audit(el, mint("entity", ename, "collection", c.name))
    text(el, "name", c.name)
    scalar(el, "default", c.default)
    text(el, "description", c.description)
    scalar(el, "tableAllowed", c.table_allowed)
    scalar(el, "listAllowed", c.list_allowed)
    scalar(el, "gridAllowed", c.grid_allowed)
    # Every list/grid/table display field the product writes on a CollectionView.
    for tag in ("gridColumns", "gridTextPosition", "gridTileHeight", "gridTileLines",
                "listItemLines", "listShowDisplayCardAvatar", "listShowDivider",
                "tableDisplayCardColumnLabel", "tableDisplayCardColumnWidth",
                "tableRowLines", "tableShowDisplayCard"):
        setting(el, tag, c.settings.get(tag))
    if c.display_card:
        ref(el, "displayCard", mint("entity", ename, "displayCard", c.display_card))
    if c.columns:
        holder = ET.SubElement(el, "tableColumns")
        for col in c.columns:
            _column(holder, ename, c.name, col)


def _column(parent: ET.Element, ename: str, cname: str, col) -> None:
    check_component(col.component, col.properties)
    el = ET.SubElement(parent, "TableColumn")
    envelope.audit(el, mint("entity", ename, "collection", cname, "col", col.name))
    text(el, "name", col.name)
    text(el, "value", col.value)
    text(el, "componentName", col.component)
    text(el, "label", col.label)
    scalar(el, "valueDataType", col.data_type)
    scalar(el, "columnAlign", col.align)
    scalar(el, "visibleByDefault", col.visible)
    scalar(el, "posInParent", col.position)
    text(el, "description", None)
    text(el, "documentation", None)
    scalar(el, "documentationInterpreter", "LITERAL")
    text(el, "defaultWidth", col.default_width)
    text(el, "labelColor", None)
    text(el, "displayCard", None)
    text(el, "referencedEntity", None)
    scalar(el, "useCustomLabel", bool(col.label))
    holder = ET.SubElement(el, "componentProperties")
    fill_component_properties(
        holder, col.component, {p.name for p in col.properties},
        lambda n: mint("entity", ename, "collection", cname, "col", col.name, "prop", n),
        host="TableColumn")
    if col.properties:
        for p in col.properties:
            cp = ET.SubElement(holder, "ComponentProperty")
            envelope.audit(cp, mint("entity", ename, "collection", cname, "col",
                                    col.name, "prop", p.name))
            text(cp, "name", p.name)
            # "" is a REAL value meaning "inherit the default" — not the same as unset.
            text(cp, "value", p.value)
            scalar(cp, "dataType", _property_datatype(p.name, p.data_type))
            scalar(cp, "valueInterpreter", "LITERAL")


CONTAINER_TAG = {"tab": "FormTab", "section": "FormContainer",
                 "section2": "FormSection2"}


def _form(parent: ET.Element, ename: str, f) -> None:
    el = ET.SubElement(parent, "Form")
    envelope.audit(el, mint("entity", ename, "form", f.name))
    text(el, "name", f.name)
    scalar(el, "default", f.default)
    # The product writes these on EVERY Form, as explicit nulls or empty holders.
    # Omitting an element is not the same as emitting it null — that is what made the
    # survivorship import refuse (LESSONS §19), and the app layer had the same gap.
    text(el, "description", f.description)
    text(el, "documentation", f.documentation)
    for empty in ("formCharts", "formCollections", "formDashboards"):
        ET.SubElement(el, empty)

    def cuid(name: str) -> str:
        return mint("entity", ename, "form", f.name, "container", name)

    known = {c.name for c in f.containers}
    if f.containers:
        holder = ET.SubElement(el, "formContainers")
        for c in f.containers:
            if c.parent and c.parent not in known:
                raise EmitError(
                    f"form {f.name!r}: container {c.name!r} has parent {c.parent!r}, "
                    f"which is not declared in this form")
            ce = ET.SubElement(holder, CONTAINER_TAG[c.kind])
            envelope.audit(ce, cuid(c.name))
            text(ce, "name", c.name)
            text(ce, "label", c.label)
            text(ce, "description", None)
            text(ce, "documentation", None)
            scalar(ce, "documentationInterpreter", "LITERAL")
            text(ce, "iconUrl", None)
            text(ce, "labelWidth", None)
            scalar(ce, "displayFormTabAs", c.display_as)
            text(ce, "visibleValue", c.visible_value)
            scalar(ce, "visibleValueInterpreter", "LITERAL")
            scalar(ce, "posInParent", c.position)
            if c.parent:
                ref(ce, "parentFormContainer", cuid(c.parent))
            else:
                text(ce, "parentFormContainer", None)
    if f.fields:
        holder = ET.SubElement(el, "formFields")
        for fl in f.fields:
            check_component(fl.component, fl.properties)
            if fl.container and fl.container not in known:
                raise EmitError(
                    f"form {f.name!r}: field {fl.name!r} sits in container "
                    f"{fl.container!r}, which is not declared in this form")
            fe = ET.SubElement(holder, "FormField")
            envelope.audit(fe, mint("entity", ename, "form", f.name, "field", fl.name))
            text(fe, "name", fl.name)
            text(fe, "value", fl.value)
            text(fe, "componentName", fl.component)
            text(fe, "label", fl.label)
            text(fe, "relativeWidth", fl.relative_width)
            text(fe, "description", None)
            text(fe, "documentation", None)
            scalar(fe, "documentationInterpreter", "LITERAL")
            scalar(fe, "useCustomLabel", bool(fl.label))
            text(fe, "visibleValue", fl.visible_value)
            scalar(fe, "visibleValueInterpreter", "LITERAL")
            text(fe, "displayCard", None)
            text(fe, "referencedEntity", None)
            scalar(fe, "valueDataType", fl.data_type)
            scalar(fe, "posInParent", fl.position)
            if fl.container:
                ref(fe, "parentFormContainer", cuid(fl.container))
            else:
                text(fe, "parentFormContainer", None)
            ph = ET.SubElement(fe, "componentProperties")
            fill_component_properties(
                ph, fl.component, {p.name for p in fl.properties},
                lambda n: mint("entity", ename, "form", f.name, "field", fl.name,
                               "prop", n),
                host="FormField")
            if fl.properties:
                for p in fl.properties:
                    cp = ET.SubElement(ph, "ComponentProperty")
                    envelope.audit(cp, mint("entity", ename, "form", f.name, "field",
                                            fl.name, "prop", p.name))
                    text(cp, "name", p.name)
                    text(cp, "value", p.value)
                    scalar(cp, "dataType", _property_datatype(p.name, p.data_type))
                    scalar(cp, "valueInterpreter", "LITERAL")


def _names(app, ename: str):
    """The four name sets an app-layer ref may legally land in, for this entity."""
    return (
        {s.name for s in app.steppers if s.entity == ename},
        {c.name for c in app.display_cards if c.entity == ename},
        {c.name for c in app.collections if c.entity == ename},
        {f.name: {c.name for c in f.containers if c.kind == "tab"}
         for f in app.forms if f.entity == ename},
    )


def _form_tab_ref(el: ET.Element, ename: str, forms: dict, form, tab, where: str) -> None:
    # A tab name is unique only within its form, so both are required to resolve it.
    if form not in forms or tab not in forms[form]:
        raise EmitError(
            f"{where} opens tab {tab!r} of form {form!r}, which is not declared "
            f"on {ename!r}")
    ref(el, "formTab", mint("entity", ename, "form", form, "container", tab))


def _dups_manager(parent: ET.Element, ename: str, d, app, job_uuid) -> None:
    _, cards, colls, forms = _names(app, ename)
    el = ET.SubElement(parent, "DupsManager")
    envelope.audit(el, mint("entity", ename, "dupsManager", d.name))
    text(el, "name", d.name)
    text(el, "label", d.label)
    text(el, "description", d.description)
    for k, v in d.settings.items():
        setting(el, k, v)
    text(el, "checkoutSortExpression", d.checkout_sort_expression)
    for field, tag, name in (("collection", "collectionView", d.collection),
                             ("table_collection", "tableViewCollection",
                              d.table_collection)):
        if name:
            if name not in colls:
                raise EmitError(
                    f"dups manager {d.name!r}: {field} {name!r} is not a collection "
                    f"of entity {ename!r}")
            ref(el, tag, mint("entity", ename, "collection", name))
        else:
            text(el, tag, None)
    if d.display_card:
        if d.display_card not in cards:
            raise EmitError(
                f"dups manager {d.name!r} names display card {d.display_card!r}, "
                f"which is not declared on {ename!r}")
        ref(el, "displayCard", mint("entity", ename, "displayCard", d.display_card))
    if d.form_tab:
        _form_tab_ref(el, ename, forms, d.form, d.form_tab,
                      f"dups manager {d.name!r}")
    if d.model_job:
        if job_uuid is None:
            raise EmitError(
                f"dups manager {d.name!r} runs job {d.model_job!r} but no "
                f"certification IR was supplied to resolve it")
        ref(el, "modelJob", job_uuid(d.model_job))
    _search_configs(el, "DupsCheckoutSearchTypeConfig", "checkoutSearchConfigs",
                    d.search_configs,
                    {n: mint("entity", ename, "form", n) for n in forms},
                    lambda st: mint("entity", ename, "dupsManager", d.name,
                                    "search", st), f"dups manager {d.name!r}")


def _action_set(parent: ET.Element, ename: str, a, app, publisher_uuid,
                job_uuid=None) -> None:
    el = ET.SubElement(parent, "ActionSet")
    envelope.audit(el, mint("entity", ename, "actionSet", a.name))
    text(el, "name", a.name)
    text(el, "label", a.label)
    text(el, "description", a.description)
    scalar(el, "defaultActionSet", a.default)
    if not a.actions:
        return
    steppers, cards, _colls, forms = _names(app, ename)
    dups = {d.name for d in app.dups_managers if d.entity == ename}
    holder = ET.SubElement(el, "actions")
    for act in a.actions:
        ae = ET.SubElement(holder, act.kind)
        envelope.audit(ae, mint("entity", ename, "actionSet", a.name,
                                "action", act.name))
        text(ae, "name", act.name)
        text(ae, "label", act.label)
        text(ae, "requiredRole", act.required_role)
        scalar(ae, "posInParent", act.position)
        for k, v in act.settings.items():
            setting(ae, k, v)
        if act.stepper:
            if act.stepper not in steppers:
                raise EmitError(
                    f"action {a.name}.{act.name} runs stepper {act.stepper!r}, which "
                    f"is not a stepper of entity {ename!r}")
            ref(ae, "stepper", mint("entity", ename, "stepper", act.stepper))
        if act.publisher:
            if publisher_uuid is None:
                raise EmitError(
                    f"action {a.name}.{act.name} names publisher {act.publisher!r} but "
                    f"no publisher resolver was supplied")
            ref(ae, "defaultPublisher", publisher_uuid(act.publisher))
        if act.display_card:
            if act.display_card not in cards:
                raise EmitError(
                    f"action {a.name}.{act.name} names display card "
                    f"{act.display_card!r}, which is not declared on {ename!r}")
            ref(ae, "displayCard",
                mint("entity", ename, "displayCard", act.display_card))
        if act.form_tab:
            _form_tab_ref(ae, ename, forms, act.form, act.form_tab,
                          f"action {a.name}.{act.name}")
        if act.dups_manager:
            if act.dups_manager not in dups:
                raise EmitError(
                    f"action {a.name}.{act.name} is a stewardship action on duplicate "
                    f"manager {act.dups_manager!r}, which is not declared on "
                    f"{ename!r} — the queue it reviews does not exist")
            ref(ae, "dupsManager",
                mint("entity", ename, "dupsManager", act.dups_manager))
        if act.model_job:
            if job_uuid is None:
                raise EmitError(
                    f"action {a.name}.{act.name} runs job {act.model_job!r} but no "
                    f"certification IR was supplied to resolve it")
            ref(ae, "modelJob", job_uuid(act.model_job))


def _search_configs(parent: ET.Element, tag: str, holder_tag: str, configs,
                    forms: dict, uid, where: str) -> None:
    if not configs:
        return
    h = ET.SubElement(parent, holder_tag)
    for c in configs:
        ce = ET.SubElement(h, tag)
        envelope.audit(ce, uid(c.search_type))
        scalar(ce, "searchType", c.search_type)
        scalar(ce, "enabled", c.enabled)
        scalar(ce, "posInParent", c.position)
        if c.custom_form:
            if c.custom_form not in forms:
                raise EmitError(
                    f"{where}: search config names custom form {c.custom_form!r}, "
                    f"which is not declared on the entity it searches")
            ref(ce, "customForm", forms[c.custom_form])
        else:
            text(ce, "customForm", None)


def _business_view(parent: ET.Element, ename: str, v, app) -> None:
    el = ET.SubElement(parent, "BusinessObjectView")
    envelope.audit(el, mint("entity", ename, "boView", v.name))
    text(el, "name", v.name)
    text(el, "label", v.label)
    text(el, "description", v.description)
    text(el, "rootLabel", v.root_label)
    text(el, "rootPluralLabel", v.root_plural_label)
    text(el, "rootDescription", v.root_description)
    text(el, "iconUrl", None)
    text(el, "filter", v.filter)
    text(el, "requiredRoleName", v.required_role)
    for k, val in v.settings.items():
        setting(el, k, val)

    def nuid(name: str) -> str:
        return mint("entity", ename, "boView", v.name, "node", name)

    known = {n.name for n in v.nodes}
    if v.root not in known:
        raise EmitError(
            f"business view {v.name!r}: root {v.root!r} is not one of its nodes")
    ref(el, "rootBOViewEntity", nuid(v.root))
    if not v.nodes:
        return
    holder = ET.SubElement(el, "BOViewEntities")
    for n in v.nodes:
        _bo_view_node(holder, ename, v, n, app, known, nuid)


def _bo_view_node(parent, ename: str, v, n, app, known: set, nuid) -> None:
    # Each node resolves against ITS OWN entity, not the view's owner — a view walks
    # the model graph, so a node may sit on any entity.
    steppers, cards, colls, form_tabs = _names(app, n.entity)
    sets = {a.name for a in app.action_sets if a.entity == n.entity}
    forms = {name: mint("entity", n.entity, "form", name) for name in form_tabs}

    el = ET.SubElement(parent, "BOViewEntity")
    envelope.audit(el, nuid(n.name))
    text(el, "name", n.name)
    text(el, "sortExpression", n.sort_expression)
    for k, val in n.settings.items():
        setting(el, k, val)
    ref(el, "entity", mint("entity", n.entity))
    where = f"business view {v.name!r} node {n.name!r}"
    if n.collection:
        if n.collection not in colls:
            raise EmitError(
                f"{where}: collection {n.collection!r} is not declared on entity "
                f"{n.entity!r}")
        ref(el, "collection", mint("entity", n.entity, "collection", n.collection))
    for field, tag in (("form", "form"), ("form_view", "formView"),
                       ("data_entry_form", "dataEntryFormView")):
        name = getattr(n, field)
        if name:
            if name not in forms:
                raise EmitError(
                    f"{where}: {field} {name!r} is not declared on entity "
                    f"{n.entity!r}")
            ref(el, tag, forms[name])
        else:
            text(el, tag, None)
    if n.action_set:
        if n.action_set not in sets:
            raise EmitError(
                f"{where}: action set {n.action_set!r} is not declared on entity "
                f"{n.entity!r}")
        ref(el, "actionSet", mint("entity", n.entity, "actionSet", n.action_set))
    else:
        text(el, "actionSet", None)
    text(el, "displayCard", None)
    text(el, "tableView", None)
    if n.display_card:
        if n.display_card not in cards:
            raise EmitError(
                f"{where}: display card {n.display_card!r} is not declared on entity "
                f"{n.entity!r}")
        ref(el, "recordNodeDisplayCard",
            mint("entity", n.entity, "displayCard", n.display_card))
    else:
        text(el, "recordNodeDisplayCard", None)
    for empty in ("embeddedCollectionNavigations",
                  "referenceAttributeEditionConfigs",
                  "referenceAttributeNavigationConfigs"):
        ET.SubElement(el, empty)
    if not n.filters:
        ET.SubElement(el, "businessEntityBuiltInFilters")
    if not n.transitions:
        ET.SubElement(el, "transitions")
    if n.filters:
        fh = ET.SubElement(el, "businessEntityBuiltInFilters")
        for f in n.filters:
            fe = ET.SubElement(fh, "BusinessEntityBuiltInFilter")
            envelope.audit(fe, mint("entity", ename, "boView", v.name, "node", n.name,
                                    "filter", f.name))
            text(fe, "name", f.name)
            text(fe, "label", f.label)
            text(fe, "description", f.description)
            text(fe, "semQLCondition", f.condition)
            scalar(fe, "visible", f.visible)
    _search_configs(el, "BusinessEntitySearchTypeConfig", "businessEntitySearchConfigs",
                    n.search_configs, forms,
                    lambda st: mint("entity", ename, "boView", v.name, "node", n.name,
                                    "search", st), where)
    if n.transitions:
        th = ET.SubElement(el, "transitions")
        for t in n.transitions:
            if t.target not in known:
                raise EmitError(
                    f"{where}: transition {t.name!r} targets node {t.target!r}, which "
                    f"is not a node of this view")
            te = ET.SubElement(th, "BOViewTransition")
            envelope.audit(te, mint("entity", ename, "boView", v.name, "node", n.name,
                                    "transition", t.name))
            text(te, "name", t.name)
            text(te, "transitionPath", t.path)
            scalar(te, "posInParent", t.position)
            for k, val in t.settings.items():
                setting(te, k, val)
            ref(te, "targetBOViewEntity", nuid(t.target))


STEP_TAG = {"form": "FormStep", "collection": "CollectionStep"}


def _derive_root(ename: str, st, colls: set[str]):
    """A stepper cannot be a bare form, so supply the root collection step.

    MEASURED across every Stepper in samples/, live/ and harvest/ — 20 instances:

        rootCollectionStep          ref in 20/20, NEVER null
        it resolves to a CollectionStep inside <steps>   20/20
        FormStep.parentCollectionStep   ref in 26/26, NEVER null
        FormStep.formTab                ref in 26/26, NEVER null
        steppers with no CollectionStep at all           0/20

    So "one form step and nothing else" is not a smaller stepper — it is a shape the
    product has never written. That is exactly the D3 line: the IR says a steward
    authors a Party through this form, and deterministic code supplies the nesting the
    product requires. An author should no more have to know a stepper roots in a
    collection than that every FormField carries a documentationInterpreter.

    Returns a synthesised StepperStep, or None when the author declared their own root.
    The IR object is NEVER mutated — the synthesis is local to this emit.
    """
    from agent.ir.schema import StepperStep
    roots = [s for s in st.steps if s.kind == "collection" and not s.parent_step]
    if len(roots) > 1:
        raise EmitError(
            f"stepper {st.name!r} has {len(roots)} collection steps with no parent "
            f"({', '.join(r.name for r in roots)}). Exactly one step is the root in all "
            f"20 observed steppers; which of these it should be is a design decision, "
            f"so name a parent_step on the others.")
    if roots:
        return None
    name = st.collection or next(iter(sorted(colls)), None)
    if not name:
        raise EmitError(
            f"stepper {st.name!r} declares no collection step and entity {ename!r} has "
            f"no collection to root one in. CollectionStep.collectionView is a real ref "
            f"in 24/24 observed instances and never null, so there is nothing valid to "
            f"emit — declare a collection on the entity, or name one on the stepper.")
    if name not in colls:
        raise EmitError(
            f"stepper {st.name!r} roots in collection {name!r}, which is not a "
            f"collection of entity {ename!r}")
    return StepperStep(kind="collection", name=name, label=name, position=0,
                       collection=name)


def _stepper(parent: ET.Element, ename: str, st, app, enricher_uuid,
             job_uuid=None) -> None:
    _, _cards, colls, _ = _names(app, ename)
    # MODEL-WIDE, not entity-scoped, and that distinction is measured rather than
    # defensive: 3 of 26 form steps and 3 of 24 collection steps in the corpus point at
    # a form or collection on a DIFFERENT entity — the Product -> Items -> Images
    # nesting, where a child step is about the child. Scoping these to the stepper's own
    # entity refuses six real steps the product wrote.
    #
    # Tabs are kept IN ORDER, which `_names` cannot give — it returns a set, and "the
    # first tab" has to be deterministic or the default is a coin flip.
    all_tabs = {(f.entity, f.name): [c.name for c in sorted(f.containers,
                                                            key=lambda c: c.position)
                                     if c.kind == "tab"]
                for f in app.forms}
    all_colls = {(c.entity, c.name) for c in app.collections}

    el = ET.SubElement(parent, "Stepper")
    envelope.audit(el, mint("entity", ename, "stepper", st.name))
    text(el, "name", st.name)
    text(el, "label", st.label)
    if st.model_job:
        if job_uuid is None:
            raise EmitError(
                f"stepper {st.name!r} runs job {st.model_job!r} on finish but no "
                f"certification IR was supplied to resolve it")
        ref(el, "modelJob", job_uuid(st.model_job))

    def suid(name: str) -> str:
        return mint("entity", ename, "stepper", st.name, "step", name)

    if not st.steps:
        return
    derived = _derive_root(ename, st, colls)
    steps = ([derived] + list(st.steps)) if derived else list(st.steps)
    root = derived or next(s for s in steps
                           if s.kind == "collection" and not s.parent_step)

    # rootCollectionStep BEFORE <steps>, which is where the product puts it.
    ref(el, "rootCollectionStep", suid(root.name))

    known = {s.name for s in steps}
    holder = ET.SubElement(el, "steps")
    for s in steps:
        if s.parent_step and s.parent_step not in known:
            raise EmitError(
                f"stepper {st.name!r}: step {s.name!r} has parent {s.parent_step!r}, "
                f"which is not a step of this stepper")
        se = ET.SubElement(holder, STEP_TAG[s.kind])
        envelope.audit(se, suid(s.name))
        text(se, "name", s.name)
        text(se, "label", s.label)
        scalar(se, "posInParent", s.position)
        # Passthrough toggles, carried verbatim rather than modelled one by one.
        for k, v in s.settings.items():
            setting(se, k, v)
        sent = s.entity or ename          # the entity this step is ABOUT
        if s.kind == "collection":
            cname = s.collection or s.name
            if (sent, cname) not in all_colls:
                raise EmitError(
                    f"stepper {st.name!r}: collection step {s.name!r} lists "
                    f"{cname!r}, which is not a collection of entity {sent!r}")
            ref(se, "collectionView", mint("entity", sent, "collection", cname))
        else:
            # A FormStep shows one TAB. `formTab` is a real ref in 26/26 instances, so
            # there is no valid form step without one — but WHICH tab is derivable when
            # the form has one obvious answer, and the author already named the form.
            if not s.form:
                raise EmitError(
                    f"stepper {st.name!r}: form step {s.name!r} names no form. A form "
                    f"step opens a TAB of a form and `formTab` is never null in any of "
                    f"the 26 observed instances, so there is nothing to point it at.")
            tabs = all_tabs.get((sent, s.form))
            if not tabs:
                raise EmitError(
                    f"stepper {st.name!r}: form step {s.name!r} opens form {s.form!r}, "
                    f"which is not a form of entity {sent!r} or declares no tab")
            tab = s.form_tab or tabs[0]
            if tab not in tabs:
                raise EmitError(
                    f"stepper {st.name!r} step {s.name!r} opens tab {tab!r} of form "
                    f"{s.form!r}, which is not a tab of that form on {sent!r}")
            ref(se, "formTab", mint("entity", sent, "form", s.form, "container", tab))
        # EVERY non-root step is parented, not just the ones that said so.
        # `parentCollectionStep` is a real ref in 26/26 form steps and the deployer
        # dereferences it; a form step floating beside the root is the shape that
        # imports at 204 and then has nowhere to render.
        if s.parent_step:
            ref(se, "parentCollectionStep", suid(s.parent_step))
        elif s is not root:
            ref(se, "parentCollectionStep", suid(root.name))
        if s.enrichers:
            eh = ET.SubElement(se, "formStepEnrichers")
            for b in s.enrichers:
                if enricher_uuid is None:
                    raise EmitError(
                        f"stepper {st.name!r} binds enricher {b.enricher!r} but no "
                        f"certification IR was supplied to resolve it")
                be = ET.SubElement(eh, "FormStepEnricher")
                envelope.audit(be, mint("entity", ename, "stepper", st.name, "step",
                                        s.name, "enricherBinding", b.enricher))
                scalar(be, "executedOnFormOpen", b.on_form_open)
                scalar(be, "executedOnDataChange", b.on_data_change)
                scalar(be, "executedOnButtonClick", b.on_button_click)
                ref(be, "enricher", enricher_uuid(b.enricher))
