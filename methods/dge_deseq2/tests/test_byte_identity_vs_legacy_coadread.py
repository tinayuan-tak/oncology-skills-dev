"""R4 byte-identity gate — test that the carved-out dge_deseq2 CLI produces output
that is byte-identical (on deterministic fields) to the legacy
claude-oncology-skills/batch/expression_rna_COADREAD/run_pipeline.R output.

This is the LOAD-BEARING TEST for the R4 carve-out step. Per A1's refactor sequencing,
R4 cannot be declared complete (and the legacy batch/expression_rna_COADREAD/ cannot
be deleted in R7) until this test passes.

REQUIRES: R + DESeq2 + bioconductor (heavy env). Skipped if Rscript is not on PATH.

Test discipline:
  1. Run legacy: cd skills && Rscript batch/expression_rna_COADREAD/run_pipeline.R --config configs/COADREAD.yaml ...
     → produces legacy_parquet
  2. Run carved: dge-deseq2 --indication COADREAD --contrast tumor_vs_adjacent --release-pin 2026-Q2 ...
     → produces new_parquet
  3. Read both as pandas DataFrames
  4. Assert that all deterministic columns (gene_id, log2fc, baseMean, stat, pvalue, padj, lfcSE)
     are byte-identical between the two runs.
  5. Allow drift on: timestamp fields, intermediate .rds files, machine-identity fields.

Iter-1 status: SCAFFOLDED. The actual test execution requires (a) the R env to be available,
(b) the legacy batch/ scripts to be still present (which they are until R7 deletes), and
(c) the data-catalog config files at the new location (which R5 lands).

Run in iter-1 execution:
    cd rnd-computational-biology-oncology-analysis-methods
    pixi run pytest methods/dge_deseq2/tests/test_byte_identity_vs_legacy_coadread.py -v
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SKILLS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills")
METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CATALOG_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")

DETERMINISTIC_COLUMNS = ["gene_id", "log2FoldChange", "baseMean", "stat", "pvalue", "padj", "lfcSE"]


@pytest.mark.skipif(
    shutil.which("Rscript") is None,
    reason="Rscript not on PATH; cannot run R4 byte-identity gate without R env",
)
@pytest.mark.skipif(
    not (SKILLS_REPO / "batch" / "expression_rna_COADREAD" / "run_pipeline.R").exists(),
    reason="Legacy pipeline not present (R7 may already have deleted it)",
)
def test_dge_deseq2_byte_identity_vs_legacy_coadread(tmp_path):
    """The carved-out dge_deseq2 must produce byte-identical deterministic-field output
    to the legacy batch/expression_rna_COADREAD/ pipeline."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("pandas")
    import pandas as pd

    # 1. Run legacy pipeline
    legacy_out = tmp_path / "legacy"
    legacy_out.mkdir()
    legacy_parquet = legacy_out / "tumor_vs_adjacent.parquet"
    legacy_cmd = [
        "Rscript",
        str(SKILLS_REPO / "batch" / "expression_rna_COADREAD" / "run_pipeline.R"),
        f"--config={SKILLS_REPO / 'configs' / 'COADREAD.yaml'}",
        f"--catalog-repo={CATALOG_REPO}",
        f"--git-sha=R4-byte-identity-test",
        f"--out-dir={legacy_out}",
        f"--parquet-uri={legacy_parquet}",
        "--threads=4",
    ]
    legacy_result = subprocess.run(legacy_cmd, capture_output=True, text=True)
    assert legacy_result.returncode == 0, f"legacy run failed: {legacy_result.stderr}"

    # 2. Run carved-out CLI
    new_out = tmp_path / "carved"
    new_out.mkdir()
    new_parquet = new_out / "result.parquet"
    new_cmd = [
        "python", "-m", "methods.dge_deseq2.cli",
        "--indication", "COADREAD",
        "--contrast", "tumor_vs_adjacent",
        "--release-pin", "2026-Q2",
        f"--catalog-repo={CATALOG_REPO}",
        f"--out={new_out}",
        f"--parquet-uri={new_parquet}",
    ]
    new_result = subprocess.run(new_cmd, capture_output=True, text=True, cwd=METHODS_REPO)
    assert new_result.returncode == 0, f"carved run failed: {new_result.stderr}"

    # 3. Compare deterministic columns
    df_legacy = pd.read_parquet(legacy_parquet)
    df_new = pd.read_parquet(new_parquet)

    assert set(df_legacy.columns) == set(df_new.columns), (
        f"column sets differ: legacy={sorted(df_legacy.columns)}, new={sorted(df_new.columns)}"
    )
    assert len(df_legacy) == len(df_new), (
        f"row counts differ: legacy={len(df_legacy)}, new={len(df_new)}"
    )

    df_legacy_sorted = df_legacy.sort_values("gene_id").reset_index(drop=True)
    df_new_sorted = df_new.sort_values("gene_id").reset_index(drop=True)

    for col in DETERMINISTIC_COLUMNS:
        if col not in df_legacy_sorted.columns:
            continue
        pd.testing.assert_series_equal(
            df_legacy_sorted[col], df_new_sorted[col],
            check_exact=True,
            obj=f"R4 byte-identity column {col}",
        )


def test_cli_dry_run_smoke():
    """Smoke test: the CLI imports cleanly and --dry-run succeeds.
    This is the minimal sanity check that does NOT require R env."""
    result = subprocess.run(
        [
            "python", "-m", "methods.dge_deseq2.cli",
            "--indication", "COADREAD",
            "--contrast", "tumor_vs_adjacent",
            "--release-pin", "2026-Q2",
            "--out", "/tmp/dge_deseq2_dryrun",
            "--dry-run",
        ],
        capture_output=True, text=True, cwd=METHODS_REPO,
    )
    # CLI may fail config resolution if no config exists; we accept that for dry-run smoke
    # — what we care about is that the Python imports and Click parsing work.
    assert "dge-deseq2 invocation" in result.stdout or "No config found" in (result.stderr or "") or "No config found" in (result.stdout or ""), (
        f"CLI did not produce expected output. stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
