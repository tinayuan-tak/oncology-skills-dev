"""Hermetic tests for harvest_literature — stubs the fan-out; NO live S3 / NO Bedrock.

Runs via: pixi run pytest eval/tests/test_harvest_literature.py -q   (from the home checkout).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import harvest_literature as hl  # noqa: E402


def test_parse_pairs():
    assert hl._parse_pairs("KRAS/COADREAD, MET/LUAD") == [("KRAS", "COADREAD"), ("MET", "LUAD")]
    assert hl._parse_pairs("") == []


def test_normalize_verdict():
    assert hl._normalize_verdict(("lineage_selective", "rule-x")) == ("lineage_selective", "rule-x")
    assert hl._normalize_verdict(None) == (None, None)
    assert hl._normalize_verdict(("v",)) == ("v", None)


def test_harvest_pair_projects_records(monkeypatch):
    """Stub _run_sub_skills so harvest_pair runs with no network. Only sub-skills whose lane
    actually ran (literature_synthesis present) yield a record."""
    fake = {
        "dependency": {
            "skill_dir": "functional-requirement",
            "verdict": ("lineage_selective", "lineage-selective-supportive"),
            "fired": [{"rule_id": "lineage-selective-supportive"}, {"rule_id": "x-neutral"}],
            "synthesis_facet": {
                "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high"}},
                "literature_synthesis": {
                    "overall_consistency": "concordant", "key_divergence": "none",
                    "axes": [], "blind_spots": [],
                    "_model_id": "us.anthropic.claude-opus-4-8", "_prompt_hash": "h1",
                },
            },
        },
        # a skill with no lane (no literature_synthesis) → skipped
        "target_intrinsic": {"skill_dir": "target-intrinsic", "verdict": None,
                             "fired": [], "synthesis_facet": {"claim_vector": {}}},
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("KRAS", "COADREAD", literature_scope="gating")
    assert len(recs) == 1
    r = recs[0]
    assert r["target"] == "KRAS" and r["indication"] == "COADREAD"
    assert r["skill"] == "functional-requirement"          # skill DIR id, not the short
    assert r["sub_verdict"]["verdict"] == "lineage_selective"
    assert r["sub_verdict"]["driving_rule_id"] == "lineage-selective-supportive"
    assert r["sub_verdict"]["fired_rule_ids"] == ["lineage-selective-supportive", "x-neutral"]
    assert r["claim_vector"]["DEP"]["signal"] == "strong"
    assert r["_provenance"]["model_id"] == "us.anthropic.claude-opus-4-8"


def test_harvested_records_feed_the_aggregator(monkeypatch, tmp_path):
    """End-to-end (offline): harvest → snapshot → build_discordance_ledger."""
    import build_discordance_ledger as bdl
    import json

    fake = {
        "genomic_alteration": {
            "skill_dir": "genomic-alteration-profile",
            "verdict": ("passenger_or_absent", "no-recurrent-driver-neutral"),
            "fired": [{"rule_id": "no-recurrent-driver-neutral"}],
            "synthesis_facet": {
                "claim_vector": {},
                "literature_synthesis": {
                    "overall_consistency": "discordant", "key_divergence": "METex14 driver",
                    "axes": [{"axis_key": "A", "literature_read": "strongly_supports",
                              "assertion": "METex14 is a validated driver.",
                              "agreement_vs_omics": "contradicts", "confidence": "high",
                              "citations": [{"label": "Paik 2020", "pmid": "32469185", "verified": True}]}],
                    "blind_spots": [], "_model_id": "m", "_prompt_hash": "h"},
            },
        },
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("MET", "LUAD")
    snap = tmp_path / "MET__LUAD.json"
    snap.write_text(json.dumps(recs))
    ledger = bdl.build_ledger(tmp_path, calibration_targets={"MET"})
    assert ledger["n_rows"] == 1
    assert ledger["rows"][0]["gap_class"] == bdl.GAP_CALIBRATION
