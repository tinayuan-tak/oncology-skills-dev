"""Genomic-alteration / functional-state / phospho figure emitters.

Part of the _skills_common figure-emitter package (rehomed off the retired compose-dashboard, #654) (Stage-4 split of the monolith).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — type hints (stringized by future-annotations)

from ._common import (  # shared emitter helpers/constants
    TARGET_CONTRACTS,
    _ensure_methods_path,
    _has_live_read_error,
)


def _emit_alteration_role(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the alteration-role evidence card (typed driver classification): the role call +
    the OncoKB/IntOGen evidence it rests on. Gated on alteration_role (data_unavailable → []).
    On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("alteration_role") in (None, "data_unavailable"):
        return []
    _ensure_methods_path()
    from onc_methods.driver_role_overlay import cli as dro

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = dro.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "alteration_role_evidence_card",
            "path": "figure_alteration_role.svg",
            "type": "alteration_role_evidence_card",
            "primary": True,
        },
    ]


def _emit_functional_gene_state(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the functional-gene-state figure (M6): per-arm STACKED composition of the two-hit
    states (patient vs model — wt / monoallelic / biallelic-genetic / uncertain). Gated on the
    presence of at least one arm's state distribution (both data_unavailable → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    # both arms must be structured-absent for the figure to be skipped; else there is a bar to draw.
    patient = summary.get("patient") or {}
    model = summary.get("model") or {}
    if not (patient.get("state_counts") or model.get("state_counts")):
        return []
    _ensure_methods_path()
    from onc_methods.functional_gene_state import cli as fgs

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = fgs.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "functional_gene_state_stacked_bar",
            "path": "figure_functional_gene_state.svg",
            "type": "functional_gene_state_stacked_bar",
            "primary": True,
        },
    ]


def _emit_genomic_event_model_match(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the genomic-event-model-match figure (M11): the tumor event being matched + the
    correspondence class + top genotype-matched models. Gated on having matched models with a real
    correspondence class (data_unavailable / no_target_event with no models → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("event_correspondence_class")
    matched = summary.get("matched_models") or []
    if cls in (None, "data_unavailable", "no_target_event") and not matched:
        return []
    _ensure_methods_path()
    from onc_methods.genomic_event_model_match import cli as gemm

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = gemm.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "genomic_event_model_match_card",
            "path": "figure_genomic_event_model_match.svg",
            "type": "genomic_event_model_match_card",
            "primary": True,
        },
    ]


def _emit_abundance_dependency(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the abundance-dependency figure (Q7): protein-abundance→dependency class + correlation
    stats. Gated on a computed correlation (data_unavailable / insufficient / no-r → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("abundance_dependency_class")
    if (
        cls in (None, "data_unavailable", "insufficient_paired_models")
        or summary.get("protein_dependency_pearson_r") is None
    ):
        return []
    _ensure_methods_path()
    from onc_methods.abundance_dependency import cli as ad

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = ad.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "abundance_dependency_card",
            "path": "figure_abundance_dependency.svg",
            "type": "abundance_dependency_card",
            "primary": True,
        },
    ]


def _emit_phospho_pathway_activity(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the phospho-pathway-activity figure (Q8): activity class + top phosphosites. Gated on the
    target having detected phosphosites (phospho_not_detected / data_unavailable → nothing to plot → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("phospho_activity_class")
    if cls in (None, "data_unavailable", "phospho_not_detected"):
        return []
    _ensure_methods_path()
    from onc_methods.phospho_pathway_activity import cli as ppa

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = ppa.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "phospho_pathway_activity_card",
            "path": "figure_phospho_pathway_activity.svg",
            "type": "phospho_pathway_activity_card",
            "primary": True,
        },
    ]
