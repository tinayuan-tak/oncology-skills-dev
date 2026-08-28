#!/usr/bin/env python3
"""build_unified_dashboard.py — framework health + architecture wiring.

CONSOLIDATION NOTE (2026-08-28): the SINGLE canonical published dashboard is now the Living
Architecture Document (validators/architecture_dashboard/living), which SUPERSETS this one
(it renders these same Overview/Explorer/Health/Cards/Datasets/Coverage tabs PLUS Flow / Gaps /
Concepts / Docs). This module remains the composition ENGINE — the living builder imports
`compute_or_load_health`, `merge`, and `load_coverage` from here — and stays runnable standalone
for debugging the wiring/health layer in isolation. `make dashboard` / publish_dashboard publish
the living document, not this artifact.

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

import build_architecture_explorer as A
from render_unified import render_html

HOME = Path.home()


def compute_or_load_health(tc: Path, out_dir: Path, prefer_compute: bool = True) -> dict | None:
    """Fresh health via framework_health.generate() (accurate current-state), else load a
    committed/prior JSON. Writes the fresh copy to out_dir/health_current.json."""
    if prefer_compute:
        try:
            import sys
            sys.path.insert(0, str(tc))
            from validators.framework_health import build_framework_health as B, probe
            roots = probe.default_roots()
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


def load_coverage(dp_root: Path) -> dict | None:
    """The output registry's committed catalog.json at the data-products root — the OUTPUT
    coverage layer (governed evidence packages ∪ exploratory skill-runs + the card-firing
    index that framework_health's fires_in_any_run signal derives from). Returns None when
    absent so the Coverage tab degrades to an honest 'no registry' message."""
    cat_path = Path(dp_root) / "catalog.json"
    if not cat_path.exists():
        return None
    try:
        cat = json.loads(cat_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "generated_at": cat.get("generated_at"),
        "summary": cat.get("summary", {}),
        "grid": cat.get("coverage", {}),          # {lanes, cells, grid}
        "firings": cat.get("card_firings", {}),
        "profiles": cat.get("profiles", {}),      # cell -> published-profile pointers (link target)
    }


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tc", default=str(A.DEFAULTS["tc"]))
    ap.add_argument("--sk", default=str(A.DEFAULTS["sk"]))
    ap.add_argument("--dc", default=str(A.DEFAULTS["dc"]))
    ap.add_argument("--dp", default=str(A.DEFAULTS.get("dp") or
                    (Path(A.DEFAULTS["tc"]).parent / "rnd-computational-biology-oncology-data-products")),
                    help="data-products checkout (reads its root catalog.json for the Coverage tab)")
    ap.add_argument("--out", default=str(HOME / "dev/framework-runs/architecture-explorer/framework_dashboard.html"))
    ap.add_argument("--json", default=str(HOME / "dev/framework-runs/architecture-explorer/framework_dashboard.json"))
    ap.add_argument("--no-compute-health", action="store_true", help="load health JSON instead of recomputing")
    ap.add_argument("--check", action="store_true",
                    help="CI drift-guard: recompute and fail (exit 1) if the committed JSON is stale; writes nothing")
    args = ap.parse_args()

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    health = compute_or_load_health(Path(args.tc), out_dir, prefer_compute=not args.no_compute_health)
    hpath = out_dir / "health_current.json"
    graph = A.build(Path(args.tc), Path(args.sk), Path(args.dc),
                    health_json_path=(hpath if hpath.exists() else None))
    graph = merge(graph, health)
    graph["coverage"] = load_coverage(Path(args.dp))  # OUTPUT layer (registry catalog.json)

    def _stable(gr):
        # strip volatile fields so --check compares structure/wiring, not timestamps/shas/health-gen-time
        g2 = json.loads(json.dumps(gr, default=str))
        for k in ("generated_at", "root_shas", "health_overlay_at", "health", "coverage"):
            g2.pop(k, None)  # health + coverage are time-varying snapshots (own regen cadence); guard WIRING only
        return json.dumps(g2, sort_keys=True, separators=(",", ":"))

    if args.check:
        import sys
        p = Path(args.json)
        if not p.exists():
            print(f"  MISSING {p.name} — run without --check to generate.", file=sys.stderr)
            sys.exit(1)
        try:
            prior = json.loads(p.read_text())
        except Exception as e:
            print(f"  UNREADABLE {p.name}: {e}", file=sys.stderr)
            sys.exit(1)
        if _stable(prior) != _stable(graph):
            print(f"  STALE {p.name} — committed dashboard differs from computed wiring/health; "
                  f"regenerate with: python3 build_unified_dashboard.py", file=sys.stderr)
            sys.exit(1)
        print(f"  OK {p.name} (fresh — wiring + health match on-disk)")
        sys.exit(0)

    Path(args.json).write_text(json.dumps(graph, separators=(",", ":")))
    Path(args.out).write_text(render_html(graph))

    s = graph["summary"]
    hs = (graph.get("health") or {}).get("summary", {})
    import os
    print(f"\n✓ UNIFIED dashboard: {s['n_skills']} skills · {s['n_cards']} cards · "
          f"{s['n_datasets']} datasets · {s['n_resolvers']} resolvers")
    if hs:
        print(f"  health: {hs.get('verdict_tally')} · {hs.get('n_drift_flags')} drift ({hs.get('n_error_drift')} error)")
    cv = graph.get("coverage")
    if cv:
        cs = cv["summary"]
        print(f"  coverage: {cs.get('n_entries')} outputs · {cs.get('n_cells')} cells "
              f"({cs.get('n_cells_governed')} gov / {cs.get('n_cells_exploratory_only')} exp-only) · "
              f"cards fired governed {cs.get('n_cards_fired_governed')} "
              f"(+{cs.get('n_cards_fired_exploratory_only')} exploratory-only)")
    print(f"  HTML → {args.out}  ({os.path.getsize(args.out)//1024} KB)")


if __name__ == "__main__":
    main()
