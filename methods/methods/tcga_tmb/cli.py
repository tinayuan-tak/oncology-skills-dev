#!/usr/bin/env python3
"""tcga_tmb CLI — emit the per-sample TMB derived product from the MC3 MAF.

Reads the pan-TCGA MC3 MAF (mc3.v0.2.8.PUBLIC.maf.gz), computes per-sample
nonsynonymous-mutations-per-Mb + a categorical tmb_bucket, and writes:

  <out>/tmb_per_sample.parquet   (patient_key, n_nonsyn, tmb_mut_per_mb, tmb_bucket)
  <out>/_provenance.json

Consumers (subgroup catalogs) point a TMB-high stratum at the derived product
with a scalar rule `tmb_bucket == 'high'` — no per-sample aggregation needed in
the assigner.

Invocation:
  python -m methods.tcga_tmb.cli \\
      --mc3-maf ~/.cache/framework-tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz \\
      --out /path/to/output-dir/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd

from methods.tcga_tmb.compute import (
    DEFAULT_EXOME_MB,
    DEFAULT_TMB_HIGH_THRESHOLD,
    compute_tmb,
)

METHOD_VERSION = "0.1.0"


@click.command()
@click.option(
    "--mc3-maf",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="MC3 MAF (mc3.v0.2.8.PUBLIC.maf.gz).",
)
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--exome-mb", default=DEFAULT_EXOME_MB, show_default=True, help="Exome-covered Mb for the TMB denominator."
)
@click.option(
    "--high-threshold",
    default=DEFAULT_TMB_HIGH_THRESHOLD,
    show_default=True,
    help="mut/Mb threshold for tmb_bucket == 'high'.",
)
def main(mc3_maf: Path, out: Path, exome_mb: float, high_threshold: float) -> int:
    out.mkdir(parents=True, exist_ok=True)
    click.echo(f"=== tcga_tmb v{METHOD_VERSION} ===")
    click.echo(f"  reading MC3 MAF: {mc3_maf}")
    maf = pd.read_csv(
        mc3_maf,
        sep="\t",
        usecols=["Variant_Classification", "Tumor_Sample_Barcode"],
        low_memory=False,
        compression="gzip" if str(mc3_maf).endswith(".gz") else None,
    )
    click.echo(f"    {len(maf):,} MAF rows")

    tmb = compute_tmb(maf, exome_mb=exome_mb, high_threshold=high_threshold)
    n_high = int((tmb["tmb_bucket"] == "high").sum())
    click.echo(f"  {len(tmb):,} samples | TMB-high (>= {high_threshold} mut/Mb): {n_high:,} ({n_high / len(tmb):.1%})")

    tmb_path = out / "tmb_per_sample.parquet"
    tmb.to_parquet(tmb_path, index=False)
    click.echo(f"  wrote {tmb_path} ({tmb_path.stat().st_size:,} bytes)")

    prov = {
        "method": "tcga_tmb",
        "method_version": METHOD_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {"mc3_maf": str(mc3_maf)},
        "exome_mb": exome_mb,
        "tmb_high_threshold": high_threshold,
        "n_samples": len(tmb),
        "n_tmb_high": n_high,
        "tmb_high_fraction": round(n_high / len(tmb), 4),
    }
    (out / "_provenance.json").write_text(json.dumps(prov, indent=2))
    click.echo("  wrote _provenance.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
