"""report_render — the standalone subskill dashboard renders the approved sandbox design
(eg-sandbox-genomic.html) through the ONE renderer: the header headline + kv grid, the per-question
meter/dots/qstrip/qkey drill summary, the consolidated card reading + labeled scale bar + top-strata
table (.ketbl), the two-tone (--det/--lit) narrative bullets, and the auto/light/dark theme toggle.

These are the sandbox signature classes that landed on top of #1240 (which shipped the question-grouped
drill, role badges, litdot agreement glyph, litaxis border, table twin, ring-confidence heatmap). All
are VERDICT-INERT display bound to the carried evidence_graph; a graph without the fields degrades.
"""

from _skills_common.report_render import backends as be
from _skills_common.report_render import build_ir_for_skill, render_skill_report, resolve_spec


def _rich_graph() -> dict:
    """A KRAS-shaped graph: a verdict with coverage + top_tension, a question carrying signal tier +
    confidence dots + evidence_refs, a card with a numeric key_evidence.effect + top_strata, and a
    two-tone narrative bullet (mentions 'literature')."""
    return {
        "schema_version": "1.0",
        "skill": "genomic-alteration-profile",
        "target": "KRAS",
        "indication": "COADREAD",
        "verdict": {
            "id": "biomarker_stratified_dependency",
            "call": "Biomarker-stratified genetic dependency",
            "polarity": "supportive",
            "driving_rule_id": "mutant-strongly-dependent-supportive",
            "confidence": {"level": "moderate", "coverage": {"n_measured": 4, "n_axes": 4, "n_critical_measured": 4}},
            "top_tension": {"text": "No recurrent copy-number alteration", "severity": 1},
        },
        "questions": [
            {
                "id": "snv_indel_class",
                "seq": 1,
                "text": "Recurrent SNV/indel driver?",
                "axis_id": "SNV",
                "role": "verdict_bearing",
                "signal": {"tier": "strong", "polarity": "supportive", "label": "missense_dominant"},
                "confidence": {"level": "moderate", "dots": 2},
                "card_ids": ["mutation-stratified-dependency"],
                "literature_axis_ids": ["SNV"],
                "evidence_refs": [
                    {
                        "card_id": "mutation-stratified-dependency",
                        "label": "mutation-stratified mutant_strongly_dependent",
                    }
                ],
            }
        ],
        "cards": [
            {
                "id": "mutation-stratified-dependency",
                "measurement_type": "mutation_stratified_dependency",
                "role": "verdict_bearing",
                "question_ids": ["snv_indel_class"],
                "signal": {"tier": "strong", "polarity": "supportive", "label": "mutant_strongly_dependent"},
                "confidence": {"level": "high", "dots": 3, "n": 88},
                "class": {"field": "mutation_stratification_class", "value": "mutant_strongly_dependent"},
                "dataset_ids": ["depmap-consortium-26q1"],
                "chain": {
                    "dataset_ids": ["depmap-consortium-26q1"],
                    "data": [{"field": "hotspot_dependency_ppv", "value": 1.0}],
                    "rule_id": "mutant-strongly-dependent-supportive",
                    "contributes_to_verdict": True,
                    "is_driving": True,
                },
                "key_evidence": {
                    "effect": {
                        "metric": "median_chronos_hotspot_mutant",
                        "value": -1.7287,
                        "direction": "lower_is_stronger",
                    },
                    "n": 43,
                    "top_strata": [{"label": "Bowel", "role": "indication", "value": -1.73, "n": 43}],
                    "interpretation": [
                        {
                            "metric": "median_chronos_hotspot_mutant",
                            "value": -1.7287,
                            "scale": "chronos",
                            "direction": "lower_is_stronger",
                            "frame": {
                                "kind": "comparator_delta",
                                "anchors": [
                                    {"role": "comparator", "label": "hotspot_wildtype", "value": -0.5864},
                                    {"role": "cut", "label": "strong_effect_delta", "value": -0.5},
                                ],
                            },
                            "distance_to_cut": -1.142,
                        }
                    ],
                },
            }
        ],
        "literature": {
            "axes": [
                {
                    "axis_id": "SNV",
                    "question_ids": ["snv_indel_class"],
                    "read": "strongly_supports",
                    "agreement_vs_omics": "agree",
                    "confidence": "high",
                    "assertion": "Hotspot missense is the CRC driver.",
                    "citation_ids": ["k2026"],
                }
            ],
            "blind_spots": [],
            "overall_consistency": "concordant",
            "key_divergence": None,
        },
        "citations": [{"id": "k2026", "label": "Kulmambetova 2026", "pmid": "42644004", "verified": True}],
        "narrative": {
            "relevance": "strongly_supports",
            "exec_bullets": [
                {
                    "text": "KRAS is missense-dominant with top-percentile recurrence; the literature corroborates hotspot G12/G13.",
                    "polarity": "supportive",
                    "cites": {"card_ids": ["mutation-stratified-dependency"]},
                }
            ],
        },
    }


def _skill_report() -> dict:
    return {
        "role": "gating",
        "call": "biomarker_stratified_dependency",
        "polarity": "supportive",
        "honest_phrase": "Biomarker-stratified genetic dependency",
        "confidence": {"level": "moderate"},
        "evidence_graph": _rich_graph(),
        "provenance": {
            "driving_rule_id": "r1",
            "fired_rule_ids": ["r1"],
            "cards_used": ["mutation-stratified-dependency"],
        },
    }


def _html() -> str:
    ir = build_ir_for_skill(
        _skill_report(), resolve_spec("full"), short="genomic_alteration", target="KRAS", indication="COADREAD"
    )
    return be.render(ir, "html")


def test_header_headline_and_kv_bind_to_graph_verdict():
    h = _html()
    # the sandbox `.hdr` header structure (eg-sandbox-genomic.html): the accent .card.hdr, a `.titlerow`
    # with the skill eyebrow + `{TARGET} · {INDICATION}` h1 on the left and the polarity `.vchip` on the
    # right, then the one-sentence headline, then the `.kv` grid — trimmed 2026-09-10 to the Tension row
    # only (the Verdict + Driving rows were removed; verdict/call/driving/confidence live in the headline).
    assert "hdr" in h and 'class="titlerow"' in h  # accent header card + title row
    assert 'class="eyebrow"' in h and "<h1>KRAS · COADREAD</h1>" in h  # eyebrow + GENE · INDICATION h1
    assert 'class="vchip"' in h  # top-right polarity chip
    assert "stitle" not in h  # the OLD .stitle header line is gone
    assert 'class="headline"' in h  # one-sentence read inside the header
    assert "moderate-confidence supportive call" in h  # confidence + polarity clause
    assert "mutant-strongly-dependent-supportive" in h  # driving rule surfaced (in the headline sentence)
    # the trimmed kv carries the Tension row only (Verdict/Driving rows + the .vline verdict line removed).
    assert 'class="kv"' in h and "<dt>Tension" in h
    assert "<dt>Verdict" not in h and "<dt>Driving" not in h
    assert "No recurrent copy-number alteration" in h  # top_tension caveat


def test_question_summary_has_meter_dots_qstrip_and_key():
    h = _html()
    assert 'class="qtab"' in h and 'details class="qr"' in h  # question drill scaffold
    assert "meter" in h and "mfill" in h  # signal-tier bar
    assert "class='dots'" in h and ("●" in h or "○" in h)  # confidence dots
    assert "qstrip" in h and "qcell" in h  # mini per-card signal strip
    assert "mutation-stratified mutant_strongly_dependent" in h  # evidence-ref key


def test_card_reading_scale_bar_and_top_strata_table():
    h = _html()
    # 2026-09-10 de-clutter: the split metric-gloss (.kegloss) + separate KEY line are gone; the numeric
    # reading is now carried ONCE by the labeled scale bar's caption, and the top-strata table remains.
    assert "kegloss" not in h  # the redundant split gloss is removed
    assert "class='scalebar'" in h and "class='sb-cap'>" in h  # the labeled scale bar + its reading caption
    assert "median CHRONOS in hotspot-mutant lines -1.729" in h  # the reading (glossed metric + value)
    assert "past the -0.5 cut" in h  # the cut reading in the caption
    assert "ketbl" in h and "Bowel" in h  # top-strata table retained


def test_two_tone_narrative_and_theme_toggle():
    h = _html()
    assert "fx-det" in h and "fx-lit" in h  # omics vs literature two-tone
    assert 'data-theme="auto"' in h and "theme-toggle" in h  # theme toggle shell
    assert "[data-theme=dark]" in h  # explicit dark override (not only the media query)


def test_render_skill_report_entrypoint_prints_all_sandbox_classes():
    # the public standalone entrypoint (what the dispatcher calls) surfaces the full sandbox signature
    from _skills_common.report_render import render_skill_report as _rsr

    dec = {
        "skill": "genomic-alteration-profile",
        "target": "KRAS",
        "indication": "COADREAD",
        "headline": {"skill_report": _skill_report(), "evidence_graph": _rich_graph()},
    }
    h = _rsr(dec, backend="html", preset="full", skill_name="genomic-alteration-profile")
    for cls in (
        "hdr",
        'class="titlerow"',
        'class="eyebrow"',
        'class="vchip"',
        'class="kv"',
        'class="qtab"',
        'details class="qr"',
        "meter",
        "mfill",
        "class='scalebar'",
        "scope-chip",
        "qstrip",
        "fx-det",
    ):
        assert cls in h, f"standalone dashboard missing {cls}"
    assert "stitle" not in h  # OLD header line retired


def test_graph_without_new_fields_degrades_gracefully():
    # a graph verdict without coverage/tension/driving-rule still renders (no crash, no literal 'None')
    sr = _skill_report()
    sr["evidence_graph"]["verdict"] = {"id": "v", "call": "A call", "polarity": "supportive"}
    out = render_skill_report(
        {
            "skill": "s",
            "target": "KRAS",
            "indication": "COADREAD",
            "headline": {"skill_report": sr, "evidence_graph": sr["evidence_graph"]},
        },
        backend="html",
        preset="full",
    )
    assert "None" not in out
    assert 'class="titlerow"' in out and "hdr" in out  # header still renders (accent .card.hdr + title row)
