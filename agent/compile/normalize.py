"""Canonical form for semantically diffing two metaDataExport files.

Sprint 00. Exports churn on audit stamps and serialization order (authoring guide
§6.3), and a recompile never reuses the original UUIDs, so a byte diff is useless.
This reduces two files to a form where equality means "the same model".

Ordering matters, and an earlier draft of the spec got it wrong (RED-TEAM R6): it
sorted children by `internalID` and *then* numbered UUIDs by encounter order. That
is circular — traversal order depended on the UUIDs it was trying to erase, so two
structurally identical models normalised differently and diffed as unequal, which
is exactly the comparison this exists to make.

The order here is therefore:

    1. strip audit fields
    2. sort children by a SEMANTIC key, with every UUID masked so it cannot
       influence the sort
    3. only then assign UUID ordinals, in traversal order of the sorted tree
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

AUDIT = frozenset({
    "internalCreationDate", "internalCreationUser",
    "internalUpdateDate", "internalUpdateUser",
    "internalRevisionID",
})

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
MASK = "\x00U\x00"          # placeholder used only while sorting
# Identity-bearing values must be masked in the sort key. That means raw UUIDs AND
# the u0/u1 ordinals a previous pass produced — otherwise normalize(normalize(x))
# sorts differently from normalize(x) and the function is not idempotent.
_ORDINAL = re.compile(r"\Au\d+\Z")

# SemQL lives in these; their text is compared byte-exact, never whitespace-collapsed.
VERBATIM = frozenset({"condition", "expression"})


def _strip_audit(el: ET.Element) -> None:
    for child in [c for c in el if c.tag in AUDIT]:
        el.remove(child)
    for child in el:
        _strip_audit(child)


def _mask(tag: str, key: str, value: str) -> str:
    """Blank out anything that carries identity rather than meaning."""
    if key == "ref" or (tag == "internalID" and key == "val"):
        return MASK
    return MASK if _ORDINAL.match(value) else _UUID.sub(MASK, value)


def _sort(el: ET.Element) -> str:
    """Sort children by semantic key, bottom-up, and return this node's sort key.

    The key is (tag, <name> text, masked subtree). Masking means a UUID can never
    influence the order — the ordering must not depend on the values it exists to
    erase (RED-TEAM R6).

    Each subtree's canonical string is built ONCE, from its children's already-
    computed strings. Recomputing it inside the sort comparator instead makes this
    quadratic, which on a 1.4 MB export does not finish.
    """
    keys = [_sort(c) for c in el]
    pairs = sorted(zip(el, keys),
                   key=lambda p: (p[0].tag, p[0].findtext("name") or "", p[1]))
    el[:] = [c for c, _ in pairs]

    attrs = "".join(f" {k}={_mask(el.tag, k, v)}" for k, v in sorted(el.attrib.items()))
    text = _UUID.sub(MASK, el.text or "")
    return f"<{el.tag}{attrs}>{text}{''.join(k for _, k in pairs)}</{el.tag}>"


def _renumber(el: ET.Element, seen: dict[str, str]) -> None:
    """Assign u0, u1, ... in traversal order of the already-sorted tree."""
    def sub(v: str) -> str:
        return _UUID.sub(lambda m: seen.setdefault(m.group(0), f"u{len(seen)}"), v)

    for k, v in el.attrib.items():
        el.attrib[k] = sub(v)
    if el.text:
        el.text = sub(el.text)
    for child in el:
        _renumber(child, seen)


def _collapse(el: ET.Element) -> None:
    """Collapse insignificant whitespace, but leave SemQL bodies byte-exact."""
    if el.tag not in VERBATIM and el.text:
        el.text = " ".join(el.text.split())
    el.tail = None
    for child in el:
        _collapse(child)


def _sort_attrs(el: ET.Element) -> None:
    ordered = dict(sorted(el.attrib.items()))
    el.attrib.clear()
    el.attrib.update(ordered)
    for child in el:
        _sort_attrs(child)


def normalize(xml: str | bytes) -> str:
    """Canonical form. Equal output means the models are the same.

    Emits VALID XML, so the result can be re-parsed, diffed with ordinary tools,
    and fed back through this function unchanged.
    """
    root = ET.fromstring(xml)
    _strip_audit(root)
    _collapse(root)
    _sort(root)
    _renumber(root, {})
    _sort_attrs(root)
    return ET.tostring(root, encoding="unicode")
