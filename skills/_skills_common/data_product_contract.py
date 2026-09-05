"""Shared helpers for the finalized emitted-output data-product contract (see docs/UNIFIED_OUTPUT_CONTRACT.md
and each skill's DATA_PRODUCT.md).

Every wired skill's per-skill emitted-output schema is generated + self-contained in target-contracts
(schemas/skills/<skill>.decision.schema.json). These helpers are the SINGLE place the per-skill tests
(tests/test_data_product_schema.py) and replay tests (test_<skill>_replay.py) load + validate against
that schema — imported as `_skills_common.data_product_contract` (works under any pytest import mode,
unlike a sibling-test import). Pure helpers: they do NOT call pytest.skip/fail — the test decides that,
so the CI-fail-not-skip policy stays in the test layer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEFAULT_TC = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"


def schema_path(skill: str) -> Path:
    root = Path(os.environ.get("TARGET_CONTRACTS_ROOT", _DEFAULT_TC))
    return root / "schemas" / "skills" / f"{skill}.decision.schema.json"


def load_schema(skill: str) -> dict | None:
    """The generated self-contained per-skill schema, or None if unresolvable."""
    p = schema_path(skill)
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
