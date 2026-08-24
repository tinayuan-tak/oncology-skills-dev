"""tumor-presence factored-record SHADOW builder (M1) — the FIRST no-resolver axis. Pins the
presence_verdict->record mapping, open-world/negative cases, fired-set cross-check, and schema
conformance (token-pattern only — the no-resolver invariant-C enum is an M3 item). Consumed-by-nothing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run as pr  # noqa: E402


def _fired(*rids):
    return [{"rule_id": r, "card_id": "tumor-rna-distribution"} for r in rids]


def test_upregulated_supports_measured_positive():
    rec = pr._claim_record([], fired=_fired("rna-strong-up"),
                           verdict_pair=("strongly_upregulated_in_tumor", "rna-strong-up"))
    assert rec["axis"] == "tumor_presence"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["provenance"]["fired_rule_ids"] == ["rna-strong-up"]


def test_downregulated_is_measured_negative_opposes():
    rec = pr._claim_record([], fired=[], verdict_pair=("strongly_downregulated_in_tumor", None))
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["finding"]["direction"] == "opposes"


def test_not_informative_is_underpowered():
    rec = pr._claim_record([], fired=[], verdict_pair=("not_informative", None))
    assert rec["finding"]["availability"] == "insufficient"


def test_data_unavailable_open_world():
    rec = pr._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["availability"] == "not_wired"
    assert f["state"] == "unknown" and f["direction"] == "neutral"


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
    for v in ("strongly_upregulated_in_tumor", "modestly_upregulated_in_tumor", "tumor_sparsely_expressed",
              "strongly_downregulated_in_tumor", "broadly_low_expression", "not_informative",
              "data_unavailable"):
        rec = pr._claim_record([], fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
