"""The element-shape library, and the conformance check that uses it.

`blocks.yaml` is harvested from real exports (see `harvest_blocks.py`). This module
turns it into the thing that pays: a check that answers, mechanically,

    does this XML have the shape the PRODUCT writes?

Every shape defect this project hit is one of three findings below, and each one cost a
deploy cycle or a live instance to discover:

    ENCODING   `<queueName val="Default"/>` where the product writes element text.
               Imports at 204, stored as null, queue shows as `Q0.null`. (LESSONS §20)
    MISSING    an element absent rather than explicitly null. The survivorship import
               refused; 30+ app-layer elements were silently dropped. (LESSONS §19)
    UNKNOWN    an element no export contains — an invention, like `NEVER`. (§16)

A fourth arrived on 2026-08-07 from the Application Builder's own Validation view,
which is a register no REST call reaches:

    DUPLICATE-POSITION  two objects sharing a position inside one ordered set. Every
               other finding here is a property of ONE object; this is a property of a
               SET, and that is exactly why three independent offline checks, an
               import, an export, a deploy and a successful job all missed it.

The library is a FLOOR. `unknown` findings are therefore reported at lower confidence
than the other two: an element these six models never use may still be legitimate.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

BLOCKS_YAML = Path(__file__).with_name("blocks.yaml")
EXCEPTIONS_YAML = Path(__file__).with_name("block_exceptions.yaml")
AUDIT_PREFIX = "internal"

#: How to make an unknown element known. The D8 loop, which is the only thing that has
#: ever actually worked here: build it once in the product, export, re-harvest.
HOW_TO_TEACH_IT = (
    "If this element is real, TEACH THE LIBRARY rather than relaxing the check:\n"
    "  1. build the construct once in the model designer (operator present, D12)\n"
    "  2. export it into harvest/\n"
    "  3. python -m agent.compile.harvest_blocks samples/*.xml live/*.xml "
    "harvest/*.xml > agent/compile/blocks.yaml\n"
    "If it is real but UNBUILDABLE here, record it in "
    "agent/compile/block_exceptions.yaml with a docs/ citation — a decision that "
    "overrides evidence goes on disk, not into a severity flag.")


@functools.lru_cache(maxsize=1)
def library() -> dict:
    return yaml.safe_load(BLOCKS_YAML.read_text())["blocks"]


@functools.lru_cache(maxsize=1)
def positions() -> dict:
    """Per object type: which element orders it, and the set it must be unique within.

    Harvested (`harvest_blocks.harvest_positions`) from the PRODUCT-AUTHORED exports
    only — see `harvest_blocks.COMPILER_DERIVED` for why a round-trip of our own model
    is evidence about spelling and not about position values.
    """
    return yaml.safe_load(BLOCKS_YAML.read_text()).get("positions", {})


@functools.lru_cache(maxsize=1)
def component_defaults() -> dict:
    """Per (componentName, property) modal value, harvested from real exports."""
    return yaml.safe_load(BLOCKS_YAML.read_text()).get("component_defaults", {})


@functools.lru_cache(maxsize=1)
def component_property_datatypes() -> dict:
    """`ComponentProperty.name` -> the dataType the product writes for it.

    Harvested from PRODUCT-AUTHORED exports only (46 names, 8536 instances, zero
    ambiguity). The dataType is a property of the NAME, not of the value — the emitter
    wrote STRING on every auto-filled default, which imported at 204, deployed and ran,
    and was 60 errors in the Application Builder's Validation view, the one register
    that reads the component registry (OBSERVED 2026-08-07, scenario 4).
    """
    return yaml.safe_load(BLOCKS_YAML.read_text()).get(
        "component_property_datatypes", {})


@functools.lru_cache(maxsize=1)
def exceptions() -> dict[tuple[str, str], dict]:
    """Elements accepted despite no export containing them, each with a citation.

    This is the escape hatch for "the docs describe it, no sample uses it". It is a
    RECORDED DECISION, not a severity toggle: name the element, say why, cite the page.
    """
    if not EXCEPTIONS_YAML.exists():
        return {}
    raw = yaml.safe_load(EXCEPTIONS_YAML.read_text()) or {}
    return {(e["object"], e["element"]): e for e in raw.get("accepted", [])}


@dataclass(frozen=True)
class Finding:
    kind: str            # encoding | missing | unknown | null-not-allowed |
                         # null-ref | empty-holder | duplicate-position | datatype
    obj: str
    element: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.obj}.{self.element}: {self.detail}"

    @property
    def remedy(self) -> str:
        """A refusal that does not name the way out is just an obstacle."""
        if self.kind == "unknown":
            return HOW_TO_TEACH_IT
        if self.kind == "encoding":
            want = library().get(self.obj, {}).get("elements", {}).get(self.element)
            return (f"Emit it with "
                    f"{'text()' if want == 'text' else 'scalar()' if want == 'val' else want}. "
                    f"Both spellings import at 204 and the wrong one is stored as "
                    f"null, so only the runtime would tell you.")
        if self.kind == "duplicate-position":
            return ("Give each object in the set its own position. The IR is allowed "
                    "to leave two things unordered — `depends` reads equal positions "
                    "as \"no constraint\" — but the PRODUCT is not: the emitter has to "
                    "resolve the tie into distinct integers that preserve the authored "
                    "order. Nothing here imports as null and nothing 500s; the model "
                    "loads, and the Application Builder's Validation view is the only "
                    "register that says so (LESSONS §56).")
        if self.kind == "null-ref":
            return ("Mint the target and wire the ref in the EMITTER. There is no "
                    "value to fill in here — a ref's value is a per-model UUID, which "
                    "is why complete() cannot do it and why the slot went unchecked "
                    "until it broke a deploy. If the target does not exist yet, the "
                    "emitter has to derive it (see emit_app._derive_root).")
        if self.kind == "datatype":
            spec = component_property_datatypes().get(self.element, {})
            return (f"Emit dataType {spec.get('dataType', '?')} for "
                    f"{self.element!r} — look it up in "
                    f"blocks.component_property_datatypes(), never author it. This "
                    f"imports at 204, deploys and runs; only the Application "
                    f"Builder's Validation view names it (LESSONS §56).")
        return ("Emit it explicitly null rather than omitting it. An absent element "
                "is not an explicitly-null one to this importer.")


def _encoding(child: ET.Element, expect_holder: bool) -> str:
    if expect_holder and (len(child) or not (child.attrib or child.text)):
        return "holder"
    if "ref" in child.attrib:
        return "ref"
    if "val" in child.attrib:
        return "val"
    if child.attrib.get("null") == "true":
        return "null"
    return "text"


def check_element(el: ET.Element, *, require_always: bool = True) -> list[Finding]:
    """Check one object against its block. Unknown object types are NOT reported —
    the library is a floor, and an unharvested type is a gap in evidence, not a bug."""
    block = library().get(el.tag)
    if block is None:
        return []
    spec = block["elements"]
    out: list[Finding] = []
    present = set()
    for c in el:
        if c.tag.startswith(AUDIT_PREFIX):
            continue
        present.add(c.tag)
        want = spec.get(c.tag)
        if want is None:
            if (el.tag, c.tag) in exceptions():
                continue
            out.append(Finding("unknown", el.tag, c.tag,
                               "no export contains this element on this object"))
            continue
        got = _encoding(c, want == "holder")
        # An EMPTY holder the product never leaves empty. The element-set checks all
        # pass — the element IS present — and the deployer then dereferences into it.
        # `Reference.foreignAttribute` empty imports at 204 and kills the deploy with a
        # bare "Unexpected Error" (OBSERVED 2026-08-05, scenario 4).
        #
        # This is `never_null` one nesting level down, and it exists because
        # `complete()` fills SLOTS and cannot create OBJECTS — so every holder it fills
        # is emitted empty unless an emitter populated it first. That gap was invisible
        # to all three offline checks until it was measured.
        if want == "holder" and not len(c) and c.tag in block.get("never_empty", ()):
            if (el.tag, c.tag) not in exceptions():
                out.append(Finding(
                    "empty-holder", el.tag, c.tag,
                    f"emitted with no children, but all {block['instances']} observed "
                    f"instances populate it. complete() can fill the slot but not mint "
                    f"the object — populate it in the emitter"))
            continue
        # A REF slot the product never leaves null. Invisible to every check until
        # 2026-08-06: `never_null` needs a modal value to record and a ref's value is a
        # per-model UUID, so the whole class of ref slots was excluded from the
        # harvest — and the s3 stepper emitted three of them null, passed every offline
        # check, imported at 204, exported cleanly, and killed the deploy.
        #
        # Reported separately from `null-not-allowed` because the REMEDY is different:
        # there is no value to fill in. Something has to be minted and wired, and only
        # an emitter can do that.
        if got == "null" and c.tag in block.get("never_null_refs", ()):
            if (el.tag, c.tag) not in exceptions():
                out.append(Finding(
                    "null-ref", el.tag, c.tag,
                    f"emitted null, but it is a real reference in all "
                    f"{block['instances']} observed instances of {el.tag} and never "
                    f"null. complete() cannot mint — wire it in the emitter"))
            continue
        if got == "null" and c.tag in block.get("never_null", {}):
            out.append(Finding(
                "null-not-allowed", el.tag, c.tag,
                f"emitted null, but no export leaves it null "
                f"(observed default {block['never_null'][c.tag]!r})"))
            continue
        # `null` is a legal spelling of any slot: it means "explicitly unset".
        if got != want and not (got == "null" or want == "null"):
            out.append(Finding("encoding", el.tag, c.tag,
                               f"emitted as {got}, product writes {want}"))
    if require_always:
        for tag in block.get("always", ()):
            if tag not in present:
                out.append(Finding("missing", el.tag, tag,
                                   f"present on all {block['instances']} observed "
                                   f"instances; absent is not the same as null"))
    return out


def duplicate_positions(root: ET.Element) -> list[Finding]:
    """Objects sharing a position inside the set the product requires it unique in.

    The Application Builder's Validation view, run by the operator on 2026-08-07,
    is where this class was named for the first time:

        Duplicate Position: Position "0" is already used in the set of objects.

    Six occurrences on a model that imports at 204, exports cleanly, deploys, runs a
    job and holds data. Every offline check we had was blind to it, because all three
    ask about objects one at a time and this is a property of a SET.

    An object type with no harvested scope is skipped — the library is a floor, and an
    unmeasured type is a gap in evidence rather than a licence to refuse.
    """
    spec = positions()
    if not spec:
        return []
    enc: dict[int, ET.Element] = {}

    def walk(el: ET.Element, cur: ET.Element) -> None:
        for c in el:
            if any(g.tag == "internalID" for g in c):
                enc[id(c)] = cur
                walk(c, c)
            else:
                walk(c, cur)

    walk(root, root)

    def value(el: ET.Element, tag: str) -> str | None:
        for c in el:
            if c.tag == tag:
                if c.attrib.get("null") == "true":
                    return None
                return c.attrib.get("val", c.text)
        return None

    sets: dict[tuple, list[tuple[str, str]]] = {}
    for el in root.iter():
        block = spec.get(el.tag)
        if block is None:
            continue
        v = value(el, block["element"])
        if v is None:
            continue
        scope = block["scope"]
        key = None
        if scope != "__enclosing__":
            for c in el:
                if c.tag == scope and "ref" in c.attrib:
                    key = ("ref", c.attrib["ref"])
        if key is None:
            parent = enc.get(id(el))
            key = ("enc", id(parent) if parent is not None else "ROOT")
        sets.setdefault((el.tag, block["element"], key), []).append(
            (v, value(el, "name") or "?"))

    out: list[Finding] = []
    for (tag, element, _), members in sets.items():
        by_value: dict[str, list[str]] = {}
        for v, name in members:
            by_value.setdefault(v, []).append(name)
        for v, names in sorted(by_value.items()):
            if len(names) < 2:
                continue
            block = spec[tag]
            out.append(Finding(
                "duplicate-position", tag, element,
                f"position {v!r} is used by {len(names)} objects in one set "
                f"({', '.join(sorted(names))}). The product orders {tag} by "
                f"{element} within {block['scope']} and never repeats a value: "
                f"{block['instances']} instances over {block['groups']} sets in the "
                f"corpus, zero duplicates"))
    return out


def component_datatypes(root: ET.Element) -> list[Finding]:
    """ComponentProperty elements whose dataType contradicts the harvested table.

    The fourth register (the Application Builder's Validation view) named this class
    on 2026-08-07: the emitter wrote `dataType STRING` on every auto-filled default,
    and the registry wants BOOLEAN for `isMultiline` and friends, DECIMAL for the
    multiline line counts. 60 errors on a model that imports at 204, deploys, runs a
    job and holds data — RUNNABLE is not VALID, again.

    The table is a lookup, not a judgement: every property name carries exactly one
    dataType across 8536 product-authored instances. A name the corpus has never seen
    is SKIPPED — the library is a floor, and an unharvested name is a gap in evidence.

    Note the wire spelling is DECIMAL where the registry's error message says NUMBER —
    emit what the product exports, not what the message names (§51.2).
    """
    table = component_property_datatypes()
    if not table:
        return []
    out: list[Finding] = []
    for cp in root.iter("ComponentProperty"):
        name = cp.findtext("name")
        spec = table.get(name or "")
        if spec is None:
            continue
        dt = cp.find("dataType")
        got = dt.attrib.get("val", dt.text) if dt is not None else None
        if got is not None and got != spec["dataType"]:
            out.append(Finding(
                "datatype", "ComponentProperty", name,
                f"emitted with dataType {got}, but all {spec['instances']} "
                f"product-authored instances of {name!r} carry "
                f"{spec['dataType']}. The dataType belongs to the property NAME — "
                f"look it up, never author it"))
    return out


def check(xml: str | bytes | ET.Element, *,
          require_always: bool = True) -> list[Finding]:
    """Every conformance finding in a whole document, deduplicated."""
    root = xml if isinstance(xml, ET.Element) else ET.fromstring(
        xml.encode() if isinstance(xml, str) else xml)
    seen: dict[tuple, Finding] = {}
    for el in root.iter():
        if not el.tag[:1].isupper():
            continue
        for f in check_element(el, require_always=require_always):
            seen[(f.kind, f.obj, f.element)] = f
    # Deduplicated on (kind, obj, element) like the rest, so a model that repeats the
    # same mistake in twenty entities reports it once with the first set named.
    for f in duplicate_positions(root):
        seen.setdefault((f.kind, f.obj, f.element), f)
    for f in component_datatypes(root):
        seen.setdefault((f.kind, f.obj, f.element), f)
    return sorted(seen.values(), key=lambda f: (f.kind, f.obj, f.element))


def render(findings: list[Finding]) -> str:
    if not findings:
        return "CONFORMS: every element matches the shape the product writes."
    lines = [f"{len(findings)} conformance finding(s):"]
    for f in findings:
        lines.append(f"  {f}")
    # The remedy differs per KIND, not per finding, so say each one once.
    for kind in ("unknown", "encoding", "null-ref", "duplicate-position", "missing"):
        if any(f.kind == kind for f in findings):
            lines.append("")
            lines.append(f"  -> {kind}:")
            first = next(f for f in findings if f.kind == kind)
            lines += [f"     {ln}" for ln in first.remedy.splitlines()]
    return "\n".join(lines)


def stale_sources() -> list[Finding]:
    """Findings raised by the PRODUCT's own exports. Any is proof the library is stale.

    This is the ratchet: `unknown` keeps its sharp meaning of "invented" only if every
    shape the product has ever written is already in the table. When a new export lands
    the fix is mechanical — re-harvest — and no judgement is involved.
    """
    root = Path(__file__).resolve().parents[2]
    out: list[Finding] = []
    for d in ("samples", "live", "harvest"):
        for f in sorted((root / d).glob("*.xml")):
            try:
                out += [x for x in check(f.read_bytes()) if x.kind == "unknown"]
            except ET.ParseError:
                continue
    return out


# ------------------------------------------------------------------ the assembler
def complete(root: ET.Element) -> int:
    """Fill in every element the product ALWAYS writes and this document omits.

    The null-preservation fix in `extract_app` only helps a ROUND TRIP: the nulls come
    back through `settings` because a real export put them there. An AUTHORED model has
    no such entries — nobody writes `description: null` in a yaml file — so the elements
    are simply absent, and absent is not explicitly-null to this importer (LESSONS §19).

    That is the gap this closes, and it is why the library exists rather than a
    checklist: the emitters describe INTENT, and the shape the product expects is
    filled in from measurement afterwards. An emitter cannot forget a field it never
    had to know about.

    Returns the number of elements added. Never overwrites anything already present.
    """
    lib = library()
    added = 0

    for el in root.iter():
        block = lib.get(el.tag)
        if block is None:
            continue
        # A slot the product NEVER leaves null must not be emitted null. The deployer
        # dereferences some of them — CollectionView.listItemLines NPEs on
        # Integer.intValue() — so an explicit null imports at 204 and kills the deploy.
        nn = block.get("never_null", {})
        for c in el:
            if c.tag in nn and c.attrib.get("null") == "true":
                del c.attrib["null"]
                if lib[el.tag]["elements"].get(c.tag) == "val":
                    c.set("val", nn[c.tag])
                else:
                    c.text = nn[c.tag]
                added += 1
        present = {c.tag for c in el}
        order = list(block["elements"])
        for tag in block.get("always", ()):
            if tag in present:
                continue
            enc = block["elements"][tag]
            if enc == "holder":
                new = ET.Element(tag)
            elif tag in block.get("never_null", {}):
                v = block["never_null"][tag]
                new = ET.Element(tag, val=v) if enc == "val" else ET.Element(tag)
                if enc != "val":
                    new.text = v
            elif enc == "val" and tag in block.get("defaults", {}):
                # A single observed value across the whole corpus is not a guess.
                new = ET.Element(tag, val=block["defaults"][tag])
            else:
                new = ET.Element(tag, null="true")
            # Position it where the product puts it, so a byte diff stays readable.
            after = [c.tag for c in el]
            idx = len(el)
            for i, existing in enumerate(after):
                if existing in order and order.index(existing) > order.index(tag):
                    idx = i
                    break
            el.insert(idx, new)
            added += 1
    return added
