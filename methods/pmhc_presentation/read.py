"""pmhc_presentation.read — S3 boundary for the peptide-centric HLA-presentation card.

Reads hla-ligand-atlas-presentation-per-protein-v1 (benign immunopeptidome, per source protein),
resolving target HGNC symbol → UniProt accession via the product's resolver sidecar (same discipline
as the CSPA + topology readers). UniProt-keyed predicate-pushdown.

Presentation is a protein property (indication-independent) — `indication` is accepted for the
dispatcher contract but not consumed. An absent target is a WEAK-negative (`not_observed`), not
data_unavailable — MS immunopeptidomics tracks abundance×turnover, so absence != non-presentation.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for
from . import classify as _classify

DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "hla-ligand-atlas-presentation-per-protein-v1"
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
    """UPPER(HGNC symbol) → uniprot_id, from the resolver sidecar. {} iff GENUINELY absent (AC-direct
    still works). A transient/creds/broken-env failure is RE-RAISED — not masked as an empty map that
    @lru_cache would then memoize process-wide (one blip → every symbol unresolvable for the process)."""
    from methods.target_id_sidecar import is_definitively_absent
    try:
        df = _read_parquet(S3_BUCKET, SIDECAR_KEY).to_pandas()
    except Exception as e:  # noqa: BLE001
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return {}
    # sidecar schema (target_resolution): hgnc_primary_symbol_at_resolution → uniprot_canonical
    # (exact column names — this is a stable materialized product, not a heuristic target).
    sym_col = "hgnc_primary_symbol_at_resolution"
    ac_col = "uniprot_canonical"
    if sym_col not in df.columns or ac_col not in df.columns:
        # A present sidecar missing its expected columns is schema drift on a broken/misdescribed
        # product, NOT a data gap — raise (do not memoize an empty map). Mirrors read_resolver_sidecar_map.
        raise ValueError(
            f"pMHC resolver sidecar s3://{S3_BUCKET}/{SIDECAR_KEY} missing expected columns "
            f"{sym_col!r}/{ac_col!r} (present: {list(df.columns)[:10]}) — schema drift")
    out = {}
    for sym, ac in zip(df[sym_col], df[ac_col]):
        if sym is not None and ac is not None and str(sym).strip() and str(sym) != "nan":
            out.setdefault(str(sym).upper().strip(), str(ac))
    return out


def _resolve_ac(target: str) -> Optional[str]:
    """target → UniProt AC. Prefer the sidecar HGNC→AC map; else pass through a bare UniProt accession."""
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
    """The atlas row for a UniProt AC (pushdown): None if the AC is absent (weak-negative), or the
    "UNREADABLE" sentinel iff the product is GENUINELY absent (404 / NoSuchKey / missing object →
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
        return "UNREADABLE"   # genuine product absence → data_unavailable (stable; memoization ok)
    df = tbl.to_pandas()
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def read_pmhc_presentation(target: str, indication: str = None) -> dict:
    """Peptide-centric HLA-presentation summary for a target. indication accepted (dispatcher
    contract) but not consumed — presentation is a protein property."""
    ac = _resolve_ac(target)
    if ac is None:
        # can't map target → UniProt at all → data_unavailable (a resolution gap, not a weak-negative)
        out = _classify.summarize_pmhc(None)
        out["pmhc_presentation_class"] = "data_unavailable"
        out["_data_note"] = f"{target} not resolvable to a UniProt accession (sidecar miss)"
        out["method_version"] = METHOD_VERSION
        out["_data_source"] = DERIVED_MANIFEST_ID
        return out
    row = _row_for_ac(ac)
    if row == "UNREADABLE":
        out = _classify.summarize_pmhc(None)
        out["pmhc_presentation_class"] = "data_unavailable"
        out["_live_read_error"] = "hla_ligand_atlas_read_failed"
    else:
        out = _classify.summarize_pmhc(row)   # row=None → not_observed (weak-negative)
    out["uniprot_ac"] = ac
    out["method_version"] = METHOD_VERSION
    out["_data_source"] = DERIVED_MANIFEST_ID
    return out
