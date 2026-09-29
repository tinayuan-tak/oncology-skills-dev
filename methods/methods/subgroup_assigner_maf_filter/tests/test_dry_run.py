"""Smoke tests for subgroup_assigner_maf_filter CLI.

test_dry_run_on_coadread_tcga: dry-run picks up MAF-filter strata.
test_dry_run_on_paad_tcga: PAAD catalog (Phase 1b renamed from PDAC).
test_rule_compiler_supported_forms: unit tests for the MAF-predicate compiler.
test_real_execution_synthetic_tcga_maf: end-to-end with synthetic MAF.
"""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

# Portable repo roots: were hardcoded to the author's /home/sagemaker-user checkout, so these
# subprocess tests FileNotFoundError'd (cwd) the moment they ran anywhere else — including CI.
METHODS_REPO = Path(__file__).resolve().parents[3]
CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT") or METHODS_REPO.parent / "rnd-computational-biology-oncology-data-catalog"
)


def test_dry_run_on_coadread_tcga():
    """Dry-run picks up KRAS_mut, KRAS_G12C, BRAF_V600E from COADREAD catalog."""
    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "COADREAD" / "2026-Q2.yaml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "methods.subgroup_assigner_maf_filter.cli",
            "--subgroup-catalog",
            str(catalog_path),
            "--data-source",
            "tcga",
            "--release-pin",
            "2026-Q2",
            "--catalog-repo",
            str(CATALOG_REPO),
            "--out",
            "/tmp/saf_dryrun",
            "--dry-run",
        ],
        cwd=METHODS_REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "subgroup_assigner_maf_filter" in result.stdout
    assert "KRAS_mut" in result.stdout
    assert "KRAS_G12C" in result.stdout
    assert "BRAF_V600E" in result.stdout
    assert "skipped strata" in result.stdout
    assert "MSI_H" in result.stdout  # Should skip MSI_H (directly_tagged)


def test_dry_run_on_paad_tcga():
    """Dry-run against PAAD catalog picks up KRAS variants + TP53 + BRCA."""
    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "PAAD" / "2026-Q3.yaml"
    if not catalog_path.exists():
        pytest.skip(f"PAAD catalog not landed on this branch/main: {catalog_path}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "methods.subgroup_assigner_maf_filter.cli",
            "--subgroup-catalog",
            str(catalog_path),
            "--data-source",
            "tcga",
            "--release-pin",
            "2026-Q3",
            "--catalog-repo",
            str(CATALOG_REPO),
            "--out",
            "/tmp/saf_paad_dryrun",
            "--dry-run",
        ],
        cwd=METHODS_REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "KRAS_G12D" in result.stdout
    assert "TP53_mut" in result.stdout


def test_rule_compiler_supported_forms():
    """Unit tests for the MAF-predicate compiler."""
    from methods.subgroup_assigner_maf_filter.cli import compile_rule

    # gene_symbol == 'X' && protein_change == 'Y'
    p = compile_rule("gene_symbol == 'KRAS' && protein_change == 'p.G12C'")
    assert p({"gene_symbol": "KRAS", "protein_change": "p.G12C"}) is True
    assert p({"gene_symbol": "KRAS", "protein_change": "p.G12D"}) is False
    assert p({"gene_symbol": "BRAF", "protein_change": "p.V600E"}) is False

    # `field in [values]`
    p = compile_rule("gene_symbol == 'KRAS' && protein_change in ['p.G12C', 'p.G12D', 'p.G12V']")
    assert p({"gene_symbol": "KRAS", "protein_change": "p.G12C"}) is True
    assert p({"gene_symbol": "KRAS", "protein_change": "p.G12A"}) is False

    # Integer exon comparison
    p = compile_rule("gene_symbol == 'EGFR' && effect == 'in_frame_deletion' && exon == 19")
    assert p({"gene_symbol": "EGFR", "effect": "in_frame_deletion", "exon": 19}) is True
    assert p({"gene_symbol": "EGFR", "effect": "in_frame_deletion", "exon": 20}) is False
    assert p({"gene_symbol": "EGFR", "effect": "missense", "exon": 19}) is False

    # Negation (KRAS-WT stratum)
    p = compile_rule("!(gene_symbol == 'KRAS' && protein_change in ['p.G12C', 'p.G12D'])")
    assert p({"gene_symbol": "KRAS", "protein_change": "p.G12C"}) is False
    assert p({"gene_symbol": "KRAS", "protein_change": "p.G12A"}) is True
    assert p({"gene_symbol": "BRAF", "protein_change": "p.V600E"}) is True

    # NaN handling
    import numpy as np

    p = compile_rule("gene_symbol == 'KRAS' && protein_change == 'p.G12C'")
    # NaN in a required field → None (tri-value)
    assert p({"gene_symbol": np.nan, "protein_change": "p.G12C"}) is None


def test_sample_level_negation_wildtype():
    """SAMPLE-level negation (KRAS-WT): a sample is WT iff it has ZERO KRAS-hotspot
    rows — NOT if some non-KRAS row fails to match. This is the regression test
    for the all-members bug: row-level `!(...)` any-hit marks every mutated sample
    a member (a TP53 row is 'not a KRAS hotspot')."""
    import pandas as pd

    from methods.subgroup_assigner_maf_filter.cli import _evaluate_stratum_maf

    # 3 samples: S1 has KRAS G12D (mutant), S2 has only TP53 (KRAS-WT),
    # S3 has KRAS G12D + a TP53 row (mutant). Correct WT set = {S2}.
    maf = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3", "S3"],
            "patient_id": ["S1", "S2", "S3", "S3"],
            "source_native_id": ["S1", "S2", "S3", "S3"],
            "gene_symbol": ["KRAS", "TP53", "KRAS", "TP53"],
            "protein_change": ["p.G12D", "p.R175H", "p.G12D", "p.R248Q"],
        }
    )
    all_samples = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "patient_id": ["S1", "S2", "S3"],
            "source_native_id": ["S1", "S2", "S3"],
        }
    )
    stratum = {
        "id": "KRAS_WT",
        "rule": "!(gene_symbol == 'KRAS' && protein_change in ['p.G12C','p.G12D','p.G12V'])",
        "derivation_source": "maf_filter_per_rule",
    }
    out = _evaluate_stratum_maf(stratum, maf, "sample_id", "patient_id", "source_native_id", all_samples)
    members = set(out[out["is_member"] == True]["sample_id"])
    # Only S2 (no KRAS hotspot) is WT. NOT S1/S3 (they carry KRAS G12D).
    assert members == {"S2"}, f"expected {{S2}}, got {members}"
    # A WT member reports no matched variant.
    assert out[out["sample_id"] == "S2"].iloc[0]["derivation_value"] == ""

    # Sanity: the POSITIVE (non-negated) form gives the complement {S1, S3}.
    pos = {
        **stratum,
        "id": "KRAS_mut",
        "rule": "gene_symbol == 'KRAS' && protein_change in ['p.G12C','p.G12D','p.G12V']",
    }
    out_pos = _evaluate_stratum_maf(pos, maf, "sample_id", "patient_id", "source_native_id", all_samples)
    assert set(out_pos[out_pos["is_member"] == True]["sample_id"]) == {"S1", "S3"}


def test_real_execution_synthetic_tcga_maf(tmp_path):
    """End-to-end test with synthetic TCGA MAF placed at the loader's fallback location."""
    # Stage the fixture under a TMP cache root (FRAMEWORK_CACHE_ROOT), never the
    # real ~/.cache — a subprocess writing the real path would clobber real data.
    cache_root = tmp_path / ".cache"
    cache = cache_root / "framework-gdc-pancohort-somatic"
    cache.mkdir(parents=True, exist_ok=True)
    maf_path = cache / "coadread-mc3.parquet"

    # Fabricate 20 MAF rows across 8 samples. Sample distribution:
    # - S1, S2: KRAS G12C
    # - S3: KRAS G12D
    # - S4: BRAF V600E
    # - S5: BRAF V600K (not V600E)
    # - S6, S7, S8: no KRAS/BRAF hotspot mutations (should be KRAS_G12C=false)
    rows = [
        {
            "sample_id": "TCGA-01",
            "patient_id": "TCGA-01",
            "source_native_id": "TCGA-01-01A",
            "gene_symbol": "KRAS",
            "protein_change": "p.G12C",
            "effect": "missense",
            "exon": 2,
        },
        {
            "sample_id": "TCGA-01",
            "patient_id": "TCGA-01",
            "source_native_id": "TCGA-01-01A",
            "gene_symbol": "TP53",
            "protein_change": "p.R175H",
            "effect": "missense",
            "exon": 5,
        },
        {
            "sample_id": "TCGA-02",
            "patient_id": "TCGA-02",
            "source_native_id": "TCGA-02-01A",
            "gene_symbol": "KRAS",
            "protein_change": "p.G12C",
            "effect": "missense",
            "exon": 2,
        },
        {
            "sample_id": "TCGA-03",
            "patient_id": "TCGA-03",
            "source_native_id": "TCGA-03-01A",
            "gene_symbol": "KRAS",
            "protein_change": "p.G12D",
            "effect": "missense",
            "exon": 2,
        },
        {
            "sample_id": "TCGA-04",
            "patient_id": "TCGA-04",
            "source_native_id": "TCGA-04-01A",
            "gene_symbol": "BRAF",
            "protein_change": "p.V600E",
            "effect": "missense",
            "exon": 15,
        },
        {
            "sample_id": "TCGA-05",
            "patient_id": "TCGA-05",
            "source_native_id": "TCGA-05-01A",
            "gene_symbol": "BRAF",
            "protein_change": "p.V600K",
            "effect": "missense",
            "exon": 15,
        },
        {
            "sample_id": "TCGA-06",
            "patient_id": "TCGA-06",
            "source_native_id": "TCGA-06-01A",
            "gene_symbol": "APC",
            "protein_change": "p.R1450*",
            "effect": "nonsense",
            "exon": 15,
        },
        {
            "sample_id": "TCGA-07",
            "patient_id": "TCGA-07",
            "source_native_id": "TCGA-07-01A",
            "gene_symbol": "TP53",
            "protein_change": "p.R248W",
            "effect": "missense",
            "exon": 7,
        },
        {
            "sample_id": "TCGA-08",
            "patient_id": "TCGA-08",
            "source_native_id": "TCGA-08-01A",
            "gene_symbol": "APC",
            "protein_change": "p.T1493fs",
            "effect": "frameshift",
            "exon": 15,
        },
    ]
    pd.DataFrame(rows).to_parquet(maf_path, index=False)

    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "COADREAD" / "2026-Q2.yaml"
    out_dir = tmp_path / "saf_out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "methods.subgroup_assigner_maf_filter.cli",
            "--subgroup-catalog",
            str(catalog_path),
            "--data-source",
            "tcga",
            "--release-pin",
            "2026-Q2",
            "--catalog-repo",
            str(CATALOG_REPO),
            "--out",
            str(out_dir),
        ],
        cwd=METHODS_REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "FRAMEWORK_CACHE_ROOT": str(cache_root)},
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}\nstdout:\n{result.stdout}"

    parquet_path = out_dir / "assignments.parquet"
    manifest_path = out_dir / "manifest.yaml"
    assert parquet_path.exists()
    assert manifest_path.exists()

    assignments = pd.read_parquet(parquet_path)

    # KRAS_G12C: TCGA-01 + TCGA-02 → true (2 samples); others → false (6 samples)
    krsg12c = assignments[assignments["stratum_id"] == "KRAS_G12C"]
    assert (krsg12c["is_member"] == True).sum() == 2
    assert (krsg12c["is_member"] == False).sum() == 6

    # KRAS_mut (any KRAS hotspot): TCGA-01 + TCGA-02 (G12C) + TCGA-03 (G12D) → 3 true
    krasm = assignments[assignments["stratum_id"] == "KRAS_mut"]
    assert (krasm["is_member"] == True).sum() == 3

    # BRAF_V600E: TCGA-04 only → 1 true; TCGA-05 (V600K) NOT a match → false
    braf = assignments[assignments["stratum_id"] == "BRAF_V600E"]
    assert (braf["is_member"] == True).sum() == 1
    assert (braf["is_member"] == False).sum() == 7  # 8 samples in cohort, 1 hit

    # Manifest is the schema-valid subgroup_assignment_product shape (variant=maf)
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["manifest_kind"] == "subgroup_assignment_product"
    assert manifest["indication"] == "COADREAD"
    assert manifest["data_source"] == "tcga"
    assert manifest["assignment_product_id"] == "subgroup-assignments-coadread-tcga-maf-2026-q2"
    assert manifest["assigner_method"] == "subgroup_assigner_maf_filter"
    strata = {s["subgroup_id"]: s for s in manifest["strata_summary"]}
    assert "KRAS_G12C" in strata
    assert manifest["n_samples_total"] == 8
    assert len(manifest["subgroup_catalog_content_pin"]) == 64
