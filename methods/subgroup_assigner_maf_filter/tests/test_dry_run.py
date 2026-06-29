"""Smoke test: subgroup_assigner_maf_filter CLI's dry-run path parses MAF-derived strata cleanly."""

import subprocess
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CATALOG_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")


def test_dry_run_on_coadread_tcga():
    """Dry-run picks up KRAS_mut, KRAS_G12C, BRAF_V600E from COADREAD catalog."""
    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "COADREAD" / "2026-Q2.yaml"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_maf_filter.cli",
            "--subgroup-catalog", str(catalog_path),
            "--data-source", "tcga",
            "--release-pin", "2026-Q2",
            "--catalog-repo", str(CATALOG_REPO),
            "--out", "/tmp/saf_dryrun",
            "--dry-run",
        ],
        cwd=METHODS_REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "subgroup_assigner_maf_filter" in result.stdout
    assert "KRAS_mut" in result.stdout
    assert "KRAS_G12C" in result.stdout
    assert "BRAF_V600E" in result.stdout
    # Should skip MSI_H / MSS (directly_tagged, not MAF-filter)
    assert "skipped strata" in result.stdout
    assert "MSI_H" in result.stdout


def test_dry_run_on_pdac_tcga():
    """Dry-run picks up KRAS hotspot strata + SMAD4_loss from PDAC catalog."""
    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "PDAC" / "2026-Q2.yaml"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_maf_filter.cli",
            "--subgroup-catalog", str(catalog_path),
            "--data-source", "tcga",
            "--release-pin", "2026-Q2",
            "--catalog-repo", str(CATALOG_REPO),
            "--out", "/tmp/saf_pdac_dryrun",
            "--dry-run",
        ],
        cwd=METHODS_REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "KRAS_mut" in result.stdout
    assert "KRAS_G12D" in result.stdout
    assert "SMAD4_loss" in result.stdout
