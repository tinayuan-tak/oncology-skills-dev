"""Hermetic tests for run_known_target_panel._capture_by_family — the per-family coverage map.

Runs via: pixi run pytest eval/tests/test_known_target_panel_capture.py -q   (from the home checkout).

Regression guard for Step 2 fix (2): the map USED to also credit "the live run now evidences this
family" via a field `live_any_captured`, computed by OR-ing the emitted `deciding_axis_capture` bands
into the curated family. Those bands are keyed by FRAMEWORK axis shorts (surface_modality,
genomic_alteration, …) — a different vocabulary from the curated deciding axis
(E2_density_threshold_same_organ_normal, …) with no sound crosswalk — so a captured axis UNRELATED to
the family (e.g. genomic_alteration) counted as "this family captured live". The reframe removes the
live join entirely and reports only the hand-curated coverage distribution per family.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import run_known_target_panel as panel  # noqa: E402

SURF = "surface_antigen_biology (density/topology/avidity)"
LANE = "captured_lane (mutation/pocket)"


def _row(fam, coverage, capture):
    """A scored row as score_profile emits it, trimmed to the keys _capture_by_family reads."""
    return {
        "deciding_axis_family": fam,
        "curated_coverage": coverage,
        "signal_vector": {"deciding_axis_capture": capture},
    }


def test_no_live_capture_credit_field_survives():
    # The defect: a curated-BLIND family got live-captured credit because an UNRELATED framework axis
    # (genomic_alteration) was captured. After the reframe the family carries NO live-capture field —
    # only the curated truth, which is: one blind target.
    rows = [_row(SURF, "blind", {"genomic_alteration": "captured", "surface_modality": "partial"})]
    entry = panel._capture_by_family(rows)[SURF]
    assert "live_any_captured" not in entry
    assert "live_any_partial_or_captured" not in entry
    assert "curated_blind" not in entry
    assert entry == {"n": 1, "curated_coverage": {"blind": 1}}


def test_a_captured_unrelated_axis_never_moves_a_blind_family():
    # Anti-vacuity: even if the framework captures EVERY axis in the vector, a curated-blind family
    # stays blind — because the metric no longer reads the framework capture map at all. Under the old
    # logic this row would have set live_any_captured=1; the assertion below would then fail.
    rows = [_row(SURF, "blind", {"a": "captured", "b": "captured", "c": "captured"})]
    assert panel._capture_by_family(rows)[SURF]["curated_coverage"] == {"blind": 1}


def test_curated_coverage_distribution_sums_to_n():
    rows = [
        _row(SURF, "blind", {"genomic_alteration": "captured"}),
        _row(SURF, "captured", {"surface_modality": "captured"}),
        _row(SURF, "partial", {}),
        _row(LANE, "blind", {"genomic_alteration": "captured"}),
    ]
    cbf = panel._capture_by_family(rows)
    assert cbf[SURF]["n"] == 3
    assert sum(cbf[SURF]["curated_coverage"].values()) == 3
    assert cbf[SURF]["curated_coverage"] == {"blind": 1, "captured": 1, "partial": 1}
    assert cbf[LANE]["curated_coverage"] == {"blind": 1}


def test_families_sorted_most_curated_blind_first():
    # blind/license_blocked/out_of_scope all count toward the fidelity-gap ordering.
    rows = [
        _row(LANE, "captured", {}),
        _row(SURF, "out_of_scope", {}),
        _row(SURF, "blind", {}),
    ]
    cbf = panel._capture_by_family(rows)
    assert list(cbf.keys())[0] == SURF  # 2 curated-blind-ish > 0


def test_rows_without_a_signal_vector_are_skipped():
    # n must match the live-scored denominator, so an unscored row (no vector) contributes nothing.
    rows = [{"deciding_axis_family": SURF, "curated_coverage": "blind"}]
    assert panel._capture_by_family(rows) == {}


def test_missing_family_and_band_fall_back_without_crashing():
    rows = [_row(None, None, {})]
    cbf = panel._capture_by_family(rows)
    assert cbf == {"unclassified": {"n": 1, "curated_coverage": {"unknown": 1}}}
