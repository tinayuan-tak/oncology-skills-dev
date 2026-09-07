"""topology_predictions_tmbed — ecd_engineerability_class derivation (pure, no S3, dict fixtures).

The engineerable-ECD categorical (biologics-augment Phase 3.1) makes the extracellular-domain
SIZE a first-class biologics-substrate signal, derived from fields TMbed already produces
(extracellular_residue_count + topology_class + ecd_orientation). Truth table + the
measured-vs-data_unavailable discipline are pinned here.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.topology_predictions_tmbed.classify import (  # noqa: E402
    classify_ecd_engineerability,
    compute_summary,
    ECD_ENGINEERABLE_FLOOR,
    ECD_AMPLE_EPITOPE_AREA,
)


def _e(topology_class, ecd_len, orient="outside") -> str:
    return classify_ecd_engineerability(topology_class, ecd_len, orient)


# ── the size ladder (outside-facing, membrane-anchored) ──────────────────────
def test_large_ecd_ample_epitope_area():
    # >= 200 AA — ample area for both ADC epitope + TCE binder
    assert _e("single_pass_type_1", 300) == "large_ecd"
    assert _e("single_pass_type_1", ECD_AMPLE_EPITOPE_AREA) == "large_ecd"  # boundary inclusive


def test_moderate_ecd_engineerable_but_constrained():
    # 30..199 AA — engineerable (TCE-viable) but epitope-area-constrained for ADC
    assert _e("single_pass_type_2", 120) == "moderate_ecd"
    assert _e("single_pass_type_1", ECD_ENGINEERABLE_FLOOR) == "moderate_ecd"  # 30 inclusive
    assert _e("single_pass_type_1", ECD_AMPLE_EPITOPE_AREA - 1) == "moderate_ecd"  # 199 upper


def test_minimal_ecd_too_small_to_engineer():
    # < 30 AA — no bindable ectodomain regardless of surface residency
    assert _e("multi_pass", 12) == "minimal_ecd"
    assert _e("single_pass_type_1", ECD_ENGINEERABLE_FLOOR - 1) == "minimal_ecd"  # 29


# ── no-substrate cases ───────────────────────────────────────────────────────
def test_no_transmembrane_has_no_extracellular_domain():
    # secreted / intracellular — no membrane anchor to display an antigen
    assert _e("no_transmembrane", 500) == "no_extracellular_domain"


def test_inside_facing_ecd_is_no_extracellular_domain():
    # a long run that faces the cytoplasm is not an accessible extracellular target
    assert _e("single_pass_type_other", 400, orient="inside") == "no_extracellular_domain"
    assert _e("single_pass_type_other", 400, orient="unknown") == "no_extracellular_domain"


# ── measured-vs-data_unavailable discipline (mirrors the endocytosis-abstains doctrine) ──
def test_unmeasured_ecd_length_is_data_unavailable_not_zero():
    # None ECD length must NOT collapse to no_extracellular_domain (a measured-negative) —
    # it is a coverage gap → data_unavailable (abstain).
    assert _e("single_pass_type_1", None) == "data_unavailable"


def test_data_unavailable_topology_propagates():
    assert _e("data_unavailable", 300) == "data_unavailable"


# ── compute_summary integration: the field is emitted alongside topology_class ──
def _row(**kw):
    base = {
        "n_tm_alpha_helices": 1,
        "n_tm_beta_strands": 0,
        "signal_peptide": True,
        "ecd_orientation": "outside",
        "ecd_length": 250,
    }
    base.update(kw)
    return base


def test_compute_summary_emits_ecd_engineerability_class():
    s = compute_summary(_row(), ptm_fields={}, method_version="test")
    assert s["ecd_engineerability_class"] == "large_ecd"
    assert s["extracellular_residue_count"] == 250
    # topology_class still derived as before (no regression)
    assert s["topology_class"] == "single_pass_type_1"


def test_compute_summary_none_ecd_length_abstains():
    s = compute_summary(_row(ecd_length=None), ptm_fields={}, method_version="test")
    assert s["ecd_engineerability_class"] == "data_unavailable"


def test_compute_summary_multipass_small_loop_is_minimal():
    # multi-pass GPCR-like: many TM, tiny extracellular loop → minimal_ecd (the steric-constraint case)
    s = compute_summary(
        _row(n_tm_alpha_helices=7, ecd_length=18, signal_peptide=False), ptm_fields={}, method_version="test"
    )
    assert s["topology_class"] == "multi_pass"
    assert s["ecd_engineerability_class"] == "minimal_ecd"
