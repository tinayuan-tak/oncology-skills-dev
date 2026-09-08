"""differentiation-landscape factored-record SHADOW builder (M1) — DESCRIPTIVE axis (pattern TYPE,
neutral valence). Pins direction always neutral, the availability mapping, open-world, fired-set
cross-check, and schema conformance. Consumed-by-nothing / verdict-inert."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

diff = load_run_py(Path(__file__).resolve().parent.parent, "diff_run_claim_shadow")


def _cards(n_pairs=80):
    return [{"card_id": "co-mutation-and-mutual-exclusivity", "summary": {"n_pairs_panel_intersect_eligible": n_pairs}}]


def _fired(*rids):
    return [{"rule_id": r, "card_id": "co-mutation-and-mutual-exclusivity"} for r in rids]


def test_pattern_is_measured_positive_but_neutral_valence():
    rec = diff._claim_record(
        _cards(), fired=_fired("strong-cooccurring"), verdict_pair=("strong_cooccurring", "strong-cooccurring")
    )
    assert rec["axis"] == "differentiation"
    assert rec["finding"]["direction"] == "neutral"  # pattern TYPE — never pushes nomination
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["provenance"]["fired_rule_ids"] == ["strong-cooccurring"]


def test_ns_is_measured_negative_still_neutral():
    rec = diff._claim_record(_cards(), fired=[], verdict_pair=("ns", None))
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["finding"]["direction"] == "neutral"


def test_data_unavailable_is_open_world():
    rec = diff._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
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
        pytest.skip("contracts repo / claim_record.schema.json not available")
    from jsonschema import Draft202012Validator

    for v in (
        "strong_cooccurring",
        "strong_mutually_exclusive",
        "both_patterns_present",
        "has_cooccurring_driver",
        "modest_cooccurring",
        "ns",
        "insufficient",
        "data_unavailable",
    ):
        rec = diff._claim_record(_cards(), fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
