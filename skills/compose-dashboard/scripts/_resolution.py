"""compose-dashboard phase-1 resolution helpers.

Each function reads ONE artifact from target-contracts/ or data-catalog/ and returns
a structured dataclass. Side-effect-free; deterministic given the input filesystem.
"""

from __future__ import annotations
import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# Default repo paths — overridable for tests
TARGET_CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
DATA_CATALOG = Path(os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"))


@dataclass
class AxisResolution:
    """Output of biology_axis lookup for a target."""
    status: str                                # resolved | unknown | incompatible
    resolved_axis: str                          # the axis value (or 'unknown')
    lookup_source: str
    lookup_rationale: Optional[str] = None
    selected_base_dashboard: Optional[str] = None
    fallback_reason: Optional[str] = None


@dataclass
class ModalityResolution:
    """Output of modality-axis compatibility resolution."""
    mode: str                                   # user_specified | enumerated_plausible | not_applicable_axis_unresolved | incompatible_modality_for_axis
    user_specified_modality: Optional[str] = None
    plausible_modalities: list[str] = field(default_factory=list)
    compatibility_source: str = ""
    incompatibility_reason: Optional[str] = None


def load_target_biology_axis(target_symbol: str,
                              contracts_root: Path = TARGET_CONTRACTS) -> AxisResolution:
    """Look up a target's biology_axis from target_biology_axis_lookup.yaml.

    Returns AxisResolution with status:
      - resolved   → axis found, status=resolved, selected_base_dashboard set
      - unknown    → target not in lookup, status=unknown, fallback_reason populated
      - incompatible → axis found but iter-1b doesn't ship a base dashboard for it
        (extrinsic, mixed) → status=incompatible
    """
    lookup_path = contracts_root / "vocabularies" / "target_biology_axis_lookup.yaml"
    with lookup_path.open() as f:
        lookup = yaml.safe_load(f)

    # Match on hgnc_symbol primary or aliases
    target_upper = target_symbol.upper()
    matched_entry = None
    for entry in lookup.get("targets", []):
        if entry.get("hgnc_symbol", "").upper() == target_upper:
            matched_entry = entry
            break
        aliases = [a.upper() for a in entry.get("hgnc_symbol_aliases", [])]
        if target_upper in aliases:
            matched_entry = entry
            break

    if matched_entry is None:
        return AxisResolution(
            status="unknown",
            resolved_axis="unknown",
            lookup_source=str(lookup_path.relative_to(contracts_root.parent)),
            fallback_reason=(
                f"target {target_symbol!r} not in target_biology_axis_lookup.yaml; framework "
                f"cannot select a base dashboard until axis is curated. Add the target to the "
                f"lookup with a curated biology_axis assignment before proceeding."
            ),
        )

    axis = matched_entry.get("biology_axis", "unknown")

    # Map axis → base dashboard via biology_axis.enum.yaml
    axis_enum_path = contracts_root / "vocabularies" / "biology_axis.enum.yaml"
    with axis_enum_path.open() as f:
        axis_enum = yaml.safe_load(f)
    axis_entry = next((v for v in axis_enum["values"] if v["value"] == axis), None)

    if axis_entry is None:
        return AxisResolution(
            status="unknown",
            resolved_axis=axis,
            lookup_source=str(lookup_path.relative_to(contracts_root.parent)),
            fallback_reason=f"axis value {axis!r} not in biology_axis.enum.yaml; vocabulary mismatch.",
        )

    iter1b_status = axis_entry.get("iter1b_status")
    if iter1b_status != "active":
        return AxisResolution(
            status="incompatible",
            resolved_axis=axis,
            lookup_source=str(lookup_path.relative_to(contracts_root.parent)),
            lookup_rationale=matched_entry.get("rationale"),
            selected_base_dashboard=None,
            fallback_reason=(
                f"axis {axis!r} has iter1b_status={iter1b_status!r}: "
                f"{axis_entry.get('iter1b_deferred_reason', 'no iter-1b base dashboard available')}"
            ),
        )

    return AxisResolution(
        status="resolved",
        resolved_axis=axis,
        lookup_source=str(lookup_path.relative_to(contracts_root.parent)),
        lookup_rationale=matched_entry.get("rationale"),
        selected_base_dashboard=axis_entry.get("base_dashboard"),
    )


def resolve_modality(axis_resolution: AxisResolution,
                      user_modality: Optional[str],
                      contracts_root: Path = TARGET_CONTRACTS) -> ModalityResolution:
    """Determine which modality module(s) to load given the resolved axis and (optional) user input.

    Cases:
      - axis not resolved → mode=not_applicable_axis_unresolved
      - user specified modality + compatible with axis → mode=user_specified
      - user specified modality + incompatible with axis → mode=incompatible_modality_for_axis
      - no user modality + axis resolved → enumerate plausible_modalities_iter1b
    """
    compat_path = contracts_root / "vocabularies" / "modality_axis_compatibility.yaml"
    with compat_path.open() as f:
        compat = yaml.safe_load(f)
    compat_source = str(compat_path.relative_to(contracts_root.parent))

    if axis_resolution.status != "resolved":
        return ModalityResolution(
            mode="not_applicable_axis_unresolved",
            user_specified_modality=user_modality,
            compatibility_source=compat_source,
            incompatibility_reason="axis not resolved; cannot determine plausible modalities",
        )

    axis = axis_resolution.resolved_axis
    axis_compat = compat["axis_compatibility"].get(axis)
    if axis_compat is None:
        return ModalityResolution(
            mode="incompatible_modality_for_axis",
            user_specified_modality=user_modality,
            compatibility_source=compat_source,
            incompatibility_reason=f"axis {axis!r} not in modality_axis_compatibility.yaml",
        )

    plausible = axis_compat.get("plausible_modalities_iter1b", []) or []

    if user_modality is not None:
        if user_modality in plausible:
            return ModalityResolution(
                mode="user_specified",
                user_specified_modality=user_modality,
                plausible_modalities=[user_modality],
                compatibility_source=compat_source,
            )
        # incompatible — but record what WAS plausible so the user can correct
        incompatible_list = axis_compat.get("incompatible_modalities", []) or []
        return ModalityResolution(
            mode="incompatible_modality_for_axis",
            user_specified_modality=user_modality,
            plausible_modalities=plausible,
            compatibility_source=compat_source,
            incompatibility_reason=(
                f"modality {user_modality!r} not in plausible_modalities_iter1b for axis "
                f"{axis!r}. Plausible: {plausible}. Incompatible (listed): {incompatible_list}."
            ),
        )

    # No user modality → enumerate all plausible
    return ModalityResolution(
        mode="enumerated_plausible",
        plausible_modalities=plausible,
        compatibility_source=compat_source,
    )


def load_dashboard_spec(dashboard_id: str,
                        contracts_root: Path = TARGET_CONTRACTS) -> dict:
    """Load a dashboard_spec by dashboard_id. Looks under target-contracts/dashboards/."""
    candidates = list((contracts_root / "dashboards").glob(f"{dashboard_id}.dashboard_spec.yaml"))
    if not candidates:
        raise FileNotFoundError(
            f"No dashboard_spec found for dashboard_id={dashboard_id!r} under "
            f"{contracts_root / 'dashboards'}"
        )
    with candidates[0].open() as f:
        return yaml.safe_load(f)


def load_modality_module(modality: str, contracts_root: Path = TARGET_CONTRACTS) -> dict:
    """Load a modality_module YAML by modality name."""
    module_path = contracts_root / "dashboards" / "modality-modules" / f"{modality}.module.yaml"
    if not module_path.exists():
        raise FileNotFoundError(
            f"No modality_module found at {module_path}. Modality {modality!r} may be deferred."
        )
    with module_path.open() as f:
        return yaml.safe_load(f)


def load_card_spec(card_id: str, contracts_root: Path = TARGET_CONTRACTS) -> tuple[dict, Path]:
    """Load a card_spec by card_id; returns (spec_dict, path)."""
    candidates = list((contracts_root / "cards").glob(f"{card_id}.card.yaml"))
    if not candidates:
        raise FileNotFoundError(f"No card_spec found for card_id={card_id!r}")
    path = candidates[0]
    with path.open() as f:
        return yaml.safe_load(f), path


def resolve_subgroup_catalog(indication: str,
                              subgroup_spec: object,
                              catalog_root: Path = DATA_CATALOG) -> dict:
    """Resolve which subgroup_catalog to load + which strata are in scope.

    Returns dict with keys:
      subgroup_catalog_ref: str | None
      catalog_status: resolved_active | not_requested | not_available_for_indication | uncurated
      resolved_strata_ids: list[str]
      applicable_data_sources: list[str]
    """
    if subgroup_spec is None:
        return {
            "subgroup_catalog_ref": None,
            "catalog_status": "not_requested",
            "resolved_strata_ids": [],
            "applicable_data_sources": [],
        }

    catalog_dir = catalog_root / "subgroup-catalogs" / indication
    if not catalog_dir.exists():
        return {
            "subgroup_catalog_ref": None,
            "catalog_status": "not_available_for_indication",
            "resolved_strata_ids": [],
            "applicable_data_sources": [],
        }

    candidates = sorted(catalog_dir.glob("*.yaml"))
    if not candidates:
        return {
            "subgroup_catalog_ref": None,
            "catalog_status": "uncurated",
            "resolved_strata_ids": [],
            "applicable_data_sources": [],
        }

    with candidates[-1].open() as f:
        catalog = yaml.safe_load(f)

    atomic_strata = catalog.get("atomic_strata", [])
    all_strata_ids = [s["id"] for s in atomic_strata]

    if subgroup_spec == "all":
        resolved = all_strata_ids
    elif isinstance(subgroup_spec, list):
        resolved = [s for s in subgroup_spec if s in all_strata_ids]
    else:
        resolved = []

    applicable_sources = sorted({
        src
        for s in atomic_strata
        if s["id"] in resolved
        for src in s.get("applicable_data_sources", [])
    })

    return {
        "subgroup_catalog_ref": catalog.get("id"),
        "catalog_status": "resolved_active",
        "resolved_strata_ids": resolved,
        "applicable_data_sources": applicable_sources,
    }
