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
                    "overall_consistency": "concordant",
                    "key_divergence": "none",
                    "axes": [],
                    "blind_spots": [],
                    "_model_id": "us.anthropic.claude-opus-4-8",
                    "_prompt_hash": "h1",
                },
            },
        },
        # a skill with no lane (no literature_synthesis) → skipped
        "target_intrinsic": {
            "skill_dir": "target-intrinsic",
            "verdict": None,
            "fired": [],
            "synthesis_facet": {"claim_vector": {}},
        },
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("KRAS", "COADREAD", literature_scope="gating")
    assert len(recs) == 1
    r = recs[0]
    assert r["target"] == "KRAS" and r["indication"] == "COADREAD"
    assert r["skill"] == "functional-requirement"  # skill DIR id, not the short
    assert r["sub_verdict"]["verdict"] == "lineage_selective"
    assert r["sub_verdict"]["driving_rule_id"] == "lineage-selective-supportive"
    assert r["sub_verdict"]["fired_rule_ids"] == ["lineage-selective-supportive", "x-neutral"]
    assert r["claim_vector"]["DEP"]["signal"] == "strong"
    assert r["_provenance"]["model_id"] == "us.anthropic.claude-opus-4-8"


def test_canonical_symbol_maps_aliases():
    """The calibration-set alias KEYS resolve to their HGNC-canonical gene symbol; canonical /
    unknown symbols pass through unchanged (CASE-011)."""
    assert hl._canonical_symbol("HER2") == "ERBB2"
    assert hl._canonical_symbol("TROP2") == "TACSTD2"
    assert hl._canonical_symbol("BCMA") == "TNFRSF17"
    assert hl._canonical_symbol("CD20") == "MS4A1"
    assert hl._canonical_symbol(" HER2 ") == "ERBB2"  # whitespace-tolerant
    assert hl._canonical_symbol("KRAS") == "KRAS"  # already canonical → unchanged
    assert hl._canonical_symbol("NOT_A_GENE") == "NOT_A_GENE"


def test_harvest_pair_runs_on_canonical_symbol_but_labels_the_alias(monkeypatch):
    """CASE-011 regression: the fan-out is invoked on the HGNC symbol (ERBB2), so gene-keyed
    readers resolve, while the emitted record stays LABELLED with the calibration alias (HER2) —
    calibration_gap tagging + the snapshot filename remain keyed by the display symbol."""
    seen = {}

    def _capture(target, indication, **kw):
        seen["target"] = target
        seen["indication"] = indication
        return {
            "tractability_sm": {
                "skill_dir": "tractability-small-molecule",
                "verdict": ("chemically_active", "prism-clinically-active-supportive-sm"),
                "fired": [{"rule_id": "prism-clinically-active-supportive-sm"}],
                "synthesis_facet": {
                    "claim_vector": {},
                    "literature_synthesis": {
                        "overall_consistency": "concordant",
                        "axes": [],
                        "blind_spots": [],
                        "_model_id": "m",
                        "_prompt_hash": "h",
                    },
                },
            },
        }

    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = _capture
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("HER2", "BRCA")
    assert seen["target"] == "ERBB2"  # fan-out ran on the HGNC symbol
    assert len(recs) == 1
    assert recs[0]["target"] == "HER2"  # record keeps the alias label
    assert recs[0]["resolved_symbol"] == "ERBB2"  # audit trail records the resolution
    assert recs[0]["sub_verdict"]["verdict"] == "chemically_active"


def test_harvested_records_feed_the_aggregator(monkeypatch, tmp_path):
    """End-to-end (offline): harvest → snapshot → build_discordance_ledger."""
    import json

    import build_discordance_ledger as bdl

    fake = {
        "genomic_alteration": {
            "skill_dir": "genomic-alteration-profile",
            "verdict": ("passenger_or_absent", "no-recurrent-driver-neutral"),
            "fired": [{"rule_id": "no-recurrent-driver-neutral"}],
            "synthesis_facet": {
                "claim_vector": {},
                "literature_synthesis": {
                    "overall_consistency": "discordant",
                    "key_divergence": "METex14 driver",
                    "axes": [
                        {
                            "axis_key": "A",
                            "literature_read": "strongly_supports",
                            "assertion": "METex14 is a validated driver.",
                            "agreement_vs_omics": "contradicts",
                            "confidence": "high",
                            "citations": [{"label": "Paik 2020", "pmid": "32469185", "verified": True}],
                        }
                    ],
                    "blind_spots": [],
                    "_model_id": "m",
                    "_prompt_hash": "h",
                },
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


def test_pairs_from_calibration_dict_keyed(tmp_path):
    """(target,indication) pairs come from dict-keyed sections; composites + `multi` skipped."""
    cal = tmp_path / "cal.yaml"
    cal.write_text(
        "reference_profiles:\n  PARP1:\n    indication: OV\n  CDK4_6:\n    indication: BRCA\n"
        "  ADAR1:\n    indication: multi\n"
        "known_gap_watchlist:\n  MET:\n    indication: LUAD\n"
    )
    pairs = hl._pairs_from_calibration(cal)
    assert ("PARP1", "OV") in pairs
    assert ("MET", "LUAD") in pairs
    assert not any(t == "CDK4_6" for t, _ in pairs)  # composite skipped
    assert not any(i == "multi" for _, i in pairs)  # non-specific indication skipped
