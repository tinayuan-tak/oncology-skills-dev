"""cross-evidence-hypothesis — P4 (cross-gate shared-evidence) + P5 (fragility + competitor panel
facets): the integrator consumes the remaining synthesis.decision_facets members — surfacing the
spine's authoritative cross-gate correlation in evidence_independence and rendering fragility /
competitor / cross-gate into the LLM panel. All verdict-inert (offline; LLM stubbed)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_decision_facets")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"


def _pkg_with_facets():
    pkg = json.loads(PKG.read_text())
    pkg["synthesis"]["decision_facets"] = {
        "cross_gate_shared_evidence": {
            "shared_input_cards": {"copy-number-distribution": ["safety", "genomic_alteration"]},
            "correlated_gate_pairs": [["safety", "genomic_alteration"]]},
        "fragility": {"contested": True, "acquisition_backlog": [
            {"axis": "immune_context", "coverage": "low", "action": "acquire",
             "missing_cards": [{"card_id": "immune-context", "availability_state": "not_wired"}]}]},
        "competitor_crossref": {"competition_density": "crowded", "modality_validated": True},
    }
    return pkg


def _stub(system, user, name, schema, **kw):
    if name == "cross_edges":
        return {"edges": [], "principal_tensions": [], "evidence_paths": []}
    return {
        "causal_rationale": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_hypothesis": {"statement": "x", "modality": "small_molecule",
                                   "citations": ["dependency"]},
        "population": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_window": {"statement": "x", "citations": ["safety"]},
        "evidence_grade": {"overall": "moderate", "per_line": []},
        "proposed_verdict": "advanceable", "proposed_verdict_reason": "x",
        "go_forth": {"next_evidence": "y"},
    }


# =============================== assemble surfaces the facets ======================================

def test_assemble_surfaces_decision_facets(tmp_path):
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(_pkg_with_facets()))
    panel = hc.assemble(str(p), None, None, "small_molecule")
    assert panel["cross_gate_shared_evidence"]["correlated_gate_pairs"] == [["safety", "genomic_alteration"]]
    assert panel["fragility_facet"]["contested"] is True
    assert panel["competitor_crossref"]["competition_density"] == "crowded"


def test_assemble_tolerates_absent_facets(tmp_path):
    p = tmp_path / "ep.json"
    p.write_text(PKG.read_text())        # fixture has no decision_facets
    panel = hc.assemble(str(p), None, None, "small_molecule")
    assert panel["cross_gate_shared_evidence"] == {}
    assert panel["fragility_facet"] == {} and panel["competitor_crossref"] == {}


# =============================== P5 — panel rendering =============================================

def test_render_decision_facets_present():
    panel = {"fragility_facet": {"contested": True,
                                 "acquisition_backlog": [{"axis": "immune_context"}]},
             "competitor_crossref": {"competition_density": "crowded"},
             "cross_gate_shared_evidence": {"correlated_gate_pairs": [["safety", "genomic_alteration"]]}}
    block = R._render_decision_facets(panel)
    assert "contested=True" in block
    assert "immune_context" in block                 # backlog axis surfaced (feeds go_forth)
    assert "crowded" in block                         # competitor density
    assert "correlated" in block and "safety" in block  # cross-gate correlation surfaced


def test_render_surfaces_factored_record_consumers():
    """M4: the per-modality call, over-precision audit, and the acquire-vs-strengthen split reach the
    synthesis prompt (the distinctions the scalar verdict could not carry)."""
    panel = {
        "fragility_facet": {"contested": False,
                            "acquisition_backlog": [{"axis": "surface_modality"}],
                            "underpowered_axes": [{"axis": "selectivity", "action": "strengthen"}]},
        "modality_fit_by_channel": {"small_molecule": {"fit": "conditional"},
                                    "degrader": {"fit": "unfavorable"}, "adc": {"fit": "na"}},
        "magnitude_borderline": [{"axis": "selectivity", "scale": "log2fc", "distance_to_cut": 0.1}],
    }
    block = R._render_decision_facets(panel)
    assert "STRENGTHEN" in block and "selectivity" in block          # measured-thin split
    assert "acquisition_backlog" in block and "surface_modality" in block
    assert "modality_fit_by_channel" in block and "conditional" in block and "unfavorable" in block
    assert "adc" not in block            # 'na' channels are dropped from the per-modality call
    assert "magnitude_borderline" in block and "knife-edge" in block


def test_render_decision_facets_empty_when_absent():
    assert R._render_decision_facets({"fragility_facet": {}, "competitor_crossref": {},
                                      "cross_gate_shared_evidence": {}}) == ""


def test_panel_block_includes_facets(tmp_path):
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(_pkg_with_facets()))
    panel = hc.assemble(str(p), None, None, "small_molecule")
    block, *_ = R._panel_block(panel, "small-molecule drug target")
    assert "decision facets (verdict-INERT" in block
    assert "contested=True" in block and "crowded" in block


# =============================== P4 — result surfacing ============================================

def test_run_surfaces_cross_gate_shared_evidence(tmp_path):
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(_pkg_with_facets()))
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    cgse = r["evidence_independence"]["cross_gate_shared_evidence"]
    assert cgse["correlated_gate_pairs"] == [["safety", "genomic_alteration"]]
    # the substrate-unit certainty basis is untouched (additive surfacing, not a discount rewrite)
    assert "n_independent_units" in r["evidence_independence"]


def test_run_without_facets_leaves_cross_gate_empty(tmp_path):
    p = tmp_path / "ep.json"
    p.write_text(PKG.read_text())
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    assert r["evidence_independence"]["cross_gate_shared_evidence"] == {}
