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
    # 2026-08-18 simplification: the banner shows Verdict + confidence + promotable only; the dense
    # ceiling / clause-traceability / coherence-violations metadata was removed as low-value jargon.
    h = _render(hypothesis=_HYP)
    assert "Advanceable" in h                       # humanized computed verdict (banner lead)
    assert "promotable" in h                        # defensibility still surfaced, plainly
    assert "Run an isogenic mutant-vs-WT organoid panel." in h   # go_forth
    assert "No actionable SL partner mapped in COADREAD." in h    # tensions inside the section
    assert "clause-traceability" not in h           # dense metadata jargon removed


def test_hypothesis_cites_and_flags_countervailing():
    h = _render(hypothesis=_HYP)
    assert "signaling-network-mechanism" in h       # a supporting citation chip
    assert "Countervailing" in h and "partner-conditional-dependency" in h  # contradicting-citation flag


def test_deterministic_recommendation_not_in_header_when_hypothesis_present():
    """2026-08-18 redesign: the header is HYPOTHESIS-LED — it leads with the integrator verdict and
    does NOT show the deterministic scalar at all (it under-called + confused). The scalar lives in the
    detail sections below, not the top-line."""
    h = _render(hypothesis=_HYP)
    head = h.split("<div class=rec>", 1)[1].split("</header>", 1)[0]
    assert "Advanceable" in head                       # hypothesis verdict leads
    assert "Nominate" not in head and "engine:" not in head   # deterministic scalar dropped from the header


def test_no_hypothesis_keeps_original_executive_summary():
    h = _render(hypothesis=None)
    assert "id=s-exec" in h and "Executive summary" in h
    assert "id=s-hypothesis" not in h


# ---------- review fixes: header coherence / robustness / drift-guard ----------

def _render2(hypothesis=None, risk_assessment=None, grounded_by_axis=None, confidence_tier=None,
             risk_rollup=None, addressable_population=None):
    sc = tp._gate_scorecard(_sr(), None)
    return tp._render_target_profile_html(
        "KRAS", "COADREAD", _sr(), _LLM, {}, scorecard=sc, hypothesis=hypothesis,
        risk_assessment=risk_assessment, grounded_by_axis=grounded_by_axis,
        confidence_tier=confidence_tier, risk_rollup=risk_rollup,
        addressable_population=addressable_population)


_AP = {"addressable_population_class": "broad", "selection_basis": "snv_indel_stratified",
       "biomarker_prevalence": 0.435, "prevalence_source": "genie", "n_samples_in_indication": 559,
       "_note": None}


def test_addressable_population_section_is_not_rendered():
    """2026-08-18: the addressable-population section was removed from the dashboard (not ready for
    prime time). The helper + param are retained, but the section must NOT appear even when data is
    supplied — this guards against it silently reappearing."""
    assert "id=s-population" not in _render2(addressable_population=_AP)
    assert "id=s-population" not in _render2(addressable_population=None)


def test_malformed_addressable_population_does_not_crash():
    h = _render2(addressable_population={"biomarker_prevalence": "not-a-number"})
    assert "id=s-evidence" in h and "</html>" in h


def test_header_is_hypothesis_led_and_demotes_the_deterministic_scalar():
    """2026-08-18 redesign: the header LEADS with the cross-evidence integrator verdict + its
    confidence; the deterministic recommendation is DEMOTED to a small 'engine:' chip (the single
    scalar can under-call mutant-selective targets). The old 'deterministic tier / AI narrative said /
    reconciliation line' clutter is gone."""
    h = _render2(hypothesis=_HYP, confidence_tier={"tier": "moderate"})
    head = h.split("<div class=rec>", 1)[1].split("</header>", 1)[0]
    assert "Advanceable" in head                           # integrator verdict is the lead
    assert "cross-evidence integrator" in head
    assert "engine:" not in head                           # deterministic scalar dropped from the header
    assert "low" in head                                   # hypothesis certainty (NOT the LLM 'high')
    # the old clutter is gone
    assert "deterministic tier" not in head and "AI narrative said" not in head


def test_malformed_risk_assessment_does_not_crash_dashboard():
    """A parseable-but-wrong-shape risk_assessment degrades the panel to 'not shown', never losing the
    whole report. dimensions-as-list and a non-dict dimension value are both tolerated."""
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


_RR = {
    "biological": {"pillar": "Right Target", "bin": "LOW", "chain": ["mutant-conditioned dependency"],
                   "engine_literature_discordance": True, "blind_spots": ["in-vivo"]},
    "druggability": {"pillar": "Right Molecule", "bin": "LOW", "chain": ["clinical allele-specific SM"]},
    "safety": {"pillar": "Right Safety", "bin": "MED", "chain": ["WT constraint"], "blind_spots": ["ocular", "gi"]},
    "clinical": {"pillar": "Right Patient (clinical precedent)", "bin": "ENGINE-BLIND", "chain": []},
}


def test_deterministic_risk_rollup_lead_renders():
    """The deterministic 'Risk by category' 5R lead table renders (reproducible spine), with bins as
    chips, engine-blind shown as 'not evidenced', and the literature-diverges flag — leading ABOVE the
    non-reproducible literature panel."""
    h = _render2(risk_rollup=_RR)
    assert "id=s-risk-rollup" in h
    assert "Risk by category" in h and "reproducible" in h
    assert "not evidenced" in h                      # engine-blind clinical
    assert "literature diverges" in h                # biological discordance flag
    # deterministic lead is positioned ABOVE the literature-context panel
    ra = {"indication": "x", "dimensions": {"safety": {"pillar": "p", "risk_level": "LOW",
          "interpretation": "i", "justification": "j", "cited_pmids": []}},
          "provenance": {"corpus_pin": {}}}
    h2 = _render2(risk_rollup=_RR, risk_assessment=ra)
    assert h2.index("id=s-risk-rollup") < h2.index("id=s-litrisk")


def test_risk_rollup_absent_no_section():
    assert "id=s-risk-rollup" not in _render2(risk_rollup=None)


def test_malformed_risk_rollup_does_not_crash():
    h = _render2(risk_rollup={"safety": "not-a-dict", "biological": 123})
    assert "id=s-evidence" in h and "</html>" in h


def test_groundable_axes_parity_with_axis_config():
    """Drift-guard: _GROUNDABLE_AXES must equal ground_axis.AXIS_CONFIG's verdict_key-
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


# ---------- per-subskill card-board summary graphic ----------
import sys as _sys
_TPH = _sys.modules["tp_render_html"]  # the render module run.py imported


def test_presence_subskill_gets_card_board_summary_graphic():
    """The presence (expression) section leads with the card-board summary graphic — every card as a
    ternary signal / no-signal / not-measured, reading real card values."""
    sr = {"expression": {"skill_dir": "tumor-presence", "verdict": ("x", "y"), "fired": [], "cards": [
        {"card_id": "tumor-rna-distribution", "summary": {"tumor_expression_class": "broadly_high",
                                                          "n_tumor_samples": 300}},
        {"card_id": "tumor-rna-vs-adjacent", "summary": {"expression_call_class": "strong_down",
                                                         "q_value": 0.9}},
        {"card_id": "tumor-elevation-breadth", "summary": {"tumor_elevation_breadth_class": "data_unavailable"}},
    ]}}
    out = _TPH._subskill_summary_svg_html("expression", sr, {}, "KRAS", "COADREAD")
    h = "".join(out)
    assert "card board" in h and "Signal summary" in h
    assert "●" in h and "○" in h and "▨" in h   # signal + no-signal + not-measured all distinct


def test_non_presence_subskill_has_no_summary_graphic_yet():
    # other subskills slot in as their card->claim maps are authored; until then, render nothing.
    sr = {"safety": {"cards": [{"card_id": "gnomad", "summary": {}}]}}
    assert _TPH._subskill_summary_svg_html("safety", sr, {}, "KRAS", "COADREAD") == []


def test_summary_graphic_empty_when_no_cards():
    assert _TPH._subskill_summary_svg_html("expression", {"expression": {"cards": []}}, {}, "K", "C") == []
