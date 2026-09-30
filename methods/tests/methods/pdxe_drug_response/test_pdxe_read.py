"""Hermetic (credential-less) tests for the pdxe_drug_response per-gene reader.

Monkeypatches the S3 read (`_read_gene_row`) so the summariser + absence discipline + response-class
logic run offline. VERDICT-INERT display reader; pins the per-gene PDX-response shape, the
responder-fraction-driven class, the indication-ignored target-grain, and the data_unavailable paths.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from onc_methods.pdxe_drug_response import read as R

_COLS = [
    "gene_symbol",
    "n_treatments",
    "n_models_tested",
    "n_response_records",
    "median_best_avg_response",
    "min_best_avg_response",
    "responder_fraction",
    "most_active_treatment",
    "most_active_treatment_median_best_avg_response",
    "treatment_types",
]


def _df(rows):
    return pd.DataFrame(rows, columns=_COLS)


def _braf_like():
    # BRAF-like: an active in-vivo signal (median shrinkage, some objective responders).
    return _df([["BRAF", 6, 40, 88, -11.1, -55.2, 0.34, "LEE011 + encorafenib", -22.4, "single|combo"]])


def test_summary_shape_and_responders_class(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_row", lambda target: _braf_like())
    out = R.read_target_summary("BRAF", indication="SKCM")
    assert out["pdx_drug_response_class"] == "pdx_objective_responders"
    assert out["n_treatments"] == 6
    assert out["n_models_tested"] == 40
    assert out["n_response_records"] == 88
    assert out["median_best_avg_response"] == -11.1
    assert out["min_best_avg_response"] == -55.2
    assert out["responder_fraction"] == 0.34
    assert out["most_active_treatment"] == "LEE011 + encorafenib"
    assert out["most_active_treatment_median_best_avg_response"] == -22.4
    assert out["treatment_types"] == "single|combo"
    assert out["source"] == R.SOURCE
    # the substantive (non-underscore) emit set is EXACTLY the card's summary_fields set
    assert {k for k in out if not k.startswith("_")} == {
        "pdx_drug_response_class",
        "n_treatments",
        "n_models_tested",
        "n_response_records",
        "median_best_avg_response",
        "min_best_avg_response",
        "responder_fraction",
        "most_active_treatment",
        "most_active_treatment_median_best_avg_response",
        "treatment_types",
        "source",
    }


def test_no_objective_response_class(monkeypatch):
    # measured, but zero mRECIST CR/PR responders -> the honest 'measured, no objective response' class.
    df = _df([["MDM2", 2, 20, 30, 28.8, 5.1, 0.0, "HDM201", 24.0, "single"]])
    monkeypatch.setattr(R, "_read_gene_row", lambda target: df)
    out = R.read_target_summary("MDM2")  # indication omitted (target-grain)
    assert out["pdx_drug_response_class"] == "pdx_no_objective_response"
    assert out["responder_fraction"] == 0.0


def test_indication_is_ignored_target_grain(monkeypatch):
    # same gene, different indications -> identical payload (the rollup has no per-indication split).
    monkeypatch.setattr(R, "_read_gene_row", lambda target: _braf_like())
    a = R.read_target_summary("BRAF", indication="SKCM")
    b = R.read_target_summary("BRAF", indication="COADREAD")
    assert a == b


def test_nan_response_fields_round_to_none(monkeypatch):
    df = _df([["EGFR", 1, 5, 5, np.nan, np.nan, np.nan, "erlotinib", np.nan, "single"]])
    monkeypatch.setattr(R, "_read_gene_row", lambda target: df)
    out = R.read_target_summary("EGFR")
    assert out["pdx_drug_response_class"] == "pdx_response_unavailable"
    assert out["median_best_avg_response"] is None
    assert out["responder_fraction"] is None


def test_gene_absent_and_no_product(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_row", lambda target: _df([]))
    absent = R.read_target_summary("ZZZ")
    assert absent["pdx_drug_response_class"] == "data_unavailable"
    assert "not a PDXE" in absent["_data_note"]
    monkeypatch.setattr(R, "_read_gene_row", lambda target: None)
    no_prod = R.read_target_summary("BRAF")
    assert no_prod["pdx_drug_response_class"] == "data_unavailable"
    assert "No landed PDXE" in no_prod["_data_note"]


def test_no_target_supplied():
    assert R.read_target_summary("")["pdx_drug_response_class"] == "data_unavailable"


# ---------------------------------------------------------------------------
# Real read-boundary coverage (issue #764): the tests above all monkeypatch
# `_read_gene_row` itself, so the actual S3 boundary inside it — bucket_key_for
# resolution, pyarrow S3FileSystem construction, the filters=/columns= pushdown
# call, and the `except FileNotFoundError` clauses — was exercised by NO test.
# These patch one layer DEEPER (bucket_key_for + pq.read_table / fs.S3FileSystem),
# so `_read_gene_row`'s own body runs for real.
# ---------------------------------------------------------------------------


def _landed_manifest_columns():
    """The manifest's parquet_schema column names — the authoritative schema
    _PARQUET_COLS is pinned against (data-catalog:manifests/derived/
    pdxe-drug-response-per-gene-v1.yaml)."""
    return {
        "gene_symbol",
        "looks_like_gene_symbol",
        "n_treatments",
        "n_models_tested",
        "n_response_records",
        "median_best_avg_response",
        "min_best_avg_response",
        "n_responders",
        "responder_fraction",
        "most_active_treatment",
        "most_active_treatment_median_best_avg_response",
        "treatment_types",
        "treatments",
    }


def test_parquet_cols_pinned_to_landed_schema():
    """_PARQUET_COLS (the columns= pushdown pin) must be a subset of the landed
    product's actual columns — a rename/drop upstream must fail this, not ship
    a silent read error."""
    landed = _landed_manifest_columns()
    missing = set(R._PARQUET_COLS) - landed
    assert not missing, f"_PARQUET_COLS references columns absent from the landed schema: {missing}"
    # gene_symbol (the filter/sort key) and responder_fraction (the class driver) must always be pulled.
    assert "gene_symbol" in R._PARQUET_COLS
    assert "responder_fraction" in R._PARQUET_COLS


def test_read_gene_row_real_boundary_pushdown_and_columns(monkeypatch):
    """Exercise the real `_read_gene_row` body: bucket_key_for resolution, the
    S3FileSystem construction, and the exact filters=/columns= passed to
    pq.read_table — mocking only the pyarrow/catalog boundary, not the reader."""
    R._read_gene_row.cache_clear()
    calls = {}

    def fake_bucket_key_for(manifest_id):
        assert manifest_id == R.MANIFEST_ID
        return (
            "onc-compbio",
            "data-catalog/derived/pdxe-drug-response-per-gene-v1/pdxe_drug_response_per_gene.parquet",
        )

    class FakeS3FileSystem:
        def __init__(self, region=None):
            calls["region"] = region

    def fake_read_table(path, filesystem=None, filters=None, columns=None):
        calls["path"] = path
        calls["filesystem"] = filesystem
        calls["filters"] = filters
        calls["columns"] = columns
        return _braf_like_table()

    def _braf_like_table():
        import pyarrow as pa

        return pa.Table.from_pandas(_braf_like(), preserve_index=False)

    monkeypatch.setattr(R, "bucket_key_for", fake_bucket_key_for)
    monkeypatch.setattr("pyarrow.fs.S3FileSystem", FakeS3FileSystem)
    monkeypatch.setattr("pyarrow.parquet.read_table", fake_read_table)

    out = R._read_gene_row("BRAF")

    assert (
        calls["path"]
        == "onc-compbio/data-catalog/derived/pdxe-drug-response-per-gene-v1/pdxe_drug_response_per_gene.parquet"
    )
    assert calls["filters"] == [("gene_symbol", "==", "BRAF")]
    assert calls["columns"] == R._PARQUET_COLS
    assert isinstance(calls["filesystem"], FakeS3FileSystem)
    assert out.iloc[0]["gene_symbol"] == "BRAF"
    R._read_gene_row.cache_clear()


def test_read_gene_row_manifest_not_found_returns_none(monkeypatch):
    """bucket_key_for raising FileNotFoundError (unknown manifest_id) must resolve
    the same honest None/absence path as a 404 object read — never propagate as
    an unhandled crash."""
    R._read_gene_row.cache_clear()

    def raise_not_found(manifest_id):
        raise FileNotFoundError(f"unknown manifest {manifest_id}")

    monkeypatch.setattr(R, "bucket_key_for", raise_not_found)
    assert R._read_gene_row("BRAF") is None
    R._read_gene_row.cache_clear()


def test_read_gene_row_object_404_returns_none(monkeypatch):
    """A `pq.read_table` FileNotFoundError (missing landed object) must resolve
    None (absence), not propagate — the narrow except clause at read.py:103."""
    R._read_gene_row.cache_clear()

    def fake_bucket_key_for(manifest_id):
        return (
            "onc-compbio",
            "data-catalog/derived/pdxe-drug-response-per-gene-v1/pdxe_drug_response_per_gene.parquet",
        )

    def raise_404(path, filesystem=None, filters=None, columns=None):
        raise FileNotFoundError("object not found")

    monkeypatch.setattr(R, "bucket_key_for", fake_bucket_key_for)
    monkeypatch.setattr("pyarrow.fs.S3FileSystem", lambda region=None: object())
    monkeypatch.setattr("pyarrow.parquet.read_table", raise_404)
    assert R._read_gene_row("BRAF") is None
    R._read_gene_row.cache_clear()


def test_read_gene_row_transient_fault_propagates(monkeypatch):
    """A transient S3 fault (e.g. throttling/timeout, NOT FileNotFoundError) must
    PROPAGATE rather than be masked as absence — the reader's absence-discipline
    invariant (only `except FileNotFoundError` is caught)."""
    R._read_gene_row.cache_clear()

    def fake_bucket_key_for(manifest_id):
        return (
            "onc-compbio",
            "data-catalog/derived/pdxe-drug-response-per-gene-v1/pdxe_drug_response_per_gene.parquet",
        )

    def raise_transient(path, filesystem=None, filters=None, columns=None):
        raise TimeoutError("transient S3 timeout")

    monkeypatch.setattr(R, "bucket_key_for", fake_bucket_key_for)
    monkeypatch.setattr("pyarrow.fs.S3FileSystem", lambda region=None: object())
    monkeypatch.setattr("pyarrow.parquet.read_table", raise_transient)
    try:
        R._read_gene_row("BRAF")
        raised = False
    except TimeoutError:
        raised = True
    assert raised, "transient fault must propagate, not resolve to None/absence"
    R._read_gene_row.cache_clear()
