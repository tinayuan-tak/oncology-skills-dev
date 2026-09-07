"""Hermetic tests for pancan_mutation_ccf.read — synthetic per-indication clonality parquet,
no S3. Guards the read-side contract + the graceful data_unavailable floor."""

from __future__ import annotations


import pytest

pd = pytest.importorskip("pandas")
from methods.pancan_mutation_ccf.read import read_clonality  # noqa: E402


def _fixture(tmp_path) -> str:
    df = pd.DataFrame(
        [
            {
                "indication": "COADREAD",
                "gene_symbol": "APC",
                "n_mutant_samples": 395,
                "clonal_fraction": 0.9291,
                "median_ccf": 1.1842,
                "clonality_class": "predominantly_clonal",
                "evidence_tier": "inferred_diploid",
            },
            {
                "indication": "COADREAD",
                "gene_symbol": "BRCA2",
                "n_mutant_samples": 38,
                "clonal_fraction": 0.5263,
                "median_ccf": 0.8487,
                "clonality_class": "mixed_clonality",
                "evidence_tier": "inferred_diploid",
            },
        ]
    )
    p = tmp_path / "COADREAD-clonality.parquet"
    df.to_parquet(p)
    return str(p)


def test_truncal_driver_reads_predominantly_clonal(tmp_path):
    r = read_clonality("APC", "COADREAD", _fixture(tmp_path))
    assert r["clonality_class"] == "predominantly_clonal"
    assert r["clonal_fraction"] == pytest.approx(0.9291)
    assert r["n_mutant_samples"] == 395
    assert r["evidence_tier"] == "inferred_diploid"


def test_non_driver_reads_mixed(tmp_path):
    r = read_clonality("BRCA2", "COADREAD", _fixture(tmp_path))
    assert r["clonality_class"] == "mixed_clonality"


def test_gene_below_floor_is_data_unavailable(tmp_path):
    r = read_clonality("GFAP", "COADREAD", _fixture(tmp_path))
    assert r["clonality_class"] == "data_unavailable"
    assert r["n_mutant_samples"] == 0
    assert "not recurrently mutated" in r["_missing_reason"]


def test_unmaterialized_indication_is_data_unavailable(tmp_path):
    r = read_clonality("APC", "XXXX", str(tmp_path / "nope.parquet"))
    assert r["clonality_class"] == "data_unavailable"
    assert "no clonality product" in r["_missing_reason"]


def test_generic_dispatch_contract_accepts_target_as_gene(tmp_path):
    """_generic_dispatch calls fn(target=, indication=) where target IS the gene symbol. Without the
    target->gene alias the target-clonality card silently errored to data_unavailable in live comps."""
    r = read_clonality(target="APC", indication="COADREAD", product_path=_fixture(tmp_path))
    assert r["clonality_class"] != "data_unavailable"
    assert r["n_mutant_samples"] > 0
