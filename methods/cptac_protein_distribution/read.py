"""Subtype-stratified CPTAC tumor-protein distribution reader + panorama composer."""

from __future__ import annotations

from typing import Optional

import numpy as np

from methods.subgroup_common.iteration import subgroup_iterable
from methods.subgroup_common.panorama import (
    SUBGROUP_EXPLORATORY_FLOOR,
    SUBGROUP_N_FLOOR,
    axis_quality,
    build_panorama,
    evidence_state,
)

# indication -> the landed CPTAC subgroup-assignment shard. COADREAD only today (MSI_H/MSS from
# MMR-IHC). Absent -> subtype_axis_available:false (honest), mirroring the RNA-subtype allowlist.
INDICATION_TO_CPTAC_ASSIGNMENT_MANIFEST = {
    "COADREAD": "cptac-subgroup-assignments-coadread-v1",
    "COAD": "cptac-subgroup-assignments-coadread-v1",
    "READ": "cptac-subgroup-assignments-coadread-v1",
}
# indication -> CPTAC protein cohort tag in the per-sample product.
INDICATION_TO_CPTAC_COHORT = {"COADREAD": "COAD", "COAD": "COAD", "READ": "COAD"}

# tumor-vs-reference log2-ratio bands (whole-cell-lysate TMT). Relative to the CPTAC common
# reference; >0 = elevated in tumor. Coarse presence-abundance class for display.
_ELEVATED = 0.5
_REDUCED = -0.5


def _protein_class(median: Optional[float]) -> str:
    if median is None:
        return "insufficient"
    if median >= _ELEVATED:
        return "protein_elevated"
    if median <= _REDUCED:
        return "protein_reduced"
    return "protein_neutral"


@subgroup_iterable
def read_stratified_protein(
    target: str,
    indication: str,
    *,
    _sample_id_filter=None,
    _stratum_evaluated: Optional[bool] = None,
    cohort: Optional[str] = None,
) -> dict:
    """Per-subgroup CPTAC tumor-protein distribution of `target` across the stratum's member aliquots.

    The CPTAC-protein analogue of depmap_expression_distribution.read_stratified_expression. Reads the
    per-aliquot tumor-vs-reference log2 ratios (cptac_protein_deg.read_per_sample), keeps the
    indication's cohort + tumor condition, and intersects with the stratum's member aliquots via
    `_sample_id_filter` (the CPTAC assignment shard). DESCRIPTIVE — no signal, no verdict."""
    from methods.cptac_protein_deg.read import read_per_sample

    cohort = cohort or INDICATION_TO_CPTAC_COHORT.get(indication.upper().strip())
    df = read_per_sample(target)
    empty = {
        "target": target,
        "indication": indication,
        "subgroup_n": 0,
        "median_log2_ratio": None,
        "detectable_fraction": None,
        "subgroup_n_floor_met": False,
        # Graded, not hardcoded: this template is returned BOTH when the stratum has no member
        # aliquots and when the CPTAC product/cohort is missing. In either case a stratum the
        # assigner never classified is an ABSTENTION, not the measured absence `absent` asserts.
        # Historical value preserved exactly when `_stratum_evaluated is None` (unstratified call).
        "evidence_state": evidence_state(0, False, evaluated=_stratum_evaluated),
        "protein_class": "insufficient",
        "source_cohort": f"CPTAC-{cohort}",
    }
    if df is None or df.empty or cohort is None:
        return empty
    df = df[df["cohort"].astype(str).str.upper() == cohort]
    if "condition" in df.columns:
        df = df[df["condition"].astype(str).str.contains("Tumor|Primary", case=False, na=False)]
    if _sample_id_filter is not None:
        df = df[df["aliquot_submitter_id"].isin(_sample_id_filter)]
    vals = df["log2_ratio"].dropna().astype(float).to_numpy()
    n = int(vals.size)
    if n == 0:
        return empty
    median = float(np.median(vals))
    floor_met = n >= SUBGROUP_N_FLOOR
    return {
        "target": target,
        "indication": indication,
        "subgroup_n": n,
        "median_log2_ratio": round(median, 4),
        "detectable_fraction": round(float(np.isfinite(vals).mean()), 4),
        "subgroup_n_floor_met": floor_met,
        # `evaluated=` is deliberately omitted: evidence_state consults it only at subgroup_n == 0
        # and the `n == 0` early return above makes n > 0 unreachable-otherwise here, so passing it
        # would be an inert argument. `exploratory_floor` is the live opt-in on this path.
        "evidence_state": evidence_state(n, floor_met, exploratory_floor=SUBGROUP_EXPLORATORY_FLOOR),
        "protein_class": _protein_class(median),
        "source_cohort": f"CPTAC-{cohort}",
    }


def _protein_projection(stratum_id: str, rec: dict) -> dict:
    """Per-stratum protein record -> flat per_subgroup_metrics record. subtype_signal filled post-pass."""
    return {
        "stratum": stratum_id,
        "class": rec["protein_class"],
        "evidence_state": rec["evidence_state"],
        "median_log2_ratio": rec["median_log2_ratio"],
        "detectable_fraction": rec["detectable_fraction"],
        "subgroup_n": rec["subgroup_n"],
        "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
        # Declared here, not only in the post-pass: the rollup writes these two onto `measured` rows
        # ONLY, so before this default an unmeasured stratum came back with the keys ABSENT while a
        # measured one had them present. A consumer reading `rec["subtype_signal"]` KeyErrors on the
        # first empty stratum, and `rec.get("subtype_signal", "uniform")` returns its default only
        # for the absent case — i.e. the record shape itself encoded whether the row was measured.
        # Defaulting both to None makes the shape uniform and the null mean "no cut applied".
        "subtype_signal": None,
        "subtype_enrich_log2_delta": None,
        "source_cohort": rec["source_cohort"],
    }


# Per-stratum enrichment cutoff vs the pooled-cohort median, in log2 tumor-vs-reference RATIO units.
# NAMED 2026-09-18 (behaviour-neutral — the value is unchanged): this cut used to be an inline literal
# repeated at both comparison sites below, so it was the one arm of the three whose `enriched` threshold
# had NO symbol to grep for. tumor-protein-distribution-by-subtype.card.yaml now declares it in
# `thresholds:` with a `threshold_roles` entry naming this method as the consumer (TC#811), and that
# declaration is only auditable if the value is named here.
# ⚠️ Do NOT confuse this with _ELEVATED / _REDUCED above: those are the DISPLAY class bands
# (protein_elevated / protein_neutral / protein_reduced), NOT the enrichment cut. They differ (0.5 vs
# 0.25), so a name-based search for "the protein threshold" that lands on _ELEVATED is wrong by 2x.
# ⚠️ NOT comparable to the RNA arms' cut: 0.585 (tumor) and 1.0 (cell line) are deltas of a
# log2(TPM+1) MEDIAN, while this is a delta of a tumor-vs-reference log2 RATIO — different measurand,
# so the three values must never be "aligned" to each other.
_SUBTYPE_ENRICH_LOG2_DELTA = 0.25


def _classify_subtype_signal(median: Optional[float], pooled_median: Optional[float]) -> Optional[str]:
    if median is None or pooled_median is None:
        return None
    delta = median - pooled_median
    if delta >= _SUBTYPE_ENRICH_LOG2_DELTA:
        return "enriched"
    if delta <= -_SUBTYPE_ENRICH_LOG2_DELTA:
        return "depleted"
    return "uniform"


def _subtype_rollup(records: list, pooled_median: Optional[float]) -> dict:
    measured = [r for r in records if r.get("evidence_state") == "measured"]
    for r in measured:
        r["subtype_signal"] = _classify_subtype_signal(r.get("median_log2_ratio"), pooled_median)
        # The cutoff ACTUALLY APPLIED to produce that call (card: tumor-protein-distribution-by-
        # subtype, TC#811). Cross-arm comparability is the whole point: `enriched` means 0.25 of a
        # tumor-vs-reference log2 RATIO here, 0.585 of a log2(TPM+1) median shift on the tumour RNA
        # arm and 1.0 on the cell-line RNA arm — three cuts differing in value AND in units, and
        # previously discoverable nowhere in the emitted record. Emitting the applied value lets a
        # consumer normalise (or decline to join) WITHOUT moving any cut.
        # The gate is the SIGNAL, not the medians, and that is exact rather than a convenience:
        # _classify_subtype_signal returns None precisely when a median is missing, so `is not None`
        # means "a comparison ran". NOTE the asymmetry with the two RNA arms, whose classifiers fall
        # THROUGH to "uniform" on a missing median and therefore have to re-test the medians here.
        if r["subtype_signal"] is not None:
            r["subtype_enrich_log2_delta"] = _SUBTYPE_ENRICH_LOG2_DELTA
    n_enr = sum(1 for r in measured if r.get("subtype_signal") == "enriched")
    n_dep = sum(1 for r in measured if r.get("subtype_signal") == "depleted")
    if n_enr and n_dep:
        strat = "subtype_variable"
    elif n_enr:
        strat = "subtype_enriched"
    elif n_dep:
        strat = "subtype_depleted"
    else:
        strat = "pan_subtype_uniform"
    return {
        "subtype_axis_available": bool(records),
        "subtype_axis_quality": axis_quality(records),
        "n_subtypes_measured": len(measured),
        "n_subtypes_enriched": n_enr,
        "n_subtypes_depleted": n_dep,
        "subtype_stratification_class": strat,
        "pooled_cohort_median_log2_ratio": (round(pooled_median, 4) if pooled_median is not None else None),
    }


def build_protein_subtype_panorama(
    target: str,
    indication: str,
    subgroups: list,
    subgroup_assignments_manifest: Optional[str] = None,
    subgroup_catalog_repo=None,
) -> dict:
    """Assemble the tumor-protein-distribution-by-subtype panorama. Thin call into build_panorama
    (same composer as the RNA subtype + dependency panoramas). Honest subtype_axis_available:false
    when the indication has no landed CPTAC assignment shard."""
    ind = indication.upper().strip()
    manifest = subgroup_assignments_manifest or INDICATION_TO_CPTAC_ASSIGNMENT_MANIFEST.get(ind)
    cohort = INDICATION_TO_CPTAC_COHORT.get(ind)
    if manifest is None:
        return {
            "target": target,
            "indication": indication,
            "per_subgroup_metrics": [],
            "subtype_axis_available": False,
            "subtype_axis_quality": "unavailable",
            "n_subtypes_measured": 0,
            "n_subtypes_enriched": 0,
            "n_subtypes_depleted": 0,
            "subtype_stratification_class": "subtype_axis_unavailable",
            # Explicit null, NOT the stamp: no shard was resolved on this path, so there is nothing
            # to attest. The key is still present so the record shape does not vary by path.
            "assignment_manifest": None,
            "_subtype_note": "no landed CPTAC subgroup-assignment shard for this indication",
        }
    # pooled cohort median (the enrichment baseline) — all tumor aliquots, no stratum filter
    pooled_rec = read_stratified_protein(target, indication, cohort=cohort)
    pooled_median = pooled_rec.get("median_log2_ratio")
    panorama = build_panorama(
        read_stratified_protein,
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=manifest,
        record_projection=_protein_projection,
        reducer=lambda records: {},  # rollup applied below (needs the pooled baseline)
        subgroup_catalog_repo=subgroup_catalog_repo,
        reader_kwargs={"cohort": cohort},
    )
    panorama.update(_subtype_rollup(panorama["per_subgroup_metrics"], pooled_median))
    # Reader-side stamp of the RESOLVED shard, mirroring the tumour RNA arm (which has always emitted
    # it) and the cell-line arm (stamped in this same change). `manifest` is the value the read
    # actually used — either the caller's override or the INDICATION_TO_* fallback — so this attests
    # the substrate rather than re-resolving it. envelope.py::_refine_product_id_staleness reports
    # staleness as INDETERMINATE for want of exactly this stamp: a card may pin several candidate
    # shards, so without it the envelope cannot tell WHICH one a given run read.
    panorama["assignment_manifest"] = manifest
    return panorama
