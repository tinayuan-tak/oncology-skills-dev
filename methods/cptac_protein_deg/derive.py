#!/usr/bin/env python3
"""derive.py — orchestrate the CPTAC protein tumor-vs-normal DEG pipeline.

Stages:
  00 (Python) — pull per-aliquot sample_type from PDC GraphQL
  01 (Python) — reshape tmt10.tsv + sample.txt + annotations into MSstatsTMT
                input feather (log-abundance long form)
  02 (R)      — MSstatsTMT::groupComparisonTMT tumor-vs-normal (plex batch as
                random effect + limma-eBayes moderated)
  03 (Python) — pool per-cohort TSVs, join to UniProt AC, write parquet

Runtime discipline: cohorts are independent; stage 02 (the slow stage,
per-protein lmer fits) is safe to parallelize across cohorts. Default
--parallel=4 gives ~2x wall-clock speedup on typical instances.

Usage:
  pixi run python -m methods.cptac_protein_deg.derive \\
      --out-parquet ~/dev/framework-runs/cptac-protein-deg-YYYY-MM-DD/cptac_protein_deg.parquet
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CPTAC_COHORTS = ["BRCA", "CCRCC", "COAD", "GBM", "HNSCC",
                 "LSCC", "LUAD", "OV", "PDAC", "UCEC"]

STEPS_DIR = Path(__file__).resolve().parent / "steps"
PIXI = "pixi"


def run_cmd(cmd: list[str], name: str, log_path: Path | None = None) -> int:
    """Run a subprocess; on failure raise with a captured tail."""
    print(f"[derive] $ {' '.join(cmd)}", file=sys.stderr, flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    else:
        r = subprocess.run(cmd)
    if r.returncode != 0:
        tail = ""
        if log_path is not None and log_path.exists():
            tail = "\n".join(log_path.read_text().splitlines()[-30:])
        raise RuntimeError(f"[derive] {name} failed rc={r.returncode}\n{tail}")
    return r.returncode


def stage_00(annotations_dir: Path, cohort_filter: str | None) -> None:
    cmd = [PIXI, "run", "python", str(STEPS_DIR / "00_pull_annotations.py"),
           "--annotations-dir", str(annotations_dir)]
    if cohort_filter:
        cmd += ["--cohort", cohort_filter]
    run_cmd(cmd, "stage 00 (annotations)")


def stage_01(work_dir: Path, annotations_dir: Path, cohort_filter: str | None) -> None:
    cmd = [PIXI, "run", "python", str(STEPS_DIR / "01_prepare_msstats_input.py"),
           "--work-dir", str(work_dir),
           "--annotations-dir", str(annotations_dir)]
    if cohort_filter:
        cmd += ["--cohort", cohort_filter]
    run_cmd(cmd, "stage 01 (msstats input)")


def stage_02_cohort(cohort: str, work_dir: Path, min_normal: int) -> tuple[str, float, bool]:
    log_path = work_dir / f"{cohort}_msstats.log"
    cmd = [PIXI, "run", "Rscript", str(STEPS_DIR / "02_msstats_deg.R"),
           "--work-dir", str(work_dir),
           "--cohort", cohort,
           "--min-normal", str(min_normal)]
    t0 = time.time()
    try:
        run_cmd(cmd, f"stage 02 ({cohort})", log_path=log_path)
        return (cohort, time.time() - t0, True)
    except RuntimeError as e:
        print(f"[derive] stage 02 {cohort} FAILED: {e}", file=sys.stderr)
        return (cohort, time.time() - t0, False)


def stage_02(work_dir: Path, cohorts: list[str], parallel: int, min_normal: int) -> None:
    print(f"[derive] stage 02: {len(cohorts)} cohorts × parallel={parallel}",
          file=sys.stderr)
    results = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futures = {ex.submit(stage_02_cohort, c, work_dir, min_normal): c
                   for c in cohorts}
        for fut in as_completed(futures):
            results.append(fut.result())
            c, secs, ok = results[-1]
            print(f"[derive] stage 02 {c}: {'OK' if ok else 'FAIL'} ({secs:.1f}s)",
                  file=sys.stderr, flush=True)
    n_ok = sum(1 for _, _, ok in results if ok)
    failed = sorted(c for c, _, ok in results if not ok)
    print(f"[derive] stage 02 summary: {n_ok}/{len(cohorts)} OK", file=sys.stderr)
    # Require EVERY requested cohort to succeed. Previously the gate only tripped at
    # n_ok < 3, so 3-9 of 10 cohorts could fail silently and still ship a product with
    # no record of which cohorts are present — a downstream reader can't tell a genuinely
    # 10-cohort product from one silently missing (e.g.) UCEC + OV + GBM. Fail loud with
    # the failed roster instead. (A deliberate subset run is still explicit via --cohort.)
    if n_ok != len(cohorts):
        raise RuntimeError(
            f"stage 02: {n_ok}/{len(cohorts)} cohorts succeeded — failed cohorts: {failed}. "
            f"Every requested cohort must succeed before pooling (stage 03), else the product "
            f"would silently omit cohorts with no record of which are present. Re-run the failed "
            f"cohorts (e.g. --cohort {failed[0] if failed else '<COHORT>'}) or drop them from the "
            f"requested set explicitly."
        )


def stage_03(work_dir: Path, out_parquet: Path, uniprot_map: Path | None) -> None:
    cmd = [PIXI, "run", "python", str(STEPS_DIR / "03_pool_and_write.py"),
           "--work-dir", str(work_dir),
           "--out-parquet", str(out_parquet)]
    if uniprot_map is not None:
        cmd += ["--uniprot-map", str(uniprot_map)]
    run_cmd(cmd, "stage 03 (pool + parquet)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-parquet", required=True, type=Path)
    ap.add_argument("--work-root", type=Path,
                    default=Path.home() / "dev" / "framework-runs" / "cptac-protein-deg")
    ap.add_argument("--cohort", default=None,
                    help="Single-cohort smoke mode (default: all 10)")
    ap.add_argument("--parallel", type=int, default=4,
                    help="Concurrent stage-02 cohorts [default 4]")
    ap.add_argument("--min-normal", type=int, default=5)
    ap.add_argument("--uniprot-map", type=Path, default=None,
                    help="Optional gene_symbol → uniprot_ac TSV for stage 03")
    ap.add_argument("--skip-stage-00", action="store_true")
    ap.add_argument("--skip-stage-01", action="store_true")
    ap.add_argument("--skip-stage-02", action="store_true")
    ap.add_argument("--skip-stage-03", action="store_true")
    args = ap.parse_args()

    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = "cbg"

    args.work_root.mkdir(parents=True, exist_ok=True)
    annotations_dir = args.work_root / "annotations"
    per_cohort_dir = args.work_root / "per_cohort"
    annotations_dir.mkdir(parents=True, exist_ok=True)
    per_cohort_dir.mkdir(parents=True, exist_ok=True)

    cohorts = [args.cohort] if args.cohort else list(CPTAC_COHORTS)

    if not args.skip_stage_00:
        stage_00(annotations_dir, args.cohort)
    if not args.skip_stage_01:
        stage_01(per_cohort_dir, annotations_dir, args.cohort)
    if not args.skip_stage_02:
        stage_02(per_cohort_dir, cohorts, args.parallel, args.min_normal)
    if not args.skip_stage_03:
        stage_03(per_cohort_dir, args.out_parquet, args.uniprot_map)

    print(f"[derive] DONE — parquet at {args.out_parquet}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
