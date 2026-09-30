#!/usr/bin/env python3
"""Portfolio-scale target-signature LANDSCAPE painter (offline / analysis tool).

Reuses the FROZEN atlas + the shipped `archetype_core` companion to paint the whole reference corpus (or an
ingested set of new --package-dir runs) as a portfolio: a per-target PHENOTYPE table (dominant phenotype +
soft mixture + novelty + coverage + nearest analog) and a 2D map painted by dominant phenotype with the
anchors marked. DESCRIPTIVE / verdict-inert — a whitespace / orientation view, never a gate.

Usage:
  python3 paint_landscape.py --atlas ../atlas/atlas.json \
      [--package-dir <full-package-run> ...]   # optional: add new (target,indication) runs to the map
      [--out-csv portfolio_landscape.csv] [--out-png portfolio_landscape.png]

`portfolio_table(atlas, extra=None)` is the pure, testable core (no matplotlib); the PNG is best-effort.
"""

import argparse
import glob
import json
import os
from pathlib import Path

from _skills_common import archetype_core as ac  # noqa: E402

# anchor-phenotype -> colour (dataviz categorical palette), reused for the painted map
PHENO_COLOR = {
    "snv_driver": "#e34948",
    "tsg_loss": "#4a3aa7",
    "amp_driver": "#eda100",
    "expression_surface": "#2a78d6",
    "dependency_essential": "#1baf7a",
    "control_housekeeping": "#52514e",
}


def _feat_of_row(atlas: ac.Atlas, i: int) -> dict:
    return {k: v for k, v in zip(atlas.feature_order, atlas.X[i]) if v is not None}


def _feat_from_package_dir(pkg_dir: str) -> "tuple[str, str, dict]":
    """Vectorise an existing --full-package run tree into (target, indication, feat)."""
    nom = json.load(open(os.path.join(pkg_dir, "nomination.json")))
    cvs = {}
    for pk in glob.glob(f"{pkg_dir}/subskills/*/package.json"):
        d = json.load(open(pk))
        cv = d.get("claim_vector")
        if isinstance(cv, dict) and cv:
            cvs[d.get("sub_skill") or os.path.basename(os.path.dirname(pk))] = cv
    return nom.get("target"), nom.get("indication"), ac.claim_features(cvs)


def portfolio_table(atlas: ac.Atlas, extra=None) -> list:
    """Pure core: per (target,indication), the dominant phenotype + soft mixture + novelty + coverage +
    nearest analog. `extra` = optional list of (target, indication, feat) for new targets. Testable."""
    rows = []
    items = [(atlas.targets[i], atlas.indications[i], _feat_of_row(atlas, i)) for i in range(len(atlas.targets))]
    items += list(extra or [])
    for tgt, ind, feat in items:
        c = atlas.companion(feat, k=3)
        mix = c.get("phenotype_mixture") or {}
        dom = max(mix, key=mix.get) if mix else None
        nov = c.get("novelty") or {}
        miss = c.get("missingness") or {}
        analog = (c.get("nearest_analogs") or [{}])[0]
        rows.append(
            {
                "target": tgt,
                "indication": ind,
                "dominant_phenotype": dom,
                "mixture": mix,
                "inconsistent": bool(nov.get("inconsistent_flag")),
                "local_outlier": bool(nov.get("local_density_flag")),
                "hull_residual": nov.get("hull_residual"),
                "coverage": round((miss.get("n_features_measured") or 0) / (miss.get("n_features_total") or 1), 3),
                "nearest_analog": analog.get("target"),
            }
        )
    return rows


def _write_csv(rows: list, path: str):
    import csv

    labels = sorted({k for r in rows for k in r["mixture"]})
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "target",
                "indication",
                "dominant_phenotype",
                "coverage",
                "inconsistent",
                "local_outlier",
                "hull_residual",
                "nearest_analog",
            ]
            + [f"m_{l}" for l in labels]
        )
        for r in rows:
            w.writerow(
                [
                    r["target"],
                    r["indication"],
                    r["dominant_phenotype"],
                    r["coverage"],
                    r["inconsistent"],
                    r["local_outlier"],
                    r["hull_residual"],
                    r["nearest_analog"],
                ]
                + [round(r["mixture"].get(l, 0.0), 3) for l in labels]
            )


def _paint_png(atlas: ac.Atlas, rows: list, path: str):
    """Best-effort 2D map: PCA(2) of the frozen corpus embedding, painted by dominant phenotype; anchors
    ringed. Only the corpus points (with frozen coords) are plotted; extra targets are in the CSV."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    E = np.array(atlas.corpus_emb, float)
    if E.shape[0] < 3 or E.shape[1] < 2:
        return
    # the frozen embedding is PCA-ordered (components are PCA loadings), so columns 0,1 ARE the top-2 PCs —
    # no re-fit needed (keeps this tool numpy+matplotlib-only, no sklearn dependency).
    xy = E[:, :2]
    dom = [r["dominant_phenotype"] for r in rows[: len(atlas.targets)]]
    SURF, INK = "#fcfcfb", "#0b0b0b"
    fig, ax = plt.subplots(figsize=(9, 7), facecolor=SURF)
    ax.set_facecolor(SURF)
    for s in ax.spines.values():
        s.set_visible(False)
    seen = set()
    for i in range(len(atlas.targets)):
        c = PHENO_COLOR.get(dom[i], "#b0b0a8")
        lab = dom[i] if dom[i] not in seen else None
        seen.add(dom[i])
        ax.scatter(xy[i, 0], xy[i, 1], s=38, c=c, alpha=0.75, linewidths=0, label=lab)
    anchor_idx = {(a["target"], a["indication"]): a["label"] for a in atlas.anchors}
    for i in range(len(atlas.targets)):
        key = (atlas.targets[i], atlas.indications[i])
        if key in anchor_idx:
            ax.scatter(
                xy[i, 0],
                xy[i, 1],
                s=230,
                facecolor=PHENO_COLOR.get(anchor_idx[key], "#000"),
                edgecolor=INK,
                linewidths=1.8,
                zorder=5,
            )
            ax.annotate(
                atlas.targets[i],
                xy[i],
                fontsize=9,
                fontweight="bold",
                color=INK,
                xytext=(6, 5),
                textcoords="offset points",
                zorder=6,
            )
    ax.set_title(
        f"Target-signature portfolio landscape (n={len(atlas.targets)}; anchors ringed)",
        color=INK,
        fontsize=12,
        loc="left",
    )
    ax.set_xlabel("embed-1", color="#52514e", fontsize=9)
    ax.set_ylabel("embed-2", color="#52514e", fontsize=9)
    ax.tick_params(colors="#52514e", labelsize=8)
    ax.legend(fontsize=8, loc="best", frameon=False)
    plt.tight_layout()
    plt.savefig(path, dpi=140, facecolor=SURF, bbox_inches="tight")


def main():
    ap = argparse.ArgumentParser(description="portfolio-scale target-signature landscape painter (verdict-inert)")
    ap.add_argument("--atlas", default=str(Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"))
    ap.add_argument("--package-dir", action="append", default=[], help="extra --full-package run dirs to add")
    ap.add_argument("--out-csv", default="portfolio_landscape.csv")
    ap.add_argument("--out-png", default="portfolio_landscape.png")
    a = ap.parse_args()
    atlas = ac.Atlas.load(a.atlas)
    extra = [_feat_from_package_dir(p) for p in a.package_dir]
    rows = portfolio_table(atlas, extra=extra)
    _write_csv(rows, a.out_csv)
    try:
        _paint_png(atlas, rows, a.out_png)
        png_note = a.out_png
    except Exception as e:  # matplotlib/sklearn optional at paint time
        png_note = f"(skipped PNG: {e})"
    from collections import Counter

    dist = Counter(r["dominant_phenotype"] for r in rows)
    print(f"portfolio: {len(rows)} targets  dominant-phenotype dist={dict(dist)}")
    print(f"wrote {a.out_csv}  +  {png_note}")


if __name__ == "__main__":
    main()
