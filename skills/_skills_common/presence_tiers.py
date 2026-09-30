"""Single source of truth for the tumor-presence abundance-tier ladder and the
n-power buckets (issue #1742).

Before this module the abundance ladder (median-log2TPM cuts and the all-gene
percentile cuts) was hard-coded in THREE places — ``presence_claims._claim_A``,
``presence_claims._tier_from_median`` and ``subgroup_derivation._stratum_tier`` —
and the n-power buckets in three more, with a rounded moderate cut (``3.46``) and
two *inconsistent* moderate n-floors (``20`` vs ``30``) that had drifted apart by
copy. Every one of those call sites now imports from here, so the ladder and the
buckets have exactly one definition.
"""

from __future__ import annotations

import math

# ── Abundance-tier ladder (median log2TPM) ─────────────────────────────────────
# Anchored to the upstream expression-distribution method
# (analysis-methods/onc_methods/tcga_gtex_expression_distribution/stats.py):
#   MODERATE_LOG2TPM = 3.4594  (= log2(11) ≈ TPM 10)  — the "moderate abundance" anchor.
# The presence ladder REUSES that moderate anchor and adds its own STRONG cut at
# log2TPM 5.0 (≈ TPM 31).
#
# NOTE the STRONG cut is DELIBERATELY DISTINCT from the upstream
#   HIGH_LOG2TPM = 5.6724  (= log2(51) ≈ TPM 50).
# The presence ladder's top band opens at TPM≈31, not at the upstream TPM≈50 —
# do not conflate the two. Only the *moderate* cut is shared with upstream.
#
# The moderate cut was previously written as a rounded ``3.46`` in all three
# copies; it is aligned to the exact upstream ``3.4594`` here. The [3.4594, 3.46)
# sliver is far below the precision of any realistic reported median, so this is a
# provenance cleanup, not a tier move.
ABUNDANCE_STRONG_LOG2TPM = 5.0
ABUNDANCE_MODERATE_LOG2TPM = 3.4594
# Below this a MEASURED median reads "absent" (undetectable) in the 4-tier variant.
ABUNDANCE_DETECTABLE_LOG2TPM = 1.0

# All-gene percentile cuts (same three tiers, percentile-scaled).
ABUNDANCE_STRONG_PCT = 95
ABUNDANCE_MODERATE_PCT = 75


def abundance_tier_from_median(med, *, absent_floor: bool = True):
    """strong / moderate / weak [/ absent] from a median log2TPM.

    Returns ``None`` when ``med`` is not a FINITE number (``None``/``nan``/``±inf``
    all read as "no usable median" — a non-finite median is not a measurement, so
    the caller should treat ``None`` as unmeasured).

    ``absent_floor=True`` (default) yields the 4-tier ladder: a measured-but-
    undetectable median below ``ABUNDANCE_DETECTABLE_LOG2TPM`` reads "absent".
    ``absent_floor=False`` yields the 3-tier ladder that bottoms out at "weak" —
    used by Claim A's raw-median branch, which has no detectable floor (it never
    mints "absent" off a bare median with no anchor).
    """
    if not isinstance(med, (int, float)) or not math.isfinite(med):
        return None
    if med >= ABUNDANCE_STRONG_LOG2TPM:
        return "strong"
    if med >= ABUNDANCE_MODERATE_LOG2TPM:
        return "moderate"
    if not absent_floor:
        return "weak"
    return "weak" if med >= ABUNDANCE_DETECTABLE_LOG2TPM else "absent"


def abundance_tier_from_percentile(pct):
    """strong / moderate / weak from an all-gene percentile, or ``None`` when
    ``pct`` is not a finite number."""
    if not isinstance(pct, (int, float)) or not math.isfinite(pct):
        return None
    if pct >= ABUNDANCE_STRONG_PCT:
        return "strong"
    if pct >= ABUNDANCE_MODERATE_PCT:
        return "moderate"
    return "weak"


# ── n-power buckets ────────────────────────────────────────────────────────────
# TWO INTENTIONALLY-DISTINCT moderate floors, keyed on measurement GRAIN. This
# difference is deliberate, not incidental:
#
#   SUBGROUP_N_FLOOR = 30 — BULK sample-count grain. The n>=30 large-sample
#       convention for a bulk cohort; mirrors upstream
#       analysis-methods/onc_methods/subgroup_common/panorama.py SUBGROUP_N_FLOOR
#       (and skills/render-evidence-package copies the same 30). Governs the
#       per-stratum `powered` gate, the per-stratum power base, and the
#       tumor-RNA-distribution cardboard reliability (bulk tumor samples).
#
#   POWER_MODERATE_N = 20 — SINGLE-CELL-donor-group / generic-reader grain. A
#       single-cell "sample" is a DONOR / patient GROUP — a coarser, scarcer unit
#       than a bulk tumor sample — so the *descriptive* power tier opens "moderate"
#       at 20 donor groups. Raising it to 30 would strip the moderate tier from
#       most single-cell cards. Governs the generic subgroup power tier
#       (`_nbucket`) and the sc-celltype cardboard reliability (donor groups).
#
# The HIGH floor is 100 for BOTH grains; the generic 4-tier tier adds VERY_HIGH at
# 1e5. These upper floors do NOT diverge across call sites.
POWER_HIGH_N = 100
POWER_VERY_HIGH_N = 100_000
SUBGROUP_N_FLOOR = 30
POWER_MODERATE_N = 20


# ── Absence-emission power floors (issue #1743) ────────────────────────────────
# A MEASURED-ABSENCE call — single-cell `broadly_low`/`microenvironment_dominant`
# (Claim C) or breadth `not_tumor_elevated` (Claim D) — asserts a confident
# NEGATIVE. Under the codebase's gap!=absent discipline (claim_vector_core
# SIGNAL_ORD: unmeasured/underpowered -> None) such a negative must NOT be
# asserted from an under-powered study: too few donors/cells/cohorts cannot
# distinguish "measured and absent" from "barely looked". These floors gate
# absence emission at the CLAIM layer (presence_claims._claim_C/_claim_D) —
# defense-in-depth, since a stale or ungated headline could otherwise slip a
# confident measured-absence through.
#
# SINGLE-CELL malignant grain. MIN_RELIABLE_DONORS / MIN_MALIGNANT_CELLS_TOTAL
# mirror EXACTLY the upstream reader
#   analysis-methods/onc_methods/sc_tumor_expression_celltype/stats.py
# which emits `data_unavailable` when malignant n_donors < 5 OR total malignant
# cells < 100 (a cross-donor median resting on 1-2 donors, or a pooled cube with
# single-digit cells per donor, is a false-confidence call). The claim layer
# re-applies the SAME floor so the confident sc negative is reachable only when
# BOTH are satisfied.
MIN_RELIABLE_DONORS = 5
MIN_MALIGNANT_CELLS_TOTAL = 100

# BULK BREADTH grain — a COUNT of tumor cohorts/indications the breadth axis was
# tested over (NOT donors; a distinct, coarser unit). The minimum roster size
# before a confident `not_tumor_elevated` (elevated in NO tested cohort) may be
# asserted. Set to the MODERATE rung of _claim_D's existing n_tested
# corroboration ladder (>=5): below it the breadth-absent call rests on too few
# cohorts to distinguish "elevated nowhere" from "barely looked", so it reads
# `underpowered` instead.
BREADTH_ABSENCE_N_FLOOR = 5
