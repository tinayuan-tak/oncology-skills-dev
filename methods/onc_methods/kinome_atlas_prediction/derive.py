"""kinome_atlas_prediction.derive — one-shot ETL from raw Excel → long parquet.

This is a Layer-3 derived product builder. Run ONCE per source-manifest refresh;
the compute is expensive (~2-3 min end-to-end) and the output is a small
parquet the runtime method loads via pyarrow with @lru_cache.

Why we need a derived product here (not straight Excel-read like paralog):
  - Johnson 2023 Supp Table 3 = 89,784 phosphosites × 303 kinase columns
    (`{KINASE}_percentile` + `{KINASE}_rank` per kinase). Load via pandas +
    calamine engine takes ~85s + ~500MB RAM.
  - Yaron-Barir 2024 Supp Table 3 (mislabeled `_noncanonical_tyr_pwms.xlsx`
    on ingest) = 7,315 phosphosites × 94 kinases in the same wide layout.
  - Long-format melt after percentile>=90 filter reduces to ~2-3M edges
    that fits comfortably in a ~150MB parquet with dictionary-encoded
    strings, loads in <2s and supports O(1) per-target lookup.

Output schema (long-format kinase-substrate prediction edges):
    kinase_symbol    str   HGNC-style kinase name (e.g., 'AKT1', 'SRC')
    substrate_gene   str   substrate HGNC symbol (from raw table `Gene` col)
    substrate_ac     str   UniProt primary accession
    phosphosite      str   site string (e.g., 'S24', 'Y1023')
    phos_res         str   'S' | 'T' | 'Y'
    motif_15mer      str   SITE_+/-7_AA sequence context
    kinome           str   'ser_thr' | 'tyr' (source atlas)
    percentile       float PWM percentile rank (>=90 filtered)
    rank             int   integer rank of this kinase among all scored

Usage:
    python -m onc_methods.kinome_atlas_prediction.derive \\
        --johnson-xlsx /path/to/johnson_2023_predicted_substrates.xlsx \\
        --yaron-xlsx   /path/to/yaron_barir_2024_noncanonical_tyr_pwms.xlsx \\
        --out-parquet  /path/to/kinome_atlas_long_edges_v1.parquet \\
        --percentile-threshold 90.0
    # then aws s3 cp --profile cbg ... s3://onc-compbio/data-catalog/derived/
    #   kinome-atlas-long-edges-v1/kinome_atlas_long_edges.parquet

Design choices:
  - We use pandas + calamine (rust-based) NOT openpyxl. openpyxl returns
    empty sheet_names on the Johnson 370MB file (unusual sheet-registration
    format the openpyxl parser can't index).
  - percentile>=90 threshold: paper's own convention for "meaningful
    prediction." Below 90, PWM scores are noise; keeping them inflates
    parquet size 10x and false-positive edges downstream.
  - HGNC symbol resolution: kinome-atlas column names ARE mostly HGNC
    symbols but some are family aliases (`WEE1_TYR`, `ABL`, `ARG`, ...).
    Iter-1 keeps the atlas-native name in kinase_symbol; a follow-up can
    add HGNC crosswalk.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

DEFAULT_PERCENTILE_THRESHOLD = 90.0

# Metadata columns from the raw wide-format tables (identifying the SUBSTRATE
# side of each edge). Everything else in the header should be either a
# `{KINASE}_percentile` or `{KINASE}_rank` column, plus a couple of
# aggregate/summary columns we filter out.
_SUBSTRATE_METADATA_COLS = {
    "Database Uniprot Accession",
    "Uniprot Primary Accession",
    "Uniprot Entry",
    "Gene",
    "Alternative Gene Names",
    "Protein",
    "Description",
    "Uniprot",
    "Phosphosite",
    "Database",
    "SITE_+/-7_AA",
    "ORIGINAL_SITE_+/-7_AA",
    "phos_res",
    "median_percentile",
    "promiscuity_index",
    # Yaron-Barir 'median' column is an aggregate of kinase percentiles,
    # NOT a per-kinase score — skip it.
}


def _kinase_from_percentile_col(col: str) -> str | None:
    """Extract kinase symbol from a `{KINASE}_percentile` header. Returns
    None if `col` doesn't match the pattern OR maps to a metadata alias
    that should be dropped."""
    if not col.endswith("_percentile"):
        return None
    kinase = col[: -len("_percentile")]
    # Drop aggregate median column
    if kinase.lower() == "median":
        return None
    return kinase


def _melt_wide_atlas(
    xlsx_path: Path,
    sheet_name: str,
    kinome_label: str,
    percentile_threshold: float,
) -> pd.DataFrame:
    """Read one wide-format kinome-atlas sheet, melt to long, filter
    percentile>=threshold. Returns a DataFrame with the target schema.
    """
    t0 = time.perf_counter()
    print(f"[{kinome_label}] reading {xlsx_path.name!r} sheet {sheet_name!r} (calamine engine)...")
    df = pd.read_excel(xlsx_path, engine="calamine", sheet_name=sheet_name)
    print(f"[{kinome_label}] wide-format: {df.shape[0]:,} rows × {df.shape[1]} cols ({time.perf_counter() - t0:.1f}s)")

    # Identify kinase percentile cols
    kinase_percentile_cols = [c for c in df.columns if _kinase_from_percentile_col(c) is not None]
    if not kinase_percentile_cols:
        raise RuntimeError(
            f"[{kinome_label}] no `{{KINASE}}_percentile` columns found in sheet {sheet_name!r} — schema drift?"
        )
    print(f"[{kinome_label}] {len(kinase_percentile_cols)} kinase columns detected")

    # Identify metadata cols present in this atlas (schemas vary across
    # the two files — Yaron-Barir has extra ORIGINAL_SITE_ column)
    id_cols = [c for c in df.columns if c in _SUBSTRATE_METADATA_COLS]

    # Melt percentile columns into long form, then filter to >=threshold BEFORE
    # merging rank data (keeps memory bounded — the filtered set is ~2-3% of
    # the full 27M-row cross-product).
    t0 = time.perf_counter()
    long_pct = df[id_cols + kinase_percentile_cols].melt(
        id_vars=id_cols,
        value_vars=kinase_percentile_cols,
        var_name="_kinase_pct_col",
        value_name="percentile",
    )
    print(f"[{kinome_label}] melted percentile: {long_pct.shape[0]:,} rows ({time.perf_counter() - t0:.1f}s)")
    long_pct["kinase_symbol"] = long_pct["_kinase_pct_col"].map(_kinase_from_percentile_col)
    long_pct = long_pct.drop(columns=["_kinase_pct_col"])

    # Apply percentile threshold. This is the big memory drop.
    n_before = len(long_pct)
    long_pct = long_pct[long_pct["percentile"] >= percentile_threshold].copy()
    print(
        f"[{kinome_label}] percentile>={percentile_threshold} filter: "
        f"{n_before:,} → {len(long_pct):,} rows "
        f"({100 * len(long_pct) / max(n_before, 1):.1f}%)"
    )

    # Also melt the rank column so we can join it to the surviving rows.
    # Only rank columns whose kinase survived the percentile filter matter,
    # but a simple full melt+join is bounded now (post-filter).
    rank_cols = [
        c for c in df.columns if c.endswith("_rank") and _kinase_from_percentile_col(c.replace("_rank", "_percentile"))
    ]
    if rank_cols:
        t0 = time.perf_counter()
        long_rank = df[id_cols + rank_cols].melt(
            id_vars=id_cols,
            value_vars=rank_cols,
            var_name="_kinase_rank_col",
            value_name="rank",
        )
        long_rank["kinase_symbol"] = long_rank["_kinase_rank_col"].map(
            lambda c: c[: -len("_rank")] if c.endswith("_rank") else None
        )
        long_rank = long_rank.drop(columns=["_kinase_rank_col"])
        # Join on the substrate identifier + kinase — pick a natural key.
        # Phosphosite alone is not unique across substrates; use
        # (Uniprot Primary Accession, Phosphosite, kinase_symbol) if present.
        join_keys = [c for c in ("Uniprot Primary Accession", "Phosphosite") if c in id_cols]
        join_keys.append("kinase_symbol")
        long_out = long_pct.merge(long_rank[join_keys + ["rank"]], on=join_keys, how="left")
        print(f"[{kinome_label}] joined rank: {len(long_out):,} rows ({time.perf_counter() - t0:.1f}s)")
    else:
        long_out = long_pct
        long_out["rank"] = pd.NA

    # Normalize to the target schema (columns may not exist in some sheets).
    result = pd.DataFrame(
        {
            "kinase_symbol": long_out["kinase_symbol"].astype("string"),
            "substrate_gene": long_out.get("Gene", pd.Series(dtype="string")).astype("string"),
            "substrate_ac": long_out.get("Uniprot Primary Accession", pd.Series(dtype="string")).astype("string"),
            "phosphosite": long_out.get("Phosphosite", pd.Series(dtype="string")).astype("string"),
            "phos_res": long_out.get("phos_res", pd.Series(dtype="string")).astype("string"),
            "motif_15mer": long_out.get("SITE_+/-7_AA", pd.Series(dtype="string")).astype("string"),
            "kinome": kinome_label,
            "percentile": pd.to_numeric(long_out["percentile"], errors="coerce"),
            "rank": pd.to_numeric(long_out["rank"], errors="coerce").astype("Int64"),
        }
    )

    # Drop rows where substrate_gene is null — those can't be looked up.
    n_before = len(result)
    result = result[result["substrate_gene"].notna() & (result["substrate_gene"] != "")]
    print(f"[{kinome_label}] drop null substrate_gene: {n_before:,} → {len(result):,} rows")

    return result


def derive_kinome_atlas_long(
    johnson_xlsx: Path,
    yaron_xlsx: Path,
    out_parquet: Path,
    percentile_threshold: float = DEFAULT_PERCENTILE_THRESHOLD,
) -> None:
    """Melt both wide-format atlas files, concatenate, write parquet."""
    frames: list[pd.DataFrame] = []

    print("=== Deriving kinome-atlas long-edges parquet ===")
    print(f"  johnson_xlsx: {johnson_xlsx}")
    print(f"  yaron_xlsx:   {yaron_xlsx}")
    print(f"  out_parquet:  {out_parquet}")
    print(f"  percentile_threshold: {percentile_threshold}")
    print()

    # Johnson 2023 (Ser/Thr): Supplementary Table 3 sheet
    frames.append(
        _melt_wide_atlas(
            johnson_xlsx,
            sheet_name="Supplementary Table 3",
            kinome_label="ser_thr",
            percentile_threshold=percentile_threshold,
        )
    )

    # Yaron-Barir 2024 (Tyr): "Annotation - with non-canonical" sheet in the
    # (mislabeled) noncanonical_tyr_pwms.xlsx file — this is the genome-wide
    # Tyr-kinome scored annotation for all 94 canonical + non-canonical Tyr
    # kinases.
    frames.append(
        _melt_wide_atlas(
            yaron_xlsx,
            sheet_name="Annotation - with non-canonical",
            kinome_label="tyr",
            percentile_threshold=percentile_threshold,
        )
    )

    print()
    combined = pd.concat(frames, ignore_index=True)
    print(f"=== Combined: {len(combined):,} edges ({combined.memory_usage(deep=True).sum() / 1e6:.0f}MB in-memory) ===")
    print()
    print(f"  kinase count: {combined['kinase_symbol'].nunique()}")
    print(f"  substrate count: {combined['substrate_gene'].nunique()}")
    print(f"  by kinome: {combined['kinome'].value_counts().to_dict()}")
    print("  percentile distribution:")
    print(combined["percentile"].describe().to_string())
    print()

    # Sort by percentile DESCENDING before write so the runtime reader's
    # filters=[('percentile','>=',95)] pushdown actually prunes row-groups: with an
    # unsorted product every row-group spans the full [90,100] range and pyarrow must
    # scan them all. Descending order clusters the high-percentile edges into the first
    # row-groups, so the >=95 predicate skips the tail. (kind='mergesort' = stable.)
    combined = combined.sort_values("percentile", ascending=False, kind="mergesort").reset_index(drop=True)

    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    combined.to_parquet(
        out_parquet,
        engine="pyarrow",
        compression="snappy",
        index=False,
    )
    print(f"Wrote {out_parquet} ({out_parquet.stat().st_size / 1e6:.1f}MB, {time.perf_counter() - t0:.1f}s to write)")


def _main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--johnson-xlsx", type=Path, required=True)
    p.add_argument("--yaron-xlsx", type=Path, required=True)
    p.add_argument("--out-parquet", type=Path, required=True)
    p.add_argument("--percentile-threshold", type=float, default=DEFAULT_PERCENTILE_THRESHOLD)
    args = p.parse_args(argv)

    if not args.johnson_xlsx.exists():
        print(f"ERROR: johnson_xlsx not found: {args.johnson_xlsx}", file=sys.stderr)
        return 2
    if not args.yaron_xlsx.exists():
        print(f"ERROR: yaron_xlsx not found: {args.yaron_xlsx}", file=sys.stderr)
        return 2

    derive_kinome_atlas_long(
        johnson_xlsx=args.johnson_xlsx,
        yaron_xlsx=args.yaron_xlsx,
        out_parquet=args.out_parquet,
        percentile_threshold=args.percentile_threshold,
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
