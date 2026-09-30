"""Shared helpers for the finalized emitted-output data-product contract (see docs/UNIFIED_OUTPUT_CONTRACT.md
and each skill's DATA_PRODUCT.md).

Every wired skill's per-skill emitted-output schema is generated + self-contained in target-contracts.
Two flavours, selected by `suffix`:
  - `decision` (default) — the fan-out skill_decision envelope, GENERATED from pins:
    schemas/skills/<skill>.decision.schema.json
  - `emit` — HAND-AUTHORED bespoke contracts for AUX skills whose output is NOT the fan-out envelope
    (no run_health / headline.skill_report — e.g. target-archetype, cross-evidence-hypothesis,
    literature-risk-assessment): schemas/skills/<skill>.emit.schema.json

These helpers are the SINGLE place the per-skill tests (tests/test_data_product_schema.py) and replay
tests (test_<skill>_replay.py) load + validate against that schema — imported as
`_skills_common.data_product_contract` (works under any pytest import mode, unlike a sibling-test import).
Pure helpers: they do NOT call pytest.skip/fail — the test decides that, so the CI-fail-not-skip policy
stays in the test layer.
"""

from __future__ import annotations

import json
from pathlib import Path

from oncology_target_contracts.loader import contracts_root as _contracts_root


def schema_path(skill: str, suffix: str = "decision") -> Path:
    """Path to the per-skill schema. `suffix='decision'` (default) = the generated envelope schema;
    `suffix='emit'` = a hand-authored bespoke aux-skill emit schema."""
    # SK#2144 stage 3a: resolve the contracts tree through the packaged loader's single
    # resolution point instead of the duplicated _skills_common.paths helper. The per-skill
    # schema lives under schemas/skills/<skill>.<suffix>.schema.json — a layout the packaged
    # loader.load_schema does not cover — so the read stays here; only the ROOT is routed.
    # contracts_root() == target_contracts_root() (both honor $TARGET_CONTRACTS_ROOT, else
    # <checkout>/contracts); with no runtime mutation of that env its lru_cache is inert.
    root = _contracts_root()
    return root / "schemas" / "skills" / f"{skill}.{suffix}.schema.json"


def load_schema(skill: str, suffix: str = "decision") -> dict | None:
    """The self-contained per-skill schema, or None if unresolvable."""
    p = schema_path(skill, suffix)
    return json.loads(p.read_text()) if p.exists() else None


def conformance_errors(schema: dict, decision: dict) -> list:
    """Sorted jsonschema validation errors of `decision` against the self-contained `schema` (no registry)."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    return sorted(validator.iter_errors(decision), key=lambda e: list(e.path))


def is_full_decision(decision: dict) -> bool:
    """True when a fixture is a FULL emitted decision (has the shared envelope + a skill_report), vs a
    trimmed fixture (some goldens keep only skill/target/indication/headline/cards/fired_rules). A trimmed
    golden is not a valid conformance target — the fresh replay emit is (see each replay test)."""
    if not isinstance(decision, dict):
        return False
    if not {"provenance", "run_health", "generated_at"} <= set(decision):
        return False
    return isinstance((decision.get("headline") or {}).get("skill_report"), dict)
