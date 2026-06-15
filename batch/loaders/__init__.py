"""Expression-source loader interface.

The loader Protocol defined here lets `batch/run_global_dge.py` consume any
canonical TCGA/GTEx source (GDC, UCSC Xena/Toil, recount3, OncoLand, …)
without changing its own code. The implementation choice is gated by the
configs/{indication}.yaml `source` block; the orchestrator dispatches via
`get_loader(name)`.

When a new source is selected, drop a new file in this directory implementing
the Protocol, register it in REGISTRY, and update the indication config —
no edits to run_global_dge.py.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class ExpressionSource(Protocol):
    """A canonical source of TCGA-tumor + matched-normal expression.

    Implementations live as siblings in this package (e.g. `oncoland.py`,
    `gdc.py`, `xena_toil.py`, `recount3.py`). The orchestrator interacts
    only through this Protocol — it does NOT import implementations directly.
    """

    name: str
    """Stable slug, e.g. 'oncoland-b38_gc33', 'gdc-dr42', 'xena-toil-2025'."""

    catalog_ref: str
    """data-catalog manifest id this source resolves to (e.g. 'tcga-gdc-dr42').
    Goes verbatim into evidence.json provenance.catalog_refs."""

    def load_expression_matrix(
        self, indication: str, samples: list[str] | None = None
    ) -> pd.DataFrame:
        """Return a gene × sample matrix of log2(TPM+1) (or equivalent).

        Index: gene symbols (HGNC). Columns: sample_id strings.
        If samples is given, restrict columns to that list (subset). If None,
        return all available samples.
        """
        ...

    def tumor_samples(self, indication: str) -> list[str]:
        """Sample IDs for the tumor cohort of this indication."""
        ...

    def adjacent_normal_samples(self, indication: str) -> list[str]:
        """Sample IDs for matched adjacent-normal samples (TCGA -11 barcodes
        for TCGA sources). Empty list if the source does not provide them."""
        ...

    def gtex_normal_samples(self, indication: str) -> list[str]:
        """Sample IDs for the GTEx normal-tissue cohort matched to this
        indication (e.g. colon for CRC). Empty list if the source does not
        include GTEx (e.g. GDC)."""
        ...


# Loader registry — populated as concrete implementations are added.
# Key is the `source.name` used in configs/{indication}.yaml.
REGISTRY: dict[str, type[ExpressionSource]] = {}


def register(name: str):
    """Decorator: register an ExpressionSource implementation under a name."""
    def deco(cls):
        REGISTRY[name] = cls
        return cls
    return deco


def get_loader(name: str) -> ExpressionSource:
    """Resolve a loader by name. Raises with a helpful message if not registered."""
    if name not in REGISTRY:
        available = ", ".join(sorted(REGISTRY)) or "(none registered yet)"
        raise ValueError(
            f"Expression source '{name}' is not registered. "
            f"Available: {available}. "
            "Add an implementation in batch/loaders/ and decorate with "
            "@register('your-name')."
        )
    return REGISTRY[name]()
