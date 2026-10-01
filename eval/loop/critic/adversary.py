#!/usr/bin/env python3
"""eval/loop/critic/adversary.py — the subskill-iteration loop's LLM ADVERSARIAL CRITIC (SK#2303 follow-on
to WI-D #2356).

A SECOND LLM pass that sits AFTER the deterministic containment guard (``critic/containment.py``) and
BEFORE the ledger/tiers. Containment is deterministic and fail-closed, but it only catches the failure
modes it has an explicit predicate for (confabulation, the ``corroboration`` strength-misread, the
``_class_semantics`` tail/max misread, the ``provenance.sources`` arm artifact, the L3-claim consumption
misread). The CONTAINED survivors can still carry judgment-level defects a deterministic rule cannot
settle — an OVERSTATED kernel, an unsupported CAUSAL leap, a 'missing relationship' that is really design
taste. This critic adversarially tries to KILL each surviving finding on those grounds.

An adversarial-review pass over iter-001's findings (2026-10-01) found that ZERO of 9 judge findings were
actionable: the deterministic predicates now DROP/DEMOTE 7 (contract-misread + cosmetic re-keying); the
remaining 2 (a paralog causal overreach, a lineage 'missing relationship') are exactly the judgment cases
this critic targets.

CONSERVATIVE / ANNOTATE-NOT-FILTER (STOP-A, mirroring ``teeth_green``). This is a NEW, non-reproducible LLM
stage, so by default it only ANNOTATES each finding with its adversarial verdict (``_adversary``) — it does
NOT remove a 'killed' finding from the ledger / tiers / convergence. A reviewer who has seen its teeth hold
can enable filtering downstream (``iterate.py --adversary-filter``). Annotating-not-filtering means the
critic can never, on its own, make a batch read as 'clean' by silently dropping a real finding — the same
reason the judge's findings do not auto-land until ``teeth_green``.

PROPOSE-ONLY: writes nothing, moves no threshold, asserts no verdict. INJECTABLE LLM (``llm=``) so the
behaviour is covered by a fixtured contrast test with no live Bedrock. A dead / NULL substrate, or an empty
finding set, is NEVER sent to the LLM — the critic returns ``skipped`` (nothing to adjudicate), so a dead
package can never read as 'all findings survived'.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

# Sibling bare-import convention (no package __init__ under critic/ — see judge.py / containment.py).
_CRITIC_DIR = Path(__file__).resolve().parent
_LOOP_DIR = _CRITIC_DIR.parent
for _p in (str(_LOOP_DIR), str(_CRITIC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import judge as _judge  # noqa: E402  (reuse build_views / _unwrap — the same deterministic view the judge saw)

SCHEMA_VERSION = "1.0"

# The adversarial failure modes — why a CONTAINED finding may still not be actionable. These mirror the
# verdicts the human adversarial review used; the deterministic containment guard already removes the
# contract-misread / cosmetic cases, so the critic focuses on the judgment ones.
FAILURE_MODES = (
    "contract_misread",  # attacks a field for not meaning what its contract never claimed
    "overstated",  # a real kernel, but the claim exceeds what the datum supports
    "cosmetic",  # true but no evidential consequence (a pure re-shaping)
    "mislabeled_unused",  # calls a signal unused/isolated when a property layer already carries it
    "causal_overreach",  # asserts an unsupported mechanistic 'explains why' link
    "false_premise",  # the load-bearing claim is factually wrong against the datum
)

TOOL_NAME = "adversarially_verify_findings"

TOOL: dict = {
    "type": "object",
    "description": (
        "Adversarial verdicts on propose-only structural findings for a deterministic cancer-target "
        "evidence pipeline. A SINGLE array to avoid multi-array tool-call flakiness."
    ),
    "properties": {
        "verdicts": {
            "type": "array",
            "description": (
                "EXACTLY one verdict per finding you were given, in the SAME ORDER (echo finding_index). "
                "A finding SURVIVES only if you genuinely cannot break it; otherwise KILL it and name the "
                "failure mode. Do not be charitable — but do not kill a finding you cannot ground a "
                "rebuttal for (an un-rebuttable finding SURVIVES)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "finding_index": {"type": "integer", "description": "0-based index of the finding being judged."},
                    "verdict": {"type": "string", "enum": ["survives", "killed"]},
                    "failure_mode": {
                        "type": "string",
                        "enum": list(FAILURE_MODES),
                        "description": "(when killed) which adversarial test the finding failed.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "the decisive rebuttal (killed) or why it survives — cite the datum/contract/property layer.",
                    },
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["finding_index", "verdict", "reason", "confidence"],
            },
        }
    },
    "required": ["verdicts"],
}

SYS = (
    "You are an ADVERSARIAL reviewer of propose-only structural findings about a deterministic "
    "cancer-target evidence pipeline. Each finding proposes a refinement to the pipeline's L1-L3 property "
    "layers; a prior deterministic guard has ALREADY removed confabulations, contract-misreads of "
    "`corroboration`, tail/max class-label misreads, and cosmetic 'empty arms' re-keyings. Your job is to "
    "try to KILL each SURVIVING finding on the JUDGMENT grounds a deterministic rule cannot settle: "
    "(1) contract_misread — it attacks a field for not meaning what its contract never claimed; "
    "(2) overstated — a real kernel, but the claim exceeds what the datum supports; "
    "(3) cosmetic — true but with no evidential consequence (a pure re-shaping); "
    "(4) mislabeled_unused — it calls a signal 'unused/isolated' when a PROPERTY LAYER (L2a property, L2b "
    "family, or an L3 claim in `l3`/local_composites) already carries it — judge this on the PROPERTY "
    "LAYERS, NEVER on whether a verdict rule fired; "
    "(5) causal_overreach — it asserts an unsupported mechanistic 'explains why' link the datum does not "
    "license; (6) false_premise — the load-bearing claim is factually wrong against the datum. "
    "You are given (A) the SAME deterministic L1-L3 view the finding was proposed against (RAW islands, "
    "per-source anchors WITH numbers, `field_contracts` defining what each token/`corroboration` means) "
    "and the list of findings to judge. Return EXACTLY one verdict per finding, echoing finding_index in "
    "order. A finding you cannot ground a rebuttal for SURVIVES — do not kill on vibes. PROPOSE-ONLY: you "
    "assert no verdict and move no threshold; you only adjudicate whether each proposal is actionable."
)


def _render_findings(findings: list[dict]) -> str:
    import json  # local — keep module import-light

    rows = []
    for i, f in enumerate(findings):
        rows.append(
            {
                "finding_index": i,
                "kind": f.get("kind"),
                "target": f.get("target"),
                "finding": f.get("finding"),
                "why": f.get("why"),
                "datum_refs": f.get("datum_refs"),
            }
        )
    return json.dumps(rows, indent=1, default=str)


def render_user_prompt(views: dict, findings: list[dict]) -> str:
    import json

    det = views.get("deterministic") or {}
    return (
        "(A) DETERMINISTIC L1-L3 the findings were proposed against (`token`/`class` are ABSTRACTIONS to "
        "AUDIT against the numbers; `field_contracts` DEFINES each token/`corroboration`; `l3` /"
        "local_composites carry the L3 claim axes):\n"
        + json.dumps(det, indent=1, default=str)
        + "\n\n(FINDINGS TO ADVERSARIALLY VERIFY — one verdict each, in order):\n"
        + _render_findings(findings)
    )


def parse_verdicts(raw: Any, n_findings: int) -> list[dict]:
    """Parse the LLM tool call into a per-finding verdict list of length ``n_findings``, index-aligned.

    Any finding without a well-formed verdict defaults to ``survives`` (fail-OPEN on the critic's own
    judgement — the critic may only REMOVE a finding on a confident kill, never silently drop one it failed
    to score; a missing/garbled verdict must not read as 'killed')."""
    out = [
        {"verdict": "survives", "failure_mode": None, "reason": "no adversarial verdict returned", "confidence": "low"}
        for _ in range(n_findings)
    ]
    if not isinstance(raw, dict):
        return out
    items = _judge._unwrap(raw.get("verdicts"))
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("finding_index")
        if not isinstance(idx, int) or not (0 <= idx < n_findings):
            continue
        verdict = item.get("verdict")
        verdict = verdict if verdict in ("survives", "killed") else "survives"
        out[idx] = {
            "verdict": verdict,
            "failure_mode": item.get("failure_mode") if verdict == "killed" else None,
            "reason": item.get("reason"),
            "confidence": item.get("confidence") if item.get("confidence") in ("high", "medium", "low") else "low",
        }
    return out


def _default_llm(system_prompt: str, user_prompt: str, tool_name: str, tool_schema: dict, max_tokens: int) -> dict:
    skills_root = _LOOP_DIR.parents[1] / "skills"
    if str(skills_root) not in sys.path:
        sys.path.insert(0, str(skills_root))
    from _skills_common.llm import synthesize_structured  # noqa: PLC0415

    os.environ.setdefault("BEDROCK_AWS_PROFILE", "cmp-dev")
    return synthesize_structured(system_prompt, user_prompt, tool_name, tool_schema, max_tokens=max_tokens)


def adversarially_verify(
    substrate_bundle: dict,
    findings: list[dict],
    decision: "Optional[dict]" = None,
    *,
    llm: "Optional[Callable[..., dict]]" = None,
    max_tokens: int = 2500,
) -> dict:
    """Adversarially verify a list of CONTAINED findings against the same deterministic substrate view.

    Returns a PROPOSE-ONLY, ANNOTATE-NOT-FILTER report: ``annotated`` is the input findings, each with an
    ``_adversary`` block (``verdict`` / ``failure_mode`` / ``reason`` / ``confidence``). ``n_killed`` /
    ``n_survived`` are counts; the caller decides whether to FILTER (``iterate.py --adversary-filter``) —
    by default nothing is removed (STOP-A). A dead/NULL substrate or an EMPTY finding set is skipped (never
    sent to the LLM), so a dead package never reads as 'all findings survived'."""
    base = {
        "schema_version": SCHEMA_VERSION,
        "report_only": True,
        "n_in": len(findings) if isinstance(findings, list) else 0,
        "n_killed": 0,
        "n_survived": 0,
        "annotated": [],
        "skipped": None,
        "provenance": {},
    }

    if not isinstance(substrate_bundle, dict) or substrate_bundle.get("null_everything"):
        reason = (
            substrate_bundle.get("null_reason", "null substrate")
            if isinstance(substrate_bundle, dict)
            else "substrate is not a dict"
        )
        base["skipped"] = f"null_everything: {reason}"
        return base
    if not isinstance(findings, list) or not findings:
        base["skipped"] = "no contained findings to verify"
        return base

    views = _judge.build_views(substrate_bundle, decision)
    user_prompt = render_user_prompt(views, findings)
    call = llm or (lambda s, u, tn, ts, max_tokens=max_tokens: _default_llm(s, u, tn, ts, max_tokens))
    raw = call(SYS, user_prompt, TOOL_NAME, TOOL, max_tokens=max_tokens)

    verdicts = parse_verdicts(raw if isinstance(raw, dict) else {}, len(findings))
    annotated: list[dict] = []
    for f, v in zip(findings, verdicts):
        g = dict(f)
        g["_adversary"] = v
        annotated.append(g)
    base["annotated"] = annotated
    base["n_killed"] = sum(1 for v in verdicts if v["verdict"] == "killed")
    base["n_survived"] = len(verdicts) - base["n_killed"]
    base["provenance"] = _judge._provenance(raw if isinstance(raw, dict) else {})
    return base


def survivors(annotated: list[dict]) -> list[dict]:
    """The findings an enabled filter would route: those NOT killed by the critic. Strips ``_adversary``'s
    presence off the routing copy is NOT done here — the tag is kept so the ledger records the adjudication."""
    return [f for f in (annotated or []) if (f.get("_adversary") or {}).get("verdict") != "killed"]
