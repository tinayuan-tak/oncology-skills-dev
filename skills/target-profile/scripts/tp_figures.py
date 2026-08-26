"""target-profile — figure ORCHESTRATOR (PR-1 of the composed-dashboard restructure).

ONE place that owns the composed run's `figures/` tree. It does NOT own the figure PRIMITIVES —
those are fleet-shared in `_skills_common` (the per-card registry, `composite_panel`, the headline
hero) and are only CALLED here. This module composes them for a single composed run and returns a
`FigureManifest` so the renderers read figure paths from one source instead of re-deriving `figures/`.

Behavior-preserving vs the prior inline block in run.py (composite skipped under --verdict-only;
per-card figures skipped under --no-figures), PLUS one additive fix: per-sub-skill HERO svgs are now
written to `figures/subskills/<short>/hero.svg` (previously computed but only re-rendered inline in
HTML, never emitted as files). All verdict-inert — figures never touch the nomination spine.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Shared PRIMITIVES (fleet-owned; called, not owned) + the TP-only per-card emitter (pinned name/module).
from _skills_common import render_composite_panel
from tp_evidence_package import _emit_card_figures


def resolve_figures_root(out: Path) -> Path:
    """The ONE figures/ root for a run (kills the two separate `args.out/'figures'` computations)."""
    return Path(out) / "figures"


@dataclass
class FigureManifest:
    """Everything a renderer needs to reference this run's figures — one source of truth."""
    figures_dir: Path
    composite_png: Optional[Path] = None
    composite_svg: Optional[Path] = None
    composite_rel: Optional[str] = None          # md image relpath; None when composite skipped/failed
    card_figures: dict = field(default_factory=dict)      # {card_id: [descriptor,...]} from the registry
    subskill_heros: dict = field(default_factory=dict)    # {short: "figures/subskills/<short>/hero.svg"}


def emit_subskill_heros(sub_results: dict, figures_dir: Path, target: str, indication: str) -> dict:
    """Write each sub-skill's canonical headline HERO to figures/subskills/<short>/hero.svg, using the
    SAME shared `render_headline_hero_svg` the HTML inlines — from the `headline_block.hero` payload the
    fan-out stashes at sub_results[short]['synthesis_facet']['headline_block']. Additive + verdict-inert;
    fail-open per sub-skill (a sub-skill with no headline_block or a render error contributes nothing)."""
    try:
        from _skills_common.headline_hero import render_headline_hero_svg
    except Exception as e:  # noqa: BLE001 — heros must never block a run
        print(f"[target-profile] WARN: headline_hero unavailable ({type(e).__name__}); no sub-skill heros",
              file=sys.stderr)
        return {}
    out: dict = {}
    for short, sr in (sub_results or {}).items():
        facet = (sr or {}).get("synthesis_facet")
        hb = facet.get("headline_block") if isinstance(facet, dict) else None
        hero = hb.get("hero") if isinstance(hb, dict) else None
        if not isinstance(hero, dict):
            continue
        try:
            svg = render_headline_hero_svg(hero, target, indication)
        except Exception as e:  # noqa: BLE001
            print(f"[target-profile] WARN: hero render failed for {short} ({type(e).__name__})",
                  file=sys.stderr)
            continue
        d = figures_dir / "subskills" / short
        d.mkdir(parents=True, exist_ok=True)
        (d / "hero.svg").write_text(svg)
        out[short] = f"figures/subskills/{short}/hero.svg"
    if out:
        print(f"[target-profile] wrote {len(out)} sub-skill hero svg(s) → figures/subskills/",
              file=sys.stderr)
    return out


def emit_figures(args, sub_results: dict, llm_output: dict, *, profile_timers: bool = False) -> FigureManifest:
    """Produce the composed run's figures and return a FigureManifest. Mirrors the prior run.py block:
    composite panel (skipped under --verdict-only), per-card registry figures (skipped under
    --no-figures), + the additive per-sub-skill heros. Best-effort — a render failure never blocks the run."""
    figures_dir = resolve_figures_root(args.out)
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Composite "at a glance" panel (Shape C slide asset). Skipped under --verdict-only.
    composite_png = figures_dir / "target_profile_at_a_glance.png"
    composite_rel: Optional[str] = None
    if args.verdict_only:
        print("[target-profile] --verdict-only: skipped composite panel render", file=sys.stderr)
    else:
        try:
            render_composite_panel(out_path=composite_png, target=args.target,
                                   indication=args.indication, sub_results=sub_results,
                                   llm_output=llm_output)
            composite_rel = f"figures/{composite_png.name}"
            print(f"[target-profile] wrote {composite_png} (+ .svg companion)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — never block emission on a panel render failure
            print(f"[target-profile] WARN: composite panel render failed: {e}", file=sys.stderr)

    # Per-card figures + per-sub-skill heros. Skipped under --no-figures (byte-identical spine).
    if args.no_figures:
        card_figures: dict = {}
        subskill_heros: dict = {}
        print("[target-profile] --no-figures: skipped per-card figure + hero emission", file=sys.stderr)
    else:
        _t0 = time.perf_counter() if profile_timers else 0.0
        card_figures = _emit_card_figures(sub_results, figures_dir, args.target, args.indication)
        subskill_heros = emit_subskill_heros(sub_results, figures_dir, args.target, args.indication)
        if profile_timers:
            print(f"[perf] === figure-emit total {time.perf_counter() - _t0:6.1f}s ===", file=sys.stderr)

    return FigureManifest(
        figures_dir=figures_dir,
        composite_png=composite_png if composite_rel else None,
        composite_svg=composite_png.with_suffix(".svg") if composite_rel else None,
        composite_rel=composite_rel,
        card_figures=card_figures,
        subskill_heros=subskill_heros,
    )


__all__ = ["resolve_figures_root", "FigureManifest", "emit_subskill_heros", "emit_figures"]
