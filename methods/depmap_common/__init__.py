"""depmap_common — shared loaders + utilities for DepMap-consuming methods.

Consolidates access to small metadata tables (Model.csv, ModelCondition.csv,
sample_info.csv) behind cached loaders so multiple methods invoked in the same
Python process (e.g. a compose_dashboard run) share a single fetch per file
instead of each method independently re-fetching.

Public API:
    from methods.depmap_common import (
        load_model_csv,           # DepMap 26Q1 Model.csv (ModelID + lineage)
        load_model_condition_csv, # DepMap 26Q1 ModelCondition.csv (MC_ID → ModelID bridge)
        load_rnai_sample_info,    # DepMap 26Q1 RNAi sample_info.csv (CCLE_ID metadata)
    )

All loaders are @lru_cache-wrapped: first call fetches from S3 (with local-cache
fallback), subsequent calls in the same process return the cached pandas
DataFrame. Cache is process-lifetime; a new Python invocation re-fetches.

Tier-2 (parquet precompute) is a separate module —
methods.depmap_common.parquet — that provides pyarrow.dataset accessors for the
large numeric matrices (CRISPRGeneEffect, TPM, CN, DEMETER2, MAF).
"""

__version__ = "0.1.0"

from .loaders import (
    clear_all_caches,
    load_model_condition_csv,
    load_model_csv,
    load_rnai_sample_info,
    model_metadata_by_id,
)

__all__ = [
    "load_model_csv",
    "load_model_condition_csv",
    "load_rnai_sample_info",
    "model_metadata_by_id",
    "clear_all_caches",
]
