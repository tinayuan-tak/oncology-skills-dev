"""mechanism-and-pharmacology factored-record SHADOW (M1) — descriptive characterization axis.
Understanding supports; minimal coverage-only certainty. Consumed-by-nothing / verdict-inert."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")


def _fired(*rids):
    return [{"rule_id": r, "card_id": "mechanism-of-action"} for r in rids]


def test_well_characterized_supports_strong():
    rec = me._claim_record(
        [], fired=_fired("moa-well-characterized"), verdict_pair=("well_characterized", "moa-well-characterized")
    )
    assert rec["axis"] == "mechanism"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["provenance"]["fired_rule_ids"] == ["moa-well-characterized"]


def test_moa_classes_populate_mechanism_coordinate():
    cards = [
        {
            "card_id": "signaling-network-mechanism",
            "summary": {"moa_classes_present": ["kinase", "transcription_factor"]},
        }
    ]
    rec = me._claim_record(
        cards, fired=_fired("moa-well-characterized"), verdict_pair=("well_characterized", "moa-well-characterized")
    )
    assert rec["mechanism"]["classes"] == ["kinase", "transcription_factor"]  # WHY on the chart


def test_no_mechanism_block_when_moa_absent():
    rec = me._claim_record([], fired=[], verdict_pair=("sparse", None))
    assert "mechanism" not in rec  # empty MoA → no fabricated block


def test_data_unavailable_open_world():
    rec = me._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    assert rec["finding"]["availability"] == "not_wired"
    assert rec["finding"]["state"] == "unknown" and rec["finding"]["direction"] == "neutral"


def _schema():
    try:
        from _skills_common.scope import DEFAULT_CONTRACTS_REPO
        from jsonschema import Draft202012Validator  # noqa: F401
    except Exception:
        return None
    p = Path(DEFAULT_CONTRACTS_REPO) / "schemas" / "claim_record.schema.json"
    return json.loads(p.read_text()) if p.exists() else None


def test_conforms_to_contract_schema_if_available():
    schema = _schema()
    if schema is None:
        pytest.skip("contracts schema not available")
    from jsonschema import Draft202012Validator

    for v in ("well_characterized", "has_pd_marker", "partial", "sparse", "insufficient", "data_unavailable"):
        rec = me._claim_record([], fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
