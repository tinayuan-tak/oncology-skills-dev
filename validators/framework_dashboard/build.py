#!/usr/bin/env python3
"""build_unified_dashboard.py — ONE product: framework health + architecture wiring.

Consolidates the two dashboards into a single self-contained HTML with an executive
Overview landing that drills into an Explorer (Miller-columns wiring), a Health matrix,
a Cards inventory, and a Datasets inventory — all from one build, one data model, one
palette.

Design constraint (2026-08-18): the canonical home is target-contracts/validators/
framework_health, but that package is under active parallel rework. So this product
CONSUMES both data sources without modifying the probe:
  - the architecture graph is fresh-extracted (build_architecture_explorer.build)
  - health is computed fresh via framework_health.generate() when importable, else
    loaded from a health JSON on disk.
Upstream into the framework_health package once the probe rework lands.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from . import extract as A
from .render_unified import render_html

HOME = Path.home()


def compute_or_load_health(tc: Path, sk: Path, dc: Path, out_dir: Path,
                           prefer_compute: bool = True) -> dict | None:
    """Fresh health via framework_health.generate() (accurate current-state), else load a
    committed/prior JSON. Writes the fresh copy to out_dir/health_current.json.

    Health is computed over the SAME roots the CLI resolved (contracts/skills/catalog),
    keeping methods/products from probe defaults — so running from a /tmp worktree (whose
    siblings aren't co-located) still points at the real sibling checkouts."""
    if prefer_compute:
        try:
            import sys
            sys.path.insert(0, str(tc))
            from validators.framework_health import build_framework_health as B, probe
            roots = {**probe.default_roots(), "contracts": tc, "skills": sk, "catalog": dc}
            report = B.generate(roots)
            report["generated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
            out = out_dir / "health_current.json"
            out.write_text(json.dumps(report, indent=1, default=str))
            print(f"· computed fresh health ({report['summary']['n_skills']} skills) → {out.name}")
            return report
        except Exception as e:
            print(f"  ! fresh health compute failed ({e}); falling back to on-disk JSON")
    for cand in (out_dir / "health_current.json", tc / "health" / "framework_health.json"):
        if cand.exists():
            print(f"· loaded health from {cand}")
            return json.load(open(cand))
    print("  ! no health data available — health/overview tabs will be thin")
    return None


def merge(graph: dict, health: dict | None) -> dict:
    """Attach the full health slice the Overview + Health tabs need onto the arch graph."""
    if not health:
        graph["health"] = None
        return graph
    skills = {}
    for s in health.get("skills", []):
        skills[s["name"]] = {
            "verdict": s.get("health_verdict"),
            "reason_text": s.get("reason_text"),
            "health_reason": s.get("health_reason"),
            "drift_flags": s.get("drift_flags", []),
            "risk_category": s.get("risk_category"),
            "runs_clean": s.get("runs_clean"),
            "kind": (s.get("derived") or {}).get("kind"),
            "resolver_bound": (s.get("derived") or {}).get("resolver_bound"),
            "test_count": (s.get("derived") or {}).get("test_count"),
            "n_cards": s.get("n_cards"),
            "n_cards_live": s.get("n_cards_live"),
            "declared_status": (s.get("declared") or {}).get("status"),
        }
    cards = {c["card_id"]: {
        "card_health": c.get("card_health"),
        "has_live_reader": c.get("has_live_reader"),
        "fires_in_real_package": c.get("fires_in_real_package"),
        "is_orphan": c.get("is_orphan"),
        "consumers": c.get("consumers", []),
        "reason_text": c.get("reason_text"),
    } for c in health.get("cards", [])}
    graph["health"] = {
        "generated_at": health.get("generated_at"),
        "summary": health.get("summary", {}),
        "drift_index": health.get("drift_index", []),
        "skills": skills,
        "cards": cards,
    }
    return graph


def _default_roots():
    """Resolve sibling-repo roots via framework_health.probe (single source of truth),
    falling back to extract.DEFAULTS when the probe isn't importable."""
    try:
        from validators.framework_health import probe
        r = probe.default_roots()
        return {"tc": r["contracts"], "sk": r["skills"], "dc": r["catalog"]}
    except Exception:
        return {k: A.DEFAULTS[k] for k in ("tc", "sk", "dc")}


def main():
    R = _default_roots()
    # Default artifacts land in the contracts repo's health/ dir, beside framework_health's.
    out_default = R["tc"] / "health" / "framework_dashboard.html"
    ap = argparse.ArgumentParser(description="Build the consolidated framework dashboard (health + architecture).")
    ap.add_argument("--tc", default=str(R["tc"]))
    ap.add_argument("--sk", default=str(R["sk"]))
    ap.add_argument("--dc", default=str(R["dc"]))
    ap.add_argument("--out", default=str(out_default))
    ap.add_argument("--json", default=str(out_default.with_suffix(".json")))
    ap.add_argument("--no-compute-health", action="store_true", help="load health JSON instead of recomputing")
    args = ap.parse_args()

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    health = compute_or_load_health(Path(args.tc), Path(args.sk), Path(args.dc), out_dir,
                                    prefer_compute=not args.no_compute_health)
    hpath = out_dir / "health_current.json"
    graph = A.build(Path(args.tc), Path(args.sk), Path(args.dc),
                    health_json_path=(hpath if hpath.exists() else None))
    graph = merge(graph, health)

    Path(args.json).write_text(json.dumps(graph, separators=(",", ":")))
    Path(args.out).write_text(render_html(graph))

    s = graph["summary"]
    hs = (graph.get("health") or {}).get("summary", {})
    import os
    print(f"\n✓ UNIFIED dashboard: {s['n_skills']} skills · {s['n_cards']} cards · "
          f"{s['n_datasets']} datasets · {s['n_resolvers']} resolvers")
    if hs:
        print(f"  health: {hs.get('verdict_tally')} · {hs.get('n_drift_flags')} drift ({hs.get('n_error_drift')} error)")
    print(f"  HTML → {args.out}  ({os.path.getsize(args.out)//1024} KB)")


if __name__ == "__main__":
    main()
