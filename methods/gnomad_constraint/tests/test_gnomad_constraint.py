"""Synthetic-data tests for the gnomad_constraint reader (no S3).

Validates: (1) the constraint_class classifier at each band + the card thresholds;
(2) canonical/MANE transcript selection; (3) the not-in-table → `indeterminate`
distinction (a real read, gene absent) vs the graceful `data_unavailable` (couldn't
read); (4) the card-contract field set. The classifier is pure — most assertions
need no file at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(METHODS_REPO))
from methods.gnomad_constraint import cli as gc  # noqa: E402
from methods.gnomad_constraint import read as gc_read  # noqa: E402


# --- classifier (pure; the card thresholds) -------------------------------

def test_classify_highly_constrained():
    # LOEUF <= 0.35 OR pLI >= 0.9
    assert gc.classify_constraint(pli=0.99, loeuf=0.15) == "highly_constrained"
    assert gc.classify_constraint(pli=None, loeuf=0.30) == "highly_constrained"   # LOEUF alone
    assert gc.classify_constraint(pli=0.95, loeuf=None) == "highly_constrained"   # pLI alone


def test_classify_moderately_constrained():
    assert gc.classify_constraint(pli=0.6, loeuf=0.5) == "moderately_constrained"
    assert gc.classify_constraint(pli=None, loeuf=0.55) == "moderately_constrained"


def test_classify_tolerant():
    assert gc.classify_constraint(pli=0.1, loeuf=1.2) == "tolerant"
    assert gc.classify_constraint(pli=0.0, loeuf=0.9) == "tolerant"


def test_classify_indeterminate_when_both_missing():
    assert gc.classify_constraint(pli=None, loeuf=None) == "indeterminate"


def test_band_boundaries_are_inclusive():
    # exactly at the high thresholds → highly_constrained
    assert gc.classify_constraint(pli=0.9, loeuf=1.0) == "highly_constrained"    # pLI==0.9
    assert gc.classify_constraint(pli=0.0, loeuf=0.35) == "highly_constrained"   # LOEUF==0.35
    # exactly at the moderate thresholds → moderately_constrained
    assert gc.classify_constraint(pli=0.5, loeuf=1.0) == "moderately_constrained"
    assert gc.classify_constraint(pli=0.0, loeuf=0.6) == "moderately_constrained"


# --- row selection + summary (synthetic TSV) ------------------------------

def _write_tsv(tmp_path):
    p = tmp_path / "gnomad.v4.1.constraint_metrics.tsv"
    cols = [gc.COL_GENE, "transcript", gc.COL_CANONICAL, gc.COL_MANE,
            gc.COL_PLI, gc.COL_LOEUF, gc.COL_MIS_Z, gc.COL_SYN_Z,
            gc.COL_OBS_LOF, gc.COL_EXP_LOF]
    rows = [
        # TP53: two transcripts; the MANE row is the constrained one — selection must pick it
        ["TP53", "ENST_alt", "false", "false", "0.10", "1.10", "0.5", "0.1", "40", "45.0"],
        ["TP53", "ENST_mane", "true", "true", "0.99", "0.12", "5.2", "0.3", "1", "38.0"],
        # KRAS: highly constrained, canonical only
        ["KRAS", "ENST_kras", "true", "false", "0.96", "0.20", "3.1", "0.2", "2", "20.0"],
        # SCD (an expendable-ish gene): tolerant
        ["SCD", "ENST_scd", "true", "true", "0.02", "1.35", "0.1", "0.0", "60", "55.0"],
    ]
    with open(p, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return str(p)


def test_mane_row_selected_and_classified(tmp_path):
    tsv = _write_tsv(tmp_path)
    row = gc.load_constraint_row("TP53", tsv_path=tsv)
    assert row["transcript"] == "ENST_mane", "must pick the MANE_select transcript, not the alt"
    s = gc.compute_summary(row, "TP53")
    assert s["constraint_class"] == "highly_constrained"
    assert s["pli_score"] == 0.99 and s["loeuf_score"] == 0.12
    assert s["mis_z_score"] == 5.2 and s["syn_z_score"] == 0.3
    assert s["obs_lof_count"] == 1 and s["exp_lof_count"] == 38.0
    assert s["method_version"] == gc.METHOD_VERSION


def test_tolerant_gene(tmp_path):
    tsv = _write_tsv(tmp_path)
    s = gc.compute_summary(gc.load_constraint_row("SCD", tsv_path=tsv), "SCD")
    assert s["constraint_class"] == "tolerant"


def test_gene_not_in_table_is_indeterminate_not_data_unavailable(tmp_path):
    tsv = _write_tsv(tmp_path)
    row = gc.load_constraint_row("FOOBAR", tsv_path=tsv)
    assert row is None
    s = gc.compute_summary(row, "FOOBAR")
    assert s["constraint_class"] == "indeterminate", (
        "a gene READ but absent from the table is indeterminate (real negative-ish), "
        "NOT data_unavailable (which means we couldn't read)")


def test_card_contract_fields_present(tmp_path):
    tsv = _write_tsv(tmp_path)
    s = gc.compute_summary(gc.load_constraint_row("KRAS", tsv_path=tsv), "KRAS")
    for f in ("constraint_class", "pli_score", "loeuf_score", "mis_z_score",
              "syn_z_score", "obs_lof_count", "exp_lof_count", "gene_length_bp",
              "method_version"):
        assert f in s, f"card-contract field missing: {f}"


# --- graceful degradation (the dispatcher entry) --------------------------

def test_read_target_summary_graceful_on_unreadable_source(monkeypatch):
    """If the source can't be loaded, read_target_summary must return
    data_unavailable + _live_read_error — NOT raise (framework degradation contract).
    Distinct from indeterminate (which is a successful read of an absent gene)."""
    def _boom(*a, **k):
        raise RuntimeError("s3 unreachable")
    monkeypatch.setattr(gc, "load_constraint_row", _boom)
    out = gc_read.read_target_summary(target="KRAS", indication="COADREAD")
    assert out["constraint_class"] == "data_unavailable"
    assert out["_live_read_error"] == "gnomad_constraint_read_failed"
