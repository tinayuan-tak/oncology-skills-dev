"""broad_dependency_band (skills #1794, 2026-09-28): SAFETY grading of the strongly-dependent
fraction, emitted alongside dependency_class.

The 0.60-0.85 strongly-dependent band classifies `broadly_dependent` (finding #2, 2026-08-13:
"a broad-toxicity liability nearly as severe as a common-essential") but the pan-essential
broad-tox SAFETY warning keys only on `common_essential` (>= 0.85 + curated anchor) — so a
genuine partial broad-tox band was INVISIBLE on the safety axis (read as clean). The band field
surfaces it as an explicit categorical the Tier-2 safety rules can grade
(`partial_broad_band` → target-contracts broad-dependency-partial-tox-safety-warning).

MUTATION TEETH: test_partial_broad_band_emitted RED-fails if the band emission is removed or if
the 0.60-0.85 population is folded back into a band value the safety rules do not grade.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "onc_methods" / "depmap_chronos_distribution" / "cli.py"
# cli.py itself does `from onc_methods.catalog_query.read import ...`, which resolves through the
# editable install from any cwd — so exec'ing it here no longer depends on what is on sys.path
# (that dependence is exactly what made a standalone collection order-dependent; skills#2237).


def _load():
    spec = importlib.util.spec_from_file_location("chr_cli_band", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_cli_band"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _summary(frac_strong: float, n: int = 1000, curated=None):
    """Synthetic panel with exactly frac_strong of n lines at Chronos -2.5 (strong), rest at +0.1."""
    k = round(frac_strong * n)
    scores = {f"ACH-{i:06d}": (-2.5 if i < k else 0.1) for i in range(n)}
    meta = {m: {"OncotreeLineage": "Bowel"} for m in scores}
    return cli.compute_summary_stats(scores, meta, curated_common_essential=curated)


def test_partial_broad_band_emitted():
    # THE #1794 BAND FIX (mutation teeth): a 0.60-0.85 strongly-dependent fraction surfaces as
    # partial_broad_band — the graded broad-tox liability the safety rules key on — while the
    # dependency_class stays broadly_dependent (the dependency-gate read is unchanged).
    s = _summary(0.70)
    assert s["broad_dependency_band"] == "partial_broad_band"
    assert s["dependency_class"] == "broadly_dependent"


def test_pan_essential_fraction_is_pan_essential_band():
    s = _summary(0.90, curated=True)
    assert s["broad_dependency_band"] == "pan_essential_band"
    assert s["dependency_class"] == "common_essential"


def test_below_band_for_selective_fraction():
    s = _summary(0.30)
    assert s["broad_dependency_band"] == "below_band"


def test_band_edges_mirror_the_classifier():
    # 0.60 exactly is INSIDE the classifier's selective band (<= selective_max) → below_band;
    # 0.85 exactly is the pan-essential floor (>= pan_essential_fraction) → pan_essential_band.
    assert _summary(0.60)["broad_dependency_band"] == "below_band"
    assert _summary(0.85, curated=True)["broad_dependency_band"] == "pan_essential_band"


def test_band_is_a_pure_fraction_banding_independent_of_anchor():
    # The band grades the MEASURED fraction; the curated anchor (and its absence) only moves
    # dependency_class. An unanchored >=85% call keeps its pan_essential_band read (the SAFETY
    # conservatism for the unanchored case rides on dependency_class == common_essential_unanchored).
    s = _summary(0.90, curated=None)
    assert s["broad_dependency_band"] == "pan_essential_band"
    assert s["dependency_class"] == "common_essential_unanchored"
    # ...and a curated-False context-essential keeps the band too (T3 deliberately clears the
    # dependency killer for it; the band field stays an honest record of the measured breadth).
    s2 = _summary(0.90, curated=False)
    assert s2["broad_dependency_band"] == "pan_essential_band"
    assert s2["dependency_class"] == "broadly_dependent"
