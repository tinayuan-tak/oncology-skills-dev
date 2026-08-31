"""CLI + dispatcher entrypoint for the surface same-cell AVIDITY (co-localization) card."""
from __future__ import annotations

import json
from pathlib import Path

from . import samecell as _samecell
from . import window as _window

METHOD_VERSION = "0.2.0"


def build_summary(target: str, indication: str = None) -> dict:
    """Dispatcher entrypoint (CARD_DISPATCHERS contract). Target-centric same-cell avidity + the
    tumor-vs-normal SELECTIVITY WINDOW.

    Two readouts, kept side by side:
      1. TUMOR avidity (samecell.read_target_samecell_avidity) — does the best nominated partner
         co-express with the target on the SAME malignant cells? (samecell_avidity_class, unchanged;
         the existing avidity rules key on it.)
      2. SELECTIVITY WINDOW (window.read_target_selectivity_window) — the safety complement, reading
         the pan-tissue normal same-cell cube sc-samecell-coexpr-normal-v1: does ANY well-powered
         normal cell type co-express BOTH antigens on the same cell? Combines with the tumor axis into
         an AND-gate verdict (window_open / window_marginal / no_window / selectivity_unproven /
         insufficient_tumor_engagement / insufficient_tumor_power / data_unavailable) + a
         selectivity_margin (tumor_both - normal_max_both) for ranking.

    Before v0.2.0 only the tumor axis was surfaced — the normal selectivity gate was built
    (window.py / normal.py) but the cube sc-samecell-coexpr-normal-v1 was orphaned (read by no card).
    Wiring the window here closes that gap so the SAFETY half of the bispecific readout reaches the
    dashboard. Indication-scoped (the tumor cube is per-indication; the normal cube is pan-tissue)."""
    summary = _samecell.read_target_samecell_avidity(target, indication)

    # Selectivity window (tumor engagement AND normal selectivity). Namespaced so the tumor-avidity
    # fields the existing rules read (samecell_avidity_class, best_partner-by-enrichment) are intact;
    # window_best_partner is the best partner by SAFETY verdict, which can differ from the avidity best.
    win = _window.read_target_selectivity_window(target, indication)
    summary["window_verdict"] = win.get("window_verdict")
    summary["selectivity_margin"] = win.get("best_selectivity_margin")
    summary["window_best_partner"] = win.get("best_partner")
    summary["n_window_open"] = win.get("n_window_open")
    summary["normal_liability_locus"] = win.get("best_normal_liability_locus")
    summary["_window"] = win

    summary["method_version"] = METHOD_VERSION
    return summary


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(args.target, args.indication)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (args.out / "manifest.json").write_text(json.dumps(
        {"method": "pair_selectivity_gate", "method_version": METHOD_VERSION, "target": args.target,
         "samecell_avidity_class": summary.get("samecell_avidity_class"),
         "window_verdict": summary.get("window_verdict"),
         "artifacts": {"summary": "summary.json"}, "plotly_figures": []}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
