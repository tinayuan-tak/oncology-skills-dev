"""Adversarial-pass rigor: skeptic evidence-surface symmetry (W5), ensemble diversity (W6),
absence-based refutation containment (W7), and the edge-endpoint validation flag."""

from __future__ import annotations

import sys
from pathlib import Path

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import adversarial_survival as AS  # noqa: E402
import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_adversarial")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"
RISK = FIX / "risk.json"
DOSSIER = FIX / "dossier.json"


def _hyp_result():
    return {
        "target": "T",
        "indication": "I",
        "hypothesis": {
            "causal_rationale": {"statement": "A", "citations": ["dependency"]},
            "therapeutic_hypothesis": {"statement": "B", "citations": ["dependency"]},
            "population": {"statement": "C", "citations": ["MSS"]},
            "therapeutic_window": {"statement": "D", "citations": ["safety"]},
        },
    }


# ------------------------------- W5: evidence-surface symmetry -------------------------------
def _synth_panel():
    return {
        "conviction": {"dependency": "strong", "safety": "data_unavailable"},  # one GAP line
        "cards_brief": {"pan-cancer-crispr-dependency-distribution": "strong"},
        "dossier": {},
        "risk": {},
        "claim_vectors": {
            "dependency": {
                "claim_vector": {
                    "DEP": {
                        "signal": "strong",
                        "corroboration": "high",
                        "conflict": None,
                        "evidence_atom": {
                            "read": "strong",
                            "values": {"x": 1},
                            "cite": {"card_id": "pan-cancer-crispr-dependency-distribution"},
                        },
                    }
                },
                "key_signals": {"headline": "Selective dependency."},
            }
        },
        "grounded_substrate": {
            "present": True,
            "per_axis": [{"axis": "safety", "findings": [{"finding": "hepatotox", "cited_pmids": ["31234567"]}]}],
        },
        "subtype": {"present": True, "per_stratum": {"MSS": {"dependency": "strong"}}},
    }


def test_evidence_block_shows_enriched_surface_and_marks_gaps():
    block = AS._evidence_block(_synth_panel())
    assert "claim-vector" in block  # W5: atoms the integrator cited are shown
    assert "GROUNDED per-axis literature findings" in block
    assert "SUBTYPE-RESOLVED per-stratum" in block and "MSS" in block
    assert "GAP / ABSENT lines" in block and "safety" in block


def test_evidence_block_on_real_panel_marks_gaps_when_present():
    panel = hc.assemble(str(PKG), str(RISK), str(DOSSIER), "modality_agnostic")
    block = AS._evidence_block(panel)
    gap_lines = sorted(d for d, v in (panel.get("conviction") or {}).items() if v in hc.GAP_VERDICTS)
    if gap_lines:
        assert "GAP / ABSENT lines" in block


# ------------------------------- W6: ensemble diversity -------------------------------
def test_skeptic_angles_are_distinct_and_cycle():
    assert len(set(AS.SKEPTIC_ANGLES)) == 3
    assert AS._angle_for(0) != AS._angle_for(1) != AS._angle_for(2)
    assert AS._angle_for(3) == AS._angle_for(0)  # cycles


def test_each_skeptic_pass_gets_a_distinct_angle_in_system_prompt():
    seen = []

    def stub(system, user, name, schema, **kw):
        seen.append(system)
        return {
            "clauses": [
                {"clause": k, "refuted": False, "refutation": "", "cited": []}
                for k in ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window")
            ]
        }

    r = AS.adversarial_survival(_hyp_result(), str(PKG), str(RISK), str(DOSSIER), n_skeptics=3, synthesize_fn=stub)
    # three passes → three DIFFERENT system prompts (base + distinct angle)
    assert len(seen) == 3 and len(set(seen)) == 3
    # the angle is recorded per vote
    votes = r["clauses"]["causal_rationale"]["skeptics"]
    assert {v["angle"] for v in votes} == {"OVER-REACH AUDITOR", "ABSENCE AUDITOR", "COMPETING-LINE FINDER"}


# ------------------------------- W7: absence-based refutation is containable -------------------------------
def test_absence_refutation_citing_gap_line_is_contained():
    # a refutation that names the absent line's OWN dimension token is CONTAINED (the token is in the
    # citation surface's sub_verdicts), so a legitimate absence objection is no longer discarded.
    panel = hc.assemble(str(PKG), str(RISK), str(DOSSIER), "modality_agnostic")
    surface = panel["citation_surface"]
    a_sub_verdict = sorted(surface["sub_verdicts"])[0]  # a real dimension token from THIS package
    untraceable = hc.check_traceability([a_sub_verdict], surface)
    assert untraceable == []  # citing a dimension name is traceable → an absence refutation stays valid


# ------------------------------- edge-endpoint validation flag -------------------------------
def test_edge_endpoint_warning_flags_unrecognized_dimension():
    panel = hc.assemble(str(PKG), str(RISK), str(DOSSIER), "modality_agnostic")
    conv = sorted(panel["conviction"])[0]
    edges = [
        {"type": "corroborates", "from_dimension": conv, "to_dimension": "dependency"},  # recognized
        {
            "type": "contradicts",
            "from_dimension": "made_up_dimension_zzz",
            "to_dimension": "dependency",
        },  # hallucinated
    ]
    warns = R._edge_endpoint_warnings(edges, panel)
    vals = {w["value"] for w in warns}
    assert "made_up_dimension_zzz" in vals
    assert conv not in vals and "dependency" not in vals
