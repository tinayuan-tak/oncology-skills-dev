#!/usr/bin/env python3
"""rewrite_long — re-encode tcga-tumor-tpm-per-sample-v1 (wide) into long/tidy.

The TUMOR analogue of gtex_tpm_precompute/rewrite_long. Motivation identical: the wide gene-row /
sample-column layout makes per-gene predicate-pushdown reads slow (>2 min — Parquet parses metadata
for ~10k sample column chunks), which mismatches the primary access pattern (pan-tissue plot: one
gene → its distribution across all TCGA studies). This re-encodes to long/tidy sorted by
ensembl_gene_id with modest row-groups, so a single-gene query touches 2-3 row-groups.

PURE LAYOUT RE-ENCODING — consumes LOCAL copies of the wide product + sidecar; does NOT re-stream
recount3 or recompute TPM. Values are byte-identical to the wide matrix.

Input:  tcga_tpm_log2.parquet + tcga_sample_study.parquet (already on S3 under
        derived/tcga-tumor-tpm-per-sample-v1/).
Output: tcga_tpm_long.parquet with columns:
    gene_symbol      string   HGNC symbol (not unique)
    ensembl_gene_id  string   Unversioned Ensembl gene ID — sort key + effective PK
    sample_id        string   recount3 gdc_file_id (matches the sidecar)
    study            string   TCGA study code (COAD, LUAD, ...); embedded so no join needed
    log2_tpm         float32  log2(TPM + 1); identical values to the wide matrix

Sorted by ensembl_gene_id. Row-group ~8k rows so each gene's ~10k rows spans 2-3 row-groups and a
filter `ensembl_gene_id == X` (or `gene_symbol == X`) prunes to just those.

Usage:
    python -m onc_methods.tcga_tpm_precompute.rewrite_long \\
        --wide-parquet ~/dev/framework-runs/tcga-tpm-precompute-v1/tcga_tpm_log2.parquet \\
        --sidecar      ~/dev/framework-runs/tcga-tpm-precompute-v1/tcga_sample_study.parquet \\
        --out          ~/dev/framework-runs/tcga-tpm-long-v1/tcga_tpm_long.parquet \\
        --no-upload    # smoke run; omit to upload to
                       # s3://onc-compbio/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import click

DEPMAP_S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/tcga-tumor-tpm-recount3-long-v1"

# Validation triples: (gene_symbol, study, description). Actual log2_tpm medians are checked against
# the wide matrix at emit time — tumor-appropriate genes across a few studies.
CORRECTNESS_TRIPLES = [
    ("KRAS", "COAD", "broadly-expressed oncogene, colorectal"),
    ("EPCAM", "COAD", "epithelial marker, high in carcinomas"),
    ("GFAP", "GBM", "astrocyte marker, high in glioblastoma"),
]


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — integrity, not security
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_long(wide_path: Path, sidecar_path: Path, out_path: Path, row_group_size: int) -> tuple[int, dict]:
    """Read wide matrix + sidecar, melt to long (sorted by ensembl_gene_id), write long parquet.
    Returns (size_bytes, stats_dict)."""
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    _log(f"[rewrite_long] reading sidecar {sidecar_path}")
    sidecar = pd.read_parquet(sidecar_path)
    sample_to_study = dict(zip(sidecar["sample_id"], sidecar["study"]))
    _log(f"  sidecar: {len(sidecar):,} samples across {sidecar['study'].nunique()} studies")

    _log(f"[rewrite_long] opening wide parquet {wide_path}")
    wide_pf = pq.ParquetFile(str(wide_path))
    all_cols = wide_pf.schema_arrow.names
    key_cols = ["gene_symbol", "ensembl_gene_id"]
    sample_cols = [c for c in all_cols if c not in key_cols]
    _log(f"  wide: {wide_pf.metadata.num_rows:,} genes x {len(sample_cols):,} samples")
    missing = [s for s in sample_cols if s not in sample_to_study]
    if missing:
        raise RuntimeError(f"{len(missing)} sample columns absent from sidecar; first 3: {missing[:3]}")

    long_schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("ensembl_gene_id", pa.string()),
            pa.field("sample_id", pa.string()),
            pa.field("study", pa.string()),
            pa.field("log2_tpm", pa.float32()),
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"[rewrite_long] melting -> {out_path} (row_group_size={row_group_size})")

    study_series = pd.Series(sample_to_study)  # sample_id -> study lookup
    n_total = n_row_groups_written = 0
    study_uniq: set[str] = set()
    ensembl_uniq: set[str] = set()

    writer = pq.ParquetWriter(str(out_path), long_schema, compression="snappy")
    try:
        t0 = time.monotonic()
        _log("  reading wide matrix into memory...")
        wide = wide_pf.read().to_pandas()
        _log(f"  loaded wide dataframe: {wide.shape} ({time.monotonic() - t0:.0f}s)")

        # Sort by ensembl_gene_id BEFORE melting so the long parquet is naturally sorted
        # (critical for per-gene pushdown).
        wide = wide.sort_values("ensembl_gene_id").reset_index(drop=True)
        ensembl_uniq.update(wide["ensembl_gene_id"].unique())

        BATCH = 512  # genes per melt-batch
        _log(f"  melting in gene-batches of {BATCH} ...")
        for batch_start in range(0, len(wide), BATCH):
            batch = wide.iloc[batch_start : batch_start + BATCH]
            melted = batch.melt(id_vars=key_cols, value_vars=sample_cols, var_name="sample_id", value_name="log2_tpm")
            # CRITICAL: melt emits SAMPLE-major rows (gene0,gene1,…,gene0,gene1,…), so within a
            # batch every row-group spans the whole 512-gene range — per-gene pushdown then can't
            # prune below the batch (~500x read amplification; measured 7-132s/gene). Re-sort the
            # MELTED frame by ensembl_gene_id so each row-group covers a narrow contiguous gene span
            # and a single-gene filter touches 1-3 row-groups. (Sorting the WIDE frame earlier is
            # necessary but NOT sufficient — melt destroys that order.)
            melted = melted.sort_values("ensembl_gene_id", kind="stable").reset_index(drop=True)
            melted["study"] = melted["sample_id"].map(study_series)
            melted = melted[["gene_symbol", "ensembl_gene_id", "sample_id", "study", "log2_tpm"]]
            melted["log2_tpm"] = melted["log2_tpm"].astype(np.float32)
            study_uniq.update(melted["study"].unique())
            table = pa.Table.from_pandas(melted, schema=long_schema, preserve_index=False)
            writer.write_table(table, row_group_size=row_group_size)
            n_total += len(melted)
            n_row_groups_written += (len(melted) + row_group_size - 1) // row_group_size
            if batch_start % (BATCH * 20) == 0:
                _log(
                    f"    processed {batch_start + len(batch):,}/{len(wide):,} genes "
                    f"(long rows so far: {n_total:,}, {time.monotonic() - t0:.0f}s)"
                )
    finally:
        writer.close()

    size_bytes = out_path.stat().st_size
    stats = {
        "n_rows": n_total,
        "n_row_groups": n_row_groups_written,
        "n_ensembl_ids": len(ensembl_uniq),
        "n_samples": len(sample_cols),
        "n_studies": len(study_uniq),
    }
    _log(
        f"[rewrite_long] wrote {out_path} ({size_bytes / 1e9:.2f} GB) "
        f"| rows={n_total:,} | row_groups={n_row_groups_written:,}"
    )
    return size_bytes, stats


def correctness_check(wide_path: Path, sidecar_path: Path, long_path: Path) -> None:
    """Assert 3 (gene, study) medians match between wide and long products."""
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    sidecar = pd.read_parquet(sidecar_path)
    _log("[rewrite_long] correctness check:")
    for gene, study, desc in CORRECTNESS_TRIPLES:
        t0 = time.monotonic()
        wide_row = pq.read_table(str(wide_path), filters=[("gene_symbol", "=", gene)]).to_pandas()
        if wide_row.empty:
            _log(f"  {gene}: WIDE has no row — skipping")
            continue
        wide_row = wide_row.iloc[0]
        study_samples = set(sidecar.loc[sidecar["study"] == study, "sample_id"])
        wide_vals = np.array([float(wide_row[s]) for s in study_samples if s in wide_row.index], dtype=float)
        wide_median = float(np.median(wide_vals)) if len(wide_vals) else float("nan")
        wide_dt = time.monotonic() - t0

        t0 = time.monotonic()
        long_hit = pq.read_table(
            str(long_path), filters=[("gene_symbol", "=", gene), ("study", "=", study)]
        ).to_pandas()
        long_median = float(long_hit["log2_tpm"].median()) if not long_hit.empty else float("nan")
        long_dt = time.monotonic() - t0

        _log(
            f"  {gene:6s} {study:5s} | wide median={wide_median:.4f} ({wide_dt:.2f}s)  |  "
            f"long median={long_median:.4f} ({long_dt:.2f}s)  |  {desc}"
        )
        diff = abs(wide_median - long_median)
        assert diff < 1e-4, f"MISMATCH {gene}/{study}: wide={wide_median} long={long_median} |diff|={diff}"
    _log("  all triples matched (|diff| < 1e-4).")


@click.command()
@click.option(
    "--wide-parquet",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Local path to tcga_tpm_log2.parquet (the v1 wide product).",
)
@click.option(
    "--sidecar",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Local path to tcga_sample_study.parquet (v1 sidecar).",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Local output path for tcga_tpm_long.parquet.",
)
@click.option(
    "--row-group-size",
    type=int,
    default=8192,
    help="Rows per Parquet row-group. Tuned so one gene's ~10k rows spans 2-3 row-groups.",
)
@click.option("--no-upload", is_flag=True, help="Write locally only; skip S3 upload.")
@click.option(
    "--skip-correctness-check", is_flag=True, help="Skip wide-vs-long assertions (only for iterating on layout)."
)
def main(
    wide_parquet: Path, sidecar: Path, out: Path, row_group_size: int, no_upload: bool, skip_correctness_check: bool
) -> None:
    """Re-encode the wide TCGA tumor TPM matrix to long/tidy for fast per-gene reads."""
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
        s3.upload_file(str(out), DEPMAP_S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": md5}})
        _log("[rewrite_long] uploaded.")

    _log(f"[rewrite_long] done. size={size_bytes} md5={md5}")


if __name__ == "__main__":
    main()
