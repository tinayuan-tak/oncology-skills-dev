"""R4 byte-identity gate — test that the carved-out dge_deseq2 CLI produces output
that is byte-identical (on deterministic fields) to the legacy
claude-oncology-skills/batch/expression_rna_COADREAD/run_pipeline.R output.

This is the LOAD-BEARING TEST for the R4 carve-out step. Per A1's refactor sequencing,
R4 cannot be declared complete (and the legacy batch/expression_rna_COADREAD/ cannot
be deleted in R7) until this test passes.

REQUIRES: R + DESeq2 + bioconductor (heavy env). Skipped if no Rscript can be found.

Test discipline:
  1. Run legacy: Rscript batch/expression_rna_COADREAD/run_pipeline.R --config configs/COADREAD.yaml ...
     → produces legacy_parquet
  2. Run carved: dge-deseq2 --indication COADREAD --contrast tumor_vs_adjacent --release-pin 2026-Q2 ...
     → produces new_parquet
  3. Read both as pandas DataFrames
  4. Assert that EVERY column the parquet carries is byte-identical between the two runs.
  5. Allow drift on: timestamp fields, intermediate .rds files, machine-identity fields —
     all of which live in 05_provenance.yaml, not in the parquet, so DRIFT_ALLOWED_COLUMNS
     is empty.

WHY THE COLUMN HANDLING AND SORT KEY LOOK DIFFERENT THAN YOU MIGHT EXPECT: this gate used to
declare a fixed 7-name list including `gene_id` and `stat`, and NEITHER is in the product
schema — `04_write_parquet.R` emits `gene_symbol` (and sorts by it, deliberately, for
predicate pushdown) and does not carry DESeq2's `stat`. So `sort_values("gene_id")` raised
`KeyError` the moment the run actually got that far, and the comparison loop's
`if col not in df.columns: continue` silently dropped 2 of the 7. Fixing the names alone
would still have left the gate comparing 6 of the 11 columns the product actually carries,
because a DECLARED list is a ceiling the schema grows past unnoticed. So the compared
population is now DERIVED from the data, with REQUIRED_COLUMNS as the liveness floor and
an explicit (empty) drift allowlist. Measured on real output: all 11 columns agree exactly
across 34531 genes, including the derived `is_actionable`/`is_significant`/`is_upregulated`
booleans (which catch threshold drift) and `n_tumor`/`n_normal` (which catch cohort drift) —
none of which the old declared list compared.

Run it:
    cd rnd-computational-biology-oncology-analysis-methods
    pixi run pytest methods/dge_deseq2/tests/test_byte_identity_vs_legacy_coadread.py -v

Running it WITHOUT `pixi run` (e.g. by absolute interpreter path, which is how you have to
drive a /tmp worktree) leaves `.pixi/envs/default/bin` off PATH. That used to disarm the
gate silently via `shutil.which("Rscript")`; `_resolve_rscript()` below now looks in this
repo's own pixi env first, so the gate runs either way.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]

# Sibling repo roots are ENV-OVERRIDABLE, defaulting to the sibling checkout DERIVED from this
# file's own location — so a worktree resolves ITS OWN siblings rather than another checkout's.
# DATA_CATALOG_ROOT is the repo-wide convention (see methods/catalog_query/read.py and ~20 other
# call sites) and methods-validate.yml already exports it. Overriding it is what lets the gate be
# verified against a data-catalog BRANCH (e.g. a fixed indication-config) without editing the
# primary checkout to make a test pass. `or` rather than a two-arg .get() default so an EMPTY
# value falls back too: .get(K, d) returns "" and Path("") is "." — the CWD.
CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT")
    or Path(__file__).resolve().parents[3].parent / "rnd-computational-biology-oncology-data-catalog"
)
# No CI job clones claude-oncology-skills, so the skipif below fires on every runner and this
# gate is LOCAL-ONLY by construction. Kept env-overridable anyway so it is not machine-locked.
SKILLS_REPO = Path(
    os.environ.get("CLAUDE_ONCOLOGY_SKILLS_ROOT")
    or Path(__file__).resolve().parents[3].parent / "rnd-computational-biology-oncology-claude-oncology-skills"
)

# The key the two frames are aligned by before any column is compared.
GENE_KEY = "gene_symbol"

# THE FLOOR, not the scope. These columns must be PRESENT — asserted below, never skipped — so a
# product-schema rename fails this gate loudly instead of quietly shrinking what it compares. The
# columns actually compared are derived from the data (see `compare_columns`), because a declared
# list is a CEILING that the schema silently grows past: this gate named 7 columns while the
# product carried 11, and 2 of the 7 did not exist.
REQUIRED_COLUMNS = [GENE_KEY, "log2FoldChange", "baseMean", "pvalue", "padj", "lfcSE"]

# Columns the two arms are allowed to differ on. EMPTY ON PURPOSE: every field the parquet carries
# is a deterministic function of the counts and the config. The non-deterministic provenance
# (computed_date, git_commit, computed_by) lives in 05_provenance.yaml, which is a separate
# artifact this gate does not compare. Anything added here narrows the gate, so REQUIRED_COLUMNS
# is re-asserted against the result below to keep this list from being used to neuter it.
DRIFT_ALLOWED_COLUMNS: set[str] = set()


def _resolve_rscript() -> str | None:
    """Return an Rscript path, preferring the env of the RUNNING INTERPRETER over PATH.

    R ships in the same pixi env as this python, so `sys.executable`'s bin/ is the reliable
    anchor: it holds under `pixi run`, and it also holds when a /tmp worktree is driven by the
    primary checkout's interpreter (a worktree has no .pixi/ of its own — copying a multi-GB env
    onto the overlay is the ENOSPC trap — so anchoring to METHODS_REPO would resolve to nothing
    in exactly the case that matters). PATH is the last resort, because a PATH-only lookup is
    what silently disarmed this gate whenever pytest was invoked by absolute interpreter path.
    """
    candidates = [
        Path(sys.executable).parent / "Rscript",
        METHODS_REPO / ".pixi" / "envs" / "default" / "bin" / "Rscript",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("Rscript")


RSCRIPT = _resolve_rscript()


@pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot run R4 byte-identity gate without R env",
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
        RSCRIPT,
        str(SKILLS_REPO / "batch" / "expression_rna_COADREAD" / "run_pipeline.R"),
        f"--config={SKILLS_REPO / 'configs' / 'COADREAD.yaml'}",
        f"--catalog-repo={CATALOG_REPO}",
        "--git-sha=R4-byte-identity-test",
        f"--out-dir={legacy_out}",
        f"--parquet-uri={legacy_parquet}",
        "--threads=4",
    ]
    # Both arms shell out to a BARE `Rscript`: run_pipeline.R runs `Rscript <step>.R` per stage,
    # and the carved cli.py resolves "Rscript" from PATH (cli.py:198). So resolving RSCRIPT for the
    # parent is not enough — put its directory on PATH for every child of this test.
    r_env = dict(os.environ)
    r_env["PATH"] = os.pathsep.join([str(Path(RSCRIPT).parent), r_env.get("PATH", "")])
    legacy_result = subprocess.run(legacy_cmd, capture_output=True, text=True, env=r_env)
    assert legacy_result.returncode == 0, f"legacy run failed: {legacy_result.stderr}"

    # 2. Run carved-out CLI
    new_out = tmp_path / "carved"
    new_out.mkdir()
    new_parquet = new_out / "result.parquet"
    new_cmd = [
        sys.executable,
        "-m",
        "methods.dge_deseq2.cli",
        "--indication",
        "COADREAD",
        "--contrast",
        "tumor_vs_adjacent",
        "--release-pin",
        "2026-Q2",
        f"--catalog-repo={CATALOG_REPO}",
        f"--out={new_out}",
        f"--parquet-uri={new_parquet}",
    ]
    new_result = subprocess.run(new_cmd, capture_output=True, text=True, cwd=METHODS_REPO, env=r_env)
    assert new_result.returncode == 0, f"carved run failed: {new_result.stderr}"

    # 3. Compare deterministic columns
    df_legacy = pd.read_parquet(legacy_parquet)
    df_new = pd.read_parquet(new_parquet)

    assert set(df_legacy.columns) == set(df_new.columns), (
        f"column sets differ: legacy={sorted(df_legacy.columns)}, new={sorted(df_new.columns)}"
    )
    assert len(df_legacy) == len(df_new), f"row counts differ: legacy={len(df_legacy)}, new={len(df_new)}"

    # FAIL, never skip, on a required column the schema no longer carries. The previous
    # `if col not in df.columns: continue` meant a renamed column was quietly not compared —
    # the gate would have gone green while checking less and less.
    missing = [col for col in REQUIRED_COLUMNS if col not in df_legacy.columns]
    assert not missing, (
        f"REQUIRED_COLUMNS names {missing}, which the pipeline output does not carry. "
        f"Either the product schema changed or this list is stale — do NOT skip these columns, "
        f"the whole point of the gate is that they are compared. Present: {sorted(df_legacy.columns)}"
    )

    # Compare EVERY column the product carries. Taking the population from the data rather than
    # from a declared list means a column ADDED by the pipeline is compared automatically instead
    # of silently escaping the gate. REQUIRED_COLUMNS above is the liveness floor that keeps this
    # from degenerating: a derived population is vacuous if the population can be empty.
    compare_columns = sorted(set(df_legacy.columns) - DRIFT_ALLOWED_COLUMNS)
    swallowed = sorted(set(REQUIRED_COLUMNS) - set(compare_columns))
    assert not swallowed, f"DRIFT_ALLOWED_COLUMNS excludes required columns {swallowed}"

    df_legacy_sorted = df_legacy.sort_values(GENE_KEY).reset_index(drop=True)
    df_new_sorted = df_new.sort_values(GENE_KEY).reset_index(drop=True)

    for col in compare_columns:
        pd.testing.assert_series_equal(
            df_legacy_sorted[col],
            df_new_sorted[col],
            check_exact=True,
            obj=f"R4 byte-identity column {col}",
        )


def test_cli_dry_run_smoke():
    """Smoke test: the CLI imports cleanly and --dry-run succeeds.
    This is the minimal sanity check that does NOT require R env."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "methods.dge_deseq2.cli",
            "--indication",
            "COADREAD",
            "--contrast",
            "tumor_vs_adjacent",
            "--release-pin",
            "2026-Q2",
            "--out",
            "/tmp/dge_deseq2_dryrun",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=METHODS_REPO,
    )
    # CLI may fail config resolution if no config exists; we accept that for dry-run smoke
    # — what we care about is that the Python imports and Click parsing work.
    assert (
        "dge-deseq2 invocation" in result.stdout
        or "No config found" in (result.stderr or "")
        or "No config found" in (result.stdout or "")
    ), f"CLI did not produce expected output. stdout={result.stdout!r}, stderr={result.stderr!r}"
