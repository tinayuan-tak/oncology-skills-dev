"""Single source of truth for the SAFETY-ESSENTIAL normal-organ set shared by the three
normal-tissue liability cards.

Motivation: the three normal-tissue cards each maintained their
OWN essential/critical-organ list, and they DIVERGED. `tcga_gtex_expression_distribution.stats.
CRITICAL_NORMAL_TISSUES` (the safety-comparator card) OMITTED THYROID / ADRENAL_GLAND / PITUITARY /
BLOOD_VESSEL — and carried a dead `ARTERY` entry that never matches the recount3/GTEx vocabulary
(GTEx groups the arteries under `BLOOD_VESSEL`). So a thyroid-/adrenal-/vascular-restricted target
(e.g. TSHR, ~159 TPM in thyroid) read `restricted_normal` — a FAVORABLE signal — and its TCE
liability reached the composed surface-modality verdict as `both_viable`. Meanwhile the GTEx
*window* card (`tcga_gtex_tpm_quantiles.window.ESSENTIAL_GTEX_TISSUES`) already used the correct
15-tissue set, so the framework held two divergent GTEx essential sets at once.

Fix: declare the canonical vital-organ set ONCE and crosswalk it to each card's native tissue
vocabulary. `None` in a crosswalk means the organ is NOT representable in that source's vocabulary
(e.g. HPA's 16-name grouped-intensity field has no thyroid / adrenal / pituitary group — a DATA
SUBSTRATE gap, not a list omission; closing it requires a new normal-tissue proteomics source).

SPLEEN is intentionally EXCLUDED from the canonical set: immunologically important but not a
classic dose-limiting vital organ, and its inclusion is a judgment call reserved for review.
The CI guard asserts COVERAGE (each source covers the canonical organs
its vocab supports), NOT equality — so a source that ADDITIONALLY lists SPLEEN (the GTEx window
card does) is fine, and promoting spleen to canonical later is a one-line change here.
"""

from __future__ import annotations

# Canonical vital / dose-limiting organs: on-target expression here is a therapeutic-window red
# flag regardless of tumor abundance. Semantic tokens (source-vocab-independent).
CANONICAL_VITAL_ORGANS = frozenset(
    {
        "heart",
        "brain",
        "liver",
        "lung",
        "kidney",
        "nerve",
        "muscle",
        "blood",
        "bone_marrow",
        "pancreas",
        "adrenal_gland",
        "pituitary",
        "thyroid",
        "vasculature",
        # "spleen": HELD — see module docstring (pending review).
    }
)

# The endocrine / vascular / CNS organs whose ABSENCE from a source's essential set WAS the S1-3
# safety false-negative. The CI guard REQUIRES every source that can represent one of these to
# include it (the load-bearing safety invariant this module exists to enforce).
S1_3_REQUIRED_ORGANS = frozenset({"adrenal_gland", "pituitary", "thyroid", "vasculature", "brain"})

# --- Per-source crosswalks: canonical organ -> that source's native tissue name (None if the
#     organ is not representable in the source's vocabulary). ---

# recount3 / GTEx `tissue` column (UPPERCASE). All 14 canonical organs exist in the GTEx vocab.
# vasculature -> BLOOD_VESSEL (GTEx groups Artery-Aorta/Coronary/Tibial here; the old bare `ARTERY`
# was never a GTEx tissue label and silently never matched).
GTEX_CROSSWALK = {
    "heart": "HEART",
    "brain": "BRAIN",
    "liver": "LIVER",
    "lung": "LUNG",
    "kidney": "KIDNEY",
    "nerve": "NERVE",
    "muscle": "MUSCLE",
    "blood": "BLOOD",
    "bone_marrow": "BONE_MARROW",
    "pancreas": "PANCREAS",
    "adrenal_gland": "ADRENAL_GLAND",
    "pituitary": "PITUITARY",
    "thyroid": "THYROID",
    "vasculature": "BLOOD_VESSEL",
}

# HPA closed 16-name grouped-intensity vocabulary. None = no group for that organ (substrate gap).
HPA_CROSSWALK = {
    "heart": "heart muscle",
    "brain": "cerebral cortex",
    "liver": "liver",
    "lung": "lung",
    "kidney": "kidney",
    "pancreas": "pancreas",
    "bone_marrow": "bone marrow",
    "vasculature": "blood vessel",
    # Not in HPA's 16-name grouped-intensity field (data-substrate gap, NOT a list omission):
    "nerve": None,
    "muscle": None,
    "blood": None,
    "adrenal_gland": None,
    "pituitary": None,
    "thyroid": None,
}

# Single-cell normal-tissue ALWAYS-ON shard slug (must be a `TISSUE_TO_PRODUCT` key). None where the
# organ has no dedicated always-on single-cell normal shard. brain + adrenal_gland were promoted first
# (S1-3 CNS + endocrine holes); lung + pancreas promoted 2026-08-19 — a target expressed in normal
# pneumocytes (the ADC-pneumonitis organ) or pancreatic islet is a cross-indication safety liability
# previously visible only for NSCLC/PAAD (indication-matched). Safe to promote now that the sc-normal
# critical-organ arm produces a NAMED-organ liability FLAG (selective_with_normal_liability), not the
# blunt selective_but_broadly_normal kill (Phase S).
SC_NORMAL_CROSSWALK = {
    "heart": "heart",
    "liver": "liver",
    "kidney": "kidney",
    "bone_marrow": "bone_marrow",
    "brain": "brain",
    "adrenal_gland": "adrenal_gland",
    "lung": "lung",
    "pancreas": "pancreas",  # PROMOTED to always-on (pneumonitis / islet safety) 2026-08-19
    "nerve": None,
    "muscle": None,
    "blood": None,
    "pituitary": None,
    "thyroid": None,
    "vasculature": None,
}

# TPHP DIA-MS pan-tissue proteome `tissue` column (SDRF organism-part, lowercase). None = the organ
# has no organism-part in the 70-tissue adult TPHP panel. TPHP's value for SAFETY is that DIA-MS
# PROTEIN resolves the endocrine/vascular/CNS organs HPA-IHC's 16-name grouped field is BLIND to:
# it covers nerve / muscle / blood / adrenal_gland / thyroid (all None in HPA_CROSSWALK) and 4 of the
# 5 S1_3_REQUIRED_ORGANS (adrenal_gland, thyroid, vasculature, brain) — missing ONLY pituitary, which
# is absent from the TPHP panel (a data-substrate gap, like HPA's). Scalar convention (one
# representative organism-part per organ) matches GTEX/HPA/SC; muscle->skeletal muscle and
# vasculature->artery pick the canonical dose-limiting representative among TPHP's finer parts
# (smooth muscle / vein / lymph vessel also present but not the crosswalk anchor).
TPHP_CROSSWALK = {
    "heart": "heart",
    "brain": "brain",
    "liver": "liver",
    "lung": "lung",
    "kidney": "kidney",
    "nerve": "nerve",
    "muscle": "skeletal muscle",
    "blood": "blood",
    "bone_marrow": "bone marrow",
    "pancreas": "pancreas",
    "adrenal_gland": "adrenal gland",
    "thyroid": "thyroid gland",
    "vasculature": "artery",
    # Not in the 70-tissue adult TPHP panel (data-substrate gap, NOT a list omission):
    "pituitary": None,
}

# --- Derived per-source essential sets (what each card imports). ---
GTEX_ESSENTIAL_TISSUES = frozenset(v for v in GTEX_CROSSWALK.values() if v)
HPA_ESSENTIAL_TISSUES = frozenset(v for v in HPA_CROSSWALK.values() if v)
# order-stable list (sc-normal queries + de-dups against indication-matched tissues in insertion order)
SC_NORMAL_ESSENTIAL_TISSUES = [v for v in SC_NORMAL_CROSSWALK.values() if v]
TPHP_ESSENTIAL_TISSUES = frozenset(v for v in TPHP_CROSSWALK.values() if v)


def required_names(crosswalk: dict) -> set:
    """The source-native names a source MUST cover for the S1-3 safety invariant: every
    S1_3_REQUIRED_ORGANS organ that the source's vocabulary can represent (non-None crosswalk)."""
    return {crosswalk[o] for o in S1_3_REQUIRED_ORGANS if crosswalk.get(o)}
