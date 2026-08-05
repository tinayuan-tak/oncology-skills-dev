#!/usr/bin/env python3
"""catalog_query CLI — query, explore, and understand the data-catalog.

READ-ONLY over the data-catalog manifest YAMLs. No S3, no AWS profile, no
writes — a pure function of the on-disk catalog. Four subcommands:

    search    which dataset/manifest covers a need? (facet filter + keyword)
    describe  everything about ONE manifest (s3_uri, schema, sort key, lineage)
    lineage   walk derived_from (upstream) / cited_by (downstream)
    audit     coverage gaps, stale/legacy references, orphans

Text output by default; --json for downstream/machine consumers.

Usage:
    python -m methods.catalog_query.cli search "CPTAC phospho" --data-subject tumor
    python -m methods.catalog_query.cli describe biogrid-physical-interactions-per-gene-v1
    python -m methods.catalog_query.cli lineage tcga-gdc-dr45-0 --direction downstream
    python -m methods.catalog_query.cli audit --coverage-gaps
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .read import DATA_CATALOG, TARGET_CONTRACTS, load_catalog


# ---------------------------------------------------------------------------
# text renderers (mirror the scoring/emit language of the source of truth)
# ---------------------------------------------------------------------------


def _render_search(records) -> str:
    if not records:
        return "No manifests match."
    lines = [f"{len(records)} manifest(s) match:\n"]
    for r in records:
        sor = "" if r.type == "derived" else ("  [SoR]" if r.system_of_record else "  [cache]")
        subj = f"  ({r.data_subject})" if r.data_subject else ""
        lines.append(f"  {r.id}{subj}{sor}")
        desc = r.description.strip().splitlines()[0] if r.description.strip() else ""
        if desc:
            lines.append(f"      {desc[:110]}")
    return "\n".join(lines)


def _render_describe(d: dict) -> str:
    L = [f"{d['id']}   [{d['type']}]"]
    L.append(f"  s3_uri:        {d['s3_uri']}")
    if d.get("provider"):
        L.append(f"  provider:      {d['provider']}  dataset={d.get('dataset')}  version={d.get('version')}")
    if d.get("data_subject"):
        L.append(f"  data_subject:  {d['data_subject']}")
    if d.get("system_of_record") is not None:
        L.append(f"  system_of_record: {d['system_of_record']}")
    if d.get("size_bytes"):
        L.append(f"  size_bytes:    {d['size_bytes']:,}")
    if d.get("license"):
        L.append(f"  license:       {d['license'].strip().splitlines()[0][:100]}")
    if d.get("file_categories"):
        L.append(f"  file categories: {', '.join(d['file_categories'])}")
    if d.get("parquet_schema"):
        cols = ", ".join(f"{c.get('name')}:{c.get('type')}" for c in d["parquet_schema"])
        L.append(f"  parquet_schema: {cols}")
    if d.get("query_optimization"):
        qo = d["query_optimization"]
        L.append(f"  query_optimization: sort={qo.get('sort_columns')} primary_filter={qo.get('primary_filter_column')}")
    if d.get("derived_from"):
        L.append(f"  derived_from:  {', '.join(d['derived_from'])}")
    if d.get("cited_by"):
        L.append(f"  cited_by:      {', '.join(d['cited_by'])}")
    if d.get("cited_by_subgroup_catalogs"):
        L.append(f"  cited_by (subgroup-catalogs): {', '.join(d['cited_by_subgroup_catalogs'])}")
    if d.get("consumed_by_products"):
        L.append(f"  consumed_by_products: {', '.join(d['consumed_by_products'])}")
    desc = (d.get("description") or "").strip()
    if desc:
        L.append(f"\n  {desc.splitlines()[0][:200]}")
    L.append(f"\n  manifest: {d['manifest_path']}")
    return "\n".join(L)


def _render_lineage_tree(node: dict, prefix: str = "", is_last: bool = True) -> list[str]:
    connector = "└─ " if is_last else "├─ "
    tag = ""
    if node.get("missing"):
        tag = "  (MISSING)"
    elif node.get("truncated"):
        tag = "  (…cycle)"
    lines = [f"{prefix}{connector}{node['id']}{tag}"]
    children = node.get("children", [])
    child_prefix = prefix + ("   " if is_last else "│  ")
    for i, ch in enumerate(children):
        lines += _render_lineage_tree(ch, child_prefix, i == len(children) - 1)
    return lines


def _render_lineage(result: dict) -> str:
    L = [f"Lineage for {result['id']}:"]
    if "upstream" in result:
        L.append("\n  ▲ upstream (derived_from):")
        up = result["upstream"]
        if not up.get("children"):
            L.append("     (none — a source-release / root)")
        else:
            L += ["   " + s for s in _render_lineage_tree(up)]
    if "downstream" in result:
        L.append("\n  ▼ downstream (cited_by):")
        dn = result["downstream"]
        if not dn.get("children"):
            L.append("     (none — nothing derives from or cites this)")
        else:
            L += ["   " + s for s in _render_lineage_tree(dn)]
    return "\n".join(L)


def _render_audit(a: dict, sections: set[str]) -> str:
    L = []
    c = a["counts"]
    L.append(
        f"Catalog: {c['sources']} sources · {c['derived']} derived · "
        f"{c['indication_configs']} indication-configs · {c['subgroup_catalogs']} subgroup-catalogs"
    )
    if "coverage-gaps" in sections:
        gaps = a["dge_coverage_gaps"]
        L.append(f"\nDGE tumor-vs-normal coverage gaps ({len(gaps)} indication-configs lack a "
                 f"*-dge-tumor-vs-normal-sensitivity-v* product):")
        L.append("  " + (", ".join(gaps) if gaps else "(none — all configured indications covered)"))
    if "uncited" in sections:
        u = a["uncited_sources"]
        L.append(f"\nUncited source-releases ({len(u)} — no derived_from / product / subgroup-catalog "
                 f"citation). NOTE: not 'unused' — reference/annotation data is often read by direct "
                 f"S3 path. Citation-hygiene candidates, not dead data:")
        L.append("  " + (", ".join(u) if u else "(none)"))
    if "stale" in sections:
        s = a["superseded_still_present"]
        L.append(f"\nSuperseded-but-still-present manifests ({len(s)}):")
        L.append("  " + ("\n  ".join(s) if s else "(none)"))
    return "\n".join(L)


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # Common flags on a parent parser so they work BEFORE or AFTER the
    # subcommand (argparse routes post-subcommand flags to the subparser; a
    # top-level-only --json would silently fail on `describe <id> --json`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable JSON output")
    common.add_argument("--catalog-root", type=Path, default=DATA_CATALOG,
                        help="path to the data-catalog repo (default: the standard checkout)")
    common.add_argument("--contracts-root", type=Path, default=TARGET_CONTRACTS,
                        help="path to target-contracts (for products.yaml consumer map)")

    # Flags live ONLY on the subparsers (git-style: `catalog_query describe X --json`).
    # Putting them on the top-level parser too would let the subparser's default
    # clobber a pre-subcommand value — one home per dest avoids that.
    p = argparse.ArgumentParser(prog="catalog_query", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="find manifests by keyword + facets", parents=[common])
    s.add_argument("query", nargs="?", default=None, help="keyword (id/description/dataset/provider)")
    s.add_argument("--provider")
    s.add_argument("--data-subject", choices=["cell-line", "tumor", "rwd", "reference-data"])
    s.add_argument("--type", choices=["source-release", "derived"])
    s.add_argument("--category", help="a file category, e.g. mutation, expression, proteomics")
    s.add_argument("--license", help="substring match on the license field")
    sor = s.add_mutually_exclusive_group()
    sor.add_argument("--system-of-record", dest="sor", action="store_true", default=None)
    sor.add_argument("--not-system-of-record", dest="sor", action="store_false")

    d = sub.add_parser("describe", help="full detail for one manifest_id", parents=[common])
    d.add_argument("manifest_id")

    ln = sub.add_parser("lineage", help="walk derived_from / cited_by", parents=[common])
    ln.add_argument("manifest_id")
    ln.add_argument("--direction", choices=["upstream", "downstream", "both"], default="both")
    ln.add_argument("--depth", type=int, default=None)

    a = sub.add_parser("audit", help="coverage gaps, superseded, uncited sources", parents=[common])
    a.add_argument("--coverage-gaps", action="store_true")
    a.add_argument("--uncited", action="store_true", help="source-releases with no citation edge")
    a.add_argument("--stale", action="store_true", help="superseded-but-still-present manifests")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    idx = load_catalog(root=args.catalog_root, contracts_root=args.contracts_root)

    if args.command == "search":
        recs = idx.search(
            args.query, provider=args.provider, data_subject=args.data_subject,
            type=args.type, category=args.category, license=args.license,
            system_of_record=args.sor,
        )
        if args.json:
            print(json.dumps([idx.describe(r.id) for r in recs], indent=2, default=str))
        else:
            print(_render_search(recs))

    elif args.command == "describe":
        try:
            d = idx.describe(args.manifest_id)
        except KeyError:
            print(f"error: manifest {args.manifest_id!r} not found in the catalog.\n"
                  f"try:  catalog_query search {args.manifest_id.split('-')[0]!r}", file=sys.stderr)
            return 2
        print(json.dumps(d, indent=2, default=str) if args.json else _render_describe(d))

    elif args.command == "lineage":
        try:
            r = idx.lineage(args.manifest_id, direction=args.direction, depth=args.depth)
        except KeyError:
            print(f"error: manifest {args.manifest_id!r} not found in the catalog.", file=sys.stderr)
            return 2
        print(json.dumps(r, indent=2, default=str) if args.json else _render_lineage(r))

    elif args.command == "audit":
        a = idx.audit()
        if args.json:
            print(json.dumps(a, indent=2, default=str))
        else:
            # default: show everything if no section flag was passed
            sections = {k for k, on in
                        [("coverage-gaps", args.coverage_gaps), ("uncited", args.uncited),
                         ("stale", args.stale)] if on} or {"coverage-gaps", "uncited", "stale"}
            print(_render_audit(a, sections))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
