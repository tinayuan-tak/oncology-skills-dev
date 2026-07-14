#!/usr/bin/env python3
"""validate_biology.py — biology-anchor gate for the CPTAC protein DEG parquet.

Reads the derive.py output parquet and asserts well-characterized
tumor-antigen overexpression targets recover the expected direction +
significance. If any anchor fails, exits non-zero to block PR merge.

Anchors (from CPTAC_FORMAT_NOTES.md + the plan's PR 2 validation gate):
  - ERBB2 in BRCA:  log2FC > 2.0, q < 0.001
  - MSLN in OV:     log2FC > 3.0, q < 0.001
  - FOLH1 in PDAC:  log2FC > 0.5
  - MDM2 present in the parquet
  - MKI67 up in >= 8 of 10 cohorts (log2FC > 1.0, q < 0.05)

Usage:
    python -m methods.cptac_protein_deg.validate_biology \\
        --parquet ~/dev/framework-runs/.../cptac_protein_deg.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def load(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["gene_symbol"] = df["gene_symbol"].astype(str).str.upper()
    df["cohort"] = df["cohort"].astype(str).str.upper()
    return df


def check_target_cohort(df, gene, cohort, min_logfc, max_q, label) -> tuple[bool, str]:
    sub = df[(df["gene_symbol"] == gene) & (df["cohort"] == cohort)]
    if sub.empty:
        return False, f"{label}: {gene} not in {cohort}"
    logfc = float(sub["protein_effect_size"].iloc[0])
    q = float(sub["protein_bh_q_value"].iloc[0])
    ok = (logfc >= min_logfc) and (q <= max_q)
    return ok, f"{label}: {gene} in {cohort} logFC={logfc:.2f} (>={min_logfc}), q={q:.2e} (<={max_q}) — {'PASS' if ok else 'FAIL'}"


def check_mki67_universal(df) -> tuple[bool, str]:
    mki = df[df["gene_symbol"] == "MKI67"]
    if mki.empty:
        return False, "MKI67 not in parquet"
    up = mki[(mki["protein_effect_size"] > 1.0) & (mki["protein_bh_q_value"] < 0.05)]
    n_up = len(up)
    n_total = len(mki)
    ok = n_up >= 8
    return ok, (f"MKI67 up (logFC>1.0, q<0.05) in {n_up}/{n_total} cohorts (>=8 required) "
                f"— {'PASS' if ok else 'FAIL'}")


def check_target_present(df, gene, label) -> tuple[bool, str]:
    sub = df[df["gene_symbol"] == gene]
    ok = not sub.empty
    return ok, f"{label}: {gene} rows={len(sub)} — {'PASS' if ok else 'FAIL'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True, type=Path)
    args = ap.parse_args()

    df = load(args.parquet)
    print(f"[validate] loaded {len(df):,} rows, "
          f"{df['gene_symbol'].nunique()} unique proteins, "
          f"{df['cohort'].nunique()} cohorts: {sorted(df['cohort'].unique())}",
          file=sys.stderr)

    checks = [
        check_target_cohort(df, "ERBB2", "BRCA", 2.0, 0.001, "ERBB2/BRCA"),
        check_target_cohort(df, "MSLN",  "OV",   3.0, 0.001, "MSLN/OV"),
        check_target_cohort(df, "FOLH1", "PDAC", 0.5, 0.05,  "FOLH1/PDAC"),
        check_target_present(df, "MDM2", "MDM2 presence"),
        check_mki67_universal(df),
    ]

    passed = sum(1 for ok, _ in checks if ok)
    for ok, msg in checks:
        prefix = "✓" if ok else "✗"
        print(f"  {prefix} {msg}", file=sys.stderr)

    print(f"[validate] {passed}/{len(checks)} anchors passed", file=sys.stderr)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
