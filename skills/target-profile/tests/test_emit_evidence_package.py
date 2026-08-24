"""Emitter-stage guard — target-profile `--emit evidence-package` produces a schema-valid,
LLM-free evidence_package.json from the SAME per-sub-skill verdict spine.

Drives `_write_evidence_package` directly (target-identity read monkeypatched) so it runs
offline. Asserts:
  1. the envelope validates against target-contracts/schemas/evidence_package.schema.json;
  2. the SUPERSET synthesis shape (product decision): nomination fields + a compose-dashboard-style
     primary/additional split + full per-sub-skill sub_verdicts, all sourced from the
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
# _write_evidence_package (and its resolve_cards call) moved to tp_evidence_package in the
# 2026-08-16 god-module split; patch resolve_cards there so it is intercepted in that namespace.
import tp_evidence_package  # noqa: E402

_IDENTITY_CARD = {
    "card_id": "target-identity-summary",
    "summary": {"resolved_hgnc_symbol": "KRAS", "resolved_hgnc_id": 6407},
    "interpretation_call": "resolved",
    "provenance": {"method_calls": [], "input_manifest_ids": []},
}


def _sub(card_id, fired_id, gate, verdict_pair, synthesis_facet=None):
    cards = [{"card_id": card_id, "summary": {"x": 1},
              "interpretation_call": "informative",
              "provenance": {"method_calls": [], "input_manifest_ids": []}}]
    fired = [{"rule_id": fired_id}]
    out = {
        "skill_dir": f"dir-{gate or 'none'}",
        "cards": cards,
        "fired": fired,
        "verdict": verdict_pair,
        "composition": subskill_composition(
            card_outputs=cards, fired=fired, gate=gate, verdict_pair=verdict_pair),
    }
    if synthesis_facet is not None:
        out["synthesis_facet"] = synthesis_facet   # the fan-out stashes the claim-vector facet here
    return out


# A dependency synthesis_facet carrying a claim_vector with a citable evidence atom.
_DEP_FACET = {
    "claim_vector": {
        "DEP": {"signal": "strong", "corroboration": "high", "evidence": "CRISPR strongly_selective",
                "conflict": None, "informs": "dep",
                "evidence_atom": {
                    "read": "strongly_selective",
                    "values": {"bimodality_coefficient": 0.70, "fraction_strongly_dependent": 0.176},
                    "cite": {"card_id": "pan-cancer-crispr-dependency-distribution",
                             "fields": ["bimodality_coefficient", "fraction_strongly_dependent"]},
                    "entity": {"measurement_type": "crispr_lof_dependency",
                               "sample_context": "cell_line", "stratum": "pan_cancer"}}},
        "_disclaimer": "verdict-inert projection"},
    "key_signals": {"headline": "Strong genetic dependency.", "supports": [], "caveat": None},
}


def _build_ep(tmp_path, monkeypatch):
    # target-identity is read separately by the emitter — return a resolved card so hgnc_id >= 1.
    monkeypatch.setattr(tp_evidence_package, "resolve_cards",
                        lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)])
    sub_results = {
        "expression": _sub("tumor-rna-distribution", "expr-01", None,
                           ("tumor_broadly_expressed", "expr-01")),   # GATELESS
        "dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency",
                           ("selective_dependency", "dep-01"), synthesis_facet=_DEP_FACET),
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


def test_synthesis_carries_claim_vectors_with_citable_atoms(tmp_path, monkeypatch):
    # the machine envelope carries each sub-skill's claim_vector (+ key_signals) — the SIGNAL
    # decomposition + citable evidence atoms — so a downstream reasoner sees more than the verdict label.
    ep = _build_ep(tmp_path, monkeypatch)
    cv = ep["synthesis"]["claim_vectors"]
    # the dependency short exposed a synthesis_facet → carried, with the citable atom intact
    assert "dependency" in cv
    atom = cv["dependency"]["claim_vector"]["DEP"]["evidence_atom"]
    assert atom["cite"]["card_id"] == "pan-cancer-crispr-dependency-distribution"
    assert atom["values"]["bimodality_coefficient"] == 0.70          # the numeric value survives to the envelope
    assert "bimodality_coefficient" in atom["cite"]["fields"]        # citable by discrete token
    assert cv["dependency"]["key_signals"]["headline"] == "Strong genetic dependency."
    # shorts with NO synthesis_facet contribute nothing (byte-stable for un-migrated skills)
    assert "expression" not in cv and "selectivity" not in cv


def test_claim_vectors_empty_when_no_facets(tmp_path, monkeypatch):
    # helper is a pure projection: no synthesis_facet anywhere → empty dict, never a crash.
    assert tp_evidence_package._claim_vectors_from_sub_results(
        {"a": {"cards": [], "fired": []}, "b": {"synthesis_facet": {"key_signals": {}}}}) == {}


def test_none_verdict_gateless_short_in_evidence_package(tmp_path, monkeypatch):
    """(2026-08-17): the --emit evidence-package emitter must tolerate a verdict=None GATELESS
    short (target-intrinsic — synthesis:none, no gate). It contributes NO gate block but appears in
    sub_verdicts with verdict=None/gate=None, and the envelope stays schema-valid."""
    monkeypatch.setattr(tp_evidence_package, "resolve_cards",
                        lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)])
    sub_results = {
        "dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency",
                           ("selective_dependency", "dep-01")),
        # gateless + NO verdict (gate=None, verdict_pair=None) — the target-intrinsic pattern
        "target_intrinsic": _sub("protein-domains-class", "ti-01", None, None),
    }
    args = SimpleNamespace(target="KRAS", indication="COADREAD", release_pin=None, out=tmp_path)
    ep_path = tp._write_evidence_package(
        args=args, sub_results=sub_results, gate_action="nominate",
        recommendation_gate={"fired": True, "forced_recommendation": "nominate"},
        confidence_tier={"tier": "high"},
        deciding_axis={"basis": "gate_fired",
                       "deciding_axis": {"short": "dependency", "gate": "dependency"},
                       "routing": "decided by gate dependency"},
        validation_summary={"n_cards_attempted": 2, "n_cards_passed": 2,
                            "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                            "n_cards_excluded_by_applies_when": 0})
    ep = json.loads(Path(ep_path).read_text())
    schema = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(ep)]
    assert errors == [], f"evidence_package failed schema validation with a None-verdict gateless short: {errors}"
    ti = ep["synthesis"]["sub_verdicts"]["target_intrinsic"]
    assert ti["verdict"] is None and ti["gate"] is None       # descriptive, non-gating
    # never appears as a gate block
    all_block_gates = ({ep["synthesis"]["primary_gate_verdict"]["gate"]}
                       | {b["gate"] for b in ep["synthesis"]["additional_gate_verdicts"]})
    assert "target_intrinsic" not in all_block_gates


def test_envelope_is_llm_free(tmp_path, monkeypatch):
    ep = _build_ep(tmp_path, monkeypatch)
    blob = json.dumps(ep)
    assert "llm_synthesis" not in ep
    assert "llm_synthesis" not in ep["synthesis"]
    for marker in ("_model_id", "_prompt_hash", "llm_synthesized"):
        assert marker not in blob, f"unexpected LLM marker {marker!r} in evidence-package"
    assert ep["generated_by"].startswith("skills/target-profile@")


# ── the two previously-UNCOVERED branches (2026-08-14 critical-issues sweep) ──────────────────────

def _emit(tmp_path, monkeypatch, *, gate_action, identity_ok):
    """Drive _write_evidence_package with configurable gate_action + whether target-identity resolves.
    Returns the parsed envelope (raises SystemExit if the emitter's schema validation fails)."""
    if identity_ok:
        monkeypatch.setattr(tp_evidence_package, "resolve_cards",
                            lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)])
    else:
        # identity read yields a _missing card → assemble emits the hgnc_id=-1 unresolved sentinel
        monkeypatch.setattr(tp_evidence_package, "resolve_cards",
                            lambda card_ids, target, indication, **kw: [
                                {"card_id": "target-identity-summary", "_missing": True,
                                 "_missing_reason": "identity read failed (test)"}])
    sub_results = {
        "expression": _sub("tumor-rna-distribution", "expr-01", None,
                           ("tumor_broadly_expressed", "expr-01")),
        "dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency",
                           ("selective_dependency", "dep-01")),
    }
    args = SimpleNamespace(target="KRAS", indication="COADREAD", release_pin=None, out=tmp_path)
    ep_path = tp._write_evidence_package(
        args=args, sub_results=sub_results, gate_action=gate_action,
        recommendation_gate={"fired": bool(gate_action)},
        confidence_tier={"tier": "strong"},
        deciding_axis={"basis": "gate_fired",
                       "deciding_axis": {"short": "dependency", "gate": "dependency"}, "routing": "x"},
        validation_summary={"n_cards_attempted": 2, "n_cards_passed": 2,
                            "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                            "n_cards_excluded_by_applies_when": 0},
    )
    return json.loads(Path(ep_path).read_text())


def test_validation_summary_dedupes_multi_homed_cards(tmp_path, monkeypatch):
    """(2026-08-15): a card composing under >1 sub-skill lens must be counted ONCE in
    validation_summary — the raw union double-counted it (inflated n_cards_attempted). The counts must
    equal the DEDUPED payload the evidence-package `cards` array carries."""
    shared = {"card_id": "shared-multi-homed", "summary": {"x": 1},
              "interpretation_call": "informative",
              "provenance": {"method_calls": [], "input_manifest_ids": []}}
    missing = {"card_id": "gone", "_missing": True}
    sub_results = {
        "dependency": {"cards": [dict(shared), {"card_id": "dep-only", "summary": {}, "_missing": False,
                                                "interpretation_call": "informative",
                                                "provenance": {"method_calls": [], "input_manifest_ids": []}}]},
        # `shared-multi-homed` composes AGAIN under a second lens + a missing card
        "selectivity": {"cards": [dict(shared), dict(missing)]},
    }
    vs = tp._validation_summary_from_sub_results(sub_results)
    # distinct card_ids: shared-multi-homed, dep-only, gone == 3 (NOT 4 — shared counted once)
    assert vs["n_cards_attempted"] == 3, vs
    assert vs["n_cards_failed"] == 1                      # only `gone`
    assert vs["n_cards_passed"] == 2
    assert vs["n_cards_passed_with_warnings"] == 0
    assert vs["n_cards_excluded_by_applies_when"] == 0

    # And the count matches the emitted payload's deduped cards array (present + unavailable).
    monkeypatch.setattr(tp_evidence_package, "resolve_cards",
                        lambda card_ids, target, indication, **kw: [
                            {"card_id": "target-identity-summary", "_missing": True}])
    args = SimpleNamespace(target="KRAS", indication="COADREAD", release_pin=None, out=tmp_path)
    try:
        tp._write_evidence_package(
            args=args, sub_results=sub_results, gate_action="veto",
            recommendation_gate={"fired": True}, confidence_tier={"tier": "low"},
            deciding_axis={"basis": "gate_fired",
                           "deciding_axis": {"short": "dependency", "gate": "dependency"}, "routing": "x"},
            validation_summary=vs)
    except SystemExit:
        pass  # identity unresolved → hgnc_id=-1 schema tripwire; we only need the written payload
    ep = json.loads((tmp_path / "evidence_package.json").read_text())
    payload_cards = {c["card_id"] for c in ep["cards"] if c.get("card_id") != "target-identity-summary"}
    assert payload_cards == {"shared-multi-homed", "dep-only", "gone"}
    assert vs["n_cards_attempted"] == len(payload_cards)


def test_no_killer_recommendation_is_coherent_not_insufficient(tmp_path, monkeypatch):
    """When no killer gate fires (gate_action=None) for a positive target, the
    evidence-package headline must NOT read 'insufficient (strong confidence)' (incoherent + machine-
    misleading — it disagrees with the same run's nomination.json). It should carry the honest neutral
    'no_deterministic_kill' term instead."""
    ep = _emit(tmp_path, monkeypatch, gate_action=None, identity_ok=True)
    headline = ep["synthesis"]["headline"]
    assert "no_deterministic_kill" in headline, f"headline={headline!r}"
    assert "insufficient" not in headline, (
        f"headline still mislabels a no-killer positive as 'insufficient': {headline!r}")


# ── DECISION FACETS + modality×safety seam (2026-08-24, cross-evidence alignment) ─────────────────

def _build_ep_with_facets(tmp_path, monkeypatch, *, facets, modality, extra_subs=None):
    """Drive _write_evidence_package with the new verdict-inert decision facets + composed modality
    (+ optional extra sub_results, e.g. a `safety` short) so the cross-evidence integrator's input
    contract is exercised end-to-end through the real emitter."""
    monkeypatch.setattr(tp_evidence_package, "resolve_cards",
                        lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)])
    sub_results = {
        "dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency",
                           ("selective_dependency", "dep-01")),
    }
    sub_results.update(extra_subs or {})
    args = SimpleNamespace(target="KRAS", indication="COADREAD", release_pin=None, out=tmp_path)
    ep_path = tp._write_evidence_package(
        args=args, sub_results=sub_results, gate_action="nominate",
        recommendation_gate={"fired": True, "forced_recommendation": "nominate"},
        confidence_tier={"tier": "high"},
        deciding_axis={"basis": "gate_fired",
                       "deciding_axis": {"short": "dependency", "gate": "dependency"}, "routing": "x"},
        validation_summary={"n_cards_attempted": 1, "n_cards_passed": 1,
                            "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                            "n_cards_excluded_by_applies_when": 0},
        modality=modality, **facets)
    return json.loads(Path(ep_path).read_text())


def test_decision_facets_default_empty_and_byte_stable(tmp_path, monkeypatch):
    """The DEFAULT (no facets passed) run carries an all-empty decision_facets block and
    context.composed_modality=None — the byte-stable contract for a run that computed no facets."""
    ep = _build_ep(tmp_path, monkeypatch)
    df = ep["synthesis"]["decision_facets"]
    assert df == {"certainty_by_axis": {}, "cross_gate_shared_evidence": {},
                  "fragility": {}, "competitor_crossref": {}, "composed_modality": None}


def test_decision_facets_carried_into_synthesis(tmp_path, monkeypatch):
    """The four verdict-inert facets (previously nomination.json-only) reach synthesis.decision_facets,
    and the composed modality reaches context — the cross-evidence integrator's new read surface."""
    facets = {
        "certainty_by_axis": {"dependency": {"strength": "strong_positive",
                                             "certainty": {"level": "high", "coverage": "high",
                                                           "corroboration": "high", "unknown_mass": 0.0}}},
        "cross_gate_shared_evidence": {"shared_input_cards": {"copy-number-distribution":
                                                              ["safety", "genomic_alteration"]},
                                       "correlated_gate_pairs": [["safety", "genomic_alteration"]]},
        "fragility": {"contested": False, "acquisition_backlog": [
            {"axis": "immune_context", "gate": None, "coverage": "low", "action": "acquire",
             "missing_cards": [{"card_id": "immune-context", "availability_state": "not_wired"}]}]},
        "competitor_crossref": {"competition_density": "crowded", "modality_validated": True},
    }
    ep = _build_ep_with_facets(tmp_path, monkeypatch, facets=facets, modality="adc")
    df = ep["synthesis"]["decision_facets"]
    assert df["certainty_by_axis"]["dependency"]["certainty"]["level"] == "high"
    assert df["cross_gate_shared_evidence"]["correlated_gate_pairs"] == [["safety", "genomic_alteration"]]
    assert df["fragility"]["acquisition_backlog"][0]["axis"] == "immune_context"
    assert df["competitor_crossref"]["competition_density"] == "crowded"
    assert df["composed_modality"] == "adc"
    # still schema-valid with the new blocks present
    schema = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(ep)]
    assert errors == [], f"evidence_package with decision_facets failed schema validation: {errors}"


def test_safety_verdict_by_modality_stamped_on_safety_short(tmp_path, monkeypatch):
    """A `safety` short gets its per-modality safety verdict stamped onto its sub_verdicts entry so the
    integrator can refine its hold-grade cap per --modality. Recomputed from the safety fired rules via
    the shared modality_safety transform (single source of truth with tp_gates)."""
    safety_sub = _sub("gnomad-lof-constraint", "gnomad-lof-intolerant", "safety",
                      ("human_genetics_safety_concern", "gnomad-lof-intolerant"))
    ep = _build_ep_with_facets(tmp_path, monkeypatch, facets={}, modality=None,
                               extra_subs={"safety": safety_sub})
    svbm = ep["synthesis"]["sub_verdicts"]["safety"].get("safety_verdict_by_modality")
    assert isinstance(svbm, dict) and svbm, "expected a per-modality safety verdict on the safety short"
    # every channel carries an action + wt_engagement (the modality_safety contract shape)
    for channel, rec in svbm.items():
        assert "action" in rec and "wt_engagement" in rec, (channel, rec)
    # a non-safety short must NOT carry the block (it is safety-specific)
    assert "safety_verdict_by_modality" not in ep["synthesis"]["sub_verdicts"]["dependency"]


def test_failed_identity_fails_schema_validation_loudly(tmp_path, monkeypatch):
    """When target-identity fails to resolve, assemble emits hgnc_id=-1 (schema requires
    >= 1) ON PURPOSE as a validation tripwire. The emitter must now VALIDATE and fail LOUD (SystemExit)
    rather than silently persist a schema-invalid governance artifact + return success. Also assert the
    -1 sentinel really is what the schema rejects (guards the tripwire itself)."""
    import pytest
    with pytest.raises(SystemExit) as exc:
        _emit(tmp_path, monkeypatch, gate_action="veto", identity_ok=False)
    assert exc.value.code == 1
    # the invalid envelope is still written for inspection — confirm it carries the -1 sentinel and
    # that the schema validator flags exactly that (the tripwire is real, not incidental).
    ep = json.loads((tmp_path / "evidence_package.json").read_text())
    assert ep["context"]["target"]["hgnc_id"] == -1
    errs = tp._validate_evidence_package(ep, CONTRACTS)
    assert any("hgnc_id" in e for e in errs), f"expected an hgnc_id schema error, got: {errs}"
