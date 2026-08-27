"""Generic stratified sub-group derivation (first-class subtype, fleet engine). Per-stratum reads from
`tier: subtype` cards' per_subgroup_metrics, multiplicity-aware + power-gated. skipif target-contracts
absent (needs measurement_type/tier lookup)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.subgroup_derivation import derive_stratified  # noqa: E402


def _contracts_absent():
    root = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                               "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
    return not (root / "cards").is_dir()


# abundance ← tumor_expression_distribution; the tier:subtype card of that type is tumor-rna-distribution-by-subtype
_HIER = {"sub_groups": [{"id": "abundance",
                         "questions": [{"id": "x", "measurement_types": ["tumor_expression_distribution"]}]}]}


def _card(rows):
    return [{"card_id": "tumor-rna-distribution-by-subtype", "summary": {"per_subgroup_metrics": rows}}]


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")
def test_per_stratum_with_power_gate():
    rows = [
        {"stratum_id": "MSI_H", "tumor_expression_class": "broadly_high", "n_tumor_samples": 100, "evidence_state": "measured"},
        {"stratum_id": "MSS", "tumor_expression_class": "broadly_low", "n_tumor_samples": 100, "evidence_state": "measured"},
        {"stratum_id": "CIMP_low", "tumor_expression_class": "broadly_high", "n_tumor_samples": 10, "evidence_state": "measured"},
    ]
    out = derive_stratified(_HIER, _card(rows))
    assert "abundance" in out
    ab = out["abundance"]
    assert ab["MSI_H"]["signal"] == "strong" and ab["MSI_H"]["powered"] is True
    assert ab["MSI_H"]["certainty"] == "high"          # n=100, k=3 (<5) -> no haircut
    assert ab["MSS"]["signal"] == "weak"
    # underpowered stratum (n=10 < floor) -> power-gated to low, powered False
    assert ab["CIMP_low"]["powered"] is False and ab["CIMP_low"]["certainty"] == "low"
    assert ab["MSI_H"]["multiplicity_strata_tested"] == 3


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")
def test_multiplicity_haircut_when_many_strata():
    rows = [{"stratum_id": f"S{i}", "tumor_expression_class": "broadly_high", "n_tumor_samples": 100,
             "evidence_state": "measured"} for i in range(6)]      # k=6 >= 5
    out = derive_stratified(_HIER, _card(rows))
    # base high, 6 strata scanned -> 1-tier haircut -> moderate
    assert out["abundance"]["S0"]["certainty"] == "moderate"


def test_empty_when_no_subtype_cards():
    # a card with no subtype-tier / no per_subgroup_metrics -> no strata
    assert derive_stratified(_HIER, [{"card_id": "tumor-rna-distribution", "summary": {}}]) == {}
