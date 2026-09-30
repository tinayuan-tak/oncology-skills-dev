"""exon_window.read — S3 boundary for the per-exon tumor-vs-normal window (E5).

Reads tcga-gtex-exon-tpm-quantiles-v1 (per exon_id × source × group log2(exon-TPM+1) quantiles,
surfaceome-scoped, sorted/pruned on gene_id). Pushdown by gene_id (the SORT KEY) → all exon rows
for the gene, then classify.compute_exon_window_from_rows reduces to the exon-window summary.

Pushdown discipline (mirrors tcga_gtex_tpm_quantiles.read): resolve the target symbol to its
unversioned Ensembl gene_id(s) via the shared id-map resolver and push down on gene_id — the
product's sort_key / primary_filter_column — so the read prunes row-groups instead of scanning
the whole 427 MB file, and a non-unique HGNC symbol can't pull exons from two ENSG loci. Fall back
to a gene_symbol pushdown (with a breadcrumb) ONLY when symbol→id resolution is unavailable.

Cache discipline (mirrors structure_features_static): cache ONLY successful reads in a module-level
dict. A transient read failure returns None WITHOUT caching, so a later call retries — an @lru_cache
over the raw read would memoize that None permanently, poisoning the target to data_unavailable for
the whole process lifetime after one S3 blip (silently, mid-batch)."""

from __future__ import annotations

from typing import Optional

from onc_methods.catalog_query.read import bucket_key_for

from . import classify as _classify

PRODUCT_MANIFEST_ID = "tcga-gtex-exon-tpm-quantiles-v1"
DEFAULT_AWS_PROFILE = "cbg"
METHOD_VERSION = _classify.METHOD_VERSION

# Caches ONLY successful reads as (DataFrame, meta) keyed by UPPER(target). A transient read
# failure is NOT cached (returns None), so a later call retries instead of poisoning the process.
_ROWS_CACHE: dict = {}


def _symbol_to_gene_ids(target: str) -> Optional[list]:
    """Resolve a gene symbol to unversioned Ensembl gene_id(s) via the SHARED id-map resolver
    (reused verbatim from tcga_gtex_tpm_quantiles — no duplicate id-map). None if unavailable.

    Imported lazily inside the function (mirrors tumor_presence_controls' reuse of the sibling
    _symbol_to_ensembl_ids) so importing this module does not eagerly load the sibling's
    manifest-resolution module-level constants."""
    from onc_methods.tcga_gtex_tpm_quantiles.read import _symbol_to_ensembl_ids

    return _symbol_to_ensembl_ids(target)


def _read_exon_rows_cached(target: str):
    """(DataFrame, meta) for a gene's exon quantile rows. DataFrame is None ONLY on read failure
    (NOT cached, so a later call retries); successful reads (incl. an empty frame for an absent
    gene) are cached. `meta` carries the pushdown key + a fallback breadcrumb if symbol→gene_id
    resolution was unavailable and we fell back to a gene_symbol pushdown."""
    sym = (target or "").strip().upper()
    if sym in _ROWS_CACHE:
        return _ROWS_CACHE[sym]
    import os

    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
    meta: dict = {}
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        s3fs = fs.S3FileSystem(region="us-east-1")
        # Resolve symbol -> gene_id(s) and push down on the SORT KEY. A resolver failure is a
        # transient/absence signal, not fatal: fall back to a gene_symbol pushdown + breadcrumb.
        try:
            gene_ids = _symbol_to_gene_ids(sym)
        except Exception as e:  # noqa: BLE001
            gene_ids = None
            meta["_gene_id_resolution_error"] = f"{type(e).__name__}: {e}"
        if gene_ids:
            filters = [("gene_id", "in", list(gene_ids))]
            meta["pushdown_key"] = "gene_id"
        else:
            filters = [("gene_symbol", "==", sym)]
            meta["pushdown_key"] = "gene_symbol"
            meta["_pushdown_fallback"] = (
                "symbol->gene_id resolution unavailable; fell back to a gene_symbol pushdown "
                "(no row-group pruning; non-unique-HGNC-symbol correctness risk)."
            )
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=s3fs, filters=filters)
        df = tbl.to_pandas()
    except Exception:  # noqa: BLE001
        return None, {"pushdown_key": None}  # NOT cached — a transient failure must retry.
    result = (df, meta)
    _ROWS_CACHE[sym] = result
    return result


def read_exon_rows(target: str):
    """All exon quantile rows for a gene (pushdown on gene_id, the sort key; gene_symbol fallback).
    None if unreadable. Shape-preserving wrapper over _read_exon_rows_cached."""
    return _read_exon_rows_cached(target)[0]


def read_exon_window(target: str, indication: str, modality: str = "bite_tce") -> dict:
    """Reader entry the card dispatcher calls: per-gene exon-window summary for the indication at
    the modality's essential-tissue tier (bite_tce=1.0/adc=5.0/antibody=10.0)."""
    tier = _classify.MODALITY_TIER_THRESHOLD.get(str(modality).lower(), _classify.MODALITY_TIER_THRESHOLD["bite_tce"])
    rows, meta = _read_exon_rows_cached(target)
    if rows is None:
        out = _classify._empty("data_unavailable", "exon product unreadable (infra failure)")
        out["_live_read_error"] = "exon_tpm_quantiles_read_failed"
    else:
        out = _classify.compute_exon_window_from_rows(rows, indication, tier_threshold_tpm=tier)
    # Surface the pushdown-fallback breadcrumb(s) so a symbol-only read is auditable (additive keys).
    if meta.get("_pushdown_fallback"):
        out["_pushdown_fallback"] = meta["_pushdown_fallback"]
    if meta.get("_gene_id_resolution_error"):
        out["_gene_id_resolution_error"] = meta["_gene_id_resolution_error"]
    out["modality"] = str(modality).lower()
    out["target"] = target
    out["indication"] = str(indication).upper().strip()
    out["method_version"] = METHOD_VERSION
    return out
