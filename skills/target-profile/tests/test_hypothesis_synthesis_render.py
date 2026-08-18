"""Cross-evidence hypothesis synthesis swap (dashboard).

When a cross-evidence-hypothesis `hypothesis.json` is passed to the HTML renderer it REPLACES the
original Tier-3 LLM synthesis (executive_summary + tension_analysis) with the gate-clamped, cited
6-part structured hypothesis. The deterministic recommendation stays the header top-line; the
integrator's own verdict/go_forth render INSIDE the hypothesis section. Absent a hypothesis, the
original executive summary is shown (backward-compatible).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_hyp", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _sr():
    return {
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {}}],
                       "verdict": ("lineage_selective", "lineage-selective-supportive"), "fired": []},
        "safety": {"skill_dir": "on-target-safety-liability",
                   "cards": [{"card_id": "g", "summary": {}}],
                   "verdict": ("highly_constrained_safety_concern", "hcs-warning"), "fired": []},
    }


_LLM = {"executive_summary": {"value": "KRAS is modality-constrained."},
        "overall_recommendation": {"value": "nominate"}, "confidence": {"value": "high"},
        "tension_analysis": {"value": "the-old-tension-narrative"}}

_HYP = {
    "skill_version": "0.2.0",
    "hypothesis": {
        "causal_rationale": {"statement": "KRAS is a dominant signaling node.",
                             "citations": ["signaling-network-mechanism"]},
        "therapeutic_hypothesis": {"statement": "Allele-specific inhibition of mutant KRAS.",
                                   "modality": "small_molecule",
                                   "citations": ["known-drug-tractability"],
                                   "contradicting_citations": ["partner-conditional-dependency"]},
        "population": {"statement": "KRAS-mutant COADREAD.", "subtype_or_biomarker": "G12C",
                       "citations": ["mutation-hotspot-frequency"]},
        "therapeutic_window": {"statement": "Rests on allele selectivity.",
                               "citations": ["normal-tissue-liability-gtex"],
                               "contradicting_citations": ["safety"]},
        "evidence_grade": {"overall": "moderate",
                           "per_line": [{"dimension": "mechanism", "strength": "strong"},
                                        {"dimension": "safety", "strength": "weak"}]},
        "tensions": [{"statement": "No actionable SL partner mapped in COADREAD.",
                      "citations": ["partner-conditional-dependency"]}],
        "go_forth": {"next_evidence": "Run an isogenic mutant-vs-WT organoid panel.",
                     "value_of_information": "Highest — resolves the window question."},
    },
    "verdict": {"computed": "advanceable_with_caveat", "gate_ceiling": "advanceable_with_caveat",
                "gate_reason": "opposing measured evidence (selectivity:discordant_across_comparators)",
                "reason": {"value": "Advanceable only as an allele-specific small molecule."}},
    "defensibility": {"clause_traceability": 1.0, "n_clauses": 23, "n_fully_traceable": 23,
                      "promotable": True, "n_coherence_violations": 0},
    "uncertainty": {"overall_certainty": "low"},
    "provenance": {"model_id": "us.anthropic.claude-opus-4-8", "prompt_template_hash": "a9c0cca3669cbb"},
}


def _render(hypothesis=None):
    sc = tp._gate_scorecard(_sr(), None)
    return tp._render_target_profile_html(
        "KRAS", "COADREAD", _sr(), _LLM, {}, scorecard=sc, hypothesis=hypothesis)


def test_hypothesis_replaces_the_tier3_synthesis():
    h = _render(hypothesis=_HYP)
    assert "id=s-hypothesis" in h
    assert "Cross-evidence hypothesis" in h
    # the original exec-summary + tension sections are REPLACED (not rendered)
    assert "id=s-exec" not in h
    assert "id=s-tension" not in h
    assert "the-old-tension-narrative" not in h


def test_hypothesis_surfaces_verdict_defensibility_and_go_forth():
    h = _render(hypothesis=_HYP)
    assert "Advanceable" in h                       # humanized computed verdict
    assert "ceiling" in h                           # gate-clamp ceiling shown
    assert "clause-traceability 100%" in h          # 1.0 → 100%
    assert "Run an isogenic mutant-vs-WT organoid panel." in h   # go_forth
    assert "No actionable SL partner mapped in COADREAD." in h    # tensions inside the section


def test_hypothesis_cites_and_flags_countervailing():
    h = _render(hypothesis=_HYP)
    assert "signaling-network-mechanism" in h       # a supporting citation chip
    assert "Countervailing" in h and "partner-conditional-dependency" in h  # contradicting-citation flag


def test_deterministic_recommendation_stays_the_header_top_line():
    """User decision: the header recommendation stays the rule-fired verdict; the integrator's
    go/no-go lives inside the hypothesis section, not the top-line."""
    h = _render(hypothesis=_HYP)
    head = h.split("<div class=rec>", 1)[1].split("</div>", 1)[0]
    assert "Nominate" in head or "nominate" in head   # deterministic recommendation, not the integrator's


def test_no_hypothesis_keeps_original_executive_summary():
    h = _render(hypothesis=None)
    assert "id=s-exec" in h and "Executive summary" in h
    assert "id=s-hypothesis" not in h
