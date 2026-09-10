"""genomic-alteration factored-record SHADOW builder (M1). The FIRST per-axis shadow: maps the
genomic_alteration verdict onto the factored record. Pins the M1 cross-check (provenance.fired_rule_ids
== the resolver fired set), the driver/passenger/open-world mappings, and — when the sibling contracts
repo is checked out — full conformance to claim_record.schema.json. Consumed-by-nothing / verdict-inert."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

ga = load_run_py(Path(__file__).resolve().parent.parent, "ga_run_claim")


def _fired(*rule_ids):
    return [{"rule_id": r, "card_id": "variant-level-interpretation"} for r in rule_ids]


def test_driver_is_measured_positive_and_provenance_mirrors_fired():
    fired = _fired("recurrent-snv-driver", "focal-amplification-driver", "recurrent-snv-driver")
    rec = ga._claim_record([], fired=fired, verdict_pair=("multi_class_driver", "recurrent-snv-driver"))
    assert rec["axis"] == "genomic_alteration"
    assert rec["finding"]["state"] == "multi_class_driver"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    # M1 CROSS-CHECK: provenance.fired_rule_ids == the resolver fired set (sorted-unique)
    assert rec["provenance"]["fired_rule_ids"] == ["focal-amplification-driver", "recurrent-snv-driver"]


def test_passenger_is_measured_negative_opposes():
    rec = ga._claim_record([], fired=_fired("passenger-only"), verdict_pair=("passenger_pattern", "passenger-only"))
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["finding"]["direction"] == "opposes"


def test_data_unavailable_is_open_world_noncommittal():
    rec = ga._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["availability"] == "not_wired"  # open-world
    assert f["state"] == "unknown" and f["direction"] == "neutral"  # ignorance != negation
    assert rec["provenance"]["fired_rule_ids"] == []


def test_insufficient_is_measured_but_underpowered():
    rec = ga._claim_record([], fired=[], verdict_pair=("insufficient", None))
    assert rec["finding"]["availability"] == "insufficient"
    assert rec["finding"]["state"] == "insufficient"


def test_lof_verdict_carries_lof_role():
    rec = ga._claim_record([], fired=_fired("lof-driver"), verdict_pair=("confirmed_lof_driver", "lof-driver"))
    assert rec["mechanism"]["role"] == "LoF"


# ── optional: validate against the real contract schema when the sibling repo is present ──
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
        pytest.skip("contracts repo / claim_record.schema.json not available on this runner")
    from jsonschema import Draft202012Validator

    for vp in [
        ("multi_class_driver", "r"),
        ("passenger_pattern", "r"),
        ("data_unavailable", None),
        ("insufficient", None),
        ("confirmed_lof_driver", "r"),
    ]:
        rec = ga._claim_record([], fired=_fired("r") if vp[1] else [], verdict_pair=vp)
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{vp} -> schema errors: {[e.message for e in errs]}"
