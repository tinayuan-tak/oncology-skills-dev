"""immune_context.classify — per-indication tumor immune-context (T-cell infiltration) classifier.

The EFFECTOR arm of the biologics story (the IO-target-ID seed note's method #2): a T-cell engager
redirects cytotoxic T cells to the antigen, so it can only work where T cells are PRESENT to be
redirected. Surface antigen presence (surface-modality-fit) answers "is there a target?"; this
answers the orthogonal "is there an effector population?" — immune-hot vs immune-cold.

Pure over per-sample CIBERSORT LM22 leukocyte fractions (no S3 here). Substrate:
gdc-pancanatlas-immune-2018 (Thorsson 2018) — 22 leukocyte subtypes per TCGA sample, grouped by TCGA
study (CancerType). The core TCE-relevant signal is the CD8 (+ total) T-cell fraction of the
leukocyte compartment.

v1 is target-INDEPENDENT (tier: indication): the immune landscape of the indication. The sharper
antigen-CONDITIONED join (are the ANTIGEN-HIGH patients also T-cell-high?) SHIPPED (see
antigen_conditioned.py; surfaced by the skill since v1.6.1) as an additive verdict-inert facet.

Thresholds are anchored to the PAN-CANCER across-study distribution (data-driven, not arbitrary):
CD8-fraction study medians across 33 TCGA studies have quartiles ~[0.084, 0.097, 0.113].

READ THE CLASS AS A PAN-CANCER RANK, NOT AN ABSOLUTE DENSITY. The cuts ARE the 33-study Q3/Q1, so
~a quarter of studies are hot and a quarter cold BY CONSTRUCTION.

TWO FAIL-CLOSED GUARDS on top of the ladder, because a RELATIVE fraction is confidently computable
in situations where it means nothing:
  1. LYMPHOID DENOMINATOR — LM22 reports the CD8 share OF THE LEUKOCYTE COMPARTMENT, so where the
     leukocyte compartment IS the malignancy (leukemia, lymphoma) or IS a normal lymphoid organ
     (thymus), the denominator is not a tumor microenvironment and the share is meaningless.
  2. SAMPLE FLOOR — a median CD8 fraction over a handful of samples is a wide-CI guess; the sibling
     absolute-TIL reader (til_fraction_saltz) has had MIN_N = 30 since v1.0.0, this one had none.
Both resolve to a token that WITHHOLDS the number rather than publishing it with a caveat: a
reader anchors on "13% CD8" and never re-reads the caveat.
"""

from __future__ import annotations

from typing import Optional

# The LM22 columns that are T cells (CIBERSORT relative fractions of the leukocyte compartment).
T_CELL_COLUMNS = (
    "T.cells.CD8",
    "T.cells.CD4.naive",
    "T.cells.CD4.memory.resting",
    "T.cells.CD4.memory.activated",
    "T.cells.follicular.helper",
    "T.cells.regulatory..Tregs.",
    "T.cells.gamma.delta",
)
CD8_COLUMN = "T.cells.CD8"
# The SUPPRESSIVE side of the TME. These columns are already in the frame the reduction receives and
# were discarded — a CD8 fraction alone says nothing about whether those CD8 cells can function.
TREG_COLUMN = "T.cells.regulatory..Tregs."
M2_COLUMN = "Macrophages.M2"
M1_COLUMN = "Macrophages.M1"

# Pan-cancer across-study CD8-fraction quartiles (measured on the 33-study medians). A study at/above
# the pan-cancer Q3 is immune-hot for its CD8 compartment; at/below Q1 is immune-cold; between is
# intermediate. Anchored to the data so "hot"/"cold" means "relative to the pan-cancer landscape".
CD8_FRACTION_HOT_MIN = 0.113  # >= pan-cancer Q3 → immune-hot
CD8_FRACTION_COLD_MAX = 0.084  # <= pan-cancer Q1 → immune-cold

# Per-indication admissibility floor. Deliberately the SAME number as til_fraction_saltz.MIN_N: the two
# readers corroborate each other on the immune-context headline, so an n one of them calls too thin must
# not be an n the other scores confidently.
MIN_N_SAMPLES = 30

# RATIO DENOMINATOR NOISE FLOOR (2026-09-13, found by the 20-target panel). A ratio of medians is only
# as good as its denominator, and LM22's suppressor signatures COLLAPSE toward 0 in some cohorts rather
# than degrading smoothly — the Treg signature is the worst offender because CD4-memory-resting absorbs
# it. GBM's cohort median Treg fraction is 0.0002, which turned CD8:Treg into 176.0 next to a
# pan-cancer range of ~2.6-14 in every other measured indication: a division artefact presented as a
# 176-fold effector advantage in the one indication that is unambiguously immune-COLD (its own class
# token says immune_cold). Returning None below the floor is the same posture as the exact-0 case
# (PRAD, median Treg 0.0) rather than a special case for it, and the two medians are emitted beside the
# ratio, so a reader can always see WHY it abstained. 0.005 = 0.5% of the leukocyte compartment: it
# sits 25x above GBM's 0.0002 and well below the ~0.006-0.05 denominators of every ratio the panel
# actually produced, so it removes the artefact without touching a single real read.
MIN_RATIO_DENOMINATOR_FRACTION = 0.005

# THE DENOMINATOR CEILING. CIBERSORT LM22 is a RELATIVE deconvolution: every fraction is a share of the
# leukocyte compartment. That denominator is only a meaningful reference frame when the leukocytes are
# INFILTRATE. In these TCGA studies they are not:
#   LAML — the malignant myeloid clone is itself deconvolved into the leukocyte pool (median CD8 share
#          0.0216 → a confident `immune_cold` that is really "the denominator is blasts").
#   DLBC — the malignant B cells are the denominator (0.1142 → `immune_hot`). This is the dangerous one:
#          DLBCL is a TCE-VALIDATED indication (glofitamab, mosunetuzumab), so it is exactly where
#          someone will ask this skill for an effector read.
#   THYM — thymoma arises in a primary lymphoid organ; its (non-malignant) thymocytes dominate the pool
#          (0.2782 → the highest `immune_hot` in the atlas, and pure thymopoiesis, not anti-tumor TIL).
# NOT included, deliberately: TGCT (0.1130 → `immune_hot`). Seminoma is a germ-cell tumor with genuinely
# brisk lymphocytic infiltrate — the denominator is real infiltrate, so the read is admissible. Grouping
# it here because its class is also surprising would be guarding on OUTLIER-NESS instead of on mechanism.
# Keyed on the resolved TCGA STUDY code, not the indication string, so an alias ("AML", "DLBCL") added to
# any indication map is caught automatically rather than depending on a second denylist staying in sync.
LYMPHOID_DENOMINATOR_STUDIES = frozenset({"LAML", "DLBC", "THYM"})


def has_lymphoid_denominator(studies) -> bool:
    """True if ANY resolved TCGA study makes the leukocyte denominator uninterpretable.

    ANY, not ALL: pooling DLBC with a solid study contaminates the pooled median, so one bad study
    poisons the read. Fail-closed by construction."""
    if not studies:
        return False
    return bool({str(s).upper().strip() for s in studies} & LYMPHOID_DENOMINATOR_STUDIES)


def classify_immune_context(cd8_fraction: Optional[float], n_samples: Optional[int] = None) -> str:
    """immune_context_class from the indication's median CD8 T-cell fraction of the leukocyte pool.

    immune_hot          — CD8 fraction >= pan-cancer Q3 (ample effector population; TCE-favorable)
    immune_intermediate — between Q1 and Q3
    immune_cold         — CD8 fraction <= pan-cancer Q1 (T-cell-excluded/desert; TCE efficacy at risk)
    data_unavailable    — no CIBERSORT samples, or fewer than MIN_N_SAMPLES (abstain, never a false 'cold')

    `n_samples` is optional so this stays usable as the pure ladder (the antigen-conditioned facet
    applies its own n floor before calling). When supplied, the floor is enforced here.
    """
    if cd8_fraction is None:
        return "data_unavailable"
    if n_samples is not None and n_samples < MIN_N_SAMPLES:
        return "data_unavailable"
    if cd8_fraction >= CD8_FRACTION_HOT_MIN:
        return "immune_hot"
    if cd8_fraction <= CD8_FRACTION_COLD_MAX:
        return "immune_cold"
    return "immune_intermediate"


def _empty_summary(cls: str = "data_unavailable", n_samples: int = 0, note: Optional[str] = None) -> dict:
    """The abstain shape. EVERY numeric is None: a fail-closed class must not ship the number that
    provoked it, or a reader anchors on the number and forgets the class. Same KEY SET as a scored
    summary so a consumer never has to branch on the class to know which fields exist."""
    out = {
        "immune_context_class": cls,
        "median_cd8_fraction": None,
        "median_total_t_cell_fraction": None,
        "n_samples": n_samples,
        "cd8_hot_sample_fraction": None,
        "cd8_treg_ratio": None,
        "cd8_m2_ratio": None,
        "median_treg_fraction": None,
        "median_m2_macrophage_fraction": None,
        "median_m1_macrophage_fraction": None,
    }
    if note:
        out["_data_note"] = note
    return out


def _ratio_of_medians(numer_med: float, denom_med: Optional[float]) -> Optional[float]:
    """CD8:suppressor ratio as a ratio OF MEDIANS, not a median of per-sample ratios.

    Per-sample ratios are unusable here: LM22 assigns an exact 0.0 to absent subsets, so a per-sample
    Treg of 0 makes the ratio infinite, and in a cohort where most samples have Treg == 0 the MEDIAN of
    those ratios is itself infinite. The ratio of the two cohort medians is the same quantity a reader
    would compute from the two published medians, which is also the point: it is reproducible from the
    fields beside it. None when the denominator median is 0 (undefined, not "infinitely favorable")
    or below MIN_RATIO_DENOMINATOR_FRACTION (a deconvolution-noise-floor denominator, see below)."""
    if denom_med is None or denom_med < MIN_RATIO_DENOMINATOR_FRACTION:
        return None
    return round(numer_med / denom_med, 3)


def summarize_immune_context(rows, studies=None) -> dict:
    """Reduce per-sample CIBERSORT rows (for ONE indication's studies) to an immune-context summary.

    `rows`: list of dicts (or DataFrame) with the LM22 fraction columns. `studies`: the resolved TCGA
    study code(s) the rows came from — supplied so the LYMPHOID-DENOMINATOR guard can fire BEFORE any
    number is computed. Empty input → data_unavailable (honest — an indication with no CIBERSORT
    coverage is a gap, not a cold tumor)."""
    import numpy as np
    import pandas as pd

    # Guard FIRST, on the study codes alone: the failure mode here is not a missing number, it is a
    # perfectly computable one. Nothing downstream should see a median it might publish.
    if has_lymphoid_denominator(studies):
        bad = sorted({str(s).upper().strip() for s in studies} & LYMPHOID_DENOMINATOR_STUDIES)
        return _empty_summary(
            "lymphoid_denominator_unreliable",
            note=f"TCGA study/studies {bad} are hematologic or lymphoid-organ cohorts: CIBERSORT LM22 "
            f"reports the CD8 share OF THE LEUKOCYTE COMPARTMENT, and there that denominator is the "
            f"malignant clone (LAML/DLBC) or normal lymphoid tissue (THYM), not tumor-infiltrating "
            f"immunity. The share is arithmetically valid and biologically uninterpretable, so it is "
            f"withheld rather than published with a caveat.",
        )

    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty or CD8_COLUMN not in df.columns:
        return _empty_summary()
    n = int(len(df))
    cd8 = df[CD8_COLUMN].astype(float)
    if n < MIN_N_SAMPLES:
        return _empty_summary(
            n_samples=n,
            note=f"only {n} CIBERSORT samples (floor {MIN_N_SAMPLES}, the same floor the corroborating "
            f"til_fraction_saltz reader applies) — a cohort median this thin is a wide-CI guess, not a class",
        )
    tcols = [c for c in T_CELL_COLUMNS if c in df.columns]
    total_t = df[tcols].sum(axis=1)
    cd8_med = float(np.median(cd8))

    def _med(col):
        return float(np.median(df[col].astype(float))) if col in df.columns else None

    treg_med, m2_med, m1_med = _med(TREG_COLUMN), _med(M2_COLUMN), _med(M1_COLUMN)
    return {
        "immune_context_class": classify_immune_context(cd8_med, n_samples=n),
        "median_cd8_fraction": round(cd8_med, 4),
        "median_total_t_cell_fraction": round(float(np.median(total_t)), 4),
        "n_samples": n,
        # HETEROGENEITY. The cohort median is a poor summary of a BIMODAL cohort: MSI-H colorectal
        # (~15% of CRC) is strongly infiltrated and the other 85% is not, so the pooled median reads
        # `immune_intermediate` and the patient population a TCE would actually be developed for is
        # invisible. This is the fraction of SAMPLES at or above the hot cut — the same threshold, read
        # as prevalence instead of central tendency.
        "cd8_hot_sample_fraction": round(float((cd8 >= CD8_FRACTION_HOT_MIN).mean()), 3),
        # SUPPRESSION. Effector PRESENCE is only half a TCE-efficacy read; an inflamed-but-suppressed
        # TME (Treg-high / M2-high) is a different proposition from a bare hot call. Both denominators
        # were already columns in this frame and were being discarded.
        "cd8_treg_ratio": _ratio_of_medians(cd8_med, treg_med),
        "cd8_m2_ratio": _ratio_of_medians(cd8_med, m2_med),
        "median_treg_fraction": round(treg_med, 4) if treg_med is not None else None,
        "median_m2_macrophage_fraction": round(m2_med, 4) if m2_med is not None else None,
        "median_m1_macrophage_fraction": round(m1_med, 4) if m1_med is not None else None,
    }
