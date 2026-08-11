"""T5 (2026-08-11 engineering review): per-card summary-schema validation at compose time.

DEVELOPMENT_GUIDELINES promised method outputs "validate against the method's per-method output
schema ... Drift fails compose-time validation" — but no such schemas existed and no validation ran.
This pins the opt-in gate: _validate_card_outputs validates a card's `summary` against
target-contracts/schemas/methods/<card_id>.summary.schema.json WHEN it exists (and skips when it
doesn't, so unschematized cards are unaffected).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts.compose_dashboard import _validate_card_outputs, _validate_summary  # noqa: E402

# Resolve the contracts root the SAME way _resolution.py does (env override → default), so these
# tests run against whichever checkout carries the summary schemas.
CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
))
_SCHEMA = CONTRACTS / "schemas" / "methods" / "dependency-lineage-selectivity.summary.schema.json"
_have_schema = _SCHEMA.exists()

pytestmark = pytest.mark.skipif(
    not _have_schema,
    reason="per-card summary schemas not present in this contracts checkout (opt-in T5)",
)


def _card(summary: dict) -> dict:
    return {
        "card_id": "dependency-lineage-selectivity", "card_version": "1.0.0",
        "validation_state": "pass", "summary": summary,
        "interpretation_call": "x",
        "provenance": {"method_calls": [], "input_manifest_ids": []},
    }


def test_valid_summary_passes():
    errs = _validate_card_outputs(
        [_card({"enrichment_class": "lineage_selective", "median_chronos_panel": -0.7,
                "_internal_extra": "allowed"})],
        contracts_root=CONTRACTS,
    )
    assert errs == [], f"valid summary should pass: {errs}"


def test_bad_enum_and_type_are_caught():
    errs = _validate_card_outputs(
        [_card({"enrichment_class": "NONSENSE", "median_chronos_panel": "not_a_number"})],
        contracts_root=CONTRACTS,
    )
    joined = " ".join(errs)
    assert any("summary card_id=dependency-lineage-selectivity" in e for e in errs)
    assert "NONSENSE" in joined and "not_a_number" in joined


def test_unschematized_card_is_not_validated():
    """A card_id with no summary schema on disk must produce no summary errors (opt-in)."""
    errs = _validate_summary("a-card-with-no-summary-schema-xyz", {"anything": 1}, CONTRACTS)
    assert errs == []


def test_generated_schemas_accept_their_stub_summaries():
    """Every generated summary schema must accept the real stub summary for its card (guards the
    generator against emitting a schema that rejects legitimate data)."""
    import yaml
    from jsonschema import Draft202012Validator
    methods_dir = CONTRACTS / "schemas" / "methods"
    fixtures = list((Path(__file__).resolve().parent / "fixtures" / "stubs").glob("*.yaml"))
    checked = 0
    for schema_path in methods_dir.glob("*.summary.schema.json"):
        cid = schema_path.name[: -len(".summary.schema.json")]
        schema = json.loads(schema_path.read_text())
        v = Draft202012Validator(schema)
        for fx in fixtures:
            doc = yaml.safe_load(fx.read_text()) or {}
            if cid in doc and isinstance(doc[cid], dict):
                errs = [e.message for e in v.iter_errors(doc[cid])]
                assert errs == [], f"{cid} schema rejects its stub in {fx.name}: {errs[:2]}"
                checked += 1
    assert checked > 0, "no (schema, stub) pairs checked — generator/fixtures wiring?"
