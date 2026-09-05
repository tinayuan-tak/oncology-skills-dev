"""Signals-first rollout for surface-modality-fit: narrator LEADS with the signal vector (verdict
demoted to a compressed label) + strength_certainty emits a composite. Verdict-INERT."""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py


def _sm():
    return load_run_py(Path(__file__).resolve().parents[1], "sm_run")


def _decision():
    return {"target": "FOLR1", "indication": "OV", "cards": [],
            "headline": {"surface_modality_verdict": "ADC_preferred", "fit_class": "ADC_preferred",
                         "driving_rule_id": "rid",
                         "claim_vector": {
                             "TOPOLOGY": {"signal": "strong", "corroboration": "high", "evidence": "type-I"},
                             "SAFETY": {"signal": "moderate", "corroboration": "moderate", "evidence": "ok"}}}}


def test_composite_in_strength_certainty():
    sm = _sm()
    sc = sm._strength_certainty([], verdict_pair=("ADC_preferred", None))
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc
