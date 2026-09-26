"""Surface-modality question-table hero — deterministic projection over a synthetic surface-modality-fit
headline. Verdict-inert; no I/O. Signal maps each surface card's OWN class vocabulary (polarity differs
per field: shed not_shed=good, density low=bad)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.presence_question_table import render_question_table_html
from _skills_common.surface_modality_question_table import surface_modality_question_table


def _headline():
    return {
        "fit_class": "ADC_preferred",
        "topology_class": "single_pass_type_1",  # ADC-ideal surface topology → strong
        "surface_density_class": "high",  # above floor → strong
        "shed_liability_class": "not_shed_membrane_retained",  # membrane-retained → strong (ADC-good)
        "tce_antigen_escape_class": "escape_risk_high",  # escape reservoir → absent (TCE-bad)
    }


def test_rows_one_per_surface_subquestion_in_order():
    rows = surface_modality_question_table(_headline())
    assert [r["id"] for r in rows] == ["Surface", "Density", "ADC", "TCE"]


def test_signal_tiers_respect_per_field_polarity():
    rows = {r["id"]: r for r in surface_modality_question_table(_headline())}
    assert rows["Surface"]["signal"]["tier"] == "strong"  # single_pass_type_1
    assert rows["Density"]["signal"]["tier"] == "strong"  # high
    assert rows["ADC"]["signal"]["tier"] == "strong"  # not_shed → GOOD (polarity!)
    assert rows["TCE"]["signal"]["tier"] == "absent"  # escape_risk_high → TCE-opposing


def test_bad_shed_and_low_density_oppose():
    h = {
        "shed_liability_class": "clinically_shed",
        "surface_density_class": "very_low",
        "topology_class": "no_transmembrane",
    }
    rows = {r["id"]: r for r in surface_modality_question_table(h)}
    assert rows["ADC"]["signal"]["tier"] == "absent"  # clinically_shed → ADC-opposing
    assert rows["Density"]["signal"]["tier"] == "absent"  # very_low
    assert rows["Surface"]["signal"]["tier"] == "absent"  # no_transmembrane = not a surface protein
    assert rows["TCE"]["signal"]["tier"] == "unmeasured"  # field absent → named gap


def test_no_absolute_measurement_density_is_grey_not_weak_supports_994():
    # #994: a coverage gap (no absolute density measurement) must render `unmeasured` (grey / polarity
    # none), NOT fall through to the "weak" default and read as a weak *supports* signal.
    for token in ("not_surface_density_whole_cell_estimate", "no_absolute_measurement"):
        rows = {r["id"]: r for r in surface_modality_question_table({"surface_density_class": token})}
        sig = rows["Density"]["signal"]
        assert sig["tier"] == "unmeasured", token
        assert sig["polarity"] == "none", token  # never "supports"
        assert sig["fill"] == 0, token


def test_tce_row_reads_same_source_class_as_verdict_1738():
    # #1738: the TCE display row must read the SAME field the verdict fires on
    # (tce_antigen_escape_class), NOT the deprecated lenient tce_homogeneity_class — else the hero can
    # show "homogeneous / strong" while the verdict fired tce_escape_risk.
    from _skills_common.surface_modality_question_table import _ROWS

    tce_row = [r for r in _ROWS if r[0] == "TCE"]
    assert len(tce_row) == 1
    assert tce_row[0][2] == "tce_antigen_escape_class"  # field the verdict path also reads (run.py)


def test_tce_escape_bands_track_verdict_polarity_1738():
    # escape_risk_low = TCE-favorable (supportive); escape_risk_high = escape reservoir (foreclosure).
    low = {r["id"]: r for r in surface_modality_question_table({"tce_antigen_escape_class": "escape_risk_low"})}
    high = {r["id"]: r for r in surface_modality_question_table({"tce_antigen_escape_class": "escape_risk_high"})}
    assert low["TCE"]["signal"]["tier"] == "strong"
    assert high["TCE"]["signal"]["tier"] == "absent"


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(
        surface_modality_question_table(_headline()), verdict="ADC_preferred", title="Surface modality"
    )
    assert "<table" in html and "Surface modality at a glance" in html and "ADC_preferred" in html
