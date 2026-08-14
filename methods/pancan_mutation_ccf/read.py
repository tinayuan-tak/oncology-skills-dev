"""pancan_mutation_ccf.read — card-side reader for the per-(gene, indication) clonality product.

The aggregator (cli.py) materializes per-indication clonality parquets (one row per mutated gene);
this returns the per-(gene, indication) summary the target-clonality card consumes. Graceful
data_unavailable when the gene is not recurrently mutated in-indication (below MIN_MUTANT_SAMPLES →
not in the product) or the product is not materialized for the indication.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

# Per-indication materialized clonality product (mirrors gdc_somatic_hotspot's per-indication cache).
DEFAULT_CACHE = Path.home() / ".cache" / "framework-pancan-clonality"

_UNAVAILABLE = {
    "clonality_class": "data_unavailable",
    "clonal_fraction": None,
    "median_ccf": None,
    "n_mutant_samples": 0,
    "evidence_tier": "inferred_diploid",
}


@lru_cache(maxsize=32)
def _load_indication_table(indication: str, product_path: "Optional[str]" = None):
    import pandas as pd
    path = Path(product_path) if product_path else (DEFAULT_CACHE / f"{indication}-clonality.parquet")
    if not path.exists():
        return None
    return pd.read_parquet(path)


def read_clonality(gene: str, indication: str, product_path: "Optional[str]" = None) -> dict:
    """Per-(gene, indication) clonality summary for the target-clonality card. VERDICT-INERT signal."""
    df = _load_indication_table(indication, product_path)
    if df is None or df.empty:
        return dict(_UNAVAILABLE, _missing_reason=f"no clonality product materialized for {indication}")
    hit = df[df["gene_symbol"] == gene]
    if hit.empty:
        return dict(_UNAVAILABLE,
                    _missing_reason=f"{gene} not recurrently mutated in {indication} (below floor)")
    row = hit.iloc[0]
    return {
        "clonality_class": row["clonality_class"],
        "clonal_fraction": None if row["clonal_fraction"] is None else float(row["clonal_fraction"]),
        "median_ccf": None if row["median_ccf"] is None else float(row["median_ccf"]),
        "n_mutant_samples": int(row["n_mutant_samples"]),
        "evidence_tier": row["evidence_tier"],
    }
