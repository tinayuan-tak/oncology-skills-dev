#!/usr/bin/env python3
"""depmap_paralog_aggregator CLI — paralog-buffering signal from DepMap.

Fuses (a) DepMap PARIS 2024 paralog CRISPR screens (dual-KO Chronos effect
sizes for paralog pairs) + (b) Sanger Paralog Screen 2023 + (c) Ensembl
paralog annotation (ohnolog identification via WGD ancestry) into a per-gene
paralog-buffering signal.

Reviewer-driven design (2026-07-08): paralog buffering (Dede 2020, De Kegel
2021, Ito 2021) is a distinct dependency-hardening signal from co-mutation.
The plan originally folded this under differentiation-landscape (Phase E); the
content reviewer flagged this as a category error and recommended a dedicated
Phase C-adjacent card. This method emits the categorical
`paralog_buffering_class` field that consumer cards + rules consume.

Output schema (per row):
    target_gene_symbol                str
    target_uniprot_ac                 str
    functional_paralogs               list<struct>
                                      # per struct:
                                      #   partner_symbol: str
                                      #   partner_uniprot_ac: str
                                      #   ohnolog_flag: bool
                                      #   ensembl_paralog_type: str
                                      #   dep_single_ko_target_only: float
                                      #   dep_single_ko_partner_only: float
                                      #   dep_dual_ko_paired: float
                                      #   dep_delta_paired_vs_max_single: float
                                      #   buffering_strength: str
                                      #                       # 'strong' | 'partial' | 'none'
                                      #   source_screen: str  # 'PARIS_2024' | 'Sanger_2023'
    n_paralogs_annotated              int
    n_paralogs_functionally_buffering int
    paralog_buffering_class           str  — 'strong' | 'partial' | 'none' | 'no_paralog' | 'data_unavailable'
    method_version                    str

Reviewer note: The `dep_delta_paired_vs_max_single` field measures the
excess dependency of the paired-KO condition vs the max of the two single-
KO effects. Positive delta = synthetic lethality between paralogs =
buffering signal. Cutoffs for strong/partial are calibrated against
published SL screen hits (SMARCA4-SMARCA2, ARID1A-ARID1B, etc.).

Usage:
    python -m methods.depmap_paralog_aggregator.cli \\
        --out /tmp/paralog_buffering.parquet
"""
from __future__ import annotations

import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DEPMAP_PARALOG_S3_PREFIX = "data-catalog/sources/depmap-consortium-25q1v2-paralogs/"
DEPMAP_25Q2_PARALOG_S3_PREFIX = "data-catalog/sources/depmap-consortium-25q2-paralogs/"
ENSEMBL_PARALOG_S3_PREFIX = "data-catalog/sources/ensembl-coords-release-116-snapshot-2026-06-22/"


@click.command()
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output parquet path.")
def main(out: Path):
    """Aggregate DepMap PARIS + Sanger paralog screens + Ensembl paralog annotation.

    iter-1 SCAFFOLD: row schema + caveats sidecar; full compute defers to a
    Layer 2 delivery follow-up.
    """
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)

    click.echo(
        f"[depmap_paralog_aggregator] scaffold: PARIS + Sanger + Ensembl paralog fusion",
        err=True,
    )

    caveats = [
        "Paralog buffering is a SYNTHETIC-LETHAL signal — the target and its "
        "paralog are dispensable individually but essential in combination. This is "
        "a HARDENING signal (single-agent inhibition may fail) that is distinct "
        "from co-mutation cooccurrence.",
        "PARIS 2024 covers ~1,500 human paralog pairs across ~60 cell lines. Sanger "
        "2023 covers ~700 pairs across ~50 lines. Pairs NOT screened in either "
        "return paralog_buffering_class='data_unavailable'.",
        "Ohnolog flag (whole-genome-duplication ancestry) is stricter than "
        "Ensembl 'paralog_type' — ohnologs share cell-type-specific gene regulatory "
        "context that non-ohnolog paralogs may not. Consumers may filter to "
        "ohnolog_flag=True for the highest-confidence buffering candidates.",
        "The dep_delta_paired_vs_max_single cutoffs (strong: delta > 0.5, partial: "
        "0.2-0.5) are calibrated against published SL screen hits (SMARCA4/2, "
        "ARID1A/B, MAGOH/MAGOHB). Cutoffs may be tuned per-lineage in iter-2.",
    ]

    df = pd.DataFrame(columns=[
        "target_gene_symbol", "target_uniprot_ac", "functional_paralogs",
        "n_paralogs_annotated", "n_paralogs_functionally_buffering",
        "paralog_buffering_class", "method_version",
    ])

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    sidecar = out.with_suffix(".caveats.txt")
    with sidecar.open("w") as f:
        f.write("\n\n".join(caveats))

    click.echo(
        f"[depmap_paralog_aggregator] wrote scaffold parquet (0 rows) -> {out}\n"
        f"[depmap_paralog_aggregator] wrote caveats sidecar -> {sidecar}",
        err=True,
    )


if __name__ == "__main__":
    main()
