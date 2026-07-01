"""Synthetic tests for the PRISM precompute — parses + aggregates + classifier."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_prism_precompute import cli as pc  # noqa: E402


# ---------------------------------------------------------------------------
# Compound-list parsers
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
        "P1,PRC-003,OncRef 24Q2,FALSE,BAY-293,SOS1 inhibitor,C3,,SOS1,SYN\n"
    )
    df = pc.load_oncref_compound_list(csv.encode())
    assert len(df) == 3
    assert df.iloc[0]["compound_id"] == "PRC-001"
    assert df.iloc[0]["drug_name"] == "SOTORASIB"
    assert df.iloc[0]["gene_targets"] == ["KRAS"]
    assert df.iloc[0]["prioritized"] is True or df.iloc[0]["prioritized"] == True
    assert df.iloc[2]["prioritized"] is False or df.iloc[2]["prioritized"] == False
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
    assert df.iloc[0]["compound_id"] == "BRD-A04843135"  # trimmed to 2 hyphen segments
    assert df.iloc[0]["drug_name"] == "LONAFARNIB"
    assert set(df.iloc[0]["gene_targets"]) == {"KRAS", "HRAS", "NRAS", "FNTA"}
    assert df.iloc[2]["gene_targets"] == []  # empty repurposing_target
    assert (df["source_release"] == "repurposing-24q2").all()


# ---------------------------------------------------------------------------
# LFC loaders
# ---------------------------------------------------------------------------

def test_load_oncref_lfc_shape():
    """Wide OncRef matrix melted + doses collapsed per compound."""
    csv = (
        ",SOTORASIB (PRC-001) @0.01 uM,SOTORASIB (PRC-001) @1.0 uM,ADAGRASIB (PRC-002) @1.0 uM\n"
        "ACH-000001,-2.5,-2.8,-1.2\n"
        "ACH-000002,-0.1,-0.15,0.05\n"
    )
    df = pc.load_oncref_lfc(csv.encode())
    # Should collapse doses: 2 compounds × 2 cell lines = 4 rows
    assert len(df) == 4
    assert set(df["model_id"]) == {"ACH-000001", "ACH-000002"}
    assert set(df["compound_id"]) == {"PRC-001", "PRC-002"}
    # ACH-000001 × PRC-001: median of (-2.5, -2.8) = -2.65
    sub = df[(df["model_id"] == "ACH-000001") & (df["compound_id"] == "PRC-001")]
    assert sub.iloc[0]["median_lfc"] == pytest.approx(-2.65, abs=1e-2)


def test_load_repurposing_lfc_filters_and_qc():
    """Long Repurposing LFC filtered by wanted compound-IDs, QC-failures dropped."""
    csv = (
        "row_id,broad_id,dose,compound_plate,screen,culture,LFC\n"
        "ACH-000001::P1::PR500B::REP300,BRD-A04843135-001-09-9,2.5,PREP053,REP300,PR500B,-2.5\n"
        "ACH-000002::P1::PR500B::REP300,BRD-A04843135-001-09-9,2.5,PREP053,REP300,PR500B,-1.5\n"
        "ACH-000001::P1::PR500B::REP300,BRD-A99999999-001-01-1 - QC Failure,2.5,PREP053,REP300,PR500B,0.5\n"
        "ACH-000001::P1::PR500B::REP300,BRD-A11111111-001-01-1,2.5,PREP053,REP300,PR500B,-0.3\n"
    )
    wanted = {"BRD-A04843135", "BRD-A11111111"}  # note: NOT the QC-fail one
    df = pc.load_repurposing_lfc(csv.encode(), wanted)
    # QC-failure row dropped; only wanted compounds present
    assert set(df["compound_id"]) == wanted
    lonaf = df[df["compound_id"] == "BRD-A04843135"]
    assert len(lonaf) == 2
    assert lonaf[lonaf["model_id"] == "ACH-000001"]["median_lfc"].iloc[0] == pytest.approx(-2.5)


# ---------------------------------------------------------------------------
# Cross-release merge
# ---------------------------------------------------------------------------

def test_merge_compound_universes_prefers_oncref():
    """When the same drug_name exists in both, OncRef row wins."""
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
    # SOTORASIB should be from OncRef; LONAFARNIB from Repurposing
    sot = merged[merged["drug_name"].str.upper() == "SOTORASIB"]
    assert len(sot) == 1
    assert sot.iloc[0]["source_release"] == "oncref-25q4"
    lon = merged[merged["drug_name"].str.upper() == "LONAFARNIB"]
    assert len(lon) == 1
    assert lon.iloc[0]["source_release"] == "repurposing-24q2"


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def test_classify_prism_activity_no_compounds():
    assert pc.classify_prism_activity(0, "tool", None) == pc.CLASS_NO_COMPOUNDS_FOUND


def test_classify_prism_activity_clinically_active_with_activity():
    """Phase 1+ compound with negative pan-cancer LFC → clinically_active."""
    assert pc.classify_prism_activity(2, "phase_1_plus", -1.5) == pc.CLASS_CLINICALLY_ACTIVE


def test_classify_prism_activity_clinically_active_no_lfc():
    """Phase 1+ compound exists but no measured activity — still clinically_active
    because the framework rewards CLINICAL PRESENCE, not just pan-cancer signal."""
    assert pc.classify_prism_activity(2, "phase_1_plus", None) == pc.CLASS_CLINICALLY_ACTIVE
    # And even with weak/flat activity — clinical presence still counts
    assert pc.classify_prism_activity(2, "phase_1_plus", -0.1) == pc.CLASS_CLINICALLY_ACTIVE


def test_classify_prism_activity_weakly_active():
    assert pc.classify_prism_activity(3, "tool", -0.8) == pc.CLASS_WEAKLY_ACTIVE


def test_classify_prism_activity_tool_only():
    assert pc.classify_prism_activity(3, "tool", -0.1) == pc.CLASS_TOOL_COMPOUND_ONLY


# ---------------------------------------------------------------------------
# End-to-end: build gene aggregate
# ---------------------------------------------------------------------------

def test_build_gene_aggregate_kras_case():
    """LONAFARNIB (poly, Repurposing) + SOTORASIB (KRAS-only, OncRef prioritized)
    → KRAS gene row shows n_compounds_targeting=2, class=clinically_active."""
    merged = pd.DataFrame([
        {"compound_id": "PRC-001", "drug_name": "SOTORASIB",
         "gene_targets": ["KRAS"], "moa": "KRAS G12C",
         "prioritized": True, "source_release": "oncref-25q4"},
        {"compound_id": "BRD-A04843135", "drug_name": "LONAFARNIB",
         "gene_targets": ["KRAS", "HRAS", "NRAS", "FNTA"], "moa": "FTase",
         "prioritized": False, "source_release": "repurposing-24q2"},
    ])
    lfc_by_release = {
        "oncref-25q4": pd.DataFrame([
            {"model_id": "ACH-1", "compound_id": "PRC-001", "median_lfc": -2.5},
            {"model_id": "ACH-2", "compound_id": "PRC-001", "median_lfc": -1.8},
            {"model_id": "ACH-3", "compound_id": "PRC-001", "median_lfc": -0.2},
        ]),
        "repurposing-24q2": pd.DataFrame([
            {"model_id": "ACH-1", "compound_id": "BRD-A04843135", "median_lfc": -0.5},
            {"model_id": "ACH-2", "compound_id": "BRD-A04843135", "median_lfc": -0.3},
        ]),
    }
    agg = pc.build_gene_aggregate(merged, lfc_by_release)
    kras = agg[agg["gene_symbol"] == "KRAS"]
    assert len(kras) == 1
    k = kras.iloc[0]
    assert k["n_compounds_targeting"] == 2
    assert k["highest_clinical_phase"] == "phase_1_plus"   # any prioritized OncRef → phase_1_plus
    assert k["prism_activity_class"] == pc.CLASS_CLINICALLY_ACTIVE
    # top_compounds: SOTORASIB should rank ahead of LONAFARNIB (better median LFC + prioritized)
    top = k["top_compounds"]
    assert len(top) == 2
    assert top[0]["drug_name"] == "SOTORASIB"
    assert top[0]["prioritized"] is True or top[0]["prioritized"] == True
    assert top[1]["drug_name"] == "LONAFARNIB"
    assert top[1]["polyselective"] is True or top[1]["polyselective"] == True
    assert top[1]["n_annotated_targets"] == 4
    # HRAS, NRAS, FNTA should also have gene rows (from LONAFARNIB)
    assert set(agg["gene_symbol"]) == {"KRAS", "HRAS", "NRAS", "FNTA"}
    hras = agg[agg["gene_symbol"] == "HRAS"].iloc[0]
    assert hras["n_compounds_targeting"] == 1  # only LONAFARNIB
    # Tool-compound-only class since only Repurposing entry, no prio, mean LFC weak
    assert hras["prism_activity_class"] == pc.CLASS_TOOL_COMPOUND_ONLY


def test_build_gene_aggregate_no_lfc_data():
    """Compound annotated but not in LFC → still shows up in top_compounds with
    null activity; gene passes into tool_compound_only class."""
    merged = pd.DataFrame([{
        "compound_id": "BRD-XYZ", "drug_name": "ONLY_ANNOTATED",
        "gene_targets": ["GHOST"], "moa": "unknown",
        "prioritized": False, "source_release": "repurposing-24q2",
    }])
    agg = pc.build_gene_aggregate(merged, {"repurposing-24q2": pd.DataFrame(
        columns=["model_id", "compound_id", "median_lfc"]
    )})
    g = agg[agg["gene_symbol"] == "GHOST"].iloc[0]
    assert g["n_compounds_targeting"] == 1
    assert g["median_lfc_across_compounds"] is None or pd.isna(g["median_lfc_across_compounds"])
    assert g["prism_activity_class"] == pc.CLASS_TOOL_COMPOUND_ONLY
    assert g["top_compounds"][0]["median_lfc"] is None


def test_write_gene_aggregate_parquet_roundtrip(tmp_path):
    """Full write + read path — verifies pyarrow struct-list schema roundtrips."""
    import pyarrow.parquet as pq
    df = pd.DataFrame([
        {
            "gene_symbol": "KRAS",
            "n_compounds_targeting": 2,
            "highest_clinical_phase": "phase_1_plus",
            "median_lfc_across_compounds": -1.3,
            "top_compounds": [
                {"compound_id": "PRC-001", "drug_name": "SOTORASIB", "moa": "G12C",
                 "median_lfc": -2.5, "fraction_lines_responding": 0.6,
                 "n_lines_screened": 300, "polyselective": False,
                 "n_annotated_targets": 1, "source_release": "oncref-25q4",
                 "prioritized": True},
            ],
            "prism_activity_class": pc.CLASS_CLINICALLY_ACTIVE,
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
