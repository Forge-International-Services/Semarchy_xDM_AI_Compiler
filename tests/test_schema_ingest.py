"""Sprint 02 acceptance: schema_ingest."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.tools.schema_ingest import (  # noqa: E402
    XDM_TYPES, ingest, from_ddl, from_describe, from_markdown, initcap, map_type,
)

DDL = Path(__file__).parent / "fixtures" / "ddl" / "customer_snowflake.sql"


@pytest.fixture(scope="module")
def inv():
    return ingest(DDL)


def _attr(inv, table, col):
    cand = next(c for c in inv.candidates if c.table == table)
    return next(a for a in cand.attributes if a.column == col)


def test_tables_and_entity_names(inv):
    assert [c.table for c in inv.candidates] == ["CUSTOMER", "ORDER_LINE"]
    assert [c.suggested_entity for c in inv.candidates] == ["Customer", "OrderLine"]


def test_initcap():
    assert initcap("CUST_ID") == "CustId"
    assert initcap("full name") == "FullName"
    assert initcap("SKU") == "Sku"


@pytest.mark.parametrize("col,xdm", [
    ("FULL_NAME", "String"), ("BIRTH_DATE", "Date"), ("CREATED_AT", "Timestamp"),
    ("IS_ACTIVE", "Boolean"), ("CREDIT_LIMIT", "Decimal"), ("NOTES", "LongText"),
    ("CUST_ID", "Decimal"),          # NUMBER(38,0) exceeds LongInteger range
])
def test_type_mapping(inv, col, xdm):
    assert _attr(inv, "CUSTOMER", col).xdm_type == xdm


def test_integral_precision_widens_not_narrows(inv):
    """Under-sizing is a real bug, so precision maps up, never down."""
    assert _attr(inv, "ORDER_LINE", "LINE_NO").xdm_type == "Integer"       # p=9
    assert _attr(inv, "CUSTOMER", "ACCOUNT_NO").xdm_type == "LongInteger"  # p=18
    # p=20 exceeds LongInteger's 64-bit range (~9.2e18, 19 digits), so Decimal
    # is the correct mapping, not a wider integer.
    assert _attr(inv, "CUSTOMER", "BIG_REF").xdm_type == "Decimal"         # p=20


def test_string_length_preserved(inv):
    assert _attr(inv, "CUSTOMER", "FULL_NAME").length == 200


def test_float_is_flagged_lossy_not_silently_coerced(inv):
    a = _attr(inv, "CUSTOMER", "LIFETIME_VALUE")
    assert a.xdm_type == "Decimal" and a.confidence == "medium" and "lossy" in a.note


def test_unmapped_type_is_unresolved_not_coerced(inv):
    assert _attr(inv, "CUSTOMER", "PROFILE_BLOB").xdm_type is None
    assert any(u.get("column") == "PROFILE_BLOB" for u in inv.unresolved)


def test_not_null_and_pk(inv):
    assert _attr(inv, "CUSTOMER", "CUST_ID").pk
    assert _attr(inv, "CUSTOMER", "FULL_NAME").mandatory
    assert not _attr(inv, "CUSTOMER", "EMAIL").mandatory


def test_foreign_key_becomes_a_candidate_reference(inv):
    refs = next(c for c in inv.candidates if c.table == "CUSTOMER").references
    assert refs == [{"from_columns": ["COUNTRY_CODE"], "to_table": "COUNTRY",
                     "confidence": "high"}]


def test_composite_pk_is_surfaced_with_the_id_matched_rule(inv):
    u = next(u for u in inv.unresolved if u.get("table") == "ORDER_LINE")
    assert "ORDER_ID + LINE_NO" == u["column"]
    assert "concatenated" in u["reason"]


def test_every_emitted_type_is_a_real_xdm_type(inv):
    """Guards the type table against typos — a bad name would reach the IR."""
    for c in inv.candidates:
        for a in c.attributes:
            assert a.xdm_type is None or a.xdm_type in XDM_TYPES, a.xdm_type


def test_no_entity_type_or_publisher_is_inferred(inv):
    """Schema cannot express publisher topology; guessing it pre-empts G1."""
    blob = str(inv.to_dict()).lower()
    for forbidden in ("fuzzy", "id_matched", "publisher", "searchable"):
        assert forbidden not in blob


def test_describe_output():
    inv = from_describe(
        "COLUMN_NAME,DATA_TYPE,IS_NULLABLE\nCUST_ID,NUMBER(38,0),NO\nEMAIL,VARCHAR(255),YES\n")
    a, b = inv.candidates[0].attributes
    assert (a.suggested_name, a.mandatory) == ("CustId", True)
    assert (b.xdm_type, b.length, b.mandatory) == ("String", 255, False)


def test_markdown_table():
    inv = from_markdown(
        "| COLUMN_NAME | DATA_TYPE |\n|---|---|\n| EMAIL | VARCHAR(255) |\n")
    assert inv.candidates[0].attributes[0].xdm_type == "String"


def test_malformed_input_degrades_rather_than_raising(tmp_path):
    p = tmp_path / "broken.sql"
    p.write_text("CREATE TABLE (((( totally not sql")
    inv = ingest(p)
    assert inv.unresolved and not inv.candidates


def test_unrecognised_input_says_what_to_supply(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("we have customers and orders somewhere in the CRM")
    inv = ingest(p)
    assert "CREATE TABLE" in inv.unresolved[0]["reason"]


def test_map_type_rejects_unknown_cleanly():
    dt = sqlglot.parse_one("GEOGRAPHY", into=exp.DataType, read="snowflake")
    xdm, _, conf, note = map_type(dt)
    assert xdm is None and conf == "none" and "GEOGRAPHY" in note
