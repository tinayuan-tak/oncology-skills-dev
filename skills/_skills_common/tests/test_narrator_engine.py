"""narrator_engine — the ONE generic capsule-driven single-lens narrator. Deterministic prompt/schema
assertions, no Bedrock. Two-slot / verdict-inert."""
from __future__ import annotations
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import narrator_engine as NE  # noqa: E402
from _skills_common.narrator_lenses import FUNCTIONAL_REQUIREMENT, ON_TARGET_SAFETY  # noqa: E402


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


def test_make_synthesize_fn_signature(monkeypatch):
    seen = {}
    monkeypatch.setattr(NE, "narrate", lambda dec, lens, model_id=None: seen.update(lens=lens.name, m=model_id) or {"ok": 1})
    fn = NE.make_synthesize_fn(FUNCTIONAL_REQUIREMENT)
    out = fn(_decision(), "modelX", "MSI_H")                 # (decision, model_id, subtype_query)
    assert out == {"ok": 1} and seen["lens"] == "functional-requirement" and seen["m"] == "modelX"
