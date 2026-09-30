#!/usr/bin/env python3
"""resort_long — globally re-sort tcga-tumor-tpm-recount3-long-v1 by ensembl_gene_id.

The existing long product was emitted with a per-batch sort (each 512-gene melt batch was
sorted by ensembl_gene_id independently, then written sequentially). Because the wide matrix
is gene_symbol-ordered, consecutive batches contain genes whose Ensembl IDs interleave rather
than follow a continuous range. Parquet row-group min/max statistics on ensembl_gene_id
therefore overlap across ALL batch boundaries — predicate pushdown cannot prune any row-group
for a single-gene query, yielding full-file scans at 65–132 s from S3.

This script consumes the existing long product (local or S3) and writes a new version that
is GLOBALLY sorted by ensembl_gene_id using DuckDB's out-of-core ORDER BY — DuckDB spills to
disk, keeping peak RAM under ~4 GB regardless of file size. Expected output row-group
statistics are non-overlapping, so a `ensembl_gene_id == X` filter prunes to 2–3 row-groups
out of ~51k.

Pure re-sort — values are byte-identical to the input. Does NOT re-stream recount3 or
recompute TPM. Does NOT change schema.

Output schema (unchanged from v1 long product):
    gene_symbol      string
    ensembl_gene_id  string   <- sort key; row-group stats will be non-overlapping
    sample_id        string
    study            string
    log2_tpm         float32

Usage:
    # Smoke run (local → local, no upload):
    python -m onc_methods.tcga_tpm_precompute.resort_long \\
        --in  s3://onc-compbio/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet \\
        --out ~/dev/framework-runs/tcga-tpm-resort/tcga_tpm_long.parquet \\
        --no-upload

    # Production run (S3 → local → upload back):
    python -m onc_methods.tcga_tpm_precompute.resort_long \\
        --in  s3://onc-compbio/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet \\
        --out ~/dev/framework-runs/tcga-tpm-resort/tcga_tpm_long.parquet
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import click

S3_BUCKET = "onc-compbio"
OUTPUT_S3_KEY = "data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet"

# Validation: (gene_symbol, study) — per-gene per-study median should be unchanged.
CORRECTNESS_CHECKS = [
    ("KRAS", "COAD"),
    ("EPCAM", "COAD"),
    ("GFAP", "GBM"),
]


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — integrity not security
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


from onc_methods.target_id_sidecar import ensure_aws_profile


def resort(in_uri: str, out_path: Path, row_group_size: int) -> tuple[int, dict]:
    """Re-sort the long parquet globally by ensembl_gene_id using DuckDB out-of-core sort.

    Returns (size_bytes, stats_dict).
    """
    import duckdb

    ensure_aws_profile()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Cap memory so DuckDB spills to disk before any OOM risk.
    # 419M rows x ~71 bytes ≈ 30 GB raw; 2× sort buffer = 60 GB would exceed a 62 GB
    # instance. At 40 GB DuckDB writes spill files under temp_directory and keeps
    # peak RSS well below available RAM.
    tmp_dir = out_path.parent / "_duckdb_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='40GB';")
    con.execute(f"SET temp_directory='{tmp_dir}';")

    if in_uri.startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("SET s3_region='us-east-1';")
        # Inject SSO credentials explicitly — DuckDB httpfs does not always pick up the
        # boto3 SSO credential chain reliably; injecting via CREATE SECRET is the safe path.
        import boto3

        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "cbg"))
        creds = session.get_credentials().get_frozen_credentials()
        con.execute(f"""
            CREATE SECRET s3_cbg (
                TYPE S3,
                KEY_ID '{creds.access_key}',
                SECRET '{creds.secret_key}',
                SESSION_TOKEN '{creds.token}',
                REGION 'us-east-1'
            )
        """)

    in_ref = f"read_parquet('{in_uri}')"

    # Row count + distinct-gene sanity check before sorting
    _log(f"[resort_long] counting input rows in {in_uri} ...")
    t0 = time.monotonic()
    row_count, gene_count = con.execute(f"SELECT COUNT(*), COUNT(DISTINCT ensembl_gene_id) FROM {in_ref}").fetchone()
    _log(f"  {row_count:,} rows, {gene_count:,} distinct ensembl_gene_ids ({time.monotonic() - t0:.0f}s)")

    _log(f"[resort_long] sorting -> {out_path}  (row_group_size={row_group_size})")
    t0 = time.monotonic()
    con.execute(f"""
        COPY (
            SELECT gene_symbol, ensembl_gene_id, sample_id, study, log2_tpm
            FROM {in_ref}
            ORDER BY ensembl_gene_id
        )
        TO '{out_path}'
        (FORMAT PARQUET, COMPRESSION 'snappy', ROW_GROUP_SIZE {row_group_size})
    """)
    elapsed = time.monotonic() - t0
    size_bytes = out_path.stat().st_size
    _log(f"[resort_long] wrote {out_path} ({size_bytes / 1e9:.2f} GB) in {elapsed:.0f}s")

    import shutil

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    stats = {"n_rows_in": row_count, "n_genes": gene_count, "size_bytes": size_bytes, "elapsed_s": elapsed}
    return size_bytes, stats


def verify_sort(out_path: Path, n_sample: int = 500) -> None:
    """Check that row-group ensembl_gene_id statistics are non-overlapping."""
    import pyarrow.parquet as pq

    _log(f"[resort_long] verifying sort on {out_path} (sampling {n_sample} row-groups) ...")
    pf = pq.ParquetFile(str(out_path))
    md = pf.metadata
    _log(f"  {md.num_row_groups:,} row-groups, {md.num_rows:,} rows")

    eid_col = None
    for j in range(md.row_group(0).num_columns):
        if md.row_group(0).column(j).path_in_schema == "ensembl_gene_id":
            eid_col = j
            break
    if eid_col is None:
        raise RuntimeError("ensembl_gene_id column not found in output schema")

    overlaps = 0
    prev_max = None
    for i in range(min(n_sample, md.num_row_groups)):
        st = md.row_group(i).column(eid_col).statistics
        if st is None:
            continue
        if prev_max is not None and st.min < prev_max:
            overlaps += 1
        prev_max = st.max

    if overlaps > 0:
        raise RuntimeError(
            f"Sort verification FAILED: {overlaps} row-group pairs have overlapping "
            f"ensembl_gene_id ranges in first {n_sample} row-groups. "
            "The output is not globally sorted."
        )
    _log(
        f"  Sort verification OK — 0 overlapping ensembl_gene_id ranges in "
        f"{min(n_sample, md.num_row_groups)} sampled row-groups."
    )


def correctness_check(in_uri: str, out_path: Path) -> None:
    """Assert per-(gene, study) medians match between input and re-sorted output."""
    import duckdb

    _log("[resort_long] correctness check (per-gene per-study median):")
    con = duckdb.connect()
    if in_uri.startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("SET s3_region='us-east-1';")
        import boto3

        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "cbg"))
        creds = session.get_credentials().get_frozen_credentials()
        con.execute(f"""
            CREATE SECRET s3_cbg2 (
                TYPE S3,
                KEY_ID '{creds.access_key}',
                SECRET '{creds.secret_key}',
                SESSION_TOKEN '{creds.token}',
                REGION 'us-east-1'
            )
        """)

    out_ref = f"read_parquet('{out_path}')"
    in_ref = f"read_parquet('{in_uri}')"

    all_ok = True
    for gene, study in CORRECTNESS_CHECKS:
        med_in = con.execute(
            f"SELECT median(log2_tpm) FROM {in_ref}  WHERE gene_symbol='{gene}' AND study='{study}'"
        ).fetchone()[0]
        med_out = con.execute(
            f"SELECT median(log2_tpm) FROM {out_ref} WHERE gene_symbol='{gene}' AND study='{study}'"
        ).fetchone()[0]
        diff = abs((med_in or 0.0) - (med_out or 0.0))
        ok = diff < 1e-4
        _log(
            f"  {gene:6s}/{study:5s}  in={med_in:.4f}  out={med_out:.4f}  diff={diff:.6f}  {'OK' if ok else 'MISMATCH'}"
        )
        if not ok:
            all_ok = False

    if not all_ok:
        raise RuntimeError("Correctness check FAILED — medians differ between input and output.")
    _log("  All checks passed.")


@click.command()
@click.option("--in", "in_uri", required=True, help="Input long parquet (local path or s3:// URI).")
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Local output path for the re-sorted parquet.",
)
@click.option(
    "--row-group-size",
    type=int,
    default=8192,
    help="Rows per output row-group (default 8192 — each gene spans ~2-3 groups).",
)
@click.option("--no-upload", is_flag=True, help="Skip S3 upload; write locally only.")
@click.option("--skip-correctness-check", is_flag=True, help="Skip per-gene median assertions.")
def main(in_uri: str, out: Path, row_group_size: int, no_upload: bool, skip_correctness_check: bool) -> None:
    """Globally re-sort the TCGA long TPM parquet by ensembl_gene_id for fast per-gene reads."""
    import boto3

    ensure_aws_profile()

    size_bytes, stats = resort(in_uri, out, row_group_size)
    _log(f"[resort_long] stats: {stats}")

    verify_sort(out)

    md5 = _md5_hex(out)
    _log(f"[resort_long] md5={md5}")

    if not skip_correctness_check:
        correctness_check(in_uri, out)

    if not no_upload:
        s3 = boto3.client("s3")
        _log(f"[resort_long] uploading to s3://{S3_BUCKET}/{OUTPUT_S3_KEY}")
        s3.upload_file(
            str(out), S3_BUCKET, OUTPUT_S3_KEY, ExtraArgs={"Metadata": {"md5": md5, "sort_key": "ensembl_gene_id"}}
        )
        _log("[resort_long] upload complete.")

    _log(f"[resort_long] done. size={size_bytes:,} md5={md5}")


if __name__ == "__main__":
    main()
