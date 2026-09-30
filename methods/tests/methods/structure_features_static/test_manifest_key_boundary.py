"""structure_features_static.read — manifest-key + schema boundary test.

The tractability-family readers historically had NO test crossing the S3 read
boundary: nothing proved (a) the reader resolves its object location through the
catalog manifest rather than a hardcoded s3://bucket/key literal, (b) it parses the
expected product schema on read, or (c) it degrades honestly on genuine absence
without failing open. So a manifest re-point (bucket move / key rename) or a schema
regression would ship GREEN. This file closes that gap for structure_features_static.

Hermetic — no live S3, no PDB/AlphaFold API. The boto3 download seam
(`R._boto3_client().download_file`) is replaced with a capturing fake that (1) records
the exact (bucket, key) the reader requests and (2) serves a synthetic product parquet
to the cache path. `bucket_key_for(<manifest_id>)` is the manifest source-of-truth the
reader is asserted to route through.
"""

from __future__ import annotations

import pandas as pd

from onc_methods.catalog_query.read import bucket_key_for
from onc_methods.structure_features_static import read as R

# Manifest-resolved (bucket, key) pairs — the single source of truth the reader must use.
DERIVED_BK = bucket_key_for(R.DERIVED_MANIFEST_ID)
LIGAND_BK = bucket_key_for(R.LIGAND_MANIFEST_ID)


def _structure_df() -> pd.DataFrame:
    """Minimal fixture in the hotspot-adjacency product schema."""
    return pd.DataFrame(
        [
            {
                "gene_symbol": "KRAS",
                "uniprot_ac": "P01116",
                "hotspot_pocket_adjacency_call": "adjacent",
                "mutation_hotspot_in_druggable_pocket": True,
                "pdb_ids_available": ["6OIM", "4OBE"],
                "pdb_best_resolution_angstrom": 1.65,
                "pdb_best_method": "X-RAY DIFFRACTION",
                "alphafold_plddt_mean": 92.0,
                "alphafold_plddt_min": 40.0,
                "alphafold_plddt_min_domain": 55.0,
                "n_domains_low_plddt": 0,
                "disordered_fraction": 0.05,
                "alphafold_prediction_id": "AF-P01116-F1",
            }
        ]
    )


def _ligand_df() -> pd.DataFrame:
    """Minimal fixture in the composite ligandability product schema."""
    return pd.DataFrame(
        [
            {
                "uniprot_id": "P01116",
                "gene_symbol": "KRAS",
                "structural_ligandability_class": "experimental_ligandable",
                "n_ligandability_axes": 2,
                "experimental_cocrystal": True,
                "druggable_pocket": True,
                "virtual_screen_hit": False,
                "cryptic_site": False,
                "annotated_binding_site": False,
                "foldable": True,
                "disorder_tractability_class": "mostly_ordered",
            }
        ]
    )


class _CapturingClient:
    """download_file records each (bucket, key) requested and serves the matching product parquet."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def download_file(self, bucket, key, dest):
        self.calls.append((bucket, key))
        if (bucket, key) == DERIVED_BK:
            _structure_df().to_parquet(dest, index=False)
        elif (bucket, key) == LIGAND_BK:
            _ligand_df().to_parquet(dest, index=False)
        else:  # a key that does NOT match the manifest — surface it loudly in the test
            raise AssertionError(f"reader requested an off-manifest object: {(bucket, key)!r}")


class _AbsentClient:
    def __init__(self, exc):
        self._exc = exc

    def download_file(self, bucket, key, dest):
        raise self._exc


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(R, "CACHE_PARQUET", tmp_path / "structure_features.parquet")
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", tmp_path / "structure_ligandability_per_protein.parquet")
    monkeypatch.setattr(R, "_DERIVED_STATUS", None)
    monkeypatch.setattr(R, "_LIGAND_STATUS", None)
    R._load_structure_indexed.cache_clear()
    R._load_ligandability_indexed.cache_clear()


def test_manifest_ids_resolve():
    """The reader carries manifest IDs that resolve to a (bucket, key) via the catalog — not a
    hardcoded literal. Guards the fix: a re-point in the manifest propagates here."""
    assert DERIVED_BK[0] and DERIVED_BK[1].endswith(".parquet")
    assert LIGAND_BK[0] and LIGAND_BK[1].endswith(".parquet")


def test_reader_requests_manifest_resolved_keys(monkeypatch, tmp_path):
    """The boundary: both product downloads must be issued against the MANIFEST-resolved
    (bucket, key), not a hardcoded S3 literal. A reader that reverts to a drifted literal reds here."""
    _reset(monkeypatch, tmp_path)
    client = _CapturingClient()
    monkeypatch.setattr(R, "_boto3_client", lambda: client)

    R.read_target_summary("KRAS")

    assert DERIVED_BK in client.calls, f"hotspot leg did not resolve via manifest: {client.calls}"
    assert LIGAND_BK in client.calls, f"ligandability leg did not resolve via manifest: {client.calls}"


def test_schema_boundary_parses_expected_fields(monkeypatch, tmp_path):
    """Reading the manifest-resolved product parses the expected schema into the card summary shape."""
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(R, "_boto3_client", lambda: _CapturingClient())

    out = R.read_target_summary("KRAS")

    # Hotspot-adjacency leg parsed from the derived product schema.
    assert out["hotspot_pocket_adjacency_call"] == "adjacent"
    assert out["mutation_hotspot_in_druggable_pocket"] is True
    assert out["pdb_coverage_class"] == "partial"  # 2 PDB ids
    assert out["alphafold_confidence_class"] == "high"  # plddt_mean 92
    assert out["pdb_ids_available"] == ["6OIM", "4OBE"]
    assert out["_data_source"] == R.DERIVED_MANIFEST_ID
    # Composite ligandability leg parsed from its product schema.
    assert out["structural_ligandability_class"] == "experimental_ligandable"
    assert out["has_experimental_cocrystal"] is True
    assert out["_ligandability_source"] == R.LIGAND_MANIFEST_ID


def test_absence_degrades_without_failing_open(monkeypatch, tmp_path):
    """Genuine object absence (definitive 404/NoSuchKey) → honest coverage-gap summary, never a
    crash and never a false measured-negative."""
    _reset(monkeypatch, tmp_path)
    from botocore.exceptions import ClientError

    monkeypatch.setattr(
        R, "_boto3_client", lambda: _AbsentClient(ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"))
    )

    out = R.read_target_summary("KRAS")
    assert out["hotspot_pocket_adjacency_call"] == "no_structure"
    assert out["_data_note"] == "structure_data_unavailable"
    assert out["structural_ligandability_class"] == "insufficient_evidence"
