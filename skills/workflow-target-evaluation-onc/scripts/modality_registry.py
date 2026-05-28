"""Modality class registry loader.

Pure-data loader for `configs/modality_classes.yaml`. Resolves user-facing
modality strings (e.g. "Molecular Glue") to canonical class IDs (e.g.
"degrader") and looks up Phase 3 tox rules per class. Contains no scoring
logic — that lives in `phase3_dispatcher.py`.

Used by:
  - phase3_dispatcher.apply_phase3_rule (engine-internal)
  - scoring_engine.evaluate_target (records modality in audit trail)
  - {disease}_comprehensive_analysis.compute_subgroup_suitability (Phase 3)
  - generate_target_report_pdf (footer text comes from registry notes)
  - {disease}_protein_analysis (validates subcellular vs declared modality)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "configs" / "modality_classes.yaml"


@dataclass(frozen=True)
class ModalityClass:
    """Resolved modality class — what the dispatcher consumes."""
    class_id: str            # canonical class ID, e.g. "degrader"
    phase3_tox_rule: str     # rule name, e.g. "expression_floor_only"
    expression_floor_rna: float
    expression_floor_protein: str | None
    requires_surface_localization: bool
    safety_flags: list[str]
    primary_evidence: list[str]
    description: str
    notes: str


class ModalityRegistry:
    """Loads and queries the modality_classes.yaml registry."""

    def __init__(self, registry_path: Path | None = None) -> None:
        path = registry_path or DEFAULT_REGISTRY_PATH
        with open(path) as f:
            self._raw = yaml.safe_load(f)
        self._classes: dict[str, dict[str, Any]] = self._raw["modality_classes"]
        self._rules: dict[str, dict[str, Any]] = self._raw["phase3_tox_rules"]
        self._defaults: dict[str, Any] = self._raw["defaults"]
        self._subcellular: dict[str, list[str]] = self._raw["subcellular_to_classes"]

        # Build alias → class_id index for fuzzy resolution.
        self._alias_index: dict[str, str] = {}
        for cid, cfg in self._classes.items():
            self._alias_index[cid.lower()] = cid
            for alias in cfg.get("aliases", []):
                self._alias_index[alias.lower()] = cid

    @property
    def version(self) -> str:
        return self._raw.get("version", "unknown")

    def resolve_class(self, modality: str | None) -> str:
        """Resolve a user-supplied modality string to a canonical class_id.

        Matching is case-insensitive and substring-tolerant: "Molecular Glue",
        "molecular glue", "PROTAC", "TPD" all → "degrader".

        Returns the default class (antibody_naked) for None or unrecognized
        input. Use `is_known_modality()` to detect the unknown case.
        """
        if not modality:
            return self._defaults["unknown_modality_class"]
        m = modality.strip().lower()
        if m in self._alias_index:
            return self._alias_index[m]
        # Substring fallback: "Selective CRBN-binding small-molecule molecular
        # glue or PROTAC" should still resolve to degrader.
        for alias_lc, cid in self._alias_index.items():
            if alias_lc in m:
                return cid
        return self._defaults["unknown_modality_class"]

    def is_known_modality(self, modality: str | None) -> bool:
        """True if the modality string is recognized (no fallback)."""
        if not modality:
            return False
        m = modality.strip().lower()
        if m in self._alias_index:
            return True
        return any(alias_lc in m for alias_lc in self._alias_index)

    def get_class(self, class_id: str) -> ModalityClass:
        """Return the resolved ModalityClass record for `class_id`."""
        if class_id not in self._classes:
            raise KeyError(f"Unknown modality class_id: {class_id!r}")
        cfg = self._classes[class_id]
        floor = cfg.get("expression_floor", {})
        return ModalityClass(
            class_id=class_id,
            phase3_tox_rule=cfg["phase3_tox_rule"],
            expression_floor_rna=float(floor.get("rna_log2tpm", 0.0)),
            expression_floor_protein=floor.get("protein_ihc"),
            requires_surface_localization=cfg.get("requires_surface_localization", False),
            safety_flags=list(cfg.get("safety_flags", [])),
            primary_evidence=list(cfg.get("primary_evidence", [])),
            description=cfg.get("description", "").strip(),
            notes=cfg.get("notes", "").strip(),
        )

    def get_rule_config(self, rule_name: str) -> dict[str, Any]:
        """Return the raw rule config for a phase3_tox_rule name."""
        if rule_name not in self._rules:
            raise KeyError(f"Unknown phase3_tox_rule: {rule_name!r}")
        return self._rules[rule_name]

    def is_compatible_subcellular(self, class_id: str, location: str) -> bool:
        """Cross-check: is `class_id` valid for a target with this subcellular location?

        Returns True if no mapping exists for the location (don't block on
        unknown locations) — the registry's subcellular_to_classes covers
        the canonical HPA locations only.
        """
        compat = self._subcellular.get(location)
        if compat is None:
            return True
        return class_id in compat

    def list_classes(self) -> list[str]:
        return list(self._classes.keys())

    def list_rules(self) -> list[str]:
        return list(self._rules.keys())

    def all_aliases(self) -> dict[str, str]:
        """Read-only copy of the alias index (alias_lc → class_id)."""
        return dict(self._alias_index)
