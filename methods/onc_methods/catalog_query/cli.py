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
    python -m onc_methods.catalog_query.cli search "CPTAC phospho" --data-subject tumor
    python -m onc_methods.catalog_query.cli describe biogrid-physical-interactions-per-gene-v1
    python -m onc_methods.catalog_query.cli lineage tcga-gdc-dr45-0 --direction downstream
    python -m onc_methods.catalog_query.cli audit --coverage-gaps
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


_FACET_NAMES = [
    "indications",
    "measurement_class",
    "measurement_type",
    "molecular_grain",
    "gene_key",
    "sample_type",
    "analytical_stage",
    "reference_genome",
    "license_class",
    "tissue",
    "platform",
    "treatment",
    "aggregation_recommendation",
]


def _fact_val(x):
    return x.get("value") if isinstance(x, dict) else x


def _render_facets(idx, names) -> str:
    L = []
    for n in names:
        vals = idx.facet_values(n)
        L.append(f"{n} ({len(vals)} distinct value(s)):")
        for val, cnt in vals[:40]:
            L.append(f"  {cnt:>5}  {val}")
        if not vals:
            L.append("  (none present)")
        L.append("")
    return "\n".join(L).rstrip()


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
        L.append(
            f"  query_optimization: sort={qo.get('sort_columns')} primary_filter={qo.get('primary_filter_column')}"
        )
    if d.get("enrichment"):
        parts = []
        for fname, e in d["enrichment"].items():
            val = e["value"]
            val = ",".join(str(x) for x in val) if isinstance(val, list) else str(val)
            parts.append(f"{fname}={'~' if e['source'] == 'inferred' else ''}{val}")
        L.append("  classification: " + "  ".join(parts) + "   (~ = inferred fallback, else curated)")
    if d.get("file_formats"):
        L.append(f"  file formats:  {', '.join(d['file_formats'])}")
    if d.get("pipeline"):
        pp = d["pipeline"]
        bits = [
            f"{k}={pp[k]}" for k in ("name", "aligner", "quantifier", "reference_genome", "annotation") if pp.get(k)
        ]
        if bits:
            L.append("  pipeline:      " + "  ".join(bits))
    if d.get("has_resolver_sidecar"):
        L.append(f"  resolver:      hgnc-id sidecar present (native_key={d.get('native_key_type')})")
    sc = d.get("scale") or {}
    scbits = [
        f"{k}={_fact_val(sc.get(k))}" for k in ("n_samples", "n_donors", "n_cells", "n_genes") if _fact_val(sc.get(k))
    ]
    if scbits:
        L.append("  scale:         " + "  ".join(scbits))
    if d.get("aggregation_recommendation"):
        L.append(f"  aggregation:   {d['aggregation_recommendation']}")
    prov = [x for x in (d.get("entity_purity"), d.get("annotation_provenance"), d.get("access_tier")) if x]
    if prov:
        L.append("  quality:       " + " · ".join(prov))
    if d.get("constituent_studies"):
        keys = [s.get("key") for s in d["constituent_studies"] if s.get("key")][:8]
        if keys:
            L.append(f"  studies:       {', '.join(keys)}")
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
        L.append(
            f"\nDGE tumor-vs-normal coverage gaps ({len(gaps)} indication-configs lack a "
            f"*-dge-tumor-vs-normal-sensitivity-v* product):"
        )
        L.append("  " + (", ".join(gaps) if gaps else "(none — all configured indications covered)"))
        gf = a.get("dge_coverage_gaps_by_field", [])
        L.append(
            f"\n  [field-based cross-check] indications with NO curated tumor_vs_normal_selectivity "
            f"bulk_rna product ({len(gf)}); shrinks as the classification backfill proceeds:"
        )
        L.append("  " + (", ".join(gf) if gf else "(none)"))
    if "uncited" in sections:
        u = a["uncited_sources"]
        L.append(
            f"\nUncited source-releases ({len(u)} — no derived_from / product / subgroup-catalog "
            f"citation). NOTE: not 'unused' — reference/annotation data is often read by direct "
            f"S3 path. Citation-hygiene candidates, not dead data:"
        )
        L.append("  " + (", ".join(u) if u else "(none)"))
    if "stale" in sections:
        s = a["superseded_still_present"]
        L.append(f"\nSuperseded-but-still-present manifests ({len(s)}):")
        L.append("  " + ("\n  ".join(s) if s else "(none)"))
    if "overlaps" in sections:
        ov = a.get("overlaps", {})
        L.append(
            f"\nCross-source study overlaps ({len(ov)} — same underlying study reachable via >1 "
            f"manifest; double-count risk when merging):"
        )
        if ov:
            for k in list(ov)[:20]:
                L.append(f"  {k}: {', '.join(ov[k])}")
        else:
            L.append("  (none detected on shared study keys)")
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
    common.add_argument(
        "--catalog-root",
        type=Path,
        default=DATA_CATALOG,
        help="path to the data-catalog repo (default: the standard checkout)",
    )
    common.add_argument(
        "--contracts-root",
        type=Path,
        default=TARGET_CONTRACTS,
        help="path to target-contracts (for products.yaml consumer map)",
    )

    # Flags live ONLY on the subparsers (git-style: `catalog_query describe X --json`).
    # Putting them on the top-level parser too would let the subparser's default
    # clobber a pre-subcommand value — one home per dest avoids that.
    p = argparse.ArgumentParser(prog="catalog_query", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="find manifests by keyword + facets", parents=[common])
    s.add_argument("query", nargs="?", default=None, help="keyword (id/description/dataset/provider)")
    s.add_argument("--provider")
    s.add_argument("--data-subject", choices=["cell-line", "tumor", "mixed", "rwd", "reference-data"])
    s.add_argument("--type", choices=["source-release", "derived"])
    s.add_argument("--category", help="a file category, e.g. mutation, expression, proteomics")
    s.add_argument(
        "--format",
        dest="file_format",
        action="append",
        help="file format, e.g. fastq, bam, vcf, h5ad, parquet (raw-data triage). Repeatable (OR).",
    )
    s.add_argument("--license", help="substring match on the license field")
    sor = s.add_mutually_exclusive_group()
    sor.add_argument("--system-of-record", dest="sor", action="store_true", default=None)
    sor.add_argument("--not-system-of-record", dest="sor", action="store_false")
    # Scientific facets over the merged classification view (curated block ⊕ inferred profile).
    # All are REPEATABLE (--indication A --indication B => OR within the facet); facets AND together.
    s.add_argument("--indication", action="append", help="canonical indication code, e.g. COADREAD, NSCLC, pan-cancer")
    s.add_argument(
        "--measurement-class",
        dest="measurement_class",
        action="append",
        help="modality, e.g. bulk_rna, scrna, proteomics_ms, wes, cnv, crispr_screen, drug_response, immunopeptidomics",
    )
    s.add_argument(
        "--measurement-type",
        dest="measurement_type",
        action="append",
        help="fine measurement_type registry key, e.g. tumor_vs_normal_selectivity, crispr_lof_dependency",
    )
    s.add_argument(
        "--grain",
        action="append",
        help="molecular grain: gene | transcript | single_cell | pseudobulk | bulk_sample | protein | peptide | phospho_site | region | variant_site | cohort",
    )
    s.add_argument(
        "--gene-key", dest="gene_key", action="append", help="join key: gene_symbol | hgnc_id | ensembl | uniprot | n/a"
    )
    s.add_argument(
        "--sample-type",
        dest="sample_type",
        action="append",
        help="sample material, e.g. cell-line, patient-tumor, organoid, pdx-xenograft, cdx-xenograft, adjacent-normal",
    )
    s.add_argument("--stage", action="append", help="analytical stage: raw | processed | summarized")
    s.add_argument(
        "--genome-build",
        dest="genome_build",
        action="append",
        help="reference genome: GRCh37 | GRCh38 | T2T-CHM13 | n/a",
    )
    s.add_argument(
        "--license-class",
        dest="license_class",
        action="append",
        help="license class: public-open | public-attribution | public-share-alike | research-only | commercial-restricted | dua-gated",
    )
    s.add_argument("--platform", action="append", help="assay platform (substring), e.g. '10x', 'TMT', 'DIA'")
    s.add_argument("--tissue", action="append", help="tissue / organ, e.g. colon, lung")
    s.add_argument("--treatment", action="append", help="treatment context, e.g. anti-PD1, untreated")
    s.add_argument(
        "--aggregation",
        action="append",
        help="poolability doctrine: pool_donor_median | prefer_curated_atlas | use_individual | needs_integration | not_aggregable",
    )

    d = sub.add_parser("describe", help="full detail for one manifest_id", parents=[common])
    d.add_argument("manifest_id")

    ln = sub.add_parser("lineage", help="walk derived_from / cited_by", parents=[common])
    ln.add_argument("manifest_id")
    ln.add_argument("--direction", choices=["upstream", "downstream", "both"], default="both")
    ln.add_argument("--depth", type=int, default=None)

    f = sub.add_parser("facets", help="list distinct values + counts for a facet (discovery)", parents=[common])
    f.add_argument(
        "facet",
        nargs="?",
        default=None,
        help="which facet to enumerate (default: all). One of the scientific facet names.",
    )

    a = sub.add_parser("audit", help="coverage gaps, superseded, uncited sources, overlaps", parents=[common])
    a.add_argument("--coverage-gaps", action="store_true")
    a.add_argument("--uncited", action="store_true", help="source-releases with no citation edge")
    a.add_argument("--stale", action="store_true", help="superseded-but-still-present manifests")
    a.add_argument("--overlaps", action="store_true", help="same study reachable via >1 manifest (double-count risk)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    idx = load_catalog(root=args.catalog_root, contracts_root=args.contracts_root)

    if args.command == "search":
        recs = idx.search(
            args.query,
            provider=args.provider,
            data_subject=args.data_subject,
            type=args.type,
            category=args.category,
            file_format=args.file_format,
            license=args.license,
            system_of_record=args.sor,
            indication=args.indication,
            measurement_class=args.measurement_class,
            measurement_type=args.measurement_type,
            grain=args.grain,
            gene_key=args.gene_key,
            sample_type=args.sample_type,
            stage=args.stage,
            genome_build=args.genome_build,
            license_class=args.license_class,
            platform=args.platform,
            tissue=args.tissue,
            treatment=args.treatment,
            aggregation=args.aggregation,
        )
        if args.json:
            print(json.dumps([idx.describe(r.id) for r in recs], indent=2, default=str))
        else:
            print(_render_search(recs))

    elif args.command == "describe":
        try:
            d = idx.describe(args.manifest_id)
        except KeyError:
            print(
                f"error: manifest {args.manifest_id!r} not found in the catalog.\n"
                f"try:  catalog_query search {args.manifest_id.split('-')[0]!r}",
                file=sys.stderr,
            )
            return 2
        print(json.dumps(d, indent=2, default=str) if args.json else _render_describe(d))

    elif args.command == "lineage":
        try:
            r = idx.lineage(args.manifest_id, direction=args.direction, depth=args.depth)
        except KeyError:
            print(f"error: manifest {args.manifest_id!r} not found in the catalog.", file=sys.stderr)
            return 2
        print(json.dumps(r, indent=2, default=str) if args.json else _render_lineage(r))

    elif args.command == "facets":
        names = [args.facet] if args.facet else list(_FACET_NAMES)
        if args.json:
            print(json.dumps({n: dict(idx.facet_values(n)) for n in names}, indent=2, default=str))
        else:
            print(_render_facets(idx, names))

    elif args.command == "audit":
        a = idx.audit()
        if args.json:
            print(json.dumps(a, indent=2, default=str))
        else:
            # default: show everything if no section flag was passed
            flags = [
                ("coverage-gaps", args.coverage_gaps),
                ("uncited", args.uncited),
                ("stale", args.stale),
                ("overlaps", args.overlaps),
            ]
            sections = {k for k, on in flags if on} or {"coverage-gaps", "uncited", "stale", "overlaps"}
            print(_render_audit(a, sections))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
