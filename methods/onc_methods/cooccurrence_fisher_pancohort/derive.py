"""cooccurrence_fisher_pancohort.derive — Python orchestrator for the R pipeline.

Fans out to 7 R stage scripts (plus 1 Python stage for panel-intersect
computation) that together produce `pancohort-cooccurrence-fisher-v1`:
per-pair cooccurrence + mutual-exclusivity stats across TCGA MC3 +
GENIE 19.0-public, with per-source AND panel-intersect-restricted
pooled q-values, plus DISCOVER + SELECT q-values.

## STATUS: 2026-07-10 BOUNDED-CHECKPOINT SKELETON

This orchestrator is a SKELETON. The 7 R stage scripts + 1 Python stage
under steps/ are TODO-marked. Fresh session picks up:

  Stage 00_load_mc3.R          — R: parse MC3 MAF to binary sample×gene matrix
  Stage 01_panel_intersect.py  — Python: parse 166 GENIE gene_panel_*.txt +
                                  data_gene_matrix.txt, emit
                                  panel_intersect_by_cohort.tsv
  Stage 02_build_matrices.R    — R: build per-cohort sample×gene binary
                                  matrices for TCGA + GENIE (cohort-tagged)
  Stage 03_fisher_per_source.R — R: fisher.test() per (target, partner,
                                  cohort, source), emit log2_OR + fisher_p +
                                  BH-FDR-per-cohort-per-source
  Stage 04_discover.R          — R: DISCOVER::pairwise.discover.test() on
                                  per-cohort matrices (rate>=2%, count>=5)
  Stage 05_select.R            — R: sources vendor/select/*.R, runs SELECT
                                  influence-graph per cohort
  Stage 06_pool_and_write.R    — R: union results, apply panel-intersect
                                  gating for pooled_eligible flag,
                                  BH-adjust genome-wide q, arrow::write_parquet

Full plan: ~/.claude/plans/deep-foraging-thompson.md (PR 1 section).

## Biology validation gate (BLOCKING before PR merge)

The fresh session must confirm all 5 canonical pairs recover published
cooccurrence/mutex signs before opening the PR:

  - TP53↔MDM2 in PANCAN: co-occurring, q<0.001
  - IDH1↔TP53 in GBM: mutually exclusive
  - KRAS↔BRAF in COAD: strong mutex (Yaeger 2017)
  - EGFR↔KRAS in LUAD: strong mutex
  - APC↔CTNNB1 in COAD: mutex

## Inputs (verified 2026-07-10)

- s3://onc-compbio/data-catalog/sources/synapse/tcga-mc3-public/
    mc3.v0.2.8.PUBLIC.maf.gz (753 MB gz)
- s3://.../genie-public-v19-0/data_mutations_extended.txt (1.12 GB)
- s3://.../genie-public-v19-0/data_gene_matrix.txt (17.8 MB sample→panel)
- s3://.../genie-public-v19-0/gene_panels/data_gene_panel_*.txt (166 files)

## Runtime estimate

~90 min end-to-end cold (MAF parse 8m + MC3 matrix 5m + panel intersect
2m + Fisher 40m + DISCOVER 20m + SELECT 15m).

## Usage (fresh-session, after `pixi shell`)

    pixi run Rscript methods/cooccurrence_fisher_pancohort/setup.R
    pixi run python -m onc_methods.cooccurrence_fisher_pancohort.derive \\
        --out /tmp/cooccurrence_fisher.parquet
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
METHOD_DIR = Path(__file__).resolve().parent
STEPS_DIR = METHOD_DIR / "steps"


def _run_r_stage(stage_script: Path, work_dir: Path, extra_args: list[str] | None = None) -> None:
    """Run an R stage via `Rscript` subprocess. Mirrors
    methods/dge_deseq2/steps/run_pipeline.R:51-57 pattern.

    Fails loudly on non-zero exit. Assumes `pixi shell` (or `pixi run`)
    has provisioned R + bioconductor + DISCOVER.
    """
    cmd = ["Rscript", str(stage_script), "--work-dir", str(work_dir)]
    if extra_args:
        cmd.extend(extra_args)
    print(f"[derive] running: {' '.join(cmd)}", file=sys.stderr)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, check=False, capture_output=False)
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(f"Stage {stage_script.name} failed with exit {result.returncode} after {elapsed:.0f}s")
    print(f"[derive]   -> ok ({elapsed:.0f}s)", file=sys.stderr)


def _run_python_stage(stage_script: Path, work_dir: Path) -> None:
    """Run a Python stage via `python`. Same pattern as _run_r_stage."""
    cmd = [sys.executable, str(stage_script), "--work-dir", str(work_dir)]
    print(f"[derive] running: {' '.join(cmd)}", file=sys.stderr)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, check=False, capture_output=False)
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(f"Stage {stage_script.name} failed with exit {result.returncode} after {elapsed:.0f}s")
    print(f"[derive]   -> ok ({elapsed:.0f}s)", file=sys.stderr)


def derive_cooccurrence_fisher(out_parquet: Path, work_dir: Path) -> None:
    """Full pipeline. Runs the 7 stages sequentially; writes final parquet."""
    work_dir.mkdir(parents=True, exist_ok=True)
    total_t0 = time.perf_counter()

    # TODO(fresh-session): the R stage scripts do not exist yet. Fresh
    # session must write them before this pipeline runs. Skeletons for
    # each stage's expected inputs/outputs live in the docstrings of the
    # .R files at steps/00_load_mc3.R through steps/06_pool_and_write.R.
    _run_r_stage(STEPS_DIR / "00_load_mc3.R", work_dir)
    _run_python_stage(STEPS_DIR / "01_panel_intersect.py", work_dir)
    _run_r_stage(STEPS_DIR / "02_build_matrices.R", work_dir)
    _run_r_stage(STEPS_DIR / "03_fisher_per_source.R", work_dir)
    _run_r_stage(STEPS_DIR / "04_discover.R", work_dir)
    _run_r_stage(STEPS_DIR / "05_select.R", work_dir)
    _run_r_stage(
        STEPS_DIR / "06_pool_and_write.R",
        work_dir,
        extra_args=["--out-parquet", str(out_parquet)],
    )

    print(
        f"[derive] pipeline complete in {time.perf_counter() - total_t0:.0f}s",
        file=sys.stderr,
    )
    print(f"[derive] output parquet: {out_parquet}", file=sys.stderr)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output parquet path (final cooccurrence_fisher.parquet)",
    )
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=Path.home() / ".cache" / "framework-cooccurrence-fisher",
        help="Working directory for intermediate .rds + .tsv files",
    )
    args = ap.parse_args(argv)

    # TODO(fresh-session): remove this guard once stage scripts exist.
    missing_stages = [
        p.name
        for p in [
            STEPS_DIR / "00_load_mc3.R",
            STEPS_DIR / "01_panel_intersect.py",
            STEPS_DIR / "02_build_matrices.R",
            STEPS_DIR / "03_fisher_per_source.R",
            STEPS_DIR / "04_discover.R",
            STEPS_DIR / "05_select.R",
            STEPS_DIR / "06_pool_and_write.R",
        ]
        if not p.exists()
    ]
    if missing_stages:
        print(
            "[derive] ERROR: pipeline stages not yet written. Missing:\n  " + "\n  ".join(missing_stages),
            file=sys.stderr,
        )
        print(
            "\nThis is a bounded-checkpoint SKELETON. Fresh session must "
            "write the stages per the plan at "
            "~/.claude/plans/deep-foraging-thompson.md (PR 1 section).",
            file=sys.stderr,
        )
        return 2

    derive_cooccurrence_fisher(args.out, args.work_dir)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
