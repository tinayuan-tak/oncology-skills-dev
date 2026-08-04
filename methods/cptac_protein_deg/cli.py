#!/usr/bin/env python3
"""cptac_protein_deg CLI — CPTAC protein tumor-vs-normal DEG per cohort.

Runs per-gene protein-level tumor-vs-normal differential-expression across the
CPTAC-PDC snapshot (10 cohorts: BRCA, CCRCC, COAD, GBM, HNSCC, LSCC, LUAD, OV,
PDAC, UCEC). Emits per-cohort effect sizes + BH-corrected q-values + median
log2-abundance in tumor vs. normal.

Reviewer-driven design (2026-07-08): the plan's original 7-card scope was RNA-
forward with a protein-shaped hole; adding CPTAC protein-level cards makes the
target-profile framework governance-defensible for ADC/TCE decisions where
protein-level presence is the primary evidence layer, not RNA. The tumor-antigen
dashboard's most novel content (EGFR CPTAC protein tumor-vs-normal effect
sizes across 10 cohorts) is what this method's output reproduces + extends.

Output schema (per row):
    cohort                              str  — 'BRCA' | 'CCRCC' | ... | 'PDAC'
    gene_symbol                         str
    uniprot_ac                          str
    n_tumor_samples                     int
    n_normal_samples                    int
    protein_median_log2_tumor           float
    protein_median_log2_normal          float
    protein_effect_size                 float  — median_log2_tumor - median_log2_normal
    protein_effect_size_pooled_sd       float
    protein_p_value                     float  — MSstatsTMT groupComparisonTMT (limma-eBayes moderated t)
    protein_bh_q_value                  float
    protein_expression_class            str    — 'strong_up' | 'modest_up' | 'ns' | 'modest_down' | 'strong_down' | 'not_detected'
    stat_test_used                      str    — 'msstatstmt_limma_ebayes_moderated' | 'skipped_low_n'
    method_version                      str

Reviewer note: Slaga et al 2018 (Sci Transl Med) established that TCE viability
requires >1,000 copies/cell surface expression — CPTAC's absolute intensity is
NOT that measurement, but IS the best public proxy for tumor-relative protein
abundance. Downstream surface-abundance-density card converts CPTAC intensity
to an estimated copies-per-cell class using HPA IHC intensity as an anchor.

Usage:
    python -m methods.cptac_protein_deg.cli \\
        --cohort BRCA --out /tmp/cptac_brca_deg.parquet
"""
from __future__ import annotations

import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
CPTAC_S3_PREFIX = "data-catalog/sources/cptac-pdc/snapshot-2026-07-01/"

CPTAC_COHORTS = [
    "BRCA", "CCRCC", "COAD", "GBM", "HNSCC",
    "LSCC", "LUAD", "OV", "PDAC", "UCEC",
]


@click.command()
@click.option("--cohort", type=click.Choice(CPTAC_COHORTS + ["all"]), default="all",
              help="CPTAC cohort code. 'all' iterates over all 10 cohorts.")
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output parquet path.")
def main(cohort: str, out: Path):
    """CPTAC protein tumor-vs-normal DEG scanner.

    iter-1 SCAFFOLD: row schema + caveats sidecar; full compute defers to a
    Layer 2 delivery follow-up (PDC GraphQL query + protein-abundance matrix
    parse + Welch/Wilcoxon + BH-FDR).
    """
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)

    click.echo(
        f"[cptac_protein_deg] scaffold: cohort={cohort}",
        err=True,
    )

    caveats = [
        "CPTAC-PDC declared md5 + size are advisory (stale) per the source manifest; "
        "downstream compute must trust streamed md5, not declared. See the cptac-pdc-* "
        "manifest for the ingest-time discipline.",
        "Protein abundance is measured by TMT-labeled mass-spec; ratios are batch-"
        "corrected per CPTAC pipeline. Absolute intensity is NOT copies-per-cell — "
        "downstream surface-abundance-density card must derive that separately using "
        "HPA IHC intensity as an anchor.",
        "Some CPTAC cohorts (GBM, OV, PDAC) have small normal-sample sets (n<20). "
        "stat_test_used='skipped_low_n' when < 5 samples per arm; consumers should "
        "treat those rows as data_unavailable for statistical claims.",
        "The 10 CPTAC cohorts do NOT cover all TCGA indications — CPTAC lacks BLCA, "
        "SKCM, KIRC, STAD, ESCA, LIHC, CESC, PRAD, CHOL, ACC. For those indications, "
        "the RNA-based tumor-rna-vs-adjacent card remains the primary presence "
        "signal.",
    ]

    df = pd.DataFrame(columns=[
        "cohort", "gene_symbol", "uniprot_ac",
        "n_tumor_samples", "n_normal_samples",
        "protein_median_log2_tumor", "protein_median_log2_normal",
        "protein_effect_size", "protein_effect_size_pooled_sd",
        "protein_p_value", "protein_bh_q_value",
        "protein_expression_class", "stat_test_used", "method_version",
    ])

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    sidecar = out.with_suffix(".caveats.txt")
    with sidecar.open("w") as f:
        f.write("\n\n".join(caveats))

    click.echo(
        f"[cptac_protein_deg] wrote scaffold parquet (0 rows) -> {out}\n"
        f"[cptac_protein_deg] wrote caveats sidecar -> {sidecar}",
        err=True,
    )


if __name__ == "__main__":
    main()
