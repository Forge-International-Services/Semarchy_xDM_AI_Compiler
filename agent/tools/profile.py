"""Blocking-key coverage — what a file of records says about the model's binning keys.
Sprint 12, deliverable 2.

The advisor can say *this matcher has no binning key* and *this key is not normalized*
(CA-013). It cannot say **how many records fall out of matching entirely**, because it
has never seen a record. This reads a CSV and says so, per binning key and overall.

    python3 -m agent.tools.profile <ir-dir> <csv> [<csv>...]

WHAT A BINNING KEY IS. `docs/Design/matching/match-rules.md` § Binning: "Records for
which all binning expressions produce identical results are placed in the same bin."
So the unit here is the RULE, and its key is the tuple of all its binning expressions.
A record that has no value for one of them shares that key with nothing it could be
compared against — and the equality the rule then tests is UNKNOWN for a NULL rather
than true, so the rule cannot fire for it either way. A record carrying no rule's key
at all is UN-BLOCKABLE: it is never a candidate for anything.

WHAT THIS IS NOT. It does not reimplement a matcher and it does not evaluate SemQL. It
uses the offline SemQL tools to name the ATTRIBUTES an expression reads
(`semql.attributes_in`) and then asks the file one question per attribute: is there a
value here? The only normalization applied to a cell is stripping surrounding
whitespace — empty after that is absent. `UPPER`, `SUBSTR`, `REGEXP_REPLACE` and every
other function in the expression are NOT applied.

WHICH IS WHY "NOT MEASURABLE" IS A VERDICT AND NOT A SKIP. Most binning keys in a real
model read an enricher's output — `NormalizedName`, `ErpKeyNorm`, `Address.Zip5` — and
an enricher runs on the master record AFTER it lands. A load file does not carry those
columns and never will. This tool says so by name, lists the columns that are missing,
and traces each one back to the enricher that writes it and the columns that enricher
reads. It does not run the enricher, and the upstream number it prints is labelled as
what it is: the presence of the enricher's INPUTS, not the coverage of the key.
Absence of evidence is not evidence (LESSONS §1, §21).

THRESHOLD CALIBRATION IS ABSENT, DELIBERATELY. Sweeping the auto-merge band needs
labelled pairs the engagement must supply. `calibrate_thresholds()` returns a
`NotSupplied` marker naming what is missing; it never synthesizes a label. The seam is
a function so a future engagement can plug real labels into it.

--------------------------------------------------------------------------- the input
INPUT IS A CSV FILE PATH, never a live query (sprint 12 says so). Columns are the WIRE
names — the same names the loader posts, per CLAUDE.md §3: `SourceID` for the master
key on a matched entity, dotted members for complex attributes (`Address.Zip5`).

FILE -> ENTITY is by filename, following the convention `out/s4-multi-source-ids/data/`
already uses for its record groups (`customers:`, `opportunities:`): the stem names the
entity, case-insensitively, with a trailing plural tolerated (`customers.csv` ->
`Customer`, `opportunities.csv` -> `Opportunity`). A stem that matches no entity is
REFUSED, not guessed at; pass `Customer=path/to/anything.csv` to say it explicitly.

NOTE for `out/s4-multi-source-ids/`: that directory holds `records.yaml` and `load.py`,
not CSVs — the loader reads YAML and posts JSON. Profiling s4 means deriving the CSVs
from `records.yaml` first (one row per record, columns = the union of its `values`
keys). `tests/test_profile.py` does exactly that, so the fixture stays the real dataset
rather than a copy of it.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.tools import semql

#: How many record ids a rendered line names before it stops and gives the count.
NAME_CAP = 12


# --------------------------------------------------------------------------- results
@dataclass(frozen=True)
class Derivation:
    """An attribute the file lacks, traced to the enricher that writes it.

    Provenance, NOT a measurement of the key it feeds. `inputs_carried` counts records
    with a value in every input column the file DOES carry — which answers "is the raw
    material here?" and not "would the enricher produce a key?". A function can map a
    non-empty input to an empty output (`SUBSTR(REGEXP_REPLACE(Zip,'[^0-9]',''),1,5)`
    on a value with no digits), and this does not run it.
    """
    attribute: str
    enricher: str                                # "Customer/NormalizeCarriedKeys"
    scope: str
    expression: str
    reads: tuple[str, ...] = ()
    reads_in_file: tuple[str, ...] = ()
    reads_missing: tuple[str, ...] = ()
    inputs_carried: int | None = None            # None when no input is in the file
    total: int = 0


@dataclass(frozen=True)
class KeyCoverage:
    """One match rule's binning key, measured against one file."""
    entity: str
    rule: str
    expressions: tuple[str, ...]
    attributes: tuple[str, ...] = ()
    missing_columns: tuple[str, ...] = ()
    unparseable: tuple[str, ...] = ()
    measurable: bool = False
    total: int = 0
    carried: int = 0
    absent_ids: tuple[str, ...] = ()
    derivations: tuple[Derivation, ...] = ()

    @property
    def absent(self) -> int:
        return self.total - self.carried

    @property
    def share(self) -> float | None:
        if not self.measurable or not self.total:
            return None
        return self.carried / self.total

    @property
    def reason(self) -> str:
        """Why this key is not measurable from this file. Empty when it is."""
        if self.measurable:
            return ""
        if self.unparseable:
            return ("binning expression does not parse, so the attributes it reads "
                    "cannot be named: " + ", ".join(self.unparseable))
        if not self.attributes:
            return ("the binning expression reads no attribute, so every record "
                    "produces the same bin — nothing here is a coverage question")
        return "the file does not carry " + ", ".join(self.missing_columns)


@dataclass(frozen=True)
class EntityProfile:
    entity: str
    source: str                                  # the csv path, as given
    total: int = 0
    id_column: str = ""
    columns: tuple[str, ...] = ()
    keys: tuple[KeyCoverage, ...] = ()
    #: Rules that declare no binning at all. They compare globally, so no record falls
    #: out of matching through them — which makes the un-blockable share zero by
    #: construction, and the cost quadratic. Both facts are worth saying out loud.
    global_rules: tuple[str, ...] = ()
    unblockable_ids: tuple[str, ...] = ()
    unblockable: int = 0
    #: True when every declared key was measurable, so `unblockable` is a MEASUREMENT.
    #: False when it was computed over a subset, so it is an UPPER BOUND — adding the
    #: unmeasured keys can only move records out of the un-blockable set, never into it.
    unblockable_exact: bool = False
    measurable_keys: int = 0
    declared_keys: int = 0
    note: str = ""                               # set when there is nothing to measure


@dataclass(frozen=True)
class Report:
    model: str
    profiles: tuple[EntityProfile, ...] = ()
    #: Entities whose matcher declares binning keys and for which no file was supplied.
    unprofiled: tuple[str, ...] = ()
    files: tuple[str, ...] = ()


# ------------------------------------------------------------ the calibration seam
@dataclass(frozen=True)
class NotSupplied:
    """The engagement has not supplied something, and nothing is invented in its place.

    Falsy on purpose, so `if not calibrate_thresholds(...)` reads correctly.
    """
    what: str
    needed: str

    def __bool__(self) -> bool:
        return False

    def render(self) -> str:
        return (f"NOT SUPPLIED: {self.what}\n"
                f"  needed: {self.needed}\n"
                f"  Nothing is inferred in its place. A synthetic label set would "
                f"measure the generator, not the model.")


def calibrate_thresholds(ir, labelled_pairs=None):
    """Sweep the auto-merge band against labelled pairs — or say they are absent.

    The sprint asks for a precision floor held while maximising recall, which needs two
    inputs this tool has neither of: pairs a human has labelled duplicate / not, AND a
    SCORE per pair, which only the matcher produces. So this returns `NotSupplied`
    rather than a number.

    The seam is here so a future engagement plugs real labels in at one place. Passing
    labels today raises, loudly, rather than quietly scoring pairs itself — scoring
    pairs is reimplementing the matcher, which is out of scope by name (sprint 12
    § Honest scope).
    """
    if not labelled_pairs:
        return NotSupplied(
            what="labelled duplicate / not-duplicate pairs",
            needed="a set of record-id pairs with a human verdict, plus the match "
                   "score each pair received from a matcher run. Then a sweep over "
                   "the band can report precision and recall per threshold.")
    raise NotImplementedError(
        "labelled pairs were supplied, and scoring them is out of scope: this tool "
        "profiles attribute completeness against declared binning keys and does not "
        "run a matcher (sprint 12 § Honest scope). Supply the pairs WITH their match "
        "scores and extend this function to sweep them.")


# ------------------------------------------------------------------------ the mapping
def _fold(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def _singulars(stem: str) -> list[str]:
    """The stem, plus the singular a plural filename implies. No other guessing."""
    out = [stem]
    if stem.endswith("ies") and len(stem) > 3:
        out.append(stem[:-3] + "y")
    if stem.endswith("es") and len(stem) > 2:
        out.append(stem[:-2])
    if stem.endswith("s") and len(stem) > 1:
        out.append(stem[:-1])
    return out


def resolve_entity(spec: str, ir) -> tuple[str, Path]:
    """`Customer=file.csv` or `customers.csv` -> (entity name, path). Refuses a guess."""
    entities = [e.name for e in ir.model_ir.entities]
    if "=" in spec:
        name, _, raw = spec.partition("=")
        name, path = name.strip(), Path(raw.strip())
        if name not in entities:
            raise ValueError(
                f"{name!r} is not an entity of {ir.model_ir.model.name}. "
                f"Entities: {', '.join(entities) or '(none)'}")
        return name, path
    path = Path(spec)
    folded = {_fold(e): e for e in entities}
    for cand in _singulars(_fold(path.stem)):
        if cand in folded:
            return folded[cand], path
    raise ValueError(
        f"cannot tell which entity {path.name!r} holds. The stem must name an entity, "
        f"a trailing plural aside — entities are {', '.join(entities) or '(none)'}. "
        f"Say it explicitly instead: <Entity>={path}")


# ------------------------------------------------------------------------ measurement
def _present(value) -> bool:
    """The ONLY normalization this tool applies: strip, then non-empty."""
    return value is not None and str(value).strip() != ""


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = [c for c in (reader.fieldnames or []) if c is not None]
        return cols, [dict(row) for row in reader]


def _id_column(columns, ir, entity: str) -> str:
    """`SourceID` on a matched entity, the PK otherwise, and the row number as a last
    resort — never a silently invented identifier."""
    if "SourceID" in columns:
        return "SourceID"
    ent = next((e for e in ir.model_ir.entities if e.name == entity), None)
    if ent is not None:
        for a in ent.attributes:
            if a.pk and a.name in columns:
                return a.name
    return ""


def _row_id(row: dict, id_column: str, n: int) -> str:
    if id_column and _present(row.get(id_column)):
        return str(row[id_column]).strip()
    return f"row {n}"


def _derivations(attribute: str, entity: str, ir, columns, rows) -> list[Derivation]:
    """Every enricher on `entity` that writes `attribute`, and what it reads."""
    out: list[Derivation] = []
    for e in ir.certify.enrichers:
        if e.entity != entity:
            continue
        for x in e.expressions:
            if x.attribute != attribute:
                continue
            try:
                reads = tuple(semql.attributes_in(x.expression))
            except ValueError:
                reads = ()
            in_file = tuple(r for r in reads if r in columns)
            missing = tuple(r for r in reads if r not in columns)
            carried = None
            if in_file:
                carried = sum(1 for row in rows
                              if all(_present(row.get(c)) for c in in_file))
            out.append(Derivation(
                attribute=attribute, enricher=f"{e.entity}/{e.name}",
                scope=e.scope or "NONE", expression=x.expression,
                reads=reads, reads_in_file=in_file, reads_missing=missing,
                inputs_carried=carried, total=len(rows)))
    return out


def profile_entity(ir, entity: str, path: Path) -> EntityProfile:
    """One entity, one file. Every binning key its matcher declares, measured or named."""
    columns, rows = read_csv(path)
    id_column = _id_column(columns, ir, entity)
    matcher = next((m for m in ir.certify.matchers if m.entity == entity), None)
    base = dict(entity=entity, source=str(path), total=len(rows),
                id_column=id_column or "(row number)", columns=tuple(columns))

    if matcher is None:
        return EntityProfile(**base, note=(
            "no matcher — this entity is never matched, so it has no binning key and "
            "no record can be un-blockable."))
    if not matcher.rules:
        return EntityProfile(**base, note=(
            "matcher declares no rules, so there is no binning key to measure."))

    ids = [_row_id(r, id_column, i + 1) for i, r in enumerate(rows)]
    keys: list[KeyCoverage] = []
    global_rules: list[str] = []

    for rule in matcher.rules:
        if not rule.binning:
            global_rules.append(rule.name)
            continue
        attrs: list[str] = []
        bad: list[str] = []
        for expr in rule.binning:
            if semql.check(expr, "expression"):
                bad.append(expr)
                continue
            try:
                for a in semql.attributes_in(expr):
                    if a not in attrs:
                        attrs.append(a)
            except ValueError:
                bad.append(expr)
        missing = tuple(a for a in attrs if a not in columns)
        measurable = not bad and not missing and bool(attrs)
        carried, absent_ids = 0, ()
        derivations: tuple[Derivation, ...] = ()
        if measurable:
            absent = []
            for rid, row in zip(ids, rows):
                if all(_present(row.get(a)) for a in attrs):
                    carried += 1
                else:
                    absent.append(rid)
            absent_ids = tuple(absent)
        else:
            derivations = tuple(d for a in missing
                                for d in _derivations(a, entity, ir, columns, rows))
        keys.append(KeyCoverage(
            entity=entity, rule=rule.name, expressions=tuple(rule.binning),
            attributes=tuple(attrs), missing_columns=missing, unparseable=tuple(bad),
            measurable=measurable, total=len(rows), carried=carried,
            absent_ids=absent_ids, derivations=derivations))

    measurable_keys = [k for k in keys if k.measurable]
    # A rule with no binning compares every record with every other, so nothing falls
    # out of matching through it. That is not a coverage finding, it is a cost one.
    if global_rules:
        return EntityProfile(**base, keys=tuple(keys),
                             global_rules=tuple(global_rules),
                             unblockable=0, unblockable_exact=True,
                             measurable_keys=len(measurable_keys),
                             declared_keys=len(keys), note=(
            f"{len(global_rules)} rule(s) declare no binning key and so compare every "
            f"record with every other. No record is un-blockable while that is true — "
            f"the exposure is comparison cost, not missed matches."))

    if not measurable_keys:
        return EntityProfile(**base, keys=tuple(keys),
                             measurable_keys=0, declared_keys=len(keys), note=(
            "no binning key is measurable from this file, so the un-blockable share "
            "cannot be bounded from it."))

    unblockable = tuple(
        rid for i, rid in enumerate(ids)
        if not any(all(_present(rows[i].get(a)) for a in k.attributes)
                   for k in measurable_keys))
    return EntityProfile(**base, keys=tuple(keys),
                         unblockable_ids=unblockable, unblockable=len(unblockable),
                         unblockable_exact=len(measurable_keys) == len(keys),
                         measurable_keys=len(measurable_keys), declared_keys=len(keys))


def profile(ir, files: dict[str, Path]) -> Report:
    """`{entity: csv path}` -> the report. Entities with keys and no file are named."""
    profiles = tuple(profile_entity(ir, e, p) for e, p in files.items())
    with_keys = {m.entity for m in ir.certify.matchers
                 if any(r.binning for r in m.rules)}
    return Report(model=ir.model_ir.model.name, profiles=profiles,
                  unprofiled=tuple(sorted(with_keys - set(files))),
                  files=tuple(str(p) for p in files.values()))


# ---------------------------------------------------------------------------- render
def _pct(n: int, d: int) -> str:
    return "n/a" if not d else f"{100.0 * n / d:.1f}%"


def _names(ids, cap: int = NAME_CAP) -> str:
    if not ids:
        return "none"
    if len(ids) <= cap:
        return ", ".join(ids)
    return f"{', '.join(ids[:cap])} … and {len(ids) - cap} more ({len(ids)} total)"


def render(report: Report, cap: int = NAME_CAP) -> str:
    lines = [f"BLOCKING-KEY COVERAGE — {report.model}, "
             f"{len(report.profiles)} file(s)",
             "  measured: a record CARRIES a key when every attribute the key's "
             "expressions read has a value.",
             "  the only normalization applied is strip-then-non-empty. No SemQL is "
             "evaluated."]

    for p in report.profiles:
        lines += ["", f"{p.entity}  <- {p.source}",
                  f"  {p.total} record(s), identified by {p.id_column}"]
        if p.declared_keys:
            lines.append(f"  binning keys: {p.measurable_keys} of {p.declared_keys} "
                         f"measurable from this file")
        if p.unblockable_exact and p.declared_keys and not p.global_rules:
            lines.append(f"  UN-BLOCKABLE: {p.unblockable}/{p.total} "
                         f"({_pct(p.unblockable, p.total).strip()}) — carry no binning "
                         f"key at all")
            if p.unblockable:
                lines.append(f"      {_names(p.unblockable_ids, cap)}")
        elif p.measurable_keys and not p.global_rules:
            lines.append(f"  UN-BLOCKABLE: at most {p.unblockable}/{p.total} "
                         f"({_pct(p.unblockable, p.total).strip()}) — an UPPER BOUND, "
                         f"over the {p.measurable_keys} measurable key(s) only. The "
                         f"unmeasured keys can only move records out of this set.")
            if p.unblockable:
                lines.append(f"      {_names(p.unblockable_ids, cap)}")
        elif p.declared_keys:
            lines.append("  UN-BLOCKABLE: NOT MEASURABLE from this file")
        if p.note:
            lines.append(f"  note: {p.note}")
        if p.global_rules:
            lines.append(f"  no binning key: {', '.join(p.global_rules)}")

        for k in p.keys:
            lines.append("")
            if k.measurable:
                lines.append(f"  {k.rule}: {k.carried}/{k.total} carry the key "
                             f"({_pct(k.carried, k.total).strip()}), "
                             f"{k.absent} do not")
                lines.append(f"      binning:  {' + '.join(k.expressions)}")
                if k.absent:
                    lines.append(f"      absent:   {_names(k.absent_ids, cap)}")
            else:
                lines.append(f"  {k.rule}: NOT MEASURABLE — {k.reason}")
                lines.append(f"      binning:  {' + '.join(k.expressions)}")
                if k.attributes:
                    lines.append(f"      reads:    {', '.join(k.attributes)}")
                for d in k.derivations:
                    lines.append(f"      upstream: {d.attribute} is written by "
                                 f"enricher {d.enricher} ({d.scope})")
                    lines.append(f"                {d.expression}")
                    if d.reads_in_file:
                        lines.append(
                            f"                reads {', '.join(d.reads_in_file)} — "
                            f"{d.inputs_carried}/{d.total} record(s) carry "
                            f"{'them all' if len(d.reads_in_file) > 1 else 'it'} "
                            f"({_pct(d.inputs_carried or 0, d.total).strip()})")
                    if d.reads_missing:
                        lines.append(f"                reads {', '.join(d.reads_missing)}"
                                     f", also absent from this file")
                    lines.append("                NOT this key's coverage — the "
                                 "enricher is not evaluated here.")
                if not k.derivations and k.missing_columns:
                    lines.append("      upstream: nothing in the IR writes "
                                 f"{', '.join(k.missing_columns)}. Either the file is "
                                 f"missing a column the publisher should send, or the "
                                 f"key names an attribute that is never populated.")

    if report.unprofiled:
        lines += ["", "NOT PROFILED — these entities declare binning keys and no file "
                      "was supplied:", f"  {', '.join(report.unprofiled)}"]

    lines += ["", "THRESHOLD CALIBRATION"]
    lines += ["  " + ln for ln in calibrate_thresholds(None).render().splitlines()]
    return "\n".join(lines)


# ------------------------------------------------------------------------------- CLI
def _load_ir(ir_dir: Path):
    from agent.ir.schema import IR
    cert, app = ir_dir / "certify.yaml", ir_dir / "app.yaml"
    return IR.load(ir_dir / "model.yaml", cert if cert.exists() else None,
                   app if app.exists() else None)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print("usage: python3 -m agent.tools.profile <ir-dir> <csv> [<csv>...]")
        print("       a csv may be given as <Entity>=<path> when the filename does "
              "not name the entity")
        return 2
    ir = _load_ir(Path(argv[0]))
    files: dict[str, Path] = {}
    try:
        for spec in argv[1:]:
            entity, path = resolve_entity(spec, ir)
            if entity in files:
                raise ValueError(
                    f"two files both claim {entity}: {files[entity]} and {path}. "
                    f"One file per entity — merge them, or profile them one at a time.")
            files[entity] = path
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(render(profile(ir, files)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
