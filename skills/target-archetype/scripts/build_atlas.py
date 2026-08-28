#!/usr/bin/env python3
"""Build the FROZEN reference atlas for the target-archetype companion.

OFFLINE, one-time (re-run only to re-freeze after a validated substrate change). Iterates a corpus of
composed target-profile --full-package runs, vectorises each via archetype_core.claim_features (the SAME
vectoriser the runtime query uses — single source of truth), and writes atlas.json:
  feature_order · mu · sd (nan-aware) · X (n x d, null=unmeasured) · targets · indications · labels ·
  rule_fingerprints · meta(provenance: corpus, n, build code + git sha, source runs dir).

Usage:
  python3 build_atlas.py \
      --runs   ~/dev/tumor-presence-audit-2026-08-26/tp_runs_xl \
      --panel  ~/dev/tumor-presence-audit-2026-08-26/tp_panel_xl.tsv \
      --out    ../atlas/atlas.json

Governance: labels are PROVISIONAL (partly circular). This atlas backs a DESCRIPTIVE, verdict-inert
companion only — NOT a classifier freeze. Ship n as-is (no silent drop of hard/mislabelled pairs)."""
import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parents[2]        # .../skills
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import claim_features  # noqa: E402


def _load_panel(path: Path) -> dict:
    panel = {}
    for line in Path(path).read_text().splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            panel[(parts[0], parts[1])] = parts[2]
    return panel


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(SKILLS_DIR),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def _train_d2(feats, targets, feature_order, outcome_labels_path) -> dict:
    """Train the FROZEN D2 predictive-score model = a de-FAMEd logistic on OT approval outcome. We ship the
    COEFFICIENTS (data, not a pickle) so the runtime is pure-numpy + deterministic; the linear model's
    additive structure gives the D2 score AND the D3 per-axis attribution in one computation. De-FAMEd:
    the target_intrinsic axis (a notoriety/centrality proxy — see the FAME-confound ablation) is EXCLUDED,
    so the shipped score reflects disease biology, not gene fame."""
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
    from sklearn.metrics import roc_auc_score, brier_score_loss

    lab = pd.read_csv(outcome_labels_path)
    appr = {t: bool(a) for t, a in zip(lab["target"], lab["ot_is_approved"].fillna(False))}
    d2_feats = [k for k in feature_order if not k.startswith("target_intrinsic::")]   # DE-FAME
    Xn = np.array([[np.nan if f.get(k) is None else f.get(k) for k in d2_feats] for f in feats], float)
    y = np.array([1 if appr.get(t) else 0 for t in targets], int)
    mean = np.nanmean(Xn, axis=0); std = np.nanstd(Xn, axis=0); std = np.where(std == 0, 1.0, std)
    Z = (np.where(np.isnan(Xn), mean, Xn) - mean) / std      # mean-impute then z (missing -> z=0)
    clf = LogisticRegression(max_iter=2000, C=0.5).fit(Z, y)
    groups = np.array(targets)
    oof = cross_val_predict(LogisticRegression(max_iter=2000, C=0.5), Z, y,
                            cv=LeaveOneGroupOut(), groups=groups, method="predict_proba")[:, 1]
    return {
        "feature_order": d2_feats,
        "coef": [round(float(c), 6) for c in clf.coef_[0]],
        "intercept": round(float(clf.intercept_[0]), 6),
        "mean": [round(float(m), 6) for m in mean],
        "std": [round(float(s), 6) for s in std],
        "target_label": "ot_is_approved",
        "de_famed": True,
        "provenance": {
            "model": "logistic C=0.5, de-FAMEd (target_intrinsic axis excluded)",
            "loto_auc": round(float(roc_auc_score(y, oof)), 3),
            "loto_brier": round(float(brier_score_loss(y, oof)), 3),
            "n_train": int(len(y)), "n_positive": int(y.sum()),
            "note": ("outcome-trained predictive companion; VERDICT-INERT; report as biology-predicted "
                     "clinical-advancement PROPENSITY, not P(success). FAME confound bounded (target_intrinsic "
                     "excluded). Coefficients are DATA (no pickle); runtime is pure-numpy + deterministic."),
        },
    }


def build(runs: Path, panel_path: Path, build_date: str, outcome_labels: Path = None) -> dict:
    panel = _load_panel(panel_path)
    feats, targets, indications, labels, fingerprints = [], [], [], [], []
    for sub_dir in sorted(glob.glob(f"{runs}/*/subskills")):
        run = os.path.dirname(sub_dir)
        nom_f = os.path.join(run, "nomination.json")
        if not os.path.exists(nom_f):
            continue
        nom = json.load(open(nom_f))
        tgt, ind = nom.get("target"), nom.get("indication")
        cvs = {}
        for pkg in glob.glob(f"{sub_dir}/*/package.json"):
            d = json.load(open(pkg))
            short = d.get("sub_skill") or os.path.basename(os.path.dirname(pkg))
            cv = d.get("claim_vector")
            if isinstance(cv, dict) and cv:
                cvs[short] = cv
        feat = claim_features(cvs)
        if not feat:
            continue
        # rule fingerprint from nomination sub_verdicts (the auditable fired-rule signature)
        rules = set()
        for v in (nom.get("sub_verdicts") or {}).values():
            if isinstance(v, dict):
                rules.update(v.get("fired_rule_ids") or [])
        feats.append(feat)
        targets.append(tgt)
        indications.append(ind)
        labels.append(panel.get((tgt, ind), "?"))
        fingerprints.append(sorted(rules))

    # candidate features = union of all claim keys; DROP columns measured in <2 targets (all-NaN /
    # singleton columns carry no cross-target signal and produce a NaN mean that would poison z-scoring).
    cand = sorted({k for f in feats for k in f})
    min_measured = 2
    feature_order = [k for k in cand
                     if sum(1 for f in feats if f.get(k) is not None) >= min_measured]
    dropped = len(cand) - len(feature_order)
    X = [[f.get(k) for k in feature_order] for f in feats]
    Xn = np.array([[np.nan if v is None else v for v in row] for row in X], dtype=float)
    mu = np.nanmean(Xn, axis=0)
    sd = np.nanstd(Xn, axis=0)
    sd = np.where(sd == 0, 1.0, sd)

    # AXIS reference stats for the D1 nomination scorecard: per target, axis_score = nan-mean of that
    # axis's ::signal claim features; then store the corpus mean/std of axis_score per axis (for z-scoring
    # a query's axis position at runtime). SIGNAL tiers only (not corrob) — the decision-relevant signal.
    sig_idx = [i for i, k in enumerate(feature_order) if k.endswith("::signal")]
    axis_of = {i: feature_order[i].split("::")[0] for i in sig_idx}
    axes = sorted(set(axis_of.values()))
    axis_scores = np.full((len(feats), len(axes)), np.nan)
    for r in range(len(feats)):
        for a_i, ax in enumerate(axes):
            vals = [Xn[r, i] for i in sig_idx if axis_of[i] == ax and not np.isnan(Xn[r, i])]
            if vals:
                axis_scores[r, a_i] = float(np.mean(vals))
    ax_mean = np.nanmean(axis_scores, axis=0)
    ax_std = np.nanstd(axis_scores, axis=0)
    ax_std = np.where((ax_std == 0) | np.isnan(ax_std), 1.0, ax_std)
    axis_ref = {axes[j]: {"mean": round(float(ax_mean[j]), 6), "std": round(float(ax_std[j]), 6)}
                for j in range(len(axes))}

    return {
        "feature_order": feature_order,
        "mu": [round(float(x), 6) for x in mu],
        "sd": [round(float(x), 6) for x in sd],
        "X": X,
        "targets": targets,
        "indications": indications,
        "labels": labels,
        "rule_fingerprints": fingerprints,
        "axis_ref": axis_ref,               # per-axis corpus mean/std of axis_score (D1 scorecard z-ref)
        "d2_model": (_train_d2(feats, targets, feature_order, outcome_labels) if outcome_labels else None),
        "meta": {
            "n_targets": len(targets),
            "n_features": len(feature_order),
            "n_features_dropped_sparse": dropped,
            "min_measured_per_feature": min_measured,
            "classes": sorted(set(labels)),
            "corpus": os.path.basename(str(runs)),
            "build_date": build_date,
            "build_git_sha": _git_sha(),
            "vectoriser": "archetype_core.claim_features",
            "note": ("DESCRIPTIVE companion atlas; provisional partly-circular labels; not a classifier "
                     "freeze; housekeeping not a distinct archetype; amp_driver small-n."),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--build-date", default=os.environ.get("ATLAS_BUILD_DATE", "unknown"),
                    help="stamp explicitly (Date.now is unavailable in some harnesses)")
    ap.add_argument("--outcome-labels", default=None,
                    help="CSV with target,ot_is_approved to train + embed the frozen D2 logistic (optional)")
    a = ap.parse_args()
    doc = build(Path(a.runs).expanduser(), Path(a.panel).expanduser(), a.build_date,
                outcome_labels=Path(a.outcome_labels).expanduser() if a.outcome_labels else None)
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=False))
    m = doc["meta"]
    print(f"wrote {out}  n_targets={m['n_targets']} n_features={m['n_features']} classes={m['classes']}")


if __name__ == "__main__":
    main()
