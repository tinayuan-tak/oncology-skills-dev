#!/usr/bin/env python3
"""subskill_discordance — the standing per-subskill omics↔literature DISCORDANCE harness.

The composed target-profile already computes, per subskill, a corpus-grounded literature read vs the
deterministic omics signal: `evidence_graph.literature.axes[].agreement_vs_omics`
(agree / extends / contradicts / omics_unavailable / omics_blind), each with an `assertion` +
`citation_ids`, plus a `key_divergence` narrative. This tool AGGREGATES that RICH per-axis signal across a
panel of composed runs into a per-subskill discordance profile — the driver for subskill-by-subskill
enhancement. It reads the SHARP per-axis `contradicts` (NOT the blunt LLM `overall_consistency` rollup),
so a real disagreement (e.g. dependency non_dependent vs literature "KIT is the archetypal GIST addiction")
surfaces instead of hiding in "partially_concordant".

Decoupled from the nomination verdict: a subskill's signal counts whether or not it is verdict-bearing.

Usage:
  python subskill_discordance.py <run_glob_or_dir>...   [--json OUT.json]
  # e.g. python subskill_discordance.py '/home/.../examples/*/2026-09-09-full'
Each positional is a glob or dir; each matched dir must contain a nomination.json. Later dirs do NOT
override an already-seen target (first-seen wins — pass the freshest panel first).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict

_CONTRA = "contradicts"
_UNAVAIL = ("omics_unavailable", "omics_blind")


def _lit_of(rep: dict) -> dict:
    eg = rep.get("evidence_graph") if isinstance(rep, dict) else None
    return (eg or {}).get("literature") or {} if isinstance(eg, dict) else {}


def _iter_runs(patterns: list[str]):
    """Yield (target_dir_name, nomination_dict), first-seen wins across the given globs/dirs."""
    seen: set[str] = set()
    for pat in patterns:
        for d in sorted(glob.glob(pat)):
            if not os.path.isdir(d):
                continue
            t = os.path.basename(os.path.dirname(d))
            f = os.path.join(d, "nomination.json")
            if t in seen or not os.path.exists(f):
                continue
            try:
                yield t, json.load(open(f))
                seen.add(t)
            except (OSError, ValueError):
                continue


def build_profile(patterns: list[str]) -> dict:
    per = defaultdict(
        lambda: {
            "targets": 0,
            "contradicts": 0,
            "extends": 0,
            "agree": 0,
            "unmeasurable": 0,  # every axis omics_unavailable → discordance NOT measurable (axis/coverage gap)
            "contra_cite_anchored": 0,  # discordant targets whose contradicting axis carries ≥1 citation
            "cases": [],
        }
    )
    n_targets = 0
    for t, nom in _iter_runs(patterns):
        n_targets += 1
        sr = (nom.get("target_report") or {}).get("skill_reports") or {}
        for short, rep in sr.items():
            lit = _lit_of(rep)
            axes = lit.get("axes") or []
            if not axes and not lit:
                continue
            ags = [(a.get("agreement_vs_omics") or "") for a in axes]
            if not ags:
                continue
            p = per[short]
            p["targets"] += 1
            if all(x in _UNAVAIL or x == "" for x in ags):
                p["unmeasurable"] += 1
                continue
            contra_axes = [a for a in axes if a.get("agreement_vs_omics") == _CONTRA]
            if contra_axes:
                p["contradicts"] += 1
                if any(a.get("citation_ids") for a in contra_axes):
                    p["contra_cite_anchored"] += 1
                p["cases"].append(
                    {
                        "target": t,
                        "key_divergence": lit.get("key_divergence") or "",
                        "n_contra_axes": len(contra_axes),
                        "n_citations": sum(len(a.get("citation_ids") or []) for a in contra_axes),
                    }
                )
            if any(x == "extends" for x in ags):
                p["extends"] += 1
            if any(x == "agree" for x in ags):
                p["agree"] += 1
    return {"n_targets": n_targets, "per_subskill": dict(per)}


def render(profile: dict) -> str:
    per = profile["per_subskill"]
    order = sorted(per, key=lambda k: (-per[k]["contradicts"], per[k]["unmeasurable"]))
    out = [f"# Per-subskill omics↔literature discordance ({profile['n_targets']} targets)\n"]
    out.append(f"{'subskill':26} {'N':>3} {'CONTRA':>6} {'rate':>5} {'cited':>6} {'unmeasurable':>12}")
    for k in order:
        p = per[k]
        ev = p["targets"] - p["unmeasurable"]  # evaluable = had a measurable comparison
        rate = f"{p['contradicts'] / ev:.0%}" if ev else "n/a"
        cited = f"{p['contra_cite_anchored']}/{p['contradicts']}" if p["contradicts"] else "-"
        out.append(f"{k:26} {p['targets']:3} {p['contradicts']:6} {rate:>5} {cited:>6} {p['unmeasurable']:12}")
    out.append("\n## Discordant cases (ranked by subskill) — the iteration backlog\n")
    for k in order:
        for c in sorted(per[k]["cases"], key=lambda c: -c["n_citations"]):
            out.append(f"[{k}] {c['target']} ({c['n_citations']} cites): {c['key_divergence'][:280]}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    json_out = next((argv[i + 1] for i, a in enumerate(argv) if a == "--json" and i + 1 < len(argv)), None)
    if not args:
        print(__doc__)
        return 2
    profile = build_profile(args)
    print(render(profile))
    if json_out:
        json.dump(profile, open(json_out, "w"), indent=2)
        print(f"\n[wrote {json_out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
