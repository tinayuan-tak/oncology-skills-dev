"""imvigor210_ici_response.read — per-gene IMvigor210 ICI-response + immune-phenotype for a target.

read_target_summary(target, indication) → the ici-response-imvigor210 card summary: the target's
expression in anti-PD-L1 responders vs non-responders + its desert/excluded/inflamed enrichment, via
gene_symbol pushdown on imvigor210-ici-response-per-gene-v1. UROTHELIAL-scoped (IMvigor210 is mUC): a
non-urothelial `indication` → data_unavailable (honest scope ceiling, never a cross-indication read).
Absence-safe: 404 / gene-miss → data_unavailable; transient/creds → _live_read_error.
"""

from __future__ import annotations

import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for
from methods.target_id_sidecar import ensure_aws_profile, is_definitively_absent

METHOD_VERSION = "1.0.0"
MANIFEST_ID = "imvigor210-ici-response-per-gene-v1"
COL_GENE = "gene_symbol"
# IMvigor210 is metastatic urothelial carcinoma → only urothelial/bladder indications are in scope.
_UROTHELIAL_INDICATIONS = frozenset({"BLCA", "UROTHELIAL", "BLADDER", "MIBC", "UCEC_UROTHELIAL", "UC"})

# The IMvigor210 CoreBiologies object stores fData$symbol as PUBLISHED — for renamed genes the LEGACY
# symbol is stored (e.g. NECTIN4 under its prev-symbol PVRL4), so a modern-HGNC query misses. Fold
# current<->legacy so either symbol resolves. Interim reader-side fold (#1272); the durable fix
# re-derives the product on the current HGNC symbol (data-catalog #549.4).
_SYMBOL_ALIASES = {"NECTIN4": ("PVRL4",), "PVRL4": ("NECTIN4",)}


def _gene_candidates(sym: str) -> list:
    """Upper-cased query symbol + any legacy/current aliases, for a symbol-rename-tolerant read."""
    return [sym, *_SYMBOL_ALIASES.get(sym, ())]


_SUMMARY_FIELDS = (
    "ici_response_class",
    "log2fc_resp_vs_nonresp",
    "mwu_p",
    "bh_q",
    "n_responder",
    "n_nonresponder",
    "mean_logcpm_responder",
    "mean_logcpm_nonresponder",
    "immune_phenotype_enriched_in",
    "kw_p_phenotype",
    "mean_logcpm_desert",
    "mean_logcpm_excluded",
    "mean_logcpm_inflamed",
)

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                ensure_aws_profile()
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _empty(note: str) -> dict:
    return {
        "ici_response_class": "data_unavailable",
        "_data_note": note,
        "_data_source": MANIFEST_ID,
        "method_version": METHOD_VERSION,
    }


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    sym = (target or "").upper().strip()
    if not sym:
        return _empty("no target symbol")
    if not indication or indication.upper().strip() not in _UROTHELIAL_INDICATIONS:
        # IMvigor210 is metastatic urothelial — do NOT read cross-indication (honest scope ceiling).
        return _empty(f"IMvigor210 is urothelial-only; indication {indication!r} out of scope")
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    cands = _gene_candidates(sym)
    bucket, key = bucket_key_for(MANIFEST_ID)
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[(COL_GENE, "in", cands)])
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e):
            return _empty(f"{MANIFEST_ID} not found (404)")
        return {
            "ici_response_class": "data_unavailable",
            "method_version": METHOD_VERSION,
            "_data_source": MANIFEST_ID,
            "_live_read_error": f"imvigor210_ici_response read failed for {sym}: {type(e).__name__}: {e}",
        }
    rows = tbl.filter(pc.is_in(pc.utf8_upper(tbl[COL_GENE]), value_set=pa.array(cands))).to_pylist()
    if not rows:
        return _empty(f"{sym} absent from IMvigor210 product")
    r = rows[0]
    out = {k: r.get(k) for k in _SUMMARY_FIELDS}
    out["ici_response_context"] = (
        f"IMvigor210 (atezolizumab mUC): {sym} {out['ici_response_class']} "
        f"(log2FC resp-vs-nonresp {out.get('log2fc_resp_vs_nonresp')}, BH-q {out.get('bh_q')}); "
        f"enriched in the {out.get('immune_phenotype_enriched_in')} immune phenotype"
    )
    out["indication_scope"] = "BLCA"
    out["_data_source"] = MANIFEST_ID
    out["method_version"] = METHOD_VERSION
    return out
