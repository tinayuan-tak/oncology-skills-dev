"""structure_features_static.read — hermetic tests for the composite LIGANDABILITY leg.

No S3, no PDB/AlphaFold API. A synthetic ligandability parquet is written to the module's
cache path and the negative-cache flags are reset, so _load_ligandability_indexed reads it
directly. Pins: (1) the ligandability fields are merged onto read_target_summary regardless
of the (unmaterialized) hotspot product; (2) gene-symbol AND uniprot lookup both resolve;
(3) an absent target degrades to insufficient_evidence (coverage gap, never a false negative);
(4) the hotspot fields remain present + backward-compatible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.structure_features_static import read as R  # noqa: E402


@pytest.fixture
def synthetic_ligandability(tmp_path, monkeypatch):
    """Point the reader's ligandability cache at a synthetic parquet + reset caches."""
    df = pd.DataFrame([
        # KRAS — experimental co-crystal + pocket, foldable
        {"uniprot_id": "P01116", "gene_symbol": "KRAS",
         "structural_ligandability_class": "experimental_ligandable", "n_ligandability_axes": 2,
         "experimental_cocrystal": True, "druggable_pocket": True, "virtual_screen_hit": False,
         "cryptic_site": False, "annotated_binding_site": False, "foldable": True,
         "disorder_tractability_class": "mostly_ordered"},
        # A disordered target — measured negative
        {"uniprot_id": "Q99999", "gene_symbol": "IDPX",
         "structural_ligandability_class": "disordered_low", "n_ligandability_axes": 0,
         "experimental_cocrystal": False, "druggable_pocket": False, "virtual_screen_hit": False,
         "cryptic_site": False, "annotated_binding_site": False, "foldable": False,
         "disorder_tractability_class": "highly_disordered"},
    ])
    cache = tmp_path / "structure_ligandability_per_protein.parquet"
    df.to_parquet(cache, index=False)
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", cache)
    monkeypatch.setattr(R, "_LIGAND_STATUS", True)
    # hotspot product stays unavailable (its schema is unbuilt) — force the negative cache
    monkeypatch.setattr(R, "_DERIVED_STATUS", False)
    R._load_ligandability_indexed.cache_clear()
    R._load_structure_indexed.cache_clear()
    yield
    R._load_ligandability_indexed.cache_clear()
    R._load_structure_indexed.cache_clear()


def test_ligandability_merged_by_symbol(synthetic_ligandability):
    s = R.read_target_summary("KRAS")
    assert s["structural_ligandability_class"] == "experimental_ligandable"
    assert s["has_experimental_cocrystal"] is True
    assert s["has_druggable_pocket"] is True
    assert s["is_foldable"] is True
    assert s["n_ligandability_axes"] == 2
    # hotspot leg still present + backward-compatible (unmaterialized -> no_structure)
    assert s["hotspot_pocket_adjacency_call"] == "no_structure"
    assert s["method_version"] == "0.2.0"


def test_ligandability_lookup_by_uniprot(synthetic_ligandability):
    s = R.read_target_summary("P01116")
    assert s["structural_ligandability_class"] == "experimental_ligandable"


def test_disordered_low_is_measured_negative(synthetic_ligandability):
    s = R.read_target_summary("IDPX")
    assert s["structural_ligandability_class"] == "disordered_low"
    assert s["is_foldable"] is False
    assert s["ligandability_disorder_class"] == "highly_disordered"


def test_absent_target_is_insufficient_not_false_negative(synthetic_ligandability):
    s = R.read_target_summary("NOTATARGET")
    assert s["structural_ligandability_class"] == "insufficient_evidence"
    assert s["n_ligandability_axes"] == 0
    assert s["has_druggable_pocket"] is False


def test_product_unavailable_degrades_gracefully(tmp_path, monkeypatch):
    """No ligandability product at all -> insufficient_evidence, no crash."""
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", tmp_path / "nonexistent.parquet")
    monkeypatch.setattr(R, "_LIGAND_STATUS", False)   # definitive-absent
    monkeypatch.setattr(R, "_DERIVED_STATUS", False)
    R._load_ligandability_indexed.cache_clear()
    R._load_structure_indexed.cache_clear()
    s = R.read_target_summary("KRAS")
    assert s["structural_ligandability_class"] == "insufficient_evidence"
    R._load_ligandability_indexed.cache_clear()
