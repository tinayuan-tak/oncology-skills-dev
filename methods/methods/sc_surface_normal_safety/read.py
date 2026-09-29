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
import pandas as pd
import pyarrow.fs as fs
import pyarrow.parquet as pq

from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
# Normal surface-protein shards, unioned across compartments (peripheral immune + bone marrow).
# The class is the PEAK across ALL shards' cell types (an antigen displayed in EITHER compartment is
# an off-tumor floor). compartment_scope distinguishes them in each row. Add a shard = one line here.
MANIFEST_IDS = [
    "sc-cite-surface-normal-immune-v1",  # Hao 2021 PBMC (peripheral immune)
    "sc-cite-surface-normal-bonemarrow-v1",  # NeurIPS 2021 BMMC (hematopoietic-progenitor compartment)
]
_PRODUCTS = [(mid, *bucket_key_for(mid)) for mid in MANIFEST_IDS]

_PARQUET_COLS = [
    "gene_symbol",
    "hgnc_id",
    "adt_proteins",
    "cell_type",
    "compartment_scope",
    "n_cells",
    "n_donors",
    "adt_mean_clr_median",
    "adt_positive_fraction_median",
]

# surface-liability ladder on the PEAK cross-donor mean CLR-ADT across normal immune cell types.
# mean-CLR (not positive_fraction) is the safety signal: ADT ambient/spillover makes per-cell CLR>0
# fire almost everywhere (a high-background antibody reads "positive" even on lineages that don't
# display it), so a positive-fraction breadth count OVER-CALLS. The relative mean-CLR level separates
# true display (CD8A ~4.4 on T lineages) from spillover (~ -1 on B cells).
_HIGH = 2.0  # peak mean-CLR clearly enriched on ≥1 normal immune lineage → off-tumor hazard
_MODERATE = 0.5
_LOW = 0.0  # peak mean-CLR at/above the cell's own protein average somewhere
# a cell type "displays" the antigen (breadth count) at/above this absolute mean-CLR floor
_DISPLAY_CLR = 1.0

# Minimum-support floor for a cell type to be eligible to SET the safety class (argmax/breadth).
# Matches the avidity normal-gate contract (data-catalog specs/sc-normal-samecell-coexpr.md §6.3):
# a thin cell type (single donor / a handful of cells) whose peak CLR clears _HIGH via ADT spillover
# would otherwise mint an unearned off-tumor safety hazard. Dropout biases surface abundance DOWN, so
# the un-floored MAX is NOT conservative — a thin, noisy lineage produces a FALSE hazard. Cell types
# below the floor are dropped from class derivation; if NONE pass, the target is under-powered
# (data_unavailable), never a measured safety pass.
_MIN_DONORS = 3
_MIN_CELLS = 10


def _s3fs():
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    creds = boto3.Session(profile_name=profile).get_credentials().get_frozen_credentials()
    return fs.S3FileSystem(
        region="us-east-1", access_key=creds.access_key, secret_key=creds.secret_key, session_token=creds.token
    )


def read_gene_rows(target: str) -> Optional[pd.DataFrame]:
    """Per-(cell_type) surface rows for one gene, UNIONED across all normal-surface shards
    (immune + bone marrow). None = NO shard readable on S3 (coverage gap); empty DataFrame = gene
    absent from every present shard (not surface-profiled)."""
    gene = str(target).strip().upper()
    frames, any_present = [], False
    fs_ = _s3fs()
    for _mid, bucket, key in _PRODUCTS:
        try:
            tbl = pq.read_table(
                f"{bucket}/{key}", filesystem=fs_, filters=[("gene_symbol", "==", gene)], columns=_PARQUET_COLS
            )
            any_present = True
            frames.append(tbl.to_pandas())
        except FileNotFoundError:
            continue  # this shard not on S3 yet — treat as coverage gap for that shard only
        except Exception:  # noqa: BLE001
            continue
    if not any_present:
        return None
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_PARQUET_COLS)


def _classify(peak_clr: float) -> str:
    if peak_clr >= _HIGH:
        return "high_surface_on_normal_immune"
    if peak_clr >= _MODERATE:
        return "moderate_surface_on_normal_immune"
    if peak_clr >= _LOW:
        return "low_surface_on_normal_immune"
    return "not_surface_detected_normal_immune"


def _data_unavailable(target: str, note: str) -> dict:
    return {
        "target": target,
        "compartment_scope": "immune_pbmc",
        "sc_surface_normal_class": "data_unavailable",
        "max_surface_cell_type": None,
        "max_positive_fraction": None,
        "max_mean_clr": None,
        "n_celltypes_surface_positive": 0,
        "_data_note": note,
    }


def read_sc_surface_normal_safety(target: str, indication: Optional[str] = None) -> dict:
    """Normal-immune surface-protein safety summary for a target (indication accepted, not consumed —
    the immune substrate is indication-independent). Primary `sc_surface_normal_class`."""
    rows = read_gene_rows(target)
    if rows is None:
        return _data_unavailable(
            target,
            note="no normal-surface shard readable on S3 "
            f"({', '.join(MANIFEST_IDS)}) — coverage gap, not a safety pass.",
        )
    if rows.empty:
        return _data_unavailable(
            target, note=f"{target} not surface-profiled by ADT in the immune panel (not measured; not a safety pass)."
        )
    # Minimum-support floor: only cell types backed by >= _MIN_DONORS donors AND >= _MIN_CELLS cells
    # are eligible to set the safety class. A thin/noisy lineage clearing _HIGH via ADT spillover would
    # otherwise mint a FALSE off-tumor hazard (dropout biases surface abundance DOWN → un-floored MAX is
    # not conservative). See _MIN_DONORS/_MIN_CELLS.
    supported = rows[(rows["n_donors"] >= _MIN_DONORS) & (rows["n_cells"] >= _MIN_CELLS)]
    if supported.empty:
        return _data_unavailable(
            target,
            note=f"{target} surface-profiled but NO cell type meets the support floor "
            f"(>= {_MIN_DONORS} donors AND >= {_MIN_CELLS} cells) — under-powered, not a safety pass.",
        )
    top = supported.loc[supported["adt_mean_clr_median"].idxmax()]  # peak-display lineage (by mean CLR)
    peak_clr = float(top["adt_mean_clr_median"])
    n_display = int((supported["adt_mean_clr_median"] >= _DISPLAY_CLR).sum())
    return {
        "target": target,
        "compartment_scope": str(top["compartment_scope"]),
        "sc_surface_normal_class": _classify(peak_clr),
        "max_surface_cell_type": str(top["cell_type"]),
        "max_mean_clr": round(peak_clr, 4),
        "max_positive_fraction": round(float(top["adt_positive_fraction_median"]), 4),
        "max_surface_n_donors": int(top["n_donors"]),  # support behind the class-driving lineage
        "max_surface_n_cells": int(top["n_cells"]),
        "n_celltypes_surface_displaying": n_display,  # cell types with mean-CLR >= 1.0 (broad off-tumor breadth)
        "n_cell_types_assessed": int(len(rows)),  # all cell types read (pre-floor)
        "n_cell_types_supported": int(len(supported)),  # cell types passing the support floor
        "compartments_assessed": sorted(rows["compartment_scope"].astype(str).unique().tolist()),
    }
