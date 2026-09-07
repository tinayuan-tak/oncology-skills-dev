"""Thread 4: genotype × PRISM DRUG-RESPONSE biomarker (the pharmacological half).

Pure-dict (no S3): synthetic drug-response (PRISM Log2AUC) + mutation bool vectors. Verifies the
classification directions (mutant more sensitive / resistant / not stratified / insufficient) and
that the drug-response classification-performance passes through from the shared primitive.
Lower Log2AUC = more drug-sensitive (same direction as lower Chronos = more dependent).
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

from methods.depmap_mutation_drug_response.cli import (  # noqa: E402
    compute_drug_response_stratification as C,
)


def _build(mut_log2auc, wt_log2auc):
    """N mutant lines at mut_log2auc, M WT at wt_log2auc (jittered). Returns dr/hot/dam dicts."""
    import random

    rng = random.Random(0)
    dr, hot, dam = {}, {}, {}
    i = 0
    for v in mut_log2auc:
        m = f"ACH-{i:05d}"
        dr[m] = v + rng.uniform(-0.02, 0.02)
        hot[m] = True
        dam[m] = True
        i += 1
    for v in wt_log2auc:
        m = f"ACH-{i:05d}"
        dr[m] = v + rng.uniform(-0.02, 0.02)
        hot[m] = False
        dam[m] = False
        i += 1
    return dr, hot, dam


def test_mutant_strongly_drug_sensitive():
    # mutant lines much more sensitive (Log2AUC ~ -0.6) vs WT near-flat (~ -0.02): delta <= -0.2.
    dr, hot, dam = _build([-0.6] * 30, [-0.02] * 200)
    r = C(dr, hot, dam, compound_records=[{"name": "VEMURAFENIB", "target_or_mechanism": "inhibitor of BRAF p.V600E"}])
    assert r["drug_response_stratification_class"] == "mutant_strongly_drug_sensitive"
    assert r["delta_log2auc_mut_vs_wt"] <= -0.2
    assert r["n_on_target_compounds"] == 1


def test_mutant_moderately_drug_sensitive():
    dr, hot, dam = _build([-0.15] * 30, [-0.02] * 200)
    r = C(dr, hot, dam)
    assert r["drug_response_stratification_class"] == "mutant_moderately_drug_sensitive"


def test_not_stratified_when_no_separation():
    dr, hot, dam = _build([-0.05] * 30, [-0.05] * 200)
    r = C(dr, hot, dam)
    assert r["drug_response_stratification_class"] == "not_drug_response_stratified"


def test_mutant_drug_resistant_reverse_direction():
    # mutant lines RESISTANT (near-flat) while WT sensitive → reverse (positive delta) → resistant.
    dr, hot, dam = _build([-0.02] * 30, [-0.6] * 200)
    r = C(dr, hot, dam)
    assert r["drug_response_stratification_class"] == "mutant_drug_resistant"
    assert r["delta_log2auc_mut_vs_wt"] > 0
    assert r["drug_response_mannwhitney_q_reverse"] < 0.05


def test_insufficient_when_too_few_mutant():
    dr, hot, dam = _build([-0.6] * 3, [-0.02] * 200)  # only 3 mutant (< 5)
    r = C(dr, hot, dam)
    assert r["drug_response_stratification_class"] == "insufficient_mutant_or_drug_data"


def test_drug_response_performance_passthrough():
    # drug-response classification performance rides along from the shared primitive.
    dr, hot, dam = _build([-0.9] * 30, [-0.02] * 200)  # mutant deep responders (Log2AUC <= -0.5)
    r = C(dr, hot, dam)
    assert r["drug_response_ppv"] is not None
    assert r["drug_response_ppv"] > 0.9  # nearly all mutant lines are deep responders
    assert r["drug_response_ppv_lift"] is not None
    assert r["drug_response_base_rate"] is not None


def test_compound_provenance_surfaced():
    dr, hot, dam = _build([-0.6] * 30, [-0.02] * 200)
    recs = [
        {"name": "VEMURAFENIB", "target_or_mechanism": "inhibitor of BRAF p.V600E"},
        {"name": "DABRAFENIB", "target_or_mechanism": "inhibitor of BRAF p.V600E"},
    ]
    r = C(dr, hot, dam, compound_records=recs)
    assert r["n_on_target_compounds"] == 2
    assert {c["name"] for c in r["on_target_compounds"]} == {"VEMURAFENIB", "DABRAFENIB"}
