"""Surface-modality question-table hero — deterministic projection over a synthetic surface-modality-fit
headline. Verdict-inert; no I/O. Signal maps each surface card's OWN class vocabulary (polarity differs
per field: shed not_shed=good, density low=bad)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.surface_modality_question_table import surface_modality_question_table
from _skills_common.presence_question_table import render_question_table_html


def _headline():
    return {
        "fit_class": "ADC_preferred",
        "topology_class": "single_pass_type_1",      # ADC-ideal surface topology → strong
        "surface_density_class": "high",             # above floor → strong
        "shed_liability_class": "not_shed_membrane_retained",  # membrane-retained → strong (ADC-good)
        "tce_homogeneity_class": "heterogeneous",    # heterogeneous → absent (TCE-bad)
    }


def test_rows_one_per_surface_subquestion_in_order():
    rows = surface_modality_question_table(_headline())
    assert [r["id"] for r in rows] == ["Surface", "Density", "ADC", "TCE"]


def test_signal_tiers_respect_per_field_polarity():
    rows = {r["id"]: r for r in surface_modality_question_table(_headline())}
    assert rows["Surface"]["signal"]["tier"] == "strong"      # single_pass_type_1
    assert rows["Density"]["signal"]["tier"] == "strong"      # high
    assert rows["ADC"]["signal"]["tier"] == "strong"          # not_shed → GOOD (polarity!)
    assert rows["TCE"]["signal"]["tier"] == "absent"          # heterogeneous → TCE-opposing


def test_bad_shed_and_low_density_oppose():
    h = {"shed_liability_class": "clinically_shed", "surface_density_class": "very_low",
         "topology_class": "no_transmembrane"}
    rows = {r["id"]: r for r in surface_modality_question_table(h)}
    assert rows["ADC"]["signal"]["tier"] == "absent"          # clinically_shed → ADC-opposing
    assert rows["Density"]["signal"]["tier"] == "absent"      # very_low
    assert rows["Surface"]["signal"]["tier"] == "absent"      # no_transmembrane = not a surface protein
    assert rows["TCE"]["signal"]["tier"] == "unmeasured"      # field absent → named gap


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(surface_modality_question_table(_headline()),
                                      verdict="ADC_preferred", title="Surface modality")
    assert "<table" in html and "Surface modality at a glance" in html and "ADC_preferred" in html
