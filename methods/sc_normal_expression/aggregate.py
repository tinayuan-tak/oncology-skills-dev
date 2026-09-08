#!/usr/bin/env python3
"""aggregate — Tier-2 → Tier-1 cross-donor aggregation for sc-normal-celltype-expression-{tissue}-v1.

Reads sc-pseudobulk-normal-celltype-{tissue}-v1 (Tier-2: 935M rows for colon, ~1.7B for lung)
from S3 and writes sc-normal-celltype-expression-{tissue}-v1 (Tier-1: ~30-40M rows after the
median_det > 0.01 filter) to S3.

The single DuckDB pass computes per-(gene, tissue, cell_type):
  - n_donors_total:           all donor groups (including small-n ones)
  - n_donors_reliable:        groups with n_cells >= 10 (statistically reliable detection estimates)
  - n_datasets_reliable:      distinct dataset_ids with n_cells >= 10 (atlas replication count —
                               a HIGH_LIABILITY call from 1 dataset vs. 3 independent atlases are
                               qualitatively different confidence levels)
  - n_donors_expressing:      reliable groups with detection_fraction > 0.10
  - median_det:               cross-donor median detection_fraction (reliable donors only)
  - q25_det / q75_det:        IQR of detection_fraction
  - expressing_donor_fraction: n_donors_expressing / n_donors_reliable
  - median_abund:             cross-donor median abundance_log1p_cp10k
  - q25_abund / q75_abund:    IQR of abundance (q25 enables bimodality detection — a high q75
                               with low median signals a high-expressing tail, not uniform expression)
  - detection_pct_rank:       PERCENT_RANK over cell types for this gene+tissue
  - n_cell_types_above_20pct: count of cell types with median_det > 0.20 (breadth indicator)

Output is gene-sorted (predicate-pushdown for per-gene reads).

Usage:
    # Full run (reads + writes to S3):
    python -m methods.sc_normal_expression.aggregate --tissue colon

    # Dry-run (no upload — writes local parquet to --out):
    python -m methods.sc_normal_expression.aggregate --tissue colon --no-upload --out /tmp/test.parquet

S3 auth: DuckDB httpfs does not reliably pick up boto3 SSO credential chain; injected via
CREATE SECRET (same pattern as methods/tcga_tpm_precompute/resort_long.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

S3_BUCKET = "onc-compbio"
# Tier-2 product path template (output of data-catalog aggregate_sc_pseudobulk.py --normal-mode)
TIER2_PRODUCT_TEMPLATE = (
    "s3://onc-compbio/data-catalog/derived/sc-pseudobulk-normal-celltype-{tissue}-v1/sc_pseudobulk.parquet"
)
# Tier-1 output path template
TIER1_PRODUCT_TEMPLATE = (
    "s3://onc-compbio/data-catalog/derived/sc-normal-celltype-expression-{tissue}-v1/sc_normal_expression.parquet"
)

MIN_CELLS_PER_GROUP = 10  # donor-cell_type groups below this are excluded (unreliable detection)
ROW_GROUP_SIZE = 50_000  # matches Tier-2 row-group size and the query_optimization block
MEMORY_LIMIT = "150GB"  # 512 GB instance; 150 GB headroom for DuckDB sort windows


def _inject_s3_creds(con, profile: str = "cbg") -> None:
    """Inject SSO credentials as a named DuckDB S3 secret — httpfs boto3 chain is unreliable."""
    import boto3

    session = boto3.Session(profile_name=profile)
    creds = session.get_credentials().get_frozen_credentials()
    con.execute(f"""
        CREATE OR REPLACE SECRET s3_cbg (
            TYPE S3,
            KEY_ID '{creds.access_key}',
            SECRET '{creds.secret_key}',
            SESSION_TOKEN '{creds.token}',
            REGION 'us-east-1'
        )
    """)


TIER1_SQL = """
WITH agg AS (
    SELECT
        gene_symbol,
        ensembl_gene_id,
        tissue,
        cell_type,
        COUNT(DISTINCT (dataset_id, donor_id))                                                    AS n_donors_total,
        COUNT(DISTINCT (dataset_id, donor_id)) FILTER (WHERE n_cells >= {min_cells})              AS n_donors_reliable,
        COUNT(DISTINCT dataset_id)             FILTER (WHERE n_cells >= {min_cells})              AS n_datasets_reliable,
        COUNT(DISTINCT (dataset_id, donor_id))
            FILTER (WHERE n_cells >= {min_cells} AND detection_fraction > 0.10)                   AS n_donors_expressing,
        MEDIAN(CASE WHEN n_cells >= {min_cells} THEN detection_fraction    END)                   AS median_det,
        PERCENTILE_CONT(0.25) WITHIN GROUP
            (ORDER BY CASE WHEN n_cells >= {min_cells} THEN detection_fraction    END)            AS q25_det,
        PERCENTILE_CONT(0.75) WITHIN GROUP
            (ORDER BY CASE WHEN n_cells >= {min_cells} THEN detection_fraction    END)            AS q75_det,
        MEDIAN(CASE WHEN n_cells >= {min_cells} THEN abundance_log1p_cp10k END)                   AS median_abund,
        PERCENTILE_CONT(0.25) WITHIN GROUP
            (ORDER BY CASE WHEN n_cells >= {min_cells} THEN abundance_log1p_cp10k END)            AS q25_abund,
        PERCENTILE_CONT(0.75) WITHIN GROUP
            (ORDER BY CASE WHEN n_cells >= {min_cells} THEN abundance_log1p_cp10k END)            AS q75_abund
    FROM read_parquet($tier2_uri)
    GROUP BY gene_symbol, ensembl_gene_id, tissue, cell_type
),
with_frac AS (
    SELECT *,
        n_donors_expressing * 1.0 / NULLIF(n_donors_reliable, 0) AS expressing_donor_fraction
    FROM agg
),
with_selectivity AS (
    SELECT *,
        PERCENT_RANK() OVER (PARTITION BY gene_symbol, tissue ORDER BY median_det) AS detection_pct_rank,
        COUNT(*) FILTER (WHERE median_det > 0.20)
            OVER (PARTITION BY gene_symbol, tissue)                               AS n_cell_types_above_20pct
    FROM with_frac
)
SELECT
    gene_symbol, ensembl_gene_id, tissue, cell_type,
    n_donors_total, n_donors_reliable, n_datasets_reliable, n_donors_expressing,
    median_det, q25_det, q75_det,
    expressing_donor_fraction,
    median_abund, q25_abund, q75_abund,
    detection_pct_rank, n_cell_types_above_20pct
FROM with_selectivity
WHERE median_det > 0.01
ORDER BY gene_symbol, tissue, cell_type
""".strip()


def run_aggregation(
    tissue: str,
    no_upload: bool = False,
    out_override: Path | None = None,
    merge_temp_dir: Path | None = None,
    aws_profile: str = "cbg",
) -> dict:
    """Execute Tier-2 → Tier-1 cross-donor aggregation for one tissue shard.

    Returns a dict with n_rows, size_bytes, output_uri, elapsed_seconds.
    """
    import hashlib

    import duckdb

    # Product IDs use hyphenated slugs (e.g. "bone-marrow", "small-intestine"); accept either
    # underscore or hyphen on the CLI and normalize so the S3 keys always resolve.
    slug = tissue.strip().lower().replace("_", "-")
    tier2_uri = TIER2_PRODUCT_TEMPLATE.format(tissue=slug)
    tier1_uri = TIER1_PRODUCT_TEMPLATE.format(tissue=slug)

    if out_override:
        local_out = out_override
    else:
        local_out = Path(f"/tmp/sc_normal_expression_{tissue}.parquet")

    log.info(f"[aggregate] tissue={tissue}")
    log.info(f"  Tier-2 source: {tier2_uri}")
    log.info(f"  Tier-1 output: {local_out}")

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}';")
    if merge_temp_dir:
        Path(merge_temp_dir).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{merge_temp_dir}';")

    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-east-1';")
    _inject_s3_creds(con, profile=aws_profile)

    t0 = time.monotonic()
    sql = TIER1_SQL.format(min_cells=MIN_CELLS_PER_GROUP)
    log.info("[aggregate] running Tier-1 SQL (single DuckDB pass)...")
    con.execute(
        f"""
        COPY (
            {sql}
        ) TO '{local_out}' (
            FORMAT PARQUET,
            COMPRESSION SNAPPY,
            ROW_GROUP_SIZE {ROW_GROUP_SIZE}
        )
    """,
        {"tier2_uri": tier2_uri},
    )
    elapsed = time.monotonic() - t0
    size = local_out.stat().st_size
    row_count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{local_out}')").fetchone()[0]
    con.close()

    # md5
    md5 = hashlib.md5()
    with open(local_out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            md5.update(chunk)
    md5_hex = md5.hexdigest()

    log.info(f"[aggregate] done — {row_count:,} rows, {size:,} bytes, md5={md5_hex}, {elapsed:.0f}s")

    output_uri = str(local_out)
    if not no_upload:
        import boto3

        s3 = boto3.Session(profile_name=aws_profile).client("s3", region_name="us-east-1")
        key = TIER1_PRODUCT_TEMPLATE.format(tissue=slug).removeprefix(f"s3://{S3_BUCKET}/")
        log.info(f"[aggregate] uploading to s3://{S3_BUCKET}/{key} ...")
        s3.upload_file(str(local_out), S3_BUCKET, key)
        output_uri = f"s3://{S3_BUCKET}/{key}"
        log.info("[aggregate] upload complete")

    return {
        "tissue": tissue,
        "n_rows": row_count,
        "size_bytes": size,
        "md5": md5_hex,
        "output_uri": output_uri,
        "elapsed_seconds": round(elapsed, 1),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tier-2 → Tier-1 sc_normal_expression aggregation.")
    ap.add_argument("--tissue", required=True, help="Tissue shard to aggregate (e.g. colon, lung)")
    ap.add_argument(
        "--no-upload", action="store_true", help="Skip S3 upload — write local parquet only (dry-run / testing)"
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override local output path (default: /tmp/sc_normal_expression_{tissue}.parquet)",
    )
    ap.add_argument(
        "--merge-temp-dir",
        type=Path,
        default=None,
        help="DuckDB sort spill directory (default: system temp). Use EFS for large tissues.",
    )
    ap.add_argument("--aws-profile", default="cbg", help="AWS profile for S3 credentials (default: cbg)")
    args = ap.parse_args(argv)

    result = run_aggregation(
        tissue=args.tissue,
        no_upload=args.no_upload,
        out_override=args.out,
        merge_temp_dir=args.merge_temp_dir,
        aws_profile=args.aws_profile,
    )
    import json

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
