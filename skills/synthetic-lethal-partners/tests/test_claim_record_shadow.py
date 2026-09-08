"""synthetic-lethal-partners factored-record SHADOW (M1). An SL partner is an opportunity (supports);
its measured absence is neutral. Minimal coverage-only certainty. Consumed-by-nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

sl = load_run_py(Path(__file__).resolve().parent.parent, "sl_run_shadow")


def _fired(*rids):
    return [{"rule_id": r, "card_id": "synthetic-lethal-partners"} for r in rids]


def test_experimental_partner_supports_strong():
    rec = sl._claim_record(
        [], fired=_fired("sl-experimental"), verdict_pair=("has_experimental_sl_partner", "sl-experimental")
    )
    assert rec["axis"] == "synthetic_lethal_partners"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["provenance"]["fired_rule_ids"] == ["sl-experimental"]


def test_computational_partner_is_moderate():
    rec = sl._claim_record([], fired=[], verdict_pair=("has_computational_sl_partner", None))
    assert rec["finding"]["magnitude"]["level"] == "moderate"


def test_no_curated_is_measured_negative_but_neutral():
    rec = sl._claim_record([], fired=[], verdict_pair=("no_curated_sl_partner", None))
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["finding"]["direction"] == "neutral"  # absence of an SL opportunity is not a target-negative


def test_data_unavailable_open_world():
    rec = sl._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
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

    for v in (
        "has_experimental_sl_partner",
        "has_computational_sl_partner",
        "no_curated_sl_partner",
        "insufficient",
        "data_unavailable",
    ):
        rec = sl._claim_record([], fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
