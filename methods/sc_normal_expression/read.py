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

import boto3
import pyarrow.fs as fs
import pyarrow.parquet as pq
import pandas as pd

from . import stats as _stats
from methods.normal_tissue_safety_common import SC_NORMAL_ESSENTIAL_TISSUES

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# tissue name → landed Tier-1 product key.
# Only tissues with sc-normal-celltype-expression-{tissue}-v1 on S3 are listed.
# Others → data_unavailable (honest capability ceiling, never a silent fall-back).
# Keys are the hyphen-free tissue names; product IDs use hyphenated slugs.
# 2026-08-12: brain (critical fix — in card since #298 but missing here), plus 4 new tissues
# now on S3 (data-catalog PR #330 + the normal-tissue batch PRs #275–#286 + expansion set).
TISSUE_TO_PRODUCT = {
    "colon":            "sc-normal-celltype-expression-colon-v1",
    "lung":             "sc-normal-celltype-expression-lung-v1",
    "heart":            "sc-normal-celltype-expression-heart-v1",
    "liver":            "sc-normal-celltype-expression-liver-v1",
    "kidney":           "sc-normal-celltype-expression-kidney-v1",
    "stomach":          "sc-normal-celltype-expression-stomach-v1",
    "bone_marrow":      "sc-normal-celltype-expression-bone-marrow-v1",
    "skin":             "sc-normal-celltype-expression-skin-v1",
    "small_intestine":  "sc-normal-celltype-expression-small-intestine-v1",
    # Added 2026-08-12:
    "brain":            "sc-normal-celltype-expression-brain-v1",           # always-on CNS safety (36M cells, 172 types)
    "esophagus":        "sc-normal-celltype-expression-esophagus-v1",        # ESCA; squamous-normal proxy for HNSC
    "pancreas":         "sc-normal-celltype-expression-pancreas-v1",         # PAAD normal comparator
    "ovary":            "sc-normal-celltype-expression-ovary-v1",             # OV normal comparator
    "prostate_gland":   "sc-normal-celltype-expression-prostate-gland-v1",   # PRAD normal comparator
    # Added 2026-08-15: complete the map to all 19 landed normal-tissue shards so the card's
    # required_inputs can honestly declare the full atlas (readable via tissues_for_indication /
    # future indication maps; not yet in any indication's always-on scan set).
    "adrenal_gland":    "sc-normal-celltype-expression-adrenal-gland-v1",
    "bladder_organ":    "sc-normal-celltype-expression-bladder-organ-v1",
    "large_intestine":  "sc-normal-celltype-expression-large-intestine-v1",
    "spleen":           "sc-normal-celltype-expression-spleen-v1",
    "uterus":           "sc-normal-celltype-expression-uterus-v1",
}

# SAFETY-ESSENTIAL tissues queried for EVERY target regardless of indication. On-target
# toxicity in these organs is catastrophic and modality-limiting whether the tumor is colon,
# lung, or anything else — a BiTE/ADC against a target expressed in cardiomyocytes, hepatocytes,
# nephron tubule, or hematopoietic progenitors is dangerous independent of the treated indication.
# So these are ALWAYS included in the liability read, in addition to the indication-matched tissue.
# SINGLE-SOURCED (cards review 2026-08-17, S1-3) from normal_tissue_safety_common — this promotes
# the BRAIN shard (advertised as "always-on CNS safety" but never actually queried → CNS on-target
# tox was silently unassessed for every target) and the ADRENAL_GLAND shard (endocrine hole) to the
# always-on set. Both shards already exist in TISSUE_TO_PRODUCT.
SAFETY_ESSENTIAL_TISSUES = list(SC_NORMAL_ESSENTIAL_TISSUES)

# indication → tumor-matched normal tissue(s). The matched tissue is queried IN ADDITION to the
# always-on SAFETY_ESSENTIAL_TISSUES (see tissues_for_indication).
# 2026-08-12: STAD/ESCA/PAAD/HNSC/OV/PRAD added as 3CA buckets land and new Tier-1 products are
# on S3. HNSC maps to esophagus — the best available squamous-normal proxy (oral/pharyngeal
# mucosa is not a distinct Census tissue_general; squamous esophagus is the closest lineage match).
INDICATION_TO_TISSUES = {
    "COADREAD": ["colon"],
    "COAD":     ["colon"],
    "READ":     ["colon"],
    "NSCLC":    ["lung"],
    "LUAD":     ["lung"],
    "LUSC":     ["lung"],
    "STAD":     ["stomach"],
    "ESCA":     ["esophagus"],
    "PAAD":     ["pancreas"],
    "HNSC":     ["esophagus"],    # squamous-normal proxy (oral/pharyngeal mucosa absent from Census)
    "OV":       ["ovary"],
    "PRAD":     ["prostate_gland"],
}


def tissues_for_indication(indication: str) -> list[str]:
    """Tissues to query for a (target, indication) liability read: the tumor-matched normal
    tissue(s) UNION the always-on safety-essential tissues, de-duplicated, order-stable.
    Safety-essential tissues are queried for EVERY indication (cross-tissue on-target-tox check);
    the matched tissue adds indication-local context. Unknown indication → safety-essential only
    (still a meaningful cross-tissue safety read, never an empty/abstain result)."""
    matched = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    out: list[str] = []
    for t in matched + SAFETY_ESSENTIAL_TISSUES:
        if t not in out:
            out.append(t)
    return out

_PARQUET_COLS = [
    "gene_symbol", "ensembl_gene_id", "tissue", "cell_type",
    "n_donors_total", "n_donors_reliable", "n_datasets_reliable", "n_donors_expressing",
    "median_det", "q25_det", "q75_det",
    "expressing_donor_fraction",
    "median_abund", "q25_abund", "q75_abund",
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
    # Explicit credential injection — mirrors aggregate.py's CREATE SECRET pattern.
    # pyarrow S3FileSystem can use AWS_PROFILE via botocore, but that silently falls back to the
    # Developer-Dev role (cmp-dev) if the env var is unset, which lacks GetObject on onc-compbio.
    # Explicit boto3 Session guarantees the cbg SSO profile is always used regardless of env state.
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    session = boto3.Session(profile_name=profile)
    creds = session.get_credentials().get_frozen_credentials()
    s3fs = fs.S3FileSystem(
        region="us-east-1",
        access_key=creds.access_key,
        secret_key=creds.secret_key,
        session_token=creds.token,
    )

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

    Queries the tumor-matched normal tissue(s) UNION the always-on safety-essential tissues
    (heart/liver/kidney/bone_marrow), reads the Tier-1 parquet via predicate-pushdown, classifies
    the normal-tissue liability across ALL queried cell types, and returns a summary dict with
    `sc_normal_expression_class` as the primary field. data_unavailable-safe on both "no product"
    and "gene absent from product". Because safety-essential tissues are always included, even an
    unknown indication yields a meaningful cross-tissue safety read (never an abstain-by-mapping-gap)."""
    tissues = tissues_for_indication(indication)
    rows = read_gene_celltype_rows(target, tissues)
    if rows is None:
        return _data_unavailable(target, indication,
                                 note=f"No sc-normal-celltype-expression product landed for "
                                      f"tissues {tissues}; coverage gap, not a safety pass.")
    if rows.empty:
        return _data_unavailable(target, indication,
                                 note=f"{target} absent from sc-normal-celltype-expression products "
                                      f"for tissues {tissues} (not measured in the Census atlases).")
    # origin_tissues = the tumor's tissue-of-origin ONLY (matched normal), NOT the always-on
    # safety-essential organs — so the classifier can split origin-tissue essential expression
    # (on-tissue, therapeutic-window-arbitrated) from non-origin critical-organ expression (hard veto).
    origin_tissues = INDICATION_TO_TISSUES.get(str(indication).upper().strip(), [])
    result = _stats.classify_sc_normal_expression(rows, origin_tissues=origin_tissues)
    result["tissues_queried"] = tissues
    result["origin_tissues"] = origin_tissues
    result["indication"] = str(indication).upper().strip()
    return result


def _data_unavailable(target: str, indication: str, note: str) -> dict:
    base = _stats._data_unavailable_class(note=note)
    base["tissues_queried"] = tissues_for_indication(indication)
    base["indication"] = str(indication).upper().strip()
    return base
