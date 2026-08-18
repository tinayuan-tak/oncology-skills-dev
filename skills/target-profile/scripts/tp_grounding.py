"""target-profile — AUTO-GROUNDING step (fanout-integration, grounded-substrate two-projection design).

After the fan-out has produced the deterministic verdict spine, this runs literature-risk-assessment's
`ground_axis` over the assembled `evidence_package.json` to PRODUCE the per-axis GROUNDED SUBSTRATE in
ONE pass — the escalate-only, PMID-cited literature findings for each configured axis. A single
`target-profile --ground` run therefore yields the grounded records that feed BOTH downstream
consumers of the shared substrate:
  - the inline per-subskill grounded blocks on the HTML dashboard (via grounded_by_axis), and
  - `--substrate axis=path` on risk_rollup [3A] and cross-evidence-hypothesis [3B].

VERDICT-INERT BY CONSTRUCTION: grounding reads the ALREADY-FINISHED evidence package; it cannot change
any sub-verdict, gate, or facet. OFF BY DEFAULT (opt-in `--ground`), so a run without the flag makes no
network/Bedrock call and is byte-identical. BEST-EFFORT: any failure (retrieval, Bedrock, parse, a
single bad axis) degrades to 'not grounded' and is logged — it never blocks the run's other artifacts.

The orchestration lives HERE (in target-profile) and only IMPORTS ground_axis from the sibling skill —
`_skills_common` and literature-risk-assessment are untouched, so no other skill's byte-output moves.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Optional

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from tp_common import SKILLS_DIR

# The ENGINE axes anchor to a target-profile sub-verdict (their grounded findings escalate a real
# deterministic axis). The PSEUDO axes are engine-blind (clinical/commercial) — literature-only, no
# sub-verdict to anchor to; included only via the explicit `all`. Kept in step with ground_axis's
# AXIS_CONFIG (a bad axis is validated against the live config in resolve_axes → never silently dropped).
ENGINE_AXES = ("safety", "dependency", "selectivity", "surface_modality", "tractability_sm")
PSEUDO_AXES = ("clinical", "commercial")


def _configured_axes() -> set:
    """The axes ground_axis actually supports this build (source of truth = AXIS_CONFIG). Imported
    lazily so a bad import degrades gracefully and offline tests need not touch the sibling skill."""
    try:
        ga = _import_ground_axis()
        return set(ga.AXIS_CONFIG)
    except Exception:  # noqa: BLE001 — fall back to the known engine+pseudo set
        return set(ENGINE_AXES) | set(PSEUDO_AXES)


def resolve_axes(spec: Optional[str]) -> list:
    """Resolve the --ground value to an ordered, validated axis list.
      - None / '' / 'engine' → the 5 engine axes (anchor to sub-verdicts; the sensible default).
      - 'all'               → engine + the clinical/commercial pseudo-cards.
      - 'a,b,c'             → exactly those, validated against ground_axis.AXIS_CONFIG (unknown → error,
                              so a typo is caught loudly, never silently skipped).
    Deterministic order (engine-then-pseudo, then requested order) so the produced record set is stable."""
    s = (spec or "engine").strip().lower()
    if s in ("engine", ""):
        return list(ENGINE_AXES)
    if s == "all":
        return list(ENGINE_AXES) + list(PSEUDO_AXES)
    requested = [a.strip() for a in s.split(",") if a.strip()]
    configured = _configured_axes()
    unknown = [a for a in requested if a not in configured]
    if unknown:
        raise ValueError(f"--ground: unknown axis/axes {unknown}; configured: {sorted(configured)}")
    # preserve engine-then-pseudo-then-other ordering for stability
    order = list(ENGINE_AXES) + list(PSEUDO_AXES)
    return sorted(dict.fromkeys(requested), key=lambda a: (order.index(a) if a in order else 99, a))


def _import_ground_axis():
    """Import literature-risk-assessment/ground_axis lazily (its live deps — pubmed_search, Bedrock —
    load only when ground_axis() is CALLED, so importing the module here is cheap + offline-safe)."""
    lra = SKILLS_DIR / "literature-risk-assessment" / "scripts"
    if str(lra) not in sys.path:
        sys.path.insert(0, str(lra))
    import ground_axis as ga  # noqa: E402
    return ga


def _default_ground_fn() -> Callable:
    return _import_ground_axis().ground_axis


def auto_ground(target: str, indication: str, pkg_path, out_dir: Path, axes: list, *,
                ground_fn: Optional[Callable] = None, mindate: str = "2015",
                maxdate: str = "2026") -> dict:
    """Run ground_axis for each axis over the assembled evidence package, writing grounded_<axis>.json
    into out_dir and returning {axis: record}. `ground_fn` is injectable for offline testing
    (defaults to literature-risk-assessment.ground_axis.ground_axis).

    BEST-EFFORT per axis: a failing axis is logged + skipped; the others still produce records. Records
    are the full {axis, deterministic, grounded} shape both the HTML renderer (grounded_by_axis) and the
    --substrate consumers (parse_grounded_substrate) accept."""
    gf = ground_fn or _default_ground_fn()
    out_dir = Path(out_dir)
    produced: dict = {}
    for ax in axes:
        try:
            rec = gf(target, indication, str(pkg_path), axis=ax, mindate=mindate, maxdate=maxdate)
        except Exception as e:  # noqa: BLE001 — one axis failing never blocks the rest
            print(f"[target-profile] WARN: grounding axis {ax!r} failed "
                  f"({type(e).__name__}: {e}); skipping", file=sys.stderr)
            continue
        if not isinstance(rec, dict):
            print(f"[target-profile] WARN: grounding axis {ax!r} returned non-dict; skipping",
                  file=sys.stderr)
            continue
        rec.setdefault("axis", ax)
        (out_dir / f"grounded_{ax}.json").write_text(json.dumps(rec, indent=2, default=str))
        produced[ax] = rec
    return produced


__all__ = ["ENGINE_AXES", "PSEUDO_AXES", "resolve_axes", "auto_ground"]
