"""surfaceome_family_fusion.read — SURFY + HPA + UniProt + IUPHAR family reader.

Consumer: surfaceome-family-classification evidence card (Phase F) via
tractability-and-modality skill. Emits per-target surface-protein family
classification fused from 4 upstream sources with source-agreement scoring.

Runtime discipline:
  - pd.read_parquet with no predicate pushdown (20K rows total, small enough)
  - Column-array iteration (df.col.values) to build gene_symbol + uniprot_ac
    indices — NOT iterrows (which is O(rows) Python-object materialization)
  - Lazy per-target row materialization via df.iloc[[idx]].to_dict — bounded
    to a single row per lookup instead of the full 20K
  - @lru_cache(maxsize=1) on load+index + module-level negative cache

Companion:
  data-catalog:manifests/derived/surfaceome-family-classification-per-uniprot-v1.yaml
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_key_for


DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "surfaceome-family-classification-per-uniprot-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, DERIVED_S3_KEY = bucket_key_for(DERIVED_MANIFEST_ID)

CACHE_DIR = Path.home() / ".cache" / "framework-surfaceome-family"
CACHE_PARQUET = CACHE_DIR / "surfaceome_family.parquet"

_DERIVED_STATUS: Optional[bool] = None


from methods.target_id_sidecar import s3_client as _boto3_client


def _ensure_derived_cached() -> Optional[Path]:
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    if _DERIVED_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, DERIVED_S3_KEY, str(CACHE_PARQUET))
            _DERIVED_STATUS = True
            return CACHE_PARQUET
        except Exception as e:
            # Distinguish "genuinely not published yet" (a definitive 404 / NoSuchKey) from a
            # TRANSIENT failure (expired creds, 403/AccessDenied, network blip, throttling). Latch
            # _DERIVED_STATUS = False + return None ONLY on a genuine object-absence — honest,
            # process-stable data_unavailable. 403/AccessDenied is NOT definitive (almost always a
            # transient creds blip). For any TRANSIENT / broken-env failure, RAISE: the outer
            # @lru_cache on _load_indexed would otherwise memoize EMPTY frames (path=None → the
            # `return pd.DataFrame(), {}, {}` branch) off one blip and poison the whole batch — the
            # exact bug this fix closes. lru_cache never memoizes a raise, so the next call retries.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (
                code in ("404", "NoSuchKey")
                or e.__class__.__name__ in ("NoSuchKey", "404")
                or isinstance(e, FileNotFoundError)
            )
            if definitive:
                _DERIVED_STATUS = False
                return None
            raise
    return None


@lru_cache(maxsize=1)
def _load_indexed():
    """Load derived parquet + build gene_symbol and uniprot_ac indices.

    Returns (df, gene_idx, ac_idx):
        - df: pandas.DataFrame with 20K rows (source-of-truth; row lookups
          happen lazily via df.iloc[[idx]] at read_target_summary time)
        - gene_idx: dict[gene_symbol_upper -> row_index_in_df]
        - ac_idx: dict[uniprot_ac -> row_index_in_df]

    On failure returns (empty DataFrame, {}, {}).
    """
    path = _ensure_derived_cached()
    if path is None:
        import pandas as pd

        return pd.DataFrame(), {}, {}
    import pandas as pd

    # LOCAL cache read — S3 absence (404/NoSuchKey) is latched in _ensure_derived_cached (path=None
    # above -> honest data_unavailable). A failure reading a PRESENT file is broken-env (missing
    # pyarrow) or a corrupt/partial cache, NOT data absence -> PROPAGATE (honest _live_read_error at
    # the live-read seam), never mask as an empty frame. @lru_cache does not memoize the raise, so
    # this also avoids the poison-on-failure the old return-empty caused (mirrors cptac_protein_deg /
    # surface_antigen_density_ladder).
    df = pd.read_parquet(path)
    if df.empty:
        return df, {}, {}

    # Column-array iteration builds indices in ~10ms on 20K rows.
    gene_col = df["gene_symbol"].values
    ac_col = df["uniprot_ac"].values
    gene_idx: dict[str, int] = {}
    ac_idx: dict[str, int] = {}
    for i in range(len(df)):
        g = gene_col[i]
        a = ac_col[i]
        if g:
            gene_idx[str(g).strip().upper()] = i
        if a:
            ac_idx[str(a).strip()] = i
    return df, gene_idx, ac_idx


def read_target_summary(target: str, indication: str = None) -> dict:
    # Let broken-env/corrupt-cache propagate from _load_indexed (honest _live_read_error) instead of
    # re-swallowing to _empty. Genuine absent product -> empty df below -> _empty (data_unavailable).
    df, gene_idx, ac_idx = _load_indexed()
    if df is None or df.empty:
        return _empty("surfaceome_family_data_unavailable")

    # Accept either HGNC symbol or UniProt AC as input
    sym_key = target.upper().strip()
    ac_key = target.strip()
    row_idx = gene_idx.get(sym_key)
    if row_idx is None:
        row_idx = ac_idx.get(ac_key)
    if row_idx is None:
        return _empty("target_not_in_surfaceome_family")

    # Lazy: single-row dict materialization
    row = df.iloc[row_idx].to_dict()

    return {
        "family_class": row.get("family_class", "data_unavailable"),
        "surface_protein_family": row.get("surface_protein_family", "Other"),
        "is_surface_protein": bool(row.get("is_surface_protein", False)),
        "surfaceome_confidence_score": row.get("surfaceome_confidence_score"),
        "source_surfy_positive": bool(row.get("source_surfy_positive", False)),
        "source_hpa_plasma_membrane": bool(row.get("source_hpa_plasma_membrane", False)),
        "source_uniprot_ec_number": row.get("source_uniprot_ec_number", ""),
        "source_iuphar_family": row.get("source_iuphar_family", ""),
        "hpa_protein_class_verbatim": row.get("hpa_protein_class_verbatim", ""),
        "fusion_provenance": [
            str(x) for x in (row.get("fusion_provenance") if row.get("fusion_provenance") is not None else [])
        ],
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "family_class": "data_unavailable",
        "surface_protein_family": "Not_surface",
        "is_surface_protein": False,
        "surfaceome_confidence_score": None,
        "source_surfy_positive": False,
        "source_hpa_plasma_membrane": False,
        "source_uniprot_ec_number": "",
        "source_iuphar_family": "",
        "hpa_protein_class_verbatim": "",
        "fusion_provenance": [],
        "method_version": "0.1.0",
        "_data_note": note,
    }
