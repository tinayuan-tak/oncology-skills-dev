"""alteration_role overlay — the OncoKB × IntOGen join + 4-role classification. No S3 (loaders
are monkeypatched with synthetic OncoKB dict + IntOGen DataFrame)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.driver_role_overlay import read as R  # noqa: E402


def _wire(monkeypatch, oncokb: dict, intogen_rows: list):
    # clear the lru_cache only if the real (cached) fn is still in place — guarded so a prior
    # test's monkeypatched lambda (no cache_clear) doesn't error.
    for fn in (R._load_oncokb_roles, R._load_intogen_compendium):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
    monkeypatch.setattr(R, "_load_oncokb_roles", lambda: oncokb)
    cols = ["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"]
    monkeypatch.setattr(R, "_load_intogen_compendium", lambda: pd.DataFrame(intogen_rows, columns=cols))


def test_gof_driver_oncogene_plus_intogen_act(monkeypatch):
    _wire(
        monkeypatch,
        {"KRAS": "ONCOGENE"},
        [
            {
                "SYMBOL": "KRAS",
                "CANCER_TYPE": "COAD",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 1e-30,
                "%_SAMPLES_COHORT": 0.4,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("KRAS", "COADREAD")
    assert o["alteration_role"] == "direct_driver_gof"
    assert o["functional_direction"] == "activating"
    assert o["intogen_scope"] == "indication" and o["intogen_min_qvalue"] == 1e-30


def test_lof_driver_tsg_plus_intogen_lof(monkeypatch):
    _wire(
        monkeypatch,
        {"APC": "TSG"},
        [
            {
                "SYMBOL": "APC",
                "CANCER_TYPE": "COAD",
                "ROLE": "LoF",
                "QVALUE_COMBINATION": 1e-20,
                "%_SAMPLES_COHORT": 0.7,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("APC", "COADREAD")
    assert o["alteration_role"] == "direct_driver_lof" and o["functional_direction"] == "loss_of_function"


def test_dual_role_is_predictive_biomarker(monkeypatch):
    # OncoKB ONCOGENE_AND_TSG → ambiguous direction → predictive_biomarker
    _wire(monkeypatch, {"NOTCH1": "ONCOGENE_AND_TSG"}, [])
    o = R.read_alteration_role("NOTCH1", "HNSC")
    assert o["alteration_role"] == "predictive_biomarker"


def test_conflicting_directions_is_predictive_biomarker(monkeypatch):
    # OncoKB ONCOGENE but IntOGen LoF in this indication → conflict → marker, not a clean driver
    _wire(
        monkeypatch,
        {"X": "ONCOGENE"},
        [
            {
                "SYMBOL": "X",
                "CANCER_TYPE": "COAD",
                "ROLE": "LoF",
                "QVALUE_COMBINATION": 1e-10,
                "%_SAMPLES_COHORT": 0.2,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("X", "COADREAD")
    assert o["alteration_role"] == "predictive_biomarker"


def test_passenger_known_gene_no_driver_role(monkeypatch):
    _wire(monkeypatch, {"ACTB": "NEITHER"}, [])
    o = R.read_alteration_role("ACTB", "COADREAD")
    assert o["alteration_role"] == "passenger" and o["functional_direction"] is None


def test_data_unavailable_absent_from_both(monkeypatch):
    _wire(monkeypatch, {}, [])
    o = R.read_alteration_role("GHOST", "COADREAD")
    assert o["alteration_role"] == "data_unavailable"


def test_pan_cancer_scope_when_indication_absent(monkeypatch):
    # gene is an IntOGen driver but not in THIS indication's cohorts → pan_cancer scope, still classified
    _wire(
        monkeypatch,
        {"IDH1": "ONCOGENE"},
        [
            {
                "SYMBOL": "IDH1",
                "CANCER_TYPE": "GBM",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 1e-15,
                "%_SAMPLES_COHORT": 0.8,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("IDH1", "COADREAD")  # COADREAD maps to COAD/READ, not GBM
    assert o["intogen_scope"] == "pan_cancer"
    assert o["alteration_role"] == "direct_driver_gof"  # OncoKB ONCOGENE + pan-cancer Act


def test_cli_build_and_figure(tmp_path, monkeypatch):
    import importlib

    pytest.importorskip("matplotlib")
    cli = importlib.import_module("methods.driver_role_overlay.cli")
    _wire(
        monkeypatch,
        {"KRAS": "ONCOGENE"},
        [
            {
                "SYMBOL": "KRAS",
                "CANCER_TYPE": "COAD",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 1e-30,
                "%_SAMPLES_COHORT": 0.4,
                "IS_DRIVER": True,
            }
        ],
    )
    s = cli.build_summary("KRAS", "COADREAD")
    assert s["alteration_role"] == "direct_driver_gof" and "method_version" in s
    svg = cli.emit_svg("KRAS", "COADREAD", s, tmp_path)
    assert svg is not None and svg.exists()
    # data_unavailable (absent from both sources) → no figure (passenger DOES render — it's a real call)
    _wire(monkeypatch, {}, [])
    assert cli.emit_svg("GHOST", "COADREAD", cli.build_summary("GHOST", "COADREAD"), tmp_path) is None
