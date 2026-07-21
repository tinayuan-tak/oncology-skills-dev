"""Static HTML target-profile report + honest gate scorecard (2026-07-20).

Pins the two honesty-critical properties of the HTML artifact:
  1. the scorecard is a PROJECTION of the nomination-gate policy (can't diverge from the verdict),
     shows EVERY registry sub-skill grouped by gate (a gate with no sub-verdict this run still
     appears, greyed), and maps status to the 4-state chip so a coverage gap is NEVER an opposing;
  2. the HTML is static self-contained (no external src/link/cdn/script), LLM sections are tinted
     + separated from deterministic ones, the ordinal disclaimer survives, and it's well-formed.
All Bedrock-free (render from synthetic sub_results/nomination dicts).
"""
from __future__ import annotations

import importlib.util
import re
from html.parser import HTMLParser
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
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {},
                                  "provenance": {"input_manifest_ids": ["depmap-consortium-26q1"]}}],
                       "verdict": ("lineage_selective", "lineage-selective-supportive"),
                       "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"})},
        "safety": {"skill_dir": "on-target-safety-liability",
                   "cards": [{"card_id": "g", "summary": {},
                              "provenance": {"input_manifest_ids": ["gnomad-v4"]}}],
                   "verdict": ("highly_constrained_safety_concern", "highly-constrained-safety-warning"),
                   "fired": _fired({"small_molecule": "opposing"})},
    }


_LLM = {"executive_summary": {"value": "KRAS is modality-constrained.", "_prompt_hash": "abc"},
        "overall_recommendation": {"value": "hold"}, "confidence": {"value": "high"},
        "tension_analysis": {"value": "t"}}
_DA = {"basis": "gate_fired", "routing": "decided by gate F (Safe): safety forced 'hold'.",
       "deciding_axis": {"gate": "F", "gate_name": "Safe", "short": "safety",
                         "framework_can_evidence": "partial"}}


# ---------- scorecard ----------

def test_scorecard_includes_every_registry_sub_skill_even_when_absent():
    """Rows come from the gate registry, NOT from iterating sub_results — a sub-skill with no
    verdict this run still appears (greyed), so the gates we're blind on are never dropped."""
    sc = tp._gate_scorecard(_sr(), _DA)
    shorts = {r["short"] for r in sc}
    # dependency + safety produced verdicts; the rest are registry gates with no sub_result → present anyway
    assert {"dependency", "safety"} <= shorts
    assert {"expression", "surface_modality", "differentiation", "mechanism"} <= shorts, \
        "registry gates with no sub_result this run must still be rows"
    # every row has a gate letter A..H
    assert all(r["gate"] in set("ABCDEFGH") for r in sc)


def test_scorecard_status_is_4state_and_gap_is_not_opposing():
    sc = {r["short"]: r for r in tp._gate_scorecard(_sr(), _DA)}
    # safety fired a hold (a kill tuple) → opposing
    assert sc["safety"]["status"] == "opposing"
    assert sc["safety"]["is_deciding"] is True
    # a registry gate with no sub_result → coverage_gap, NOT opposing (we didn't look ≠ negative)
    assert sc["surface_modality"]["status"] == "coverage_gap"
    assert sc["surface_modality"]["status"] != "opposing"
    # dependency lineage_selective is a curated positive → supportive
    assert sc["dependency"]["status"] == "supportive"


def test_scorecard_supportive_requires_curated_positive_not_just_measured():
    """A measured verdict that is neither a kill nor a curated positive is 'neutral', not
    'supportive' — the chip can't over-claim."""
    sr = {"mechanism": {"skill_dir": "mechanism-and-pharmacology", "cards": [],
                        "verdict": ("well_characterized", "x"), "fired": []}}
    sc = {r["short"]: r for r in tp._gate_scorecard(sr, None)}
    assert sc["mechanism"]["status"] in ("neutral", "supportive")  # not opposing, not gap
    # and an insufficient verdict is a coverage gap
    sr2 = {"mechanism": {"skill_dir": "m", "cards": [], "verdict": ("insufficient", None), "fired": []}}
    sc2 = {r["short"]: r for r in tp._gate_scorecard(sr2, None)}
    assert sc2["mechanism"]["status"] == "coverage_gap"


# ---------- HTML ----------

def _html():
    sr = _sr()
    return tp._render_target_profile_html(
        "KRAS", "COADREAD", sr, _LLM, {},
        deciding_axis=_DA, ordinal_matrix=tp._ordinal_matrix(sr),
        scorecard=tp._gate_scorecard(sr, _DA),
        catalogue_rows=tp._catalogue_rows_from_sub_results(sr))


def test_html_is_static_self_contained():
    """The DEFAULT (no card_figures) path is the static fallback: self-contained, and — because no
    interactive figure was produced — carries NO JS at all. (The dynamic path adds inline JS; that's
    tested separately.)"""
    h = _html()
    # zero external references — no CDN, no external stylesheet, no script src, no http(s) src
    assert re.search(r"src=[\"']https?://", h) is None
    assert "<link" not in h
    assert re.search(r"<script[ >]", h) is None    # no JS in the static fallback
    assert "cdn." not in h
    assert h.startswith("<!DOCTYPE")


def test_html_llm_sections_tinted_and_separated():
    h = _html()
    assert h.count("class=llm") >= 2               # exec summary + tension in tinted panels
    # LLM sections carry an AI-authorship tag; deterministic sections carry a computed-from tag —
    # the two provenance classes are visually distinct (the honesty separation).
    assert "AI-generated" in h
    assert "Computed from the evidence" in h
    assert "class=det" in h                        # deterministic sections marked
    assert "Gate scorecard" in h


def test_html_scorecard_and_matrix_honesty_survives():
    h = _html()
    assert "chip-gap" in h                          # coverage-gap chip rendered
    assert "coverage gap" in h                      # the "not a negative" framing
    assert "NOT calibrated" in h                    # ordinal-matrix disclaimer
    assert "the verdict, not a cell, is the call" in h   # matrix subtitle carries the honesty note


def test_composite_svg_not_embedded_scorecard_is_the_glance():
    """The composite-panel SVG (a slide-sized matplotlib text-badge grid) is deliberately NOT
    embedded in the web report — it rendered poorly. The scorecard is the native-HTML at-a-glance.
    (The SVG remains a .md/PPT slide asset; passing composite_svg_path must not inject it.)"""
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        svg = pathlib.Path(d) / "panel.svg"
        svg.write_text('<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"><text>SLIDE</text></svg>')
        sr = _sr()
        h = tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {},
                                           scorecard=tp._gate_scorecard(sr, _DA),
                                           composite_svg_path=svg)
    assert "SLIDE" not in h and "<svg" not in h    # the slide SVG is NOT injected
    assert "Gate scorecard" in h                    # the scorecard is the at-a-glance instead


def test_exec_summary_is_first_content_section():
    """Executive summary leads (right after the header), before the scorecard."""
    h = _html()
    assert h.index("id=s-exec") < h.index("id=s-scorecard")


def test_evidence_by_question_section_present():
    """The per-question card-DATA section renders (summaries from the run)."""
    h = _html()
    assert "id=s-evidence" in h
    assert "Evidence by question" in h


def test_language_is_humanized_no_raw_tokens_leak():
    """Reader-facing labels are plain English; internal identifiers are humanized (raw snake_case
    verdict/gate tokens must not appear as bare cell text)."""
    h = _html()
    assert "Functional dependency" in h            # gate short → human label
    assert "Not evaluated" in h                     # coverage_gap → human
    # a couple of raw tokens that must NOT appear as visible text
    assert "framework_can_evidence" not in h
    assert "coverage_gap" not in h                  # the status key is a CSS class only, not shown


def test_header_jargon_glossed():
    """Header terms are reader-friendly: the action carries a plain gloss, 'AI-generated' is the
    consistent term (not 'LLM-synthesized'), and 'gate-clamped' is gone (→ a rule-checked badge)."""
    h = _html()  # _LLM action is 'hold'
    assert "do not advance yet" in h               # 'hold' glossed inline
    assert "AI-generated" in h
    assert "LLM-synthesized" not in h              # converged away
    assert "gate-clamped" not in h                 # jargon removed
    assert "rule-checked" in h                     # replaced by the badge


def test_band_jargon_fully_removed():
    """necessity/sufficiency jargon is gone AND the band-question glosses were removed per user
    (no 'Is it real biology?' / 'Will it become a drug?' either)."""
    h = _html()
    assert ">necessity<" not in h.lower() and ">sufficiency<" not in h.lower()
    assert "Is it real biology" not in h
    assert "Will it become a drug" not in h


def test_tension_renamed_to_plain_english():
    h = _html()
    assert "Conflicting signals" in h
    assert "Tension analysis" not in h


def test_scorecard_cross_references_are_shown():
    """Display cross-refs surface signals that live under one gate but feed another (logic
    unchanged): biomarker-stratified (under genomic) notes it feeds Dependency; tractability
    notes it also confirms Dependency (the PRISM dual-role)."""
    # a genomic row with a biomarker verdict + a tractability row
    sr = {
        "genomic_alteration": {"skill_dir": "genomic-alteration-profile", "cards": [],
                               "verdict": ("biomarker_stratified_dependency", "x"), "fired": []},
        "tractability_sm": {"skill_dir": "tractability-small-molecule", "cards": [],
                            "verdict": ("well_covered", "y"), "fired": []},
    }
    h = tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {},
                                       scorecard=tp._gate_scorecard(sr, None))
    assert "feeds Dependency" in h
    assert "also confirms Dependency" in h


def test_redundant_subverdicts_section_removed():
    """The standalone Sub-verdicts table is gone — the scorecard is the single per-question view."""
    h = _html()
    assert "id=s-subverdicts" not in h


def test_deciding_axis_hidden_by_default_but_toggleable():
    """The deciding-axis section is HIDDEN by default (its router logic can over-claim on a thin
    single-dataset gate — a known backlog fix), yet the data is still passed + the section renders
    when explicitly enabled. Guards the default + the toggle."""
    sr = _sr()
    common = dict(deciding_axis=_DA, scorecard=tp._gate_scorecard(sr, _DA))
    hidden = tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {}, **common)
    shown = tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {},
                                           show_deciding_axis=True, **common)
    assert "id=s-deciding" not in hidden          # default: not rendered
    assert "id=s-deciding" in shown               # toggle re-enables (for post-logic-fix)


def test_html_wellformed_parses():
    HTMLParser().feed(_html())   # raises on malformed structure


def test_html_additive_without_optional_sections():
    sr = _sr()
    h = tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {})  # no scorecard/da/matrix
    assert h.startswith("<!DOCTYPE") and "</html>" in h
    assert "Gate scorecard" not in h                # omitted cleanly
    assert "Recommendation" in h                    # core still renders
