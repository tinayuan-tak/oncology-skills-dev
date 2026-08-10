"""Tests for the tahoe_drug_perturbation facet reader (cli.compute_summary + read).

compute_summary is pure over an injected DataFrame (no S3), so the aggregation + classification is
tested hermetically. The DUSP6/trametinib pattern (strong suppression by a MEK inhibitor) is the
worked example from the Pilot-2 backtest.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402

from methods.tahoe_drug_perturbation import cli as C  # noqa: E402


def _df(rows):
    return pd.DataFrame(rows, columns=[
        "gene_name", "drug", "Cell_ID_DepMap", "concentration",
        "log2FoldChange", "padj", "stat", "baseMean",
    ])


def _rows_dusp6():
    rows = []
    # Trametinik strongly suppresses DUSP6 across 6 lines (median well below -1)
    for i in range(6):
        rows.append(["DUSP6", "Trametinib", f"ACH-{i:06d}", 0.1, -3.0 - 0.1 * i, 1e-8, -10, 50])
    # A weak/no-move drug
    for i in range(4):
        rows.append(["DUSP6", "DMSO_TF", f"ACH-{i:06d}", 0.0, 0.02, 0.9, 0.1, 50])
    # An inducer across 3 lines
    for i in range(3):
        rows.append(["DUSP6", "SomeInducer", f"ACH-{i:06d}", 0.5, 1.4 + 0.1 * i, 1e-4, 6, 40])
    return rows


def test_data_unavailable_on_none():
    out = C.compute_summary(None, "DUSP6")
    assert out["tahoe_perturbation_class"] == "data_unavailable"
    assert out["_live_read_error"] == "tahoe_drug_perturbation_read_failed"


def test_not_measured_on_empty():
    out = C.compute_summary(_df([]), "FOOBAR")
    assert out["tahoe_perturbation_class"] == "not_measured"
    assert out["n_perturbing_drugs"] == 0


def test_bidirectional_perturbation_dusp6():
    out = C.compute_summary(_df(_rows_dusp6()), "DUSP6")
    assert out["tahoe_perturbation_class"] == "bidirectionally_perturbed"
    # strongest suppressor is Trametinik
    assert out["top_suppressing_drugs"][0]["drug"] == "Trametinib"
    assert out["top_suppressing_drugs"][0]["median_log2FoldChange"] < -1.0
    assert out["top_suppressing_drugs"][0]["n_cancer_lines"] == 6
    # an inducer surfaced
    assert out["top_inducing_drugs"][0]["drug"] == "SomeInducer"
    # DMSO (weak) excluded from both strong lists
    supp_drugs = {d["drug"] for d in out["top_suppressing_drugs"]}
    assert "DMSO_TF" not in supp_drugs


def test_drug_suppressed_only():
    rows = [["DUSP6", "Trametinib", f"ACH-{i:06d}", 0.1, -2.5, 1e-6, -8, 50] for i in range(5)]
    out = C.compute_summary(_df(rows), "DUSP6")
    assert out["tahoe_perturbation_class"] == "drug_suppressed"
    assert out["top_inducing_drugs"] == []
    assert out["strongest_mover_drug"] == "Trametinib"


def test_weakly_perturbed_when_no_strong_mover():
    # all moves are sub-2-fold in median
    rows = [["MYGENE", "DrugA", f"ACH-{i:06d}", 0.1, 0.3, 1e-3, 2, 30] for i in range(4)]
    out = C.compute_summary(_df(rows), "MYGENE")
    assert out["tahoe_perturbation_class"] == "weakly_perturbed"
    assert out["n_perturbing_drugs"] == 1


def test_read_layer_passes_through(monkeypatch):
    from methods.tahoe_drug_perturbation import read as R
    monkeypatch.setattr(C, "fetch_gene_rows", lambda t: _df(_rows_dusp6()))
    out = R.read_tahoe_drug_perturbation("DUSP6", "PAAD")   # indication ignored
    assert out["tahoe_perturbation_class"] == "bidirectionally_perturbed"
    assert out["_data_source"] == "tahoe-drug-perturbation-per-gene-v1"
