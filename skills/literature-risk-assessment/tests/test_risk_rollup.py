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


def test_pseudo_card_dims_get_coarse_literature_bin():
    pkg = _pkg("tolerant_reduced_safety_risk", {})
    # no substrate -> engine-blind
    assert rr.project(pkg, "adc")["clinical"]["bin"] == "ENGINE-BLIND"
    # a failed-trial finding escalates the clinical pseudo-card to HIGH (literature-only)
    sub = {"clinical": {"grounded": {"findings": [{"finding": "Ph3 failed", "kind": "failed_trial", "cited_pmids": ["1"]}]}}}
    out = rr.project(pkg, "adc", sub)["clinical"]
    assert out["bin"] == "HIGH" and out["bin_basis"] == "literature-only (uncalibrated)"
    # a benign finding -> MED; no findings -> LOW
    sub2 = {"commercial": {"grounded": {"findings": [{"finding": "some context", "kind": "context", "cited_pmids": []}]}}}
    assert rr.project(pkg, "adc", sub2)["commercial"]["bin"] == "MED"


def test_pan_essential_is_MED_biological_not_high():
    # pan_essential = a dependency but not tumor-selective -> MED biological (tox routes to safety), NOT HIGH
    pkg = {"synthesis": {"sub_verdicts": {"safety": {"verdict": "tolerant_reduced_safety_risk"},
            "dependency": {"verdict": "pan_essential_killer"}, "mechanism": {"verdict": "well_characterized"}}},
           "cards": []}
    assert rr.deterministic_bins(pkg, "small_molecule")["biological"]["bin"] == "MED"
    # non_dependent is the HIGH biological case
    pkg["synthesis"]["sub_verdicts"]["dependency"]["verdict"] = "non_dependent"
    assert rr.deterministic_bins(pkg, "small_molecule")["biological"]["bin"] == "HIGH"


def test_calibration_surfaces_raw_anchoring_quantities():
    pkg = {"synthesis": {"sub_verdicts": {"safety": {"verdict": "highly_constrained_safety_concern"},
            "dependency": {"verdict": "lineage_selective"}, "mechanism": {"verdict": "well_characterized"},
            "tractability_sm": {"verdict": "well_covered"}}},
           "cards": [{"card_id": "gnomad-lof-constraint", "summary": {"loeuf_score": 0.23}},
                     {"card_id": "target-development-level", "summary": {"tdl_class": "Tclin"}}]}
    dims = rr.deterministic_bins(pkg, "small_molecule")
    assert any("LOEUF=0.23" in str(n[1]) for n in dims["safety"]["chain"])       # raw LOEUF surfaced
    assert any("Pharos TDL=Tclin" in str(n[1]) for n in dims["druggability"]["chain"])  # raw TDL surfaced
