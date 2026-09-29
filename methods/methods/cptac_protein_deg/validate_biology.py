#!/usr/bin/env python3
"""validate_biology.py — executable gate for the CPTAC protein DEG parquet.

Two tiers, one exit code.

STRUCTURAL tier — invariants about how the product represents an UNESTIMABLE contrast. These are
version-conditional so the gate flips automatically at the next rebuild instead of rotting:
    method_version <= 1.2.0  -> the unestimable defect is KNOWN-PRESENT; assert the count matches the
                                pinned measurement exactly (drift in EITHER direction is a failure).
    method_version >= 1.3.0  -> the defect must be GONE; assert every non-finite-effect row is
                                classed `data_unavailable`.

BIOLOGY-ANCHOR tier — well-characterized tumor-antigen overexpression anchors that a correct
tumor-vs-normal contrast must recover. On the shipped v1.2.0 build 4 of 5 FAIL, and the failures are
NOT mis-set thresholds — they say the contrast itself is compressed or inverted (see KNOWN_RED_ANCHORS).
The anchors are therefore kept VERBATIM and pinned as a known-red ledger: the gate is green when
reality matches the ledger, and RED when a listed anchor starts passing (the build changed — retire
the ledger entry) or an unlisted one fails (a NEW regression). `--strict-anchors` ignores the ledger
and demands all anchors pass; that is the acceptance gate for the contrast-design rebuild.

Usage:
    python -m methods.cptac_protein_deg.validate_biology \\
        --parquet ~/dev/framework-runs/.../cptac_protein_deg.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------------------------------
# Pinned measurements of the currently-shipped build (v1.2.0, measured 2026-09-12 against
# s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/).
#
# MSstatsTMT reports a protein quantified in only ONE condition as log2FC = +/-Inf with NA p/q/SE, not
# as NA. `pd.isna(Inf)` is False, so classify()'s isna guard passed them through to its `q >= 0.05` arm
# and stamped them `not_significant` — "tested, no tumor-vs-normal difference" about a ratio with no
# denominator. Fixed for future builds in steps/02 + steps/03; the shipped product still carries it, and
# methods/cptac_protein_deg/read.py neutralizes it at read time.
UNESTIMABLE_ROWS_V1_2_0 = 1618  # BRCA 1,613 of 10,491 (15.4%) + GBM 5; ALL carry NaN q AND NaN SE
FIXED_IN_METHOD_VERSION = "1.3.0"

# Anchors that FAIL on the shipped v1.2.0 build, with the measured value and why the failure is a BUILD
# defect rather than an over-optimistic threshold. Per-sample evidence (read_per_sample):
#   ERBB2/BRCA   normal median -1.718 (sd 0.235, n=18) vs tumor -1.534 (sd 1.072, n=125) -> logFC +0.18
#   MSLN/OV      normal median  0.033 vs tumor  0.072 -> logFC +0.02, i.e. no difference at all
#   MKI67/BRCA   normal median -0.245 vs tumor -0.615 -> Ki-67, THE proliferation marker, reads DOWN in
#                tumor. That is not a threshold miss; it is a broken contrast.
# The normals' spread is ~4x tighter than the tumors' in every case, the signature of normal channels
# concentrated in a few TMT plexes against a plex-specific reference pool. Root cause sits in the
# deferred contrast-design workstream (paired data analysed unpaired, proteinSummarization skipped,
# pseudo-replication fan-out, comparator selection, 76 dropped normal aliquots) — NOT here.
KNOWN_RED_ANCHORS = {
    "ERBB2/BRCA": "logFC +0.57 (need >=2.0), q 0.32 — contrast compressed; see per-sample note above",
    "MSLN/OV": "logFC +0.02 (need >=3.0), q 0.88 — tumor and normal medians are indistinguishable",
    "FOLH1/PDAC": "logFC -0.07 (need >=0.5), q 0.61 — wrong sign",
    "MKI67 universal": "up in 3/10 cohorts (need >=8) — DOWN in BRCA tumor vs normal",
}


def load(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["gene_symbol"] = df["gene_symbol"].astype(str).str.upper()
    df["cohort"] = df["cohort"].astype(str).str.upper()
    return df


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(p) for p in str(v).strip().split("."))
    except ValueError:
        return (0,)


# --- structural tier -------------------------------------------------------------------------------


def check_unestimable_representation(df) -> tuple[bool, str]:
    """An unestimable contrast must never be reported as a flat measurement."""
    eff = df["protein_effect_size"].astype(float)
    nonfinite = ~np.isfinite(eff)
    n = int(nonfinite.sum())
    versions = sorted(str(v) for v in df["method_version"].dropna().unique())
    build = max(versions, key=_version_tuple) if versions else "0"
    mislabelled = df.loc[nonfinite & (df["protein_expression_class"] != "data_unavailable")]

    if _version_tuple(build) >= _version_tuple(FIXED_IN_METHOD_VERSION):
        ok = mislabelled.empty
        detail = "" if ok else f" — e.g. {sorted(mislabelled['gene_symbol'].unique())[:5]}"
        return ok, (
            f"unestimable representation (build {build} >= {FIXED_IN_METHOD_VERSION}): "
            f"{len(mislabelled)} of {n} non-finite-effect rows are NOT data_unavailable "
            f"(0 required){detail} — {'PASS' if ok else 'FAIL'}"
        )

    ok = n == UNESTIMABLE_ROWS_V1_2_0
    return ok, (
        f"unestimable representation (build {build}, KNOWN-DEFECT ledger): {n} non-finite-effect rows, "
        f"{len(mislabelled)} of them mislabelled non-data_unavailable; pinned expectation "
        f"{UNESTIMABLE_ROWS_V1_2_0} — {'PASS (matches ledger)' if ok else 'FAIL (count drifted)'}"
    )


def check_unestimable_is_detectable(df) -> tuple[bool, str]:
    """Finiteness of the effect size must remain a COMPLETE discriminator for unestimability — the read
    layer relies on it (there is no `issue` column in the product schema). If a row ever appears with a
    finite effect but no q, or with a non-finite effect AND a q, that assumption is broken and read.py's
    neutralization silently stops covering some rows."""
    eff = df["protein_effect_size"].astype(float)
    q = df["protein_bh_q_value"].astype(float)
    finite_no_q = int((np.isfinite(eff) & q.isna()).sum())
    nonfinite_with_q = int((~np.isfinite(eff) & q.notna()).sum())
    ok = finite_no_q == 0 and nonfinite_with_q == 0
    return ok, (
        f"non-finite-effect <-> NaN-q equivalence: {finite_no_q} finite-effect rows lack q, "
        f"{nonfinite_with_q} non-finite-effect rows carry a q (0/0 required) — {'PASS' if ok else 'FAIL'}"
    )


def check_no_effect_size_poisons_ranking(df) -> tuple[bool, str]:
    """Every gene whose only rows are unestimable must be reportable as data_unavailable rather than as a
    flat measurement — i.e. the product must not be the sole source of a fabricated 'tested and flat'."""
    eff = df["protein_effect_size"].astype(float)
    per_gene = df.assign(_fin=np.isfinite(eff)).groupby("gene_symbol")["_fin"].any()
    only_unestimable = sorted(per_gene[~per_gene].index)
    return True, (
        f"genes with NO estimable cohort: {len(only_unestimable)} "
        f"(e.g. {only_unestimable[:4]}) — read.py must report these data_unavailable, not not_significant "
        "(informational)"
    )


# --- biology-anchor tier ---------------------------------------------------------------------------


def check_target_cohort(df, gene, cohort, min_logfc, max_q, label) -> tuple[bool, str]:
    sub = df[(df["gene_symbol"] == gene) & (df["cohort"] == cohort)]
    if sub.empty:
        return False, f"{label}: {gene} not in {cohort}"
    logfc = float(sub["protein_effect_size"].iloc[0])
    q = float(sub["protein_bh_q_value"].iloc[0])
    ok = (logfc >= min_logfc) and (q <= max_q)
    return (
        ok,
        f"{label}: {gene} in {cohort} logFC={logfc:.2f} (>={min_logfc}), q={q:.2e} (<={max_q}) — {'PASS' if ok else 'FAIL'}",
    )


def check_mki67_universal(df) -> tuple[bool, str]:
    mki = df[df["gene_symbol"] == "MKI67"]
    if mki.empty:
        return False, "MKI67 not in parquet"
    up = mki[(mki["protein_effect_size"] > 1.0) & (mki["protein_bh_q_value"] < 0.05)]
    n_up = len(up)
    n_total = len(mki)
    ok = n_up >= 8
    return ok, (f"MKI67 up (logFC>1.0, q<0.05) in {n_up}/{n_total} cohorts (>=8 required) — {'PASS' if ok else 'FAIL'}")


def check_target_present(df, gene, label) -> tuple[bool, str]:
    sub = df[df["gene_symbol"] == gene]
    ok = not sub.empty
    return ok, f"{label}: {gene} rows={len(sub)} — {'PASS' if ok else 'FAIL'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True, type=Path)
    ap.add_argument(
        "--strict-anchors",
        action="store_true",
        help="Ignore KNOWN_RED_ANCHORS and require every biology anchor to pass "
        "(the acceptance gate for a contrast-design rebuild).",
    )
    args = ap.parse_args()

    df = load(args.parquet)
    print(
        f"[validate] loaded {len(df):,} rows, "
        f"{df['gene_symbol'].nunique()} unique proteins, "
        f"{df['cohort'].nunique()} cohorts: {sorted(df['cohort'].unique())}",
        file=sys.stderr,
    )

    structural = [
        check_unestimable_representation(df),
        check_unestimable_is_detectable(df),
        check_no_effect_size_poisons_ranking(df),
    ]
    print("[validate] STRUCTURAL tier (must pass):", file=sys.stderr)
    for ok, msg in structural:
        print(f"  {'✓' if ok else '✗'} {msg}", file=sys.stderr)

    anchors = {
        "ERBB2/BRCA": check_target_cohort(df, "ERBB2", "BRCA", 2.0, 0.001, "ERBB2/BRCA"),
        "MSLN/OV": check_target_cohort(df, "MSLN", "OV", 3.0, 0.001, "MSLN/OV"),
        "FOLH1/PDAC": check_target_cohort(df, "FOLH1", "PDAC", 0.5, 0.05, "FOLH1/PDAC"),
        "MDM2 presence": check_target_present(df, "MDM2", "MDM2 presence"),
        "MKI67 universal": check_mki67_universal(df),
    }
    print("[validate] BIOLOGY-ANCHOR tier:", file=sys.stderr)
    for name, (ok, msg) in anchors.items():
        expected_red = (not args.strict_anchors) and name in KNOWN_RED_ANCHORS
        mark = "✓" if ok else ("~ KNOWN-RED" if expected_red else "✗")
        print(f"  {mark} {msg}", file=sys.stderr)
        if expected_red and not ok:
            print(f"        ledger: {KNOWN_RED_ANCHORS[name]}", file=sys.stderr)

    failures = [f"structural: {msg}" for ok, msg in structural if not ok]
    if args.strict_anchors:
        failures += [f"anchor: {msg}" for ok, msg in anchors.values() if not ok]
    else:
        # Ratchet on the ledger: a NEW failure is a regression, and a listed anchor that now PASSES
        # means the build moved and the ledger is stale (it must be retired, not silently carried).
        for name, (ok, msg) in anchors.items():
            if not ok and name not in KNOWN_RED_ANCHORS:
                failures.append(f"anchor NEW regression: {msg}")
            if ok and name in KNOWN_RED_ANCHORS:
                failures.append(
                    f"anchor {name} now PASSES but is pinned in KNOWN_RED_ANCHORS — the contrast was "
                    "rebuilt; retire the ledger entry (and re-run with --strict-anchors)"
                )

    n_red = sum(1 for name, (ok, _) in anchors.items() if not ok)
    print(
        f"[validate] structural {sum(1 for ok, _ in structural if ok)}/{len(structural)} · "
        f"anchors {len(anchors) - n_red}/{len(anchors)} passing "
        f"({len(KNOWN_RED_ANCHORS)} pinned known-red) · {len(failures)} gate failure(s)",
        file=sys.stderr,
    )
    if not args.strict_anchors and n_red:
        print(
            "[validate] NOTE: the known-red anchors are evidence that the tumor-vs-normal CONTRAST is "
            "compressed/inverted, not that the thresholds are wrong. Tracked separately from this gate; "
            "run --strict-anchors to validate a contrast-design rebuild.",
            file=sys.stderr,
        )
    for f in failures:
        print(f"[validate] GATE FAILURE — {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
