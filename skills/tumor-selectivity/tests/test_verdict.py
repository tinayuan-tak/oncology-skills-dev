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


# --- NORMAL-BREADTH VETO: the essential-organ window arm ------------------------------------
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


# --- NORMAL-BREADTH VETO: the pan-normal window arm (tvn-no-full-normal-window-veto). ---
_FULL_VETO = "tvn-no-full-normal-window-veto"


def test_strong_selective_downgraded_by_full_normal_veto():
    """TROP2/TACSTD2 archetype: clean vs essential organs but broad across NON-essential normals →
    the pan-normal veto (alone) downgrades a selective axis-A call."""
    assert ts._verdict(
        [{"rule_id": "tvn-strong-selective-supportive"}, {"rule_id": _FULL_VETO}]) == (
        "selective_but_broadly_normal", _FULL_VETO)


def test_field_effect_downgraded_by_full_normal_veto():
    assert ts._verdict(
        [{"rule_id": "tvn-field-effect-selective-supportive"}, {"rule_id": _FULL_VETO}])[0] == (
        "selective_but_broadly_normal")


def test_full_normal_veto_alone_does_not_manufacture_selective():
    """One-directional: the pan-normal veto with no axis-A selective rule does not mint a downgrade."""
    assert ts._verdict([{"rule_id": _FULL_VETO}])[0] != "selective_but_broadly_normal"


def test_essential_veto_takes_precedence_in_driving_rule_when_both_fire():
    """When BOTH normal-breadth vetoes fire, the verdict is the downgrade and the driving_rule names
    the essential-organ veto (the stricter critical-organ signal)."""
    v, drv = ts._verdict([{"rule_id": "tvn-strong-selective-supportive"},
                          {"rule_id": _VETO}, {"rule_id": _FULL_VETO}])
    assert v == "selective_but_broadly_normal"
    assert drv == _VETO


def test_clean_full_normal_target_retains_selective():
    """CEACAM5/FOLR1/MSLN archetype: neither veto fired → axis-A selective call stands (no false downgrade)."""
    assert _fire("tvn-strong-selective-supportive") == (
        "strong_tumor_selective", "tvn-strong-selective-supportive")


# --- NORMAL-BREADTH VETO: the cell-type-resolved sc-normal arm (tvn-sc-normal-critical-organ-veto). ---
_SC_VETO = "tvn-sc-normal-critical-organ-veto"


def test_strong_selective_flagged_liability_by_sc_normal_veto():
    """FOLR1/DLL3/ERBB2 archetype: highly detected in an essential cell type of a NON-origin critical
    organ (critical_organ_liability) → the sc-normal arm produces the SELECTIVITY-PRESERVING
    selective_with_normal_liability (a named-organ SAFETY flag), NOT the housekeeping
    selective_but_broadly_normal KILL. The bulk window vetoes did not fire (a real window exists)."""
    assert ts._verdict(
        [{"rule_id": "tvn-strong-selective-supportive"}, {"rule_id": _SC_VETO}]) == (
        "selective_with_normal_liability", _SC_VETO)


def test_sc_normal_veto_alone_does_not_manufacture_selective():
    v = ts._verdict([{"rule_id": _SC_VETO}])[0]
    assert v not in ("selective_but_broadly_normal", "selective_with_normal_liability")


def test_veto_precedence_essential_over_full_over_sc(tmp_path=None):
    """When multiple normal-breadth vetoes fire, the verdict is the downgrade and the driving_rule
    follows precedence: essential-organ window > pan-normal window > sc-normal cell-type."""
    # all three fire → essential-organ wins the label
    v, drv = ts._verdict([{"rule_id": "tvn-strong-selective-supportive"},
                          {"rule_id": _VETO}, {"rule_id": _FULL_VETO}, {"rule_id": _SC_VETO}])
    assert v == "selective_but_broadly_normal" and drv == _VETO
    # full + sc (no essential) → pan-normal wins
    _, drv2 = ts._verdict([{"rule_id": "tvn-strong-selective-supportive"},
                           {"rule_id": _FULL_VETO}, {"rule_id": _SC_VETO}])
    assert drv2 == _FULL_VETO
    # sc alone → sc names it
    _, drv3 = ts._verdict([{"rule_id": "tvn-strong-selective-supportive"}, {"rule_id": _SC_VETO}])
    assert drv3 == _SC_VETO


def test_selective_without_veto_is_unchanged():
    """No veto fired (CEACAM5/FOLR1/MSLN archetype: real window) → axis-A call stands byte-for-byte."""
    assert _fire("tvn-strong-selective-supportive") == (
        "strong_tumor_selective", "tvn-strong-selective-supportive")

# --- NORMAL-BREADTH VETO: the quantitative normal-PROTEIN abundance arm (tphp, Floor-C). ---
_TPHP_VETO = "tvn-tphp-broad-abundant-normal-protein-veto"


def test_strong_selective_flagged_liability_by_tphp_normal_protein_veto():
    """A target broadly ABUNDANT (Floor-C, not trace) across normal tissues at the PROTEIN level
    (tphp_normal_protein_liability_class == broad_and_abundant) with a real RNA window → the tphp arm
    produces the SELECTIVITY-PRESERVING selective_with_normal_liability (mirrors the sc-normal arm),
    NOT the housekeeping KILL. This is the RNA-clean / protein-broad safety-net the arm closes."""
    assert ts._verdict(
        [{"rule_id": "tvn-strong-selective-supportive"}, {"rule_id": _TPHP_VETO}]) == (
        "selective_with_normal_liability", _TPHP_VETO)


def test_tphp_veto_alone_does_not_manufacture_selective():
    v = ts._verdict([{"rule_id": _TPHP_VETO}])[0]
    assert v not in ("selective_but_broadly_normal", "selective_with_normal_liability")


def test_window_kill_outranks_tphp_liability_when_both_fire():
    """Precedence: a no-window KILL (housekeeping GAPDH: window veto + broad_and_abundant tphp both
    fire) outranks the tphp named liability → selective_but_broadly_normal, driven by the window veto."""
    v, drv = ts._verdict([{"rule_id": "tvn-strong-selective-supportive"},
                          {"rule_id": _VETO}, {"rule_id": _TPHP_VETO}])
    assert v == "selective_but_broadly_normal" and drv == _VETO


def test_tphp_does_not_clamp_a_non_selective_call():
    """KRAS archetype: broad_and_abundant tphp fires but axis-A is not selective (discordant/not_selective)
    → the one-directional clamp is a no-op (never manufactures a downgrade on a non-selective verdict)."""
    v = ts._verdict([{"rule_id": "tvn-not-selective-neutral"}, {"rule_id": _TPHP_VETO}])[0]
    assert v == "not_selective"


# --- _headline must EMIT the resolved (post-veto) verdict, not the raw pre-veto axis-A class. ---
# If _headline emitted the raw tvn.selectivity_class, a veto-downgraded target
# (selective_but_broadly_normal) would never appear in decision.json and the narrator would over-claim.

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
    """The verdict-inert purity-confound facet is surfaced in the headline."""
    h = _headline_for("strong_tumor_selective", ("strong_tumor_selective", "r"))
    assert h["purity_confound_class"] == "purity_independent"


def test_composed_path_composes_all_veto_cards():
    """target-profile's SUB_SKILL_CARDS[tumor-selectivity] must include EVERY normal-breadth veto card,
    so ALL three veto arms fire in the COMPOSED path (card_id_filter) identically to standalone — else
    a broadly-normal gene nominates as selective. In particular the sc-normal arm
    (tvn-sc-normal-critical-organ-veto, keying sc-normal-celltype-expression) must not silently drop
    from the selectivity lens."""
    import ast
    # SUB_SKILL_CARDS lives in target-profile/scripts/tp_fanout.py.
    tp_run = (RUN_PY.parent.parent.parent / "target-profile" / "scripts" / "tp_fanout.py").read_text()
    tree = ast.parse(tp_run)
    ssc = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "SUB_SKILL_CARDS" for t in node.targets):
            ssc = node.value
    assert ssc is not None, "SUB_SKILL_CARDS not found in target-profile/scripts/tp_fanout.py"
    # find the tumor-selectivity entry
    sel_cards = None
    for k, v in zip(ssc.keys, ssc.values):
        if isinstance(k, ast.Constant) and k.value == "tumor-selectivity":
            sel_cards = [e.value for e in v.elts if isinstance(e, ast.Constant)]
    assert sel_cards is not None
    # Every card backing a normal-breadth veto arm must be composed into the selectivity lens.
    for veto_card in ("modality-therapeutic-window", "sc-normal-celltype-expression"):
        assert veto_card in sel_cards, (
            f"regression: veto card {veto_card!r} is not composed into the selectivity "
            f"lens → its normal-breadth veto arm cannot fire in target-profile (housekeeping FP "
            f"resurrected for that arm).")


# --- The absolute surface-density facet is VERDICT-INERT (a display facet, NOT a veto).
# The CD19 counterexample (110 copies/cell, grade A — a validated CAR-T/TCE antigen below the soluble-TCE
# floor) is why below_tce_floor must NOT clamp the selectivity verdict. These pin the inert contract. ---

def _headline_with_density(axis_a_class, verdict_pair, density_fields):
    cards = [{"card_id": "tumor-vs-normal-selectivity", "summary": {"selectivity_class": axis_a_class}},
             {"card_id": "tumor-vs-normal-percentile-crossing", "summary": {}},
             {"card_id": "modality-therapeutic-window", "summary": {}},
             {"card_id": "sc-normal-celltype-expression", "summary": {}},
             {"card_id": "expression-purity-confound", "summary": {}},
             {"card_id": "surface-abundance-density", "summary": density_fields}]
    return ts._headline(cards, [], verdict_pair)


def test_density_facet_surfaced_but_verdict_inert():
    """The absolute-density facet appears in the headline but the selectivity_class is exactly the
    resolved verdict — the density fields feed NO clamp."""
    h = _headline_with_density(
        "strong_tumor_selective", ("strong_tumor_selective", "tvn-strong-selective-supportive"),
        {"absolute_copies_per_cell": 110.0, "absolute_density_grade": "A",
         "density_floor_verdict": "below_tce_floor", "is_tce_viable": False})
    assert h["selectivity_class"] == "strong_tumor_selective"      # NOT downgraded by below_tce_floor
    assert h["absolute_copies_per_cell"] == 110.0                  # facet surfaced
    assert h["density_floor_verdict"] == "below_tce_floor"


def test_below_floor_does_not_appear_in_veto_rule_set():
    """Hard guard: no density-floor rule id is in the normal-breadth veto set — axis-C is a facet, not
    a 4th veto arm (the CD19-protection design decision)."""
    veto_rules = set(ts._NORMAL_BREADTH_VETO_RULES)
    assert not any("density" in r or "floor" in r for r in veto_rules), (
        "regression: a density-floor rule leaked into the veto set — axis-C must stay verdict-inert "
        "(below-floor is a modality caveat, not a target killer; CD19=110/cell is a validated antigen).")


def test_density_facet_unmeasured_when_no_anchor():
    """Un-anchored target → density_floor_verdict passes through as whatever the card emits (unmeasured);
    the facet still does not touch the verdict."""
    h = _headline_with_density(
        "modest_tumor_selective", ("modest_tumor_selective", "tvn-modest-selective-supportive"),
        {"absolute_copies_per_cell": None, "density_floor_verdict": "unmeasured"})
    assert h["selectivity_class"] == "modest_tumor_selective"
    assert h["density_floor_verdict"] == "unmeasured"


# ── (strength, certainty) sidecar — CERTAINTY_MODEL 2nd axis ─────────────────────────────────────
def _sel_cards(sel_class, cells_ran=3, n_tumor=50, direction="up", prot_eff=1.5, prot_q=0.01, protein=True):
    c = [{"card_id": "tumor-vs-normal-selectivity",
          "summary": {"selectivity_class": sel_class, "cells_ran": cells_ran, "n_tumor": n_tumor,
                      "dominant_direction": direction}},
         {"card_id": "modality-therapeutic-window", "summary": {"therapeutic_window_class": "adequate_window"}},
         {"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_safety_essential_class": "no_liability"}}]
    if protein:
        c.append({"card_id": "tumor-protein-abundance-cptac",
                  "summary": {"protein_effect_size": prot_eff, "protein_bh_q_value": prot_q}})
    return c


def test_strength_certainty_strong_selective_concordant():
    sc = ts._strength_certainty(_sel_cards("strong_tumor_selective"),
                                verdict_pair=("strong_tumor_selective", "tvn-strong-selective-supportive"))
    assert sc["strength"] == "strong_positive"
    assert sc["certainty"]["coverage"] == "high"           # 3 cells, n_tumor>=10
    assert sc["certainty"]["corroboration"] == "high"      # CPTAC protein concordant
    assert sc["certainty"]["level"] == "high"
    assert sc["certainty"]["unknown_mass"] == 0.0


def test_strength_certainty_protein_unmeasured_drops_from_level():
    # no CPTAC card -> corroboration unmeasured -> level = coverage (absence is ignorance, not disagreement)
    sc = ts._strength_certainty(_sel_cards("modest_tumor_selective", cells_ran=2, protein=False),
                                verdict_pair=("modest_tumor_selective", "tvn-modest-selective-supportive"))
    assert sc["strength"] == "moderate_positive"
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == sc["certainty"]["coverage"] == "medium"


def test_strength_certainty_insufficient_forces_low():
    sc = ts._strength_certainty(_sel_cards("data_unavailable", cells_ran=0, protein=False),
                                verdict_pair=("insufficient", None))
    assert sc["strength"] == "none"
    assert sc["certainty"]["level"] == "low"


def test_strength_certainty_corroborator_is_cptac_not_percentile_crossing():
    # DISJOINTNESS in spirit: corroboration is driven by the CPTAC protein card, NOT by the same-RNA
    # percentile-crossing card (pseudo-replication). Adding a percentile-crossing card must not change it.
    base = _sel_cards("strong_tumor_selective", protein=False)
    base.append({"card_id": "tumor-vs-normal-percentile-crossing",
                 "summary": {"selectivity_class": "strong_tumor_selective",
                             "fraction_tumor_above_normal_p95": 0.9}})
    sc = ts._strength_certainty(base, verdict_pair=("strong_tumor_selective", "x"))
    assert sc["certainty"]["corroboration"] == "unmeasured"   # no CPTAC -> unmeasured despite percentile card
