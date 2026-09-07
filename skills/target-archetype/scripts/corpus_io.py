#!/usr/bin/env python3
"""corpus_io — the ONE on-disk reader for target-archetype corpus / full-package run artifacts.

A composed target-profile run has stored its per-sub-skill claim vectors in TWO layouts over time:

  * CURRENT  <run>/evidence_package.json  →  synthesis.claim_vectors[<short>].claim_vector
  * LEGACY   <run>/subskills/<short>/package.json  →  .claim_vector

Both the offline `build_atlas` and the `atlas_health` drift guard must read whichever layout a run
actually uses — otherwise the frozen model silently drifts from the live substrate. A layout change
ALONE once disabled the guard: `_read_claim_vectors` globbed only the legacy layout, so pointed at a
current run it harvested NOTHING and (pre-fail-closed) reported a vacuous PASS. This module is the
single place that knows both shapes, so a future layout change is fixed in one spot, not per consumer.

Pure stdlib, read-only, best-effort (a malformed run yields {} rather than raising).
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path


def claim_vectors_for_run(run_dir) -> dict:
    """Return {short: claim_vector} for ONE run dir.

    Prefers the CURRENT evidence_package layout; falls back to the LEGACY subskills/*/package.json
    layout. Returns {} when neither yields a non-empty claim vector (an empty harvest is the caller's
    signal to fail-closed, not a silent pass)."""
    run = Path(run_dir)

    # CURRENT layout: evidence_package.json → synthesis.claim_vectors[short].claim_vector
    ep = run / "evidence_package.json"
    if ep.exists():
        try:
            syn = json.loads(ep.read_text()).get("synthesis") or {}
        except (ValueError, OSError):
            syn = {}
        out: dict = {}
        for short, entry in (syn.get("claim_vectors") or {}).items():
            cv = entry.get("claim_vector") if isinstance(entry, dict) else None
            if isinstance(cv, dict) and cv:
                out[short] = cv
        if out:
            return out

    # LEGACY layout: subskills/<short>/package.json → .claim_vector
    out = {}
    for pkg in glob.glob(str(run / "subskills" / "*" / "package.json")):
        try:
            d = json.loads(Path(pkg).read_text())
        except (ValueError, OSError):
            continue
        short = d.get("sub_skill") or os.path.basename(os.path.dirname(pkg))
        cv = d.get("claim_vector")
        if isinstance(cv, dict) and cv:
            out[short] = cv
    return out


def _target_indication(run: Path) -> tuple:
    """Best-effort (target, indication) for a run dir, from nomination.json / evidence_package.json."""
    for name in ("nomination.json", "evidence_package.json"):
        p = run / name
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
        except (ValueError, OSError):
            continue
        meta = d.get("meta") or {}
        t = d.get("target") or meta.get("target")
        i = d.get("indication") or meta.get("indication")
        if t:
            return (t, i)
    return (run.name, None)


def iter_corpus_runs(runs_dirs):
    """Yield (target, indication, claim_vectors) for every run dir under each path in `runs_dirs`,
    layout-tolerant via `claim_vectors_for_run`. Runs with no harvestable claim vectors are skipped.
    Shared by build_atlas (corpus assembly) and any numeric/claim harvester."""
    for base in runs_dirs:
        base = Path(base)
        if not base.exists():
            continue
        for run in sorted(p for p in base.iterdir() if p.is_dir()):
            cvs = claim_vectors_for_run(run)
            if not cvs:
                continue
            target, indication = _target_indication(run)
            yield (target, indication, cvs)
