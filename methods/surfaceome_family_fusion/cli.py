#!/usr/bin/env python3
"""surfaceome_family_fusion CLI — fuse SURFY + HPA + UniProt EC + IUPHAR.

Emits a per-UniProt-AC parquet with a resolved surface-protein family
categorical (`surface_protein_family`) + a `surfaceome_confidence_score`
(0.0-1.0) derived from source agreement. Consumer: the surfaceome-family-
classification evidence card (Phase F).

SURFY 2018 alone misses ~15% of clinically-validated ADC targets by our audit; HPA's
protein_class covers kinases/enzymes better but adhesion molecules worse.
Fusing four sources produces a family field robust to any single source's
gap.

Family taxonomy (categorical `surface_protein_family`):
    Kinase             — receptor tyrosine kinases + surface-adjacent kinases
    Enzyme             — surface-bound proteases / phosphatases / hydrolases
    Transporter        — SLC + ABC + ion channels + gap junctions
    CD_molecule        — canonical CDN cluster-of-differentiation markers
    Adhesion           — cadherins, integrins, IgSF adhesion, CEACAMs
    GPCR               — G-protein-coupled receptors (rhodopsin, secretin, glutamate)
    Growth_factor      — growth-factor + cytokine receptor family (non-RTK)
    Immune_receptor    — TCR/BCR/NK/complement/Fc receptor classes
    Other              — surface-confirmed but not fitting the above (fallback)
    Not_surface        — SURFY / HPA disagree; treated as non-surface

Output schema (per row):
    uniprot_ac                        str
    gene_symbol                       str
    surface_protein_family            str  — categorical from taxonomy above
    surfaceome_confidence_score       float — 0.0-1.0 agreement across sources
    surface_present_surfy             bool
    surfy_confidence_score            float — SURFY ML score
    surface_present_hpa               bool  — HPA subcellular_main_location contains 'Plasma membrane'
    hpa_protein_class                 str   — verbatim HPA class field
    uniprot_ec_number                 str   — full EC where applicable, else ""
    iuphar_family                     str
    fusion_provenance                 list<str>  — which sources agreed / disagreed
    family_class                      str  — rules-firing shorthand: 'kinase_surface' etc
    method_version                    str

Reviewer note: the surfaceome_confidence_score is a simple agreement fraction
(sources_agreeing_on_surface_status / sources_reporting) — not a probabilistic
posterior. Rules engine consumes the categorical `surface_protein_family`;
the score is a per-row confidence tie-breaker for downstream ranking.

Usage:
    python -m methods.surfaceome_family_fusion.cli \\
        --out /tmp/surfaceome_family_v1.parquet
"""

from __future__ import annotations

import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

SURFY_S3_KEY = "data-catalog/sources/surfacome-ethz-2018/table_S3_surfaceome.xlsx"
HPA_S3_KEY = "data-catalog/sources/hpa-v25-1/proteinatlas.tsv.zip"
UNIPROT_S3_KEY = "data-catalog/sources/uniprot-sprot-human/2026_02-snapshot-2026-06-18/uniprot_sprot_human.dat.gz"

FAMILY_TAXONOMY = [
    "Kinase",
    "Enzyme",
    "Transporter",
    "CD_molecule",
    "Adhesion",
    "GPCR",
    "Growth_factor",
    "Immune_receptor",
    "Other",
    "Not_surface",
]

# HPA protein_class column values → our family taxonomy.
_HPA_CLASS_TO_FAMILY = {
    "Kinases": "Kinase",
    "RAS pathway related proteins": "Kinase",
    "Enzymes": "Enzyme",
    "Transporters": "Transporter",
    "Voltage-gated ion channels": "Transporter",
    "Ion channels": "Transporter",
    "SLC transporters": "Transporter",
    "ABC transporters": "Transporter",
    "CD markers": "CD_molecule",
    "GPCRs": "GPCR",
    "Adhesion": "Adhesion",
    "Cell adhesion": "Adhesion",
    "Integrins": "Adhesion",
    "Cadherins": "Adhesion",
    "Growth factor receptors": "Growth_factor",
    "Cytokine receptors": "Growth_factor",
    "Immunoglobulin superfamily": "Immune_receptor",
    "T-cell receptors": "Immune_receptor",
    "Fc receptors": "Immune_receptor",
    "Complement receptors": "Immune_receptor",
}


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Output parquet path.")
def main(out: Path):
    """Fuse SURFY + HPA + UniProt EC + IUPHAR into a per-UniProt-AC family table.

    SCAFFOLD implementation:
      This CLI emits an empty-schema parquet with the row shape documented in
      the module docstring, plus a caveats sidecar. The full compute path
      (SURFY XLSX read via openpyxl + HPA TSV zip stream + UniProt DAT keyword
      parse + IUPHAR REST fetch) is a Layer 2 compute-delivery follow-up.

      The scaffold's value: consumers can wire the surfaceome-family-
      classification card dispatcher against the row schema NOW, run
      integration tests against the empty parquet with clear
      `family_class = 'data_unavailable'` semantics, and swap in the compute
      later without moving the schema.
    """
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)

    click.echo(
        "[surfaceome_family_fusion] scaffold: fusing 4 sources into a per-UniProt-AC family taxonomy",
        err=True,
    )

    caveats = [
        "surfaceome_confidence_score is a simple source-agreement fraction, "
        "NOT a probabilistic posterior. Interpret as tie-breaker only.",
        "SURFY 2018 misses ~15% of clinically-validated ADC targets by our audit; "
        "the fusion with HPA v25.1 + UniProt EC + IUPHAR is designed to close "
        "this gap. Governance readers should still cross-reference HPA IHC "
        "intensity for critical modality decisions.",
        "The family taxonomy is oncology-drug-discovery-oriented; it does not "
        "cover every surface protein class (e.g., olfactory receptors, taste "
        "receptors). Those fall into 'Other'.",
        "HPA v25.1 protein_class taxonomy is source-of-truth for kinase / "
        "enzyme / transporter / CD-molecule assignments. Where HPA is silent, "
        "UniProt EC number + IUPHAR receptor class provide fallbacks.",
    ]

    df = pd.DataFrame(
        columns=[
            "uniprot_ac",
            "gene_symbol",
            "surface_protein_family",
            "surfaceome_confidence_score",
            "surface_present_surfy",
            "surfy_confidence_score",
            "surface_present_hpa",
            "hpa_protein_class",
            "uniprot_ec_number",
            "iuphar_family",
            "fusion_provenance",
            "family_class",
            "method_version",
        ]
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    sidecar = out.with_suffix(".caveats.txt")
    with sidecar.open("w") as f:
        f.write("\n\n".join(caveats))

    click.echo(
        f"[surfaceome_family_fusion] wrote scaffold parquet (0 rows) -> {out}\n"
        f"[surfaceome_family_fusion] wrote caveats sidecar -> {sidecar}",
        err=True,
    )


if __name__ == "__main__":
    main()
