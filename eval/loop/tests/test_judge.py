#!/usr/bin/env python3
"""Teeth for eval/loop/critic/judge.py — the triangulation judge (SK#2303 WI-C, #2355).

The judge's VERDICT behaviour (does it discriminate? does it confabulate?) is an LLM sample and is NOT
reproducible, so it is NOT gated against live Bedrock. Instead the LLM call is INJECTED with RECORDED
responses (``fixtures/judge_response_*.json`` — the pilot's validated CD274 judgement transcribed into
the production single-array schema, plus a silent/empty response). These teeth gate the CONSUMER
machinery the pilot's correctness depends on:

  - ``["value"]`` unwrap (a provenance-stamped array arrives WRAPPED);
  - the single-array schema (multi-array ``synthesize_structured`` calls are flaky — the measured gotcha);
  - the parse-level CONTRAST (silent recording → 0 findings; discordant recording → structured findings);
  - PROPOSE-ONLY (no verdict/recommendation surface) + no-confabulation (every finding carries datum_refs);
  - the garbage-in guard (a NULL / dead substrate is SKIPPED, never sent to the LLM, never read as clean);
  - the two guardrails: the field CONTRACT + raw datum are fed in the prompt; both shipped lanes are read.

NOTE on the acceptance's "silent on CEACAM5": the PRE-contract pilot judge was silent on CEACAM5; the
CONTRACT-AWARE judge (``judgeC2_CEACAM5.json``) legitimately surfaces REAL structural gaps there (an
``abundance_concordant`` token over two null arms) — those are discoveries, not confabulation. The LLM
sample is not CI-gated; these teeth gate the machinery and the propose-only / no-confabulation / silent
contracts, which hold regardless of which target the sample came from.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]  # eval/loop
_CRITIC = _LOOP / "critic"
for _p in (str(_LOOP), str(_CRITIC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import judge as J  # noqa: E402
import substrate as S  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures"


def _emitted(name: str) -> dict:
    return json.loads((_FIX / f"{name}_coadread_emitted.json").read_text())


def _substrate(name: str) -> dict:
    bundle = _emitted(name)
    return S.assemble_from_objects(bundle["evidence_package"], bundle["decision"])


def _response(name: str) -> dict:
    return json.loads((_FIX / f"judge_response_{name}.json").read_text())


def _llm_returning(response: dict):
    """A stub LLM that records its call args and returns the recorded response (no live Bedrock)."""
    calls = []

    def _fake(system_prompt, user_prompt, tool_name, tool_schema, max_tokens=3000):
        calls.append({"system": system_prompt, "user": user_prompt, "tool_name": tool_name, "tool_schema": tool_schema})
        return response

    _fake.calls = calls  # type: ignore[attr-defined]
    return _fake


def _exploding_llm(*a, **k):
    raise AssertionError("the LLM must NOT be called for a NULL / dead substrate")


# ── the garbage-in guard: a dead substrate is SKIPPED, never judged ──────────────────────────────────
def test_null_everything_substrate_is_skipped_without_calling_llm():
    dead = S.assemble_from_objects(
        _emitted("ceacam5")["evidence_package"], {"run_health": {"status": "ok", "n_cards_resolved": 0}}
    )
    assert dead["null_everything"] is True
    out = J.judge(dead, None, llm=_exploding_llm)
    assert out["skipped"] and "null_everything" in out["skipped"]
    assert out["n_findings"] == 0 and out["findings"] == []
    assert out["report_only"] is True  # a skip is still report-only, never a clean pass


def test_missing_run_health_substrate_is_skipped():
    null_sub = S.assemble_from_objects(_emitted("ceacam5")["evidence_package"], None)
    out = J.judge(null_sub, None, llm=_exploding_llm)
    assert out["skipped"] is not None and out["findings"] == []


# ── unwrap + parse ───────────────────────────────────────────────────────────────────────────────────
def test_wrapped_findings_are_unwrapped():
    """A provenance-stamped array arrives WRAPPED ({"value":[...]}). parse_findings must unwrap it."""
    parsed = J.parse_findings(_response("cd274_luad"))
    assert isinstance(parsed, list) and len(parsed) == 5
    assert all(isinstance(f, dict) for f in parsed)


def test_unwrap_tooth_a_naive_consumer_would_see_a_dict_not_a_list():
    """TOOTH: the raw findings field is a dict, not a list — if the ['value'] unwrap is removed the
    consumer gets the wrapper dict and loses every finding. _unwrap is what prevents that."""
    raw = _response("cd274_luad")
    assert isinstance(raw["findings"], dict)  # premise: wrapped
    assert "value" in raw["findings"]
    assert J._unwrap(raw["findings"]) == raw["findings"]["value"]  # unwrap recovers the list
    assert J._unwrap([1, 2]) == [1, 2]  # a bare (already-unwrapped) list passes through


def test_bare_unwrapped_list_also_parses():
    parsed = J.parse_findings(
        {"findings": [{"kind": "divergence", "target": "x", "finding": "y", "why": "z", "datum_refs": ["a"]}]}
    )
    assert len(parsed) == 1


def test_string_finding_is_coerced_not_dropped():
    parsed = J.parse_findings({"findings": {"value": ["a loose string finding"]}})
    assert len(parsed) == 1 and parsed[0]["kind"] == "unstructured"
    assert parsed[0]["datum_refs"] == []


def test_malformed_result_parses_to_empty():
    assert J.parse_findings(None) == []
    assert J.parse_findings({"findings": "not a list and not wrapped"}) == []
    assert J.parse_findings({}) == []


# ── the parse-level CONTRAST (silent vs discordant), LLM injected ────────────────────────────────────
def test_silent_recording_yields_zero_findings():
    sub = _substrate("ceacam5")
    out = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("silent")))
    assert out["n_findings"] == 0 and out["findings"] == []
    assert out["skipped"] is None  # it RAN (not skipped) and found nothing — the clean/silent path


def test_discordant_recording_yields_structured_findings():
    sub = _substrate("ceacam5")
    out = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("cd274_luad")))
    assert out["n_findings"] == 5
    kinds = {f["kind"] for f in out["findings"]}
    assert kinds <= set(J.FINDING_KINDS)  # every kind is in the governed vocabulary
    assert {"divergence", "new_family"} <= kinds


def test_contrast_silent_vs_discordant_on_same_substrate():
    """The pilot's discrimination, reproduced deterministically at the consumer level: the SAME substrate
    yields 0 findings for a silent recording and >0 for a discordant one — the judge faithfully surfaces
    whatever the (injected) LLM returns, without inventing or suppressing."""
    sub = _substrate("ceacam5")
    silent = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("silent")))
    discordant = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("cd274_luad")))
    assert silent["n_findings"] == 0
    assert discordant["n_findings"] > silent["n_findings"]


# ── propose-only + no-confabulation ──────────────────────────────────────────────────────────────────
def test_report_is_propose_only_no_verdict_surface():
    """STOP-A: the report carries NO verdict / recommendation / go_forth key, and report_only is True."""
    sub = _substrate("ceacam5")
    out = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("cd274_luad")))
    assert out["report_only"] is True
    forbidden = {"verdict", "recommendation", "go_forth", "proposed_verdict", "overall_recommendation", "decision"}
    assert not (set(out) & forbidden)
    for f in out["findings"]:
        assert not (set(f) & forbidden)


def test_every_finding_carries_datum_refs_no_confabulation():
    """No confabulation: every emitted finding must trace to a real datum field via datum_refs, so the
    WI-D containment guard can re-verify it. A finding with empty datum_refs is a judge defect."""
    sub = _substrate("ceacam5")
    out = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("cd274_luad")))
    for f in out["findings"]:
        assert f.get("datum_refs"), f
        assert all(isinstance(r, str) and r for r in f["datum_refs"])


# ── the single-array schema (the measured flakiness gotcha) ──────────────────────────────────────────
def test_tool_schema_has_exactly_one_array_property():
    """TOOTH: synthesize_structured is flaky on a multi-array schema (a trailing array returns as a markup
    blob → coerced to []). The judge tool must expose EXACTLY ONE array (findings) — divergences are
    entries IN it, never a second array. Reintroducing a 2nd array reds this test."""
    props = J.TOOL["properties"]
    array_props = [k for k, v in props.items() if v.get("type") == "array"]
    assert array_props == ["findings"]


# ── the two pilot guardrails: contract + datum fed; both lanes read ──────────────────────────────────
def test_prompt_feeds_field_contracts_and_raw_datum():
    """Guardrail 1: without the field CONTRACT the judge flags correct-by-contract fields (CD274
    corroboration:high). The prompt must carry field_contracts (incl. the corroboration semantics) AND
    the raw per-arm datum (the labels are abstractions audited against the numbers)."""
    sub = _substrate("ceacam5")
    llm = _llm_returning(_response("silent"))
    J.judge(sub, {"run_health": {}}, llm=llm)
    user = llm.calls[0]["user"]  # type: ignore[attr-defined]
    assert "field_contracts" in user
    assert "corroboration" in user and "INDEPENDENCE-AGREEMENT" in user
    assert "fraction_detected" in user or "high_fraction" in user  # raw datum present
    assert llm.calls[0]["system"].find("PROPOSE ONLY") != -1  # type: ignore[attr-defined]


def test_both_shipped_lanes_are_read_from_decision():
    """Guardrail / 3-view fold: literature_synthesis + llm_synthesis are read off the decision, including
    the headline nesting and a provenance wrapper."""
    sub = _substrate("ceacam5")
    decision = {
        "run_health": {"n_cards_resolved": 16},
        "literature_synthesis": {"value": {"overall_consistency": "mixed", "key_divergence": "RNA-flat vs protein-up"}},
        "headline": {"llm_synthesis": {"headline": "a narrative"}},
    }
    views = J.build_views(sub, decision)
    assert views["literature_lane"] == {"overall_consistency": "mixed", "key_divergence": "RNA-flat vs protein-up"}
    assert views["narrative"] == {"headline": "a narrative"}
    out = J.judge(sub, decision, llm=_llm_returning(_response("silent")))
    assert out["lanes_present"] == {"literature": True, "narrative": True}


def test_lanes_absent_still_runs_single_view_marked():
    sub = _substrate("ceacam5")
    out = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("silent")))
    assert out["lanes_present"] == {"literature": False, "narrative": False}
    assert out["skipped"] is None  # a missing lane degrades the fold, it does not abort the judge


def test_provenance_is_surfaced():
    sub = _substrate("ceacam5")
    out = J.judge(sub, {"run_health": {}}, llm=_llm_returning(_response("cd274_luad")))
    assert out["provenance"]["model_id"] == "us.anthropic.claude-opus-4-8"
    assert out["provenance"]["prompt_hash"]


def test_build_views_does_not_mutate_substrate():
    """Purity: build_views reads the substrate, never mutates it (the raw islands are shared refs)."""
    sub = _substrate("ceacam5")
    before = copy.deepcopy(sub)
    J.build_views(sub, {"run_health": {}})
    assert sub == before
