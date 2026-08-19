"""synthesis_dependency — the opt-in dependency-lens narrator (prompt build + tool schema +
two-slot dispatch). Bedrock fully mocked (no network).

Pins: (1) the tool schema is CONFIDENCE-only (no dependency_verdict field the LLM could emit);
(2) build_user_prompt reads the FULL evidence set + both new axes and renders a measured-but-
unavailable card as DATA_UNAVAILABLE (the H1 drops-nulls guard); (3) the pan-essential→tox steer
is present; (4) two-slot byte-stability through the dispatcher with synthesize_dependency.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis_dependency as SD  # noqa: E402
from _skills_common import dispatcher as D  # noqa: E402


def _decision(prism_missing: bool = True):
    """A realistic functional-requirement decision spine (mirrors run.py::_headline + card summaries)."""
    return {
        "target": "KRAS", "indication": "COADREAD",
        "headline": {
            "dependency_verdict": "concordant_dependent",
            "driving_rule_id": "concordant-dependent-supportive-dominant",
            "crispr_call": "strongly_selective", "rnai_call": "selective",
            "concordance_call": "concordant", "lineage_selectivity": "lineage_selective",
            "paralog_buffering_class": "no_buffering", "strongest_paralog_symbol": None,
            "predictability_class": "own_omics_driven", "pred_dominant_feature_class": "expression",
            "dependency_confidence": "high", "dependency_confidence_note": "predictable from own omics",
            "model_correspondence_class": "well_modeled", "n_positive_models_in_lineage": 12,
        },
        "cards": [
            {"card_id": "pan-cancer-crispr-dependency-distribution", "_missing": False, "summary": {
                "dep_control_position_class": "between_controls",
                "dep_control_position": "as/more essential than 0/6 pan-essential; more dependent than 4/4 non-essential",
                "dep_control_target_chronos": -0.457,
                "dep_control_pan_essential_ceiling": -1.499,
                "dep_control_non_essential_floor": -0.038,
                "dep_control_position_context": "DepMap 26q1 ... INVERTED ..."}},
            {"card_id": "dependency-lineage-selectivity", "_missing": False, "summary": {
                "lineage_omnibus_effect_size_class": "large", "lineage_variance_explained": 0.186,
                "which_lineages_separate": {"highest": "Kidney", "lowest": "Pancreas"},
                "enrichment_class": "lineage_selective"}},
            {"card_id": "pan-cancer-rnai-dependency-distribution", "_missing": False, "summary": {}},
            {"card_id": "crispr-rnai-dependency-concordance", "_missing": False, "summary": {}},
            {"card_id": "prism-crispr-concordance", "_missing": prism_missing, "summary": {}},
            {"card_id": "paralog-buffering", "_missing": False, "summary": {}},
        ],
    }


# ---- schema is confidence-only ----
def test_tool_schema_has_no_verdict_field():
    """The LLM must NOT be able to emit a dependency_verdict — it narrates a FIXED spine."""
    props = set(SD.SYNTHESIS_TOOL_SCHEMA["properties"])
    assert "dependency_verdict" not in props
    assert props == {"dependency_relevance_for_target", "dependency_rationale",
                     "selectivity_vs_pan_essential_read", "confidence_qualifier", "key_caveat"}
    assert SD.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


# ---- prompt reads the full evidence set + both axes, and never drops a null ----
def test_prompt_grounds_full_evidence_and_axes():
    p = SD.build_user_prompt(_decision())
    # verdict spine
    assert "dependency_verdict: concordant_dependent" in p
    # all genetic assays named
    for token in ("CRISPR call", "RNAi call", "concordance", "lineage_selectivity",
                  "PARALOG BUFFERING", "PREDICTABILITY"):
        assert token in p
    # both new axes
    assert "AXIS-2 — CONTROL-BENCHMARK POSITION" in p and "between_controls" in p
    assert "AXIS-3 — ACROSS-LINEAGE OMNIBUS" in p and "ε²=0.186" in p


def test_prompt_renders_unavailable_card_as_data_unavailable():
    """The H1 drops-nulls guard: a measured-but-missing card is shown as DATA_UNAVAILABLE,
    not silently omitted."""
    p = SD.build_user_prompt(_decision(prism_missing=True))
    assert "prism-crispr-concordance: DATA_UNAVAILABLE" in p


def test_prompt_carries_pan_essential_tox_steer():
    p = SD.build_user_prompt(_decision())
    assert "pan-essential" in p.lower()
    assert "ARGUES AGAINST" in p  # the inversion steer must be explicit


# ---- two-slot byte-stability through the dispatcher ----
def _run_dispatch(tmp_path, *, synthesize):
    card_outputs = [
        {"card_id": "pan-cancer-crispr-dependency-distribution", "summary": {}, "_missing": False},
    ]

    def _headline(cards, fired, vp):
        return {"dependency_verdict": "concordant_dependent", "driving_rule_id": "r"}

    argv = ["--target", "KRAS", "--indication", "COADREAD", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    def _fake(decision, model_id=None, subtype_query=None):
        return {"dependency_relevance_for_target": {"value": "strongly_supports",
                "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}

    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="functional-requirement", skill_version="9.9.9",
            cards=["pan-cancer-crispr-dependency-distribution"], axis="intracellular_intrinsic",
            question="Is {target} a dependency in {indication}?",
            headline_fn=_headline, synthesize_fn=_fake, argv=argv)
    return json.loads((tmp_path / "decision.json").read_text())


def test_two_slot_byte_stability(tmp_path, scrub_volatile):
    base = scrub_volatile(_run_dispatch(tmp_path / "a", synthesize=False))
    synth = scrub_volatile(_run_dispatch(tmp_path / "b", synthesize=True))
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    assert {k: v for k, v in synth.items() if k != "llm_synthesis"} == base


def test_synthesis_failure_degrades_to_note(tmp_path):
    """A narration failure must never break the deterministic run."""
    card_outputs = [{"card_id": "pan-cancer-crispr-dependency-distribution", "summary": {}, "_missing": False}]

    def _headline(cards, fired, vp):
        return {"dependency_verdict": "concordant_dependent", "driving_rule_id": "r"}

    def _boom(decision, model_id=None, subtype_query=None):
        raise RuntimeError("bedrock down")

    out = tmp_path / "c"
    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="functional-requirement", skill_version="9.9.9",
            cards=["pan-cancer-crispr-dependency-distribution"], axis="intracellular_intrinsic",
            question="Is {target} a dependency in {indication}?",
            headline_fn=_headline, synthesize_fn=_boom,
            argv=["--target", "KRAS", "--indication", "COADREAD", "--out", str(out), "--synthesize"])
    d = json.loads((out / "decision.json").read_text())
    assert "_synthesis_error" in d["llm_synthesis"]
    assert d["headline"]["dependency_verdict"] == "concordant_dependent"


# --- publication-register + deterministic metric legend (2026-08-05) ---

def test_metric_legend_is_deterministic_and_covers_cited_metrics():
    """METRIC_LEGEND must define, in plain language, every technical quantity the narration
    cites — so a non-computational reader has an accurate, byte-stable reference."""
    keys = set(SD.METRIC_LEGEND)
    assert {"chronos_score", "rnai_demeter2", "dep_control_position",
            "epsilon_squared", "paralog_buffering", "predictability"} <= keys
    # each legend entry is a non-trivial plain-language sentence, not a bare token
    for k, v in SD.METRIC_LEGEND.items():
        assert isinstance(v, str) and len(v) > 40, f"{k} legend too short"
    # the ε² legend must give the plain-language bands (readable by a non-statistician)
    assert "0.06" in SD.METRIC_LEGEND["epsilon_squared"] and "lineage" in SD.METRIC_LEGEND["epsilon_squared"].lower()
    # the Chronos legend must anchor the 0 / -1 scale
    assert "-1" in SD.METRIC_LEGEND["chronos_score"] and "essential" in SD.METRIC_LEGEND["chronos_score"].lower()


def test_legend_attached_on_success_not_on_failure():
    """synthesize_dependency attaches metric_legend on a successful narration; a degraded
    {_synthesis_error} block stays minimal (no legend padding a failure)."""
    # success: mock synthesize_structured to return a valid narration
    ok = {"dependency_relevance_for_target": {"value": "supports_with_caveats",
          "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}
    with patch("_skills_common.llm.synthesize_structured", return_value=dict(ok)):
        res = SD.synthesize_dependency(_decision())
    assert res["metric_legend"] == SD.METRIC_LEGEND
    assert res["dependency_relevance_for_target"]["value"] == "supports_with_caveats"

    # failure: a degraded block must NOT carry the legend
    degraded = {"_synthesis_error": "RuntimeError: bedrock down", "_note": "..."}
    with patch("_skills_common.llm.synthesize_structured", return_value=dict(degraded)):
        res2 = SD.synthesize_dependency(_decision())
    assert "metric_legend" not in res2
    assert "_synthesis_error" in res2


def test_system_prompt_enforces_publication_register_and_glosses():
    """The system prompt must instruct the publication register (no promotional language) AND
    require plain-language metric glosses on first use."""
    sysp = SD._SYSTEM.lower()
    # register discipline: names the register + bans editorialising words
    assert "publication" in sysp
    assert "promotional" in sysp or "editorialis" in sysp
    # explicitly lists banned promo words + requires a gloss
    assert "promising" in sysp
    assert "gloss" in sysp
    # the schema field descriptions also ask for the register / glossing
    desc = SD.SYNTHESIS_TOOL_SCHEMA["properties"]["dependency_rationale"]["description"].lower()
    assert "publication register" in desc and "plain language" in desc


# --- molecular-subgroup panorama in the narration (2026-08-06) ---

def _decision_with_panorama(pattern="not_informative"):
    d = _decision(prism_missing=False)
    d["headline"]["subtype_scope"] = ["MSI_H", "MSS"]
    d["headline"]["subtype_dependency_panorama"] = {
        "subtype_dependency_pattern": pattern,
        "cross_subgroup_delta_dependency": 0.53,
        "measured_strata": ["MSS"],
        "per_stratum": [
            {"stratum": "MSI_H", "class": "moderate_dependency",
             "evidence_state": "underpowered", "median_chronos": -0.69, "subgroup_n": 17},
            {"stratum": "MSS", "class": "strong_dependency",
             "evidence_state": "measured", "median_chronos": -1.22, "subgroup_n": 71},
        ],
    }
    return d


def test_prompt_renders_subgroup_panorama_with_power_flags():
    p = SD.build_user_prompt(_decision_with_panorama())
    assert "MOLECULAR-SUBGROUP DEPENDENCY" in p
    assert "MSI_H" in p and "MSS" in p
    # per-stratum evidence_state must be shown so an underpowered stratum is visible
    assert "underpowered" in p and "measured" in p
    # the discipline instruction must be present
    assert "compare ONLY across strata tagged 'measured'" in p
    # scope + admissible strata surfaced
    assert "measured' strata: ['MSS']" in p or "['MSS']" in p


def test_prompt_omits_subgroup_block_when_no_panorama():
    """Without --subtypes (no panorama in the headline), the subgroup block must not appear."""
    p = SD.build_user_prompt(_decision(prism_missing=False))
    assert "MOLECULAR-SUBGROUP DEPENDENCY" not in p


# ---- organoid corroboration facet (2026-08-18) ----
def test_prompt_renders_organoid_corroboration_present():
    """build_user_prompt surfaces the organoid-crispr-dependency card as a CORROBORATING facet
    with its class + fraction, and states the 'not a trusted veto' discipline."""
    d = _decision()
    d["cards"].append({"card_id": "organoid-crispr-dependency", "_missing": False, "summary": {
        "organoid_dependency_class": "broad_organoid_dependency",
        "frac_dependent": 0.746, "median_gene_effect": -0.87, "n_models_screened": 114}})
    prompt = SD.build_user_prompt(d)
    assert "ORGANOID CORROBORATION" in prompt
    assert "broad_organoid_dependency" in prompt
    assert "0.75" in prompt  # frac_dependent rendered via _fmt (2dp)
    assert "not a trusted veto" in prompt.lower()


def test_prompt_renders_organoid_indication_lineage():
    """When the organoid card carries an indication-matched lineage (v0.2.0), the prompt surfaces
    that lineage's fraction and steers toward it over the pooled pan-organoid fraction."""
    d = _decision()
    d["cards"].append({"card_id": "organoid-crispr-dependency", "_missing": False, "summary": {
        "organoid_dependency_class": "broad_organoid_dependency",
        "frac_dependent": 0.746, "median_gene_effect": -0.87, "n_models_screened": 114,
        "organoid_lineage": "Bowel", "organoid_lineage_frac_dependent": 0.955,
        "organoid_lineage_class": "pan_organoid_essential", "organoid_lineage_n_screened": 22}})
    prompt = SD.build_user_prompt(d)
    assert "organoid lineage for this indication: Bowel" in prompt
    assert "0.95" in prompt  # the lineage fraction, stronger than pooled 0.75
    assert "PREFER this lineage read" in prompt


def test_prompt_organoid_no_lineage_mapped():
    """No indication→organoid-lineage mapping → the facet says so, no lineage steer."""
    d = _decision()
    d["cards"].append({"card_id": "organoid-crispr-dependency", "_missing": False, "summary": {
        "organoid_dependency_class": "broad_organoid_dependency", "frac_dependent": 0.746,
        "median_gene_effect": -0.87, "n_models_screened": 114, "organoid_lineage": None}})
    prompt = SD.build_user_prompt(d)
    assert "not mapped / no organoid cohort" in prompt
    assert "PREFER this lineage read" not in prompt


def test_prompt_renders_organoid_data_unavailable_not_dropped():
    """A measured-null organoid card is rendered DATA_UNAVAILABLE, never silently dropped (H1)."""
    d = _decision()
    d["cards"].append({"card_id": "organoid-crispr-dependency", "_missing": True, "summary": {}})
    prompt = SD.build_user_prompt(d)
    assert "ORGANOID CORROBORATION" in prompt
    assert "DATA_UNAVAILABLE" in prompt
