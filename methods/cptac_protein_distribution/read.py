"""Subtype-stratified CPTAC tumor-protein distribution reader + panorama composer."""

from __future__ import annotations

from typing import Optional

import numpy as np

from methods.subgroup_common.iteration import subgroup_iterable
from methods.subgroup_common.panorama import build_panorama, evidence_state, axis_quality, SUBGROUP_N_FLOOR

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
    target: str, indication: str, *, _sample_id_filter=None, cohort: Optional[str] = None
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
        "evidence_state": "absent",
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
        "evidence_state": evidence_state(n, floor_met),
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
        "source_cohort": rec["source_cohort"],
    }


def _classify_subtype_signal(median: Optional[float], pooled_median: Optional[float]) -> Optional[str]:
    if median is None or pooled_median is None:
        return None
    delta = median - pooled_median
    if delta >= 0.25:
        return "enriched"
    if delta <= -0.25:
        return "depleted"
    return "uniform"


def _subtype_rollup(records: list, pooled_median: Optional[float]) -> dict:
    measured = [r for r in records if r.get("evidence_state") == "measured"]
    for r in measured:
        r["subtype_signal"] = _classify_subtype_signal(r.get("median_log2_ratio"), pooled_median)
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
    return panorama
