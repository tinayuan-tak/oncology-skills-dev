"""cis-feature-coherence factored-record SHADOW (M1) — descriptive coherence axis. Coherent-driver
supports; other patterns neutral. Minimal coverage-only certainty. Consumed-by-nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

cis = load_run_py(Path(__file__).resolve().parent.parent, "cis_run")


def _fired(*rids):
    return [{"rule_id": r, "card_id": "cis-coherence"} for r in rids]


def test_coherent_driver_supports():
    rec = cis._claim_record([], fired=_fired("cis-coherent"), verdict_pair=("coherent_cis_driver", "cis-coherent"))
    assert rec["axis"] == "cis_coherence"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "moderate"
    assert rec["provenance"]["fired_rule_ids"] == ["cis-coherent"]


def test_uncoupled_is_neutral_measured():
    rec = cis._claim_record([], fired=[], verdict_pair=("cis_uncoupled_no_dependency", None))
    assert rec["finding"]["direction"] == "neutral"
    assert rec["finding"]["availability"] == "measured_positive"


def test_insufficient_underpowered():
    rec = cis._claim_record([], fired=[], verdict_pair=("insufficient_cis_coherence", None))
    assert rec["finding"]["availability"] == "insufficient"


def _schema():
    try:
        from _skills_common.paths import DEFAULT_CONTRACTS_REPO
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
        "coherent_cis_driver",
        "coherent_epigenetic_silencing",
        "cis_uncoupled_no_dependency",
        "dependency_without_cis_dosage",
        "expressed_cis_coupled_inert",
        "insufficient_cis_coherence",
    ):
        rec = cis._claim_record([], fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
