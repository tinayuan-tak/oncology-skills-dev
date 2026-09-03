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
from _skills_common.narrator_lenses import TUMOR_PRESENCE as LENS
from _skills_common import narrator_engine as ne


def _decision():
    return {
        "target": "EPCAM", "indication": "COADREAD",
        "headline": {
            "presence_verdict": "tumor_broadly_expressed",
            "claim_vector": {
                "A": {"signal": "strong", "corroboration": "moderate", "evidence": "top 1% all-gene"},
                "B": {"signal": "absent", "corroboration": "moderate", "evidence": "flat vs adjacent",
                      "conflict": None},
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
    assert {"axis_key", "literature_read", "assertion", "agreement_vs_omics", "confidence", "citations"} <= set(axis_item["required"])
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
    assert "not elevated vs adjacent normal" in p   # the omics caveat is carried in


def test_make_literature_fn_returns_synth_output(monkeypatch):
    canned = {"axes": [{"axis_key": "B", "literature_read": "supports", "assertion": "adjacent colon is EpCAM-high",
                        "agreement_vs_omics": "agree", "confidence": "high", "citations": []}],
              "blind_spots": [], "overall_consistency": "concordant", "key_divergence": "none",
              "_source": "llm_synthesized", "_model_id": "stub", "_prompt_hash": "deadbeef"}
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
        "axes": [{"axis_key": "B", "literature_read": "supports", "assertion": "adjacent colon EpCAM-high",
                  "agreement_vs_omics": "agree", "confidence": "high",
                  "citations": [{"label": "Han 2017", "pmid": "28558958", "verified": True},
                                {"label": "guessed", "verified": False}]}],
        "blind_spots": [{"signal": "invasive-front membranous loss", "why_omics_blind": "bulk/sc cannot see localization"}],
        "overall_consistency": "partially_concordant", "key_divergence": "membranous loss at margin",
    }
    prompt = ne.build_capsule_prompt(d, LENS)
    assert "LITERATURE LANE" in prompt
    assert "adjacent colon EpCAM-high" in prompt
    assert "PMID:28558958" in prompt
    assert "[unverified]" in prompt                      # the unverified citation is flagged in-line
    assert "OMICS-BLIND: invasive-front membranous loss" in prompt
    assert "KEY DIVERGENCE" in prompt


def test_narrator_omits_literature_lane_when_absent_or_errored():
    base = ne.build_capsule_prompt(_decision(), LENS)
    assert "LITERATURE LANE" not in base
    for block in ({"_literature_error": "boom"}, {"_literature_skipped": "no_literature_lens_declared"}, {}):
        d = _decision(); d["literature_synthesis"] = block
        assert "LITERATURE LANE" not in ne.build_capsule_prompt(d, LENS)


def test_system_prompt_instructs_verdict_inert_literature_use():
    sys = ne._system(LENS)
    assert "LITERATURE LANE" in sys
    assert "never let the literature move the fixed verdict" in sys.lower()
