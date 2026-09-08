"""Parse Johnson 2023 + Yaron-Barir 2024 kinome-atlas PWM Excel workbooks,
melt norm_scaled matrices, emit a compact long-format Parquet.

Input source manifest:
  s3://onc-compbio/data-catalog/sources/kinome-atlas/nature-supplementary-snapshot-2026-07-10/
    - johnson_2023_serthr_pwms.xlsx      (303 Ser/Thr kinases)
    - yaron_barir_2024_tyr_pwms.xlsx     (78 canonical Tyr kinases)

Sheet layout (both workbooks):
  Sheet 0: legend
  Sheet 1: {ser_thr|tyrosine}_all_raw_matrices        (raw densitometry)
  Sheet 2: {ser_thr|tyrosine}_all_norm_matrices       (row-normalized)
  Sheet 3: {ser_thr|tyrosine}_all_norm_scaled_matrice (norm + z-scored) <- THIS

Wide-matrix shape: (~300 rows kinases) × (208 or 231 columns).
Column names: "{position}{amino_acid}" — e.g. "-5P" (position -5, Pro),
"+3Y" (position +3, Tyr), "0S", "0T", "0Y" (phospho-position acceptors).
Position range: -5..+5, EXCLUDING position 0 (phospho-acceptor slot is
by definition S/T/Y). Ser/Thr atlas: -5..-1, +1..+4 (9 positions).
Tyr atlas: -5..-1, +1..+5 (10 positions). Amino acids: 20 standard + 3
phospho (pS, pT, pY, denoted 's', 't', 'y' or as suffix) = 23 total per
position.

Output schema (7 columns):
    family              str  - 'ser_thr' or 'tyrosine'
    kinase              str  - kinase name from xlsx first column
    position            int32 - position relative to phospho-site (-5..+4)
    amino_acid          str  - single-letter amino acid code (standard + phospho)
    norm_scaled_value   float32 - PWM norm+scaled log-odds enrichment
    matrix_type         str  - 'norm_scaled' (constant; reserved for future
                               variants that emit raw or norm too)
    source_paper        str  - 'johnson_2023' or 'yaron_barir_2024'

Row layout: sorted by (family, kinase, position, amino_acid) for
predicate-pushdown-friendly reads.

Row count: 396 kinases across both atlases (303 Ser/Thr × 207 cells/kinase
+ 93 Tyr × 230 cells/kinase) = 84,111 rows.
Size on disk: ~240 KB snappy parquet.

Usage:
    python -m methods.kinome_atlas_pwm_lookup.build \\
        --ser-thr-xlsx /path/to/johnson_2023_serthr_pwms.xlsx \\
        --tyr-xlsx /path/to/yaron_barir_2024_tyr_pwms.xlsx \\
        --out-parquet pwm_lookup_v1.parquet
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

# Column header format: "{position:+/-N or 0}{amino_acid}"
# Examples: "-5P", "+3Y", "0S", "0s" (phospho-Ser at position 0)
_COL_RE = re.compile(r"^([+-]?\d+)([A-Za-z])$")


def _parse_col(col: str) -> tuple[int, str] | None:
    """Parse '{position}{amino_acid}' column header. Returns (pos:int, aa:str)
    or None if the column isn't a position×aa cell (e.g. the first column
    which holds kinase names)."""
    m = _COL_RE.match(str(col).strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def _load_norm_scaled_sheet(xlsx_path: Path, sheet_name: str) -> pd.DataFrame:
    """Load a norm_scaled sheet, return long-format DataFrame with columns
    (kinase, position, amino_acid, norm_scaled_value).

    The sheet is wide: rows = kinases (name in first column, which pandas
    labels 'Unnamed: 0'), columns = position×aa cells + the kinase-name column.
    """
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, engine="openpyxl")

    # First column is the kinase name (unnamed in the xlsx header row).
    kinase_col = df.columns[0]
    if not (isinstance(kinase_col, str) and kinase_col.startswith("Unnamed")):
        print(
            f"[build] WARN: expected first column to be 'Unnamed:*' (kinase names); "
            f"got '{kinase_col}'. Will use it as kinase key anyway.",
            file=sys.stderr,
        )
    df = df.rename(columns={kinase_col: "kinase"})

    # Identify position×aa columns
    pos_aa_cols: list[str] = []
    for c in df.columns:
        if c == "kinase":
            continue
        parsed = _parse_col(c)
        if parsed is None:
            print(f"[build] WARN: skipping unparseable column '{c}' in {sheet_name}", file=sys.stderr)
            continue
        pos_aa_cols.append(c)

    # Melt: (kinase, pos_aa_col, value) -> parse pos_aa_col into position + amino_acid
    melted = df.melt(
        id_vars=["kinase"],
        value_vars=pos_aa_cols,
        var_name="pos_aa",
        value_name="norm_scaled_value",
    )
    parsed = melted["pos_aa"].apply(_parse_col)
    melted["position"] = parsed.apply(lambda p: p[0])
    melted["amino_acid"] = parsed.apply(lambda p: p[1])
    melted = melted.drop(columns=["pos_aa"])

    # Coerce
    melted["position"] = melted["position"].astype("int32")
    melted["norm_scaled_value"] = melted["norm_scaled_value"].astype("float32")
    # Drop rows with NaN kinase (blank trailing rows in xlsx)
    melted = melted[melted["kinase"].notna()]
    return melted


def build_pwm_lookup(ser_thr_xlsx: Path, tyr_xlsx: Path) -> pd.DataFrame:
    """Load both workbooks' norm_scaled sheets, tag family + source_paper,
    concatenate, sort, return long-format DataFrame.
    """
    st = _load_norm_scaled_sheet(ser_thr_xlsx, "ser_thr_all_norm_scaled_matrice")
    st["family"] = "ser_thr"
    st["source_paper"] = "johnson_2023"

    ty = _load_norm_scaled_sheet(tyr_xlsx, "tyrosine_all_norm_scaled_matric")
    ty["family"] = "tyrosine"
    ty["source_paper"] = "yaron_barir_2024"

    combined = pd.concat([st, ty], ignore_index=True)
    combined["matrix_type"] = "norm_scaled"
    combined = combined[
        [
            "family",
            "kinase",
            "position",
            "amino_acid",
            "norm_scaled_value",
            "matrix_type",
            "source_paper",
        ]
    ]
    combined = combined.sort_values(
        ["family", "kinase", "position", "amino_acid"],
        kind="stable",
    ).reset_index(drop=True)
    return combined


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ser-thr-xlsx", required=True, type=Path)
    ap.add_argument("--tyr-xlsx", required=True, type=Path)
    ap.add_argument("--out-parquet", required=True, type=Path)
    args = ap.parse_args()

    df = build_pwm_lookup(args.ser_thr_xlsx, args.tyr_xlsx)

    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out_parquet, index=False, compression="snappy")

    print(f"[build] wrote {len(df):,} rows -> {args.out_parquet}", file=sys.stderr)
    print(f"[build] families: {df['family'].value_counts().to_dict()}", file=sys.stderr)
    print(f"[build] kinases: {df['kinase'].nunique():,}", file=sys.stderr)
    print(f"[build] position range: {df['position'].min()}..{df['position'].max()}", file=sys.stderr)
    print(f"[build] amino_acid count: {df['amino_acid'].nunique()}", file=sys.stderr)
    print(
        f"[build] value range: {df['norm_scaled_value'].min():.4g}..{df['norm_scaled_value'].max():.4g}",
        file=sys.stderr,
    )
    print(f"[build] size on disk: {args.out_parquet.stat().st_size:,} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
