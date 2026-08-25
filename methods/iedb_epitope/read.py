"""iedb_epitope.read — S3 boundary for the per-protein IEDB epitope / MHC card.

Reads iedb-epitope-mhc-per-protein-v1 (experimentally-validated human source-protein epitope / MHC
rollup), resolving the target HGNC symbol -> UniProt accession via the product's resolver sidecar (the
same discipline as the pmhc_presentation + CSPA + topology readers). UniProt-keyed predicate-pushdown.

Epitope evidence is a protein property (indication-independent) — `indication` is accepted for the
generic-dispatch contract but not consumed. An absent target is a WEAK-negative (`not_observed`), not
data_unavailable — a POSITIVE assay is strong evidence, ABSENCE is weak (assay asymmetry): absence !=
non-epitope. VERDICT-INERT: consumed by surface-modality-fit as a DISPLAY card (adds pMHC narrative
context; moves no verdict).

Entrypoint: read_target_summary(target, indication=None) — invoked by the skills generic dispatcher via
the card's `methods: module: iedb_epitope, entrypoint: read_target_summary` declaration.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for
from . import classify as _classify

DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "iedb-epitope-mhc-per-protein-v1"
S3_BUCKET, PAYLOAD_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
_, SIDECAR_KEY = sidecar_bucket_key_for(DERIVED_MANIFEST_ID)

METHOD_VERSION = "1.0.0"


def _read_parquet(bucket, key):
    import pyarrow.parquet as pq
    import pyarrow.fs as fs
    s3fs = fs.S3FileSystem(region="us-east-1")   # default cred chain honors AWS_PROFILE=cbg
    return pq.read_table(f"{bucket}/{key}", filesystem=s3fs)


@lru_cache(maxsize=1)
def _symbol_to_ac() -> dict:
    """UPPER(HGNC symbol) -> uniprot_id, from the resolver sidecar. {} iff GENUINELY absent (AC-direct
    still works). A transient/creds/broken-env failure is RE-RAISED — not masked as an empty map that
    @lru_cache would then memoize process-wide (one blip -> every symbol unresolvable for the process)."""
    from methods.target_id_sidecar import is_definitively_absent
    try:
        df = _read_parquet(S3_BUCKET, SIDECAR_KEY).to_pandas()
    except Exception as e:  # noqa: BLE001
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return {}
    # sidecar schema (target_resolution): hgnc_primary_symbol_at_resolution -> uniprot_canonical
    # (exact column names — this is a stable materialized product, not a heuristic target).
    sym_col = "hgnc_primary_symbol_at_resolution"
    ac_col = "uniprot_canonical"
    if sym_col not in df.columns or ac_col not in df.columns:
        # A present sidecar missing its expected columns is schema drift on a broken/misdescribed
        # product, NOT a data gap — raise (do not memoize an empty map). Mirrors pmhc_presentation.
        raise ValueError(
            f"IEDB resolver sidecar s3://{S3_BUCKET}/{SIDECAR_KEY} missing expected columns "
            f"{sym_col!r}/{ac_col!r} (present: {list(df.columns)[:10]}) — schema drift")
    out = {}
    for sym, ac in zip(df[sym_col], df[ac_col]):
        if sym is not None and ac is not None and str(sym).strip() and str(sym) != "nan":
            out.setdefault(str(sym).upper().strip(), str(ac))
    return out


def _resolve_ac(target: str) -> Optional[str]:
    """target -> UniProt AC. Prefer the sidecar HGNC->AC map; else pass through a bare UniProt accession."""
    t = target.strip().upper()
    hit = _symbol_to_ac().get(t)
    if hit:
        return hit
    return t if _looks_like_ac(t) else None


def _looks_like_ac(s: str) -> bool:
    s = s.strip().upper()
    return 6 <= len(s) <= 10 and s[0].isalpha() and any(c.isdigit() for c in s)


@lru_cache(maxsize=512)
def _row_for_ac(ac: str) -> Optional[dict]:
    """The IEDB row for a UniProt AC (pushdown): None if the AC is absent (weak-negative), or the
    "UNREADABLE" sentinel iff the product is GENUINELY absent (404 / NoSuchKey / missing object ->
    data_unavailable). A transient/creds/broken-env failure is RE-RAISED, so @lru_cache does NOT
    memoize the failure — otherwise one blip would pin this AC to UNREADABLE for the whole process."""
    from methods.target_id_sidecar import is_definitively_absent
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        s3fs = fs.S3FileSystem(region="us-east-1")
        tbl = pq.read_table(f"{S3_BUCKET}/{PAYLOAD_KEY}", filesystem=s3fs,
                            filters=[("uniprot_id", "==", ac)])
    except Exception as e:  # noqa: BLE001
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return "UNREADABLE"   # genuine product absence -> data_unavailable (stable; memoization ok)
    df = tbl.to_pandas()
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-protein IEDB epitope-evidence summary for a target. indication accepted (generic-dispatch
    contract) but not consumed — epitope evidence is a protein property."""
    ac = _resolve_ac(target)
    if ac is None:
        # can't map target -> UniProt at all -> data_unavailable (a resolution gap, not a weak-negative)
        out = _classify.summarize_epitope(None)
        out["epitope_evidence_class"] = "data_unavailable"
        out["_data_note"] = f"{target} not resolvable to a UniProt accession (sidecar miss)"
        out["uniprot_ac"] = None
        out["method_version"] = METHOD_VERSION
        out["_data_source"] = DERIVED_MANIFEST_ID
        return out
    row = _row_for_ac(ac)
    if row == "UNREADABLE":
        out = _classify.summarize_epitope(None)
        out["epitope_evidence_class"] = "data_unavailable"
        out["_live_read_error"] = "iedb_epitope_read_failed"
    else:
        out = _classify.summarize_epitope(row)   # row=None -> not_observed (weak-negative)
    out["uniprot_ac"] = ac
    out["method_version"] = METHOD_VERSION
    out["_data_source"] = DERIVED_MANIFEST_ID
    return out
