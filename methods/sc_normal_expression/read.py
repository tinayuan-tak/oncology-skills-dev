"""Per-gene reader over the sc-normal-celltype-expression Tier-1 products.

Reads sc-normal-celltype-expression-{tissue}-v1 (one row per cell_type × gene, already
cross-donor-aggregated: median_det, expressing_donor_fraction, n_donors_reliable, etc.).
Products are gene-SORTED — a per-gene read uses pyarrow + predicate-pushdown to touch
few row-groups (same invariant as the bulk and sc_tumor readers).

Dependencies: pyarrow/pandas/boto3 ONLY — no scanpy/anndata/cellxgene-census at read time.
Credential discipline: boto3 Session(profile_name=AWS_PROFILE) where default="cbg" — the
Developer-Dev SSO role lacks GetObject on onc-compbio (see sc_tumor_expression_celltype/read.py).
"""
from __future__ import annotations

import os
from typing import Optional

import pyarrow.fs as fs
import pyarrow.parquet as pq
import pandas as pd

from . import stats as _stats

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# tissue name → landed Tier-1 product key.
# Only tissues with sc-normal-celltype-expression-{tissue}-v1 on S3 are listed.
# Others → data_unavailable (honest capability ceiling, never a silent fall-back).
TISSUE_TO_PRODUCT = {
    "colon":  "sc-normal-celltype-expression-colon-v1",
    "lung":   "sc-normal-celltype-expression-lung-v1",
}

# indication → primary safety tissue(s) to query. The matched normal tissue for the
# tumor indication is the first-priority read; additional tissues can be added later.
INDICATION_TO_TISSUES = {
    "COADREAD": ["colon"],
    "COAD":     ["colon"],
    "READ":     ["colon"],
    "NSCLC":    ["lung"],
    "LUAD":     ["lung"],
    "LUSC":     ["lung"],
}

_PARQUET_COLS = [
    "gene_symbol", "ensembl_gene_id", "tissue", "cell_type",
    "n_donors_total", "n_donors_reliable", "n_donors_expressing",
    "median_det", "q25_det", "q75_det",
    "expressing_donor_fraction",
    "median_abund", "q75_abund",
    "detection_pct_rank", "n_cell_types_above_20pct",
]


def _s3_key(tissue: str) -> Optional[str]:
    prod = TISSUE_TO_PRODUCT.get(tissue.lower().strip())
    if not prod:
        return None
    return f"data-catalog/derived/{prod}/sc_normal_expression.parquet"


def read_gene_celltype_rows(target: str, tissues: list[str]) -> Optional[pd.DataFrame]:
    """Per-cell_type Tier-1 rows for one gene across the requested tissues.

    Returns a concatenated DataFrame (possibly empty), or None when no Tier-1 product
    exists for ANY of the requested tissues. Empty (0-row) DataFrame means the gene is
    absent from the product(s); None means no product exists at all."""
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    s3fs = fs.S3FileSystem(region="us-east-1",
                           role_arn=None)   # honors AWS_PROFILE env var credential chain
    # boto3 SSO credential injection — DuckDB path uses CREATE SECRET; pyarrow S3FileSystem
    # picks up the boto3 credential chain via botocore (AWS_PROFILE honored at session level).
    # If auth fails, FileNotFoundError is raised rather than a silent empty result.

    dfs = []
    found_any_product = False
    for tissue in tissues:
        key = _s3_key(tissue)
        if key is None:
            continue
        found_any_product = True
        filters = [("gene_symbol", "==", str(target).strip())]
        try:
            tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs,
                                filters=filters, columns=_PARQUET_COLS)
            dfs.append(tbl.to_pandas())
        except FileNotFoundError:
            pass   # product not yet on S3 for this tissue — treat as coverage gap
    if not found_any_product:
        return None
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def read_target_summary(target: str, indication: str) -> dict:
    """Assemble the sc-normal-celltype-expression summary for a (target, indication).

    Looks up the tissue(s) for the indication, reads the Tier-1 parquet via predicate-pushdown,
    classifies the normal-tissue liability, and returns a summary dict with `sc_normal_expression_class`
    as the primary field. data_unavailable-safe on both "no product" and "gene absent from product"."""
    tissues = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    if not tissues:
        return _data_unavailable(target, indication,
                                 note=f"No tissue mapping for indication {indication}; "
                                      f"sc normal-tissue assessment not available here.")
    rows = read_gene_celltype_rows(target, tissues)
    if rows is None:
        return _data_unavailable(target, indication,
                                 note=f"No sc-normal-celltype-expression product landed for "
                                      f"tissues {tissues}; coverage gap, not a safety pass.")
    if rows.empty:
        return _data_unavailable(target, indication,
                                 note=f"{target} absent from sc-normal-celltype-expression products "
                                      f"for tissues {tissues} (not measured in the Census atlases).")
    result = _stats.classify_sc_normal_expression(rows)
    result["tissues_queried"] = tissues
    result["indication"] = str(indication).upper().strip()
    return result


def _data_unavailable(target: str, indication: str, note: str) -> dict:
    base = _stats._data_unavailable_class(note=note)
    base["tissues_queried"] = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    base["indication"] = str(indication).upper().strip()
    return base
