"""Turn an uploaded schema into a CANDIDATE inventory for the intake questionnaire.

Sprint 02. Accepts SQL DDL, DESCRIBE / INFORMATION_SCHEMA output, and Markdown
tables, and emits candidates — never decisions.

What it deliberately does not infer, because a schema cannot express it:
  - entity type (basic / id-matched / fuzzy) — follows from PUBLISHER TOPOLOGY,
    which is asked at G1
  - publishers, searchable/golden flags, match rules
Emitting a guess for any of those would hand the user a plausible answer to a
question they should have been asked.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

import sqlglot
from sqlglot import exp

# The 12 built-in types, from docs/Design/logical-model/built-in-datatypes.md.
# Read from the corpus rather than recalled — the doc is authoritative for the
# running version. Note it documents Oracle/PostgreSQL/SQL Server mappings and
# says nothing about Snowflake, which is what this deployment runs on (D13).
XDM_TYPES = frozenset({
    "ByteInteger", "ShortInteger", "Integer", "LongInteger", "Decimal",
    "String", "LongText", "Date", "Timestamp", "Binary", "UUID", "Boolean",
})

T = exp.DataType.Type

# Mapped off sqlglot's normalised type enum, so one table covers every dialect.
_SIMPLE: dict[T, str] = {
    T.BOOLEAN: "Boolean",
    T.DATE: "Date",
    T.DATE32: "Date",
    T.UUID: "UUID",
    T.BINARY: "Binary", T.VARBINARY: "Binary", T.BLOB: "Binary",
    T.TEXT: "LongText", T.MEDIUMTEXT: "LongText", T.LONGTEXT: "LongText",
    T.TINYINT: "ShortInteger", T.SMALLINT: "ShortInteger",
    T.INT: "Integer", T.MEDIUMINT: "Integer",
    T.BIGINT: "LongInteger",
}
_TIMESTAMPS = {T.TIMESTAMP, T.TIMESTAMPNTZ, T.TIMESTAMPTZ, T.TIMESTAMPLTZ,
               T.DATETIME, T.DATETIME64, T.TIMESTAMP_S, T.TIMESTAMP_MS, T.TIMESTAMP_NS}
_CHARS = {T.VARCHAR, T.CHAR, T.NCHAR, T.NVARCHAR}
_DECIMALS = {T.DECIMAL, T.BIGDECIMAL, T.UDECIMAL,
             T.DECIMAL32, T.DECIMAL64, T.DECIMAL128, T.DECIMAL256}
_FLOATS = {T.FLOAT, T.DOUBLE, T.UDOUBLE, T.DECFLOAT}

# xDM String tops out at 4,000 chars unless an admin opts into extended size.
STRING_MAX = 4000


@dataclass
class Attribute:
    column: str
    suggested_name: str
    sql_type: str
    xdm_type: str | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    mandatory: bool = False
    pk: bool = False
    confidence: str = "high"
    note: str | None = None


@dataclass
class Candidate:
    table: str
    suggested_entity: str
    attributes: list[Attribute] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)


@dataclass
class Inventory:
    source: dict
    candidates: list[Candidate] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def initcap(name: str) -> str:
    """CUST_ID -> CustId. Naming is load-bearing: names reach SemQL and the API."""
    return "".join(p.capitalize() for p in re.split(r"[_\s-]+", name.strip()) if p)


def map_type(dtype: exp.DataType) -> tuple[str | None, dict, str, str | None]:
    """SQL type -> (xdm_type, extras, confidence, note). None means unresolved.

    Anything without a clean mapping is left unresolved rather than coerced. A
    silently wrong datatype propagates through every later phase and is painful to
    change after deployment.
    """
    t = dtype.this
    params = [p for p in dtype.expressions if isinstance(p, exp.DataTypeParam)]
    nums = [int(p.name) for p in params if p.name.isdigit()]

    if t in _SIMPLE:
        return _SIMPLE[t], {}, "high", None
    if t in _TIMESTAMPS:
        return "Timestamp", {}, "high", None
    if t in _CHARS:
        n = nums[0] if nums else None
        if n is None:
            return "LongText", {}, "medium", "unbounded character type"
        return ("String", {"length": n}, "high", None) if n <= STRING_MAX else \
               ("LongText", {}, "high", f"length {n} exceeds String max {STRING_MAX}")
    if t in _DECIMALS:
        p, s = (nums + [None, None])[:2]
        if s:                       # non-zero scale: genuinely fractional
            return "Decimal", {"precision": p, "scale": s}, "high", None
        if p is None:
            return "Decimal", {}, "medium", "unspecified precision"
        # Integral. Widen rather than narrow — under-sizing is a real bug, and
        # ByteInteger/ShortInteger are never inferred from precision alone.
        if p <= 9:
            return "Integer", {"precision": p}, "high", None
        if p <= 18:
            return "LongInteger", {"precision": p}, "high", None
        return "Decimal", {"precision": p, "scale": 0}, "high", None
    if t in _FLOATS:
        return "Decimal", {}, "medium", "xDM has no floating-point type; Decimal is lossy"
    return None, {}, "none", f"no xDM datatype for {t.name}"


def _column(col: exp.ColumnDef, dialect: str) -> Attribute:
    kinds = {type(c.kind).__name__ for c in col.constraints}
    xdm, extras, conf, note = map_type(col.kind) if col.kind else (None, {}, "none", "no type")
    return Attribute(
        column=col.name,
        suggested_name=initcap(col.name),
        sql_type=col.kind.sql(dialect=dialect) if col.kind else "",
        xdm_type=xdm,
        mandatory="NotNullColumnConstraint" in kinds or "PrimaryKeyColumnConstraint" in kinds,
        pk="PrimaryKeyColumnConstraint" in kinds,
        confidence=conf, note=note, **extras,
    )


def from_ddl(sql: str, dialect: str = "snowflake") -> Inventory:
    inv = Inventory(source={"kind": "ddl", "dialect": dialect, "parsed_by": "sqlglot"})
    for stmt in sqlglot.parse(sql, read=dialect):
        if not isinstance(stmt, exp.Create) or not (schema := stmt.find(exp.Schema)):
            continue
        cand = Candidate(table=schema.this.name, suggested_entity=initcap(schema.this.name))
        for c in schema.expressions:
            if isinstance(c, exp.ColumnDef):
                a = _column(c, dialect)
                cand.attributes.append(a)
                if a.xdm_type is None:
                    inv.unresolved.append({"table": cand.table, "column": a.column,
                                           "sql_type": a.sql_type, "reason": a.note})
            elif isinstance(c, exp.PrimaryKey):          # table-level PK
                names = {i.name for i in c.expressions}
                for a in cand.attributes:
                    if a.column in names:
                        a.pk = a.mandatory = True
            elif isinstance(c, exp.ForeignKey):
                ref = c.args.get("reference")
                to = ref.find(exp.Table) if ref else None
                cand.references.append({
                    "from_columns": [i.name for i in c.expressions],
                    "to_table": to.name if to is not None else None,
                    "confidence": "high" if to is not None else "low",
                })
        _flag_composite_pk(cand, inv)
        inv.candidates.append(cand)
    return inv


def _flag_composite_pk(cand: Candidate, inv: Inventory) -> None:
    """An ID-matched entity's PK must be a single attribute — composites get
    concatenated into one PK column (docs/Design/logical-model/entities.md)."""
    pks = [a.column for a in cand.attributes if a.pk]
    if len(pks) > 1:
        inv.unresolved.append({
            "table": cand.table, "column": " + ".join(pks),
            "reason": "composite primary key — if this becomes an ID-matched entity the "
                      "columns must be concatenated into a single PK column",
        })


def from_describe(text: str) -> Inventory:
    """DESCRIBE TABLE / INFORMATION_SCHEMA output, comma- or tab-separated."""
    delim = "\t" if "\t" in text.split("\n")[0] else ","
    raw = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if r]
    if not raw:
        return Inventory(source={"kind": "describe", "parsed_by": "none"})
    header, body = raw[0], raw[1:]
    # An unquoted SQL type spills extra fields: NUMBER(38,0) -> "NUMBER(38" + "0)".
    # Rejoin the surplus rather than dropping it; pasted DESCRIBE output is rarely quoted.
    lower = [h.lower().strip() for h in header]
    tcol = next((i for i, h in enumerate(lower) if h in ("data_type", "type")), None)
    fixed = []
    for r in body:
        if tcol is not None and len(r) > len(header):
            extra = len(r) - len(header)
            r = r[:tcol] + [delim.join(r[tcol:tcol + extra + 1])] + r[tcol + extra + 1:]
        fixed.append(dict(zip(header, r)))
    rows = fixed
    keys = {k.lower().strip(): k for k in header}
    name_k = keys.get("column_name") or keys.get("name")
    type_k = keys.get("data_type") or keys.get("type")
    null_k = keys.get("is_nullable") or keys.get("null?") or keys.get("null")

    inv = Inventory(source={"kind": "describe", "parsed_by": "csv"})
    cand = Candidate(table="UNKNOWN", suggested_entity="Unknown")
    for r in rows:
        raw = (r[type_k] or "").strip()
        try:
            dt = sqlglot.parse_one(raw, into=exp.DataType, read="snowflake")
            xdm, extras, conf, note = map_type(dt)
        except Exception:
            xdm, extras, conf, note = None, {}, "none", f"unparsed type {raw!r}"
        nullable = (r.get(null_k) or "").strip().upper() in {"Y", "YES", "TRUE", "1"}
        a = Attribute(column=r[name_k], suggested_name=initcap(r[name_k]), sql_type=raw,
                      xdm_type=xdm, mandatory=not nullable and null_k is not None,
                      confidence=conf, note=note, **extras)
        cand.attributes.append(a)
        if xdm is None:
            inv.unresolved.append({"column": a.column, "sql_type": raw, "reason": note})
    inv.candidates.append(cand)
    return inv


def from_markdown(text: str) -> Inventory:
    """A pipe table pasted from a wiki. Assumes column | type [| nullable]."""
    rows = [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in text.split("\n")
        if ln.strip().startswith("|") and not re.fullmatch(r"[|\s:-]+", ln.strip())
    ]
    return from_describe("\n".join(",".join(r) for r in rows)) if rows else \
        Inventory(source={"kind": "markdown", "parsed_by": "none"})


def ingest(path: str | Path) -> Inventory:
    """Sniff the input kind and parse. Never raises on malformed input."""
    p = Path(path)
    text = p.read_text()
    head = "\n".join(text.split("\n")[:5]).upper()

    if "CREATE TABLE" in text.upper():
        try:
            inv = from_ddl(text)
        except Exception as exc:                      # noqa: BLE001
            inv = Inventory(source={"kind": "ddl", "parsed_by": "failed"})
            inv.unresolved.append({"reason": f"DDL parse failed: {exc}"[:200]})
        inv.source["file"] = p.name
        return inv
    if text.lstrip().startswith("|"):
        inv = from_markdown(text)
    elif "COLUMN_NAME" in head or "DATA_TYPE" in head or head.startswith("NAME,"):
        inv = from_describe(text)
    else:
        inv = Inventory(source={"kind": "unrecognised", "parsed_by": "none"})
        inv.unresolved.append({
            "reason": "not DDL, DESCRIBE output, or a Markdown table. Free-text schema "
                      "extraction is not implemented — supply CREATE TABLE statements."})
    inv.source["file"] = p.name
    return inv
