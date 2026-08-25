"""tractability-small-molecule factored-record SHADOW builder (M1) — SM-specific modality_scope axis.
Pins druggable->favorable / intractable->unfavorable SM scope, direction/availability, minimal
coverage-only certainty, fired-set cross-check, and schema conformance. Consumed-by-nothing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run as tr  # noqa: E402


def _fired(*rids):
    return [{"rule_id": r, "card_id": "known-drug-tractability"} for r in rids]


def test_ligandable_supports_sm_favorable():
    rec = tr._claim_record([], fired=_fired("structurally-ligandable"),
                           verdict_pair=("measured_potent_ligand", "structurally-ligandable"))
    assert rec["axis"] == "tractability_small_molecule"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["modality_scope"] == {"small_molecule": "favorable", "biologics": "na"}
    assert rec["provenance"]["fired_rule_ids"] == ["structurally-ligandable"]


def test_intractable_opposes_sm_unfavorable():
    rec = tr._claim_record([], fired=[], verdict_pair=("structurally_intractable", None))
    assert rec["finding"]["direction"] == "opposes"
    assert rec["finding"]["availability"] == "measured_negative"
    assert rec["modality_scope"]["small_molecule"] == "unfavorable"


def test_insufficient_has_no_sm_call():
    rec = tr._claim_record([], fired=[], verdict_pair=("insufficient", None))
    assert rec["finding"]["availability"] == "insufficient"
    assert "modality_scope" not in rec
    assert rec["certainty"]["corroboration"] == "unmeasured"


def test_none_verdict_open_world():
    rec = tr._claim_record([], fired=[], verdict_pair=(None, None))
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
    for v in ("well_covered", "measured_potent_ligand", "chemically_active", "structurally_ligandable",
              "clinical_precedent_only", "tool_compound_only", "weakly_active", "structurally_intractable",
              "chemically_unhit", "discordant", "insufficient", None):
        rec = tr._claim_record([], fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"


# ── D1: degrader channel lifted onto modality_scope._refinements.degrader ────────────────────────
def test_degrader_favorable_splits_from_intractable_sm(monkeypatch):
    """The multi-modality story: SM-intractable but degrader-favorable (BRD4/STAT3) — the degrader
    channel must reflect its OWN measured feasibility, not inherit the SM unfavorable call."""
    monkeypatch.setattr(tr, "_degrader_snapshot", lambda fired: ("strong_degrader_rationale", "r"))
    rec = tr._claim_record([], fired=[{"rule_id": "x"}], verdict_pair=("structurally_intractable", None))
    assert rec["modality_scope"]["small_molecule"] == "unfavorable"
    assert rec["modality_scope"]["_refinements"]["degrader"] == "favorable"


def test_degrader_unviable_and_opposed_map(monkeypatch):
    monkeypatch.setattr(tr, "_degrader_snapshot", lambda fired: ("degrader_unviable", "r"))
    r1 = tr._claim_record([], fired=[{"rule_id": "x"}], verdict_pair=("structurally_ligandable", None))
    assert r1["modality_scope"]["_refinements"]["degrader"] == "unfavorable"
    monkeypatch.setattr(tr, "_degrader_snapshot", lambda fired: ("degrader_opposed", "r"))
    r2 = tr._claim_record([], fired=[{"rule_id": "x"}], verdict_pair=("structurally_ligandable", None))
    assert r2["modality_scope"]["_refinements"]["degrader"] == "conditional"


def test_degrader_insufficient_omits_refinement(monkeypatch):
    monkeypatch.setattr(tr, "_degrader_snapshot", lambda fired: ("insufficient", None))
    rec = tr._claim_record([], fired=[{"rule_id": "x"}], verdict_pair=("structurally_ligandable", None))
    assert "_refinements" not in (rec.get("modality_scope") or {})   # keeps SM-base fallback
