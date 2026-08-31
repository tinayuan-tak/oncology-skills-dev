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
  NOTE: the default --labels point at frozen snapshot fixtures (tests/fixtures/*, see PROVENANCE.md);
  for a production run against current data, pass a freshly-derived --labels CSV.
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

# Coherence-QC HEADS: each predicts an orthogonal external biological label from the signature with the
# label-defining (de-circularizing) axis REMOVED, then flags targets whose signature disagrees. Each head
# is a binary recover: pos vs everything-else. Add a head by ingesting its label + naming its drop axis.
HEADS = {
    "role": {  # OncoKB oncogene-vs-TSG; de-circ by removing the OncoKB-fed genomic axis
        "drop_axis": DECIRC_DROP_AXIS, "csv_col": "role", "pos": "oncogene", "neg": "tsg",
        "label_field": "oncokb_role", "pred_field": "pred_role", "prob_field": "pred_prob_oncogene",
        "default_csv": "oncokb_roles.csv",
        "decirc_note": f"removed '{DECIRC_DROP_AXIS}' axis (OncoKB-fed)",
        "label_name": "OncoKB role",
    },
    "surface": {  # CSPA wet-lab surface confirmation; de-circ by removing the surface-modality axis
        "drop_axis": "surface_modality", "csv_col": "surface", "pos": "yes", "neg": "no",
        "label_field": "cspa_surface", "pred_field": "pred_surface", "prob_field": "pred_prob_surface",
        "default_csv": "cspa_surface.csv",
        "decirc_note": "removed 'surface_modality' axis (CSPA/surface-fed)",
        "label_name": "CSPA surface confirmation",
    },
}


def _load_labels(path: str, col: str, pos: str, neg: str) -> dict:
    out = {}
    for row in csv.DictReader(open(path)):
        v = (row.get(col) or "").strip().lower()
        if v in (pos, neg):
            out[row["target"].strip()] = v
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


def coherence_report(atlas: ac.Atlas, label_map: dict, head: str = "role") -> tuple:
    """Pure, testable core for any HEAD. Predict the head's external label from the signature with the
    head's de-circularizing axis REMOVED (leave-one-TARGET-out), then per labeled (target,indication):
    the head's label_field, prob_field, pred_field + agree. summary: n, auc, accuracy, majority_baseline,
    n_disagree, de_circularized. Row field NAMES are per-head (role keeps its landed schema)."""
    h = HEADS[head]
    drop, pos, neg = h["drop_axis"], h["pos"], h["neg"]
    dc_cols = [j for j, k in enumerate(atlas.feature_order) if k.split("::")[0] != drop]
    idx, y, groups, meta = [], [], [], []
    for i, (t, ind) in enumerate(zip(atlas.targets, atlas.indications)):
        v = label_map.get(t)
        if v is None:
            continue
        idx.append(i); y.append(1 if v == pos else 0); groups.append(t); meta.append((t, ind, v))
    if len(idx) < 6:
        return [], {"n": len(idx), "note": "too few labeled targets"}
    X = np.array([[atlas.X[i][j] for j in dc_cols] for i in idx], float)
    col_mean = np.nanmean(X, 0); col_mean = np.where(np.isnan(col_mean), 0.0, col_mean)
    X = np.where(np.isnan(X), col_mean, X)                 # mean-impute (missing -> corpus mean)
    oof = _logistic_loto(X, y, groups)
    ok = ~np.isnan(oof)
    auc = _auc(np.array(y)[ok], oof[ok])
    rows = []
    for k, (t, ind, v) in enumerate(meta):
        if np.isnan(oof[k]):
            continue
        p = float(oof[k]); pred = pos if p >= 0.5 else neg
        rows.append({"target": t, "indication": ind, h["label_field"]: v,
                     h["prob_field"]: round(p, 3), h["pred_field"]: pred, "agree": pred == v})
    yv = np.array(y)[ok]
    acc = float(np.mean([(oof[k] >= 0.5) == (y[k] == 1) for k in range(len(y)) if ok[k]]))
    summary = {"n": len(rows), "head": head, "auc": round(auc, 3), "accuracy": round(acc, 3),
               "majority_baseline": round(max(yv.mean(), 1 - yv.mean()), 3),
               "n_disagree": sum(1 for r in rows if not r["agree"]),
               "de_circularized": h["decirc_note"]}
    return rows, summary


# ---- dependency-predictability ANNOTATION (not a de-circ recovery head) --------------------------------
# The DepMap-predictability product already answers "is this gene's dependency omics-EXPLAINABLE?" (an
# external model recovering dependency from omics). We ANNOTATE each atlas target with that external call
# rather than re-predict it — surfacing the ~minority whose dependency is feature-explainable (and the
# dominant feature class), verdict-inert context for the dependency axis.
_PREDICTABLE_CLASSES = {"weakly_predictable", "own_omics_driven", "context_or_driver_dependent"}


def _load_predictability(path: str) -> dict:
    out = {}
    for row in csv.DictReader(open(path)):
        cls = (row.get("predictability_class") or "").strip()
        if cls and cls != "not_evaluated":
            out[row["target"].strip()] = {"predictability_class": cls,
                                          "r2_rf": row.get("r2_rf", ""),
                                          "dominant_feature_class": row.get("dominant_feature_class", "")}
    return out


def dependency_predictability_report(atlas: ac.Atlas, pred_map: dict) -> tuple:
    """Annotate each atlas target with the external DepMap-predictability call (is its dependency
    omics-explainable, r², dominant feature class). Pure/testable. Returns (rows, summary)."""
    rows = []
    seen = set()
    for t, ind in zip(atlas.targets, atlas.indications):
        p = pred_map.get(t)
        if p is None or (t, ind) in seen:
            continue
        seen.add((t, ind))
        rows.append({"target": t, "indication": ind,
                     "predictability_class": p["predictability_class"], "r2_rf": p.get("r2_rf", ""),
                     "dominant_feature_class": p.get("dominant_feature_class", ""),
                     "explainable": p["predictability_class"] in _PREDICTABLE_CLASSES})
    n = len(rows); n_ex = sum(1 for r in rows if r["explainable"])
    from collections import Counter
    summary = {"n_evaluated": n, "n_explainable": n_ex,
               "explainable_fraction": round(n_ex / n, 3) if n else 0.0,
               "class_distribution": dict(Counter(r["predictability_class"] for r in rows)),
               "note": "external DepMap-predictability annotation (verdict-inert); most dependencies are "
                       "NOT omics-explainable — the explainable minority is the useful signal."}
    return rows, summary


def main():
    ap = argparse.ArgumentParser(description="biological-recovery coherence-QC (verdict-inert, offline)")
    ap.add_argument("--head", choices=sorted(list(HEADS) + ["dependency"]), default="role")
    ap.add_argument("--atlas", default=str(Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"))
    ap.add_argument("--labels", default=None, help="label CSV (default: the head's fixture)")
    ap.add_argument("--roles", default=None, help="[deprecated alias for --labels on the role head]")
    ap.add_argument("--out-csv", default=None)
    a = ap.parse_args()
    fx = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    atlas = ac.Atlas.load(a.atlas)

    if a.head == "dependency":     # ANNOTATION path (external predictability call, not a de-circ classifier)
        labels_path = a.labels or str(fx / "depmap_predictability.csv")
        rows, summary = dependency_predictability_report(atlas, _load_predictability(labels_path))
        out_csv = a.out_csv or "dependency_predictability.csv"
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["target", "indication", "predictability_class", "r2_rf",
                                              "dominant_feature_class", "explainable"])
            w.writeheader(); w.writerows(rows)
        print(f"dependency-predictability annotation: {summary}")
        ex = sorted((r for r in rows if r["explainable"]),
                    key=lambda x: float(x["r2_rf"] or 0), reverse=True)[:15]
        print(f"\nEXPLAINABLE dependencies (omics-predictable — the useful minority): {summary['n_explainable']}")
        for r in ex:
            print(f"  {r['target']}/{r['indication']}: {r['predictability_class']} "
                  f"(r2={r['r2_rf']}, via {r['dominant_feature_class']})")
        print(f"\nwrote {out_csv}")
        return

    h = HEADS[a.head]              # de-circ recovery-and-flag path (role / surface)
    labels_path = a.labels or a.roles or str(fx / h["default_csv"])
    rows, summary = coherence_report(atlas, _load_labels(labels_path, h["csv_col"], h["pos"], h["neg"]), a.head)
    out_csv = a.out_csv or f"{a.head}_coherence.csv"
    fields = ["target", "indication", h["label_field"], h["prob_field"], h["pred_field"], "agree"]
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    print(f"{a.head}-recovery coherence-QC (de-circularized): {summary}")
    disagree = [r for r in rows if not r["agree"]]
    print(f"\nINCOHERENT (signature disagrees with {h['label_name']} — REVIEW, not an auto-edit): {len(disagree)}")
    for r in sorted(disagree, key=lambda x: abs(x[h["prob_field"]] - 0.5), reverse=True)[:15]:
        print(f"  {r['target']}/{r['indication']}: {h['label_name']}={r[h['label_field']]} "
              f"signature->{r[h['pred_field']]} (p={r[h['prob_field']]})")
    print(f"\nwrote {out_csv}")


if __name__ == "__main__":
    main()
