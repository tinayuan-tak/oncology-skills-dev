"""The lineage-conditional refit must not name a feature it cannot support.

Consumer report, 2026-09-16, against framework-run 2026-09-11-verdict-only-tables: "I couldn't
figure out what RF feature was displayed on the by-lineage-predictability bar chart. If it is the
top feature within an indication, own_hotspot should have been the top feature for most lineages in
the KRAS analysis." For KRAS, own_mut_hotspot carries global RF importance 0.4405 (10x the runner-up)
and predictability_class own_omics_driven — and topped 0 of 14 lineages, losing to expr_KRT83,
expr_TAS2R46, cn_ENSG00000258790 and similar.

The innocent explanation would be that own_mut_hotspot has no within-lineage variance. It is refuted
by an independent card computed on the SAME 88 Bowel cell lines: mutation-stratified-dependency
reports 43 hotspot-mutant vs 45 wildtype, delta_chronos -1.142, Mann-Whitney p=1.2467e-10. That is
maximum variance on the most significant variable available, against a lineage row whose top_feature
was expr_KRT83 at r2=0.108.

Two independent defects, measured here rather than argued:

1. THE DENOMINATOR. Importances were averaged over only the folds in which SelectKBest happened to
   choose the feature, so a feature selected in 1 of 3 folds at 0.30 outranked one selected in all 3
   at 0.25. Not being selected is a measurement of ZERO for that fold, not a missing observation.
   test_rf_importance_means_sum_to_one_like_the_per_fold_importances_they_average pins this with an
   exact invariant rather than a threshold: RF impurity importances sum to 1.0 within a fold, so
   their mean across folds must also sum to 1.0. Measured on trunk: 1.2977.

2. NO REPORTING GATE. argmax over a near-flat importance vector from an unpredictive model names a
   feature essentially at random, and every qualifying lineage was reported with a confidently
   formatted top feature — 13 of KRAS's 14 lineages sitting below the r2=0.16 DepMap
   high-confidence floor THE FIGURE ITSELF DRAWS. A 12-seed synthetic sweep at n=88 with 9000
   correlated features showed the failure is entirely concentrated at low r2: every seed where a
   noise feature beat the true biomarker had r2 < 0.03, and every seed clearing the 0.16 floor
   named the true biomarker. So the floor is not an arbitrary cutoff here; it separates the regime
   where the argmax is informative from the regime where it is a coin flip.

The tests deliberately do NOT assert that the fixed fit picks the true feature more often, even
though the full sweep says it does. RETRACTION, recorded here because an earlier draft of this
docstring asserted the opposite: an interim 8-seed read reported the k-cap as "6 of 8 up, 2 down,
within noise". The completed 12-seed three-arm sweep refutes that. Isolated (see the measurement
recorded at LINEAGE_SELECT_K_FLOOR in cli.py), the denominator fix moved true-biomarker wins from
7/12 to 9/12 at exactly zero r2 change, and the k-cap raised r2 in 11 of 12 seeds (mean +0.024, sign
test p=0.0032), moving wins 9/12 -> 10/12.

The reason not to assert it here is REACHABILITY, not absence of effect: every ranking flip in the
sweep occurred at r2 < 0.07, below the r2=0.16 floor, so under the reporting gate added in
_fit_lineage_conditional every flipped row is withheld from the consumer anyway. A test asserting a
ranking improvement would therefore be pinning behaviour no product surface can show, on a synthetic
generator, at n=12. The claims worth pinning are the exact invariant above and the withholding below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_predictability_precompute import cli as e5cli  # noqa: E402


def _lineage_inputs(n_per_lineage: int, beta: float, n_noise: int = 60, seed: int = 0):
    """One lineage's worth of samples with a genuinely bipartite own_mut_hotspot feature.

    beta scales the hotspot's effect on y, which is how each test chooses whether the resulting fit
    lands above or below the r2 floor. The hotspot is a 50/50 split, so it always has maximum
    within-lineage variance — the point being that a WITHHELD top_feature is not a claim that the
    feature is absent or constant.
    """
    rng = np.random.default_rng(seed)
    hot = np.zeros(n_per_lineage, dtype=np.float32)
    hot[: n_per_lineage // 2] = 1.0
    rng.shuffle(hot)
    noise = rng.normal(0, 1, (n_per_lineage, n_noise)).astype(np.float32)
    y = (-0.4 + beta * hot + rng.normal(0, 0.55, n_per_lineage)).astype(np.float32)
    X = np.column_stack([hot, noise]).astype(np.float32)
    names = ["own_mut_hotspot"] + [f"expr_N{i}" for i in range(n_noise)]
    model_ids = [f"ACH-{i:06d}" for i in range(n_per_lineage)]
    model_df = pd.DataFrame({"ModelID": model_ids, "OncotreeLineage": ["Bowel"] * n_per_lineage})
    return X, y, model_ids, model_df, names


def _fit_one_lineage(beta: float, seed: int = 0):
    X, y, mids, model_df, names = _lineage_inputs(60, beta, seed=seed)
    rows = e5cli._fit_lineage_conditional(X, y, mids, model_df, names)
    assert len(rows) == 1, f"expected exactly one qualifying lineage, got {[r['lineage'] for r in rows]}"
    return rows[0]


# --------------------------------------------------------------------------------------------------
# 1. The denominator, pinned by an exact invariant
# --------------------------------------------------------------------------------------------------


def test_rf_importance_means_sum_to_one_like_the_per_fold_importances_they_average(monkeypatch):
    """sklearn's feature_importances_ sum to 1.0 per fit; a fold-mean must preserve that.

    SELECT_K_BEST is monkeypatched below the feature count ON PURPOSE: the defect is only reachable
    when KBest's choice VARIES across folds, so a test run with k >= n_features would pass against
    the broken code (the two denominators coincide when every feature is selected every fold). This
    is the fixture-can-express-the-failure control, inlined.
    """
    monkeypatch.setattr(e5cli, "SELECT_K_BEST", 20)
    rng = np.random.default_rng(3)
    n, p = 90, 200
    X = rng.normal(0, 1, (n, p)).astype(np.float32)
    y = (0.8 * X[:, 0] + rng.normal(0, 0.6, n)).astype(np.float32)
    trained = e5cli._train_dual_model_cv(X, y, [f"f{i}" for i in range(p)])

    assert trained["n_folds"] == e5cli.CV_N_SPLITS, "every fold fits an RF, so all of them measured every feature"
    total = float(trained["rf_importances_mean"].sum())
    assert total == pytest.approx(1.0, abs=1e-6), (
        f"fold-mean of RF importances sums to {total:.4f}, not 1.0 — the denominator is counting "
        f"selections instead of folds, which inflates inconsistently-selected (noisy) features"
    )


def test_a_fold_whose_shap_never_ran_shrinks_only_the_shap_denominator(monkeypatch):
    """The asymmetry the fix turns on, stated as a test.

    An unselected feature was MEASURED as zero, so it must not shrink a denominator. A fold in which
    shap/xgboost RAISED measured nothing at all, so it must. Conflating the two is what made the old
    code wrong; keeping them separate is what stops the fix from over-correcting.
    """
    monkeypatch.setattr(e5cli, "SELECT_K_BEST", 20)
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (60, 80)).astype(np.float32)
    y = (0.7 * X[:, 0] + rng.normal(0, 0.5, 60)).astype(np.float32)
    trained = e5cli._train_dual_model_cv(X, y, [f"f{i}" for i in range(80)])

    assert trained["n_folds"] == e5cli.CV_N_SPLITS
    # shap is an optional lazy import; whether it is installed decides which branch is live, so
    # assert the INVARIANT that holds either way rather than pinning the environment.
    if trained["has_shap"]:
        assert 0 <= trained["n_folds_shap_rf"] <= trained["n_folds"]
    else:
        assert trained["n_folds_shap_rf"] == 0, "no shap ⇒ no fold measured a SHAP value"
        assert float(trained["shap_rf_mean_abs"].sum()) == 0.0, "and an unmeasured quantity must be 0, not a 0/0 nan"


# --------------------------------------------------------------------------------------------------
# 2. The reporting gate
# --------------------------------------------------------------------------------------------------


def test_a_lineage_below_the_r2_floor_withholds_its_top_feature():
    """The core regression. This is the KRAS-Bowel shape: real biomarker, unpredictive fit."""
    row = _fit_one_lineage(beta=-0.05)
    assert row["r2"] < e5cli.R2_DEPMAP_HIGH_CONF, (
        f"fixture must land BELOW the floor to be meaningful, got r2={row['r2']}"
    )
    assert row["top_feature"] is None, (
        f"named {row['top_feature']!r} from a fit at r2={row['r2']:.4f}; argmax over a near-flat "
        f"importance vector is not a finding"
    )
    assert row["top_feature_status"] == "withheld_r2_below_high_conf_floor"


def test_the_r2_itself_is_still_reported_when_the_feature_is_withheld():
    """Withholding the feature must not drop the row: the r2 is a real read-out, and removing the
    lineage would silently misrepresent which lineages were evaluated at all."""
    row = _fit_one_lineage(beta=-0.05)
    assert row["lineage"] == "Bowel"
    assert row["n_cell_lines"] == 60
    assert isinstance(row["r2"], float)


def test_a_lineage_above_the_r2_floor_still_reports_its_top_feature():
    """The gate must not be over-broad — a predictive fit still names its feature, and on this
    fixture that feature is the real one."""
    row = _fit_one_lineage(beta=-2.2)
    assert row["r2"] >= e5cli.R2_DEPMAP_HIGH_CONF, f"fixture must clear the floor, got r2={row['r2']}"
    assert row["top_feature"] == "own_mut_hotspot"
    assert row["top_feature_status"] == "reported"


def test_the_withholding_reason_is_a_field_not_a_prose_string():
    """A consumer must be able to tell "withheld" from "never computed" WITHOUT parsing English.

    Every row carries top_feature_status, so a null top_feature is never ambiguous. This repo has
    now hit the prose-only-caveat failure mode three separate times; a machine-readable status is
    the cheap structural fix.
    """
    for beta in (-0.05, -2.2):
        row = _fit_one_lineage(beta=beta)
        assert row["top_feature_status"] in ("reported", "withheld_r2_below_high_conf_floor")
        assert (row["top_feature"] is None) == (row["top_feature_status"] != "reported"), (
            "top_feature and top_feature_status must never disagree"
        )


def test_the_withheld_status_survives_the_parquet_round_trip(tmp_path):
    """The status has to reach the reader, which means it has to be in the written schema."""
    rec = {
        "gene_symbol": "KRAS",
        "n_cell_lines_evaluated": 1500,
        "per_lineage_predictability": [
            {
                "lineage": "Bowel",
                "n_cell_lines": 88,
                "r2": 0.108,
                "top_feature": None,
                "top_feature_status": "withheld_r2_below_high_conf_floor",
            },
            {
                "lineage": "Pancreas",
                "n_cell_lines": 45,
                "r2": 0.42,
                "top_feature": "own_mut_hotspot",
                "top_feature_status": "reported",
            },
        ],
    }
    out = e5cli.write_parquet([rec], tmp_path / "p.parquet")
    rows = pq.read_table(out).column("per_lineage_predictability")[0].as_py()
    by_lin = {r["lineage"]: r for r in rows}
    assert by_lin["Bowel"]["top_feature"] is None
    assert by_lin["Bowel"]["top_feature_status"] == "withheld_r2_below_high_conf_floor"
    assert by_lin["Pancreas"]["top_feature_status"] == "reported"


# --------------------------------------------------------------------------------------------------
# 3. The xgb feature table must not be the RF table wearing an xgb label
# --------------------------------------------------------------------------------------------------


def test_the_xgb_fallback_ranks_by_xgboosts_own_importances(monkeypatch):
    """With shap absent, the xgb table used trained["rf_importances_mean"] — RF's ranking under an
    xgb name, byte-identical scores and all — and the rf_importance=0.0 fill hid the duplication.

    Skipped when xgboost is unavailable, because then there is no xgb table to be wrong about.
    """
    monkeypatch.setattr(e5cli, "SELECT_K_BEST", 20)
    rng = np.random.default_rng(1)
    n, p = 90, 120
    X = rng.normal(0, 1, (n, p)).astype(np.float32)
    y = (0.9 * X[:, 0] + 0.5 * X[:, 1] + rng.normal(0, 0.5, n)).astype(np.float32)
    names = [f"f{i}" for i in range(p)]
    trained = e5cli._train_dual_model_cv(X, y, names)
    if not trained["has_xgb"]:
        pytest.skip("xgboost not installed — no xgb ranking exists to mislabel")

    assert "xgb_importances_mean" in trained, "xgb's own gain importances must be accumulated"
    rf_rank = trained["rf_importances_mean"]
    xgb_rank = trained["xgb_importances_mean"]
    assert float(xgb_rank.sum()) > 0, "xgb gain importances must actually be populated"
    assert not np.allclose(rf_rank, xgb_rank), (
        "the two models' importance vectors are identical, so one of them is not being measured"
    )


def test_the_xgb_table_carries_the_real_rf_importance_not_a_zero_fill():
    """rf_importance was hard-coded to 0.0 for xgb entries with the comment "XGBoost has its own
    importances; we skip" — false in the fallback case, and it zeroed the one column a reader could
    have used to notice the two tables were the same."""
    omics = _make_small_omics(n_lines=150)
    rec = e5cli.train_gene("KRAS", omics)
    assert rec is not None
    if not rec["top_features_xgb_shap"]:
        pytest.skip("xgboost not installed — no xgb table emitted")
    assert any(e["rf_importance"] != 0.0 for e in rec["top_features_xgb_shap"]), (
        "every xgb entry still reports rf_importance == 0.0, so the parity column is uninformative"
    )


def test_an_xgb_ranking_no_fold_produced_emits_no_table_rather_than_ten_zeros(monkeypatch):
    """A regression guard on THIS fix, not on trunk.

    has_xgb records that `import xgboost` succeeded, not that any fit did — every per-fold fit sits
    inside `except Exception: pass`. So xgb_importances_mean can be all zeros while has_xgb is True.
    _top_features would then rank an all-zero vector and return the 10 alphabetically-first features
    at importance 0.0: a published ranking with no measurement behind it. The old fallback could not
    reach this state because RF's importances are never all zero, so switching the fallback to xgb's
    own importances is what created the hazard.
    """
    real = e5cli._train_dual_model_cv

    def _no_xgb_signal(X, y, feature_names, random_state=42):
        out = real(X, y, feature_names, random_state)
        out["has_xgb"] = True  # import succeeded ...
        out["has_shap"] = False  # ... no SHAP, so the xgb table falls back to xgb's own importances
        out["xgb_importances_mean"] = np.zeros_like(out["xgb_importances_mean"])  # ... but every fit raised
        out["n_folds_xgb"] = 0
        return out

    monkeypatch.setattr(e5cli, "_train_dual_model_cv", _no_xgb_signal)
    rec = e5cli.train_gene("KRAS", _make_small_omics(n_lines=150))
    assert rec is not None
    assert rec["top_features_xgb_shap"] == [], (
        f"emitted {len(rec['top_features_xgb_shap'])} xgb features from an all-zero ranking: "
        f"{[e['feature'] for e in rec['top_features_xgb_shap']]}"
    )
    assert rec["top_features_rf_shap"], "the RF table must be unaffected — only the xgb leg was blind"


def _make_small_omics(n_lines=150):
    """A minimal omics bundle (mirrors test_synthetic_predictability._make_omics_bundle) with enough
    lines to clear MIN_CELL_LINES_PER_GENE and one strong own-omics signal."""
    from depmap_predictability_precompute import features as feat

    rng = np.random.default_rng(0)
    model_ids = [f"ACH-{i:06d}" for i in range(n_lines)]
    lineages = (["A"] * (n_lines // 2)) + ["B"] * (n_lines - n_lines // 2)
    model_df = pd.DataFrame({"ModelID": model_ids, "OncotreeLineage": lineages})
    idx = pd.Index(model_ids, name="ModelID")
    expr_kras = rng.normal(3, 1, n_lines).astype(np.float32)
    y = (-2.0 + 0.5 * expr_kras + rng.normal(0, 0.1, n_lines)).astype(np.float32)
    frame = lambda **kw: pd.DataFrame(kw, index=idx)  # noqa: E731
    chronos = frame(KRAS=y, TP53=rng.normal(-0.3, 0.3, n_lines).astype(np.float32))
    expression = frame(KRAS=expr_kras, TP53=rng.normal(4, 1, n_lines).astype(np.float32))
    cn = frame(
        KRAS=rng.normal(1.0, 0.1, n_lines).astype(np.float32), TP53=rng.normal(1.0, 0.1, n_lines).astype(np.float32)
    )
    mh = frame(KRAS=np.zeros(n_lines, dtype="int8"), TP53=np.zeros(n_lines, dtype="int8"))
    return {
        "chronos": chronos,
        "expression": expression,
        "copy_number": cn,
        "mut_hotspot": mh,
        "mut_damaging": mh.copy(),
        "lineage_one_hot": feat.build_lineage_one_hot(model_df, min_lines_per_lineage=5),
        "arm_level_cn": pd.DataFrame(index=idx),
        "driver_flags": pd.DataFrame(index=idx),
        "model_df": model_df,
    }
