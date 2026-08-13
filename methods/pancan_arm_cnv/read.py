"""Derive per-(sample, chromosome_arm) copy-number loss/gain calls from the TCGA PanCanAtlas
GISTIC gene-level thresholded matrix (all_thresholded.by_genes_whitelisted.tsv), plus a
per-(chromosome_arm, indication) loss/gain frequency companion.

WHY derive: the source's seg_based_scores.tsv is GENOME-WIDE only (n_segs/frac_altered/n_extrema) —
it has NO per-arm calls (see the corrected gdc-pancanatlas-cnv-2018 manifest). The GISTIC
all_thresholded file gives per-(gene, sample) discrete calls in {-2,-1,0,+1,+2} and a per-gene
`Cytoband` column, so an arm call is a fraction-of-arm-altered aggregation of its genes' calls.

ARM-CALL METHOD (documented + parametrized): for each (sample, arm),
  loss_frac = fraction of the arm's genes with GISTIC <= -1 (single- or deep-loss)
  gain_frac = fraction with GISTIC >= +1
  arm_call  = -1 (loss)  if loss_frac >= threshold and loss_frac >= gain_frac
              +1 (gain)  if gain_frac >= threshold and gain_frac >  loss_frac
               0 (neutral) otherwise
`threshold` defaults to 0.5 (arm called altered when a majority of its genes are altered) — a
standard fraction-of-arm cutoff. This is a threshold-based derivation; the canonical Taylor et al.
2018 arm calls (PANCAN_ArmCallsAndAneuploidyScore) are the intended future VALIDATION cross-check
(not yet pulled). The threshold is surfaced in provenance so downstream (the SL arm-loss find-mode)
can see it; the find-mode applies its own FDR + min-frequency floor on top.

The pure functions (build_arm_calls / build_arm_indication_freq / arm_of) take DataFrames/dicts and
are S3-free (unit-testable offline); the S3 read + parquet write live in derive.py.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

# Non-gene columns in the GISTIC all_thresholded matrix; everything else is a sample barcode column.
_META_COLS = ("Gene Symbol", "Locus ID", "Cytoband")
_ARM_RE = re.compile(r"^(\d{1,2}|X|Y)([pq])")


def arm_of(cytoband: Optional[str]) -> Optional[str]:
    """Map a GISTIC cytoband string ('1p36.33', '12q24.11', 'Xp22.33') to its chromosome arm
    ('1p', '12q', 'Xp'). None for acrocentric/unparseable bands (dropped)."""
    if not isinstance(cytoband, str):
        return None
    m = _ARM_RE.match(cytoband.strip())
    return f"{m.group(1)}{m.group(2)}" if m else None


def _patient_of(sample_barcode: str) -> str:
    """TCGA patient id = first 3 hyphen fields of an aliquot barcode (TCGA-OR-A5J1-01A-... -> TCGA-OR-A5J1)."""
    return "-".join(sample_barcode.split("-")[:3])


def build_arm_calls(gistic_df: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    """Per-(sample, chromosome_arm) loss/gain call from the GISTIC gene-level thresholded matrix.

    gistic_df: rows = genes; columns include 'Gene Symbol','Locus ID','Cytoband' + one column per
    sample barcode with values in {-2,-1,0,1,2}. Returns long DataFrame:
      sample_barcode, chromosome_arm, arm_call (-1/0/+1), loss_frac, gain_frac, n_genes.
    """
    if "Cytoband" not in gistic_df.columns:
        raise KeyError("gistic_df must have a 'Cytoband' column")
    sample_cols = [c for c in gistic_df.columns if c not in _META_COLS]
    arms = gistic_df["Cytoband"].map(arm_of)
    rows = []
    for arm, idx in arms.dropna().groupby(arms).groups.items():
        block = gistic_df.loc[idx, sample_cols]
        n_genes = len(idx)
        if n_genes == 0:
            continue
        loss_frac = (block <= -1).sum(axis=0) / n_genes      # per-sample Series
        gain_frac = (block >= 1).sum(axis=0) / n_genes
        for s in sample_cols:
            lf, gf = float(loss_frac[s]), float(gain_frac[s])
            if lf >= threshold and lf >= gf:
                call = -1
            elif gf >= threshold and gf > lf:
                call = 1
            else:
                call = 0
            rows.append({"sample_barcode": s, "chromosome_arm": arm, "arm_call": call,
                         "loss_frac": round(lf, 4), "gain_frac": round(gf, 4), "n_genes": n_genes})
    out = pd.DataFrame(rows, columns=["sample_barcode", "chromosome_arm", "arm_call",
                                      "loss_frac", "gain_frac", "n_genes"])
    return out.sort_values(["chromosome_arm", "sample_barcode"]).reset_index(drop=True)


def build_arm_indication_freq(arm_calls: pd.DataFrame, barcode_to_indication: dict) -> pd.DataFrame:
    """Per-(chromosome_arm, indication) loss/gain frequency — the 'arm event enriched in indication Y'
    edge. barcode_to_indication maps a sample or patient barcode to an OncoTree/TCGA indication code;
    samples with no mapping are dropped."""
    df = arm_calls.copy()
    df["indication"] = df["sample_barcode"].map(
        lambda b: barcode_to_indication.get(b) or barcode_to_indication.get(_patient_of(b)))
    df = df[df["indication"].notna()]
    rows = []
    for (arm, ind), g in df.groupby(["chromosome_arm", "indication"]):
        n = len(g)
        rows.append({"chromosome_arm": arm, "indication": ind, "n_samples": n,
                     "loss_frequency": round((g["arm_call"] == -1).sum() / n, 4),
                     "gain_frequency": round((g["arm_call"] == 1).sum() / n, 4)})
    return pd.DataFrame(rows, columns=["chromosome_arm", "indication", "n_samples",
                                       "loss_frequency", "gain_frequency"]
                        ).sort_values(["chromosome_arm", "indication"]).reset_index(drop=True)


def gene_arm_map(gistic_meta_df: pd.DataFrame) -> dict:
    """Map gene symbol -> chromosome arm from the GISTIC meta columns ('Gene Symbol','Cytoband').

    Cheap side-table (usecols=['Gene Symbol','Cytoband'] over the same all_thresholded matrix the
    arm calls derive from) so a downstream scan can look up an SL partner's arm without a separate
    coord/cytoband source. Genes on acrocentric/unparseable bands are dropped. Upper-cased keys
    (HGNC symbols as in GISTIC). Last-wins on the rare duplicate symbol."""
    if "Gene Symbol" not in gistic_meta_df.columns or "Cytoband" not in gistic_meta_df.columns:
        raise KeyError("gistic_meta_df must have 'Gene Symbol' and 'Cytoband' columns")
    out = {}
    for sym, band in zip(gistic_meta_df["Gene Symbol"], gistic_meta_df["Cytoband"]):
        arm = arm_of(band)
        if arm is not None and isinstance(sym, str):
            out[sym.strip().upper()] = arm
    return out
