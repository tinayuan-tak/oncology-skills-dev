"""imvigor210_ici_response.read — per-gene IMvigor210 ICI-response + immune-phenotype for a target.

read_target_summary(target, indication) → the ici-response-imvigor210 card summary: the target's
expression in anti-PD-L1 responders vs non-responders + its desert/excluded/inflamed enrichment, via
gene_symbol pushdown on imvigor210-ici-response-per-gene-v1. UROTHELIAL-scoped (IMvigor210 is mUC): a
non-urothelial `indication` → data_unavailable (honest scope ceiling, never a cross-indication read).
Absence-safe: 404 / gene-miss → data_unavailable; transient/creds → _live_read_error.
"""

from __future__ import annotations

from typing import Optional

from methods._common.s3 import get_s3fs
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


# VOCABULARY FOLD (2026-09-12). `measurement_type: ici_response_expression` is carried by TWO cards —
# ici-response-imvigor210 (this reader) and ici-response-association (methods/ici_response) — and a
# measurement_type is the DATA_TO_SKILL_CONTRACT unit: one type must mean ONE vocabulary, or a consumer
# reads the same claim differently depending on which card answered. The two diverged on the null class,
# because each was individually honest about its own product: methods/ici_response MINTS
# `no_ici_association` in Python, whereas the IMvigor210 product mints `no_association` in the R derive
# script (data-catalog scripts/derive_imvigor210_ici_response.R) and this reader passed it through
# verbatim. Nothing failed — no interpretation rule keys on ici_response_class at all today — so the
# cost would have landed on the first rule author, whose `equals:` would be permanently DEAD on one of
# the two cards while looking authored. Folded HERE (reader-side) rather than by re-deriving the product,
# because the product's own token is correct in its own namespace; the skill contract is what needs one
# spelling. The corresponding target-contracts vocabulary-divergence allowlist entry is deleted once
# this ships.
_CLASS_ALIASES = {"no_association": "no_ici_association"}

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


def _get_s3fs():
    return get_s3fs(pre_hook=ensure_aws_profile)


def _empty(note: str) -> dict:
    return {
        "ici_response_class": "data_unavailable",
        "_data_note": note,
        "_data_source": MANIFEST_ID,
        "method_version": METHOD_VERSION,
    }


def _rows_for_candidates(cands: list) -> list:
    """S3 seam: the product rows for any of the candidate gene symbols. Extracted so the SUMMARY path
    (which is where the vocabulary fold lives) is testable without credentials — it previously had no
    hermetic coverage at all, which is exactly why the token divergence was invisible.

    Raises on a transient/creds fault; `is_definitively_absent` 404s surface as FileNotFoundError."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    bucket, key = bucket_key_for(MANIFEST_ID)
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[(COL_GENE, "in", cands)])
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e):
            raise FileNotFoundError(f"{MANIFEST_ID} not found (404)") from e
        raise
    return tbl.filter(pc.is_in(pc.utf8_upper(tbl[COL_GENE]), value_set=pa.array(cands))).to_pylist()


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    sym = (target or "").upper().strip()
    if not sym:
        return _empty("no target symbol")
    if not indication or indication.upper().strip() not in _UROTHELIAL_INDICATIONS:
        # IMvigor210 is metastatic urothelial — do NOT read cross-indication (honest scope ceiling).
        return _empty(f"IMvigor210 is urothelial-only; indication {indication!r} out of scope")
    cands = _gene_candidates(sym)
    try:
        rows = _rows_for_candidates(cands)
    except FileNotFoundError:
        # genuine absence: _rows_for_candidates converts ClientError NoSuchKey/404 (and an unknown
        # manifest id) to FileNotFoundError -> honest data_unavailable.
        return _empty(f"{MANIFEST_ID} not found (404)")
    # Absence discipline (#832): transient / creds / broken-env now PROPAGATE (an honest _live_read_error
    # at the compose seam) rather than being masked as ici_response_class=data_unavailable. Genuine
    # absence is fully handled above (FileNotFoundError); a gene simply absent from the product returns
    # empty rows and is handled by the `if not rows` guard below.
    if not rows:
        return _empty(f"{sym} absent from IMvigor210 product")
    r = rows[0]
    out = {k: r.get(k) for k in _SUMMARY_FIELDS}
    # fold the product's null-class spelling onto the shared measurement_type vocabulary (see _CLASS_ALIASES)
    out["ici_response_class"] = _CLASS_ALIASES.get(out["ici_response_class"], out["ici_response_class"])
    out["ici_response_context"] = (
        f"IMvigor210 (atezolizumab mUC): {sym} {out['ici_response_class']} "
        f"(log2FC resp-vs-nonresp {out.get('log2fc_resp_vs_nonresp')}, BH-q {out.get('bh_q')}); "
        f"enriched in the {out.get('immune_phenotype_enriched_in')} immune phenotype"
    )
    out["indication_scope"] = "BLCA"
    out["_data_source"] = MANIFEST_ID
    out["method_version"] = METHOD_VERSION
    return out
