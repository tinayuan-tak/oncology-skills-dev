"""Two-slot LLM synthesis for the GENOMIC-ALTERATION lens: prompt grounding + schema discipline.

Mirrors test_synthesis.py (presence). Bedrock fully mocked (no network). The generic
byte-stability guarantee lives in test_synthesis_dispatch.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis_genomic as SG  # noqa: E402


def _decision_fixture(with_subtype=False):
    headline = {
        "genomic_alteration_profile": "confirmed_driver",
        "driving_rule_id": "mut-missense-dominant-supportive",
        "mutation_landscape_class": "missense_dominant",
        "mutation_stratification_class": "mutant_strongly_dependent",
        "copy_number_class": "broadly_neutral",
        "fusion_class": "no_recurrent_fusion",
        "alteration_role": "direct_driver_gof", "functional_direction": "activating",
        "functional_state_class": "sporadic_biallelic_inactivation",
        "event_correspondence_class": "event_matched_dependent_in_lineage",
        "overall_mutation_frequency": 0.42,
        "driver_recurrence_class": "top_1pct", "driver_recurrence_percentile": 99.7,
    }
    if with_subtype:
        headline["subtype_axis"] = {
            "subtype_mutation_pattern": "subgroup_specific_pattern",
            "cross_subgroup_delta_frequency": 0.22,
            "measured_strata": ["MSI_H", "MSS"]}
    return {"skill": "genomic-alteration-profile", "target": "KRAS", "indication": "COADREAD",
            "headline": headline, "cards": [], "fired_rules": []}


def test_prompt_grounds_verdict_mix_role_and_recurrence():
    p = SG.build_user_prompt(_decision_fixture())
    assert "confirmed_driver" in p                            # verdict
    assert "missense_dominant" in p                           # alteration mix
    assert "direct_driver_gof" in p and "activating" in p     # role
    assert "top_1pct" in p and "99.7" in p                    # Axis-1 recurrence
    # system prompt forbids changing the verdict + separates frequency from function
    assert "never change" in SG._SYSTEM.lower()
    assert "frequency != function" in SG._SYSTEM.lower() or "recurrently mutated without being a driver" in SG._SYSTEM.lower()


def test_prompt_gates_subtype_panorama():
    # not scoped → says so; scoped → narrates the pattern
    p_no = SG.build_user_prompt(_decision_fixture(with_subtype=False))
    assert "not scoped this run" in p_no
    p_yes = SG.build_user_prompt(_decision_fixture(with_subtype=True))
    assert "subgroup_specific_pattern" in p_yes and "MSI_H" in p_yes


def test_tool_schema_is_relevance_read_never_a_verdict():
    props = SG.SYNTHESIS_TOOL_SCHEMA["properties"]
    assert props["alteration_relevance_for_target"]["enum"] == [
        "strongly_supports", "supports_with_caveats", "neutral_uninformative", "argues_against"]
    assert props["confidence_qualifier"]["enum"] == [
        "well_supported", "supported_with_caveats", "weakly_supported", "insufficient_evidence"]
    assert "genomic_alteration_profile" not in props          # cannot restate the verdict
    assert SG.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


def test_schema_and_system_are_modality_free():
    schema_txt = json.dumps(SG.SYNTHESIS_TOOL_SCHEMA).lower()
    for tok in ["adc", "t-cell-engager", "tce", "bite", "car ", "small_molecule", "degrader"]:
        assert tok not in schema_txt, f"genomic schema should not mention modality token {tok!r}"
    assert "do not discuss therapeutic modality" in SG._SYSTEM.lower()


def test_synthesize_genomic_returns_stamped_block():
    fake = {"alteration_relevance_for_target": {"value": "strongly_supports",
            "_source": "llm_synthesized", "_model_id": "opus", "_prompt_hash": "abc"}}
    with patch("_skills_common.llm.synthesize_structured", return_value=fake) as m:
        out = SG.synthesize_genomic_alteration(_decision_fixture())
    assert m.called
    assert out["alteration_relevance_for_target"]["_source"] == "llm_synthesized"
