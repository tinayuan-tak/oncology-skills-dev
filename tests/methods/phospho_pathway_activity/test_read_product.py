"""read_phospho_pathway_activity read-path tests — pushdown over the gene-sorted product.

Uses a tiny local fixture parquet (no S3/network) via the product_path kwarg. Verifies the
emitted-field contract + the three honest outcomes: sites populate, a no-site gene is
not_phosphoprotein (distinct from data_unavailable), and an out-of-panel indication is
data_unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

METHODS = Path(__file__).resolve().parents[3] / "methods"
sys.path.insert(0, str(METHODS.parent))

from methods.phospho_pathway_activity.read import (  # noqa: E402
    read_phospho_pathway_activity,
)


@pytest.fixture(scope="module")
def product(tmp_path_factory):
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    # EGFR (coad): 2 sites, one frequent; BRAF (coad): 1 low-detection site;
    # MYC (coad): appears only as a cohort row with 0 sites is not representable — instead we rely
    # on _cohort_n_tumors: a gene absent from the product but cohort present → not_phosphoprotein.
    # site_phospho_minus_protein + n_paired_tumors added in product v2 (cross-layer statistic).
    # EGFR top site t648 has residual 0.6 (> DELTA 0.25) with 80 paired tumors → exceeds_abundance True.
    rows = [
        {"cohort": "coad", "gene_symbol": "BRAF", "phosphosite": "NP_x:s365",
         "detection_fraction": 0.05, "mean_log_ratio": 0.1, "n_tumors_cohort": 100,
         "site_phospho_minus_protein": -0.1, "n_paired_tumors": 3},
        {"cohort": "coad", "gene_symbol": "EGFR", "phosphosite": "NP_y:t648",
         "detection_fraction": 0.90, "mean_log_ratio": 0.4, "n_tumors_cohort": 100,
         "site_phospho_minus_protein": 0.6, "n_paired_tumors": 80},
        {"cohort": "coad", "gene_symbol": "EGFR", "phosphosite": "NP_y:s1121",
         "detection_fraction": 0.30, "mean_log_ratio": 0.2, "n_tumors_cohort": 100,
         "site_phospho_minus_protein": -0.5, "n_paired_tumors": 40},
    ]
    df = pd.DataFrame(rows).sort_values(["gene_symbol", "cohort", "detection_fraction"],
                                        ascending=[True, True, False]).reset_index(drop=True)
    p = tmp_path_factory.mktemp("phospho") / "prod.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), p)
    return str(p)


def test_site_bearing_gene_populates(product):
    r = read_phospho_pathway_activity("EGFR", "COADREAD", product_path=product)
    assert r["phospho_activity_class"] == "phospho_active"   # max_det 0.90 >= 0.50
    assert r["n_phosphosites"] == 2
    assert r["max_site_detection_fraction"] == 0.90
    assert r["n_phosphosites_frequent"] == 1
    assert r["top_phosphosites"][0]["site"] == "NP_y:t648"   # highest detection first


def test_cross_layer_exceeds_abundance_true(product):
    # 1.1.0: real phospho-vs-protein residual. EGFR top site t648 residual 0.6 > 0.25 with 80 paired
    # tumors → phospho_exceeds_abundance True; top_site residual surfaced; per-site residual on top_phosphosites.
    r = read_phospho_pathway_activity("EGFR", "COADREAD", product_path=product)
    assert r["phospho_exceeds_abundance"] is True
    assert r["top_site_phospho_minus_protein"] == 0.6
    assert r["top_phosphosites"][0]["phospho_minus_protein"] == 0.6


def test_cross_layer_below_min_paired_is_none(product):
    # BRAF's only site has n_paired_tumors=3 (< MIN_PAIRED_TUMORS 20) → no reliable residual → None
    # (classifier then treats None as "can't tell"; BRAF is phospho_low here anyway on detection).
    r = read_phospho_pathway_activity("BRAF", "COADREAD", product_path=product)
    assert r["phospho_exceeds_abundance"] is None
    assert r["top_site_phospho_minus_protein"] is None


def test_low_detection_gene_is_phospho_low(product):
    r = read_phospho_pathway_activity("BRAF", "COADREAD", product_path=product)
    assert r["n_phosphosites"] == 1
    assert r["phospho_activity_class"] == "phospho_low"      # max_det 0.05 < 0.10


def test_gene_with_no_sites_is_not_phosphoprotein(product):
    # KRAS is absent from the product but the coad cohort IS present → not_phosphoprotein,
    # NOT data_unavailable (the distinction the old live-package path could not make cleanly).
    r = read_phospho_pathway_activity("KRAS", "COADREAD", product_path=product)
    assert r["n_phosphosites"] == 0
    assert r["phospho_activity_class"] == "not_phosphoprotein"
    assert r["n_tumors"] == 100


def test_indication_without_cohort_is_data_unavailable(product):
    r = read_phospho_pathway_activity("EGFR", "UVM", product_path=product)
    assert r["phospho_activity_class"] == "data_unavailable"
    assert "no CPTAC phospho cohort" in r["_data_note"]


def test_no_import_cptac_in_module():
    """Regression: the live cptac package import must be GONE (the whole point of the sourcing fix)."""
    src = (METHODS / "phospho_pathway_activity" / "read.py").read_text()
    assert "import cptac" not in src
    assert "cptac-phospho-per-site-per-cohort-v1" in src
