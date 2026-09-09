#!/usr/bin/env python3
"""eval_retrieval — the RETRIEVAL eval harness (PR-3, Part D): make "enriches the RIGHT info" measurable.

The existing validation/gold_seed_v0.json scores the DETERMINISTIC risk bins; nothing measured whether the
literature layer surfaces the decision-relevant papers or filters noise. This harness does, per gold case
(target, indication, axis):

  - critical_signal_recall — does ANY kept abstract mention the decision-critical TOPIC (a curated regex,
    e.g. FOLR1 safety → ocular/keratopathy)? A regex PROXY, deliberately NOT a pinned PMID: PMIDs are
    brittle (relevance re-ranks, papers get added) whereas "did we surface the ocular-tox topic at all" is
    the property that actually matters and stays curatable.
  - on_axis_precision — fraction of kept abstracts that are on-axis (≥1 axis phrase-token). The Stage-2
    relevance gate should raise this; the harness is how we PROVE a gate/source change helped vs added noise.
  - n_kept / n_dropped — the gate's throughput + how much it removed.

The metric functions are PURE (unit-tested offline on synthetic abstracts). The CLI runs the LIVE 3-lane
retrieval per case (needs network; no Bedrock — retrieval only) and prints a per-case table + a summary.
Best-effort per case: a retrieval error is reported, never fatal.

    python3 scripts/eval_retrieval.py --gold validation/retrieval_gold_v0.json [--per-cat 8]
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


def on_axis_precision(abstracts: list, axis: str) -> float | None:
    """PURE: fraction of abstracts that are ON-AXIS (≥1 axis phrase-token). None for an empty set (a
    precision of 0/0 is undefined — report it as N/A, never 0.0, so it can't be mistaken for 'all noise')."""
    if not abstracts:
        return None
    tokens = rl._axis_tokens(rl.AXIS_PUBMED_TERMS.get(axis, ("", True))[0])
    on = sum(1 for a in abstracts if rl._axis_match(_text(a), tokens) > 0)
    return round(on / len(abstracts), 3)


def score_case(case: dict, kept: list, dropped: list) -> dict:
    """PURE: fold one case's retrieved (kept, dropped) into the scored row."""
    return {
        "target": case.get("target"),
        "indication": case.get("indication"),
        "axis": case.get("axis"),
        "note": case.get("note"),
        "critical_signal_recall": critical_signal_present(kept, case.get("critical_signal", "")),
        "on_axis_precision": on_axis_precision(kept, case.get("axis", "")),
        "n_kept": len(kept),
        "n_dropped": len(dropped),
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
    a = ap.parse_args(argv)
    gold = json.loads(Path(a.gold).read_text())
    rows = evaluate(gold, per_cat=a.per_cat)

    print(f"{'target':10} {'indication':22} {'axis':14} {'recall':7} {'prec':6} {'kept':5} {'drop':5}")
    print("-" * 78)
    n_recall = 0
    for r in rows:
        if "error" in r:
            print(
                f"{r.get('target', ''):10} {r.get('indication', ''):22} {r.get('axis', ''):14} ERROR {r['error'][:30]}"
            )
            continue
        n_recall += 1 if r["critical_signal_recall"] else 0
        prec = "N/A" if r["on_axis_precision"] is None else f"{r['on_axis_precision']:.2f}"
        print(
            f"{r['target']:10} {r['indication']:22} {r['axis']:14} "
            f"{'HIT' if r['critical_signal_recall'] else 'miss':7} {prec:6} {r['n_kept']:<5} {r['n_dropped']:<5}"
        )
    scored = [r for r in rows if "error" not in r]
    print(
        f"\ncritical_signal_recall: {n_recall}/{len(scored)} cases"
        + (f"  ({len(rows) - len(scored)} errored)" if len(rows) != len(scored) else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
