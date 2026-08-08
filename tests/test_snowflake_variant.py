"""The Snowflake variant must differ from the bench variant ONLY where it is declared to.

A fork's failure mode is drift: two copies of the same design diverge somewhere nobody
looked, and the divergence is found on the target rather than here. There is no include
mechanism in the IR, so the two directories are genuine copies — which makes an
automated diff the only thing standing between "a deliberate dialect fork" and "two
models that used to be the same".

The allow-list below IS the specification. Adding a legitimate difference means adding
it here, with a reason, in the open.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.ir.schema import IR  # noqa: E402
from agent.tools.semql import unknown_functions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "out" / "s6-organization-hub" / "ir"
SNOW = ROOT / "out" / "s6-organization-hub" / "ir-snowflake"

#: EVERY test in this module is a diff between those two directories, and s6 is a
#: privately-sourced scenario that the public export does not ship. So the whole module
#: skips there rather than failing. Module-level is right here and nowhere else in the
#: suite: there is no test in this file that has anything to say without both halves of
#: the fork. No assertion was changed — in the full repository all six run.
pytestmark = pytest.mark.skipif(
    not (BENCH.is_dir() and SNOW.is_dir()),
    reason="out/s6-organization-hub/{ir,ir-snowflake} not present")

#: Every sanctioned textual difference, as (bench text, snowflake text, why).
DECLARED = (
    ("target_technology: postgresql", "target_technology: snowflake",
     "the point of the fork"),
    ("name: OrgHubProbe\n", "name: OrgHubProbeSnow\n",
     "the lab holds both; they must not overwrite each other"),
    ("label: Organization Hub Probe\n", "label: Organization Hub Probe (Snowflake)\n",
     "follows the name"),
    # The dialect token is anchored on the digit-stripping pattern rather than on
    # `, '')` alone — the short form also matches every COALESCE(..., '') in the file,
    # which made the first version of this test count sixteen of nine.
    ("'[^0-9]', '', 'g')", "'[^0-9]', '')",
     "PostgreSQL REGEXP_REPLACE needs 'g' to replace all matches; Snowflake replaces "
     "all by default and its fourth argument is an integer POSITION, so 'g' is the "
     "wrong type in the wrong slot"),
)

#: How many times the dialect difference is expected to appear. Pinned, so removing a
#: call site on one side only is drift rather than a silently smaller fork.
#:
#: Was 9 until the tax-id predicate was materialized into `ENR_NORMALIZE_TAXID`: the two
#: deterministic match rules carried 8 of those calls between them and now carry none.
#: What remains is 1 in `VAL_STATE_ZIP_FORMAT` and 2 in the new enricher — the enricher is
#: itself a forked site, and counting it honestly is the point of pinning the number.
DIALECT_SITES = 3


def _canonical(text: str) -> str:
    """Collapse every declared difference, so what remains is undeclared drift.

    LONGEST FIRST. `label: … Probe` is a prefix of `label: … Probe (Snowflake)`, so
    replacing in declaration order collapsed the prefix and left ` (Snowflake)` behind
    looking exactly like undeclared drift.
    """
    for bench, snow, _ in sorted(DECLARED, key=lambda d: -max(len(d[0]), len(d[1]))):
        text = text.replace(snow, "@@DECLARED@@").replace(bench, "@@DECLARED@@")
    return text


@pytest.mark.parametrize("fname", ["model.yaml", "certify.yaml"])
def test_the_variants_differ_only_where_declared(fname):
    a, b = (BENCH / fname).read_text(), (SNOW / fname).read_text()
    ca, cb = _canonical(a), _canonical(b)
    if ca != cb:
        import difflib
        diff = "\n".join(difflib.unified_diff(
            ca.splitlines(), cb.splitlines(), "bench", "snowflake", lineterm="", n=1))
        pytest.fail(f"undeclared drift in {fname}:\n{diff[:3000]}")


def test_the_dialect_difference_is_actually_present():
    """A collapsing diff would also pass if someone made the two files identical and
    reintroduced the PostgreSQL spelling on Snowflake. Assert the direction too."""
    snow = (SNOW / "certify.yaml").read_text()
    bench = (BENCH / "certify.yaml").read_text()
    assert "'[^0-9]', '', 'g')" in bench, \
        "the bench variant lost its global-replace flag"
    assert "'[^0-9]', '', 'g')" not in snow, \
        "the Snowflake variant carries PostgreSQL's 'g' flag, which lands in its " \
        "integer POSITION argument"
    assert bench.count("'[^0-9]', '', 'g')") == DIALECT_SITES
    assert snow.count("'[^0-9]', '')") == DIALECT_SITES


def test_both_variants_declare_the_technology_they_are_for():
    for d, tech in ((BENCH, "postgresql"), (SNOW, "snowflake")):
        ir = IR.load(d / "model.yaml", d / "certify.yaml")
        assert ir.model_ir.model.target_technology == tech


def test_neither_variant_calls_an_unavailable_function():
    """Per-technology, because the lists genuinely differ — and because this check is
    what a fork is FOR. Note what it cannot do: it verifies a function NAME is available,
    not that its SIGNATURE matches. `REGEXP_REPLACE` passes on both technologies and
    still needed a dialect fork."""
    for d, tech in ((BENCH, "postgresql"), (SNOW, "snowflake")):
        ir = IR.load(d / "model.yaml", d / "certify.yaml")
        declared = [f.name for f in ir.model_ir.sql_functions]
        bad = []
        for e in ir.certify.enrichers:
            for x in e.expressions:
                bad += unknown_functions(x.expression, tech, declared)
        for v in ir.certify.validations:
            bad += unknown_functions(v.condition, tech, declared)
        for m in ir.certify.matchers:
            for r in m.rules:
                bad += unknown_functions(r.condition, tech, declared)
        assert not bad, f"{tech}: {sorted(set(bad))}"


def test_the_snowflake_variant_passes_every_offline_gate():
    from agent.compile.blocks import check as shape_check
    from agent.compile.emit import emit
    from agent.ir import depends
    from agent.ir.decisions import divergences
    from agent.ir.validate import errors, validate

    ir = IR.load(SNOW / "model.yaml", SNOW / "certify.yaml")
    assert errors(validate(ir)) == []
    assert depends.blocking_violations(ir) == [] and depends.cycles(ir) == []
    assert divergences(ir) == []
    xml = emit(ir.model_ir, platform_version="2025.1.8",
               repository_version="2025.1.2", certify=ir.certify)
    hard = [f for f in shape_check(xml)
            if f.kind in ("encoding", "unknown", "null-ref", "empty-holder")]
    assert hard == [], [str(f) for f in hard]
