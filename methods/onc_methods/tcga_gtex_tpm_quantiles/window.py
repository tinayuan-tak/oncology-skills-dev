"""tcga_gtex_tpm_quantiles.window — modality therapeutic-window scorer (biologics-augment).

The clean-antigen therapeutic-window signal from the biologics-target-discovery repo, re-homed
onto the framework's own materialized product (tcga-gtex-tpm-tissue-quantiles-v1) at CLAIM-GRADE
TPM (the source repo used a CPM-analog). Answers the question NEITHER tumor-vs-normal-selectivity
(a within-tissue-of-origin contrast) NOR normal-tissue-liability (off-tumor breadth) answers:

    is tumor expression high enough RELATIVE TO the worst essential normal organ to open a
    therapeutic window for THIS modality tier?

CEACAM5 is the archetype the single fused ratio surfaces: a ~440x window that is STILL a strict-
TCE liability (lung > 1.0 TPM), clean for a moderate-tier ADC. Neither existing card makes that call.

TWO deliberate corrections over the source repo's shipped scorer (its OWN audit flagged both):
  1. THEME-1 FIX — the source divides by max_essential_expr and DISCARDS max_normal_expr, so
     "clean" means "clean vs ~15 essential organs" only. TACSTD2 (TROP2) is the proof: essential-
     only window looks fine, but its true liability is salivary_gland/skin/vagina (non-essential,
     ~500 TPM). We emit BOTH window_essential AND window_full_normal so non-essential-tissue
     dirtiness is VISIBLE, never hidden.
  2. COHORT-HONESTY — DLL3 in LUAD reads ~0 (neuroendocrine target, wrong cohort; TCGA has no SCLC
     study). A missing/near-zero tumor cell is data_unavailable / not_expressed, NEVER a false
     "clean" or "not a candidate".

TWO SUBSTRATE CORRECTIONS (2026-09-12 denominator audit over the full product; both VERDICT-MOVING):
  3. MARROW IS NOT A TISSUE HERE — recount3's GTEx `BONE_MARROW` is the K-562 erythroleukemia cell
     line (ELANE 0.06 / MPO 1.98 / LTF 0.23 vs HBG1 11,162), yet it was the essential argmax for
     24.2% of expressed genes. The label is EXCLUDED from both denominators and the marrow slot is
     REPOINTED to primary marrow (marrow.primary_marrow_tpm) — dropping it outright would delete
     myelosuppression, the dose-limiting toxicity for payload ADCs and myeloid TCEs. See marrow.py
     for the marker panel, the measured cross-platform offset, and the coverage discipline.
  4. TESTIS IS IMMUNE-PRIVILEGED — behind the blood-testis barrier and not dose-limiting the way
     liver/marrow/heart are, yet it was the FULL-normal argmax for 25.8% of genes and specifically
     sank the cancer-testis antigen class (CTAG1B/NY-ESO-1 full-normal 0.17, MAGEA4 0.04, PRAME
     0.28). Testis is excluded from the full-normal KILL denominator but STILL REPORTED
     (`testis_tpm` + the `*_incl_privileged` triplet), so nothing is hidden — it just does not gate.

Pure over quantile rows (no S3 here; the caller passes rows from read_pan_cancer_by_tissue plus the
marrow value, so the substrate repoint does not break purity), unit-testable with a synthetic frame.
Modality tiers ported verbatim from target-contracts/cards/normal-tissue-liability.card.yaml
(strict 1.0 / moderate 5.0 / pathway_dependent 10.0) — the SAME thresholds the framework governs by.
"""

from __future__ import annotations

from typing import Optional

from .marrow import (
    MARROW_ORGAN_LABEL,
    MARROW_PLATFORM_OFFSET_MEDIAN,
    MARROW_SUBSTRATE_ID,
    SUBSTRATE_UNAVAILABLE,
)

# 2.0.0 (2026-09-12): MAJOR — the essential and full-normal denominators changed substrate (K-562
# `BONE_MARROW` out + primary marrow in; TESTIS out of the full-normal KILL denominator). Window
# ratios and all three *_window_class fields MOVE. Not a compatible 1.x refinement.
METHOD_VERSION = "2.0.0"

# Indication -> TCGA study code(s). Reuses the canonical map from dge_deseq2 (do NOT invent a 7th
# indication map — see the framework's indication-vocabulary-fragmentation lesson). Imported lazily
# in the reader entry; duplicated minimally here only for the pure path's default.
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

# Essential normal organs (life-critical; on-target-off-tumor toxicity catastrophic). GTEx `group`
# labels in the quantiles product. Mirrors the biologics repo's gtex_tissue_map essential set +
# the framework's own hpa_normal_tissue_liability ESSENTIAL_TISSUES (same intent, GTEx vocabulary).
#
# BY DESIGN (2026-08-13 review, finding #1): this set is indication-INDEPENDENT and therefore INCLUDES
# the tumour's own tissue of origin (e.g. LUNG for a LUAD target, LIVER for LIHC, BRAIN for GBM). That
# is intentional, not a bug: the therapeutic-window ratio is the framework's ORIGIN-TISSUE ARBITER —
# the sc-normal veto arm (sc_normal_expression) deliberately treats an origin-tissue hit as "on-tissue,
# arbitrated by the therapeutic window", deferring the origin call HERE. An antigen highly expressed in
# its own normal origin organ IS a real ADC/TCE toxicity concern (you cannot spare the origin organ),
# so counting the origin toward the window is the correct conservative stance, not a false veto.
#
# This is the essential-ORGAN POLICY set (which organs are life-critical) and it is unchanged — it is
# crosswalked by normal_tissue_safety_common.essential_organs and CI-guarded against the canonical
# vital-organ vocabulary, so BONE_MARROW stays. WHICH SUBSTRATE may stand in for an organ is a
# separate question, answered by CELL_LINE_GTEX_GROUPS below: marrow is still essential, but the
# product's GTEx `BONE_MARROW` rows are a cell line and never reach a denominator.
ESSENTIAL_GTEX_TISSUES = frozenset(
    {
        "ADRENAL_GLAND",
        "BLOOD",
        "BLOOD_VESSEL",
        "BONE_MARROW",
        "BRAIN",
        # COLON — added 2026-09-18 with the `gut` promotion in CANONICAL_VITAL_ORGANS. This literal
        # must track `essential_organs.GTEX_ESSENTIAL_TISSUES`: the CI guard asserts
        # `GTEX_ESSENTIAL_TISSUES <= WINDOW_SET`, so the shared set gaining an organ REDS this file
        # until the organ is added here. SPLEEN remains the one legitimate extra (canonical holds it).
        "COLON",
        "HEART",
        "KIDNEY",
        "LIVER",
        "LUNG",
        "MUSCLE",
        "NERVE",
        "PANCREAS",
        "PITUITARY",
        # SMALL_INTESTINE — added 2026-09-18 with `small_intestine` in CANONICAL_VITAL_ORGANS. THIS is
        # the arm the second gut organ exists FOR: GTEx COLON pools Sigmoid (muscularis) + Transverse
        # (mucosa) into one n=822 group, and THIS function reduces on the MEDIAN, which for a mucosal
        # antigen lands in the trough between the two modes. Measured live over the 504-pair corpus:
        # COLON alone moves `window_class` for 0 pairs; adding SMALL_INTESTINE moves 2
        # (GUCY2C-COADREAD, MUC17-STAD: clean_window -> essential_tissue_liability) and
        # `therapeutic_window_class` 3 (+ CDH17-COADREAD clean -> narrow).
        "SMALL_INTESTINE",
        "SPLEEN",
        "THYROID",
    }
)

# GTEx `group` labels in tcga-gtex-tpm-tissue-quantiles-v1 that are NOT primary tissue and therefore
# may not set a safety denominator. recount3's GTEx `BONE_MARROW` is the K-562 erythroleukemia cell
# line (2026-09-12 marker audit — see marrow.py). Excluded from BOTH denominators; the marrow slot is
# repointed via marrow.primary_marrow_tpm, not deleted.
#
# ★KNOWN WIDER SCOPE (this branch does not reach it): three OTHER methods carry their own copy of the
# 17-name essential set and still read the K-562 rows as marrow —
# `exon_window.classify.ESSENTIAL_GTEX_TISSUES`, `pair_selectivity_gate.gates.ESSENTIAL_GTEX_TISSUES`,
# and everything keyed on `normal_tissue_safety_common.essential_organs.GTEX_CROSSWALK["bone_marrow"]`
# (notably tcga_gtex_expression_distribution.stats). They need the same exclusion + repoint.
CELL_LINE_GTEX_GROUPS = frozenset({"BONE_MARROW"})

# Immune-privileged normal sites excluded from the FULL-NORMAL denominator (the pan-normal KILL) but
# STILL REPORTED. TESTIS sits behind the blood-testis barrier: high normal expression there is not
# dose-limiting the way liver/marrow/heart expression is, and the whole cancer-testis antigen class
# (CTAG1B/NY-ESO-1, MAGEA*, PRAME) is defined by exactly this pattern. It was the full-normal argmax
# for 25.8% of expressed genes. NB: TESTIS was never in the ESSENTIAL set, so this scopes the
# full-normal denominator ONLY — `window_ratio_essential` is untouched by it.
PRIVILEGED_NORMAL_SITES = frozenset({"TESTIS"})

# Modality-tiered essential-tissue thresholds, LINEAR TPM (ported from normal-tissue-liability.card.yaml).
MODALITY_TIER_THRESHOLD = {
    "bite_tce": 1.0,  # strict — no bystander payload; low-level essential expression is a killer
    "cell_therapy": 1.0,  # strict
    "adc": 5.0,  # moderate — bystander payload buffers some normal expression
    "antibody": 10.0,  # pathway_dependent
}
TUMOR_EXPRESSION_FLOOR_TPM = 1.0  # below this the tumor is effectively not-expressed (cohort-honesty)
CLEAN_WINDOW_RATIO = 4.0  # window ratio at/above which the tumor:normal separation is "clean"
_PSEUDOCOUNT = 1.0  # linear-TPM pseudocount (window = (tumor+1)/(normal+1))
# therapeutic_window_class tiers (2026-08-07, selectivity-conjunction INC-1/2) — a PURELY RATIO-BASED
# re-tiering of the tumor÷worst-essential-normal window, ADDITIVE to the legacy window_class (which
# keys off an ABSOLUTE essential-organ tier and collapsed high-window genes like CEACAM5 558x into the
# same essential_tissue_liability bucket as housekeeping genes at 0.5x). Empirically (30-gene backtest)
# housekeeping genes sit <1.0 (tumor BELOW worst critical normal = no window) while validated antigens
# are >1 (CEACAM5 558, NECTIN4 17, MSLN 8, EPCAM 4.8, MET 2.6). Thresholds are the user-set 2026-08-07.
THERAPEUTIC_WINDOW_CLEAN_RATIO = 5.0  # >= 5x worst critical-normal → comfortable window
THERAPEUTIC_WINDOW_MIN_RATIO = 1.0  # 1-5x → narrow (real but modest); < 1 → NO window (the veto)


def _log2tpm_to_linear(x: Optional[float]) -> Optional[float]:
    """Product stores log2(TPM+1); return linear TPM. None-safe."""
    if x is None:
        return None
    try:
        return float(2 ** float(x) - 1)
    except (TypeError, ValueError):
        return None


def compute_window_from_rows(
    rows,
    indication: str,
    tier_threshold_tpm: float = MODALITY_TIER_THRESHOLD["bite_tce"],
    marrow_tpm: Optional[float] = None,
    marrow_substrate: str = SUBSTRATE_UNAVAILABLE,
    marrow_note: Optional[str] = None,
) -> dict:
    """Therapeutic-window summary for one gene in one indication, from quantile rows.

    `rows`: the read_pan_cancer_by_tissue(target) DataFrame (columns source, group, median, ...).
    `marrow_tpm` / `marrow_substrate`: primary bone-marrow expression from marrow.primary_marrow_tpm,
    injected so this function stays pure. When it is None the essential denominator covers 14 organs
    and `n_essential_organs` says so — marrow is NEVER scored as 0 (that would read as a clean window).
    Returns a dict with BOTH denominators (Theme-1 fix) + a tiered window_class. Pure — no S3.

    window_class vocabulary:
      not_expressed_in_cohort — tumor median < TUMOR_EXPRESSION_FLOOR_TPM (or cohort absent)
                                → cohort-honesty: NOT a "clean"/"dirty" call (data_unavailable-adjacent)
      clean_window            — window_essential >= CLEAN_WINDOW_RATIO AND no essential organ >= tier
      essential_tissue_liability — an essential organ >= the modality tier threshold (the teeth)
      narrow_window           — expressed + no essential liability, but window_essential < clean ratio
      data_unavailable        — no tumor rows for the indication's studies, or product empty
    """
    import pandas as pd

    if rows is None or (hasattr(rows, "empty") and rows.empty):
        return _empty("no TPM quantile rows for target (absent from product or product unavailable)")

    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    studies = INDICATION_TO_TCGA_STUDIES.get(str(indication).upper().strip())
    if not studies:
        return _empty(f"indication {indication} has no TCGA study mapping (window is TCGA-cohort-based)")

    tum = df[(df["source"] == "tcga_tumor") & (df["group"].isin(studies))]
    if tum.empty:
        return _empty(f"no TCGA tumor rows for {indication} studies {studies} (cohort gap, not a zero)")
    # numerator: max median across the indication's studies (conservative — the study where the
    # target is highest; a COADREAD target high in COAD but not READ still gets its due).
    tumor_tpm = max(_log2tpm_to_linear(v) or 0.0 for v in tum["median"])

    normal = df[df["source"] == "gtex_normal"]
    # SUBSTRATE GATE — the K-562 `BONE_MARROW` label may not set either denominator (see marrow.py).
    tissue = normal[~normal["group"].isin(CELL_LINE_GTEX_GROUPS)]

    def _max_over(frame, extra=()) -> tuple[float, Optional[str]]:
        """(max linear TPM, its label) over quantile rows plus any injected (label, tpm) pairs."""
        best_tpm, best_label = 0.0, None
        for _, r in frame.iterrows():
            lin = _log2tpm_to_linear(r["median"]) or 0.0
            if lin > best_tpm:
                best_tpm, best_label = lin, r["group"]
        for label, val in extra:
            if val is not None and float(val) > best_tpm:
                best_tpm, best_label = float(val), label
        return best_tpm, best_label

    # marrow arrives out-of-band (primary marrow, not the cell line). None => 14-organ essential set.
    marrow_pair = ((MARROW_ORGAN_LABEL, marrow_tpm),) if marrow_tpm is not None else ()

    # essential denominator + which organ
    ess = tissue[tissue["group"].isin(ESSENTIAL_GTEX_TISSUES)]
    max_ess_tpm, max_ess_organ = _max_over(ess, marrow_pair)
    # FULL-normal-panel denominator (Theme-1 fix) — catches non-essential-tissue dirtiness. The
    # immune-privileged sites are held OUT of the gating max but reported below, both ways.
    gating = tissue[~tissue["group"].isin(PRIVILEGED_NORMAL_SITES)]
    max_norm_tpm, max_norm_organ = _max_over(gating, marrow_pair)
    max_norm_tpm_incl, max_norm_organ_incl = _max_over(tissue, marrow_pair)

    privileged_tpm = {}
    for _, r in tissue[tissue["group"].isin(PRIVILEGED_NORMAL_SITES)].iterrows():
        privileged_tpm[str(r["group"])] = round(_log2tpm_to_linear(r["median"]) or 0.0, 2)

    window_essential = (tumor_tpm + _PSEUDOCOUNT) / (max_ess_tpm + _PSEUDOCOUNT)
    window_full_normal = (tumor_tpm + _PSEUDOCOUNT) / (max_norm_tpm + _PSEUDOCOUNT)
    window_full_normal_incl = (tumor_tpm + _PSEUDOCOUNT) / (max_norm_tpm_incl + _PSEUDOCOUNT)

    result = {
        "window_class": None,
        "full_normal_window_class": None,  # set below (axis-B pan-normal companion; additive)
        "tumor_tpm": round(tumor_tpm, 2),
        "max_essential_normal_tpm": round(max_ess_tpm, 2),
        "max_essential_normal_organ": max_ess_organ,
        "max_full_normal_tpm": round(max_norm_tpm, 2),
        "max_full_normal_organ": max_norm_organ,
        "window_ratio_essential": round(window_essential, 2),
        "window_ratio_full_normal": round(window_full_normal, 2),
        "modality_tier_threshold_tpm": tier_threshold_tpm,
        "tumor_studies": studies,
        "n_gtex_tissues": int(tissue["group"].nunique()),
        # --- substrate provenance (2026-09-12): what the denominators are actually made of --------
        "excluded_cell_line_groups": sorted(CELL_LINE_GTEX_GROUPS),
        "marrow_tpm": None if marrow_tpm is None else round(float(marrow_tpm), 2),
        "marrow_substrate": marrow_substrate,
        "marrow_substrate_id": MARROW_SUBSTRATE_ID,
        "marrow_platform_offset_median": MARROW_PLATFORM_OFFSET_MEDIAN,  # measured, NOT applied
        "n_essential_organs": int(ess["group"].nunique()) + (1 if marrow_tpm is not None else 0),
        # --- immune-privileged sites: REPORTED, but not gating the pan-normal KILL ---------------
        "privileged_normal_sites_excluded": sorted(PRIVILEGED_NORMAL_SITES),
        "privileged_normal_tpm": privileged_tpm,
        "max_full_normal_tpm_incl_privileged": round(max_norm_tpm_incl, 2),
        "max_full_normal_organ_incl_privileged": max_norm_organ_incl,
        "window_ratio_full_normal_incl_privileged": round(window_full_normal_incl, 2),
    }
    if marrow_note:
        result["_marrow_note"] = marrow_note
    # NEW therapeutic_window_class (INC-1/2): PURELY the ratio, independent of the absolute-tier
    # window_class below. This is the selectivity-veto instrument (the ratio separates housekeeping
    # from real antigens where the absolute-tier class does not). Computed even when not_expressed.
    if tumor_tpm < TUMOR_EXPRESSION_FLOOR_TPM:
        result["therapeutic_window_class"] = "not_expressed_in_cohort"
    elif window_essential >= THERAPEUTIC_WINDOW_CLEAN_RATIO:
        result["therapeutic_window_class"] = "clean_window"
    elif window_essential >= THERAPEUTIC_WINDOW_MIN_RATIO:
        result["therapeutic_window_class"] = "narrow_window"
    else:
        result["therapeutic_window_class"] = "no_therapeutic_window"  # ratio < 1: tumor BELOW worst
        # critical normal → the veto

    # full_normal_window_class (2026-08-08, selectivity review axis-B companion) — the SAME ratio
    # tiering as therapeutic_window_class but keyed on window_full_normal (tumor ÷ worst of the
    # FULL GTEx atlas, not just the 15 essential organs). therapeutic_window_class can only see
    # essential-organ liability, so a gene broad across NON-essential normals (the TROP2/salivary-
    # gland archetype: skin/salivary/vagina, none life-critical) reads clean_window there yet has
    # no real pan-normal window. This companion surfaces that breadth. ADDITIVE + verdict-inert:
    # therapeutic_window_class above is UNCHANGED (the INC-1/2 veto instrument stays byte-stable);
    # this field is a NEW signal for a future pan-normal-breadth veto arm (see the selectivity-
    # conjunction plan, deferred to the selectivity session) and for narrative honesty today.
    if tumor_tpm < TUMOR_EXPRESSION_FLOOR_TPM:
        result["full_normal_window_class"] = "not_expressed_in_cohort"
    elif window_full_normal >= THERAPEUTIC_WINDOW_CLEAN_RATIO:
        result["full_normal_window_class"] = "clean_full_normal_window"
    elif window_full_normal >= THERAPEUTIC_WINDOW_MIN_RATIO:
        result["full_normal_window_class"] = "narrow_full_normal_window"
    else:
        result["full_normal_window_class"] = "no_full_normal_window"  # broad across the atlas
        # (incl. non-essential) → veto candidate

    # cohort-honesty gate first (legacy window_class — UNCHANGED tiering, its 3 surface rules stay byte-stable)
    if tumor_tpm < TUMOR_EXPRESSION_FLOOR_TPM:
        result["window_class"] = "not_expressed_in_cohort"
        return result
    essential_liability = max_ess_tpm >= tier_threshold_tpm
    if essential_liability:
        result["window_class"] = "essential_tissue_liability"
    elif window_essential >= CLEAN_WINDOW_RATIO:
        result["window_class"] = "clean_window"
    else:
        result["window_class"] = "narrow_window"
    return result


def _empty(note: str) -> dict:
    return {
        "window_class": "data_unavailable",
        "therapeutic_window_class": "data_unavailable",
        "full_normal_window_class": "data_unavailable",
        "tumor_tpm": None,
        "max_essential_normal_tpm": None,
        "max_essential_normal_organ": None,
        "max_full_normal_tpm": None,
        "max_full_normal_organ": None,
        "window_ratio_essential": None,
        "window_ratio_full_normal": None,
        "modality_tier_threshold_tpm": None,
        "tumor_studies": None,
        "n_gtex_tissues": 0,
        "excluded_cell_line_groups": sorted(CELL_LINE_GTEX_GROUPS),
        "marrow_tpm": None,
        "marrow_substrate": SUBSTRATE_UNAVAILABLE,
        "marrow_substrate_id": MARROW_SUBSTRATE_ID,
        "marrow_platform_offset_median": MARROW_PLATFORM_OFFSET_MEDIAN,
        "n_essential_organs": 0,
        "privileged_normal_sites_excluded": sorted(PRIVILEGED_NORMAL_SITES),
        "privileged_normal_tpm": {},
        "max_full_normal_tpm_incl_privileged": None,
        "max_full_normal_organ_incl_privileged": None,
        "window_ratio_full_normal_incl_privileged": None,
        "_data_note": note,
    }


def read_modality_window(target: str, indication: str, modality: str = "bite_tce") -> dict:
    """Reader entry the card dispatcher calls: fetch quantile rows for the gene, reduce to the
    therapeutic-window summary for the indication at the modality's essential-tissue tier.

    modality selects the tier threshold (bite_tce=strict 1.0 / adc=moderate 5.0 / antibody=10.0);
    default strict (the conservative BiTE/TCE tier), matching the source repo's default.

    Two substrates, not one: the quantiles product supplies tumour + the 14 primary GTEx essentials,
    and marrow.primary_marrow_tpm supplies the repointed marrow value (the GTEx `BONE_MARROW` label
    is K-562). A marrow read failure degrades to a 14-organ essential set with `marrow_substrate:
    unavailable`, never to a silent marrow == 0."""
    from .marrow import primary_marrow_tpm
    from .read import read_pan_cancer_by_tissue

    tier = MODALITY_TIER_THRESHOLD.get(str(modality).lower(), MODALITY_TIER_THRESHOLD["bite_tce"])
    rows = read_pan_cancer_by_tissue(target)
    marrow_tpm, marrow_substrate, marrow_note = primary_marrow_tpm(target)
    out = compute_window_from_rows(
        rows,
        indication,
        tier_threshold_tpm=tier,
        marrow_tpm=marrow_tpm,
        marrow_substrate=marrow_substrate,
        marrow_note=marrow_note,
    )
    out["modality"] = str(modality).lower()
    out["target"] = target
    out["indication"] = str(indication).upper().strip()
    out["method_version"] = METHOD_VERSION  # card-declared summary_field (was never emitted)
    return out
