"""Offline SemQL syntax checking. Sprint 08b.

The corpus settles what SemQL is. docs/SemQL/semql-syntax.md, first line:

    "The SemQL syntax supports the equivalent of SQL expressions, conditions or
     ORDER BY clauses"

Measured against all three samples: **135 of 137** distinct expressions parse as
Snowflake SQL unmodified. The whole delta is ONE construct — the child-collection
quantifier — plus bind variables, which every SQL dialect already has:

    ANY  <role> HAVE ( <condition> )      docs/SemQL/operators.md
    ALL  <role> HAVE ( <condition> )
    NOT ANY <role> HAS ( <condition> )    HAS is an accepted synonym for HAVE
    :V_USER_ROLES                         model variables and search parameters

So a real syntax check IS possible without an instance, by rewriting the quantifier
into a function call and handing the rest to a SQL parser. That matters because the
alternative — "only xDM's validation can tell you" — costs a full compile, import and
validate cycle to discover a missing bracket.

WHAT THIS DOES NOT DO. It checks SYNTAX, not meaning. It cannot know that `Custmer` is
a typo, that a role path exists, or that a function is supported by the target
database. A clean result here means "this will parse", not "this is correct" — the
same distinction as round-trip fidelity versus correctness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import sqlglot

from agent import corpus

Kind = Literal["expression", "condition", "order_by"]

# `[NOT] ANY|ALL <role path> HAVE|HAS (` — case-insensitive per the docs ("Operators
# are not case-sensitive"). The role path may be dotted: Items.Images.
_QUANT = re.compile(
    r"\b(?P<quant>ANY|ALL)\s+(?P<role>[A-Za-z_]\w*(?:\.\w+)*)\s+(?:HAVE|HAS)\s*\(",
    re.IGNORECASE)


# Aggregate functions. An enricher computes ONE VALUE PER ROW, so an aggregate has
# nothing to aggregate over: xDM generates `select <expr>, <pk> from …` with no GROUP
# BY, and the database rejects it.
#
# OBSERVED 2026-08-03: an enricher expression of JSONB_OBJECT_AGG('a', 1) generated
#     select FUZPR.FUPRI AS FUPRI, cast(JSONB_OBJECT_AGG('a'::text, 1) as text) …
# and suspended the whole integration queue. It is SYNTACTICALLY VALID SQL, so the
# parser accepted it — this is the semantic check that catches it.
#
# SemQL itself does NOT catch this. Its editor warns on unknown FUNCTION NAMES but
# passes them through to the database, so a function it has never heard of still
# reaches Postgres. The name being known is no protection either: JSONB_OBJECT_AGG
# raised no warning at all.
AGGREGATES = frozenset({
    "SUM", "AVG", "MIN", "MAX", "COUNT", "ARRAY_AGG", "STRING_AGG", "LISTAGG",
    "JSON_AGG", "JSONB_AGG", "JSON_OBJECT_AGG", "JSONB_OBJECT_AGG",
    "BOOL_AND", "BOOL_OR", "EVERY", "BIT_AND", "BIT_OR",
    "STDDEV", "STDDEV_POP", "STDDEV_SAMP", "VARIANCE", "VAR_POP", "VAR_SAMP",
    "CORR", "COVAR_POP", "COVAR_SAMP", "PERCENTILE_CONT", "PERCENTILE_DISC",
    "MODE", "RANK", "DENSE_RANK", "CUME_DIST", "PERCENT_RANK",
})

_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


# ------------------------------------------------ per-technology built-in functions
#: Parsed from the mirrored docs rather than pinned here, so a doc refresh updates it.
#:
#: This is the ONE corpus file the export pack carries (agent/corpus.py, SHIPPED).
#: The dependency is not incidental: IR-017 runs unknown_functions() over every
#: enricher expression, validation condition and match rule, and it decides by
#: SUBTRACTING the set this file defines. An empty set makes LOWER() an invention and
#: refuses a model that is correct — a validator that fails closed on its own missing
#: input, which is the worst direction for one to fail in.
_FUNCTION_LIST = "docs/SemQL/function-list.md"
_BUILTINS: dict[str, frozenset[str]] | None = None
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z_0-9]*)\s*\(")
#: SemQL keywords and constructs that look like calls but are not functions.
_NOT_FUNCTIONS = frozenset({
    "AND", "OR", "NOT", "IN", "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "CAST", "ANY", "ALL", "HAVE", "BETWEEN", "LIKE", "IS", "NULL", "DISTINCT",
    "SELECT", "FROM", "WHERE", "AS", "ON", "USING", "INTERVAL", "DECIMAL",
})


#: SQL functions the doc omits because the standard spells them as SYNTAX rather than
#: as calls — `TRIM(BOTH x FROM y)`, `EXTRACT(YEAR FROM d)`. They are absent from every
#: technology table and are nonetheless valid everywhere. TRIM is verified live: it is
#: what normalized "  Ada  Lovelace " on the lab.
_SQL_SYNTAX_FUNCTIONS = frozenset({
    "TRIM", "SUBSTRING", "POSITION", "OVERLAY", "EXTRACT",
})

#: Functions the TARGET DATABASE resolves that xDM's own function list never mentions.
#:
#: This set has to exist because of what SemQL is: unknown names are passed straight
#: through to the database, so the set of expressions that actually work is "documented
#: SemQL functions UNION everything the target database offers". `function-list.md` is
#: only the first half, which makes every native database function a false refusal.
#:
#: EVERY ENTRY NEEDS EVIDENCE, and "it is in the vendor's manual" is not enough on its
#: own — SEM_METAPHONE reached a database precisely because the editor passes names
#: through without checking (LESSONS §11, §20). Nor is "a real export uses it": an
#: export proves someone WROTE it, not that it RAN.
#:
#: The evidence that counts is the DATABASE's own verdict. When Snowflake refused a
#: live job with `Unknown functions UDF_DOUBLE_METAPHONE, UDF_DOUBLE_METAPHONE,
#: UDF_DOUBLE_METAPHONE`, it named every unresolved function in the statement — and
#: `GET`, in the same statement, was not among them. The compiler resolved it. That is
#: a positive result from the only authority that matters.
_DB_NATIVE: dict[str, frozenset[str]] = {
    # GET(<object>, '<key>') — reads a field out of a VARIANT/OBJECT. Evidenced by a
    # Snowflake compilation error that named the UDFs beside it and not GET itself,
    # 2026-08-05.
    "snowflake": frozenset({"GET"}),
}


def builtins_for(technology: str) -> frozenset[str]:
    """Built-in SemQL functions for one hub technology, from docs/SemQL/function-list.md.

    The lists genuinely differ, and that difference is a portability constraint rather
    than trivia: METAPHONE and DMETAPHONE are PostgreSQL-only, so a phonetic enricher
    written against the lab does not move to Snowflake (D13's target), which offers
    SOUNDEX alone.
    """
    global _BUILTINS
    if _BUILTINS is None:
        path = corpus.require(_FUNCTION_LIST, "SemQL function checking (IR-017)")
        acc: dict[str, set[str]] = {}
        section = None
        for line in path.read_text().splitlines():
            if line.startswith("#"):
                section = line.strip("# ").strip()
            m = re.match(r"^\|\s*`([A-Z_0-9]+)`", line)
            if m and section and section.startswith("Functions for"):
                key = section[len("Functions for"):].strip().lower()
                acc.setdefault(key, set()).add(m.group(1))
        _BUILTINS = {k: frozenset(v) for k, v in acc.items()}
    return _BUILTINS.get((technology or "").strip().lower(), frozenset())


def calls_in(text: str) -> list[str]:
    """Every function-looking name invoked in an expression, upper-cased."""
    if not text:
        return []
    out, seen = [], set()
    for name in _CALL.findall(text):
        u = name.upper()
        if u in _NOT_FUNCTIONS or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def unknown_functions(text: str, technology: str, declared=()) -> list[str]:
    """Names that are neither built in for `technology` nor declared on the model.

    This is the check that would have caught `SEM_METAPHONE`: it parses as SQL, the
    xDM editor warns and passes it through, the model deploys, and the enricher dies
    on the first row with `bad SQL grammar` (LESSONS §20). A function xDM does not
    know is legitimate ONLY if the model declares it as a SqlFunction.
    """
    known = (builtins_for(technology) | _SQL_SYNTAX_FUNCTIONS
             | _DB_NATIVE.get((technology or "").strip().lower(), frozenset())
             | {d.upper() for d in declared})
    return [c for c in calls_in(text) if c not in known]


def aggregates_in(text: str) -> list[str]:
    """Aggregate function names called in an expression, uppercased and de-duplicated."""
    if not text:
        return []
    return sorted({m.group(1).upper() for m in _CALL.finditer(text)
                   if m.group(1).upper() in AGGREGATES})


@dataclass(frozen=True)
class SemQLIssue:
    where: str
    expression: str
    message: str

    def render(self) -> str:
        return f"{self.where}: {self.message}\n    {self.expression.strip()[:160]}"


def _rewrite_quantifiers(text: str) -> str:
    """`ANY Items HAVE (cond)` -> `SEM_QUANT_ANY_Items(cond)`.

    A function call, so the parser still descends into the inner condition and a
    syntax error inside the brackets is still reported. Applied repeatedly because
    quantifiers nest.
    """
    for _ in range(20):                        # bounded; nesting deeper than this is not real
        m = _QUANT.search(text)
        if m is None:
            return text
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += (text[i] == "(") - (text[i] == ")")
            i += 1
        if depth:                              # unbalanced — let the parser report it
            return text
        inner = text[m.end():i - 1]
        text = (f"{text[:m.start()]}"
                f"SEM_QUANT_{m.group('quant').upper()}_"
                f"{m.group('role').replace('.', '_')}({inner}){text[i:]}")
    return text


def normalize(text: str) -> str:
    """SemQL -> something a SQL parser accepts, preserving structure."""
    out = _rewrite_quantifiers(text)
    # Model variables and search parameters. sqlglot understands `:name` in some
    # dialects but not all, and the value is irrelevant to a syntax check.
    return re.sub(r":(\w+)", r"SEM_VAR_\1", out)


def attributes_in(text: str) -> list[str]:
    """Every attribute PATH an expression reads, in order of first appearance.

    `UPPER(TRIM(Name))` -> `["Name"]`. `Address.StateCodeNorm` -> that dotted path
    intact, because a complex-attribute member is one attribute in the IR and one
    column on the wire (`Address.Zip5`), not a table and a column.

    This names what an expression READS. It says nothing about what those names mean:
    an attribute that does not exist on the entity looks exactly like one that does,
    which is the same syntax-is-not-semantics line the rest of this module draws.

    Raises ValueError when the expression does not parse. A caller that wants a verdict
    rather than an exception should run `check()` first — an unparseable expression has
    no attribute list, and returning an empty one would read as "reads nothing".
    """
    if not text or not text.strip():
        return []
    try:
        tree = sqlglot.parse_one(normalize(text), read="snowflake")
    except Exception as exc:                   # sqlglot raises several types
        raise ValueError(f"cannot name the attributes of {text!r}: "
                         f"{str(exc).splitlines()[0][:200]}") from exc
    out, seen = [], set()
    for col in tree.find_all(sqlglot.exp.Column):
        path = ".".join(p.name for p in col.parts)
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def check(text: str, kind: Kind = "condition", where: str = "") -> list[SemQLIssue]:
    """Empty list if it parses. One issue if it does not."""
    if not text or not text.strip():
        return []
    agg = aggregates_in(text)
    if agg and kind != "order_by":
        return [SemQLIssue(
            where or kind, text,
            f"calls the aggregate function{'s' if len(agg) > 1 else ''} "
            f"{', '.join(agg)} in a row-level expression. xDM generates a per-row "
            f"SELECT with no GROUP BY, so the database rejects it and the integration "
            f"queue suspends. Use the row-level equivalent — e.g. JSONB_BUILD_OBJECT "
            f"instead of JSONB_OBJECT_AGG.")]
    sql = normalize(text)
    # An ORDER BY clause is a comma-separated LIST with optional ASC/DESC/NULLS, which
    # is not a single expression — parsing it as one reports a spurious error at the
    # first comma.
    stmt = f"SELECT 1 ORDER BY {sql}" if kind == "order_by" else sql
    try:
        sqlglot.parse_one(stmt, read="snowflake")
    except Exception as exc:                   # sqlglot raises several types
        first = str(exc).split("\n")[0][:200]
        return [SemQLIssue(where or kind, text,
                           f"does not parse as SemQL ({kind}): {first}")]
    return []


# Which IR fields hold what kind of phrase. Getting this wrong produces false errors,
# so it is stated rather than inferred.
RANKING_IS_ORDER_BY = "order_by"


def check_ir(ir) -> list[SemQLIssue]:
    """Every SemQL phrase the IR carries, checked in one pass."""
    issues: list[SemQLIssue] = []

    def look(text, kind, where):
        issues.extend(check(text, kind, where))

    tech = ir.model_ir.model.target_technology
    declared = [f.name for f in ir.model_ir.sql_functions]

    def unknown(text, where):
        for fn in unknown_functions(text or "", tech, declared):
            issues.append(SemQLIssue(
                where, text or "",
                f"calls {fn!r}, which is not a built-in SemQL function for "
                f"{tech!r} and is not declared as a SqlFunction on the model. "
                f"An undeclared name is passed straight through to the database and "
                f"fails at RUN time, not at compile or deploy time."))

    for e in ir.certify.enrichers:
        for x in e.expressions:
            look(x.expression, "expression",
                 f"enricher {e.entity}/{e.name} -> {x.attribute}")
            unknown(x.expression, f"enricher {e.entity}/{e.name} -> {x.attribute}")
        look(e.condition, "condition", f"enricher {e.entity}/{e.name} condition")
    for v in ir.certify.validations:
        look(v.condition, "condition", f"validation {v.entity}/{v.name}")
        unknown(v.condition, f"validation {v.entity}/{v.name}")
    for m in ir.certify.matchers:
        for r in m.rules:
            look(r.condition, "condition", f"match rule {m.entity}/{r.name}")
            unknown(r.condition, f"match rule {m.entity}/{r.name}")
            for b in r.binning:
                look(b, "expression", f"binning {m.entity}/{r.name}")
    for s in ir.certify.survivorship:
        # A ranking expression is an ORDER BY clause — it takes ASC/DESC and
        # NULLS FIRST/LAST, which are illegal in a plain expression.
        look(s.order_by, RANKING_IS_ORDER_BY, f"survivorship {s.entity}/{s.name}")

    for c in ir.app.display_cards:
        for field, text in (("primary", c.primary_text),
                            ("secondary", c.secondary_text),
                            ("supporting", c.supporting_text)):
            look(text, "expression", f"display card {c.entity}/{c.name} {field}")
    for v in ir.app.business_views:
        look(v.filter, "condition", f"business view {v.entity}/{v.name} filter")
        for n in v.nodes:
            look(n.sort_expression, "order_by",
                 f"business view {v.entity}/{v.name} node {n.name} sort")
            for f in n.filters:
                look(f.condition, "condition",
                     f"built-in filter {v.name}/{f.name}")
    return issues
