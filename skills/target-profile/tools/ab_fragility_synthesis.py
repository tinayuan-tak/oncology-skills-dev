#!/usr/bin/env python3
"""A/B harness for the Phase-0 certainty-layer gate.

Runs target-profile over a FIXED PANEL twice per (target, indication):
  - TREATMENT: default (the per-axis how-solid / certainty block IS in the synthesis prompt)
  - CONTROL:   --ab-suppress-fragility-prompt (block suppressed; everything else identical)

then, for each pair:
  1. ASSERTS the deterministic spine is byte-identical across arms — overall_recommendation
     (post gate-clamp), confidence (post positive-tier floor), and every sub-verdict. This is the
     verdict-inert guarantee; a mismatch is a HARD FAIL (the block leaked into the decision).
  2. Emits a side-by-side markdown (executive_summary + tension_analysis, control vs treatment)
     for the human reviewer, who applies tools/AB_REVIEW_RUBRIC.md to decide the Phase-0 gate.

This harness does NOT itself decide the gate — it produces the artifact a reviewer signs off on.
It is intentionally NOT wired into CI (it needs Bedrock + cbg S3 and is slow: ~12 subskills x
2 arms x |panel|). Run it manually under the synthesis env (see below).

Usage (from the target-profile skill dir):
    export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev
    python3 tools/ab_fragility_synthesis.py --out-root ~/scratch/ab-fragility

The fixed panel lives in AB_REVIEW_RUBRIC.md and is duplicated here as the single source the
harness runs; keep the two in sync (a rubric change without a panel change would review the wrong
targets).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_RUN_PY = _SKILL_DIR / "scripts" / "run.py"

# FIXED PANEL — chosen to span the certainty regimes the block is meant to distinguish:
#   - a broad-coverage, robust call (KRAS/COADREAD)
#   - an amplification/driver target with a different alteration mix (ERBB2/BRCA)
#   - a target with known thin/blind axes on some indications (MET/LUAD)
#   - a de-differentiating surface antigen where presence coverage matters (FOLR1/OV)
#   - a target expected to be fragile/contested on at least one decision axis (CDK4/LGG-adjacent)
# Keep in lockstep with AB_REVIEW_RUBRIC.md § Panel.
PANEL = [
    ("KRAS", "COADREAD"),
    ("ERBB2", "BRCA"),
    ("MET", "LUAD"),
    ("FOLR1", "OV"),
    ("CDK4", "GBM"),
]

# keys whose across-arm equality proves the change stayed verdict-inert
_SPINE_KEYS = ("overall_recommendation", "confidence")


def _find_first(obj, key):
    """Depth-first search for the first occurrence of `key` anywhere in a nested dict/list."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            hit = _find_first(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_first(v, key)
            if hit is not None:
                return hit
    return None


def _spine(nom: dict) -> dict:
    """The deterministic decision spine that MUST match across arms.

    Compares the decision VALUES (recommendation value + `_gated` clamp flag, confidence value,
    every sub-verdict) — NOT the provenance metadata. `_prompt_hash` legitimately DIFFERS across
    arms (the prompt text changes when the certainty block is added/removed); comparing it would be
    a false positive. `_source`/`_model_id` are likewise metadata, not the decision."""
    spine = {}
    for k in _SPINE_KEYS:
        v = _find_first(nom, k)
        spine[k] = v.get("value") if isinstance(v, dict) else v
    rec = _find_first(nom, "overall_recommendation")
    spine["recommendation_gated"] = rec.get("_gated") if isinstance(rec, dict) else None
    sv = nom.get("sub_verdicts") or {}
    spine["sub_verdicts"] = {s: (r.get("verdict") if isinstance(r, dict) else None)
                             for s, r in sv.items()}
    return spine


def _run(target: str, indication: str, out: Path, control: bool) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(_RUN_PY), "--target", target, "--indication", indication,
           "--out", str(out), "--no-figures"]
    if control:
        cmd.append("--ab-suppress-fragility-prompt")
    print(f"  [{'CONTROL' if control else 'TREAT'}] {target}/{indication} -> {out}", file=sys.stderr)
    subprocess.run(cmd, check=True)
    return out / "nomination.json"


def _clean(s) -> str:
    """Flatten a prose value into one GFM-table-safe cell (no newlines, escaped pipes)."""
    if s is None:
        return ""
    return str(s).replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def _prose(nom: dict) -> dict:
    def _txt(k):
        v = _find_first(nom, k)
        if isinstance(v, dict):
            # strip provenance tags; keep the human text field if present
            v = v.get("text") or v.get("value") or json.dumps({kk: vv for kk, vv in v.items()
                                                               if not kk.startswith("_")})
        return _clean(v)
    return {"executive_summary": _txt("executive_summary"),
            "tension_analysis": _txt("tension_analysis")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", required=True, type=Path)
    ap.add_argument("--report-only", action="store_true",
                    help="Skip the (expensive) runs; re-derive the report + parity check from the "
                         "nomination.json files already written under --out-root. Use after a full "
                         "run to iterate on the report/parity logic without re-invoking Bedrock.")
    args = ap.parse_args()

    report = ["# A/B — fragility/certainty block in synthesis (Phase-0 gate artifact)", "",
              "For each pair: deterministic spine MUST match (verdict-inert); compare the prose per "
              "the rubric.", ""]
    spine_failures = []

    for target, indication in PANEL:
        base = args.out_root / f"{target}-{indication}"
        if args.report_only:
            treat_nom = json.loads((base / "treatment" / "nomination.json").read_text())
            ctrl_nom = json.loads((base / "control" / "nomination.json").read_text())
        else:
            treat_nom = json.loads(_run(target, indication, base / "treatment", control=False).read_text())
            ctrl_nom = json.loads(_run(target, indication, base / "control", control=True).read_text())

        st, sc = _spine(treat_nom), _spine(ctrl_nom)
        ok = st == sc
        if not ok:
            spine_failures.append((target, indication, sc, st))

        pt, pc = _prose(treat_nom), _prose(ctrl_nom)
        report += [
            f"## {target} / {indication}",
            f"- **spine parity (verdict-inert):** {'✅ IDENTICAL' if ok else '❌ MISMATCH — HARD FAIL'}",
            f"- recommendation: `{sc['overall_recommendation']}` (both arms)" if ok else
            f"- CONTROL spine {sc}  vs  TREATMENT spine {st}",
            "",
            "| | CONTROL (no block) | TREATMENT (block) |",
            "|---|---|---|",
            f"| executive_summary | {pc['executive_summary']} | {pt['executive_summary']} |",
            f"| tension_analysis | {pc['tension_analysis']} | {pt['tension_analysis']} |",
            "",
        ]

    out_md = args.out_root / "ab_report.md"
    out_md.write_text("\n".join(str(x) for x in report))
    print(f"\nWrote {out_md}")

    if spine_failures:
        print(f"\n❌ SPINE PARITY FAILED for {len(spine_failures)} pair(s) — the certainty block is "
              f"NOT verdict-inert. This is a blocker, not a review item.", file=sys.stderr)
        return 1
    print("\n✅ Spine byte-identical across arms for the whole panel (verdict-inert confirmed). "
          "Now apply tools/AB_REVIEW_RUBRIC.md to the prose in ab_report.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
