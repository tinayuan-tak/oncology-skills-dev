"""Offline tests for the derived long-parquet pushdown read path (parquet-storage-standard).

Builds a tiny synthetic long product (uniprot_base, uniprot_id, model_id, log2_abundance) + a
median-null sidecar, then exercises the reader's local-path seam — no S3. Covers: per-protein
pushdown, the 'first base-match column' isoform selection, absent-accession -> None, and the
null-sidecar read.
"""

from __future__ import annotations

from onc_methods.depmap_protein_abundance import cli as pc


def _write_long(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = [
        # P01116: 3 detected lines
        ("P01116", "P01116", "ACH-1", 5.0),
        ("P01116", "P01116", "ACH-2", 5.2),
        ("P01116", "P01116", "ACH-3", 4.8),
        # Q8WY21 base with TWO isoform-suffixed columns; 'first base-match' = min uniprot_id (Q8WY21-2)
        ("Q8WY21", "Q8WY21-2", "ACH-1", 1.0),
        ("Q8WY21", "Q8WY21-2", "ACH-2", 1.4),
        ("Q8WY21", "Q8WY21-9", "ACH-1", 9.0),
    ]
    tbl = pa.table(
        {
            "uniprot_base": [r[0] for r in rows],
            "uniprot_id": [r[1] for r in rows],
            "model_id": [r[2] for r in rows],
            "log2_abundance": [float(r[3]) for r in rows],
        }
    )
    p = tmp_path / "long.parquet"
    pq.write_table(tbl, p)
    return p


def _write_null(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = tmp_path / "null.parquet"
    pq.write_table(
        pa.table(
            {
                "uniprot_id": ["P01116", "Q8WY21-2", "Q8WY21-9"],
                "uniprot_base": ["P01116", "Q8WY21", "Q8WY21"],
                "median_log2_abundance": [5.0, 1.2, 9.0],
            }
        ),
        p,
    )
    return p


def test_pushdown_reads_target_column(tmp_path, monkeypatch):
    lp = _write_long(tmp_path)
    monkeypatch.setattr(pc, "_derived_panel_size", lambda: 4)  # panel bigger than detected -> frac<1
    col, panel = pc._load_gygi_abundance_pushdown("P01116", product_path=lp)
    assert panel == 4
    assert col == {"ACH-1": 5.0, "ACH-2": 5.2, "ACH-3": 4.8}


def test_pushdown_isoform_first_base_match(tmp_path, monkeypatch):
    lp = _write_long(tmp_path)
    monkeypatch.setattr(pc, "_derived_panel_size", lambda: 4)
    # base 'Q8WY21' has two isoform columns; the min uniprot_id (Q8WY21-2) wins, matching the
    # wide-CSV 'first base-match column' semantics (never merges isoforms).
    col, _ = pc._load_gygi_abundance_pushdown("Q8WY21", product_path=lp)
    assert col == {"ACH-1": 1.0, "ACH-2": 1.4}


def test_pushdown_absent_accession_is_none(tmp_path, monkeypatch):
    lp = _write_long(tmp_path)
    monkeypatch.setattr(pc, "_derived_panel_size", lambda: 4)
    col, panel = pc._load_gygi_abundance_pushdown("P99999", product_path=lp)
    assert col is None and panel == 4


def test_allgene_null_sidecar_read(tmp_path):
    np_ = _write_null(tmp_path)
    null = pc._load_allgene_null_sidecar(null_path=np_)
    assert null == (5.0, 1.2, 9.0)
