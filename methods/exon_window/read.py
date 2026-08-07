"""exon_window.read — S3 boundary for the per-exon tumor-vs-normal window (E5).

Reads tcga-gtex-exon-tpm-quantiles-v1 (per exon_id × source × group log2(exon-TPM+1) quantiles,
surfaceome-scoped, sorted on gene_id). Pushdown by gene_symbol → all exon rows for the gene, then
classify.compute_exon_window_from_rows reduces to the exon-window summary."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for
from . import classify as _classify

PRODUCT_MANIFEST_ID = "tcga-gtex-exon-tpm-quantiles-v1"
DEFAULT_AWS_PROFILE = "cbg"
METHOD_VERSION = _classify.METHOD_VERSION


@lru_cache(maxsize=256)
def read_exon_rows(target: str):
    """All exon quantile rows for a gene (pushdown on gene_symbol). None if unreadable."""
    import os
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        s3fs = fs.S3FileSystem(region="us-east-1")
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=s3fs,
                            filters=[("gene_symbol", "==", target.strip().upper())])
        return tbl.to_pandas()
    except Exception:  # noqa: BLE001
        return None


def read_exon_window(target: str, indication: str, modality: str = "bite_tce") -> dict:
    """Reader entry the card dispatcher calls: per-gene exon-window summary for the indication at
    the modality's essential-tissue tier (bite_tce=1.0/adc=5.0/antibody=10.0)."""
    tier = _classify.MODALITY_TIER_THRESHOLD.get(str(modality).lower(),
                                                 _classify.MODALITY_TIER_THRESHOLD["bite_tce"])
    rows = read_exon_rows(target)
    if rows is None:
        out = _classify._empty("data_unavailable", "exon product unreadable (infra failure)")
        out["_live_read_error"] = "exon_tpm_quantiles_read_failed"
    else:
        out = _classify.compute_exon_window_from_rows(rows, indication, tier_threshold_tpm=tier)
    out["modality"] = str(modality).lower()
    out["target"] = target
    out["indication"] = str(indication).upper().strip()
    out["method_version"] = METHOD_VERSION
    return out
