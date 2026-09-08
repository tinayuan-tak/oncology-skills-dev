"""surfaceome_cohort_ranking.read — per-indication whole-surfaceome ranking.

Consumer: surfaceome-cohort-ranking evidence card + skill (Phase F target-
scan hook). Emits per-target percentile-context lookup within the ranked
surfaceome for a given indication.

Wiring approach:
  - STREAMS the derived parquet (surfaceome-cohort-ranking-per-indication-v1)
    directly from S3 via a pyarrow S3FileSystem, pushing down the gene_symbol
    filter (the manifest's query_optimization.primary_filter_column) so only
    the requested target's rows are fetched — no whole-file download, no
    full-frame index build. Bucket/key resolve through the catalog
    (bucket_key_for), never a hardcoded path.
  - The upstream compute composes over all wired tumor-vs-normal sensitivity
    products, filters cells_supporting >= min(2, cells_ran), ranks per
    indication — this method is a per-target lookup into that result.
  - Absence discipline: a GENUINE product-object absence (NoSuchKey/404) ->
    data_unavailable; a transient / creds / broken-env failure propagates (it
    is never swallowed as a silent dead axis).

Runtime discipline: per-target row cache; definitive-absence latch.
"""

from __future__ import annotations

from typing import Optional

DERIVED_MANIFEST_ID = "surfaceome-cohort-ranking-per-indication-v1"

# Columns consumed downstream (_row_to_summary + the by-indication / best-percentile lookup).
# Projecting them keeps the streamed read to just what the summary needs.
_COLUMNS = [
    "indication",
    "gene_symbol",
    "cohort_rank_class",
    "tissue_rank",
    "tissue_percentile_rna",
    "tissue_percentile_protein",
    "rna_protein_concordance",
    "ranking_score",
    "cells_supporting",
    "cells_ran",
    "max_abs_log2fc",
    "surface_protein_family",
    "uniprot_ac",
]

# Per-target row cache (keyed by UPPER(gene_symbol)); caches ONLY successful reads. A transient
# read RAISES and is NOT cached, so a later call retries rather than latching the target to
# data_unavailable for the process lifetime.
_ROWS_CACHE: dict = {}
# Latched True ONLY on a definitive product-object absence (NoSuchKey/404), short-circuiting every
# later per-gene read in the process (mirrors the former whole-product negative cache).
_PRODUCT_ABSENT: bool = False


def _read_gene_rows(target: str) -> Optional[list]:
    """Streamed pushdown read of the ranking rows for ONE gene_symbol across indications.

    Returns a list of row dicts (possibly empty) on success, None on a GENUINE no-object
    (NoSuchKey/404), and RAISES on a transient/creds/broken-env failure (neither cached, so a
    later call retries). Mirrors methods/combo_drug_anchor.read._read_rows.
    """
    global _PRODUCT_ABSENT
    sym = (target or "").strip().upper()
    if _PRODUCT_ABSENT:
        return None
    if sym in _ROWS_CACHE:
        return _ROWS_CACHE[sym]
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(region="us-east-1"),
            filters=[("gene_symbol", "=", sym)],
            columns=_COLUMNS,
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # GENUINE absence (NoSuchKey/404 or a pyarrow FileNotFoundError) -> latch + None (honest
        # data_unavailable). A transient / creds / broken-env failure is NOT absence -> re-raise so
        # the caller's boundary records the real cause; not cached, so a later call still retries.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _PRODUCT_ABSENT = True
            return None
        raise
    rows = tbl.to_pylist()
    _ROWS_CACHE[sym] = rows
    return rows


def load_indication_ranking(indication: str) -> Optional[list]:
    """Streamed pushdown read of the WHOLE per-indication surfaceome ranking (every gene_symbol
    ranked in `indication`), for the standalone surfaceome-cohort-ranking skill's cohort-scan mode.

    Companion to _read_gene_rows: same S3 streaming + absence discipline, but pushes down on the
    `indication` column instead of gene_symbol (the product is gene_symbol-sorted, so this is an
    inherent full scan filtered to the indication — acceptable for a whole-cohort load). Returns a
    list of row dicts (possibly empty) on success, None on a GENUINE no-object (NoSuchKey/404), and
    RAISES on a transient/creds/broken-env failure (so the caller can retry / surface the real cause).
    """
    global _PRODUCT_ABSENT
    ind = (indication or "").strip().upper()
    if _PRODUCT_ABSENT:
        return None
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(region="us-east-1"),
            filters=[("indication", "=", ind)],
            columns=_COLUMNS,
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _PRODUCT_ABSENT = True
            return None
        raise
    return tbl.to_pylist()


def read_target_summary(target: str, indication: str = None) -> dict:
    sym = target.upper().strip()
    try:
        rows = _read_gene_rows(sym)
    except Exception as e:  # noqa: BLE001
        # Graceful PUBLIC boundary: _read_gene_rows already discriminates definitive-absence (-> None)
        # from a transient/creds/broken-env failure (-> raise, uncached) per the repo's absence
        # discipline; here we degrade that surfaced failure to a cause-named breadcrumb rather than
        # crash the whole card run on a read blip. (Returns a populated dict, not an empty result.)
        return _empty(f"cohort_ranking_load_failed: {type(e).__name__}: {e}")
    if rows is None:
        return _empty("cohort_ranking_data_unavailable")

    # rows are pre-filtered to this gene_symbol; index by indication for the exact-match lookup.
    gene_rows = [r for r in rows if str(r.get("indication", "")).strip().upper()]
    by_ind: dict[str, dict] = {}
    for r in gene_rows:
        by_ind[str(r.get("indication", "")).strip().upper()] = r

    # Indication-specific lookup
    if indication:
        ind = indication.upper().strip()
        row = by_ind.get(ind)
        if row is None:
            # Gene-only fallback (any indication)
            if not gene_rows:
                return _empty("target_not_in_ranking_any_indication")
            return _empty(f"target_not_in_ranking_for_{ind}")
        return _row_to_summary(row)

    # No indication -> return best-percentile row across all indications
    if not gene_rows:
        return _empty("target_not_in_any_ranking")
    best = max(gene_rows, key=lambda r: float(r.get("tissue_percentile_rna", 0) or 0))
    return _row_to_summary(best)


def _row_to_summary(row: dict) -> dict:
    return {
        "indication": str(row.get("indication", "")).upper(),
        "cohort_rank_class": row.get("cohort_rank_class", "below_25_percent"),
        "tissue_rank": row.get("tissue_rank"),
        "tissue_percentile_rna": row.get("tissue_percentile_rna"),
        "tissue_percentile_protein": row.get("tissue_percentile_protein"),
        "rna_protein_concordance": row.get("rna_protein_concordance", "no_protein"),
        "ranking_score": row.get("ranking_score"),
        "cells_supporting": row.get("cells_supporting"),
        "max_abs_log2fc": row.get("max_abs_log2fc"),
        "surface_protein_family": row.get("surface_protein_family"),
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "indication": None,
        "cohort_rank_class": "data_unavailable",
        "tissue_rank": None,
        "tissue_percentile_rna": None,
        "tissue_percentile_protein": None,
        "rna_protein_concordance": "no_protein",
        "ranking_score": None,
        "cells_supporting": None,
        "max_abs_log2fc": None,
        "surface_protein_family": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }
