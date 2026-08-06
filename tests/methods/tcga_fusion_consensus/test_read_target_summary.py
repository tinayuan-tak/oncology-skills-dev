"""read_target_summary — per-(target, indication) fusion recurrence over the consensus product.

Reads the tcga-fusion-consensus-v1 derived product (S3) for the fusion-rearrangement-landscape card.
Tests monkeypatch _load_consensus to a synthetic consensus DataFrame (no S3), pinning:
  - a recurrent partner (>= _RECURRENT_MIN_SAMPLES samples) -> recurrent_fusion_driver + ranked partners;
  - target recurs but no single recurrent partner -> still recurrent_fusion_driver (promiscuous);
  - target fused in only 1-2 samples -> sporadic_fusion;
  - target in product but NOT in the queried indication -> no_recurrent_fusion (measured-negative);
  - target absent from the product -> data_unavailable;
  - empty/unavailable product -> data_unavailable (never a fabricated call);
  - min_callers filter drops single-caller rows;
  - COADREAD maps to COAD+READ.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.tcga_fusion_consensus.read")


def _row(sample, gene, tissue, caller_count, partners_tf=(), n_tf=0, n_gao=0, n_cb=0):
    return {"sample_key": sample, "gene_symbol": gene, "tissue": tissue,
            "caller_count": caller_count, "callers_supporting": [],
            "partners_tumorfusions": list(partners_tf), "partners_gao_2018": [],
            "partners_cbioportal": [], "frame_preds_tumorfusions": [],
            "frame_preds_gao_2018": [], "frame_preds_cbioportal": [],
            "n_events_tumorfusions": n_tf, "n_events_gao_2018": n_gao, "n_events_cbioportal": n_cb}


def _patch(monkeypatch, rows):
    df = pd.DataFrame(rows)
    monkeypatch.setattr(r, "_load_consensus", lambda: df)


def test_recurrent_partner_is_driver(monkeypatch):
    rows = [_row(f"TCGA-01-{i}-01", "ALK", "LUAD", 3, partners_tf=["EML4"], n_tf=1) for i in range(4)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("ALK", "NSCLC")
    assert d["fusion_class"] == "recurrent_fusion_driver"
    assert d["n_samples_with_fusion"] == 4
    assert d["recurrent_partners"][0]["partner"] == "EML4"
    assert d["recurrent_partners"][0]["n_samples"] == 4


def test_recurs_without_single_recurrent_partner_still_driver(monkeypatch):
    rows = [_row(f"TCGA-01-{i}-01", "ROS1", "LUAD", 2, partners_tf=[f"P{i}"], n_tf=1) for i in range(4)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("ROS1", "LUAD")
    assert d["fusion_class"] == "recurrent_fusion_driver"
    assert d["recurrent_partners"] == []
    assert d["n_samples_with_fusion"] == 4


def test_sporadic_when_few_samples(monkeypatch):
    rows = [_row("TCGA-01-1-01", "XYZ", "BRCA", 1, partners_tf=["A"], n_tf=1)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("XYZ", "BRCA")
    assert d["fusion_class"] == "sporadic_fusion"
    assert d["n_samples_with_fusion"] == 1


def test_in_product_but_not_in_indication_is_measured_negative(monkeypatch):
    rows = [_row(f"TCGA-01-{i}-01", "ALK", "LUAD", 3, partners_tf=["EML4"], n_tf=1) for i in range(4)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("ALK", "BRCA")
    assert d["fusion_class"] == "no_recurrent_fusion"
    assert d["n_samples_with_fusion"] == 0


def test_absent_target_is_data_unavailable(monkeypatch):
    rows = [_row("TCGA-01-1-01", "ALK", "LUAD", 3, partners_tf=["EML4"], n_tf=1)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("GHOSTGENE", "LUAD")
    assert d["fusion_class"] == "data_unavailable"
    assert d["n_samples_with_fusion"] == 0


def test_empty_product_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(r, "_load_consensus", lambda: pd.DataFrame())
    d = r.read_target_summary("ALK", "LUAD")
    assert d["fusion_class"] == "data_unavailable"
    assert d["_data_note"] == "fusion_consensus_product_unavailable"


def test_min_callers_filters_single_caller(monkeypatch):
    rows = [_row(f"TCGA-01-{i}-01", "ALK", "LUAD", 1, partners_tf=["EML4"], n_tf=1) for i in range(4)]
    _patch(monkeypatch, rows)
    assert r.read_target_summary("ALK", "LUAD", min_callers=1)["n_samples_with_fusion"] == 4
    dm = r.read_target_summary("ALK", "LUAD", min_callers=2)
    assert dm["n_samples_with_fusion"] == 0
    assert dm["fusion_class"] == "no_recurrent_fusion"


def test_coadread_indication_maps_coad_and_read(monkeypatch):
    rows = [_row("TCGA-01-1-01", "APC", "COAD", 2, partners_tf=["X"], n_tf=1),
            _row("TCGA-01-2-01", "APC", "READ", 2, partners_tf=["X"], n_tf=1),
            _row("TCGA-01-3-01", "APC", "COAD", 2, partners_tf=["X"], n_tf=1)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("APC", "COADREAD")
    assert d["n_samples_with_fusion"] == 3
    assert d["recurrent_partners"][0]["partner"] == "X"


# --- fusion_frequency denominator (Phase 2a) ---------------------------------

def _patch_coverage(monkeypatch, cov_rows):
    monkeypatch.setattr(r, "_load_coverage", lambda: pd.DataFrame(cov_rows))


def test_fusion_frequency_uses_assayed_denominator(monkeypatch):
    # 3 LUAD samples with ALK fusion; coverage = 10 assayed LUAD samples → freq 3/10.
    rows = [_row(f"TCGA-01-{i}-01", "ALK", "LUAD", 3, partners_tf=["EML4"], n_tf=1) for i in range(3)]
    _patch(monkeypatch, rows)
    _patch_coverage(monkeypatch, [{"sample_key": f"TCGA-01-{i}-01", "tissue": "LUAD", "caller": "x"}
                                  for i in range(10)])
    d = r.read_target_summary("ALK", "NSCLC")
    assert d["n_samples_with_fusion"] == 3
    assert d["n_assayed_in_tissue"] == 10
    assert abs(d["fusion_frequency"] - 0.3) < 1e-9


def test_fusion_frequency_none_when_coverage_absent(monkeypatch):
    rows = [_row("TCGA-01-1-01", "ALK", "LUAD", 3, partners_tf=["EML4"], n_tf=1)]
    _patch(monkeypatch, rows)
    _patch_coverage(monkeypatch, [])   # coverage sibling unavailable
    d = r.read_target_summary("ALK", "NSCLC")
    assert d["fusion_frequency"] is None and d["n_assayed_in_tissue"] is None
    assert d["n_samples_with_fusion"] == 1   # count still reported


def test_fusion_frequency_none_without_indication(monkeypatch):
    # pan-tissue query has no single honest denominator → None even if coverage exists.
    rows = [_row("TCGA-01-1-01", "ALK", "LUAD", 3, partners_tf=["EML4"], n_tf=1)]
    _patch(monkeypatch, rows)
    _patch_coverage(monkeypatch, [{"sample_key": "TCGA-01-1-01", "tissue": "LUAD", "caller": "x"}])
    d = r.read_target_summary("ALK")   # no indication
    assert d["fusion_frequency"] is None
