"""stemness_index — hermetic tests (synthetic per-indication frame, no S3)."""
from __future__ import annotations
import sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path: sys.path.insert(0,str(REPO))
from methods.stemness_index import read as sr  # noqa: E402


def _fake():
    import pandas as pd
    # pan-cancer median 0.37, q3 0.45 (baked into every row, as the build does)
    return pd.DataFrame([
        {"indication":"TGCT","n_samples":140,"median_mrnasi":0.71,"p25_mrnasi":0.6,"p75_mrnasi":0.8,"stemness_class":"stem_high","pan_cancer_median_mrnasi":0.37,"pan_cancer_q3_mrnasi":0.45},
        {"indication":"COAD","n_samples":300,"median_mrnasi":0.51,"p25_mrnasi":0.4,"p75_mrnasi":0.6,"stemness_class":"stem_high","pan_cancer_median_mrnasi":0.37,"pan_cancer_q3_mrnasi":0.45},
        {"indication":"READ","n_samples":100,"median_mrnasi":0.50,"p25_mrnasi":0.4,"p75_mrnasi":0.6,"stemness_class":"stem_high","pan_cancer_median_mrnasi":0.37,"pan_cancer_q3_mrnasi":0.45},
        {"indication":"THCA","n_samples":450,"median_mrnasi":0.25,"p25_mrnasi":0.2,"p75_mrnasi":0.3,"stemness_class":"stem_low","pan_cancer_median_mrnasi":0.37,"pan_cancer_q3_mrnasi":0.45},
    ])


def test_stem_high_low_relative_to_pancancer(monkeypatch):
    monkeypatch.setattr(sr,"_load_product",_fake)
    assert sr.read_stemness_index(indication="TGCT")["stemness_class"]=="stem_high"   # 0.71 >= q3 0.45
    assert sr.read_stemness_index(indication="THCA")["stemness_class"]=="stem_low"     # 0.25 < median 0.37


def test_composite_pooling(monkeypatch):
    monkeypatch.setattr(sr,"_load_product",_fake)
    out=sr.read_stemness_index(indication="COADREAD")
    assert out["pooled_from"]==["COAD","READ"]
    assert out["n_samples"]==400
    # weighted median ~0.5075 → still >= q3 → stem_high
    assert out["stemness_class"]=="stem_high"


def test_unmapped_and_missing(monkeypatch):
    monkeypatch.setattr(sr,"_load_product",_fake)
    assert sr.read_stemness_index(indication="ZZZ")["stemness_class"]=="data_unavailable"
    assert sr.read_stemness_index(indication=None)["stemness_class"]=="data_unavailable"
