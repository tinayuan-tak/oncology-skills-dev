#!/usr/bin/env python3
"""Biological-recovery COHERENCE-QC (offline / analysis tool) — role-recovery head (Stage 1).

Tests whether the target-signature RECOVERS an orthogonal, externally-labelled biological property, and
flags targets whose signature DISAGREES with the external label (a card bug, a mislabel, or genuinely
novel biology — a review queue, never an automated edit). DESCRIPTIVE / verdict-inert.

Role head: predict OncoKB oncogene-vs-TSG role from the signature with the OncoKB-fed GENOMIC axis REMOVED
(de-circularized — the P3 tier-C test), leave-one-TARGET-out. If de-circ biology recovers role, the
predictor is real (not re-reading the label). Then per labeled target: predicted role vs OncoKB role →
AGREE / DISAGREE (incoherent). Pure-numpy (no sklearn) so it runs anywhere the skills tests run.

Usage:
  python3 coherence_qc.py --atlas ../atlas/atlas.json --roles tests/fixtures/oncokb_roles.csv \
      [--out-csv role_coherence.csv]
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common import archetype_core as ac  # noqa: E402

DECIRC_DROP_AXIS = "genomic_alteration"   # the OncoKB-fed axis — removed to de-circularize the role head


def _load_roles(path: str) -> dict:
    out = {}
    for row in csv.DictReader(open(path)):
        r = (row.get("role") or "").strip().lower()
        if r in ("oncogene", "tsg"):
            out[row["target"].strip()] = r
    return out


def _logistic_loto(X, y, groups, l2=1.0, iters=300, lr=0.5):
    """Pure-numpy L2 logistic, leave-one-TARGET-out OOF probabilities. Deterministic."""
    X = np.asarray(X, float); y = np.asarray(y, float); groups = np.asarray(groups)
    n, d = X.shape
    oof = np.full(n, np.nan)
    for g in np.unique(groups):
        te = groups == g; tr = ~te
        if tr.sum() < 3 or len(np.unique(y[tr])) < 2:
            continue
        Xtr = X[tr]; ytr = y[tr]
        mu = Xtr.mean(0); sd = Xtr.std(0); sd[sd == 0] = 1.0
        Ztr = (Xtr - mu) / sd
        Zte = (X[te] - mu) / sd
        w = np.zeros(d); b = 0.0
        for _ in range(iters):
            p = 1.0 / (1.0 + np.exp(-(Ztr @ w + b)))
            gw = Ztr.T @ (p - ytr) / len(ytr) + l2 * w / len(ytr)
            gb = float((p - ytr).mean())
            w -= lr * gw; b -= lr * gb
        oof[te] = 1.0 / (1.0 + np.exp(-(Zte @ w + b)))
    return oof


def _auc(y, p):
    y = np.asarray(y); p = np.asarray(p)
    pos = p[y == 1]; neg = p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), float); ranks[order] = np.arange(1, len(order) + 1)
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def coherence_report(atlas: ac.Atlas, role_map: dict) -> tuple:
    """Pure, testable core. Returns (rows, summary). rows: per labeled (target,indication) — oncokb_role,
    pred_prob_oncogene, pred_role, agree. summary: n, auc, accuracy, majority_baseline, n_disagree."""
    dc_cols = [j for j, k in enumerate(atlas.feature_order) if k.split("::")[0] != DECIRC_DROP_AXIS]
    idx, y, groups, meta = [], [], [], []
    for i, (t, ind) in enumerate(zip(atlas.targets, atlas.indications)):
        r = role_map.get(t)
        if r is None:
            continue
        idx.append(i); y.append(1 if r == "oncogene" else 0); groups.append(t); meta.append((t, ind, r))
    if len(idx) < 6:
        return [], {"n": len(idx), "note": "too few labeled targets"}
    X = np.array([[atlas.X[i][j] for j in dc_cols] for i in idx], float)
    col_mean = np.nanmean(X, 0); col_mean = np.where(np.isnan(col_mean), 0.0, col_mean)
    X = np.where(np.isnan(X), col_mean, X)                 # mean-impute (missing -> corpus mean)
    oof = _logistic_loto(X, y, groups)
    ok = ~np.isnan(oof)
    auc = _auc(np.array(y)[ok], oof[ok])
    rows = []
    for k, (t, ind, r) in enumerate(meta):
        if np.isnan(oof[k]):
            continue
        p = float(oof[k]); pred = "oncogene" if p >= 0.5 else "tsg"
        rows.append({"target": t, "indication": ind, "oncokb_role": r,
                     "pred_prob_oncogene": round(p, 3), "pred_role": pred, "agree": pred == r})
    yv = np.array(y)[ok]
    acc = float(np.mean([(oof[k] >= 0.5) == (y[k] == 1) for k in range(len(y)) if ok[k]]))
    summary = {"n": len(rows), "auc": round(auc, 3), "accuracy": round(acc, 3),
               "majority_baseline": round(max(yv.mean(), 1 - yv.mean()), 3),
               "n_disagree": sum(1 for r in rows if not r["agree"]),
               "de_circularized": f"removed '{DECIRC_DROP_AXIS}' axis (OncoKB-fed)"}
    return rows, summary


def main():
    ap = argparse.ArgumentParser(description="role-recovery coherence-QC (verdict-inert, offline)")
    ap.add_argument("--atlas", default=str(Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"))
    ap.add_argument("--roles", default=str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" /
                                           "oncokb_roles.csv"))
    ap.add_argument("--out-csv", default="role_coherence.csv")
    a = ap.parse_args()
    atlas = ac.Atlas.load(a.atlas)
    rows, summary = coherence_report(atlas, _load_roles(a.roles))
    with open(a.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["target", "indication", "oncokb_role", "pred_prob_oncogene",
                                          "pred_role", "agree"])
        w.writeheader(); w.writerows(rows)
    print(f"role-recovery coherence-QC (de-circularized): {summary}")
    disagree = [r for r in rows if not r["agree"]]
    print(f"\nINCOHERENT (signature disagrees with OncoKB role — REVIEW, not an auto-edit): {len(disagree)}")
    for r in sorted(disagree, key=lambda x: abs(x["pred_prob_oncogene"] - 0.5), reverse=True)[:15]:
        print(f"  {r['target']}/{r['indication']}: OncoKB={r['oncokb_role']} "
              f"signature->{r['pred_role']} (p_oncogene={r['pred_prob_oncogene']})")
    print(f"\nwrote {a.out_csv}")


if __name__ == "__main__":
    main()
