#!/usr/bin/env python3
"""prefetch_marker_paper.py — stage the TCGA marker-paper subtype CSV the
subgroup_assigner_directly_tagged method reads from cache, composing
multi-histology indications from their per-cohort files.

Codifies the marker-paper staging that was previously ad-hoc. The MAF side has
prefetch_source_maf.py; this is its directly-tagged (Modality A) counterpart.

Why composition matters (NSCLC): the per-cohort marker-paper CSVs
(tcga_subtype_LUAD.csv, tcga_subtype_LUSC.csv) carry NO histology column —
histology is IMPLICIT in which cohort file a patient came from. NSCLC =
LUAD (adenocarcinoma) + LUSC (squamous). This script concatenates the cohort
files and adds a derived `histology` column from cohort provenance, so the
catalog's `clinical.histology == 'adenocarcinoma'` / `'squamous_cell_carcinoma'`
rules can fire. Single-histology indications (COADREAD → tcga_subtype_CRC.csv)
pass through unchanged.

  NOTE (sourcing upgrade path): the cross-indication audit (data-catalog PR #175)
  identifies gdc-pancanatlas-clinical-2018 as the cleaner long-term histology
  source. This cohort-provenance composition needs NO new ingestion and is the
  interim source; a future revision can repoint histology at the clinical manifest.

Output: ~/.cache/framework-tcga-marker-paper/{indication_lower}/subtypes.csv
with a `patient` column (the directly_tagged loader's join key) + the union of
per-cohort columns + `histology` for multi-cohort indications.

Invocation:
    python -m scripts.prefetch_marker_paper --indication NSCLC
    python -m scripts.prefetch_marker_paper --indication COADREAD
    DRY_RUN=1 python -m scripts.prefetch_marker_paper --indication NSCLC
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

S3_BUCKET = "onc-compbio"
S3_PREFIX = "data-catalog/sources/tcga-marker-papers/subtypes-2018"

# Indication → list of (marker-paper cohort file, histology label). Multi-entry
# indications are composed with a derived histology column; single-entry ones
# pass through (histology label is None → no column added).
INDICATION_COHORTS: dict[str, list[tuple[str, str | None]]] = {
    "COADREAD": [("tcga_subtype_CRC.csv", None)],
    "NSCLC": [
        ("tcga_subtype_LUAD.csv", "adenocarcinoma"),
        ("tcga_subtype_LUSC.csv", "squamous_cell_carcinoma"),
    ],
    "HNSC": [("tcga_subtype_HNSC.csv", None)],
    "STAD": [("tcga_subtype_STAD.csv", None)],
    "PAAD": [("tcga_subtype_PAAD.csv", None)],
}


def _log(msg: str) -> None:
    click.echo(f"[prefetch-marker-paper] {msg}", err=True)


def _s3_download(filename: str, dest: Path, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _log(f"cache hit: {dest} (skip download)")
        return
    key = f"{S3_PREFIX}/{filename}"
    if dry_run:
        _log(f"DRY_RUN: would download s3://{S3_BUCKET}/{key} → {dest}")
        return
    _log(f"downloading s3://{S3_BUCKET}/{key} → {dest}")
    r = subprocess.run(
        ["aws", "s3", "cp", f"s3://{S3_BUCKET}/{key}", str(dest), "--no-progress"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        _log(f"download FAILED: {r.stderr}")
        sys.exit(r.returncode)


@click.command()
@click.option("--indication", required=True, help="iDAS indication code (e.g. NSCLC).")
def main(indication: str) -> int:
    dry_run = os.environ.get("DRY_RUN") == "1"
    ind = indication.upper()
    cohorts = INDICATION_COHORTS.get(ind)
    _log(f"=== prefetch marker-paper × {ind} ===")
    if cohorts is None:
        _log(f"No marker-paper cohort mapping for {ind}; add it to INDICATION_COHORTS. "
             f"(AML has no marker-paper LAML file — see the D7 audit.)")
        sys.exit(1)

    out_dir = Path.home() / ".cache" / "framework-tcga-marker-paper" / ind.lower()
    out_path = out_dir / "subtypes.csv"
    raw_dir = Path.home() / ".cache" / "framework-tcga-marker-paper" / "_raw"

    _log(f"  cohorts:  {[c[0] for c in cohorts]}")
    _log(f"  output:   {out_path}")
    if dry_run:
        for fn, _ in cohorts:
            _s3_download(fn, raw_dir / fn, dry_run=True)
        _log("DRY_RUN: skipping compose + write")
        return 0

    import pandas as pd

    frames = []
    for filename, histology in cohorts:
        local = raw_dir / filename
        _s3_download(filename, local, dry_run=False)
        df = pd.read_csv(local)
        if "patient" not in df.columns:
            _log(f"WARNING: {filename} has no `patient` column — the directly_tagged "
                 f"loader joins on it. Columns: {list(df.columns)[:6]}")
        if histology is not None:
            df["histology"] = histology
        frames.append(df)
        _log(f"  {filename}: {len(df)} rows"
             + (f" (histology={histology})" if histology else ""))

    composed = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    out_dir.mkdir(parents=True, exist_ok=True)
    composed.to_csv(out_path, index=False)
    hist_note = ""
    if "histology" in composed.columns:
        hist_note = f" | histology: {composed['histology'].value_counts().to_dict()}"
    _log(f"wrote {out_path}: {len(composed)} rows{hist_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
