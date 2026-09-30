"""procan_protein_abundance.cli — ProCan-DepMapSanger DIA/SWATH cell-line protein-abundance loaders.

Second-platform sibling of depmap_protein_abundance (Gygi TMT MS). Reads the derived long/tidy
product `procan-cellline-protein-abundance-per-protein-v1`
(uniprot_base / uniprot_id / model_id[SIDM] / log_abundance) via per-protein pyarrow column-pushdown
(filters=[("uniprot_base","=",accession)] reads ~1 row group), and emits the SAME
cellline-protein-abundance card summary as the Gygi reader.

It REUSES (does not fork) the Gygi sibling's shape + classifier + symbol->UniProt path:
  - compute_summary / classify_protein_abundance  (identical summary shape + distribution vocab)
  - _symbol_to_uniprot_map                          (the general uniprot_hugo map — accessions are
    universal UniProt ids, so they join ProCan's uniprot_base directly; the Gygi target_resolution
    sidecar is Gygi-only and cannot resolve into the ProCan panel)
and methods.percentile_null for the all-gene percentile.

Documented platform differences (NOT forks of the Gygi logic):
  * abundance column is `log_abundance` (DIA-NN MaxLFQ log-intensity), not `log2_abundance`; the
    emitted field keeps the sibling's `*_log2_abundance_panel` NAME for cross-platform field parity
    (verdict-inert display), with the scale noted in the card caveat.
  * the cell-line axis is Sanger SIDM ids with NO DepMap-ModelID / OncotreeLineage crosswalk yet, so
    per-lineage stratification is unavailable (per_lineage_stats == []); a SIDM->ACH map is a v2.
  * the product ships NO all-protein median-null sidecar (unlike Gygi), so the null is computed
    on-read: one cached 2-column scan + groupby-median. It backs allgene_percentile AND the
    panel-relative broadly_high cutoff (H3 discipline: broadly_high is decided relative to the
    all-protein panel, never the target's own spread).

Absence discipline (mirror of the Gygi reader): a symbol that resolves to no accession, or an
accession absent from the ProCan panel, is `data_unavailable` (a coverage gap, NOT a measured
negative). A transient S3/read failure PROPAGATES (never memoized) so read.py surfaces an honest
_live_read_error.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Optional

from onc_methods.catalog_query.read import bucket_key_for, load_manifest

# Reuse the Gygi sibling's summary shape + classifier + symbol->UniProt path (single source of truth).
from onc_methods.depmap_protein_abundance.cli import (  # noqa: F401
    _symbol_to_uniprot_map,
    classify_protein_abundance,
    compute_summary,
)
from onc_methods.percentile_null import DEFAULT_CUTOFFS, classify_percentile, percentile_rank
from onc_methods.target_id_sidecar import ensure_aws_profile

METHOD_VERSION = "0.1.0"
DERIVED_PRODUCT_MANIFEST_ID = "procan-cellline-protein-abundance-per-protein-v1"
PROTEIN_ABUNDANCE_SOURCE = "procan_dia_swath"

# all-gene percentile-class cutoffs. F6: derive from onc_methods.percentile_null.DEFAULT_CUTOFFS (the same
# source the Gygi sibling uses via classify_percentile(pct) with no arg) instead of hard-copying the
# literals, so a future change to DEFAULT_CUTOFFS cannot silently drift ProCan out of parity. Values
# are identical today {top_1pct:99, top_decile:90, bottom_decile:10} — this is behavior-inert.
_PCT_CUTOFFS = dict(DEFAULT_CUTOFFS)


# --- F5: shared S3FileSystem singleton -------------------------------------------------------------
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (F5). Both cached loaders below share ONE instance
    instead of constructing a fresh `pafs.S3FileSystem()` inline per loader, and this is the single
    place to add retry/connect-timeout/region hardening later (parity with tcga_gtex_expression_
    distribution.read._get_s3fs). Double-checked locking so concurrent first-callers build exactly one.
    """
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs

                _S3FS = pafs.S3FileSystem()
    return _S3FS


@lru_cache(maxsize=1)
def _derived_bucket_key() -> tuple:
    """(bucket, key) of the derived long-parquet payload, resolved from the manifest (never hard-coded)."""
    return bucket_key_for(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _derived_manifest() -> dict:
    return load_manifest(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _panel_size() -> Optional[int]:
    """Total ProCan cell lines (detection denominator = 949) — a release constant carried in manifest
    params (NOT recoverable from the detected-only long table)."""
    v = (_derived_manifest().get("parameters", {}) or {}).get("panel_size_n_cell_lines")
    return int(v) if v is not None else None


def resolve_accessions(target: str) -> list:
    """HGNC symbol -> [UniProt accession, ...] via the GENERAL uniprot_hugo map (reused from the Gygi
    sibling). ProCan's uniprot_base is the universal UniProt accession, so these join directly. Empty
    list when the symbol is not in the map (→ data_unavailable, honest)."""
    return list(_symbol_to_uniprot_map().get(target.strip().upper()) or [])


def _select_abundance_from_table(tbl, accession: str, panel_size):
    """Post-read selection shared by the live + offline paths. `tbl` is a pyarrow Table of the rows for
    one uniprot_base. Returns (abundance_by_model | None, panel_size). Deterministic isoform tie-break:
    pick the min uniprot_id (parity with the Gygi selector's 'first base-match column' semantics)."""
    if tbl.num_rows == 0:
        return None, panel_size  # accession not in the ProCan panel → caller → data_unavailable
    d = tbl.to_pydict()
    uids = sorted(set(d["uniprot_id"]))
    chosen = uids[0]
    out = {m: float(v) for u, m, v in zip(d["uniprot_id"], d["model_id"], d["log_abundance"]) if u == chosen}
    return (out or None), panel_size


def _load_abundance_pushdown(accession: str, product_path=None):
    """Pushdown-read one protein's per-cell-line abundance from the derived long parquet. Returns
    (abundance_by_model | None, panel_size). `product_path` (offline test seam) reads a local parquet
    with the same filter; None => the live S3 product (cached per accession)."""
    import pyarrow.parquet as pq

    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=[("uniprot_base", "=", accession)])
        return _select_abundance_from_table(tbl, accession, _panel_size())
    return _load_abundance_pushdown_live(accession)


@lru_cache(maxsize=128)
def _load_abundance_pushdown_live(accession: str):
    """LIVE S3 pushdown, cached per accession (a single small row-group slice). A transient failure
    RAISES and is NOT cached (lru_cache never memoizes exceptions), so a later call retries."""
    import pyarrow.parquet as pq

    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[("uniprot_base", "=", accession)])
    return _select_abundance_from_table(tbl, accession, _panel_size())


def _compute_null_from_table(path, filesystem=None) -> tuple:
    """One median per protein (uniprot_base) over the 2-column (uniprot_base, log_abundance) scan of the
    product — the all-protein null the product ships no sidecar for. Returned as a hashable tuple."""
    import pyarrow.parquet as pq

    tbl = pq.read_table(path, filesystem=filesystem, columns=["uniprot_base", "log_abundance"])
    med = tbl.to_pandas().groupby("uniprot_base")["log_abundance"].median()
    return tuple(float(x) for x in med.tolist())


def _allprotein_median_null(product_path=None) -> tuple:
    """All-protein median-abundance null. `product_path` (offline test seam) reads a local parquet;
    None => the live S3 product (cached). Empty tuple on any live read failure → high_cutoff stays None
    (broadly_high honestly cannot fire) + percentile data_unavailable — same graceful degrade as Gygi."""
    if product_path is not None:
        return _compute_null_from_table(str(product_path))
    return _allprotein_median_null_live()


# F1: SUCCESS-ONLY memo (was @lru_cache(maxsize=1)). The bare-except degrade below returns tuple()
# on a transient scan failure; lru_cache would MEMOIZE that empty tuple and poison the whole session
# (allgene_percentile → data_unavailable + broadly_high high_cutoff → None for ALL targets for the
# process lifetime). So we cache ONLY a successful scan and let a failure fall through uncached, so a
# later call retries — parity with the raising primary pushdown (_load_abundance_pushdown_live), which
# lru_cache correctly never memoizes. `None` sentinel = not-yet-successfully-computed (a genuine empty
# product legitimately caches an empty tuple, distinct from the None "no success yet" state).
_ALLPROTEIN_NULL_CACHE: Optional[tuple] = None


def _reset_allprotein_null_cache() -> None:
    """Clear the success-only null memo (test seam; parity with the old lru_cache.cache_clear())."""
    global _ALLPROTEIN_NULL_CACHE
    _ALLPROTEIN_NULL_CACHE = None


def _allprotein_median_null_live() -> tuple:
    global _ALLPROTEIN_NULL_CACHE
    if _ALLPROTEIN_NULL_CACHE is not None:
        return _ALLPROTEIN_NULL_CACHE
    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    try:
        result = _compute_null_from_table(f"{bucket}/{key}", filesystem=_get_s3fs())
    except Exception:  # noqa: BLE001  # absence-discipline: exempt -- the null is an OPTIONAL enhancement, not an absence signal: the per-protein pushdown (_load_abundance_pushdown_live, no broad except) runs FIRST in load_and_classify and propagates any transient/creds/broken-env failure honestly as _live_read_error; a null-read failure at that point only degrades broadly_high (unreachable) + allgene_percentile (data_unavailable), never masks a coverage gap. Mirrors the Gygi sibling's _all_protein_median_null. F1: NOT memoized so a transient failure does not stick session-wide.
        return tuple()
    _ALLPROTEIN_NULL_CACHE = result
    return result


def _pct_context() -> str:
    return f"{DERIVED_PRODUCT_MANIFEST_ID} panel-wide metric=median_log_abundance source={PROTEIN_ABUNDANCE_SOURCE}"


def _data_unavailable_summary(target: str, panel_size, note: Optional[str] = None) -> dict:
    """The card-shaped data_unavailable summary (coverage-gap / missing-input path). Reuses the Gygi
    sibling's compute_summary None-branch (fraction_detected=0.0, never fabricated) + the ProCan source
    marker and null-percentile placeholders. `note` (optional) records WHY it is unavailable."""
    summ = compute_summary(target, None, {}, n_panel=panel_size)
    summ["method_version"] = METHOD_VERSION
    summ["protein_abundance_source"] = "data_unavailable"
    summ["allgene_percentile"] = None
    summ["allgene_percentile_class"] = "data_unavailable"
    summ["allgene_percentile_context"] = _pct_context()
    if note is not None:
        summ["_data_note"] = note
    return summ


def load_and_classify(target: str, product_path=None, null_path=None) -> dict:
    """Full pipeline for one target: resolve symbol→UniProt → pushdown-read the protein column →
    classify (reusing the Gygi sibling's compute_summary). Emits the cellline-protein-abundance card
    shape + the ProCan platform source marker + the all-gene percentile.

    product_path / null_path: offline test seams (local parquet). Default None => the live S3 product.
    Lineage is unavailable for SIDM ids (no ACH crosswalk), so an EMPTY lineage map is passed →
    per_lineage_stats == [] (honest)."""
    panel_size = _panel_size()
    if panel_size is None:
        # F7: panel_size_n_cell_lines (the detection denominator) is a release constant carried in the
        # manifest params — it is NOT recoverable from the detected-only long table. Absent it,
        # compute_summary falls back to denom=n_eval → a fabricated fraction_detected=1.0 ("100% of
        # panel") that could mislabel the detection band (broadly_moderate/broadly_high). Fail loud
        # with data_unavailable instead of minting a false full-panel detection. Inert today: the
        # manifest carries 949; this fires only if a future manifest genuinely drops the field.
        return _data_unavailable_summary(target, panel_size, note="panel_size_n_cell_lines absent from manifest params")
    col = None
    for acc in resolve_accessions(target):
        col, panel_size = _load_abundance_pushdown(acc, product_path=product_path)
        if col:
            break
    if not col:
        return _data_unavailable_summary(target, panel_size)

    null_vec = _allprotein_median_null(product_path=(null_path if null_path is not None else product_path))
    summary = compute_summary(target, col, {}, n_panel=panel_size, all_protein_medians=(null_vec or None))
    summary["method_version"] = METHOD_VERSION
    summary["protein_abundance_source"] = PROTEIN_ABUNDANCE_SOURCE
    pct = percentile_rank(summary.get("median_log2_abundance_panel"), null_vec or [])
    summary["allgene_percentile"] = pct
    summary["allgene_percentile_class"] = classify_percentile(pct, _PCT_CUTOFFS)
    summary["allgene_percentile_context"] = _pct_context()
    return summary


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="ProCan cell-line protein-abundance distribution for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--product-path", default=None)
    ap.add_argument("--null-path", default=None)
    args = ap.parse_args(argv)
    out = load_and_classify(args.target, product_path=args.product_path, null_path=args.null_path)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    _main()
