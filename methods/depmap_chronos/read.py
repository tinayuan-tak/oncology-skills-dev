"""depmap_chronos.read — library entry point for live-mode reads (Card 2).

Exposes a single function `read_lineage_selectivity(target, indication)` that
returns the summary dict for the dependency-lineage-selectivity card. Reuses the
loader + compute helpers from cli.py rather than duplicating them — matches the
canonical pattern established by Card 1 (methods/depmap_chronos_distribution).

When the underlying DepMap data is unreachable (no local cache + no AWS creds),
returns a dict with `_live_read_error` key; the orchestrator's live-stub-fallback
mode then falls back to the stub fixture.

This function does NOT emit figures or plot_data; it returns scalars only. For
full card emission (with SVGs + parquet), the framework's figure-emission
registry (skills/compose-dashboard/scripts/_figure_emitters.py) re-invokes the
cli's emit_* helpers separately. Same code path the unit tests exercise.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Optional

from . import cli as _cli
from methods.subgroup_common.iteration import subgroup_iterable
from methods.subgroup_common.panorama import (
    SUBGROUP_N_FLOOR,
    build_panorama,
    delta_reducer,
    evidence_state,
)

DEFAULT_AWS_PROFILE = "cbg"

# Per-ModelID Chronos gene-effect matrix (the raw substrate for subgroup-
# stratified dependency). Columns are `SYMBOL (ENTREZ)`; index/col `ModelID`.
DEFAULT_CHRONOS_PARQUET = (
    Path.home() / ".cache" / "framework-depmap-26q1-parquet" / "CRISPRGeneEffect.parquet"
)

# Indication → DepMap OncotreeLineage mapping — the CANONICAL, single-source map.
# It is DEFINED as a literal in cli.py (the leaf module) and re-exported here as the
# SAME object (not a copy/fork), so `depmap_chronos.read.INDICATION_TO_DEPMAP_LINEAGE`
# stays the stable import name used by the 4 stratified-dependency readers + the
# lineage_ladder, while `depmap_chronos.cli.INDICATION_LINEAGE` is the identical object
# the display CLIs + pathway_node_leverage import. Single-sourcing is guarded by
# tests/methods/depmap_chronos/test_lineage_map_single_source.py. `_cli` is already
# imported above, so this is a plain re-export (no circular import — cli imports
# nothing from read).
INDICATION_TO_DEPMAP_LINEAGE = _cli.INDICATION_LINEAGE


from methods.target_id_sidecar import ensure_aws_profile


def read_lineage_selectivity(
    target: str,
    indication: str,
    strong_threshold: float = -1.0,
    moderate_threshold: float = -0.5,
) -> dict:
    """Compute lineage selectivity for a target in an indication's DepMap lineage.

    Delegates to cli.load_depmap_files + cli.compute_lineage_summary — same code
    paths the CLI and the figure-emission registry use. Returns the dict shape
    matching Card 2's outputs.summary_fields.

    On data-unreachable errors, returns a dict with `_live_read_error` key.
    """
    ensure_aws_profile()

    chronos_by_model, model_metadata, load_errors = _cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q1; verify local cache or AWS credentials.",
            # Tier-2 vocabulary: always emit enrichment_class so rules can fire on data_unavailable.
            "enrichment_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "target": target,
            "_remediation": f"target {target!r} not found in CRISPRGeneEffect.csv; confirm HGNC symbol.",
            "enrichment_class": "data_unavailable",
        }

    # `indication` accepted for back-compat with existing callers but NOT consumed
    # by the compute path. Card 2 is target-only per Decision 2A.
    return _cli.compute_lineage_summary(
        chronos_by_model, model_metadata, indication=indication,
        strong_threshold=strong_threshold,
        moderate_threshold=moderate_threshold,
    )


# ---- Subgroup-stratified dependency panorama (descriptive) ----------------

def _dependency_class(median_chronos: float | None,
                      strong: float = -1.0, moderate: float = -0.5) -> str:
    """Coarse dependency class for a subgroup (descriptive, not a verdict)."""
    if median_chronos is None:
        return "insufficient"
    if median_chronos <= strong:
        return "strong_dependency"
    if median_chronos <= moderate:
        return "moderate_dependency"
    return "not_dependent"


def _chronos_gene_column(columns, target: str) -> str | None:
    """Resolve the `SYMBOL (ENTREZ)` Chronos column for an HGNC symbol."""
    prefix = f"{target} ("
    for c in columns:
        if c == target or c.startswith(prefix):
            return c
    return None


@subgroup_iterable
def read_stratified_dependency(
    target: str,
    indication: str,
    chronos_parquet: Path | None = None,
    _sample_id_filter: set[str] | None = None,
) -> dict:
    """Per-subgroup CRISPR (Chronos) dependency of `target` across cell lines.

    DESCRIPTIVE panorama reader — the SECOND substrate proving the composer is
    substrate-agnostic (dependency, not mutation). Reads the per-ModelID Chronos
    matrix and computes median gene-effect within each subgroup's member-set
    (the DepMap-side assignments shard, already lineage-scoped by the assigner).

    Chronos gene-effect: ≤ -1.0 strong dependency, ≤ -0.5 moderate, > -0.5 not.
    Member-set intersection at read time via `_sample_id_filter` (ModelIDs).
    """
    import pandas as pd
    import numpy as np

    path = chronos_parquet or DEFAULT_CHRONOS_PARQUET
    if not path.exists():
        return {
            "target": target, "indication": indication,
            "subgroup_n": 0, "median_chronos": None, "n_strong_dependent": None,
            "subgroup_n_floor_met": False, "evidence_state": "absent",
            "dependency_class": "insufficient", "source_cohort": "DepMap-26Q1",
            "_data_note": f"No Chronos parquet at {path}.",
        }

    ce = pd.read_parquet(path)
    if "ModelID" in ce.columns:
        ce = ce.set_index("ModelID")
    col = _chronos_gene_column(ce.columns, target)
    if col is None:
        return {
            "target": target, "indication": indication,
            "subgroup_n": 0, "median_chronos": None, "n_strong_dependent": None,
            "subgroup_n_floor_met": False, "evidence_state": "absent",
            "dependency_class": "insufficient", "source_cohort": "DepMap-26Q1",
            "_data_note": f"{target!r} not a Chronos column.",
        }

    gene = ce[col].dropna()
    if _sample_id_filter is not None:
        gene = gene[gene.index.isin(_sample_id_filter)]

    n = int(gene.shape[0])
    median = float(gene.median()) if n else None
    n_strong = int((gene <= -1.0).sum()) if n else None
    floor_met = n >= SUBGROUP_N_FLOOR
    return {
        "target": target,
        "indication": indication,
        "subgroup_n": n,
        "median_chronos": (round(median, 4) if median is not None else None),
        "n_strong_dependent": n_strong,
        "subgroup_n_floor_met": floor_met,
        "evidence_state": evidence_state(n, floor_met),
        "dependency_class": _dependency_class(median),
        "source_cohort": "DepMap-26Q1",
    }


def _dependency_projection(stratum_id: str, rec: dict) -> dict:
    """Project a per-stratum dependency record → the card's flat record."""
    return {
        "stratum": stratum_id,
        "class": rec["dependency_class"],
        "evidence_state": rec["evidence_state"],
        "median_chronos": rec["median_chronos"],
        "n_strong_dependent": rec["n_strong_dependent"],
        "subgroup_n": rec["subgroup_n"],
        "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
        "subtype_defining_data": "genomic",
        "source_cohort": rec["source_cohort"],
    }


def build_dependency_panorama(
    target: str,
    indication: str,
    subgroups: list[str],
    subgroup_assignments_manifest: str,
    subgroup_catalog_repo: Path | str | None = None,
    chronos_parquet: Path | None = None,
) -> dict:
    """Assemble the dependency card's per_subgroup_metrics panorama.

    Thin call into subgroup_common.panorama.build_panorama — same composer as the
    mutation-frequency panorama, different substrate. Descriptive; emits no signals.
    The subgroup_assignments_manifest MUST be the DepMap-side shard (cell-line
    ModelIDs), e.g. 'depmap-subgroup-assignments-coadread-v1'.
    """
    panorama = build_panorama(
        read_stratified_dependency,
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
        record_projection=_dependency_projection,
        reducer=partial(delta_reducer, metric_key="median_chronos", label="dependency"),
        subgroup_catalog_repo=subgroup_catalog_repo,
        reader_kwargs={"chronos_parquet": chronos_parquet},
    )
    panorama["_data_source"] = "DepMap-26Q1 Chronos (subgroup-stratified)"
    return panorama
