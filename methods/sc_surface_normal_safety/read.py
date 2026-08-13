"""Per-gene reader over sc-cite-surface-normal-immune-v1 — normal-immune surface-protein safety.

Product is gene-SORTED; per-gene read uses pyarrow predicate-pushdown. Classifies the target's
SURFACE-protein footprint across normal immune cell types into a safety-liability ladder. Class is
DERIVED here from the per-(gene, cell_type) positive fractions (the product carries the measurements,
not the class). data_unavailable-safe: product-missing (coverage gap) vs gene-absent (not surface-
profiled — honest, never a safety pass).

Dependencies: pyarrow/pandas/boto3 only. Credential discipline: boto3 Session(profile_name=cbg).
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
MANIFEST_ID = "sc-cite-surface-normal-immune-v1"
S3_BUCKET, PAYLOAD_KEY = bucket_key_for(MANIFEST_ID)

_PARQUET_COLS = ["gene_symbol", "hgnc_id", "adt_proteins", "cell_type", "compartment_scope",
                 "n_cells", "n_donors", "adt_mean_clr_median", "adt_positive_fraction_median"]

# surface-liability ladder on the PEAK cross-donor mean CLR-ADT across normal immune cell types.
# mean-CLR (not positive_fraction) is the safety signal: ADT ambient/spillover makes per-cell CLR>0
# fire almost everywhere (a high-background antibody reads "positive" even on lineages that don't
# display it), so a positive-fraction breadth count OVER-CALLS. The relative mean-CLR level separates
# true display (CD8A ~4.4 on T lineages) from spillover (~ -1 on B cells).
_HIGH = 2.0         # peak mean-CLR clearly enriched on ≥1 normal immune lineage → off-tumor hazard
_MODERATE = 0.5
_LOW = 0.0          # peak mean-CLR at/above the cell's own protein average somewhere
# a cell type "displays" the antigen (breadth count) at/above this absolute mean-CLR floor
_DISPLAY_CLR = 1.0


def _s3fs():
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    creds = boto3.Session(profile_name=profile).get_credentials().get_frozen_credentials()
    return fs.S3FileSystem(region="us-east-1", access_key=creds.access_key,
                           secret_key=creds.secret_key, session_token=creds.token)


def read_gene_rows(target: str) -> Optional[pd.DataFrame]:
    """Per-(cell_type) surface rows for one gene. None = product not on S3; empty = gene absent."""
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{PAYLOAD_KEY}", filesystem=_s3fs(),
                            filters=[("gene_symbol", "==", str(target).strip().upper())],
                            columns=_PARQUET_COLS)
        return tbl.to_pandas()
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        return None


def _classify(peak_clr: float) -> str:
    if peak_clr >= _HIGH:
        return "high_surface_on_normal_immune"
    if peak_clr >= _MODERATE:
        return "moderate_surface_on_normal_immune"
    if peak_clr >= _LOW:
        return "low_surface_on_normal_immune"
    return "not_surface_detected_normal_immune"


def _data_unavailable(target: str, note: str) -> dict:
    return {"target": target, "compartment_scope": "immune_pbmc",
            "sc_surface_normal_class": "data_unavailable", "max_surface_cell_type": None,
            "max_positive_fraction": None, "max_mean_clr": None,
            "n_celltypes_surface_positive": 0, "_data_note": note}


def read_sc_surface_normal_safety(target: str, indication: Optional[str] = None) -> dict:
    """Normal-immune surface-protein safety summary for a target (indication accepted, not consumed —
    the immune substrate is indication-independent). Primary `sc_surface_normal_class`."""
    rows = read_gene_rows(target)
    if rows is None:
        return _data_unavailable(target, note=f"{MANIFEST_ID} not readable on S3 (coverage gap, not a safety pass).")
    if rows.empty:
        return _data_unavailable(target, note=f"{target} not surface-profiled by ADT in the immune panel "
                                              f"(not measured; not a safety pass).")
    top = rows.loc[rows["adt_mean_clr_median"].idxmax()]     # peak-display lineage (by mean CLR)
    peak_clr = float(top["adt_mean_clr_median"])
    n_display = int((rows["adt_mean_clr_median"] >= _DISPLAY_CLR).sum())
    return {
        "target": target,
        "compartment_scope": str(top["compartment_scope"]),
        "sc_surface_normal_class": _classify(peak_clr),
        "max_surface_cell_type": str(top["cell_type"]),
        "max_mean_clr": round(peak_clr, 4),
        "max_positive_fraction": round(float(top["adt_positive_fraction_median"]), 4),
        "n_celltypes_surface_displaying": n_display,       # cell types with mean-CLR >= 1.0 (broad off-tumor breadth)
        "n_cell_types_assessed": int(len(rows)),
    }
