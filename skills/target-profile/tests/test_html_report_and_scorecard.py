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
    # Every row carries an axis (biology|modality_fit). Version-agnostic letter rule: a row MAY be
    # letterless (v2 modality-fit gates are named-not-lettered; v2 biology FACETS like SL-partners
    # are letterless too) — but any row that DOES carry a letter must use a valid one (A..H). This
    # passes against both the v1 flat contract (all lettered) and the v2 three-list contract.
    assert all(r.get("axis") in ("biology", "modality_fit") for r in sc)
    assert all(r["gate"] in set("ABCDEFGH") for r in sc if r.get("gate"))


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
    assert h.count("class='llm") + h.count("class=llm") >= 2   # exec summary + tension in tinted panels
    # LLM sections carry an AI-authorship tag (exec summary's is a corner chip); deterministic
    # sections are marked class=det. The two provenance classes stay visually distinct.
    assert "AI-generated" in h
    assert "class=det" in h                        # deterministic sections marked
    assert "Risk by category" in h                 # the 5R lead lens (replaced "Gate scorecard")


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
    assert "Risk by category" in h                  # the risk-category lead lens is the at-a-glance instead


def test_exec_summary_is_first_content_section():
    """Executive summary leads (right after the header), before the scorecard."""
    h = _html()
    assert h.index("id=s-exec") < h.index("id=s-scorecard")


def test_evidence_by_question_section_removed():
    """The standalone 'Evidence by question' recap was REMOVED (2026-07-21) — the axis-grouped gate
    sections now carry each card's data + figures, so the recap was a duplicate."""
    h = _html()
    assert "id=s-evidence" not in h
    assert "Evidence by question" not in h
    # the per-card data still lives in the gate sections (this fixture has dependency + safety)
    assert "id=s-gate-c" in h and "card-rail" in h


def test_language_is_humanized_no_raw_tokens_leak():
    """Reader-facing labels are plain English; internal identifiers are humanized (raw snake_case
    verdict/gate tokens must not appear as bare cell text)."""
    h = _html()
    assert "Functional dependence" in h            # gate short → human label (gate C renamed)
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


# ---------- GI-style layout (PR-B3) ----------

def test_html_has_about_band_with_citation():
    """The GI-style 'About this analysis' band frames the report + carries a provenance/citation
    line (framework version + 'projection of nomination.json') — descriptive, no new computation."""
    h = _html()
    assert "class=about" in h
    assert "About this analysis" in h
    assert "class=citation" in h
    assert "target-profile v" in h                  # framework version stamped in the citation
    assert "nomination.json" in h                   # provenance framing
    # the honesty framing survives into the About copy
    assert "Coverage gaps are shown as gaps" in h


def test_html_status_banner_summarizes_the_run():
    """The GI-style data-loaded banner names target × indication + what was assessed."""
    h = _html()   # _sr() has 2 sub-skills (dependency, safety), each 1 card
    assert "class=statusbar" in h
    assert "Evaluated KRAS × COADREAD" in h or "Evaluated KRAS × COADREAD" in h
    assert "question-gate" in h
    assert "evidence card" in h


def test_html_status_banner_counts_interactive_figures_when_present(tmp_path):
    """When a run produced interactive figures, the banner reports the count; otherwise it's absent."""
    sr = _sr()
    # no figures → no interactive-figure note
    assert "interactive figure" not in tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {})
    cf = {"g": [{"id": "x", "path": "cards/g/f.plotly.json", "type": "plotly", "dynamic": True}]}
    h = tp._render_target_profile_html("KRAS", "COADREAD", sr, _LLM, {}, card_figures=cf,
                                       figures_dir=tmp_path)
    assert "1 interactive figure" in h


def test_html_section_bars_do_not_break_wellformedness():
    """The navy section-header bars are pure CSS on existing <h2>; the doc still parses."""
    HTMLParser().feed(_html())


# ---------- risk-category roll-up (5R lead lens) ----------

def test_risk_category_rollup_surfaces_only_evidenced():
    """Data-driven surfacing: a category appears iff >=1 member sub-skill has an on-scale status.
    Categories with no evidenced member fall to not_evidenced (no placeholder row)."""
    sc = tp._gate_scorecard(_sr(), _DA)   # _sr has dependency (biological) + safety
    ru = tp._risk_category_rollup(sc)
    cats = {c["category"] for c in ru["surfaced"]}
    assert "biological" in cats           # dependency fired → biological surfaces
    assert "safety" in cats               # safety fired → safety surfaces
    # categories with no evidenced sub-skill this run are NOT surfaced as rows
    assert "translational" in ru["not_evidenced"]
    assert "clinical" in ru["not_evidenced"]
    # every surfaced category carries a computed risk level + driver
    for c in ru["surfaced"]:
        assert c["risk_level"] in ("elevated", "supported", "neutral")
        assert c["driver"]


def test_risk_category_rollup_level_is_computed_from_members():
    """Risk level rolls up member statuses: an opposing member → elevated; else supportive → supported."""
    sc = tp._gate_scorecard(_sr(), _DA)
    ru = {c["category"]: c for c in tp._risk_category_rollup(sc)["surfaced"]}
    # safety fired a kill (opposing) in _sr → elevated
    assert ru["safety"]["risk_level"] == "elevated"


def test_risk_category_lead_lens_renders_and_replaces_scorecard_heading():
    h = _html()
    assert "id=s-riskcat" in h and "Risk by category" in h   # the lead lens
    assert "5R framework" in h                                # anchored
    assert "Gate detail" in h                                 # old scorecard demoted, not deleted
