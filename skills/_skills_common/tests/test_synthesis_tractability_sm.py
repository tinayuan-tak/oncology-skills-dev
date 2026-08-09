"""synthesis_tractability_sm — the opt-in small-molecule tractability lens narrator (prompt build +
tool schema + two-slot dispatch). Bedrock fully mocked (no network).

Pins: (1) the tool schema is CONFIDENCE-only (no druggability_snapshot field the LLM could emit);
(2) build_user_prompt reads the FULL tractability evidence set and renders a measured-but-unavailable
card as DATA_UNAVAILABLE (H1 drops-nulls guard); (3) the on-target-vs-forward-structural + discordant-
argues-against steer is present; (4) two-slot byte-stability through the dispatcher; (5) failure degrades
to a note; (6) publication register + deterministic metric legend.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis_tractability_sm as ST  # noqa: E402
from _skills_common import dispatcher as D  # noqa: E402


def _decision(structure_missing: bool = True):
    """A realistic tractability-small-molecule decision spine (mirrors run.py::_headline)."""
    return {
        "target": "KRAS", "indication": "COADREAD",
        "headline": {
            "druggability_snapshot": "chemically_confirmed_genetic",
            "driving_rule_id": "e7-crispr-confirmed-supportive-sm",
            "degrader_snapshot": "degrader_rationale",
            "degrader_driving_rule_id": "degrader-supportive",
            "degradability_machinery": "not_yet_assessed",
            "prism_activity_class": "clinically_active",
            "prism_crispr_concord": "concordant",
            "predictability_class": "own_omics_driven",
            "hotspot_pocket_adjacency": "in_pocket",
            "hotspot_in_druggable_pocket": True,
            "pdb_coverage_class": "high_coverage",
            "alphafold_confidence_class": "high_confidence",
        },
        "cards": [
            {"card_id": "prism-compound-activity", "_missing": False, "summary": {}},
            {"card_id": "prism-crispr-concordance", "_missing": False, "summary": {}},
            {"card_id": "dependency-predictability", "_missing": False, "summary": {}},
            {"card_id": "structure-features-static", "_missing": structure_missing, "summary": {}},
        ],
    }


# ---- schema is confidence-only ----
def test_tool_schema_has_no_verdict_field():
    props = set(ST.SYNTHESIS_TOOL_SCHEMA["properties"])
    assert "druggability_snapshot" not in props and "degrader_snapshot" not in props
    assert props == {"tractability_relevance_for_target", "tractability_rationale",
                     "on_target_vs_structural_read", "confidence_qualifier", "key_caveat"}
    assert ST.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


# ---- prompt reads the full evidence set and never drops a null ----
def test_prompt_grounds_full_evidence():
    p = ST.build_user_prompt(_decision())
    assert "druggability_snapshot: chemically_confirmed_genetic" in p
    for token in ("RETROSPECTIVE CHEMICAL EVIDENCE", "ON-TARGET ENGAGEMENT",
                  "FORWARD STRUCTURAL LIGANDABILITY", "PREDICTABILITY", "degrader_snapshot"):
        assert token in p, f"missing block: {token}"


def test_prompt_renders_unavailable_card_as_data_unavailable():
    p = ST.build_user_prompt(_decision(structure_missing=True))
    assert "structure-features-static: DATA_UNAVAILABLE" in p


def test_prompt_carries_discordant_and_structural_steer():
    p = ST.build_user_prompt(_decision())
    assert "DISCORDANT" in p and "ARGUES AGAINST" in p
    assert "FORWARD" in p and "DEGRADER" in p


# ---- two-slot byte-stability through the dispatcher ----
def _run_dispatch(tmp_path, *, synthesize):
    card_outputs = [{"card_id": "prism-compound-activity", "summary": {}, "_missing": False}]

    def _headline(cards, fired, vp):
        return {"druggability_snapshot": "chemically_confirmed_genetic",
                "driving_rule_id": "e7-crispr-confirmed-supportive-sm"}

    argv = ["--target", "KRAS", "--indication", "COADREAD", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    def _fake(decision, model_id=None, subtype_query=None):
        return {"tractability_relevance_for_target": {"value": "strongly_supports",
                "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}

    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="tractability-small-molecule", skill_version="9.9.9",
            cards=["prism-compound-activity"], axis="intracellular_intrinsic",
            question="Is {target} druggable in {indication}?",
            headline_fn=_headline, synthesize_fn=_fake, argv=argv)
    return json.loads((tmp_path / "decision.json").read_text())


def test_two_slot_byte_stability(tmp_path, scrub_volatile):
    base = scrub_volatile(_run_dispatch(tmp_path / "a", synthesize=False))
    synth = scrub_volatile(_run_dispatch(tmp_path / "b", synthesize=True))
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    assert {k: v for k, v in synth.items() if k != "llm_synthesis"} == base


def test_synthesis_failure_degrades_to_note(tmp_path):
    card_outputs = [{"card_id": "prism-compound-activity", "summary": {}, "_missing": False}]

    def _headline(cards, fired, vp):
        return {"druggability_snapshot": "chemically_confirmed_genetic",
                "driving_rule_id": "e7-crispr-confirmed-supportive-sm"}

    def _boom(decision, model_id=None, subtype_query=None):
        raise RuntimeError("bedrock down")

    out = tmp_path / "c"
    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="tractability-small-molecule", skill_version="9.9.9",
            cards=["prism-compound-activity"], axis="intracellular_intrinsic",
            question="Is {target} druggable in {indication}?",
            headline_fn=_headline, synthesize_fn=_boom,
            argv=["--target", "KRAS", "--indication", "COADREAD", "--out", str(out), "--synthesize"])
    d = json.loads((out / "decision.json").read_text())
    assert "_synthesis_error" in d["llm_synthesis"]
    assert d["headline"]["druggability_snapshot"] == "chemically_confirmed_genetic"


# --- publication-register + deterministic metric legend ---

def test_metric_legend_is_deterministic_and_covers_cited_metrics():
    keys = set(ST.METRIC_LEGEND)
    assert {"druggability_snapshot", "prism_activity_class", "prism_crispr_concord",
            "hotspot_pocket_adjacency", "pdb_coverage_class", "predictability_class",
            "degrader_snapshot"} <= keys
    for k, v in ST.METRIC_LEGEND.items():
        assert isinstance(v, str) and len(v) > 40, f"{k} legend too short"
    # the concordance legend must explain the on-target/off-target meaning
    assert "off-target" in ST.METRIC_LEGEND["prism_crispr_concord"].lower()


def test_legend_attached_on_success_not_on_failure():
    ok = {"tractability_relevance_for_target": {"value": "supports_with_caveats",
          "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}
    with patch("_skills_common.llm.synthesize_structured", return_value=dict(ok)):
        res = ST.synthesize_tractability_sm(_decision())
    assert res["metric_legend"] == ST.METRIC_LEGEND

    degraded = {"_synthesis_error": "RuntimeError: bedrock down", "_note": "..."}
    with patch("_skills_common.llm.synthesize_structured", return_value=dict(degraded)):
        res2 = ST.synthesize_tractability_sm(_decision())
    assert "metric_legend" not in res2 and "_synthesis_error" in res2


def test_system_prompt_enforces_publication_register_and_glosses():
    sysp = ST._SYSTEM.lower()
    assert "publication" in sysp
    assert "promotional" in sysp or "editorialis" in sysp
    assert "promising" in sysp
    assert "gloss" in sysp
    desc = ST.SYNTHESIS_TOOL_SCHEMA["properties"]["tractability_rationale"]["description"].lower()
    assert "publication register" in desc and "plain language" in desc
