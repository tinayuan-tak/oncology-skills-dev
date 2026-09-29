"""Synthetic offline tests for the by-subgroup fusion-recurrence panorama (scope-coherence Phase 3).

No S3: the consensus event table + the assayed-coverage sibling are monkeypatched with in-memory
DataFrames, and the subgroup resolver is stubbed. Verifies the per-stratum denominator (assayed samples),
the id-grain patient normalization, honest evidence_state, and the cross-stratum panorama."""

from __future__ import annotations

import pandas as pd

import methods.tcga_fusion_consensus.stratified as strat
from methods.subgroup_common import iteration


def _pts(prefix, n):
    return [f"TCGA-{prefix}-{i:04d}" for i in range(n)]


def _install(monkeypatch, consensus_rows, coverage_pts_by_tissue):
    monkeypatch.setattr(strat, "_load_consensus", lambda: pd.DataFrame(consensus_rows))
    cov = [{"sample_key": f"{p}-01", "tissue": t} for t, pts in coverage_pts_by_tissue.items() for p in pts]
    monkeypatch.setattr(strat, "_load_coverage", lambda: pd.DataFrame(cov))


def _row(pid, partner=None):
    return {
        "gene_symbol": "FUSG",
        "caller_count": 3,
        "tissue": "COAD",
        "sample_key": f"{pid}-01",
        "partners_tumorfusions": [partner] if partner else [],
        "partners_gao_2018": [],
        "partners_cbioportal": [],
    }


def test_recurrent_partner_within_stratum_is_driver(monkeypatch):
    msi = _pts("AA", 40)
    rows = [_row(p, "PARTX") for p in msi[:4]]  # same partner in 4 stratum patients
    _install(monkeypatch, rows, {"COAD": msi})
    rec = strat.read_stratified_fusion("FUSG", "COADREAD", _sample_id_filter=set(msi))
    assert rec["subgroup_n"] == 40  # assayed denominator (not the fused count)
    assert rec["evidence_state"] == "measured"
    assert rec["fusion_class"] == "recurrent_fusion_driver"
    assert rec["fusion_recurrence_confidence"] == "high_recurrent_partner"
    assert rec["n_samples_with_fusion"] == 4


def test_well_assayed_zero_fusion_stratum_is_measured_negative(monkeypatch):
    """evidence_state keys on the DENOMINATOR: a well-assayed stratum with no fusions is a measured
    negative (no_recurrent_fusion), NOT absent."""
    mss = _pts("BB", 35)
    _install(monkeypatch, [], {"COAD": mss})  # coverage present, no fusion events
    rec = strat.read_stratified_fusion("FUSG", "COADREAD", _sample_id_filter=set(mss))
    assert rec["subgroup_n"] == 35 and rec["evidence_state"] == "measured"
    assert rec["fusion_class"] == "no_recurrent_fusion"
    assert rec["n_samples_with_fusion"] == 0 and rec["fusion_frequency"] == 0.0


def test_no_coverage_for_stratum_is_absent(monkeypatch):
    _install(monkeypatch, [], {"COAD": _pts("CC", 10)})
    rec = strat.read_stratified_fusion("FUSG", "COADREAD", _sample_id_filter={"TCGA-ZZ-9999"})
    assert rec["subgroup_n"] == 0 and rec["evidence_state"] == "absent"
    assert rec["fusion_class"] == "data_unavailable"


def test_panorama_two_strata(monkeypatch):
    msi, mss = _pts("DA", 40), _pts("DB", 40)
    rows = [_row(p, "PARTX") for p in msi[:5]]  # MSI: recurrent; MSS: none
    _install(monkeypatch, rows, {"COAD": msi + mss})
    monkeypatch.setattr(
        iteration,
        "resolve_subgroup_cohort",
        lambda manifest, sid, data_catalog_repo=None: {"MSI": set(msi), "MSS": set(mss)}[sid],
    )
    pan = strat.build_fusion_panorama(
        "FUSG",
        "COADREAD",
        subgroups=["MSI", "MSS"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1",
    )
    rows_by = {r["stratum"]: r for r in pan["per_subgroup_metrics"]}
    assert rows_by["MSI"]["class"] == "recurrent_fusion_driver"
    assert rows_by["MSS"]["class"] == "no_recurrent_fusion"
    assert pan["n_subgroups_with_data"] == 2
