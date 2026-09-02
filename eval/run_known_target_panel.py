#!/usr/bin/env python3
"""eval/run_known_target_panel.py — the LIVE known-target nomination backtest (Phase 2).

The framework's discrimination harness scores HAND-CURATED labels (`reference_profiles` in
target-contracts/vocabularies/known_target_calibration_set.yaml). This harness closes the gap it
names: it runs `target-profile --emit evidence-package` FRESH over those same targets (LLM-free,
deterministic spine) and scores the emitted nomination against the curated expectation — the
"measure the output, not the curation" step.

It reads the SINGLE durable source of truth (`reference_profiles`); it does not maintain a second
truth-set. Two modes:

  --emit    run target-profile fresh for each in-scope profile → packages/<TARGET>__<CODE>.json
            (slow: one live run per target; best-effort with a per-run timeout). Needs AWS_PROFILE=cbg.
  (default) SCORE whatever packages already exist against the profiles + emit a report. Fast, offline,
            credential-less — this is what run_scorecard.py calls.

Scoring (nomination-level, from `synthesis.recommendation_gate.forced_recommendation`):
  - a positive-outcome profile (approved_class / advanced / active) that comes back a hard `veto`
    is a FRESH silent-false-negative;
  - a `declined` profile flagged `dangerous_false_positive` that comes back `nominate` CONFIRMS the
    danger; if it comes back veto/hold the framework is correctly cautious;
  - `honest_blind` / `out_of_scope_tier2` profiles are REPORTED, never scored (the framework
    correctly abstains — scoring them would penalise honesty);
  - DRIFT: whenever the fresh recommendation disagrees with what the curated `agreement`/`severity`
    predicts, it is surfaced (a curated label the live framework has outgrown → flip the calibration
    entry; or a regression → investigate).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_SIBLINGS = Path.home()
SKILLS_ROOT = Path(os.environ.get("CLAUDE_ONCOLOGY_SKILLS_ROOT",
                                  _SIBLINGS / "rnd-computational-biology-oncology-claude-oncology-skills"))
CONTRACTS_ROOT = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                                     _SIBLINGS / "rnd-computational-biology-oncology-target-contracts"))
RUN_PY = SKILLS_ROOT / "skills" / "target-profile" / "scripts" / "run.py"
CAL_SET = CONTRACTS_ROOT / "vocabularies" / "known_target_calibration_set.yaml"

EVAL_DIR = Path(__file__).resolve().parent
PKG_DIR = EVAL_DIR / "known-target-packages"          # gitignored (generated, large)
OUT_PATH = EVAL_DIR / "known_target_panel_report.json"

# Target symbol the resolver accepts (profile key -> gene symbol). Composite / non-gene keys are
# SKIPPED (reported as out-of-scope, never silently passed).
TARGET_CANON = {"HER2": "ERBB2", "TROP2": "TACSTD2", "BCMA": "TNFRSF17", "TACSTD1": "EPCAM"}
_COMPOSITE = {  # multi-gene or non-gene profile keys — not a single-target run
    "CLDN18.2_LRRC15", "EGFR_cMET_VEGF", "MARK2_3", "CDK4_6", "MLLT1_3", "KAT2A_B",
    "POSTN_PDL1", "CTHRC1_PDL1", "panRAF_MEK_FAK", "CA19_9", "CLDN18.2",
}

# curated indication -> resolvable OncoTree code. None = coverage gap (no framework cohort, e.g. heme).
# 'multi' and target-level (safety/druggability) profiles map to a well-covered default (cohort-invariant
# for those axes). Heme indications with no solid cohort become honest coverage gaps.
IND_MAP = {
    "multi": "COADREAD", "COADREAD": "COADREAD", "CRC": "COADREAD",
    "NSCLC": "LUAD", "LUAD": "LUAD", "SCLC": "SCLC",
    "PAAD": "PAAD", "OV": "OV", "BRCA": "BRCA", "TNBC": "BRCA",
    "SKCM": "SKCM", "prostate": "PRAD", "urothelial": "BLCA", "GI": "STAD",
    "lymphoma": "DLBC", "RCC": "COADREAD",   # KIRC not a curated cohort; RCC profile is license-blocked/oos anyway
    # heme with no solid framework cohort -> coverage gap
    "MM": None, "CLL_AML": None, "AML": None, "BALL": None, "heme": None,
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def _tally(vals) -> dict:
    out: dict = {}
    for v in vals:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def load_profiles() -> dict:
    import yaml
    spec = yaml.safe_load(CAL_SET.read_text())
    return spec.get("reference_profiles") or {}


def resolve_job(name: str, prof: dict):
    """(emit_target, code) or (None, reason). Skips composite/non-gene keys + uncovered indications."""
    if name in _COMPOSITE:
        return None, "composite_or_nongene"
    code = IND_MAP.get(prof.get("indication"), "UNMAPPED")
    if code is None:
        return None, "no_cohort"
    if code == "UNMAPPED":
        return None, f"unmapped_indication:{prof.get('indication')}"
    return (TARGET_CANON.get(name, name), code), None


# --- outcome semantics -------------------------------------------------------------------------
_POSITIVE = {"approved_class", "advanced", "active"}        # framework must not hard-veto these
_NEGATIVE = {"declined", "declined_ph3"}
# severities the discrimination harness tracks; we score the two actionable error classes.
_SCORED_SEV = {"validated_lane", "silent_false_negative", "dangerous_false_positive"}


def _forced_reco(pkg: dict):
    return (((pkg.get("synthesis") or {}).get("recommendation_gate") or {}).get("forced_recommendation"))


def _dep_verdict(pkg: dict):
    return (((pkg.get("synthesis") or {}).get("sub_verdicts") or {}).get("dependency") or {}).get("verdict")


# --- signal vector -----------------------------------------------------------------------------
# The framework's value is the JOINTLY-ADDRESSABLE SIGNAL SUBSTRATE, not the collapsed word (the
# substrate-sufficiency principle). So we capture the FULL vector per target — per-axis verdict +
# the graded claim atoms (signal × corroboration × conflict) — and score/record against it, with
# the one-word recommendation as just ONE facet.
_SIGNAL_ORDER = {"strong": 3, "moderate": 2, "weak": 1, "unmeasured": 0, None: 0}


def extract_signal_vector(pkg: dict) -> dict:
    """The compact, diffable signal substrate a reasoner would join on — not just the recommendation."""
    syn = pkg.get("synthesis") or {}
    sub = syn.get("sub_verdicts") or {}
    cvs = syn.get("claim_vectors") or {}

    ct = syn.get("confidence_tier")
    conf_tier = ct.get("tier") if isinstance(ct, dict) else ct   # dict {tier, hits} -> scalar

    # LIVE deciding-axis coverage — the crux of substrate-sufficiency: for the axes that DECIDE this
    # target, can the framework actually evidence them? (blind/partial/captured). Already computed in
    # the package; compact it to {axis_short: band}.
    da = syn.get("deciding_axis")
    deciding_capture = {}
    if isinstance(da, dict):
        for d in da.get("deciding_axes") or []:
            if isinstance(d, dict) and d.get("short"):
                deciding_capture[d["short"]] = d.get("framework_can_evidence")

    per_axis = {}
    for axis, block in cvs.items():
        cv = (block or {}).get("claim_vector") or {}
        atoms = {k: v for k, v in cv.items() if isinstance(v, dict) and "signal" in v}
        if not atoms:
            continue
        # the strongest measured claim on the axis + whether any claim conflicts
        top = max(atoms.values(), key=lambda a: _SIGNAL_ORDER.get(a.get("signal"), 0))
        per_axis[axis] = {
            "verdict": (sub.get(axis) or {}).get("verdict"),
            "driving_rule_id": (sub.get(axis) or {}).get("driving_rule_id"),
            "top_signal": top.get("signal"),
            "top_corroboration": top.get("corroboration"),
            "any_conflict": any(a.get("conflict") for a in atoms.values()),
            "n_claims": len(atoms),
        }

    measured = [a for a in per_axis.values() if _SIGNAL_ORDER.get(a["top_signal"], 0) > 0]
    return {
        "recommendation": _forced_reco(pkg),
        "confidence_tier": conf_tier,
        "deciding_axis_capture": deciding_capture,
        "primary_gate_verdict": (syn.get("primary_gate_verdict") or {}).get("verdict")
            if isinstance(syn.get("primary_gate_verdict"), dict) else syn.get("primary_gate_verdict"),
        "gate_verdicts": {ax: (v or {}).get("verdict") for ax, v in sub.items()},
        "per_axis_signal": per_axis,
        "substrate_summary": {
            "n_axes": len(per_axis),
            "n_measured": len(measured),
            "n_strong": sum(1 for a in per_axis.values() if a["top_signal"] == "strong"),
            "n_conflicted": sum(1 for a in per_axis.values() if a["any_conflict"]),
        },
    }


def score_profile(name: str, prof: dict, pkg) -> dict:
    (job, reason) = resolve_job(name, prof)
    row = {"target": name, "indication": prof.get("indication"), "modality": prof.get("modality"),
           "outcome": prof.get("outcome"), "severity": prof.get("severity"),
           "curated_agreement": prof.get("agreement"), "deciding_axis": prof.get("deciding_axis")}
    if job is None:
        return {**row, "status": "out_of_scope", "reason": reason, "reco": None}
    row["emit_target"], row["code"] = job
    if pkg is None:
        return {**row, "status": "no_package", "reco": None}

    # Capture the FULL signal vector (substrate), not just the collapsed word.
    sv = extract_signal_vector(pkg)
    row["signal_vector"] = sv
    reco = sv["recommendation"]
    row["reco"] = reco
    row["dependency_verdict"] = sv["gate_verdicts"].get("dependency")

    sev, outcome = prof.get("severity"), prof.get("outcome")
    # Only the two actionable error classes + the positive control are pass/fail scored.
    if sev not in _SCORED_SEV:
        return {**row, "status": "reported_unscored"}

    if outcome in _POSITIVE:
        # a hard veto of a validated / eventually-right target is the silent-FN failure
        hit = reco != "veto"
        return {**row, "status": "scored", "class": "must_not_hard_veto", "hit": hit,
                "fresh_error": None if hit else "fresh_silent_false_negative"}
    if outcome in _NEGATIVE:
        # a confident nominate of a declined target is the dangerous-FP failure
        hit = reco != "nominate"
        return {**row, "status": "scored", "class": "must_not_nominate", "hit": hit,
                "fresh_error": None if hit else "fresh_dangerous_false_positive"}
    return {**row, "status": "reported_unscored"}


def _drift(row: dict) -> str | None:
    """Curated label vs fresh recommendation — surfaces both regressions and outgrown labels."""
    if row.get("status") != "scored":
        return None
    sev, reco = row.get("severity"), row.get("reco")
    if sev == "silent_false_negative" and reco == "nominate":
        return "curated=silent_FN but live NOMINATES → framework outgrew the label; flip calibration entry"
    if sev == "validated_lane" and reco == "veto":
        return "curated=validated_lane but live VETOES → REGRESSION"
    if sev == "dangerous_false_positive" and reco != "nominate":
        return "curated=dangerous_FP but live does NOT nominate → framework caught up; re-review"
    return None


def score_all(profiles: dict, pkg_dir: Path) -> dict:
    rows = []
    for name, prof in sorted(profiles.items()):
        (job, _) = resolve_job(name, prof)
        pkg = None
        if job is not None:
            et, code = job
            p = pkg_dir / f"{et}__{_slug(code)}.json"
            if p.exists():
                try:
                    pkg = json.loads(p.read_text())
                except (ValueError, OSError):
                    pkg = None
        rows.append(score_profile(name, prof, pkg))

    scored = [r for r in rows if r.get("status") == "scored"]
    hits = [r for r in scored if r.get("hit")]
    fresh_errors = [f"{r['target']}/{r.get('code')} [{r['modality']}] {r['fresh_error']} "
                    f"(reco={r['reco']}, dep={r.get('dependency_verdict')})"
                    for r in scored if r.get("fresh_error")]
    drifts = [f"{r['target']}/{r.get('code')}: {d}" for r in rows if (d := _drift(r))]
    by_status: dict = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    # Signal-substrate rollup across every target that produced a package (broader than the
    # pass/fail word): how rich + how measured + how conflicted is the vector the framework emits?
    with_sv = [r["signal_vector"] for r in rows if r.get("signal_vector")]
    substrate = None
    if with_sv:
        n = len(with_sv)
        # deciding-axis capture across the panel: the substrate-sufficiency headline — a target whose
        # deciding axis the framework is BLIND to is one it can't truly reason about, however confident
        # the collapsed word looks.
        deciding_bands = _tally(band for v in with_sv
                                for band in v["deciding_axis_capture"].values())
        substrate = {
            "n_with_vector": n,
            "avg_axes": round(sum(v["substrate_summary"]["n_axes"] for v in with_sv) / n, 1),
            "avg_measured": round(sum(v["substrate_summary"]["n_measured"] for v in with_sv) / n, 1),
            "avg_strong": round(sum(v["substrate_summary"]["n_strong"] for v in with_sv) / n, 1),
            "any_conflict_rate": round(
                sum(1 for v in with_sv if v["substrate_summary"]["n_conflicted"]) / n, 3),
            "recommendation_tally": _tally(v["recommendation"] for v in with_sv),
            "confidence_tally": _tally(v["confidence_tier"] for v in with_sv),
            "deciding_axis_capture_tally": deciding_bands,
        }

    return {
        "schema_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(CAL_SET),
        "n_profiles": len(profiles),
        "by_status": by_status,
        "scored": {"n": len(scored), "hit": len(hits),
                   "accuracy": round(len(hits) / len(scored), 3) if scored else None},
        "signal_substrate": substrate,
        "fresh_errors": fresh_errors,
        "drift_vs_curated": drifts,
        "rows": rows,
    }


def emit_packages(profiles: dict, pkg_dir: Path, timeout: int, only: set | None) -> None:
    pkg_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "AWS_PROFILE": "cbg", "AWS_REGION": "us-east-1"}
    jobs = {}
    for name, prof in profiles.items():
        if only and name not in only:
            continue
        (job, reason) = resolve_job(name, prof)
        if job is None:
            print(f"  SKIP {name} ({reason})", flush=True)
            continue
        # Carry the profile's curated MODALITY. Critical: a surface antigen that is not a genetic
        # dependency (DLL3/FOLR1/TROP2) is correctly HELD without a declared modality (the gate's
        # conservative no-modality branch), but the non_dependent veto is fully suppressed once the
        # biologics modality is declared (modality_scoped branch). Emitting modality-blind under-powers
        # the backtest and manufactures false silent-FNs. dedup identical (target, code); a collision
        # keeps the first modality (reference_profiles have one modality per key).
        jobs.setdefault(job, prof.get("modality"))
    print(f"[known-panel] emitting {len(jobs)} unique (target, code) jobs", flush=True)
    for i, ((et, code), modality) in enumerate(sorted(jobs.items()), 1):
        out = pkg_dir / f"_emit__{et}__{_slug(code)}"
        out.mkdir(exist_ok=True)
        argv = [sys.executable, str(RUN_PY), "--target", et, "--indication", code,
                "--emit", "evidence-package", "--out", str(out)]
        if modality:
            argv += ["--modality", str(modality)]   # run.py normalizes; unrecognized → warn + ignore
        t0 = time.time()
        try:
            r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
            ep = out / "evidence_package.json"
            if r.returncode == 0 and ep.exists():
                (pkg_dir / f"{et}__{_slug(code)}.json").write_text(ep.read_text())
                status = "OK"
            else:
                status = f"FAIL rc={r.returncode} {(r.stderr or '')[-120:].strip()}"
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
        print(f"  [{i}/{len(jobs)}] {et}/{code} ({time.time()-t0:.0f}s) {status}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Live known-target nomination backtest over reference_profiles.")
    ap.add_argument("--emit", action="store_true", help="run target-profile fresh to (re)populate packages")
    ap.add_argument("--only", nargs="*", help="restrict --emit to these profile keys (fast subset)")
    ap.add_argument("--packages-dir", type=Path, default=PKG_DIR)
    ap.add_argument("--timeout", type=int, default=400, help="per-emit timeout (s)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    profiles = load_profiles()
    if args.emit:
        emit_packages(profiles, args.packages_dir, args.timeout, set(args.only) if args.only else None)

    report = score_all(profiles, args.packages_dir)
    OUT_PATH.write_text(json.dumps(report, indent=2))

    s = report["scored"]
    print(f"\n=== KNOWN-TARGET PANEL ({report['generated_at']}) ===")
    print(f"  profiles: {report['n_profiles']}   status: {report['by_status']}")
    print(f"  scored (recommendation gate): {s['hit']}/{s['n']} hit (acc={s['accuracy']})")
    sub = report.get("signal_substrate")
    if sub:
        print(f"  signal substrate ({sub['n_with_vector']} vectors): "
              f"avg {sub['avg_measured']}/{sub['avg_axes']} axes measured, "
              f"{sub['avg_strong']} strong, conflict-rate {sub['any_conflict_rate']}")
        print(f"    recommendations: {sub['recommendation_tally']}   confidence: {sub['confidence_tally']}")
        print(f"    deciding-axis capture: {sub['deciding_axis_capture_tally']}")
    for e in report["fresh_errors"]:
        print(f"    FRESH-ERROR {e}")
    for d in report["drift_vs_curated"]:
        print(f"    DRIFT {d}")
    print(f"  wrote {OUT_PATH}")
    if args.json:
        print(json.dumps(report, indent=2))
    # Non-zero only on a fresh REGRESSION (validated_lane now vetoed) — outgrown labels are not failures.
    regressions = [d for d in report["drift_vs_curated"] if "REGRESSION" in d]
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
