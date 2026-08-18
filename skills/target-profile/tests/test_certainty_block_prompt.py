"""Phase 0 of the per-axis certainty layer: the ALREADY-computed fragility facet is routed into
the Tier-3 synthesis prompt as a per-axis how-solid block, so synthesis stops treating a
coverage-thin / flip-fragile axis identically to a rock-solid one.

Pins that _build_user_prompt embeds the certainty block with (a) a per-axis coverage +
call-fragility + missing-card row, (b) the aggregate fragility indices, (c) the blind-axis gap
list, and (d) the honesty framing (weakest-link, absence-of-evidence != negative, VERDICT-INERT).
Purely additive: omitting `fragility` leaves the prompt in its pre-Phase-0 shape. Bedrock-free
(renders the prompt string only). The DETERMINISTIC verdict/gate/confidence spine is untouched by
this change — this test guards the prompt text only, which is exactly the boundary Phase 0 moves.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_certainty", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _sub_results():
    return {
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {"x": 1}},
                                 {"card_id": "rnai", "summary": {"x": 1}}],
                       "verdict": ("lineage_selective", "lineage-selective-supportive"),
                       "fired": []},
        "selectivity": {"skill_dir": "tumor-selectivity",
                        "cards": [{"card_id": "sel", "summary": {}}],
                        "verdict": ("strong_tumor_selective", "x"),
                        "fired": []},
        "safety": {"skill_dir": "on-target-safety-liability",
                   # every card missing this run → the axis is blind (coverage gap, not a negative)
                   "cards": [{"card_id": "gnomad", "summary": {}, "_missing": True,
                              "_missing_reason": "data_unavailable"}],
                   "verdict": ("insufficient", None),
                   "fired": []},
    }


def _fragility():
    """Mirrors the real _fragility_facet emit shape (see tp_facets._fragility_facet)."""
    return {
        "target_index": 0.5,
        "recommendation_fragility_index": 0.0,
        "contested": False,
        "decision_relevant_axes": ["dependency", "safety", "selectivity"],
        "blind_decision_axes": ["safety"],
        "per_axis": {
            "dependency": {"gate": "dependency", "has_signal": True, "coverage": "high",
                           "base_verdict": "lineage_selective", "fragility": 0.5},
            "selectivity": {"gate": "selectivity", "has_signal": True, "coverage": "medium",
                            "base_verdict": "strong_tumor_selective", "fragility": 0.0},
            "safety": {"gate": "safety", "has_signal": False, "coverage": "blind",
                       "fragility": None, "reason": "blind"},
        },
    }


def test_prompt_includes_certainty_block_when_provided():
    prompt = tp._build_user_prompt("KRAS", "COADREAD", _sub_results(), fragility=_fragility())
    assert "### Per-axis certainty / how-solid facet" in prompt
    # per-axis rows: evidenced axis shows its call + coverage + fragility; blind axis shows the gap
    assert "| dependency | `lineage_selective` | high | 0.5 |" in prompt
    assert "| selectivity | `strong_tumor_selective` | medium | 0.0 |" in prompt
    assert "blind" in prompt and "(blind — no evidenced verdict)" in prompt
    # aggregate indices + contested surfaced
    assert "target_index): 0.5" in prompt and "recommendation_fragility_index): 0.0" in prompt
    # blind-axis gap list names the un-evidenced decision-relevant axis
    assert "BLIND decision-relevant axes" in prompt and "'safety'" in prompt


def test_certainty_block_shows_missing_card_count():
    prompt = tp._build_user_prompt("KRAS", "COADREAD", _sub_results(), fragility=_fragility())
    # safety had 1/1 cards missing this run; dependency 0/2
    assert "| safety | " in prompt and "| 1/1 |" in prompt
    assert "| dependency |" in prompt and "| 0/2 |" in prompt


def test_certainty_block_carries_weakest_link_and_mnar_framing():
    prompt = tp._build_user_prompt("KRAS", "COADREAD", _sub_results(), fragility=_fragility())
    seg = prompt[prompt.find("### Per-axis certainty"):]
    seg = seg[:seg.find("### ", 5)] if "### " in seg[5:] else seg
    assert "WEAKEST-LINK" in seg
    assert "ABSENCE OF EVIDENCE" in seg and "NOT evidence of absence" in seg
    assert "VERDICT-INERT" in seg
    assert "NOT a probability the target succeeds" in seg
    assert "do NOT average" in seg or "never sum/average" in seg


def test_prompt_backward_compatible_without_fragility():
    """Omitting `fragility` (the pre-Phase-0 call shape) must still produce a valid prompt with NO
    certainty block — purely additive, so the spine and every existing prompt test are unaffected."""
    prompt = tp._build_user_prompt("KRAS", "COADREAD", _sub_results())  # no fragility
    assert "### Per-axis certainty / how-solid facet" not in prompt
    assert "### Sub-verdicts" in prompt


def test_certainty_block_empty_per_axis_renders_nothing():
    """A facet with no per_axis (e.g. no decision-relevant axis this run) emits no block rather
    than a header with an empty table."""
    prompt = tp._build_user_prompt("KRAS", "COADREAD", _sub_results(),
                                   fragility={"per_axis": {}, "blind_decision_axes": []})
    assert "### Per-axis certainty / how-solid facet" not in prompt
