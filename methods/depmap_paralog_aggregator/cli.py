#!/usr/bin/env python3
"""depmap_paralog_aggregator CLI — genome-wide paralog buffering derived product.

Emits `depmap-paralog-buffering-per-gene-v1` parquet: one row per gene present
in DepMap 26Q1 dual-KO paralog screens, with per-gene paralog buffering class
and top partner list.

Data sources (all landed in data-catalog):
  - depmap-consortium-26q1-paralogs/ParalogGeneEffect.csv  (69 MB)
  - ensembl-compara-release-116-snapshot-2026-07-10/hsapiens_paralog_subtypes_release-116.tsv

Sanger Paralog Screen 2023 NOT included (no-resale clause; pending legal review).
v1 covers DepMap dual-KO library only (~4,550 gene-pair columns).

Output schema:
    target_gene_symbol      str — HGNC gene symbol
    paralog_buffering_class str — 'strong' | 'partial' | 'none' | 'data_unavailable'
    n_paralogs_annotated    int — total screened partners in DepMap library
    n_paralogs_buffering    int — partners classified strong or partial
    strongest_partner       str — partner with highest dep_delta
    strongest_delta         float | null — max dep_delta_paired_vs_max_single
    top_partners            list<struct> — up to 20 partners, sorted by delta desc
    sanger_screen_included  bool — always False in v1; placeholder for v2
    method_version          str

Usage:
    python -m methods.depmap_paralog_aggregator.cli \\
        --out /path/to/paralog_buffering.parquet
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from methods.catalog_query.read import bucket_prefix_for

DEFAULT_AWS_PROFILE = "cbg"
ENSEMBL_COMPARA_MANIFEST_ID = "ensembl-compara-release-116-snapshot-2026-07-10"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, _ENSEMBL_COMPARA_PREFIX = bucket_prefix_for(ENSEMBL_COMPARA_MANIFEST_ID)
ENSEMBL_PARALOG_S3_KEY = f"{_ENSEMBL_COMPARA_PREFIX}hsapiens_paralog_subtypes_release-116.tsv"
ENSEMBL_CACHE_DIR = Path.home() / ".cache" / "framework-ensembl-compara"
ENSEMBL_CACHE_TSV = ENSEMBL_CACHE_DIR / "hsapiens_paralog_subtypes_release-116.tsv"

# Ensembl gene-ID -> HGNC-symbol bridge. The paralog-subtypes TSV keys the QUERY side on
# `Gene stable ID` (an Ensembl gene id, ENSG...), NOT a symbol — only the PARTNER side carries a
# symbol. DepMap paralog columns are HGNC symbols, so the query id must be mapped to its symbol
# before a (query_symbol, partner_symbol) pair can be formed. The compara manifest names this
# companion explicitly ("bridges to the HGNC symbol via ensembl-id-mapping-release-116-...").
ENSEMBL_ID_MAP_MANIFEST_ID = "ensembl-id-mapping-release-116-snapshot-2026-06-18"
_S3_BUCKET_IDMAP, _ENSEMBL_IDMAP_PREFIX = bucket_prefix_for(ENSEMBL_ID_MAP_MANIFEST_ID)
ENSEMBL_ID_MAP_S3_KEY = f"{_ENSEMBL_IDMAP_PREFIX}hsapiens_gene_id_map_release-116.tsv"
ENSEMBL_ID_MAP_CACHE_TSV = ENSEMBL_CACHE_DIR / "hsapiens_gene_id_map_release-116.tsv"

METHOD_VERSION = "1.0.0"


def _ensure_ensembl_cached() -> Path | None:
    """Download Ensembl compara paralog subtypes file to local cache."""
    ENSEMBL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if ENSEMBL_CACHE_TSV.exists() and ENSEMBL_CACHE_TSV.stat().st_size > 0:
        return ENSEMBL_CACHE_TSV
    try:
        import boto3

        s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
        click.echo("  Downloading Ensembl compara paralog subtypes (~188 MB)...", err=True)
        s3.download_file(S3_BUCKET, ENSEMBL_PARALOG_S3_KEY, str(ENSEMBL_CACHE_TSV))
        return ENSEMBL_CACHE_TSV
    except Exception as e:  # absence-discipline: exempt -- build-time OPTIONAL ohnolog enrichment; failure WARNs to stderr + skips (not a silent card-facing gap)
        click.echo(f"  WARNING: Ensembl paralog cache failed: {e} — ohnolog annotation skipped", err=True)
        return None


def _ensure_ensembl_id_map_cached() -> Path | None:
    """Download the Ensembl gene-ID -> HGNC-symbol bridge TSV to local cache."""
    ENSEMBL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if ENSEMBL_ID_MAP_CACHE_TSV.exists() and ENSEMBL_ID_MAP_CACHE_TSV.stat().st_size > 0:
        return ENSEMBL_ID_MAP_CACHE_TSV
    try:
        import boto3

        s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
        click.echo("  Downloading Ensembl gene-ID -> HGNC-symbol map...", err=True)
        s3.download_file(_S3_BUCKET_IDMAP, ENSEMBL_ID_MAP_S3_KEY, str(ENSEMBL_ID_MAP_CACHE_TSV))
        return ENSEMBL_ID_MAP_CACHE_TSV
    except Exception as e:  # absence-discipline: exempt -- build-time OPTIONAL ohnolog enrichment; failure WARNs to stderr + skips (not a silent card-facing gap)
        click.echo(f"  WARNING: Ensembl id-map cache failed: {e} — ohnolog annotation skipped", err=True)
        return None


def _load_ensembl_gene_id_to_symbol() -> dict[str, str]:
    """Ensembl `Gene stable ID` (ENSG..., no version) -> upper-cased HGNC symbol.

    Reads hsapiens_gene_id_map_release-116.tsv (columns: Gene stable ID, Gene stable ID
    version, HGNC ID, HGNC symbol, Gene name). Only rows with a non-empty HGNC symbol are
    kept. Returns {} if the bridge is unavailable (caller then yields no ohnolog pairs)."""
    path = _ensure_ensembl_id_map_cached()
    if not path:
        return {}
    import csv

    id2sym: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            gid = (row.get("Gene stable ID") or "").strip()
            sym = (row.get("HGNC symbol") or "").strip().upper()
            if gid and sym:
                id2sym[gid] = sym
    click.echo(f"  Loaded {len(id2sym):,} Ensembl-ID -> HGNC-symbol mappings", err=True)
    return id2sym


def _load_ensembl_ohnolog_set() -> frozenset[tuple[str, str]]:
    """Load the set of (GENE_A_upper, GENE_B_upper) HGNC-symbol pairs that are ohnologs.

    Ohnologs = ancient whole-genome-duplication products. The compara paralog-subtypes TSV
    columns are: `Gene stable ID` (QUERY, an Ensembl gene id — NOT a symbol),
    `Human paralogue associated gene name` (PARTNER symbol),
    `Human paralogue gene stable ID`, `Paralogue last common ancestor with Human` (LCA).
    We map the query id -> HGNC symbol via the id-mapping companion, take the partner symbol
    directly, and keep pairs whose LCA is in the ANCIENT set (proxy for WGD ancestry;
    conservative — recent divergences like 'Homo sapiens' / 'Mammalia' / 'Primates' are NOT
    ohnologs). ANCIENT set matches the derived manifest's declared ohnolog_lca_set plus the
    older strata present in this release's data (Chordata/Gnathostomata/Euteleostomi are
    vertebrate-WGD-era and correctly included; Eutheria/Amniota and later are excluded).

    Returns empty frozenset if either the paralog TSV or the id->symbol bridge is unavailable.
    """
    path = _ensure_ensembl_cached()
    if not path:
        return frozenset()
    id2sym = _load_ensembl_gene_id_to_symbol()
    if not id2sym:
        click.echo("  WARNING: Ensembl-ID->symbol bridge empty — ohnolog annotation skipped", err=True)
        return frozenset()

    import csv

    # WGD-era ancestry (Vertebrata-2R and older). Anything younger than the jawed-vertebrate
    # radiation (Euteleostomi/Gnathostomata/Vertebrata/Chordata + the deep pan-eukaryotic strata)
    # is treated as an ohnolog-era divergence; Eutheria and later placental/primate strata are not.
    ANCIENT_LCAS = {
        "Vertebrata",
        "Chordata",
        "Gnathostomata",
        "Euteleostomi",  # vertebrate 2R-WGD era
        "Bilateria",
        "Opisthokonta",
        "Eukaryota",
        "Unikonta",  # deep pan-eukaryotic
    }
    n_query_unmapped = 0
    ohnolog_pairs: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            gid = (row.get("Gene stable ID") or "").strip()
            partner_sym = (row.get("Human paralogue associated gene name") or "").strip().upper()
            lca = (row.get("Paralogue last common ancestor with Human") or "").strip()
            if not gid or not partner_sym or lca not in ANCIENT_LCAS:
                continue
            query_sym = id2sym.get(gid)
            if not query_sym:
                n_query_unmapped += 1
                continue
            if query_sym == partner_sym:
                continue
            ohnolog_pairs.add(tuple(sorted([query_sym, partner_sym])))
    click.echo(
        f"  Loaded {len(ohnolog_pairs):,} ohnolog pairs from Ensembl compara "
        f"({n_query_unmapped:,} query rows had no HGNC symbol)",
        err=True,
    )
    return frozenset(ohnolog_pairs)


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Output parquet path.")
@click.option(
    "--no-ensembl",
    is_flag=True,
    default=False,
    help="Skip Ensembl ohnolog annotation (faster; ohnolog_flag will be null).",
)
def main(out: Path, no_ensembl: bool):
    """Emit genome-wide per-gene paralog buffering parquet from DepMap 26Q1."""
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    click.echo(f"=== depmap_paralog_aggregator v{METHOD_VERSION} ===", err=True)

    # Pull paralog indexed data from read.py (triggers S3 cache if needed)
    from methods.depmap_paralog_aggregator.read import (
        _load_paralog_indexed,
        _classify_buffering,
        PARALOG_SOURCE_MANIFEST_ID,
    )

    click.echo("  Loading DepMap paralog gene-effect index...", err=True)
    pair_delta_index, per_gene_pair_index = _load_paralog_indexed()
    if not pair_delta_index:
        click.echo("ERROR: paralog data unavailable — check S3 / AWS_PROFILE", err=True)
        raise SystemExit(1)
    click.echo(f"  Indexed {len(pair_delta_index):,} pairs, {len(per_gene_pair_index):,} unique genes", err=True)

    # Optional Ensembl ohnolog annotation
    ohnolog_pairs: frozenset = frozenset()
    if not no_ensembl:
        ohnolog_pairs = _load_ensembl_ohnolog_set()

    # Build one row per gene
    rows = []
    for gene, partners in per_gene_pair_index.items():
        # Sort partners by delta desc (strongest buffering first), unmeasured last
        measured = [(p, rec) for p, rec in partners if rec["delta_vs_max_single"] is not None]
        unmeasured = [(p, rec) for p, rec in partners if rec["delta_vs_max_single"] is None]
        measured.sort(key=lambda x: x[1]["delta_vs_max_single"], reverse=True)
        sorted_partners = measured + unmeasured

        top_partners_out = []
        for partner, rec in sorted_partners[:20]:
            delta = rec["delta_vs_max_single"]
            pair_key = tuple(sorted([gene, partner]))
            ohnolog = pair_key in ohnolog_pairs if ohnolog_pairs else None
            top_partners_out.append(
                {
                    "partner_symbol": partner,
                    "dep_delta_paired_vs_max_single": delta,
                    "median_dual_ko_effect": rec["median_dual"],
                    "single_ko_target": rec.get("single_a") if gene < partner else rec.get("single_b"),
                    "single_ko_partner": rec.get("single_b") if gene < partner else rec.get("single_a"),
                    "buffering_class": _classify_buffering(delta),
                    "ohnolog_flag": ohnolog,
                    "ensembl_lca": None,
                }
            )

        n_buffering = sum(1 for p in top_partners_out if p["buffering_class"] in ("strong", "partial"))
        strongest = measured[0] if measured else None
        buffering_class = (
            _classify_buffering(strongest[1]["delta_vs_max_single"] if strongest else None)
            if measured
            else "data_unavailable"
        )

        rows.append(
            {
                "target_gene_symbol": gene,
                "paralog_buffering_class": buffering_class,
                "n_paralogs_annotated": len(sorted_partners),
                "n_paralogs_buffering": n_buffering,
                "strongest_partner": strongest[0] if strongest else None,
                "strongest_delta": strongest[1]["delta_vs_max_single"] if strongest else None,
                "top_partners": json.dumps(top_partners_out),
                "sanger_screen_included": False,
                "method_version": METHOD_VERSION,
            }
        )

    df = pd.DataFrame(rows)

    # Summary stats
    n_strong = int((df["paralog_buffering_class"] == "strong").sum())
    n_partial = int((df["paralog_buffering_class"] == "partial").sum())
    n_none = int((df["paralog_buffering_class"] == "none").sum())
    n_unavail = int((df["paralog_buffering_class"] == "data_unavailable").sum())
    click.echo(
        f"  Genes: {len(df):,} total | strong={n_strong} partial={n_partial} none={n_none} unavailable={n_unavail}",
        err=True,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    click.echo(f"  Wrote {out} ({out.stat().st_size:,} bytes, {len(df):,} rows)", err=True)

    # Write provenance sidecar
    prov = {
        "method_version": METHOD_VERSION,
        "source_manifest_id": PARALOG_SOURCE_MANIFEST_ID,
        "ensembl_manifest_id": "ensembl-compara-release-116-snapshot-2026-07-10",
        "sanger_screen_included": False,
        "sanger_screen_note": (
            "Sanger Paralog Screen 2023 NOT included in v1: no-resale clause, "
            "legal review pending. v2 will add Sanger screen once cleared."
        ),
        "n_genes": len(df),
        "n_pairs": len(pair_delta_index),
        "class_distribution": {
            "strong": n_strong,
            "partial": n_partial,
            "none": n_none,
            "data_unavailable": n_unavail,
        },
        "buffering_thresholds": {
            "strong_delta_threshold": 0.5,
            "partial_delta_threshold": 0.2,
            "delta_definition": "max(single_a, single_b) - median_dual_ko (positive = buffering)",
        },
        "ohnolog_annotation_source": (
            "ensembl-compara-release-116; LCA in {Vertebrata, Bilateria, Opisthokonta, Eukaryota}"
        )
        if not no_ensembl and ohnolog_pairs
        else "skipped",
    }
    prov_path = out.with_suffix(".provenance.json")
    prov_path.write_text(json.dumps(prov, indent=2))
    click.echo(f"  Wrote {prov_path}", err=True)


if __name__ == "__main__":
    main()
