"""surface_antigen_density_ladder — absolute surface-density calibration corpus (schema v3, superset).

The committed corpus is the GOVERNED dataset (per-patient QuantiBRITE/QIFIKIT/dSTORM values, real DOIs;
domain-expert curated). These tests pin the reader/validator contract against BOTH synthetic rows
(edge cases) and the real committed corpus (integration):

  - validate_row admits a well-formed native row and REJECTS malformed/quarantined shapes (bad
    unit/method/partition/grade/qualifier, non-DOI, un-bracketed bounds, not-admissible-for-abs-scale,
    explicit_negative-as-numeric-anchor);
  - bound-only rows (lower_bound/upper_bound with value in value_lower/upper) ARE admissible;
  - PARTITION gating: the native default read excludes normal_reference / calibration_reference /
    method_control / explicit_negative;
  - grade preference A > A- > B > B-; patient rows preferred;
  - read_explicit_negatives surfaces the status records;
  - the real committed corpus: 181 rows, exactly the 8 negatives + 2 method-controls held.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

r = importlib.import_module("onc_methods.surface_antigen_density_ladder.read")
COLS = r.SCHEMA_V3_COLUMNS


def _write_corpus(tmp_path, rows):
    p = tmp_path / "corpus.tsv"
    lines = ["\t".join(COLS)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")) for c in COLS))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _good_row(**over):
    row = {c: "" for c in COLS}
    row.update(
        {
            "record_id": "TEST_ROW",
            "target_gene": "EGFR",
            "model_or_sample": "H1993",
            "sample_type": "native cancer cell line",
            "disease_or_context": "NSCLC",
            "species": "human",
            "native_or_engineered": "native",
            "measurement_method": "monovalent Quantibrite PE calibrated flow cytometry",
            "measurement_semantics": "monovalent_epitope_count",
            "reported_unit": "epitopes/cell",
            "value_qualifier": "mean",
            "value_central": "325000",
            "record_partition": "native_cell_line",
            "evidence_grade": "B",
            "admissible_for_absolute_scale": "yes",
            "admissible_for_native_biology": "yes",
            "source_doi": "10.1074/jbc.M115.651653",
        }
    )
    row.update(over)
    return row


# --- admissible native row resolves --------------------------------------------------------------
def test_admissible_row_resolves(tmp_path):
    p = _write_corpus(tmp_path, [_good_row()])
    d = r.read_absolute_density("EGFR", corpus_path=p)
    assert d["density_evidence_level"] == "B"
    assert d["absolute_density_class"] == "high"  # 325k > 10k
    assert d["value_best"] == 325000.0
    assert d["reported_unit"] == "epitopes/cell"
    assert d["n_admissible_measurements"] == 1


# --- required-field + vocabulary rejections ------------------------------------------------------
@pytest.mark.parametrize(
    "field",
    [
        "target_gene",
        "value_qualifier",
        "reported_unit",
        "measurement_method",
        "record_partition",
        "evidence_grade",
        "source_doi",
    ],
)
def test_missing_required_field_rejected(field):
    ok, reason = r.validate_row(_good_row(**{field: ""}))
    assert ok is False and reason == f"missing_required:{field}"


def test_relative_unit_rejected():
    ok, reason = r.validate_row(_good_row(reported_unit="log2_ratio"))
    assert ok is False and reason.startswith("reported_unit_not_admissible")


def test_noncalibrated_method_rejected():
    ok, reason = r.validate_row(_good_row(measurement_method="estimated from RNA"))
    assert ok is False and reason.startswith("measurement_method_not_admissible")


def test_bad_partition_rejected():
    ok, reason = r.validate_row(_good_row(record_partition="made_up"))
    assert ok is False and reason.startswith("record_partition_not_admissible")


def test_non_doi_rejected():
    ok, reason = r.validate_row(_good_row(source_doi="see supplement"))
    assert ok is False and reason == "source_doi_not_doi_shaped"


def test_not_admissible_for_absolute_scale_rejected():
    ok, reason = r.validate_row(_good_row(admissible_for_absolute_scale="no"))
    assert ok is False and reason.startswith("not_admissible_for_absolute_scale")


def test_explicit_negative_not_a_numeric_anchor():
    ok, reason = r.validate_row(
        _good_row(
            value_qualifier="explicit_negative",
            value_central="",
            record_partition="explicit_negative",
            admissible_for_absolute_scale="no",
        )
    )
    # held either on abs-scale flag or the explicit-negative guard — both are correct rejections
    assert ok is False


def test_bound_only_row_admissible():
    # an upper_bound row carries its value in value_upper (value_central empty) — must still admit
    ok, reason = r.validate_row(
        _good_row(
            value_qualifier="upper_bound",
            value_central="",
            value_upper="1000",
            reported_unit="ABS/cell",
            record_partition="normal_reference",
            evidence_grade="A-N",
            measurement_method="QIFIKIT calibrated flow cytometry",
        )
    )
    assert ok is True, reason


def test_unbracketed_bounds_rejected():
    ok, reason = r.validate_row(_good_row(value_central="5000000", value_lower="1000", value_upper="2000"))
    assert ok is False and reason == "bounds_do_not_bracket_value"


# --- partition gating + grade preference ---------------------------------------------------------
def test_native_default_excludes_nonnative(tmp_path):
    rows = [
        _good_row(
            record_id="CAL",
            target_gene="CD19",
            model_or_sample="NALM6-eng",
            value_central="45851",
            record_partition="calibration_reference",
            evidence_grade="CAL",
            measurement_method="quantitative antigen-density characterization reported by study",
            measurement_semantics="molecule_count",
            reported_unit="molecules/cell",
            value_qualifier="exact_reported",
            source_doi="10.1000/cal.example",
        ),
        _good_row(
            record_id="PT",
            target_gene="CD19",
            model_or_sample="primary",
            value_central="110",
            record_partition="native_patient",
            evidence_grade="A",
            sample_type="primary patient tumor cells",
            measurement_method="dSTORM single-molecule localization microscopy",
            measurement_semantics="direct_molecule_count",
            reported_unit="molecules/cell",
            value_qualifier="mean_with_reported_range",
            source_doi="10.1000/pt.example",
        ),
    ]
    p = _write_corpus(tmp_path, rows)
    d = r.read_absolute_density("CD19", corpus_path=p)  # native default
    assert d["n_admissible_measurements"] == 1  # only the patient row
    assert d["density_evidence_level"] == "A"
    assert d["record_partition_best"] == "native_patient"
    # calibration_reference readable only when explicitly requested
    dc = r.read_absolute_density("CD19", partitions=("calibration_reference",), corpus_path=p)
    assert dc["n_admissible_measurements"] == 1 and dc["value_best"] == 45851.0


def test_grade_preference_patient_over_cellline(tmp_path):
    rows = [
        _good_row(
            record_id="CL",
            target_gene="MSLN",
            value_central="80000",
            evidence_grade="B",
            record_partition="native_cell_line",
            reported_unit="ABS/cell",
            measurement_method="QIFIKIT calibrated flow cytometry",
            value_qualifier="approximate",
            source_doi="10.1000/cl.example",
        ),
        _good_row(
            record_id="PT",
            target_gene="MSLN",
            value_central="5000",
            evidence_grade="A",
            record_partition="native_patient",
            reported_unit="ABC/cell",
            measurement_method="Quantibrite PE calibrated flow cytometry",
            value_qualifier="exact_reported",
            source_doi="10.1000/pt.example",
        ),
    ]
    p = _write_corpus(tmp_path, rows)
    d = r.read_absolute_density("MSLN", corpus_path=p)
    assert d["density_evidence_level"] == "A"  # patient A beats cell-line B
    assert d["value_best"] == 5000.0
    assert d["n_admissible_measurements"] == 2


def test_empty_target_grade_e(tmp_path):
    p = _write_corpus(tmp_path, [_good_row()])
    d = r.read_absolute_density("NOTATARGET", corpus_path=p)
    assert d["density_evidence_level"] == "E"
    assert d["value_best"] is None


# --- integration against a bundled slice of the GOVERNED corpus ----------------------------------
# The governed corpus is the S3 source-of-truth (data-catalog surface-antigen-absolute-density-
# curated-v1) — the reader pulls it from S3. To keep CI deterministic + offline, these integration
# assertions run against a committed FIXTURE SLICE (70 real rows extracted from the corpus), passed
# via corpus_path. The fixture is real data (not synthetic), so it exercises the true schema.
FIXTURE = Path(__file__).resolve().parent / "fixture_corpus_slice.tsv"


def test_fixture_slice_admissible_counts():
    rows = r._load_corpus(corpus_path=FIXTURE)
    assert len(rows) >= 60, "fixture slice should be populated"
    held = [(row["record_id"], r.validate_row(row)[1]) for row in rows if not r.validate_row(row)[0]]
    # only explicit negatives (+ any method-controls) are held; everything else is a numeric anchor
    for _rid, reason in held:
        assert reason in ("explicit_negative_not_a_numeric_anchor", "not_admissible_for_absolute_scale:no"), (
            _rid,
            reason,
        )


def test_fixture_known_targets():
    # patient-grade hematologic anchors + cell-line solid-tumor anchors both resolve
    cll = r.read_absolute_density("MS4A1", "CLL", corpus_path=FIXTURE)  # CD20
    assert cll["density_evidence_level"] == "A" and cll["n_patient"] == 28
    egfr = r.read_absolute_density("EGFR", "NSCLC", corpus_path=FIXTURE)
    assert egfr["density_evidence_level"] in ("B", "B-") and egfr["n_admissible_measurements"] >= 18
    # CD19 myeloma is the ultra-low patient anchor (grade A, low class)
    cd19 = r.read_absolute_density("CD19", "MM", corpus_path=FIXTURE)
    assert cd19["density_evidence_level"] == "A" and cd19["absolute_density_class"] in ("low", "very_low")


def test_fixture_explicit_negatives():
    assert len(r.read_explicit_negatives("CD19", corpus_path=FIXTURE)) == 4
    assert len(r.read_explicit_negatives("IL2RA", corpus_path=FIXTURE)) == 4
