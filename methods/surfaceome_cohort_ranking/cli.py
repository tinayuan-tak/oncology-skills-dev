#!/usr/bin/env python3
"""surfaceome_cohort_ranking CLI — per-indication whole-surfaceome effect-size ranking.

Composes a per-indication ranking of all SURFY/HPA-confirmed surface proteins by tumor-vs-normal
effect size, filtered to comparator-robust tumor-up hits, then overlays CPTAC protein concordance.
Reads the DESeq2 sensitivity products at
    s3://onc-compbio/data-catalog/derived/{indication}-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet
joins surfaceome-family-classification (surface-only filter + family) and
cptac-protein-tumor-vs-normal-per-cohort (protein overlay). Compute lives in derive.py (unit-tested,
S3-free). Output is the derived product cataloged as
    data-catalog:manifests/derived/surfaceome-cohort-ranking-per-indication-v1.yaml

Sensitivity products are HETEROGENEOUS (1-3 comparator cells per indication); the robustness filter
is relative (cells_supporting >= min(--min-cells-supporting, cells_ran)). See derive.py.

Usage:
    python -m methods.surfaceome_cohort_ranking.cli --indication all \\
        --out /tmp/surfaceome_cohort_ranking.parquet
    python -m methods.surfaceome_cohort_ranking.cli --indication COADREAD \\
        --out /tmp/coadread_ranking.parquet
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_PREFIX = "data-catalog/derived/"
SURFACE_KEY = f"{DERIVED_PREFIX}surfaceome-family-classification-per-uniprot-v1/surfaceome_family.parquet"
CPTAC_KEY = f"{DERIVED_PREFIX}cptac-protein-tumor-vs-normal-per-cohort-v1/cptac_protein_deg.parquet"

# Indications with a materialized *-dge-tumor-vs-normal-sensitivity-v1 product on S3 (2026-08-18).
WIRED_INDICATIONS = [
    "ACC", "BLCA", "BRCA", "CESC", "COAD", "COADREAD", "ESCA", "GBM", "HNSC", "KICH",
    "KIRC", "KIRP", "LGG", "LIHC", "LUAD", "LUSC", "NSCLC", "OV", "PAAD", "PCPG",
    "PRAD", "READ", "SCLC", "SKCM", "STAD", "TGCT", "THCA", "UCEC", "UCS",
]


def _s3():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _read_parquet_s3(s3, key: str):
    import pyarrow.parquet as pq
    raw = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    return pq.read_table(io.BytesIO(raw)).to_pandas()


def _sensitivity_key(indication: str) -> str:
    return f"{DERIVED_PREFIX}{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet"


@click.command()
@click.option("--indication", required=True,
              help="Indication code (e.g. COADREAD). 'all' iterates every wired indication.")
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output parquet path (one long frame across the requested indication(s)).")
@click.option("--min-cells-supporting", type=int, default=2,
              help="Robustness threshold; effective per-indication = min(this, cells_ran). "
                   "Default 2 (both comparator cells agree where 2+ ran). Set 1 to include "
                   "single-cell indications on their single comparator.")
@click.option("--profile", default=DEFAULT_AWS_PROFILE)
def main(indication: str, out: Path, min_cells_supporting: int, profile: str):
    import pandas as pd  # noqa: F401
    from methods.surfaceome_cohort_ranking.derive import rank_all

    os.environ.setdefault("AWS_PROFILE", profile)
    s3 = _s3()

    targets = WIRED_INDICATIONS if indication.lower() == "all" else [indication.upper()]

    click.echo("[surfaceome_cohort_ranking] loading surfaceome-family + CPTAC overlays…", err=True)
    surface_df = _read_parquet_s3(s3, SURFACE_KEY)
    try:
        cptac_df = _read_parquet_s3(s3, CPTAC_KEY)
    except Exception as e:  # noqa: BLE001
        click.echo(f"[surfaceome_cohort_ranking] CPTAC overlay unavailable ({e}); "
                   f"emitting rna_protein_concordance=no_protein throughout.", err=True)
        cptac_df = None

    sensitivity_by_indication: dict = {}
    for ind in targets:
        try:
            sensitivity_by_indication[ind] = _read_parquet_s3(s3, _sensitivity_key(ind))
        except Exception as e:  # noqa: BLE001
            click.echo(f"[surfaceome_cohort_ranking] skip {ind}: no sensitivity product ({type(e).__name__})",
                       err=True)

    ranked = rank_all(sensitivity_by_indication, surface_df, cptac_df,
                      min_cells_supporting=min_cells_supporting)

    out.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_parquet(out, index=False)
    by_ind = ranked.groupby("indication").size().to_dict() if not ranked.empty else {}
    click.echo(f"[surfaceome_cohort_ranking] wrote {len(ranked):,} rows -> {out}\n"
               f"[surfaceome_cohort_ranking] per-indication counts: {by_ind}", err=True)


if __name__ == "__main__":
    main()
