"""gdc_somatic_hotspot.read — read functions for the MC3-aggregated hotspot Parquet.

This module is the *consumption* side of gdc_somatic_hotspot; cli.py is the
*production* side (runs the MC3 aggregation). Both live in the methods repo because
both are deterministic data operations.

Consumes the Parquet produced by `python -m methods.gdc_somatic_hotspot.cli`
(typically at data-products-cache/gdc_hotspots/{indication}.parquet or registered
as a derived manifest in data-catalog).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"

# Default cache location for aggregator outputs. Iter-2 may register these as
# proper derived manifests in data-catalog.
DEFAULT_CACHE_BASE = Path("/home/sagemaker-user/data-products-cache/gdc_hotspots")

# Indication → list of TCGA projects (same as cli.py — duplicated here to keep read.py
# importable without dragging in cli.py's click dependency).
INDICATION_TO_GDC_PROJECTS = {
    "COADREAD": ["TCGA-COAD", "TCGA-READ"],
    "PDAC": ["TCGA-PAAD"],
    "NSCLC": ["TCGA-LUAD", "TCGA-LUSC"],
    "SCLC": [],
    "GC": ["TCGA-STAD"],
}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _resolve_aggregate_path(indication: str, cache_base: Path = DEFAULT_CACHE_BASE) -> Path:
    """Locate the aggregated Parquet for an indication. Iter-1b uses a local cache
    location; iter-2 expects this to resolve through a data-catalog derived manifest."""
    return cache_base / f"{indication.lower()}_mc3_hotspots.parquet"


def read_hotspot_summary(
    target: str,
    indication: str,
    aggregate_path: Optional[Path] = None,
    top_n_hotspots: int = 5,
    top_n_cooccurring: int = 10,
) -> dict:
    """Query the MC3-aggregated hotspot Parquet for a target+indication.

    Returns dict matching the mutation-hotspot-frequency card_spec's summary_fields:
      overall_mutation_frequency, n_samples_in_indication, n_samples_mutated,
      hotspot_frequencies (list of {codon, frequency}), top_cooccurring_genes,
      top_mutually_exclusive_genes.

    `top_cooccurring_genes` and `top_mutually_exclusive_genes` are *iter-2 work*
    (requires co-mutation analysis across samples; iter-1b returns empty lists
    with a structured note).
    """
    import pyarrow.parquet as pq

    _ensure_aws_profile()
    if aggregate_path is None:
        aggregate_path = _resolve_aggregate_path(indication)

    if not aggregate_path.exists():
        return {
            "overall_mutation_frequency": None,
            "n_samples_in_indication": None,
            "n_samples_mutated": None,
            "hotspot_frequencies": [],
            "top_cooccurring_genes": [],
            "top_mutually_exclusive_genes": [],
            "_data_note": (
                f"No MC3 aggregate Parquet found at {aggregate_path}. "
                f"Run `python -m methods.gdc_somatic_hotspot.cli --indication {indication} "
                f"--out {aggregate_path}` to produce it."
            ),
        }

    # Predicate pushdown on (indication, gene_symbol) — both columns are present in the aggregate
    table = pq.read_table(
        aggregate_path,
        filters=[("indication", "=", indication), ("gene_symbol", "=", target)],
    )

    if table.num_rows == 0:
        return {
            "overall_mutation_frequency": 0.0,
            "n_samples_in_indication": None,
            "n_samples_mutated": 0,
            "hotspot_frequencies": [],
            "top_cooccurring_genes": [],
            "top_mutually_exclusive_genes": [],
            "_data_source": str(aggregate_path),
            "_data_note": f"target {target!r} has no rows in {indication} MC3 aggregate (no non-synonymous mutations)",
        }

    # Convert to pandas for easier processing
    df = table.to_pandas()
    # Gene-summary row is the one with hotspot_protein_change == null
    summary_row = df[df["hotspot_protein_change"].isnull()].iloc[0]
    hotspot_rows = df[df["hotspot_protein_change"].notnull()].sort_values(
        "hotspot_n_samples", ascending=False
    ).head(top_n_hotspots)

    return {
        "overall_mutation_frequency": float(summary_row["overall_mutation_frequency"]),
        "n_samples_in_indication": int(summary_row["n_samples_in_indication"]),
        "n_samples_mutated": int(summary_row["n_samples_mutated"]),
        "hotspot_frequencies": [
            {
                "protein_change": r["hotspot_protein_change"],
                "n_samples": int(r["hotspot_n_samples"]),
                "frequency": float(r["hotspot_frequency"]),
            }
            for _, r in hotspot_rows.iterrows()
        ],
        # Iter-1b: co-occurrence requires cross-sample co-mutation analysis;
        # the aggregate Parquet doesn't carry that information yet
        "top_cooccurring_genes": [],
        "top_mutually_exclusive_genes": [],
        "_data_source": str(aggregate_path),
        "_aggregate_path": str(aggregate_path),
        "_co_occurrence_note": "co-occurrence + mutual-exclusivity analysis is iter-2 work",
    }
