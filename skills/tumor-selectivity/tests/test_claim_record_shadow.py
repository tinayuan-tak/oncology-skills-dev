"""tumor-selectivity factored-record SHADOW builder (M1) — first WIRED-skill exemplar. Pins the
verdict->record mapping, the REAL continuous magnitude (max_abs_log2fc), the open-world case, the
fired-set cross-check, and full conformance to claim_record.schema.json when contracts is present.
Consumed-by-nothing / verdict-inert."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _test_support import load_run_py

sel = load_run_py(Path(__file__).resolve().parent.parent, "sel_run_shadow")


def _tvn(**kw):
    base = {"dominant_direction": "tumor_up", "cells_ran": 400, "n_tumor": 300, "max_abs_log2fc": 3.1}
    base.update(kw)
    return [{"card_id": "tumor-vs-normal-selectivity", "summary": base}]


def _fired(*rids):
    return [{"rule_id": r, "card_id": "tumor-vs-normal-selectivity"} for r in rids]


def test_strong_selective_measured_positive_with_real_magnitude():
    rec = sel._claim_record(_tvn(), fired=_fired("tumor-selective-strong"),
                            verdict_pair=("strong_tumor_selective", "tumor-selective-strong"))
    assert rec["axis"] == "selectivity"
    assert rec["finding"]["state"] == "strong_tumor_selective"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    # the tumor-vs-normal window is a genuine continuous measure — carried with its scale
    assert rec["finding"]["magnitude"]["value"] == 3.1
    assert rec["finding"]["magnitude"]["scale"] == "log2fc"
    assert rec["provenance"]["fired_rule_ids"] == ["tumor-selective-strong"]


def test_magnitude_carries_distance_to_cut():
    # strong verdict, max|log2FC|=3.1 vs the strong cutpoint 1.5 -> distance_to_cut = 1.6 (well clear)
    rec = sel._claim_record(_tvn(max_abs_log2fc=3.1), fired=[],
                            verdict_pair=("strong_tumor_selective", None))
    assert rec["finding"]["magnitude"]["distance_to_cut"] == 1.6
    # a barely-cleared modest call: 0.6 vs the modest cutpoint 0.5 -> distance 0.1 (knife-edge)
    rec2 = sel._claim_record(_tvn(max_abs_log2fc=0.6), fired=[],
                             verdict_pair=("modest_tumor_selective", None))
    assert rec2["finding"]["magnitude"]["distance_to_cut"] == 0.1


def test_not_selective_is_measured_negative_opposes():
    rec = sel._claim_record(_tvn(), fired=[], verdict_pair=("not_selective", None))
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["finding"]["direction"] == "opposes"


def test_data_unavailable_is_open_world_noncommittal():
    rec = sel._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["availability"] == "not_wired"
    assert f["state"] == "unknown" and f["direction"] == "neutral"
    assert f["magnitude"]["value"] is None            # open-world flattens magnitude


def test_inconclusive_is_measured_but_underpowered():
    rec = sel._claim_record(_tvn(), fired=[], verdict_pair=("discordant_across_comparators", None))
    assert rec["finding"]["availability"] == "insufficient"


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
    for vp in [("strong_tumor_selective", "r"), ("not_selective", None),
               ("data_unavailable", None), ("discordant_across_comparators", None),
               ("modest_tumor_selective", "r")]:
        rec = sel._claim_record(_tvn(), fired=_fired("r") if vp[1] else [], verdict_pair=vp)
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{vp} -> {[e.message for e in errs]}"
