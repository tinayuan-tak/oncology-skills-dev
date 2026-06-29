"""compose-dashboard phase-1 validation: validate the emitted run_plan against
run_plan.schema.json from target-contracts."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ._resolution import TARGET_CONTRACTS


def validate_run_plan(run_plan: dict,
                       contracts_root: Path = TARGET_CONTRACTS) -> list[str]:
    """Validate a run_plan dict against run_plan.schema.json.

    Returns a list of error messages (empty if valid).
    """
    schema_path = contracts_root / "schemas" / "run_plan.schema.json"
    with schema_path.open() as f:
        schema = json.load(f)
    v = Draft202012Validator(schema)
    errors = []
    for e in v.iter_errors(run_plan):
        path_str = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"[{path_str}] {e.message}")
    return errors
