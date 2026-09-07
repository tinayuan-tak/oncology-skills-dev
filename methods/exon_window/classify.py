"""exon_window.classify — per-EXON tumor-vs-normal window scorer (enrichment E5).

The exon-resolution twin of tcga_gtex_tpm_quantiles.window. Reads
tcga-gtex-exon-tpm-quantiles-v1 (per exon_id × source × group log2(exon-TPM+1) quantiles,
surfaceome-scoped).

WHAT IT HONESTLY CLAIMS (calibrated by live-smoke 2026-08-07 against the real product):
  This scores a per-gene tumor-vs-essential-normal window at EXON resolution + within-gene
  exon HETEROGENEITY. It is a HYPOTHESIS-GENERATING flag, NOT an isoform-identity call.
  Per-exon COVERAGE quantiles (recount3 exon_sums) are blind to WHICH TRANSCRIPT an exon
  belongs to, so this CANNOT confirm a specific isoform (e.g. it cannot resolve CLDN18.2 from
  CLDN18.1 — the tumor-dominant CLDN18 exon is a shared/constitutive exon). A high
  exon_heterogeneity_flag means "this gene's tumor-dominant exon stands well above its other
  exons with a clean window — worth a JUNCTION-level / isoform-resolved follow-up", not
  "this is an isoform-restricted target". Isoform identity needs junction/PSI data.

exon_window_class vocabulary:
  exon_heterogeneity_flag   — the tumor-DOMINANT exon (a) stands >= EXON_HETEROGENEITY_LOG2
                              above the gene's median exon in tumor AND (b) has a clean
                              tumor-vs-essential-normal window. A candidate for isoform-resolved
                              follow-up (NOT a confirmed isoform target).
  uniform_gene_window       — expressed, exons behave uniformly (low heterogeneity) → the
                              gene-level window already captures it; no exon-level nuance.
  essential_exon_liability  — the tumor-dominant exon's own essential-normal expression clears
                              the modality tier → not clean even at exon grain (a real liability).
  not_expressed_in_cohort   — tumor-dominant exon < floor (cohort-honesty).
  not_in_product            — gene absent from the surfaceome-scoped product → honest coverage
                              gap, NOT a negative.
  data_unavailable          — product unreadable / indication unmapped.

BEST EXON = the TUMOR-DOMINANT exon (highest tumor expression) — the epitope-bearing exon of
the dominant tumor isoform, i.e. what a binder actually engages. NOT the max-window-ratio exon
(which could be a low-tumor exon whose window is high only because normal ~0 — the bug caught at
live-smoke that gave CLDN18 negative heterogeneity). Reuses the gene-window's
INDICATION_TO_TCGA_STUDIES + ESSENTIAL_GTEX_TISSUES + modality tiers verbatim (no new map).
"""

from __future__ import annotations

import math
from typing import Optional

INDICATION_TO_TCGA_STUDIES = {
    "COADREAD": ["COAD", "READ"],
    "COAD": ["COAD"],
    "READ": ["READ"],
    "NSCLC": ["LUAD", "LUSC"],
    "LUAD": ["LUAD"],
    "LUSC": ["LUSC"],
    "PAAD": ["PAAD"],
    "BRCA": ["BRCA"],
    "OV": ["OV"],
    "STAD": ["STAD"],
    "HNSC": ["HNSC"],
    "HNSCC": ["HNSC"],
    "LIHC": ["LIHC"],
    "PRAD": ["PRAD"],
    "BLCA": ["BLCA"],
    "KIRC": ["KIRC"],
    "GBM": ["GBM"],
    "SKCM": ["SKCM"],
    "UCEC": ["UCEC"],
    "ESCA": ["ESCA"],
    "CESC": ["CESC"],
    "THCA": ["THCA"],
}
ESSENTIAL_GTEX_TISSUES = frozenset(
    {
        "ADRENAL_GLAND",
        "BLOOD",
        "BLOOD_VESSEL",
        "BONE_MARROW",
        "BRAIN",
        "HEART",
        "KIDNEY",
        "LIVER",
        "LUNG",
        "MUSCLE",
        "NERVE",
        "PANCREAS",
        "PITUITARY",
        "SPLEEN",
        "THYROID",
    }
)
MODALITY_TIER_THRESHOLD = {"bite_tce": 1.0, "cell_therapy": 1.0, "adc": 5.0, "antibody": 10.0}
TUMOR_EXPRESSION_FLOOR_TPM = 1.0
CLEAN_WINDOW_RATIO = 4.0
EXON_HETEROGENEITY_LOG2 = 2.0  # tumor-dominant exon must exceed the gene's median exon by >= this (4x)
_PSEUDOCOUNT = 1.0
METHOD_VERSION = "1.1.0"  # 1.1.0: tumor-dominant best-exon (live-smoke fix) + honest exon_heterogeneity_flag naming


def _lin(x: Optional[float]) -> float:
    if x is None:
        return 0.0
    try:
        return float(2 ** float(x) - 1)
    except (TypeError, ValueError):
        return 0.0


def compute_exon_window_from_rows(
    rows, indication: str, tier_threshold_tpm: float = MODALITY_TIER_THRESHOLD["bite_tce"]
) -> dict:
    """Per-gene exon-window summary from exon-quantile rows (all exons of ONE gene). Pure — no S3."""
    import pandas as pd

    if rows is None or (hasattr(rows, "empty") and rows.empty):
        return _empty("not_in_product", "gene absent from surfaceome-scoped exon product")
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    studies = INDICATION_TO_TCGA_STUDIES.get(str(indication).upper().strip())
    if not studies:
        return _empty("data_unavailable", f"indication {indication} has no TCGA study mapping")

    tum = df[(df["source"] == "tcga_tumor") & (df["group"].isin(studies))]
    if tum.empty:
        return _empty("data_unavailable", f"no tumor exon rows for {indication} studies {studies}")
    ess = df[(df["source"] == "gtex_normal") & (df["group"].isin(ESSENTIAL_GTEX_TISSUES))]

    per_exon = {}
    for exon_id, g in tum.groupby("exon_id"):
        per_exon.setdefault(exon_id, {})["tumor"] = max(_lin(v) for v in g["median"])
    for exon_id, g in ess.groupby("exon_id"):
        per_exon.setdefault(exon_id, {})["ess"] = max(_lin(v) for v in g["median"])
    if not per_exon:
        return _empty("data_unavailable", "no per-exon tumor values")

    # BEST EXON = tumor-dominant (max tumor expression) — see module docstring.
    best = None
    for exon_id, d in per_exon.items():
        t = d.get("tumor", 0.0)
        if best is None or t > best["tumor_tpm"]:
            best = {"exon_id": exon_id, "tumor_tpm": t, "ess_tpm": d.get("ess", 0.0)}
    best["window"] = (best["tumor_tpm"] + _PSEUDOCOUNT) / (best["ess_tpm"] + _PSEUDOCOUNT)

    tumor_log2 = sorted(math.log2(d.get("tumor", 0.0) + 1.0) for d in per_exon.values())
    median_exon_log2 = tumor_log2[len(tumor_log2) // 2]
    best_exon_log2 = math.log2(best["tumor_tpm"] + 1.0)
    heterogeneity = best_exon_log2 - median_exon_log2  # >= 0 by construction (best is the max-tumor exon)

    result = {
        "exon_window_class": None,
        "n_exons": len(per_exon),
        "best_exon_id": best["exon_id"],
        "best_exon_tumor_tpm": round(best["tumor_tpm"], 2),
        "best_exon_max_essential_tpm": round(best["ess_tpm"], 2),
        "best_exon_window_ratio": round(best["window"], 2),
        "exon_heterogeneity_log2": round(heterogeneity, 2),
        "median_exon_tumor_log2tpm": round(median_exon_log2, 2),
        "modality_tier_threshold_tpm": tier_threshold_tpm,
        "tumor_studies": studies,
    }
    if best["tumor_tpm"] < TUMOR_EXPRESSION_FLOOR_TPM:
        result["exon_window_class"] = "not_expressed_in_cohort"
    elif best["ess_tpm"] >= tier_threshold_tpm:
        result["exon_window_class"] = "essential_exon_liability"
    elif best["window"] >= CLEAN_WINDOW_RATIO and heterogeneity >= EXON_HETEROGENEITY_LOG2:
        result["exon_window_class"] = "exon_heterogeneity_flag"
    else:
        result["exon_window_class"] = "uniform_gene_window"
    return result


def _empty(cls: str, note: str) -> dict:
    return {
        "exon_window_class": cls,
        "n_exons": 0,
        "best_exon_id": None,
        "best_exon_tumor_tpm": None,
        "best_exon_max_essential_tpm": None,
        "best_exon_window_ratio": None,
        "exon_heterogeneity_log2": None,
        "median_exon_tumor_log2tpm": None,
        "modality_tier_threshold_tpm": None,
        "tumor_studies": None,
        "_data_note": note,
    }
