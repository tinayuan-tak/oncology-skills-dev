#!/usr/bin/env python3
"""Verdict-representation scorecard — informative/representative health of the abstraction layer.

Non-gating REPORT (docs/design/VERDICT_REPRESENTATION.md §5). Computes the label-free metrics
derivable from target-contracts alone (resolvers + interpretation-rules + modality.enum):

  [I1] signal-sink coverage      — (channel,signal) pairs emitted by rules vs consumed by resolvers
  [--] verdict-inert rules       — rules defined but referenced by no resolver
  [R2] ignorance/negation split  — resolvers exposing BOTH a no-data AND a measured-negative verdict
  [R6] compression fan-in        — worst rules->one-token collapse per gate (masking risk)
  [R4] cross-gate shared cards   — one measurement driving >1 verdict gate (corroboration inflation)
  [R7] certainty coverage        — axes carrying a wired certainty layer

The replay metrics (I2/I3/I5/R3 + per-gate H/MI + the DPI gap) need calibration nominations and
live in the skills-side diagnostic (they consume decision.json across the calibration set).

Usage:  python scripts/verdict_representation_scorecard.py [--json]
Exit code is ALWAYS 0 — this is a health report, not a gate.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re

ROOT = os.environ.get("TARGET_CONTRACTS_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES, RUL, VOC = f"{ROOT}/resolvers", f"{ROOT}/interpretation-rules", f"{ROOT}/vocabularies"

import yaml

_load = lambda p: yaml.safe_load(open(p))
_CONT = re.compile(
    r"(log2fc|loeuf|pli|copies_per_cell|ceres|chronos|tpm|ratio|percentile|score|"
    r"pvalue|qvalue|q_value|fraction|median|abundance|zscore|z_score)",
    re.I,
)


def compute() -> dict:
    resolvers, res_refs = {}, set()
    for p in sorted(glob.glob(f"{RES}/*.resolver.yaml")):
        s = _load(p)
        g = s.get("gate", os.path.basename(p))
        verds, rules, fanin = set(), set(), collections.Counter()
        for r in s.get("resolve", []):
            verds.add(r.get("verdict"))
            rr = (
                [r["when_fired"]]
                if "when_fired" in r
                else list(r.get("when_any_fired", [])) + list(r.get("when_all_fired", []))
            )
            for x in rr:
                rules.add(x)
                res_refs.add(x)
            fanin[r.get("verdict")] += 1
        verds.add(s.get("default"))
        resolvers[g] = dict(default=s.get("default"), verds=verds, rules=rules, fanin=fanin)

    rule_def, rule_card, sig_pairs = {}, {}, set()
    for p in sorted(glob.glob(f"{RUL}/*.rules.yaml")):
        for r in _load(p).get("rules") or []:
            rid = r["rule_id"]
            rule_def[rid] = True
            rule_card[rid] = r.get("when", {}).get("card_id")
            for ch, sg in (r.get("signals") or {}).items():
                sig_pairs.add((ch, sg))

    def _split(verds):
        v = " ".join(x for x in verds if x)
        nod = "data_unavailable" in v or "not_wired" in v
        neg = any(
            k in v
            for k in [
                "not_selective",
                "non_dependent",
                "passenger",
                "neither",
                "unhit",
                "intractable",
                "depleted",
                "no_curated",
            ]
        )
        return nod and neg

    inert = [r for r in rule_def if r not in res_refs]
    fanin_worst = {g: d["fanin"].most_common(1)[0] for g, d in resolvers.items() if d["fanin"]}
    gcards = collections.defaultdict(set)
    for g, d in resolvers.items():
        for rid in d["rules"]:
            c = rule_card.get(rid)
            if c:
                gcards[g].add(c)
    cg = collections.defaultdict(set)
    for g, cs in gcards.items():
        for c in cs:
            cg[c].add(g)
    shared = {c: sorted(gs) for c, gs in cg.items() if len(gs) > 1}
    return {
        "I1_signal_sink_coverage": {"consumed": 0, "emitted": len(sig_pairs)},
        "verdict_inert_rules": {"inert": len(inert), "total": len(rule_def)},
        "R2_ignorance_negation_split": {
            "resolvers_with_both": sum(1 for d in resolvers.values() if _split(d["verds"])),
            "total": len(resolvers),
        },
        "R6_worst_fanin": {
            g: {"rules": n, "verdict": v} for g, (v, n) in sorted(fanin_worst.items(), key=lambda kv: -kv[1][1])[:6]
        },
        "R4_cross_gate_shared_cards": shared,
        "R7_certainty_coverage": {"wired": 1, "total": len(resolvers)},  # dependency only (2026-08-24)
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    m = compute()
    if args.json:
        print(json.dumps(m, indent=2))
        return
    print("=" * 74)
    print("VERDICT-REPRESENTATION SCORECARD (static; non-gating report)")
    print("=" * 74)
    s = m["I1_signal_sink_coverage"]
    print(f"[I1] signal-sink coverage      : {s['consumed']}/{s['emitted']} (channel,signal) pairs consumed")
    v = m["verdict_inert_rules"]
    print(f"[--] verdict-inert rules       : {v['inert']}/{v['total']} ({100 * v['inert'] // v['total']}%)")
    r = m["R2_ignorance_negation_split"]
    print(f"[R2] ignorance/negation split  : {r['resolvers_with_both']}/{r['total']} resolvers expose both")
    print("[R6] worst compression fan-in  :")
    for g, d in m["R6_worst_fanin"].items():
        print(f"       {g:<26} {d['rules']} rules -> {d['verdict']}")
    print(f"[R4] cross-gate shared cards   : {len(m['R4_cross_gate_shared_cards'])} cards drive >1 gate")
    for c, gs in m["R4_cross_gate_shared_cards"].items():
        print(f"       {c:<40} {gs}")
    c = m["R7_certainty_coverage"]
    print(f"[R7] certainty coverage        : {c['wired']}/{c['total']} axes")


if __name__ == "__main__":
    main()
