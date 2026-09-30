"""Q4 recommended_models — role classification, representativeness, ranking, data-gap safety.

No S3: the patient reader + the DepMap card4 loader are monkeypatched.
"""

from __future__ import annotations

import pytest

from onc_methods.patient_model_expression_correspondence import read as R


def _wire(monkeypatch, patient_vals, chronos, tpm, meta, errs=None):
    import onc_methods.tcga_gtex_expression_distribution.read as pt

    monkeypatch.setattr(pt, "read_tumor_samples", lambda t, i: patient_vals)
    import onc_methods.depmap_expression_dependency.cli as c4

    monkeypatch.setattr(
        c4, "load_depmap_files_for_card4", lambda release_pin, target_symbol: (chronos, tpm, meta, errs or [])
    )


def test_role_classification():
    assert R._classify_model_role(5.0, -1.5) == "positive_model"  # expressed + dependent
    assert R._classify_model_role(5.0, 0.1) == "resistance_model"  # expressed + not-dependent
    assert R._classify_model_role(0.3, -2.0) == "negative_control"  # not expressed (even if low chronos)
    assert R._classify_model_role(5.0, None) == "indeterminate"  # expressed, no chronos
    assert R._classify_model_role(5.0, -0.35) == "indeterminate"  # expressed, intermediate


def test_representativeness_band():
    assert R._representativeness(4.0, 3.5, 4.5) == 1.0  # inside IQR
    assert R._representativeness(6.0, 3.5, 4.5) < 1.0  # above IQR decays
    assert R._representativeness(None, 3.5, 4.5) == 0.0  # gap


def test_recommended_models_ranks_lineage_positive_first(monkeypatch):
    # patient tumor median ~4; Bowel positive model (in-lineage) should top a Lung positive model.
    patient = [3.8, 4.0, 4.2] * 10
    chronos = {"M_bowel_pos": -2.0, "M_lung_pos": -2.5, "M_bowel_neg": 0.2, "M_offtarget": -1.0}
    tpm = {"M_bowel_pos": 4.1, "M_lung_pos": 4.0, "M_bowel_neg": 4.0, "M_offtarget": 0.2}
    meta = {
        "M_bowel_pos": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "BOWELPOS"},
        "M_lung_pos": {"OncotreeLineage": "Lung", "StrippedCellLineName": "LUNGPOS"},
        "M_bowel_neg": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "BOWELRES"},
        "M_offtarget": {"OncotreeLineage": "Skin", "StrippedCellLineName": "SKINNEG"},
    }
    _wire(monkeypatch, patient, chronos, tpm, meta)
    res = R.read_recommended_models("KRAS", "COADREAD")
    assert res["correspondence_class"] == "well_modeled_in_lineage"
    assert res["depmap_lineage"] == "Bowel"
    top = res["recommended_models"][0]
    assert top["model_id"] == "M_bowel_pos" and top["screen_role"] == "positive_model"
    assert top["lineage_match"] is True
    # roles resolved across the panel
    roles = {r["model_id"]: r["screen_role"] for r in res["recommended_models"]}
    assert roles["M_bowel_neg"] == "resistance_model"  # Bowel, expressed, not dependent
    assert roles["M_offtarget"] == "negative_control"  # not expressed


def test_off_lineage_positive_only(monkeypatch):
    # positive models exist but none in the indication's lineage → well_modeled_off_lineage
    _wire(
        monkeypatch,
        [4.0] * 20,
        {"M1": -2.0},
        {"M1": 4.0},
        {"M1": {"OncotreeLineage": "Lung", "StrippedCellLineName": "L1"}},
    )
    res = R.read_recommended_models("KRAS", "COADREAD")  # COADREAD → Bowel, M1 is Lung
    assert res["correspondence_class"] == "well_modeled_off_lineage"
    assert res["n_positive_models"] == 1 and res["n_positive_models_in_lineage"] == 0


def test_poorly_modeled(monkeypatch):
    # no expressed+dependent model anywhere
    _wire(
        monkeypatch,
        [4.0] * 20,
        {"M1": 0.1},
        {"M1": 4.0},
        {"M1": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "B1"}},
    )
    res = R.read_recommended_models("KRAS", "COADREAD")
    assert res["correspondence_class"] == "poorly_modeled"


def test_cli_build_and_figure(tmp_path, monkeypatch):
    import importlib

    pytest.importorskip("matplotlib")
    cli = importlib.import_module("onc_methods.patient_model_expression_correspondence.cli")
    _wire(
        monkeypatch,
        [4.0] * 20,
        {"M1": -2.0, "M2": 0.2},
        {"M1": 4.1, "M2": 4.0},
        {
            "M1": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "B1"},
            "M2": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "B2"},
        },
    )
    s = cli.build_summary("KRAS", "COADREAD")
    assert s["correspondence_class"] == "well_modeled_in_lineage" and "method_version" in s
    svg = cli.emit_svg("KRAS", "COADREAD", s, tmp_path)
    assert svg is not None and svg.exists()
    specs = cli.emit_plotly_specs("KRAS", "COADREAD", tmp_path)
    assert [x["id"] for x in specs] == ["recommended_models_scatter"]


def test_data_unavailable_paths(monkeypatch):
    # no patient TPM
    _wire(monkeypatch, [], {}, {}, {})
    assert R.read_recommended_models("X", "COADREAD")["correspondence_class"] == "data_unavailable"
    # patient present but DepMap load error
    _wire(monkeypatch, [4.0] * 10, {}, {}, {}, errs=[{"_live_read_error": "s3_read_failed"}])
    out = R.read_recommended_models("X", "COADREAD")
    assert out["correspondence_class"] == "data_unavailable"
    assert out["recommended_models"] == []
