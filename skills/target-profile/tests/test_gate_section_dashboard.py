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
            {"card_id": "cellline-rna-distribution", "summary": expr},
            {"card_id": "cellline-protein-abundance", "summary": {"protein_expression_class": "broadly_moderate"}},
            {"card_id": "tumor-elevation-breadth",
             "summary": {"tumor_elevation_breadth_class": "multi_tumor_elevated",
                         "n_cohorts_elevated": 2, "rna_n_indications_elevated": 4}}],
            "verdict": ("broadly_high_expression", "expression-broadly-high-supportive"),
            "fired": [_fired("expression-broadly-high-supportive", "cellline-rna-distribution",
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
    assert "id=s-skill-expression" in h
    # one tab button per card (3 cards)
    assert h.count("data-panel=s-skill-expression-p") == 3
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
    assert "id=s-evidence" not in h         # Evidence summary gone
    assert "Evidence summary" not in h
    assert "id=s-litrisk" not in h          # literature panel gone
    # but the expression section + exec summary remain
    assert "id=s-skill-expression" in h and "Executive summary" in h


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
    assert "id=s-evidence" in h and "id=s-skill-expression" in h   # the Evidence-summary lens AND the subskill section


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


def test_dependency_section_renders():
    h = _render(_sr_required())
    assert "id=s-skill-dependency" in h and "Functional dependence" in h   # dependency subskill label


def test_dependency_and_sl_render_as_separate_flat_sections():
    """v-flat: NO gate-C unification. The dependency subskill + synthetic_lethal_partners each get
    their OWN flat section; the dependency corroboration facet (CRISPR×RNAi) now renders UNDER
    dependency (no longer routed out)."""
    h = _render(_sr_required())
    dep = re.search(r"<section id=s-skill-dependency\b.*?</section>", h, re.S).group(0)
    assert "CRISPR dependency" in dep        # primary dependency card
    assert "CRISPR×RNAi" in dep              # corroboration facet now stays under dependency
    # SL partners is its OWN section, not unified under dependency
    assert "id=s-skill-synthetic-lethal-partners" in h
    sl = re.search(r"<section id=s-skill-synthetic-lethal-partners\b.*?</section>", h, re.S).group(0)
    assert "SL partners" in sl
    assert "SL partners" not in dep          # not merged into dependency
    # mutation-stratified lives under genomic-alteration, not dependency
    assert "Mutation-stratified" not in dep


def test_genomic_alteration_renders_as_own_flat_section_with_its_facet():
    """v-flat: genomic_alteration gets its own section (id=s-skill-genomic-alteration); its
    mutation-stratified FACET now renders UNDER it — biomarker routing removed (item #4)."""
    h = _render(_sr_required())
    assert "id=s-skill-genomic-alteration" in h and "Genomic alteration" in h
    seg = re.search(r"<section id=s-skill-genomic-alteration\b.*?</section>", h, re.S).group(0)
    assert "Mutation-stratified" in seg      # facet now renders under its home section


def test_no_biomarker_section_facets_render_under_home_subskills():
    """Item #4: biomarker ROUTING removed. There is no separate Biomarker section; the facet cards
    render under their home subskill sections — mutation-stratified under genomic-alteration,
    CRISPR×RNAi under dependency."""
    h = _render(_sr_required())
    assert "id=s-gate-biomarker" not in h
    assert ">Biomarker<" not in h
    gen = re.search(r"<section id=s-skill-genomic-alteration\b.*?</section>", h, re.S).group(0)
    assert "Mutation-stratified" in gen      # stratification facet under its home
    dep = re.search(r"<section id=s-skill-dependency\b.*?</section>", h, re.S).group(0)
    assert "CRISPR×RNAi" in dep              # corroboration facet under its home


def test_dependency_section_lists_primary_and_facet_cards():
    """After the biomarker-routing removal (item #4), the dependency section lists BOTH its primary
    dependency cards AND the corroboration facet (CRISPR×RNAi) that used to be routed out."""
    h = _render(_sr_required())
    seg = re.search(r"<section id=s-skill-dependency\b.*?</section>", h, re.S).group(0)
    order = re.findall(r"<button class='tab[^>]*>([^<]+)", seg)
    assert "CRISPR dependency" in order      # primary dependency card
    assert "CRISPR×RNAi" in order            # facet now stays under dependency (not routed out)


# --- Surface-biologics — modality-fit gate (v2 axis 2) -----------------------

def _sr_surface():
    sr = _sr()
    sr["surface_modality"] = {"skill_dir": "surface-modality-fit", "cards": [
        {"card_id": "surface-topology-and-ptm", "summary": {"tm_pass_count": 1}},
        {"card_id": "surfaceome-family-classification", "summary": {"is_surface_protein": True}},
        {"card_id": "adc-tce-modality-fit", "summary": {"fit_class": "ADC_preferred"}}],
        "verdict": ("adc_favorable", "adc-favorable-supportive"), "fired": []}
    return sr


def test_surface_modality_section_renders_with_no_gate_letter():
    h = _render(_sr_surface())
    assert "id=s-skill-surface-modality" in h
    assert "Surface / biologics fit" in h                 # the subskill label
    assert "<span class=gate-letter></span>" not in h    # flat layout → no gate-letter square


def test_surface_composed_verdict_leads_inputs():
    """The composed adc-tce-modality-fit card (role 'composed') sorts FIRST + carries a 'verdict'
    badge; its input cards follow."""
    h = _render(_sr_surface())
    seg = h.split("id=s-skill-surface-modality")[1].split("</section>")[0]
    order = re.findall(r"<button class='tab[^>]*>([^<]+)", seg)
    assert order[0] == "ADC/TCE fit"        # composed verdict first
    assert "verdict</span>" in seg


def test_surface_modality_section_renders_composed_and_input_cards():
    """v-flat: the surface-modality section renders the composed ADC/TCE fit verdict card plus its
    input cards (topology, surfaceome family). The old lens-conditional 'Druggability' modality
    banner is gone in the flat layout."""
    h = _render(_sr_surface())
    seg = h.split("id=s-skill-surface-modality")[1].split("</section>")[0]
    for title in ("ADC/TCE fit", "Topology", "Surfaceome family"):
        assert title in seg, title
    assert "Druggability" not in seg        # no modality-relevance banner in the flat layout


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


def test_biology_subskill_sections_render_in_fanout_order():
    """v-flat: sections render one-per-subskill in fan-out order (expression → selectivity →
    dependency → … → mechanism), NOT grouped into A/B/C/D gate bands."""
    h = _render(_sr_all_gates())
    pos = {s: h.find(f"id=s-skill-{s}") for s in
           ("expression", "selectivity", "dependency", "mechanism")}
    assert all(v >= 0 for v in pos.values()), pos
    assert pos["expression"] < pos["selectivity"] < pos["dependency"] < pos["mechanism"]


def test_selective_and_mechanism_key_facts():
    h = _render(_sr_all_gates())
    # split on the SECTION tag (not the nav href='#s-skill-selectivity' which also contains the id)
    b = re.search(r"<section id=s-skill-selectivity\b.*?</section>", h, re.S).group(0)
    assert "Selectivity" in b and "Cells supporting" in b
    d = re.search(r"<section id=s-skill-mechanism\b.*?</section>", h, re.S).group(0)
    assert "Network" in d and "Upstream" in d


def test_absent_gate_is_skipped():
    """A subskill absent this run renders no section (not an empty one)."""
    sr = _sr()   # has expression + dependency (bare) but no selectivity/mechanism/surface
    del sr["dependency"]
    h = _render(sr)
    assert "id=s-skill-selectivity" not in h and "id=s-skill-mechanism" not in h
    assert "id=s-skill-surface-modality" not in h
    assert "id=s-skill-expression" in h   # present one still renders


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
    sm = re.search(r"<section id=s-skill-tractability-sm\b.*?</section>", h, re.S).group(0)
    order = re.findall(r"<button class='tab[^>]*>([^<]+)", sm)
    assert order[0] == "Compound activity"                 # primary tractability evidence first
    assert "Chemical-genetic" in order and "Predictability" in order   # corroboration facets present
    assert "confidence</span>" in sm                        # facets carry the confidence badge


def test_safety_section_renders_constraint_key_facts():
    """v-flat: the safety section renders its gnomAD constraint key facts. (The old modality-fit
    'tiered severity' banner is gone in the flat layout.)"""
    h = _render(_sr_modality_fit())
    sf = re.search(r"<section id=s-skill-safety\b.*?</section>", h, re.S).group(0)
    assert "Constraint" in sf and "pLI" in sf
    assert "On-target safety" in sf         # the subskill label
    assert "tiered severity" not in sf      # modality banner removed


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
    """The Evidence summary is the top-level lens: each subskill row links down to its rendered
    flat section (s-skill-*)."""
    h = _render(_sr_full())
    sc = re.search(r"<section id=s-evidence.*?</section>", h, re.S).group(0)
    links = set(re.findall(r"href='#(s-skill-[^']+)'", sc))
    # every rendered subskill section is reachable from the Evidence summary
    for anchor in ("s-skill-expression", "s-skill-selectivity", "s-skill-dependency",
                   "s-skill-synthetic-lethal-partners", "s-skill-mechanism",
                   "s-skill-genomic-alteration", "s-skill-tractability-sm",
                   "s-skill-surface-modality", "s-skill-safety"):
        assert anchor in links, f"Evidence summary missing link to {anchor}"


def test_scorecard_does_not_link_unrendered_gate():
    """A subskill whose section did NOT render this run stays plain text (no dangling anchor)."""
    sr = _sr()   # only expression (+ bare dependency); no selectivity section
    del sr["dependency"]
    h = _render(sr)
    sc = re.search(r"<section id=s-evidence.*?</section>", h, re.S).group(0)
    assert "href='#s-skill-selectivity'" not in sc   # Selectivity didn't render → no link


# --- v2 axis-band grouping ---------------------------------------------------

def test_sections_render_flat_no_axis_bands():
    """v-flat: NO 5R axis-band grouping — sections render flat, one per subskill, in fan-out order.
    The old <div class=axis-band> Biological/Druggability/Safety headers are gone."""
    sr = _sr_all_gates()
    sr["safety"] = _sr_modality_fit()["safety"]
    sr["tractability_sm"] = _sr_modality_fit()["tractability_sm"]
    h = _render(sr)
    assert "<div class=axis-band>" not in h   # the element (not the CSS rule) is gone
    # fan-out order: expression → selectivity → dependency → mechanism → tractability_sm → safety
    pos = {s: h.find(f"id=s-skill-{s}") for s in
           ("expression", "selectivity", "dependency", "mechanism", "tractability-sm", "safety")}
    assert all(v >= 0 for v in pos.values()), pos
    assert (pos["expression"] < pos["selectivity"] < pos["dependency"] < pos["mechanism"]
            < pos["tractability-sm"] < pos["safety"])


def test_axis_band_suppressed_in_presence_only():
    """The focused Presence view renders no axis-band chrome (single-section view)."""
    h = _render(_sr(), presence_only=True)
    assert "<div class=axis-band>" not in h   # the element, not the CSS rule
    assert "id=s-skill-expression" in h


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
    sm = re.search(r"<section id=s-skill-tractability-sm\b.*?</section>", h, re.S).group(0)
    assert "Also feeds" in sm and "(C)" in sm
    assert "href='#s-skill-dependency'" in sm   # breadcrumb links to the flat dependence section


def test_no_self_referential_breadcrumb():
    """A cross-section breadcrumb names a DIFFERENT section, never its own s-skill anchor. The
    dependency section carries facet breadcrumbs, but none point at its own s-skill-dependency id."""
    sr = _sr_required()
    h = _render(sr)
    dep = re.search(r"<section id=s-skill-dependency\b.*?</section>", h, re.S).group(0)
    assert "href='#s-skill-dependency'" not in dep


# --- rail key-metric humanization (no raw snake_case token leaks) ------------

def test_rail_key_metrics_humanize_enum_values():
    """Rail 'Key metrics' values must be human-readable — raw snake_case enum tokens
    (modest_upregulation, ...) must NOT leak into visible <b> text. Numbers pass through unformatted.
    Uses a REAL classifier label (modest_upregulation with a matching +log2FC) — not a fabricated
    class/value combo."""
    card = {"card_id": "tumor-rna-vs-adjacent",
            "summary": {"expression_call_class": "modest_upregulation", "log2_fc": 0.8, "q_value": 3e-6}}
    facts = dict(tp._card_key_facts(card))
    assert facts["Call"] == "Modest upregulation"   # humanized, not "modest_upregulation"
    assert facts["log2FC"] == "0.800"               # numbers preserved (positive lfc = up, correct)
    # and a full render carries no raw snake_case token in a rail value
    import re
    h = _render(_sr())
    assert not re.findall(r"<b>[a-z]+_[a-z_]+</b>", h), "raw snake_case token leaked into a rail value"


# --- provenance trace section (the full skill run) ---------------------------

def test_provenance_trace_section_renders_run():
    """The provenance trace lists each sub-skill, its cards + data sources, and fired rules —
    a projection of sub_results, collapsed at the bottom (reference material)."""
    h = _render(_sr())
    assert "id=s-provenance" in h and "Provenance trace" in h
    seg = re.search(r"<section id=s-provenance\b.*?</section>", h, re.S).group(0)
    assert "<details>" in seg                       # collapsed by default
    # names the sub-skills + their cards
    assert "expression" in seg and "dependency" in seg
    assert "cellline-rna-distribution" in seg          # a resolved card_id appears
    assert "trace-cards" in seg                       # the per-card table


def test_provenance_trace_suppressed_in_presence_only():
    h = _render(_sr(), presence_only=True)
    assert "id=s-provenance" not in h


# --- NEW: per-subskill grounded literature block -----------------------------

def _grounded_safety_record():
    return {"grounded": {
        "anchor_verdict": "highly_constrained_safety_concern",
        "corpus_pin": {"mindate": "2015/01/01", "maxdate": "2026/01/01"},
        "n_retrieved": 12, "confabulated_dropped": ["999"],
        "findings": [{"kind": "liability", "finding": "cardiotoxic in conditional-KO mice",
                      "cited_pmids": [44445555]}],
        "corroborations": ["consistent with gnomAD constraint"]}}


def test_grounded_block_renders_in_safety_section_when_passed():
    """NEW per-subskill grounded block: passing grounded_by_axis={'safety': <rec>} renders an
    escalate-only 'Grounded findings' block inside the safety section, with PubMed-linked PMIDs."""
    h = _render(_sr_modality_fit(),
                grounded_by_axis={"safety": _grounded_safety_record()})
    sf = re.search(r"<section id=s-skill-safety\b.*?</section>", h, re.S).group(0)
    assert "class=grounded" in sf
    assert "Grounded findings" in sf
    assert "escalate-only" in sf
    assert "pubmed.ncbi.nlm.nih.gov/44445555" in sf   # a cited PMID links out


def test_groundable_axis_without_record_renders_no_block():
    """A groundable axis (dependency/safety) with NO record passed renders nothing (not a false
    gap) — the block is opt-in."""
    h = _render(_sr_modality_fit())   # no grounded_by_axis
    sf = re.search(r"<section id=s-skill-safety\b.*?</section>", h, re.S).group(0)
    assert "class=grounded" not in sf


def test_nongroundable_axis_renders_not_configured_note():
    """A subskill whose axis is NOT groundable (e.g. expression) renders an honest
    'not yet configured' grounding note (coverage-gap honesty), even with no record."""
    h = _render(_sr())
    expr = re.search(r"<section id=s-skill-expression\b.*?</section>", h, re.S).group(0)
    assert "grounded-none" in expr
    assert "not yet configured" in expr


# --- NEW: gateless subskills get their own flat sections ---------------------

def test_target_intrinsic_and_combinatorial_get_own_sections():
    """v-flat: the gateless subskills target_intrinsic + combinatorial_dependency (previously
    section-less under the gate-band layout) now each get their OWN flat s-skill-* section."""
    sr = _sr()
    sr["combinatorial_dependency"] = {"skill_dir": "combinatorial-dependency",
        "cards": [{"card_id": "combo-crispr-screen", "summary": {}}],
        "verdict": ("has_combo_partner", "r"), "fired": []}
    sr["target_intrinsic"] = {"skill_dir": "target-intrinsic",
        "cards": [{"card_id": "target-intrinsic-dossier", "summary": {}}],
        "verdict": None, "fired": []}
    h = _render(sr)
    assert "id=s-skill-combinatorial-dependency" in h
    assert "Combinatorial dependency (dual-KO)" in h
    assert "id=s-skill-target-intrinsic" in h
    assert "Target-intrinsic dossier" in h
