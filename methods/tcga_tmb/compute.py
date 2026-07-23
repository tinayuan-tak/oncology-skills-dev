"""compute.py — TMB computation core for tcga_tmb (pure, unit-testable).

TMB = count of NONSYNONYMOUS coding mutations per sample / exome-covered Mb.
Nonsynonymous = the MAF v2.4 coding-altering classes (excludes Silent, UTR,
Intron, Flank, RNA, IGR). Denominator is the standard 38 Mb TMB exome size.
Threshold for tmb_bucket == 'high' is the FDA pan-cancer 10 mut/Mb (pembrolizumab
TMB-H label, KEYNOTE-158 / Marabelle 2020).
"""
from __future__ import annotations

import re

import pandas as pd

# MAF v2.4 Variant_Classification values counted toward TMB (nonsynonymous
# coding). Mirrors the cBioPortal / FDA-aligned nonsynonymous set.
NONSYNONYMOUS_CLASSES = frozenset({
    "Missense_Mutation",
    "Nonsense_Mutation",
    "Nonstop_Mutation",
    "Splice_Site",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
    "In_Frame_Del",
    "In_Frame_Ins",
    "Translation_Start_Site",
})

# Standard whole-exome covered size for TMB normalization (Mb). MC3 is WES;
# 38 Mb is the conventional TMB denominator (cf. Chalmers 2017, FoundationOne).
DEFAULT_EXOME_MB = 38.0

# FDA pan-cancer TMB-high threshold (mut/Mb).
DEFAULT_TMB_HIGH_THRESHOLD = 10.0

_BARCODE_PATIENT_RE = re.compile(r"^(TCGA-[A-Z0-9]+-[A-Z0-9]+)")


def patient_key(barcode: str | None) -> str | None:
    """TCGA participant-level barcode (TCGA-tss-participant) from any aliquot."""
    if not isinstance(barcode, str):
        return None
    m = _BARCODE_PATIENT_RE.match(barcode)
    return m.group(1) if m else None


def compute_tmb(
    maf: pd.DataFrame,
    *,
    variant_class_col: str = "Variant_Classification",
    barcode_col: str = "Tumor_Sample_Barcode",
    exome_mb: float = DEFAULT_EXOME_MB,
    high_threshold: float = DEFAULT_TMB_HIGH_THRESHOLD,
) -> pd.DataFrame:
    """Per-sample TMB table from a MAF-shaped DataFrame.

    Returns one row per patient_key with columns:
      patient_key, n_nonsyn, tmb_mut_per_mb, tmb_bucket ('high'|'low').

    Samples present in the MAF but with zero nonsynonymous variants still get a
    row (n_nonsyn=0, tmb=0, bucket='low') — a sample assayed with no coding
    mutation is a true TMB-low, not missing.
    """
    df = maf[[variant_class_col, barcode_col]].copy()
    df["patient_key"] = df[barcode_col].map(patient_key)
    df = df[df["patient_key"].notna()]

    all_samples = pd.Index(df["patient_key"].unique(), name="patient_key")
    nonsyn = df[df[variant_class_col].isin(NONSYNONYMOUS_CLASSES)]
    counts = nonsyn.groupby("patient_key").size().reindex(all_samples, fill_value=0)

    out = counts.rename("n_nonsyn").reset_index()
    out["tmb_mut_per_mb"] = (out["n_nonsyn"] / exome_mb).round(4)
    out["tmb_bucket"] = out["tmb_mut_per_mb"].apply(
        lambda v: "high" if v >= high_threshold else "low")
    return out.sort_values("patient_key").reset_index(drop=True)
