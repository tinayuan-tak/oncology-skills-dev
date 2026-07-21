"""Gate-section dashboard: card-subtabbed gate sections + presence-only focused view (2026-07-21).

The presence gate (A / expression) renders as a section whose SUBTABS are its evidence cards; each
card panel is a 2-column body (plots left, summary rail right) with a verdict/rule strip, key facts,
an indication-lineage focus (COADREAD→Bowel) + human-readable interpretation, and the card's Plotly
figure. Pure projection — no recompute. `presence_only=True` is the focused view: clean "T × I"
header, no About/statusbar/scorecard, tab bootstrap always present.

Bedrock-free (synthetic sub_results + a fake figures dir; no S3, no plotly bundle assertions).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_gate", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _fired(rid, cid, sig):
    return {"rule_id": rid, "card_id": cid, "field": "f", "value": "v", "signals": sig}


def _sr(per_lineage=None):
    expr = {"expression_call_class": "broadly_high", "median_log2tpm_panel": 5.6, "n_cell_lines": 820}
    if per_lineage is not None:
        expr["per_lineage_stats"] = per_lineage
        expr["n_lineages_evaluated"] = len(per_lineage)
    return {
        "expression": {"skill_dir": "tumor-presence", "cards": [
            {"card_id": "expression-distribution", "summary": expr},
            {"card_id": "protein-abundance-celline", "summary": {"protein_expression_class": "broadly_moderate"}},
            {"card_id": "tumor-elevation-breadth",
             "summary": {"tumor_elevation_breadth_class": "multi_tumor_elevated",
                         "n_cohorts_elevated": 2, "rna_n_indications_elevated": 4}}],
            "verdict": ("broadly_high_expression", "expression-broadly-high-supportive"),
            "fired": [_fired("expression-broadly-high-supportive", "expression-distribution",
                             {"small_molecule": "supportive", "degrader": "supportive"}),
                      _fired("tumor-breadth-multi-supportive", "tumor-elevation-breadth",
                             {"small_molecule": "supportive"})]},
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {}}],
                       "verdict": ("lineage_selective", "lineage-selective-supportive"), "fired": []},
    }


_LLM = {"executive_summary": {"value": "KRAS broadly expressed.", "_prompt_hash": "x"},
        "overall_recommendation": {"value": "advance"}, "confidence": {"value": "moderate"},
        "tension_analysis": {"value": "—"}}


def _render(sr, **kw):
    return tp._render_target_profile_html("KRAS", "COAD", sr, _LLM, {},
                                          scorecard=tp._gate_scorecard(sr, None), **kw)


# --- gate section structure ---------------------------------------------------

def test_presence_gate_section_has_card_subtabs():
    h = _render(_sr())
    assert "id=s-gate-a" in h
    # one tab button per card (3 cards)
    assert h.count("data-panel=s-gate-a-p") == 3
    for title in ("Cell-line RNA", "Cell-line protein", "Pan-cancer breadth"):
        assert title in h, title


def test_card_panel_is_two_column_with_rail():
    h = _render(_sr())
    assert "card-body" in h and "card-plots" in h and "card-rail" in h
    # rail carries the rule-fired strip
    assert "Rule fired" in h and "expression-broadly-high-supportive" in h


def test_indication_lineage_focus_and_interpretation():
    per_lineage = [
        {"lineage": "Lung", "n": 90, "median_log2tpm": 6.1, "fraction_expressed": 0.95},
        {"lineage": "Bowel", "n": 103, "median_log2tpm": 5.55, "fraction_expressed": 0.99},
        {"lineage": "Skin", "n": 40, "median_log2tpm": 2.0, "fraction_expressed": 0.5},
    ]
    h = _render(_sr(per_lineage))
    assert "COAD focus (Bowel)" in h                       # indication → lineage
    assert "In Bowel cell lines" in h                       # human-readable interpretation
    assert "highly expressed" in h                          # bucketed level (median 5.55 ≥ 5)


def test_indication_focus_absent_when_lineage_below_floor():
    # per_lineage_stats present but Bowel absent (didn't clear n>=5) → honest 'not available' note
    per_lineage = [{"lineage": "Lung", "n": 90, "median_log2tpm": 6.1, "fraction_expressed": 0.95}]
    h = _render(_sr(per_lineage))
    assert "COAD focus (Bowel)" in h
    assert "isn't available" in h or "No Bowel cell-line cohort" in h


# --- presence-only focused view ----------------------------------------------

def test_presence_only_strips_full_report_sections():
    h = _render(_sr(), presence_only=True)
    assert "About this analysis" not in h
    assert "Evaluated " not in h            # statusbar gone
    assert "Gate scorecard" not in h        # scorecard gone
    assert "Risk by category" not in h
    # but the presence gate + exec summary remain
    assert "id=s-gate-a" in h and "Executive summary" in h


def test_presence_only_clean_header():
    h = _render(_sr(), presence_only=True)
    assert "<h1>KRAS" in h and "COAD</h1>" in h
    assert "target profile</h1>" not in h   # no verbose suffix
    assert "Recommendation:" not in h        # no rec clutter


def test_tab_bootstrap_always_present_when_gate_rendered():
    h = _render(_sr(), presence_only=True)
    assert "tabs-js" in h and "__resizePlots" in h   # tab JS + plotly resize hook


def test_full_report_still_renders_all_sections():
    h = _render(_sr(), presence_only=False)
    assert "id=s-riskcat" in h and "id=s-gate-a" in h   # both the risk-category lead lens AND the gate section


# --- Required (C) gate — v2 biomarker facets ---------------------------------

def _sr_required():
    """sub_results with Required (C) evidence scattered across 3 sub-skills (the v2 case)."""
    sr = _sr()
    sr["dependency"] = {"skill_dir": "functional-requirement", "cards": [
        {"card_id": "pan-cancer-crispr-dependency-distribution", "summary": {"dependency_class": "selective"}},
        {"card_id": "pan-cancer-rnai-dependency-distribution", "summary": {"dependency_class": "selective"}},
        {"card_id": "crispr-rnai-dependency-concordance", "summary": {"concordance_class": "concordant_dependent"}},
        {"card_id": "dependency-lineage-selectivity", "summary": {"lineage_selectivity_class": "lineage_selective"}},
        {"card_id": "paralog-buffering", "summary": {"paralog_buffering_class": "no_buffering"}}],
        "verdict": ("lineage_selective", "lineage-selective-supportive"),
        "fired": [_fired("concordant-dependent-supportive-dominant", "crispr-rnai-dependency-concordance",
                         {"small_molecule": "supportive"})]}
    sr["synthetic_lethal_partners"] = {"skill_dir": "synthetic-lethal-partners", "cards": [
        {"card_id": "synthetic-lethal-partners", "summary": {"sl_partner_class": "has_experimental_sl_partner"}}],
        "verdict": ("has_experimental_sl_partner", "sl-partner-supportive"), "fired": []}
    sr["genomic_alteration"] = {"skill_dir": "genomic-alteration-profile", "cards": [
        {"card_id": "mutation-stratified-dependency", "summary": {"mutation_stratification_class": "mutant_strongly_dependent"}}],
        "verdict": ("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"), "fired": []}
    return sr


def test_required_gate_section_renders():
    h = _render(_sr_required())
    assert "id=s-gate-c" in h and "Functional dependence" in h   # gate C renamed from "Required"


def test_required_unifies_dependency_and_sl_under_c():
    """v2: Required (C) unifies the dependency sub-skill + synthetic_lethal_partners. The
    genomic-alteration cards move to their OWN 'Altered' (E) gate (see below)."""
    h = _render(_sr_required())
    seg = h.split("id=s-gate-c")[1].split("</section>")[0]
    for title in ("CRISPR dependency", "SL partners"):
        assert title in seg, title
    # mutation-stratified is NO LONGER unified into C in v2 — it lives under Altered (E).
    assert "Mutation-stratified" not in seg


def test_genomic_alteration_renders_as_own_altered_gate_e():
    """v2: genomic_alteration is its OWN biology gate 'Altered' (E), not folded into Required.
    Its mutation-stratified card renders there + shows an 'Also feeds → Required (C)' breadcrumb."""
    h = _render(_sr_required())
    assert "id=s-gate-e" in h and "Altered" in h
    # split on the SECTION tag, not the scorecard's href='#s-gate-e' link (which also contains the id)
    seg = re.search(r"<section id=s-gate-e\b.*?</section>", h, re.S).group(0)
    assert "Mutation-stratified" in seg
    assert "Also feeds" in seg and "href='#s-gate-c'" in seg   # reports_into breadcrumb to Required


def test_required_orders_primary_before_corroboration_facets():
    """v2 ordering within Required: primary dependency cards first, then the corroboration
    (confidence-badged) CRISPR×RNAi facet."""
    h = _render(_sr_required())
    seg = h.split("id=s-gate-c")[1].split("</section>")[0]
    order = re.findall(r"<button class='tab[^>]*>([^<]+)", seg)
    assert order.index("CRISPR dependency") < order.index("CRISPR×RNAi")
    assert "confidence</span>" in seg   # the corroboration facet's badge


# --- Surface-biologics — modality-fit gate (v2 axis 2) -----------------------

def _sr_surface():
    sr = _sr()
    sr["surface_modality"] = {"skill_dir": "surface-modality-fit", "cards": [
        {"card_id": "surface-topology-and-ptm", "summary": {"tm_pass_count": 1}},
        {"card_id": "surfaceome-family-classification", "summary": {"is_surface_protein": True}},
        {"card_id": "adc-tce-modality-fit", "summary": {"fit_class": "ADC_preferred"}}],
        "verdict": ("adc_favorable", "adc-favorable-supportive"), "fired": []}
    return sr


def test_surface_modality_gate_renders_named_not_lettered():
    h = _render(_sr_surface())
    assert "id=s-gate-surface-biologics-fit" in h
    assert "Surface-biologics fit" in h
    assert "<span class=gate-letter></span>" not in h    # named gate → no empty letter square


def test_surface_composed_verdict_leads_inputs():
    """The composed adc-tce-modality-fit card (role 'composed') sorts FIRST + carries a 'verdict'
    badge; its input cards follow."""
    h = _render(_sr_surface())
    seg = h.split("id=s-gate-surface-biologics-fit")[1].split("</section>")[0]
    order = re.findall(r"<button class='tab[^>]*>([^<]+)", seg)
    assert order[0] == "ADC/TCE fit"        # composed verdict first
    assert "verdict</span>" in seg


def test_surface_gate_carries_modality_relevance_banner():
    """A modality-fit gate's relevance is lens-conditional — the section states which modalities."""
    h = _render(_sr_surface())
    seg = h.split("id=s-gate-surface-biologics-fit")[1].split("</section>")[0]
    assert "Modality-fit assessment" in seg and "ADC" in seg


# --- multi-gate sequence (B Selective + D Mechanism, clean biology gates) ----

def _sr_all_gates():
    sr = _sr_required()
    sr["selectivity"] = {"skill_dir": "tumor-selectivity", "cards": [
        {"card_id": "tumor-vs-normal-selectivity", "summary": {"selectivity_class": "strong_tumor_selective",
                                                               "cells_supporting": 3, "dominant_direction": "up"}}],
        "verdict": ("strong_tumor_selective", "strong-selective-supportive"), "fired": []}
    sr["mechanism"] = {"skill_dir": "mechanism-and-pharmacology", "cards": [
        {"card_id": "signaling-network-mechanism", "summary": {"network_class": "well_characterized",
                                                              "n_upstream_regulators": 12}}],
        "verdict": ("well_characterized", "network-well-characterized"), "fired": []}
    return sr


def test_biology_gates_render_in_A_B_C_D_order():
    h = _render(_sr_all_gates())
    positions = {g: h.find(f"id=s-gate-{g}") for g in ("a", "b", "c", "d")}
    assert all(v >= 0 for v in positions.values()), positions
    assert positions["a"] < positions["b"] < positions["c"] < positions["d"]


def test_selective_and_mechanism_key_facts():
    h = _render(_sr_all_gates())
    # split on the SECTION tag (not the nav href='#s-gate-b' which also contains the id)
    b = re.search(r"<section id=s-gate-b\b.*?</section>", h, re.S).group(0)
    assert "Selectivity" in b and "Cells supporting" in b
    d = re.search(r"<section id=s-gate-d\b.*?</section>", h, re.S).group(0)
    assert "Network" in d and "Upstream" in d


def test_absent_gate_is_skipped():
    """A gate whose sub-skills are all absent this run renders no section (not an empty one)."""
    sr = _sr()   # has expression + dependency (bare) but no selectivity/mechanism/surface
    del sr["dependency"]
    h = _render(sr)
    assert "id=s-gate-b" not in h and "id=s-gate-d" not in h
    assert "id=s-gate-surface-biologics-fit" not in h
    assert "id=s-gate-a" in h   # present one still renders


# --- remaining modality-fit gates: Small-molecule tractability + Safety ------

def _sr_modality_fit():
    sr = _sr()
    sr["tractability_sm"] = {"skill_dir": "tractability-small-molecule", "cards": [
        {"card_id": "prism-compound-activity", "summary": {"prism_activity_class": "active", "n_compounds_targeting": 7}},
        {"card_id": "prism-crispr-concordance", "summary": {"crispr_prism_concordance_class": "triangulated"}},
        {"card_id": "dependency-predictability", "summary": {"predictability_class": "own_omics_driven"}}],
        "verdict": ("chemically_confirmed_genetic", "r"), "fired": []}
    sr["safety"] = {"skill_dir": "on-target-safety-liability", "cards": [
        {"card_id": "gnomad-lof-constraint", "summary": {"constraint_class": "highly_constrained", "pli_score": 0.99}}],
        "verdict": ("highly_constrained_safety_concern", "r"), "fired": []}
    return sr


def test_small_molecule_gate_primary_leads_corroboration_facets():
    h = _render(_sr_modality_fit())
    sm = re.search(r"<section id=s-gate-small-molecule-druggability\b.*?</section>", h, re.S).group(0)
    order = re.findall(r"<button class='tab[^>]*>([^<]+)", sm)
    assert order[0] == "Compound activity"                 # primary tractability evidence first
    assert "Chemical-genetic" in order and "Predictability" in order   # corroboration facets present
    assert "confidence</span>" in sm                        # facets carry the confidence badge
    assert "small-molecule / degrader" in sm                # modality banner


def test_safety_gate_renders_with_tiered_banner():
    h = _render(_sr_modality_fit())
    sf = re.search(r"<section id=s-gate-safety\b.*?</section>", h, re.S).group(0)
    assert "Constraint" in sf and "pLI" in sf
    assert "tiered severity" in sf and "Modality-fit assessment" in sf


# --- roll-up lens: scorecard rows link down to their gate sections -----------

def _sr_full():
    """All sub-skills present → all gate sections render."""
    sr = _sr_all_gates()
    mf = _sr_modality_fit()
    sr["tractability_sm"] = mf["tractability_sm"]
    sr["safety"] = mf["safety"]
    sr["surface_modality"] = _sr_surface()["surface_modality"]
    return sr


def test_scorecard_rows_link_to_gate_sections():
    """The scorecard is the top-level lens: each question-row links down to its rendered gate section."""
    h = _render(_sr_full())
    sc = re.search(r"<section id=s-scorecard.*?</section>", h, re.S).group(0)
    links = set(re.findall(r"href='#(s-gate-[^']+)'", sc))
    # every rendered gate section is reachable from the scorecard
    for anchor in ("s-gate-a", "s-gate-b", "s-gate-c", "s-gate-d",
                   "s-gate-small-molecule-druggability", "s-gate-surface-biologics-fit", "s-gate-safety"):
        assert anchor in links, f"scorecard missing link to {anchor}"


def test_scorecard_does_not_link_unrendered_gate():
    """A sub-skill whose gate section did NOT render this run stays plain text (no dangling anchor)."""
    sr = _sr()   # only expression (+ bare dependency); no selectivity section
    del sr["dependency"]
    h = _render(sr)
    sc = re.search(r"<section id=s-scorecard.*?</section>", h, re.S).group(0)
    assert "href='#s-gate-b'" not in sc   # Selective didn't render → no link


# --- v2 axis-band grouping ---------------------------------------------------

def test_gate_sections_grouped_under_two_axis_bands():
    """v2 hybrid: gate sections render under two axis bands — Biology (necessity) then
    Modality fit (sufficiency) — and Biology precedes Modality fit."""
    sr = _sr_all_gates()
    sr["safety"] = _sr_modality_fit()["safety"]
    sr["tractability_sm"] = _sr_modality_fit()["tractability_sm"]
    h = _render(sr)
    assert "<div class=axis-band>" in h
    bio = h.find(">Biology ")
    mod = h.find(">Modality fit ")
    assert bio >= 0 and mod >= 0, (bio, mod)
    assert bio < mod, "Biology band must precede Modality-fit band"
    # the Present (A) SECTION sits after the Biology band + before the Modality-fit band; the Safety
    # SECTION sits after the Modality-fit band. Use the section-tag position, not the scorecard href.
    a_sec = re.search(r"<section id=s-gate-a\b", h).start()
    safety_sec = re.search(r"<section id=s-gate-safety\b", h).start()
    assert bio < a_sec < mod
    assert mod < safety_sec


def test_axis_band_suppressed_in_presence_only():
    """The focused Presence view renders no axis-band chrome (single-section view)."""
    h = _render(_sr(), presence_only=True)
    assert "<div class=axis-band>" not in h   # the element, not the CSS rule
    assert "id=s-gate-a" in h


# --- reports_into cross-gate breadcrumb --------------------------------------

def test_reports_into_breadcrumb_on_cross_gate_card():
    """A card whose home gate differs from a gate it feeds shows an 'Also feeds → <gate>' breadcrumb.
    prism-crispr-concordance lives under Small-molecule but also feeds gate C. The breadcrumb LINKS
    to the gate-C section + is labelled '(C)'; the label text itself is read from the contract's
    gate_name (which may be renamed on other branches), so we assert on the letter + link, not the
    exact name."""
    sr = _sr_required()
    sr["tractability_sm"] = _sr_modality_fit()["tractability_sm"]   # prism-crispr under SM
    h = _render(sr)
    sm = re.search(r"<section id=s-gate-small-molecule-druggability\b.*?</section>", h, re.S).group(0)
    assert "Also feeds" in sm and "(C)" in sm
    assert "href='#s-gate-c'" in sm   # links to the gate-C section (label tracks the contract name)


def test_no_self_referential_breadcrumb():
    """The breadcrumb names a DIFFERENT gate, never its own. Required (C) hosts dependency + SL
    (neither reports_into C from elsewhere) → no 'Also feeds' self-reference in the C section."""
    sr = _sr_required()
    h = _render(sr)
    c = re.search(r"<section id=s-gate-c\b.*?</section>", h, re.S).group(0)
    # C's own cards don't self-reference C; the only 'Also feeds' pointing at C comes from the
    # Altered (E) section's mutation-stratified card, which is a different section.
    assert "href='#s-gate-c'" not in c


# --- rail key-metric humanization (no raw snake_case token leaks) ------------

def test_rail_key_metrics_humanize_enum_values():
    """Rail 'Key metrics' values must be human-readable — raw snake_case enum tokens
    (modest_upregulation, ...) must NOT leak into visible <b> text. Numbers pass through unformatted.
    Uses a REAL classifier label (modest_upregulation with a matching +log2FC) — not a fabricated
    class/value combo."""
    card = {"card_id": "expression-tumor-vs-adjacent",
            "summary": {"expression_call_class": "modest_upregulation", "log2_fc": 0.8, "q_value": 3e-6}}
    facts = dict(tp._card_key_facts(card))
    assert facts["Call"] == "Modest upregulation"   # humanized, not "modest_upregulation"
    assert facts["log2FC"] == "0.800"               # numbers preserved (positive lfc = up, correct)
    # and a full render carries no raw snake_case token in a rail value
    import re
    h = _render(_sr())
    assert not re.findall(r"<b>[a-z]+_[a-z_]+</b>", h), "raw snake_case token leaked into a rail value"
