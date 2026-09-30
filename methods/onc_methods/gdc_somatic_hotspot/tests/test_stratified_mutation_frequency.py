"""Synthetic-data test for the subgroup-stratified mutation-frequency reader.

Validates the descriptive-panorama path (Phase-3 enumeration case):
  - read_stratified_mutation_frequency recomputes frequency WITHIN a subgroup
    member-set (compute rerun, not a filter over a pre-aggregated value)
  - the @subgroup_iterable decorator fans out to {stratum: record}
  - build_mutation_frequency_panorama shapes the per_subgroup_metrics list
  - subgroup_n_floor_met flags small strata
  - backward-compat scalar path (no subgroups) returns the whole-cohort record

No S3 / real-data dependency: builds a synthetic MC3 MAF parquet + a synthetic
subgroup-assignments parquet in tmp caches with a KNOWN answer (target mutated
in every "MUT_HI" sample, in none of "MUT_LO"), then asserts the recomputed
per-stratum frequencies match.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _build_synthetic_maf(maf_cache: Path, indication: str) -> set[str]:
    """20 samples; TESTGENE mutated in s00..s09 (10/20 = 0.50 overall)."""
    maf_cache.mkdir(parents=True, exist_ok=True)
    rows = []
    samples = [f"TCGA-XX-{i:04d}" for i in range(20)]
    for i, sid in enumerate(samples):
        # Every sample has a background mutation so it's in the cohort denominator.
        rows.append(
            {
                "gene_symbol": "BACKGROUND",
                "protein_change": "p.X1Y",
                "sample_id": sid,
                "patient_id": sid,
                "source_native_id": sid,
                "effect": "Missense_Mutation",
            }
        )
        if i < 10:  # first 10 carry TESTGENE
            change = "p.G12D" if i < 6 else "p.G12C"
            rows.append(
                {
                    "gene_symbol": "TESTGENE",
                    "protein_change": change,
                    "sample_id": sid,
                    "patient_id": sid,
                    "source_native_id": sid,
                    "effect": "Missense_Mutation",
                }
            )
    pd.DataFrame(rows).to_parquet(maf_cache / f"{indication.lower()}-mc3.parquet")
    return set(samples)


def _build_synthetic_assignments(assign_cache: Path, manifest_id: str) -> None:
    """Two strata: MUT_HI = s00..s07 (8 of the 10 mutated), MUT_LO = s10..s19.

    Expected within-stratum TESTGENE frequency:
      MUT_HI: 8/8 = 1.0   (all members carry it)
      MUT_LO: 0/10 = 0.0  (none carry it)
    """
    d = assign_cache / manifest_id
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(20):
        sid = f"TCGA-XX-{i:04d}"
        for stratum in ("MUT_HI", "MUT_LO"):
            if stratum == "MUT_HI":
                is_member = i < 8
            else:
                is_member = i >= 10
            rows.append(
                {
                    "sample_id": sid,
                    "patient_id": sid,
                    "source_native_id": sid,
                    "stratum_id": stratum,
                    "is_member": is_member,
                    "derivation_source": "synthetic",
                    "derivation_value": "",
                    "evaluated_at_release": "test",
                }
            )
    pd.DataFrame(rows).to_parquet(d / "assignments.parquet")


@pytest.fixture
def synthetic_env(tmp_path, monkeypatch):
    from onc_methods.subgroup_common import loaders

    maf_cache = tmp_path / "maf"
    assign_cache = tmp_path / "assignments"
    _build_synthetic_maf(maf_cache, "COADREAD")
    _build_synthetic_assignments(assign_cache, "synthetic-assignments-v1")
    # Point the assignments loader at the tmp cache + clear lru_cache.
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", assign_cache)
    loaders.clear_all_caches()
    return {"maf_cache": maf_cache, "manifest_id": "synthetic-assignments-v1"}


def test_scalar_path_whole_cohort(synthetic_env):
    """No subgroups → whole-cohort frequency (10/20 = 0.5)."""
    from onc_methods.gdc_somatic_hotspot.read import read_stratified_mutation_frequency

    rec = read_stratified_mutation_frequency("TESTGENE", "COADREAD", maf_cache=synthetic_env["maf_cache"])
    assert rec["subgroup_n"] == 20
    assert rec["overall_mutation_frequency"] == 0.5
    assert rec["mutation_class"] == "recurrently_mutated"
    assert rec["subgroup_n_floor_met"] is False  # 20 < 30


def test_stratified_recomputes_within_member_set(synthetic_env):
    """Frequency is recomputed within each stratum denominator, not sliced from a global."""
    from onc_methods.gdc_somatic_hotspot.read import build_mutation_frequency_panorama

    pan = build_mutation_frequency_panorama(
        "TESTGENE",
        "COADREAD",
        subgroups=["MUT_HI", "MUT_LO"],
        subgroup_assignments_manifest=synthetic_env["manifest_id"],
        hotspot_changes=("p.G12D", "p.G12C"),
        maf_cache=synthetic_env["maf_cache"],
    )
    by = {r["stratum"]: r for r in pan["per_subgroup_metrics"]}
    assert by["MUT_HI"]["overall_mutation_frequency"] == 1.0
    assert by["MUT_HI"]["subgroup_n"] == 8
    assert by["MUT_LO"]["overall_mutation_frequency"] == 0.0
    assert by["MUT_LO"]["subgroup_n"] == 10
    # Descriptive metadata present on every record
    assert by["MUT_HI"]["subtype_defining_data"] == "genomic"
    assert by["MUT_HI"]["source_cohort"] == "TCGA-MC3"
    # B11-S2-1: both strata are UNDERPOWERED (n=8, 10 < the n-floor of 30), so neither may drive
    # the cross-stratum spread — they are inadmissible in comparative prose. The spread scalars are
    # therefore None (n_subgroups_measured=0), even though both are counted in n_subgroups_with_data.
    assert pan["cross_subgroup_delta_frequency"] is None
    assert pan["max_subgroup_frequency"] is None
    assert pan["n_subgroups_measured"] == 0
    assert pan["n_subgroups_with_data"] == 2


def test_hotspot_frequencies_within_stratum(synthetic_env):
    """Per-hotspot frequency also uses the stratum denominator."""
    from onc_methods.gdc_somatic_hotspot.read import build_mutation_frequency_panorama

    pan = build_mutation_frequency_panorama(
        "TESTGENE",
        "COADREAD",
        subgroups=["MUT_HI"],
        subgroup_assignments_manifest=synthetic_env["manifest_id"],
        hotspot_changes=("p.G12D", "p.G12C"),
        maf_cache=synthetic_env["maf_cache"],
    )
    hs = {h["protein_change"]: h for h in pan["per_subgroup_metrics"][0]["hotspot_frequencies"]}
    # s00..s05 = G12D (6), s06..s07 = G12C (2) within MUT_HI (n=8)
    assert hs["p.G12D"]["frequency"] == 0.75  # 6/8
    assert hs["p.G12C"]["frequency"] == 0.25  # 2/8


def test_evidence_state_trichotomy(synthetic_env):
    """measured (floor met) vs underpowered (floor not met) vs absent (n=0).

    The positive/negative/unknown distinction the selection principle requires:
    a real zero on a floor-clearing cohort must be 'measured', not conflated with
    'we can't tell'.
    """
    from onc_methods.gdc_somatic_hotspot.read import build_mutation_frequency_panorama

    # BACKGROUND gene is present in every sample; TESTGENE absent from MUT_LO.
    pan = build_mutation_frequency_panorama(
        "TESTGENE",
        "COADREAD",
        subgroups=["MUT_HI", "MUT_LO", "NONEXISTENT_STRATUM"],
        subgroup_assignments_manifest=synthetic_env["manifest_id"],
        maf_cache=synthetic_env["maf_cache"],
    )
    by = {r["stratum"]: r for r in pan["per_subgroup_metrics"]}
    # MUT_LO: freq 0.0 but only n=10 (< floor 30) → underpowered, NOT a trusted negative
    assert by["MUT_LO"]["overall_mutation_frequency"] == 0.0
    assert by["MUT_LO"]["evidence_state"] == "underpowered"
    # A stratum with no members at all → absent
    assert by["NONEXISTENT_STRATUM"]["subgroup_n"] == 0
    assert by["NONEXISTENT_STRATUM"]["evidence_state"] == "absent"


def test_floor_flag_true_for_large_stratum(synthetic_env, tmp_path, monkeypatch):
    """subgroup_n_floor_met flips True once a stratum clears SUBGROUP_N_FLOOR."""
    from onc_methods.gdc_somatic_hotspot import read as gsh_read
    from onc_methods.subgroup_common import loaders

    # Build a 40-sample cohort, all in one stratum.
    maf_cache = tmp_path / "maf2"
    maf_cache.mkdir()
    rows = []
    for i in range(40):
        sid = f"TCGA-YY-{i:04d}"
        rows.append(
            {
                "gene_symbol": "TESTGENE",
                "protein_change": "p.G12D",
                "sample_id": sid,
                "patient_id": sid,
                "source_native_id": sid,
                "effect": "Missense_Mutation",
            }
        )
    pd.DataFrame(rows).to_parquet(maf_cache / "coadread-mc3.parquet")
    assign = tmp_path / "assign2"
    d = assign / "big-v1"
    d.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "sample_id": f"TCGA-YY-{i:04d}",
                "patient_id": f"TCGA-YY-{i:04d}",
                "source_native_id": f"TCGA-YY-{i:04d}",
                "stratum_id": "BIG",
                "is_member": True,
                "derivation_source": "synthetic",
                "derivation_value": "",
                "evaluated_at_release": "test",
            }
            for i in range(40)
        ]
    ).to_parquet(d / "assignments.parquet")
    monkeypatch.setattr(loaders, "CACHE_ASSIGNMENTS", assign)
    loaders.clear_all_caches()
    pan = gsh_read.build_mutation_frequency_panorama(
        "TESTGENE", "COADREAD", subgroups=["BIG"], subgroup_assignments_manifest="big-v1", maf_cache=maf_cache
    )
    rec = pan["per_subgroup_metrics"][0]
    assert rec["subgroup_n"] == 40
    assert rec["subgroup_n_floor_met"] is True
