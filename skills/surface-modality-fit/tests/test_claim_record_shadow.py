"""surface-modality-fit factored-record SHADOW builder (M1) — the axis where modality_scope is NATIVE
(the verdict directly names the fitting biologic modality). Pins the per-verdict ADC/TCE preference,
open-world/negative cases, fired-set cross-check, and schema conformance. Consumed-by-nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

sm = load_run_py(Path(__file__).resolve().parent.parent, "smf_run_shadow")


def _cards():
    return [{"card_id": "surface-abundance-density", "summary": {"surface_density_class": "high"}}]


def _fired(*rids):
    return [{"rule_id": r, "card_id": "adc-tce-modality-fit"} for r in rids]


def test_adc_preferred_maps_to_adc_favorable_tce_unfavorable():
    rec = sm._claim_record(_cards(), fired=_fired("adc-preferred"), verdict_pair=("adc_preferred", "adc-preferred"))
    assert rec["axis"] == "surface_modality"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    ms = rec["modality_scope"]
    assert ms["small_molecule"] == "na"  # surface fit does not speak to SM
    assert ms["_refinements"]["adc"] == "favorable"
    assert ms["_refinements"]["bite_tce"] == "unfavorable"
    assert ms["biologics"] == "favorable"
    assert rec["provenance"]["fired_rule_ids"] == ["adc-preferred"]


def test_both_viable():
    rec = sm._claim_record(_cards(), fired=[], verdict_pair=("both_viable", None))
    ms = rec["modality_scope"]
    assert ms["_refinements"] == {"adc": "favorable", "bite_tce": "favorable"}


def test_neither_viable_is_measured_negative():
    rec = sm._claim_record(_cards(), fired=[], verdict_pair=("neither_viable", None))
    assert rec["finding"]["direction"] == "opposes"
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["modality_scope"]["biologics"] == "unfavorable"


def test_tce_escape_risk_is_conditional_tce():
    rec = sm._claim_record(_cards(), fired=[], verdict_pair=("tce_escape_risk", None))
    assert rec["modality_scope"]["_refinements"]["bite_tce"] == "conditional"


def test_ambiguous_has_no_modality_call():
    rec = sm._claim_record(_cards(), fired=[], verdict_pair=("modality_ambiguous", None))
    assert rec["finding"]["availability"] == "insufficient"
    assert "modality_scope" not in rec  # no call → block omitted


def test_data_unavailable_is_open_world():
    rec = sm._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["availability"] == "not_wired"
    assert f["state"] == "unknown" and f["direction"] == "neutral"


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
        pytest.skip("contracts repo / claim_record.schema.json not available")
    from jsonschema import Draft202012Validator

    for v in (
        "adc_preferred",
        "adc_preferred_tce_escape_risk",
        "tce_preferred",
        "both_viable",
        "surface_viable_density_caveated",
        "shed_dominant_opposed",
        "neither_viable",
        "tce_unsafe_normal_liability",
        "modality_ambiguous",
        "data_unavailable",
    ):
        rec = sm._claim_record(_cards(), fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
