"""W1c: the sc-normal named-organ liability is de-anonymized into the headline/tension.

The safety-essential veto used to surface an anonymous flag; analysis-methods #572 emits the NAMED
essential-cell driver, and run.py now builds a masking-safe `sc_normal_liability_detail` string and
interpolates it into the tension text — including the case where a coarser window KILL wins the
verdict LABEL but the sc-normal arm ALSO flagged a named critical organ (the masking fix)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("ts_run_w1c", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ts = _load()


def _sc(cls, cell="kidney proximal tubule cell", tissue="kidney", n_atlas=3):
    return {
        "sc_normal_safety_essential_class": cls,
        "sc_normal_essential_max_cell_type": cell,
        "sc_normal_essential_max_tissue": tissue,
        "sc_normal_essential_n_datasets_reliable": n_atlas,
    }


def test_liability_detail_names_organ_cell_and_atlases():
    d = ts._sc_normal_liability_detail(_sc("critical_organ_liability"))
    assert d == "kidney kidney proximal tubule cell (3 atlases)"


def test_liability_detail_origin_tissue_also_named():
    d = ts._sc_normal_liability_detail(_sc("origin_tissue_liability", cell="pneumocyte", tissue="lung", n_atlas=1))
    assert d == "lung pneumocyte (1 atlas)"


def test_liability_detail_none_when_no_essential_hit():
    assert ts._sc_normal_liability_detail(_sc("none")) is None
    assert ts._sc_normal_liability_detail(_sc("data_unavailable")) is None
    assert ts._sc_normal_liability_detail({"sc_normal_safety_essential_class": "critical_organ_liability",
                                           "sc_normal_essential_max_cell_type": None}) is None
    assert ts._sc_normal_liability_detail({}) is None


def test_tension_names_organ_for_preserving_liability():
    hl = {"selectivity_class": "selective_with_normal_liability",
          "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)"}
    t = ts._selectivity_tension_extra(hl)
    assert "kidney proximal tubule cell" in t["text"]
    assert t["severity"] == 3


def test_masking_fix_surfaces_named_liability_under_window_kill():
    """When the window KILL wins the label, a co-fired sc-normal named liability is NOT discarded."""
    hl = {"selectivity_class": "selective_but_broadly_normal",
          "sc_normal_liability_detail": "kidney kidney proximal tubule cell (3 atlases)"}
    t = ts._selectivity_tension_extra(hl)
    assert "also flags a critical-organ single-cell liability" in t["text"]
    assert "kidney proximal tubule cell" in t["text"]
    assert t["severity"] == 4   # the KILL still owns the slot


def test_masking_fix_noop_when_no_sc_normal_liability():
    hl = {"selectivity_class": "selective_but_broadly_normal", "sc_normal_liability_detail": None}
    t = ts._selectivity_tension_extra(hl)
    assert "also flags" not in t["text"]
