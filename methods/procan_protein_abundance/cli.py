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

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, load_manifest

# Reuse the Gygi sibling's summary shape + classifier + symbol->UniProt path (single source of truth).
from methods.depmap_protein_abundance.cli import (  # noqa: F401
    _symbol_to_uniprot_map,
    classify_protein_abundance,
    compute_summary,
)
from methods.percentile_null import classify_percentile, percentile_rank
from methods.target_id_sidecar import ensure_aws_profile

METHOD_VERSION = "0.1.0"
DERIVED_PRODUCT_MANIFEST_ID = "procan-cellline-protein-abundance-per-protein-v1"
PROTEIN_ABUNDANCE_SOURCE = "procan_dia_swath"

# all-gene percentile-class cutoffs (mirror cellline-protein-abundance*.card.yaml thresholds).
_PCT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}


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
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    tbl = pq.read_table(f"{bucket}/{key}", filesystem=pafs.S3FileSystem(), filters=[("uniprot_base", "=", accession)])
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


@lru_cache(maxsize=1)
def _allprotein_median_null_live() -> tuple:
    import pyarrow.fs as pafs

    ensure_aws_profile()
    bucket, key = _derived_bucket_key()
    try:
        return _compute_null_from_table(f"{bucket}/{key}", filesystem=pafs.S3FileSystem())
    except Exception:  # noqa: BLE001  # absence-discipline: exempt -- the null is an OPTIONAL enhancement, not an absence signal: the per-protein pushdown (_load_abundance_pushdown_live, no broad except) runs FIRST in load_and_classify and propagates any transient/creds/broken-env failure honestly as _live_read_error; a null-read failure at that point only degrades broadly_high (unreachable) + allgene_percentile (data_unavailable), never masks a coverage gap. Mirrors the Gygi sibling's _all_protein_median_null.
        return tuple()


def _pct_context() -> str:
    return f"{DERIVED_PRODUCT_MANIFEST_ID} panel-wide metric=median_log_abundance source={PROTEIN_ABUNDANCE_SOURCE}"


def load_and_classify(target: str, product_path=None, null_path=None) -> dict:
    """Full pipeline for one target: resolve symbol→UniProt → pushdown-read the protein column →
    classify (reusing the Gygi sibling's compute_summary). Emits the cellline-protein-abundance card
    shape + the ProCan platform source marker + the all-gene percentile.

    product_path / null_path: offline test seams (local parquet). Default None => the live S3 product.
    Lineage is unavailable for SIDM ids (no ACH crosswalk), so an EMPTY lineage map is passed →
    per_lineage_stats == [] (honest)."""
    panel_size = _panel_size()
    col = None
    for acc in resolve_accessions(target):
        col, panel_size = _load_abundance_pushdown(acc, product_path=product_path)
        if col:
            break
    if not col:
        summ = compute_summary(target, None, {}, n_panel=panel_size)
        summ["method_version"] = METHOD_VERSION
        summ["protein_abundance_source"] = "data_unavailable"
        summ["allgene_percentile"] = None
        summ["allgene_percentile_class"] = "data_unavailable"
        summ["allgene_percentile_context"] = _pct_context()
        return summ

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
