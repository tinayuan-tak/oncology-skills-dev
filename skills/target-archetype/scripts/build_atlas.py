#!/usr/bin/env python3
"""Build the FROZEN reference atlas for the target-signature LANDSCAPE companion.

OFFLINE, one-time (re-run only to re-freeze after a validated substrate change). Iterates a corpus of
composed target-profile --full-package runs, vectorises each via archetype_core.claim_features (the SAME
vectoriser the runtime query uses — single source of truth), and freezes:
  feature_order · mu · sd (nan-aware) · X · targets · indications · labels · rule_fingerprints · axis_ref
  · embedding{components (m x d PCA loadings), corpus (n x m coords)} · anchors[{label,target,indication,
  coord}] · meta.

The embedding is a LINEAR PCA projection fit on the z-scored, mean-imputed (missing->0) corpus — the
EXACT transform archetype_core applies to a single query at runtime, so offline == runtime, pure-numpy,
deterministic. Phenotype ANCHORS are curated canonical exemplars (one per drug-target phenotype); a query
is expressed as a convex mixture of the anchors' frozen embedding coords.

Usage:
  python3 build_atlas.py \
      --runs  ~/dev/tumor-presence-audit-2026-08-26/tp_runs_xl \
              ~/dev/tumor-presence-audit-2026-08-26/tp_runs_expansion \
              ~/dev/tumor-presence-audit-2026-08-26/tp_runs_prospective \
      --panel ~/dev/tumor-presence-audit-2026-08-26/tp_panel_xl.tsv \
      --out   ../atlas/atlas.json --emb-dim 16

Governance: labels are PROVISIONAL (panel-derived, partly circular) and back a DESCRIPTIVE, verdict-inert
companion only — NOT a classifier freeze. Anchor labels reuse the archetype vocabulary so the D1 scorecard
consumes the mixture unchanged. Ship n as-is (no silent drop of hard pairs)."""

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import claim_features  # noqa: E402

# curated canonical phenotype anchors (label reuses the archetype vocabulary; exemplar = (target, indication)).
# One well-covered exemplar per drug-target phenotype; the query is a convex mixture of these.
# Curated phenotype anchors — each is the CENTROID of a small exemplar SET (not a single point), so a
# corner no longer pivots on one target's noisy/partial signature. First member is the canonical
# representative (shown in the payload); the anchor coord is the mean of all present members' embeddings.
ANCHOR_SETS = {
    "snv_driver": [("KRAS", "LUAD"), ("BRAF", "COADREAD"), ("NRAS", "COADREAD")],
    "tsg_loss": [("VHL", "KIRC"), ("STK11", "LUAD"), ("PTEN", "COADREAD"), ("RB1", "LUSC")],
    "amp_driver": [("ERBB2", "BRCA"), ("CCND1", "BRCA"), ("MYC", "COADREAD"), ("MET", "LUAD")],
    "expression_surface": [("EPCAM", "COADREAD"), ("CEACAM6", "COADREAD"), ("MSLN", "PAAD"), ("FOLR1", "OV")],
    "dependency_essential": [("AURKA", "BRCA"), ("PLK1", "LUAD"), ("BIRC5", "LUAD"), ("WEE1", "OV")],
    "immune_checkpoint": [("PDCD1", "LUAD"), ("CD28", "BRCA"), ("ICOSLG", "BRCA")],  # immune-synapse set
    "control_housekeeping": [("GAPDH", "LUAD"), ("ACTB", "COADREAD"), ("RPL13A", "OV")],
    # fusion/rearrangement-driver phenotype. Members were LIVE-verified to read `fusion:
    # recurrent_fusion_driver` (strong FUS) in their canonical fusion indication (RET/NSCLC + NTRK1/LUAD
    # were REJECTED — sporadic/absent there). ⚠️ NOT ACTIVATED (kept aspirational; exemplar runs live under
    # a separate tp_runs_fusion corpus, NOT the shipped --runs, so build SKIPS it). WHY DEFERRED: a
    # 2026-09-02 re-freeze that DID activate it regressed the panel — the exemplars correctly land on the
    # anchor (ALK 97%, NTRK1 88%, RET 83%, ROS1 67%), BUT because FUS is ONE sparse feature of 108 and every
    # recurrent-fusion driver is an RTK, the anchor centroid encodes RTK-ness not rearrangement, bleeding
    # spurious fusion mass into non-fusion RTK/surface targets (MET flipped fusion-DOMINANT; ERBB2 35%; EGFR
    # 20%; CLDN18 — not even a kinase — 31%). Activating this cleanly needs the fusion signal made SEPARABLE
    # (e.g. FUS-feature up-weighting in the embedding) first, not just adding exemplars. See
    # project_target_archetype_augment memory.
    "fusion_driver": [("ALK", "LUAD"), ("ROS1", "LUAD"), ("RET", "THCA"), ("FGFR2", "CHOL"), ("NTRK1", "THCA")],
}


def _load_panel(path: Path) -> dict:
    panel = {}
    for line in Path(path).read_text().splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            panel[(parts[0], parts[1])] = parts[2]
    return panel


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(SKILLS_DIR), stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def build(runs_dirs, panel_path: Path, build_date: str, emb_dim: int = 16) -> dict:
    panel = _load_panel(panel_path)
    feats, targets, indications, labels, fingerprints = [], [], [], [], []
    seen = set()
    for runs in runs_dirs:
        for sub_dir in sorted(glob.glob(f"{runs}/*/subskills")):
            run = os.path.dirname(sub_dir)
            nom_f = os.path.join(run, "nomination.json")
            if not os.path.exists(nom_f):
                continue
            nom = json.load(open(nom_f))
            tgt, ind = nom.get("target"), nom.get("indication")
            if (tgt, ind) in seen:
                continue
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
            rules = set()
            for v in (nom.get("sub_verdicts") or {}).values():
                if isinstance(v, dict):
                    rules.update(v.get("fired_rule_ids") or [])
            seen.add((tgt, ind))
            feats.append(feat)
            targets.append(tgt)
            indications.append(ind)
            labels.append(panel.get((tgt, ind), "?"))
            fingerprints.append(sorted(rules))

    # feature_order = union of claim keys measured in >=2 targets (drop all-NaN/singleton columns)
    cand = sorted({k for f in feats for k in f})
    feature_order = [k for k in cand if sum(1 for f in feats if f.get(k) is not None) >= 2]
    dropped = len(cand) - len(feature_order)
    X = [[f.get(k) for k in feature_order] for f in feats]
    Xn = np.array([[np.nan if v is None else v for v in row] for row in X], dtype=float)
    mu = np.nanmean(Xn, axis=0)
    sd = np.nanstd(Xn, axis=0)
    sd = np.where(sd == 0, 1.0, sd)

    # LINEAR embedding: z-score vs mu/sd, mean-impute missing -> 0 (EXACT runtime transform), then PCA.
    from sklearn.decomposition import PCA

    Z = (np.where(np.isnan(Xn), mu, Xn) - mu) / sd  # missing -> mean -> z=0
    m = min(emb_dim, Z.shape[1], Z.shape[0])
    pca = PCA(n_components=m, random_state=0).fit(Z)
    components = pca.components_  # m x d
    corpus_emb = pca.transform(Z)  # n x m

    # anchors: each label's coord = CENTROID (mean embedding) of its present exemplar-set members
    idx_of = {(t, i): r for r, (t, i) in enumerate(zip(targets, indications))}
    anchors = []
    skipped_anchors = []
    for label, members in ANCHOR_SETS.items():
        present = [(t, i) for (t, i) in members if (t, i) in idx_of]
        if not present:
            # An ASPIRATIONAL anchor (its exemplars are not yet in the corpus, e.g. fusion_driver awaiting
            # ALK/ROS1/NTRK-fusion runs) is SKIPPED with a warning rather than aborting the whole build —
            # so the exemplar spec can carry the target panel forward and the anchor activates once its
            # runs land. A wrongly-typo'd exemplar surfaces the same way (empty → skipped + warned).
            skipped_anchors.append(label)
            print(f"WARN: anchor '{label}' skipped — no exemplar members present in corpus: {members}", file=sys.stderr)
            continue
        rows = [idx_of[(t, i)] for (t, i) in present]
        centroid = corpus_emb[rows].mean(axis=0)
        rep_t, rep_i = present[0]  # canonical representative (shown in payload)
        anchors.append(
            {
                "label": label,
                "target": rep_t,
                "indication": rep_i,
                "coord": [round(float(x), 6) for x in centroid],
                "members": [[t, i] for (t, i) in present],
                "n_members": len(present),
            }
        )

    # axis_ref (D1 scorecard z-ref): per-axis corpus mean/std of axis_score (nan-mean of ::signal tiers)
    sig_idx = [j for j, k in enumerate(feature_order) if k.endswith("::signal")]
    axis_of = {j: feature_order[j].split("::")[0] for j in sig_idx}
    axes = sorted(set(axis_of.values()))
    axis_scores = np.full((len(feats), len(axes)), np.nan)
    for r in range(len(feats)):
        for a_i, ax in enumerate(axes):
            vals = [Xn[r, j] for j in sig_idx if axis_of[j] == ax and not np.isnan(Xn[r, j])]
            if vals:
                axis_scores[r, a_i] = float(np.mean(vals))
    ax_mean = np.nanmean(axis_scores, axis=0)
    ax_std = np.nanstd(axis_scores, axis=0)
    ax_std = np.where((ax_std == 0) | np.isnan(ax_std), 1.0, ax_std)
    axis_ref = {
        axes[j]: {"mean": round(float(ax_mean[j]), 6), "std": round(float(ax_std[j]), 6)} for j in range(len(axes))
    }

    doc = {
        "feature_order": feature_order,
        "mu": [round(float(x), 6) for x in mu],
        "sd": [round(float(x), 6) for x in sd],
        "X": X,
        "targets": targets,
        "indications": indications,
        "labels": labels,
        "rule_fingerprints": fingerprints,
        "axis_ref": axis_ref,
        "embedding": {
            "kind": "pca_linear_on_zscored_mean_imputed",
            "dim": int(m),
            "components": [[round(float(x), 6) for x in row] for row in components],
            "explained_variance_ratio": [round(float(x), 5) for x in pca.explained_variance_ratio_],
            "corpus": [[round(float(x), 6) for x in row] for row in corpus_emb],
        },
        "anchors": anchors,
        "meta": {
            "n_targets": len(targets),
            "n_features": len(feature_order),
            "n_features_dropped_sparse": dropped,
            "emb_dim": int(m),
            "classes": sorted(set(labels)),
            "anchor_phenotypes": [a["label"] for a in anchors],
            "anchor_phenotypes_skipped": skipped_anchors,  # aspirational anchors awaiting exemplar runs
            "corpus": "+".join(os.path.basename(str(r)) for r in runs_dirs),
            "build_date": build_date,
            "build_git_sha": _git_sha(),
            "vectoriser": "archetype_core.claim_features (corroboration low/mod/high fixed)",
            "note": (
                "DESCRIPTIVE phenotype-landscape atlas; provisional partly-circular panel labels; NOT "
                "a classifier freeze. Anchored convex mixture over curated canonical exemplars. The "
                "former outcome/approval-propensity (D2/D3) score was RETIRED."
            ),
        },
    }
    # soft_labels: the anchored-mixture DOMINANT phenotype for EVERY corpus target — a data-derived
    # display label so nearest-analogs read meaningfully even where the curated panel label is "?"
    # (106/213 unlabeled). Descriptive only; the curated `labels` field is left untouched.
    from _skills_common.archetype_core import Atlas  # noqa: E402  (reuse the runtime membership solver)

    _a = Atlas(doc)
    soft = []
    for e in _a.corpus_emb:
        votes, _hull, _recon = _a._membership(e)
        soft.append(max(votes, key=votes.get) if votes else "?")
    doc["soft_labels"] = soft
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, nargs="+", help="one or more target-profile run dirs")
    ap.add_argument("--panel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--emb-dim", type=int, default=16)
    ap.add_argument("--build-date", default=os.environ.get("ATLAS_BUILD_DATE", "unknown"))
    a = ap.parse_args()
    doc = build([Path(r).expanduser() for r in a.runs], Path(a.panel).expanduser(), a.build_date, a.emb_dim)
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=False))
    m = doc["meta"]
    print(
        f"wrote {out}  n_targets={m['n_targets']} n_features={m['n_features']} emb_dim={m['emb_dim']} "
        f"anchors={m['anchor_phenotypes']}"
    )


if __name__ == "__main__":
    main()
