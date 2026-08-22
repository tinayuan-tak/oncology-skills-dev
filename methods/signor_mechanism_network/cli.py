#!/usr/bin/env python3
"""signor_mechanism_network CLI — per-gene SIGNOR mechanism-network parquet emitter.

Reads the DIRECT SIGNOR release (signor-jul2026, SIGNOR_Jul2026_release.txt) — the same source the
reader's inline compose-on-read path uses — filters to human protein-protein edges, classifies each
via the shared moa_ontology, and DUAL-EMITS one row per (target side) so the derived product is
keyed/sorted by target_gene_symbol for pushdown. This RE-BASES the prior OmniPath-sourced emitter
(reverted product signor-mechanism-network-per-gene-v1) onto the direct release the current reader
reads, so the materialized parquet is byte-identical to the reader's inline `_compute_edges_for_target`
(the emitter reuses the reader's row parser + replicates its per-row edge logic; verified per-target).

Output schema (per row) — target_gene_symbol/target_uniprot_ac are the pushdown keys the reader
strips on read; the remaining columns are exactly the reader's per-edge dict:
    target_gene_symbol   str    — pushdown/sort key (the gene whose neighbourhood this row belongs to)
    target_uniprot_ac    str
    partner_gene_symbol  str
    partner_uniprot_ac   str
    direction            str    — 'upstream' | 'downstream'
    raw_mechanism        str    — verbatim SIGNOR MECHANISM
    raw_effect           str    — verbatim SIGNOR EFFECT
    moa_class            str    — from moa_ontology (or 'unmapped')
    modality_relevance   list<str>
    is_stimulation       bool
    is_inhibition        bool
    direct_flag          bool
    references           str    — SIGNOR PMID(s)
    moa_ontology_version str

Usage:
    python -m methods.signor_mechanism_network.cli --out /tmp/signor_mechanism_network.parquet
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from .moa_ontology import classify_edge, ONTOLOGY_VERSION
# Reuse the reader's SIGNOR-TSV parser (human TAX_ID filter + header mapping) — one source of truth
# for which rows exist, so the emitted product and the reader's inline fallback see identical rows.
from .read import _load_signor_rows_indexed


def _edges_from_row(row: dict) -> list[dict]:
    """Dual-emit the classified edge dict(s) for one SIGNOR row — one keyed by ENTITYA (downstream),
    one by ENTITYB (upstream). Replicates the reader's `_compute_edges_for_target` per-row logic
    EXACTLY (protein-only filter, mechanism/effect parsing, is_stim/is_inh, per-direction classify),
    adding the target_gene_symbol/target_uniprot_ac pushdown keys. Returns [] for skipped rows."""
    entity_a = row.get("ENTITYA", "").strip()
    entity_b = row.get("ENTITYB", "").strip()
    if not entity_a or not entity_b:
        return []
    type_a = row.get("TYPEA", "").strip().lower()
    type_b = row.get("TYPEB", "").strip().lower()
    if "protein" not in type_a or "protein" not in type_b:
        return []   # skip complex-involved edges (parity with the reader)
    id_a = row.get("IDA", "").strip()
    id_b = row.get("IDB", "").strip()
    effect = row.get("EFFECT", "").strip().strip('"')
    mechanism = row.get("MECHANISM", "").strip().strip('"')
    pmid = row.get("PMID", "").strip()
    direct_flag = row.get("DIRECT", "").strip().lower() in ("t", "true", "1", "yes")

    effect_lower = effect.lower()
    is_stim = "up-regulates" in effect_lower or "up regulates" in effect_lower
    is_inh = "down-regulates" in effect_lower or "down regulates" in effect_lower
    if mechanism:
        mech_str = mechanism.lower()
    elif is_inh:
        mech_str = "inhibition"
    elif is_stim:
        mech_str = "stimulation"
    else:
        mech_str = "binding"

    # target=ENTITYA → downstream (partner B); target=ENTITYB → upstream (partner A).
    # SELF-LOOP (ENTITYA==ENTITYB): the reader indexes the row under the entity TWICE (ENTITYA +
    # ENTITYB columns) and both passes hit `target==entity_a` → TWO downstream edges. Reproduce that
    # exactly so per-target counts are byte-identical to the inline compose (source-data quirk).
    if entity_a == entity_b:
        sides = ((entity_a, id_a, entity_b, id_b, "downstream"),
                 (entity_a, id_a, entity_b, id_b, "downstream"))
    else:
        sides = ((entity_a, id_a, entity_b, id_b, "downstream"),
                 (entity_b, id_b, entity_a, id_a, "upstream"))
    out: list[dict] = []
    for target_sym, target_ac, partner_sym, partner_ac, direction in sides:
        cls = classify_edge(mech_str, direction)
        moa_class = "unmapped" if cls is None else cls.moa_class
        modality_relevance = [] if cls is None else list(cls.modality_relevance)
        out.append({
            "target_gene_symbol": target_sym,
            "target_uniprot_ac": target_ac,
            "partner_gene_symbol": partner_sym,
            "partner_uniprot_ac": partner_ac,
            "direction": direction,
            "raw_mechanism": mechanism,
            "raw_effect": effect,
            "moa_class": moa_class,
            "modality_relevance": modality_relevance,
            "is_stimulation": is_stim,
            "is_inhibition": is_inh,
            "direct_flag": direct_flag,
            "references": pmid,
            "moa_ontology_version": ONTOLOGY_VERSION,
        })
    return out


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Output parquet path.")
@click.option("--unmapped-log-path", default=None, type=click.Path(path_type=Path),
              help="Optional path for the unmapped-mechanism jsonl log "
                   "(default: alongside --out, suffix _unmapped_mechanisms.jsonl).")
def main(out: Path, unmapped_log_path: Path):
    """Emit the full per-gene SIGNOR mechanism-network parquet from the direct SIGNOR release."""
    import pandas as pd

    if unmapped_log_path is None:
        unmapped_log_path = out.with_name(out.stem + "_unmapped_mechanisms.jsonl")

    rows, _ = _load_signor_rows_indexed()   # human-filtered SIGNOR rows (reader's parser)
    click.echo(f"[signor_mechanism_network] {len(rows):,} human SIGNOR rows", err=True)

    edges: list[dict] = []
    for row in rows:
        edges.extend(_edges_from_row(row))
    # sort by the pushdown key so row-group pruning fires (query_optimization.sort_columns)
    edges.sort(key=lambda e: (e["target_gene_symbol"], e["direction"], e["partner_gene_symbol"]))
    n_unmapped = sum(1 for e in edges if e["moa_class"] == "unmapped")
    click.echo(f"[signor_mechanism_network] emitted {len(edges):,} dual-emitted edges "
               f"({n_unmapped:,} unmapped, {100.0*n_unmapped/max(1,len(edges)):.1f}%)", err=True)

    df = pd.DataFrame(edges)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, row_group_size=20000)
    click.echo(f"[signor_mechanism_network] wrote {len(df):,} rows -> {out}", err=True)

    if n_unmapped:
        seen = set()
        with open(unmapped_log_path, "w") as f:
            for e in edges:
                if e["moa_class"] == "unmapped":
                    keyk = (e["raw_mechanism"], e["direction"])
                    if keyk in seen:
                        continue
                    seen.add(keyk)
                    f.write(json.dumps({"raw_mechanism": e["raw_mechanism"],
                                        "direction": e["direction"]}) + "\n")
        click.echo(f"[signor_mechanism_network] {len(seen):,} distinct unmapped mechanisms "
                   f"-> {unmapped_log_path}", err=True)


if __name__ == "__main__":
    main()
