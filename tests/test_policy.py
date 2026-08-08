from pathlib import Path as _Path

import pytest


# ------------------------------------------------- the override-strategy vocabulary
def test_override_strategies_are_only_the_ones_with_evidence_behind_them():
    """Two were PROBED LIVE 2026-08-04, one constant at a time, because every
    overrideStrategy element in the corpus available then was NULL — nothing was there
    to read. `NEVER` was an invention: it compiled, it round-tripped, and the importer
    refused the whole payload with "Unable to parse payload".

    The third was ADDED 2026-08-06 on stronger evidence — the product's own exports
    write it. See `test_until_consolidated_val_change_is_measured_not_guessed`.
    """
    from agent.ir import policy
    assert policy.OVERRIDE_STRATEGIES == ("NO_OVERRIDE", "UNTIL_NEXT_USER_CHANGE",
                                          "UNTIL_CONSOLIDATED_VAL_CHANGE")
    assert policy.OVERRIDE_FORBIDDEN in policy.OVERRIDE_STRATEGIES
    assert policy.OVERRIDE_ALLOWED in policy.OVERRIDE_STRATEGIES
    assert policy.OVERRIDE_UNTIL_CONSOLIDATED in policy.OVERRIDE_STRATEGIES
    assert "NEVER" not in policy.OVERRIDE_STRATEGIES
    # REFUSED by the live importer, each tried individually against a fresh model.
    # `UNTIL_CONSOLIDATED_VALUE` stays here and stays refused: it is a DIFFERENT and
    # shorter string than the one the product writes, and keeping the near-miss on the
    # list is what stops the accepted value being read as "the guess finally landed".
    for invented in ("NEVER", "NONE", "NEVER_OVERRIDE", "ALWAYS_AUTHORED",
                     "UNTIL_NEXT_CONSOLIDATION", "UNTIL_CONSOLIDATED_VALUE"):
        assert invented not in policy.OVERRIDE_STRATEGIES


#: The exports this file measures against. `samples/`, `live/` and `harvest/` are a
#: production-sourced model, vendor demo content and the measurement bench, and the public
#: export ships none of them — so the one test here whose subject is the CORPUS skips
#: rather than reporting "the evidence is gone" about a tree that never had it. The
#: vocabulary assertions above read `policy` and keep running.
_ROOT = _Path(__file__).resolve().parents[1]
requires_product_exports = pytest.mark.skipif(
    not [f for d in ("samples", "live", "harvest") for f in (_ROOT / d).glob("*.xml")],
    reason="samples/, live/ and harvest/ product exports not present")


@requires_product_exports
def test_until_consolidated_val_change_is_measured_not_guessed():
    """The evidence that widened the vocabulary, pinned so it cannot quietly become
    folklore: the value is in exports THE PRODUCT WROTE, not in anything this compiler
    emitted. If the corpus stops containing it, this vocabulary needs re-arguing."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    from agent.ir import policy

    root = Path(__file__).resolve().parents[1]
    found = {}
    for d in ("samples", "live", "harvest"):
        for f in sorted((root / d).glob("*.xml")):
            try:
                tree = ET.parse(f)
            except ET.ParseError:
                continue
            n = sum(1 for el in tree.getroot().iter("overrideStrategy")
                    if el.get("val") == policy.OVERRIDE_UNTIL_CONSOLIDATED)
            if n:
                found[f.name] = n
    assert found, ("no corpus export writes UNTIL_CONSOLIDATED_VAL_CHANGE any more — "
                   "the evidence that widened OVERRIDE_STRATEGIES is gone")
    # Two DISTINCT models, so the value is not one modeller's habit in one file.
    assert len(found) >= 2, found
    assert sum(found.values()) >= 7, found


def test_policy_picks_a_strategy_the_importer_accepts():
    from agent.ir import policy
    assert policy.override_strategy(computed=True) == "NO_OVERRIDE"
    assert policy.override_strategy(computed=False) == "UNTIL_NEXT_USER_CHANGE"
