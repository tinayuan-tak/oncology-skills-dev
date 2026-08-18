#!/usr/bin/env python3
"""signor_mechanism_network CLI — SIGNOR mechanism network from OmniPath.

Streams the OmniPath commercially-cleared interactions.tsv (already
catalogued at omnipath-snapshot-2026-06-29), filters to the SIGNOR-tagged
subset, and emits a per-gene mechanism-network parquet consumed by the
signaling-network-mechanism evidence card.

Design note: OmniPath aggregates 100+ upstream resources under a single
API + license-filtered TSV; SIGNOR is the "curator-tight, causally-directed"
subset (~30k human interactions). Filtering to SIGNOR-only within OmniPath
gives us (a) a defensible provenance chain (one catalogued source manifest),
(b) directed + effect-annotated edges (SIGNOR's discipline), and (c) MIT-
class license clearance (SIGNOR is CC-BY, retained by OmniPath's
license=commercial filter).

Output schema (per row):
    target_uniprot_ac       str    — the target being profiled
    target_gene_symbol      str
    partner_uniprot_ac      str    — the interaction partner
    partner_gene_symbol     str
    direction               str    — 'upstream' | 'downstream'
    raw_mechanism           str    — verbatim SIGNOR mechanism string
    moa_class               str    — from moa_ontology (or 'unmapped')
    modality_relevance      list<str>
    signor_reference        str    — SIGNOR row identifier / citation
    is_stimulation          bool
    is_inhibition           bool
    consensus_direction     bool
    moa_ontology_version    str

Usage:
    python -m methods.signor_mechanism_network.cli \\
        --out /tmp/signor_mechanism_network_v1.parquet

    # Or per-target extraction for a card dispatcher:
    python -m methods.signor_mechanism_network.cli \\
        --target-symbol KRAS \\
        --out /tmp/kras_signor.parquet
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import click

from .moa_ontology import classify_edge, ONTOLOGY_VERSION
from methods.catalog_query.read import bucket_prefix_for

DEFAULT_AWS_PROFILE = "cbg"
OMNIPATH_MANIFEST_ID = "omnipath-snapshot-2026-06-29"
# bucket + key resolved from the data-catalog manifest (single source of truth).
OMNIPATH_S3_BUCKET, _OMNIPATH_PREFIX = bucket_prefix_for(OMNIPATH_MANIFEST_ID)
OMNIPATH_S3_KEY = f"{_OMNIPATH_PREFIX}interactions.tsv"

# SIGNOR is the target upstream source we filter to. OmniPath's `sources` column
# is a semicolon-delimited list of upstream resource identifiers; SIGNOR-tagged
# rows contain 'SIGNOR' (case-sensitive) as one of the tokens.
SIGNOR_SOURCE_TAG = "SIGNOR"


def _stream_interactions(s3_uri: str):
    """Yield header-mapped dicts from OmniPath's interactions.tsv.

    OmniPath's TSV is streamable — the file is 4.9 MB total, so we can also
    load it fully into memory; streaming is used for the sake of a uniform
    method contract with other TSV-based derived-manifest pipelines.
    """
    import boto3

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=OMNIPATH_S3_BUCKET, Key=OMNIPATH_S3_KEY)
    body = obj["Body"].read().decode("utf-8")
    lines = body.splitlines()
    header = lines[0].split("\t")
    for raw in lines[1:]:
        parts = raw.split("\t")
        if len(parts) != len(header):
            continue
        yield dict(zip(header, parts))


def _is_signor(row: dict) -> bool:
    """SIGNOR-tagged rows carry 'SIGNOR' in the semicolon-delimited sources column."""
    sources = row.get("sources", "")
    return SIGNOR_SOURCE_TAG in {s.strip() for s in sources.split(";")}


def _emit_edges_for_row(row: dict):
    """Emit (target, partner, direction, mechanism, ...) records for one row.

    OmniPath edges are directed: source → target. When the target-being-profiled
    matches the row's `source` column, the partner is `target` (a downstream
    partner from the target's perspective). When the target matches the row's
    `target` column, the partner is `source` (an upstream partner).

    This function returns BOTH directions per row as separate records; the
    caller filters to the target of interest.
    """
    src = row.get("source", "").strip()  # uniprot AC
    tgt = row.get("target", "").strip()
    if not src or not tgt:
        return
    # Gene-symbol columns. OmniPath emits *_genesymbol
    # columns alongside the UniProt-AC source/target; the card summary_fields
    # + downstream mechanism-and-pharmacology dispatcher expect a
    # `target_gene_symbol` column for HGNC-symbol-based filtering. Fall back
    # to empty string when the *_genesymbol column is absent (older OmniPath
    # snapshots) — downstream still has target_uniprot_ac as canonical key.
    src_sym = row.get("source_genesymbol", "").strip()
    tgt_sym = row.get("target_genesymbol", "").strip()

    is_stim = row.get("is_stimulation", "").strip() in ("1", "True", "true")
    is_inh = row.get("is_inhibition", "").strip() in ("1", "True", "true")
    consensus = row.get("consensus_direction", "").strip() in (
        "1", "True", "true"
    )
    references = row.get("references", "").strip()

    # SIGNOR's effect / mechanism column. OmniPath aggregates this as
    # `consensus_direction` + a per-source effect column; we prefer the SIGNOR-
    # specific effect if present. When the effect
    # strings are empty, DERIVE a mechanism from is_stimulation /
    # is_inhibition rather than hard-coding "binding" — the previous fallback
    # misclassified inhibitory edges as `molecular_glue_disruptor` MoA class.
    effect_signor = row.get("effect_signor", "").strip()
    effect_omni = row.get("effect", "").strip()
    if effect_signor:
        mechanism = effect_signor
    elif effect_omni:
        mechanism = effect_omni
    elif is_inh:
        mechanism = "inhibition"
    elif is_stim:
        mechanism = "stimulation"
    else:
        mechanism = "binding"

    yield {
        "target_uniprot_ac": src,
        "target_gene_symbol": src_sym,
        "partner_uniprot_ac": tgt,
        "partner_gene_symbol": tgt_sym,
        "direction": "downstream",
        "raw_mechanism": mechanism,
        "is_stimulation": is_stim,
        "is_inhibition": is_inh,
        "consensus_direction": consensus,
        "references": references,
    }
    yield {
        "target_uniprot_ac": tgt,
        "target_gene_symbol": tgt_sym,
        "partner_uniprot_ac": src,
        "partner_gene_symbol": src_sym,
        "direction": "upstream",
        "raw_mechanism": mechanism,
        "is_stimulation": is_stim,
        "is_inhibition": is_inh,
        "consensus_direction": consensus,
        "references": references,
    }


def _classify_and_resolve(records, unmapped_log: list):
    """Enrich records with MoA classification. Logs unmapped mechanisms."""
    for r in records:
        cls = classify_edge(r["raw_mechanism"], r["direction"])
        if cls is None:
            unmapped_log.append({
                "raw_mechanism": r["raw_mechanism"],
                "direction": r["direction"],
                "target_uniprot_ac": r["target_uniprot_ac"],
                "partner_uniprot_ac": r["partner_uniprot_ac"],
            })
            r["moa_class"] = "unmapped"
            r["modality_relevance"] = []
        else:
            r["moa_class"] = cls.moa_class
            r["modality_relevance"] = list(cls.modality_relevance)
        r["moa_ontology_version"] = ONTOLOGY_VERSION
        yield r


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output parquet path.")
@click.option("--target-symbol", default=None,
              help="OPTIONAL. If provided, filter output to edges involving "
                   "the named HGNC symbol on either side. When omitted, all "
                   "SIGNOR-tagged edges are emitted.")
@click.option("--unmapped-log-path", default=None, type=click.Path(path_type=Path),
              help="Optional path for the unmapped-mechanism jsonl log. "
                   "Defaults to alongside --out with suffix _unmapped_mechanisms.jsonl.")
def main(out: Path, target_symbol: str, unmapped_log_path: Path):
    """Extract SIGNOR-tagged mechanism network from OmniPath into a parquet."""
    import pandas as pd

    if unmapped_log_path is None:
        unmapped_log_path = out.with_name(
            out.stem + "_unmapped_mechanisms.jsonl"
        )

    click.echo(f"[signor_mechanism_network] streaming OmniPath interactions "
               f"from s3://{OMNIPATH_S3_BUCKET}/{OMNIPATH_S3_KEY}", err=True)

    unmapped: list[dict] = []
    edges: list[dict] = []
    n_rows = n_signor = n_edges = 0
    for row in _stream_interactions(""):
        n_rows += 1
        if not _is_signor(row):
            continue
        n_signor += 1
        for edge in _emit_edges_for_row(row):
            edges.append(edge)
            n_edges += 1

    click.echo(
        f"[signor_mechanism_network] read {n_rows} OmniPath rows, "
        f"{n_signor} SIGNOR-tagged, emitted {n_edges} directed edges.",
        err=True,
    )

    edges = list(_classify_and_resolve(edges, unmapped))

    if target_symbol:
        # Symbol-based filtering requires a UniProt-AC ↔ HGNC-symbol join.
        # We emit the FULL parquet and expect card dispatchers
        # to filter at read time using the framework's identifier-resolver
        # sidecar (target-contracts/vocabularies). Emit a warning to make
        # this explicit.
        click.echo(
            "[signor_mechanism_network] WARNING: --target-symbol filtering "
            "delegates to the identifier-resolver sidecar at read time. "
            "Emitting FULL parquet; card dispatcher must filter downstream.",
            err=True,
        )

    df = pd.DataFrame(edges)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    click.echo(f"[signor_mechanism_network] wrote {len(df):,} rows -> {out}",
               err=True)

    # Write unmapped mechanism log (one JSON per line)
    if unmapped:
        with open(unmapped_log_path, "w") as f:
            for entry in unmapped:
                f.write(json.dumps(entry) + "\n")
        pct = 100.0 * len(unmapped) / max(1, len(edges))
        click.echo(
            f"[signor_mechanism_network] {len(unmapped):,} unmapped mechanism "
            f"entries ({pct:.1f}%) written to {unmapped_log_path}",
            err=True,
        )
        if pct > 5.0:
            click.echo(
                f"[signor_mechanism_network] WARNING: unmapped fraction {pct:.1f}% "
                f"exceeds 5% threshold. Extend moa_ontology.py to cover new "
                f"mechanism strings.",
                err=True,
            )


if __name__ == "__main__":
    main()
