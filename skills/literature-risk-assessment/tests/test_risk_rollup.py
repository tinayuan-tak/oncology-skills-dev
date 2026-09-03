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


def test_new_target_biology_axes_fold_into_biological_dim():
    # ROLLOUT 2026-08-18: mechanism/genomic/SL/combinatorial/expression grounded findings escalate the
    # BIOLOGICAL (Right Target) dim; the bin stays deterministic (escalate-only).
    pkg = _pkg("tolerant_reduced_safety_risk", {})
    bin_no_sub = rr.project(pkg, "small_molecule")["biological"]["bin"]
    substrate = {
        "mechanism": {"grounded": {"findings": [{"finding": "tumor-suppressive in this context",
                                                 "kind": "moa", "cited_pmids": ["9"]}],
                                   "contradicts_deterministic": True}},
        "genomic_alteration": {"grounded": {"findings": [{"finding": "alteration is a passenger",
                                            "kind": "driver", "cited_pmids": ["8"]}],
                                            "contradicts_deterministic": False}},
    }
    bio = rr.project(pkg, "small_molecule", substrate)["biological"]
    assert bio["bin"] == bin_no_sub                                   # escalate-only: bin unchanged
    findings = [f["finding"] for f in bio["grounded_findings"]]
    assert "tumor-suppressive in this context" in findings
    assert "alteration is a passenger" in findings                   # both new axes fold in
    assert bio["engine_literature_discordance"] is True              # mechanism contradiction propagates


def test_differentiation_folds_into_translational_dim():
    # follow-up: differentiation (patient-selection) now escalates the TRANSLATIONAL dim, completing the
    # 6-dim map. translational is engine-blind → its bin is the coarse literature bin from the findings.
    assert rr.AXIS_TO_DIM["differentiation"] == "translational"
    pkg = _pkg("tolerant_reduced_safety_risk", {})
    dims_no_sub = rr.project(pkg, "small_molecule")
    # engine-blind: with NO substrate the bin stays ENGINE-BLIND (same as clinical/commercial)
    assert dims_no_sub["translational"]["bin"] == "ENGINE-BLIND"
    substrate = {"differentiation": {"grounded": {"findings": [
        {"finding": "KRAS co-mutation predicts resistance", "kind": "resistance", "cited_pmids": ["7"]}],
        "contradicts_deterministic": False}}}
    tr = rr.project(pkg, "small_molecule", substrate)["translational"]
    assert tr["grounded_findings"][0]["finding"] == "KRAS co-mutation predicts resistance"
    assert tr["bin"] in ("MED", "HIGH")                             # a finding raises the coarse lit bin
    assert tr["bin_basis"] == "literature-only (uncalibrated)"


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
    # a severity=high finding escalates the clinical pseudo-card to HIGH (literature-only). This keys on
    # the controlled `severity` enum, NOT a substring-grep of `kind` — so prose that doesn't contain an
    # escalator token (e.g. "lack of clinical validation") no longer silently under-bins.
    sub = {"clinical": {"grounded": {"findings": [
        {"finding": "Ph3 failed", "kind": "failed_trial", "severity": "high", "cited_pmids": ["1"]}]}}}
    out = rr.project(pkg, "adc", sub)["clinical"]
    assert out["bin"] == "HIGH" and out["bin_basis"] == "literature-only (uncalibrated)"
    # a moderate-severity finding -> MED; no findings -> LOW
    sub2 = {"commercial": {"grounded": {"findings": [
        {"finding": "lack of clinical validation", "kind": "no_validation", "severity": "moderate", "cited_pmids": []}]}}}
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


# ── coverage-wiring fixes (2026-09-02): druggability strong verdicts, clinical & commercial engine bins ──
def _pkg2(sub_verdicts: dict, card_summaries: dict | None = None):
    return {"synthesis": {"sub_verdicts": {k: {"verdict": v} for k, v in sub_verdicts.items()}},
            "cards": [{"card_id": k, "summary": s} for k, s in (card_summaries or {}).items()]}


def test_druggability_strong_tractability_is_low():
    # BUG FIX: measured_potent_ligand / chemically_confirmed_genetic are STRONG positives — previously
    # missing from the lookup, so they silently defaulted to MED. They must read LOW.
    for v in ("measured_potent_ligand", "chemically_confirmed_genetic", "well_covered", "chemically_active"):
        dims = rr.deterministic_bins(_pkg2({"tractability_sm": v}), "small_molecule")
        assert dims["druggability"]["bin"] == "LOW", (v, dims["druggability"])
    # a caveated moderate rung stays MED via the default; a negative is HIGH
    assert rr.deterministic_bins(_pkg2({"tractability_sm": "structurally_ligandable"}), "small_molecule")["druggability"]["bin"] == "MED"
    assert rr.deterministic_bins(_pkg2({"tractability_sm": "chemically_unhit"}), "small_molecule")["druggability"]["bin"] == "HIGH"


def test_clinical_bin_from_precedent_card():
    approved = _pkg2({}, {"clinical-precedent": {"highest_clinical_stage": "approved"}})
    assert rr.deterministic_bins(approved, "small_molecule")["clinical"]["bin"] == "LOW"
    early = _pkg2({}, {"clinical-precedent": {"highest_clinical_stage": "phase_1"}})
    assert rr.deterministic_bins(early, "small_molecule")["clinical"]["bin"] == "MED"
    failed = _pkg2({}, {"clinical-precedent": {"highest_clinical_stage": "phase_2", "notable_failures": ["drugX"]}})
    assert rr.deterministic_bins(failed, "small_molecule")["clinical"]["bin"] == "HIGH"
    # absent card → stays engine-blind (literature-only)
    assert rr.deterministic_bins(_pkg2({}), "small_molecule")["clinical"]["bin"] == "ENGINE-BLIND"


def test_commercial_bin_from_competitor_card():
    crowded = _pkg2({}, {"competitor-landscape": {"competitor_class": "approved_competitor", "n_competitor_programs": 5}})
    assert rr.deterministic_bins(crowded, "small_molecule")["commercial"]["bin"] == "HIGH"
    whitespace = _pkg2({}, {"competitor-landscape": {"competitor_class": "no_known_competitor", "n_competitor_programs": 0}})
    assert rr.deterministic_bins(whitespace, "small_molecule")["commercial"]["bin"] == "LOW"
    # insufficient / absent → engine-blind
    assert rr.deterministic_bins(_pkg2({}, {"competitor-landscape": {"competitor_class": "insufficient"}}),
                                 "small_molecule")["commercial"]["bin"] == "ENGINE-BLIND"


def test_clinical_commercial_engine_bins_not_clobbered_by_project():
    # a real engine bin must survive project() (deterministic wins; literature attaches, never overwrites)
    pkg = _pkg2({}, {"clinical-precedent": {"highest_clinical_stage": "approved"},
                     "competitor-landscape": {"competitor_class": "no_known_competitor"}})
    substrate = {"clinical": {"grounded": {"findings": [{"finding": "f", "severity": "high", "cited_pmids": ["1"]}]}}}
    dims = rr.project(pkg, "small_molecule", substrate)
    assert dims["clinical"]["bin"] == "LOW"                 # NOT escalated to HIGH by the finding
    assert dims["commercial"]["bin"] == "LOW"
    assert dims["clinical"]["grounded_findings"][0]["finding"] == "f"   # finding still attached
