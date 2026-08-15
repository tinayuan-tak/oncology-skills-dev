"""Per-gene reader over the sc-cite-rna-protein-concordance-v1 product.

Reads the precomputed per-gene concordance (one row per (dataset_id, gene): pearson_r_rna_vs_adt,
spearman_r_rna_vs_adt, rna_as_biomarker, n_cell_types, compartment_scope, ...). The product is
gene-SORTED — a per-gene read uses pyarrow + predicate-pushdown (same invariant as the sc_normal /
sc_tumor readers). Unlike the cell-line + tumor concordance arms, the class is NOT recomputed here:
the catalog product already carries `rna_as_biomarker` (Pearson-based, 0.6/0.3 cutoffs) — this reader
surfaces it.

Dependencies: pyarrow/pandas/boto3 ONLY. Credential discipline: boto3 Session(profile_name=AWS_PROFILE)
default="cbg" — the Developer-Dev SSO role lacks GetObject on onc-compbio.
"""
from __future__ import annotations

import os
from typing import Optional

import boto3
import pyarrow.fs as fs
import pyarrow.parquet as pq
import pandas as pd

from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
MANIFEST_ID = "sc-cite-rna-protein-concordance-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, PAYLOAD_KEY = bucket_key_for(MANIFEST_ID)

_PARQUET_COLS = [
    "dataset_id", "gene_symbol", "hgnc_id", "adt_proteins", "n_cell_types", "n_cells",
    "pearson_r_rna_vs_adt", "spearman_r_rna_vs_adt", "rna_as_biomarker",
    "compartment_scope", "matched_via",
]


def _s3fs():
    """pyarrow S3FileSystem with explicit cbg SSO creds (never the Developer-Dev fallback)."""
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    creds = boto3.Session(profile_name=profile).get_credentials().get_frozen_credentials()
    return fs.S3FileSystem(region="us-east-1", access_key=creds.access_key,
                           secret_key=creds.secret_key, session_token=creds.token)


def read_gene_rows(target: str) -> Optional[pd.DataFrame]:
    """Concordance rows for one gene (0+ rows, one per dataset). None = product not on S3
    (coverage gap); empty DataFrame = gene absent from the panel (honest not-surface-profiled)."""
    filters = [("gene_symbol", "==", str(target).strip().upper())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{PAYLOAD_KEY}", filesystem=_s3fs(),
                            filters=filters, columns=_PARQUET_COLS)
        return tbl.to_pandas()
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # A genuine NoSuchKey/404 (product not on S3) is an honest coverage gap -> None (caller emits
        # data_unavailable, unchanged). A transient/creds/broken-env failure is NOT a coverage gap ->
        # re-raise so the live-read seam surfaces an honest _live_read_error rather than a masked gap.
        if not is_definitively_absent(e):
            raise
        return None


def _data_unavailable(target: str, note: str) -> dict:
    return {"target": target, "substrate": "cite_seq_surface", "measurement_type": "rna_protein_concordance",
            "rna_as_biomarker": "data_unavailable", "rna_protein_r": None, "rna_protein_spearman": None,
            "n_cell_types": 0, "compartment_scope": None, "adt_proteins": None, "datasets": [],
            "_data_note": note}


def read_sc_surface_concordance(target: str, indication: Optional[str] = None) -> dict:
    """Surface-protein concordance summary for a target (target grain; indication ignored — the
    concordance is measured per cell type within the CITE-seq atlas, not per indication).

    Primary field `rna_as_biomarker` ∈ {adequate_proxy, partial_proxy, poor_proxy, indeterminate,
    data_unavailable}. data_unavailable-safe: distinguishes product-missing from gene-absent."""
    rows = read_gene_rows(target)
    if rows is None:
        return _data_unavailable(target, note=f"{MANIFEST_ID} not readable on S3 (coverage gap, "
                                              f"not a concordance pass).")
    if rows.empty:
        return _data_unavailable(target, note=f"{target} not in the CITE-seq surface panel "
                                              f"(not surface-profiled by ADT; not measured, not a pass).")
    # One row per dataset. v1 has a single dataset; if multiple, prefer the best-powered row
    # (most cells), and report the full dataset set. Never average across datasets here — a
    # cross-dataset consensus is a Tier-1 step.
    rows = rows.sort_values("n_cells", ascending=False).reset_index(drop=True)
    top = rows.iloc[0]
    pear = top["pearson_r_rna_vs_adt"]
    spear = top["spearman_r_rna_vs_adt"]
    return {
        "target": target,
        "substrate": "cite_seq_surface",
        "measurement_type": "rna_protein_concordance",
        "rna_as_biomarker": str(top["rna_as_biomarker"]),
        "rna_protein_r": (round(float(pear), 4) if pd.notna(pear) else None),
        "rna_protein_spearman": (round(float(spear), 4) if pd.notna(spear) else None),
        "n_cell_types": int(top["n_cell_types"]),
        "n_cells": int(top["n_cells"]),
        "compartment_scope": str(top["compartment_scope"]),
        "adt_proteins": str(top["adt_proteins"]),
        "matched_via": str(top["matched_via"]),
        "dataset_id": str(top["dataset_id"]),
        "datasets": sorted(rows["dataset_id"].astype(str).unique().tolist()),
    }
