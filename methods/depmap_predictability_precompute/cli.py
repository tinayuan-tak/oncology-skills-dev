#!/usr/bin/env python3
"""depmap-predictability-precompute CLI (v2 — DepMap-parity + extensions).

Per-gene predictability precompute for the E5 v2 build:

  - Feature set: target-own multi-omics + genome-wide expr/CN + arm-level CN
    + OncoKB-derived GoF/LoF driver flags + lineage one-hot.
    (See features.py for construction; ~60k features per gene.)
  - Per-fold `SelectKBest(f_regression, k=1000)` avoids leakage while matching
    DepMap Daintree's `KFilteredForest` reduction.
  - Dual model: RandomForestRegressor + XGBRegressor. Both fit on the same
    per-fold selected features. Delta-r² surfaced as a divergence diagnostic.
  - Cross-validation: **3-fold QuantileKFold** (quantile-stratified) matching
    DepMap's CV splitter. Report Pearson r + Pearson² r² on out-of-fold
    predictions.
  - Bootstrap 95% CI on r² via 500 resamples over cell-line indices.
  - SHAP TreeExplainer for feature attributions (mean(|SHAP|) across folds);
    RF `feature_importances_` reported alongside for DepMap-parity.
  - Lineage-conditional companion: for each OncotreeLineage with n_lines ≥ 30,
    refit RF and report per-lineage r² + top-3 SHAP features.
  - Classification (v2, CI-aware):
      r² CI lower bound ≥ 0.35  AND dominant feature is target-own → own_omics_driven
      r² CI lower bound ≥ 0.35  AND dominant feature is context/driver → context_or_driver_dependent
      r² ≥ 0.16 (DepMap high-conf) but CI-lo < 0.35 → weakly_predictable
      r² < 0.16 → unpredictable

Output parquet schema is documented in the plan file § "Output schema (v2)".
Includes checkpointing every N genes (default 25) so a crash loses ≤ N gene
fits.
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import numpy as np
import pandas as pd

from . import features as feat

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.2.0"


def _git_provenance() -> dict:
    """Capture the producing repo's git HEAD + working-tree cleanliness so
    run_manifest.json records the exact code that produced the artifact,
    rather than leaving downstream consumers (e.g. the data-catalog derived
    manifest) to infer the commit from checkout state.

    Degrades gracefully — provenance capture must NEVER fail the precompute.
    Returns {commit: None, dirty: None} if git or the repo is unavailable
    (e.g. running from an installed package outside a git checkout)."""
    repo_dir = METHOD_DIR.parents[1]

    def _git(*args: str) -> Optional[str]:
        try:
            r = subprocess.run(
                ["git", "-C", str(repo_dir), *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain") if commit is not None else None
    return {
        "commit": commit,
        "dirty": (status != "") if status is not None else None,
        "repo_dir": str(repo_dir),
    }


# Classification thresholds (v2). See card YAML for the authoritative copy.
R2_HIGH_CI_LO = 0.35  # CI lower bound above → strong-predictor bucket
R2_DEPMAP_HIGH_CONF = 0.16  # DepMap high-conf floor (Pearson r ≥ 0.4)

# CV + bootstrap constants
CV_N_SPLITS = 3
BOOTSTRAP_N = 500
LINEAGE_MIN_LINES = 30  # per-lineage refit min-n
SELECT_K_BEST = 1000
MIN_CELL_LINES_PER_GENE = 100  # exclusion floor


# ---------------------------------------------------------------------------
# QuantileKFold — quantile-stratified CV matching DepMap's cds-daintree
# ---------------------------------------------------------------------------


class QuantileKFold:
    """Stratify samples by y quantile then k-fold within each stratum.

    Ensures each fold has a similar distribution of the target's dependency
    values — critical when Chronos values are heavy-tailed or unbalanced across
    the cell-line panel. Mirrors Broad Institute's cds-daintree custom splitter.
    """

    def __init__(self, n_splits: int = 3, random_state: int = 42):
        self.n_splits = n_splits
        self.random_state = random_state

    def split(self, X, y):
        y = np.asarray(y)
        n = len(y)
        # Assign each sample to a quantile bin; then split each bin into n_splits folds.
        # Uses np.digitize on q-quantiles of y.
        n_bins = min(self.n_splits * 3, n // self.n_splits)
        edges = np.quantile(y, np.linspace(0, 1, n_bins + 1)[1:-1])
        bins = np.digitize(y, edges)
        rng = np.random.default_rng(self.random_state)
        # Shuffle within each bin, then assign to folds round-robin
        fold_assignment = np.full(n, -1, dtype=np.int32)
        for b in np.unique(bins):
            idxs = np.where(bins == b)[0]
            rng.shuffle(idxs)
            for i, idx in enumerate(idxs):
                fold_assignment[idx] = i % self.n_splits
        for k in range(self.n_splits):
            test = np.where(fold_assignment == k)[0]
            train = np.where(fold_assignment != k)[0]
            yield train, test


# ---------------------------------------------------------------------------
# Metrics + bootstrap
# ---------------------------------------------------------------------------


def _pearson_r(a: np.ndarray, b: np.ndarray) -> float:
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    r = float(np.corrcoef(a, b)[0, 1])
    return 0.0 if not np.isfinite(r) else r


def bootstrap_r2_ci(y_oof: np.ndarray, y_true: np.ndarray, n: int = BOOTSTRAP_N, seed: int = 42) -> tuple[float, float]:
    """Bootstrap 95% CI on Pearson² r² over cell-line indices."""
    rng = np.random.default_rng(seed)
    n_samples = len(y_true)
    r2s = np.empty(n, dtype=np.float32)
    for i in range(n):
        idx = rng.integers(0, n_samples, size=n_samples)
        r = _pearson_r(y_oof[idx], y_true[idx])
        r2s[i] = r * r
    lo = float(np.percentile(r2s, 2.5))
    hi = float(np.percentile(r2s, 97.5))
    return lo, hi


# ---------------------------------------------------------------------------
# Per-fold pipeline: SelectKBest → RF + XGB → OOF predictions
# ---------------------------------------------------------------------------


def _train_dual_model_cv(X: np.ndarray, y: np.ndarray, feature_names: list, random_state: int = 42) -> dict:
    """Run 3-fold QuantileKFold with per-fold KBest → RF + XGB. Return dict
    with y_oof arrays, aggregated SHAP means, and RF feature_importances_ means.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.feature_selection import SelectKBest, f_regression

    n = len(y)
    y_oof_rf = np.full(n, np.nan, dtype=np.float32)
    y_oof_xgb = np.full(n, np.nan, dtype=np.float32)

    # Per-feature aggregators — shape (n_features,)
    rf_importances_sum = np.zeros(X.shape[1], dtype=np.float64)
    rf_importances_count = np.zeros(X.shape[1], dtype=np.int32)
    shap_rf_abs_sum = np.zeros(X.shape[1], dtype=np.float64)
    shap_rf_count = np.zeros(X.shape[1], dtype=np.int32)
    shap_xgb_abs_sum = np.zeros(X.shape[1], dtype=np.float64)
    shap_xgb_count = np.zeros(X.shape[1], dtype=np.int32)

    k = min(SELECT_K_BEST, X.shape[1])

    # Lazy-import XGBoost + SHAP so import failures don't kill single-model runs
    try:
        from xgboost import XGBRegressor

        _has_xgb = True
    except ImportError:
        _has_xgb = False
    try:
        import shap

        _has_shap = True
    except ImportError:
        _has_shap = False

    for train_idx, test_idx in QuantileKFold(n_splits=CV_N_SPLITS, random_state=random_state).split(X, y):
        # Per-fold feature selection (avoids leakage)
        kbest = SelectKBest(f_regression, k=k)
        kbest.fit(X[train_idx], y[train_idx])
        selected_mask = kbest.get_support()  # (n_features,) bool
        selected_idx = np.where(selected_mask)[0]
        X_tr = X[train_idx][:, selected_idx]
        X_te = X[test_idx][:, selected_idx]

        # Fit RF
        rf = RandomForestRegressor(
            n_estimators=100,
            max_depth=8,
            min_samples_leaf=5,
            random_state=random_state,
            n_jobs=1,
        )
        rf.fit(X_tr, y[train_idx])
        y_oof_rf[test_idx] = rf.predict(X_te)

        # Accumulate RF importances (aligned back to full feature space)
        for i, src_idx in enumerate(selected_idx):
            rf_importances_sum[src_idx] += rf.feature_importances_[i]
            rf_importances_count[src_idx] += 1

        # SHAP for RF (mean(|SHAP|) across fold's test set)
        if _has_shap:
            try:
                explainer = shap.TreeExplainer(rf)
                shap_vals = explainer.shap_values(X_te, check_additivity=False)
                mean_abs = np.abs(shap_vals).mean(axis=0)
                for i, src_idx in enumerate(selected_idx):
                    shap_rf_abs_sum[src_idx] += mean_abs[i]
                    shap_rf_count[src_idx] += 1
            except Exception:
                pass

        # Fit XGBoost
        if _has_xgb:
            try:
                xgb = XGBRegressor(
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=random_state,
                    n_jobs=1,
                    verbosity=0,
                    objective="reg:squarederror",
                )
                xgb.fit(X_tr, y[train_idx])
                y_oof_xgb[test_idx] = xgb.predict(X_te)
                if _has_shap:
                    try:
                        expl_xgb = shap.TreeExplainer(xgb)
                        shap_vals = expl_xgb.shap_values(X_te, check_additivity=False)
                        mean_abs = np.abs(shap_vals).mean(axis=0)
                        for i, src_idx in enumerate(selected_idx):
                            shap_xgb_abs_sum[src_idx] += mean_abs[i]
                            shap_xgb_count[src_idx] += 1
                    except Exception:
                        pass
            except Exception:
                pass

    # Reduce accumulators → per-feature means (0 where the feature never made it through KBest)
    rf_importances_mean = np.where(
        rf_importances_count > 0,
        rf_importances_sum / np.maximum(rf_importances_count, 1),
        0.0,
    )
    shap_rf_mean = np.where(shap_rf_count > 0, shap_rf_abs_sum / np.maximum(shap_rf_count, 1), 0.0)
    shap_xgb_mean = np.where(shap_xgb_count > 0, shap_xgb_abs_sum / np.maximum(shap_xgb_count, 1), 0.0)

    return {
        "y_oof_rf": y_oof_rf,
        "y_oof_xgb": y_oof_xgb,
        "rf_importances_mean": rf_importances_mean,
        "shap_rf_mean_abs": shap_rf_mean,
        "shap_xgb_mean_abs": shap_xgb_mean,
        "has_xgb": _has_xgb,
        "has_shap": _has_shap,
    }


def _top_features(names: list, ranks: np.ndarray, k: int = 10) -> list:
    """Return the top-k (feature, feature_class, score) records by descending
    rank score. Ties broken alphabetically for reproducibility."""
    order = np.lexsort((names, -ranks))
    out = []
    seen = set()
    for i in order:
        if len(out) >= k:
            break
        n = names[i]
        if n in seen:
            continue
        seen.add(n)
        out.append(
            {
                "feature": n,
                "feature_class": feat.feature_class_of(n),
                "importance": float(ranks[i]),
            }
        )
    return out


def _classify(r2_rf: float, r2_rf_ci_lo: float, top_feature_class: str) -> tuple[str, str]:
    """Return (predictability_class, dominant_feature_class).

    Uses r² CI lower bound for the strong-predictor bucket; falls back to
    DepMap's high-confidence r ≥ 0.4 floor for the weakly_predictable band.
    """
    if r2_rf < R2_DEPMAP_HIGH_CONF:
        return "unpredictable", "unpredictable"
    if r2_rf_ci_lo >= R2_HIGH_CI_LO:
        if top_feature_class in feat.FEATURE_CLASS_OWN:
            return "own_omics_driven", top_feature_class
        return "context_or_driver_dependent", top_feature_class
    return "weakly_predictable", top_feature_class


# ---------------------------------------------------------------------------
# Lineage-conditional companion
# ---------------------------------------------------------------------------


def _fit_lineage_conditional(
    X: np.ndarray, y: np.ndarray, model_ids: list, model_df: pd.DataFrame, feature_names: list
) -> list:
    """For each large-enough lineage, refit RF within-lineage and report r² +
    top-3 features by RF importance. RF-only (no XGB / SHAP) to keep cost down.
    """
    lineage_map = dict(zip(model_df["ModelID"], model_df["OncotreeLineage"]))
    lineages = np.array([lineage_map.get(m) or "unknown" for m in model_ids])
    results = []
    for lin in np.unique(lineages):
        if lin in (None, "unknown", "OTHER"):
            continue
        idx = np.where(lineages == lin)[0]
        if len(idx) < LINEAGE_MIN_LINES:
            continue
        try:
            r2, top = _lineage_fit(X[idx], y[idx], feature_names)
        except Exception:
            continue
        results.append(
            {
                "lineage": lin,
                "n_cell_lines": int(len(idx)),
                "r2": float(r2),
                "top_feature": top,
            }
        )
    results.sort(key=lambda r: -r["r2"])
    return results


def _lineage_fit(X: np.ndarray, y: np.ndarray, feature_names: list) -> tuple[float, str]:
    """RF-only 3-fold on a lineage subset. Return (r², top feature name)."""
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.feature_selection import SelectKBest, f_regression

    y_oof = np.full(len(y), np.nan, dtype=np.float32)
    imp_sum = np.zeros(X.shape[1], dtype=np.float64)
    imp_count = np.zeros(X.shape[1], dtype=np.int32)
    k = min(SELECT_K_BEST, X.shape[1])
    for tr, te in QuantileKFold(n_splits=CV_N_SPLITS, random_state=42).split(X, y):
        kbest = SelectKBest(f_regression, k=k)
        kbest.fit(X[tr], y[tr])
        sel = np.where(kbest.get_support())[0]
        rf = RandomForestRegressor(n_estimators=50, max_depth=8, min_samples_leaf=5, random_state=42, n_jobs=1)
        rf.fit(X[tr][:, sel], y[tr])
        y_oof[te] = rf.predict(X[te][:, sel])
        for i, src in enumerate(sel):
            imp_sum[src] += rf.feature_importances_[i]
            imp_count[src] += 1
    r = _pearson_r(y_oof, y)
    imp = np.where(imp_count > 0, imp_sum / np.maximum(imp_count, 1), 0.0)
    top_idx = int(np.argmax(imp))
    return r * r, feature_names[top_idx]


# ---------------------------------------------------------------------------
# Per-gene compute (the hot loop)
# ---------------------------------------------------------------------------


def train_gene(gene: str, omics: dict) -> Optional[dict]:
    """End-to-end per-gene v2 predictability record. Returns dict matching the
    v2 parquet schema, or None if gene lacks coverage."""
    fm = feat.build_gene_feature_matrix(gene, omics, min_cell_lines=MIN_CELL_LINES_PER_GENE)
    if fm is None:
        return None
    X, y, names, mids = fm["X"], fm["y"], fm["feature_names"], fm["model_ids"]
    t0 = time.time()

    trained = _train_dual_model_cv(X, y, names)
    r_rf = _pearson_r(trained["y_oof_rf"], y)
    r2_rf = r_rf * r_rf
    r2_rf_ci = bootstrap_r2_ci(trained["y_oof_rf"], y)

    if trained["has_xgb"]:
        r_xgb = _pearson_r(trained["y_oof_xgb"], y)
        r2_xgb = r_xgb * r_xgb
        r2_xgb_ci = bootstrap_r2_ci(trained["y_oof_xgb"], y)
    else:
        r_xgb = float("nan")
        r2_xgb = float("nan")
        r2_xgb_ci = (float("nan"), float("nan"))

    # SHAP-ranked top features for RF (fall back to RF importances if SHAP absent)
    rf_rank = trained["shap_rf_mean_abs"] if trained["has_shap"] else trained["rf_importances_mean"]
    top_rf = _top_features(names, rf_rank, k=10)
    if trained["has_xgb"]:
        xgb_rank = trained["shap_xgb_mean_abs"] if trained["has_shap"] else trained["rf_importances_mean"]
        top_xgb = _top_features(names, xgb_rank, k=10)
    else:
        top_xgb = []

    # Also attach the RF importance beside SHAP for parity/comparison
    for entry in top_rf:
        entry["rf_importance"] = float(trained["rf_importances_mean"][names.index(entry["feature"])])
    for entry in top_xgb:
        entry["rf_importance"] = 0.0  # XGBoost has its own importances; we skip

    top_class = top_rf[0]["feature_class"] if top_rf else "unpredictable"
    pred_class, dom_class = _classify(r2_rf, r2_rf_ci[0], top_class)

    delta_r2 = (r2_rf - r2_xgb) if trained["has_xgb"] else float("nan")
    model_agreement = "single_model"
    if trained["has_xgb"]:
        model_agreement = "concordant" if abs(delta_r2) < 0.1 else "divergent"

    # Lineage-conditional companion (RF-only, per-lineage r² + top feature)
    lineage_results = _fit_lineage_conditional(X, y, mids, omics["model_df"], names)

    elapsed = time.time() - t0
    return {
        "gene_symbol": gene,
        "n_cell_lines_evaluated": int(X.shape[0]),
        "pearson_r_rf": float(r_rf),
        "pearson_r_squared_rf": float(r2_rf),
        "pearson_r_squared_rf_ci_lo": float(r2_rf_ci[0]),
        "pearson_r_squared_rf_ci_hi": float(r2_rf_ci[1]),
        "pearson_r_xgb": float(r_xgb),
        "pearson_r_squared_xgb": float(r2_xgb),
        "pearson_r_squared_xgb_ci_lo": float(r2_xgb_ci[0]),
        "pearson_r_squared_xgb_ci_hi": float(r2_xgb_ci[1]),
        "model_agreement": model_agreement,
        "delta_r2": float(delta_r2) if trained["has_xgb"] else 0.0,
        "top_features_rf_shap": top_rf,
        "top_features_xgb_shap": top_xgb,
        "dominant_feature_class": dom_class,
        "predictability_class": pred_class,
        "per_lineage_predictability": lineage_results,
        "n_features_total": int(X.shape[1]),
        "elapsed_seconds": float(elapsed),
    }


# ---------------------------------------------------------------------------
# Parquet writer
# ---------------------------------------------------------------------------


def write_parquet(records: list, out_path: Path) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = sorted([r for r in records if r and "_error" not in r], key=lambda r: r["gene_symbol"])

    top_struct = pa.struct(
        [
            pa.field("feature", pa.string()),
            pa.field("feature_class", pa.string()),
            pa.field("importance", pa.float32()),
            pa.field("rf_importance", pa.float32()),
        ]
    )
    lineage_struct = pa.struct(
        [
            pa.field("lineage", pa.string()),
            pa.field("n_cell_lines", pa.int32()),
            pa.field("r2", pa.float32()),
            pa.field("top_feature", pa.string()),
        ]
    )
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("n_cell_lines_evaluated", pa.int32()),
            pa.field("pearson_r_rf", pa.float32()),
            pa.field("pearson_r_squared_rf", pa.float32()),
            pa.field("pearson_r_squared_rf_ci_lo", pa.float32()),
            pa.field("pearson_r_squared_rf_ci_hi", pa.float32()),
            pa.field("pearson_r_xgb", pa.float32()),
            pa.field("pearson_r_squared_xgb", pa.float32()),
            pa.field("pearson_r_squared_xgb_ci_lo", pa.float32()),
            pa.field("pearson_r_squared_xgb_ci_hi", pa.float32()),
            pa.field("model_agreement", pa.string()),
            pa.field("delta_r2", pa.float32()),
            pa.field("top_features_rf_shap", pa.list_(top_struct)),
            pa.field("top_features_xgb_shap", pa.list_(top_struct)),
            pa.field("dominant_feature_class", pa.string()),
            pa.field("predictability_class", pa.string()),
            pa.field("per_lineage_predictability", pa.list_(lineage_struct)),
        ]
    )
    columns = {name: [] for name in [f.name for f in schema]}
    for r in rows:
        for name in columns:
            columns[name].append(r.get(name))
    table = pa.Table.from_pydict(columns, schema=schema)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, row_group_size=64, compression="snappy")
    return out_path


# ---------------------------------------------------------------------------
# Gene-set selection (unchanged from v1)
# ---------------------------------------------------------------------------


def build_medium_gene_set(
    chronos_df: pd.DataFrame,
    model_df: pd.DataFrame,
    min_lines_per_lineage: int = 5,
    threshold: float = 0.3,
    priority_order: str = "selective",
) -> list:
    """Select dependency-mappable genes and order them for the training queue.

    Selection: any OncotreeLineage (n_lines ≥ min_lines_per_lineage) has
    |median Chronos| > threshold. This is the "medium scope" of ~3-4k genes
    that carry the biologically-informative predictability signal (rest of the
    genome is mostly non-dependent, R² near zero).

    Ordering (matters because checkpoints land in submission order; earlier
    genes = higher-value results banked first, robust to instance reboots):
      - 'selective' (DEFAULT): max_lineage(|median Chronos|) descending.
        Strongest lineage-selective dependencies first. Best default because
        it prioritizes the same signal that gated inclusion.
      - 'pan_cancer_median': |pan-cancer median Chronos| descending. Highlights
        broadly-essential genes (which are usually less predictable than
        lineage-selective ones, but sometimes carry biomarker signal).
      - 'alpha': alphabetical (legacy behavior). Deterministic but non-informative.
    """
    lineage_map = dict(zip(model_df["ModelID"], model_df["OncotreeLineage"]))
    lineage_groups: dict = {}
    for mid in chronos_df.index:
        lin = lineage_map.get(mid)
        if isinstance(lin, str) and lin:
            lineage_groups.setdefault(lin, []).append(mid)
    # Track max |median| per gene across all qualifying lineages
    gene_max_abs_median: dict = {}
    for lin, mids in lineage_groups.items():
        if len(mids) < min_lines_per_lineage:
            continue
        sub = chronos_df.loc[mids]
        medians = sub.median(axis=0, skipna=True)
        for gene, m in medians.items():
            if pd.notna(m):
                a = abs(float(m))
                if a > threshold:
                    prev = gene_max_abs_median.get(gene, 0.0)
                    if a > prev:
                        gene_max_abs_median[gene] = a
    if not gene_max_abs_median:
        return []
    if priority_order == "selective":
        # Most-selective first: max_lineage(|median|) descending. Ties → alpha.
        return sorted(gene_max_abs_median.keys(), key=lambda g: (-gene_max_abs_median[g], g))
    if priority_order == "pan_cancer_median":
        pan_median = chronos_df.median(axis=0, skipna=True).abs()
        return sorted(gene_max_abs_median.keys(), key=lambda g: (-float(pan_median.get(g, 0.0)), g))
    # 'alpha' fallback
    return sorted(gene_max_abs_median.keys())


# ---------------------------------------------------------------------------
# Worker plumbing for ProcessPoolExecutor
# ---------------------------------------------------------------------------

_WORKER_OMICS = None


def _worker_init_shm(handle):
    """Initialize a worker by attaching to the shared-memory omics bundle.

    Replaces the previous pickle-per-worker load pattern that killed the
    2026-07-02 genome-wide run via OOM (N workers × 5 GB pickle load exceeded
    the 62 GB RAM ceiling at N=16). Attaching to SHM is O(1) in worker count.
    """
    global _WORKER_OMICS
    from . import shared_omics as _shm

    _WORKER_OMICS = _shm.attach_omics_from_shm(handle)


def _worker_train(gene: str) -> Optional[dict]:
    if _WORKER_OMICS is None:
        raise RuntimeError("_WORKER_OMICS not initialized")
    try:
        return train_gene(gene, _WORKER_OMICS)
    except Exception as e:
        return {"gene_symbol": gene, "_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option("--release-pin", default="26q1", show_default=True)
@click.option(
    "--gene-set",
    type=click.Choice(["smoke", "anchor", "medium", "genome", "explicit"]),
    default="medium",
    show_default=True,
)
@click.option(
    "--gene-set-override",
    default=None,
    help="Comma-separated HGNC symbols (used when --gene-set=explicit or appended to smoke).",
)
@click.option(
    "--out",
    required=True,
    type=click.Path(path_type=Path),
    help="Output directory. Writes predictability_per_gene.parquet + checkpoints + run_manifest.json inside.",
)
@click.option("--workers", default=8, show_default=True, type=int)
@click.option(
    "--checkpoint-every", default=25, show_default=True, type=int, help="Write a checkpoint parquet every N genes."
)
@click.option("--min-lines-per-lineage", default=5, show_default=True, type=int)
@click.option("--threshold", default=0.3, show_default=True, type=float)
@click.option(
    "--priority-order",
    type=click.Choice(["selective", "pan_cancer_median", "alpha"]),
    default="selective",
    show_default=True,
    help="Gene training order. 'selective' = strongest lineage-selective "
    "dependencies first (recommended: banks the highest-value results "
    "earliest, so partial-run checkpoints are maximally useful). "
    "'pan_cancer_median' = largest |pan-cancer median| first. "
    "'alpha' = alphabetical (legacy).",
)
@click.option(
    "--resume/--no-resume",
    default=False,
    help="If set, load the most-recent checkpoint parquet from --out and "
    "skip genes already computed. Enables restart-from-crash on the "
    "genome-wide multi-day batch.",
)
def main(
    release_pin,
    gene_set,
    gene_set_override,
    out,
    workers,
    checkpoint_every,
    min_lines_per_lineage,
    threshold,
    priority_order,
    resume,
):
    out = Path(out)
    if out.suffix == ".parquet":
        parquet_path = out
        out_dir = out.parent
    else:
        out_dir = out
        parquet_path = out_dir / "predictability_per_gene.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo("Loading DepMap inputs + external sources...", err=True)
    omics = feat.load_all_omics(min_lines_per_lineage=min_lines_per_lineage)
    click.echo(f"  Chronos: {omics['chronos'].shape}", err=True)
    click.echo(f"  Expression: {omics['expression'].shape}", err=True)
    click.echo(f"  CN: {omics['copy_number'].shape}", err=True)
    click.echo(f"  Mut hotspot: {omics['mut_hotspot'].shape}", err=True)
    click.echo(f"  Mut damaging: {omics['mut_damaging'].shape}", err=True)
    click.echo(f"  Lineage one-hot: {omics['lineage_one_hot'].shape}", err=True)
    click.echo(f"  Arm-level CN: {omics['arm_level_cn'].shape}", err=True)
    click.echo(f"  OncoKB driver flags: {omics['driver_flags'].shape}", err=True)
    # v2.1 additions (may be None if a loader failed)
    for key in (
        "fusion",
        "rppa",
        "ms_proteomics",
        "paralog_dep",
        "mol_signatures",
        "msi_status",
        "sv_matrix",
        "methylation",
        "metabolomics",
    ):
        val = omics.get(key)
        if val is None:
            click.echo(f"  {key}: OMITTED (loader failed)", err=True)
        elif hasattr(val, "shape"):
            click.echo(f"  {key}: {val.shape}", err=True)

    # Gene set
    ANCHOR_10 = ["KRAS", "BRAF", "EGFR", "PIK3CA", "TP53", "MYC", "MDM2", "MCL1", "CDK4", "WRN"]
    if gene_set == "smoke":
        genes = ["KRAS", "TP53", "MYC", "BRAF", "EGFR"]
        if gene_set_override:
            genes = list(dict.fromkeys(genes + [g.strip() for g in gene_set_override.split(",")]))
    elif gene_set == "anchor":
        genes = ANCHOR_10
    elif gene_set == "explicit":
        if not gene_set_override:
            raise click.UsageError("--gene-set=explicit requires --gene-set-override=SYM1,SYM2,...")
        genes = [g.strip() for g in gene_set_override.split(",") if g.strip()]
    elif gene_set == "genome":
        # All CRISPR-covered protein-coding genes. Priority-ordered so the
        # highest-signal genes complete first (partial-run checkpoints are
        # then maximally useful for downstream consumers).
        all_genes = omics["chronos"].columns.tolist()
        if priority_order == "alpha":
            genes = sorted(all_genes)
        else:
            # Rank by max_lineage(|median Chronos|), NaN → 0. Same signal as
            # build_medium_gene_set but without the > threshold cut.
            lineage_map = dict(zip(omics["model_df"]["ModelID"], omics["model_df"]["OncotreeLineage"]))
            gene_score = {g: 0.0 for g in all_genes}
            lineage_groups: dict = {}
            for mid in omics["chronos"].index:
                lin = lineage_map.get(mid)
                if isinstance(lin, str) and lin:
                    lineage_groups.setdefault(lin, []).append(mid)
            for lin, mids in lineage_groups.items():
                if len(mids) < min_lines_per_lineage:
                    continue
                medians = omics["chronos"].loc[mids].median(axis=0, skipna=True)
                for gene, m in medians.items():
                    if pd.notna(m):
                        a = abs(float(m))
                        if a > gene_score.get(gene, 0.0):
                            gene_score[gene] = a
            if priority_order == "pan_cancer_median":
                pan_median = omics["chronos"].median(axis=0, skipna=True).abs()
                genes = sorted(all_genes, key=lambda g: (-float(pan_median.get(g, 0.0)), g))
            else:  # 'selective' default
                genes = sorted(all_genes, key=lambda g: (-gene_score.get(g, 0.0), g))
    else:  # medium
        click.echo(
            f"Building medium-scope gene set "
            f"(any-lineage |median Chronos| > {threshold}, "
            f"priority={priority_order})...",
            err=True,
        )
        genes = build_medium_gene_set(
            omics["chronos"], omics["model_df"], min_lines_per_lineage, threshold, priority_order=priority_order
        )
    click.echo(f"  Gene set size: {len(genes)}", err=True)
    if len(genes) > 0 and priority_order == "selective":
        click.echo(f"  Priority head (top 5 most-selective): {genes[:5]}", err=True)
        click.echo(f"  Priority tail (bottom 5 least-selective): {genes[-5:]}", err=True)

    # Records collected in-process; checkpoints written every N.
    records = []
    n_excluded = 0
    n_errored = 0
    t_start = time.time()

    # === RESUME PATH: load newest checkpoint, drop already-computed genes ===
    if resume:
        import pyarrow.parquet as pq

        ckpts = sorted(out_dir.glob("checkpoint_*.parquet"))
        # Also consider the final parquet if a prior run finished writing it
        if parquet_path.exists():
            ckpts.append(parquet_path)
        if ckpts:
            newest = ckpts[-1]
            click.echo(f"Resume: loading {newest.name}", err=True)
            prev_df = pq.read_table(newest).to_pandas()
            already = set(prev_df["gene_symbol"].tolist())
            click.echo(f"  {len(already)} genes already computed; skipping", err=True)
            # Convert prior parquet rows back to record dicts for downstream write
            for _, prev_row in prev_df.iterrows():
                rec = {}
                for col in prev_df.columns:
                    val = prev_row[col]
                    # Numpy arrays of dicts (top_features, per_lineage) → list
                    if hasattr(val, "tolist") and not isinstance(val, str):
                        val = val.tolist()
                    rec[col] = val
                records.append(rec)
            genes = [g for g in genes if g not in already]
            click.echo(f"  {len(genes)} genes remaining", err=True)
        else:
            click.echo("Resume: no checkpoint found; starting fresh", err=True)

    # Publish omics to POSIX shared memory ONCE. Workers attach by name; there
    # is exactly one physical copy of each numeric matrix in RAM regardless
    # of worker count. Replaces the previous pickle-per-worker pattern that
    # caused an instance OOM crash on 2026-07-02 with 16 workers × 5 GB each.
    from . import shared_omics as _shm

    click.echo("Publishing omics to shared memory...", err=True)
    omics_handle = _shm.publish_omics_to_shm(omics)
    # Drop our local reference to the DataFrames so the arrays we copied into
    # SHM are the only in-RAM copy on the coordinator; frees ~5 GB.
    del omics
    import gc

    gc.collect()
    click.echo(
        f"  {len(omics_handle.frames)} matrices in SHM; "
        f"handle size ≈ {len(omics_handle.extras_pickle) // 1024} KB extras + "
        f"{sum(len(f.index_pickle) + len(f.columns_pickle) for f in omics_handle.frames.values()) // 1024} KB labels",
        err=True,
    )

    try:
        if workers <= 1:
            _worker_init_shm(omics_handle)
            for i, gene in enumerate(genes):
                rec = _worker_train(gene)
                if rec is None:
                    n_excluded += 1
                elif "_error" in rec:
                    n_errored += 1
                    click.echo(f"  [error] {gene}: {rec['_error']}", err=True)
                else:
                    records.append(rec)
                if (i + 1) % checkpoint_every == 0:
                    _write_checkpoint(records, out_dir, i + 1, len(genes), t_start)
                    click.echo(f"  {i + 1}/{len(genes)} done ({time.time() - t_start:.1f}s elapsed)", err=True)
        else:
            # Chunked submission bounds the executor's internal queue (submitting
            # all 18k futures eagerly caused a coordinator-death OOM in the
            # 2026-07-01 run). Chunk = workers × 4, drain to completion between
            # chunks; max_tasks_per_child=50 recycles workers periodically.
            #
            # Workers now attach to SHM instead of unpickling — memory cost is
            # O(1) in worker count, so the 2026-07-02 16-worker OOM cannot recur.
            import multiprocessing as _mp

            ctx = _mp.get_context("spawn")
            chunk_size = max(workers * 4, checkpoint_every)
            total = len(genes)
            processed = 0
            for chunk_start in range(0, total, chunk_size):
                chunk = genes[chunk_start : chunk_start + chunk_size]
                with ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=ctx,
                    initializer=_worker_init_shm,
                    initargs=(omics_handle,),
                    max_tasks_per_child=50,
                ) as ex:
                    futures = {ex.submit(_worker_train, g): g for g in chunk}
                    for fut in as_completed(futures):
                        rec = fut.result()
                        processed += 1
                        if rec is None:
                            n_excluded += 1
                        elif "_error" in rec:
                            n_errored += 1
                            click.echo(f"  [error] {futures[fut]}: {rec['_error']}", err=True)
                        else:
                            records.append(rec)
                        if processed % checkpoint_every == 0:
                            _write_checkpoint(records, out_dir, processed, total, t_start)
                            click.echo(
                                f"  {processed}/{total} done "
                                f"({time.time() - t_start:.1f}s elapsed, "
                                f"n_evaluated={len(records)}, "
                                f"n_excluded={n_excluded}, "
                                f"n_errored={n_errored})",
                                err=True,
                            )
    finally:
        # Free the POSIX shared-memory segments. Idempotent; safe to call even
        # if workers have already exited or the coordinator is crashing.
        omics_handle.unlink_all()

    click.echo(f"Writing final parquet → {parquet_path}", err=True)
    write_parquet(records, parquet_path)

    _prov = _git_provenance()
    run_manifest = {
        "method_id": "depmap-predictability-precompute",
        "method_version": METHOD_VERSION,
        "git_commit": _prov["commit"],
        "git_dirty": _prov["dirty"],
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gene_set_mode": gene_set,
        "n_genes_requested": len(genes),
        "n_genes_evaluated": len([r for r in records if r and "_error" not in r]),
        "n_genes_excluded_low_coverage": n_excluded,
        "n_genes_errored": n_errored,
        "wall_time_seconds": time.time() - t_start,
        "parameters": {
            "min_lines_per_lineage": min_lines_per_lineage,
            "threshold": threshold,
            "priority_order": priority_order,
            "cv_n_splits": CV_N_SPLITS,
            "select_k_best": SELECT_K_BEST,
            "bootstrap_n": BOOTSTRAP_N,
            "lineage_min_lines": LINEAGE_MIN_LINES,
            "rf_n_estimators": 100,
            "rf_max_depth": 8,
            "rf_min_samples_leaf": 5,
            "xgb_n_estimators": 100,
            "xgb_max_depth": 6,
            "xgb_learning_rate": 0.1,
            "random_state": 42,
        },
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2))
    click.echo(f"Done. Manifest → {out_dir / 'run_manifest.json'}", err=True)


def _write_checkpoint(records, out_dir, n_done, n_total, t_start):
    checkpoint = out_dir / f"checkpoint_{n_done:06d}_of_{n_total:06d}.parquet"
    write_parquet(records, checkpoint)


if __name__ == "__main__":
    main()
