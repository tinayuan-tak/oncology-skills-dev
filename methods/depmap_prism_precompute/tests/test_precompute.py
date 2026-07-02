"""Synthetic tests for the PRISM precompute v3 — Log2AUC primary + LFC responder tail."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_prism_precompute import cli as pc  # noqa: E402


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
        "REP.PRIMARY,2.5,\"KRAS, HRAS, NRAS, FNTA\",farnesyltransferase inhibitor,"
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
    csv = (
        ",PRC-001,PRC-002\n"
        "ACH-000001,-2.3,-1.5\n"
        "ACH-000002,-0.1,-0.2\n"
        "ACH-000003,0.0,-0.05\n"
    )
    df = pc.load_oncref_log2auc(csv.encode())
    assert len(df) == 6                # 3 lines × 2 compounds
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
    assert set(df["compound_id"]) == {"PRC-001"}   # PRC-999 filtered
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
    oncref = pd.DataFrame([{
        "compound_id": "PRC-001", "drug_name": "SOTORASIB",
        "gene_targets": ["KRAS"], "moa": "KRAS G12C inhibitor",
        "prioritized": True, "source_release": "oncref-25q4",
    }])
    repur = pd.DataFrame([
        {"compound_id": "BRD-SOMETHING", "drug_name": "SOTORASIB",
         "gene_targets": ["KRAS"], "moa": "KRAS inhibitor",
         "prioritized": False, "source_release": "repurposing-24q2"},
        {"compound_id": "BRD-A04843135", "drug_name": "LONAFARNIB",
         "gene_targets": ["KRAS", "HRAS", "NRAS", "FNTA"],
         "moa": "FTase inhibitor",
         "prioritized": False, "source_release": "repurposing-24q2"},
    ])
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


def test_classify_prism_activity_clinically_active_no_activity():
    """Phase 1+ compound exists but no measured Log2AUC → still clinically_active."""
    assert pc.classify_prism_activity(2, "phase_1_plus", None) == pc.CLASS_CLINICALLY_ACTIVE
    # And even with weak/flat Log2AUC — clinical presence still counts
    assert pc.classify_prism_activity(2, "phase_1_plus", -0.02) == pc.CLASS_CLINICALLY_ACTIVE


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
        {"lineage": "Bowel",    "median_log2auc": -0.40},
        {"lineage": "Pancreas", "median_log2auc": -0.20},
        {"lineage": "Lung",     "median_log2auc": -0.02},
        {"lineage": "Skin",     "median_log2auc": 0.02},
    ]
    assert pc.classify_prism_lineage_selectivity(entries) == pc.LINEAGE_SEL_SELECTIVE


def test_classify_prism_lineage_selectivity_broadly_active():
    """Most lineages active but no clear inactive contrast → broadly_active."""
    entries = [
        {"lineage": "Bowel",    "median_log2auc": -0.40},
        {"lineage": "Pancreas", "median_log2auc": -0.30},
        {"lineage": "Lung",     "median_log2auc": -0.25},
        {"lineage": "Skin",     "median_log2auc": -0.20},
        {"lineage": "Bladder",  "median_log2auc": -0.18},
    ]
    assert pc.classify_prism_lineage_selectivity(entries) == pc.LINEAGE_SEL_BROADLY_ACTIVE


def test_classify_prism_lineage_selectivity_no_signal():
    """No active lineages → no_lineage_signal."""
    entries = [
        {"lineage": "Bowel",    "median_log2auc": -0.04},
        {"lineage": "Pancreas", "median_log2auc": -0.02},
        {"lineage": "Lung",     "median_log2auc": 0.00},
    ]
    assert pc.classify_prism_lineage_selectivity(entries) == pc.LINEAGE_SEL_NO_SIGNAL


def test_classify_prism_lineage_selectivity_data_unavailable_when_empty():
    assert pc.classify_prism_lineage_selectivity([]) == pc.LINEAGE_SEL_DATA_UNAVAILABLE


# ---------------------------------------------------------------------------
# Model.csv loader
# ---------------------------------------------------------------------------

def test_load_model_to_lineage_basic():
    csv = (
        "ModelID,OncotreeLineage,Extra\n"
        "ACH-000001,Bowel,x\n"
        "ACH-000002,Lung,x\n"
        "ACH-000003,,x\n"
        "ACH-000004,Pancreas,x\n"
    )
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
    merged = pd.DataFrame([
        {"compound_id": "PRC-001", "drug_name": "SOTORASIB",
         "gene_targets": ["KRAS"], "moa": "KRAS G12C",
         "prioritized": True, "source_release": "oncref-25q4"},
        {"compound_id": "BRD-A04843135", "drug_name": "LONAFARNIB",
         "gene_targets": ["KRAS", "HRAS", "NRAS", "FNTA"], "moa": "FTase",
         "prioritized": False, "source_release": "repurposing-24q2"},
    ])
    oncref_log2auc = pd.DataFrame([
        {"model_id": "ACH-1", "compound_id": "PRC-001", "log2auc": -0.4, "source_release": "oncref-25q4"},
        {"model_id": "ACH-2", "compound_id": "PRC-001", "log2auc": -0.2, "source_release": "oncref-25q4"},
        {"model_id": "ACH-3", "compound_id": "PRC-001", "log2auc": -0.05, "source_release": "oncref-25q4"},
    ])
    oncref_lfccollapsed = pd.DataFrame([
        {"model_id": "ACH-1", "compound_id": "PRC-001", "min_lfc": -3.5, "source_release": "oncref-25q4"},
        {"model_id": "ACH-2", "compound_id": "PRC-001", "min_lfc": -1.2, "source_release": "oncref-25q4"},
    ])
    repurposing_lfc = pd.DataFrame([
        {"model_id": "ACH-1", "compound_id": "BRD-A04843135", "median_lfc": -0.5, "source_release": "repurposing-24q2"},
        {"model_id": "ACH-2", "compound_id": "BRD-A04843135", "median_lfc": -0.3, "source_release": "repurposing-24q2"},
    ])
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
    merged = pd.DataFrame([{
        "compound_id": "BRD-XYZ", "drug_name": "ONLY_ANNOTATED",
        "gene_targets": ["GHOST"], "moa": "unknown",
        "prioritized": False, "source_release": "repurposing-24q2",
    }])
    agg = pc.build_gene_aggregate(merged)
    g = agg[agg["gene_symbol"] == "GHOST"].iloc[0]
    assert g["n_compounds_targeting"] == 1
    assert g["median_log2auc_across_compounds"] is None
    assert g["prism_activity_class"] == pc.CLASS_TOOL_COMPOUND_ONLY


def test_build_gene_aggregate_lineage_selective():
    """KRAS in Bowel/Pancreas → active (Log2AUC < -0.15); Lung → inactive (> -0.05).
    Expected: lineage_selective."""
    merged = pd.DataFrame([
        {"compound_id": "PRC-001", "drug_name": "SOTORASIB",
         "gene_targets": ["KRAS"], "moa": "KRAS G12C",
         "prioritized": True, "source_release": "oncref-25q4"},
    ])
    bowel = [f"ACH-B-{i:03d}" for i in range(5)]
    pancreas = [f"ACH-P-{i:03d}" for i in range(5)]
    lung = [f"ACH-L-{i:03d}" for i in range(5)]
    log2auc_rows = []
    # Bowel: Log2AUC = -0.4 (active)
    log2auc_rows += [{"model_id": m, "compound_id": "PRC-001", "log2auc": -0.4,
                      "source_release": "oncref-25q4"} for m in bowel]
    # Pancreas: Log2AUC = -0.2 (active)
    log2auc_rows += [{"model_id": m, "compound_id": "PRC-001", "log2auc": -0.2,
                      "source_release": "oncref-25q4"} for m in pancreas]
    # Lung: Log2AUC = 0.0 (inactive)
    log2auc_rows += [{"model_id": m, "compound_id": "PRC-001", "log2auc": 0.0,
                      "source_release": "oncref-25q4"} for m in lung]
    oncref_log2auc = pd.DataFrame(log2auc_rows)
    model_to_lineage = {**{m: "Bowel" for m in bowel},
                         **{m: "Lung" for m in lung},
                         **{m: "Pancreas" for m in pancreas}}
    agg = pc.build_gene_aggregate(merged, oncref_log2auc=oncref_log2auc,
                                    model_to_lineage=model_to_lineage)
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
    merged = pd.DataFrame([
        {"compound_id": "PRC-001", "drug_name": "TESTCMPD",
         "gene_targets": ["TARGET"], "moa": "test",
         "prioritized": True, "source_release": "oncref-25q4"},
    ])
    bowel = [f"ACH-B-{i:03d}" for i in range(5)]
    rare = [f"ACH-R-{i:03d}" for i in range(2)]
    log2auc = pd.DataFrame(
        [{"model_id": m, "compound_id": "PRC-001", "log2auc": -0.3,
          "source_release": "oncref-25q4"} for m in bowel] +
        [{"model_id": m, "compound_id": "PRC-001", "log2auc": -0.5,
          "source_release": "oncref-25q4"} for m in rare]
    )
    model_to_lineage = {**{m: "Bowel" for m in bowel}, **{m: "RareLineage" for m in rare}}
    agg = pc.build_gene_aggregate(merged, oncref_log2auc=log2auc, model_to_lineage=model_to_lineage)
    tgt = agg[agg["gene_symbol"] == "TARGET"].iloc[0]
    lineages = {e["lineage"] for e in tgt["per_lineage_activity"]}
    assert lineages == {"Bowel"}


def test_build_gene_aggregate_no_model_map():
    """When model_to_lineage is None, per_lineage_activity stays empty."""
    merged = pd.DataFrame([
        {"compound_id": "PRC-001", "drug_name": "SOTORASIB",
         "gene_targets": ["KRAS"], "moa": "KRAS G12C",
         "prioritized": True, "source_release": "oncref-25q4"},
    ])
    oncref_log2auc = pd.DataFrame([
        {"model_id": "ACH-1", "compound_id": "PRC-001", "log2auc": -0.5,
         "source_release": "oncref-25q4"},
    ])
    agg = pc.build_gene_aggregate(merged, oncref_log2auc=oncref_log2auc)
    kras = agg[agg["gene_symbol"] == "KRAS"].iloc[0]
    assert kras["per_lineage_activity"] == []
    assert kras["prism_lineage_selectivity"] == pc.LINEAGE_SEL_DATA_UNAVAILABLE


def test_write_gene_aggregate_parquet_roundtrip(tmp_path):
    """v3 parquet writer roundtrips full schema including best_responder_lfc + metric_source."""
    import pyarrow.parquet as pq
    df = pd.DataFrame([
        {
            "gene_symbol": "KRAS",
            "n_compounds_targeting": 2,
            "highest_clinical_phase": "phase_1_plus",
            "median_log2auc_across_compounds": -0.25,
            "top_compounds": [
                {"compound_id": "PRC-001", "drug_name": "SOTORASIB", "moa": "G12C",
                 "median_log2auc": -0.20, "best_responder_lfc": -3.5,
                 "single_dose_lfc": None,
                 "n_lines_screened": 300, "polyselective": False,
                 "n_annotated_targets": 1, "source_release": "oncref-25q4",
                 "prioritized": True, "metric_source": "log2auc"},
            ],
            "prism_activity_class": pc.CLASS_CLINICALLY_ACTIVE,
            "per_lineage_activity": [
                {"lineage": "Bowel", "n_lines_screened": 45,
                 "median_log2auc": -0.4, "best_responder_lfc": -4.5,
                 "top_compound_in_lineage": "SOTORASIB", "n_compounds_evaluated": 1},
            ],
            "prism_lineage_selectivity": pc.LINEAGE_SEL_SELECTIVE,
        }
    ])
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
