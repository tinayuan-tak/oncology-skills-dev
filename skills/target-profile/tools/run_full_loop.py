#!/usr/bin/env python3
"""One-shot driver for the grounded-substrate two-projection loop.

The full grounded + hypothesis dashboard is THREE invocations across two skills, glued by hand
today (see the grounded-substrate two-projection design). This wraps them into one reproducible
command so a colleague can regenerate the whole artifact — and so the loop is CI-runnable — instead
of the loop only existing as a hand-built demo directory.

The loop (each stage writes into a numbered subdir of --out):
  1. GROUND   target-profile --ground <axes> --no-synthesis --no-figures
              → 01-ground/evidence_package.json + 01-ground/grounded_<axis>.json
              (deterministic fan-out + the per-axis grounded substrate; Tier-3 synthesis SKIPPED —
              grounding reads sub_verdicts + cards, not the narration, so this stage stays cheap)
  2. HYPOTHESIZE  cross-evidence-hypothesis --evidence-package … --substrate axis=path …
              → 02-hypothesis/hypothesis.json   (the [3B] projection, over the SAME substrate)
  3. RENDER   target-profile --grounded-dir 01-ground --hypothesis 02-hypothesis/hypothesis.json
              → 03-dashboard/target_profile.html   (full synthesized dashboard: inline grounded
              blocks REUSED from stage 1 — no re-grounding — + the hypothesis as the synthesis)

Design fidelity: ONE substrate (stage 1) feeds BOTH the inline render (stage 3 via --grounded-dir)
and the hypothesis (stage 2 via --substrate) — the two consumers cannot silently disagree. No stage
runs Tier-3 synthesis twice and no axis is grounded twice.

Live stages need Bedrock (cmp-dev) + cbg S3. Use --dry-run to print the exact commands without
running them (offline; what the tests assert).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/target-profile
_SKILLS = _SKILL_DIR.parent  # skills/
_TP_RUN = _SKILL_DIR / "scripts" / "run.py"
_CEH_RUN = _SKILLS / "cross-evidence-hypothesis" / "scripts" / "run.py"
_TI_RUN = _SKILLS / "target-intrinsic" / "scripts" / "run.py"

DOSSIER_DIR, GROUND_DIR, HYP_DIR, DASH_DIR = "00-dossier", "01-ground", "02-hypothesis", "03-dashboard"


def dossier_cmd(py: str, target: str, out: Path) -> list:
    """Stage 0: the indication-INDEPENDENT target-intrinsic DOSSIER (decision.json). It feeds the
    hypothesis's causal-rationale + therapeutic-window; WITHOUT it the hypothesis runs degraded and
    floors certainty to 'low' regardless of how strong the indication evidence is. The dossier
    headline is deterministic, so no synthesis is needed here (cheap)."""
    return [py, str(_TI_RUN), "--target", target, "--out", str(out / DOSSIER_DIR)]


def ground_cmd(py: str, target: str, indication: str, out: Path, ground: str, ground_indication: str | None) -> list:
    """Stage 1: deterministic fan-out + grounding, NO Tier-3 synthesis (cheap)."""
    cmd = [
        py,
        str(_TP_RUN),
        "--target",
        target,
        "--indication",
        indication,
        "--out",
        str(out / GROUND_DIR),
        "--ground",
        ground,
        "--no-synthesis",
        "--no-figures",
    ]
    if ground_indication:
        cmd += ["--ground-indication", ground_indication]
    return cmd


def collect_substrate(ground_dir: Path) -> list:
    """Stage 1 → stage 2 bridge: the grounded_<axis>.json records as `axis=path` specs, axis-sorted
    for a stable command. Returns [] when nothing was grounded (caller decides whether that's fatal)."""
    specs = []
    for gp in sorted(ground_dir.glob("grounded_*.json")):
        axis = gp.stem[len("grounded_") :]
        specs.append(f"{axis}={gp}")
    return specs


def hypothesis_cmd(
    py: str,
    ep_path: Path,
    substrate_specs: list,
    out: Path,
    modality: str | None,
    dossier: Path | None,
    objective: str | None,
) -> list:
    """Stage 2: the [3B] cross-evidence hypothesis over the grounded substrate."""
    cmd = [py, str(_CEH_RUN), "--evidence-package", str(ep_path), "--out", str(out / HYP_DIR)]
    if substrate_specs:
        cmd += ["--substrate", *substrate_specs]
    if modality:
        cmd += ["--modality", modality]
    if objective:
        cmd += ["--objective", objective]
    if dossier:
        cmd += ["--target-dossier", str(dossier)]
    return cmd


def render_cmd(py: str, target: str, indication: str, out: Path, modality: str | None) -> list:
    """Stage 3: full synthesized dashboard, REUSING stage-1 grounded records (--grounded-dir, no
    re-grounding) + the stage-2 hypothesis as the synthesis section."""
    cmd = [
        py,
        str(_TP_RUN),
        "--target",
        target,
        "--indication",
        indication,
        "--out",
        str(out / DASH_DIR),
        "--grounded-dir",
        str(out / GROUND_DIR),
        "--hypothesis",
        str(out / HYP_DIR / "hypothesis.json"),
    ]
    if modality:
        cmd += ["--modality", modality]
    return cmd


def _run(cmd: list, label: str) -> None:
    print(f"\n=== [{label}] {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="one-shot grounded + hypothesis target-profile loop")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path, help="output root (stages write numbered subdirs)")
    ap.add_argument("--ground", default="engine", help="axes to ground: engine | all | comma-list")
    ap.add_argument(
        "--ground-indication",
        default=None,
        help="PubMed disease term for grounding (OncoTree codes retrieve ~nothing); "
        "defaults to --indication inside target-profile",
    )
    ap.add_argument("--modality", default=None, help="controlled modality enum (threaded to both skills)")
    ap.add_argument("--objective", default=None, help="free-text objective for the hypothesis (narration)")
    ap.add_argument(
        "--target-dossier",
        default=None,
        type=Path,
        help="target-intrinsic decision.json (indication-independent biology) for the hypothesis; "
        "if omitted, stage 0 PRODUCES one (see --no-dossier)",
    )
    ap.add_argument(
        "--no-dossier",
        action="store_true",
        help="skip stage 0 (do not produce a target-intrinsic dossier). The hypothesis then runs "
        "degraded and floors certainty to 'low' — only use for a quick ground+render check",
    )
    ap.add_argument("--dry-run", action="store_true", help="print the stage commands; run nothing")
    args = ap.parse_args(argv)

    py = sys.executable
    out = args.out
    # Stage 0 DOSSIER: use an explicitly-supplied one, else PRODUCE it (unless opted out). Feeding the
    # dossier is what keeps the hypothesis out of degraded mode (which caps certainty at 'low').
    produce_dossier = args.target_dossier is None and not args.no_dossier
    dossier_path = args.target_dossier or (out / DOSSIER_DIR / "decision.json")
    c0 = dossier_cmd(py, args.target, out) if produce_dossier else None
    c1 = ground_cmd(py, args.target, args.indication, out, args.ground, args.ground_indication)
    ep_path = out / GROUND_DIR / "evidence_package.json"
    if args.dry_run:
        subs_preview = collect_substrate(out / GROUND_DIR)  # whatever exists now (usually none)
        d_preview = dossier_path if (produce_dossier or args.target_dossier) else None
        c2 = hypothesis_cmd(py, ep_path, subs_preview, out, args.modality, d_preview, args.objective)
        c3 = render_cmd(py, args.target, args.indication, out, args.modality)
        stages = ([("0 DOSSIER", c0)] if c0 else []) + [("1 GROUND", c1), ("2 HYPOTHESIZE", c2), ("3 RENDER", c3)]
        for label, c in stages:
            print(f"[{label}] {' '.join(c)}")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    if c0:
        _run(c0, "0 DOSSIER")
    _run(c1, "1 GROUND")
    if not ep_path.exists():
        print(f"stage 1 did not produce {ep_path}; aborting", file=sys.stderr)
        return 1
    substrate = collect_substrate(out / GROUND_DIR)
    if not substrate:
        print(
            "WARNING: stage 1 produced no grounded_<axis>.json — the hypothesis will run WITHOUT "
            "grounded literature (substrate-empty). Check --ground / --ground-indication.",
            file=sys.stderr,
        )
    hyp_dossier = dossier_path if (produce_dossier or args.target_dossier) and dossier_path.exists() else None
    if produce_dossier and hyp_dossier is None:
        print(
            "WARNING: stage 0 did not produce a dossier; the hypothesis will run degraded (certainty capped 'low').",
            file=sys.stderr,
        )
    _run(hypothesis_cmd(py, ep_path, substrate, out, args.modality, hyp_dossier, args.objective), "2 HYPOTHESIZE")
    _run(render_cmd(py, args.target, args.indication, out, args.modality), "3 RENDER")
    print(f"\n✓ full loop complete → {out / DASH_DIR / 'target_profile.html'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
