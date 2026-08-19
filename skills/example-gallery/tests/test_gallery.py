"""example-gallery HTML assembly — pure render test from a fixture decision.json (no S3/subprocess/LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_example_gallery as G  # noqa: E402


def _decision():
    return {
        "skill": "tumor-presence", "target": "CEACAM5", "indication": "COADREAD",
        "headline": {"presence_verdict": "lineage_restricted",
                     "driving_rule_id": "expression-lineage-restricted-supportive"},
        "llm_synthesis": {
            "expression_relevance_for_target": {"value": "strongly_supports", "_source": "llm_synthesized"},
            "relevance_rationale": {"value": "CEACAM5 sits in the top 1% of all genes...", "_source": "llm_synthesized"},
        },
        "cards": [
            {"card_id": "tumor-rna-distribution",
             "summary": {"tumor_expression_class": "broadly_high", "median_log2tpm": 10.99,
                         "allgene_percentile": 99.9, "_data_source": "allgene-tumor-rank-v1"}},
            {"card_id": "tumor-protein-abundance-cptac", "summary": {},
             "_missing": True, "_missing_reason": "no_cptac_cohort_for_indication"},
        ],
        "fired_rules": [
            {"rule_id": "expression-broadly-high-supportive", "card_id": "tumor-rna-distribution",
             "field": "tumor_expression_class", "value": "broadly_high", "dominant": True,
             "rationale_summary": "top-quartile broad expression"},
        ],
    }


def test_page_has_verdict_synthesis_and_card(tmp_path):
    page = G.render_page(_decision(), tmp_path, fig_map={}, interactive=False)
    # verdict + driving rule in the header
    assert "lineage_restricted" in page
    assert "expression-lineage-restricted-supportive" in page
    # exec summary surfaces the LLM narrative
    assert "strongly_supports" in page and "Summary" in page
    # tumor-presence LEADS with the 7-question summary table; the scope-hierarchical layout
    # (sample-context sections) is demoted to a drill-down below it.
    assert "Presence at a glance" in page and "Expressed in cancers at all?" in page
    assert "Detailed evidence by lens" in page and "Patient tumor" in page
    # headline chip value shown
    assert "broadly_high" in page
    # cards are COLLAPSIBLE (details.card) with a header summary
    assert '<details class="card"' in page and 'class="cardhead"' in page
    # per-card FLOW tabs present (all 5)
    assert 'class="flowtabs"' in page
    for tab in (">Data<", ">Method<", ">Measurement<", ">Rules<", ">Verdict<"):
        assert tab in page
    # the fired rule surfaces in the flow (Rules/Verdict tab)
    assert "expression-broadly-high-supportive" in page
    # full data still available behind a nested collapsible
    assert "show all fields" in page
    # missing card rendered honestly, not dropped
    assert "Data unavailable" in page and "no_cptac_cohort_for_indication" in page
    # zoomable figures scaffold + lightbox present
    assert "zbackdrop" in page
    # self-contained (no external asset refs)
    assert "<!DOCTYPE html>" in page and "src=\"http" not in page


def test_presence_hero_emitted_and_inlined_when_matrix_present(tmp_path):
    """A run whose decision carries presence_verdict_by_modality (tumor-presence) gets the
    Presence × Context hero: the SVG PERSISTS into run_dir/figures (→ publishes to S3) AND is
    inlined into the page. Gated on the field, not the skill name."""
    d = _decision()
    d["headline"]["presence_verdict_by_modality"] = {
        "bulk_rna/tumor": {"verdict": "tumor_broadly_expressed", "evidence_state": "measured",
                           "driving_rule_id": "expression-lineage-restricted-supportive"},
        "sc_rna/normal": {"verdict": "HIGH_LIABILITY", "evidence_state": "comparator",
                          "driving_rule_id": None},
    }
    page = G.render_page(d, tmp_path, fig_map={}, interactive=False)
    assert "Presence × context" in page
    assert 'class="hero-matrix"' in page
    assert "<svg" in page                                    # inlined
    # persisted into the run's figures/ so publish_run.py ships it
    assert (tmp_path / "figures" / "figure_presence_context_matrix.svg").exists()
    assert (tmp_path / "figures" / "presence_context_matrix.json").exists()


def test_presence_hero_absent_without_matrix(tmp_path):
    # the default fixture has no presence_verdict_by_modality → no hero (additive, gated)
    page = G.render_page(_decision(), tmp_path, fig_map={}, interactive=False)
    assert "hero-matrix" not in page
    assert not (tmp_path / "figures" / "figure_presence_context_matrix.svg").exists()


def test_headline_and_metrics_curation():
    # curated card: headline field + prettified key-metric labels
    s = {"expression_class": "broadly_high", "median_log2tpm_panel": 10.99, "allgene_percentile": 99.9,
         "fraction_expressed": 0.26}
    hl, kind, val = G._card_headline_html("cellline-rna-distribution", s, missing=False)
    assert val == "broadly_high" and kind == "good"
    m = G._key_metrics_html("cellline-rna-distribution", s)
    assert "Median log2TPM" in m and "All-gene %ile" in m   # pretty labels from CARD_DISPLAY
    assert "median_log2tpm" not in m                        # raw key not shown


def test_heuristic_headline_for_uncurated_card():
    # a card_id NOT in CARD_DISPLAY → heuristic picks the first *_class field
    assert G._headline_field("some-new-card", {"foo": 1, "widget_class": "hub", "bar_call": True}) == "widget_class"


def test_summary_table_skips_private_and_big_values():
    t = G._summary_table({"good_thing": 1, "_hidden": 2, "big": list(range(200))})
    assert "Good thing" in t and "_hidden" not in t   # prettified label; private hidden
    assert "list, 200 items" in t   # large list summarized, not dumped


def test_csv_table_renders_rows(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("metric,value\nmedian,10.99\nmax,13.2\n")
    html = G._csv_table(p)
    assert "<th>metric</th>" in html and "median" in html and "10.99" in html


def test_fig_css_sets_explicit_width_not_only_maxwidth():
    """Regression: the inlined matplotlib SVG has a viewBox but NO width/height attr (stripped so it
    scales). CSS must give it an EXPLICIT width — with only max-width, browsers render it 0×0 (the
    'blank plots' bug). Assert .fig has a width and .fig svg is width:100%."""
    css = G._CSS
    assert ".fig{" in css and "width:380px" in css          # the figure box has a real width
    assert ".fig svg{width:100%" in css                     # svg fills it (not just max-width)


def test_subtype_breakdown_panel_promoted_to_card_body():
    """The per-subtype breakdown (per_subgroup_metrics list-of-dicts) must render as a VISIBLE table
    in the card body — one row per subtype with its signal chip — not be collapsed to '<list, N items>'
    in the buried drill-down. This is the subgroup-analysis visibility the framework requires."""
    summary = {
        "subtype_axis_available": True, "subtype_stratification_class": "pan_subtype_uniform",
        "subtype_effect_size_class": "moderate", "subtype_variance_explained": 0.062,
        "subtype_omnibus_p": 2.8e-11, "n_subtypes_measured": 7,
        "which_subtypes_separate": {"highest": "left_sided", "lowest": "MSI_H"},
        "per_subgroup_metrics": [
            {"stratum_id": "MSI_H", "n_tumor_samples": 47, "median_log2tpm": 9.19,
             "tumor_expression_class": "broadly_high", "fraction_tumor_above_normal_p95": 0.32,
             "subtype_signal": "subtype_depleted"},
            {"stratum_id": "MSS", "n_tumor_samples": 205, "median_log2tpm": 10.86,
             "tumor_expression_class": "broadly_high", "fraction_tumor_above_normal_p95": 0.80,
             "subtype_signal": "subtype_uniform"},
        ],
    }
    panel = G._breakdown_panel_html("tumor-rna-distribution-by-subtype", summary)
    assert 'class="breakdown"' in panel
    # every subtype identity appears as a row
    assert "MSI_H" in panel and "MSS" in panel
    # per-row numbers surfaced (not collapsed)
    assert "9.19" in panel and "205" in panel
    # the per-row signal renders as a chip
    assert "subtype_depleted" in panel and 'class="chip' in panel
    # curated metrics now promote the omnibus stat + verdict (not just the effect-size adjective)
    m = G._key_metrics_html("tumor-rna-distribution-by-subtype", summary)
    assert "Kruskal" in m and "Variance explained" in m
    # headline field is now the subtype VERDICT
    assert G._headline_field("tumor-rna-distribution-by-subtype", summary) == "subtype_stratification_class"


def test_breakdown_panel_absent_when_not_configured_or_empty():
    # a card with no BREAKDOWN_PANELS entry → "" ; configured card but empty list → ""
    assert G._breakdown_panel_html("tumor-rna-distribution", {"per_subgroup_metrics": []}) == ""
    assert G._breakdown_panel_html("tumor-rna-distribution-by-subtype", {}) == ""
    assert G._breakdown_panel_html("tumor-rna-distribution-by-subtype",
                                   {"per_subgroup_metrics": []}) == ""


def test_static_figure_inlines_svg(tmp_path):
    # a card figure descriptor pointing at a real SVG on disk → inlined <svg>
    card_dir = tmp_path / "cards" / "tumor-rna-distribution"
    card_dir.mkdir(parents=True)
    (card_dir / "figure_x.svg").write_text(
        '<?xml version="1.0"?>\n<svg width="600pt" height="400pt" viewBox="0 0 600 400">'
        '<rect width="10" height="10"/></svg>')
    figs = [{"id": "x", "path": "cards/tumor-rna-distribution/figure_x.svg"}]
    out = G._card_figures_html(tmp_path, figs, interactive=False)
    assert "<svg" in out and "viewBox" in out
    assert 'width="600pt"' not in out   # fixed width stripped so it scales


def test_missing_svg_is_graceful(tmp_path):
    figs = [{"id": "x", "path": "cards/nope/figure_missing.svg"}]
    assert G._card_figures_html(tmp_path, figs, interactive=False) == ""


def test_flow_tabs_chain_and_structure():
    # flow tabs: 5 radios (nth-of-type CSS), one tabbar with 5 labels, one tabpanels with 5 panels;
    # the fired rule + its value + _data_source appear in the chain.
    fired = [{"rule_id": "r1", "card_id": "tumor-rna-distribution", "field": "tumor_expression_class",
              "value": "broadly_high", "dominant": True, "rationale_summary": "why"}]
    html = G._flow_tabs_html("tumor-rna-distribution",
                             {"tumor_expression_class": "broadly_high", "_data_source": "prod-x"},
                             fired, uid="0", target="KRAS", indication="COADREAD")
    assert html.count('class="tabin"') == 5
    assert html.count('class="tablabel"') == 5
    assert html.count('class="tabpanel"') == 5
    assert '<div class="tabbar">' in html and '<div class="tabpanels">' in html
    # radios come BEFORE the tabbar (required for the ~ sibling selector)
    assert html.index('class="tabin"') < html.index('class="tabbar"') < html.index('class="tabpanels"')
    assert "r1" in html and "broadly_high" in html          # rule + value in the chain
    assert "prod-x" in html                                 # _data_source surfaced in Data tab


def test_question_template_placeholders_filled():
    # {target.symbol}/{indication.label} in a card question must be substituted (no raw leak)
    assert G._fill_template("expr of {target.symbol} in {indication.label}", "KRAS", "COADREAD") \
        == "expr of KRAS in COADREAD"
    # in a real flow-tabs render, no raw placeholder remains
    html = G._flow_tabs_html("tumor-rna-distribution", {}, [], uid="0", target="KRAS", indication="COADREAD")
    assert "{target.symbol}" not in html and "{indication" not in html


def test_flow_tabs_descriptive_card_no_rules():
    # a card with no fired rules → Rules/Verdict panels say so, doesn't crash
    html = G._flow_tabs_html("target-identity-summary", {"resolved_hgnc_symbol": "KRAS"}, [], uid="3")
    assert "flowtabs" in html and ("Descriptive" in html or "display-only" in html or "not" in html.lower())


def test_card_meta_loads_or_degrades():
    # loader returns a dict (populated if target-contracts present, else {} — never raises)
    m = G._card_meta()
    assert isinstance(m, dict)


def test_synthesize_retry_without_flag(tmp_path, monkeypatch):
    """A subskill that rejects --synthesize (e.g. genomic-alteration-profile's custom main) must be
    retried WITHOUT it, not fail the row. We stub subprocess.run to reject --synthesize once."""
    import subprocess as _sp
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--synthesize" in cmd:
            raise _sp.CalledProcessError(2, cmd, stderr="run.py: error: unrecognized arguments: --synthesize")
        # second call (no --synthesize): write a minimal decision.json so the run "succeeds"
        out_dir = Path(cmd[cmd.index("--out") + 1])
        (out_dir).mkdir(parents=True, exist_ok=True)
        (out_dir / "decision.json").write_text('{"skill":"genomic-alteration-profile","target":"KRAS",'
                                               '"indication":"COADREAD","headline":{},"cards":[]}')
        class R: pass
        return R()

    # point SKILLS_DIR's run.py existence check at a real run.py (any subskill's) so the guard passes
    monkeypatch.setattr(_sp, "run", fake_run)
    monkeypatch.setattr(G, "SKILLS_DIR", G.SKILLS_DIR)  # unchanged; genomic-alteration-profile/run.py exists
    dec = G.run_subskill("genomic-alteration-profile", "KRAS", "COADREAD", tmp_path, synthesize=True)
    assert dec is not None and dec["skill"] == "genomic-alteration-profile"
    assert any("--synthesize" in c for c in calls)       # first attempt had it
    assert any("--synthesize" not in c for c in calls)   # retry dropped it


# --- render-from-existing-dir mode (no skill re-run) -------------------------

import json as _json  # noqa: E402


def _make_existing_run(tmp_path):
    """A minimal already-populated data-package: decision.json + figures/cards/<cid>/figure.svg (+twin)."""
    run = tmp_path / "EPCAM-COADREAD"
    (run / "figures" / "cards" / "tumor-rna-distribution").mkdir(parents=True)
    svg = run / "figures" / "cards" / "tumor-rna-distribution" / "figure_expression_distribution.svg"
    svg.write_text('<svg viewBox="0 0 10 10"><rect/></svg>')
    svg.with_suffix(".plotly.json").write_text('{"data":[],"layout":{}}')  # interactive twin
    # a second card with only an SVG (no twin)
    (run / "figures" / "cards" / "cellline-rna-distribution").mkdir(parents=True)
    (run / "figures" / "cards" / "cellline-rna-distribution" / "figure_density_expression.svg").write_text(
        '<svg viewBox="0 0 10 10"><rect/></svg>')
    (run / "decision.json").write_text(_json.dumps(_decision()))
    return run


def test_fig_map_from_existing_reconstructs_descriptors(tmp_path):
    run = _make_existing_run(tmp_path)
    fm = G.fig_map_from_existing(run)
    assert set(fm) == {"tumor-rna-distribution", "cellline-rna-distribution"}
    trd = fm["tumor-rna-distribution"][0]
    # path is relative to run_dir and points under figures/cards/
    assert trd["path"] == "figures/cards/tumor-rna-distribution/figure_expression_distribution.svg"
    assert trd["dynamic"] is True                       # .plotly.json twin present
    # the SVG-only card carries no dynamic flag
    assert "dynamic" not in fm["cellline-rna-distribution"][0]


def test_fig_map_from_existing_empty_when_no_figures(tmp_path):
    run = tmp_path / "no-figs"
    run.mkdir()
    (run / "decision.json").write_text(_json.dumps(_decision()))
    assert G.fig_map_from_existing(run) == {}


def test_render_from_existing_writes_dashboard_and_index(tmp_path):
    run = _make_existing_run(tmp_path)
    out = tmp_path / "gallery"
    rc = G._render_from_existing([str(run)], out, interactive=False)
    assert rc == 0
    # dashboard.html written BESIDE the package + a gallery copy + index
    dash = run / "dashboard.html"
    assert dash.exists()
    page = dash.read_text()
    assert "lineage_restricted" in page and "<svg" in page      # verdict + inlined figure
    assert (out / "index.html").exists()
    assert (out / "tumor-presence__CEACAM5__COADREAD.html").exists()


def test_render_from_existing_graceful_on_missing_decision(tmp_path):
    out = tmp_path / "g"
    rc = G._render_from_existing([str(tmp_path / "does-not-exist")], out, interactive=False)
    assert rc == 0                                       # no raise
    assert (out / "index.html").exists()                 # index still written (row marked NO decision.json)


# --- provenance surfacing in card metrics (WS-A) ----------------------------

def test_scrna_card_surfaces_indication_and_atlas_provenance(tmp_path):
    """The single-cell card must render its indication + atlas + donor/dataset provenance so a
    reader can see the read is indication-specific (not generic)."""
    decision = {
        "skill": "tumor-presence", "target": "CEACAM5", "indication": "NSCLC",
        "headline": {"presence_verdict": "tumor_broadly_expressed"},
        "cards": [{"card_id": "tumor-scrna-celltype-expression",
                   "summary": {"sc_expression_class": "malignant_subset_detected",
                               "indication": "NSCLC",
                               "product_id": "sc-pseudobulk-tumor-luca-nsclc-v1",
                               "malignant_n_donors": 115, "n_datasets": 14, "n_donor_groups": 146,
                               "malignant_detection_fraction": 0.182}}],
    }
    page = G.render_page(decision, tmp_path, fig_map={}, interactive=False)
    assert "Indication" in page and "NSCLC" in page
    assert "Atlas" in page and "sc-pseudobulk-tumor-luca-nsclc-v1" in page
    assert "Malignant donors" in page and "115" in page


def test_deg_card_adjacent_only_gtex_moves_to_normal_band(tmp_path):
    """In the presence view the DEG card shows the ADJACENT-normal contrast (which drives the call);
    the population-normal GTEx contrast (selectivity, owned by tumor-selectivity) is NOT shown as a
    DEG-card metric — it is rendered once in the normal-comparator band as a labeled reference."""
    decision = {
        "skill": "tumor-presence", "target": "CEACAM5", "indication": "LUAD",
        "headline": {"presence_verdict": "tumor_broadly_expressed"},
        "cards": [{"card_id": "tumor-rna-vs-adjacent",
                   "summary": {"expression_call_class": "modest_upregulation",
                               "log2_fc": 0.8, "q_value": 1e-4,
                               "gtex_log2_fc": 3.1, "gtex_q_value": 1e-20}}],
    }
    page = G.render_page(decision, tmp_path, fig_map={}, interactive=False)
    # adjacent contrast still on the DEG card
    assert "log2FC vs adjacent" in page
    # GTEx is NOT a curated DEG-card metric anymore
    assert "log2FC vs GTEx" not in page and "q vs GTEx" not in page
    # GTEx surfaces once in the normal-comparator band, labeled as selectivity-owned reference
    assert "Population-normal (GTEx)" in page and "tumor-selectivity" in page


def test_presence_scope_layout_placement_and_ladder(tmp_path, monkeypatch):
    """The tumor-presence scope layout places cards by their DECLARED coordinate into sample-context
    sections → data-type subsections → scope ladder; the rung at query depth leads; the subtype
    decomposition is inline at indication depth; typed-empty + cross-lens band render. Hermetic:
    the coordinate map is injected (no dependency on the sibling target-contracts checkout)."""
    monkeypatch.setattr(G, "_CARD_META_CACHE", {
        # (sample_context, measurement, tier) — tier absent on cellline-rna-distribution → fallback pan-cancer
        "cellline-rna-distribution":            {"sample_context": "cell_line", "measurement": "bulk_rna"},
        "tumor-rna-distribution":               {"sample_context": "tumor", "measurement": "bulk_rna", "tier": "indication"},
        "tumor-rna-distribution-by-subtype":    {"sample_context": "tumor", "measurement": "bulk_rna", "tier": "subtype"},
        "tumor-scrna-celltype-expression":      {"sample_context": "tumor", "measurement": "sc_rna", "tier": "indication"},
        "sc-normal-celltype-expression":        {"sample_context": "normal", "measurement": "sc_rna", "tier": "target"},
        "cellline-rna-protein-concordance":     {"sample_context": "cell_line", "measurement": "bulk_rna", "tier": "target"},
    })
    decision = {
        "skill": "tumor-presence", "target": "CEACAM5", "indication": "COADREAD",
        "headline": {"presence_verdict": "tumor_broadly_expressed"},
        "cards": [
            {"card_id": "cellline-rna-distribution", "summary": {"expression_class": "broadly_high"}},
            {"card_id": "tumor-rna-distribution", "summary": {"tumor_expression_class": "broadly_high", "median_log2tpm": 10.9}},
            {"card_id": "tumor-rna-distribution-by-subtype",
             "summary": {"subtype_stratification_class": "subtype_enriched",
                         "per_subgroup_metrics": [
                             {"stratum_id": "CMS1", "n_tumor_samples": 40, "median_log2tpm": 11.2,
                              "tumor_expression_class": "broadly_high",
                              "fraction_tumor_above_normal_p95": 0.9, "subtype_signal": "subtype_enriched"},
                             {"stratum_id": "MSS", "n_tumor_samples": 300, "median_log2tpm": 10.7,
                              "tumor_expression_class": "broadly_high",
                              "fraction_tumor_above_normal_p95": 0.7, "subtype_signal": "pan_subtype_uniform"}]}},
            {"card_id": "tumor-scrna-celltype-expression", "summary": {"sc_expression_class": "sc_malignant_detected"}},
            {"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_expression_class": "MODERATE"}},
            {"card_id": "cellline-rna-protein-concordance", "summary": {"rna_as_biomarker": "adequate_proxy"}},
        ],
        "fired_rules": [],
    }
    page = G.render_page(decision, tmp_path, fig_map={}, interactive=False)
    # three sample-context sections
    assert "Patient tumor — the answer" in page
    assert "Cell-line models — the proxy" in page
    assert "Normal-tissue comparator" in page
    # scope ladder: indication rung leads (query is target+indication)
    assert 'scopetag leads">indication' in page
    # cell-line pan-cancer leads (no indication-tier cell-line card; tier absent → fallback pan-cancer)
    assert 'scopetag leads">pan-cancer' in page
    # inline subtype decomposition at indication depth + a stratum row
    assert "How the indication read decomposes across subtypes" in page and "CMS1" in page
    # typed-empty: cell-line has no single-cell layer by design
    assert "not-applicable-by-design" in page
    # cross-lens relation band for the concordance card
    assert "Cross-lens agreement" in page and "Cell-line RNA ↔ protein concordance" in page


def test_presence_question_table_leads(tmp_path):
    """tumor-presence renders the 7-question signal+confidence table FIRST, with the scope-hierarchical
    layout demoted to a drill-down. Signal meters + confidence dots render; the table leads the cards."""
    page = G.render_page(_decision(), tmp_path, fig_map={}, interactive=False)
    assert "Presence at a glance" in page
    # all 7 question rows
    for q in ("Expressed in cancers at all?", "This indication vs other cancers?",
              "Elevated vs normals", "Do subtypes differ", "Absolute abundance vs all genes?",
              "Do RNA and protein agree?", "malignant-cell-intrinsic"):
        assert q in page, q
    # signal meter segments (7 rows × 5) + confidence dots present
    assert page.count('class="seg') >= 35
    assert 'class="dot"' in page or 'class="dot on"' in page
    # the table leads; the scope layout is inside the demoted drill-down
    assert page.index("Presence at a glance") < page.index("Detailed evidence by lens")
    assert page.index("Detailed evidence by lens") < page.index("Patient tumor")


# --- functional-requirement claim×scope layout (Phase 1, renderer-only, verdict-inert) --------------

def _dependency_decision():
    """A realistic functional-requirement decision.json (KRAS/COADREAD-shaped) for render tests."""
    return {
        "skill": "functional-requirement", "target": "KRAS", "indication": "COADREAD",
        "headline": {
            "dependency_verdict": "lineage_selective",
            "driving_rule_id": "lineage-selective-supportive",
            "crispr_call": "strongly_selective", "rnai_call": "strongly_selective",
            "concordance_call": "moderately_concordant_dependent",
            "lineage_selectivity": "lineage_selective",
            "cross_consortium_class": "concordant_dependent",
            "predictability_class": "own_omics_driven",
            "claim_vector": {
                "DEP": {"signal": "strong", "corroboration": "high", "evidence": "CRISPR strongly_selective; RNAi strongly_selective",
                        "conflict": None, "informs": "genetic dependency — is loss lethal?"},
                "SEL": {"signal": "strong", "corroboration": "moderate",
                        "evidence": "lineage enrichment: lineage_selective (target-grain)", "conflict": None,
                        "informs": "context-selectivity"},
                "COND": {"signal": "unmeasured", "corroboration": "unmeasured",
                         "evidence": "partner-conditional: no_partner_mapped", "conflict": None, "informs": "conditional / SL"},
                "CHEM": {"signal": "moderate", "corroboration": "moderate",
                         "evidence": "PRISM×CRISPR: crispr_confirmed_engagement", "conflict": None, "informs": "chemical-genetic"},
                "_disclaimer": "modality-blind, verdict-inert",
            },
            "key_signals": {"headline": "Selective genetic dependency, chemically confirmed.",
                            "supports": ["Genetic dependency — CRISPR strongly_selective, RNAi strongly_selective [CRISPR + RNAi distributions]"],
                            "caveat": None},
        },
        "cards": [
            {"card_id": "pan-cancer-crispr-dependency-distribution",
             "summary": {"dependency_class": "strongly_selective", "median_chronos_panel": -0.457,
                         "fraction_strongly_dependent": 0.31, "dep_control_position_class": "between_controls",
                         "n_cell_lines_evaluated": 1538}},
            {"card_id": "pan-cancer-rnai-dependency-distribution",
             "summary": {"rnai_dependency_class": "strongly_selective", "rnai_median_dep_score": -0.3}},
            {"card_id": "crispr-rnai-dependency-concordance",
             "summary": {"concordance_class": "moderately_concordant_dependent", "fraction_agree": 0.746}},
            {"card_id": "dependency-lineage-selectivity",
             "summary": {"enrichment_class": "lineage_selective", "n_enriched_lineages": 3,
                         "lineage_variance_explained": 0.186,
                         "enriched_lineages": [
                             {"lineage": "Pancreas", "n": 74, "median_chronos": -1.83, "effect_size": 0.73, "q_value": 2.7e-25},
                             {"lineage": "Bowel", "n": 88, "median_chronos": -1.18, "effect_size": 0.53, "q_value": 3.8e-16}]}},
            {"card_id": "paralog-buffering", "summary": {"paralog_buffering_class": "none"}},
            {"card_id": "partner-conditional-dependency",
             "summary": {"partner_stratification_class": "no_partner_mapped"}},
            {"card_id": "prism-crispr-concordance",
             "summary": {"crispr_prism_concordance_class": "crispr_confirmed_engagement", "n_compounds_evaluated": 4}},
            {"card_id": "cross-consortium-dependency",
             "summary": {"cross_consortium_class": "concordant_dependent", "broad_frac_dependent": 0.449}},
            {"card_id": "dependency-predictability",
             "summary": {"predictability_class": "own_omics_driven", "pearson_r_squared_rf": 0.42}},
            {"card_id": "expression-dependency-correlation",
             "summary": {"correlation_class": "moderate_negative", "pearson_r": -0.35}},
            {"card_id": "recommended-models",
             "summary": {"correspondence_class": "well_modeled_in_lineage", "n_positive_models_in_lineage": 12}},
        ],
        "fired_rules": [
            {"rule_id": "lineage-selective-supportive", "card_id": "dependency-lineage-selectivity",
             "field": "enrichment_class", "value": "lineage_selective", "dominant": True}],
    }


def test_dependency_claim_scope_layout(tmp_path):
    page = G.render_page(_dependency_decision(), tmp_path, fig_map={}, interactive=False)
    # verdict in header (verdict-inert layout does not change it)
    assert "lineage_selective" in page and "lineage-selective-supportive" in page
    # claim strip present with all four claim codes + the deterministic key-signals headline
    assert "Dependency claims" in page
    for code in (">DEP<", ">SEL<", ">COND<", ">CHEM<"):
        assert code in page
    assert "Selective genetic dependency, chemically confirmed." in page
    # claim SECTION headers (grouped, not flat-by-source)
    assert "DEP · Genetic dependency" in page
    assert "SEL · Context-selectivity" in page
    assert "COND · Conditional / synthetic-lethal" in page
    assert "CHEM · Chemical-genetic confirmation" in page
    # confidence band + biomarker fold rendered
    assert "Confidence" in page and "Broad ↔ Sanger" in page
    assert "Biomarker &amp; model context" in page
    # per-lineage breakdown promoted (Bowel + Pancreas rows, the SEL scope rung)
    assert "Enriched lineages" in page and "Bowel" in page and "Pancreas" in page
    # cards still render as collapsible blocks with flow tabs (same _render_card_block as flat path)
    assert '<details class="card"' in page and 'class="flowtabs"' in page


def test_dependency_layout_only_for_functional_requirement(tmp_path):
    # a skill that is NEITHER functional-requirement, tumor-presence, NOR tumor-selectivity must get
    # the FLAT cardlist (no claim layout, no scope/question-table layout) — the byte-stable path for
    # every other skill.
    d = _dependency_decision(); d["skill"] = "mechanism-and-pharmacology"
    page = G.render_page(d, tmp_path, fig_map={}, interactive=False)
    assert "Dependency claims" not in page and "DEP · Genetic dependency" not in page
    assert "Evidence at a glance" in page   # the flat header


def test_selectivity_layout_renders_question_table(tmp_path):
    # tumor-selectivity gets the LEADING 8-question table (from headline['question_table']) + a
    # "Detailed evidence" drill-down, NOT the flat "Evidence at a glance" header.
    d = _dependency_decision(); d["skill"] = "tumor-selectivity"
    d["headline"]["question_table"] = [
        {"id": "Q1", "question": "Over-expressed vs tissue-of-origin?", "primary": "axis-A strong",
         "support": "RNA→protein: rna_protein_concordant",
         "signal": {"fill": 5, "polarity": "supports", "label": "strong"}, "confidence": {"dots": 3}},
    ]
    d["headline"]["selectivity_class"] = "field_effect_tumor_selective"
    page = G.render_page(d, tmp_path, fig_map={}, interactive=False)
    assert "Dependency claims" not in page          # not the FR layout
    assert "<table" in page and "Q1" in page         # the leading question table rendered
    assert "Detailed evidence" in page               # per-card drill-down, not the flat header


def test_dependency_catchall_no_card_dropped(tmp_path):
    # a card not mapped to any claim still renders under "Other evidence"
    d = _dependency_decision()
    d["cards"].append({"card_id": "some-unmapped-dep-card", "summary": {"foo_class": "hub"}})
    page = G.render_page(d, tmp_path, fig_map={}, interactive=False)
    assert "Other evidence" in page and "some-unmapped-dep-card" in page


def test_dependency_subgroup_panorama_and_scope_when_present(tmp_path):
    # --subtypes path: the subgroup panorama card renders in the drill-down with the per-stratum table;
    # dependency_verdict_by_scope (Phase 3/4 forward-compat) renders a scope grid when present.
    d = _dependency_decision()
    d["headline"]["dependency_verdict_by_scope"] = {
        "pan_cancer": {"verdict": "lineage_selective"},
        "indication": {"verdict": "selective_in_indication"},
        "subtype": {"verdict": "MSI_H_dependent"}}
    d["cards"].append({"card_id": "subgroup-stratified-dependency",
                       "summary": {"subtype_dependency_pattern": "subgroup_specific_dependency",
                                   "cross_subgroup_delta_dependency": 0.4,
                                   "per_subgroup_metrics": [
                                       {"stratum": "MSI_H", "subgroup_n": 30, "median_chronos": -0.9,
                                        "class": "strong_dependency", "evidence_state": "measured"},
                                       {"stratum": "MSS", "subgroup_n": 106, "median_chronos": -0.4,
                                        "class": "not_dependent", "evidence_state": "measured"}]}})
    page = G.render_page(d, tmp_path, fig_map={}, interactive=False)
    assert "Verdict by scope" in page and "selective_in_indication" in page
    assert "Molecular-subgroup panorama" in page
    assert "Per-subgroup dependency" in page and "MSI_H" in page and "MSS" in page
