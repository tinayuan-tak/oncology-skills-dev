#!/usr/bin/env python
"""Project every POLARITY-BEARING surface of a live nomination run onto ONE row per axis.

WHY THIS EXISTS
---------------
A composed nomination emits the same axis's "how did it go" judgement on FIVE different surfaces,
each with its own vocabulary:

  1. `sub_verdicts.<axis>.verdict`                             — the resolver's OPEN verdict token
  2. `target_report.skill_reports.<axis>.polarity`             — a 4-token polarity
  3. `target_report.skill_reports.<axis>.role`                 — the synthesis role
  4. `…skill_reports.<axis>.evidence_graph.verdict.{id,polarity}` — the renderer's own copy
  5. `target_report.target_call.gate_scorecard[].{verdict,status}` — dashboard polarity
  6. `target_report.target_call.gate.hard_gates[].{status,disposition}` — gate LIFECYCLE + the
     vocab-sourced disposition (`policy_source: vocab`)

These are NOT redundant copies of one value, and that is exactly the problem: nothing in the repo
declares WHICH surface is authoritative FOR WHICH TYPE, so a reader that compares two of them is
sometimes checking agreement and sometimes committing a category error. `sub_verdict` and
`scorecard_status` cannot agree or disagree — their vocabularies are DISJOINT (a 66-token open
resolver vocabulary vs a 4-token polarity), so "they differ" is type-incommensurability, not a bug.
`sub_verdict` vs `evidence_graph.verdict.id` are DIFFERENT types and need NOT be identical: the first
is the resolver's verdict token, the second is the skill's OWN call token, and they coincide only
because ten of eleven skills pass their resolver verdict straight into `build_skill_report(verdict=…)`.
Treating that coincidence as a type rule is the exact category error this docstring warns about, and it
sat in this file for its whole life — see docs/UNIFIED_OUTPUT_CONTRACT.md § "Type 1".

This script freezes that comparison over a real corpus so the authority contract is checkable
instead of asserted. It reads only ALREADY-EMITTED artifacts (no S3, no credentials) — unlike its
sibling `freeze_fixture.py`, which does live card reads.

Two anti-vacuity rules are enforced here rather than left to the test:
  * an artifact missing ANY of the three surfaces is SKIPPED and COUNTED by reason, so a corpus that
    silently shrank to the one pair that still carries everything cannot masquerade as coverage;
  * `latest/` is a SYMLINK to a dated run, so symlinked run dirs are skipped — following them
    double-counts a pair and inflates every agreement rate by its duplicate.

Usage:
    python skills/target-profile/tests/build_polarity_surface_projection.py \
        --runs ~/dev/framework-runs/examples \
        --out skills/target-profile/tests/fixtures/polarity_surface_projection.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCHEMA = "polarity_surface_projection/v1"


def _run_dirs(root: Path) -> list[Path]:
    """Every non-symlinked run directory containing a nomination.json.

    `latest` is a symlink to a dated sibling; following it double-counts that pair.
    """
    out = []
    for pair_dir in sorted(root.iterdir()):
        if not pair_dir.is_dir():
            continue
        for run_dir in sorted(pair_dir.iterdir()):
            if run_dir.is_symlink() or not run_dir.is_dir():
                continue
            if (run_dir / "nomination.json").is_file():
                out.append(run_dir)
    return out


def _surfaces(nom: dict) -> tuple[dict | None, dict | None, dict | None, str]:
    """Return (sub_verdicts, skill_reports, target_call, reason) — reason is '' when all present.

    Tolerates BOTH emitted layouts: the current one nests the call under `target_report`, the older
    2026-08-26 one carried `gate_scorecard` / `recommendation_gate` at top level. A layout probe that
    only knew one of them would silently report the other as 'no scorecard'.
    """
    sub_verdicts = nom.get("sub_verdicts")
    report = nom.get("target_report") or {}
    skill_reports = report.get("skill_reports") or nom.get("skill_reports")
    target_call = report.get("target_call") or nom.get("target_call")
    if target_call is None and "gate_scorecard" in nom:  # 2026-08-26 layout
        target_call = {
            "gate_scorecard": nom["gate_scorecard"],
            "gate": {"hard_gates": (nom.get("recommendation_gate") or {}).get("hard_gates", [])},
        }
    missing = [
        name
        for name, val in (
            ("sub_verdicts", sub_verdicts),
            ("skill_reports", skill_reports),
            ("target_call", target_call),
        )
        if not val
    ]
    return sub_verdicts, skill_reports, target_call, ("missing:" + "+".join(missing) if missing else "")


def project(run_dir: Path) -> tuple[list[dict], str]:
    """Project one run into rows (one per axis). Returns (rows, skip_reason)."""
    nom = json.loads((run_dir / "nomination.json").read_text())
    sub_verdicts, skill_reports, target_call, reason = _surfaces(nom)
    if reason:
        return [], reason

    scorecard_by_axis = {r["short"]: r for r in (target_call.get("gate_scorecard") or []) if r.get("short")}
    hard_gates_by_axis: dict[str, list[dict]] = {}
    for hg in (target_call.get("gate") or {}).get("hard_gates") or []:
        hard_gates_by_axis.setdefault(hg.get("short"), []).append(hg)

    # The axis key is the JOIN across all surfaces. Union, not intersection: an axis present on one
    # surface and absent from another is precisely the asymmetry the contract has to name, so
    # intersecting here would delete the evidence.
    axes = sorted(set(sub_verdicts) | set(skill_reports) | set(scorecard_by_axis) | set(hard_gates_by_axis))

    rows = []
    for axis in axes:
        sr = skill_reports.get(axis) or {}
        eg_verdict = (sr.get("evidence_graph") or {}).get("verdict") or {}
        sc = scorecard_by_axis.get(axis) or {}
        rows.append(
            {
                "target": nom.get("target"),
                "indication": nom.get("indication"),
                "generated_at": nom.get("generated_at"),
                "run": run_dir.name,
                "axis": axis,
                # surface 1 — resolver verdict token (OPEN vocabulary)
                "sub_verdict": (sub_verdicts.get(axis) or {}).get("verdict"),
                "sub_verdict_driving_rule_id": (sub_verdicts.get(axis) or {}).get("driving_rule_id"),
                # surfaces 2+3 — skill report
                "skill_report_polarity": sr.get("polarity"),
                "skill_report_role": sr.get("role"),
                "skill_report_call": sr.get("call"),
                # surface 4 — the renderer's own copy of the verdict
                "evidence_graph_verdict_id": eg_verdict.get("id"),
                "evidence_graph_verdict_polarity": eg_verdict.get("polarity"),
                # surface 5 — dashboard scorecard
                "scorecard_verdict": sc.get("verdict"),
                "scorecard_status": sc.get("status"),
                "scorecard_is_deciding": sc.get("is_deciding"),
                # surface 6 — gate lifecycle rows (MANY per axis: one per declared kill-capable
                # verdict), each carrying the vocab-sourced disposition.
                "hard_gates": [
                    {
                        "verdict": hg.get("verdict"),
                        "status": hg.get("status"),
                        "disposition": hg.get("disposition"),
                        "live_verdict": hg.get("live_verdict"),
                        "policy_source": hg.get("policy_source"),
                    }
                    for hg in hard_gates_by_axis.get(axis, [])
                ],
            }
        )
    return rows, ""


def build(runs_root: Path) -> dict:
    rows: list[dict] = []
    skipped: dict[str, int] = {}
    kept_runs: list[str] = []
    # Dedupe LATEST-PER-PAIR by generated_at: the corpus carries several runs per pair and an
    # agreement rate computed over all of them weights whichever pair was re-run most.
    best: dict[tuple[str, str], tuple[str, list[dict], str]] = {}
    for run_dir in _run_dirs(runs_root):
        try:
            r, reason = project(run_dir)
        except Exception as e:  # noqa: BLE001 — record, never abort the build
            skipped[f"error:{type(e).__name__}"] = skipped.get(f"error:{type(e).__name__}", 0) + 1
            continue
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        key = (r[0]["target"], r[0]["indication"])
        stamp = r[0]["generated_at"] or ""
        if key not in best or stamp > best[key][0]:
            best[key] = (stamp, r, f"{run_dir.parent.name}/{run_dir.name}")
    for _stamp, r, label in sorted(best.values(), key=lambda t: t[2]):
        rows.extend(r)
        kept_runs.append(label)

    return {
        "_schema": SCHEMA,
        "_provenance": {
            "runs_root": str(runs_root),
            "n_runs_kept": len(kept_runs),
            "runs_kept": kept_runs,
            "n_runs_skipped": sum(skipped.values()),
            "skipped_by_reason": dict(sorted(skipped.items())),
            "n_rows": len(rows),
        },
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="~/dev/framework-runs/examples")
    ap.add_argument("--out", default=str(HERE / "fixtures" / "polarity_surface_projection.json"))
    args = ap.parse_args()

    runs_root = Path(args.runs).expanduser()
    proj = build(runs_root)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proj, indent=1, sort_keys=False) + "\n")

    p = proj["_provenance"]
    print(f"wrote {out}")
    print(f"  runs kept {p['n_runs_kept']} (latest-per-pair), skipped {p['n_runs_skipped']}: {p['skipped_by_reason']}")
    print(f"  rows {p['n_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
