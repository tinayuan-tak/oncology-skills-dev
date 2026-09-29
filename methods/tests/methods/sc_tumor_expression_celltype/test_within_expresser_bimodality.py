"""Within-EXPRESSER malignant shape / bimodality headline (#695) — the emit half of the target-contracts
card `tumor-scrna-celltype-expression` (#955) within-expresser bimodality display.

Covers: BC value correctness on a known shape, the measured surfacing on read_sc_expression_presence
(bimodal / unimodal), the under-powered gate (malignant_n_detected < min_detected_for_shape → None), the
null-shape gate (<3 expressers / zero variance → None), the pre-republish path (product lacks the #668
shape columns → underpowered, but malignant_n_detected still computed), the data_unavailable path, and a
VERDICT-INERT spine guard (adding the shape columns must not move the presence sc_expression_class).

Kept in its own file (mirrors test_heterogeneity_surfacing.py) so it does not collide with the shared
test_stats_and_assembler.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_tumor_expression_celltype import read as R
from methods.sc_tumor_expression_celltype import stats as S

_SHAPE_KEYS = (
    "malignant_expresser_bimodality_class",
    "malignant_expresser_bimodality_coefficient",
    "malignant_expresser_skewness",
    "malignant_expresser_excess_kurtosis",
    "malignant_n_detected",
)


def _rows(spec, with_shape=True):
    """spec rows: (compartment, dataset_id, donor_id, n_cells, detection_fraction, abundance,
    expressing_skewness, expressing_kurtosis). with_shape=False drops the #668 shape columns to model a
    pre-republish product."""
    out = []
    for c, ds, d, n, det, ab, sk, ku in spec:
        row = {
            "gene_symbol": "EPCAM",
            "compartment": c,
            "dataset_id": ds,
            "donor_id": d,
            "n_cells": n,
            "detection_fraction": det,
            "abundance_log1p_cp10k": ab,
        }
        if with_shape:
            row["expressing_skewness"] = sk
            row["expressing_kurtosis"] = ku
        out.append(row)
    return out


# five high-detection malignant donors (n_detected well over the floor); shape set per test.
def _five_malignant(sk, ku):
    return [
        ("malignant", "dsA", "d1", 300, 0.86, 3.1, sk, ku),
        ("malignant", "dsA", "d2", 250, 0.88, 2.8, sk, ku),
        ("malignant", "dsA", "d3", 280, 0.90, 3.0, sk, ku),
        ("malignant", "dsB", "d4", 220, 0.84, 2.9, sk, ku),
        ("malignant", "dsB", "d5", 260, 0.92, 2.7, sk, ku),
    ]


# ── BC value correctness (the pure Sarle formula) ────────────────────────────────────────────────
def test_bimodality_coefficient_normal_is_unimodal_value():
    # skew 0, excess kurtosis 0 (normal) → BC = 1/3
    assert S._bimodality_coefficient(0.0, 0.0) == pytest.approx(1.0 / 3.0)


def test_bimodality_coefficient_two_mode_value():
    # skew 0, excess kurtosis -1.5 → BC = 1/1.5 = 0.6667 (> 5/9 → bimodal)
    assert S._bimodality_coefficient(0.0, -1.5) == pytest.approx(1.0 / 1.5)


def test_bimodality_coefficient_none_on_null_moment():
    assert S._bimodality_coefficient(None, 0.0) is None
    assert S._bimodality_coefficient(0.0, None) is None


def test_bimodality_coefficient_none_on_nonpositive_denominator():
    assert S._bimodality_coefficient(0.0, -3.0) is None  # denom 0
    assert S._bimodality_coefficient(0.0, -4.0) is None  # denom < 0


# ── measured surfacing on the assembled card summary ─────────────────────────────────────────────
def test_bimodal_surfaced_on_measured_path(monkeypatch):
    import pandas as pd

    rows = pd.DataFrame(_rows(_five_malignant(0.0, -1.5)))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    for k in _SHAPE_KEYS:
        assert k in out, f"{k} not surfaced into the sc card summary"
    assert out["malignant_expresser_bimodality_class"] == "bimodal"
    assert out["malignant_expresser_bimodality_coefficient"] == pytest.approx(1.0 / 1.5, abs=1e-4)
    assert out["malignant_expresser_skewness"] == pytest.approx(0.0)
    assert out["malignant_expresser_excess_kurtosis"] == pytest.approx(-1.5)
    # denominator is DETECTED cells, distinct from total malignant cells; ~0.88 * 1310 total
    assert out["malignant_n_detected"] >= S.MIN_DETECTED_FOR_SHAPE
    assert out["malignant_n_detected"] != out["malignant_n_cells"]


def test_unimodal_surfaced_on_measured_path(monkeypatch):
    import pandas as pd

    rows = pd.DataFrame(_rows(_five_malignant(0.0, 0.0)))  # normal shape → BC 1/3
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["malignant_expresser_bimodality_class"] == "unimodal"
    assert out["malignant_expresser_bimodality_coefficient"] == pytest.approx(1.0 / 3.0, abs=1e-4)


# ── the two honest gates: n_detected floor + null shape ──────────────────────────────────────────
def test_underpowered_when_too_few_detected(monkeypatch):
    """Below the detected-cell floor → underpowered, BC withheld (None), but the source moments +
    n_detected are still surfaced (an honest power gap, never a measured unimodal/bimodal call)."""
    import pandas as pd

    # 5 reliable donors (>= MIN_CELLS_PER_DONOR cells, clears the presence floor via total cells) but a
    # tiny detection fraction → detected cells below MIN_DETECTED_FOR_SHAPE.
    spec = [
        ("malignant", "dsA", "d1", 400, 0.008, 0.2, 0.0, -1.5),
        ("malignant", "dsA", "d2", 400, 0.008, 0.2, 0.0, -1.5),
        ("malignant", "dsA", "d3", 400, 0.008, 0.2, 0.0, -1.5),
        ("malignant", "dsB", "d4", 400, 0.008, 0.2, 0.0, -1.5),
        ("malignant", "dsB", "d5", 400, 0.008, 0.2, 0.0, -1.5),
    ]
    rows = pd.DataFrame(_rows(spec))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["malignant_n_detected"] < S.MIN_DETECTED_FOR_SHAPE
    assert out["malignant_expresser_bimodality_class"] == "underpowered"
    assert out["malignant_expresser_bimodality_coefficient"] is None
    # source moments still surfaced when the emit provided them
    assert out["malignant_expresser_skewness"] == pytest.approx(0.0)


def test_underpowered_when_shape_stats_null(monkeypatch):
    """Null per-donor shape (the #668 emit returns None for <3 expressers / zero variance) → skew/kurt
    None, BC None, class underpowered — even though n_detected clears the floor."""
    import pandas as pd

    rows = pd.DataFrame(_rows(_five_malignant(None, None)))
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["malignant_n_detected"] >= S.MIN_DETECTED_FOR_SHAPE
    assert out["malignant_expresser_skewness"] is None
    assert out["malignant_expresser_excess_kurtosis"] is None
    assert out["malignant_expresser_bimodality_coefficient"] is None
    assert out["malignant_expresser_bimodality_class"] == "underpowered"


def test_pre_republish_product_without_shape_columns(monkeypatch):
    """A product that lacks the #668 shape columns (pre-republish) → shape None / underpowered, but
    malignant_n_detected is still computed from detection_fraction * n_cells."""
    import pandas as pd

    rows = pd.DataFrame(_rows(_five_malignant(0.0, -1.5), with_shape=False))
    assert "expressing_skewness" not in rows.columns
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: rows)
    out = R.read_sc_expression_presence("EPCAM", "COADREAD")
    assert out["malignant_n_detected"] >= S.MIN_DETECTED_FOR_SHAPE  # computable without the shape cols
    assert out["malignant_expresser_skewness"] is None
    assert out["malignant_expresser_bimodality_coefficient"] is None
    assert out["malignant_expresser_bimodality_class"] == "underpowered"


# ── data_unavailable path ────────────────────────────────────────────────────────────────────────
def test_shape_fields_surfaced_on_data_unavailable_path(monkeypatch):
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: None)
    out = R.read_sc_expression_presence("EPCAM", "PAAD")
    for k in _SHAPE_KEYS:
        assert k in out
    assert out["malignant_expresser_bimodality_class"] == "data_unavailable"
    assert out["malignant_expresser_bimodality_coefficient"] is None
    assert out["malignant_expresser_skewness"] is None
    assert out["malignant_expresser_excess_kurtosis"] is None
    assert out["malignant_n_detected"] == 0


def test_data_unavailable_when_no_malignant_compartment():
    """No malignant compartment in the summary → data_unavailable (abstain), never a measured shape."""
    summ = S.compartment_summary(
        [
            {
                "gene_symbol": "EPCAM",
                "compartment": "immune",
                "dataset_id": "dsA",
                "donor_id": f"d{i}",
                "n_cells": 500,
                "detection_fraction": 0.4,
                "abundance_log1p_cp10k": 1.2,
                "expressing_skewness": 0.0,
                "expressing_kurtosis": -1.5,
            }
            for i in range(5)
        ]
    )
    shape = S.malignant_expresser_shape_readout(summ)
    assert shape["malignant_expresser_bimodality_class"] == "data_unavailable"
    assert shape["malignant_expresser_bimodality_coefficient"] is None


# ── VERDICT-INERT spine guard: shape columns must not move the presence class ─────────────────────
def test_spine_unchanged_by_shape_columns(monkeypatch):
    """The within-expresser shape emit is additive/descriptive: the presence sc_expression_class and the
    malignant detection fraction must be byte-identical with vs without the #668 shape columns."""
    import pandas as pd

    with_shape = pd.DataFrame(_rows(_five_malignant(0.0, -1.5), with_shape=True))
    without = pd.DataFrame(_rows(_five_malignant(0.0, -1.5), with_shape=False))

    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: with_shape)
    a = R.read_sc_expression_presence("EPCAM", "COADREAD")
    monkeypatch.setattr(R, "read_gene_compartment_rows", lambda t, i: without)
    b = R.read_sc_expression_presence("EPCAM", "COADREAD")

    spine = (
        "sc_expression_class",
        "tce_homogeneity_class",
        "malignant_detection_fraction",
        "malignant_n_cells",
        "malignant_n_donors",
        "tce_antigen_escape_class",
        "stromal_confound_class",
    )
    for k in spine:
        assert a[k] == b[k], f"shape columns moved the presence spine field {k}"
    assert a["sc_expression_class"] == "malignant_broadly_detected"  # detection alone drives it
