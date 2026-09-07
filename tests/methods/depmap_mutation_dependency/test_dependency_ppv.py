"""Thread 3: dependency-classification PERFORMANCE metrics.

Treats the biomarker (mutant = positive) as a classifier for the DepMap-dependency phenotype
(Chronos <= -0.5) and computes PPV / sensitivity / specificity / base-rate / PPV-lift. These are
DEPENDENCY performance metrics on the one ground truth the framework has (DepMap genetic
dependency) — NOT drug-response or clinical metrics. Verdict-inert (new fields; classifier unchanged).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_mutation_dependency.cli import (  # noqa: E402
    _mannwhitney_stratification,
    compute_mutation_stratification as C,
)


def _vec(mut_scores, wt_scores):
    chronos, mut = {}, {}
    i = 0
    for s in mut_scores:
        m = f"ACH-{i:05d}"
        chronos[m] = s
        mut[m] = True
        i += 1
    for s in wt_scores:
        m = f"ACH-{i:05d}"
        chronos[m] = s
        mut[m] = False
        i += 1
    return chronos, mut


def test_perfect_classifier_ppv_one_sensitivity_one():
    # 20 mutant all dependent (-1.0), 100 WT all non-dependent (0.0) → PPV=1, sens=1, spec=1.
    chronos, mut = _vec([-1.0] * 20, [0.0] * 100)
    r = _mannwhitney_stratification(chronos, mut)
    assert r["dependency_ppv"] == 1.0
    assert r["dependency_sensitivity"] == 1.0
    assert r["dependency_specificity"] == 1.0
    assert r["dependency_base_rate"] == pytest.approx(20 / 120)
    # lift = PPV / base_rate — a perfect specific biomarker lifts far above the prior
    assert r["dependency_ppv_lift"] == pytest.approx(1.0 / (20 / 120))


def test_ppv_below_one_with_false_positives():
    # 10 mutant: 6 dependent (-0.8), 4 not (-0.1). 90 WT non-dependent. PPV = 6/10 = 0.6.
    chronos, mut = _vec([-0.8] * 6 + [-0.1] * 4, [0.0] * 90)
    r = _mannwhitney_stratification(chronos, mut)
    assert r["dependency_ppv"] == pytest.approx(0.6)
    # sensitivity = 6 dependent-mut / 6 total-dependent = 1.0 (no dependent WT)
    assert r["dependency_sensitivity"] == pytest.approx(1.0)


def test_threshold_boundary_is_inclusive_at_minus_half():
    # exactly -0.5 counts as dependent (<=). 5 mutant at -0.5, 40 WT at 0.0.
    chronos, mut = _vec([-0.5] * 5, [0.0] * 40)
    r = _mannwhitney_stratification(chronos, mut)
    assert r["dependency_ppv"] == 1.0
    assert r["dependency_threshold"] == -0.5


def test_base_rate_and_lift_when_biomarker_uninformative():
    # mutant and WT both 30% dependent → biomarker adds nothing: PPV ~ base_rate, lift ~ 1.
    chronos, mut = _vec([-0.8] * 6 + [0.0] * 14, [-0.8] * 30 + [0.0] * 70)
    r = _mannwhitney_stratification(chronos, mut)
    assert r["dependency_ppv"] == pytest.approx(0.30, abs=0.01)
    assert r["dependency_base_rate"] == pytest.approx(36 / 120, abs=0.01)
    assert r["dependency_ppv_lift"] == pytest.approx(1.0, abs=0.05)


def test_surfaced_in_compute_summary_hotspot():
    # the summary lifts the hotspot-tier dependency performance fields.
    import random

    rng = random.Random(0)
    chronos, hot, dam = {}, {}, {}
    i = 0
    for _ in range(30):
        m = f"ACH-{i:05d}"
        chronos[m] = -1.1 + rng.uniform(-0.1, 0.1)
        hot[m] = True
        dam[m] = True
        i += 1
    for _ in range(200):
        m = f"ACH-{i:05d}"
        chronos[m] = -0.02 + rng.uniform(-0.1, 0.1)
        hot[m] = False
        dam[m] = False
        i += 1
    s = C(chronos, hot, dam)
    assert s["hotspot_dependency_ppv"] is not None
    assert s["hotspot_dependency_ppv"] > 0.9  # mutants deeply dependent
    assert s["hotspot_dependency_base_rate"] is not None
    assert s["hotspot_dependency_ppv_lift"] > 1.0  # informative biomarker
