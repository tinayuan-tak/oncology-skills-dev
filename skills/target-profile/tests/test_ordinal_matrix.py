"""target-profile ordinal-matrix helper tests (gap #3/#4, 2026-07-20).

Pins the gate × modality extraction that feeds the ordinal evidence-matrix VIEW: the strongest
(most-decisive) signal wins a cell, a co-fired killer dominates a co-fired supportive, off-scale
signals only surface when no on-scale signal exists, and the matrix carries the disclaimer +
never a verdict. (The scale semantics themselves are tested in _skills_common/test_ordinal_view.)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _fired(*signal_maps):
    return [{"rule_id": f"r{i}", "signals": s} for i, s in enumerate(signal_maps)]


def test_killer_dominates_supportive_in_a_cell():
    """When one rule emits small_molecule:supportive and another small_molecule:killer, the
    cell shows the killer (most-negative) — the display convention that a killer dominates."""
    got = tp._strongest_signal_for_modality(
        _fired({"small_molecule": "supportive"}, {"small_molecule": "killer"}),
        "small_molecule")
    assert got == "killer"


def test_offscale_only_when_no_onscale():
    """insufficient is returned ONLY if no on-scale signal was emitted for that modality — an
    on-scale signal always wins over a coverage gap."""
    assert tp._strongest_signal_for_modality(
        _fired({"degrader": "insufficient"}, {"degrader": "supportive"}), "degrader") == "supportive"
    assert tp._strongest_signal_for_modality(
        _fired({"degrader": "insufficient"}), "degrader") == "insufficient"
    # a modality no rule mentions → None (empty cell)
    assert tp._strongest_signal_for_modality(_fired({"small_molecule": "supportive"}), "adc") is None


def test_matrix_shape_and_disclaimer():
    sub_results = {
        "dependency": {"skill_dir": "functional-requirement",
                       "verdict": ("lineage_selective", "lineage-selective-supportive"),
                       "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"})},
        "surface_modality": {"skill_dir": "surface-modality-fit",
                             "verdict": ("neither_viable", "x"),
                             "fired": _fired({"adc": "killer", "bite_tce": "killer"})},
    }
    mx = tp._ordinal_matrix(sub_results)
    assert mx["_disclaimer"] and "NOT calibrated" in mx["_disclaimer"]
    assert mx["axes"]["columns"] == ["small_molecule", "degrader", "adc", "bite_tce", "antibody"]
    rows = {r["short"]: r for r in mx["rows"]}
    # dependency: SM opposing (-1), degrader supportive (+2) — the degrader-preferred split
    assert rows["dependency"]["cells"]["small_molecule"]["ordinal"] == -1
    assert rows["dependency"]["cells"]["degrader"]["ordinal"] == 2
    # surface_modality: adc/bite_tce killer (-3); antibody empty (·)
    assert rows["surface_modality"]["cells"]["adc"]["ordinal"] == -3
    assert rows["surface_modality"]["cells"]["antibody"]["signal"] is None
    # the matrix carries the verdict for context but the cell is NOT the verdict
    assert rows["dependency"]["verdict"] == "lineage_selective"


def test_render_matrix_md_is_labeled_and_tabular():
    sub_results = {
        "dependency": {"skill_dir": "functional-requirement", "verdict": ("lineage_selective", "x"),
                       "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"})},
    }
    from _skills_common import ordinal_view
    md = ordinal_view.render_matrix_md(tp._ordinal_matrix(sub_results), "KRAS", "COADREAD")
    assert "Ordinal evidence matrix — KRAS × COADREAD" in md
    assert "NOT calibrated measurement" in md
    assert "| gate (sub-skill) |" in md
    assert "Why a cell can differ from the verdict" in md
