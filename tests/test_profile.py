"""agent/tools/profile.py — blocking-key coverage. Sprint 12, deliverable 2.

TWO KINDS OF FIXTURE, on purpose.

The REAL one is `out/s4-multi-source-ids/data/records.yaml` — the dataset that loaded
the running instance. That directory holds no CSVs (the loader reads YAML and posts
JSON), so the test derives them, one row per record. Deriving keeps the fixture the
real dataset instead of a copy that can drift from it, and it is the same conversion
the module docstring documents.

The SYNTHETIC one exists because s4 answers "not measurable" to every key — every
binning key it declares reads a PRE_CONSO enricher's output, which a load file does not
carry. That is the correct answer and it proves nothing about the arithmetic. So the
un-blockable count is proven against a hand-built file with a deliberately empty key
column and an answer worked out by hand, rather than against the tool's own output.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from agent.ir.schema import IR
from agent.tools import profile as P
from agent.tools import semql

ROOT = Path(__file__).resolve().parents[1]
S4 = ROOT / "out" / "s4-multi-source-ids"


# ------------------------------------------------------------------ the real dataset
def _records_to_csv(records_yaml: Path, out_dir: Path) -> dict[str, Path]:
    """records.yaml -> one CSV per record group. Columns are the union of `values`."""
    ds = yaml.safe_load(records_yaml.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)
    made = {}
    for group in ("customers", "opportunities"):
        rows = [r["values"] for r in ds.get(group, [])]
        cols = list(dict.fromkeys(k for row in rows for k in row))
        path = out_dir / f"{group}.csv"
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for row in rows:
                w.writerow({c: row.get(c, "") for c in cols})
        made[group] = path
    return made


@pytest.fixture(scope="module")
def s4_ir():
    return IR.load(S4 / "ir" / "model.yaml", S4 / "ir" / "certify.yaml")


@pytest.fixture
def s4_csvs(tmp_path):
    return _records_to_csv(S4 / "data" / "records.yaml", tmp_path)


def test_s4_csvs_carry_the_wire_column_convention(s4_csvs):
    """The FILES decide the convention, not this test's assumption about it."""
    with open(s4_csvs["customers"]) as fh:
        cols = next(csv.reader(fh))
    assert "SourceID" in cols                    # master key, not the PK attribute
    assert "Address.Zip" in cols                 # complex members are dotted
    assert "CustomerGoldenId" not in cols        # the golden id is output, never loaded


def test_s4_every_binning_key_is_not_measurable_from_the_load_file(s4_ir, s4_csvs):
    """All three keys read a PRE_CONSO enricher's output. The file cannot carry them."""
    prof = P.profile_entity(s4_ir, "Customer", s4_csvs["customers"])
    assert prof.total == 8
    assert prof.id_column == "SourceID"
    assert prof.declared_keys == 3
    assert prof.measurable_keys == 0
    assert [k.rule for k in prof.keys] == ["D_ERP_KEY", "D_BILLING_KEY",
                                           "P_NAME_STATE_ZIP"]
    assert not any(k.measurable for k in prof.keys)
    missing = {k.rule: k.missing_columns for k in prof.keys}
    assert missing["D_ERP_KEY"] == ("ErpKeyNorm",)
    assert missing["D_BILLING_KEY"] == ("BillingKeyNorm",)
    assert missing["P_NAME_STATE_ZIP"] == ("NormalizedName", "Address.StateCodeNorm")
    # and the un-blockable share is withheld rather than computed over nothing
    assert prof.unblockable == 0
    assert not prof.unblockable_exact
    assert "cannot be bounded" in prof.note


def test_s4_names_the_enricher_and_the_upstream_column(s4_ir, s4_csvs):
    """Not-measurable is a verdict with a cause, not a skip."""
    prof = P.profile_entity(s4_ir, "Customer", s4_csvs["customers"])
    by_rule = {k.rule: k for k in prof.keys}

    d = by_rule["D_ERP_KEY"].derivations
    assert len(d) == 1
    assert d[0].enricher == "Customer/NormalizeCarriedKeys"
    assert d[0].scope == "PRE_CONSO"
    assert d[0].reads == ("ErpKey",)
    assert d[0].reads_in_file == ("ErpKey",)
    assert (d[0].inputs_carried, d[0].total) == (4, 8)   # 4 of 8 records carry an ErpKey

    assert by_rule["D_BILLING_KEY"].derivations[0].inputs_carried == 3
    # a two-attribute key traces BOTH of its missing attributes
    p = by_rule["P_NAME_STATE_ZIP"].derivations
    assert [x.attribute for x in p] == ["NormalizedName", "Address.StateCodeNorm"]
    assert [x.inputs_carried for x in p] == [8, 8]


def test_s4_basic_entity_has_no_matcher_and_says_so(s4_ir, s4_csvs):
    prof = P.profile_entity(s4_ir, "Opportunity", s4_csvs["opportunities"])
    assert prof.total == 4
    assert prof.id_column == "OpportunityId"     # no SourceID on a BASIC entity
    assert prof.declared_keys == 0
    assert "no matcher" in prof.note


def test_s4_renders(s4_ir, s4_csvs):
    rep = P.profile(s4_ir, {"Customer": s4_csvs["customers"],
                            "Opportunity": s4_csvs["opportunities"]})
    text = P.render(rep)
    assert "AccountHub" in text
    assert "NOT MEASURABLE" in text
    assert "NormalizeCarriedKeys" in text
    assert "NOT this key's coverage" in text
    assert "NOT SUPPLIED: labelled duplicate / not-duplicate pairs" in text
    assert rep.unprofiled == ()


# --------------------------------------------------- the arithmetic, on known answers
WIDGET_MODEL = {
    "model": {"name": "WidgetHub", "target_technology": "postgresql"},
    "entities": [{
        "name": "Widget", "type": "fuzzy",
        "attributes": [
            {"name": "WidgetGoldenId", "type": "UUID", "pk": True, "mandatory": True},
            {"name": "Serial", "type": "String", "length": 40},
            {"name": "Region", "type": "String", "length": 40},
            {"name": "Tag", "type": "String", "length": 40},
        ],
    }],
}

# SIX RECORDS, and the answer is worked out here rather than read off the tool.
#   W-1  Serial + Region + Tag   -> carries both keys
#   W-2  Serial + Region + Tag   -> carries both keys
#   W-3  Region + Tag            -> carries P_REGION_TAG only
#   W-4  Serial                  -> carries D_SERIAL only
#   W-5  nothing                 -> UN-BLOCKABLE
#   W-6  whitespace Region, Tag  -> UN-BLOCKABLE, and only if strip() is applied
WIDGET_ROWS = [
    {"SourceID": "W-1", "Serial": "S1", "Region": "R1", "Tag": "T1"},
    {"SourceID": "W-2", "Serial": "S2", "Region": "R1", "Tag": "T1"},
    {"SourceID": "W-3", "Serial": "",   "Region": "R2", "Tag": "T2"},
    {"SourceID": "W-4", "Serial": "S4", "Region": "",   "Tag": "T3"},
    {"SourceID": "W-5", "Serial": "",   "Region": "",   "Tag": ""},
    {"SourceID": "W-6", "Serial": "",   "Region": "   ", "Tag": "T6"},
]


def _widget(tmp_path, rules, rows=WIDGET_ROWS, enrichers=()):
    (tmp_path / "model.yaml").write_text(yaml.safe_dump(WIDGET_MODEL))
    (tmp_path / "certify.yaml").write_text(yaml.safe_dump({
        "enrichers": list(enrichers),
        "matchers": [{"entity": "Widget",
                      "policy": {"auto_merge_at": 95, "review_from": 80},
                      "rules": rules}]}))
    path = tmp_path / "widgets.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return IR.load(tmp_path / "model.yaml", tmp_path / "certify.yaml"), path


TWO_KEYS = [
    {"name": "D_SERIAL", "score": 100,
     "condition": "Record1.Serial = Record2.Serial", "binning": ["Serial"]},
    {"name": "P_REGION_TAG", "score": 85,
     "condition": "Record1.Region = Record2.Region AND Record1.Tag = Record2.Tag",
     "binning": ["Region", "Tag"]},
]


def test_coverage_and_unblockable_against_a_hand_worked_answer(tmp_path):
    ir, csv_path = _widget(tmp_path, TWO_KEYS)
    prof = P.profile_entity(ir, "Widget", csv_path)

    assert prof.total == 6
    assert prof.measurable_keys == prof.declared_keys == 2
    by_rule = {k.rule: k for k in prof.keys}

    serial = by_rule["D_SERIAL"]
    assert serial.measurable and (serial.carried, serial.absent) == (3, 3)
    assert serial.absent_ids == ("W-3", "W-5", "W-6")
    assert serial.share == 0.5

    both = by_rule["P_REGION_TAG"]
    assert both.attributes == ("Region", "Tag")          # a key is ALL its expressions
    assert (both.carried, both.absent) == (3, 3)
    assert both.absent_ids == ("W-4", "W-5", "W-6")

    # W-6's Region is "   ". Non-empty as a string, absent as a value.
    assert prof.unblockable_exact
    assert prof.unblockable_ids == ("W-5", "W-6")
    assert prof.unblockable == 2


def test_a_key_the_file_cannot_measure_makes_the_count_an_upper_bound(tmp_path):
    """Adding an unmeasurable key must not silently keep the number a measurement."""
    rules = TWO_KEYS + [{"name": "P_DERIVED", "score": 90,
                         "condition": "Record1.SerialNorm = Record2.SerialNorm",
                         "binning": ["SerialNorm"]}]
    ir, csv_path = _widget(tmp_path, rules)
    prof = P.profile_entity(ir, "Widget", csv_path)

    assert (prof.measurable_keys, prof.declared_keys) == (2, 3)
    assert not prof.unblockable_exact
    assert prof.unblockable_ids == ("W-5", "W-6")        # still sound as a BOUND
    assert "upper bound" in P.render(P.profile(ir, {"Widget": csv_path})).lower()
    # nothing in the IR writes SerialNorm, so there is no enricher to name
    assert {k.rule: k.derivations for k in prof.keys}["P_DERIVED"] == ()
    assert "nothing in the IR writes SerialNorm" in P.render(
        P.profile(ir, {"Widget": csv_path}))


def test_a_rule_with_no_binning_makes_nobody_unblockable(tmp_path):
    """It compares globally. The exposure is cost, not missed matches — say which."""
    rules = TWO_KEYS + [{"name": "P_GLOBAL", "score": 82,
                         "condition": "Record1.Tag = Record2.Tag", "binning": [],
                         "justification": "deliberately global"}]
    ir, csv_path = _widget(tmp_path, rules)
    prof = P.profile_entity(ir, "Widget", csv_path)
    assert prof.global_rules == ("P_GLOBAL",)
    assert prof.unblockable == 0 and prof.unblockable_exact
    assert "compare every record with every other" in prof.note


def test_the_enricher_trace_reports_inputs_not_coverage(tmp_path):
    """The upstream number must never be presented as the key's coverage."""
    rules = [{"name": "P_DERIVED", "score": 90,
              "condition": "Record1.SerialNorm = Record2.SerialNorm",
              "binning": ["SerialNorm"]}]
    enrichers = [{"entity": "Widget", "name": "NormSerial", "scope": "PRE_CONSO",
                  "expressions": [{"attribute": "SerialNorm",
                                   "expression": "UPPER(TRIM(Serial))"}]}]
    ir, csv_path = _widget(tmp_path, rules, enrichers=enrichers)
    prof = P.profile_entity(ir, "Widget", csv_path)
    d = prof.keys[0].derivations[0]
    assert d.enricher == "Widget/NormSerial"
    assert d.reads == ("Serial",) and d.inputs_carried == 3
    assert prof.keys[0].carried == 0 and not prof.keys[0].measurable
    text = P.render(P.profile(ir, {"Widget": csv_path}))
    assert "NOT this key's coverage — the enricher is not evaluated here." in text


def test_names_are_capped_and_the_total_is_still_given(tmp_path):
    rows = [{"SourceID": f"W-{i}", "Serial": "", "Region": "", "Tag": ""}
            for i in range(30)]
    ir, csv_path = _widget(tmp_path, TWO_KEYS, rows=rows)
    text = P.render(P.profile(ir, {"Widget": csv_path}), cap=5)
    assert "… and 25 more (30 total)" in text
    assert "W-29" not in text


def test_a_row_with_no_id_is_numbered_not_invented(tmp_path):
    rows = [{"SourceID": "", "Serial": "", "Region": "", "Tag": ""}]
    ir, csv_path = _widget(tmp_path, TWO_KEYS, rows=rows)
    prof = P.profile_entity(ir, "Widget", csv_path)
    assert prof.unblockable_ids == ("row 1",)


# --------------------------------------------------------------- the file -> entity map
def test_filename_maps_to_entity_including_the_plural(s4_ir, tmp_path):
    for stem, expect in (("customers", "Customer"), ("Customer", "Customer"),
                         ("opportunities", "Opportunity")):
        name, path = P.resolve_entity(str(tmp_path / f"{stem}.csv"), s4_ir)
        assert name == expect and path.name == f"{stem}.csv"


def test_an_explicit_mapping_wins_and_an_unknown_entity_is_refused(s4_ir):
    assert P.resolve_entity("Customer=/tmp/anything.dat", s4_ir)[0] == "Customer"
    with pytest.raises(ValueError, match="not an entity"):
        P.resolve_entity("Widget=/tmp/x.csv", s4_ir)


def test_an_unrecognised_filename_refuses_rather_than_guessing(s4_ir):
    with pytest.raises(ValueError, match="cannot tell which entity"):
        P.resolve_entity("/tmp/extract_2026_08_08.csv", s4_ir)


def test_an_entity_with_keys_and_no_file_is_named(s4_ir, s4_csvs):
    rep = P.profile(s4_ir, {"Opportunity": s4_csvs["opportunities"]})
    assert rep.unprofiled == ("Customer",)
    assert "NOT PROFILED" in P.render(rep)


# ------------------------------------------------------------------ the absent half
def test_calibration_reports_absence_and_never_synthesizes(s4_ir):
    result = P.calibrate_thresholds(s4_ir)
    assert isinstance(result, P.NotSupplied)
    assert not result                              # falsy, so callers cannot misread it
    assert "labelled" in result.what
    assert "match score" in result.needed


def test_supplying_labels_raises_rather_than_scoring_pairs(s4_ir):
    with pytest.raises(NotImplementedError, match="does not run a matcher"):
        P.calibrate_thresholds(s4_ir, labelled_pairs=[("A", "B", True)])


# ------------------------------------------------------- semql.attributes_in, the seam
def test_attributes_in_names_what_an_expression_reads():
    assert semql.attributes_in("ErpKeyNorm") == ["ErpKeyNorm"]
    assert semql.attributes_in("UPPER(TRIM(Name))") == ["Name"]
    # a complex member is ONE attribute path, not a table and a column
    assert semql.attributes_in("Address.StateCodeNorm") == ["Address.StateCodeNorm"]
    assert semql.attributes_in(
        "SUBSTR(REGEXP_REPLACE(TRIM(Address.Zip), '[^0-9]', ''), 1, 5)"
    ) == ["Address.Zip"]
    assert semql.attributes_in("COALESCE(A, B, A)") == ["A", "B"]   # de-duplicated
    assert semql.attributes_in("") == []
    assert semql.attributes_in("'literal'") == []


def test_attributes_in_raises_rather_than_returning_reads_nothing():
    with pytest.raises(ValueError, match="cannot name the attributes"):
        semql.attributes_in("UPPER(TRIM(")


def test_an_unparseable_binning_expression_is_a_verdict_not_a_crash(tmp_path):
    rules = [{"name": "P_BROKEN", "score": 90, "condition": "Record1.Tag = Record2.Tag",
              "binning": ["UPPER(TRIM("]}]
    ir, csv_path = _widget(tmp_path, rules)
    prof = P.profile_entity(ir, "Widget", csv_path)
    assert prof.keys[0].unparseable == ("UPPER(TRIM(",)
    assert not prof.keys[0].measurable
    assert "does not parse" in prof.keys[0].reason


# ---------------------------------------------------------------------------- the CLI
def test_cli_runs_against_s4(s4_ir, s4_csvs, capsys):
    code = P.main([str(S4 / "ir"), str(s4_csvs["customers"]),
                   str(s4_csvs["opportunities"])])
    out = capsys.readouterr().out
    assert code == 0
    assert "BLOCKING-KEY COVERAGE — AccountHub" in out
    assert "D_ERP_KEY: NOT MEASURABLE" in out


def test_cli_refuses_two_files_claiming_one_entity(s4_csvs, capsys):
    code = P.main([str(S4 / "ir"), str(s4_csvs["customers"]),
                   f"Customer={s4_csvs['opportunities']}"])
    assert code == 2
    assert "REFUSED: two files both claim Customer" in capsys.readouterr().out


def test_cli_usage_without_a_csv(capsys):
    assert P.main([str(S4 / "ir")]) == 2
    assert "usage:" in capsys.readouterr().out
