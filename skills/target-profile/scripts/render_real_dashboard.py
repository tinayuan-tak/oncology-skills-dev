#!/usr/bin/env python3
"""Render the target-profile dashboard from a REAL sub-skill run (real card summaries + real
figures) — WITHOUT the Bedrock LLM synthesis step.

Motivation (2026-07-21): hand-authored synthetic `sub_results` fixtures contradicted the
real-data plots (the emitters re-read live data), which masqueraded as dashboard bugs. This
harness runs the actual sub-skills so every card VALUE and its PLOT come from the same real data
and agree by construction — the honest artifact to review + demo. Only the LLM narrative
(executive summary / tension) is stubbed, since it needs Bedrock and is cosmetic text, not data.

Usage:
    AWS_PROFILE=cbg python -m skills.target-profile.scripts.render_real_dashboard \
        --target KRAS --indication COADREAD --out <dir>
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve()
_RUN = _HERE.parent / "run.py"


def _load_run():
    spec = importlib.util.spec_from_file_location("tp_run_real", _RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_LLM_STUB = {
    "executive_summary": {"value": "[LLM synthesis skipped in this render — deterministic evidence "
                                   "below is real. Run the full skill with Bedrock for the narrative.]",
                          "_source": "stub", "_prompt_hash": "n/a"},
    "overall_recommendation": {"value": "see gate evidence below", "_source": "stub"},
    "confidence": {"value": "n/a", "_source": "stub"},
    "tension_analysis": {"value": "[LLM tension analysis skipped — see the deterministic gate "
                                  "sections + risk-category lens.]", "_source": "stub"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tp = _load_run()

    # 1. REAL sub-skill fan-out (real card summaries from live/cached data).
    print(f"[render-real] running sub-skills for {args.target} / {args.indication} ...")
    sub_results = tp._run_sub_skills(args.target, args.indication, subtypes=None)
    for short, r in sub_results.items():
        v = r.get("verdict")
        print(f"  - {short:28s} -> {(v[0] if v else '(no verdict)')}")

    # 2. REAL per-card figure emission (re-runs method internals → real plots).
    figs = args.out / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    card_figures = tp._emit_card_figures(sub_results, figs, args.target, args.indication)

    # 3. Deterministic structured outputs (scorecard + ordinal matrix + deciding axis).
    ordinal_matrix = tp._ordinal_matrix(sub_results)
    deciding = None
    try:
        gate_action, gate_hits, _ = tp._gate_recommendation(sub_results, modality=None)
        # positive hits for the deciding-axis router (best-effort; not required for the render)
        deciding = tp._deciding_axis(sub_results, gate_action, gate_hits, [], contracts_repo=None)
    except Exception as e:  # noqa: BLE001 — deciding axis is optional chrome for this harness
        print(f"[render-real] deciding-axis skipped: {e}")
    scorecard = tp._gate_scorecard(sub_results, deciding)

    # 4. Render (LLM narrative stubbed; everything else real).
    html = tp._render_target_profile_html(
        args.target, args.indication, sub_results, _LLM_STUB, {},
        deciding_axis=deciding, ordinal_matrix=ordinal_matrix, scorecard=scorecard,
        card_figures=card_figures, figures_dir=figs)
    out = args.out / "dashboard.html"
    out.write_text(html)
    n_plotly = html.count("class=plotly-fig")
    print(f"[render-real] wrote {out} ({len(html)/1e6:.2f} MB, {n_plotly} plotly figs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
