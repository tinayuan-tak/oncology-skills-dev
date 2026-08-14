"""Tests for hcmi_model_availability — the per-indication translational model-availability signal (#1)."""
from __future__ import annotations

import pytest

from methods.hcmi_model_availability import read_model_availability
from methods.hcmi_model_availability.cli import (
    aggregate_model_availability,
    crosswalk_indication,
    _availability_class,
)


# ── crosswalk unit tests (the (primary_site, disease_type) -> indication judgment) ──────────────────
@pytest.mark.parametrize("ps,dt,expected", [
    ("Colon", "Adenomas and Adenocarcinomas", "COADREAD"),
    ("Rectum", "Adenomas and Adenocarcinomas", "COADREAD"),
    ("Rectosigmoid junction", "Adenomas and Adenocarcinomas", "COADREAD"),
    ("Pancreas", "Ductal and Lobular Neoplasms", "PAAD"),
    ("Pancreas", "Adenomas and Adenocarcinomas", "PAAD"),
    ("Bronchus and lung", "Adenomas and Adenocarcinomas", "NSCLC"),
    ("Bronchus and lung", "Squamous Cell Neoplasms", "NSCLC"),
    ("Stomach", "Adenomas and Adenocarcinomas", "GC"),
    # unmapped histologies / sites -> None (conservative: never mis-assign)
    ("Breast", "Ductal and Lobular Neoplasms", None),
    ("Skin", "Nevi and Melanomas", None),
    ("Colon", "Cystic, Mucinous and Serous Neoplasms", None),  # non-adenocarcinoma colon histology
    (None, None, None),
])
def test_crosswalk_maps_core_indications_and_rejects_unmapped(ps, dt, expected):
    assert crosswalk_indication(ps, dt) == expected


def test_availability_class_thresholds():
    assert _availability_class(209) == "deep_model_coverage"
    assert _availability_class(50) == "deep_model_coverage"
    assert _availability_class(49) == "moderate_model_coverage"
    assert _availability_class(15) == "moderate_model_coverage"
    assert _availability_class(14) == "sparse_model_coverage"
    assert _availability_class(0) == "sparse_model_coverage"


# ── hermetic reader tests (local product_path, no S3) ────────────────────────────────────────────────
@pytest.fixture
def product(tmp_path):
    import pandas as pd
    p = tmp_path / "hcmi_model_availability.parquet"
    pd.DataFrame([
        {"indication": "COADREAD", "n_patient_derived_models": 209,
         "model_availability_class": "deep_model_coverage", "source": "HCMI-CMDC-DR45",
         "primary_site_breakdown": "Colon|Adenomas and Adenocarcinomas=153"},
        {"indication": "GC", "n_patient_derived_models": 25,
         "model_availability_class": "moderate_model_coverage", "source": "HCMI-CMDC-DR45",
         "primary_site_breakdown": "Stomach|Adenomas and Adenocarcinomas=25"},
    ]).to_parquet(p)
    return str(p)


def test_read_hit_returns_summary(product):
    r = read_model_availability("COADREAD", product_path=product)
    assert r["model_availability_class"] == "deep_model_coverage"
    assert r["n_patient_derived_models"] == 209
    assert r["source"] == "HCMI-CMDC-DR45"


def test_read_unmapped_indication_is_graceful(product):
    r = read_model_availability("PRAD", product_path=product)  # not in the crosswalk / product
    assert r["model_availability_class"] == "data_unavailable"
    assert r["n_patient_derived_models"] == 0
    assert "not in the HCMI" in r["_missing_reason"]


def test_read_missing_product_is_graceful(tmp_path):
    r = read_model_availability("COADREAD", product_path=str(tmp_path / "nope.parquet"))
    assert r["model_availability_class"] == "data_unavailable"
    assert "no HCMI model-availability product" in r["_missing_reason"]


# ── live biology-gate (skips if HCMI source unreachable) ─────────────────────────────────────────────
def test_hcmi_gi_heavy_composition_biology_gate():
    """HCMI is documented GI/colorectal-heavy: COADREAD must be the deepest-covered core indication."""
    try:
        rows = aggregate_model_availability()
    except Exception as e:  # noqa: BLE001 — no S3 creds in CI → skip, not fail
        pytest.skip(f"HCMI source unreachable: {e}")
    if not rows:
        pytest.skip("HCMI source returned no rows (unreachable)")
    by = {r["indication"]: r for r in rows}
    assert "COADREAD" in by, "COADREAD should map from HCMI colon/rectum adenocarcinoma models"
    assert by["COADREAD"]["model_availability_class"] == "deep_model_coverage"
    # COADREAD is the deepest-covered (GI-heavy cohort)
    assert by["COADREAD"]["n_patient_derived_models"] == max(r["n_patient_derived_models"] for r in rows)


# ── generic-dispatch contract (2026-08-14): compose-dashboard calls fn(target=, indication=) ──────────
def test_generic_dispatch_contract_accepts_target_kwarg(product):
    """_live_readers._generic_dispatch calls every reader as fn(target=, indication=). The reader must
    accept target (ignored — model availability is target-independent) or the card silently errors to
    data_unavailable in live compositions."""
    r = read_model_availability(target="KRAS", indication="COADREAD", product_path=product)
    assert r["model_availability_class"] == "deep_model_coverage"
    assert r["n_patient_derived_models"] == 209
