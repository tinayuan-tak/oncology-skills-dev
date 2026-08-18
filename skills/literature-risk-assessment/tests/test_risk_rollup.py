"""risk_rollup [3A]: structure tests (no network / no Bedrock). Pin the CONTRACT, not the thresholds:
  - the SAFETY false-LOW fix (modality-conditioned conjunction, not on-target-only 1:1),
  - reproducible deterministic bin,
  - ESCALATE-ONLY: grounded findings attach but NEVER change the bin,
  - engine↔literature discordance propagates,
  - engine-blind dims (clinical/commercial).
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "risk_rollup.py"


def _load():
    spec = importlib.util.spec_from_file_location("risk_rollup", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rr = _load()


def _pkg(safety, cards):
    return {"synthesis": {"sub_verdicts": {"safety": {"verdict": safety}, "dependency": {"verdict": "lineage_selective"},
            "mechanism": {"verdict": "well_characterized"}, "surface_modality": {"verdict": "both_viable"},
            "selectivity": {"verdict": "modest_tumor_selective"}}},
            "cards": [{"card_id": k, "interpretation_call": v} for k, v in cards.items()]}


def test_safety_false_low_fixed_by_conjunction():
    # ADC, on-target-safety reads "tolerant"-grade, but a critical-organ normal-tissue liability exists.
    pkg = _pkg("wt_human_genetics_mechanism_mismatch",
               {"normal-tissue-liability-gtex": "critical_organ_liability",
                "sc-normal-celltype-expression": "HIGH_LIABILITY"})
    dims = rr.project(pkg, "adc")
    assert dims["safety"]["bin"] == "HIGH", dims["safety"]   # NOT the false-LOW the 1:1 mapping gives


def test_deterministic_bin_is_reproducible():
    pkg = _pkg("wt_human_genetics_mechanism_mismatch", {"normal-tissue-liability-gtex": "critical_organ_liability"})
    a = rr.project(pkg, "adc")["safety"]["bin"]
    b = rr.project(pkg, "adc")["safety"]["bin"]
    assert a == b       # pure function of the package


def test_grounded_findings_escalate_only_never_change_bin():
    pkg = _pkg("wt_human_genetics_mechanism_mismatch", {"normal-tissue-liability-gtex": "critical_organ_liability"})
    bin_no_sub = rr.project(pkg, "adc")["safety"]["bin"]
    substrate = {"safety": {"grounded": {"findings": [{"finding": "ocular tox", "kind": "eye", "cited_pmids": ["1"]}],
                            "contradicts_deterministic": True}}}
    out = rr.project(pkg, "adc", substrate)["safety"]
    assert out["bin"] == bin_no_sub                         # findings do NOT move the bin
    assert out["grounded_findings"][0]["finding"] == "ocular tox"
    assert out["engine_literature_discordance"] is True      # discordance flag propagates


def test_engine_blind_dims_present():
    dims = rr.project(_pkg("tolerant_reduced_safety_risk", {}), "small_molecule")
    assert dims["clinical"]["bin"] == "ENGINE-BLIND" and dims["commercial"]["bin"] == "ENGINE-BLIND"


def test_tolerates_both_substrate_field_names():
    pkg = _pkg("tolerant_reduced_safety_risk", {})
    # old #490 shape (liability_findings) still attaches
    sub = {"safety": {"grounded": {"liability_findings": [{"liability": "x", "cited_pmids": []}]}}}
    assert rr.project(pkg, "adc", sub)["safety"]["grounded_findings"]
