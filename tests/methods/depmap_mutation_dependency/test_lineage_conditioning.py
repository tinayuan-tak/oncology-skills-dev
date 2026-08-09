"""T2.0 lineage-conditioned mutation-stratified dependency.

Oncogenic hotspots are lineage-enriched, so a pan-DepMap mutant-vs-WT contrast can be
tissue-confounded. `compute_mutation_stratification_conditioned` runs the stratification
WITHIN the indication's DepMap lineage when powered, with a graceful-degradation ladder,
and records evidence_scope + lineage_context_divergent + the pan audit class.

Pure-dict (no S3): synthetic chronos + hotspot/damaging + model_metadata (OncotreeLineage).
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
    compute_mutation_stratification as C,
    compute_mutation_stratification_conditioned as CC,
)

# COADREAD → Bowel in the depmap_chronos single-source map.
IND = "COADREAD"
LIN = "Bowel"


def _build(n_lin_mut, n_lin_wt, n_off_mut, n_off_wt,
           lin_mut_chr, lin_wt_chr, off_mut_chr, off_wt_chr):
    """Build chronos/hotspot/damaging/metadata dicts across an in-lineage (Bowel) group and an
    off-lineage (Skin) group, each split mut/WT. Mutants are hotspot-mutant."""
    import random
    rng = random.Random(0)
    chronos, hot, dam, meta = {}, {}, {}, {}
    i = 0

    def add(n, chrval, is_mut, lineage):
        nonlocal i
        for _ in range(n):
            m = f"ACH-{i:05d}"
            chronos[m] = chrval + rng.uniform(-0.08, 0.08)
            hot[m] = is_mut
            dam[m] = is_mut
            meta[m] = {"OncotreeLineage": lineage}
            i += 1

    add(n_lin_mut, lin_mut_chr, True, LIN)
    add(n_lin_wt, lin_wt_chr, False, LIN)
    add(n_off_mut, off_mut_chr, True, "Skin")
    add(n_off_wt, off_wt_chr, False, "Skin")
    return chronos, hot, dam, meta


def test_no_context_is_byte_identical_to_pan():
    # No model_metadata / no indication → pan_no_indication, result equals the pan core verbatim
    # (minus the added provenance keys).
    chronos, hot, dam, _ = _build(40, 200, 40, 200, -1.2, -0.05, -1.2, -0.05)
    pan = C(chronos, hot, dam)
    cc = CC(chronos, hot, dam, model_metadata=None, indication=None)
    assert cc["evidence_scope"] == "pan_no_indication"
    assert cc["mutation_stratification_class"] == pan["mutation_stratification_class"]
    # every pan field preserved unchanged
    for k, v in pan.items():
        if k.startswith("_"):
            continue
        assert cc[k] == v, f"field {k} drifted from pan"


def test_within_indication_when_powered():
    # Bowel has 30 mutant + 100 WT (both powered), mutants strongly dependent in-lineage.
    chronos, hot, dam, meta = _build(30, 100, 20, 200, -1.2, -0.05, -0.05, -0.05)
    cc = CC(chronos, hot, dam, model_metadata=meta, indication=IND)
    assert cc["evidence_scope"] == "within_indication"
    assert cc["indication_lineage"] == LIN
    assert cc["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_within_indication_mut_vs_pan_wt_when_wt_underpowered():
    # Bowel has 8 mutant (powered) but only 10 WT (< 30) → broaden WT to pan comparator.
    chronos, hot, dam, meta = _build(8, 10, 5, 300, -1.3, -0.05, -0.05, -0.02)
    cc = CC(chronos, hot, dam, model_metadata=meta, indication=IND)
    assert cc["evidence_scope"] == "within_indication_mut_vs_pan_wt"
    assert cc["mutation_stratification_class"] in (
        "mutant_strongly_dependent", "mutant_moderately_dependent")


def test_pan_fallback_caps_strong_to_moderate_when_lineage_mut_underpowered():
    # Bowel has only 2 mutant (< 5) → pan_lineage_evidence_only. Pan signal is STRONG (driven by
    # off-lineage mutants) → must be CAPPED to moderate.
    chronos, hot, dam, meta = _build(2, 100, 60, 300, -1.3, -0.05, -1.3, -0.05)
    pan = C(chronos, hot, dam)
    assert pan["mutation_stratification_class"] == "mutant_strongly_dependent"  # precondition
    cc = CC(chronos, hot, dam, model_metadata=meta, indication=IND)
    assert cc["evidence_scope"] == "pan_lineage_evidence_only"
    assert cc["mutation_stratification_class"] == "mutant_moderately_dependent"
    assert cc.get("pan_fallback_strong_capped_to_moderate") is True
    assert cc["pan_lineage_mutation_stratification_class"] == "mutant_strongly_dependent"


def test_lineage_context_divergent_flag():
    # Pan says mutant-dependent (strong off-lineage mutant signal) but WITHIN Bowel the mutants are
    # NOT dependent (mutant ~ WT ~ 0) → within=not_stratified, pan=mutant_dependent. With Bowel
    # powered (30 mut/100 wt) scope=within_indication; divergence: within has no directional call
    # so divergent stays False (a null within-call is not a directional disagreement) — assert the
    # provenance is populated and pan audit retained.
    chronos, hot, dam, meta = _build(30, 100, 60, 300, -0.03, -0.05, -1.3, -0.05)
    cc = CC(chronos, hot, dam, model_metadata=meta, indication=IND)
    assert cc["evidence_scope"] == "within_indication"
    assert cc["mutation_stratification_class"] == "not_mutation_stratified"
    assert cc["pan_lineage_mutation_stratification_class"] == "mutant_strongly_dependent"
    # within has no directional call → not flagged divergent (conservative: only opposing directions flag)
    assert cc["lineage_context_divergent"] is False


def test_divergent_true_on_opposing_directions():
    # WITHIN Bowel: WT strongly dependent (reverse direction → wt_strongly_dependent).
    # PAN: mutant strongly dependent (off-lineage). Opposing directions → divergent True.
    chronos, hot, dam, meta = _build(30, 100, 200, 200, -0.05, -1.3, -1.3, -0.05)
    cc = CC(chronos, hot, dam, model_metadata=meta, indication=IND)
    assert cc["evidence_scope"] == "within_indication"
    assert cc["mutation_stratification_class"] == "wt_strongly_dependent"
    assert cc["pan_lineage_mutation_stratification_class"] in (
        "mutant_strongly_dependent", "mutant_moderately_dependent")
    assert cc["lineage_context_divergent"] is True


def test_unmapped_indication_is_pan_no_indication():
    chronos, hot, dam, meta = _build(30, 100, 20, 200, -1.2, -0.05, -0.05, -0.05)
    cc = CC(chronos, hot, dam, model_metadata=meta, indication="MADE_UP_INDICATION")
    assert cc["evidence_scope"] == "pan_no_indication"
