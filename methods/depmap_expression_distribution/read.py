"""depmap_expression_distribution.read — library entry point for live-mode reads."""

from __future__ import annotations

from functools import lru_cache, partial
from typing import Optional

from . import cli as _cli

# Cell-line RNA subtype panorama (WS-C): DepMap driver-mutation / molecular-subtype stratification
# of the cell-line RNA distribution — the cell-line analogue of tumor-rna-distribution-by-subtype.
# Reuses the substrate-agnostic ModelID-keyed composer (subgroup_common.panorama.build_panorama),
# exactly as depmap_chronos.build_dependency_panorama does for dependency. DESCRIPTIVE / verdict-inert.
from methods.subgroup_common.iteration import subgroup_iterable
from methods.subgroup_common.panorama import (
    build_panorama, delta_reducer, evidence_state, SUBGROUP_N_FLOOR,
)
from methods.subgroup_common.scoping import resolve_subgroup_cohort

# DepMap log2(TPM+1) convention (mirrors cli.py).
_EXPRESSED = 1.0
_HIGHLY_EXPRESSED = 5.0
# A stratum median this many log2 units above/below the within-lineage pooled median is
# enriched/depleted (mirrors the tumor card's subtype_enrich_log2_delta threshold).
_SUBTYPE_ENRICH_LOG2_DELTA = 1.0


def read_expression_distribution(target: str, indication: Optional[str] = None,
                                  expressed_threshold: float = 1.0) -> Optional[dict]:
    """Compute pan-cancer expression distribution for target. Returns summary dict
    matching the cellline-rna-distribution card's outputs.summary_fields."""
    tpm_by_model, model_metadata, load_errors = _cli.load_expression_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q1 expression data.",
            "expression_class": "data_unavailable",
        }
    if not tpm_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "expression_class": "data_unavailable",
        }
    summary = _cli.compute_summary_stats(tpm_by_model, model_metadata,
                                         expressed_threshold=expressed_threshold)
    # All-gene percentile of the panel median (Phase 1C): where does this target's panel
    # median log2(TPM+1) sit among ALL ~19k protein-coding genes in the DepMap panel? A
    # single-gene predicate-pushdown lookup of the precomputed allgene-depmap-rank-26q1-v1
    # (NO re-scan of the wide matrix). Additive/display — never flips expression_class.
    try:
        from methods.allgene_percentile_precompute.lookup import depmap_allgene_percentile
        summary.update(depmap_allgene_percentile(target))
    except Exception:  # noqa: BLE001 — enrichment is best-effort; core summary stands
        summary.setdefault("allgene_percentile", None)
        summary.setdefault("allgene_percentile_class", "data_unavailable")
        summary.setdefault("allgene_percentile_context", None)
    # Control-benchmark position (Phase 2): where the panel-median percentile sits relative
    # to curated positive/negative control genes on the SAME pan-cancer panel scale. Additive/
    # display — never flips expression_class. Best-effort (vocab load / S3 failure → null).
    try:
        from methods.tumor_presence_controls.read import control_position_cellline
        summary.update(control_position_cellline(target))
    except Exception:  # noqa: BLE001
        summary.setdefault("control_position_class", "data_unavailable")
    return summary


# ---------------------------------------------------------------------------
# Cell-line RNA subtype panorama (WS-C) — DepMap driver-mutation stratification
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _cached_tpm(target: str, release_pin: str):
    """Load per-ModelID log2(TPM+1) for target ONCE per (target, release_pin); the panorama
    reader is called per-stratum by @subgroup_iterable, so cache the S3/parquet load."""
    tpm, _meta, errs = _cli.load_expression_files(release_pin, target)
    return (tpm or {}), bool(errs)


def _expression_class(median: Optional[float]) -> str:
    if median is None:
        return "insufficient"
    if median >= _HIGHLY_EXPRESSED:
        return "broadly_high"
    if median >= _EXPRESSED:
        return "broadly_detected"
    return "broadly_low"


@subgroup_iterable
def read_stratified_expression(target: str, indication: str, *,
                               _sample_id_filter=None, release_pin: str = "26q1") -> dict:
    """Per-subgroup cell-line RNA distribution of `target` across DepMap cell lines.

    DESCRIPTIVE panorama reader — the cell-line-expression analogue of
    depmap_chronos.read_stratified_dependency. Reads per-ModelID log2(TPM+1) and computes the
    within-stratum distribution over the subgroup's member ModelIDs (the DepMap-side assignments
    shard, already lineage-scoped by the assigner). Member-set intersection via `_sample_id_filter`.
    """
    import numpy as np
    tpm_by_model, errs = _cached_tpm(target, release_pin)
    if errs or not tpm_by_model:
        return {"target": target, "indication": indication, "subgroup_n": 0,
                "median_log2tpm": None, "fraction_expressed": None,
                "subgroup_n_floor_met": False, "evidence_state": "absent",
                "expression_class": "insufficient", "source_cohort": f"DepMap-{release_pin}",
                "_data_note": f"no DepMap {release_pin} expression for {target!r}"}
    if _sample_id_filter is not None:
        vals = [v for m, v in tpm_by_model.items() if m in _sample_id_filter]
    else:
        vals = list(tpm_by_model.values())
    scores = np.asarray(vals, dtype=float)
    n = int(scores.size)
    median = float(np.median(scores)) if n else None
    frac_expr = float((scores >= _EXPRESSED).mean()) if n else None
    floor_met = n >= SUBGROUP_N_FLOOR
    return {
        "target": target, "indication": indication,
        "subgroup_n": n,
        "median_log2tpm": (round(median, 4) if median is not None else None),
        "fraction_expressed": (round(frac_expr, 4) if frac_expr is not None else None),
        "subgroup_n_floor_met": floor_met,
        "evidence_state": evidence_state(n, floor_met),
        "expression_class": _expression_class(median),
        "source_cohort": f"DepMap-{release_pin}",
    }


def _expression_projection(stratum_id: str, rec: dict) -> dict:
    """Project a per-stratum expression record → the card's flat per_subgroup_metrics record.
    `subtype_signal` is filled by the post-pass (vs the within-lineage pooled median)."""
    return {
        "stratum": stratum_id,
        "class": rec["expression_class"],
        "evidence_state": rec["evidence_state"],
        "median_log2tpm": rec["median_log2tpm"],
        "fraction_expressed": rec["fraction_expressed"],
        "subgroup_n": rec["subgroup_n"],
        "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
        "subtype_defining_data": "genomic",
        "subtype_signal": None,
        "source_cohort": rec["source_cohort"],
    }


def _classify_subtype_signal(stratum_median: Optional[float],
                             pooled_median: Optional[float]) -> str:
    """enriched / depleted / uniform for one stratum vs the within-lineage pooled median."""
    if stratum_median is None or pooled_median is None:
        return "uniform"
    delta = stratum_median - pooled_median
    if delta >= _SUBTYPE_ENRICH_LOG2_DELTA:
        return "enriched"
    if delta <= -_SUBTYPE_ENRICH_LOG2_DELTA:
        return "depleted"
    return "uniform"


def _pooled_lineage_median(target: str, subgroups: list, manifest: str,
                           catalog_repo, release_pin: str) -> Optional[float]:
    """Within-lineage pooled median log2(TPM+1): the median over the UNION of all strata members
    (the lineage's assigned cell lines) — the baseline each stratum's enrichment is measured against."""
    import numpy as np
    tpm_by_model, errs = _cached_tpm(target, release_pin)
    if errs or not tpm_by_model:
        return None
    members: set = set()
    for sg in subgroups:
        try:
            members |= set(resolve_subgroup_cohort(manifest, sg, data_catalog_repo=catalog_repo) or [])
        except Exception:  # noqa: BLE001 — a missing stratum shard shouldn't sink the baseline
            continue
    vals = [v for m, v in tpm_by_model.items() if m in members]
    return float(np.median(vals)) if vals else None


def _subtype_rollup(records: list, pooled_median: Optional[float]) -> dict:
    """Annotate each record's subtype_signal vs the pooled median + compute cross-stratum scalars.
    subtype_stratification_class ∈ {subtype_enriched, subtype_depleted, subtype_variable,
    pan_subtype_uniform} — the display verdict tumor-presence surfaces (verdict-inert)."""
    measured = [r for r in records if r.get("evidence_state") == "measured"]
    for r in measured:
        r["subtype_signal"] = _classify_subtype_signal(r.get("median_log2tpm"), pooled_median)
    n_enriched = sum(1 for r in measured if r["subtype_signal"] == "enriched")
    n_depleted = sum(1 for r in measured if r["subtype_signal"] == "depleted")
    if n_enriched and n_depleted:
        strat = "subtype_variable"
    elif n_enriched:
        strat = "subtype_enriched"
    elif n_depleted:
        strat = "subtype_depleted"
    else:
        strat = "pan_subtype_uniform"
    spotlight = None
    enriched = [r for r in measured if r["subtype_signal"] == "enriched" and r.get("median_log2tpm") is not None]
    if enriched:
        spotlight = max(enriched, key=lambda r: r["median_log2tpm"])["stratum"]
    return {
        "subtype_axis_available": bool(records),
        "n_subtypes_measured": len(measured),
        "n_subtypes_enriched": n_enriched,
        "n_subtypes_depleted": n_depleted,
        "subtype_stratification_class": strat,
        "spotlight_subtype": spotlight,
        "pooled_lineage_median_log2tpm": (round(pooled_median, 4) if pooled_median is not None else None),
    }


def build_expression_subtype_panorama(target: str, indication: str, subgroups: list,
                                      subgroup_assignments_manifest: str,
                                      subgroup_catalog_repo=None,
                                      release_pin: str = "26q1") -> dict:
    """Assemble the cellline-rna-distribution-by-subtype card's per_subgroup_metrics panorama.

    Thin call into subgroup_common.panorama.build_panorama (same composer as the dependency
    panorama), then a post-pass classifies each stratum's subtype_signal vs the within-lineage
    pooled median and rolls up the cross-stratum scalars. DESCRIPTIVE / verdict-inert — emits no
    signals. subgroup_assignments_manifest MUST be the DepMap-side shard (cell-line ModelIDs),
    e.g. 'depmap-subgroup-assignments-coadread-v1'.
    """
    panorama = build_panorama(
        read_stratified_expression,
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
        record_projection=_expression_projection,
        reducer=partial(delta_reducer, metric_key="median_log2tpm", label="expression"),
        subgroup_catalog_repo=subgroup_catalog_repo,
        reader_kwargs={"release_pin": release_pin},
    )
    pooled = _pooled_lineage_median(target, subgroups, subgroup_assignments_manifest,
                                    subgroup_catalog_repo, release_pin)
    panorama.update(_subtype_rollup(panorama["per_subgroup_metrics"], pooled))
    panorama["_data_source"] = f"DepMap-{release_pin} expression (subgroup-stratified)"
    return panorama
