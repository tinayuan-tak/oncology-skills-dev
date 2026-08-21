"""Unit tests for the CPTAC MMR-IHC -> MSI_H/MSS assigner (pure logic, no S3/XLSX)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.subgroup_assigner_cptac_mmr.cli import (  # noqa: E402
    classify_msi_from_mmr, build_assignments, strata_summary, DERIVATION_SOURCE)


# ── classify_msi_from_mmr ──────────────────────────────────────────────────────────────────────

def test_classify_dmmr_any_loss_is_msi_h():
    status, lost = classify_msi_from_mmr(
        {"MLH1": "MLH1-not expressed", "PMS2": "PMS2-not expressed",
         "MSH2": "MSH2-expressed", "MSH6": "MSH6-expressed"})
    assert status == "MSI_H"
    assert lost == ["MLH1", "PMS2"]


def test_classify_all_expressed_is_mss():
    status, lost = classify_msi_from_mmr({p: f"{p}-expressed" for p in
                                          ("MLH1", "MSH2", "PMS2", "MSH6")})
    assert status == "MSS" and lost == []


def test_classify_all_not_tested_is_undetermined_not_mss():
    # the critical guard: absence of testing is NOT evidence of MSS
    status, _ = classify_msi_from_mmr({p: f"{p}-not tested" for p in
                                       ("MLH1", "MSH2", "PMS2", "MSH6")})
    assert status is None
    assert classify_msi_from_mmr({})[0] is None
    assert classify_msi_from_mmr({"MLH1": "", "MSH2": None})[0] is None


def test_classify_partial_testing_one_expressed_is_mss():
    # one informative "expressed" call, rest not tested -> pMMR/MSS (>=1 informative, no loss)
    status, _ = classify_msi_from_mmr(
        {"MLH1": "MLH1-expressed", "MSH2": "MSH2-not tested", "PMS2": "", "MSH6": None})
    assert status == "MSS"


# ── build_assignments (tall shard) ─────────────────────────────────────────────────────────────

def _frames():
    aliquots = pd.DataFrame({"aliquot_submitter_id": ["AL_MSI", "AL_MSS", "AL_UNK", "AL_NOCASE"]})
    bridge = pd.DataFrame({
        "aliquot_submitter_id": ["AL_MSI", "AL_MSS", "AL_UNK"],   # AL_NOCASE deliberately absent
        "case_submitter_id":    ["01CO_MSI", "01CO_MSS", "01CO_UNK"]})
    clinical = pd.DataFrame({
        "case_submitter_id": ["01CO_MSI", "01CO_MSS", "01CO_UNK"],
        "MLH1": ["MLH1-not expressed", "MLH1-expressed", "MLH1-not tested"],
        "MSH2": ["MSH2-expressed", "MSH2-expressed", "MSH2-not tested"],
        "PMS2": ["PMS2-not expressed", "PMS2-expressed", "PMS2-not tested"],
        "MSH6": ["MSH6-expressed", "MSH6-expressed", "MSH6-not tested"]})
    return aliquots, bridge, clinical


def test_build_assignments_shape_and_tri_value():
    aliquots, bridge, clinical = _frames()
    df = build_assignments(aliquots, bridge, clinical)
    # canonical row schema
    assert list(df.columns) == ["sample_id", "patient_id", "source_native_id", "stratum_id",
                                "is_member", "derivation_source", "derivation_value"]
    # every aliquot emits BOTH strata rows (4 aliquots x 2 strata = 8) — none dropped
    assert len(df) == 8
    assert set(df["derivation_source"]) == {DERIVATION_SOURCE}

    def cell(al, st):
        r = df[(df["sample_id"] == al) & (df["stratum_id"] == st)].iloc[0]
        return r["is_member"], r["derivation_value"]

    # dMMR aliquot: member of MSI_H (with trail), non-member of MSS
    assert cell("AL_MSI", "MSI_H") == (True, "dMMR:MLH1,PMS2")
    assert cell("AL_MSI", "MSS")[0] is False
    # pMMR aliquot: member of MSS, non-member of MSI_H
    assert cell("AL_MSS", "MSS") == (True, "pMMR")
    assert cell("AL_MSS", "MSI_H")[0] is False
    # not-tested aliquot: undetermined -> is_member None for BOTH strata (tri-value)
    assert cell("AL_UNK", "MSI_H")[0] is None and cell("AL_UNK", "MSS")[0] is None
    # aliquot with no case bridge -> also undetermined, still present (honest coverage)
    assert cell("AL_NOCASE", "MSI_H")[0] is None


def test_strata_summary_counts():
    df = build_assignments(*_frames())
    s = strata_summary(df)
    assert s["MSI_H"]["n_member"] == 1        # AL_MSI
    assert s["MSS"]["n_member"] == 1          # AL_MSS
    assert s["MSI_H"]["n_undetermined"] == 2  # AL_UNK + AL_NOCASE
    assert s["MSI_H"]["n_non_member"] == 1    # AL_MSS is an evaluated MSI_H non-member
