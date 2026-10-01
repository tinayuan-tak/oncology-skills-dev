#!/usr/bin/env python3
"""eval/loop/critic/judge.py — the subskill-iteration loop's TRIANGULATION JUDGE (SK#2303 WI-C, #2355).

This is **Output 2 — the QC / dev auditor**: it NEVER ships, it runs in iteration and as a regression
guard. It is the DISCOVERY CORE of the loop — the deterministic probes (WI-G) yield ~0 findings on a
mature skill; this LLM judge is what surfaces real L1→L3 structural refinements. It is distinct from
Output 1 (the redesigned shipping ``--synthesize``, arc-owned #2308).

**PROPOSE-ONLY (STOP-A).** The judge NEVER edits code, moves a threshold, mutates a verdict, writes a
file, or asserts a recommendation. Its ENTIRE output is a list of structural *proposals* for a human (or
a Tier-2/3 issue) to adjudicate. ``report_only`` is stamped ``True`` on every result and stays true until
the WI-G planted-defect teeth + the WI-D containment guard are green — do not route any finding to Tier-1
before then. Index on the property layers (L2a / L2b / L3), NEVER on the verdict (SK#2091).

The 3-view fold (plan §5A, pilot-validated):
  (A) the DETERMINISTIC L1–L3 substrate from the WI-B assembler (``eval/loop/substrate.py``): RAW L2b
      islands + each arm's L1 ``datum`` + the ``field_contracts`` block (enum dispositions + the
      load-bearing ``corroboration`` semantics). The ``token`` / ``class`` labels are the pipeline's own
      ABSTRACTIONS — the judge audits them AGAINST the raw datum, judged against their CONTRACT.
  (B) the shipped ``--literature`` lane (``decision['literature_synthesis']``): ``agreement_vs_omics`` /
      ``blind_spots`` / ``key_divergence`` / ``overall_consistency``. This lane ALREADY pre-computes the
      literature-vs-omics divergence — it is read deterministically and fed in; the LLM is called only to
      PROPOSE the L1–L3 restructure, not to re-derive the divergence.
  (C) the shipped ``--synthesize`` narrative (``decision['llm_synthesis']``).

Two guardrails the pilot validated, both load-bearing here:
  1. **Feed the field CONTRACT, not the abstraction.** Without each field's contract the judge
     confidently flags a correct-by-contract field (CD274 ``corroboration:high``) as a defect. The
     ``field_contracts`` block from WI-B carries it; the SYS prompt instructs judging-against-contract.
  2. **Single-array tool calls only.** ``synthesize_structured`` is flaky on a multi-array schema (a
     trailing array returns as a markup blob → coerced to ``[]``). So the tool exposes exactly ONE array,
     ``findings`` — a *divergence* and a *refinement proposal* are both just typed entries in it. Every
     provenance-stamped array arrives WRAPPED (``{"value": [...], "_source": ...}``) ⇒ the consumer MUST
     unwrap ``["value"]`` (see :func:`_unwrap`).

No confabulation: every finding must carry ``datum_refs`` — field paths into the substrate (e.g.
``l2b.abundance_concordance.corroboration``, ``l2a.protein_presence.anchors.cptac_effect``) that the WI-D
containment guard can re-verify against the raw island. A finding that traces to no datum is a defect of
the judge, not of the pipeline.

The LLM call is INJECTABLE (``judge(..., llm=...)``) so the behaviour is covered by a recorded / fixtured
contrast test with NO live Bedrock in CI. Live run recipe (SSO for cmp-dev expires mid-session —
re-``aws sso login`` if it 400s)::

    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev \
        PYTHONPATH=$REPO/skills pixi run python eval/loop/critic/judge.py <emitted_run_dir>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

# The substrate assembler (WI-B) lives one directory up (eval/loop/substrate.py). The eval/ convention is
# a bare sys.path import, no package __init__ under critic/ (sibling #2357 adds _predicates.py / probes.py
# here under the same convention — do NOT add an __init__.py).
_LOOP_DIR = Path(__file__).resolve().parents[1]
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))

import substrate as _substrate  # noqa: E402

SCHEMA_VERSION = "1.0"

# The structural-refinement vocabulary. A DIVERGENCE (which view is likelier right GIVEN the raw datum)
# and a REFINEMENT PROPOSAL are both entries in the single `findings` array, tagged by `kind`.
FINDING_KINDS = (
    "divergence",  # the three views disagree; name which is likelier right given the raw datum
    "new_family",  # a cross-source concordance family the islands do not capture
    "regroup_arms",  # arms grouped (or split) wrongly within a family
    "surface_unused_signal",  # a datum computed but never surfaced in the L3 story
    "missing_relationship",  # a relationship (B) or the datum implies but the islands do not represent
    "class_not_supported_by_datum",  # a class / token label the arm's raw numbers do not support
)

TOOL: dict = {
    "type": "object",
    "description": (
        "Propose-only structural refinements for a deterministic cancer-target evidence pipeline's "
        "L1-L3 property layers. A SINGLE array to avoid multi-array tool-call flakiness."
    ),
    "properties": {
        "findings": {
            "type": "array",
            "description": (
                "EMPTY LIST when the three views ALIGN and the raw datum supports every abstraction — a "
                "clean, concordant case MUST return no findings (do not manufacture a proposal). "
                "Otherwise each entry is ONE propose-only structural refinement OR divergence, grounded "
                "in a REAL datum field (datum_refs) a containment guard can re-verify. NEVER invent a "
                "datum; NEVER assert or move a verdict/threshold — propose structure for a human to "
                "adjudicate."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(FINDING_KINDS)},
                    "target": {
                        "type": "string",
                        "description": "what to restructure, e.g. 'L2b.abundance_concordance' or 'L3 headline'.",
                    },
                    "finding": {
                        "type": "string",
                        "description": "the proposed change, or (kind=divergence) what diverges and which view is likelier right.",
                    },
                    "why": {
                        "type": "string",
                        "description": "grounded reasoning citing the raw datum / contract.",
                    },
                    "datum_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "field paths into the substrate the finding rests on, e.g. "
                            "'l2b.<family>.corroboration', 'l2a.<family>.anchors.<field>', "
                            "'l2b.<family>.arms[<source>].datum.<field>'. The containment guard re-verifies these."
                        ),
                    },
                    "views_divergent": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["deterministic", "literature", "narrative"]},
                        "description": "(optional) which of the three views disagree.",
                    },
                },
                "required": ["kind", "target", "finding", "why", "datum_refs"],
            },
        }
    },
    "required": ["findings"],
}

SYS = (
    "You audit a deterministic cancer-target evidence pipeline. You are given THREE views of ONE target "
    "in ONE indication: (A) the deterministic L1-L3 structure — per-source properties (L2a) WITH their "
    "raw anchor numbers, cross-source concordance islands (L2b) where every arm carries its RAW "
    "QUANTITATIVE DATUM (fraction_detected, n_high/medium/low/not_detected, staining_score, high_fraction, "
    "n_tumor_samples, median_tpm, effect, q, ...), and the L3 story; (B) an INDEPENDENT published-"
    "literature read with per-axis agreement-vs-omics, blind_spots and key_divergence (this lane ALREADY "
    "pre-computes the literature-vs-omics divergence — use it, do not re-derive it); (C) a narrative "
    "synthesis. "
    "CRUCIAL: the `token` / `class` labels in (A) are the pipeline's own ABSTRACTIONS — do NOT take them "
    "at face value; reason from the RAW DATUM and judge whether each abstraction is warranted by its "
    "numbers (e.g. an IHC 'detected_moderate' resting on n_high=0 and mostly not_detected is an "
    "overstatement). "
    "★ CRITICAL: `field_contracts` in view (A) DEFINES what each token and `corroboration` MEAN. Judge "
    "every abstraction AGAINST ITS CONTRACT — do NOT flag a field as 'overstated' for failing to mean "
    "something it never claimed (e.g. `corroboration:high` = INDEPENDENCE-AGREEMENT of a family's arms, "
    "NOT strength/abundance). Only flag a class label the datum contradicts ON THE LABEL'S OWN TERMS. "
    "★ Where an l2a entry carries a `reliability` object (n_effective/powered/confound_flags/"
    "artifact_flags/detection_strength — #2306), it is the pipeline's OWN typed quality/power read of "
    "that entry's anchors, defined by the `_reliability` field_contract: use it as GROUNDING, not as a "
    "defect — a weak detection_strength or a confound_flag already EXPLAINS a borderline class, so do "
    "NOT re-flag that class as 'overstated' on grounds the facet already accounts for; a confound/"
    "artifact flag the L3 story does NOT surface is itself a legitimate surface_unused_signal finding. "
    "Its absence (common on signal-poor domains today) is the honest skeleton, not a gap to report. "
    "Your job: propose how the L1-L3 RELATIONSHIPS or SIGNALS could be refined or restructured — a missing "
    "concordance family, arms that should be grouped, a datum computed but not surfaced in the story, a "
    "class label the datum does not support, or a relationship the literature implies but the islands do "
    "not capture. Where the three views diverge, name which is likelier right GIVEN THE RAW DATUM. "
    "PROPOSE ONLY: NEVER assert, move, or imply a verdict/threshold; propose structural changes for a "
    "human to adjudicate. Every finding MUST cite the real datum field(s) it rests on in `datum_refs` so "
    "the proposal can be re-verified — never invent a datum. If the three views ALIGN and the datum "
    "supports every abstraction, return an EMPTY findings list."
)

TOOL_NAME = "triangulate_and_refine"


# ── provenance / unwrap helpers ──────────────────────────────────────────────────────────────────────
def _unwrap(value: Any) -> Any:
    """Unwrap a provenance-stamped array/string field. ``synthesize_structured`` wraps every top-level
    list/str field as ``{"value": <original>, "_source": ..., "_model_id": ..., "_prompt_hash": ...}``
    (``_stamp_llm_provenance``). A finding array therefore arrives WRAPPED and must be unwrapped. A bare
    (already-unwrapped, e.g. test-stub) list passes through unchanged."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _provenance(raw: dict) -> dict:
    """Pull model/prompt provenance off the wrapped ``findings`` field (framework stamps it there)."""
    fv = raw.get("findings") if isinstance(raw, dict) else None
    if isinstance(fv, dict):
        return {
            "model_id": fv.get("_model_id"),
            "prompt_hash": fv.get("_prompt_hash"),
            "truncated": raw.get("_truncated", False),
        }
    return {
        "model_id": None,
        "prompt_hash": None,
        "truncated": raw.get("_truncated", False) if isinstance(raw, dict) else False,
    }


def parse_findings(raw: Any) -> list[dict]:
    """Parse the LLM tool-call result into a clean list of finding dicts.

    Unwraps the provenance wrapper (``["value"]``); coerces each entry to a dict (a stray string entry is
    wrapped as an ``unstructured`` finding rather than dropped, so nothing is silently lost); ensures
    ``datum_refs`` is always a list. Returns ``[]`` for a malformed / empty result."""
    if not isinstance(raw, dict):
        return []
    items = _unwrap(raw.get("findings"))
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            f = dict(item)
            refs = f.get("datum_refs")
            f["datum_refs"] = refs if isinstance(refs, list) else ([] if refs is None else [refs])
            out.append(f)
        elif isinstance(item, str) and item.strip():
            out.append({"kind": "unstructured", "target": None, "finding": item, "why": None, "datum_refs": []})
    return out


# ── the three views ──────────────────────────────────────────────────────────────────────────────────
def _lane(decision: "Optional[dict]", key: str) -> Any:
    """Read a shipped synthesis lane off the decision, tolerating the ``headline`` nesting the engine
    sometimes uses, and unwrapping a provenance wrapper if the lane itself is stamped."""
    if not isinstance(decision, dict):
        return None
    lane = decision.get(key)
    if lane is None:
        headline = decision.get("headline")
        if isinstance(headline, dict):
            lane = headline.get(key)
    return _unwrap(lane)


def build_views(substrate_bundle: dict, decision: "Optional[dict]" = None) -> dict:
    """Fold the three views into the structure the judge is prompted on.

    (A) comes straight from the WI-B substrate bundle (RAW islands + datum + ``field_contracts`` — NO
    re-normalisation here; re-normalising is exactly what produced every false finding in the pilot).
    (B) and (C) are the two shipped lanes read off the decision."""
    deterministic = {
        "l2a": substrate_bundle.get("l2a") or {},
        "l2b": substrate_bundle.get("l2b") or {},
        "l3": substrate_bundle.get("l3"),
        "field_contracts": substrate_bundle.get("field_contracts") or {},
        "card_read_errors": substrate_bundle.get("card_read_errors") or [],
    }
    return {
        "deterministic": deterministic,
        "literature_lane": _lane(decision, "literature_synthesis"),
        "narrative": _lane(decision, "llm_synthesis"),
    }


def render_user_prompt(views: dict) -> str:
    """Render the three views into the LLM user message. Lanes are length-capped (they can be large and
    are secondary to the deterministic datum, which is fed in full)."""
    det = views.get("deterministic") or {}
    lit = views.get("literature_lane")
    nar = views.get("narrative")
    return (
        "(A) DETERMINISTIC L1-L3 (arms carry raw `datum`; `token`/`class` are ABSTRACTIONS to AUDIT "
        "against the numbers; `field_contracts` DEFINES what each token/`corroboration` means):\n"
        + json.dumps(det, indent=1, default=str)
        + "\n\n(B) LITERATURE LANE (pre-computed agreement_vs_omics / blind_spots / key_divergence):\n"
        + json.dumps(lit, indent=1, default=str)[:4500]
        + "\n\n(C) NARRATIVE SYNTHESIS:\n"
        + json.dumps(nar, indent=1, default=str)[:3500]
    )


# ── the judge ────────────────────────────────────────────────────────────────────────────────────────
def _default_llm(system_prompt: str, user_prompt: str, tool_name: str, tool_schema: dict, max_tokens: int) -> dict:
    """Lazy import of the framework Bedrock path, so importing this module (and the whole test suite)
    never requires the skills LLM stack or AWS creds. Only a LIVE judge run reaches here."""
    skills_root = _LOOP_DIR.parents[1] / "skills"
    if str(skills_root) not in sys.path:
        sys.path.insert(0, str(skills_root))
    from _skills_common.llm import synthesize_structured  # noqa: PLC0415

    os.environ.setdefault("BEDROCK_AWS_PROFILE", "cmp-dev")
    return synthesize_structured(system_prompt, user_prompt, tool_name, tool_schema, max_tokens=max_tokens)


def judge(
    substrate_bundle: dict,
    decision: "Optional[dict]" = None,
    *,
    llm: "Optional[Callable[..., dict]]" = None,
    max_tokens: int = 3000,
) -> dict:
    """Run the triangulation judge over ONE assembled substrate bundle + its decision lanes.

    ``substrate_bundle`` is the output of ``eval.loop.substrate.assemble*``; ``decision`` carries the two
    shipped lanes. ``llm`` is the structured-tool-call callable (``synthesize_structured`` by default);
    inject a recorded response in tests so no live Bedrock is needed.

    Returns a PROPOSE-ONLY report. A dead / NULL-everything substrate is NEVER sent to the LLM — the
    judge returns ``skipped`` with the reason (garbage-in → no judgement), so a dead package can never be
    read as 'clean, no findings'. ``report_only`` is always ``True`` (STOP-A: findings do not route to
    Tier-1 until the teeth + containment guard are green)."""
    base = {
        "schema_version": SCHEMA_VERSION,
        "report_only": True,
        "findings": [],
        "n_findings": 0,
        "lanes_present": {"literature": False, "narrative": False},
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

    views = build_views(substrate_bundle, decision)
    base["lanes_present"] = {
        "literature": views.get("literature_lane") is not None,
        "narrative": views.get("narrative") is not None,
    }

    user_prompt = render_user_prompt(views)
    call = llm or (lambda s, u, tn, ts, max_tokens=max_tokens: _default_llm(s, u, tn, ts, max_tokens))
    raw = call(SYS, user_prompt, TOOL_NAME, TOOL, max_tokens=max_tokens)

    findings = parse_findings(raw)
    base["findings"] = findings
    base["n_findings"] = len(findings)
    base["provenance"] = _provenance(raw if isinstance(raw, dict) else {})
    return base


# ── CLI (live run — never reached by the test suite) ─────────────────────────────────────────────────
def _cli(argv: "Optional[list[str]]" = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Triangulation judge over one emitted run dir (propose-only).")
    parser.add_argument("run_dir", help="an --emit-envelope run dir (evidence_package.json + decision.json)")
    parser.add_argument(
        "--out", default=None, help="where to persist the judge result JSON (default: <run_dir>/judge_result.json)"
    )
    parser.add_argument("--max-tokens", type=int, default=3000)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    bundle = _substrate.assemble(run_dir)
    decision_path = run_dir / "decision.json"
    decision = json.loads(decision_path.read_text()) if decision_path.exists() else None

    result = judge(bundle, decision, max_tokens=args.max_tokens)

    out = Path(args.out) if args.out else run_dir / "judge_result.json"
    out.write_text(json.dumps(result, indent=1, default=str))  # persist BEFORE printing

    print(f"=== triangulation judge: {run_dir.name} ===")
    if result["skipped"]:
        print(f"  SKIPPED: {result['skipped']}")
        return 0
    lp = result["lanes_present"]
    print(f"  lanes present: literature={lp['literature']} narrative={lp['narrative']}")
    n = result["n_findings"]
    print(f"  findings: {n} {'[CLEAN — judge stayed quiet]' if n == 0 else ''}  (report_only={result['report_only']})")
    for f in result["findings"]:
        print(f"  • [{f.get('kind')}] {f.get('target')}: {str(f.get('finding'))[:160]}")
        if f.get("datum_refs"):
            print(f"      datum_refs: {f['datum_refs']}")
    print(f"  → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
