"""Synthetic-data test for the subgroup-stratified dependency reader.

The SECOND panorama substrate (dependency, not mutation) — proves the
subgroup_common.panorama composer is substrate-agnostic. Builds a synthetic
Chronos parquet + assignments parquet with a KNOWN answer: target is a strong
dependency in stratum DEP (median ~ -1.5) and non-dependent in stratum INDEP
(median ~ 0.0). No S3 / real-data dependency.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _build_synthetic_chronos(path: Path, n_dep=40, n_indep=40):
    """Chronos matrix: DEP lines strongly depend on TESTGENE, INDEP lines don't."""
    rng = np.random.default_rng(7)
    dep_ids = [f"ACH-D{i:04d}" for i in range(n_dep)]
    indep_ids = [f"ACH-I{i:04d}" for i in range(n_indep)]
    rows = []
    for mid in dep_ids:
        rows.append({"ModelID": mid, "TESTGENE (99999)": rng.normal(-1.5, 0.2), "OTHER (1)": rng.normal(0, 0.2)})
    for mid in indep_ids:
        rows.append({"ModelID": mid, "TESTGENE (99999)": rng.normal(0.0, 0.2), "OTHER (1)": rng.normal(0, 0.2)})
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path)
    return dep_ids, indep_ids


def _build_assignments(assign_cache: Path, manifest_id: str, dep_ids, indep_ids):
    d = assign_cache / manifest_id
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for mid in dep_ids:
        rows.append(
            {
                "sample_id": mid,
                "patient_id": None,
                "source_native_id": mid,
                "stratum_id": "DEP",
                "is_member": True,
                "derivation_source": "synthetic",
                "derivation_value": "",
                "evaluated_at_release": "test",
            }
        )
    for mid in indep_ids:
        rows.append(
            {
                "sample_id": mid,
                "patient_id": None,
                "source_native_id": mid,
                "stratum_id": "INDEP",
                "is_member": True,
                "derivation_source": "synthetic",
                "derivation_value": "",
                "evaluated_at_release": "test",
            }
        )
    pd.DataFrame(rows).to_parquet(d / "assignments.parquet")


@pytest.fixture
def synthetic_env(tmp_path, monkeypatch):
    from onc_methods.subgroup_common import loaders

    chronos = tmp_path / "chronos" / "CRISPRGeneEffect.parquet"
    dep_ids, indep_ids = _build_synthetic_chronos(chronos)
    assign = tmp_path / "assign"
    _build_assignments(assign, "dep-synth-v1", dep_ids, indep_ids)
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", assign)
    loaders.clear_all_caches()
    return {"chronos": chronos, "manifest_id": "dep-synth-v1"}


def test_dependency_panorama_separates_strata(synthetic_env):
    from onc_methods.depmap_chronos.read import build_dependency_panorama

    pan = build_dependency_panorama(
        "TESTGENE",
        "COADREAD",
        subgroups=["DEP", "INDEP"],
        subgroup_assignments_manifest=synthetic_env["manifest_id"],
        chronos_parquet=synthetic_env["chronos"],
    )
    by = {r["stratum"]: r for r in pan["per_subgroup_metrics"]}
    assert by["DEP"]["median_chronos"] < -1.0
    assert by["DEP"]["class"] == "strong_dependency"
    assert by["DEP"]["evidence_state"] == "measured"  # n=40 clears floor
    assert by["INDEP"]["median_chronos"] > -0.5
    assert by["INDEP"]["class"] == "not_dependent"
    # cross-subgroup dependency delta is large + positive (≈1.5)
    assert pan["cross_subgroup_delta_dependency"] > 1.0
    # mandatory provenance stamp
    assert by["DEP"]["source_cohort"] == "DepMap-26Q3"


def test_scalar_path_whole_panel(synthetic_env):
    """No subgroups → whole-panel median (mix of dep + indep → intermediate)."""
    from onc_methods.depmap_chronos.read import read_stratified_dependency

    rec = read_stratified_dependency("TESTGENE", "COADREAD", chronos_parquet=synthetic_env["chronos"])
    assert rec["subgroup_n"] == 80
    assert -1.0 < rec["median_chronos"] < 0.0  # blended


def test_missing_gene_returns_absent(synthetic_env):
    from onc_methods.depmap_chronos.read import read_stratified_dependency

    rec = read_stratified_dependency("NOSUCHGENE", "COADREAD", chronos_parquet=synthetic_env["chronos"])
    assert rec["evidence_state"] == "absent"
    assert rec["dependency_class"] == "insufficient"
