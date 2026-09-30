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
  4. NUMERIC VOCABULARY DRIFT — the `::num::` half of the same guard, WARN not FAIL. Every SALIENCE_SPECS
     axis carrying a reference_frame declares an atlas numeric, so adding a card ruler mints a feature the
     frozen order lacks; the runtime drops it and the cohort_percentile ruler that reads it self-drops, so
     this is a "re-freeze to GAIN the feature" signal, not a correctness break. Needs no --package-dir (the
     declared set is read from the code). Also reports orphan masks — a frozen `::mask` whose value column
     build_atlas dropped, i.e. a column that can only ever say "unmeasured".

WARN does not fail the gate; only FAIL does.

NOT covered here — see the sibling guard `atlas_stability.py`: whether the shipped artifact's VALUES changed
at all. Check 1 asserts INTERNAL consistency (the stored coords match what the runtime transform produces
from the stored X), which a self-consistent mutation satisfies — recompute the embedding from an edited X and
this script stays green while every percentile in the fleet has moved. atlas_stability pins a per-field
sha256 of the frozen artifact and verifies that a re-freeze reproduces it.

Usage:
  python3 atlas_health.py [--atlas atlas/atlas.json] [--package-dir <full-package-run>] [--tol 1e-3]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for the sibling corpus_io module
from _skills_common.archetype_core import Atlas, vocabulary_drift  # noqa: E402
from corpus_io import claim_vectors_for_run  # noqa: E402

_DEFAULT_ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
_PROV_FIELDS = ("corpus", "build_date", "build_git_sha", "emb_dim", "n_targets")

# Claim-key PREFIXES excluded from the atlas vocabulary BY DECISION (not drift): axes/claims deliberately
# NOT modelled — maturity/study-depth-confounded (literature_context, translational_readiness,
# safety PHARMACOVIGILANCE) or single-gene/constant (genomic SPL = METex14). See the atlas data-package
# lockdown. A live key under one of these is GREEN-by-decision, not a re-freeze trigger. The allowlist
# rides on atlas.meta["atlas_excluded_namespaces"] once the model re-freezes with it; this is the default
# until then, so the guard is not silently BLIND to those axes (the alternative — dropping them from the
# emitted vector — would hide them from every other consumer too).
_DEFAULT_EXCLUDED_NAMESPACES = (
    "literature_context::",
    "translational_readiness::",
    "safety::claim::PHARMACOVIGILANCE::",
    "genomic_alteration::claim::SPL::",
)


def _read_claim_vectors(pkg_dir: Path) -> dict:
    """Layout-tolerant harvest of {short: claim_vector} for one run dir — current evidence_package
    layout first, legacy subskills/*/package.json fallback. Single source of the on-disk shape:
    corpus_io. (Repointed 2026-09-06: the old glob read ONLY the legacy layout, so a current run
    harvested nothing → the guard could not see live drift.)"""
    return claim_vectors_for_run(pkg_dir)


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
    results.append(
        {
            "check": "embedding_integrity",
            "status": "PASS" if n_bad == 0 else "FAIL",
            "detail": f"{len(atlas.X)} rows, worst_dev={worst:.2e} (tol={tol:.0e}), n_over_tol={n_bad}",
        }
    )

    # 2. provenance completeness
    missing_prov = [f for f in _PROV_FIELDS if not atlas.meta.get(f)]
    results.append(
        {
            "check": "provenance",
            "status": "PASS" if not missing_prov else "FAIL",
            "detail": ("all present: " + ", ".join(_PROV_FIELDS))
            if not missing_prov
            else f"missing meta fields: {missing_prov}",
        }
    )

    # 3. vocabulary drift (optional) — FAIL-CLOSED on an empty harvest. vocabulary_drift computes
    # missing = live_keys - frozen_keys and covered = (not missing); so an EMPTY live set yields
    # missing == {} and a VACUOUS covered=True. A caller that passed --package-dir asked the guard to
    # actually compare live claim keys against the frozen atlas, so harvesting NOTHING (no
    # subskills/*/package.json, or a package-layout change that silently breaks _read_claim_vectors'
    # glob) must be a FAIL, not a free PASS — otherwise a layout drift disables the staleness guard
    # invisibly (the exact fail-open this check exists to prevent).
    # vocabulary_drift's numeric half reads the DECLARED numeric set from the code, so it needs no live
    # package; compute the drift dict once and use the claim half only when a package dir was supplied.
    drift = vocabulary_drift(atlas, _read_claim_vectors(package_dir) if package_dir is not None else {})

    if package_dir is not None:
        if drift["n_live"] == 0:
            results.append(
                {
                    "check": "vocabulary_drift",
                    "status": "FAIL",
                    "detail": (
                        f"empty harvest: no claim vectors under {package_dir} "
                        f"(evidence_package.json → synthesis.claim_vectors, or legacy "
                        f"subskills/*/package.json) — the vocab-drift guard cannot run "
                        f"(package-layout drift?); refusing to vacuously PASS"
                    ),
                }
            )
        else:
            # Subtract keys excluded from the atlas vocabulary BY DECISION → they are not drift.
            excluded = tuple(atlas.meta.get("atlas_excluded_namespaces") or _DEFAULT_EXCLUDED_NAMESPACES)
            missing = [k for k in drift["missing_keys"] if not k.startswith(excluded)]
            n_excluded = len(drift["missing_keys"]) - len(missing)
            covered = not missing
            axes = sorted({k.split("::", 1)[0] for k in missing})
            excl_note = f" ({n_excluded} excluded-by-decision)" if n_excluded else ""
            results.append(
                {
                    "check": "vocabulary_drift",
                    "status": "PASS" if covered else "FAIL",
                    "detail": (
                        f"{drift['n_live']} live keys all covered{excl_note}"
                        if covered
                        else f"{len(missing)} live keys absent from atlas (axes: {axes}) → re-freeze{excl_note}"
                    ),
                }
            )

    # 4. NUMERIC vocabulary drift + orphan masks — WARN. See the module docstring for why this is not a FAIL:
    # an unfrozen numeric is dropped by _align_z_impute and its cohort_percentile ruler self-drops, so the
    # geometry stays correct and merely stays BLIND to the new axis until the next re-freeze. Making it red
    # would mean every card-ruler PR has to ship an atlas re-freeze in the same commit.
    missing_num = drift["missing_numeric_keys"]
    orphans = drift["orphan_mask_keys"]
    notes = []
    if missing_num:
        notes.append(
            f"{len(missing_num)}/{drift['n_declared_numeric']} declared numerics absent from atlas "
            f"(axes: {drift['missing_numeric_axes']}) → re-freeze to GAIN them"
        )
    if orphans:
        notes.append(f"{len(orphans)} orphan masks (value column dropped at build): {orphans}")
    results.append(
        {
            "check": "numeric_vocabulary_drift",
            "status": "PASS" if not notes else "WARN",
            "detail": "; ".join(notes)
            if notes
            else f"all {drift['n_declared_numeric']} declared numerics frozen, no orphan masks",
        }
    )

    ok = not any(r["status"] == "FAIL" for r in results)  # WARN is advisory, never red
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
