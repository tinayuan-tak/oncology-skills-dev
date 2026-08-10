"""progeny_pathway_activity — hermetic tests (synthetic per-(pathway x indication) frame, no S3).

Pins the relative-class thresholds (cross-indication z), the composite-indication pooling
(COADREAD = COAD+READ sample-weighted), and the data_unavailable path. The live scoring + biology
(COADREAD Hypoxia-high etc.) is verified in the build micro-benchmark, not here (hermetic = no network)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.progeny_pathway_activity import read as prog_read  # noqa: E402


def _fake_product():
    import pandas as pd
    # two member studies for COADREAD + a standalone; z already precomputed for the test
    return pd.DataFrame([
        {"indication": "COAD", "pathway": "WNT", "n_samples": 300, "median_activity": 2.0,
         "p25_activity": 1.0, "p75_activity": 3.0, "activity_z_across_indications": 1.5},
        {"indication": "READ", "pathway": "WNT", "n_samples": 100, "median_activity": 2.0,
         "p25_activity": 1.0, "p75_activity": 3.0, "activity_z_across_indications": 1.5},
        {"indication": "COAD", "pathway": "p53", "n_samples": 300, "median_activity": -3.0,
         "p25_activity": -4.0, "p75_activity": -2.0, "activity_z_across_indications": -1.4},
        {"indication": "READ", "pathway": "p53", "n_samples": 100, "median_activity": -3.0,
         "p25_activity": -4.0, "p75_activity": -2.0, "activity_z_across_indications": -1.4},
        {"indication": "COAD", "pathway": "MAPK", "n_samples": 300, "median_activity": 0.3,
         "p25_activity": -0.5, "p75_activity": 1.0, "activity_z_across_indications": 0.1},
        {"indication": "READ", "pathway": "MAPK", "n_samples": 100, "median_activity": 0.3,
         "p25_activity": -0.5, "p75_activity": 1.0, "activity_z_across_indications": 0.1},
    ])


def test_relative_class_thresholds(monkeypatch):
    monkeypatch.setattr(prog_read, "_load_product", _fake_product)
    monkeypatch.setattr(prog_read._cli, "_load_model", lambda top_n=100: __import__("pandas").DataFrame(
        {"source": ["WNT"], "target": ["ZZZ"], "weight": [1.0]}))
    out = prog_read.read_progeny_pathway_activity(target="ZZZ", indication="COADREAD")
    assert "WNT" in out["relatively_high_pathways"]      # z 1.5 >= +1
    assert "p53" in out["relatively_low_pathways"]        # z -1.4 <= -1
    assert "MAPK" not in out["relatively_high_pathways"]  # z 0.1 → average
    assert out["pooled_from"] == ["COAD", "READ"]         # composite pooling
    assert out["n_pathways_profiled"] == 3


def test_target_pathway_membership(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(prog_read, "_load_product", _fake_product)
    monkeypatch.setattr(prog_read._cli, "_load_model",
                        lambda top_n=100: pd.DataFrame({"source": ["MAPK", "WNT"], "target": ["EGFR", "MYC"], "weight": [5.0, 3.0]}))
    out = prog_read.read_progeny_pathway_activity(target="EGFR", indication="COAD")
    assert out["target_pathway_membership"] == ["MAPK"]   # EGFR is a MAPK responsive gene in the fake model


def test_unmapped_indication_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(prog_read, "_load_product", _fake_product)
    out = prog_read.read_progeny_pathway_activity(indication="ZZZ_NOT_A_CANCER")
    assert out["pathway_activity_class"] == "data_unavailable"


def test_missing_indication_is_data_unavailable():
    out = prog_read.read_progeny_pathway_activity(indication=None)
    assert out["pathway_activity_class"] == "data_unavailable"
