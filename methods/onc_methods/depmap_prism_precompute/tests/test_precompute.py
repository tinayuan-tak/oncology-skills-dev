"""Synthetic tests for the PRISM precompute v3 — Log2AUC primary + LFC responder tail."""

from __future__ import annotations

import pandas as pd
import pytest

from onc_methods.depmap_prism_precompute import cli as pc

# ---------------------------------------------------------------------------
# Compound-list parsers (unchanged in v3)
# ---------------------------------------------------------------------------


def test_split_gene_list_basic():
    assert pc._split_gene_list("KRAS") == ["KRAS"]
    assert pc._split_gene_list("KRAS, HRAS, NRAS, FNTA") == ["FNTA", "HRAS", "KRAS", "NRAS"]
    assert pc._split_gene_list("EGFR;ERBB2") == ["EGFR", "ERBB2"]
    assert pc._split_gene_list("") == []
    assert pc._split_gene_list(None) == []
    assert pc._split_gene_list("NA") == []


def test_load_oncref_compound_list_shape():
    csv = (
        "CompoundPlate,SampleID,Release,Prioritized,CompoundName,TargetOrMechanism,"
        "ChEMBLID,PubChemCID,GeneSymbolOfTargets,Synonyms\n"
        "P1,PRC-001,OncRef 24Q2,TRUE,SOTORASIB,KRAS G12C inhibitor,C1,,KRAS,SYN\n"
        "P1,PRC-002,OncRef 24Q2,TRUE,ADAGRASIB,KRAS G12C inhibitor,C2,,KRAS,SYN\n"
        "P1,PRC-003,OncRef 24Q2,FALSE,BAY-293,SOS1 inhibitor,C3,,SOS1;KRAS,SYN\n"
    )
    df = pc.load_oncref_compound_list(csv.encode())
    assert len(df) == 3
    assert df.iloc[0]["compound_id"] == "PRC-001"
    assert df.iloc[0]["drug_name"] == "SOTORASIB"
    assert df.iloc[0]["gene_targets"] == ["KRAS"]
    # BAY-293 has semicolon-separated gene list (real OncRef format)
    assert set(df.iloc[2]["gene_targets"]) == {"KRAS", "SOS1"}
    assert bool(df.iloc[0]["prioritized"]) is True
    assert bool(df.iloc[2]["prioritized"]) is False
    assert (df["source_release"] == "oncref-25q4").all()


def test_load_repurposing_compound_list_shape():
    csv = (
        "screen,dose,repurposing_target,MOA,IDs,Drug.Name,Synonyms\n"
        'REP.PRIMARY,2.5,"KRAS, HRAS, NRAS, FNTA",farnesyltransferase inhibitor,'
        "BRD:BRD-A04843135-001-09-9,LONAFARNIB,SYN\n"
        "REP.PRIMARY,2.5,EGFR,EGFR inhibitor,BRD:BRD-A99999999-001-01-1,ERLOTINIB,SYN\n"
        "REP.PRIMARY,2.5,,,BRD:BRD-A00000000-001-01-1,MYSTERY,SYN\n"
    )
    df = pc.load_repurposing_compound_list(csv.encode())
    assert len(df) == 3
    assert df.iloc[0]["compound_id"] == "BRD-A04843135"
    assert df.iloc[0]["drug_name"] == "LONAFARNIB"
    assert set(df.iloc[0]["gene_targets"]) == {"KRAS", "HRAS", "NRAS", "FNTA"}
    assert df.iloc[2]["gene_targets"] == []
    assert (df["source_release"] == "repurposing-24q2").all()


# ---------------------------------------------------------------------------
# v3 loaders
# ---------------------------------------------------------------------------


def test_load_oncref_log2auc_shape():
    """OncRef Log2AUC wide matrix: SampleID columns, ModelID row index."""
    csv = ",PRC-001,PRC-002\nACH-000001,-2.3,-1.5\nACH-000002,-0.1,-0.2\nACH-000003,0.0,-0.05\n"
    df = pc.load_oncref_log2auc(csv.encode())
    assert len(df) == 6  # 3 lines × 2 compounds
    assert set(df["compound_id"]) == {"PRC-001", "PRC-002"}
    assert set(df["model_id"]) == {"ACH-000001", "ACH-000002", "ACH-000003"}
    sub = df[(df["model_id"] == "ACH-000001") & (df["compound_id"] == "PRC-001")]
    assert sub.iloc[0]["log2auc"] == pytest.approx(-2.3)


def test_load_oncref_lfccollapsed_min():
    """LFCCollapsed collapsed to per-(compound × cell_line) min LFC across doses."""
    csv = (
        "screen,CompoundPlate,SampleID,pert_dose,pert_dose_unit,cellset,pool_id,depmap_id,LFC,LFC_uncorrected,LFC_fitted,LFC_uncorrected_fitted,outlier,outlier_uncorrected,priority\n"
        # SOTORASIB (PRC-001) at 3 doses vs ACH-000001
        "S,PS,PRC-001,0.001,ug/mL,PR300P,P121,ACH-000001,-0.05,x,x,x,F,F,1\n"
        "S,PS,PRC-001,0.01,ug/mL,PR300P,P121,ACH-000001,-0.42,x,x,x,F,F,1\n"
        "S,PS,PRC-001,0.1,ug/mL,PR300P,P121,ACH-000001,-3.05,x,x,x,F,F,1\n"
        # SOTORASIB vs ACH-000002 (weaker responder)
        "S,PS,PRC-001,0.001,ug/mL,PR300P,P121,ACH-000002,0.01,x,x,x,F,F,1\n"
        "S,PS,PRC-001,0.1,ug/mL,PR300P,P121,ACH-000002,-0.20,x,x,x,F,F,1\n"
        # UNWANTED compound (should be filtered)
        "S,PS,PRC-999,0.1,ug/mL,PR300P,P121,ACH-000001,-2.50,x,x,x,F,F,1\n"
    )
    wanted = {"PRC-001"}
    df = pc.load_oncref_lfccollapsed(csv.encode(), wanted)
    assert set(df["compound_id"]) == {"PRC-001"}  # PRC-999 filtered
    # ACH-000001 min = -3.05
    r1 = df[(df["compound_id"] == "PRC-001") & (df["model_id"] == "ACH-000001")]
    assert r1.iloc[0]["min_lfc"] == pytest.approx(-3.05)
    # ACH-000002 min = -0.20
    r2 = df[(df["compound_id"] == "PRC-001") & (df["model_id"] == "ACH-000002")]
    assert r2.iloc[0]["min_lfc"] == pytest.approx(-0.20)


def test_load_repurposing_lfc_filters_and_qc():
    """Repurposing single-dose LFC — unchanged from v2."""
    csv = (
        "row_id,broad_id,dose,compound_plate,screen,culture,LFC\n"
        "ACH-000001::P1::PR500B::REP300,BRD-A04843135-001-09-9,2.5,PREP053,REP300,PR500B,-2.5\n"
        "ACH-000002::P1::PR500B::REP300,BRD-A04843135-001-09-9,2.5,PREP053,REP300,PR500B,-1.5\n"
        "ACH-000001::P1::PR500B::REP300,BRD-A99999999-001-01-1 - QC Failure,2.5,PREP053,REP300,PR500B,0.5\n"
        "ACH-000001::P1::PR500B::REP300,BRD-A11111111-001-01-1,2.5,PREP053,REP300,PR500B,-0.3\n"
    )
    wanted = {"BRD-A04843135", "BRD-A11111111"}
    df = pc.load_repurposing_lfc(csv.encode(), wanted)
    assert set(df["compound_id"]) == wanted
    lonaf = df[df["compound_id"] == "BRD-A04843135"]
    assert len(lonaf) == 2


# ---------------------------------------------------------------------------
# Cross-release merge
# ---------------------------------------------------------------------------


def test_merge_compound_universes_prefers_oncref():
    oncref = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS G12C inhibitor",
                "prioritized": True,
                "source_release": "oncref-25q4",
            }
        ]
    )
    repur = pd.DataFrame(
        [
            {
                "compound_id": "BRD-SOMETHING",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS inhibitor",
                "prioritized": False,
                "source_release": "repurposing-24q2",
            },
            {
                "compound_id": "BRD-A04843135",
                "drug_name": "LONAFARNIB",
                "gene_targets": ["KRAS", "HRAS", "NRAS", "FNTA"],
                "moa": "FTase inhibitor",
                "prioritized": False,
                "source_release": "repurposing-24q2",
            },
        ]
    )
    merged = pc.merge_compound_universes([oncref, repur])
    sot = merged[merged["drug_name"].str.upper() == "SOTORASIB"]
    assert len(sot) == 1
    assert sot.iloc[0]["source_release"] == "oncref-25q4"


# ---------------------------------------------------------------------------
# Classifier — v3 uses Log2AUC thresholds
# ---------------------------------------------------------------------------


def test_classify_prism_activity_no_compounds():
    assert pc.classify_prism_activity(0, "tool", None) == pc.CLASS_NO_COMPOUNDS_FOUND


def test_classify_prism_activity_clinically_active_with_activity():
    """Phase 1+ compound with strongly-negative Log2AUC → clinically_active."""
    assert pc.classify_prism_activity(2, "phase_1_plus", -0.5) == pc.CLASS_CLINICALLY_ACTIVE


def test_classify_prism_activity_clinical_precedent_only_when_no_or_weak_activity():
    """T1.2 split (#263): a phase_1_plus clinical anchor WITHOUT a measured activity signal (no
    Log2AUC, or weak/flat) is the weaker `clinical_precedent_only`, NOT the strong `clinically_active`
    — which now requires an actual activity signal (see the strong-activity test above)."""
    assert pc.classify_prism_activity(2, "phase_1_plus", None) == pc.CLASS_CLINICAL_PRECEDENT_ONLY
    assert pc.classify_prism_activity(2, "phase_1_plus", -0.02) == pc.CLASS_CLINICAL_PRECEDENT_ONLY


def test_classify_prism_activity_weakly_active():
    # Log2AUC -0.3 clears WEAKLY_ACTIVE_LOG2AUC_THRESHOLD=-0.15
    assert pc.classify_prism_activity(3, "tool", -0.3) == pc.CLASS_WEAKLY_ACTIVE


def test_classify_prism_activity_tool_only():
    assert pc.classify_prism_activity(3, "tool", -0.05) == pc.CLASS_TOOL_COMPOUND_ONLY


# ---------------------------------------------------------------------------
# Lineage classifier — v3 uses Log2AUC thresholds
# ---------------------------------------------------------------------------


def test_classify_prism_lineage_selectivity_selective():
    """≥1 active + ≥1 inactive → lineage_selective (Log2AUC threshold: -0.15 active, -0.05 inactive)."""
    entries = [
        {"lineage": "Bowel", "median_log2auc": -0.40},
        {"lineage": "Pancreas", "median_log2auc": -0.20},
        {"lineage": "Lung", "median_log2auc": -0.02},
        {"lineage": "Skin", "median_log2auc": 0.02},
    ]
    assert pc.classify_prism_lineage_selectivity(entries) == pc.LINEAGE_SEL_SELECTIVE


def test_classify_prism_lineage_selectivity_broadly_active():
    """Most lineages active but no clear inactive contrast → broadly_active."""
    entries = [
        {"lineage": "Bowel", "median_log2auc": -0.40},
        {"lineage": "Pancreas", "median_log2auc": -0.30},
        {"lineage": "Lung", "median_log2auc": -0.25},
        {"lineage": "Skin", "median_log2auc": -0.20},
        {"lineage": "Bladder", "median_log2auc": -0.18},
    ]
    assert pc.classify_prism_lineage_selectivity(entries) == pc.LINEAGE_SEL_BROADLY_ACTIVE


def test_classify_prism_lineage_selectivity_no_signal():
    """No active lineages → no_lineage_signal."""
    entries = [
        {"lineage": "Bowel", "median_log2auc": -0.04},
        {"lineage": "Pancreas", "median_log2auc": -0.02},
        {"lineage": "Lung", "median_log2auc": 0.00},
    ]
    assert pc.classify_prism_lineage_selectivity(entries) == pc.LINEAGE_SEL_NO_SIGNAL


def test_classify_prism_lineage_selectivity_data_unavailable_when_empty():
    assert pc.classify_prism_lineage_selectivity([]) == pc.LINEAGE_SEL_DATA_UNAVAILABLE


# ---------------------------------------------------------------------------
# Model.csv loader
# ---------------------------------------------------------------------------


def test_load_model_to_lineage_basic():
    csv = "ModelID,OncotreeLineage,Extra\nACH-000001,Bowel,x\nACH-000002,Lung,x\nACH-000003,,x\nACH-000004,Pancreas,x\n"
    m = pc.load_model_to_lineage(csv.encode())
    assert m["ACH-000001"] == "Bowel"
    assert m["ACH-000002"] == "Lung"
    assert m["ACH-000004"] == "Pancreas"
    assert "ACH-000003" not in m


# ---------------------------------------------------------------------------
# End-to-end: build gene aggregate — v3 signature
# ---------------------------------------------------------------------------


def test_build_gene_aggregate_kras_case_v3():
    """KRAS with sotorasib (OncRef, Log2AUC) + LONAFARNIB (Repurposing, annotation).
    v3: median_log2auc_across_compounds computed from OncRef ONLY (Log2AUC data).
    LONAFARNIB appears in top_compounds but contributes no activity number.
    """
    merged = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS G12C",
                "prioritized": True,
                "source_release": "oncref-25q4",
            },
            {
                "compound_id": "BRD-A04843135",
                "drug_name": "LONAFARNIB",
                "gene_targets": ["KRAS", "HRAS", "NRAS", "FNTA"],
                "moa": "FTase",
                "prioritized": False,
                "source_release": "repurposing-24q2",
            },
        ]
    )
    oncref_log2auc = pd.DataFrame(
        [
            {"model_id": "ACH-1", "compound_id": "PRC-001", "log2auc": -0.4, "source_release": "oncref-25q4"},
            {"model_id": "ACH-2", "compound_id": "PRC-001", "log2auc": -0.2, "source_release": "oncref-25q4"},
            {"model_id": "ACH-3", "compound_id": "PRC-001", "log2auc": -0.05, "source_release": "oncref-25q4"},
        ]
    )
    oncref_lfccollapsed = pd.DataFrame(
        [
            {"model_id": "ACH-1", "compound_id": "PRC-001", "min_lfc": -3.5, "source_release": "oncref-25q4"},
            {"model_id": "ACH-2", "compound_id": "PRC-001", "min_lfc": -1.2, "source_release": "oncref-25q4"},
        ]
    )
    repurposing_lfc = pd.DataFrame(
        [
            {
                "model_id": "ACH-1",
                "compound_id": "BRD-A04843135",
                "median_lfc": -0.5,
                "source_release": "repurposing-24q2",
            },
            {
                "model_id": "ACH-2",
                "compound_id": "BRD-A04843135",
                "median_lfc": -0.3,
                "source_release": "repurposing-24q2",
            },
        ]
    )
    agg = pc.build_gene_aggregate(
        merged,
        oncref_log2auc=oncref_log2auc,
        oncref_lfccollapsed_min=oncref_lfccollapsed,
        repurposing_lfc=repurposing_lfc,
    )
    kras = agg[agg["gene_symbol"] == "KRAS"].iloc[0]
    assert kras["n_compounds_targeting"] == 2
    assert kras["highest_clinical_phase"] == "phase_1_plus"
    # median_log2auc_across_compounds = median of just SOTORASIB's median = median of [-0.4, -0.2, -0.05] = -0.2
    assert kras["median_log2auc_across_compounds"] == pytest.approx(-0.2, abs=1e-3)
    assert kras["prism_activity_class"] == pc.CLASS_CLINICALLY_ACTIVE
    top = kras["top_compounds"]
    assert len(top) == 2
    # SOTORASIB should rank first (prioritized OncRef with Log2AUC data)
    assert top[0]["drug_name"] == "SOTORASIB"
    assert top[0]["metric_source"] == "log2auc"
    assert top[0]["median_log2auc"] == pytest.approx(-0.2, abs=1e-3)
    assert top[0]["best_responder_lfc"] == pytest.approx(-3.5, abs=1e-3)
    # LONAFARNIB annotation-only (Repurposing has no Log2AUC)
    assert top[1]["drug_name"] == "LONAFARNIB"
    assert top[1]["metric_source"] == "single_dose_lfc"
    assert top[1]["median_log2auc"] is None
    assert top[1]["single_dose_lfc"] == pytest.approx(-0.4, abs=1e-3)
    # HRAS should also appear (LONAFARNIB polyselective) — but only annotation, no Log2AUC
    hras = agg[agg["gene_symbol"] == "HRAS"].iloc[0]
    assert hras["n_compounds_targeting"] == 1
    # pandas coerces None → NaN in float-dtype columns; the card-side compute_summary
    # normalizes NaN → None. Check for both representations here.
    assert pd.isna(hras["median_log2auc_across_compounds"]) or hras["median_log2auc_across_compounds"] is None
    assert hras["prism_activity_class"] == pc.CLASS_TOOL_COMPOUND_ONLY


def test_build_gene_aggregate_no_activity_data():
    """Compound annotated but no Log2AUC data → tool_compound_only (Repurposing-only)."""
    merged = pd.DataFrame(
        [
            {
                "compound_id": "BRD-XYZ",
                "drug_name": "ONLY_ANNOTATED",
                "gene_targets": ["GHOST"],
                "moa": "unknown",
                "prioritized": False,
                "source_release": "repurposing-24q2",
            }
        ]
    )
    agg = pc.build_gene_aggregate(merged)
    g = agg[agg["gene_symbol"] == "GHOST"].iloc[0]
    assert g["n_compounds_targeting"] == 1
    assert g["median_log2auc_across_compounds"] is None
    assert g["prism_activity_class"] == pc.CLASS_TOOL_COMPOUND_ONLY


def test_build_gene_aggregate_lineage_selective():
    """KRAS in Bowel/Pancreas → active (Log2AUC < -0.15); Lung → inactive (> -0.05).
    Expected: lineage_selective."""
    merged = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS G12C",
                "prioritized": True,
                "source_release": "oncref-25q4",
            },
        ]
    )
    bowel = [f"ACH-B-{i:03d}" for i in range(5)]
    pancreas = [f"ACH-P-{i:03d}" for i in range(5)]
    lung = [f"ACH-L-{i:03d}" for i in range(5)]
    log2auc_rows = []
    # Bowel: Log2AUC = -0.4 (active)
    log2auc_rows += [
        {"model_id": m, "compound_id": "PRC-001", "log2auc": -0.4, "source_release": "oncref-25q4"} for m in bowel
    ]
    # Pancreas: Log2AUC = -0.2 (active)
    log2auc_rows += [
        {"model_id": m, "compound_id": "PRC-001", "log2auc": -0.2, "source_release": "oncref-25q4"} for m in pancreas
    ]
    # Lung: Log2AUC = 0.0 (inactive)
    log2auc_rows += [
        {"model_id": m, "compound_id": "PRC-001", "log2auc": 0.0, "source_release": "oncref-25q4"} for m in lung
    ]
    oncref_log2auc = pd.DataFrame(log2auc_rows)
    model_to_lineage = {**{m: "Bowel" for m in bowel}, **{m: "Lung" for m in lung}, **{m: "Pancreas" for m in pancreas}}
    agg = pc.build_gene_aggregate(merged, oncref_log2auc=oncref_log2auc, model_to_lineage=model_to_lineage)
    kras = agg[agg["gene_symbol"] == "KRAS"].iloc[0]
    lineages = {e["lineage"] for e in kras["per_lineage_activity"]}
    assert lineages == {"Bowel", "Pancreas", "Lung"}
    bowel_entry = next(e for e in kras["per_lineage_activity"] if e["lineage"] == "Bowel")
    lung_entry = next(e for e in kras["per_lineage_activity"] if e["lineage"] == "Lung")
    assert bowel_entry["median_log2auc"] == pytest.approx(-0.4, abs=1e-3)
    assert lung_entry["median_log2auc"] == pytest.approx(0.0, abs=1e-3)
    assert kras["prism_lineage_selectivity"] == pc.LINEAGE_SEL_SELECTIVE
    # Sorted most-active-first
    assert kras["per_lineage_activity"][0]["lineage"] == "Bowel"


def test_build_gene_aggregate_lineage_min_size_filter():
    """Lineage with fewer than min_cell_lines_in_lineage=5 lines is excluded."""
    merged = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "TESTCMPD",
                "gene_targets": ["TARGET"],
                "moa": "test",
                "prioritized": True,
                "source_release": "oncref-25q4",
            },
        ]
    )
    bowel = [f"ACH-B-{i:03d}" for i in range(5)]
    rare = [f"ACH-R-{i:03d}" for i in range(2)]
    log2auc = pd.DataFrame(
        [{"model_id": m, "compound_id": "PRC-001", "log2auc": -0.3, "source_release": "oncref-25q4"} for m in bowel]
        + [{"model_id": m, "compound_id": "PRC-001", "log2auc": -0.5, "source_release": "oncref-25q4"} for m in rare]
    )
    model_to_lineage = {**{m: "Bowel" for m in bowel}, **{m: "RareLineage" for m in rare}}
    agg = pc.build_gene_aggregate(merged, oncref_log2auc=log2auc, model_to_lineage=model_to_lineage)
    tgt = agg[agg["gene_symbol"] == "TARGET"].iloc[0]
    lineages = {e["lineage"] for e in tgt["per_lineage_activity"]}
    assert lineages == {"Bowel"}


def test_build_gene_aggregate_no_model_map():
    """When model_to_lineage is None, per_lineage_activity stays empty."""
    merged = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS G12C",
                "prioritized": True,
                "source_release": "oncref-25q4",
            },
        ]
    )
    oncref_log2auc = pd.DataFrame(
        [
            {"model_id": "ACH-1", "compound_id": "PRC-001", "log2auc": -0.5, "source_release": "oncref-25q4"},
        ]
    )
    agg = pc.build_gene_aggregate(merged, oncref_log2auc=oncref_log2auc)
    kras = agg[agg["gene_symbol"] == "KRAS"].iloc[0]
    assert kras["per_lineage_activity"] == []
    assert kras["prism_lineage_selectivity"] == pc.LINEAGE_SEL_DATA_UNAVAILABLE


# ---------------------------------------------------------------------------
# v4 CRISPR × RNAi × PRISM concordance
# ---------------------------------------------------------------------------


def test_spearman_rho_perfect_positive():
    """Two ranked-identical sequences → rho = 1.0."""
    assert pc._spearman_rho([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0, abs=1e-6)


def test_spearman_rho_perfect_negative():
    """Perfectly inverted → rho = -1.0."""
    assert pc._spearman_rho([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == pytest.approx(-1.0, abs=1e-6)


def test_spearman_rho_none_on_small_n():
    """< 3 samples → None (undefined)."""
    assert pc._spearman_rho([1, 2], [3, 4]) is None


def test_spearman_rho_none_on_zero_variance():
    """One vector constant → None (undefined)."""
    assert pc._spearman_rho([1, 1, 1, 1], [1, 2, 3, 4]) is None


def test_correlate_maps_intersects_on_model_id():
    """Only shared ModelIDs contribute to correlation."""
    a = {"ACH-1": -2.0, "ACH-2": -1.5, "ACH-3": 0.0, "ACH-4": 0.5}
    b = {"ACH-1": -1.5, "ACH-2": -1.0, "ACH-3": 0.1, "ACH-5": 99.0}  # ACH-5 not in a
    # Shared = ACH-1, ACH-2, ACH-3 (3 lines) → rho computed
    rho, n = pc._correlate_maps(a, b, min_lines=3)
    assert n == 3
    assert rho == pytest.approx(1.0, abs=1e-6)  # perfectly monotonic across shared 3


def test_correlate_maps_returns_none_below_min_lines():
    a = {"ACH-1": 1.0, "ACH-2": 2.0, "ACH-3": 3.0}
    b = {"ACH-1": 1.0, "ACH-2": 2.0}
    rho, n = pc._correlate_maps(a, b, min_lines=3)
    assert rho is None and n is None


def test_classify_concordance_triangulated():
    """Both CRISPR + RNAi rho ≥ 0.30 AND FDR-significant → triangulated_target_engaged.
    (2026-08-08: strong calls now require n for a significance test — rho 0.5/0.4 at n=30 both clear
    BH q<0.05 as a single test.)"""
    per_cmp = [{"spearman_r_crispr": 0.5, "spearman_r_rnai": 0.4, "n_intersected_crispr": 30, "n_intersected_rnai": 30}]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_TRIANGULATED


def test_classify_concordance_crispr_confirmed():
    """CRISPR strong+significant, RNAi weak → crispr_confirmed_engagement."""
    per_cmp = [{"spearman_r_crispr": 0.5, "spearman_r_rnai": 0.1, "n_intersected_crispr": 30, "n_intersected_rnai": 30}]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_CRISPR_CONFIRMED


def test_classify_concordance_rnai_confirmed():
    """RNAi strong+significant, CRISPR weak → rnai_confirmed_engagement."""
    per_cmp = [{"spearman_r_crispr": 0.1, "spearman_r_rnai": 0.5, "n_intersected_crispr": 30, "n_intersected_rnai": 30}]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_RNAI_CONFIRMED


def test_classify_strong_rho_but_underpowered_n_is_not_triangulated():
    """rho ≥ 0.30 at a TINY n (not significant) must NOT trigger a target-engaged call — the exact
    gap the FDR gate closes. rho 0.31 at n=20 → p≈0.18, q≈0.18 > 0.05 → falls to mixed_engagement."""
    per_cmp = [
        {"spearman_r_crispr": 0.31, "spearman_r_rnai": 0.31, "n_intersected_crispr": 20, "n_intersected_rnai": 20}
    ]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_MIXED


def test_classify_best_of_N_multiplicity_guard():
    """A single spurious rho=0.32 among MANY (20) near-zero compounds must NOT triangulate: BH-FDR
    over the compound set neutralizes the best-of-N inflation (the heavily-annotated-gene failure mode).
    All at n=25; the lone 0.32 (single-test p≈0.12) gets q≈0.12·20 ≫ 0.05 after BH → no strong call."""
    per_cmp = [
        {"spearman_r_crispr": 0.32, "spearman_r_rnai": 0.32, "n_intersected_crispr": 25, "n_intersected_rnai": 25}
    ] + [
        {
            "spearman_r_crispr": 0.02 + 0.001 * i,
            "spearman_r_rnai": 0.01 + 0.001 * i,
            "n_intersected_crispr": 25,
            "n_intersected_rnai": 25,
        }
        for i in range(19)
    ]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) != pc.CONCORDANCE_TRIANGULATED


def test_classify_independent_max_loophole_closed():
    """Triangulation must not be minted by TWO DIFFERENT compounds each supplying one assay's max.
    Compound A: strong+significant CRISPR only; compound B: strong+significant RNAi only. Old logic
    (independent max) → triangulated. New per-assay-significant logic still returns triangulated ONLY
    because BOTH assays have their own FDR-significant compound — which is the correct semantics; the
    loophole that is closed is a NON-significant partner no longer counting. Here we assert the honest
    case: if the RNAi side is NOT significant, it must fall to crispr_confirmed, not triangulated."""
    per_cmp = [
        {
            "spearman_r_crispr": 0.6,
            "spearman_r_rnai": None,
            "n_intersected_crispr": 40,
            "n_intersected_rnai": None,
        },  # A: strong CRISPR
        {
            "spearman_r_crispr": None,
            "spearman_r_rnai": 0.31,
            "n_intersected_crispr": None,
            "n_intersected_rnai": 20,
        },  # B: weak/underpowered RNAi (p≈0.18)
    ]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_CRISPR_CONFIRMED


def test_classify_concordance_mixed():
    """Best pair-wise in [0.10, 0.30) → mixed_engagement."""
    per_cmp = [{"spearman_r_crispr": 0.15, "spearman_r_rnai": 0.12}]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_MIXED


def test_classify_concordance_off_target():
    """All rhos < 0.10 → discordant_off_target_likely."""
    per_cmp = [{"spearman_r_crispr": 0.05, "spearman_r_rnai": 0.02}]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_OFF_TARGET


def test_classify_concordance_thin_when_no_rhos():
    """Non-empty list but all rhos None → thin_evidence."""
    per_cmp = [{"spearman_r_crispr": None, "spearman_r_rnai": None}]
    assert pc.classify_crispr_prism_concordance(per_cmp, True, True) == pc.CONCORDANCE_THIN


def test_classify_concordance_data_unavailable():
    """No CRISPR AND no RNAi data → data_unavailable (regardless of list content)."""
    assert pc.classify_crispr_prism_concordance([], False, False) == pc.CONCORDANCE_DATA_UNAVAILABLE


def test_compute_per_compound_concordance_uses_lfc_when_available():
    """LFC frame preferred over Log2AUC frame."""
    chronos = {f"ACH-{i:03d}": -2.0 + i * 0.05 for i in range(30)}  # 30 lines, gradient
    rnai = {f"ACH-{i:03d}": -1.5 + i * 0.04 for i in range(30)}  # 30 lines, gradient
    lfc = pd.DataFrame(
        [
            {
                "model_id": f"ACH-{i:03d}",
                "compound_id": "PRC-001",
                "min_lfc": -3.0 + i * 0.08,
            }  # anti-correlated with chronos (both negative-dependent → correlate positive)
            for i in range(30)
        ]
    )
    log2auc = pd.DataFrame()  # empty fallback

    result = pc.compute_per_compound_concordance(
        chronos_by_model=chronos,
        rnai_by_model=rnai,
        lfc_frame=lfc,
        log2auc_frame=log2auc,
        compound_ids={"PRC-001"},
        min_lines=20,
    )
    assert len(result) == 1
    r = result[0]
    assert r["compound_id"] == "PRC-001"
    assert r["metric_used"] == "lfc"
    assert r["n_intersected_crispr"] == 30
    assert r["n_intersected_rnai"] == 30
    # Chronos and LFC both increase monotonically in ACH-XXX → perfect positive Spearman
    assert r["spearman_r_crispr"] == pytest.approx(1.0, abs=1e-6)
    assert r["spearman_r_rnai"] == pytest.approx(1.0, abs=1e-6)


def test_compute_per_compound_concordance_skips_when_both_thin():
    """Compound with insufficient intersection in BOTH assays → not returned."""
    chronos = {"ACH-1": -1.0}  # only 1 line
    lfc = pd.DataFrame([{"model_id": "ACH-1", "compound_id": "PRC-001", "min_lfc": -2.0}])
    result = pc.compute_per_compound_concordance(
        chronos_by_model=chronos,
        rnai_by_model=None,
        lfc_frame=lfc,
        log2auc_frame=None,
        compound_ids={"PRC-001"},
        min_lines=20,
    )
    assert result == []


def test_compute_dual_responders_selects_intersection():
    """Dual-responders = CRISPR-dependent AND compound-responsive (both thresholds cleared)."""
    chronos = {
        "ACH-KDEP-1": -1.2,  # CRISPR-dependent
        "ACH-KDEP-2": -0.8,  # CRISPR-dependent
        "ACH-KNOR-1": 0.1,  # not CRISPR-dependent
        "ACH-KDEP-3": -1.5,  # CRISPR-dependent BUT not compound-responsive
    }
    lfc = pd.DataFrame(
        [
            {"model_id": "ACH-KDEP-1", "compound_id": "PRC-001", "min_lfc": -2.5},  # responsive
            {"model_id": "ACH-KDEP-2", "compound_id": "PRC-001", "min_lfc": -1.5},  # responsive
            {"model_id": "ACH-KNOR-1", "compound_id": "PRC-001", "min_lfc": -3.0},  # responsive but not CRISPR-dep
            {"model_id": "ACH-KDEP-3", "compound_id": "PRC-001", "min_lfc": -0.2},  # CRISPR-dep but not responsive
        ]
    )
    dual = pc.compute_dual_responders(
        chronos_by_model=chronos,
        lfc_frame=lfc,
        compound_ids={"PRC-001"},
        model_to_lineage={"ACH-KDEP-1": "Bowel", "ACH-KDEP-2": "Lung"},
    )
    dual_ids = {d["model_id"] for d in dual}
    assert dual_ids == {"ACH-KDEP-1", "ACH-KDEP-2"}
    # Most-CRISPR-dependent first (KDEP-1 -1.2 more negative than KDEP-2 -0.8)
    assert dual[0]["model_id"] == "ACH-KDEP-1"
    assert dual[0]["lineage"] == "Bowel"


def test_build_gene_aggregate_v4_concordance_end_to_end():
    """End-to-end: gene aggregate row carries per_compound_concordance +
    class + dual_responders when chronos_by_gene + rnai_by_gene supplied."""
    merged = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS G12C",
                "prioritized": True,
                "source_release": "oncref-25q4",
            }
        ]
    )
    # Log2AUC + LFCCollapsed for the same 30 lines (gradient)
    oncref_log2auc = pd.DataFrame(
        [
            {
                "model_id": f"ACH-{i:03d}",
                "compound_id": "PRC-001",
                "log2auc": -0.5 + i * 0.02,
                "source_release": "oncref-25q4",
            }
            for i in range(30)
        ]
    )
    oncref_lfc = pd.DataFrame(
        [
            {
                "model_id": f"ACH-{i:03d}",
                "compound_id": "PRC-001",
                "min_lfc": -3.0 + i * 0.08,
                "source_release": "oncref-25q4",
            }
            for i in range(30)
        ]
    )
    # CRISPR + RNAi both monotonic → strong Spearman with LFC
    chronos_by_gene = {"KRAS": {f"ACH-{i:03d}": -2.0 + i * 0.05 for i in range(30)}}
    rnai_by_gene = {"KRAS": {f"ACH-{i:03d}": -1.5 + i * 0.04 for i in range(30)}}
    model_to_lineage = {f"ACH-{i:03d}": "Bowel" for i in range(30)}
    agg = pc.build_gene_aggregate(
        merged,
        oncref_log2auc=oncref_log2auc,
        oncref_lfccollapsed_min=oncref_lfc,
        model_to_lineage=model_to_lineage,
        chronos_by_gene=chronos_by_gene,
        rnai_by_gene=rnai_by_gene,
    )
    kras = agg[agg["gene_symbol"] == "KRAS"].iloc[0]
    assert kras["crispr_prism_concordance_class"] == pc.CONCORDANCE_TRIANGULATED
    assert len(kras["per_compound_concordance"]) == 1
    concord = kras["per_compound_concordance"][0]
    assert concord["compound_id"] == "PRC-001"
    assert concord["spearman_r_crispr"] == pytest.approx(1.0, abs=1e-6)
    assert concord["spearman_r_rnai"] == pytest.approx(1.0, abs=1e-6)
    # Dual responders: cell lines with Chronos < -0.5 AND LFC < -1.0
    dual = kras["dual_responders"]
    assert len(dual) > 0
    # Each dual-responder should meet both thresholds
    for d in dual:
        assert d["chronos_dep"] < pc.DUAL_RESPONDER_CHRONOS
        assert d["best_compound_lfc"] < pc.DUAL_RESPONDER_LFC


def test_build_gene_aggregate_v4_no_crispr_rnai_data_unavailable():
    """When chronos_by_gene + rnai_by_gene are None, concordance is data_unavailable."""
    merged = pd.DataFrame(
        [
            {
                "compound_id": "PRC-001",
                "drug_name": "SOTORASIB",
                "gene_targets": ["KRAS"],
                "moa": "KRAS G12C",
                "prioritized": True,
                "source_release": "oncref-25q4",
            }
        ]
    )
    agg = pc.build_gene_aggregate(merged)
    kras = agg[agg["gene_symbol"] == "KRAS"].iloc[0]
    assert kras["crispr_prism_concordance_class"] == pc.CONCORDANCE_DATA_UNAVAILABLE
    assert kras["per_compound_concordance"] == []
    assert kras["dual_responders"] == []


def test_write_gene_aggregate_parquet_roundtrip(tmp_path):
    """v4 parquet writer roundtrips full schema including concordance + dual_responders."""
    import pyarrow.parquet as pq

    df = pd.DataFrame(
        [
            {
                "gene_symbol": "KRAS",
                "n_compounds_targeting": 2,
                "highest_clinical_phase": "phase_1_plus",
                "median_log2auc_across_compounds": -0.25,
                "top_compounds": [
                    {
                        "compound_id": "PRC-001",
                        "drug_name": "SOTORASIB",
                        "moa": "G12C",
                        "median_log2auc": -0.20,
                        "best_responder_lfc": -3.5,
                        "single_dose_lfc": None,
                        "n_lines_screened": 300,
                        "polyselective": False,
                        "n_annotated_targets": 1,
                        "source_release": "oncref-25q4",
                        "prioritized": True,
                        "metric_source": "log2auc",
                    },
                ],
                "prism_activity_class": pc.CLASS_CLINICALLY_ACTIVE,
                "per_lineage_activity": [
                    {
                        "lineage": "Bowel",
                        "n_lines_screened": 45,
                        "median_log2auc": -0.4,
                        "best_responder_lfc": -4.5,
                        "top_compound_in_lineage": "SOTORASIB",
                        "n_compounds_evaluated": 1,
                    },
                ],
                "prism_lineage_selectivity": pc.LINEAGE_SEL_SELECTIVE,
                # v4
                "per_compound_concordance": [
                    {
                        "compound_id": "PRC-001",
                        "n_intersected_crispr": 45,
                        "spearman_r_crispr": 0.65,
                        "n_intersected_rnai": 30,
                        "spearman_r_rnai": 0.40,
                        "metric_used": "lfc",
                    },
                ],
                "crispr_prism_concordance_class": pc.CONCORDANCE_TRIANGULATED,
                "dual_responders": [
                    {
                        "model_id": "ACH-000001",
                        "lineage": "Bowel",
                        "chronos_dep": -1.2,
                        "best_compound_lfc": -3.1,
                        "best_compound_id": "PRC-001",
                    },
                ],
            }
        ]
    )
    out = tmp_path / "agg.parquet"
    size = pc.write_gene_aggregate_parquet(df, out)
    assert size > 0
    tbl = pq.read_table(str(out), filters=[("gene_symbol", "=", "KRAS")])
    assert tbl.num_rows == 1
    row = {c: tbl[c][0].as_py() for c in tbl.column_names}
    assert row["prism_activity_class"] == pc.CLASS_CLINICALLY_ACTIVE
    assert row["top_compounds"][0]["drug_name"] == "SOTORASIB"
    assert row["top_compounds"][0]["metric_source"] == "log2auc"
    assert row["top_compounds"][0]["median_log2auc"] == pytest.approx(-0.2, abs=1e-3)
    assert row["top_compounds"][0]["best_responder_lfc"] == pytest.approx(-3.5, abs=1e-3)
    assert row["per_lineage_activity"][0]["median_log2auc"] == pytest.approx(-0.4, abs=1e-3)
    assert row["prism_lineage_selectivity"] == pc.LINEAGE_SEL_SELECTIVE
    # v4 fields
    assert row["crispr_prism_concordance_class"] == pc.CONCORDANCE_TRIANGULATED
    assert row["per_compound_concordance"][0]["spearman_r_crispr"] == pytest.approx(0.65, abs=1e-3)
    assert row["per_compound_concordance"][0]["spearman_r_rnai"] == pytest.approx(0.40, abs=1e-3)
    assert row["dual_responders"][0]["model_id"] == "ACH-000001"
    assert row["dual_responders"][0]["chronos_dep"] == pytest.approx(-1.2, abs=1e-3)
