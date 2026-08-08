"""Harvest the ELEMENT-SHAPE library from real exports. Step 3 of the block design.

Every defect this compiler hit on the way to a running model was one of two kinds:

    SHAPE     an element missing, misplaced, or encoded the wrong way   (14 of 20)
    SEMANTIC  a value that is structurally fine and means the wrong thing (6 of 20)

Shape defects are decidable from the corpus and should never have been authored by
hand. Measured across the samples plus a hand-built harvest:

    117 object types, 1205 (object, element) pairs, ZERO ambiguous encodings.

That zero is the licence for this file. The encoding of an element is fully determined
by the pair (object type, element name), so it can be looked up rather than remembered
— and `queueName` emitted as `val=` (LESSONS §20) becomes a mechanical error rather
than a live-instance discovery.

A block records, per object type:
    elements   name -> encoding, in the order the product writes them
    always     elements present on EVERY instance (a missing one is a defect)
    defaults   the value when exactly one is ever observed

This is a FLOOR, not a ceiling — the same caveat `harvest_vocab.py` carries. xDM ships
shapes these six models never use, so the assembler REFUSES an unknown element rather
than inventing an encoding for it.

    python -m agent.compile.harvest_blocks samples/*.xml harvest/*.xml > agent/compile/blocks.yaml
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

#: Audit fields the envelope owns; never part of a block's shape.
AUDIT_PREFIX = "internal"

#: Every element the product uses to order a collection. One per object, always.
POSITION_ELEMENTS = ("posInParent", "posInEntity", "posInJob", "posInKey",
                     "posInName", "posInFolder", "posInForm", "position")

#: The sentinel scope: "the nearest enclosing OBJECT", i.e. XML nesting.
ENCLOSING = "__enclosing__"

#: Exports whose MODEL CORE this compiler generated. Excluded from the POSITION
#: harvest and from nothing else, and the distinction is the point:
#:
#:   a round-trip through the product attests the SPELLING and preserves the VALUES.
#:
#: When xDM re-exports an imported model it rewrites the serialization — element order,
#: encodings, audit stamps, `internalID`s — so those files remain real evidence about
#: the GRAMMAR. It does not rewrite `posInEntity`; it hands back exactly the integer we
#: sent. So harvesting a positional INVARIANT from them would launder this compiler's
#: own duplicates into "the shape the product writes", and the check would certify the
#: defect it exists to find. LESSONS §2 and §48, one layer down.
#:
#: `harvest/PartyHubProbe.*` are s3 imported and then extended BY HAND in the designer.
#: The hand-built app layer is product evidence; the model core underneath it is ours.
COMPILER_DERIVED = frozenset({
    "PartyHubProbe.before.xml",
    "PartyHubProbe.form.xml",
    "PartyHubProbe.applayer.xml",
    "PartyHubProbe.handbuilt.xml",
    "PartyHubProbe.xml",
    "AccountHub.xml",
})


def _is_object(el: ET.Element) -> bool:
    """An OBJECT carries audit fields; a holder does not.

    Tag case is not the test. `PKAttributes` is a holder whose name starts with a
    capital, and treating it as an object put every entity's primary key in its own
    sibling set — which made a real invariant look like a violated one.
    """
    return any(c.tag == "internalID" for c in el)


def _enclosing(root: ET.Element) -> dict[int, ET.Element]:
    """id(object element) -> the nearest enclosing object element."""
    out: dict[int, ET.Element] = {}

    def walk(el: ET.Element, cur: ET.Element) -> None:
        for c in el:
            if _is_object(c):
                out[id(c)] = cur
                walk(c, c)
            else:
                walk(c, cur)

    walk(root, root)
    return out


def _pos_value(el: ET.Element, tag: str) -> str | None:
    for c in el:
        if c.tag == tag:
            if c.attrib.get("null") == "true":
                return None
            return c.attrib.get("val", c.text)
    return None


def position_rows(name: str, root: ET.Element) -> list[dict]:
    """Every position-bearing object in one document, with the keys it could be
    grouped by: XML nesting, and each ref slot it carries."""
    enc = _enclosing(root)
    rows = []
    for el in root.iter():
        found = [t for t in POSITION_ELEMENTS if _pos_value(el, t) is not None]
        if not found:
            continue
        parent = enc.get(id(el))
        slots = {c.tag: (name, c.attrib["ref"]) for c in el if "ref" in c.attrib}
        # An explicitly-null parent slot is still a DECLARED slot: `FormTab` carries
        # `parentFormContainer null="true"` because it IS the root of its form. It
        # falls back to the enclosing object rather than disqualifying the candidate.
        slots.update({c.tag: None for c in el
                      if c.attrib.get("null") == "true" and c.tag not in slots})
        rows.append({
            "tag": el.tag,
            "element": found[0],
            "value": _pos_value(el, found[0]),
            "enclosing": (name, id(parent) if parent is not None else "ROOT"),
            "slots": slots,
        })
    return rows


def _group_key(row: dict, scope: str):
    if scope == ENCLOSING:
        return row["enclosing"]
    return row["slots"].get(scope) or row["enclosing"]


def harvest_positions(named_roots: list[tuple[str, ET.Element]]) -> dict:
    """Which set of objects a position has to be unique within.

    The xDM designer's own validation says it out loud, and it is the only register
    that ever did:

        Duplicate Position: Position "0" is already used in the set of objects.

    "The set of objects" is the question. It is usually XML nesting, but the product
    flattens some collections into a pool and names the real parent with a ref —
    every `FormField` of a form sits in one `formFields` holder and belongs to the
    `FormContainer` its `parentFormContainer` points at.

    So the scope is MEASURED per object type rather than assumed: prefer XML nesting,
    and fall back to a ref slot only when nesting is not duplicate-free in the corpus.
    Measured over the product-authored exports this yields a scope for every one of
    the 54 position-bearing types, with ZERO duplicates across 1919 objects, and only
    five types needing a ref — all of them spelled `parent…`.

    A type whose evidence is one object per group is recorded anyway and is simply
    vacuous. Recording `instances` and `groups` is what makes that visible instead of
    letting a check with no evidence behind it look like a check.
    """
    rows: list[dict] = []
    for name, root in named_roots:
        rows += position_rows(name, root)
    by_tag: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_tag[r["tag"]].append(r)

    def groups_if_clean(rs: list[dict], scope: str) -> int | None:
        g: dict = collections.defaultdict(list)
        for r in rs:
            g[_group_key(r, scope)].append(r["value"])
        if any(len(v) != len(set(v)) for v in g.values()):
            return None
        return len(g)

    out: dict[str, dict] = {}
    for tag, rs in sorted(by_tag.items()):
        chosen, n = None, groups_if_clean(rs, ENCLOSING)
        if n is not None:
            chosen = (ENCLOSING, n)
        else:
            common = collections.Counter()
            for r in rs:
                for k in r["slots"]:
                    common[k] += 1
            best = None
            for cand in (k for k, c in common.items() if c == len(rs)):
                g = groups_if_clean(rs, cand)
                if g is None:
                    continue
                if best is None or len(rs) / g > len(rs) / best[1]:
                    best = (cand, g)
            chosen = best
        if chosen is None:
            # The corpus itself duplicates under every candidate. Record nothing:
            # there is no invariant to enforce, and inventing one is how a check
            # starts refusing what the product writes.
            continue
        out[tag] = {"element": rs[0]["element"], "scope": chosen[0],
                    "instances": len(rs), "groups": chosen[1]}
    return out


class ConflictingEvidence(Exception):
    """Two product-authored exports disagree. There is nothing to harvest, and picking
    a winner would be an invention wearing a measurement's clothes."""


def harvest_component_property_datatypes(named_roots: list[tuple[str, ET.Element]]) -> dict:
    """`ComponentProperty.name` -> the `dataType` the PRODUCT writes for it.

    A ComponentProperty carries its value as text plus a `dataType` naming how to read
    it. The emitter wrote STRING on every auto-filled default, which imports at 204,
    exports cleanly, deploys, runs a job — and is 66 errors in the Application Builder's
    Validation view, the one register that reads the component registry:

        The datatype for component property isMultiline is STRING and should be one of
        [BOOLEAN] according to the registry.

    So the dataType is not a property of the VALUE, it is a property of the NAME, and
    the corpus settles it: 8536 instances over 46 distinct names across the
    product-authored exports, ZERO ambiguity — every name has exactly one dataType.
    That zero is what makes this a lookup rather than a rule to remember.

    **Product-authored only** (`COMPILER_DERIVED`), and here that exclusion is not a
    subtlety — it is the whole check. `live/AccountHub.xml` and `live/PartyHubProbe.xml`
    are xDM's re-export of THIS COMPILER's output, and they hand our STRING straight
    back on all 21 of the properties the registry rejects. Harvesting them would record
    `isMultiline: AMBIGUOUS` at best and bless the defect at worst — LESSONS §2 and §48
    in the same shape the position harvest already meets.

    Note the wire spelling: the validation message says NUMBER, which is the REGISTRY's
    vocabulary. Every export writes DECIMAL. Emit what the product exports (§51.2).
    """
    seen: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    where: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for name, root in named_roots:
        for cp in root.iter("ComponentProperty"):
            prop = cp.findtext("name")
            dt = cp.find("dataType")
            if not prop or dt is None:
                continue
            value = dt.attrib.get("val", dt.text)
            if value is None:
                continue
            seen[prop][value] += 1
            where[(prop, value)].add(name)
    conflicts = {p: c for p, c in seen.items() if len(c) > 1}
    if conflicts:
        raise ConflictingEvidence(
            "the same ComponentProperty name carries different dataTypes in the "
            "product-authored corpus, so there is no table to harvest:\n"
            + "\n".join(
                f"  {p}: " + ", ".join(
                    f"{v} x{n} ({', '.join(sorted(where[(p, v)]))})"
                    for v, n in sorted(c.items()))
                for p, c in sorted(conflicts.items())))
    return {p: {"dataType": next(iter(c)), "instances": sum(c.values())}
            for p, c in sorted(seen.items())}


def _encoding(child: ET.Element, is_holder: bool) -> str:
    if is_holder:
        return "holder"
    if "ref" in child.attrib:
        return "ref"
    if "val" in child.attrib:
        return "val"
    if child.attrib.get("null") == "true":
        return "null"
    return "text"


def harvest(paths: list[Path]) -> dict:
    holders: set[tuple[str, str]] = set()
    roots = []
    for p in paths:
        try:
            roots.append((p.name, ET.parse(p).getroot()))
        except ET.ParseError:
            continue
    # A holder is a holder if it EVER has children — an empty one looks like text.
    for _, root in roots:
        for el in root.iter():
            if not el.tag[:1].isupper():
                continue
            for c in el:
                if not c.tag.startswith(AUDIT_PREFIX) and len(c):
                    holders.add((el.tag, c.tag))

    enc: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter))
    order: dict[str, dict[str, int]] = collections.defaultdict(dict)
    values: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter))
    seen: collections.Counter = collections.Counter()
    present: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    #: (object, holder) -> Counter{True: populated, False: empty}
    holder_fill: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter))

    for _, root in roots:
        for el in root.iter():
            if not el.tag[:1].isupper():
                continue
            seen[el.tag] += 1
            for i, c in enumerate(el):
                if c.tag.startswith(AUDIT_PREFIX):
                    continue
                e = _encoding(c, (el.tag, c.tag) in holders)
                if e == "holder":
                    holder_fill[el.tag][c.tag][bool(len(c))] += 1
                enc[el.tag][c.tag][e] += 1
                present[el.tag][c.tag] += 1
                order[el.tag].setdefault(c.tag, i)
                if e in ("val", "text"):
                    v = c.attrib.get("val", c.text)
                    if v is not None:
                        values[el.tag][c.tag][v] += 1

    # ---- ComponentProperty defaults, per (componentName, property).
    # EVERY FormField and TableColumn in every real export carries a populated
    # componentProperties holder — 557 of 557, no exceptions. An authored model declares
    # only the properties it wants to change, so the rest must be filled from
    # measurement or the field renders unconfigured. `blocks.check` cannot see this:
    # it validates element SETS, and the holder is present-but-empty.
    # Only properties present on EVERY instance of that component are defaults. The
    # union across instances would over-emit — the same mistake as emitting `condition`
    # on every action when ImportAction does not carry one.
    props: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter))
    seen_comp: collections.Counter = collections.Counter()
    for _, root in roots:
        for host in ("FormField", "TableColumn"):
            for el in root.iter(host):
                comp = el.findtext("componentName")
                if not comp:
                    continue
                seen_comp[(host, comp)] += 1
                for cp in el.iter("ComponentProperty"):
                    n, v = cp.findtext("name"), cp.findtext("value")
                    if n:
                        props[(host, comp)][n][v if v is not None else ""] += 1
    # KEYED BY (host, component), and that is the whole fix. The same componentName
    # carries a completely different property set depending on what hosts it: the
    # product writes 20 properties on a FormField/semTextField and 3 on a
    # TableColumn/semTextField. Keyed by component alone, "present on every instance"
    # is the INTERSECTION across both hosts — which is 2, and which is why an authored
    # form field rendered with almost nothing configured.
    #
    # The denominator was the bug, not the rule. "Universal" still means present on
    # every observed instance; it now counts instances of the same HOST.
    component_defaults = {}
    for (host, comp), names in props.items():
        universal = {n: c for n, c in names.items()
                     if sum(c.values()) == seen_comp[(host, comp)]}
        if universal:
            component_defaults.setdefault(host, {})[comp] = {
                n: c.most_common(1)[0][0] for n, c in universal.items()}

    blocks = {}
    for obj in sorted(enc):
        kinds = enc[obj]
        # `null` is an ENCODING of the same slot, not a different shape.
        def settle(c: collections.Counter) -> str:
            real = [k for k in c if k != "null"]
            return real[0] if len(real) == 1 else ("null" if not real else "AMBIGUOUS")
        elements = {tag: settle(c) for tag, c in kinds.items()}
        ordered = sorted(elements, key=lambda t: order[obj][t])
        block = {
            "instances": seen[obj],
            "elements": {t: elements[t] for t in ordered},
            "always": [t for t in ordered if present[obj][t] == seen[obj]],
        }
        defaults = {t: next(iter(values[obj][t])) for t in ordered
                    if len(values[obj][t]) == 1 and elements[t] == "val"}
        if defaults:
            block["defaults"] = defaults
        # A slot the product NEVER leaves null must not be emitted null. The deployer
        # dereferences some of them directly — `CollectionView.listItemLines` NPEs on
        # Integer.intValue() — so an explicit null passes the shape check, imports at
        # 204, and kills the deploy. §19's converse: absent is not null, AND null is not
        # a value. The modal observed value is the safe fill.
        never_null = {t: values[obj][t].most_common(1)[0][0]
                      for t in ordered
                      if kinds[t].get("null", 0) == 0 and values[obj].get(t)
                      and elements[t] in ("val", "text")}
        if never_null:
            block["never_null"] = never_null
        # THE SAME RULE FOR REF SLOTS, and it was missing because of the fill rather
        # than because of the rule. `never_null` above needs a modal VALUE to record,
        # and a ref's value is a per-model UUID — there is no safe fill, so refs were
        # excluded by `elements[t] in ("val", "text")` and the whole class went
        # unchecked. But "no safe fill" is an argument about complete(), not about
        # whether emitting it null is wrong.
        #
        # That gap is precisely where the s3 stepper went: rootCollectionStep, formTab
        # and parentCollectionStep are refs in 20/20, 26/26 and 26/26 observed instances
        # and were emitted null. The document passed every offline check, imported at
        # 204, exported cleanly, and the deploy died with a bare "Unexpected Error".
        #
        # Recorded as a LIST, not a mapping: there is nothing to fill in, only something
        # to refuse. `complete()` cannot mint, so this is a debt the EMITTER owes —
        # exactly like `never_empty` one level down.
        never_null_refs = sorted(t for t in ordered
                                 if elements[t] == "ref"
                                 and kinds[t].get("null", 0) == 0)
        if never_null_refs:
            block["never_null_refs"] = never_null_refs
        # A HOLDER the product never leaves empty. The complement of `never_null`, one
        # nesting level down, and the same failure with a different spelling: an empty
        # holder passes every element-set check because the ELEMENT is present, and the
        # deployer then dereferences into it. `Reference.foreignAttribute` empty is a
        # 204 import and an "Unexpected Error" deploy (OBSERVED 2026-08-05).
        #
        # `complete()` can create the slot but never the object inside it — it has no
        # minting context — so filling these is the EMITTER's job, and this records
        # which ones the emitter owes.
        never_empty = sorted(t for t in ordered
                             if elements[t] == "holder"
                             and holder_fill[obj].get(t, {}).get(False, 0) == 0
                             and holder_fill[obj].get(t, {}).get(True, 0) > 0)
        if never_empty:
            block["never_empty"] = never_empty
        blocks[obj] = block
    pos_roots = [(n, r) for n, r in roots if n not in COMPILER_DERIVED]
    return {"sources": [n for n, _ in roots], "blocks": blocks,
            "component_defaults": component_defaults,
            "position_sources": [n for n, _ in pos_roots],
            "positions": harvest_positions(pos_roots),
            "component_property_datatypes":
                harvest_component_property_datatypes(pos_roots)}


def main(argv: list[str]) -> None:
    out = harvest([Path(a) for a in argv])
    print("# GENERATED by agent/compile/harvest_blocks.py — do not hand-edit.")
    print("# A FLOOR, not a ceiling: xDM ships shapes these models never use.")
    print(yaml.safe_dump(out, sort_keys=False, width=100))


if __name__ == "__main__":
    main(sys.argv[1:])
