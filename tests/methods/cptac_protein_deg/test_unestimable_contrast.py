"""UNESTIMABLE != FLAT (W4, 2026-09-12).

MSstatsTMT reports a protein quantified in only ONE condition as log2FC = +/-Inf with NA p/q/SE (its
`oneConditionMissing` issue), NOT as NA. Because `pd.isna(Inf)` is False, every `isna()`-shaped guard in
this method let those rows through as measurements: steps/03_pool_and_write.py::classify labelled them
`not_significant` ("tested, no tumor-vs-normal difference" — about a ratio with no denominator), the
read layer passed the +Inf effect size on to the card and into three `max(|effect|)` argmax calls. (The
all-gene percentile null was NOT affected — percentile_null already drops non-finite values; that is
pinned below rather than "fixed".)

Measured on the shipped v1.2.0 product (101,013 rows) before the fix:
  - 1,618 rows carry +/-Inf: BRCA 1,613 of 10,491 (15.4%) + GBM 5. All 1,618 have NaN q AND NaN SE.
  - 1,564 genes had their pan-cancer row hijacked by BRCA's unestimable contrast; 32 of those shadowed a
    genuine strong_up call in another cohort (ESCO2 reported BRCA/unestimable, not LUAD +3.30).
  - 54 genes have NO estimable cohort at all, so `not_tumor_elevated` was a positive claim of
    non-elevation drawn from zero tests.

STEAP1/BRCA is the motivating case: 85 tumor aliquots quantified, 0 normal.

No S3 — `_load_indexed` is monkeypatched to synthetic rows carrying the exact shipped signature.
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.cptac_protein_deg.read")

POOL = importlib.import_module("importlib.util").spec_from_file_location(
    "_pool03", REPO / "methods" / "cptac_protein_deg" / "steps" / "03_pool_and_write.py"
)
_pool = importlib.import_module("importlib.util").module_from_spec(POOL)
POOL.loader.exec_module(_pool)


def _row(cohort, gene, cls, effect, q=1e-6, med_n=3.0, med_t=5.0, se=0.1):
    return {
        "cohort": cohort,
        "gene_symbol": gene,
        "protein_effect_size": effect,
        "protein_effect_size_se": se,
        "protein_bh_q_value": q,
        "protein_p_value": q,
        "protein_median_log2_tumor": med_t,
        "protein_median_log2_normal": med_n,
        "n_tumor_samples": 125,
        "n_normal_samples": 18,
        "protein_expression_class": cls,
        "stat_test_used": "msstatstmt_limma_ebayes_moderated",
        "method_version": "1.2.0",
    }


def _unestimable_row(cohort="BRCA", gene="STEAP1", sign=1.0):
    """The EXACT shipped signature: +/-Inf effect, NaN p/q/SE, and the missing condition's median NaN."""
    row = _row(cohort, gene, "not_significant", sign * math.inf, q=float("nan"), se=float("nan"))
    row["protein_median_log2_normal"] = float("nan") if sign > 0 else 3.0
    row["protein_median_log2_tumor"] = 0.05 if sign > 0 else float("nan")
    return row


def _patch(monkeypatch, rows):
    df = pd.DataFrame(rows)
    cgi, gi = {}, {}
    for i, row in enumerate(rows):
        g = str(row["gene_symbol"]).upper()
        cgi[(str(row["cohort"]).upper(), g)] = i
        gi.setdefault(g, []).append(i)
    monkeypatch.setattr(r, "_load_indexed", lambda: (df, cgi, gi))


# --- the mechanism itself ---------------------------------------------------------------------------


def test_is_num_admits_inf_but_is_finite_num_rejects_it():
    """Pins the exact reason the defect survived: the pre-existing numeric guard treats Inf as a number."""
    assert r._is_num(math.inf) is True, "if this flips, the isna-shaped guards were never the problem"
    assert r._is_num(-math.inf) is True
    assert r._is_finite_num(math.inf) is False
    assert r._is_finite_num(-math.inf) is False
    assert r._is_finite_num(float("nan")) is False
    assert r._is_finite_num(2.0) is True


def test_unestimable_reason_fires_on_inf_and_is_silent_on_a_real_estimate():
    assert r._unestimable_reason(_unestimable_row()) is not None
    assert r._unestimable_reason(_row("OV", "MSLN", "strong_up", 3.2)) is None
    # A flat-but-ESTIMATED row is a measurement, not an absence — must NOT be swept up.
    assert r._unestimable_reason(_row("OV", "FLAT1", "not_significant", 0.01, q=0.9)) is None


def test_unestimable_reason_names_the_side_that_had_no_quantification():
    assert "ZERO normal aliquots" in r._unestimable_reason(_unestimable_row(sign=1.0))
    assert "ZERO tumor aliquots" in r._unestimable_reason(_unestimable_row(sign=-1.0))


# --- read_target_summary ---------------------------------------------------------------------------


def test_unestimable_contrast_reads_data_unavailable_not_not_significant(monkeypatch):
    _patch(monkeypatch, [_unestimable_row()])
    s = r.read_target_summary("STEAP1", indication="BRCA")
    assert s["protein_expression_class"] == "data_unavailable", s
    assert s["protein_expression_class"] != "not_significant"
    assert s["protein_contrast_estimable"] is False
    # No non-finite number may escape to the card (not JSON-serializable, and poisons every consumer).
    assert s["protein_effect_size"] is None
    for k, v in s.items():
        assert not (isinstance(v, float) and not math.isfinite(v)), f"{k}={v!r} is non-finite"
    assert "unestimable_contrast" in str(s.get("_data_note"))
    # The side that WAS measured is preserved — it is the only evidence about why the contrast failed —
    # and the missing side is None, not NaN (NaN is no more serializable than Inf).
    assert s["protein_median_log2_tumor"] == pytest.approx(0.05)
    assert s["protein_median_log2_normal"] is None
    assert s["n_tumor_samples"] == 125 and s["n_normal_samples"] == 18


def test_estimable_rows_are_untouched(monkeypatch):
    _patch(monkeypatch, [_row("OV", "MSLN", "strong_up", 3.2)])
    s = r.read_target_summary("MSLN", indication="OV")
    assert s["protein_expression_class"] == "strong_up"
    assert s["protein_contrast_estimable"] is True
    assert s["protein_effect_size"] == pytest.approx(3.2)


def test_absent_target_is_estimable_none_not_false(monkeypatch):
    """None = no row at all; False = a row exists but its contrast is unestimable. Distinct states."""
    _patch(monkeypatch, [_row("OV", "MSLN", "strong_up", 3.2)])
    s = r.read_target_summary("NOTAGENE", indication="OV")
    assert s["protein_expression_class"] == "data_unavailable"
    assert s["protein_contrast_estimable"] is None


# --- the argmax hijack -----------------------------------------------------------------------------


def test_unestimable_row_never_wins_the_pan_cancer_argmax(monkeypatch):
    """ESCO2's live shape: unestimable in BRCA, genuinely strong_up in LUAD. abs(inf) > 3.30, so the
    indication-free path reported BRCA/not_significant and hid the real call."""
    _patch(monkeypatch, [_unestimable_row("BRCA", "ESCO2"), _row("LUAD", "ESCO2", "strong_up", 3.30)])
    s = r.read_target_summary("ESCO2")  # no indication -> pan-cancer argmax
    assert s["cohort"] == "LUAD", s
    assert s["protein_expression_class"] == "strong_up"
    assert s["protein_effect_size"] == pytest.approx(3.30)


def test_read_all_cohorts_sorts_unestimable_last(monkeypatch):
    _patch(
        monkeypatch,
        [
            _unestimable_row("BRCA", "ESCO2"),
            _row("LUAD", "ESCO2", "strong_up", 3.30),
            _row("OV", "ESCO2", "small_effect", 0.2),
        ],
    )
    rows = r.read_all_cohorts("ESCO2")
    assert [row["cohort"] for row in rows] == ["LUAD", "OV", "BRCA"], rows
    # The unestimable cohort is still REPORTED (legible loss), just not ranked as the strongest signal.
    assert rows[-1]["protein_contrast_estimable"] is False


# --- the percentile null ---------------------------------------------------------------------------


def test_percentile_null_was_never_poisoned_by_the_inf_mass(monkeypatch):
    """NOT a fix — a pin on behavior that was already correct, so a percentile_null refactor cannot
    silently reintroduce the defect.

    An earlier read of this code assumed the +Inf rows sat in the all-gene null and capped every real
    BRCA gene's percentile at ~84.6. They do not: percentile_null._finite drops non-finite values from
    the null before ranking. Verified by measurement — an effect of +2.0 in BRCA ranks identically with
    and without the 1,613 Inf rows present in the input list."""
    from methods.percentile_null import percentile_rank

    rows = [_row("BRCA", f"G{i}", "small_effect", 0.0) for i in range(85)]
    rows += [_unestimable_row("BRCA", f"U{i}") for i in range(15)]
    rows.append(_row("BRCA", "REAL", "strong_up", 2.0))
    _patch(monkeypatch, rows)
    s = r.read_target_summary("REAL", indication="BRCA")
    assert s["allgene_percentile"] > 99.0, s
    assert s["allgene_percentile_class"] == "top_1pct"

    with_inf = percentile_rank(2.0, [row["protein_effect_size"] for row in rows])
    without_inf = percentile_rank(2.0, [row["protein_effect_size"] for row in rows if row["gene_symbol"][0] != "U"])
    assert with_inf == pytest.approx(without_inf), "percentile_null must ignore non-finite null values"
    assert s["allgene_percentile"] == pytest.approx(with_inf)


def test_percentile_is_none_for_an_unestimable_target(monkeypatch):
    _patch(monkeypatch, [_unestimable_row("BRCA", "STEAP1"), _row("BRCA", "G1", "small_effect", 0.1)])
    s = r.read_target_summary("STEAP1", indication="BRCA")
    assert s["allgene_percentile"] is None
    assert s["allgene_percentile_class"] == "data_unavailable"


# --- the breadth roll-up ---------------------------------------------------------------------------


def test_breadth_denominator_excludes_unestimable_cohorts(monkeypatch):
    """3 up of 3 ESTIMATED cohorts is broadly_tumor_elevated; counting an unestimable 4th as `tested`
    made it 3/4 and (at the margin) demotes the class on a coverage artifact."""
    _patch(
        monkeypatch,
        [
            _row("LUAD", "X", "strong_up", 2.0),
            _row("OV", "X", "strong_up", 2.1),
            _row("COAD", "X", "modest_up", 1.0),
            _unestimable_row("BRCA", "X"),
        ],
    )
    b = r.read_tumor_elevation_breadth("X")
    assert b["n_cohorts_tested"] == 3, b
    assert b["n_cohorts_elevated"] == 3
    assert b["fraction_elevated"] == pytest.approx(1.0)
    assert b["tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    # The dropped cohort stays LEGIBLE rather than silently vanishing.
    assert b["cohorts_unestimable"] == ["BRCA"]
    assert "BRCA" not in b["cohorts_tested"]


def test_all_cohorts_unestimable_is_data_unavailable_not_not_tumor_elevated(monkeypatch):
    """54 genes on the shipped product have no estimable cohort. `not_tumor_elevated` asserts a negative
    from zero tests; only `data_unavailable` is honest."""
    _patch(monkeypatch, [_unestimable_row("BRCA", "Y"), _unestimable_row("GBM", "Y")])
    b = r.read_tumor_elevation_breadth("Y")
    assert b["tumor_elevation_breadth_class"] == "data_unavailable", b
    assert b["tumor_elevation_breadth_class"] != "not_tumor_elevated"
    assert b["n_cohorts_tested"] == 0
    assert b["cohorts_unestimable"] == ["BRCA", "GBM"]


# --- the build layer (steps/03) --------------------------------------------------------------------


def test_classify_maps_nonfinite_logfc_to_data_unavailable():
    assert _pool.classify(math.inf, float("nan")) == "data_unavailable"
    assert _pool.classify(-math.inf, float("nan")) == "data_unavailable"
    # Regression guard: this is the branch that used to return not_significant.
    assert _pool.classify(math.inf, float("nan")) != "not_significant"


def test_classify_honors_the_upstream_msstats_issue():
    """stage 02 now carries MSstatsTMT's own `issue`; a flagged row is data_unavailable even if the
    numbers happen to look estimable."""
    assert _pool.classify(2.0, 1e-6, issue="oneConditionMissing") == "data_unavailable"
    assert _pool.classify(2.0, 1e-6, issue="completeMissing") == "data_unavailable"
    for ok in ("ok", "", "NA", None, float("nan")):
        assert _pool.classify(2.0, 1e-6, issue=ok) == "strong_up", ok


def test_classify_still_calls_a_genuinely_flat_row_not_significant():
    """No regression: a real measurement with q>=0.05 is a MEASUREMENT, not an absence."""
    assert _pool.classify(0.1, 0.9) == "not_significant"
    assert _pool.classify(3.0, 0.20) == "not_significant"  # big effect, not significant — still a measurement
    assert _pool.classify(0.8, float("nan")) == "not_significant"  # effect estimated, significance unknown
    assert _pool.classify(float("nan"), float("nan")) == "data_unavailable"  # nothing estimated at all
    assert _pool.classify(2.0, 1e-6) == "strong_up"
    assert _pool.classify(1.0, 1e-6) == "modest_up"
    assert _pool.classify(-2.0, 1e-6) == "strong_down"


def test_pool_is_finite_rejects_inf_where_pandas_isna_admits_it():
    assert not pd.isna(math.inf)  # the root cause, pinned: Inf is not NA
    assert _pool._is_finite(math.inf) is False
    assert _pool._is_finite(float("nan")) is False
    assert _pool._is_finite(None) is False
    assert _pool._is_finite(1.5) is True


# --- the R build step ------------------------------------------------------------------------------


def test_r_step_issue_column_tests_finiteness_not_just_na():
    """steps/02 used `ifelse(is.na(res$log2FC), "no_estimate", "ok")`, which stamped all 1,618
    unestimable rows "ok". A text ratchet (R is not AST-checkable here): the issue computation must
    reference is.finite AND must carry MSstatsTMT's own issue column. Weaker than the Python tests
    above by construction — the authoritative guard is validate_biology.py's structural tier, which
    reads the built product."""
    src = (REPO / "methods" / "cptac_protein_deg" / "steps" / "02_msstats_deg.R").read_text()
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    assert not any('ifelse(is.na(res$log2FC), "no_estimate", "ok")' in ln for ln in code)
    assert any("is.finite(res$log2FC)" in ln for ln in code)
    assert any("upstream_issue" in ln for ln in code)
    assert any('"issue" %in% names(res)' in ln for ln in code)
