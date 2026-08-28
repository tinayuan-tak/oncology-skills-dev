"""target-profile — AUTO-GROUNDING step (fanout-integration, grounded-substrate two-projection design).

After the fan-out has produced the deterministic verdict spine, this runs literature-risk-assessment's
`ground_axis` over the assembled `evidence_package.json` to PRODUCE the per-axis GROUNDED SUBSTRATE in
ONE pass — the escalate-only, PMID-cited literature findings for each configured axis. A single
`target-profile --ground` run therefore yields the grounded records that feed BOTH downstream
consumers of the shared substrate:
  - the inline per-subskill grounded blocks on the HTML dashboard (via grounded_by_axis), and
  - `--substrate axis=path` on risk_rollup [3A] and cross-evidence-hypothesis [3B].

VERDICT-INERT BY CONSTRUCTION: grounding reads the ALREADY-FINISHED evidence package; it cannot change
any sub-verdict, gate, or facet. DEFAULT-ON for a full nomination run (2026-08-26): grounding + both
downstream projections (auto_risk_rollup [3A], auto_risk_assessment, auto_hypothesis [3B]) run unless
opted out via --no-substrate (or a granular --no-ground/--no-risk/--no-hypothesis), and are auto-skipped
in the offline/fast/machine modes (--no-synthesis / --verdict-only / --emit) which stay byte-identical.
BEST-EFFORT: any failure (retrieval, Bedrock, parse, a single bad axis) degrades to 'not shown/grounded'
and is logged — it never blocks the run's other artifacts.

The orchestration lives HERE (in target-profile) and only IMPORTS ground_axis / risk_rollup / the
literature-risk-assessment + cross-evidence-hypothesis run() entry points from the sibling skills —
`_skills_common` and those skills are untouched, so no other skill's byte-output moves.
"""
from __future__ import annotations

import importlib.util
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
# sub-verdict to anchor to; included only via the explicit `all`.
#
# These tuples are the OFFLINE FALLBACK only. The LIVE source of truth is ground_axis.AXIS_CONFIG
# (engine = a verdict-anchored entry [verdict_key set]; pseudo = engine-blind [verdict_key None]).
# _split_configured_axes() derives the split from it so `--ground` / `--ground all` stay in lockstep
# with the configured axes. (2026-08-21: this tuple used to hard-code 5, so `--ground`/`--ground all`
# silently EXCLUDED the 4 rolled-out engine axes [mechanism, genomic_alteration, differentiation,
# expression] — they were reachable only by an explicit comma-list. Deriving fixes that drift.)
ENGINE_AXES = ("safety", "dependency", "selectivity", "surface_modality", "tractability_sm")
PSEUDO_AXES = ("clinical", "commercial")


def _split_configured_axes() -> tuple[list, list]:
    """(engine_axes, pseudo_axes) from the LIVE ground_axis.AXIS_CONFIG, preserving config order.
    engine = a real verdict-anchored axis (`verdict_key` set); pseudo = engine-blind (`verdict_key`
    None). Imported lazily (module import is cheap + offline-safe; the heavy PubMed/Bedrock deps load
    only when ground_axis() is CALLED). Falls back to the static tuples when the import fails, so an
    offline caller still resolves the known set."""
    try:
        cfg = _import_ground_axis().AXIS_CONFIG
        engine = [k for k, c in cfg.items() if c.get("verdict_key")]
        pseudo = [k for k, c in cfg.items() if not c.get("verdict_key")]
        if engine:
            return engine, pseudo
    except Exception:  # noqa: BLE001 — fall back to the known engine+pseudo set
        pass
    return list(ENGINE_AXES), list(PSEUDO_AXES)


def _configured_axes() -> set:
    """The axes ground_axis actually supports this build (source of truth = AXIS_CONFIG)."""
    engine, pseudo = _split_configured_axes()
    return set(engine) | set(pseudo)


def resolve_axes(spec: Optional[str]) -> list:
    """Resolve the --ground value to an ordered, validated axis list.
      - None / '' / 'engine' → ALL engine axes (every verdict-anchored AXIS_CONFIG entry; the default).
      - 'all'               → engine + the clinical/commercial pseudo-cards.
      - 'a,b,c'             → exactly those, validated against ground_axis.AXIS_CONFIG (unknown → error,
                              so a typo is caught loudly, never silently skipped).
    Engine + pseudo are DERIVED from the live AXIS_CONFIG (see _split_configured_axes), so a newly-added
    engine axis is picked up by the default `engine`/`all` for free. Deterministic order (engine-then-
    pseudo, in AXIS_CONFIG order, then requested order) so the produced record set is stable."""
    s = (spec or "engine").strip().lower()
    engine, pseudo = _split_configured_axes()
    if s in ("engine", ""):
        return list(engine)
    if s == "all":
        return list(engine) + list(pseudo)
    requested = [a.strip() for a in s.split(",") if a.strip()]
    configured = set(engine) | set(pseudo)
    unknown = [a for a in requested if a not in configured]
    if unknown:
        raise ValueError(f"--ground: unknown axis/axes {unknown}; configured: {sorted(configured)}")
    # preserve engine-then-pseudo-then-other ordering for stability
    order = list(engine) + list(pseudo)
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


# --------------------------------------------------------------------------------------------------
# The two DOWNSTREAM PROJECTIONS off the grounded substrate (default-ON chain, wired 2026-08-26).
# Each is DISPLAY-ONLY / verdict-INERT and BEST-EFFORT: any failure (import, Bedrock, network, parse)
# is swallowed + logged → the function returns None, so a missing dependency degrades to "not shown"
# and never blocks the profile. Sibling skills are only IMPORTED here (their byte-output is untouched),
# mirroring _import_ground_axis. Each sibling run.py is loaded under a UNIQUE module key via importlib
# to avoid the sys.modules 'run' collision with target-profile's own run.py.
# --------------------------------------------------------------------------------------------------
def plan_substrate(*, no_substrate: bool, no_synthesis: bool, emit, ground,
                   no_ground: bool, no_risk: bool, no_hypothesis: bool) -> dict:
    """PURE gating for the default-ON grounded-substrate chain (unit-testable without executing main()).

    The chain is ON for a full nomination run unless opted out (--no-substrate) and is auto-SKIPPED in
    the offline/fast/machine modes (--no-synthesis / --verdict-only [which sets no_synthesis] / --emit),
    keeping those byte-identical. Grounding honors an explicit --ground value, else defaults to the
    engine axes when the chain is on and --no-ground isn't set. Each projection ([3A] risk, [3B]
    hypothesis) runs when the chain is on and its granular opt-out isn't set. Returns a plan dict."""
    # NOTE: gate on the machine-envelope mode explicitly, NOT `emit is None` — argparse defaults
    # --emit to "nomination", so `emit is None` was never true and the DEFAULT-ON chain silently
    # never fired on any normal run. The evidence-package mode also sets no_synthesis=True upstream,
    # so this term only needs to exclude that one machine mode.
    chain_on = (not no_substrate) and (not no_synthesis) and (emit != "evidence-package")
    return {
        "chain_on": chain_on,
        "run_ground": bool(ground) or (chain_on and not no_ground),
        "ground_spec": ground if ground else "engine",
        "run_risk": chain_on and not no_risk,
        "run_hypothesis": chain_on and not no_hypothesis,
    }


def _load_sibling(module_key: str, skill: str, filename: str):
    """Load <skill>/scripts/<filename> under `module_key`, with its scripts dir on sys.path first so the
    module's own sibling imports (hypothesis_core, pubmed_search, ground_axis, ...) resolve. Heavy deps
    (Bedrock/PubMed) inside these modules are lazy, so the import itself stays cheap + offline-safe."""
    scripts = SKILLS_DIR / skill / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / filename
    spec = importlib.util.spec_from_file_location(module_key, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = mod        # register before exec so any self-reference resolves
    spec.loader.exec_module(mod)
    return mod


def auto_risk_rollup(pkg_path, modality: Optional[str], grounded_by_axis: Optional[dict],
                     out_dir) -> Optional[dict]:
    """[3A] The DETERMINISTIC 6-dim risk roll-up: modality-conditioned worst-case bins projected purely
    from the evidence-package sub_verdicts, fused with the escalate-only grounded findings (which can
    only RAISE a flag, never move a bin). Writes risk_rollup.json into out_dir. Returns the dims dict or
    None on failure. The grounded substrate (axis→record) is passed through verbatim; risk_rollup keys
    findings by axis. modality None → risk_rollup defaults it to small_molecule."""
    try:
        rr = _load_sibling("tp_sib_risk_rollup", "literature-risk-assessment", "risk_rollup.py")
        pkg = json.loads(Path(pkg_path).read_text())
        dims = rr.project(pkg, modality or "small_molecule", grounded_by_axis or None)
        (Path(out_dir) / "risk_rollup.json").write_text(json.dumps(dims, indent=2, default=str))
        print(f"[target-profile] risk_rollup [3A] → risk_rollup.json in {out_dir}", file=sys.stderr)
        return dims
    except Exception as e:  # noqa: BLE001 — verdict-inert display context, never blocks a run
        print(f"[target-profile] WARN: risk_rollup [3A] failed ({type(e).__name__}: {e}); "
              "continuing without the deterministic risk roll-up", file=sys.stderr)
        return None


def auto_risk_assessment(target: str, indication: str, pkg_path, out_dir, *,
                         mindate: str = "2015", maxdate: str = "2026", per_cat: int = 6) -> Optional[dict]:
    """The 6-dim retrieval-grounded literature RISK read (literature-risk-assessment): a live PubMed
    E-utilities search feeds a Bedrock tool-use call that grades Biological/Druggability/Translational/
    Clinical/Safety/Commercial, anchored to the evidence-package sub_verdicts. Writes risk_assessment.json
    into out_dir. Returns the result dict or None on failure. NON-reproducible (live retrieval + LLM)."""
    try:
        lra = _load_sibling("tp_sib_lra_run", "literature-risk-assessment", "run.py")
        res = lra.run(target, indication, str(pkg_path), mindate, maxdate, per_cat)
        (Path(out_dir) / "risk_assessment.json").write_text(json.dumps(res, indent=2, default=str))
        print(f"[target-profile] 6-dim literature risk_assessment → risk_assessment.json in {out_dir}",
              file=sys.stderr)
        return res
    except Exception as e:  # noqa: BLE001 — verdict-inert display context, never blocks a run
        print(f"[target-profile] WARN: 6-dim literature risk_assessment failed "
              f"({type(e).__name__}: {e}); continuing without the literature risk read", file=sys.stderr)
        return None


def auto_cited_evidence(target: str, indication: str, out_dir, *, top_cited: int = 8) -> Optional[dict]:
    """Verdict-INERT gene×indication CITED-LITERATURE card (literature-risk-assessment/cited_evidence):
    composes the OT europepmc cited-evidence product (volume/recency/top cited sentences) + the PubTator
    typed-relation DIRECTION product into one card. Writes cited_literature_evidence.json into out_dir.
    Reproducible (pinned catalogued products, no LLM). Best-effort: analysis-methods/products absent →
    'not shown', never blocks. Carries NO verdict — pure display/confidence context."""
    try:
        ce = _load_sibling("tp_sib_cited_evidence", "literature-risk-assessment", "cited_evidence.py")
        res = ce.cited_evidence(target, indication, top_cited=top_cited)
        (Path(out_dir) / "cited_literature_evidence.json").write_text(json.dumps(res, indent=2, default=str))
        print(f"[target-profile] cited-literature evidence → cited_literature_evidence.json in {out_dir}",
              file=sys.stderr)
        return res
    except Exception as e:  # noqa: BLE001 — verdict-inert display context, never blocks a run
        print(f"[target-profile] WARN: cited-literature evidence failed "
              f"({type(e).__name__}: {e}); continuing without the cited-literature card", file=sys.stderr)
        return None


def auto_hypothesis(pkg_path, out_dir, *, modality: Optional[str] = None,
                    objective: str = "small-molecule drug target", dossier_path: Optional[str] = None,
                    risk_path: Optional[str] = None,
                    grounded_by_axis: Optional[dict] = None) -> Optional[dict]:
    """[3B] The cross-evidence-hypothesis integrator: a two-call Bedrock pipeline that reasons ACROSS the
    orthogonal evidence lines (+ optional 6-dim risk + grounded substrate) into a gate-CLAMPED, cited,
    six-part drug-target hypothesis. The deterministic gate_ceiling clamps the proposed verdict — the
    integrator ENRICHES, never OVERRIDES. Writes hypothesis.json into out_dir. Returns the result dict or
    None on failure."""
    try:
        ceh = _load_sibling("tp_sib_ceh_run", "cross-evidence-hypothesis", "run.py")
        res = ceh.run(str(pkg_path), risk_path=risk_path, objective=objective, modality=modality,
                      dossier_path=dossier_path, substrate=(grounded_by_axis or None))
        (Path(out_dir) / "hypothesis.json").write_text(json.dumps(res, indent=2, default=str))
        print(f"[target-profile] cross-evidence hypothesis [3B] → hypothesis.json in {out_dir}",
              file=sys.stderr)
        return res
    except Exception as e:  # noqa: BLE001 — verdict-inert display context, never blocks a run
        print(f"[target-profile] WARN: cross-evidence hypothesis [3B] failed "
              f"({type(e).__name__}: {e}); continuing without the cross-evidence hypothesis",
              file=sys.stderr)
        return None


__all__ = ["ENGINE_AXES", "PSEUDO_AXES", "resolve_axes", "auto_ground", "plan_substrate",
           "auto_risk_rollup", "auto_risk_assessment", "auto_cited_evidence", "auto_hypothesis"]
