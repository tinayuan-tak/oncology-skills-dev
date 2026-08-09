"""T2.1 hotspot-gate: a directional oncogene-addiction call (mutant_strongly/moderately_dependent)
may be set ONLY from the hotspot (activating) tier. The damaging/'any' pool (activating+LoF+VUS)
cannot MANUFACTURE oncogene-addiction on its own — the biologically-unsound pooled-tier call the
genomic-alteration review flagged.

Pure-dict (no S3): construct chronos + hotspot/damaging bool dicts so the hotspot tier is
underpowered (< min_mutant) while the damaging tier shows a strong directional signal.
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

from methods.depmap_mutation_dependency.cli import compute_mutation_stratification as C  # noqa: E402


def _dicts(n_hot_mut, n_dam_mut, n_wt, mut_chronos, wt_chronos):
    """Build chronos + hotspot + damaging bool dicts. First n_hot_mut lines are hotspot-mutant,
    next n_dam_mut are damaging-only-mutant, rest are WT. Mutant lines get mut_chronos, WT get wt."""
    import random
    rng = random.Random(0)
    chronos, hot, dam = {}, {}, {}
    i = 0
    for _ in range(n_hot_mut):
        m = f"ACH-{i:05d}"; chronos[m] = mut_chronos + rng.uniform(-0.1, 0.1); hot[m] = True; dam[m] = True; i += 1
    for _ in range(n_dam_mut):
        m = f"ACH-{i:05d}"; chronos[m] = mut_chronos + rng.uniform(-0.1, 0.1); hot[m] = False; dam[m] = True; i += 1
    for _ in range(n_wt):
        m = f"ACH-{i:05d}"; chronos[m] = wt_chronos + rng.uniform(-0.1, 0.1); hot[m] = False; dam[m] = False; i += 1
    return chronos, hot, dam


def test_pooled_tier_alone_does_not_confer_oncogene_addiction():
    # hotspot underpowered (3 < min 5); damaging tier has 40 mutants strongly dependent → the OLD
    # behavior would fall through to damaging → mutant_strongly_dependent. T2.1: NOT credited.
    chronos, hot, dam = _dicts(n_hot_mut=3, n_dam_mut=40, n_wt=300,
                               mut_chronos=-1.2, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "not_mutation_stratified"
    assert r["hotspot_gate_note"] is not None and "pooled-tier" in r["hotspot_gate_note"]


def test_hotspot_tier_still_confers_when_powered():
    # hotspot tier well-powered + strong → mutant_strongly_dependent (unchanged; the gate only blocks
    # POOLED-only calls). Note is None.
    chronos, hot, dam = _dicts(n_hot_mut=40, n_dam_mut=0, n_wt=300,
                               mut_chronos=-1.3, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "mutant_strongly_dependent"
    assert r["hotspot_gate_note"] is None


def test_no_signal_anywhere_is_not_stratified():
    chronos, hot, dam = _dicts(n_hot_mut=10, n_dam_mut=20, n_wt=300,
                               mut_chronos=-0.05, wt_chronos=-0.05)
    r = C(chronos, hot, dam)
    assert r["mutation_stratification_class"] == "not_mutation_stratified"
    assert r["hotspot_gate_note"] is None            # no directional pooled call to suppress
