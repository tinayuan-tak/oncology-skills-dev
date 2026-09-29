#!/usr/bin/env python3
"""build_living_doc.py — generate the Framework Atlas.

A SUPERSET of the base wiring/health/coverage build: composes the existing wiring graph
(build_architecture_explorer.build) + health + output-registry coverage
(build_unified_dashboard — the internal module name; the product-facing surface this repo
ships is the Framework Atlas), then ATTACHES three sections — concepts, gaps, narrative — and a
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
    from . import concepts as _concepts
    from . import flow as _flow
    from . import gaps as _gaps
    from . import glossary as _glossary
    from . import narrative as _narrative
    from . import product_page as _product
    from .render_living import render_html
except Exception:  # pragma: no cover - bare-path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import concepts as _concepts  # type: ignore
    import flow as _flow  # type: ignore
    import gaps as _gaps  # type: ignore
    import glossary as _glossary  # type: ignore
    import narrative as _narrative  # type: ignore
    import product_page as _product  # type: ignore
    from render_living import render_html  # type: ignore

import yaml  # noqa: E402  (pyyaml; used for the axis registry the product page joins)

# The exemplar subskill the product page defaults to (the render layer's selector opens here).
# The FULL product-page roster is now enumerated from the wiring graph's skill set at build time
# (see assemble → _product_roster) rather than a hardcoded list, so a skill added to the framework
# gets a product page automatically. This constant is only the render default + a fallback.
_PRODUCT_SKILLS = ("tumor-presence",)


def _product_roster(graph: dict) -> tuple[str, ...]:
    """The full product-page roster: every skill the wiring graph knows about, sorted. Each page
    is target-invariant, so covering the whole roster is a data enumeration, not new machinery.
    Falls back to the exemplar tuple if the graph carries no skills (shouldn't happen live)."""
    roster = tuple(sorted((graph.get("skills") or {}).keys()))
    return roster or _PRODUCT_SKILLS


HOME = Path.home()
DEFAULT_JSON = _ARCH.parent.parent / "health" / "framework_atlas.json"  # <tc>/health/framework_atlas.json
DEFAULT_HTML = _ARCH.parent.parent / "health" / "framework_atlas.html"
DEFAULT_PRODUCT_DIR = _ARCH.parent.parent / "health" / "product"  # <tc>/health/product/<skill>.html


def export_product_pages(graph: dict, product_dir: Path, skills: list[str] | None = None) -> list[Path]:
    """Write one standalone ``health/product/<skill>.html`` per skill from the committed graph's
    ``product_page`` block (dependency-light, CI-safe — reads only the committed artifact, no
    siblings). ``skills=None`` → the whole built roster. Returns the paths written."""
    try:
        from .render_living import render_product_page_standalone
    except Exception:  # pragma: no cover - bare-path fallback (matches sibling living modules)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from render_living import render_product_page_standalone  # type: ignore

    pp = graph.get("product_page") or {}
    built = pp.get("skills") or {}
    want = skills if skills is not None else sorted(built)
    product_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for skill in want:
        if skill not in built:
            raise KeyError(f"skill {skill!r} not in committed product_page (built: {sorted(built)})")
        out = product_dir / f"{skill}.html"
        out.write_text(render_product_page_standalone(graph, skill))
        written.append(out)
    return written


def assemble(tc: Path, sk: Path, dc: Path, dp: Path, out_dir: Path, compute_health: bool = True) -> dict:
    """Full build (needs siblings)."""
    health = UD.compute_or_load_health(tc, out_dir, prefer_compute=compute_health)
    hpath = out_dir / "health_current.json"
    graph = A.build(tc, sk, dc, health_json_path=(hpath if hpath.exists() else None))
    graph = UD.merge(graph, health)
    graph["coverage"] = UD.load_coverage(dp)

    roots = {"target_contracts": str(tc), "skills": str(sk), "data_catalog": str(dc), "data_products": str(dp)}
    # order matters: glossary needs the wiring; concepts/gaps/narrative are independent
    graph["glossary"] = _glossary.build_glossary(graph, roots)
    graph["concepts"] = _concepts.build_concepts(graph, roots)
    graph["flow"] = _flow.build_flow(graph)  # needs concepts + glossary
    graph["gaps"] = _gaps.build_gaps(graph, roots)
    graph["narrative"] = _narrative.build_narrative(roots)
    # product page: the per-subskill five-panel view. Needs the wiring graph + the live health
    # overlay + the coverage ledgers (read from tc) + the axis registry; the ladder / code-map
    # shims read the skills sibling (sk). Attached after everything it joins is in place.
    axes_registry = _load_axes(tc)
    graph["product_page"] = _product.build_product_pages(
        graph, health, axes_registry, tc_root=tc, sk_root=sk, skills=_product_roster(graph)
    )
    graph["framework_atlas_version"] = "1.0.0"
    return graph


def _load_axes(tc: Path) -> dict:
    """Parse the target-profiling axis registry (question hierarchies + per-question risk_category)."""
    try:
        return yaml.safe_load((Path(tc) / "vocabularies" / "target_profiling_axes.yaml").read_text()) or {}
    except Exception:
        return {}


def stable_projection(graph: dict) -> str:
    """The drift-guarded projection for --check: WIRING + CONCEPTS structure only. Strip
    time-varying snapshots (health, coverage, gaps, timestamps, shas) and the checkout roots.

    `roots` is the absolute path of each sibling checkout the build ran from, so leaving it in
    the basis made the guard's verdict depend on WHERE it ran — the same defect already fixed
    for per-skill `md_path` below, one field over. It cannot be fixed the same way: `md_path`
    was reduced to its basename because a skill md rename IS wiring, but a worktree directory
    is named `<repo>__<branch>`, so basenaming a root still differs between the primary
    checkout and every worktree. Repo IDENTITY is already carried by `root_shas`, which this
    projection strips as volatile — so `roots` is pure provenance and is dropped outright."""
    g2 = json.loads(json.dumps(graph, default=str))
    for k in (
        "generated_at",
        "roots",
        "root_shas",
        "health_overlay_at",
        "health",
        "coverage",
        "gaps",
        "narrative",
        "glossary",
    ):
        g2.pop(k, None)
    # Concepts: guard the contract-derived STRUCTURE only. The example VALUES and inventory
    # counts are harvested live from the sibling repos (a manifest's git_commit, an evidence
    # package's generated_by SHA / package_id, per-type file counts) and move whenever a sibling
    # advances — NOT a target-contracts wiring change. Reduce each concept to its skeleton so
    # --check tracks structure, not sibling churn (avoids false-positive STALE).
    for c in g2.get("concepts") or []:
        ex = c.get("example") or {}
        c["example"] = {"resolved": ex.get("resolved"), "field_keys": sorted((ex.get("fields") or {}).keys())}
        di = c.get("defined_in") or {}
        c["defined_in"] = {"repo": di.get("repo"), "glob": di.get("glob"), "resolved": di.get("count") not in (None, 0)}
        sch = c.get("schema") or {}
        c["schema"] = {
            "path": sch.get("path"),
            "required": sorted(sch.get("required") or []),
            "field_names": sorted(f.get("name") for f in (sch.get("fields") or []) if f.get("name")),
            "error": bool(sch.get("error")),
        }
    # Flow: schematics embed live example values too; keep only ids + layout + schematic presence.
    for lv in g2.get("flow", {}).get("levels") or []:
        for vol in ("stages", "center", "schematic", "lane", "subtitle"):
            lv.pop(vol, None)
    # Skills: the same rule as concepts, which this projection was not applying. Each entry's
    # WIRING (cards_used, rules_scope, measurement_types_pulled, gates, fanout, synthesis, ...) is
    # what the guard exists to protect; four fields are pure sibling churn and made --check cry wolf:
    #   version       bumps on EVERY skills-repo landing, so the committed atlas went stale minutes
    #                 after any regen and only a target-contracts PR could clear it. Observed live:
    #                 two consecutive builds disagreed on immune-context 1.9.0 vs 1.9.1 because
    #                 another session landed a skills PR in between.
    #   status/health the live health overlay — already stripped at top level as time-varying, but
    #                 also merged per-skill, so stripping it there only was not stripping it.
    #   md_path       an ABSOLUTE path, so --check disagreed with itself between a /tmp worktree and
    #                 the primary checkout. Reduced to the basename rather than dropped: a skill's
    #                 md being renamed IS a wiring change, its checkout root is not.
    for s in _skill_entries(g2):
        for vol in ("version", "status", "health"):
            s.pop(vol, None)
        if s.get("md_path"):
            s["md_path"] = Path(str(s["md_path"])).name
    return json.dumps(g2, sort_keys=True, separators=(",", ":"))


def _skill_entries(graph: dict) -> list[dict]:
    """graph['skills'] is a dict keyed by skill name; tolerate a list in case that ever changes."""
    skills = graph.get("skills") or {}
    seq = skills.values() if isinstance(skills, dict) else skills
    return [s for s in seq if isinstance(s, dict)]


def self_check(graph: dict) -> list[str]:
    """CI-safe internal-consistency checks on the committed JSON (no siblings needed)."""
    errs: list[str] = []
    # concepts: every type resolved a schema + example + count
    concepts = graph.get("concepts") or []
    if not concepts:
        errs.append("no concepts present")
    # NOTE: a valid committed artifact requires generate to run with ALL FOUR siblings present
    # (dc/sk/dp) — the manifest/skill schemas + evidence-package inventory come from them. The
    # schema/count checks below assume that; if you regenerate in a partial env they will (correctly)
    # flag the resulting artifact as incomplete rather than bless a half-harvested one.
    for c in concepts:
        cid = c.get("id", "?")
        sch = c.get("schema") or {}
        if sch.get("error"):
            errs.append(f"concept {cid}: schema unresolved ({sch['error']})")
        if not c.get("narration"):
            errs.append(f"concept {cid}: missing narration")
        if (c.get("defined_in") or {}).get("count") in (None, 0):
            errs.append(
                f"concept {cid}: inventory count is {c.get('defined_in', {}).get('count')} "
                "(regenerate with all four sibling repos present)"
            )
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
    # product page: five panels present + a spine that actually resolves verdicts
    errs += product_page_errors(graph)
    return errs


def product_page_errors(graph: dict) -> list[str]:
    """Structural consistency of the committed product_page block, over the WHOLE roster
    (CI-safe, no siblings).

    Guards SHAPE, not drift: the ladder/code-map ``errors`` a block carries are surfaced findings
    (e.g. a rule the skill's ladder references that the atlas has not yet regenerated), not build
    failures, so they are deliberately NOT asserted here.

    What must hold on any committed artifact, for EVERY skill in the roster — spanning the three
    shape buckets (python-ladder, resolver-backed, and no-verdict-source descriptive/support/
    gateless skills):

      * the block exists, the default skill is present, every skill block carries the five panels;
      * a VERDICT-BEARING block (``verdict_source`` set AND a non-empty spine) resolves ≥1 verdict
        token per spine card, all within the pinned enum when one is present;
      * a NO-VERDICT-SOURCE block carries an EMPTY spine — a gateless skill must never fabricate a
        verdict spine (the "no fabricated green" invariant).

    (SK#2091 dropped a fourth clause — "every optionality lane is verdict-inert" — which asserted a
    hardcoded literal and so could never fail.)
    """
    errs: list[str] = []
    pp = graph.get("product_page")
    if not pp:
        errs.append("no product_page present")
        return errs
    skills = pp.get("skills") or {}
    if not skills:
        errs.append("product_page has no skills")
    default = pp.get("default_skill")
    if default not in skills:
        errs.append(f"product_page default_skill {default!r} not among built skills {sorted(skills)}")
    panels_expected = {"spine", "card_drilldown", "optionality", "rollup", "cards_questions"}
    for name, block in skills.items():
        panels = block.get("panels") or {}
        missing = panels_expected - set(panels)
        if missing:
            errs.append(f"product_page[{name}] missing panels: {sorted(missing)}")
            continue
        spine = panels["spine"]
        spine_cards = spine.get("cards") or []
        vsource = (block.get("ladder") or {}).get("verdict_source") or block.get("verdict_source")
        enum = set(spine.get("verdict_enum") or [])
        if vsource:
            # verdict-bearing shape: every spine card must resolve a pinned verdict token.
            for row in spine_cards:
                rules = row.get("rules") or []
                toks = {v for r in rules for v in (r.get("verdicts") or [])}
                if not rules:
                    errs.append(f"product_page[{name}] spine card {row.get('card_id')} has no rules")
                elif not toks:
                    errs.append(f"product_page[{name}] spine card {row.get('card_id')} resolves no verdict token")
                elif enum and not (toks <= enum):
                    errs.append(
                        f"product_page[{name}] spine card {row.get('card_id')} verdicts "
                        f"{sorted(toks - enum)} not in the pinned enum"
                    )
        else:
            # no-verdict-source shape: a gateless / descriptive / support skill. It must degrade to
            # an EMPTY spine — never fabricate a verdict-bearing card where the skill emits none.
            if spine_cards:
                errs.append(
                    f"product_page[{name}] has no verdict source but its spine lists "
                    f"{len(spine_cards)} card(s) — a fabricated verdict spine"
                )
        # SK#2091: the "every optionality lane is tagged verdict_inert" error was REMOVED. The tag is
        # a hardcoded True in product_page._OPTIONALITY_LANES, so the check read back its own literal
        # and could never fail — a vacuous gate, and one keyed on verdict-inertness, which is no
        # longer a proof obligation here. The tag survives as a rendered display chip.
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
    need(
        "measurement_type",
        {c.get("measurement_type") for c in cards.values() if c.get("measurement_type")},
        "card.measurement_type",
    )
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
    ap.add_argument(
        "--dp", default=str(Path(A.DEFAULTS["tc"]).parent / "rnd-computational-biology-oncology-data-products")
    )
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--out", default=str(DEFAULT_HTML))
    ap.add_argument("--no-compute-health", action="store_true")
    ap.add_argument(
        "--check",
        action="store_true",
        help="local drift-guard: recompute (needs siblings), fail if committed JSON stale",
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: validate the committed JSON's internal consistency (no siblings)",
    )
    ap.add_argument(
        "--skill",
        default=None,
        help="standalone export: render one skill's product page from the committed JSON to "
        "health/product/<skill>.html (no siblings needed)",
    )
    ap.add_argument(
        "--all-skills",
        action="store_true",
        help="standalone export: render EVERY roster skill's product page to health/product/ "
        "(the atlas-product target; reads the committed JSON, no siblings needed)",
    )
    ap.add_argument("--product-dir", default=str(DEFAULT_PRODUCT_DIR))
    args = ap.parse_args(argv)

    if args.skill or args.all_skills:
        p = Path(args.json)
        if not p.exists():
            print(f"  MISSING {p} — generate the atlas first (make atlas).", file=sys.stderr)
            return 1
        try:
            graph = json.loads(p.read_text())
        except Exception as e:
            print(f"  UNREADABLE {p}: {e}", file=sys.stderr)
            return 1
        try:
            written = export_product_pages(
                graph, Path(args.product_dir), skills=None if args.all_skills else [args.skill]
            )
        except KeyError as e:
            print(f"  {e}", file=sys.stderr)
            return 1
        print(f"  ✓ product page(s) → {args.product_dir} ({len(written)} file(s))")
        for w in written:
            print(f"      {w.name}")
        return 0

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
        print(
            f"  OK {p.name} (self-consistent: "
            f"{len(graph.get('concepts') or [])} concepts · "
            f"{(graph.get('gaps') or {}).get('summary', {}).get('n_gaps', 0)} gaps · "
            f"glossary complete)"
        )
        return 0

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = assemble(
        Path(args.tc), Path(args.sk), Path(args.dc), Path(args.dp), out_dir, compute_health=not args.no_compute_health
    )

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
            print(
                f"  STALE {p.name} — committed living doc differs from computed wiring/concepts; "
                f"regenerate with: python3 -m validators.architecture_dashboard.living.build_living_doc",
                file=sys.stderr,
            )
            return 1
        print(f"  OK {p.name} (fresh — wiring + concepts match on-disk)")
        return 0

    Path(args.json).write_text(json.dumps(graph, separators=(",", ":")))
    Path(args.out).write_text(render_html(graph))
    g = graph["gaps"]["summary"]
    print(
        f"\n✓ Framework Atlas: {len(graph['concepts'])} component types · "
        f"{g['n_gaps']} gaps ({g['n_error']} error / {g['n_warn']} warn / {g['n_info']} info) · "
        f"{graph['narrative']['n_docs']} docs · glossary "
        f"{sum(len(v) for v in graph['glossary'].values())} tokens"
    )
    print(f"  validators run: {', '.join(graph['gaps']['validators_run']) or '(none)'}")
    import os

    print(f"  JSON → {args.json}")
    print(f"  HTML → {args.out}  ({os.path.getsize(args.out) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
