#!/usr/bin/env python3
"""Stage 03 — pool per-cohort MSstatsTMT results, join to UniProt, and write parquet.

Reads:
    <work_dir>/<cohort>_msstats_results.tsv (from stage 02, per cohort)
    Optional gene→uniprot map (from target-id-resolver sidecar); if not present,
    uniprot_ac is left NULL.
Writes:
    <out_parquet>  — cptac_protein_deg.parquet with the schema from the derived
                     manifest (see CPTAC_FORMAT_NOTES.md).

Effect-size classification:
    strong_up   : logFC >  1.5, q < 0.05
    modest_up   : logFC >  0.5, q < 0.05
    strong_down : logFC < -1.5, q < 0.05
    modest_down : logFC < -0.5, q < 0.05
    ns          : otherwise
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

CPTAC_COHORTS = ["BRCA", "CCRCC", "COAD", "GBM", "HNSCC", "LSCC", "LUAD", "OV", "PDAC", "UCEC"]

METHOD_VERSION = "1.0.0"
STAT_TEST_USED = "msstatstmt_limma_ebayes_moderated"


def classify(logfc: float, q: float) -> str:
    if pd.isna(logfc) or pd.isna(q):
        return "ns"
    if q >= 0.05:
        return "ns"
    if logfc > 1.5:
        return "strong_up"
    if logfc > 0.5:
        return "modest_up"
    if logfc < -1.5:
        return "strong_down"
    if logfc < -0.5:
        return "modest_down"
    return "ns"


def load_uniprot_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    df = pd.read_csv(path, sep="\t", dtype=str)
    # target-id-resolver sidecar: expects gene_symbol + uniprot_ac columns
    if "gene_symbol" in df.columns and "uniprot_ac" in df.columns:
        m = dict(zip(df["gene_symbol"], df["uniprot_ac"]))
        m = {k: v for k, v in m.items() if isinstance(v, str) and v}
        return m
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--out-parquet", required=True, type=Path)
    ap.add_argument("--uniprot-map", type=Path, default=None,
                    help="Optional gene_symbol → uniprot_ac TSV")
    args = ap.parse_args()

    uniprot_map = load_uniprot_map(args.uniprot_map)
    print(f"[03_pool] uniprot map: {len(uniprot_map)} entries", file=sys.stderr)

    frames = []
    for cohort in CPTAC_COHORTS:
        tsv = args.work_dir / f"{cohort}_msstats_results.tsv"
        if not tsv.exists():
            print(f"[03_pool] {cohort}: MISSING {tsv.name}, skipping", file=sys.stderr)
            continue
        df = pd.read_csv(tsv, sep="\t")
        if df.empty:
            print(f"[03_pool] {cohort}: empty, skipping", file=sys.stderr)
            continue
        # Skipped-low-n rows come through as single-row with issue=skipped_low_n
        if len(df) == 1 and str(df.iloc[0].get("issue", "")).startswith("skipped_low_n"):
            print(f"[03_pool] {cohort}: skipped_low_n (n_normal too small)", file=sys.stderr)
            continue

        n_tumor = int(df["n_tumor"].iloc[0])
        n_normal = int(df["n_normal"].iloc[0])
        n_proteins_tested = int(df["gene_symbol"].nunique())

        out = pd.DataFrame({
            "cohort": cohort,
            "gene_symbol": df["gene_symbol"].astype(str),
            "uniprot_ac": df["gene_symbol"].map(uniprot_map).astype("string"),
            "protein_effect_size": df["logFC"].astype(float),
            "protein_p_value": df["pvalue"].astype(float),
            "protein_bh_q_value": df["adj.pvalue"].astype(float),
            "protein_median_log2_tumor": df["med_log2_tumor"].astype(float),
            "protein_median_log2_normal": df["med_log2_normal"].astype(float),
            "n_tumor_samples": n_tumor,
            "n_normal_samples": n_normal,
            "n_proteins_tested_cohort": n_proteins_tested,
            "protein_expression_class": [
                classify(f, q) for f, q in zip(df["logFC"], df["adj.pvalue"])
            ],
            "stat_test_used": STAT_TEST_USED,
            "method_version": METHOD_VERSION,
        })
        frames.append(out)
        n_strong_up = (out["protein_expression_class"] == "strong_up").sum()
        n_modest_up = (out["protein_expression_class"] == "modest_up").sum()
        print(f"[03_pool] {cohort}: {len(out):,} proteins, "
              f"{n_strong_up} strong_up, {n_modest_up} modest_up",
              file=sys.stderr)

    if not frames:
        raise RuntimeError("No cohort results found. Run stage 02 first.")

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["cohort", "gene_symbol"], kind="mergesort").reset_index(drop=True)

    # Pin count columns to int32 to match the derived-manifest schema contract
    # (pandas defaults these to int64, which trips strict schema validation).
    for col in ("n_tumor_samples", "n_normal_samples", "n_proteins_tested_cohort"):
        merged[col] = merged[col].astype("int32")

    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(merged, preserve_index=False)
    pq.write_table(tbl, args.out_parquet, compression="snappy")
    print(f"[03_pool] wrote {args.out_parquet} — {len(merged):,} rows, "
          f"{merged['cohort'].nunique()} cohorts, "
          f"{merged['gene_symbol'].nunique()} unique proteins",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
