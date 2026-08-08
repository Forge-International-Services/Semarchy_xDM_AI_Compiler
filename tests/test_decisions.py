"""The decision register — step 2. Which decision put this value here?

`policy.py` holds the values and the reasoning. This module adds identity and linkage,
so a compiled model can be audited rather than merely read. It found a real defect on
its first run: scenario 4 still carried `override_strategy: NEVER`, the invented value
fixed in scenario 3 and never propagated. The IR validator did not catch it, because
nothing checked the vocabulary.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.ir import policy  # noqa: E402
from agent.ir.decisions import (  # noqa: E402
    DECISIONS, Decision, attribute, divergences, report)
from agent.ir.schema import IR  # noqa: E402
from agent.ir.validate import validate  # noqa: E402

SCENARIOS = sorted(p for p in (ROOT / "out").glob("s*/ir") if p.is_dir())


def _ir(d: Path) -> IR:
    return IR.load(d / "model.yaml", d / "certify.yaml")


def test_no_decision_restates_a_value_that_lives_in_policy():
    """One copy of each decided number. A register that repeats the values is a second
    source of truth, and the two will disagree the first time one changes."""
    src = (ROOT / "agent" / "ir" / "decisions.py").read_text()
    body = src.split("DECISIONS: tuple[Decision, ...] = (")[1]
    for literal in (str(policy.HOUSE_THRESHOLDS.auto_merge_at),
                    str(policy.HOUSE_THRESHOLDS.review_from)):
        assert f"= {literal}" not in body and f"({literal}" not in body, (
            f"{literal} is hard-coded in decisions.py; read it from policy instead")


def test_every_decision_records_its_provenance():
    """`source` is load-bearing: it decides whether a divergence is a bug or a
    preference, and IR-020 keys on exactly that."""
    for d in DECISIONS:
        assert d.source in ("operator", "observed", "default"), d
        assert d.statement and d.see, d
        assert d.governs, f"{d.id} governs nothing, so it can never be checked"


def test_diverging_from_an_OBSERVED_decision_is_an_error():
    """It does not produce a different design — it produces a model that will not
    import. `NEVER` is the worked example (LESSONS §16)."""
    ir = _ir(ROOT / "out/s3-three-sources/ir")
    ir.certify.survivorship[0].override_strategy = "NEVER"
    rules = [f.rule for f in validate(ir) if f.severity == "error"]
    assert "IR-020" in rules


def test_diverging_from_an_OPERATOR_decision_is_NOT_an_error():
    """House policy is a default, never a constraint — the operator was explicit that
    trust varies per engagement. A different threshold must be VISIBLE, not forbidden.
    """
    ir = _ir(ROOT / "out/s3-three-sources/ir")
    ir.certify.matchers[0].policy.auto_merge_at = 90        # deliberate divergence
    assert not [f for f in validate(ir) if f.severity == "error"]
    diverged = divergences(ir)
    assert any(a.decision == "D-MATCH-BANDS" for a in diverged), \
        "a divergence that is not an error must still be reported"
    assert "NOT an error" in report(ir)


def test_every_decidable_value_is_attributed():
    """`unattributed` means a field policy ought to have an opinion about has none —
    a gap in the register, not in the model."""
    for d in SCENARIOS:
        rows = attribute(_ir(d))
        orphans = [a for a in rows if a.status == "unattributed"]
        assert not orphans, f"{d.parent.name}: {orphans}"


def test_the_authored_scenarios_do_not_silently_diverge():
    """They are the deliverable. A divergence in one is either a design choice that
    belongs in its narrative, or a mistake — and both need to be looked at."""
    for d in SCENARIOS:
        assert not divergences(_ir(d)), f"{d.parent.name}:\n{report(_ir(d))}"


def test_the_register_catches_what_the_validator_missed():
    """Regression for the defect that justified this module: scenario 4 carried an
    invented override strategy that no other check saw."""
    ir = _ir(ROOT / "out/s4-multi-source-ids/ir")
    strategies = {s.override_strategy for s in ir.certify.survivorship
                  if s.kind == "standard"}
    assert strategies <= set(policy.OVERRIDE_STRATEGIES), strategies


# ------------------------------------- what the hand-written list cannot tell you (2)
#
# `_walk` is a list, and a list is silent about its omissions. These tests derive the
# decidable surface from the SCHEMA instead, so the question "what are we not looking
# at?" has an answer that does not depend on anyone remembering.
def test_the_decidable_surface_comes_from_the_schema_not_a_list():
    """Add a Literal field with a default to the IR and it appears here immediately.
    That is the whole point: the register's blind spot must not be maintained by hand
    any more than the register itself."""
    from agent.ir.decisions import decidable_fields
    fields = decidable_fields()
    assert ("Entity", "golden_id_generation", "SEQUENCE") in fields
    assert ("Reference", "delete_propagation", "RESTRICT") in fields
    # Required Literals are excluded by construction: the author always states them, so
    # they cannot be chosen for anyone.
    assert not [f for f in fields if f[0:2] == ("Entity", "type")]


#: The blind spot as it stands. A RATCHET, exactly like test_blocks.py's missing-element
#: debt: it may shrink, never grow. A new IR field that silently joins this list is the
#: failure this whole derivation exists to prevent.
KNOWN_UNWATCHED = {
    ("Attribute", "mandatory_scope"),
    ("Reference", "delete_propagation"),
    ("Reference", "validation_scope"),
    ("Validation", "scope"),
    # Arrived with the workflow IR and NOT yet excused: how long a completed workflow's
    # data is kept is a governance decision, and FOREVER is the most consequential
    # default in the whole schema to take without saying so.
    ("RetentionPolicy", "retention_type"),
}


def test_the_blind_spot_only_shrinks():
    from agent.ir.decisions import unwatched
    now = {(m, f) for m, f, _ in unwatched()}
    new = now - KNOWN_UNWATCHED
    assert not new, (
        f"{len(new)} decidable field(s) newly unwatched: {sorted(new)}\n"
        "Either govern them with a Decision, walk them in _walk, or record why not in "
        "decisions.NOT_WATCHED — with the reason, not just the name.")
    gone = KNOWN_UNWATCHED - now
    assert not gone, f"{sorted(gone)} now watched — remove from KNOWN_UNWATCHED."


def test_an_excused_field_names_a_reason_not_just_itself():
    """NOT_WATCHED is a register of decisions NOT to watch something. A bare list of
    names would be indistinguishable from the omission it is meant to document."""
    from agent.ir.decisions import NOT_WATCHED, decidable_fields
    known = {(m, f) for m, f, _ in decidable_fields()}
    for key, why in NOT_WATCHED.items():
        assert key in known, f"{key} is excused but is not a decidable field at all"
        assert len(why) > 40, f"{key}: {why!r} is not a reason"


# ------------------------------------- D-NORMALIZE-FIRST speaks to MATCH INPUTS only
def test_a_post_conso_enricher_that_feeds_no_match_rule_is_not_a_divergence():
    """The decision reads "every MATCH INPUT carries a PRE_CONSO normalizer". Minting
    an identifier on a confirmed golden is POST_CONSO by necessity, and calling that a
    divergence from a rule about match inputs is the register misreading its own text.

    It stayed invisible while no scenario had a post-consolidation enricher at all —
    a rule shown only correct examples has not been tested."""
    from agent.ir.decisions import divergences
    from agent.ir.schema import CertifyIR, IR, ModelIR

    def _ir(scope):
        return IR(
            model_ir=ModelIR(
                model={"name": "P", "target_technology": "postgresql"},
                entities=[{"name": "Org", "type": "fuzzy",
                           "attributes": [
                               {"name": "Id", "type": "String", "length": 10,
                                "pk": True, "mandatory": True},
                               {"name": "NormalizedName", "type": "String",
                                "length": 50},
                               {"name": "ForceID", "type": "String", "length": 20}]}]),
            certify=CertifyIR(
                enrichers=[
                    {"entity": "Org", "name": "NormalizeName", "scope": "PRE_CONSO",
                     "position": 1,
                     "expressions": [{"attribute": "NormalizedName",
                                      "expression": "UPPER(Id)"}]},
                    {"entity": "Org", "name": "MintForceId", "scope": scope,
                     "position": 2,
                     "expressions": [{"attribute": "ForceID",
                                      "expression": "UPPER(Id)"}]}],
                matchers=[{"entity": "Org",
                           "policy": {"auto_merge_at": 95, "review_from": 80},
                           "rules": [{"name": "D_NAME", "score": 100,
                                      "binning": ["NormalizedName"],
                                      "condition": "Record1.NormalizedName = "
                                                   "Record2.NormalizedName"}]}],
                survivorship=[{"entity": "Org", "name": "IdRule", "kind": "id",
                               "strategy": "SMALLEST_VALUE", "attributes": []}]))

    # ForceID is read by no match rule, so its enricher's scope is not this decision's
    # business either way.
    assert divergences(_ir("POST_CONSO")) == []
    assert divergences(_ir("PRE_CONSO")) == []


def test_an_enricher_reaching_a_match_rule_through_a_chain_is_still_watched():
    """The transitive half. A normalizer feeding a phonetic enricher feeding a rule is
    a match input, and a one-step check does not see it."""
    from agent.ir.decisions import _match_feeders
    from agent.ir.schema import CertifyIR, IR, ModelIR
    ir = IR(
        model_ir=ModelIR(
            model={"name": "P", "target_technology": "postgresql"},
            entities=[{"name": "Org", "type": "basic",
                       "attributes": [{"name": "Id", "type": "String", "length": 10,
                                       "pk": True, "mandatory": True}]}]),
        certify=CertifyIR(
            enrichers=[
                {"entity": "Org", "name": "Normalize", "scope": "PRE_CONSO",
                 "position": 1,
                 "expressions": [{"attribute": "NormalizedName",
                                  "expression": "UPPER(Name)"}]},
                {"entity": "Org", "name": "Phonetic", "scope": "PRE_CONSO",
                 "position": 2,
                 "expressions": [{"attribute": "Token",
                                  "expression": "METAPHONE(NormalizedName, 8)"}]},
                {"entity": "Org", "name": "Unrelated", "scope": "PRE_CONSO",
                 "position": 3,
                 "expressions": [{"attribute": "Note", "expression": "UPPER(Id)"}]}],
            matchers=[{"entity": "Org",
                       "policy": {"auto_merge_at": 95, "review_from": 80},
                       "rules": [{"name": "D_TOKEN", "score": 100,
                                  "binning": ["Token"],
                                  "condition": "Record1.Token = Record2.Token"}]}]))
    feeders = {n for _, n in _match_feeders(ir)}
    assert feeders == {"Phonetic", "Normalize"}
