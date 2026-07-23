"""surface_antigen_density_ladder — the ABSOLUTE surface-density calibration corpus VESSEL (Phase 2).

The committed corpus is HEADER-ONLY by design (governance populates values later, no fabrication).
So these tests pin the VESSEL behavior:
  - the shipped corpus reads as grade 'E' (empty → no absolute measurement, never a number);
  - validate_row REJECTS every fabrication-prone row shape (missing value/unit/method/DOI/grade,
    non-admissible unit/method/grade, non-DOI source, bounds that don't bracket the value);
  - a fully-provenanced synthetic row is ADMISSIBLE and resolves to the right class + grade;
  - grade A (patient) is preferred over B (model); an all-rejected corpus for a target → grade E.

Synthetic rows are written to a temp TSV (corpus_path arg) so tests never depend on the committed
(empty) table and never author a value into the repo.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.surface_antigen_density_ladder.read")

_HEADER = ["target", "uniprot_ac", "cell_model", "disease", "specimen_type", "value",
           "lower_bound", "upper_bound", "unit", "calibration_method", "antibody_clone",
           "valency", "fluorophore", "saturation_confirmed", "viable_cell_gating",
           "replicate_count", "source_doi", "evidence_grade", "notes"]


def _write_corpus(tmp_path, rows):
    p = tmp_path / "corpus.tsv"
    lines = ["\t".join(_HEADER)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")) for c in _HEADER))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _good_row(**over):
    row = {
        "target": "ERBB2", "uniprot_ac": "P04626", "cell_model": "SKBR3", "disease": "BRCA",
        "specimen_type": "cell_line", "value": "1200000", "lower_bound": "800000",
        "upper_bound": "2000000", "unit": "ABC", "calibration_method": "QIFIKIT",
        "antibody_clone": "clone-X", "valency": "monovalent", "fluorophore": "PE",
        "saturation_confirmed": "true", "viable_cell_gating": "true", "replicate_count": "3",
        "source_doi": "10.1000/example.doi", "evidence_grade": "B", "notes": "",
    }
    row.update(over)
    return row


# --- the shipped (header-only) corpus reads as grade E, never a number ------------------------
def test_committed_corpus_is_header_only_grade_e():
    d = r.read_absolute_density("ERBB2")   # uses the real committed CORPUS_PATH
    assert d["density_evidence_level"] == "E"
    assert d["absolute_density_class"] == "no_absolute_measurement"
    assert d["copies_per_cell_best"] is None
    assert d["n_admissible_measurements"] == 0


# --- admissibility: a fully-provenanced row passes and resolves correctly ---------------------
def test_admissible_row_resolves(tmp_path):
    p = _write_corpus(tmp_path, [_good_row(value="1200000")])
    d = r.read_absolute_density("ERBB2", corpus_path=p)
    assert d["density_evidence_level"] == "B"
    assert d["absolute_density_class"] == "high"      # 1.2e6 > 10,000
    assert d["copies_per_cell_best"] == 1200000.0
    assert d["unit"] == "ABC"
    assert d["n_admissible_measurements"] == 1


@pytest.mark.parametrize("field", ["value", "unit", "calibration_method", "source_doi", "evidence_grade"])
def test_missing_required_field_rejected(field):
    ok, reason = r.validate_row(_good_row(**{field: ""}))
    assert ok is False
    assert reason == f"missing_required:{field}"


def test_non_admissible_unit_rejected():
    # a RELATIVE unit (log2/ppm) must never enter the absolute corpus
    ok, reason = r.validate_row(_good_row(unit="log2_ratio"))
    assert ok is False and reason.startswith("unit_not_admissible")


def test_non_calibrated_method_rejected():
    ok, reason = r.validate_row(_good_row(calibration_method="estimated"))
    assert ok is False and reason.startswith("calibration_method_not_admissible")


def test_grade_c_d_rejected_from_absolute_corpus():
    # C/D are inferred, not direct flow — they must not appear in the anchor corpus
    for g in ("C", "D", "E"):
        ok, reason = r.validate_row(_good_row(evidence_grade=g))
        assert ok is False and reason.startswith("evidence_grade_not_admissible")


def test_non_doi_source_rejected():
    ok, reason = r.validate_row(_good_row(source_doi="see supplementary table"))
    assert ok is False and reason == "source_doi_not_doi_shaped"


def test_bounds_must_bracket_value():
    ok, reason = r.validate_row(_good_row(value="5000000", lower_bound="800000", upper_bound="2000000"))
    assert ok is False and reason == "bounds_do_not_bracket_value"


def test_value_not_positive_rejected():
    ok, reason = r.validate_row(_good_row(value="0"))
    assert ok is False and reason == "value_not_positive"


# --- grade A (patient) preferred over B (model); all-rejected target → grade E ----------------
def test_grade_a_preferred_over_b(tmp_path):
    rows = [
        _good_row(value="1500", lower_bound="", upper_bound="", cell_model="model",
                  specimen_type="cell_line", evidence_grade="B"),
        _good_row(value="2500", lower_bound="", upper_bound="", cell_model="patient",
                  specimen_type="patient_tumor", evidence_grade="A", source_doi="10.2000/patient.doi"),
    ]
    p = _write_corpus(tmp_path, rows)
    d = r.read_absolute_density("ERBB2", corpus_path=p)
    assert d["density_evidence_level"] == "A"          # A wins
    assert d["copies_per_cell_best"] == 2500.0
    assert d["absolute_density_class"] == "moderate"    # 1000 <= 2500 <= 10000
    assert d["n_admissible_measurements"] == 2          # both are admissible, A is 'best'


def test_all_rejected_rows_for_target_is_grade_e(tmp_path):
    # a row present but INADMISSIBLE (bad unit) → target reads grade E, never the bad value
    p = _write_corpus(tmp_path, [_good_row(target="MYSTERY", unit="ppm")])
    d = r.read_absolute_density("MYSTERY", corpus_path=p)
    assert d["density_evidence_level"] == "E"
    assert d["copies_per_cell_best"] is None


def test_indication_prefers_same_disease(tmp_path):
    rows = [
        _good_row(value="1500", lower_bound="", upper_bound="", disease="BRCA", evidence_grade="B"),
        _good_row(value="9000", lower_bound="", upper_bound="", disease="COADREAD",
                  evidence_grade="B", source_doi="10.3000/crc.doi"),
    ]
    p = _write_corpus(tmp_path, rows)
    d = r.read_absolute_density("ERBB2", indication="COADREAD", corpus_path=p)
    assert d["copies_per_cell_best"] == 9000.0          # same-indication row wins as 'best'
    assert d["n_admissible_measurements"] == 2
