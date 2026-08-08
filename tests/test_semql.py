

# ------------------------------------------- declared DB functions (operator, 2026-08-04)
from pathlib import Path  # noqa: E402

from agent.tools.semql import (  # noqa: E402
    builtins_for, calls_in, unknown_functions)

ROOT = Path(__file__).resolve().parents[1]


def test_the_builtin_lists_really_do_differ_per_technology():
    """Not trivia — a portability constraint. The operator's hub is PostgreSQL and
    D13's target is Snowflake, and the phonetic functions do not survive the move."""
    assert "METAPHONE" in builtins_for("postgresql")
    assert "DMETAPHONE" in builtins_for("postgresql")
    assert "METAPHONE" not in builtins_for("snowflake")
    assert "SOUNDEX" in builtins_for("snowflake")
    assert "AGE" in builtins_for("postgresql")      # the operator's declared example
    assert builtins_for("nonesuch") == frozenset()


def test_the_check_that_would_have_caught_SEM_METAPHONE():
    """LESSONS §20: it parsed as SQL, the editor passed it through, the model deployed,
    and the enricher died on the first row with `bad SQL grammar`."""
    assert unknown_functions("SEM_METAPHONE(NormalizedName)", "postgresql") == \
        ["SEM_METAPHONE"]
    assert unknown_functions("METAPHONE(NormalizedName, 8)", "postgresql") == []


def test_a_function_declared_on_the_model_is_legitimate():
    """Declaring a SqlFunction is exactly what makes a non-built-in name valid."""
    assert unknown_functions("UDF_NORMALIZE_NAME(x)", "snowflake") == \
        ["UDF_NORMALIZE_NAME"]
    assert unknown_functions("UDF_NORMALIZE_NAME(x)", "snowflake",
                             declared=["UDF_NORMALIZE_NAME"]) == []


def test_sql_syntax_functions_are_not_false_positives():
    """TRIM is absent from every technology table because the standard spells it as
    syntax. It is valid, and it is what normalized "  Ada  Lovelace " on the lab."""
    assert unknown_functions("LOWER(TRIM(Email))", "postgresql") == []
    assert unknown_functions("EXTRACT(YEAR FROM d)", "postgresql") == []


def test_keywords_are_not_mistaken_for_calls():
    assert "CASE" not in calls_in("CASE WHEN x THEN UPPER(y) ELSE NULL END")
    assert "UPPER" in calls_in("CASE WHEN x THEN UPPER(y) ELSE NULL END")


# ------------------------------------- external functions: the extension mechanism
#
# SemQL passes unknown names straight through to the database, which is not only a
# hazard (SEM_METAPHONE) but the EXTENSION POINT: a hub calls functions you build in
# the database, and on Snowflake that reaches external functions and APIs. It is also
# the only route to phonetic matching there — METAPHONE is PostgreSQL-only, so the
# Snowflake equivalent is a UDF you build, declare, and call.
def _ir_with(fn_schema=None, expr="X(a)", tech="snowflake", deps=()):
    from agent.ir.schema import IR, Enricher, FunctionArgument, SqlFunction
    ir = IR.load(ROOT / "out/s3-three-sources/ir/model.yaml",
                 ROOT / "out/s3-three-sources/ir/certify.yaml")
    ir.model_ir.model.target_technology = tech
    ir.model_ir.external_dependencies = list(deps)
    if fn_schema is not None:
        ir.model_ir.sql_functions = [SqlFunction(
            name="UDF_DOUBLE_METAPHONE", schema_name=fn_schema or None,
            arguments=[FunctionArgument(name="name", position=1)])]
    ir.certify.enrichers = [Enricher(
        entity="Party", name="ENR_PHONETIC", kind="semql", scope="PRE_CONSO",
        expressions=[{"attribute": "PhoneticNameToken", "expression": expr}])]
    return ir


def test_declaring_a_sql_function_makes_a_udf_legitimate():
    """THE CAPABILITY. Without the declaration the name is refused as invented; with
    it, the model compiles. This is what lets a Snowflake hub have phonetic matching
    that PostgreSQL gets from a built-in."""
    from agent.ir.validate import validate
    call = "UDF_DOUBLE_METAPHONE(NormalizedName)"
    undeclared = [i for i in validate(_ir_with(expr=call)) if i.rule == "IR-017"]
    assert undeclared, "an undeclared custom function must still be refused"
    declared = [i for i in validate(_ir_with(fn_schema="", expr=call))
                if i.rule == "IR-017"]
    assert not declared, "declaring it as a SqlFunction must clear the refusal"


def test_a_schema_qualified_declaration_called_bare_is_flagged():
    """IR-027, from a live failure: an integration job died with
    `Unknown functions UDF_DOUBLE_METAPHONE` on generated SQL that called it
    unqualified, while the model declared it in a schema. Every offline check passed
    that expression."""
    from agent.ir.validate import validate
    iss = [i for i in validate(_ir_with(
        fn_schema="HUB.SHARED", expr="udf_double_metaphone(NormalizedName)"))
        if i.rule == "IR-027"]
    assert iss and iss[0].severity == "warning", \
        "warning, not error — the failure is real but the mechanism is not proven"
    assert "search path" in iss[0].why


def test_qualifying_the_call_satisfies_it():
    from agent.ir.validate import validate
    ir = _ir_with(fn_schema="HUB.SHARED",
                  expr="HUB.SHARED.UDF_DOUBLE_METAPHONE(NormalizedName)",
                  deps=["HUB.SHARED.UDF_DOUBLE_METAPHONE"])
    assert not [i for i in validate(ir) if i.rule in ("IR-027", "IR-014", "IR-017")]


def test_a_declaration_without_a_schema_is_not_flagged():
    """A native database function declared for SemQL's benefit has no schema to
    qualify with. IR-027 must not invent one."""
    from agent.ir.validate import validate
    ir = _ir_with(fn_schema="", expr="udf_double_metaphone(NormalizedName)")
    assert not [i for i in validate(ir) if i.rule == "IR-027"]


def test_a_native_database_function_is_not_refused():
    """GET() is Snowflake's, not xDM's, so function-list.md never mentions it and the
    checker called it invented. Evidence it is real comes from the database itself: a
    Snowflake compilation error named every unresolved function in a statement, and
    GET — in that same statement — was not among them."""
    from agent.tools.semql import unknown_functions
    assert unknown_functions("GET(x, 'primary')", "snowflake") == []
    assert unknown_functions("GET(x, 'primary')", "postgresql") == ["GET"], \
        "the allowance is per technology — it is a Snowflake fact, not a global one"


def test_the_native_allowance_stays_evidence_sized():
    """It must not become a dumping ground for every name someone wanted to use. Each
    entry needs a database verdict behind it, and a short list is how that stays true."""
    from agent.tools.semql import _DB_NATIVE
    assert sum(len(v) for v in _DB_NATIVE.values()) <= 5, \
        "growing this set needs evidence per entry, not convenience"
