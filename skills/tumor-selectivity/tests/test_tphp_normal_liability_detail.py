"""PR G / F10 + F11: the TPHP normal-PROTEIN veto arm is PROJECTED, and the subtype panorama is
RECONCILED against the pooled crossing call.

`selective_with_normal_liability` is minted by TWO arms — the sc-normal single-cell critical-organ
veto AND the TPHP bulk-DIA-MS broad-abundant-normal-protein veto (tvn-tphp-broad-abundant-normal-
protein-veto). Before PR G the tension text named only the sc-normal single-cell organ, so a
TPHP-driven clamp emitted an UNNAMED organ and MISATTRIBUTED bulk normal-protein breadth to a
cell-type liability; and normal_protein_breadth_class / tphp_normal_protein_liability_class were
read nowhere, making the CARDS comment's "surfaces ..." claim measurably false. These tests pin the
projection helper, the driving-rule-aware tension branch, the TPHP UNASSESSED analogue, and the
pure subtype→pooled reconciliation — each with an anti-vacuity arm so the two branches must DIFFER.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

ts = load_run_py(Path(__file__).resolve().parent.parent, "ts_run_tphp")

_TPHP_DRIVER = "tvn-tphp-broad-abundant-normal-protein-veto"


def _tphp(cls, breadth="broad", tissue="liver", tissue_class="high"):
    """A TPHP normal-tissue-protein card summary shape (fields per methods/tphp_normal_protein/read.py)."""
    return {
        "tphp_normal_protein_liability_class": cls,
        "normal_protein_breadth_class": breadth,
        "highest_abundance_tissue": tissue,
        "highest_abundance_tissue_class": tissue_class,
    }


# ── _tphp_normal_liability_detail: names the tissue ONLY when the arm fires ───────────────────────


def test_detail_names_breadth_and_tissue_when_broad_and_abundant():
    d = ts._tphp_normal_liability_detail(_tphp("broad_and_abundant", breadth="broad", tissue="liver"))
    assert d == "broad; highest in liver"


def test_detail_falls_back_when_no_breadth_or_tissue():
    # broad_and_abundant fired but the descriptive fields are absent — still a non-None, non-empty string
    d = ts._tphp_normal_liability_detail({"tphp_normal_protein_liability_class": "broad_and_abundant"})
    assert d == "broad, abundant normal-tissue protein"


def test_detail_none_for_non_firing_classes():
    # Only broad_and_abundant fires the veto and names an organ. detected_not_abundant / restricted are
    # measured-but-clean; data_unavailable is handled as the UNASSESSED tension, not a named liability.
    for cls in ("detected_not_abundant", "restricted", "data_unavailable", None):
        assert ts._tphp_normal_liability_detail(_tphp(cls)) is None, cls
    assert ts._tphp_normal_liability_detail({}) is None
    assert ts._tphp_normal_liability_detail(None) is None


# ── tension text: the TPHP arm names ITS tissue, the sc-normal arm names ITS organ ────────────────


def test_tphp_driven_clamp_names_protein_liability_not_single_cell_organ():
    hl = {
        "selectivity_class": "selective_with_normal_liability",
        "driving_rule_id": _TPHP_DRIVER,
        "tphp_normal_liability_detail": "broad; highest in liver",
        # a sc-normal detail is ALSO present — the branch must ignore it for a TPHP-driven clamp
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
    }
    t = ts._selectivity_tension_extra(hl)
    assert t["source"] == "normal_liability_flag_tphp"
    assert t["severity"] == 3
    assert "protein" in t["text"] and "liver" in t["text"]
    # MISATTRIBUTION guard: the bulk-DIA-MS arm must NOT borrow the sc-normal single-cell framing.
    assert "single-cell" not in t["text"]
    assert "kidney proximal tubule cell" not in t["text"]


def test_sc_normal_driven_clamp_still_names_critical_organ():
    hl = {
        "selectivity_class": "selective_with_normal_liability",
        "driving_rule_id": "tvn-sc-normal-critical-organ-veto",
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
        "tphp_normal_liability_detail": "broad; highest in liver",
    }
    t = ts._selectivity_tension_extra(hl)
    assert t["source"] == "normal_liability_flag"
    assert t["severity"] == 3
    assert "kidney proximal tubule cell" in t["text"]
    # ANTI-VACUITY: this arm and the TPHP arm must produce DIFFERENT text off the SAME headline shape,
    # or branching on driving_rule_id would be doing nothing.
    tphp = ts._selectivity_tension_extra({**hl, "driving_rule_id": _TPHP_DRIVER})
    assert tphp["text"] != t["text"]
    assert tphp["source"] != t["source"]


def test_absent_driving_rule_falls_through_to_sc_normal_framing():
    # A pre-PR-G headline (no driving_rule_id) must behave exactly as before: sc-normal framing.
    hl = {
        "selectivity_class": "selective_with_normal_liability",
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
    }
    t = ts._selectivity_tension_extra(hl)
    assert t["source"] == "normal_liability_flag"
    assert "kidney proximal tubule cell" in t["text"]


# ── TPHP UNASSESSED tension: absent normal-protein coverage is not a clean pass ───────────────────


def test_tphp_unassessed_fires_on_clean_selective_call_with_no_tphp_data():
    hl = {
        "selectivity_class": "strong_tumor_selective",
        "sc_normal_safety_essential_class": "none",  # sc-normal MEASURED clean → its UNASSESSED is silent
        "sc_normal_liability_detail": None,
        "tphp_normal_protein_liability_class": "data_unavailable",
    }
    t = ts._selectivity_tension_extra(hl)
    assert t is not None and t["source"] == "tphp_normal_unassessed"
    assert "UNASSESSED" in t["text"] and t["severity"] == 2


def test_sc_normal_gap_ranks_ahead_of_tphp_gap_first_match_wins():
    # BOTH arms unassessed on a clean selective call → the sc-normal single-cell gap takes the one slot.
    hl = {
        "selectivity_class": "strong_tumor_selective",
        "sc_normal_safety_essential_class": "data_unavailable",
        "sc_normal_liability_detail": None,
        "tphp_normal_protein_liability_class": "data_unavailable",
    }
    t = ts._selectivity_tension_extra(hl)
    assert t["source"] == "sc_normal_unassessed"


def test_tphp_unassessed_silent_when_tphp_measured():
    hl = {
        "selectivity_class": "strong_tumor_selective",
        "sc_normal_safety_essential_class": "none",
        "sc_normal_liability_detail": None,
        "tphp_normal_protein_liability_class": "restricted",  # measured, clean
    }
    assert ts._selectivity_tension_extra(hl) is None


def test_tphp_unassessed_silent_when_a_veto_won_the_label():
    # A downgraded call is not axis-A selective, so the TPHP UNASSESSED analogue must not fire.
    hl = {
        "selectivity_class": "selective_but_broadly_normal",
        "sc_normal_safety_essential_class": "none",
        "sc_normal_liability_detail": None,
        "tphp_normal_protein_liability_class": "data_unavailable",
    }
    t = ts._selectivity_tension_extra(hl)
    assert t["source"] == "normal_breadth_veto"  # the KILL owns the slot, not the TPHP gap


# ── subtype→pooled reconciliation (pure) ──────────────────────────────────────────────────────────


def _row(sid, cls, state="measured", frac=0.6):
    return {
        "stratum_id": sid,
        "percentile_crossing_class": cls,
        "evidence_state": state,
        "fraction_tumor_above_normal_p95": frac,
    }


def _measured(per_subgroup):
    return [
        r
        for r in per_subgroup
        if r.get("evidence_state") == "measured" and r.get("fraction_tumor_above_normal_p95") is not None
    ]


def test_reconcile_flags_only_measured_strata_that_diverge():
    per = [
        _row("MSI_H", "strongly_tumor_enriched"),  # diverges from pooled enriched_subset
        _row("MSS", "enriched_subset"),  # agrees with pooled
        _row("POLE", "data_unavailable", state="underpowered", frac=None),  # underpowered — never diverges
        _row("EBV", "not_enriched", state="absent", frac=None),  # absent — never diverges
    ]
    out = ts._reconcile_subtype_crossing(per, _measured(per), pooled_crossing_class="enriched_subset")
    assert out["pooled_percentile_crossing_class"] == "enriched_subset"
    assert out["strata_diverging_from_pooled"] == ["MSI_H"]
    assert out["n_strata_diverging_from_pooled"] == 1
    # POWER accounting: 4 requested, 1 underpowered, 1 absent
    assert out["n_strata_requested"] == 4
    assert out["n_strata_underpowered"] == 1
    assert out["n_strata_absent"] == 1


def test_reconcile_underpowered_stratum_does_not_count_as_divergence():
    # ANTI-VACUITY / the power==divergence-filter identity: a stratum that would be a DIFFERENT class is
    # underpowered (data_unavailable), so it must NOT appear in strata_diverging even though its class
    # token differs from the pooled call.
    per = [_row("MSI_H", "data_unavailable", state="underpowered", frac=None)]
    out = ts._reconcile_subtype_crossing(per, _measured(per), pooled_crossing_class="enriched_subset")
    assert out["strata_diverging_from_pooled"] == []
    assert out["n_strata_underpowered"] == 1


def test_reconcile_no_divergence_when_all_measured_agree():
    per = [_row("MSI_H", "enriched_subset"), _row("MSS", "enriched_subset")]
    out = ts._reconcile_subtype_crossing(per, _measured(per), pooled_crossing_class="enriched_subset")
    assert out["strata_diverging_from_pooled"] == []
    assert out["n_strata_diverging_from_pooled"] == 0
    assert out["n_strata_underpowered"] == 0 and out["n_strata_absent"] == 0
