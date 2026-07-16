"""Tests for the deterministic recommendation gate in target-profile/run.py.

The gate forces overall_recommendation from killer sub-verdicts regardless of
what the LLM chose. These tests exercise the pure `_gate_recommendation` helper
(no Bedrock) + the clamp semantics.

Key correctness property (from the KRAS×COADREAD golden): modality-scoped killers
(surface neither_viable, degrader expression killers) must NOT force a blanket
veto — KRAS hits those yet is a correct `nominate` via small molecule.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load_run_module()


def _sub(short, verdict, rule="some-rule"):
    return {short: {"verdict": (verdict, rule) if verdict else None}}


def _merge(*dicts):
    out = {}
    for d in dicts:
        out.update(d)
    return out


def test_pan_essential_killer_forces_veto():
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    forced, hits = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert len(hits) == 1 and hits[0]["short"] == "dependency"
    assert hits[0]["driving_rule_id"] == "pan-essential-killer"


def test_non_dependent_forces_veto():
    forced, hits = tp._gate_recommendation(_sub("dependency", "non_dependent", "non-dependent-killer"))
    assert forced == "veto"


def test_safety_concern_forces_hold_not_veto():
    forced, hits = tp._gate_recommendation(
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning"))
    assert forced == "hold"


def test_kras_pattern_no_override():
    """KRAS: dependency=lineage_selective (not a killer), surface=neither_viable
    (modality-scoped, excluded). The gate must NOT fire — LLM's nominate stands."""
    subs = _merge(
        _sub("dependency", "lineage_selective", "lineage-selective-supportive"),
        _sub("surface_modality", "neither_viable", "neither-viable-killer"),
        _sub("expression", "broadly_low_expression", "expression-broadly-low-degrader-killer"),
    )
    forced, hits = tp._gate_recommendation(subs)
    assert forced is None
    assert hits == []


def test_veto_dominates_hold_when_both_fire():
    subs = _merge(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"),
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning"),
    )
    forced, hits = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert len(hits) == 2


def test_no_verdict_and_none_verdict_ignored():
    subs = _merge(
        {"selectivity": {"verdict": None}},          # sub-skill with no verdict fn
        _sub("dependency", "concordant_dependent"),  # supportive, not a gate
    )
    forced, hits = tp._gate_recommendation(subs)
    assert forced is None and hits == []


def test_loader_reads_vocab_when_present(tmp_path):
    """_load_gate_verdicts reads the target-contracts vocab and returns source='vocab'."""
    vocab_dir = tmp_path / "vocabularies"; vocab_dir.mkdir()
    (vocab_dir / "nomination_verdict_gate.yaml").write_text(
        "gates:\n"
        "  - {sub_skill: dependency, verdict: pan_essential_killer, action: veto}\n"
        "  - {sub_skill: safety, verdict: highly_constrained_safety_concern, action: hold}\n"
    )
    mapping, source = tp._load_gate_verdicts(contracts_repo=tmp_path)
    assert source == "vocab"
    assert mapping[("dependency", "pan_essential_killer")] == "veto"
    assert mapping[("safety", "highly_constrained_safety_concern")] == "hold"


def test_loader_falls_back_conservatively_on_missing_vocab(tmp_path):
    """SAFETY: a missing vocab returns the hardcoded conservative set, NOT empty."""
    mapping, source = tp._load_gate_verdicts(contracts_repo=tmp_path / "nonexistent")
    assert source == "fallback"
    assert mapping == tp._FALLBACK_GATE_VERDICTS
    # the pan-essential veto MUST survive the fallback (never permissive)
    assert mapping[("dependency", "pan_essential_killer")] == "veto"


def test_loader_falls_back_on_malformed_vocab(tmp_path):
    vocab_dir = tmp_path / "vocabularies"; vocab_dir.mkdir()
    (vocab_dir / "nomination_verdict_gate.yaml").write_text("gates: []\n")  # empty → invalid
    mapping, source = tp._load_gate_verdicts(contracts_repo=tmp_path)
    assert source == "fallback"
    assert ("dependency", "pan_essential_killer") in mapping


def test_gate_uses_fallback_when_vocab_absent(tmp_path):
    """End-to-end: with no vocab, the gate still vetoes a pan-essential killer."""
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    forced, hits = tp._gate_recommendation(subs, contracts_repo=tmp_path / "nope")
    assert forced == "veto"
    assert hits[0]["policy_source"] == "fallback"


def test_clamp_semantics_on_wrapped_output():
    """Simulate the run.py clamp: a killer forces veto over an LLM 'nominate',
    preserving the wrapped {value, _source, ...} shape + marking _gated."""
    llm_output = {"overall_recommendation": {"value": "nominate", "_source": "llm_synthesized",
                                             "_model_id": "x", "_prompt_hash": "y"}}
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    gate_action, gate_hits = tp._gate_recommendation(subs)
    assert gate_action == "veto"
    # replicate the clamp block
    rec = llm_output["overall_recommendation"]
    llm_value = rec["value"]
    rec["value"] = gate_action
    rec["_gated"] = True
    assert llm_output["overall_recommendation"]["value"] == "veto"
    assert llm_output["overall_recommendation"]["_gated"] is True
    assert llm_value == "nominate"  # original preserved for the override record
