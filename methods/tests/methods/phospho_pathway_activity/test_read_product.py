"""read_phospho_pathway_activity read-path tests — pushdown over the gene-sorted product.

Uses tiny local fixture parquets (no S3/network) via the product_path / protein_product_path kwargs.
Verifies the emitted-field contract + the honest outcomes: sites populate; a no-site gene whose TOTAL
PROTEIN is detected reads phospho_not_detected (a MEASURED no-detection); a no-site gene whose protein
is ALSO undetected reads data_unavailable with an uninformative-axis reason (the ALK/LUAD fix); and an
out-of-panel indication is data_unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

METHODS = Path(__file__).resolve().parents[3] / "onc_methods"

from onc_methods.phospho_pathway_activity.read import (
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
        {
            "cohort": "coad",
            "gene_symbol": "BRAF",
            "phosphosite": "NP_x:s365",
            "detection_fraction": 0.05,
            "mean_log_ratio": 0.1,
            "n_tumors_cohort": 100,
            "site_phospho_minus_protein": -0.1,
            "n_paired_tumors": 3,
        },
        {
            "cohort": "coad",
            "gene_symbol": "EGFR",
            "phosphosite": "NP_y:t648",
            "detection_fraction": 0.90,
            "mean_log_ratio": 0.4,
            "n_tumors_cohort": 100,
            "site_phospho_minus_protein": 0.6,
            "n_paired_tumors": 80,
        },
        {
            "cohort": "coad",
            "gene_symbol": "EGFR",
            "phosphosite": "NP_y:s1121",
            "detection_fraction": 0.30,
            "mean_log_ratio": 0.2,
            "n_tumors_cohort": 100,
            "site_phospho_minus_protein": -0.5,
            "n_paired_tumors": 40,
        },
    ]
    df = (
        pd.DataFrame(rows)
        .sort_values(["gene_symbol", "cohort", "detection_fraction"], ascending=[True, True, False])
        .reset_index(drop=True)
    )
    p = tmp_path_factory.mktemp("phospho") / "prod.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), p)
    return str(p)


@pytest.fixture(scope="module")
def protein_product(tmp_path_factory):
    """Total-protein detection probe fixture (1.2.0). Cohort keys are UPPER-CASED in the protein product.
    KRAS's protein IS detected in COAD (→ a measured no-phospho read); ALKLIKE's is NOT (→ the axis is
    uninformative, the ALK/LUAD shape)."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [
        {"cohort": "COAD", "gene_symbol": "KRAS", "protein_median_log2_tumor": 0.2},
        {"cohort": "COAD", "gene_symbol": "EGFR", "protein_median_log2_tumor": 0.5},
        {"cohort": "COAD", "gene_symbol": "BRAF", "protein_median_log2_tumor": 0.1},
        # ALKLIKE deliberately ABSENT from the protein product for COAD.
    ]
    df = pd.DataFrame(rows).sort_values(["gene_symbol", "cohort"]).reset_index(drop=True)
    p = tmp_path_factory.mktemp("protein") / "prot.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), p)
    return str(p)


def test_site_bearing_gene_populates(product):
    r = read_phospho_pathway_activity("EGFR", "COADREAD", product_path=product)
    assert r["phospho_activity_class"] == "phospho_active"  # max_det 0.90 >= 0.50
    assert r["n_phosphosites"] == 2
    assert r["max_site_detection_fraction"] == 0.90
    assert r["n_phosphosites_frequent"] == 1
    assert r["top_phosphosites"][0]["site"] == "NP_y:t648"  # highest detection first


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
    assert r["phospho_activity_class"] == "phospho_low"  # max_det 0.05 < 0.10


def test_gene_with_no_sites_but_protein_detected_is_phospho_not_detected(product, protein_product):
    # KRAS has no phosphosites in the fixture but the coad cohort IS present and KRAS's TOTAL PROTEIN
    # is detected → phospho_not_detected: a MEASURED no-detection on the phospho axis.
    r = read_phospho_pathway_activity("KRAS", "COADREAD", product_path=product, protein_product_path=protein_product)
    assert r["n_phosphosites"] == 0
    assert r["phospho_activity_class"] == "phospho_not_detected"
    assert r["n_tumors"] == 100
    assert r["total_protein_detected_in_cohort"] is True
    assert r["phospho_axis_uninformative_reason"] is None
    assert "MEASURED" in r["_data_note"] and "unphosphorylatable" in r["_data_note"]


def test_no_sites_and_no_protein_is_uninformative_axis(product, protein_product):
    """THE ALK/LUAD FIX. A gene with no phosphosites whose TOTAL PROTEIN is also undetected in the cohort
    must read data_unavailable (axis UNINFORMATIVE) — never a biological negative. ALK reads 0 sites in
    all 10 CPTAC cohorts and its protein is detected in only 1, yet it is an RTK defined by
    autophosphorylation; the retired `not_phosphoprotein` token asserted the opposite."""
    r = read_phospho_pathway_activity("ALKLIKE", "COADREAD", product_path=product, protein_product_path=protein_product)
    assert r["n_phosphosites"] == 0
    assert r["phospho_activity_class"] == "data_unavailable"
    assert r["total_protein_detected_in_cohort"] is False
    assert r["phospho_axis_uninformative_reason"] == "total_protein_not_detected_in_cohort"
    assert "UNINFORMATIVE" in r["_data_note"]


def test_no_sites_without_protein_probe_fails_soft(product):
    """No protein_product_path → the probe returns None (genuine absence) and the class FAILS SOFT to
    phospho_not_detected rather than silently demoting the axis to data_unavailable."""
    r = read_phospho_pathway_activity("KRAS", "COADREAD", product_path=product)
    assert r["phospho_activity_class"] == "phospho_not_detected"
    assert r["total_protein_detected_in_cohort"] is None


def test_cross_cohort_phosphoprotein_evidence_is_emitted(product, protein_product):
    """The cross-cohort probe is the evidence that separates "this cohort missed it" from "CPTAC never
    sees it". BRAF has sites only in coad here → detected in 1 cohort, none elsewhere."""
    r = read_phospho_pathway_activity("BRAF", "COADREAD", product_path=product, protein_product_path=protein_product)
    assert r["n_cohorts_with_phosphosites"] == 1
    assert r["phosphoprotein_detected_in_other_cohorts"] is False


def test_detection_context_fields_emitted_on_site_bearing_path(product, protein_product):
    """The 4 detection-context fields are card-declared summary_fields and must be present on EVERY
    path (the emission sweep is a key-presence check), including the phospho_active path."""
    r = read_phospho_pathway_activity("EGFR", "COADREAD", product_path=product, protein_product_path=protein_product)
    assert r["phospho_activity_class"] == "phospho_active"
    for f in (
        "total_protein_detected_in_cohort",
        "n_cohorts_with_phosphosites",
        "phosphoprotein_detected_in_other_cohorts",
        "phospho_axis_uninformative_reason",
    ):
        assert f in r


def test_retired_token_absent_from_module():
    """Regression: the retired `not_phosphoprotein` token must not be reachable from the reader."""
    src = (METHODS / "phospho_pathway_activity" / "read.py").read_text()
    assert 'return "not_phosphoprotein"' not in src


def test_indication_without_cohort_is_data_unavailable(product):
    r = read_phospho_pathway_activity("EGFR", "UVM", product_path=product)
    assert r["phospho_activity_class"] == "data_unavailable"
    assert "no CPTAC phospho cohort" in r["_data_note"]


def test_no_import_cptac_in_module():
    """Regression: the live cptac package import must be GONE (the whole point of the sourcing fix)."""
    src = (METHODS / "phospho_pathway_activity" / "read.py").read_text()
    assert "import cptac" not in src
    assert "cptac-phospho-per-site-per-cohort-v1" in src
