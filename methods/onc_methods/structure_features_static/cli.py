#!/usr/bin/env python3
"""structure_features_static CLI — PDB + AlphaFold static structural features.

Emits scalar per-UniProt-AC summary fields for the structure-features-static
card (Phase F). No interactive viewer; no atomic coordinates. Categorical
fields drive the rules engine + downstream ADC/TCE tractability reasoning.

`alphafold_plddt_min_domain` alone is a start but a real druggability call
needs pocket-adjacency reasoning. This CLI's `mutation_hotspot_in_druggable_pocket`
is a categorical boolean derived from (a) known mutation hotspots for the gene
(joined from gdc_somatic_hotspot output) + (b) pocket-adjacency scoring from
AlphaFold pLDDT-low + surface-exposed regions. The full scoring uses fpocket
or canSAR as external tools OR a simple pLDDT + SASA heuristic as first-pass;
the scaffold implements the heuristic.

Output schema (per row):
    uniprot_ac                             str
    gene_symbol                            str
    pdb_ids_available                      list<str>  — PDB IDs matching this UniProt-AC
    pdb_best_resolution_angstrom                  float      — best crystal resolution
    pdb_best_method                        str        — 'X-ray' | 'cryo-EM' | 'NMR' | 'none'
    alphafold_prediction_id                str
    alphafold_model_version                str
    alphafold_plddt_mean                   float
    alphafold_plddt_min                    float
    alphafold_plddt_min_domain             float  — per-domain minimum (lowest across domains)
    n_domains_low_plddt                    int    — domains with pLDDT_mean < 70
    mutation_hotspot_in_druggable_pocket   bool
    hotspot_pocket_adjacency_call          str    — 'adjacent' | 'distant' | 'no_structure' | 'no_hotspots_annotated'
    disordered_fraction                    float  — fraction of residues with pLDDT < 50
    method_version                         str

Reviewer note: hotspot_pocket_adjacency_call = 'no_structure' when neither PDB
nor AlphaFold has usable coverage — clearer than a nullable boolean. Rules
consume the categorical directly.

The row-building COMPUTE now lives in compute.py (pure kernels:
HGVSp→residue, pLDDT aggregation, per-domain min, PDB coverage, and the v1 pLDDT
pocket-adjacency heuristic — all unit-tested against fixtures, no live I/O). The
compute emits the 4th enum value `no_hotspots_annotated` (structure present, no
annotated hotspot) that this scaffold could not. What remains GATED is the SOURCE
I/O: this CLI writes a 0-row scaffold until the greenfield PDB + AlphaFold source
snapshots land on S3 (the pull is a separate, infra-gated step). Once the sources exist,
the source-loading layer feeds compute.build_row per UniProt-AC to emit real rows.

Usage:
    python -m onc_methods.structure_features_static.cli \\
        --out /tmp/structure_features_v1.parquet
"""

from __future__ import annotations

import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
PDB_S3_PREFIX = "data-catalog/sources/pdb/snapshot-2026-07-08/"
ALPHAFOLD_S3_PREFIX = "data-catalog/sources/alphafold/snapshot-2026-07-08/"
HOTSPOT_S3_PREFIX = "data-catalog/derived/"  # gdc_somatic_hotspot output


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Output parquet path.")
def main(out: Path):
    """Extract PDB + AlphaFold static structural features per UniProt-AC.

    SCAFFOLD: row schema + caveats sidecar; full compute defers to a
    Layer 2 delivery follow-up.
    """
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)

    click.echo(
        "[structure_features_static] scaffold: PDB + AlphaFold + hotspot join",
        err=True,
    )

    caveats = [
        "pLDDT is AlphaFold's per-residue confidence, NOT a solvent-accessibility "
        "or druggability score. Low-pLDDT regions are typically intrinsically "
        "disordered — often functionally-relevant but not directly druggable by "
        "small molecules. Do not conflate low-pLDDT with 'undruggable'.",
        "hotspot_pocket_adjacency_call='no_structure' means neither PDB nor "
        "AlphaFold has usable coverage for pocket-adjacency scoring. Governance "
        "readers should treat this as data-unavailable, not a druggability call.",
        "This iter-1 implementation uses a pLDDT + SASA heuristic for pocket "
        "adjacency. Governance-grade druggability scoring should use fpocket "
        "(Le Guilloux 2009 BMC Bioinformatics doi:10.1186/1471-2105-10-168) "
        "or canSAR (Mitsopoulos 2021 NAR doi:10.1093/nar/gkaa1059).",
        "PDB and AlphaFold snapshots are point-in-time (2026-07-08). Newly-"
        "deposited structures after this date are not covered until snapshot "
        "refresh.",
    ]

    df = pd.DataFrame(
        columns=[
            "uniprot_ac",
            "gene_symbol",
            "pdb_ids_available",
            "pdb_best_resolution_angstrom",
            "pdb_best_method",
            "alphafold_prediction_id",
            "alphafold_model_version",
            "alphafold_plddt_mean",
            "alphafold_plddt_min",
            "alphafold_plddt_min_domain",
            "n_domains_low_plddt",
            "mutation_hotspot_in_druggable_pocket",
            "hotspot_pocket_adjacency_call",
            "disordered_fraction",
            "method_version",
        ]
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    sidecar = out.with_suffix(".caveats.txt")
    with sidecar.open("w") as f:
        f.write("\n\n".join(caveats))

    click.echo(
        f"[structure_features_static] wrote scaffold parquet (0 rows) -> {out}\n"
        f"[structure_features_static] wrote caveats sidecar -> {sidecar}",
        err=True,
    )


if __name__ == "__main__":
    main()
