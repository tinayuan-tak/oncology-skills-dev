"""synleth_partner_lookup.read — live-mode dispatcher entry for the synthetic-lethal-
partners card.

ANNOTATION lookup (not a compute / screen): target → curated SL partners from the
published SynLethDB v3 (derived synlethdb-sl-partners-per-gene-v1). Reads the derived
parquet (S3 read-through cache), point-looks-up the gene, returns the
synthetic-lethal-partners card summary.

The card/gate use this as a veto-SUPPRESSOR input, NEVER a nominator: a curated SL
partner means a pooled `non_dependent` CRISPR read is NOT a trusted negative (the target
may be a genuine dependency in the partner-altered context — SMARCA2←SMARCA4-loss). It
does not, on its own, make the target a dependency.

`has_experimental_partner` is the load-bearing gate: an experimentally-supported SL
partner (CRISPR / RNAi / throughput screen) is a trustworthy suppressor; a
computational-only annotation is weaker (surfaced but the gate wiring requires
experimental support to suppress a veto).

Graceful degradation: derived product unreachable → data_unavailable + _live_read_error
(never raises). Gene genuinely absent from the SL table → `no_curated_sl_partner`
(a real read: this gene has no known SL partner) — distinct from data_unavailable.
"""

from __future__ import annotations

import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for

METHOD_VERSION = "read-0.1.0"

DERIVED_MANIFEST_ID = "synlethdb-sl-partners-per-gene-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth);
# was a hand-typed literal with no manifest_id constant to tie it back.
S3_BUCKET, DERIVED_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
# Pushdown key: the derived manifest's query_optimization.primary_filter_column
# (gene_symbol); the product is gene_symbol-SORTED so a predicate-pushed streaming
# read prunes to the target's row-group instead of downloading the whole object.
PUSHDOWN_KEY = "gene_symbol"

# Process-wide S3FileSystem singleton (double-checked lock), mirroring the
# streamed-read exemplars (dge_deseq2._get_s3fs, depmap_common.parquet._get_s3fs).
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs
                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_gene_rows(target: str, parquet_path=None):
    """STREAMED pushdown read of the target's per-gene row(s) as a pandas DataFrame.

    Reads the derived product over a pyarrow S3FileSystem (no whole-file download) with
    a predicate pushed on the manifest's primary_filter_column (gene_symbol). The match
    is case-insensitive (utf8_upper on both sides) to preserve the reader's historical
    behaviour — SynLethDB stores native-case HGNC symbols (e.g. `C4orf54`), so an exact
    uppercase equality would silently drop the ~60 orf-genes. `parquet_path` (offline test
    seam) streams a local file instead of S3. Errors propagate to the caller's boundary."""
    import pyarrow.dataset as ds
    import pyarrow.compute as pc
    want = target.strip().upper()
    expr = pc.equal(pc.utf8_upper(pc.field(PUSHDOWN_KEY)), want)
    if parquet_path is not None:
        dset = ds.dataset(str(parquet_path), format="parquet")
    else:
        dset = ds.dataset(f"{S3_BUCKET}/{DERIVED_KEY}", filesystem=_get_s3fs(),
                          format="parquet")
    return dset.to_table(filter=expr).to_pandas()


def _summary(row) -> dict:
    """Build the synthetic-lethal-partners card summary from a per-gene parquet row."""
    n = int(row["sl_partner_count"])
    n_exp = int(row["n_experimental_partners"])
    has_exp = bool(row["has_experimental_partner"])
    # PRIMARY categorical: experimentally-supported partner is the trustworthy tier.
    if has_exp:
        klass = "has_experimental_sl_partner"
    elif n > 0:
        klass = "has_computational_sl_partner"
    else:
        klass = "no_curated_sl_partner"
    top = row["top_partners"]
    # parquet may store list-of-dict as numpy array / list
    top_list = list(top) if top is not None else []
    return {
        "sl_partner_class": klass,
        "sl_partner_count": n,
        "n_experimental_partners": n_exp,
        "has_experimental_partner": has_exp,
        "best_evidence_tier": row["best_evidence_tier"],
        "sl_partner_symbols": list(row["sl_partner_symbols"]) if row["sl_partner_symbols"] is not None else [],
        "top_partners": [dict(p) for p in top_list],
        "method_version": METHOD_VERSION,
    }


def read_target_summary(target: str, indication: Optional[str] = None,
                        parquet_path: Optional[str] = None) -> dict:
    """SL-partner annotation for a target. Gene-level (SL pairs are gene-gene) —
    `indication` accepted for the dispatcher contract but NOT consumed."""
    try:
        hit = _read_gene_rows(target, parquet_path)
    except Exception as e:  # noqa: BLE001
        # absence-discipline: exempt -- documented graceful contract (module docstring):
        # ANY read failure (transient/creds/broken-env OR a genuinely-missing product
        # object) degrades to a NON-empty `data_unavailable` dict + `_live_read_error`
        # breadcrumb (never the RD empty-return bug class), and the reader never raises
        # past this boundary. A gene genuinely absent from the (successfully-read) table
        # is the distinct `no_curated_sl_partner` path below, not this handler.
        return {
            "_live_read_error": "synlethdb_partners_read_failed",
            "_remediation": (f"Could not read SL-partners derived product "
                             f"(s3://{S3_BUCKET}/{DERIVED_KEY}) for {target}: {e}"),
            "sl_partner_class": "data_unavailable",
            "sl_partner_count": 0, "has_experimental_partner": False,
            "method_version": METHOD_VERSION,
        }
    if not len(hit):
        # a real read: this gene has no curated SL partner (NOT data_unavailable)
        return {
            "sl_partner_class": "no_curated_sl_partner",
            "sl_partner_count": 0, "n_experimental_partners": 0,
            "has_experimental_partner": False, "best_evidence_tier": None,
            "sl_partner_symbols": [], "top_partners": [],
            "method_version": METHOD_VERSION,
        }
    return _summary(hit.iloc[0])
