"""oncogenic_pathway_alteration — hermetic tests (synthetic per-(pathway x indication) frame, no S3)."""
from __future__ import annotations
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path: sys.path.insert(0, str(REPO))
from methods.oncogenic_pathway_alteration import read as opa  # noqa: E402


def _fake():
    import pandas as pd
    return pd.DataFrame([
        {"indication":"COAD","pathway":"WNT","n_samples":300,"frac_altered":0.90,"pathway_alteration_class":"frequently_altered"},
        {"indication":"READ","pathway":"WNT","n_samples":100,"frac_altered":0.86,"pathway_alteration_class":"frequently_altered"},
        {"indication":"COAD","pathway":"RTK RAS","n_samples":300,"frac_altered":0.75,"pathway_alteration_class":"frequently_altered"},
        {"indication":"READ","pathway":"RTK RAS","n_samples":100,"frac_altered":0.70,"pathway_alteration_class":"frequently_altered"},
        {"indication":"COAD","pathway":"NOTCH","n_samples":300,"frac_altered":0.05,"pathway_alteration_class":"rarely_altered"},
        {"indication":"READ","pathway":"NOTCH","n_samples":100,"frac_altered":0.04,"pathway_alteration_class":"rarely_altered"},
    ])


def test_composite_pooling_and_class(monkeypatch):
    monkeypatch.setattr(opa, "_load_product", _fake)
    monkeypatch.setattr(opa, "_gene_pathways", lambda t: ["RTK RAS"] if t=="KRAS" else [])
    out = opa.read_oncogenic_pathway_alteration(target="KRAS", indication="COADREAD")
    assert "WNT" in out["frequently_altered_pathways"]        # pooled 0.90/0.86 → still frequent
    assert "RTK RAS" in out["frequently_altered_pathways"]
    assert "NOTCH" not in out["frequently_altered_pathways"]   # 0.05 → rarely
    assert out["pooled_from"] == ["COAD","READ"]
    assert out["target_pathway_membership"] == ["RTK RAS"]
    # target's pathway alteration frequency surfaced
    assert any(r["pathway"]=="RTK RAS" for r in out["target_pathway_alteration"])


def test_unmapped_indication(monkeypatch):
    monkeypatch.setattr(opa, "_load_product", _fake)
    assert opa.read_oncogenic_pathway_alteration(indication="ZZZ")["oncogenic_pathway_class"]=="data_unavailable"


def test_missing_indication():
    assert opa.read_oncogenic_pathway_alteration(indication=None)["oncogenic_pathway_class"]=="data_unavailable"
