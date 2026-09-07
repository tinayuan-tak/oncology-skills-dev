"""Signals-first rollout for genomic-alteration-profile: narrator LEADS with the signal vector
(verdict demoted to a compressed label) + strength_certainty emits a composite. Verdict-INERT."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py


def _decision():
    return {
        "target": "ERBB2",
        "indication": "STAD",
        "cards": [],
        "headline": {
            "genomic_alteration_profile": "amplification_driven",
            "driving_rule_id": "rid",
            "claim_vector": {
                "CN": {"signal": "strong", "corroboration": "high", "evidence": "focal amp"},
                "SNV": {"signal": "absent", "corroboration": "moderate", "evidence": "no recurrent"},
            },
        },
    }


def test_composite_in_strength_certainty():
    ga = load_run_py(Path(__file__).resolve().parent.parent, "ga_run")
    sc = ga._strength_certainty([], verdict_pair=("amplification_driven", None))
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc
