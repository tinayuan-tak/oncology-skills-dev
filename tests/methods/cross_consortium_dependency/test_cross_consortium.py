from __future__ import annotations
import sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path: sys.path.insert(0,str(REPO))
from methods.cross_consortium_dependency import cli as cc  # noqa: E402


# _consortium_frac signature is (parquet_name, uri, gene) — Broad vs Sanger discriminated by the
# parquet_name (CRISPRGeneEffect.parquet = Broad; ScreenGeneEffect.parquet = Sanger).
def test_concordant_dependent(monkeypatch):
    monkeypatch.setattr(cc,"_consortium_frac", lambda pq,uri,g: {"frac_dependent":0.45,"n_lines":1800,"median":-0.5} if "CRISPRGeneEffect" in pq else {"frac_dependent":0.47,"n_lines":1878,"median":-0.48})
    assert cc.read_cross_consortium_dependency("KRAS")["cross_consortium_class"]=="concordant_dependent"

def test_concordant_non_dependent(monkeypatch):
    monkeypatch.setattr(cc,"_consortium_frac", lambda pq,uri,g: {"frac_dependent":0.02,"n_lines":1800,"median":-0.05})
    assert cc.read_cross_consortium_dependency("XYZ")["cross_consortium_class"]=="concordant_non_dependent"

def test_discordant(monkeypatch):
    monkeypatch.setattr(cc,"_consortium_frac", lambda pq,uri,g: {"frac_dependent":0.30,"n_lines":1800,"median":-0.4} if "CRISPRGeneEffect" in pq else {"frac_dependent":0.03,"n_lines":1878,"median":-0.05})
    assert cc.read_cross_consortium_dependency("G")["cross_consortium_class"]=="discordant"

def test_single_consortium(monkeypatch):
    monkeypatch.setattr(cc,"_consortium_frac", lambda pq,uri,g: {"frac_dependent":0.4,"n_lines":1800,"median":-0.5} if "CRISPRGeneEffect" in pq else None)
    assert cc.read_cross_consortium_dependency("G")["cross_consortium_class"]=="single_consortium_only"

def test_missing_target():
    assert cc.read_cross_consortium_dependency(None)["cross_consortium_class"]=="data_unavailable"
