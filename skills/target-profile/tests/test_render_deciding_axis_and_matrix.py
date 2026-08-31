"""target-profile .md renders the deciding-axis + ordinal matrix (render follow-through).

The deciding_axis block (L) and ordinal matrix (gap #3/#4) already land in nomination.json + the
LLM prompt, but a human reads target_profile.md. These tests pin that both DETERMINISTIC sections
are surfaced there, with their honesty labels, and that they're purely additive (a render with
neither still works).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _fired(*sm):
    return [{"rule_id": f"r{i}", "card_id": "c", "field": "f", "value": "v", "signals": s}
            for i, s in enumerate(sm)]


def _sr():
    return {
        "dependency": {"skill_dir": "functional-requirement", "cards": [{"card_id": "crispr", "summary": {}}],
                       "verdict": ("lineage_selective", "x"),
                       "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"})},
        "safety": {"skill_dir": "on-target-safety-liability", "cards": [{"card_id": "g", "summary": {}}],
                   "verdict": ("highly_constrained_safety_concern", "y"),
                   "fired": _fired({"small_molecule": "opposing"})},
    }


_LLM = {"executive_summary": {"value": "exec"}, "overall_recommendation": {"value": "hold"},
        "confidence": {"value": "high"}, "tension_analysis": {"value": "t"}}


def test_deciding_axis_gate_fired_rendered():
    da = {"basis": "gate_fired", "routing": "decided by gate F (Safe): safety forced 'hold'.",
          "deciding_axis": {"gate": "F", "gate_name": "Safe", "short": "safety",
                            "framework_can_evidence": "captured"}}
    md = tp._render_target_profile_md("KRAS", "COADREAD", _sr(), _LLM, {}, deciding_axis=da)
    assert "## Deciding axis" in md
    assert "decided by gate F (Safe)" in md
    assert "Load-bearing gate:** F (Safe)" in md
    assert "`captured`" in md


def test_deciding_axis_abstention_lists_unevidenced_gates():
    da = {"basis": "abstention_coverage_gaps",
          "routing": "cannot decide; unevidenced gates ...",
          "unevidenced_gates": [
              {"gate": "C", "short": "dependency", "band": "necessity", "framework_can_evidence": "partial"},
              {"gate": "E", "short": "surface_modality", "band": "sufficiency", "framework_can_evidence": "blind"}]}
    md = tp._render_target_profile_md("KRAS", "COADREAD", _sr(), _LLM, {}, deciding_axis=da)
    assert "cannot decide" in md.lower()
    assert "| gate | short | band | framework can evidence |" in md
    assert "`dependency`" in md and "`surface_modality`" in md


def test_ordinal_matrix_rendered_with_disclaimer():
    mx = tp._ordinal_matrix(_sr())
    md = tp._render_target_profile_md("KRAS", "COADREAD", _sr(), _LLM, {}, ordinal_matrix=mx)
    assert "## Modality-scoped evidence matrix" in md
    assert "NOT calibrated measurement" in md            # the disclaimer survives to the page
    assert "| gate | small_molecule | degrader |" in md
    # the degrader-preferred split is visible (dependency: SM -1, degrader +2)
    assert "| dependency | -1 | +2 |" in md
    assert "the verdict is the decision" in md


def test_render_additive_without_new_sections():
    """Omitting both (the pre-follow-through call shape) still produces a valid profile."""
    md = tp._render_target_profile_md("KRAS", "COADREAD", _sr(), _LLM, {})
    assert "# Target profile — KRAS in COADREAD" in md
    assert "## Deciding axis" not in md
    assert "## Modality-scoped evidence matrix" not in md
    assert "## Sub-verdicts" in md   # the rest still renders


# ---- target-signature landscape panel (descriptive, verdict-inert) --------------------------------
def _min_llm():
    return {"executive_summary": {"value": "x"}, "overall_recommendation": {"value": "advance"},
            "confidence": {"value": "moderate"}, "tension_analysis": {"value": ""}, "top_arguments": []}


def test_phenotype_landscape_panel_rendered_when_companion_present():
    comp = {"phenotype_mixture": {"expression_surface": 0.62, "dependency_essential": 0.28, "amp_driver": 0.1},
            "nearest_analogs": [{"target": "CDH17", "indication": "COADREAD", "distance": 4.3}],
            "novelty": {"inconsistent_flag": False, "local_density_flag": False, "hull_residual": 1.2},
            "missingness": {"unmeasured_axes": ["immune_context"], "n_features_measured": 89,
                            "n_features_total": 108}}
    sc = {"score": 0.56, "counterfactual_gap": {"limiting_axis": "safety"}}
    md = tp._render_target_profile_md("EPCAM", "COADREAD", _sr(), _min_llm(), {},
                                      archetype_companion=comp, nomination_scorecard=sc)
    assert "## Target-signature landscape" in md
    assert "Phenotype mixture" in md and "expression_surface" in md
    assert "Nearest reference analogs" in md and "CDH17" in md
    assert "Readiness (D1" in md and "0.56" in md
    assert "verdict-inert" in md.lower()          # governance label present


def test_phenotype_landscape_panel_absent_is_additive():
    # no companion -> the render still works and the section is simply absent (purely additive)
    md = tp._render_target_profile_md("KRAS", "COADREAD", _sr(), _min_llm(), {})
    assert "## Target-signature landscape" not in md
    assert "## Recommendation" in md              # rest of the profile renders normally


def test_phenotype_playbook_rendered_for_dominant_phenotype():
    comp = {"phenotype_mixture": {"expression_surface": 0.7, "dependency_essential": 0.3},
            "nearest_analogs": [], "novelty": {}, "missingness": {}}
    md = tp._render_target_profile_md("EPCAM", "COADREAD", _sr(), _min_llm(), {}, archetype_companion=comp)
    assert "Playbook (expression_surface)" in md
    assert "ADC / TCE" in md and "comparators:" in md
    assert "not a classification or a gate" in md      # governance label retained
