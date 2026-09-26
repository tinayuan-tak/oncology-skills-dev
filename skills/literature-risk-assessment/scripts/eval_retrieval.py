#!/usr/bin/env python3
"""eval_retrieval — the RETRIEVAL eval harness (PR-3, Part D): make "enriches the RIGHT info" measurable.

The existing validation/gold_seed_v0.json scores the DETERMINISTIC risk bins; nothing measured whether the
literature layer surfaces the decision-relevant papers or filters noise. This harness does, per gold case
(target, indication, axis):

  - critical_signal_recall — does ANY kept abstract mention the decision-critical TOPIC (a curated regex,
    e.g. FOLR1 safety → ocular/keratopathy)? A regex PROXY, deliberately NOT a pinned PMID: PMIDs are
    brittle (relevance re-ranks, papers get added) whereas "did we surface the ocular-tox topic at all" is
    the property that actually matters and stays curatable. This is the ONLY gated leg — its oracle (the
    per-case `critical_signal` regex) is INDEPENDENT of the Stage-2 gate's axis-token functions.
  - n_kept / n_dropped — the gate's throughput + how much it removed (reported, not gated).

`on_axis_precision` was REMOVED as an eval metric (#1618): it reused `retrieval_lanes._axis_tokens` /
`_axis_match` — the SAME functions the Stage-2 gate uses to decide what to keep — so any abstract kept via
the axis-token branch was on-axis *by construction* under the metric. It measured the code with the code
(circular) and gated nothing; a mis-specified axis vocabulary passed both the gate and its own "precision"
check. The independent teeth are `critical_signal_recall` (a separate curated regex).

THE GATE (#1618): `gate_retrieval(rows, min_recall=...)` is a PURE pass/fail over the scored rows.
Errored cases count as FAILURES (they do NOT shrink the denominator — a systematic retrieval outage must
FAIL, not vacuously pass), and an empty row set fails (non-vacuity). `main()` returns non-zero when the
gate fails, so a recall regression is detectable.

The metric functions are PURE (unit-tested offline on synthetic abstracts). The CLI runs the LIVE 3-lane
retrieval per case (needs network; no Bedrock — retrieval only) and prints a per-case table + a summary.
Best-effort per case: a retrieval error is reported per row, then FAILS the gate.

    python3 scripts/eval_retrieval.py --gold validation/retrieval_gold_v0.json [--per-cat 8] [--min-recall 1.0]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import retrieval_lanes as rl  # noqa: E402

_DEFAULT_GOLD = _HERE.parent / "validation" / "retrieval_gold_v0.json"


def _text(a) -> str:
    """title + abstract of an abstract-like object (PubMedAbstract or a dict), lowercased-safe."""
    if isinstance(a, dict):
        return f"{a.get('title', '') or ''} {a.get('abstract', '') or ''}"
    return f"{getattr(a, 'title', '') or ''} {getattr(a, 'abstract', '') or ''}"


def critical_signal_present(abstracts: list, signal_regex: str) -> bool:
    """PURE: does ANY abstract's title+abstract match the case's critical-signal regex (case-insensitive)?
    The recall proxy — surfacing the decision-critical TOPIC — with no brittle PMID pinning."""
    if not signal_regex:
        return False
    pat = re.compile(signal_regex, re.IGNORECASE)
    return any(pat.search(_text(a)) for a in abstracts)


def score_case(case: dict, kept: list, dropped: list) -> dict:
    """PURE: fold one case's retrieved (kept, dropped) into the scored row.
    `on_axis_precision` was removed (#1618): it was circular with the Stage-2 gate (measured the code with
    the code). `critical_signal_recall` — an INDEPENDENT curated regex — is the only quality leg."""
    return {
        "target": case.get("target"),
        "indication": case.get("indication"),
        "axis": case.get("axis"),
        "note": case.get("note"),
        "critical_signal_recall": critical_signal_present(kept, case.get("critical_signal", "")),
        "n_kept": len(kept),
        "n_dropped": len(dropped),
    }


def gate_retrieval(rows: list, *, min_recall: float = 1.0) -> dict:
    """PURE pass/fail gate over scored rows (#1618). The eval is now an ASSERTION, not a printout.

    - critical_signal_recall is the denominator's numerator; the denominator is EVERY row (n_total),
      so an errored case counts as a FAILURE and a systematic outage cannot shrink its way to green.
    - an empty row set FAILS (non-vacuity — an eval that scores nothing must not pass).
    Returns {passed, recall, n_hit, n_total, n_error, failures}."""
    n_total = len(rows)
    n_hit = n_error = 0
    failures: list[str] = []
    for r in rows:
        tag = f"{r.get('target')}/{r.get('axis')}"
        if "error" in r:
            n_error += 1
            failures.append(f"{tag}: ERROR {str(r.get('error'))[:60]}")
        elif r.get("critical_signal_recall"):
            n_hit += 1
        else:
            failures.append(f"{tag}: critical_signal recall MISS")
    recall = (n_hit / n_total) if n_total else 0.0
    passed = n_total > 0 and recall >= min_recall
    return {
        "passed": passed,
        "recall": round(recall, 3),
        "n_hit": n_hit,
        "n_total": n_total,
        "n_error": n_error,
        "failures": failures,
    }


def evaluate(gold: list, *, per_cat: int = 8, retrieve=None) -> list:
    """Run every gold case through retrieval (default: live rl.retrieve_axis; injectable for offline tests)
    and return the scored rows. `retrieve(target, indication, axis, per_cat=...) -> {"kept","dropped"}`."""
    retrieve = retrieve or (lambda t, i, a, **k: rl.retrieve_axis(t, i, a, **k))
    rows = []
    for case in gold:
        try:
            r = retrieve(case["target"], case["indication"], case["axis"], per_cat=per_cat)
            rows.append(score_case(case, r.get("kept", []), r.get("dropped", [])))
        except Exception as e:  # noqa: BLE001 — one case's network failure must not sink the harness
            rows.append({**{k: case.get(k) for k in ("target", "indication", "axis", "note")}, "error": repr(e)})
    return rows


def main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", default=str(_DEFAULT_GOLD))
    ap.add_argument("--per-cat", type=int, default=8)
    ap.add_argument(
        "--min-recall",
        type=float,
        default=1.0,
        help="minimum critical_signal_recall over ALL cases (errors count as failures); gate fails below it",
    )
    a = ap.parse_args(argv)
    gold = json.loads(Path(a.gold).read_text())
    rows = evaluate(gold, per_cat=a.per_cat)

    print(f"{'target':10} {'indication':22} {'axis':14} {'recall':7} {'kept':5} {'drop':5}")
    print("-" * 72)
    for r in rows:
        if "error" in r:
            print(
                f"{r.get('target', ''):10} {r.get('indication', ''):22} {r.get('axis', ''):14} ERROR {str(r['error'])[:30]}"
            )
            continue
        print(
            f"{r['target']:10} {r['indication']:22} {r['axis']:14} "
            f"{'HIT' if r['critical_signal_recall'] else 'miss':7} {r['n_kept']:<5} {r['n_dropped']:<5}"
        )
    g = gate_retrieval(rows, min_recall=a.min_recall)
    print(
        f"\ncritical_signal_recall: {g['n_hit']}/{g['n_total']} cases (recall={g['recall']}; "
        f"{g['n_error']} errored, counted as failures); min-recall={a.min_recall}"
    )
    if not g["passed"]:
        print("GATE FAILED:")
        for f in g["failures"]:
            print(f"  - {f}")
        return 1
    print("GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
