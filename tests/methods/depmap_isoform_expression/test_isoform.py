"""depmap_isoform_expression — per-gene model isoform-expression summary.

build_isoform_table is exercised on a synthetic log1p transcript-TPM CSV (models × ENST) with a
mocked ENST→gene map, pinning: the log1p→linear expm1 recovery, per-model dominant-isoform fraction,
the expressed-TPM floor, the _MIN_MODELS gate, and the class cutoffs. isoform_summary_for_gene is
tested via a forced product-read.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.depmap_isoform_expression import read as r  # noqa: E402


def _log1p(tpm):
    return math.log1p(tpm)


def _write_csv(tmp_path, enst_cols, model_rows):
    """model_rows: list of dict {enst: linear_tpm}. Writes a log1p CSV like the DepMap file."""
    p = tmp_path / "tx.csv"
    header = ["ModelID"] + enst_cols
    lines = [",".join(header)]
    for i, mr in enumerate(model_rows):
        vals = [f"model{i}"] + [str(_log1p(mr.get(e, 0.0))) for e in enst_cols]
        lines.append(",".join(vals))
    p.write_text("\n".join(lines))
    return str(p)


def _setup_map(monkeypatch, enst2gene):
    r._enst_to_gene.cache_clear()
    monkeypatch.setattr(r, "_enst_to_gene", lambda: enst2gene)


def test_single_isoform_dominant(monkeypatch):
    # GENEA: one isoform carries ~all TPM across 25 models → median fraction ~1.0 → single_isoform_dominant.
    _setup_map(monkeypatch, {"ENST1": "GENEA", "ENST2": "GENEA"})
    monkeypatch.setattr(r, "_MIN_MODELS", 20)
    rows = [{"ENST1.1": 100.0, "ENST2.1": 0.5} for _ in range(25)]  # ENST2 below expressed floor
    import tempfile
    d = tempfile.mkdtemp()
    path = _write_csv(Path(d), ["ENST1.1", "ENST2.1"], rows)
    tbl = r.build_isoform_table(local_csv=path)
    df = tbl.to_pandas()
    row = df[df.gene_symbol == "GENEA"].iloc[0]
    assert row["isoform_expression_class"] == "single_isoform_dominant"
    assert row["dominant_isoform_fraction"] >= 0.99
    assert row["dominant_isoform"] == "ENST1.1"
    assert row["n_models"] == 25


def test_isoform_diverse(monkeypatch):
    # GENEB: three isoforms ~equal → dominant fraction ~0.33 → isoform_diverse.
    _setup_map(monkeypatch, {"ENST3": "GENEB", "ENST4": "GENEB", "ENST5": "GENEB"})
    monkeypatch.setattr(r, "_MIN_MODELS", 20)
    import tempfile
    d = tempfile.mkdtemp()
    rows = [{"ENST3.1": 30.0, "ENST4.1": 30.0, "ENST5.1": 30.0} for _ in range(22)]
    path = _write_csv(Path(d), ["ENST3.1", "ENST4.1", "ENST5.1"], rows)
    tbl = r.build_isoform_table(local_csv=path)
    row = tbl.to_pandas().iloc[0]
    assert row["isoform_expression_class"] == "isoform_diverse"
    assert row["dominant_isoform_fraction"] < 0.5
    assert row["n_expressed_isoforms"] == 3


def test_expressed_tpm_floor_excludes_noise(monkeypatch):
    # sub-floor transcripts (TPM<1) are not counted as expressed isoforms.
    _setup_map(monkeypatch, {"ENST6": "GENEC", "ENST7": "GENEC"})
    monkeypatch.setattr(r, "_MIN_MODELS", 5)
    import tempfile
    d = tempfile.mkdtemp()
    rows = [{"ENST6.1": 50.0, "ENST7.1": 0.2} for _ in range(6)]  # ENST7 below floor
    path = _write_csv(Path(d), ["ENST6.1", "ENST7.1"], rows)
    row = r.build_isoform_table(local_csv=path).to_pandas().iloc[0]
    assert row["n_expressed_isoforms"] == 1 and row["dominant_isoform_fraction"] == 1.0


def test_min_models_gate(monkeypatch):
    # a gene expressed in < _MIN_MODELS models is dropped from the product.
    _setup_map(monkeypatch, {"ENST8": "RAREGENE"})
    monkeypatch.setattr(r, "_MIN_MODELS", 20)
    import tempfile
    d = tempfile.mkdtemp()
    rows = [{"ENST8.1": 40.0} for _ in range(5)]  # only 5 models
    path = _write_csv(Path(d), ["ENST8.1"], rows)
    tbl = r.build_isoform_table(local_csv=path)
    assert tbl.num_rows == 0


def test_unmapped_transcript_ignored(monkeypatch):
    # a transcript column with no gene map entry is skipped (no crash, no phantom gene).
    _setup_map(monkeypatch, {"ENST9": "GENED"})   # ENST10 unmapped
    monkeypatch.setattr(r, "_MIN_MODELS", 5)
    import tempfile
    d = tempfile.mkdtemp()
    rows = [{"ENST9.1": 20.0, "ENST10.1": 100.0} for _ in range(6)]
    path = _write_csv(Path(d), ["ENST9.1", "ENST10.1"], rows)
    df = r.build_isoform_table(local_csv=path).to_pandas()
    assert set(df.gene_symbol) == {"GENED"}       # ENST10 (unmapped) contributes nothing
    assert df.iloc[0]["dominant_isoform_fraction"] == 1.0


def test_summary_for_gene_data_unavailable(monkeypatch):
    monkeypatch.setattr(r, "_read_from_product", lambda t: None)
    out = r.isoform_summary_for_gene("NOPE")
    assert out["isoform_expression_class"] == "data_unavailable"
