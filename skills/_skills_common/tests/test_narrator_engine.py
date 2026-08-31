"""narrator_engine — the ONE generic capsule-driven single-lens narrator. Deterministic prompt/schema
assertions, no Bedrock. Two-slot / verdict-inert."""
from __future__ import annotations
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import narrator_engine as NE  # noqa: E402
from _skills_common.narrator_lenses import (  # noqa: E402
    FUNCTIONAL_REQUIREMENT, ON_TARGET_SAFETY, TUMOR_SELECTIVITY)


def _decision():
    return {"target": "KRAS", "indication": "COADREAD",
            "headline": {"verdict": "lineage_selective", "driving_rule_id": "lineage-selective-supportive",
                         "subgroup_signals": {"DEP": {"signal": "strong", "confidence": "high", "n_sources": 6,
                                                      "n_agree": 5, "power": "high", "conflict": False, "sources": []}}},
            "cards": [{"card_id": "pan-cancer-crispr-dependency-distribution",
                       "summary": {"dependency_class": "strongly_selective", "median_chronos_panel": -0.457,
                                   "selectivity_index": 0.85, "n_cell_lines_evaluated": 1538}}]}


def test_verdict_tool_uses_lens_relevance_enum():
    name, schema = NE._tool(FUNCTIONAL_REQUIREMENT)
    assert name == "emit_functional_requirement_synthesis"
    assert schema["properties"]["relevance"]["enum"] == list(FUNCTIONAL_REQUIREMENT.relevance_enum)
    assert schema["additionalProperties"] is False
    # safety carries its OWN liability enum (polarity-specific)
    _, s2 = NE._tool(ON_TARGET_SAFETY)
    assert "high_liability" in s2["properties"]["relevance"]["enum"]


def test_descriptive_mode_tool_has_no_relevance_verdict():
    from _skills_common.narrator_engine import LensConfig
    lens = LensConfig(name="combination-and-vulnerability", thesis="t", relevance_prompt="p", mode="descriptive")
    name, schema = NE._tool(lens)
    assert name.endswith("_context")
    assert "relevance" not in schema["properties"] and "context_read" in schema["properties"]


def test_system_prompt_threads_polarity_and_scope():
    s = NE._system(ON_TARGET_SAFETY).lower()
    assert "liability" in s and "reassuring" in s          # polarity note threaded
    assert "do not discuss" in s                            # scope exclusions threaded
    assert "never change the deterministic" in s            # verdict-inert guardrail


def test_prompt_carries_signal_lead_and_capsules_and_scope():
    p = NE.build_capsule_prompt(_decision(), FUNCTIONAL_REQUIREMENT)
    assert "SUB-GROUP SIGNALS" in p                          # signal layer (contract)
    assert "EVIDENCE CAPSULES" in p and "card floor" in p    # data layer (capsules) + completeness
    assert "selectivity_index=0.85" in p                     # a bounded raw anchor reached the prompt
    assert "COLLAPSED VERDICT" in p and "lineage_selective" in p
    assert p.index("SUB-GROUP SIGNALS") < p.index("COLLAPSED VERDICT")   # signals lead, verdict trails


def test_selectivity_collapsed_verdict_is_resolved_class_not_rule_id():
    """The tumor-selectivity lens declares verdict_key='selectivity_class', so the COLLAPSED VERDICT
    prompt line injects the RESOLVED (post-veto) class token — not driving_rule_id (a rule-id string
    like 'tvn-...-veto'), which is what the fallback chain landed on before the fix. Mirrors the
    TUMOR_PRESENCE verdict_key contract."""
    assert TUMOR_SELECTIVITY.verdict_key == "selectivity_class"
    decision = {"target": "TACSTD2", "indication": "COADREAD",
                "headline": {"selectivity_class": "selective_but_broadly_normal",
                             "driving_rule_id": "tvn-no-therapeutic-window-veto",
                             "claim_vector": {"WIN": {"signal": "strong", "corroboration": "high"}}}}
    p = NE.build_capsule_prompt(decision, TUMOR_SELECTIVITY)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "selective_but_broadly_normal" in collapsed
    assert "tvn-no-therapeutic-window-veto" not in collapsed


def test_functional_requirement_collapsed_verdict_is_resolved_token_not_rule_id():
    """The functional-requirement lens declares verdict_key='dependency_verdict', so the COLLAPSED
    VERDICT prompt line injects the RESOLVED dependency verdict token — not driving_rule_id (a rule-id
    string like 'pan-essential-killer'), which is what the fallback chain landed on before the fix (the
    FR headline key is dependency_verdict, never 'verdict'). Mirrors the presence/selectivity contract.
    The pan_essential case matters most: leaking the rule-id would rob the narrator of the resolved
    'this is a liability' token."""
    assert FUNCTIONAL_REQUIREMENT.verdict_key == "dependency_verdict"
    decision = {"target": "PLK1", "indication": "COADREAD",
                "headline": {"dependency_verdict": "pan_essential_killer",
                             "driving_rule_id": "pan-essential-killer",
                             "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high"}}}}
    p = NE.build_capsule_prompt(decision, FUNCTIONAL_REQUIREMENT)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "pan_essential_killer" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert collapsed.count("pan-essential-killer") == 0


def test_make_synthesize_fn_signature(monkeypatch):
    seen = {}
    monkeypatch.setattr(NE, "narrate", lambda dec, lens, model_id=None: seen.update(lens=lens.name, m=model_id) or {"ok": 1})
    fn = NE.make_synthesize_fn(FUNCTIONAL_REQUIREMENT)
    out = fn(_decision(), "modelX", "MSI_H")                 # (decision, model_id, subtype_query)
    assert out == {"ok": 1} and seen["lens"] == "functional-requirement" and seen["m"] == "modelX"
