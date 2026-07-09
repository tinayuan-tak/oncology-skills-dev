#!/usr/bin/env python3
"""surfaceome_cohort_ranking CLI — per-tissue whole-surfaceome effect-size ranking.

Composes a per-indication ranking of all SURFY-high-confidence surface proteins
by tumor-vs-normal effect size, filtered to comparator-robust hits
(cells_supporting >= 3). Reads the 4-cell DESeq2 sensitivity products at
s3://onc-compbio/data-catalog/derived/{indication}-dge-tumor-vs-normal-sensitivity-v1/
+ joins with surfaceome-family-classification for surface-only filter.

Reviewer-driven design (2026-07-08):
    - Ranking basis: log2FC × -log10(q) per-cell, aggregated across cells A/C
      via cells_supporting-weighted mean. Prevents low-effect-size but low-
      variance genes from dominating.
    - Filter: cells_supporting >= 3 (target must be robust to at least 3 of the
      4 comparator/batch-correction combinations).
    - Output is per-indication (not per-target) — target-profile joins against
      this on-demand for percentile-context lookup.

Output schema (per row):
    indication                       str   — e.g. 'COADREAD'
    gene_symbol                      str
    uniprot_ac                       str
    surface_protein_family           str   — from surfaceome-family-classification
    cells_supporting                 int   — 3 or 4
    max_abs_log2fc                   float
    ranking_score                    float — cells_supporting-weighted log2FC×-log10(q)
    tissue_rank                      int   — 1-N within this indication
    tissue_percentile_rna            float — 100.0 = best in cohort
    tissue_percentile_protein        float — 100.0 = best; NaN when no CPTAC coverage
    rna_protein_concordance          str   — 'agreement' | 'protein_only' | 'rna_only' | 'disagreement' | 'no_protein'
    cohort_rank_class                str   — 'top_1_percent' | 'top_5' | 'top_25' | 'below_25'
    method_version                   str

Usage:
    python -m methods.surfaceome_cohort_ranking.cli \\
        --indication COADREAD \\
        --out /tmp/coadread_surfaceome_ranking.parquet

    # Or all-indication mode:
    python -m methods.surfaceome_cohort_ranking.cli \\
        --indication all \\
        --out /tmp/all_indications_surfaceome_ranking.parquet
"""
from __future__ import annotations

import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
SENSITIVITY_S3_PREFIX = "data-catalog/derived/"

# 18 wired indications with 4-cell DESeq2 sensitivity products
WIRED_INDICATIONS = [
    "COAD", "READ", "COADREAD", "LUAD", "LUSC", "BRCA", "PAAD",
    "SKCM", "STAD", "PRAD", "OV", "KIRC", "GBM", "LGG",
    "BLCA", "LIHC", "CESC", "ESCA", "HNSC",
]


@click.command()
@click.option("--indication", required=True,
              help="Indication code (e.g. COADREAD). 'all' iterates over all "
                   "18 wired indications.")
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output parquet path (one file per indication, or partitioned "
                   "when --indication=all).")
@click.option("--min-cells-supporting", type=int, default=3,
              help="Cells_supporting filter threshold. Default 3 (reviewer-"
                   "recommended). Set to 4 for strict all-cells-agree ranking.")
def main(indication: str, out: Path, min_cells_supporting: int):
    """Compose per-tissue whole-surfaceome ranking.

    iter-1 SCAFFOLD: row schema + caveats sidecar; full compute defers to a
    Layer 2 delivery follow-up (sensitivity parquet reads + surfaceome join +
    percentile computation + concordance flag).
    """
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)

    click.echo(
        f"[surfaceome_cohort_ranking] scaffold: indication={indication}, "
        f"min_cells_supporting={min_cells_supporting}",
        err=True,
    )

    caveats = [
        "Rankings are cells_supporting-filtered — surface proteins that showed "
        "tumor-vs-normal significance in < 3 of the 4 DESeq2 comparator cells "
        "are excluded. This kills the top-of-list false positives seen in the "
        "dashboard's single-limma-run version.",
        "tissue_percentile_protein is NaN when the indication has no CPTAC "
        "cohort. For those tissues, downstream consumers should treat "
        "rna_protein_concordance='no_protein' as data-unavailable, not as a "
        "negative signal.",
        "The ranking is a REPRODUCIBLE DERIVED PRODUCT keyed on the underlying "
        "sensitivity-v1 manifest md5s + the SURFY XLSX md5 + the CPTAC snapshot "
        "md5. A refresh of any upstream triggers a new versioned ranking output.",
        "Cross-indication ranking patterns (a surface protein's rank across "
        "multiple indications) are arguably more informative for portfolio "
        "decisions than per-indication ranking. iter-1 emits per-indication only; "
        "cross-indication rank summary is a documented iter-2 backlog item.",
    ]

    df = pd.DataFrame(columns=[
        "indication", "gene_symbol", "uniprot_ac",
        "surface_protein_family", "cells_supporting",
        "max_abs_log2fc", "ranking_score",
        "tissue_rank", "tissue_percentile_rna",
        "tissue_percentile_protein", "rna_protein_concordance",
        "cohort_rank_class", "method_version",
    ])

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    sidecar = out.with_suffix(".caveats.txt")
    with sidecar.open("w") as f:
        f.write("\n\n".join(caveats))

    click.echo(
        f"[surfaceome_cohort_ranking] wrote scaffold parquet (0 rows) -> {out}\n"
        f"[surfaceome_cohort_ranking] wrote caveats sidecar -> {sidecar}",
        err=True,
    )


if __name__ == "__main__":
    main()
