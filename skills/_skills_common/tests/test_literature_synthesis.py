"""Tests for the OPTIONAL, verdict-INERT LLM literature lane (literature_synthesis) and its wiring into
the capsule narrator.

Pins:
  1. the tool schema is well-formed (per-axis read + agreement + citations{verified}; blind_spots; overall);
  2. the literature prompt is GROUNDED in the omics claim vector (axes + their signals appear), so the model
     can judge agreement_vs_omics rather than free-associating;
  3. make_literature_fn attaches the synthesizer output as-is (Bedrock stubbed) — the CALLER stamps/attaches;
  4. the narrator INGESTS the literature lane: build_capsule_prompt renders a LITERATURE LANE section when
     decision['literature_synthesis'] is present (and omits it — byte-identically — when absent/errored),
     and the system prompt instructs the model to treat it as a verdict-inert corroboration lane.
"""

from __future__ import annotations

from _skills_common import literature_synthesis as lit
from _skills_common import narrator_engine as ne
from _skills_common.narrator_lenses import TUMOR_PRESENCE as LENS


def _decision():
    return {
        "target": "EPCAM",
        "indication": "COADREAD",
        "headline": {
            "presence_verdict": "tumor_broadly_expressed",
            "claim_vector": {
                "A": {"signal": "strong", "corroboration": "moderate", "evidence": "top 1% all-gene"},
                "B": {
                    "signal": "absent",
                    "corroboration": "moderate",
                    "evidence": "flat vs adjacent",
                    "conflict": None,
                },
                "C": {"signal": "strong", "corroboration": "high", "evidence": "89% malignant"},
                "D": {"signal": "moderate", "corroboration": "high", "evidence": "multi-tumor"},
            },
            "key_signals": {"caveat": "not elevated vs adjacent normal"},
        },
    }


def test_tool_schema_shape():
    name, schema = lit._tool(LENS)
    assert name == "emit_tumor_presence_literature"
    assert set(schema["required"]) == {"axes", "blind_spots", "overall_consistency", "key_divergence"}
    axis_item = schema["properties"]["axes"]["items"]
    assert {"axis_key", "literature_read", "assertion", "agreement_vs_omics", "confidence", "citations"} <= set(
        axis_item["required"]
    )
    cite = axis_item["properties"]["citations"]["items"]
    assert "verified" in cite["required"] and cite["properties"]["verified"]["type"] == "boolean"
    # agreement enum must carry the omics_blind / contradicts reads the whole point of the lane
    assert {"agree", "contradicts", "omics_blind"} <= set(axis_item["properties"]["agreement_vs_omics"]["enum"])


def test_prompt_is_grounded_in_omics_axes():
    p = lit.build_literature_prompt(_decision(), LENS)
    # every omics axis label + its signal must be shown so agreement_vs_omics is grounded, not invented
    for label in ("abundance", "tumor-elevation", "malignant-intrinsic", "generality"):
        assert label in p
    assert "OMICS SIGNALS ALREADY COMPUTED" in p
    assert "agreement_vs_omics" in p
    assert "not elevated vs adjacent normal" in p  # the omics caveat is carried in


def test_prompt_tags_axis_measured_state():
    """Every axis line is tagged [MEASURED] / [NO-OMICS-DATA] so the model can't confuse a measured floor
    (signal=absent) with a genuine coverage gap. _decision()'s axes A/B/C/D are all measured (B=absent is a
    MEASURED floor); flipping D to `unmeasured` must surface a NO-OMICS-DATA tag."""
    # `]:` isolates AXIS-LINE tags from the header prose (which also mentions both tokens).
    p = lit.build_literature_prompt(_decision(), LENS)
    assert "[MEASURED]:" in p and "[NO-OMICS-DATA]:" not in p  # absent (axis B) is a MEASURED floor, not a gap
    d = _decision()
    d["headline"]["claim_vector"]["D"] = {"signal": "unmeasured", "corroboration": "unmeasured", "evidence": ""}
    assert "[NO-OMICS-DATA]:" in lit.build_literature_prompt(d, LENS)


def test_axis_measured_state_signal_tiers():
    st = lit.axis_measured_state(_decision(), LENS)
    assert st["A"]["measured"] and st["B"]["measured"]  # strong + absent (a measured floor) are MEASURED
    d = _decision()
    d["headline"]["claim_vector"]["B"] = {"signal": "negative", "corroboration": "low", "evidence": "wrong dir"}
    d["headline"]["claim_vector"]["D"] = {"signal": "unmeasured", "corroboration": "unmeasured", "evidence": ""}
    st = lit.axis_measured_state(d, LENS)
    assert st["B"]["measured"]  # negative (measured, wrong direction) is MEASURED
    assert not st["D"]["measured"]  # unmeasured is a GAP
    # an atom-less axis the claim vector leaves ambiguous is UPGRADED by a measured capsule (cross-check)
    d["headline"]["claim_vector"]["D"] = {"evidence_atom": {"cite": {"card_id": "some-card"}}}
    d["headline"]["evidence_capsules"] = {"capsules": {"some-card": {"evidence_state": "measured", "class": "hi"}}}
    st = lit.axis_measured_state(d, LENS)
    assert st["D"]["measured"] and st["D"]["class"] == "hi"


def test_reground_agreement_rewrites_measured_unavailable():
    """The deterministic guard: a MEASURED axis wrongly tagged omics_unavailable/omics_blind is rewritten to
    `extends` (+ audit breadcrumb); a genuine NO-OMICS-DATA axis and any already-valid read are untouched."""
    states = {"A": {"measured": True}, "B": {"measured": True}, "D": {"measured": False}}
    result = {
        "axes": [
            {"axis_key": "A", "agreement_vs_omics": "omics_unavailable"},  # measured → rewrite
            {"axis_key": "B", "agreement_vs_omics": "omics_blind"},  # measured → rewrite
            {"axis_key": "D", "agreement_vs_omics": "omics_unavailable"},  # NO-OMICS-DATA → keep
            {"axis_key": "C", "agreement_vs_omics": "contradicts"},  # already valid → keep (C absent from states)
        ]
    }
    lit._reground_agreement(result, states)
    by = {a["axis_key"]: a for a in result["axes"]}
    assert by["A"]["agreement_vs_omics"] == "extends" and by["A"]["agreement_regrounded"] is True
    assert by["B"]["agreement_vs_omics"] == "extends"
    assert by["D"]["agreement_vs_omics"] == "omics_unavailable" and "agreement_regrounded" not in by["D"]
    assert by["C"]["agreement_vs_omics"] == "contradicts"


def test_synthesize_regrounds_measured_axis(monkeypatch):
    """End-to-end: a stubbed model tags the MEASURED axis B (signal=absent) omics_unavailable; the lane's
    post-pass corrects it to extends before returning."""
    canned = {
        "axes": [
            {
                "axis_key": "B",
                "literature_read": "supports",
                "assertion": "adjacent EpCAM-high",
                "agreement_vs_omics": "omics_unavailable",
                "confidence": "high",
                "citations": [],
            }
        ],
        "blind_spots": [],
        "overall_consistency": "concordant",
        "key_divergence": "none",
    }
    monkeypatch.setattr("_skills_common.llm.synthesize_structured", lambda **k: canned)
    out = lit.synthesize_literature(_decision(), LENS, model_id="stub")
    assert out["axes"][0]["agreement_vs_omics"] == "extends"
    assert out["axes"][0]["agreement_regrounded"] is True


def test_make_literature_fn_returns_synth_output(monkeypatch):
    canned = {
        "axes": [
            {
                "axis_key": "B",
                "literature_read": "supports",
                "assertion": "adjacent colon is EpCAM-high",
                "agreement_vs_omics": "agree",
                "confidence": "high",
                "citations": [],
            }
        ],
        "blind_spots": [],
        "overall_consistency": "concordant",
        "key_divergence": "none",
        "_source": "llm_synthesized",
        "_model_id": "stub",
        "_prompt_hash": "deadbeef",
    }
    calls = {}

    def _fake_synth(**kwargs):
        calls.update(kwargs)
        return canned

    monkeypatch.setattr("_skills_common.llm.synthesize_structured", _fake_synth)
    out = lit.make_literature_fn(LENS)(_decision(), model_id="stub")
    assert out is canned
    assert calls["tool_name"] == "emit_tumor_presence_literature"
    assert "EPCAM" in calls["user_prompt"] and "COADREAD" in calls["user_prompt"]


def test_retrieve_fn_grounds_prompt(monkeypatch):
    monkeypatch.setattr("_skills_common.llm.synthesize_structured", lambda **k: {"user": k["user_prompt"]})
    seen = lit.make_literature_fn(LENS, retrieve_fn=lambda t, i, l: "Went 2006 PMID:16404366: 97.7% high.")(_decision())
    assert "RETRIEVED ABSTRACTS" in seen["user"] and "16404366" in seen["user"]


def test_narrator_renders_literature_lane_when_present():
    d = _decision()
    d["literature_synthesis"] = {
        "axes": [
            {
                "axis_key": "B",
                "literature_read": "supports",
                "assertion": "adjacent colon EpCAM-high",
                "agreement_vs_omics": "agree",
                "confidence": "high",
                "citations": [
                    {"label": "Han 2017", "pmid": "28558958", "verified": True},
                    {"label": "guessed", "verified": False},
                ],
            }
        ],
        "blind_spots": [
            {"signal": "invasive-front membranous loss", "why_omics_blind": "bulk/sc cannot see localization"}
        ],
        "overall_consistency": "partially_concordant",
        "key_divergence": "membranous loss at margin",
    }
    prompt = ne.build_capsule_prompt(d, LENS)
    assert "LITERATURE LANE" in prompt
    assert "adjacent colon EpCAM-high" in prompt
    assert "PMID:28558958" in prompt
    assert "[unverified]" in prompt  # the unverified citation is flagged in-line
    assert "OMICS-BLIND: invasive-front membranous loss" in prompt
    assert "KEY DIVERGENCE" in prompt


def test_narrator_omits_literature_lane_when_absent_or_errored():
    base = ne.build_capsule_prompt(_decision(), LENS)
    assert "LITERATURE LANE" not in base
    for block in ({"_literature_error": "boom"}, {"_literature_skipped": "no_literature_lens_declared"}, {}):
        d = _decision()
        d["literature_synthesis"] = block
        assert "LITERATURE LANE" not in ne.build_capsule_prompt(d, LENS)


def test_system_prompt_instructs_verdict_inert_literature_use():
    sys = ne._system(LENS)
    assert "LITERATURE LANE" in sys
    assert "never let the literature move the fixed verdict" in sys.lower()


def test_coerce_axes_dict_to_list_and_unwrap_scalars():
    """A model may emit `axes`/`blind_spots` as an OBJECT keyed by axis letter (not the declared array);
    _coerce_shapes normalizes dict→list (injecting axis_key) and unwraps provenance-stamped scalars, so
    every consumer sees the contract shape."""
    r = {
        "axes": {
            "A": {"literature_read": "supports", "citations": [{"label": "x", "pmid": "1", "verified": True}]},
            "B": {"axis_key": "B", "literature_read": "mixed", "citations": []},
        },
        "blind_spots": {"0": {"signal": "s", "why_omics_blind": "w"}},
        "overall_consistency": {"value": "concordant", "_source": "llm_synthesized"},
        "key_divergence": {"value": "none", "_source": "llm_synthesized"},
    }
    lit._coerce_shapes(r)
    assert isinstance(r["axes"], list) and {a["axis_key"] for a in r["axes"]} == {"A", "B"}
    assert isinstance(r["blind_spots"], list) and r["blind_spots"][0]["signal"] == "s"
    assert r["overall_consistency"] == "concordant" and r["key_divergence"] == "none"


def test_coerce_unwraps_provenance_stamped_fields():
    """The REAL shape from synthesize_structured: every top-level list/str is stamped as
    {"value": <orig>, "_source": "llm_synthesized", ...}. _coerce_shapes must unwrap axes/blind_spots/
    scalars back to their content (so verify + render work) while preserving provenance at the result top
    level. Regression for the live-caught bug (stamped `axes` wrapper → 0 citations checked)."""
    stamp = lambda v: {"value": v, "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}
    stamped = {
        "axes": stamp(
            [
                {
                    "axis_key": "A",
                    "literature_read": "supports",
                    "citations": [{"label": "x", "pmid": "1", "verified": False}],
                }
            ]
        ),
        "blind_spots": stamp([{"signal": "s", "why_omics_blind": "w"}]),
        "overall_consistency": stamp("concordant"),
        "key_divergence": stamp("none"),
    }
    lit._coerce_shapes(stamped)
    assert isinstance(stamped["axes"], list) and stamped["axes"][0]["axis_key"] == "A"
    assert stamped["axes"][0]["citations"][0]["pmid"] == "1"
    assert isinstance(stamped["blind_spots"], list) and stamped["blind_spots"][0]["signal"] == "s"
    assert stamped["overall_consistency"] == "concordant" and stamped["key_divergence"] == "none"
    assert stamped["_source"] == "llm_synthesized" and stamped["_model_id"] == "m" and stamped["_prompt_hash"] == "h"


def test_synthesize_coerces_dict_axes_before_verify(monkeypatch):
    """Regression for the live-caught bug: model returned axes as a dict keyed by axis, so verify_citations
    checked 0 PMIDs. After coercion the verify pass must reach each per-axis citation."""
    from _skills_common import literature_retrieval as lr

    dict_shaped = {
        "axes": {
            "A": {
                "literature_read": "supports",
                "agreement_vs_omics": "agree",
                "confidence": "high",
                "citations": [{"label": "Went", "pmid": "16404366", "verified": False}],
            }
        },
        "blind_spots": [],
        "overall_consistency": "concordant",
        "key_divergence": "none",
    }
    monkeypatch.setattr("_skills_common.llm.synthesize_structured", lambda **k: dict_shaped)
    monkeypatch.setattr(lr, "_pmid_exists", lambda pmid, timeout: True)
    out = lit.make_literature_fn(LENS, verify_fn=lr.verify_citations)(_decision())
    assert isinstance(out["axes"], list) and out["axes"][0]["axis_key"] == "A"
    assert out["axes"][0]["citations"][0]["verified"] is True
    assert out["_verification"]["n_pmid_checked"] == 1


def test_narrator_renders_dict_shaped_axes_after_coerce():
    """The narrator renderer must not choke if a raw dict-shaped literature block reaches it — build the
    prompt through _coerce_shapes first (mirrors the synthesize path)."""
    d = _decision()
    d["literature_synthesis"] = lit._coerce_shapes(
        {
            "axes": {
                "C": {
                    "axis_key": "C",
                    "literature_read": "strongly_supports",
                    "agreement_vs_omics": "agree",
                    "confidence": "high",
                    "assertion": "EpCAM marks CRC stem cells",
                    "citations": [{"label": "Dalerba 2007", "pmid": "17548814", "verified": True}],
                }
            },
            "blind_spots": [],
            "overall_consistency": "concordant",
            "key_divergence": "none",
        }
    )
    prompt = ne.build_capsule_prompt(d, LENS)
    assert "LITERATURE LANE" in prompt and "EpCAM marks CRC stem cells" in prompt and "PMID:17548814" in prompt


def test_prompt_surfaces_subtype_enrichment_as_measured():
    # FACET 2: a MEASURED subtype enrichment (CD274/MSI-H) must reach the lit prompt tagged [MEASURED],
    # so the lane classifies a subtype-specific presence pattern as agree/extends, not omics_blind.
    d = _decision()
    d["target"] = "CD274"
    d["headline"]["claim_vector_by_subtype"] = {
        "stratification_class": "subtype_enriched",
        "subtype_variance_explained": 0.28,
        "subtype_effect_size_class": "large",
        "enriched_subtypes": [
            {"stratum": "MSI_H", "subtype_signal": "subtype_enriched", "median_log2tpm": 2.51},
            {"stratum": "CMS1", "subtype_signal": "subtype_enriched", "median_log2tpm": 2.29},
        ],
        "top_enriched_subtype": "MSI_H",
    }
    p = lit.build_literature_prompt(d, LENS)
    assert "SUBTYPE ENRICHMENT [MEASURED" in p
    assert "MSI_H(subtype_enriched)" in p and "top=MSI_H" in p
    assert "NOT omics_blind" in p


def test_prompt_omits_subtype_block_when_no_subtype_axis():
    # byte-stable for lenses / runs with no claim_vector_by_subtype (the block is fully omitted)
    p = lit.build_literature_prompt(_decision(), LENS)
    assert "SUBTYPE ENRICHMENT" not in p


def test_prompt_surfaces_partner_conditional_as_measured():
    # GENERALIZATION (WRN×MSI-H): a MEASURED partner/genotype-conditional dependency lives OUTSIDE the
    # pooled axes; surface it [MEASURED] so the lane reads agree/extends, not omics_blind.
    d = _decision()
    d["target"] = "WRN"
    d["headline"]["partner_conditional_class"] = "partner_conditional_moderately_dependent"
    d["headline"]["n_partner_deficient"] = 91
    d["headline"]["partner_stratification_q"] = 8.8e-12
    p = lit.build_literature_prompt(d, LENS)
    assert "CONDITIONAL SIGNAL [MEASURED]" in p
    assert "partner_conditional_moderately_dependent" in p
    assert "n_partner_deficient=91" in p and "NOT" in p and "omics_blind" in p


def test_conditional_block_omitted_when_absent_or_negative():
    # byte-stable when no conditional field, and a NON-dependent conditional class must NOT render
    assert "CONDITIONAL SIGNAL" not in lit.build_literature_prompt(_decision(), LENS)
    d = _decision()
    d["headline"]["partner_conditional_class"] = "not_partner_stratified"
    assert "CONDITIONAL SIGNAL" not in lit.build_literature_prompt(d, LENS)


def test_conditional_signal_lines_helper():
    assert lit._conditional_signal_lines({}) == []
    assert lit._conditional_signal_lines({"partner_conditional_class": "partner_conditional_strongly_dependent"})


# ── MEASURED EVIDENCE grounding ─────────────────────────────────────────────────────────────────────
# The axis block is the resolver's COLLAPSED tier; these pins cover the per-card readings it was collapsed
# FROM. The fixture below is distilled from a real genomic-alteration-profile run (KRAS/COADREAD) rather
# than invented, because the gauge string is produced by the measurement_type's SALIENCE_SPEC
# reference_frame against the card summary — a shape that cannot be guessed.
_MSD = "mutation-stratified-dependency"
_HOTSPOT = "mutation-hotspot-frequency"


def _msd_summary() -> dict:
    return {
        "median_chronos_hotspot_mutant": -1.7287,
        "median_chronos_hotspot_wildtype": -0.5864,
        "delta_chronos_hotspot_mut_vs_wt": -1.1423,
        "hotspot_mannwhitney_q": 1.25e-10,
        "n_hotspot_mutant": 43,
        "mutation_stratification_class": "mutant_strongly_dependent",
        "stratification_direction": "forward_mutant_dependent",
    }


def _decision_with_evidence(fire_rule: bool = True) -> dict:
    """A decision carrying what the literature lane could previously not see: emitted cards + their
    capsules. Two measured cards (one verdict-bearing, one display-only) + one consulted-but-silent."""
    d = _decision()
    d["cards"] = [
        {"card_id": _MSD, "summary": _msd_summary(), "input_manifest_ids": ["depmap-26q1"]},
        {
            "card_id": _HOTSPOT,
            "summary": {"overall_mutation_frequency": 0.4204, "hotspot_recurrence_class": "top_1pct"},
            "input_manifest_ids": ["cbioportal-pancancer"],
        },
        {"card_id": "consulted-but-silent", "summary": {}, "input_manifest_ids": []},
    ]
    d["fired_rules"] = (
        [{"card_id": _MSD, "rule_id": "R-mut-dep", "field": "mutation_stratification_class", "value": "mutant"}]
        if fire_rule
        else []
    )
    d["headline"]["evidence_capsules"] = {
        "capsules": {
            _MSD: {
                "card_id": _MSD,
                "measurement_type": "mutation_stratified_dependency",
                "evidence_state": "measured",
                "class": "mutant_strongly_dependent",
                "numeric_anchors": [
                    {"metric": "delta_chronos_hotspot_mut_vs_wt", "value": -1.1423},
                    {"metric": "median_chronos_hotspot_mutant", "value": -1.7287},
                ],
                "categorical_anchors": [
                    {"field": "mutation_stratification_class", "value": "mutant_strongly_dependent"}
                ],
            },
            _HOTSPOT: {
                "card_id": _HOTSPOT,
                "measurement_type": "mutation_hotspot_frequency",
                "evidence_state": "measured",
                "class": "top_1pct",
                "numeric_anchors": [{"metric": "overall_mutation_frequency", "value": 0.4204}],
                "categorical_anchors": [{"field": "hotspot_recurrence_class", "value": "top_1pct"}],
            },
            "consulted-but-silent": {
                "card_id": "consulted-but-silent",
                "measurement_type": "rna_expression",
                "evidence_state": "measured",
            },
        }
    }
    d["headline"]["headline_block"] = {"verdict": {"driving_rule_id": "R-mut-dep"}}
    d["headline"]["subgroup_signals"] = {"SNV": {"sources": [{"card": _MSD, "tier": "strong", "n": 43}]}}
    return d


def test_prompt_carries_the_per_card_measured_datum_behind_the_axis_tiers():
    """POSITIVE CONTROL for a section that fails SOFT (an exception yields no lines at all). Asserts the
    readings actually REACH the prompt: card_id anchor, the decisive datum in words, the reference-frame
    ruler naming the cut, and n. Without this pin, a broken builder is indistinguishable from a skill that
    simply measured nothing."""
    p = lit.build_literature_prompt(_decision_with_evidence(), LENS)
    assert "MEASURED EVIDENCE" in p
    assert f"card {_MSD}" in p  # the citable anchor
    assert "CHRONOS" in p  # the glossed units — the datum is in WORDS, not a bare float
    assert "-1.7287" in p or "-1.729" in p  # the decisive value itself
    assert "vs reference:" in p and "cut" in p  # the reference frame + the threshold it was judged against
    assert "n=43" in p


def test_the_reference_frame_separates_the_measurement_from_the_threshold():
    """The whole point of carrying the gauge: `contradicts the value` and `contradicts the cut` are
    different claims, and the axis tier expresses neither. The gauge must name BOTH sides."""
    lines = lit._measured_evidence_lines(_decision_with_evidence(), LENS)
    gauge_line = next(ln for ln in lines if ln.startswith(f"  · card {_MSD}"))
    assert "vs reference:" in gauge_line
    assert "-0.5864" in gauge_line or "-0.5" in gauge_line  # the comparator/cut side, not just the effect
    assert "MEASUREMENT vs THRESHOLD" in "\n".join(lines)


def test_verdict_bearing_and_display_only_cards_are_distinguished():
    """A measured card that fired NO rule did not move the verdict, so contradicting it does not challenge
    the call. The axis-level claim vector cannot express this at all."""
    p = lit.build_literature_prompt(_decision_with_evidence(), LENS)
    msd = next(ln for ln in p.splitlines() if f"card {_MSD}" in ln)
    hot = next(ln for ln in p.splitlines() if f"card {_HOTSPOT}" in ln)
    assert "[verdict-bearing]" in msd
    assert "display-only" in hot and "fired no rule" in hot
    # and it tracks the FIRED SET, not the card identity: with no rule fired, nothing is verdict-bearing
    p2 = lit.build_literature_prompt(_decision_with_evidence(fire_rule=False), LENS)
    assert "[verdict-bearing]" not in p2 and "display-only" in p2


def test_the_evidence_graph_is_derived_on_demand_because_it_does_not_exist_yet():
    """ORDERING PIN. `headline.evidence_graph` is attached at dispatcher step 8d, AFTER this lane at 8a, and
    8d PROJECTS literature_synthesis into the graph — so the dependency is inverted by design and the graph
    cannot be moved earlier. Deriving it here is therefore the PRODUCTION path, not a fallback. This also
    pins the equivalence: a fresh projection renders the same rows as a pre-existing graph."""
    d = _decision_with_evidence()
    assert "evidence_graph" not in d["headline"]  # the live shape at prompt-build time
    derived = lit._measured_evidence_lines(d, LENS)
    assert any(ln.startswith("  · card ") for ln in derived)

    from _skills_common.evidence_graph import build_evidence_graph

    d2 = _decision_with_evidence()
    d2["headline"]["evidence_graph"] = build_evidence_graph(_decision_with_evidence())
    assert lit._measured_evidence_lines(d2, LENS) == derived


def test_a_pre_existing_graph_is_read_rather_than_rebuilt():
    """The rarer path (a re-run over a saved decision.json): an already-attached graph is used as-is. Pinned
    with a card present ONLY in the graph, so a silent rebuild would drop it."""
    d = _decision_with_evidence()
    d["headline"]["evidence_graph"] = {
        "cards": [
            {
                "id": "graph-only-card",
                "measurement_type": "crispr_lof_dependency",
                "role": "verdict_bearing",
                "confidence": {"n": 7},
                "key_evidence": {
                    "effect": {"metric": "median_chronos", "value": -0.9, "direction": "lower_is_stronger"}
                },
            }
        ]
    }
    lines = lit._measured_evidence_lines(d, LENS)
    assert any("graph-only-card" in ln for ln in lines)
    assert not any(_MSD in ln for ln in lines)  # NOT rebuilt from decision.cards


def test_the_questions_registry_does_not_change_the_rendered_rows():
    """Why the prompt builder needs no skill_dir: the five card fields the row builder reads (id,
    measurement_type, role, key_evidence, confidence) are independent of the questions registry, which only
    feeds question_ids/axis_id. Pinned so a future registry-dependent field cannot silently change the
    prompt without failing here."""
    from pathlib import Path

    from _skills_common.evidence_graph import build_evidence_graph, load_questions

    # load_questions fail-softs to [] on a missing path, so a cwd-relative path would make this test
    # compare no-questions against no-questions — VACUOUSLY green. Resolve from __file__ and assert the
    # registry actually loaded before comparing.
    skills_root = Path(__file__).resolve().parents[2]
    questions = load_questions(skills_root / "genomic-alteration-profile")
    assert questions, "questions registry did not load — the comparison below would be vacuous"

    base = _decision_with_evidence()
    without = build_evidence_graph(base)
    with_qs = build_evidence_graph(_decision_with_evidence(), questions)
    assert any(c.get("question_ids") for c in with_qs["cards"]), "questions had no effect — nothing to control for"
    read = ("id", "measurement_type", "role", "key_evidence", "confidence")
    assert [{k: c.get(k) for k in read} for c in without["cards"]] == [
        {k: c.get(k) for k in read} for c in with_qs["cards"]
    ]


def test_consulted_but_unmeasured_cards_are_counted_not_renamed_a_coverage_gap():
    """A card that surfaced no decisive datum is neither measured evidence nor a declared coverage gap —
    the axis tags remain the sole authority on omics_blind. Surfaced as a COUNT: the row builder keeps only
    a rollup tally for these, and naming them would require a second reader of evidence_graph.cards[]."""
    lines = lit._measured_evidence_lines(_decision_with_evidence(), LENS)
    tail = next(ln for ln in lines if "further card" in ln)
    assert "1 further card" in tail and "NO decisive measured datum" in tail
    assert "authoritative" in tail
    # the silent card is COUNTED, never rendered as a row (a row asserts a measurement)
    assert not any(ln.startswith("  · card consulted-but-silent") for ln in lines)


def test_the_readings_never_override_the_axis_measured_tags():
    """ANTI-DRIFT: the readings are grounding DETAIL. Adding them must not create a second measured-ness
    vocabulary competing with axis_measured_state — a NO-OMICS-DATA axis stays a gap even when sibling
    cards carry rich readings."""
    d = _decision_with_evidence()
    d["headline"]["claim_vector"]["D"] = {"signal": "unmeasured", "corroboration": "unmeasured", "evidence": ""}
    assert lit.axis_measured_state(d, LENS)["D"]["measured"] is False
    p = lit.build_literature_prompt(d, LENS)
    assert "[NO-OMICS-DATA]:" in p  # the axis tag survives the presence of measured siblings
    assert "ONLY authority" in p  # and the model is told the tags outrank the readings


def test_the_section_is_omitted_when_the_skill_emitted_no_decisive_datum():
    """Byte-stable for a decision carrying no cards/capsules (same discipline as _conditional_signal_lines),
    so every existing lens and every --literature-only replay is unaffected."""
    assert lit._measured_evidence_lines(_decision(), LENS) == []
    p = lit.build_literature_prompt(_decision(), LENS)
    # NO DANGLING POINTER: the TASK clause referencing the section must vanish with the section, or the
    # model is told to consult readings it was never shown — and may supply them from imagination.
    assert "MEASURED EVIDENCE" not in p
    assert "engage that reading" not in p
    d = _decision()
    d["cards"] = [{"card_id": "silent", "summary": {}}]
    d["headline"]["evidence_capsules"] = {"capsules": {"silent": {"measurement_type": "rna_expression"}}}
    assert lit._measured_evidence_lines(d, LENS) == []  # consulted but nothing decisive → no section


def test_building_the_prompt_does_not_mutate_the_decision():
    """The lane is verdict-INERT and decision.json must stay byte-identical: deriving the graph here is a
    projection, so it must not write anything back onto the decision it read."""
    import copy

    d = _decision_with_evidence()
    before = copy.deepcopy(d)
    lit.build_literature_prompt(d, LENS)
    assert d == before


def test_a_malformed_decision_degrades_to_no_section_and_never_raises():
    """Fail-soft: the dispatcher turns ANY raise in this lane into a `_literature_error` stub for the whole
    synthesis, so a fault in a prompt-enrichment section must cost only that section."""
    for bad in ({"headline": {"evidence_graph": {"cards": "not-a-list"}}}, {"cards": "nope"}, {}):
        assert lit._measured_evidence_lines(bad, LENS) == []
        assert isinstance(lit.build_literature_prompt(bad, LENS), str)


def test_system_prompt_directs_grounding_in_the_measurement_not_only_the_tier():
    s = lit._system(LENS)
    assert "MEASURED EVIDENCE" in s
    assert "threshold" in s.lower() and "magnitude" in s.lower()
    assert "verdict-bearing" in s and "display-only" in s
