"""Test the tumor-selectivity _verdict() (added 2026-07-17).

Before this, tumor-selectivity passed no verdict_fn — Phase-B selectivity (a
first-order nomination criterion) was computed as selectivity_class but silently
dropped (verdict=None), never reaching synthesis / the gate / the risk table.
These tests pin the rule-id → verdict mapping and that verdict strings equal the
selectivity_class values (so the risk-table _biological() reshape consumes them).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("ts_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ts = _load()


def _fire(rule_id):
    return ts._verdict([{"rule_id": rule_id}])


def test_strong_selective_maps_to_class_string():
    assert _fire("tvn-strong-selective-supportive") == (
        "strong_tumor_selective", "tvn-strong-selective-supportive")


def test_not_selective_maps():
    assert _fire("tvn-not-selective-neutral") == (
        "not_selective", "tvn-not-selective-neutral")


def test_discordant_maps():
    assert _fire("tvn-discordant-neutral-flagged")[0] == "discordant_across_comparators"


def test_data_unavailable_maps():
    assert _fire("tvn-data-unavailable-insufficient")[0] == "data_unavailable"


def test_no_rules_is_insufficient():
    assert ts._verdict([]) == ("insufficient", None)


def test_verdict_strings_match_risk_table_biological_keys():
    """The risk-table reshape's _biological() keys off these exact strings —
    guard against a rename that would silently stop selectivity feeding biological risk."""
    strong = _fire("tvn-strong-selective-supportive")[0]
    notsel = _fire("tvn-not-selective-neutral")[0]
    assert strong == "strong_tumor_selective"   # consumed by _biological() LOW branch
    assert notsel == "not_selective"            # consumed by _biological() HIGH branch


def test_verdict_fn_is_discoverable_by_composer():
    """target-profile's _load_sub_skill_verdict_fn looks for _verdict OR _snapshot."""
    assert hasattr(ts, "_verdict") or hasattr(ts, "_snapshot")


# --- axis-B/E NORMAL-BREADTH VETO (conjunction redesign INC-1/2, 2026-08-07) -----------------
# A gene over-expressed vs its tissue-of-origin (axis A: strong/modest/field_effect) but with NO
# therapeutic window vs the worst critical normal (housekeeping: GAPDH/ACTB/TUBB) is NOT a target.
# The modality-therapeutic-window card's tvn-no-therapeutic-window-veto rule fires; _verdict applies
# it as a conjunction that DOWNGRADES the axis-A call to selective_but_broadly_normal.
_VETO = "tvn-no-therapeutic-window-veto"


def _fire_two(axis_a_rule):
    return ts._verdict([{"rule_id": axis_a_rule}, {"rule_id": _VETO}])


def test_strong_selective_downgraded_by_window_veto():
    """The GAPDH archetype: strong axis-A fold-change, but tumor below worst critical normal."""
    assert _fire_two("tvn-strong-selective-supportive") == (
        "selective_but_broadly_normal", _VETO)


def test_modest_selective_downgraded_by_window_veto():
    assert _fire_two("tvn-modest-selective-supportive")[0] == "selective_but_broadly_normal"


def test_field_effect_selective_downgraded_by_window_veto():
    assert _fire_two("tvn-field-effect-selective-supportive")[0] == "selective_but_broadly_normal"


def test_veto_alone_does_not_manufacture_a_selective_call():
    """The clamp is one-directional — it only downgrades a selective axis-A verdict, never
    upgrades. With ONLY the veto (no axis-A selective rule), the resolver verdict stands."""
    verdict = ts._verdict([{"rule_id": _VETO}])[0]
    assert verdict != "selective_but_broadly_normal"


def test_not_selective_unaffected_by_window_veto():
    """A NOT-selective gene that also has no window stays not_selective — the veto can't
    turn a down-regulated gene into 'broadly normal' (that verdict is a downgrade OF selective)."""
    assert ts._verdict(
        [{"rule_id": "tvn-not-selective-neutral"}, {"rule_id": _VETO}])[0] == "not_selective"


def test_selective_without_veto_is_unchanged():
    """No veto fired (CEACAM5/FOLR1/MSLN archetype: real window) → axis-A call stands byte-for-byte."""
    assert _fire("tvn-strong-selective-supportive") == (
        "strong_tumor_selective", "tvn-strong-selective-supportive")


# --- F1 (2026-08-08 synthesis review): _headline must EMIT the resolved (post-veto) verdict. ---
# Before this, _headline ignored verdict_pair and emitted the raw pre-veto tvn.selectivity_class, so
# selective_but_broadly_normal was NEVER emitted anywhere in decision.json + the narrator over-claimed.

def _headline_for(cards_summary_class, verdict_pair):
    cards = [{"card_id": "tumor-vs-normal-selectivity", "summary": {"selectivity_class": cards_summary_class}},
             {"card_id": "tumor-vs-normal-percentile-crossing", "summary": {}},
             {"card_id": "modality-therapeutic-window", "summary": {}},
             {"card_id": "expression-purity-confound", "summary": {"purity_confound_class": "purity_independent"}}]
    return ts._headline(cards, [], verdict_pair)


def test_headline_emits_resolved_veto_downgrade():
    """When _verdict returns the veto downgrade, the headline selectivity_class is the RESOLVED
    value (not the raw axis-A class), driving_rule_id names the veto, and the raw class is preserved."""
    h = _headline_for("strong_tumor_selective",
                      ("selective_but_broadly_normal", ts._WINDOW_VETO_RULE))
    assert h["selectivity_class"] == "selective_but_broadly_normal"     # RESOLVED, was dropped before
    assert h["driving_rule_id"] == ts._WINDOW_VETO_RULE
    assert h["axis_a_selectivity_class"] == "strong_tumor_selective"    # raw pre-veto preserved


def test_headline_emits_resolved_verdict_no_veto():
    """No veto: headline selectivity_class == the resolved axis-A verdict; raw == resolved."""
    h = _headline_for("strong_tumor_selective",
                      ("strong_tumor_selective", "tvn-strong-selective-supportive"))
    assert h["selectivity_class"] == "strong_tumor_selective"
    assert h["driving_rule_id"] == "tvn-strong-selective-supportive"
    assert h["axis_a_selectivity_class"] == "strong_tumor_selective"


def test_headline_surfaces_purity_facet():
    """DEFERRED-3: the verdict-inert purity-confound facet is surfaced in the headline."""
    h = _headline_for("strong_tumor_selective", ("strong_tumor_selective", "r"))
    assert h["purity_confound_class"] == "purity_independent"


def test_deferred1_composed_path_composes_the_veto_card():
    """DEFERRED-1: target-profile's SUB_SKILL_CARDS[tumor-selectivity] must include
    modality-therapeutic-window, so the normal-breadth veto rule fires in the COMPOSED path
    (card_id_filter) identically to standalone — else a broadly-normal gene nominates as selective."""
    import ast
    tp_run = (RUN_PY.parent.parent.parent / "target-profile" / "scripts" / "run.py").read_text()
    tree = ast.parse(tp_run)
    ssc = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "SUB_SKILL_CARDS" for t in node.targets):
            ssc = node.value
    assert ssc is not None, "SUB_SKILL_CARDS not found in target-profile/run.py"
    # find the tumor-selectivity entry
    sel_cards = None
    for k, v in zip(ssc.keys, ssc.values):
        if isinstance(k, ast.Constant) and k.value == "tumor-selectivity":
            sel_cards = [e.value for e in v.elts if isinstance(e, ast.Constant)]
    assert sel_cards is not None
    assert "modality-therapeutic-window" in sel_cards, (
        "DEFERRED-1 regression: the veto card is not composed into the selectivity lens → the "
        "normal-breadth veto cannot fire in target-profile (housekeeping FP resurrected).")
