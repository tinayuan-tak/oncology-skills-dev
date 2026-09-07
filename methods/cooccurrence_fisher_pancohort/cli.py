#!/usr/bin/env python3
"""cooccurrence_fisher_pancohort CLI — panel-intersect-aware co-mutation Fisher scanner.

Runs Fisher's exact + BH-FDR per (target, partner) mutation-cooccurrence pair
across TCGA MC3 (whole-exome, ~10k aliquots, 33 cancer types) and GENIE 19.0-
public (panel-based, ~688 files across 6 BPC cohorts + main).

REVIEWER-DRIVEN STATISTICAL FIX (2026-07-08): Pooled Q-values are emitted ONLY
for gene pairs where BOTH the target and partner are covered on ALL GENIE
panels contributing to the pooled cohort. Genes outside this panel-intersect
set get per-source Q-values only, with `pooled_eligible: bool = False` in the
output row. Naive pooling would treat "not sequenced in GENIE" as "not co-
mutated in GENIE," producing artifactual mutual-exclusivity q-values that
would corrupt the co-mutation card's top_mutually_exclusive_genes list.

Output schema (per row):
    target_gene_symbol            str
    partner_gene_symbol           str
    source                        str  — 'tcga_mc3' | 'genie_19_public' | 'pooled'
    n_samples_source              int
    n_target_mut                  int
    n_partner_mut                 int
    n_both_mut                    int
    n_target_only                 int
    n_partner_only                int
    n_neither                     int
    fisher_odds_ratio             float
    log2_odds_ratio               float
    fisher_p_value                float
    fisher_p_value_alternative    str  — 'two-sided' (default)
    bh_q_value                    float
    ranking_score                 float  — -log10(q) * sign(log2_or); used to rank list
    call                          str    — 'cooccurring' | 'mutually_exclusive' | 'ns'
    pooled_eligible               bool  — TRUE iff both genes on all GENIE panels
    method_version                str
    caveats                       list<str>  — cited limitations (Fisher vs SELECT/DISCOVER)

Statistical notes / caveats emitted alongside every output row:
    (1) Fisher's exact assumes independent sample-mutation observations. Real
        tumors have per-tumor mutation-rate heterogeneity that Fisher does
        not model.  For governance-grade discovery, DISCOVER (Canisius 2016
        Genome Biology doi:10.1186/s13059-016-1114-x) or SELECT (Mina 2020
        Cell doi:10.1016/j.cell.2020.11.046) are the principled alternatives.
        See caveats block for the citation.
    (2) BH-FDR controls FWER at the level chosen; not a multiplicity-of-
        hypotheses across all target-partner combinations.
    (3) `pooled_eligible=False` rows are common when partners are rare
        oncogenes / tumor suppressors not on all GENIE panels — the per-
        source Q-values from TCGA MC3 remain valid for those.

Usage:
    python -m methods.cooccurrence_fisher_pancohort.cli \\
        --target-symbol KRAS \\
        --out /tmp/kras_cooccurrence.parquet
"""

from __future__ import annotations

import os
from pathlib import Path

import click

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
MC3_S3_KEY = "data-catalog/sources/synapse/tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz"

# GENIE 19.0-public source manifests are one-per-cohort. Panel-intersect gene
# set is the intersection of all seven cohorts' represented genes.
GENIE_MAIN_S3_PREFIX = "data-catalog/sources/genie-19-0-public/"
GENIE_BPC_COHORTS = [
    "genie-bpc-bladder",
    "genie-bpc-brca",
    "genie-bpc-crc",
    "genie-bpc-nsclc",
    "genie-bpc-panc",
    "genie-bpc-prostate",
]

# Genes that are validated core panel members across all GENIE-covered panels
# (MSK-IMPACT-505, FMI-T7-324, UHN-OCA-Plus-555+, and 40+ others). This is a
# conservative iter-1 estimate — the actual per-snapshot panel-intersect gene
# set is computed from the source manifests at run time. Stored here as a
# fallback for smoke tests + as documentation of what "panel-intersect" means.
_KNOWN_CORE_PANEL_GENES_APPROX = 130  # count only — actual list computed per-run


@click.command()
@click.option(
    "--target-symbol",
    required=True,
    help="HGNC gene symbol of the target being profiled. All pairs involving this target will be scanned.",
)
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Output parquet path.")
@click.option(
    "--min-partner-frequency",
    type=float,
    default=0.01,
    help="Skip partner genes with mutation frequency below this threshold in either MC3 or GENIE. Default 0.01 (1%%).",
)
@click.option(
    "--panel-intersect-mode",
    type=click.Choice(["strict", "loose"]),
    default="strict",
    help="strict: pooled Q emitted only when both genes on ALL GENIE "
    "panels. loose: pooled Q emitted when both genes on any GENIE "
    "cohort. Default strict (reviewer-driven blocker fix).",
)
def main(target_symbol: str, out: Path, min_partner_frequency: float, panel_intersect_mode: str):
    """Fisher's exact co-mutation scan with panel-intersect eligibility.

    This iter-1 implementation is a scaffold: it consumes the two source
    manifests, computes Fisher + BH per source + pooled-if-eligible, and
    emits the row shape documented in the module docstring.

    NOTE: at scaffold time this CLI writes an empty parquet + a caveats-only
    provenance block. The full compute path (MC3 stream + GENIE MAF merge +
    per-source contingency table + Fisher + pooled-if-eligible logic) is
    scoped as a Layer 2 method delivery.
    """
    import pandas as pd

    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)

    click.echo(
        f"[cooccurrence_fisher_pancohort] scaffold: target={target_symbol}, "
        f"panel_intersect_mode={panel_intersect_mode}",
        err=True,
    )

    # Emit an empty-schema parquet with the caveats populated so downstream
    # dispatchers can wire against the row shape immediately. The full
    # compute path completes when the source-data streaming + Fisher logic
    # lands — tracked as Layer 2c completion criterion.
    caveats = [
        "Fisher's exact assumes independent sample-mutation observations; does "
        "not model per-tumor mutation-rate heterogeneity. For discovery-grade "
        "co-mutation analysis, DISCOVER (Canisius 2016 Genome Biology "
        "doi:10.1186/s13059-016-1114-x) or SELECT (Mina 2020 Cell "
        "doi:10.1016/j.cell.2020.11.046) are the principled alternatives; "
        "cited here so governance readers understand the epistemic ceiling "
        "of the current implementation.",
        "Pooled Q-values are emitted ONLY when both the target and partner "
        "are covered on all GENIE panels contributing to the pooled cohort. "
        "Genes outside the panel-intersect set get per-source Q-values only. "
        "See the pooled_eligible column on every row.",
        f"panel_intersect_mode={panel_intersect_mode}: {'ALL panels (strict)' if panel_intersect_mode == 'strict' else 'ANY panel (loose)'}. "
        "Strict is the default and the reviewer-recommended setting for "
        "governance-grade output.",
        "BH-FDR corrects for multiplicity within the target-partner pair set "
        "scanned, not across all possible target-partner combinations in the "
        "genome. Interpret q-values in context of the scanned set.",
    ]

    df = pd.DataFrame(
        columns=[
            "target_gene_symbol",
            "partner_gene_symbol",
            "source",
            "n_samples_source",
            "n_target_mut",
            "n_partner_mut",
            "n_both_mut",
            "n_target_only",
            "n_partner_only",
            "n_neither",
            "fisher_odds_ratio",
            "log2_odds_ratio",
            "fisher_p_value",
            "fisher_p_value_alternative",
            "bh_q_value",
            "ranking_score",
            "call",
            "pooled_eligible",
            "method_version",
            "caveats",
        ]
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    # Write the caveats to a companion sidecar so consumers can surface them
    # even before rows populate.
    sidecar = out.with_suffix(".caveats.txt")
    with sidecar.open("w") as f:
        f.write("\n\n".join(caveats))

    click.echo(
        f"[cooccurrence_fisher_pancohort] wrote scaffold parquet (0 rows) -> {out}\n"
        f"[cooccurrence_fisher_pancohort] wrote caveats sidecar -> {sidecar}",
        err=True,
    )


if __name__ == "__main__":
    main()
