"""precog_prognostic — hermetic tests (synthetic per-(gene x indication) frame, no S3).

Pins the meta-Z -> prognostic_class thresholds (|z|>=1.96), the pan-cancer-context carry, the
approximation flag, the unmapped-indication path (pan-cancer context still returned), and the
absent-gene path. The live build + biology (BIRC5/FOXM1 worse-survival) is verified in the build
micro-benchmark, not here (hermetic = no network)."""

from __future__ import annotations

from onc_methods.precog_prognostic import cli
from onc_methods.precog_prognostic import read as precog_read


def _fake_product():
    import pandas as pd

    return pd.DataFrame(
        [
            # BIRC5: pan-cancer strongly worse; BRCA worse; OV null
            {
                "gene": "BIRC5",
                "indication": "PANCAN",
                "meta_z": 12.20,
                "precog_source_column": "Unweighted_meta-Z_of_all_cancers",
                "precog_indication_approx": False,
                "prognostic_class": "expression_high_worse_survival",
            },
            {
                "gene": "BIRC5",
                "indication": "BRCA",
                "meta_z": 9.17,
                "precog_source_column": "Breast_cancer",
                "precog_indication_approx": False,
                "prognostic_class": "expression_high_worse_survival",
            },
            {
                "gene": "BIRC5",
                "indication": "OV",
                "meta_z": 0.10,
                "precog_source_column": "Ovarian_cancer",
                "precog_indication_approx": False,
                "prognostic_class": "no_prognostic_association",
            },
            # TP53: better-survival in PRAD (a real negative-direction call)
            {
                "gene": "TP53",
                "indication": "PRAD",
                "meta_z": -3.89,
                "precog_source_column": "Prostate_cancer",
                "precog_indication_approx": False,
                "prognostic_class": "expression_high_better_survival",
            },
            # KRAS: COADREAD is an APPROXIMATION (maps to Colon_cancer)
            {
                "gene": "KRAS",
                "indication": "COADREAD",
                "meta_z": 1.82,
                "precog_source_column": "Colon_cancer",
                "precog_indication_approx": True,
                "prognostic_class": "no_prognostic_association",
            },
            {
                "gene": "KRAS",
                "indication": "PANCAN",
                "meta_z": -1.33,
                "precog_source_column": "Unweighted_meta-Z_of_all_cancers",
                "precog_indication_approx": False,
                "prognostic_class": "no_prognostic_association",
            },
        ]
    )


def test_classify_thresholds():
    assert cli._classify(2.0) == "expression_high_worse_survival"
    assert cli._classify(-2.0) == "expression_high_better_survival"
    assert cli._classify(1.5) == "no_prognostic_association"
    assert cli._classify(-1.95) == "no_prognostic_association"
    assert cli._classify(float("nan")) == "data_unavailable"


def test_exact_worse_survival(monkeypatch):
    monkeypatch.setattr(precog_read, "_load_product", _fake_product)
    r = precog_read.read_precog_prognostic("BIRC5", "BRCA")
    assert r["prognostic_class"] == "expression_high_worse_survival"
    assert r["meta_z"] == 9.17
    assert r["pan_cancer_meta_z"] == 12.20
    assert r["precog_indication_approx"] is False
    assert r["precog_source_column"] == "Breast_cancer"


def test_better_survival_direction(monkeypatch):
    monkeypatch.setattr(precog_read, "_load_product", _fake_product)
    r = precog_read.read_precog_prognostic("TP53", "PRAD")
    assert r["prognostic_class"] == "expression_high_better_survival"
    assert r["meta_z"] < 0


def test_approximation_flag(monkeypatch):
    monkeypatch.setattr(precog_read, "_load_product", _fake_product)
    r = precog_read.read_precog_prognostic("KRAS", "COADREAD")
    assert r["precog_indication_approx"] is True
    assert r["precog_source_column"] == "Colon_cancer"
    assert "APPROXIMATION" in r["_caveat"]


def test_unmapped_indication_returns_pancancer_context(monkeypatch):
    monkeypatch.setattr(precog_read, "_load_product", _fake_product)
    # BIRC5 exists; 'UVM' is not crosswalked → data_unavailable class but pan-cancer context carried
    r = precog_read.read_precog_prognostic("BIRC5", "UVM")
    assert r["prognostic_class"] == "data_unavailable"
    assert r["pan_cancer_meta_z"] == 12.20
    assert r["precog_indication_mapped"] is False


def test_absent_gene(monkeypatch):
    monkeypatch.setattr(precog_read, "_load_product", _fake_product)
    r = precog_read.read_precog_prognostic("NOTAGENE", "BRCA")
    assert r["prognostic_class"] == "data_unavailable"
    assert r.get("pan_cancer_meta_z") is None


def test_target_required(monkeypatch):
    monkeypatch.setattr(precog_read, "_load_product", _fake_product)
    r = precog_read.read_precog_prognostic(None, "BRCA")
    assert r["prognostic_class"] == "data_unavailable"


def test_crosswalk_columns_are_unique_and_flagged():
    # every crosswalk entry is (column:str, approx:bool); composites/aliases are flagged approx
    for ind, (col, approx) in cli.INDICATION_TO_PRECOG.items():
        assert isinstance(col, str) and col
        assert isinstance(approx, bool)
    # the known approximations
    assert cli.INDICATION_TO_PRECOG["COADREAD"][1] is True
    assert cli.INDICATION_TO_PRECOG["NSCLC"][1] is True
    # exact anchors
    assert cli.INDICATION_TO_PRECOG["LUAD"] == ("Lung_cancer_ADENO", False)
    assert cli.INDICATION_TO_PRECOG["OV"] == ("Ovarian_cancer", False)


def test_product_loaded_once_and_cached(monkeypatch):
    """The materialized product (single ~2.5 MB row group) must be fetched ONCE per process and
    reused — the fix's point (was re-downloaded on every read_precog_prognostic call)."""
    import onc_methods.derived_product as dp

    calls = {"n": 0}

    def _counting(uri, dev_build=None, **k):
        calls["n"] += 1
        return _fake_product()

    monkeypatch.setattr(dp, "load_materialized_product", _counting)
    monkeypatch.setattr(precog_read, "ensure_aws_profile", lambda *a, **k: None)
    precog_read._load_product.cache_clear()
    try:
        for _ in range(3):
            precog_read.read_precog_prognostic("BIRC5", "BRCA")
        assert calls["n"] == 1  # one download, then cache hits
    finally:
        precog_read._load_product.cache_clear()  # don't leak the cached frame to other tests
