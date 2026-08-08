"""Application layer, XML -> IR. Sprint 07.

Display cards and collections live under Entity, not under Application — the
Application element itself is thin (actions, navigation, search and documentation
config). Forms, steppers and actions follow in later steps of this sprint.

A display card is where `subject_name` actually lives: `primaryTextExpression` is what
titles a record, and an Entity has no display-name attribute of its own.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from agent.ir.schema import AppIR


def _text(el: ET.Element, tag: str) -> str | None:
    c = el.find(tag)
    if c is None:
        return None
    v = c.attrib.get("val", c.text)
    return v if v not in ("", None) else None


def _bool(el: ET.Element, tag: str, default: bool = False) -> bool:
    v = _text(el, tag)
    return default if v is None else v == "true"


def extract_app(path: str | Path) -> AppIR:
    root = ET.parse(path).getroot()
    model = root.find("Model")
    # Display cards are referenced by UUID from collections; build the lookup first.
    card_names = {_text(c, "internalID"): _text(c, "name")
                  for c in model.iter("DisplayCard")}

    cards, collections = [], []
    for entity in model.iter("Entity"):
        ename = _text(entity, "name")
        for holder in entity.findall("displayCards"):
            for c in holder.iter("DisplayCard"):
                cards.append({
                    "entity": ename, "name": _text(c, "name"),
                    "default": _bool(c, "default"),
                    "primary_text": _text(c, "primaryTextExpression") or "",
                    "secondary_text": _text(c, "secondaryTextExpression"),
                    "supporting_text": _text(c, "supportingTextExpression"),
                    "avatar_image": _text(c, "avatarImageValue"),
                })
        for holder in entity.findall("collections"):
            for v in holder.iter("CollectionView"):
                ref = v.find("displayCard")
                collections.append({
                    "entity": ename, "name": _text(v, "name"),
                    "default": _bool(v, "default"),
                    "display_card": card_names.get(ref.attrib.get("ref")) if ref is not None else None,
                    "table_allowed": _bool(v, "tableAllowed", True),
                    "list_allowed": _bool(v, "listAllowed", True),
                    "grid_allowed": _bool(v, "gridAllowed", True),
                    "columns": [
                        {"name": _text(t, "name"), "value": _text(t, "value") or "",
                         "component": _text(t, "componentName") or "semTextField",
                         "label": _text(t, "label"),
                         "data_type": _text(t, "valueDataType") or "STRING",
                         "align": _text(t, "columnAlign") or "LEFT",
                         "visible": _bool(t, "visibleByDefault", True),
                         "position": int(_text(t, "posInParent") or 0),
                         "properties": [
                             {"name": _text(cp, "name") or "",
                              "value": _text(cp, "value") or ""}
                             for cp in t.iter("ComponentProperty")]}
                        for t in v.iter("TableColumn")],
                })
    forms = []
    for entity in model.iter("Entity"):
        ename = _text(entity, "name")
        for holder in entity.findall("forms"):
            for f in holder.iter("Form"):
                forms.append(_form(f, ename))
    steppers = []
    for entity in model.iter("Entity"):
        ename = _text(entity, "name")
        for holder in entity.findall("steppers"):
            for st in holder.iter("Stepper"):
                steppers.append(_stepper(st, ename, model))
    action_sets = []
    for entity in model.iter("Entity"):
        ename = _text(entity, "name")
        for holder in entity.findall("actionSets"):
            for a in holder.iter("ActionSet"):
                action_sets.append(_action_set(a, ename, entity, model))
    dups = []
    for entity in model.iter("Entity"):
        ename = _text(entity, "name")
        for holder in entity.findall("dupsManagers"):
            for d in holder.iter("DupsManager"):
                dups.append(_dups_manager(d, ename, entity, model))
    views = []
    for entity in model.iter("Entity"):
        ename = _text(entity, "name")
        for holder in entity.findall("businessObjectViews"):
            for v in holder.iter("BusinessObjectView"):
                views.append(_business_view(v, ename, model))
    apps = [_application(a, model) for holder in model.findall("applications")
            for a in holder.iter("Application")]
    return AppIR(applications=apps, display_cards=cards, collections=collections,
                 forms=forms, steppers=steppers, action_sets=action_sets,
                 dups_managers=dups, business_views=views)


_APP_STRUCTURAL = {"name", "label", "applicationTitle", "description",
                   "requiredRoleName", "defaultAction", "abstractAppActions",
                   "navigationConfig", "globalSearchConfig", "documentationConfig",
                   "humanWorkflows"}
_APP_ACTION_STRUCTURAL = {"name", "label", "posInFolder", "requiredRole", "parentFolder",
                          "businessObjectView", "appliedFilter", "importAction",
                          "parameters"}


def _application(a: ET.Element, model: ET.Element) -> dict:
    """The Application is model-level and thin: a menu tree plus theming."""
    action_names = {_text(x, "internalID"): _text(x, "name")
                    for h in a.findall("abstractAppActions") for x in h}
    view_owner = {_text(v, "internalID"): (_text(e, "name"), _text(v, "name"))
                  for e in model.iter("Entity")
                  for v in e.iter("BusinessObjectView")}
    filters = {_text(f, "internalID"): _text(f, "name")
               for f in model.iter("BusinessEntityBuiltInFilter")}
    # An ImportAction is identified by (entity, action set, action) — see AppAction.
    imports = {_text(x, "internalID"): (_text(e, "name"), _text(st, "name"),
                                        _text(x, "name"))
               for e in model.iter("Entity") for st in e.iter("ActionSet")
               for x in st.iter("ImportAction")}
    searches = {_text(c, "internalID"): (_text(n, "name"), _text(c, "searchType"))
                for n in model.iter("BOViewEntity")
                for c in n.iter("BusinessEntitySearchTypeConfig")}

    actions = []
    for h in a.findall("abstractAppActions"):
        for x in h:
            view = _resolve(x, "businessObjectView", view_owner)
            imp = _resolve(x, "importAction", imports)
            actions.append({
                "kind": x.tag, "name": _text(x, "name"), "label": _text(x, "label"),
                "position": int(_text(x, "posInFolder") or 0),
                "parent_folder": _resolve(x, "parentFolder", action_names),
                "required_role": _text(x, "requiredRole"),
                "settings": _passthrough(x, _APP_ACTION_STRUCTURAL),
                "view_entity": view[0] if view else None,
                "view": view[1] if view else None,
                "applied_filter": _resolve(x, "appliedFilter", filters),
                "import_entity": imp[0] if imp else None,
                "import_action_set": imp[1] if imp else None,
                "import_action": imp[2] if imp else None,
            })

    nav = []
    for h in a.findall("navigationConfig"):
        for cfg in h.iter("NavigationConfig"):
            for gh in cfg.findall("navigationGroups"):
                for g in gh:
                    folder = _resolve(g, "underlyingFolder", action_names)
                    nav.append({
                        "kind": "folder" if g.tag == "FolderNavigationGroup" else "group",
                        "name": _text(g, "name"), "label": _text(g, "label"),
                        "position": int(_text(g, "position") or 0),
                        "label_visible": _bool(g, "labelVisible"),
                        "divider_visible": _bool(g, "dividerVisible"),
                        "folder": folder,
                        "items": [
                            {"action": _resolve(i, "appAction", action_names),
                             "position": int(_text(i, "position") or 0)}
                            for ih in g.findall("navigationItems")
                            for i in ih.iter("NavigationItem")],
                    })

    entries, dropdown, alpha = [], True, False
    for h in a.findall("globalSearchConfig"):
        for cfg in h.iter("GlobalSearchConfig"):
            dropdown = _bool(cfg, "displaySearchForDropdown", True)
            alpha = _bool(cfg, "sortBOViewsAlphabetically")
            for bh in cfg.findall("globalSearchBoViews"):
                for b in bh.iter("GlobalSearchBoView"):
                    view = _resolve(b, "businessObjectView", view_owner)
                    st = _resolve(b, "searchTypeConfig", searches)
                    entries.append({
                        "name": _text(b, "name"), "label": _text(b, "label"),
                        "view_entity": view[0] if view else None,
                        "view": view[1] if view else None,
                        "search_node": st[0] if st else None,
                        "search_type": st[1] if st else None,
                        "max_results": int(_text(b, "maxResults") or 5),
                        "position": int(_text(b, "position") or 0),
                        "view_type": _text(b, "viewType") or "GD",
                    })

    doc = None
    for h in a.findall("documentationConfig"):
        for cfg in h.iter("DocumentationConfig"):
            doc = _text(cfg, "documentation")
    return {"name": _text(a, "name"), "label": _text(a, "label"),
            "title": _text(a, "applicationTitle"), "description": _text(a, "description"),
            "required_role": _text(a, "requiredRoleName"),
            "default_action": _resolve(a, "defaultAction", action_names),
            "documentation": doc, "settings": _passthrough(a, _APP_STRUCTURAL),
            "actions": actions, "navigation": nav, "search_dropdown": dropdown,
            "search_sort_alphabetically": alpha, "search_entries": entries}


_VIEW_STRUCTURAL = {"name", "label", "description", "filter", "requiredRoleName",
                    "rootLabel", "rootPluralLabel", "rootDescription",
                    "rootBOViewEntity", "BOViewEntities"}
_NODE_STRUCTURAL = {"name", "sortExpression", "entity", "collection", "form",
                    "actionSet", "recordNodeDisplayCard", "displayCard", "formView",
                    "tableView", "dataEntryFormView", "transitions",
                    "businessEntitySearchConfigs", "businessEntityBuiltInFilters",
                    "referenceAttributeNavigationConfigs",
                    "referenceAttributeEditionConfigs", "embeddedCollectionNavigations"}
_TRANSITION_STRUCTURAL = {"name", "transitionPath", "posInParent", "targetBOViewEntity",
                          "formCollection"}


def _search_configs(el: ET.Element, holder: str, tag: str, forms: dict) -> list[dict]:
    return [{"search_type": _text(c, "searchType"), "enabled": _bool(c, "enabled"),
             "position": int(_text(c, "posInParent") or 0),
             "custom_form": _resolve(c, "customForm", forms)}
            for h in el.findall(holder) for c in h.iter(tag)]


def _business_view(v: ET.Element, ename: str, model: ET.Element) -> dict:
    # A view walks the model GRAPH, so its nodes belong to different entities and each
    # node's collection/form/actionSet must resolve against ITS OWN entity.
    entities = {_text(e, "internalID"): e for e in model.iter("Entity")}
    entity_names = {i: _text(e, "name") for i, e in entities.items()}
    node_names = {_text(n, "internalID"): _text(n, "name")
                  for h in v.findall("BOViewEntities") for n in h}

    nodes = []
    for h in v.findall("BOViewEntities"):
        for n in h.iter("BOViewEntity"):
            owner = n.find("entity")
            owner_el = entities.get(owner.attrib.get("ref")) if owner is not None else None
            R = _entity_refs(owner_el, model) if owner_el is not None else {}
            forms = R.get("form", {})
            nodes.append({
                "name": _text(n, "name"),
                "entity": entity_names.get(owner.attrib.get("ref")) if owner is not None else None,
                "collection": _resolve(n, "collection", R.get("collection", {})),
                "form": _resolve(n, "form", forms),
                "action_set": _resolve(n, "actionSet", R.get("actionSet", {})),
                "display_card": _resolve(n, "recordNodeDisplayCard", R.get("card", {})),
                "sort_expression": _text(n, "sortExpression"),
                "settings": _passthrough(n, _NODE_STRUCTURAL),
                "transitions": [
                    {"name": _text(t, "name"), "path": _text(t, "transitionPath") or "",
                     "target": _resolve(t, "targetBOViewEntity", node_names),
                     "position": int(_text(t, "posInParent") or 0),
                     "settings": _passthrough(t, _TRANSITION_STRUCTURAL)}
                    for th in n.findall("transitions") for t in th.iter("BOViewTransition")],
                "search_configs": _search_configs(
                    n, "businessEntitySearchConfigs",
                    "BusinessEntitySearchTypeConfig", forms),
                "filters": [
                    {"name": _text(f, "name"), "label": _text(f, "label"),
                     "description": _text(f, "description"),
                     "condition": _text(f, "semQLCondition") or "",
                     "visible": _bool(f, "visible", True)}
                    for fh in n.findall("businessEntityBuiltInFilters")
                    for f in fh.iter("BusinessEntityBuiltInFilter")],
            })
    return {"entity": ename, "name": _text(v, "name"), "label": _text(v, "label"),
            "root": _resolve(v, "rootBOViewEntity", node_names),
            "root_label": _text(v, "rootLabel"),
            "root_plural_label": _text(v, "rootPluralLabel"),
            "root_description": _text(v, "rootDescription"),
            "description": _text(v, "description"), "filter": _text(v, "filter"),
            "required_role": _text(v, "requiredRoleName"),
            "settings": _passthrough(v, _VIEW_STRUCTURAL), "nodes": nodes}


def _entity_refs(entity: ET.Element, model: ET.Element) -> dict:
    """Name lookups for everything an app-layer ref can point at, per entity."""
    return {
        "stepper": {_text(s, "internalID"): _text(s, "name")
                    for s in entity.iter("Stepper")},
        "card": {_text(c, "internalID"): _text(c, "name")
                 for c in entity.iter("DisplayCard")},
        "collection": {_text(c, "internalID"): _text(c, "name")
                       for c in entity.iter("CollectionView")},
        "form": {_text(f, "internalID"): _text(f, "name") for f in entity.iter("Form")},
        "dups": {_text(d, "internalID"): _text(d, "name")
                 for d in entity.iter("DupsManager")},
        "actionSet": {_text(a, "internalID"): _text(a, "name")
                      for a in entity.iter("ActionSet")},
        "publisher": {_text(p, "internalID"): _text(p, "name")
                      for p in model.iter("Publisher")},
        "job": {_text(j, "internalID"): _text(j, "name") for j in model.iter("ModelJob")},
        # A FormTab name is unique only WITHIN its form — gs-customerb2c has a tab
        # called `Person` in two different forms — so this resolves to the pair.
        "tab": {_text(t, "internalID"): (_text(f, "name"), _text(t, "name"))
                for f in entity.iter("Form") for t in f.iter("FormTab")},
    }


def _resolve(el: ET.Element, tag: str, table: dict):
    c = el.find(tag)
    return table.get(c.attrib.get("ref")) if c is not None else None


_DUPS_STRUCTURAL = {"name", "label", "description", "collectionView",
                    "tableViewCollection", "displayCard", "formTab", "modelJob",
                    "checkoutSearchConfigs"}


def _dups_manager(d: ET.Element, ename: str, entity: ET.Element,
                  model: ET.Element) -> dict:
    R = _entity_refs(entity, model)
    tab = _resolve(d, "formTab", R["tab"])
    return {
        "entity": ename, "name": _text(d, "name"), "label": _text(d, "label"),
        "description": _text(d, "description"),
        "collection": _resolve(d, "collectionView", R["collection"]),
        "table_collection": _resolve(d, "tableViewCollection", R["collection"]),
        "display_card": _resolve(d, "displayCard", R["card"]),
        "form": tab[0] if tab else None, "form_tab": tab[1] if tab else None,
        "model_job": _resolve(d, "modelJob", R["job"]),
        "settings": _passthrough(d, _DUPS_STRUCTURAL),
        "search_configs": _search_configs(
            d, "checkoutSearchConfigs", "DupsCheckoutSearchTypeConfig", R["form"]),
    }


def _passthrough(el: ET.Element, structural: set[str]) -> dict[str, str]:
    """Every flat scalar child that is not read explicitly, carried verbatim.

    An explicit `null="true"` is preserved as None, NOT dropped. It used to be dropped,
    with the justification that "extraction is symmetric, so the round-trip sees the
    same thing on both passes" — which is LESSONS §2 stated out loud: it compares the
    compiler against itself. The product writes those nulls, the round-trip could never
    notice they were gone, and comparing against a real export showed 30+ elements
    missing across Application, CollectionView and every app action.

    Omitted and explicitly-null are different things to this importer (§19).
    """
    # A REF slot is never a setting — but an UNSET ref carries no `ref` attribute, so
    # "ref" in c.attrib misses it and a null ref leaked into settings the moment nulls
    # started being preserved. The block library knows which slots are refs.
    from agent.compile.blocks import library
    refs = {t for t, enc in library().get(el.tag, {}).get("elements", {}).items()
            if enc == "ref"}
    out: dict[str, str | None] = {}
    for c in el:
        if (c.tag.startswith("internal") or len(c) or c.tag in structural
                or "ref" in c.attrib or c.tag in refs):
            continue
        if c.attrib.get("null") == "true":
            out[c.tag] = None
        elif "val" in c.attrib:
            out[c.tag] = c.attrib["val"]
        elif c.text:
            out[c.tag] = c.text
    return out


_ACTION_STRUCTURAL = {"name", "label", "posInParent", "requiredRole",
                      "stepper", "defaultPublisher", "displayCard", "formTab",
                      "workflow", "modelJob", "dupsManager", "parameters"}


def _action_set(a: ET.Element, ename: str, entity: ET.Element, model: ET.Element) -> dict:
    R = _entity_refs(entity, model)
    actions = []
    for holder in a.findall("actions"):
        for el in holder:
            tab = _resolve(el, "formTab", R["tab"])
            actions.append({
                "kind": el.tag, "name": _text(el, "name"), "label": _text(el, "label"),
                "position": int(_text(el, "posInParent") or 0),
                "required_role": _text(el, "requiredRole"),
                "settings": _passthrough(el, _ACTION_STRUCTURAL),
                "stepper": _resolve(el, "stepper", R["stepper"]),
                "publisher": _resolve(el, "defaultPublisher", R["publisher"]),
                "display_card": _resolve(el, "displayCard", R["card"]),
                "form": tab[0] if tab else None,
                "form_tab": tab[1] if tab else None,
                "dups_manager": _resolve(el, "dupsManager", R["dups"]),
                "model_job": _resolve(el, "modelJob", R["job"]),
            })
    return {"entity": ename, "name": _text(a, "name"), "label": _text(a, "label"),
            "default": _bool(a, "defaultActionSet"), "actions": actions}


STEP_KIND = {"FormStep": "form", "CollectionStep": "collection"}

# Structural children of a step: read explicitly or deliberately not carried. Anything
# else that is a flat scalar goes into `settings` verbatim.
_STEP_STRUCTURAL = {"name", "label", "posInParent", "parentCollectionStep",
                    "formTab", "collectionView",
                    "formStepEnrichers", "formStepValidations",
                    "stepTransitionValidations", "abstractStepTriggers",
                    "referenceFormFieldConfigs", "manyToManyPickerSearchTypeConfigs"}


def _stepper(st: ET.Element, ename: str, model: ET.Element) -> dict:
    enricher_names = {_text(e, "internalID"): _text(e, "name")
                      for e in model.iter("SemQLEnricher")}
    step_names = {_text(s, "internalID"): _text(s, "name")
                  for holder in st.findall("steps") for s in holder}
    # A step's own refs. Dropped until 2026-08-06, which made the round trip silently
    # narrower than the model: a re-emit produced steps with `formTab` and
    # `collectionView` null, and those are refs in 26/26 and 24/24 observed instances.
    # A round trip that loses a never-null ref is LESSONS §2 in miniature — it compared
    # the compiler against itself and both passes agreed on the same missing thing.
    # MODEL-WIDE lookups, because 3 of 26 form steps and 3 of 24 collection steps point
    # at an object on a CHILD entity (Product -> Items -> Images). `_entity_refs` is
    # scoped to one entity by design and cannot see them.
    tabs_any = {_text(t, "internalID"): (_text(e, "name"), _text(f, "name"),
                                         _text(t, "name"))
                for e in model.iter("Entity") for f in e.iter("Form")
                for t in f.iter("FormTab")}
    colls_any = {_text(c, "internalID"): (_text(e, "name"), _text(c, "name"))
                 for e in model.iter("Entity") for c in e.iter("CollectionView")}

    steps = []
    for holder in st.findall("steps"):
        for s in holder:
            if s.tag not in STEP_KIND:
                continue
            parent = s.find("parentCollectionStep")
            settings = _passthrough(s, _STEP_STRUCTURAL)
            tab = _resolve(s, "formTab", tabs_any)
            coll = _resolve(s, "collectionView", colls_any)
            owner = (tab or coll or (None,))[0]
            steps.append({
                "kind": STEP_KIND[s.tag], "name": _text(s, "name"),
                "label": _text(s, "label"),
                "position": int(_text(s, "posInParent") or 0),
                "parent_step": (step_names.get(parent.attrib.get("ref"))
                                if parent is not None else None),
                # Recorded only when it DIFFERS, so an ordinary step stays as terse in
                # the IR as it was before the refs were carried at all.
                "entity": owner if owner and owner != ename else None,
                "form": tab[1] if tab else None,
                "form_tab": tab[2] if tab else None,
                "collection": coll[1] if coll else None,
                "settings": settings,
                "enrichers": [
                    {"enricher": enricher_names.get(
                        (b.find("enricher").attrib.get("ref")
                         if b.find("enricher") is not None else "")) or "",
                     "on_form_open": _bool(b, "executedOnFormOpen"),
                     "on_data_change": _bool(b, "executedOnDataChange"),
                     "on_button_click": _bool(b, "executedOnButtonClick")}
                    for b in s.iter("FormStepEnricher")],
            })
    jobs = {_text(j, "internalID"): _text(j, "name") for j in model.iter("ModelJob")}
    return {"entity": ename, "name": _text(st, "name"), "label": _text(st, "label"),
            "model_job": _resolve(st, "modelJob", jobs), "steps": steps}


# Three container element types, not two. FormSection2 appears ONLY in
# gs-customerb2c — the third sample earning its place. The trailing 2 is xDM's own
# element name, so it is carried verbatim rather than normalised away.
CONTAINER_KIND = {"FormTab": "tab", "FormContainer": "section",
                  "FormSection2": "section2"}


def _form(f: ET.Element, ename: str) -> dict:
    # Containers are referenced by UUID from fields and from each other, so resolve
    # names first — the XML expresses the tree by reference, not by nesting.
    names = {_text(c, "internalID"): _text(c, "name")
             for holder in f.findall("formContainers") for c in holder}

    def parent_of(el):
        r = el.find("parentFormContainer")
        return names.get(r.attrib.get("ref")) if r is not None else None

    containers = [
        {"name": _text(c, "name"), "kind": CONTAINER_KIND.get(c.tag, "section"),
         "label": _text(c, "label"), "parent": parent_of(c)}
        for holder in f.findall("formContainers") for c in holder
        if c.tag in CONTAINER_KIND
    ]
    fields = [
        {"name": _text(fl, "name"), "value": _text(fl, "value") or "",
         "component": _text(fl, "componentName") or "semTextField",
         "container": parent_of(fl), "label": _text(fl, "label"),
         "data_type": _text(fl, "valueDataType") or "STRING",
         "position": int(_text(fl, "posInParent") or 0),
         "relative_width": _text(fl, "relativeWidth"),
         "properties": [{"name": _text(cp, "name") or "",
                         "value": _text(cp, "value") or ""}
                        for cp in fl.iter("ComponentProperty")]}
        for holder in f.findall("formFields") for fl in holder.iter("FormField")
    ]
    return {"entity": ename, "name": _text(f, "name"), "default": _bool(f, "default"),
            "containers": containers, "fields": fields}
