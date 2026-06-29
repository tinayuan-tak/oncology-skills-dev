"""Smoke test: subgroup_assigner_directly_tagged CLI's dry-run path parses catalog cleanly."""

import subprocess
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CATALOG_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")


def test_dry_run_on_coadread_tcga():
    """Dry-run against COADREAD catalog with tcga data source emits the plan without error."""
    catalog_path = CATALOG_REPO / "subgroup-catalogs" / "COADREAD" / "2026-Q2.yaml"
    result = subprocess.run(
        [
            "python", "-m", "methods.subgroup_assigner_directly_tagged.cli",
            "--subgroup-catalog", str(catalog_path),
            "--data-source", "tcga",
            "--release-pin", "2026-Q2",
            "--catalog-repo", str(CATALOG_REPO),
            "--out", "/tmp/sat_dryrun",
            "--dry-run",
        ],
        cwd=METHODS_REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "subgroup_assigner_directly_tagged" in result.stdout
    assert "MSI_H" in result.stdout
    assert "MSS" in result.stdout
    # Should skip the MAF-derived strata
    assert "skipped strata" in result.stdout
    assert "KRAS_mut" in result.stdout
