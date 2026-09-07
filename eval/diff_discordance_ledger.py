#!/usr/bin/env python3
"""diff_discordance_ledger — turn the one-shot ledger into a MONITORED cadence.

Compares a freshly-built discordance ledger against a committed BASELINE of already-seen SHARP
candidate gaps (calibration_gap + verdict_rule_gap — the high-signal classes; blind_spot / staleness
drift run-to-run under the non-reproducible LLM lane, so they are trended by COUNT, not diffed
row-by-row). Surfaces:
  * NEW    — a sharp gap whose key is absent from the baseline (appeared since last run: a framework
             change, a data refresh, or the literature moving) → the actionable signal.
  * RESOLVED — a baseline sharp key absent from the new ledger (a fix landed, or the lane no longer
             contradicts) → confirm + prune the baseline.
  * blind/staleness COUNT deltas — coarse trend only.

Row key = "SKILL|TARGET|INDICATION|AXIS|GAP_CLASS" (claim-vector-axis aligned — see
build_discordance_ledger v2). Exit non-zero when NEW sharp gaps appear (the nightly guard signal).
This is escalate-only + review-queue: it never edits a verdict, never fails a skill run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SHARP = ("calibration_gap", "verdict_rule_gap")


def _row_key(r: dict) -> str:
    return "|".join(str(r.get(k)) for k in ("skill", "target", "indication", "axis_key", "gap_class"))


def sharp_keys(ledger: dict) -> set[str]:
    return {_row_key(r) for r in ledger.get("rows", []) if r.get("gap_class") in SHARP}


def _coarse_counts(ledger: dict) -> dict:
    return dict(ledger.get("summary", {}).get("by_gap_class", {}))


def load_baseline(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema": "discordance_baseline/v1", "keys": [], "counts": {}}
    return json.loads(p.read_text())


def diff(ledger: dict, baseline: dict) -> dict:
    new_keys = sharp_keys(ledger)
    base_keys = set(baseline.get("keys", []))
    appeared = sorted(new_keys - base_keys)
    resolved = sorted(base_keys - new_keys)
    # attach the full row for each appeared key (for the report)
    by_key = {_row_key(r): r for r in ledger.get("rows", []) if r.get("gap_class") in SHARP}
    return {
        "new_sharp_gaps": [by_key[k] for k in appeared],
        "resolved_sharp_gaps": resolved,
        "n_new": len(appeared),
        "n_resolved": len(resolved),
        "coarse_count_delta": {
            cls: _coarse_counts(ledger).get(cls, 0) - baseline.get("counts", {}).get(cls, 0)
            for cls in set(_coarse_counts(ledger)) | set(baseline.get("counts", {}))
        },
    }


def baseline_from_ledger(ledger: dict) -> dict:
    import datetime as _dt

    return {
        "schema": "discordance_baseline/v1",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "corpus_fingerprint": ledger.get("corpus_fingerprint"),
        "keys": sorted(sharp_keys(ledger)),
        "counts": _coarse_counts(ledger),
        "note": (
            "SHARP (calibration_gap + verdict_rule_gap) keys seen as of this build; the monitor "
            "flags NEW sharp keys. Prune a key here when its gap is fixed/dismissed (CASE_LOG)."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True, help="fresh discordance_ledger.json (v2)")
    ap.add_argument("--baseline", required=True, help="committed eval/discordance_baseline.json")
    ap.add_argument("--out", default=None, help="write the diff report JSON here")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="(re)generate the baseline FROM --ledger and write it to --baseline (no diff/exit)",
    )
    ap.add_argument(
        "--fail-on-new", action="store_true", help="exit 1 when NEW sharp gaps appear (the nightly-guard signal)"
    )
    a = ap.parse_args(argv)

    ledger = json.loads(Path(a.ledger).read_text())
    if a.write_baseline:
        Path(a.baseline).write_text(json.dumps(baseline_from_ledger(ledger), indent=2))
        print(f"[baseline] wrote {len(sharp_keys(ledger))} sharp keys → {a.baseline}")
        return 0

    report = diff(ledger, load_baseline(a.baseline))
    text = json.dumps(report, indent=2)
    if a.out:
        Path(a.out).write_text(text)
    print(
        f"[diff] NEW sharp gaps: {report['n_new']} · RESOLVED: {report['n_resolved']} · "
        f"count delta: {report['coarse_count_delta']}"
    )
    for r in report["new_sharp_gaps"]:
        print(
            f"  NEW [{r['gap_class']}] {r['skill']} {r['target']}/{r['indication']} "
            f"axis={r['axis_key']} claim_signal={r.get('claim_signal')} vcites={r['n_verified_citations']}"
        )
    if a.fail_on_new and report["n_new"] > 0:
        print(
            f"::error title=discordance-monitor::{report['n_new']} NEW sharp discordance(s) — triage + "
            "update eval/CASE_LOG.md, then prune the baseline."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
