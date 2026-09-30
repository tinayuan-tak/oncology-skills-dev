"""iedb_epitope.read — credential-less monkeypatched read_target_summary tests + @lru_cache
transient discipline (mirrors pmhc_presentation): both @lru_cache readers must RAISE on
transient/broken-env (not memoize a failure) and return the honest empty / sentinel ONLY on a genuine
object-absence. read_target_summary must assemble the full DISPLAY-card summary shape + provenance.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pandas")
pa = pytest.importorskip("pyarrow")


from onc_methods.iedb_epitope import read as R


@pytest.fixture(autouse=True)
def _clear_lru():
    R._symbol_to_ac.cache_clear()
    R._row_for_ac.cache_clear()
    yield
    R._symbol_to_ac.cache_clear()
    R._row_for_ac.cache_clear()


# ── read_target_summary end-to-end (dispatcher contract) ──────────────────────
def _patch_pyarrow(monkeypatch, read_table):
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    monkeypatch.setattr(fs, "S3FileSystem", lambda **k: object())
    monkeypatch.setattr(pq, "read_table", read_table)


def test_read_target_summary_resolves_symbol_and_summarizes(monkeypatch):
    monkeypatch.setattr(R, "_symbol_to_ac", lambda: {"ERBB2": "P04626"})

    def read_table(path, filesystem=None, filters=None):
        return pa.table(
            {
                "uniprot_id": ["P04626"],
                "n_epitopes": [151],
                "n_mhc_class_i_epitopes": [119],
                "n_mhc_class_ii_epitopes": [36],
                "n_hla_alleles": [43],
                "n_assays": [673],
                "has_tcell_positive": [True],
                "has_mhc_ligand_positive": [True],
                "has_cancer_context": [True],
                "example_hla_alleles": ["HLA-A*02:01;HLA-A*01:01"],
                "example_epitopes": ["ALCRWGLLL;ALCRWGLLLA"],
            }
        )

    _patch_pyarrow(monkeypatch, read_table)
    out = R.read_target_summary("ERBB2", "COADREAD")
    assert out["epitope_evidence_class"] == "tcell_validated"
    assert out["n_epitopes"] == 151 and out["n_mhc_class_i_epitopes"] == 119
    assert out["n_hla_alleles"] == 43 and out["has_cancer_context"] is True
    assert out["uniprot_ac"] == "P04626"
    assert out["method_version"] == R.METHOD_VERSION
    assert out["_data_source"] == R.DERIVED_MANIFEST_ID


def test_read_target_summary_absent_is_weak_negative(monkeypatch):
    monkeypatch.setattr(R, "_symbol_to_ac", lambda: {"FOO": "P99998"})
    _patch_pyarrow(monkeypatch, lambda *a, **k: pa.table({"uniprot_id": pa.array([], pa.string())}))
    out = R.read_target_summary("FOO")
    assert out["epitope_evidence_class"] == "not_observed"
    assert out["uniprot_ac"] == "P99998"


def test_read_target_summary_unresolvable_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(R, "_symbol_to_ac", lambda: {})
    out = R.read_target_summary("NOTAGENE!")
    assert out["epitope_evidence_class"] == "data_unavailable"
    assert out["uniprot_ac"] is None
    assert "_data_note" in out


def test_read_target_summary_genuine_absence_sentinel(monkeypatch):
    monkeypatch.setattr(R, "_symbol_to_ac", lambda: {"KRAS": "P01116"})

    def read_table(path, filesystem=None, filters=None):
        raise FileNotFoundError("object does not exist")

    _patch_pyarrow(monkeypatch, read_table)
    out = R.read_target_summary("KRAS")
    assert out["epitope_evidence_class"] == "data_unavailable"
    assert out["_live_read_error"] == "iedb_epitope_read_failed"


# ── @lru_cache transient discipline ───────────────────────────────────────────
def test_symbol_to_ac_transient_raises_not_cached(monkeypatch):
    calls = {"n": 0}
    tbl = pa.table({"hgnc_primary_symbol_at_resolution": ["ERBB2"], "uniprot_canonical": ["P04626"]})

    def fake_read_parquet(bucket, key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 throttle")
        return tbl

    monkeypatch.setattr(R, "_read_parquet", fake_read_parquet)
    with pytest.raises(RuntimeError):
        R._symbol_to_ac()
    m = R._symbol_to_ac()  # NOT memoized: retry succeeds
    assert m.get("ERBB2") == "P04626"


def test_symbol_to_ac_genuine_absence_empty(monkeypatch):
    monkeypatch.setattr(
        R, "_read_parquet", lambda b, k: (_ for _ in ()).throw(FileNotFoundError("object does not exist"))
    )
    assert R._symbol_to_ac() == {}


def test_symbol_to_ac_schema_drift_raises(monkeypatch):
    bad = pa.table({"wrong_col": ["x"]})
    monkeypatch.setattr(R, "_read_parquet", lambda b, k: bad)
    with pytest.raises(ValueError):
        R._symbol_to_ac()


def test_row_for_ac_transient_raises_not_cached(monkeypatch):
    calls = {"n": 0}

    def read_table(path, filesystem=None, filters=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 throttle")
        return pa.table({"uniprot_id": ["P04626"], "n_epitopes": [151]})

    _patch_pyarrow(monkeypatch, read_table)
    with pytest.raises(RuntimeError):
        R._row_for_ac("P04626")
    row = R._row_for_ac("P04626")  # NOT memoized: retry succeeds
    assert row not in (None, "UNREADABLE")
    assert row["uniprot_id"] == "P04626"


def test_row_for_ac_genuine_absence_sentinel(monkeypatch):
    def read_table(path, filesystem=None, filters=None):
        raise FileNotFoundError("object does not exist")

    _patch_pyarrow(monkeypatch, read_table)
    assert R._row_for_ac("P99999") == "UNREADABLE"
