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
import math
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

_STD_NORMAL = NormalDist()
import pyarrow as pa
import pyarrow.parquet as pq

CPTAC_COHORTS = ["BRCA", "CCRCC", "COAD", "GBM", "HNSCC", "LSCC", "LUAD", "OV", "PDAC", "UCEC"]

METHOD_VERSION = "1.3.0"  # 2026-09-12: unestimable contrast (log2FC=+/-Inf) → data_unavailable, not not_significant
STAT_TEST_USED = "msstatstmt_limma_ebayes_moderated"

# Below this |Cohen's d| the standardized (sample-size-independent) effect is negligible — a call that
# cleared significance via cohort size / low variance rather than a real per-sample tumor-vs-normal
# difference. Conventional small-effect floor (Cohen 1988). Mirrors read.py _cohens_d_class.
NEGLIGIBLE_COHENS_D = 0.2


def _is_finite(x) -> bool:
    """True only for a real, computable number. `pd.isna` rejects NaN/None but ADMITS +/-Inf, which is
    exactly how MSstatsTMT reports an unestimable contrast — see the note in classify()."""
    try:
        return x is not None and not pd.isna(x) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _cohens_d(logfc, se, n_tumor, n_normal, p_value=None):
    """Sample-size-INDEPENDENT standardized effect. Prefers the EXACT MSstatsTMT moderated SE
    (t = logFC / SE); when SE is unavailable, recovers an APPROXIMATE t from the two-sided p-value
    (z = sign(logFC)·Φ⁻¹(1 − p/2)) — the same fallback read.py._standardized_effect uses, so a product
    that carries p-value + n (but not SE, like the currently-deployed one) is STILL variance-aware
    without a MSstats re-run. Cohen's d = t / sqrt(n_eff), n_eff = n_t·n_n/(n_t+n_n). Returns None only
    when neither SE nor p is usable, or n is missing → the caller then falls back to raw-logFC bands."""
    try:
        if not (n_tumor and n_normal and float(n_tumor) > 0 and float(n_normal) > 0):
            return None
        if not _is_finite(logfc):  # +/-Inf (unestimable contrast) as well as NaN — see classify()
            return None
        t = None
        if se is not None and not pd.isna(se) and float(se) > 0:
            t = float(logfc) / float(se)  # exact moderated-SE t
        elif p_value is not None and not pd.isna(p_value) and 0.0 <= float(p_value) <= 1.0:
            arg = min(max(1.0 - float(p_value) / 2.0, 1e-15), 1.0 - 1e-15)  # clamp for inv_cdf
            t = math.copysign(_STD_NORMAL.inv_cdf(arg), float(logfc))  # p-value z-score approximation
        if t is None:
            return None
        n_eff = (float(n_tumor) * float(n_normal)) / (float(n_tumor) + float(n_normal))
        return t / (n_eff**0.5)
    except Exception:  # noqa: BLE001
        return None


OK_ISSUES = frozenset({"", "ok", "none", "nan", "na"})


def classify(
    logfc: float,
    q: float,
    se: float = None,
    n_tumor: int = None,
    n_normal: int = None,
    p_value: float = None,
    issue: str = None,
) -> str:
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
    #
    # 2026-09-12 (W4): UNESTIMABLE != FLAT. MSstatsTMT does not emit NA for a protein quantified in only
    # ONE condition — it emits log2FC = +/-Inf with NA pvalue/adj.pvalue/SE (its `oneConditionMissing`
    # issue). `Inf` is not `NaN`, so the isna() guard below fell through to the `q >= 0.05` arm and
    # labelled 1,618 rows of the shipped v1.2.0 product `not_significant` — asserting "tested, no
    # tumor-vs-normal difference" about a ratio that has no denominator. BRCA: 1,613 of 10,491 (15.4%);
    # GBM: 5. STEAP1/BRCA (85 tumor aliquots, 0 normal) is the motivating case. `data_unavailable` is
    # already in the card's protein_expression_class vocabulary, so this is a vocabulary-legal move; it is
    # also OUT of _ELEVATED_CLASSES, so it cannot fabricate an up-call. Deliberately NOT rescued upward:
    # zero quantifications across 18 normal aliquots does not let whole-proteome TMT assert absence.
    # The upstream `issue` column (stage 02) is now authoritative when it flags anything — this is where
    # MSstatsTMT's own oneConditionMissing / completeMissing reaches the product instead of being dropped.
    # Finiteness is the independent backstop, so an older TSV with no issue column is still handled.
    if issue is not None and not pd.isna(issue) and str(issue).strip().lower() not in OK_ISSUES:
        return "data_unavailable"
    if not _is_finite(logfc):
        return "data_unavailable"
    if pd.isna(q):
        return "not_significant"
    if q >= 0.05:
        return "not_significant"
    # variance-aware gate: prefer exact SE; else the RAW p-value z-score approximation (NOT q — the
    # BH-adjusted value would understate the effect). When neither SE nor raw p is available, _cohens_d
    # returns None → raw-logFC bands (no downgrade).
    d = _cohens_d(logfc, se, n_tumor, n_normal, p_value=p_value)
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
    ap.add_argument("--uniprot-map", type=Path, default=None, help="Optional gene_symbol → uniprot_ac TSV")
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

        out = pd.DataFrame(
            {
                "cohort": cohort,
                "gene_symbol": df["gene_symbol"].astype(str),
                "uniprot_ac": df["gene_symbol"].map(uniprot_map).astype("string"),
                "protein_effect_size": df["logFC"].astype(float),
                # MSstatsTMT moderated-model standard error (02_msstats emits `SE`) — carried through so the
                # read layer can report an EXACT variance-standardized effect (logFC/SE) instead of only the
                # raw log2 difference the class thresholds on. NaN when the upstream row lacks it.
                "protein_effect_size_se": (
                    df["SE"].astype(float) if "SE" in df.columns else pd.Series([float("nan")] * len(df))
                ),
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
                    classify(f, q, se, n_tumor, n_normal, p_value=p, issue=iss)
                    for f, q, se, p, iss in zip(
                        df["logFC"],
                        df["adj.pvalue"],
                        (df["SE"] if "SE" in df.columns else [None] * len(df)),
                        (df["pvalue"] if "pvalue" in df.columns else [None] * len(df)),
                        (df["issue"] if "issue" in df.columns else [None] * len(df)),
                    )
                ],
                "stat_test_used": STAT_TEST_USED,
                "method_version": METHOD_VERSION,
            }
        )
        frames.append(out)
        n_strong_up = (out["protein_expression_class"] == "strong_up").sum()
        n_modest_up = (out["protein_expression_class"] == "modest_up").sum()
        print(
            f"[03_pool] {cohort}: {len(out):,} proteins, {n_strong_up} strong_up, {n_modest_up} modest_up",
            file=sys.stderr,
        )

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
    print(
        f"[03_pool] wrote {args.out_parquet} — {len(merged):,} rows, "
        f"{merged['cohort'].nunique()} cohorts, "
        f"{merged['gene_symbol'].nunique()} unique proteins",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
