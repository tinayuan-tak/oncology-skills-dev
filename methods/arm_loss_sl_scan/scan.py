"""arm_loss_sl_scan.scan — pure find-mode core.

SL -> arm-loss -> indication discovery. The hypothesis (passenger-deletion / CYCLOPS SL
paradigm): a target G whose curated synthetic-lethal partner P sits on a chromosome arm that
is RECURRENTLY LOST in an indication is a candidate dependency in that indication, because the
arm-level loss co-deletes P and unmasks the G-dependency. Two independent products ground the
two halves of the claim:

  DISCOVERY signal  -> pancan-arm-cnv-per-sample-v1: per-(arm, indication) loss frequency
                       (which arms are recurrently lost in which indications).
  CONFIRMATION      -> pancan-genomic-two-hit-per-gene-v1: does the SPECIFIC partner gene P
                       actually get lost (cn_class in {homdel, loss}) in those same patients,
                       or is the arm-level signal a spurious aggregate?

This module is PURE / S3-free: `sl_arm_scan` takes already-materialized DataFrames + dicts and
is fully offline-testable. The S3 reads (SL pairs, arm calls, two-hit, GISTIC gene->arm meta) and
the input_manifest_ids federation sidecar live in cli.py.

STATISTICS: for each (target, partner-arm, indication) the observed arm-loss frequency is tested
one-sided against the PAN-CANCER arm-loss baseline (binomial, "is this arm lost MORE than average
in this indication?"). p-values are Benjamini-Hochberg corrected across the full tested set. A hit
must clear BOTH q <= fdr_alpha AND a min-frequency floor (a tiny-but-significant arm loss is not
actionable). This is a DISCOVERY nomination scan, NOT a verdict input — it never feeds a resolver.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

METHOD_VERSION = "scan-0.1.0"

# Output columns (stable; the eval-ledger row_from_scan reader keys on these).
SCAN_COLUMNS = [
    "target", "sl_partner", "partner_arm", "indication",
    "arm_loss_freq", "arm_pancan_baseline", "n_samples", "n_arm_lost",
    "binom_p", "q_value",
    "partner_twohit_loss_freq", "coloss_concordance",
    "evidence_tier", "has_experimental", "rank", "method_version",
]


def _binom_greater_p(k: int, n: int, p0: float) -> float:
    """One-sided binomial p (P[X >= k] under Binom(n, p0)). scipy binomtest with legacy fallback."""
    if n <= 0:
        return 1.0
    p0 = min(max(p0, 1e-9), 1 - 1e-9)
    try:
        from scipy.stats import binomtest
        return float(binomtest(k, n, p0, alternative="greater").pvalue)
    except ImportError:  # pragma: no cover - legacy scipy
        from scipy.stats import binom_test
        return float(binom_test(k, n, p0, alternative="greater"))


def _bh_qvalues(pvals: list) -> list:
    """Benjamini-Hochberg q-values. statsmodels when present; self-contained fallback otherwise."""
    if not pvals:
        return []
    try:
        from statsmodels.stats.multitest import multipletests
        return list(multipletests(pvals, method="fdr_bh")[1])
    except ImportError:  # pragma: no cover
        m = len(pvals)
        order = sorted(range(m), key=lambda i: pvals[i])
        q = [0.0] * m
        prev = 1.0
        for rank, i in enumerate(reversed(order), start=1):
            k = m - rank + 1
            val = min(prev, pvals[i] * m / k)
            q[i] = prev = val
        return q


def sl_arm_scan(
    sl_pairs: pd.DataFrame,
    arm_ind_freq: pd.DataFrame,
    arm_pancan_baseline: dict,
    gene_to_arm: dict,
    twohit_loss_freq: Optional[dict] = None,
    *,
    min_loss_freq: float = 0.20,
    fdr_alpha: float = 0.05,
    min_baseline_delta: float = 0.0,
    method_version: str = METHOD_VERSION,
) -> pd.DataFrame:
    """Rank (target, sl_partner, partner_arm, indication) hits where the partner's arm is
    enriched-for-loss in the indication.

    sl_pairs:            DataFrame [target, partner, evidence_tier, has_experimental].
    arm_ind_freq:        DataFrame [chromosome_arm, indication, n_samples, loss_frequency, ...]
                         (pancan_arm_cnv.read.build_arm_indication_freq output).
    arm_pancan_baseline: {arm: pan-cancer loss frequency} (pooled over all indications).
    gene_to_arm:         {GENE (upper): 'chromosome_arm'} (pancan_arm_cnv.read.gene_arm_map).
    twohit_loss_freq:    optional {(PARTNER upper, indication): gene-level loss frequency} — the
                         per-patient co-loss CONFIRMATION column; missing -> NaN / 'no_twohit_data'.
    min_loss_freq:       actionability floor on the observed arm-loss frequency.
    fdr_alpha:           BH q-value cutoff.
    min_baseline_delta:  optional floor on (arm_loss_freq - pancan_baseline) to drop hits that are
                         significant only because n is large (default 0 = disabled).
    """
    twohit_loss_freq = twohit_loss_freq or {}
    freq_lookup = {
        (r["chromosome_arm"], r["indication"]): (float(r["loss_frequency"]), int(r["n_samples"]))
        for _, r in arm_ind_freq.iterrows()
    }

    candidates = []
    for _, pair in sl_pairs.iterrows():
        target = str(pair["target"]).strip().upper()
        partner = str(pair["partner"]).strip().upper()
        arm = gene_to_arm.get(partner)
        if arm is None:
            continue  # partner not on a mappable arm (acrocentric / absent from GISTIC meta)
        baseline = arm_pancan_baseline.get(arm)
        if baseline is None:
            continue
        for (a, ind), (loss_freq, n) in freq_lookup.items():
            if a != arm:
                continue
            k = int(round(loss_freq * n))
            p = _binom_greater_p(k, n, float(baseline))
            candidates.append({
                "target": target, "sl_partner": partner, "partner_arm": arm, "indication": ind,
                "arm_loss_freq": round(loss_freq, 4), "arm_pancan_baseline": round(float(baseline), 4),
                "n_samples": n, "n_arm_lost": k, "binom_p": p,
                "partner_twohit_loss_freq": twohit_loss_freq.get((partner, ind)),
                "evidence_tier": pair.get("evidence_tier"),
                "has_experimental": bool(pair.get("has_experimental", False)),
            })

    if not candidates:
        return pd.DataFrame(columns=SCAN_COLUMNS)

    qvals = _bh_qvalues([c["binom_p"] for c in candidates])
    for c, q in zip(candidates, qvals):
        c["q_value"] = float(q)

    def _concordance(row):
        tw = row["partner_twohit_loss_freq"]
        if tw is None or (isinstance(tw, float) and pd.isna(tw)):
            return "no_twohit_data"
        # partner gene-level loss confirms the arm-level inference when it also clears the floor.
        return "confirmed" if float(tw) >= min_loss_freq else "arm_only"

    hits = []
    for c in candidates:
        if c["q_value"] > fdr_alpha:
            continue
        if c["arm_loss_freq"] < min_loss_freq:
            continue
        if (c["arm_loss_freq"] - c["arm_pancan_baseline"]) < min_baseline_delta:
            continue
        c["coloss_concordance"] = _concordance(c)
        c["method_version"] = method_version
        hits.append(c)

    if not hits:
        return pd.DataFrame(columns=SCAN_COLUMNS)

    df = pd.DataFrame(hits)
    # rank: strongest enrichment first (lowest q, then highest observed loss frequency)
    df = df.sort_values(["q_value", "arm_loss_freq"], ascending=[True, False]).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df[SCAN_COLUMNS]
