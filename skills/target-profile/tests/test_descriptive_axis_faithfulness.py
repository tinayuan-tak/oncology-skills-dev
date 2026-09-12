"""A GATELESS DESCRIPTIVE sub-skill's own read must survive composition — as CONTEXT, never as a gate.

target-intrinsic is gateless by construction (`verdict_fn=None`, absent from `_SHORT_TO_GATE`), so it
emits `verdict=None` / `call=null` / `polarity=not_scored` / `role=descriptive`. It nonetheless computes a
real interpreted answer: a claim_vector (per-axis signal + corroboration + a cited evidence atom), a
verdict-INERT confirmation caveat adjudicating experimentally-MEASURED vs PREDICTED actionability, and the
unified skill_report spine. Composition dropped all of it — three artifacts each showed the axis only as an
absence, indistinguishable from an axis that FAILED or was never run, which is the opposite of the read
routing needs (a gateless axis' silence is not a negative):

  1. `narrative_by_axis` had NO entry at all (its membership comes from the fragility facet, whose axis set
     is the gate/positive/contradiction vocabularies — which a gateless skill is absent from by design).
  2. the synthesis prompt showed one line, "no rule-fired verdict", then raw card summaries, so the
     integrator re-derived from raw fields what the sub-skill had already interpreted — and never saw the
     over-call caveat.
  3. `--emit evidence-package` (the artifact cross-evidence-hypothesis actually consumes) carried NO
     skill_report spine at all, so `role` / `polarity` — the only fields that say "gateless BY DESIGN" —
     were absent from the machine package, reaching only nomination.json.

Every assertion here is VERDICT-INERT: none of these paths owns the recommendation, the gate, or the
confidence tier. The last test pins that explicitly — the descriptive axis contributes no gate block.
"""

from __future__ import annotations

import copy
import functools
import json
import os
from pathlib import Path
from types import SimpleNamespace

from _skills_common.compose_core import subskill_composition
from _skills_common.skill_report import build_skill_report
from _test_support import load_run_py

CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_descriptive")
import tp_evidence_package  # noqa: E402
import tp_facets  # noqa: E402
import tp_synthesis_prompt as tsp  # noqa: E402

_TI = Path(__file__).resolve().parents[2] / "target-intrinsic"  # sibling skill dir under skills/

_IDENTITY_CARD = {
    "card_id": "target-identity-summary",
    "summary": {"resolved_hgnc_symbol": "EGFR", "resolved_hgnc_id": 3236},
    "interpretation_call": "resolved",
    "provenance": {"method_calls": [], "input_manifest_ids": []},
}


@functools.lru_cache(maxsize=1)
def _intrinsic_facet_and_cards() -> tuple[dict, list]:
    """The REAL target-intrinsic facet, from the skill's own `_synthesis_facet` over its committed EGFR
    golden cards. Deliberately not a hand-written stand-in: the shapes this composed layer must carry
    (claim_vector atoms, the `{level, basis, coverage}` confidence object, the caveat) are the sub-skill's
    to define, and a hand-rolled approximation of them is exactly how a carry regresses unnoticed."""
    ti = load_run_py(_TI, "ti_run_for_tp_descriptive")
    golden = json.loads((_TI / "tests" / "fixtures" / "target_intrinsic_egfr_full_decision.json").read_text())
    cards = golden["cards"]
    fired = golden.get("fired_rules") or []
    facet = ti._synthesis_facet(cards, fired, None, target="EGFR", indication="LUAD")
    return facet, cards


def _sub(card_id, fired_id, gate, verdict_pair, synthesis_facet=None, cards=None):
    cards = cards or [
        {
            "card_id": card_id,
            "summary": {"x": 1},
            "interpretation_call": "informative",
            "provenance": {"method_calls": [], "input_manifest_ids": []},
        }
    ]
    fired = [{"rule_id": fired_id}] if fired_id else []
    out = {
        "skill_dir": f"dir-{gate or 'none'}",
        "cards": cards,
        "fired": fired,
        "verdict": verdict_pair,
        "composition": subskill_composition(card_outputs=cards, fired=fired, gate=gate, verdict_pair=verdict_pair),
    }
    if synthesis_facet is not None:
        out["synthesis_facet"] = synthesis_facet
    return out


def _sub_results() -> dict:
    facet, ti_cards = _intrinsic_facet_and_cards()
    return {
        "dependency": _sub(
            "pan-cancer-crispr-dependency-distribution", "dep-01", "dependency", ("selective_dependency", "dep-01")
        ),
        # gateless descriptive peer: no gate, no verdict, but a full facet + report
        "target_intrinsic": _sub(
            "domain-modality-relevance",
            None,
            None,
            None,
            synthesis_facet=copy.deepcopy(facet),
            cards=copy.deepcopy(ti_cards),
        ),
    }


# ---------------------------------------------------------------- 1. narrative_by_axis


def test_narrative_by_axis_emits_the_descriptive_axis():
    """The gateless axis gets an entry naming its gatelessness — with the verdict slots explicitly null and
    its OWN read (honest phrase, confidence, claim chips, question table) carried from the report spine."""
    nba = tp_facets._narrative_by_axis(_sub_results(), {"per_axis": {}})
    assert "target_intrinsic" in nba, "gateless descriptive axis still missing from narrative_by_axis"
    n = nba["target_intrinsic"]
    assert n["role"] == "descriptive"
    assert n["verdict"] is None and n["driving_rule_id"] is None and n["gate"] is None
    # no call → nothing to move or flip; those slots must be empty, not fabricated
    assert n["movers"] == [] and n["dissenters"] == [] and n["flip_conditions"] == []
    # ...but the interpreted read IS present
    assert n["honest_phrase"], "the axis' own honest phrase did not survive"
    assert n["confidence"]["level"] == "moderate"  # the {level, basis, coverage} object, carried whole
    assert n["claim_chips"], "claim chips dropped — the axis' own read did not survive"
    assert n["question_table"], "per-question table dropped"
    assert "domain-modality-relevance" in n["cards_used"]
    assert "gateless" in n["_basis"] and "verdict-INERT" in n["_basis"]


def test_narrative_by_axis_does_not_touch_the_fragility_facet():
    """The descriptive entry is sourced from the skill_report spine, NOT by widening the fragility facet —
    whose per_axis set feeds target_index / recommendation_fragility_index, i.e. published numbers."""
    frag = {"per_axis": {}}
    tp_facets._narrative_by_axis(_sub_results(), frag)
    assert frag == {"per_axis": {}}, "fragility facet mutated — a published index would move"


def test_narrative_by_axis_skips_gating_axes():
    """A verdict-BEARING axis must not be relabeled descriptive: only role == descriptive reports qualify,
    and an axis the fragility loop already narrated is never overwritten."""
    sr = _sub_results()
    sr["dependency"]["synthesis_facet"] = {
        "skill_report": build_skill_report(role="gating", verdict="selective_dependency")
    }
    nba = tp_facets._narrative_by_axis(sr, {"per_axis": {}})
    assert "dependency" not in nba


# ---------------------------------------------------------------- 2. synthesis prompt


def test_prompt_narrative_block_names_gatelessness_not_none():
    """The narrative block must not print "`None`" under a header promising "what SET the verdict" — that
    reads as a failed axis and invites the model to treat the absence as a negative."""
    nba = tp_facets._narrative_by_axis(_sub_results(), {"per_axis": {}})
    text = "\n".join(tsp._render_narrative_block(nba))
    assert "**target_intrinsic**: NO VERDICT" in text
    assert "gateless descriptive axis" in text
    assert "NOT a negative" in text
    assert "**target_intrinsic**: `None`" not in text


def test_prompt_carries_the_descriptive_claim_axes_and_caveat():
    """The claim axes + the experimentally-confirmed-vs-predicted caveat reach the prompt, with the
    instruction that they route and calibrate but never gate."""
    text = "\n".join(tsp._render_descriptive_claim_block(_sub_results()))
    assert "Descriptive peers' OWN reads" in text
    assert "[target_intrinsic] MODALITY_ROUTING" in text and "[target_intrinsic] TRACTABILITY_PRECEDENT" in text
    assert "signal `" in text and "corroboration " in text
    assert "(read: Tclin)" in text  # the atom's own read, not just the signal tier
    assert "[target-development-level]" in text  # citable card anchor for the axis
    assert "intrinsic_confirmation_caveat = `experimentally_confirmed_intrinsic_property`" in text
    assert "experimental co-crystal" in text  # the caveat's basis lines
    assert "do NOT convert one into a Go/No-Go" in text
    # the `_disclaimer` string member of the claim vector is not an axis
    assert "_disclaimer" not in text


def test_descriptive_claim_block_skips_verdict_bearing_and_is_empty_when_nothing_to_say():
    """Verdict-bearing shorts are excluded (their read arrives via the sub-verdict + narrative trace), and
    with nothing to render the block is [] so an un-migrated run's prompt stays byte-stable."""
    sr = _sub_results()
    text = "\n".join(tsp._render_descriptive_claim_block(sr))
    assert "[dependency]" not in text
    assert tsp._render_descriptive_claim_block({"dependency": sr["dependency"]}) == []
    assert tsp._render_descriptive_claim_block({}) == []


# ---------------------------------------------------------------- 3. evidence package


def _build_ep(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(
        tp_evidence_package, "resolve_cards", lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)]
    )
    args = SimpleNamespace(target="EGFR", indication="LUAD", release_pin=None, out=tmp_path)
    ep_path = tp._write_evidence_package(
        args=args,
        sub_results=_sub_results(),
        gate_action=None,
        recommendation_gate={"fired": True, "forced_recommendation": "nominate"},
        confidence_tier={"tier": "high"},
        deciding_axis={
            "basis": "gate_fired",
            "deciding_axis": {"short": "dependency", "gate": "dependency"},
            "routing": "decided by gate dependency",
        },
        validation_summary={
            "n_cards_attempted": 2,
            "n_cards_passed": 2,
            "n_cards_passed_with_warnings": 0,
            "n_cards_failed": 0,
            "n_cards_excluded_by_applies_when": 0,
        },
    )
    return json.loads(Path(ep_path).read_text())


def test_package_carries_the_skill_report_spine(tmp_path, monkeypatch):
    """The emitted data package carries the per-skill skill_report spine — so the integrator consuming
    THIS artifact can tell "no verdict because gateless BY DESIGN" from "no verdict because it failed"."""
    syn = _build_ep(tmp_path, monkeypatch)["synthesis"]
    reports = syn["skill_reports"]
    assert "target_intrinsic" in reports, "skill_report spine still absent from the emitted package"
    r = reports["target_intrinsic"]
    assert r["call"] is None  # gateless
    assert r["role"] == "descriptive"
    assert r["polarity"] == "not_scored"  # the field that says "not scored", vs a missing axis
    assert r["confidence"]["level"] == "moderate"
    assert r["claim_chips"], "the report's claim chips must survive into the package"
    assert r["question_table"], "the report's per-question table must survive into the package"
    # sub_verdicts alone is all-null for this short — which is exactly why the spine is needed
    assert syn["sub_verdicts"]["target_intrinsic"] == {
        "gate": None,
        "verdict": None,
        "driving_rule_id": None,
        "fired_rule_ids": [],
    }


def test_package_rollup_groups_by_role_and_flags_against_its_own_recommendation(tmp_path, monkeypatch):
    """The rollup projects the spine (role grouping + INV-6 coherence flag), cross-checked against the
    recommendation THIS package publishes — not nomination.json's narrated call."""
    syn = _build_ep(tmp_path, monkeypatch)["synthesis"]
    roll = syn["skill_report_rollup"]
    assert [e["short"] for e in roll["by_role"]["descriptive"]] == ["target_intrinsic"]
    assert "target_intrinsic" not in roll["gating_polarities"], "a descriptive axis must never count as a gating signal"
    assert roll["recommendation"] == "nominate"  # == synthesis.recommendation_gate.forced_recommendation
    assert roll["recommendation_exceeds_signals"] is False


def test_package_spine_is_verdict_inert(tmp_path, monkeypatch):
    """The descriptive axis contributes NO gate block and does not appear in the primary/additional split:
    carrying its report into the package is additive, never a route into the recommendation spine."""
    syn = _build_ep(tmp_path, monkeypatch)["synthesis"]
    gates = {syn["primary_gate_verdict"]["gate"]} | {b["gate"] for b in syn["additional_gate_verdicts"]}
    assert gates == {"dependency"}
    assert syn["recommendation_gate"]["forced_recommendation"] == "nominate"


def test_package_stays_byte_stable_without_reports(tmp_path, monkeypatch):
    """A run whose sub-skills emit no report keeps both keys EMPTY (not absent, not fabricated), so the
    envelope shape is stable across the fleet's migration."""
    monkeypatch.setattr(
        tp_evidence_package, "resolve_cards", lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)]
    )
    sr = {"dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency", ("x", "dep-01"))}
    args = SimpleNamespace(target="EGFR", indication="LUAD", release_pin=None, out=tmp_path)
    ep = json.loads(
        Path(
            tp._write_evidence_package(
                args=args,
                sub_results=sr,
                gate_action=None,
                recommendation_gate={},
                confidence_tier={},
                deciding_axis={},
                validation_summary={
                    "n_cards_attempted": 1,
                    "n_cards_passed": 1,
                    "n_cards_passed_with_warnings": 0,
                    "n_cards_failed": 0,
                    "n_cards_excluded_by_applies_when": 0,
                },
            )
        ).read_text()
    )
    assert ep["synthesis"]["skill_reports"] == {}
    assert ep["synthesis"]["skill_report_rollup"] == {}


def test_package_with_the_spine_is_still_schema_valid(tmp_path, monkeypatch):
    from jsonschema import Draft202012Validator

    schema_path = CONTRACTS / "schemas" / "evidence_package.schema.json"
    if not schema_path.exists():
        import pytest

        pytest.skip("target-contracts checkout unavailable")
    ep = _build_ep(tmp_path, monkeypatch)
    errors = [
        f"[{'.'.join(str(p) for p in e.absolute_path) or '<root>'}] {e.message}"
        for e in Draft202012Validator(json.loads(schema_path.read_text())).iter_errors(ep)
    ]
    assert errors == [], f"the skill_report spine broke envelope validation: {errors}"
