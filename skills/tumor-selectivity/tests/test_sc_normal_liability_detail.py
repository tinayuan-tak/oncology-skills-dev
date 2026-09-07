"""W1c: the sc-normal named-organ liability is de-anonymized into the headline/tension.

The safety-essential veto used to surface an anonymous flag; analysis-methods #572 emits the NAMED
essential-cell driver, and run.py now builds a masking-safe `sc_normal_liability_detail` string and
interpolates it into the tension text — including the case where a coarser window KILL wins the
verdict LABEL but the sc-normal arm ALSO flagged a named critical organ (the masking fix)."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

ts = load_run_py(Path(__file__).resolve().parent.parent, "ts_run_w1c")


def _sc(cls, cell="kidney proximal tubule cell", tissue="kidney", n_atlas=3):
    return {
        "sc_normal_safety_essential_class": cls,
        "sc_normal_essential_max_cell_type": cell,
        "sc_normal_essential_max_tissue": tissue,
        "sc_normal_essential_n_datasets_reliable": n_atlas,
    }


def test_liability_detail_names_organ_cell_and_atlases():
    d = ts._sc_normal_liability_detail(_sc("critical_organ_liability"))
    assert d == "kidney kidney proximal tubule cell (3 atlases)"


def test_liability_detail_origin_tissue_also_named():
    d = ts._sc_normal_liability_detail(_sc("origin_tissue_liability", cell="pneumocyte", tissue="lung", n_atlas=1))
    assert d == "lung pneumocyte (1 atlas)"


def test_liability_detail_none_when_no_essential_hit():
    assert ts._sc_normal_liability_detail(_sc("none")) is None
    assert ts._sc_normal_liability_detail(_sc("data_unavailable")) is None
    assert (
        ts._sc_normal_liability_detail(
            {"sc_normal_safety_essential_class": "critical_organ_liability", "sc_normal_essential_max_cell_type": None}
        )
        is None
    )
    assert ts._sc_normal_liability_detail({}) is None


def test_tension_names_organ_for_preserving_liability():
    hl = {
        "selectivity_class": "selective_with_normal_liability",
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
    }
    t = ts._selectivity_tension_extra(hl)
    assert "kidney proximal tubule cell" in t["text"]
    assert t["severity"] == 3


def test_masking_fix_surfaces_named_liability_under_window_kill():
    """When the window KILL wins the label, a co-fired sc-normal named liability is NOT discarded."""
    hl = {
        "selectivity_class": "selective_but_broadly_normal",
        "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)",
    }
    t = ts._selectivity_tension_extra(hl)
    assert "also flags a critical-organ single-cell liability" in t["text"]
    assert "kidney proximal tubule cell" in t["text"]
    assert t["severity"] == 4  # the KILL still owns the slot


def test_masking_fix_noop_when_no_sc_normal_liability():
    hl = {"selectivity_class": "selective_but_broadly_normal", "sc_normal_liability_detail": None}
    t = ts._selectivity_tension_extra(hl)
    assert "also flags" not in t["text"]


# ── W3c: severity grade + data_unavailable "unknown-mass" caveat ────────────────────────────────


def _scg(cls, det, frac, n_ds, cell="type B pancreatic cell", tissue="pancreas"):
    return {
        "sc_normal_safety_essential_class": cls,
        "sc_normal_essential_max_cell_type": cell,
        "sc_normal_essential_max_tissue": tissue,
        "sc_normal_essential_n_datasets_reliable": n_ds,
        "sc_normal_essential_max_detection_fraction": det,
        "sc_normal_essential_donor_fraction": frac,
    }


def test_severity_grades_by_magnitude_consistency_replication():
    # robust: high detection + consistent + multi-atlas (INS β-cell 1.0 / 11 atlases class)
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 1.0, 0.98, 11)) == "high_severity"
    # marginal: single-atlas → low regardless of detection
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.85, 0.9, 1)) == "low_severity"
    # marginal: sub-0.30 detection → low
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.22, 0.8, 4)) == "low_severity"
    # in-between → moderate (e.g. det 0.41 pneumocyte, replicated)
    assert ts._sc_normal_essential_severity(_scg("critical_organ_liability", 0.41, 0.75, 3)) == "moderate_severity"
    # no essential hit / no magnitude field → None (cannot grade, do not guess)
    assert ts._sc_normal_essential_severity(_sc("none")) is None
    assert ts._sc_normal_essential_severity(_sc("critical_organ_liability")) is None  # no det field


def test_liability_detail_appends_severity_when_graded():
    d = ts._sc_normal_liability_detail(_scg("critical_organ_liability", 1.0, 0.98, 11))
    assert d == "pancreas type B pancreatic cell (11 atlases, high-severity)"
    # single-atlas → low-severity, atlas count still shown
    d2 = ts._sc_normal_liability_detail(
        _scg("critical_organ_liability", 0.85, 0.9, 1, cell="acinar cell", tissue="lung")
    )
    assert d2 == "lung acinar cell (1 atlas, low-severity)"


def test_unassessed_caveat_fires_on_selective_call_with_no_sc_normal_data():
    hl = {
        "selectivity_class": "strong_tumor_selective",
        "sc_normal_safety_essential_class": "data_unavailable",
        "sc_normal_liability_detail": None,
    }
    t = ts._selectivity_tension_extra(hl)
    assert t is not None and t["source"] == "sc_normal_unassessed"
    assert "UNASSESSED" in t["text"] and t["severity"] == 2


def test_unassessed_caveat_silent_when_sc_normal_measured_or_veto_won():
    # sc-normal measured (none) → no unassessed caveat, clean selective call has no tension
    assert (
        ts._selectivity_tension_extra(
            {
                "selectivity_class": "strong_tumor_selective",
                "sc_normal_safety_essential_class": "none",
                "sc_normal_liability_detail": None,
            }
        )
        is None
    )
    # a veto already downgraded → the veto tension owns the slot, not the unassessed caveat
    t = ts._selectivity_tension_extra(
        {
            "selectivity_class": "selective_but_broadly_normal",
            "sc_normal_safety_essential_class": "data_unavailable",
            "sc_normal_liability_detail": None,
        }
    )
    assert t["source"] == "normal_breadth_veto"
