"""SEL-1 forwarding fix (2026-08-05): the card-facing COMPOSITE reader must forward the
selectivity all-gene percentile the gene_row reader computes.

The card dispatcher calls read_tumor_vs_normal_selectivity (the composite), NOT
read_tumor_vs_normal_sensitivity_gene_row (which computes the percentile). The composite's
explicit field-map silently dropped the percentile — a live EPCAM/COADREAD run surfaced
selectivity_allgene_percentile=null despite the gene_row reader returning 25.75. These tests
pin that the composite forwards the field on BOTH the v3 path and the v2 fallback (as
data_unavailable), so the orphaned-signal gap can't recur.
"""

from __future__ import annotations

from onc_methods.dge_deseq2 import read as r


def test_composite_forwards_percentile_from_gene_row(monkeypatch):
    """read_tumor_vs_normal_selectivity must forward selectivity_allgene_percentile* from
    the gene_row it calls — not drop it in the explicit field-map."""
    fake_row = {
        "cells_ran": 2,
        "cells_supporting": 2,
        "dominant_direction": "up",
        "sig_all_cells": True,
        "discordant": False,
        "max_abs_log2fc": 2.1,
        "log2fc_cell_a": 2.1,
        "q_value_cell_a": 1e-9,
        "log2fc_cell_c": 1.7,
        "q_value_cell_c": 1e-6,
        "log2fc_cell_d": None,
        "q_value_cell_d": None,
        "selectivity_allgene_percentile": 98.5,
        "selectivity_allgene_percentile_class": "top_decile",
        "selectivity_allgene_percentile_context": "coadread-...-v1 metric=log2fc_A(primary)",
        "selectivity_allgene_percentile_cell_c": 91.0,
        "_data_source": "coadread-dge-tumor-vs-normal-sensitivity-v1",
    }
    monkeypatch.setattr(r, "read_tumor_vs_normal_sensitivity_gene_row", lambda t, i: fake_row)
    out = r.read_tumor_vs_normal_selectivity("EPCAM", "COADREAD")
    assert out["selectivity_allgene_percentile"] == 98.5
    assert out["selectivity_allgene_percentile_class"] == "top_decile"
    assert out["selectivity_allgene_percentile_cell_c"] == 91.0
    assert "metric=log2fc_A" in out["selectivity_allgene_percentile_context"]
    # cell B was removed in #727 — the composite must not forward a cell-B percentile field.
    assert "selectivity_allgene_percentile_cell_b" not in out
    # the composite must not have perturbed the verdict-bearing fields
    assert out["selectivity_class"] is not None and out["cells_supporting"] == 2


def test_v2_fallback_emits_percentile_data_unavailable(monkeypatch):
    """When the sensitivity product isn't landed, the composite falls back to v2; the
    percentile field must still EXIST as data_unavailable (not silently absent)."""
    # gene_row returns None → composite takes the v2 fallback path
    monkeypatch.setattr(r, "read_tumor_vs_normal_sensitivity_gene_row", lambda t, i: None)
    # make both legacy products return nothing → a clean data_unavailable fallback
    monkeypatch.setattr(r, "read_dge_gene_row", lambda t, m: None)
    monkeypatch.setattr(r, "read_tumor_vs_gtex_gene_row", lambda t, i: None)
    out = r.read_tumor_vs_normal_selectivity("EPCAM", "COADREAD")
    assert "selectivity_allgene_percentile" in out
    assert out["selectivity_allgene_percentile"] is None
    assert out["selectivity_allgene_percentile_class"] == "data_unavailable"
