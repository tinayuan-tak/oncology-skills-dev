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


# ---------- review fixes: header coherence / robustness / drift-guard ----------

def _render2(hypothesis=None, risk_assessment=None, grounded_by_axis=None, confidence_tier=None):
    sc = tp._gate_scorecard(_sr(), None)
    return tp._render_target_profile_html(
        "KRAS", "COADREAD", _sr(), _LLM, {}, scorecard=sc, hypothesis=hypothesis,
        risk_assessment=risk_assessment, grounded_by_axis=grounded_by_axis,
        confidence_tier=confidence_tier)


def test_header_surfaces_deterministic_tier_and_flags_ai_provenance():
    """Review S1/G1: the header must NOT present the LLM 'confidence: high' as the headline. It shows
    the deterministic confidence_tier as primary, marks the recommendation AI-proposed, and (when a
    hypothesis ran) reconciles with the integrator verdict so the top line doesn't silently contradict
    the section below."""
    h = _render2(hypothesis=_HYP, confidence_tier={"tier": "moderate"})
    assert "AI-proposed" in h                              # recommendation provenance explicit
    assert "deterministic tier" in h and "moderate" in h   # deterministic confidence surfaced
    assert 'AI narrative said' in h                        # LLM 'high' shown only as transparent secondary
    assert "Cross-evidence integrator:" in h and "Advanceable" in h   # reconciliation line
    assert "✓ gate-checked" in h                           # not "rule-checked" (over-claims determinism)


def test_malformed_risk_assessment_does_not_crash_dashboard():
    """A parseable-but-wrong-shape risk_assessment degrades the panel to 'not shown', never losing the
    whole report (review S1). dimensions-as-list and a non-dict dimension value are both tolerated."""
    for bad in ({"dimensions": ["not", "a", "dict"]},
                {"dimensions": {"biological": "a string, not a dict"}},
                {"dimensions": {"safety": {"risk_level": None}}}):
        h = _render2(risk_assessment=bad)
        assert "id=s-evidence" in h            # the rest of the dashboard still renders
        assert "<html" in h and "</html>" in h


def test_malformed_hypothesis_falls_back_to_exec_summary():
    h = _render2(hypothesis={"hypothesis": {"evidence_grade": {"per_line": "not-a-list"}},
                             "verdict": "not-a-dict"})
    # panel failed → falls back to the Tier-3 exec summary rather than losing the synthesis entirely
    assert "id=s-exec" in h and "Executive summary" in h
    assert "<html" in h and "</html>" in h


def test_malformed_grounded_record_does_not_crash():
    h = _render2(grounded_by_axis={"safety": {"axis": "safety", "grounded": True}})  # grounded a bool
    assert "id=s-evidence" in h and "</html>" in h


def test_literature_risk_grade_is_case_insensitive():
    ra = {"indication": "colorectal cancer",
          "dimensions": {"safety": {"pillar": "Right Safety", "risk_level": "low",
                                    "interpretation": "x", "justification": "y", "cited_pmids": ["1"]}},
          "provenance": {"corpus_pin": {"mindate": "2015", "maxdate": "2026"}}}
    h = _render2(risk_assessment=ra)
    assert "chip-pos" in h            # lowercase 'low' normalized to the positive LOW chip
    assert ">None<" not in h          # never leaks the literal token


def test_groundable_axes_parity_with_axis_config():
    """Drift-guard (review S2.4): _GROUNDABLE_AXES must equal ground_axis.AXIS_CONFIG's verdict_key-
    bearing (non-pseudo-card) axes, so a new grounded axis can't silently mis-render."""
    import importlib.util
    ga = Path(__file__).resolve().parents[2] / "literature-risk-assessment" / "scripts" / "ground_axis.py"
    spec = importlib.util.spec_from_file_location("ground_axis_probe", ga)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    groundable = {k for k, v in m.AXIS_CONFIG.items() if v.get("verdict_key")}
    # _GROUNDABLE_AXES is private (not re-exported by run.py's `import *`) — read the render module.
    rh_path = Path(__file__).resolve().parent.parent / "scripts" / "tp_render_html.py"
    rspec = importlib.util.spec_from_file_location("tp_render_html_probe", rh_path)
    rh = importlib.util.module_from_spec(rspec)
    rspec.loader.exec_module(rh)
    assert rh._GROUNDABLE_AXES == groundable, \
        f"_GROUNDABLE_AXES drifted from AXIS_CONFIG: {rh._GROUNDABLE_AXES ^ groundable}"
