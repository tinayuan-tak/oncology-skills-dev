#!/usr/bin/env python3
"""atlas_health — a STALENESS / integrity guard for the frozen target-archetype atlas.

The atlas ships a FROZEN linear embedding + anchors + corpus coords as data. When the substrate underneath
moves (a sub-skill's claim vocabulary changes, a reader coverage fix like the LUAD→NSCLC canonicalization,
a new genomic splice class), the frozen map silently drifts from what the skills now emit — and nothing
fails, the companion just quietly degrades. This bundles the checks that catch that, terse PASS/FAIL with a
nonzero exit so it can gate CI:

  1. EMBEDDING INTEGRITY — every corpus row re-projects (runtime `_embed`) onto its stored frozen coord
     within tolerance. Offline==runtime; a corrupted/hand-edited embedding fails here.
  2. PROVENANCE — meta records corpus, build_date, build_git_sha, emb_dim, n_targets (a re-freeze is
     auditable).
  3. VOCABULARY DRIFT (optional) — given a live full-package run dir (--package-dir), report claim keys the
     skills now emit that are ABSENT from the frozen feature_order (→ re-freeze). Skipped if not provided.

Usage:
  python3 atlas_health.py [--atlas atlas/atlas.json] [--package-dir <full-package-run>] [--tol 1e-3]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas, vocabulary_drift  # noqa: E402

_DEFAULT_ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
_PROV_FIELDS = ("corpus", "build_date", "build_git_sha", "emb_dim", "n_targets")


def _read_claim_vectors(pkg_dir: Path) -> dict:
    cvs: dict = {}
    for pkg in glob.glob(str(pkg_dir / "subskills" / "*" / "package.json")):
        d = json.loads(Path(pkg).read_text())
        short = d.get("sub_skill") or os.path.basename(os.path.dirname(pkg))
        cv = d.get("claim_vector")
        if isinstance(cv, dict) and cv:
            cvs[short] = cv
    return cvs


def check(atlas: Atlas, package_dir: Path | None = None, tol: float = 1e-3) -> tuple[list, bool]:
    """Returns (results, ok). Each result is {check, status, detail}."""
    results = []

    # 1. embedding integrity — ALL rows
    worst = 0.0
    n_bad = 0
    for i, row in enumerate(atlas.X):
        feat = {k: v for k, v in zip(atlas.feature_order, row) if v is not None}
        e = atlas._embed(feat)
        dev = max((abs(a - b) for a, b in zip(e, atlas.corpus_emb[i])), default=0.0)
        worst = max(worst, dev)
        if dev > tol:
            n_bad += 1
    results.append({"check": "embedding_integrity", "status": "PASS" if n_bad == 0 else "FAIL",
                    "detail": f"{len(atlas.X)} rows, worst_dev={worst:.2e} (tol={tol:.0e}), n_over_tol={n_bad}"})

    # 2. provenance completeness
    missing_prov = [f for f in _PROV_FIELDS if not atlas.meta.get(f)]
    results.append({"check": "provenance", "status": "PASS" if not missing_prov else "FAIL",
                    "detail": ("all present: " + ", ".join(_PROV_FIELDS)) if not missing_prov
                    else f"missing meta fields: {missing_prov}"})

    # 3. vocabulary drift (optional)
    if package_dir is not None:
        drift = vocabulary_drift(atlas, _read_claim_vectors(package_dir))
        results.append({"check": "vocabulary_drift", "status": "PASS" if drift["covered"] else "FAIL",
                        "detail": (f"{drift['n_live']} live keys all covered" if drift["covered"]
                                   else f"{len(drift['missing_keys'])} live keys absent from atlas "
                                        f"(axes: {drift['missing_axes']}) → re-freeze")})

    ok = all(r["status"] == "PASS" for r in results)
    return results, ok


def main():
    ap = argparse.ArgumentParser(description="target-archetype atlas staleness/integrity guard")
    ap.add_argument("--atlas", default=str(_DEFAULT_ATLAS))
    ap.add_argument("--package-dir", default=None, help="OPTIONAL live full-package run for vocab-drift")
    ap.add_argument("--tol", type=float, default=1e-3)
    a = ap.parse_args()
    atlas = Atlas.load(a.atlas)
    pkg = Path(a.package_dir).expanduser() if a.package_dir else None
    results, ok = check(atlas, pkg, a.tol)
    for r in results:
        print(f"  [{r['status']}] {r['check']}: {r['detail']}")
    print("atlas_health: " + ("PASS" if ok else "FAIL"))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
