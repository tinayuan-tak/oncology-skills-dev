#!/usr/bin/env python3
"""validate_gold — HELD-OUT VALIDATION HARNESS for the risk_rollup [3A] deterministic bins.

Calibration decision #4: score risk_rollup's per-dimension bin against a curated per-dimension GOLD set
of (target, indication, modality, expected_bin) tuples with defensible ground-truth labels. For each
gold entry we run risk_rollup.deterministic_bins over that target's evidence_package and compare the
emitted bin to the expected bin — the empirical check that the bins mean what we claim.

WHY a harness (not the truth-set): this validates the DETERMINISTIC bins (a pure function of the
sub-verdicts) against KNOWN-LABEL targets per dimension — held-out gold, not an outcome-calibration
truth-set. It answers "does risk_rollup emit LOW biological risk for a validated target-disease link
and HIGH for a passenger?" one dimension at a time, so a miss localizes to a dimension + a bin rule.

GOLD DIMENSION → ROLLUP DIMENSION. risk_rollup emits 6 dims (safety / biological / druggability /
clinical / commercial / translational); the gold set uses `selectivity` as its own dimension, but
risk_rollup folds tumor-vs-normal SELECTIVITY into the modality-conditioned SAFETY conjunction (there
is no standalone selectivity bin). So a `selectivity` gold entry is scored against the SAFETY bin — it
tests the selectivity COMPONENT of the safety conjunction. safety/biological/druggability map 1:1.

The scorer is PURE (a pkg_resolver callback → offline-testable). The CLI resolves packages from a
directory of pre-emitted evidence_package.json files (produce them with
`target-profile --emit evidence-package`); an entry with no package is reported `no_package`, never a
silent pass. VERDICT-INERT: read-only over risk_rollup + packages; changes no skill.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import risk_rollup as rr  # noqa: E402

# gold dimension -> the risk_rollup output dim it is scored against (selectivity folds into safety).
GOLD_DIM_TO_ROLLUP = {
    "safety": "safety",
    "biological": "biological",
    "druggability": "druggability",
    "selectivity": "safety",
}


def load_gold(path) -> list:
    """Flatten a gold_seed.json ({assembled:[{dimension, gold_upheld:[...], review_queue:[...]}]}) into
    scoreable entries. Only `gold_upheld` is scored (the skeptic-upheld seed); the review queue is
    carried through untouched for the report but NOT scored (it is pending curation)."""
    doc = json.loads(Path(path).read_text())
    entries, review = [], []
    for block in doc.get("assembled", []):
        dim = block.get("dimension")
        for c in block.get("gold_upheld", []):
            entries.append({**c, "_dimension": dim})
        for c in block.get("review_queue", []):
            review.append({**c, "_dimension": dim})
    return entries, review


def score_entry(entry: dict, pkg: Optional[dict]) -> dict:
    """Score ONE gold entry against its evidence_package. Returns a row with got/expected/outcome.
    outcome ∈ {hit, miss, no_package, unknown_dim}. Pure — pkg is supplied by the caller."""
    gdim = entry.get("_dimension")
    rollup_dim = GOLD_DIM_TO_ROLLUP.get(gdim)
    base = {
        "dimension": gdim,
        "rollup_dim": rollup_dim,
        "target": entry.get("target"),
        "indication": entry.get("indication"),
        "modality": entry.get("modality"),
        "label": entry.get("label"),
        "expected_bin": entry.get("expected_bin"),
        "confidence": entry.get("confidence"),
    }
    if rollup_dim is None:
        return {**base, "got_bin": None, "outcome": "unknown_dim"}
    if pkg is None:
        return {**base, "got_bin": None, "outcome": "no_package"}
    dims = rr.deterministic_bins(pkg, rr._mod(entry.get("modality") or ""))
    got = (dims.get(rollup_dim) or {}).get("bin")
    outcome = "hit" if got == entry.get("expected_bin") else "miss"
    return {**base, "got_bin": got, "outcome": outcome}


def score_gold(entries: list, pkg_resolver: Callable) -> dict:
    """Score all entries. `pkg_resolver(target, indication) -> pkg|None`. Returns rows + a per-dimension
    summary (hit/miss/no_package counts + accuracy over SCORED entries) + the overall accuracy."""
    rows = [score_entry(e, pkg_resolver(e.get("target"), e.get("indication"))) for e in entries]
    by_dim: dict = {}
    for r in rows:
        d = by_dim.setdefault(r["dimension"], {"hit": 0, "miss": 0, "no_package": 0, "unknown_dim": 0, "misses": []})
        d[r["outcome"]] += 1
        if r["outcome"] == "miss":
            d["misses"].append(
                f"{r['target']}/{r['indication']} [{r['modality']}] expected {r['expected_bin']} got {r['got_bin']}"
            )
    for d, s in by_dim.items():
        scored = s["hit"] + s["miss"]
        s["scored"] = scored
        s["accuracy"] = round(s["hit"] / scored, 3) if scored else None
    tot_hit = sum(s["hit"] for s in by_dim.values())
    tot_scored = sum(s["scored"] for s in by_dim.values())
    return {
        "rows": rows,
        "by_dimension": by_dim,
        "overall": {
            "scored": tot_scored,
            "hit": tot_hit,
            "accuracy": round(tot_hit / tot_scored, 3) if tot_scored else None,
            "no_package": sum(s["no_package"] for s in by_dim.values()),
        },
    }


# ---- CLI package resolution -------------------------------------------------------------------
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def dir_pkg_resolver(packages_dir: Path) -> Callable:
    """Resolve (target, indication) → a pre-emitted evidence_package.json under packages_dir.
    Tries <TARGET>__<indication-slug>.json, then <TARGET>.json (indication-agnostic fallback)."""
    packages_dir = Path(packages_dir)
    cache: dict = {}

    def _resolve(target, indication):
        key = (target, indication)
        if key in cache:
            return cache[key]
        for name in (
            f"{target}__{_slug(indication)}.json",
            f"{_slug(target)}__{_slug(indication)}.json",
            f"{target}.json",
        ):
            p = packages_dir / name
            if p.exists():
                cache[key] = json.loads(p.read_text())
                return cache[key]
        cache[key] = None
        return None

    return _resolve


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="risk_rollup held-out gold validation harness")
    ap.add_argument("--gold", required=True, help="gold_seed.json")
    ap.add_argument(
        "--packages-dir",
        required=True,
        help="dir of pre-emitted evidence_package.json (target-profile --emit evidence-package), "
        "named <TARGET>__<indication-slug>.json",
    )
    ap.add_argument("--out", default=None, help="write the full report JSON here")
    a = ap.parse_args(argv)
    entries, review = load_gold(a.gold)
    report = score_gold(entries, dir_pkg_resolver(a.packages_dir))
    report["n_review_queue_unscored"] = len(review)
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2))
    o = report["overall"]
    print(
        f"OVERALL: {o['hit']}/{o['scored']} scored hit (acc={o['accuracy']}); "
        f"{o['no_package']} no_package; {len(review)} review-queue unscored"
    )
    for dim, s in sorted(report["by_dimension"].items()):
        print(
            f"  {dim:13} acc={s['accuracy']} ({s['hit']}/{s['scored']}); "
            f"no_package={s['no_package']}" + (f"  MISSES: {s['misses']}" if s["misses"] else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
