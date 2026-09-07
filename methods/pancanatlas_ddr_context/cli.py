#!/usr/bin/env python3
"""pancanatlas_ddr_context — per-indication DDR/HRD-deficiency cohort context.

A verdict-INERT, pre-integrated companion facet: how HRD/DDR-deficient is an indication's TCGA
cohort? Consumes the PanCanAtlas DDR footprint resource (Knijnenburg 2018), which already did the
multi-omics HRD integration per sample (HRD_Score = HRD-TAI + HRD-LST + HRD-LOH; mutSig3 = the HRD
mutational signature; PARPi7 = a PARPi-response signature). We aggregate to a per-INDICATION rollup
at BUILD time (read grain = pre-aggregated → O(1) skill reads, no per-sample groupby at run time).

The "disease" column in the footprints sheet IS the TCGA tumor-type code (ACC, BRCA, ...), so the
per-indication aggregation needs NO barcode join.

Cohort class (fraction of samples that are HRD-high, HRD_Score >= HRD_HIGH_CUT):
  hrd_enriched       — fraction HRD-high >= 0.30 (an HRD-enriched cohort, e.g. OV/BRCA)
  hrd_intermediate   — 0.10 <= fraction < 0.30
  hrd_low            — fraction < 0.10 (DDR-proficient cohort)
  data_unavailable   — indication not in the DDR resource

VERDICT-INERT context facet: no resolver rung, no rescue. Surfaces the cohort HRD prior alongside
the (separate, verdict-moving) partner-conditional dependency analysis; it does NOT itself flip a verdict.
"""

from __future__ import annotations

import io
from pathlib import Path

METHOD_VERSION = "0.1.0"

# HRD_Score in this resource is the Myriad-style composite (HRD-TAI + HRD-LST + HRD-LOH), integer-ish,
# typically 0-~100. The clinically-used HRD-high cut (Myriad myChoice / TCGA analyses) is ~42; we adopt
# 42 as HRD_HIGH_CUT so "HRD-high fraction" tracks the established threshold rather than an ad-hoc one.
HRD_HIGH_CUT = 42.0
HRD_ENRICHED_FRAC = 0.30
HRD_INTERMEDIATE_FRAC = 0.10
MIN_COHORT_N = 15  # below → data_unavailable (underpowered cohort)

_SOURCE_KEY = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/TCGA_DDR_Data_Resources.xlsx"
_BUCKET = "onc-compbio"
_SHEET = "DDR footprints"
_HEADER_ROW = 3  # 0-indexed; rows 0-2 are score-dictionary metadata, row 3 is the column header


def _load_footprints_df():
    """Load the per-sample DDR footprints sheet (cache→S3). Returns a DataFrame with columns
    patient_barcode / TCGA sample barcode / disease / subtype / <score columns>."""
    import pandas as pd
    from methods.depmap_common.loaders import SESSION_CACHE_DIR

    cache = Path(SESSION_CACHE_DIR) / "pancanatlas" / "TCGA_DDR_Data_Resources.xlsx"
    if cache.exists():
        raw = cache.read_bytes()
    else:
        import boto3

        raw = boto3.client("s3").get_object(Bucket=_BUCKET, Key=_SOURCE_KEY)["Body"].read()
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
        except OSError:
            pass
    df = pd.read_excel(io.BytesIO(raw), sheet_name=_SHEET, header=_HEADER_ROW)
    df.columns = [str(c).strip() for c in df.columns]  # source has trailing spaces on some cols
    return df


def build_per_indication_table():
    """BUILD-time aggregation: per-(disease) HRD context rollup. Returns a DataFrame keyed by
    indication with n_samples, median_hrd_score, frac_hrd_high, median_mutsig3, ddr_context_class."""
    import pandas as pd

    df = _load_footprints_df()
    df["HRD_Score"] = pd.to_numeric(df.get("HRD_Score"), errors="coerce")
    df["mutSig3"] = pd.to_numeric(df.get("mutSig3"), errors="coerce")
    rows = []
    for disease, g in df.groupby("disease"):
        hrd = g["HRD_Score"].dropna()
        n = int(len(hrd))
        if n == 0:
            continue
        frac_high = float((hrd >= HRD_HIGH_CUT).mean())
        rows.append(
            {
                "indication": str(disease),
                "n_samples": n,
                "median_hrd_score": round(float(hrd.median()), 3),
                "p75_hrd_score": round(float(hrd.quantile(0.75)), 3),
                "frac_hrd_high": round(frac_high, 4),
                "median_mutsig3": round(float(g["mutSig3"].dropna().median()), 4)
                if g["mutSig3"].notna().any()
                else None,
                "hrd_high_cut": HRD_HIGH_CUT,
                "ddr_context_class": _classify(n, frac_high),
            }
        )
    return pd.DataFrame(rows).sort_values("indication").reset_index(drop=True)


def _classify(n: int, frac_high: float) -> str:
    if n < MIN_COHORT_N:
        return "data_unavailable"
    if frac_high >= HRD_ENRICHED_FRAC:
        return "hrd_enriched"
    if frac_high >= HRD_INTERMEDIATE_FRAC:
        return "hrd_intermediate"
    return "hrd_low"


try:
    import click

    @click.command()
    @click.option(
        "--out",
        type=click.Path(path_type=Path),
        required=True,
        help="Output parquet path for the per-indication DDR-context product.",
    )
    def main(out):
        """Build the per-indication DDR-deficiency context product (materialized rollup)."""
        tbl = build_per_indication_table()
        out.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_parquet(out, index=False)
        click.echo(f"wrote {len(tbl)} indications -> {out}")
        click.echo(tbl.to_string(index=False))

    if __name__ == "__main__":
        main()
except ImportError:
    pass
