"""on-target-safety factored-record SHADOW builder (M1) — the axis that exercises modality_scope.
Pins the WT-loss concern -> per-modality mapping (§8: opposes engages-WT biologics, conditional for
allele-selective SM), the reassuring/open-world cases, coverage-only certainty, the fired-set
cross-check, and schema conformance. Consumed-by-nothing / verdict-inert."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

saf = load_run_py(Path(__file__).resolve().parent.parent, "saf_run")

_DECISION_CARDS = [
    {"card_id": c, "summary": {"x": 1}}
    for c in (
        "gnomad-lof-constraint",
        "normal-tissue-liability-gtex",
        "clinvar-pathogenicity-safety",
        "mouse-ko-phenotype",
        "clingen-dosage",
        "gene-burden-safety",
        "pan-cancer-crispr-dependency-distribution",
        "normal-tissue-liability",
    )
]


def _fired(*rids):
    return [{"rule_id": r, "card_id": "gnomad-lof-constraint"} for r in rids]


def test_wt_loss_concern_is_modality_conditional():
    # a germline WT-loss concern fired + the allele-selective eligibility context (activating driver)
    fired = _fired("highly-constrained-safety-warning", "activating-driver-role-safety-context")
    rec = saf._claim_record(
        _DECISION_CARDS,
        fired=fired,
        verdict_pair=("highly_constrained_safety_concern", "highly-constrained-safety-warning"),
    )
    assert rec["axis"] == "safety"
    assert rec["finding"]["direction"] == "opposes"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    ms = rec["modality_scope"]
    # the whole point: the concern is NOT a scalar — it opposes engages-WT biologics but is at most
    # conditional for an allele-selective small molecule.
    assert ms["biologics"] == "unfavorable"
    assert ms["small_molecule"] in {"conditional", "unfavorable"}
    # provenance mirrors the fired set (M1 cross-check)
    assert rec["provenance"]["fired_rule_ids"] == sorted(
        {"highly-constrained-safety-warning", "activating-driver-role-safety-context"}
    )


def test_tolerant_is_reassuring_measured_negative():
    rec = saf._claim_record(_DECISION_CARDS, fired=[], verdict_pair=("tolerant_reduced_safety_risk", None))
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_negative"


def test_data_unavailable_is_open_world_noncommittal():
    rec = saf._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["availability"] == "not_wired"
    assert f["state"] == "unknown" and f["direction"] == "neutral"


def test_coverage_only_certainty_reflects_present_cards():
    full = saf._claim_record(_DECISION_CARDS, fired=[], verdict_pair=("moderately_constrained_safety", None))
    assert full["certainty"]["coverage"] == "high"
    assert full["certainty"]["corroboration"] == "unmeasured"  # no disjoint corroborator for safety
    assert full["certainty"]["level"] == full["certainty"]["coverage"]
    assert full["certainty"]["unknown_mass"] == 0.0
    thin = saf._claim_record([], fired=[], verdict_pair=("moderately_constrained_safety", None))
    assert thin["certainty"]["coverage"] == "low" and thin["certainty"]["unknown_mass"] == 1.0


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

    cases = [
        ("highly_constrained_safety_concern", _fired("highly-constrained-safety-warning")),
        ("pan_essential_broad_tox_concern", _fired("pan-essential-killer")),
        ("tolerant_reduced_safety_risk", []),
        ("data_unavailable", []),
        ("moderately_constrained_safety", []),
    ]
    for v, fired in cases:
        rec = saf._claim_record(_DECISION_CARDS, fired=fired, verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
