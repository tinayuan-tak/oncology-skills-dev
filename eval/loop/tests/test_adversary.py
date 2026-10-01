#!/usr/bin/env python3
"""Teeth for eval/loop/critic/adversary.py — the LLM adversarial critic (SK#2303 follow-on to WI-D #2356).

The critic is a SECOND, non-reproducible LLM pass after the deterministic containment guard. Its LLM is
injectable, so these teeth fixture the tool-call and assert the behaviour with NO live Bedrock:

  - ANNOTATE-NOT-FILTER (STOP-A): a 'killed' verdict ANNOTATES the finding (``_adversary``) but does not,
    on its own, remove it — ``survivors()`` / ``routable(filter_killed=True)`` is where a kill takes effect;
  - FAIL-OPEN on the critic's own judgement: a finding with no / malformed verdict defaults to ``survives``
    (the critic may only REMOVE a finding on a confident kill, never silently drop one it failed to score);
  - a dead/NULL substrate OR an empty finding set is NEVER sent to the LLM (``skipped``) — a dead package
    can never read as 'all findings survived'.
"""

from __future__ import annotations

import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]
_CRITIC = _LOOP / "critic"
for _p in (str(_LOOP), str(_CRITIC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import adversary as A  # noqa: E402
import iterate as I  # noqa: E402


def _bundle() -> dict:
    return {
        "null_everything": False,
        "null_reason": None,
        "l2a": {"paralog_buffering": {"card_id": "paralog-buffering", "property": "partial", "anchors": {}}},
        "l2b": {},
        "l3": None,
        "l3_claims": {"axes": [], "cited_card_ids": []},
        "field_contracts": {},
        "card_read_errors": [],
    }


def _findings() -> list[dict]:
    return [
        {"kind": "surface_unused_signal", "target": "A", "finding": "f0", "why": "w0", "datum_refs": ["l2a.x"]},
        {"kind": "missing_relationship", "target": "B", "finding": "f1", "why": "w1", "datum_refs": ["l2a.y"]},
    ]


def _llm_returning(verdicts: list[dict]):
    def _call(system_prompt, user_prompt, tool_name, tool_schema, max_tokens=2500):
        return {"verdicts": {"value": verdicts, "_model_id": "stub", "_prompt_hash": "h"}}

    return _call


def test_skips_null_substrate_without_calling_llm():
    calls = []
    out = A.adversarially_verify(
        {"null_everything": True, "null_reason": "dead"}, _findings(), llm=lambda *a, **k: calls.append(1) or {}
    )
    assert out["skipped"].startswith("null_everything")
    assert calls == []  # the LLM is never reached on a dead substrate


def test_skips_empty_finding_set_without_calling_llm():
    calls = []
    out = A.adversarially_verify(_bundle(), [], llm=lambda *a, **k: calls.append(1) or {})
    assert out["skipped"] == "no contained findings to verify"
    assert calls == []


def test_annotates_kill_and_survive_but_does_not_filter():
    llm = _llm_returning(
        [
            {
                "finding_index": 0,
                "verdict": "killed",
                "failure_mode": "overstated",
                "reason": "r",
                "confidence": "high",
            },
            {"finding_index": 1, "verdict": "survives", "reason": "cannot rebut", "confidence": "medium"},
        ]
    )
    out = A.adversarially_verify(_bundle(), _findings(), llm=llm)
    assert out["skipped"] is None
    assert out["n_killed"] == 1 and out["n_survived"] == 1
    # ANNOTATE-NOT-FILTER: both findings are still present, each carrying its verdict.
    assert len(out["annotated"]) == 2
    assert out["annotated"][0]["_adversary"]["verdict"] == "killed"
    assert out["annotated"][0]["_adversary"]["failure_mode"] == "overstated"
    assert out["annotated"][1]["_adversary"]["verdict"] == "survives"
    # The FILTER (survivors) is where a kill takes effect.
    surv = A.survivors(out["annotated"])
    assert [f["target"] for f in surv] == ["B"]


def test_fail_open_when_a_verdict_is_missing():
    # Only finding 0 is scored; finding 1 has no verdict → defaults to survives (never silently killed).
    llm = _llm_returning(
        [
            {"finding_index": 0, "verdict": "killed", "failure_mode": "cosmetic", "reason": "r", "confidence": "high"},
        ]
    )
    out = A.adversarially_verify(_bundle(), _findings(), llm=llm)
    assert out["annotated"][1]["_adversary"]["verdict"] == "survives"
    assert out["n_killed"] == 1 and out["n_survived"] == 1


def test_parse_verdicts_defaults_all_survive_on_garbage():
    assert all(v["verdict"] == "survives" for v in A.parse_verdicts({"nonsense": 1}, 3))
    assert all(v["verdict"] == "survives" for v in A.parse_verdicts("not a dict", 2))


def test_out_of_range_index_is_ignored_leaving_survive_default():
    out = A.parse_verdicts({"verdicts": {"value": [{"finding_index": 9, "verdict": "killed", "reason": "r"}]}}, 2)
    assert [v["verdict"] for v in out] == ["survives", "survives"]


# ── PackageResult.routable: annotate-not-filter vs filter ──────────────────────────────────────────────
def _package_result(adversary: dict) -> "I.PackageResult":
    entry = I.Entry(target="T", indication="IND", subtype="", stratum="s", split="dev")
    contained = adversary.get("annotated") or []
    return I.PackageResult(
        entry=entry,
        assembled=True,
        null_reason=None,
        judge_skipped=None,
        n_findings=len(contained),
        containment={"contained": contained},
        probes=[],
        judge_result={},
        adversary=adversary,
    )


def test_routable_keeps_killed_by_default_and_drops_them_under_filter():
    llm = _llm_returning(
        [
            {
                "finding_index": 0,
                "verdict": "killed",
                "failure_mode": "overstated",
                "reason": "r",
                "confidence": "high",
            },
            {"finding_index": 1, "verdict": "survives", "reason": "ok", "confidence": "low"},
        ]
    )
    adversary = A.adversarially_verify(_bundle(), _findings(), llm=llm)
    pr = _package_result(adversary)
    assert len(pr.routable(filter_killed=False)) == 2  # annotate-not-filter: both route
    assert [f["target"] for f in pr.routable(filter_killed=True)] == ["B"]  # filter: killed removed
