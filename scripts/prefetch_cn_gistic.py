#!/usr/bin/env python3
"""prefetch_cn_gistic.py — extract GISTIC thresholded copy-number amp/del calls
for a small set of genes into a compact per-(patient, gene) parquet the
directly_tagged assigner's gene_amp_call path reads from cache.

The PanCanAtlas GISTIC file (all_thresholded.by_genes_whitelisted.tsv) is a
25,128-gene × 10,713-sample matrix (589 MB) with values in {-2,-1,0,1,2}:
  +2 = high-level amplification, +1 = low-level gain,
  -2 = deep (homozygous) deletion, -1 = shallow loss, 0 = neutral.
We slice to the genes actually referenced by copy_number strata (e.g. CCND1 for
HNSC, ERBB2/CCND1 for others) and melt to long form so the assigner joins on
patient barcode. The `amp_call` column normalizes +2 → 'amplified' (catalog rule
`copy_number.CCND1 == 'amplified'`), matching the high-level-amp convention.

Output: ~/.cache/framework-cn-gistic/{indication_lower}-cn.parquet
  columns: patient_key, gene_symbol, gistic_value, amp_call ('amplified'|'not_amplified')

Invocation:
  python -m scripts.prefetch_cn_gistic --indication HNSC --genes CCND1
  DRY_RUN=1 python -m scripts.prefetch_cn_gistic --indication HNSC --genes CCND1
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

S3_BUCKET = "onc-compbio"
GISTIC_S3 = ("data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/"
             "all_thresholded.by_genes_whitelisted.tsv")
# High-level amplification threshold (GISTIC +2). Low-level gain (+1) is NOT an
# amp call — matches the catalog's focal-amplification intent (CCND1/ERBB2).
AMP_THRESHOLD = 2


def _log(msg: str) -> None:
    click.echo(f"[prefetch-cn-gistic] {msg}", err=True)


def _cache_root() -> Path:
    override = os.environ.get("FRAMEWORK_CACHE_ROOT")
    return Path(override) if override else Path.home() / ".cache"


def _s3_download(key: str, dest: Path, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _log(f"cache hit: {dest}")
        return
    if dry_run:
        _log(f"DRY_RUN: would download s3://{S3_BUCKET}/{key} → {dest}")
        return
    _log(f"downloading s3://{S3_BUCKET}/{key} → {dest} (589 MB)")
    r = subprocess.run(["aws", "s3", "cp", f"s3://{S3_BUCKET}/{key}", str(dest), "--no-progress"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        _log(f"download FAILED: {r.stderr}")
        sys.exit(r.returncode)


def _patient_list(indication: str) -> set | None:
    """Restrict to the indication's marker-paper patients (else the product is
    pan-TCGA). Returns None if the marker-paper file is absent (keep all)."""
    import pandas as pd
    mp = _cache_root() / "framework-tcga-marker-paper" / indication.lower() / "subtypes.csv"
    if not mp.exists():
        _log(f"WARNING: no marker-paper patient list at {mp}; keeping all samples.")
        return None
    return set(pd.read_csv(mp)["patient"])


@click.command()
@click.option("--indication", required=True, help="iDAS indication code (e.g. HNSC).")
@click.option("--genes", required=True, help="Comma-separated gene symbols (e.g. 'CCND1,ERBB2').")
def main(indication: str, genes: str) -> int:
    dry_run = os.environ.get("DRY_RUN") == "1"
    ind = indication.upper()
    gene_list = [g.strip() for g in genes.split(",") if g.strip()]
    out_path = _cache_root() / "framework-cn-gistic" / f"{ind.lower()}-cn.parquet"
    _log(f"=== prefetch CN GISTIC × {ind} | genes={gene_list} ===")
    _log(f"  output: {out_path}")

    gistic_local = _cache_root() / "gdc-pancanatlas-gistic" / "all_thresholded.by_genes_whitelisted.tsv"
    _s3_download(GISTIC_S3, gistic_local, dry_run)
    if dry_run:
        _log("DRY_RUN: skipping parse + write")
        return 0

    import pandas as pd

    # Read only the gene-id columns + slice to requested genes (avoids loading
    # all 10,713 sample columns until we've filtered rows).
    header = pd.read_csv(gistic_local, sep="\t", nrows=0)
    sample_cols = [c for c in header.columns if c.startswith("TCGA")]
    usecols = ["Gene Symbol"] + sample_cols
    gistic = pd.read_csv(gistic_local, sep="\t", usecols=usecols, low_memory=False)
    sel = gistic[gistic["Gene Symbol"].isin(gene_list)].copy()
    missing = set(gene_list) - set(sel["Gene Symbol"])
    if missing:
        _log(f"WARNING: genes not in GISTIC matrix: {sorted(missing)}")
    _log(f"  matched {len(sel)} gene rows; {len(sample_cols):,} sample columns")

    # Melt to long form: one row per (sample, gene).
    long = sel.melt(id_vars=["Gene Symbol"], var_name="aliquot", value_name="gistic_value")
    long = long.rename(columns={"Gene Symbol": "gene_symbol"})
    long["patient_key"] = long["aliquot"].str[:12]

    keep = _patient_list(ind)
    if keep is not None:
        long = long[long["patient_key"].isin(keep)]
        _log(f"  filtered to {long['patient_key'].nunique()} {ind} patients")

    # Collapse aliquot duplicates per (patient, gene): take the MAX gistic value
    # (most-amplified call wins — conservative for amp detection).
    agg = (long.groupby(["patient_key", "gene_symbol"])["gistic_value"]
           .max().reset_index())
    agg["amp_call"] = agg["gistic_value"].apply(
        lambda v: "amplified" if v >= AMP_THRESHOLD else "not_amplified")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(out_path, index=False)
    for g in gene_list:
        sub = agg[agg["gene_symbol"] == g]
        n_amp = int((sub["amp_call"] == "amplified").sum())
        _log(f"  {g}: {n_amp}/{len(sub)} amplified ({100*n_amp/len(sub):.1f}%)" if len(sub) else f"  {g}: absent")
    _log(f"wrote {out_path}: {len(agg)} (patient, gene) rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
