"""xDM's validation report, CSV -> structured issues -> IR nodes. Sprint 08.

MAPPING BACK TO THE IR IS THE VALUABLE HALF. xDM reports issues against ITS OWN object
paths ("Customer / Matcher / P_PHONETIC_ZIP"). The refine loop needs the YAML line that
caused it, or it degrades into the agent guessing which part of the spec an xDM message
refers to.

THE CSV SCHEMA IS NOT DOCUMENTED, BUT IT IS NOW MEASURED. The first real export landed
2026-08-08 (`out/s4-multi-source-ids/06-validation-report-first-run.csv`, straight from
the builder's Export button on the 67-error first app-layer run):

    Severity, Type, Object, Description

and it REFUTED one guess in the alias table: `Type` is not a severity synonym, it is
the OBJECT KIND ("Form Field", "SemQL Enricher", "Business Entity"...). The parser
refused the file rather than misreading it — the header discipline paying for itself —
and the fix was one alias line plus the `object_type` field. The parser stays
HEADER-DRIVEN: it reads the header row, maps columns by name through a table of
accepted spellings, and REFUSES a header it does not recognise rather than falling
back on column positions.

Positional parsing of an unseen format is how you get a report that parses cleanly and
means something else. Each real export either confirms the aliases or adds to them —
one line each, in ALIASES below.

`Object` carries a SHORT NAME ("BillingKey", "CustomerNode"), not a path — which is
why `Type` matters: the same short name legally names an attribute AND the form field
displaying it. Resolution uses the (type, name) pair first and falls back to the path
logic, and ambiguity still resolves to None rather than a nearest guess.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SEVERITY = {"error": "error", "errors": "error",
            "warning": "warning", "warnings": "warning",
            "information": "information", "info": "information",
            "informations": "information"}

# header cell (lowercased, punctuation stripped) -> our field. Extend from real
# exports; never guess a column by position.
#
# "type" -> "severity" was a GUESS and the first real export refuted it: the builder
# writes `Severity, Type, Object, Description`, where Type is the object KIND. The
# guess made two columns map to severity, the second overwrote the first, and the
# severity vocabulary check refused the file — which is the designed failure mode.
ALIASES = {
    "severity": "severity", "level": "severity",
    "type": "object_type", "objecttype": "object_type", "kind": "object_type",
    "object": "object_path", "objectpath": "object_path", "path": "object_path",
    "element": "object_path", "location": "object_path", "objectname": "object_path",
    "message": "message", "description": "message", "issue": "message",
    "detail": "message", "details": "message",
    "rule": "rule", "constraint": "rule", "validationrule": "rule",
}
REQUIRED = {"severity", "object_path", "message"}


class ReportFormatError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning", "information"]
    object_path: str            # xDM's own path or short name, e.g. "BillingKey"
    message: str
    rule: str = ""
    object_type: str = ""       # xDM's object kind, e.g. "Form Field" (measured 2026-08-08)
    ir_node: str | None = None  # resolved IR path, or None — NEVER a nearest guess

    @property
    def blocks_deploy(self) -> bool:
        """Errors block deploy AND take running applications offline — the failure the
        operator has already hit (D10). docs/Design/logical-model/validate-a-model.md
        § Invalid model."""
        return self.severity == "error"


def _norm(cell: str) -> str:
    return re.sub(r"[^a-z]", "", cell.lower())


def parse(path: str | Path) -> list[ValidationIssue]:
    """Parse an exported CSV file. Use `parse_text` for content already in hand.

    utf-8-sig, because the export is opened in Excel often enough that a BOM is the
    normal case rather than the exception.
    """
    return parse_text(Path(path).read_text(encoding="utf-8-sig"))


def parse_text(text: str) -> list[ValidationIssue]:
    text = text.lstrip("﻿")
    if not text.strip():
        return []
    # xDM is a European-facing product and Excel writes ';' on those locales, so the
    # delimiter is sniffed rather than assumed.
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return []

    header = rows[0]
    mapping = {i: ALIASES[_norm(c)] for i, c in enumerate(header) if _norm(c) in ALIASES}
    found = set(mapping.values())
    if not REQUIRED <= found:
        raise ReportFormatError(
            f"validation report header {header!r} does not name "
            f"{sorted(REQUIRED - found)}. The CSV schema is undocumented, so this "
            f"refuses rather than guessing columns by position — add the real spelling "
            f"to ALIASES in agent/tools/validation_report.py.")

    issues = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        vals = {f: row[i].strip() for i, f in mapping.items() if i < len(row)}
        sev = SEVERITY.get(_norm(vals.get("severity", "")))
        if sev is None:
            raise ReportFormatError(
                f"unknown severity {vals.get('severity')!r}; known: "
                f"{sorted(set(SEVERITY.values()))}")
        issues.append(ValidationIssue(
            severity=sev, object_path=vals.get("object_path", ""),
            message=vals.get("message", ""), rule=vals.get("rule", ""),
            object_type=vals.get("object_type", "")))
    return issues


def counts(issues: list[ValidationIssue]) -> dict[str, int]:
    """Severity tallies, to compare against what the UI shows."""
    out = {"error": 0, "warning": 0, "information": 0}
    for i in issues:
        out[i.severity] += 1
    return out


# ------------------------------------------------------- mapping back to the IR
# xDM writes object paths with a separator that varies by version and view. Split on
# any of them rather than pinning one.
_SPLIT = re.compile(r"\s*(?:/|>|::|›|\|)\s*")


@dataclass
class IRIndex:
    """name-tuple -> IR path, built from the IR the agent authored.

    Keyed by the LAST TWO name segments as well as the full path, because xDM's paths
    carry object-type words ("Matcher", "Match Rule") that the IR expresses as
    structure rather than as names.

    `kinds` exists because the real export's `Object` column is a SHORT NAME and the
    same short name legally names two objects: `BillingKey` is an attribute in
    model.yaml AND the form field displaying it in app.yaml, and the report's 6
    dataType errors on it belonged to the FIELD. The (Type, Object) pair is what the
    export actually says, so it is what resolution uses first. Kind keys are the
    export's own Type spellings, normalized — extend them only from real exports.
    """
    exact: dict[tuple[str, ...], str] = field(default_factory=dict)
    tails: dict[tuple[str, ...], list[str]] = field(default_factory=dict)
    kinds: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def add(self, names: tuple[str, ...], path: str, kind: str | None = None) -> None:
        self.exact.setdefault(names, path)
        for n in (1, 2):
            if len(names) >= n:
                self.tails.setdefault(tuple(names[-n:]), []).append(path)
        if kind:
            self.kinds.setdefault((kind, names[-1]), []).append(path)

    def resolve(self, object_path: str, object_type: str = "") -> str | None:
        """The IR path, or None. Ambiguity resolves to None — a wrong mapping sends the
        operator to the wrong YAML line, which is worse than saying 'unmapped'."""
        segs = tuple(s for s in _SPLIT.split(object_path.strip()) if s)
        if not segs:
            return None
        if object_type:
            hits = self.kinds.get((_norm(object_type), segs[-1]))
            if hits and len(set(hits)) == 1:
                return hits[0]
        if segs in self.exact:
            return self.exact[segs]
        for n in (2, 1):
            if len(segs) >= n:
                hits = self.tails.get(tuple(segs[-n:]))
                if hits and len(set(hits)) == 1:
                    return hits[0]
        return None


def build_index(ir) -> IRIndex:
    """Index every named object in the IR against the YAML path that declares it."""
    idx = IRIndex()
    m = ir.model_ir
    idx.add((m.model.name,), "model.yaml:model")
    for i, p in enumerate(m.publishers):
        idx.add((p.name,), f"model.yaml:publishers[{i}]")
    for i, lov in enumerate(m.lov_types):
        idx.add((lov.name,), f"model.yaml:lov_types[{i}]")
    for i, t in enumerate(m.complex_types):
        idx.add((t.name,), f"model.yaml:complex_types[{i}]", kind="complextype")
    for i, r in enumerate(m.references):
        idx.add((r.name,), f"model.yaml:references[{i}]")
    for i, r in enumerate(m.roles):
        idx.add((r.name,), f"model.yaml:roles[{i}]")
    for i, e in enumerate(m.entities):
        base = f"model.yaml:entities[{i}]"
        idx.add((e.name,), base, kind="entity")
        for j, a in enumerate(e.attributes):
            idx.add((e.name, a.name), f"{base}.attributes[{j}]")
        for j, a in enumerate(e.complex_attributes):
            idx.add((e.name, a.name), f"{base}.complex_attributes[{j}]")

    c = ir.certify
    for i, e in enumerate(c.enrichers):
        idx.add((e.entity, e.name), f"certify.yaml:enrichers[{i}]",
                kind="semqlenricher" if e.kind == "semql" else None)
    for i, v in enumerate(c.validations):
        # Serialized as CheckConstraint; the report's Type spelling is "SemQL Validation".
        idx.add((v.entity, v.name), f"certify.yaml:validations[{i}]",
                kind="semqlvalidation")
    for i, s in enumerate(c.survivorship):
        idx.add((s.entity, s.name), f"certify.yaml:survivorship[{i}]")
    for i, x in enumerate(c.matchers):
        idx.add((x.entity, "Matcher"), f"certify.yaml:matchers[{i}]")
        for j, r in enumerate(x.rules):
            idx.add((x.entity, r.name), f"certify.yaml:matchers[{i}].rules[{j}]")
    for i, j_ in enumerate(c.jobs):
        idx.add((j_.name,), f"certify.yaml:jobs[{i}]")

    a = ir.app
    for i, x in enumerate(a.applications):
        idx.add((x.name,), f"app.yaml:applications[{i}]")
        for j, act in enumerate(x.actions):
            idx.add((x.name, act.name), f"app.yaml:applications[{i}].actions[{j}]")
    for i, f_ in enumerate(a.forms):
        idx.add((f_.entity, f_.name), f"app.yaml:forms[{i}]")
        for j, fl in enumerate(f_.fields):
            # The report's 60 dataType errors named FIELDS by short name ("BillingKey")
            # with Type "Form Field" — the same short name as the attribute, which is
            # exactly the ambiguity the kind index exists to break.
            idx.add((f_.entity, f_.name, fl.name), f"app.yaml:forms[{i}].fields[{j}]",
                    kind="formfield")
    for i, s in enumerate(a.steppers):
        idx.add((s.entity, s.name), f"app.yaml:steppers[{i}]")
    for i, col in enumerate(a.collections):
        idx.add((col.entity, col.name), f"app.yaml:collections[{i}]")
    for i, d in enumerate(a.dups_managers):
        idx.add((d.entity, d.name), f"app.yaml:dups_managers[{i}]")
    for i, st in enumerate(a.action_sets):
        idx.add((st.entity, st.name), f"app.yaml:action_sets[{i}]")
        for j, act in enumerate(st.actions):
            idx.add((st.entity, act.name), f"app.yaml:action_sets[{i}].actions[{j}]")
    for i, v in enumerate(a.business_views):
        idx.add((v.entity, v.name), f"app.yaml:business_views[{i}]")
        for j, n in enumerate(v.nodes):
            # Type "Business Entity", Object = the NODE name ("CustomerNode").
            idx.add((v.entity, v.name, n.name),
                    f"app.yaml:business_views[{i}].nodes[{j}]", kind="businessentity")
    return idx


def resolve(issues: list[ValidationIssue], ir) -> list[ValidationIssue]:
    """Attach IR paths. Unmapped issues keep ir_node=None and are reported as such."""
    idx = build_index(ir)
    return [ValidationIssue(i.severity, i.object_path, i.message, i.rule,
                            i.object_type,
                            idx.resolve(i.object_path, i.object_type))
            for i in issues]


def coverage(issues: list[ValidationIssue]) -> float:
    """Share of issues that resolved. The sprint-08 bar is >= 0.90."""
    return 1.0 if not issues else sum(
        1 for i in issues if i.ir_node) / len(issues)


def render(issues: list[ValidationIssue]) -> str:
    if not issues:
        return "validation clean: 0 issues"
    c = counts(issues)
    lines = [f"{c['error']} errors, {c['warning']} warnings, "
             f"{c['information']} information"]
    for i in issues:
        where = i.ir_node or "UNMAPPED — resolve by hand, not by guess"
        lines.append(f"  [{i.severity}] {i.object_path}\n      {i.message}\n"
                     f"      -> {where}")
    return "\n".join(lines)
