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
    # at-a-glance strip present
    assert "Evidence at a glance" in page
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
