"""2026-08-08 review fix: bimodal_selective must be gated on GENUINE bimodality (Sarle's coefficient),
not the former `median_chronos_panel > -0.5` scalar proxy.

Why it matters: distribution_shape == 'bimodal_selective' is the SOLE gate on dependency_class ==
'strongly_selective', which fires the dominant `strongly-selective-supportive` rule → resolver verdict
`selective_dependent`. The old proxy called a heavy-left-tailed UNIMODAL distribution (median just
above -0.5) bimodal_selective → a false dominant positive dependency call; and demoted a genuinely
bimodal target whose off-mode dragged the median just below -0.5. BC gates on real modality.

The Hartigan dip test was evaluated and REJECTED (too conservative on continuous heavy-tailed
dependency vectors — fails to reject unimodality even for KRAS). BC flags KRAS/EGFR, rejects impostors.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

CLI = Path(__file__).resolve().parent.parent / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("chr_dist_bc", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_dist_bc"] = m
    spec.loader.exec_module(m)
    return m


m = _load()


def _summary(scores):
    return m.compute_summary_stats({f"ACH-{i}": float(v) for i, v in enumerate(scores)}, {})


def test_bimodality_coefficient_normal_is_unimodal():
    rng = np.random.default_rng(1)
    bc = m._bimodality_coefficient(rng.normal(0, 1, 500))
    assert bc is not None and bc < m.BIMODALITY_COEFFICIENT_THRESHOLD  # normal ≈ 0.33


def test_bimodality_coefficient_two_modes_is_bimodal():
    rng = np.random.default_rng(2)
    x = np.concatenate([rng.normal(-1.4, 0.2, 200), rng.normal(-0.1, 0.2, 300)])
    bc = m._bimodality_coefficient(x)
    assert bc is not None and bc > m.BIMODALITY_COEFFICIENT_THRESHOLD


def test_bimodality_coefficient_none_below_n4():
    assert m._bimodality_coefficient([1.0, 2.0, 3.0]) is None


def test_unimodal_heavy_tail_is_not_bimodal_selective():
    """The OLD-bug case: unimodal, median just above -0.5, ~18% below -1 (in the selective band by
    tail fraction). Old proxy → bimodal_selective (false dominant selective_dependent). Now: NOT."""
    rng = np.random.default_rng(0)
    s = _summary(rng.normal(-0.45, 0.6, 600))
    assert s["distribution_shape"] != "bimodal_selective"


def test_genuine_bimodal_mixture_is_bimodal_selective():
    """A separated dependent lower mode in the selective band must still be bimodal_selective
    (preserves the true-positive selective call — e.g. KRAS-like shape)."""
    rng = np.random.default_rng(3)
    x = np.concatenate([rng.normal(-1.4, 0.2, 120), rng.normal(-0.1, 0.2, 480)])
    s = _summary(x)
    assert s["distribution_shape"] == "bimodal_selective"
    assert s["dependency_class"] == "strongly_selective" if "dependency_class" in s else True


def test_bimodality_coefficient_emitted_in_summary():
    """The coefficient is surfaced for audit/display alongside the shape call."""
    rng = np.random.default_rng(4)
    s = _summary(rng.normal(-0.2, 0.5, 300))
    assert "bimodality_coefficient" in s
