"""cli — one-shot emit for depmap-coessentiality-26q1-v1.

Loads the DepMap 26Q1 CRISPRGeneEffect parquet (via depmap_common.parquet shared cache),
runs the standardize→matmul→top-K kernel, writes a gene-sorted long-format parquet, and
uploads it to S3.

Usage:
    python -m methods.depmap_coessentiality.cli \\
        --release-pin 26q1 \\
        --top-k 100 \\
        --min-abs-r 0.2 \\
        --output-prefix s3://onc-compbio/data-catalog/derived/depmap-coessentiality-26q1-v1/

    # Dry-run (no upload):
    python -m methods.depmap_coessentiality.cli --no-upload \\
        --output-prefix /tmp/coessentiality_test/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

S3_BUCKET = "onc-compbio"
OUTPUT_KEY_TEMPLATE = "data-catalog/derived/depmap-coessentiality-{release}-v1/coessentiality_edges.parquet"
SIDECAR_KEY_TEMPLATE = "data-catalog/derived/depmap-coessentiality-{release}-v1/coessentiality_meta.json"

METHOD_VERSION = "0.1.0"


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_emit(
    release_pin: str = "26q1",
    top_k: int = 100,
    min_abs_r: float = 0.20,
    output_prefix: str | None = None,
    no_upload: bool = False,
    aws_profile: str = "cbg",
) -> dict:
    """Load → standardize → matmul → top-K → write parquet → upload.

    Returns a provenance dict suitable for the data-catalog manifest.
    """
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from methods.depmap_common.parquet import _fetch_parquet

    t0 = time.monotonic()

    # --- Load CRISPRGeneEffect parquet ---
    log.info("[coessentiality] Loading CRISPRGeneEffect.parquet …")
    local_path = _fetch_parquet("CRISPRGeneEffect.parquet")
    df = pd.read_parquet(local_path)
    log.info(f"  loaded: {df.shape[0]} cell lines × {df.shape[1]} columns ({time.monotonic()-t0:.1f}s)")

    # Drop the ModelID index column if it landed as a column (pandas artifact)
    id_col = next((c for c in df.columns if c in ("ModelID", "Unnamed: 0", "")), None)
    if id_col is not None:
        df = df.drop(columns=[id_col])

    n_genes_raw = df.shape[1]
    n_cells = df.shape[0]
    log.info(f"  {n_genes_raw} genes, {n_cells} cell lines")

    # --- Build edges ---
    from methods.depmap_coessentiality.compute import build_edges_dataframe

    log.info(f"[coessentiality] Computing co-essentiality (top_k={top_k}, min_abs_r={min_abs_r}) …")
    t1 = time.monotonic()
    edges = build_edges_dataframe(df, k=top_k, min_abs_r=min_abs_r)
    elapsed_compute = time.monotonic() - t1
    log.info(f"  {len(edges):,} edges in {elapsed_compute:.1f}s")
    log.info(f"  genes with ≥1 partner: {edges['gene_symbol'].nunique():,}")
    log.info(f"  genes dropped (>50% NaN): {n_genes_raw - edges['gene_symbol'].nunique():,}")

    # --- Write parquet ---
    if output_prefix and not output_prefix.startswith("s3://"):
        out_dir = Path(output_prefix)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "coessentiality_edges.parquet"
    else:
        out_path = Path(f"/tmp/coessentiality_edges_{release_pin}.parquet")

    schema = pa.schema([
        pa.field("gene_symbol",    pa.string()),
        pa.field("partner_symbol", pa.string()),
        pa.field("pearson_r",      pa.float32()),
        pa.field("abs_rank",       pa.int32()),
        pa.field("n_cell_lines",   pa.int32()),
    ])
    table = pa.Table.from_pandas(edges, schema=schema, preserve_index=False)
    pq.write_table(table, out_path, row_group_size=50_000, compression="snappy")
    size_bytes = out_path.stat().st_size
    md5 = _md5_file(out_path)
    log.info(f"[coessentiality] wrote {out_path} ({size_bytes/1e6:.1f} MB) md5={md5}")

    # --- Sidecar metadata ---
    meta = {
        "method": "depmap_coessentiality",
        "method_version": METHOD_VERSION,
        "release_pin": release_pin,
        "top_k": top_k,
        "min_abs_r": min_abs_r,
        "n_genes_input": n_genes_raw,
        "n_cell_lines": n_cells,
        "n_edges": len(edges),
        "n_genes_with_partners": int(edges["gene_symbol"].nunique()),
        "elapsed_compute_seconds": round(elapsed_compute, 2),
        "output_parquet_md5": md5,
        "output_parquet_size_bytes": size_bytes,
    }

    # --- Upload ---
    if not no_upload:
        import boto3
        session = boto3.Session(profile_name=aws_profile)
        s3 = session.client("s3")

        if output_prefix and output_prefix.startswith("s3://"):
            # Strip s3://bucket/ from prefix
            without_scheme = output_prefix.removeprefix("s3://")
            bucket, prefix = without_scheme.split("/", 1)
            parquet_key = prefix.rstrip("/") + "/coessentiality_edges.parquet"
            sidecar_key = prefix.rstrip("/") + "/coessentiality_meta.json"
        else:
            parquet_key = OUTPUT_KEY_TEMPLATE.format(release=release_pin)
            sidecar_key = SIDECAR_KEY_TEMPLATE.format(release=release_pin)
            bucket = S3_BUCKET

        log.info(f"[coessentiality] uploading → s3://{bucket}/{parquet_key}")
        s3.upload_file(str(out_path), bucket, parquet_key)

        sidecar_path = out_path.with_suffix(".meta.json")
        sidecar_path.write_text(json.dumps(meta, indent=2))
        s3.upload_file(str(sidecar_path), bucket, sidecar_key)
        log.info(f"[coessentiality] uploaded sidecar → s3://{bucket}/{sidecar_key}")
        log.info("[coessentiality] done.")

        meta["s3_parquet_uri"] = f"s3://{bucket}/{parquet_key}"
        meta["s3_sidecar_uri"] = f"s3://{bucket}/{sidecar_key}"

    meta["elapsed_total_seconds"] = round(time.monotonic() - t0, 2)
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Emit depmap-coessentiality-{release}-v1 parquet.")
    ap.add_argument("--release-pin", default="26q1", help="DepMap release label (default: 26q1)")
    ap.add_argument("--top-k", type=int, default=100, help="Neighbors per gene (default: 100)")
    ap.add_argument("--min-abs-r", type=float, default=0.20, help="Min |r| floor (default: 0.20)")
    ap.add_argument("--output-prefix", default=None,
                    help="S3 prefix or local dir. Default: s3://onc-compbio/data-catalog/derived/depmap-coessentiality-{release}-v1/")
    ap.add_argument("--no-upload", action="store_true", help="Skip S3 upload (dry-run)")
    ap.add_argument("--aws-profile", default="cbg", help="AWS profile (default: cbg)")
    args = ap.parse_args(argv)

    result = run_emit(
        release_pin=args.release_pin,
        top_k=args.top_k,
        min_abs_r=args.min_abs_r,
        output_prefix=args.output_prefix,
        no_upload=args.no_upload,
        aws_profile=args.aws_profile,
    )
    import json as _json
    print(_json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
