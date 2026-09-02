#!/usr/bin/env python3
"""target-archetype — the verdict-INERT cross-skill nearest-reference COMPANION (standalone entry).

Unlike the 13 dispatcher sub-skills, this is a META layer: it has NO cards of its own. It consumes the
OTHER sub-skills' composed claim-vectors (a full-package target-profile run) and positions the target
against a FROZEN reference atlas — nearest analogs + soft archetype membership + rule-fingerprint
precedent + a missingness map. See _skills_common/archetype_core.py for the primitive and the governance
contract (DESCRIPTIVE, verdict=None, never a gate).

In the COMPOSED target-profile this runs as a reduction-stage facet (target-profile run.py, alongside
fragility / heterogeneity). This script is the STANDALONE / gallery entry: point it at an existing
`--package-dir` (a `target-profile --full-package` output tree with subskills/*/package.json +
nomination.json) and it emits `companion.json`.

Usage:
  python3 run.py --package-dir <full-package-run-dir> [--k 8] [--atlas <atlas.json>] [--out companion.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]        # .../skills
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas, claim_features, nomination_scorecard  # noqa: E402

SKILL_NAME = "target-archetype"
SKILL_VERSION = "0.4.0"    # DESCRIPTIVE companion, verdict-INERT. MUST equal SKILL.md metadata.version.

_DEFAULT_ATLAS = SKILLS_DIR / "target-archetype" / "atlas" / "atlas.json"


def _read_package_dir(pkg_dir: Path) -> tuple[dict, set, str, str]:
    """Read a full-package run dir -> (subskill_claim_vectors, fired_rule_ids, target, indication)."""
    nom_f = pkg_dir / "nomination.json"
    nom = json.loads(nom_f.read_text()) if nom_f.exists() else {}
    target, indication = nom.get("target"), nom.get("indication")
    cvs: dict = {}
    for pkg in glob.glob(str(pkg_dir / "subskills" / "*" / "package.json")):
        d = json.loads(Path(pkg).read_text())
        short = d.get("sub_skill") or os.path.basename(os.path.dirname(pkg))
        cv = d.get("claim_vector")
        if isinstance(cv, dict) and cv:
            cvs[short] = cv
    rules: set = set()
    for v in (nom.get("sub_verdicts") or {}).values():
        if isinstance(v, dict):
            rules.update(v.get("fired_rule_ids") or [])
    return cvs, rules, target, indication


def main():
    ap = argparse.ArgumentParser(description="target-archetype nearest-reference companion (verdict-inert)")
    ap.add_argument("--package-dir", required=True, help="a target-profile --full-package output tree")
    ap.add_argument("--atlas", default=str(_DEFAULT_ATLAS))
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--out", default=None, help="default: <package-dir>/companion.json")
    a = ap.parse_args()

    pkg_dir = Path(a.package_dir).expanduser()
    atlas = Atlas.load(a.atlas)
    cvs, rules, target, indication = _read_package_dir(pkg_dir)
    if not cvs:
        print(f"no sub-skill claim_vectors found under {pkg_dir}/subskills/*/package.json", file=sys.stderr)
        raise SystemExit(2)
    feat = claim_features(cvs)
    companion = atlas.companion(feat, k=a.k, query_rules=rules)
    scorecard = nomination_scorecard(feat, companion.get("soft_membership"), atlas)
    doc = {
        "skill": SKILL_NAME, "skill_version": SKILL_VERSION,
        "target": target, "indication": indication,
        "verdict": None,                                    # governance: descriptive companion
        "companion": companion,
        "nomination_scorecard": scorecard,                  # D1 glass-box readiness (verdict-inert)
    }
    out = Path(a.out) if a.out else pkg_dir / "companion.json"
    out.write_text(json.dumps(doc, indent=2))

    mem = " · ".join(f"{k}:{v:.0%}" for k, v in list(companion["soft_membership"].items())[:3])
    an = ", ".join(x["target"] for x in companion["nearest_analogs"][:4])
    print(f"{target}/{indication}")
    print(f"  soft membership : {mem}")
    print(f"  nearest analogs : {an}")
    nov = companion["novelty"]
    print(f"  novelty         : hull_residual={nov['hull_residual']} "
          f"(inconsistent={nov['inconsistent_flag']}, low_density={nov['local_density_flag']})")
    print(f"  unmeasured axes : {companion['missingness']['unmeasured_axes']}")
    cf = (scorecard.get("counterfactual_gap") or {}).get("limiting_axis")
    print(f"  D1 readiness    : score={scorecard.get('score')} coverage={scorecard.get('coverage')} "
          f"route={scorecard.get('dominant_archetype_soft')} limiting_axis={cf}")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
