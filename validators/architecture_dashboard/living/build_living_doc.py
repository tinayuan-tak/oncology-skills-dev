#!/usr/bin/env python3
"""build_living_doc.py — generate the Framework Atlas.

A SUPERSET of the unified dashboard: composes the existing wiring graph
(build_architecture_explorer.build) + health + output-registry coverage
(build_unified_dashboard), then ATTACHES three sections — concepts, gaps, narrative — and a
glossary (the legibility layer). Renders one self-contained HTML with three new tabs, and
writes a committed JSON feed guarded two ways:

  generate (default) : write health/framework_atlas.{json,html}
  --check            : local guard (siblings present) — recompute, fail if committed JSON is
                       stale on WIRING+CONCEPTS structure (gaps/health/coverage are snapshots).
  --self-check       : CI-safe (no siblings) — validate the committed JSON's internal
                       consistency alone (concepts resolved, gaps tally == list, glossary total).

stdlib + pyyaml + json; bare-python (no pixi). Run:
  python3 -m validators.architecture_dashboard.living.build_living_doc [--check|--self-check]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

# sibling dashboard modules import each other by bare name → put the arch dir on the path.
_ARCH = Path(__file__).resolve().parent.parent
if str(_ARCH) not in sys.path:
    sys.path.insert(0, str(_ARCH))

import build_architecture_explorer as A  # noqa: E402
import build_unified_dashboard as UD  # noqa: E402

# living modules — work both as a package (-m) and as bare imports
try:
    from . import (concepts as _concepts, gaps as _gaps, narrative as _narrative,
                   glossary as _glossary, flow as _flow)
    from .render_living import render_html
except Exception:  # pragma: no cover - bare-path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import concepts as _concepts  # type: ignore
    import gaps as _gaps  # type: ignore
    import narrative as _narrative  # type: ignore
    import glossary as _glossary  # type: ignore
    import flow as _flow  # type: ignore
    from render_living import render_html  # type: ignore

HOME = Path.home()
DEFAULT_JSON = _ARCH.parent.parent / "health" / "framework_atlas.json"   # <tc>/health/framework_atlas.json
DEFAULT_HTML = _ARCH.parent.parent / "health" / "framework_atlas.html"


def assemble(tc: Path, sk: Path, dc: Path, dp: Path, out_dir: Path,
             compute_health: bool = True) -> dict:
    """Full build (needs siblings)."""
    health = UD.compute_or_load_health(tc, out_dir, prefer_compute=compute_health)
    hpath = out_dir / "health_current.json"
    graph = A.build(tc, sk, dc, health_json_path=(hpath if hpath.exists() else None))
    graph = UD.merge(graph, health)
    graph["coverage"] = UD.load_coverage(dp)

    roots = {"target_contracts": str(tc), "skills": str(sk),
             "data_catalog": str(dc), "data_products": str(dp)}
    # order matters: glossary needs the wiring; concepts/gaps/narrative are independent
    graph["glossary"] = _glossary.build_glossary(graph, roots)
    graph["concepts"] = _concepts.build_concepts(graph, roots)
    graph["flow"] = _flow.build_flow(graph)          # needs concepts + glossary
    graph["gaps"] = _gaps.build_gaps(graph, roots)
    graph["narrative"] = _narrative.build_narrative(roots)
    graph["framework_atlas_version"] = "1.0.0"
    return graph


def stable_projection(graph: dict) -> str:
    """The drift-guarded projection for --check: WIRING + CONCEPTS structure only. Strip
    time-varying snapshots (health, coverage, gaps, timestamps, shas)."""
    g2 = json.loads(json.dumps(graph, default=str))
    for k in ("generated_at", "root_shas", "health_overlay_at", "health", "coverage",
              "gaps", "narrative", "glossary"):
        g2.pop(k, None)
    # concepts: keep structure (ids, schema required-sets, counts, example source_path), drop
    # nothing volatile here — concept shape is contract-derived and should be stable.
    return json.dumps(g2, sort_keys=True, separators=(",", ":"))


def self_check(graph: dict) -> list[str]:
    """CI-safe internal-consistency checks on the committed JSON (no siblings needed)."""
    errs: list[str] = []
    # concepts: every type resolved a schema + example + count
    concepts = graph.get("concepts") or []
    if not concepts:
        errs.append("no concepts present")
    for c in concepts:
        cid = c.get("id", "?")
        sch = c.get("schema") or {}
        if sch.get("error"):
            errs.append(f"concept {cid}: schema unresolved ({sch['error']})")
        if not c.get("narration"):
            errs.append(f"concept {cid}: missing narration")
        if (c.get("defined_in") or {}).get("count") in (None, 0):
            errs.append(f"concept {cid}: inventory count is {c.get('defined_in', {}).get('count')}")
    # gaps: tally consistency
    G = graph.get("gaps") or {}
    items = G.get("items") or []
    s = G.get("summary") or {}
    if s.get("n_gaps") != len(items):
        errs.append(f"gaps summary n_gaps={s.get('n_gaps')} != {len(items)} items")
    tally = {"error": 0, "warn": 0, "info": 0}
    valid_sev = set(tally)
    for r in items:
        if r.get("severity") not in valid_sev:
            errs.append(f"gap has invalid severity: {r.get('severity')}")
        else:
            tally[r["severity"]] += 1
    for sev, n in tally.items():
        if s.get(f"n_{sev}") != n:
            errs.append(f"gaps n_{sev}={s.get(f'n_{sev}')} != counted {n}")
    # flow: levels present + worked-example tokens still exist in the contracts
    flow = graph.get("flow") or {}
    levels = flow.get("levels") or []
    if not levels:
        errs.append("no flow levels present")
    n_schem = 0
    for lv in levels:
        if not (lv.get("stages") or lv.get("center")):
            errs.append(f"flow level {lv.get('id')} has no stages/center")
        sc = lv.get("schematic")
        if sc:
            n_schem += 1
            if "«" in sc or "»" in sc:
                errs.append(f"flow level {lv.get('id')} schematic has unfilled «token» placeholder")
    if levels and n_schem < 5:
        errs.append(f"expected >=5 wire schematics, found {n_schem}")
    try:  # flow_token_errors is defined in flow.py; import lazily to keep self-check standalone
        try:
            from . import flow as _fl
        except Exception:
            import flow as _fl  # type: ignore
        errs += _fl.flow_token_errors(graph)
    except Exception as e:
        errs.append(f"flow token check unavailable: {e}")

    # glossary: coverage over the graph-derived token sets (legibility contract)
    errs += glossary_coverage_errors(graph)
    return errs


def glossary_coverage_errors(graph: dict) -> list[str]:
    """The baked-in legibility guarantee: every machine token the doc can surface is glossed.
    Checked against the SAME graph-derived sets build_glossary indexes, so a future code path
    that surfaces an un-modeled token kind fails here."""
    errs: list[str] = []
    gl = graph.get("glossary") or {}

    def need(kind, tokens, where):
        have = set((gl.get(kind) or {}).keys())
        for t in tokens:
            if t and t not in have:
                errs.append(f"glossary[{kind}] missing '{t}' (surfaced in {where})")

    cards = graph.get("cards") or {}
    need("card", cards.keys(), "cards")
    need("measurement_type", {c.get("measurement_type") for c in cards.values() if c.get("measurement_type")},
         "card.measurement_type")
    rule_ids, verdicts = set(), set()
    for c in cards.values():
        for r in c.get("rules") or []:
            if r.get("rule_id"):
                rule_ids.add(r["rule_id"])
    for gate, r in (graph.get("resolvers") or {}).items():
        need("gate", [gate], "resolvers")
        for v in r.get("verdicts") or []:
            if v.get("verdict"):
                verdicts.add(v["verdict"])
    need("rule", rule_ids, "interpretation-rules")
    need("verdict", verdicts, "resolvers")
    # gaps + concepts enums
    need("gap_type", {r.get("gap_type") for r in (graph.get("gaps") or {}).get("items") or []}, "gaps")
    need("severity", {r.get("severity") for r in (graph.get("gaps") or {}).get("items") or []}, "gaps")
    need("component_type", {c.get("id") for c in graph.get("concepts") or []}, "concepts")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the Framework Atlas.")
    ap.add_argument("--tc", default=str(A.DEFAULTS["tc"]))
    ap.add_argument("--sk", default=str(A.DEFAULTS["sk"]))
    ap.add_argument("--dc", default=str(A.DEFAULTS["dc"]))
    ap.add_argument("--dp", default=str(Path(A.DEFAULTS["tc"]).parent /
                    "rnd-computational-biology-oncology-data-products"))
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--out", default=str(DEFAULT_HTML))
    ap.add_argument("--no-compute-health", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="local drift-guard: recompute (needs siblings), fail if committed JSON stale")
    ap.add_argument("--self-check", action="store_true",
                    help="CI-safe: validate the committed JSON's internal consistency (no siblings)")
    args = ap.parse_args(argv)

    if args.self_check:
        p = Path(args.json)
        if not p.exists():
            print(f"  MISSING {p} — generate it first.", file=sys.stderr)
            return 1
        try:
            graph = json.loads(p.read_text())
        except Exception as e:
            print(f"  UNREADABLE {p}: {e}", file=sys.stderr)
            return 1
        errs = self_check(graph)
        if errs:
            print(f"  SELF-CHECK FAILED ({len(errs)}):", file=sys.stderr)
            for e in errs[:40]:
                print(f"    - {e}", file=sys.stderr)
            return 1
        print(f"  OK {p.name} (self-consistent: "
              f"{len(graph.get('concepts') or [])} concepts · "
              f"{(graph.get('gaps') or {}).get('summary', {}).get('n_gaps', 0)} gaps · "
              f"glossary complete)")
        return 0

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = assemble(Path(args.tc), Path(args.sk), Path(args.dc), Path(args.dp), out_dir,
                     compute_health=not args.no_compute_health)

    if args.check:
        p = Path(args.json)
        if not p.exists():
            print(f"  MISSING {p.name} — run without --check to generate.", file=sys.stderr)
            return 1
        try:
            prior = json.loads(p.read_text())
        except Exception as e:
            print(f"  UNREADABLE {p.name}: {e}", file=sys.stderr)
            return 1
        if stable_projection(prior) != stable_projection(graph):
            print(f"  STALE {p.name} — committed living doc differs from computed wiring/concepts; "
                  f"regenerate with: python3 -m validators.architecture_dashboard.living.build_living_doc",
                  file=sys.stderr)
            return 1
        print(f"  OK {p.name} (fresh — wiring + concepts match on-disk)")
        return 0

    Path(args.json).write_text(json.dumps(graph, separators=(",", ":")))
    Path(args.out).write_text(render_html(graph))
    g = graph["gaps"]["summary"]
    print(f"\n✓ Framework Atlas: {len(graph['concepts'])} component types · "
          f"{g['n_gaps']} gaps ({g['n_error']} error / {g['n_warn']} warn / {g['n_info']} info) · "
          f"{graph['narrative']['n_docs']} docs · glossary "
          f"{sum(len(v) for v in graph['glossary'].values())} tokens")
    print(f"  validators run: {', '.join(graph['gaps']['validators_run']) or '(none)'}")
    import os
    print(f"  JSON → {args.json}")
    print(f"  HTML → {args.out}  ({os.path.getsize(args.out)//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
