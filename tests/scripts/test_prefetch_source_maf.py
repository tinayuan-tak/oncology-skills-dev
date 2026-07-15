"""Tests for scripts/prefetch_source_maf.py — the Phase-2b/c mutation-source
prefetch driver.

Validates the source-config table + dry-run planning without requiring
network access. Real S3 pulls are exercised in operational runs, not CI.
"""

from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_source_configs_complete():
    """All 4 sources have complete SourceConfig entries."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    expected = {"tcga_mc3", "genie_public_v19", "genie_bpc_crc", "depmap_somatic"}
    assert set(SOURCE_CONFIGS) == expected
    for name, cfg in SOURCE_CONFIGS.items():
        assert cfg.gene_col and cfg.protein_col and cfg.effect_col and cfg.sample_col
        assert cfg.filter_strategy in {"tcga_patient_list", "genie_cancer_type",
                                        "depmap_lineage", "none"}


def test_depmap_uses_protein_change_column():
    """DepMap MAF uses Protein_Change (not HGVSp_Short like MC3/GENIE)."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    assert SOURCE_CONFIGS["depmap_somatic"].protein_col == "Protein_Change"
    assert SOURCE_CONFIGS["tcga_mc3"].protein_col == "HGVSp_Short"
    assert SOURCE_CONFIGS["genie_public_v19"].protein_col == "HGVSp_Short"


def test_genie_bpc_no_filter():
    """GENIE-BPC CRC is already CRC-only → filter_strategy=none."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    assert SOURCE_CONFIGS["genie_bpc_crc"].filter_strategy == "none"


def test_dry_run_depmap(tmp_path):
    """Dry-run prints the plan without pulling the MAF."""
    result = subprocess.run(
        ["python", "-m", "scripts.prefetch_source_maf",
         "--source", "depmap_somatic", "--indication", "COADREAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        env={"PATH": "/opt/conda/bin:/usr/bin:/bin", "HOME": str(Path.home()),
             "DRY_RUN": "1", "AWS_PROFILE": "cbg"},
    )
    assert result.returncode == 0, f"failed: {result.stderr}"
    assert "prefetch depmap_somatic × COADREAD" in result.stderr
    assert "depmap_lineage" in result.stderr
    assert "DRY_RUN" in result.stderr
