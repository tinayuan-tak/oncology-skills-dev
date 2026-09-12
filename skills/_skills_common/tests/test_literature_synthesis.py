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
