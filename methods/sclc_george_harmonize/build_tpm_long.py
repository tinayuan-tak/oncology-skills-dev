#!/usr/bin/env python3
"""build_tpm_long — SCLC George 2015 FPKM → recount3-axis log2(TPM+1) long product.

Reads the ingested FPKM matrix (cbioportal-sclc-ucologne-2015), re-normalizes FPKM→TPM
per sample (TPM = FPKM / Σ FPKM × 1e6 — exact, no gene lengths needed), takes log2(TPM+1),
maps Hugo_Symbol → ensembl_gene_id via the ensembl-116 resolver, and emits a long product
(one row per gene×sample) matching tcga-tumor-tpm-recount3-long-v1's schema so the
tumor-presence reader can consume it with the same code path (study='SCLC').

Output: sclc-george-tpm-long-v1/sclc_george_tpm_long.parquet (sorted by ensembl_gene_id).

Usage:
  python -m methods.sclc_george_harmonize.build_tpm_long --out <dir>/sclc_george_tpm_long.parquet [--no-upload]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
import time
from pathlib import Path

S3_BUCKET = "onc-compbio"
DEFAULT_AWS_PROFILE = "cbg"
FPKM_KEY = "data-catalog/sources/cbioportal/sclc-ucologne-2015/data_mrna_seq_fpkm.txt"
ENSEMBL_MAP_KEY = ("data-catalog/sources/ensembl-id-mapping/"
                   "release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv")
OUTPUT_S3_PREFIX = "data-catalog/derived/sclc-george-tpm-long-v1"
STUDY = "SCLC"

# Correctness spot-checks (verified in prototyping): SCLC-A cohort → ASCL1 dominant.
CORRECTNESS = [("ASCL1", ">=", 7.0), ("YAP1", "<=", 3.0)]  # cohort-median log2TPM sanity


def _log(m): print(m, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _s3():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _load_symbol_to_ensembl(s3) -> dict:
    """HGNC symbol → the FIRST ensembl gene id (mirrors the reader's map; symbols with
    multiple ids are rare — take the lexicographically-first for a stable 1:1 emit)."""
    import pandas as pd
    body = s3.get_object(Bucket=S3_BUCKET, Key=ENSEMBL_MAP_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t").dropna(subset=["Gene stable ID", "HGNC symbol"])
    m: dict = {}
    for eid, sym in zip(df["Gene stable ID"], df["HGNC symbol"]):
        s = str(sym).upper().strip()
        if s not in m or eid < m[s]:
            m[s] = eid
    return m


def build():
    import numpy as np
    import pandas as pd
    s3 = _s3()
    t0 = time.time()
    body = s3.get_object(Bucket=S3_BUCKET, Key=FPKM_KEY)["Body"].read()
    fpkm = pd.read_csv(io.BytesIO(body), sep="\t")
    sample_cols = [c for c in fpkm.columns if c not in ("Hugo_Symbol", "Entrez_Gene_Id")]
    _log(f"[read] FPKM {fpkm.shape[0]} genes × {len(sample_cols)} samples in {time.time()-t0:.1f}s")

    # FPKM → TPM per sample (each column re-normalized to sum 1e6), then log2(TPM+1).
    mat = fpkm[sample_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    tpm = mat.div(mat.sum(axis=0), axis=1) * 1e6
    log2tpm = np.log2(tpm + 1.0)

    # symbol → ensembl. Rows with no mapping are DROPPED (can't join the ensembl axis) —
    # counted + logged (honest attrition), consistent with the reader's ensembl-keyed reads.
    sym2ens = _load_symbol_to_ensembl(s3)
    fpkm["_sym"] = fpkm["Hugo_Symbol"].astype(str).str.upper().str.strip()
    fpkm["ensembl_gene_id"] = fpkm["_sym"].map(sym2ens)
    n_total = len(fpkm)
    mapped = fpkm["ensembl_gene_id"].notna()
    _log(f"[map] {mapped.sum()}/{n_total} genes mapped to ensembl "
         f"({n_total - mapped.sum()} unmapped, dropped)")

    # melt to long: one row per (gene, sample). Keep gene_symbol + ensembl + sample_id + study + log2_tpm.
    keep = fpkm.loc[mapped, ["Hugo_Symbol", "ensembl_gene_id"]].copy()
    keep["gene_symbol"] = keep["Hugo_Symbol"].astype(str).str.upper().str.strip()
    vals = log2tpm.loc[mapped].reset_index(drop=True)
    keep = keep.reset_index(drop=True)
    long = pd.concat([keep[["gene_symbol", "ensembl_gene_id"]], vals], axis=1)
    long = long.melt(id_vars=["gene_symbol", "ensembl_gene_id"],
                     var_name="sample_id", value_name="log2_tpm")
    # DEDUPE (gene-keyed product invariant): cBioPortal FPKM matrices carry DUPLICATE
    # Hugo_Symbol rows (multiple loci/probes collapsed to one symbol), and several map to the
    # SAME ensembl id — so the naive melt has >1 row per (ensembl_gene_id, sample_id), which
    # DOUBLE-COUNTS downstream (per-sample distributions + subtype n's inflate). Collapse to one
    # row per (ensembl_gene_id, sample_id) via MAX (matches the NAPY assigner's groupby-max), so
    # a per-gene read returns exactly one value per sample. gene_symbol kept as the first for that id.
    long = (long.sort_values("log2_tpm", ascending=False)
                .drop_duplicates(subset=["ensembl_gene_id", "sample_id"], keep="first"))
    long["study"] = STUDY
    long["log2_tpm"] = long["log2_tpm"].astype("float32")
    # gene-sorted for pushdown (read key = ensembl_gene_id, mirrors the TCGA long product)
    long = long.sort_values(["ensembl_gene_id", "sample_id"]).reset_index(drop=True)
    return long[["gene_symbol", "ensembl_gene_id", "sample_id", "study", "log2_tpm"]], len(sample_cols)


def write(df, out: Path, row_group_size: int = 65536) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("ensembl_gene_id", pa.string()),
        pa.field("sample_id", pa.string()),
        pa.field("study", pa.string()),
        pa.field("log2_tpm", pa.float32()),
    ])
    pq.write_table(pa.Table.from_pandas(df[[f.name for f in schema]], schema=schema,
                                        preserve_index=False),
                   str(out), compression="snappy", row_group_size=row_group_size)
    return {"md5": _md5_hex(out), "size_bytes": out.stat().st_size, "n_rows": len(df)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the SCLC George FPKM→log2(TPM+1) long product.")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--row-group-size", type=int, default=65536)
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    df, n_samples = build()
    meta = write(df, args.out, args.row_group_size)
    n_genes = df["ensembl_gene_id"].nunique()
    _log(f"[write] {args.out.name}: {meta['n_rows']} rows / {n_genes} genes / {n_samples} samples / "
         f"{meta['size_bytes']} B / md5={meta['md5']}")

    # correctness gate (cohort-median of a few markers)
    for sym, cmp_, thr in CORRECTNESS:
        med = df.loc[df["gene_symbol"] == sym, "log2_tpm"].median()
        ok = (med >= thr) if cmp_ == ">=" else (med <= thr)
        _log(f"  check {sym} cohort-median log2TPM={med:.2f} {cmp_} {thr} {'OK' if ok else 'UNEXPECTED'}")

    if not args.no_upload:
        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        _s3().upload_file(str(args.out), S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": meta["md5"]}})
        _log(f"[upload] s3://{S3_BUCKET}/{key}")
    else:
        _log("[upload] skipped (--no-upload)")
    print(f"md5={meta['md5']} size_bytes={meta['size_bytes']} n_rows={meta['n_rows']} "
          f"n_genes={n_genes} n_samples={n_samples}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
