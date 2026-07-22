#!/usr/bin/env python3
"""rewrite_long — re-encode gtex-tpm-recount3-per-sample-v1 (wide) into long/tidy.

Motivation: the wide gene-row / sample-column layout is optimal for whole-
matrix scans and tissue-scoped column-subset reads, but Parquet metadata for
~19k sample column chunks makes per-gene predicate-pushdown reads ~46s. That
mismatches the primary access pattern (pan-tissue plot: one gene -> its
distribution across all tissues). This module re-encodes to long/tidy sorted
by ensembl_gene_id with modest row-group size, so a single-gene query touches
2-3 row-groups instead of the whole file.

Input:  gtex_tpm_log2.parquet + gtex_sample_tissue.parquet (already on S3
        under derived/gtex-tpm-recount3-per-sample-v1/). We consume LOCAL
        copies of these files -- the emitter does NOT re-stream recount3 or
        recompute TPM; it is a pure layout re-encoding of the wide product.

Output: gtex_tpm_long.parquet with columns:
    gene_symbol      string   HGNC symbol (not unique - 14 collisions across ensembl_gene_id)
    ensembl_gene_id  string   Unversioned Ensembl gene ID - the sort key + effective PK
    sample_id        string   GTEx external_id / SAMPID (matches sidecar)
    tissue           string   Recount3 tissue code (COLON, LUNG, ...); embedded so no join needed
    log2_tpm         float32  log2(TPM + 1); identical values to the wide matrix

Sorted by (ensembl_gene_id, sample_id). Row-group ~8k rows -> each gene's ~19k
rows spans 2-3 row-groups, and a filter `ensembl_gene_id == X` prunes to just
those row-groups.

Correctness check (baked into the CLI): loads three (gene, tissue) pairs from
both the wide and long products and asserts the log2_tpm values match.

Usage:
    python -m methods.gtex_tpm_precompute.rewrite_long \\
        --wide-parquet  ~/dev/framework-runs/gtex-tpm-full/gtex_tpm_log2.parquet \\
        --sidecar       ~/dev/framework-runs/gtex-tpm-full/gtex_sample_tissue.parquet \\
        --out           ~/dev/framework-runs/gtex-tpm-long/gtex_tpm_long.parquet \\
        --no-upload    # smoke run; omit to upload to
                       # s3://onc-compbio/data-catalog/derived/gtex-tpm-recount3-long-v1/
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import click


DEPMAP_S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/gtex-tpm-recount3-long-v1"

# Validation triples: (gene_symbol, tissue, description) — expected biological
# behavior known from the wide-product validation. Actual log2_tpm values are
# checked against the wide matrix at emit time.
CORRECTNESS_TRIPLES = [
    ("EPCAM", "COLON", "epithelial marker, moderate in colon"),
    ("ACTB",  "COLON", "housekeeping, high everywhere"),
    ("GFAP",  "BRAIN", "astrocyte marker, high in brain"),
]


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — integrity, not security
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_long(wide_path: Path, sidecar_path: Path, out_path: Path,
               row_group_size: int) -> tuple[int, dict]:
    """Read wide matrix + sidecar, melt to long, write sorted long parquet.

    Returns (size_bytes, stats_dict) where stats_dict has n_rows,
    n_row_groups, n_ensembl_ids, n_samples, n_tissues.
    """
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    _log(f"[rewrite_long] reading sidecar {sidecar_path}")
    sidecar = pd.read_parquet(sidecar_path)
    sample_to_tissue = dict(zip(sidecar["sample_id"], sidecar["tissue"]))
    _log(f"  sidecar: {len(sidecar):,} samples across "
         f"{sidecar['tissue'].nunique()} tissues")

    _log(f"[rewrite_long] opening wide parquet {wide_path}")
    wide_pf = pq.ParquetFile(str(wide_path))
    schema = wide_pf.schema_arrow
    all_cols = schema.names
    key_cols = ["gene_symbol", "ensembl_gene_id"]
    sample_cols = [c for c in all_cols if c not in key_cols]
    _log(f"  wide: {wide_pf.metadata.num_rows:,} genes x {len(sample_cols):,} samples")
    # Sanity: every sample column must be in the sidecar (avoids silent tissue=NaN).
    missing = [s for s in sample_cols if s not in sample_to_tissue]
    if missing:
        raise RuntimeError(
            f"{len(missing)} sample columns absent from sidecar; first 3: {missing[:3]}"
        )

    # Melt row-group by row-group and write a growing Parquet file so peak
    # memory stays modest (one row-group * ~19k samples ~ manageable).
    long_schema = pa.schema([
        pa.field("gene_symbol",     pa.string()),
        pa.field("ensembl_gene_id", pa.string()),
        pa.field("sample_id",       pa.string()),
        pa.field("tissue",          pa.string()),
        pa.field("log2_tpm",        pa.float32()),
    ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"[rewrite_long] melting {wide_pf.num_row_groups:,} row-groups "
         f"-> {out_path} (row_group_size={row_group_size})")

    # Collect all melted rows into one DataFrame first, sort by ensembl_gene_id,
    # then write with controlled row-group size. Peak memory: ~790M rows * ~40B
    # = ~30 GB uncompressed pandas — too much. Instead: pre-sort the wide
    # parquet's genes (they're already sorted by gene_symbol; we re-sort in the
    # melt to guarantee ensembl_gene_id order), melt in gene-batches, write
    # incrementally with a ParquetWriter.
    tissue_series = pd.Series(sample_to_tissue)  # sample_id -> tissue lookup

    n_total = 0
    n_row_groups_written = 0
    tissue_uniq: set[str] = set()
    ensembl_uniq: set[str] = set()

    writer = pq.ParquetWriter(str(out_path), long_schema, compression="snappy")
    try:
        # Read one row-group of the wide parquet at a time (each row-group in
        # v1 = 64 genes * 19,081 samples ~ 1.2M cells). Melt + append.
        BATCH = 512  # genes per melt-batch — bigger for fewer writer.write_table calls
        wide_pf_read_kwargs = {}
        t0 = time.monotonic()

        # Read full parquet into memory once — 5 GB is manageable on this box
        # and simpler than gene-batched reads across the columnar layout. If
        # this OOMs, switch to per-row-group `wide_pf.read_row_group(i)`.
        _log("  reading wide matrix into memory...")
        wide = wide_pf.read().to_pandas()
        _log(f"  loaded wide dataframe: {wide.shape} ({time.monotonic()-t0:.0f}s)")

        # Sort by ensembl_gene_id BEFORE melting so the long parquet is
        # naturally sorted — critical for per-gene pushdown.
        wide = wide.sort_values("ensembl_gene_id").reset_index(drop=True)
        ensembl_uniq.update(wide["ensembl_gene_id"].unique())

        _log(f"  melting in gene-batches of {BATCH} ...")
        for batch_start in range(0, len(wide), BATCH):
            batch = wide.iloc[batch_start:batch_start + BATCH]
            # melt this batch: (gene_symbol, ensembl_gene_id, sample_id, log2_tpm)
            melted = batch.melt(
                id_vars=key_cols,
                value_vars=sample_cols,
                var_name="sample_id",
                value_name="log2_tpm",
            )
            # CRITICAL: melt emits SAMPLE-major rows, so within a batch every row-group spans the
            # whole 512-gene range and per-gene pushdown can't prune below the batch (~500x read
            # amplification). Re-sort the MELTED frame by ensembl_gene_id so each row-group covers a
            # narrow contiguous gene span (single-gene filter → 1-3 row-groups). Sorting the WIDE
            # frame above is necessary but NOT sufficient — melt destroys that order.
            melted = melted.sort_values("ensembl_gene_id", kind="stable").reset_index(drop=True)
            # add tissue via vectorized map
            melted["tissue"] = melted["sample_id"].map(tissue_series)
            # column order + dtype
            melted = melted[["gene_symbol", "ensembl_gene_id", "sample_id",
                             "tissue", "log2_tpm"]]
            melted["log2_tpm"] = melted["log2_tpm"].astype(np.float32)
            tissue_uniq.update(melted["tissue"].unique())

            table = pa.Table.from_pandas(melted, schema=long_schema,
                                         preserve_index=False)
            # Write with row_group_size — pyarrow will chunk within table
            writer.write_table(table, row_group_size=row_group_size)
            n_total += len(melted)
            n_row_groups_written += (len(melted) + row_group_size - 1) // row_group_size
            if batch_start % (BATCH * 20) == 0:
                _log(f"    processed {batch_start + len(batch):,}/{len(wide):,} genes "
                     f"(long rows so far: {n_total:,}, "
                     f"{time.monotonic()-t0:.0f}s)")
    finally:
        writer.close()

    size_bytes = out_path.stat().st_size
    stats = {
        "n_rows": n_total,
        "n_row_groups": n_row_groups_written,
        "n_ensembl_ids": len(ensembl_uniq),
        "n_samples": len(sample_cols),
        "n_tissues": len(tissue_uniq),
    }
    _log(f"[rewrite_long] wrote {out_path} ({size_bytes/1e9:.2f} GB) "
         f"| rows={n_total:,} | row_groups={n_row_groups_written:,}")
    return size_bytes, stats


def correctness_check(wide_path: Path, sidecar_path: Path,
                      long_path: Path) -> None:
    """Assert 3 (gene, tissue) medians match between wide and long products."""
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    sidecar = pd.read_parquet(sidecar_path)

    _log("[rewrite_long] correctness check:")
    for gene, tissue, desc in CORRECTNESS_TRIPLES:
        # WIDE: read the whole gene row, then subset to tissue's sample cols
        t0 = time.monotonic()
        wide_row = pq.read_table(
            str(wide_path),
            filters=[("gene_symbol", "=", gene)],
        ).to_pandas()
        if wide_row.empty:
            _log(f"  {gene}: WIDE has no row — skipping")
            continue
        wide_row = wide_row.iloc[0]
        tissue_samples = set(sidecar.loc[sidecar["tissue"] == tissue, "sample_id"])
        wide_vals = np.array(
            [float(wide_row[s]) for s in tissue_samples if s in wide_row.index],
            dtype=float,
        )
        wide_median = float(np.median(wide_vals)) if len(wide_vals) else float("nan")
        wide_dt = time.monotonic() - t0

        # LONG: predicate-pushdown by gene_symbol, then subset to tissue rows
        t0 = time.monotonic()
        long_hit = pq.read_table(
            str(long_path),
            filters=[("gene_symbol", "=", gene), ("tissue", "=", tissue)],
        ).to_pandas()
        long_median = (float(long_hit["log2_tpm"].median())
                       if not long_hit.empty else float("nan"))
        long_dt = time.monotonic() - t0

        _log(f"  {gene:6s} {tissue:6s} | wide median={wide_median:.4f} "
             f"({wide_dt:.2f}s)  |  long median={long_median:.4f} "
             f"({long_dt:.2f}s)  |  {desc}")

        diff = abs(wide_median - long_median)
        assert diff < 1e-4, (
            f"MISMATCH {gene}/{tissue}: wide={wide_median} long={long_median} "
            f"|diff|={diff}"
        )
    _log("  all triples matched (|diff| < 1e-4).")


@click.command()
@click.option("--wide-parquet", type=click.Path(exists=True, dir_okay=False,
                                                path_type=Path), required=True,
              help="Local path to gtex_tpm_log2.parquet (the v1 wide product).")
@click.option("--sidecar", type=click.Path(exists=True, dir_okay=False,
                                           path_type=Path), required=True,
              help="Local path to gtex_sample_tissue.parquet (v1 sidecar).")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path),
              required=True, help="Local output path for gtex_tpm_long.parquet.")
@click.option("--row-group-size", type=int, default=8192,
              help="Rows per Parquet row-group in the long output. Tuned so "
                   "one gene's ~19k rows span 2-3 row-groups.")
@click.option("--no-upload", is_flag=True,
              help="Write locally only; skip S3 upload.")
@click.option("--skip-correctness-check", is_flag=True,
              help="Skip the wide-vs-long sanity assertions (do not use in "
                   "production; only for iterating on layout).")
def main(wide_parquet: Path, sidecar: Path, out: Path,
         row_group_size: int, no_upload: bool, skip_correctness_check: bool) -> None:
    """Re-encode the wide GTEx TPM matrix to long/tidy for fast per-gene reads."""
    import boto3

    size_bytes, stats = build_long(wide_parquet, sidecar, out, row_group_size)
    md5 = _md5_hex(out)
    _log(f"[rewrite_long] md5={md5}")
    _log(f"[rewrite_long] stats: {stats}")

    if not skip_correctness_check:
        correctness_check(wide_parquet, sidecar, out)

    if not no_upload:
        s3 = boto3.client("s3")
        key = f"{OUTPUT_S3_PREFIX}/{out.name}"
        _log(f"[rewrite_long] uploading to s3://{DEPMAP_S3_BUCKET}/{key}")
        s3.upload_file(str(out), DEPMAP_S3_BUCKET, key,
                       ExtraArgs={"Metadata": {"md5": md5}})
        _log(f"[rewrite_long] uploaded.")

    _log(f"[rewrite_long] done. size={size_bytes} md5={md5}")


if __name__ == "__main__":
    main()
