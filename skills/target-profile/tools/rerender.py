#!/usr/bin/env python3
"""Fast standalone RE-RENDER of the target-profile dashboard from a prior run's saved artifacts —
NO 12-subskill fan-out, NO Bedrock. For iterating on tp_render_html.py layout in seconds instead of
re-running the ~10-minute synthesized loop.

Reconstructs the inputs to `_render_target_profile_html` (run.py:531) from disk:
  - nomination.json               -> most params directly (llm_synthesis, deciding_axis, facets, ...)
  - evidence_package.json         -> per-card `summary` dicts (the ONE thing nomination.json drops;
                                     keyed back to each subskill via nomination.sub_verdicts[*].cards_used)
  - 02-hypothesis/hypothesis.json -> the cross-evidence hypothesis (sibling artifact)
  - 01-ground/grounded_*.json     -> the per-axis grounded substrate (sibling artifacts)

Usage:
    python3 tools/rerender.py --run-dir ~/dev/framework-runs/KRAS-COADREAD-fullloop-v2 [--plotly-cdn]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_SKILLS_ROOT = _SCRIPTS.parent.parent          # skills/ — so `import _skills_common` resolves
for _p in (str(_SCRIPTS), str(_SKILLS_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_render_html import _render_target_profile_html  # noqa: E402
from tp_evidence_package import _catalogue_rows_from_sub_results  # noqa: E402


def _find(root: Path, *names):
    for n in names:
        p = root / n
        if p.exists():
            return p
    for n in names:
        hits = sorted(root.glob(f"*/{n}"))
        if hits:
            return hits[0]
    return None


def _load(p):
    return json.loads(p.read_text()) if p and p.exists() else None


def reconstruct_sub_results(nomination: dict, evidence_package: dict) -> dict:
    """Rebuild {short: {skill_dir, cards, fired, verdict}} from the evidence-package card summaries +
    nomination's reduced sub_verdicts. Per-card rule association is not persisted, so `fired` carries
    rule_ids with card_id=None (provenance-trace degrades gracefully; the evidence body is intact)."""
    ep_cards = {c.get("card_id"): c for c in (evidence_package.get("cards") or []) if c.get("card_id")}
    sub_results = {}
    for short, sv in (nomination.get("sub_verdicts") or {}).items():
        cards = [ep_cards[cid] for cid in (sv.get("cards_used") or []) if cid in ep_cards]
        fired = [{"rule_id": rid, "card_id": None} for rid in (sv.get("fired_rule_ids") or [])]
        sub_results[short] = {"skill_dir": sv.get("skill_dir"), "cards": cards, "fired": fired,
                              "verdict": (sv.get("verdict"), sv.get("driving_rule_id"))}
    return sub_results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fast re-render of the target-profile dashboard")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", default=None, type=Path)
    ap.add_argument("--plotly-cdn", action="store_true",
                    help="swap the inlined ~4.6MB Plotly library for a CDN <script src> (Simple Browser cap)")
    args = ap.parse_args(argv)
    root = args.run_dir

    # prefer the fully-SYNTHESIZED nomination (03-dashboard) over the --no-synthesis stage-1 copy
    # (01-ground), which carries a stub llm_synthesis with no overall_recommendation.
    nom_cands = ([root / "nomination.json"] if (root / "nomination.json").exists() else []) \
        + sorted(root.glob("*/nomination.json"),
                 key=lambda q: (0 if "dashboard" in q.parent.name else 1, str(q)))
    nom_p = nom_cands[0] if nom_cands else None
    ep_p = _find(root, "evidence_package.json")
    if not nom_p or not ep_p:
        print(f"need nomination.json ({nom_p}) AND evidence_package.json ({ep_p}) under {root}", file=sys.stderr)
        return 2
    nomination = _load(nom_p)
    evidence_package = _load(ep_p)
    dash_dir = nom_p.parent

    sub_results = reconstruct_sub_results(nomination, evidence_package)
    grounded_by_axis = {}
    for gp in sorted(root.glob("**/grounded_*.json")):
        rec = _load(gp)
        ax = (rec or {}).get("axis") or gp.stem[len("grounded_"):]
        grounded_by_axis[ax] = rec
    hypothesis = _load(_find(root, "hypothesis.json"))
    figures_dir = dash_dir / "figures"
    composite = figures_dir / "target_profile_at_a_glance.svg"

    # Full-nest (2026-09-03): the decision-spine objects live under target_call. Fall back to the legacy
    # top-level keys so rerender still works on PRE-nest nomination.json files from older runs.
    _tc = nomination.get("target_call") or {}
    html = _render_target_profile_html(
        nomination.get("target"), nomination.get("indication"), sub_results,
        nomination.get("llm_synthesis") or {}, nomination.get("invoked_lenses") or {},
        deciding_axis=_tc.get("deciding_axis") or nomination.get("deciding_axis"),
        ordinal_matrix=nomination.get("ordinal_matrix_view"),
        scorecard=_tc.get("gate_scorecard") or nomination.get("gate_scorecard"),
        composite_svg_path=composite if composite.exists() else None,
        catalogue_rows=_catalogue_rows_from_sub_results(sub_results),
        recommendation_gate=_tc.get("gate") or nomination.get("recommendation_gate"),
        card_figures=nomination.get("card_figures"), figures_dir=figures_dir,
        presence_facet=nomination.get("presence_facet"),
        grounded_by_axis=grounded_by_axis, hypothesis=hypothesis,
        confidence_tier=_tc.get("confidence") or nomination.get("confidence_tier"),
        addressable_population=nomination.get("addressable_population"),
    )
    if args.plotly_cdn:
        import re
        CDN = '<script src="https://cdn.plot.ly/plotly-3.0.1.min.js" charset="utf-8"></script>'
        html, _n = re.subn(r"<script[^>]*>(.*?)</script>",
                           lambda m: CDN if "plotly.js v3" in m.group(1)[:200] else m.group(0),
                           html, flags=re.S | re.I)   # re.I so uppercase <SCRIPT> tags match too (CodeQL)

    out = args.out or (dash_dir / "target_profile.rerender.html")
    out.write_text(html)
    print(f"re-rendered {len(sub_results)} subskills -> {out} ({len(html)//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
