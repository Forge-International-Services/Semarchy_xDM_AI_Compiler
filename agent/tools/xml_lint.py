"""The authoring guide's §7 checklist, executable. Sprint 06.

Runs on compiler output and on any export the user supplies. Exit codes:
0 clean, 1 warnings, 2 errors. Sprint 09 gates the import on < 2.

There is no XSD (D11), so this and the normalized round-trip are the only
verification that exists.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree as ET

from agent.compile.registry import PLATFORM_TYPES, UNIDENTIFIED

SEMQL_TAGS = {"condition", "expression", "idExpression",
              "consolidationOrderByExpression"}
_UDF = re.compile(r"\b([A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*)\s*\(")


@dataclass(frozen=True)
class Finding:
    check: str
    severity: Literal["error", "warning"]
    detail: str


def lint(xml: str, *, repository_version: str | None = None,
         declared_udfs: set[str] | None = None) -> list[Finding]:
    out: list[Finding] = []

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return [Finding("well-formed", "error", str(exc))]

    info = root.find("exportInfo")
    if info is None:
        out.append(Finding("envelope", "error", "no exportInfo element"))
    elif repository_version and info.attrib.get("repositoryVersion") != repository_version:
        out.append(Finding("version", "error",
                           f"repositoryVersion {info.attrib.get('repositoryVersion')!r} "
                           f"!= target {repository_version!r}; import is refused across versions"))

    ids = [e.attrib.get("val") for e in root.iter("internalID")]
    # RootModel, Model and exportInfo/modelUUID legitimately SHARE one uuid — verified
    # against a live export. Counting it as a duplicate makes every valid document fail.
    rm = root.find("RootModel/internalID")
    if rm is not None and rm.attrib.get("val") in ids:
        ids.remove(rm.attrib["val"])
    dupes = {i for i in ids if ids.count(i) > 1}
    for d in sorted(dupes):
        out.append(Finding("unique-ids", "error", f"internalID {d} appears more than once"))

    allowed = set(ids) | set(PLATFORM_TYPES) | set(UNIDENTIFIED)
    for el in root.iter():
        target = el.attrib.get("ref")
        if target and target not in allowed:
            out.append(Finding("dangling-ref", "error", f"<{el.tag} ref={target}> resolves to nothing"))
        if (el.attrib.get("null") == "true" or "ref" in el.attrib) and (el.text or "").strip():
            out.append(Finding("empty-body", "error",
                               f"<{el.tag}> carries both a body and null/ref"))

    for lov in root.iter("LOVValue"):
        if lov.find("value") is not None:
            out.append(Finding("lov-shape", "error",
                               "LOVValue has a <value> element; it pairs <code> with <label>"))
        if lov.find("code") is None or lov.find("label") is None:
            out.append(Finding("lov-shape", "error", "LOVValue is missing <code> or <label>"))

    if declared_udfs is not None:
        for el in root.iter():
            if el.tag in SEMQL_TAGS and el.text:
                for udf in _UDF.findall(el.text):
                    if udf.upper() not in {d.upper() for d in declared_udfs}:
                        out.append(Finding("external-udf", "warning",
                                           f"{udf} is not declared; a rename breaks the "
                                           f"model at runtime with no compile-time warning"))
    return out


def exit_code(findings: list[Finding]) -> int:
    if any(f.severity == "error" for f in findings):
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    findings = lint(open(sys.argv[1]).read())
    for f in findings:
        print(f"[{f.check}] {f.severity.upper()}: {f.detail}")
    print(f"{len(findings)} finding(s)")
    sys.exit(exit_code(findings))
