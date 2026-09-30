"""tahoe_drug_perturbation.read — v2 library entry for live-mode reads.

Per-target Tahoe drug-perturbation MoA facet (VERDICT-INERT). Reads the gene-keyed derived product
tahoe-drug-perturbation-per-gene-v1 via pyarrow S3 predicate-pushdown on gene_name. No
scanpy/anndata at framework runtime — the single-cell machinery lived in the data-catalog emit step;
this reads the already-distilled significant-DE parquet.

On unreachable product or missing target, returns a dict with tahoe_perturbation_class in
{data_unavailable, not_measured} so the framework's graceful-degradation contract holds.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_tahoe_drug_perturbation(target: str, indication: Optional[str] = None) -> dict:
    """Per-target Tahoe drug-perturbation summary — pan-cancer, indication-independent.

    `indication` is accepted for the framework's CARD_DISPATCHERS contract but NOT consumed:
    the product is gene-keyed (which drugs move this gene's expression, in which cancer lines).
    """
    return _cli.build_summary(target, indication)
