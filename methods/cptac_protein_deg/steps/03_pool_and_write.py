#!/usr/bin/env python3
"""Stage 03 — pool per-cohort MSstatsTMT results, join to UniProt, and write parquet.

Reads:
    <work_dir>/<cohort>_msstats_results.tsv (from stage 02, per cohort)
    Optional gene→uniprot map (from target-id-resolver sidecar); if not present,
    uniprot_ac is left NULL.
Writes:
    <out_parquet>  — cptac_protein_deg.parquet with the schema from the derived
                     manifest (see CPTAC_FORMAT_NOTES.md).

Effect-size classification:
    strong_up   : logFC >  1.5, q < 0.05
    modest_up   : logFC >  0.5, q < 0.05
    strong_down : logFC < -1.5, q < 0.05
    modest_down : logFC < -0.5, q < 0.05
    ns          : otherwise
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

CPTAC_COHORTS = ["BRCA", "CCRCC", "COAD", "GBM", "HNSCC", "LSCC", "LUAD", "OV", "PDAC", "UCEC"]

METHOD_VERSION = "1.2.0"   # 2026-08-20: variance-aware classify (G7) — negligible Cohen's d → small_effect
STAT_TEST_USED = "msstatstmt_limma_ebayes_moderated"

# Below this |Cohen's d| the standardized (sample-size-independent) effect is negligible — a call that
# cleared significance via cohort size / low variance rather than a real per-sample tumor-vs-normal
# difference. Conventional small-effect floor (Cohen 1988). Mirrors read.py _cohens_d_class.
NEGLIGIBLE_COHENS_D = 0.2


def _cohens_d(logfc, se, n_tumor, n_normal):
    """Sample-size-INDEPENDENT standardized effect from the MSstatsTMT moderated logFC + SE:
    t = logFC / SE, Cohen's d = t / sqrt(n_eff), n_eff = n_t*n_n/(n_t+n_n). Returns None when SE / n are
    unavailable (older upstream rows) — the caller then falls back to the raw-logFC bands (pre-variance
    behavior), so a missing SE never spuriously downgrades a call."""
    try:
        if se is None or pd.isna(se) or float(se) <= 0:
            return None
        if not (n_tumor and n_normal and float(n_tumor) > 0 and float(n_normal) > 0):
            return None
        t = float(logfc) / float(se)
        n_eff = (float(n_tumor) * float(n_normal)) / (float(n_tumor) + float(n_normal))
        return t / (n_eff ** 0.5)
    except Exception:  # noqa: BLE001
        return None


def classify(logfc: float, q: float, se: float = None,
             n_tumor: int = None, n_normal: int = None) -> str:
    # 2026-08-14 multi-pair review (finding #5): the former single `ns` bucket conflated TWO
    # distinct outcomes — "tested, not statistically significant" (q >= 0.05) and "significant but
    # effect too small to class up/down" (q < 0.05, |logfc| <= 0.5). That effect-size-vs-significance
    # ambiguity mislead readers (a `small_effect` percentile was misread as abundance). Split them:
    #   not_significant — q >= 0.05 (or stats unestimable), i.e. no significant tumor-vs-normal delta
    #   small_effect    — q < 0.05 but |logfc| <= 0.5, i.e. significant yet biologically small
    #
    # 2026-08-20 (G7, tumor-presence expert review): make the class VARIANCE-AWARE. The raw log2 bands
    # (±0.5 / ±1.5) are blind to variance, so a large cohort could clear the bar at a tiny per-sample
    # effect. A significant call whose standardized effect (Cohen's d = logFC/SE / sqrt(n_eff)) is
    # NEGLIGIBLE is `small_effect` regardless of the raw log2 magnitude — it cleared significance via
    # cohort size, not biology. Falls back to the raw-logFC bands when SE / n are unavailable (older
    # upstream rows), so a missing SE never downgrades a call.
    # VERDICT-SAFE: not_significant + small_effect are OUTSIDE _ELEVATED_CLASSES ({strong_up, modest_up}),
    # so this can only MOVE a call OUT of the elevated set (never fabricate an up-call); breadth/coverage
    # rollups and the tumor-presence M2 present-but-flat rescue are preserved.
    if pd.isna(logfc) or pd.isna(q):
        return "not_significant"
    if q >= 0.05:
        return "not_significant"
    d = _cohens_d(logfc, se, n_tumor, n_normal)
    if d is not None and abs(d) < NEGLIGIBLE_COHENS_D:
        return "small_effect"
    if logfc > 1.5:
        return "strong_up"
    if logfc > 0.5:
        return "modest_up"
    if logfc < -1.5:
        return "strong_down"
    if logfc < -0.5:
        return "modest_down"
    return "small_effect"


def load_uniprot_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    df = pd.read_csv(path, sep="\t", dtype=str)
    # target-id-resolver sidecar: expects gene_symbol + uniprot_ac columns
    if "gene_symbol" in df.columns and "uniprot_ac" in df.columns:
        m = dict(zip(df["gene_symbol"], df["uniprot_ac"]))
        m = {k: v for k, v in m.items() if isinstance(v, str) and v}
        return m
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--out-parquet", required=True, type=Path)
    ap.add_argument("--uniprot-map", type=Path, default=None,
                    help="Optional gene_symbol → uniprot_ac TSV")
    args = ap.parse_args()

    uniprot_map = load_uniprot_map(args.uniprot_map)
    print(f"[03_pool] uniprot map: {len(uniprot_map)} entries", file=sys.stderr)

    frames = []
    for cohort in CPTAC_COHORTS:
        tsv = args.work_dir / f"{cohort}_msstats_results.tsv"
        if not tsv.exists():
            print(f"[03_pool] {cohort}: MISSING {tsv.name}, skipping", file=sys.stderr)
            continue
        df = pd.read_csv(tsv, sep="\t")
        if df.empty:
            print(f"[03_pool] {cohort}: empty, skipping", file=sys.stderr)
            continue
        # Skipped-low-n rows come through as single-row with issue=skipped_low_n
        if len(df) == 1 and str(df.iloc[0].get("issue", "")).startswith("skipped_low_n"):
            print(f"[03_pool] {cohort}: skipped_low_n (n_normal too small)", file=sys.stderr)
            continue

        n_tumor = int(df["n_tumor"].iloc[0])
        n_normal = int(df["n_normal"].iloc[0])
        n_proteins_tested = int(df["gene_symbol"].nunique())

        out = pd.DataFrame({
            "cohort": cohort,
            "gene_symbol": df["gene_symbol"].astype(str),
            "uniprot_ac": df["gene_symbol"].map(uniprot_map).astype("string"),
            "protein_effect_size": df["logFC"].astype(float),
            # MSstatsTMT moderated-model standard error (02_msstats emits `SE`) — carried through so the
            # read layer can report an EXACT variance-standardized effect (logFC/SE) instead of only the
            # raw log2 difference the class thresholds on. NaN when the upstream row lacks it.
            "protein_effect_size_se": (df["SE"].astype(float) if "SE" in df.columns
                                       else pd.Series([float("nan")] * len(df))),
            "protein_p_value": df["pvalue"].astype(float),
            "protein_bh_q_value": df["adj.pvalue"].astype(float),
            "protein_median_log2_tumor": df["med_log2_tumor"].astype(float),
            "protein_median_log2_normal": df["med_log2_normal"].astype(float),
            "n_tumor_samples": n_tumor,
            "n_normal_samples": n_normal,
            "n_proteins_tested_cohort": n_proteins_tested,
            # variance-aware classify (G7): pass SE + per-cohort n so a negligible Cohen's d demotes a
            # significant-by-n call to small_effect. SE column is NaN-filled when the upstream lacks it
            # (→ classify falls back to the raw-logFC bands).
            "protein_expression_class": [
                classify(f, q, se, n_tumor, n_normal)
                for f, q, se in zip(df["logFC"], df["adj.pvalue"],
                                    (df["SE"] if "SE" in df.columns else [None] * len(df)))
            ],
            "stat_test_used": STAT_TEST_USED,
            "method_version": METHOD_VERSION,
        })
        frames.append(out)
        n_strong_up = (out["protein_expression_class"] == "strong_up").sum()
        n_modest_up = (out["protein_expression_class"] == "modest_up").sum()
        print(f"[03_pool] {cohort}: {len(out):,} proteins, "
              f"{n_strong_up} strong_up, {n_modest_up} modest_up",
              file=sys.stderr)

    if not frames:
        raise RuntimeError("No cohort results found. Run stage 02 first.")

    merged = pd.concat(frames, ignore_index=True)
    # Sort gene_symbol-leading so pyarrow predicate pushdown on gene_symbol fires efficiently.
    merged = merged.sort_values(["gene_symbol", "cohort"], kind="mergesort").reset_index(drop=True)

    # Pin count columns to int32 to match the derived-manifest schema contract
    # (pandas defaults these to int64, which trips strict schema validation).
    for col in ("n_tumor_samples", "n_normal_samples", "n_proteins_tested_cohort"):
        merged[col] = merged[col].astype("int32")

    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(merged, preserve_index=False)
    pq.write_table(tbl, args.out_parquet, compression="snappy", row_group_size=64)
    print(f"[03_pool] wrote {args.out_parquet} — {len(merged):,} rows, "
          f"{merged['cohort'].nunique()} cohorts, "
          f"{merged['gene_symbol'].nunique()} unique proteins",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
