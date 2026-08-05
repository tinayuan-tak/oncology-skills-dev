"""oncology_target_contracts — the governance-layer contracts as an installable package.

This repo is the framework's governance layer: evidence cards, interpretation rules,
per-gate resolvers, JSON schemas, controlled vocabularies, and dashboard specs. Those
artifacts are DATA (YAML/JSON); this package makes them reachable without a hardcoded
sibling-repo path, so downstream consumers (skills, analysis-methods) can locate and
load them whether the repo is cloned to the canonical location, cloned elsewhere (via
the TARGET_CONTRACTS_ROOT env var), or installed editable (`pip install -e .`).

Tier-1 packaging (2026-08-05): ADDITIVE. Existing consumers keep their current
env-var/path readers unchanged — this package is a new, parallel access path plus a
thin loader API. See `dev/tier1-packaging-scope.md` (skills repo) PR #2.

Public API:
    contracts_root()                -> Path to the contracts tree (resolved)
    load_card(card_id)              -> dict
    load_resolver(gate)             -> dict | None
    load_interpretation_rules(name) -> dict
    load_schema(name)               -> dict
    load_vocabulary(name)           -> dict
    load_dashboard_spec(name)       -> dict
    load_modality_module(modality)  -> dict
    iter_card_ids()                 -> list[str]

The `plot_styles` subpackage ships the shared figure palette (importable) + the
matplotlib style file (package data).
"""
from __future__ import annotations

from .loader import (
    contracts_root,
    load_card,
    load_resolver,
    load_interpretation_rules,
    load_schema,
    load_vocabulary,
    load_dashboard_spec,
    load_modality_module,
    iter_card_ids,
)

__all__ = [
    "contracts_root",
    "load_card",
    "load_resolver",
    "load_interpretation_rules",
    "load_schema",
    "load_vocabulary",
    "load_dashboard_spec",
    "load_modality_module",
    "iter_card_ids",
]

__version__ = "0.1.0"
