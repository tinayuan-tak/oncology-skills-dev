"""Two-slot LLM synthesis: byte-stability of the deterministic spine + prompt grounding.

The load-bearing guarantee: running WITH --synthesize produces a decision that is
IDENTICAL to the no-flag decision except for the added `llm_synthesis` sibling key.
The narration can never touch the verdict spine. Bedrock is fully mocked (no network).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis as SYN  # noqa: E402


# ---------------------------------------------------------------------------
# 1. build_user_prompt grounds the narration in the contextualized fields
# ---------------------------------------------------------------------------
def _decision_fixture():
    return {
        "skill": "tumor-presence", "target": "CEACAM5", "indication": "COADREAD",
        "headline": {"presence_verdict": "broadly_high_expression",
                     "driving_rule_id": "expression-broadly-high-supportive",
                     "purity_confound_class": "tumor_intrinsic"},
        "cards": [
            {"card_id": "tumor-rna-distribution", "summary": {
                "tumor_expression_class": "broadly_high", "median_log2tpm": 10.99,
                "allgene_percentile": 99.9, "allgene_percentile_class": "top_1pct",
                "allgene_percentile_context": "tcga_tumor:COAD,READ (allgene-tumor-rank-v1)",
                "control_position_class": "above_all_positives",
                "control_position": "above 4/4 positive control(s); above 4/5 negative control(s)",
                "control_positives": {"CEACAM5": 99.9, "EPCAM": 99.7},
                "control_negatives": {"ACTB": 99.9, "SFTPC": 18.0},
                "control_negatives_excluded_lineage_conflict": []}},
            {"card_id": "tumor-rna-distribution-by-subtype", "summary": {
                "subtype_effect_size_class": "moderate", "subtype_variance_explained": 0.097,
                "which_subtypes_separate": {"highest": "stage_I", "lowest": "MSI_H"},
                "subtype_stratification_class": "pan_subtype_uniform"}},
        ],
        "fired_rules": [],
    }


def test_prompt_grounds_all_three_axes():
    p = SYN.build_user_prompt(_decision_fixture())
    # verdict + all three contextualized axes must be present in the prompt
    assert "broadly_high_expression" in p
    assert "99.9" in p and "top_1pct" in p                 # axis 1
    assert "above_all_positives" in p                       # axis 2
    assert "moderate" in p and "MSI_H" in p                 # axis 3
    # the system prompt forbids inventing/changing the verdict
    assert "never" in SYN._SYSTEM.lower() and "narrate" in SYN._SYSTEM.lower()


def test_prompt_handles_missing_axes_gracefully():
    d = {"target": "X", "indication": "BRCA", "headline": {"presence_verdict": "insufficient"},
         "cards": []}
    p = SYN.build_user_prompt(d)  # must not raise on absent cards
    assert "insufficient" in p and "n/a" in p


# ---------------------------------------------------------------------------
# 2. Tool schema is well-formed + verdict-neutral (no field that could restate a verdict)
# ---------------------------------------------------------------------------
def test_tool_schema_is_confidence_only_never_a_verdict():
    props = SYN.SYNTHESIS_TOOL_SCHEMA["properties"]
    # the ONLY enum field is a CONFIDENCE qualifier — there is no presence_verdict field
    assert "confidence_qualifier" in props
    assert props["confidence_qualifier"]["enum"] == [
        "well_supported", "supported_with_caveats", "weakly_supported", "insufficient_evidence"]
    assert "presence_verdict" not in props   # the LLM cannot emit a verdict
    assert SYN.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


# ---------------------------------------------------------------------------
# 3. synthesize_presence stamps provenance (mocked Bedrock)
# ---------------------------------------------------------------------------
def test_synthesize_presence_returns_stamped_block():
    fake = {"headline_narrative": {"value": "CEACAM5 is broadly high...",
                                   "_source": "llm_synthesized", "_model_id": "opus",
                                   "_prompt_hash": "abc"},
            "confidence_qualifier": "well_supported"}
    with patch("_skills_common.llm.synthesize_structured", return_value=fake) as m:
        out = SYN.synthesize_presence(_decision_fixture())
    assert m.called
    assert out["headline_narrative"]["_source"] == "llm_synthesized"


# ---------------------------------------------------------------------------
# 4. TWO-SLOT byte-stability: --synthesize adds ONLY llm_synthesis (dispatcher e2e, mocked)
# ---------------------------------------------------------------------------
def _run(tmp_path, synthesize: bool, synth_return=None, synth_raises=False):
    """Run run_wired_skill with resolve_cards + synthesize_structured mocked, return the
    decision.json dict written to disk."""
    import json
    from _skills_common import dispatcher as D

    card_outputs = [
        {"card_id": "tumor-rna-distribution", "summary": {
            "tumor_expression_class": "broadly_high", "allgene_percentile": 99.9,
            "allgene_percentile_class": "top_1pct", "control_position_class": "above_all_positives"},
         "_missing": False},
    ]

    def _headline(cards, fired, vp):
        return {"presence_verdict": "broadly_high_expression", "driving_rule_id": None}

    argv = ["--target", "CEACAM5", "--indication", "COADREAD", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    patches = [
        patch.object(D, "resolve_cards", return_value=card_outputs),
        patch.object(D, "fired_rules", return_value=[]),
    ]
    # patch synthesize_structured at its SOURCE (_skills_common.llm) — synthesis.py imports
    # it lazily inside synthesize_presence, so it is not an attribute of the synthesis module.
    if synth_raises:
        patches.append(patch("_skills_common.llm.synthesize_structured",
                             side_effect=RuntimeError("bedrock down")))
    else:
        patches.append(patch("_skills_common.llm.synthesize_structured",
                             return_value=(synth_return or {"headline_narrative": {
                                 "value": "narr", "_source": "llm_synthesized",
                                 "_model_id": "m", "_prompt_hash": "h"}})))
    for p in patches:
        p.start()
    try:
        D.run_wired_skill(skill_name="tumor-presence", skill_version="9.9.9",
                          cards=["tumor-rna-distribution"], axis="intracellular_intrinsic",
                          question="Is {target} present in {indication}?",
                          headline_fn=_headline, argv=argv)
    finally:
        for p in patches:
            p.stop()
    return json.loads((tmp_path / "decision.json").read_text())


def test_synthesize_adds_only_llm_synthesis_key(tmp_path):
    base = _run(tmp_path / "a", synthesize=False)
    synth = _run(tmp_path / "b", synthesize=True)
    # the deterministic spine (everything except llm_synthesis + volatile timestamp) is identical
    base.pop("generated_at", None); synth.pop("generated_at", None)
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    synth_wo = {k: v for k, v in synth.items() if k != "llm_synthesis"}
    assert synth_wo == base, "synthesis must NOT change any deterministic field"
    assert synth["headline"]["presence_verdict"] == base["headline"]["presence_verdict"]


def test_synthesis_failure_degrades_to_note(tmp_path):
    d = _run(tmp_path / "c", synthesize=True, synth_raises=True)
    assert "_synthesis_error" in d["llm_synthesis"]
    # the verdict spine is untouched despite the synthesis failure
    assert d["headline"]["presence_verdict"] == "broadly_high_expression"
