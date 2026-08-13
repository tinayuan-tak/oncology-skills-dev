"""Emitter-stage guard — target-profile `--emit evidence-package` produces a schema-valid,
LLM-free evidence_package.json from the SAME per-sub-skill verdict spine.

Drives `_write_evidence_package` directly (target-identity read monkeypatched) so it runs
offline. Asserts:
  1. the envelope validates against target-contracts/schemas/evidence_package.schema.json;
  2. the SUPERSET synthesis shape (product decision): nomination fields + a compose-dashboard-style
     primary/additional split + full per-sub-skill sub_verdicts, all sourced from the Stage-1b
     CompositionResult (r["composition"]);
  3. a gateless sub-skill (tumor-presence `expression`) contributes no gate block but keeps its
     verdict in sub_verdicts;
  4. it is LLM-free (no llm_synthesis / model / prompt-hash anywhere);
  5. target identity resolves so context.target.hgnc_id >= 1 (a valid governance artifact).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
SKILLS = Path(__file__).resolve().parents[2]  # .../skills
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.compose_core import subskill_composition  # noqa: E402

CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))


def _load_run_module():
    spec = importlib.util.spec_from_file_location("tp_run_emit", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load_run_module()

_IDENTITY_CARD = {
    "card_id": "target-identity-summary",
    "summary": {"resolved_hgnc_symbol": "KRAS", "resolved_hgnc_id": 6407},
    "interpretation_call": "resolved",
    "provenance": {"method_calls": [], "input_manifest_ids": []},
}


def _sub(card_id, fired_id, gate, verdict_pair):
    cards = [{"card_id": card_id, "summary": {"x": 1},
              "interpretation_call": "informative",
              "provenance": {"method_calls": [], "input_manifest_ids": []}}]
    fired = [{"rule_id": fired_id}]
    return {
        "skill_dir": f"dir-{gate or 'none'}",
        "cards": cards,
        "fired": fired,
        "verdict": verdict_pair,
        "composition": subskill_composition(
            card_outputs=cards, fired=fired, gate=gate, verdict_pair=verdict_pair),
    }


def _build_ep(tmp_path, monkeypatch):
    # target-identity is read separately by the emitter — return a resolved card so hgnc_id >= 1.
    monkeypatch.setattr(tp, "resolve_cards",
                        lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)])
    sub_results = {
        "expression": _sub("tumor-rna-distribution", "expr-01", None,
                           ("tumor_broadly_expressed", "expr-01")),   # GATELESS
        "dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency",
                           ("selective_dependency", "dep-01")),
        "selectivity": _sub("tumor-vs-normal-selectivity", "sel-01", "selectivity",
                            ("tumor_selective", "sel-01")),
    }
    args = SimpleNamespace(target="KRAS", indication="COADREAD",
                           release_pin=None, out=tmp_path)
    ep_path = tp._write_evidence_package(
        args=args, sub_results=sub_results, gate_action="nominate",
        recommendation_gate={"fired": True, "forced_recommendation": "nominate"},
        confidence_tier={"tier": "high"},
        deciding_axis={"basis": "gate_fired",
                       "deciding_axis": {"short": "dependency", "gate": "dependency"},
                       "routing": "decided by gate dependency"},
        validation_summary={"n_cards_attempted": 3, "n_cards_passed": 3,
                            "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                            "n_cards_excluded_by_applies_when": 0},
    )
    return json.loads(Path(ep_path).read_text())


def test_envelope_is_schema_valid(tmp_path, monkeypatch):
    ep = _build_ep(tmp_path, monkeypatch)
    schema = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())
    errors = [f"[{'.'.join(str(p) for p in e.absolute_path) or '<root>'}] {e.message}"
              for e in Draft202012Validator(schema).iter_errors(ep)]
    assert errors == [], f"evidence_package failed schema validation: {errors}"


def test_context_target_identity_resolved(tmp_path, monkeypatch):
    ep = _build_ep(tmp_path, monkeypatch)
    assert ep["context"]["target"]["hgnc_id"] == 6407  # >= 1 → valid governance artifact


def test_superset_synthesis_shape(tmp_path, monkeypatch):
    ep = _build_ep(tmp_path, monkeypatch)
    syn = ep["synthesis"]
    # nomination-shaped fields present
    assert syn["recommendation_gate"]["forced_recommendation"] == "nominate"
    assert syn["confidence_tier"]["tier"] == "high"
    assert syn["deciding_axis"]["basis"] == "gate_fired"
    # compose-dashboard-shaped split: deciding gate is primary; the other gated short is additional
    assert syn["primary_gate_verdict"]["gate"] == "dependency"
    assert syn["primary_gate_verdict"]["verdict"] == "selective_dependency"
    add_gates = {b["gate"] for b in syn["additional_gate_verdicts"]}
    assert add_gates == {"selectivity"}
    # per-sub-skill grouping carries all three, incl. the gateless one
    assert set(syn["sub_verdicts"]) == {"expression", "dependency", "selectivity"}


def test_gateless_expression_kept_without_gate_block(tmp_path, monkeypatch):
    ep = _build_ep(tmp_path, monkeypatch)
    syn = ep["synthesis"]
    exp = syn["sub_verdicts"]["expression"]
    assert exp["verdict"] == "tumor_broadly_expressed"   # verdict preserved
    assert exp["gate"] is None                            # but no resolver gate
    # gateless short must NOT appear as a gate block
    all_block_gates = ({syn["primary_gate_verdict"]["gate"]}
                       | {b["gate"] for b in syn["additional_gate_verdicts"]})
    assert "expression" not in all_block_gates


def test_envelope_is_llm_free(tmp_path, monkeypatch):
    ep = _build_ep(tmp_path, monkeypatch)
    blob = json.dumps(ep)
    assert "llm_synthesis" not in ep
    assert "llm_synthesis" not in ep["synthesis"]
    for marker in ("_model_id", "_prompt_hash", "llm_synthesized"):
        assert marker not in blob, f"unexpected LLM marker {marker!r} in evidence-package"
    assert ep["generated_by"].startswith("skills/target-profile@")
