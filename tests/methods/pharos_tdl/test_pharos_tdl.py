from __future__ import annotations
import sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path: sys.path.insert(0,str(REPO))
from methods.pharos_tdl import cli as pt  # noqa: E402


def test_tdl_lookup(monkeypatch):
    import pandas as pd
    fake=pd.DataFrame([{"gene_symbol":"KRAS","tdl":"Tclin","fam":"Enzyme","novelty":0.0001},
                       {"gene_symbol":"WRN","tdl":"Tbio","fam":"Enzyme","novelty":0.0016}]).set_index("gene_symbol")
    monkeypatch.setattr(pt,"_load_table",lambda: fake); pt._TABLE_CACHE=None
    assert pt.read_pharos_tdl("KRAS")["tdl_class"]=="Tclin"
    assert "clinically drugged" in pt.read_pharos_tdl("KRAS")["tdl_meaning"]
    assert pt.read_pharos_tdl("WRN")["target_family"]=="Enzyme"

def test_unmapped(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pt,"_load_table",lambda: pd.DataFrame([{"gene_symbol":"KRAS","tdl":"Tclin","fam":"Enzyme","novelty":0.1}]).set_index("gene_symbol"))
    pt._TABLE_CACHE=None
    assert pt.read_pharos_tdl("ZZZNOTAGENE")["tdl_class"]=="data_unavailable"
    assert pt.read_pharos_tdl(None)["tdl_class"]=="data_unavailable"
