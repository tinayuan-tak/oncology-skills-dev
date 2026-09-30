#!/usr/bin/env python3
"""generate_story_pages.py — the two flagship L4 "target story" pages (epic #1986, C2 #1997).

Runs tumor-presence LIVE for each (target, indication) pair, one at a time (RSS discipline — this
host runs heavy peer daemons; never run the two flagships concurrently), passes the resulting
decision.json straight into `_skills_common.l4_synthesis.assemble_target_synthesis` (a PURE
read-over — this script does not wire L4 into envelope emission, C1 #1996 is deferred
post-cutover), and renders the synthesis (or its honest absence) as a static HTML story page via
`l4_story_page.render_story_page`.

EPCAM/COADREAD: tumor-presence's only committed L3d story — a rich, corroborated flagship.
KRAS/COADREAD: NO committed L3d/other-domain evidence (only tumor_presence resolves; the rest of
`schema.KNOWN_DOMAINS` are NOT_ASSESSED). Its page is DELIBERATELY sparse: archetype=undetermined +
critical_unknowns naming every NOT_ASSESSED domain. This IS the correct output per the coordinator's
ruling on issue #1997 — never fabricate content to make a page look fuller.

Usage:
    AWS_PROFILE=cbg python generate_story_pages.py --out ~/dev/example-gallery/stories
    # one-off:
    AWS_PROFILE=cbg python generate_story_pages.py --target EPCAM --indication COADREAD
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

SKILLS_DIR = Path(__file__).resolve().parents[2]  # skills/

from _skills_common.l4_synthesis import L4TraceabilityError, assemble_target_synthesis  # noqa: E402
from generate_example_gallery import _slug, fig_map_from_existing  # noqa: E402
from l4_story_page import render_story_page  # noqa: E402

# The two flagships (docs §"L4 terminal", plan §TERMINAL PHASE). Add a row here (no other code
# change) to extend the story-page set to a third target.
FLAGSHIPS = (
    {"target": "EPCAM", "indication": "COADREAD"},
    {"target": "KRAS", "indication": "COADREAD"},
)


def _free_gb() -> Optional[float]:
    """Best-effort free-RAM read (RSS discipline — serial live emission on a shared host). None if
    `free` is unavailable (never fatal — this is an advisory print, not a gate)."""
    try:
        out = subprocess.run(["free", "-g"], capture_output=True, text=True, timeout=10, check=True).stdout
        for line in out.splitlines():
            if line.startswith("Mem:"):
                return float(line.split()[3])
    except Exception:  # noqa: BLE001
        return None
    return None


def run_tumor_presence_live(target: str, indication: str, run_dir: Path) -> Optional[dict]:
    """Invoke tumor-presence's own run.py --emit-envelope --figures (the live pipeline named in the
    coordinator's ruling). decision.json is byte-identical whether or not --emit-envelope is set
    (dispatcher docstring) — we read decision.json either way; --emit-envelope additionally writes
    evidence_package.json beside it for inspection. Returns the parsed decision.json, or None on
    failure (never raises — a failed live run is reported, not fatal to the other flagship)."""
    run_py = SKILLS_DIR / "tumor-presence" / "scripts" / "run.py"
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(run_py),
        "--target",
        target,
        "--indication",
        indication,
        "--out",
        str(run_dir),
        "--figures",
        "--emit-envelope",
    ]
    print(f"[story-pages] running tumor-presence {target}/{indication} (live)...", file=sys.stderr)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    except subprocess.CalledProcessError as e:
        print(f"[story-pages] tumor-presence {target}/{indication} FAILED: {e.stderr[-800:]}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"[story-pages] tumor-presence {target}/{indication} timed out", file=sys.stderr)
        return None
    dec_path = run_dir / "decision.json"
    if not dec_path.exists():
        print(f"[story-pages] tumor-presence {target}/{indication}: no decision.json produced", file=sys.stderr)
        return None
    return json.loads(dec_path.read_text())


def build_story_page(target: str, indication: str, run_dir: Path, decision: dict, interactive: bool = False) -> str:
    """decision -> assemble_target_synthesis -> render_story_page. `validate=True` (default) means a
    broken/untraceable claim ref RED-fails here (the mutation teeth `L4TraceabilityError` gives us) —
    this script never swallows that into a silently-thinner page."""
    synthesis = assemble_target_synthesis(decision, target=target, indication=indication)
    fig_map = fig_map_from_existing(run_dir)
    return render_story_page(
        synthesis,
        decision,
        target=target,
        indication=indication,
        run_dir=run_dir,
        fig_map=fig_map,
        interactive=interactive,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", default=None, help="single target (with --indication) instead of the flagship set")
    ap.add_argument("--indication", default=None)
    ap.add_argument("--out", type=Path, default=Path.home() / "dev" / "example-gallery" / "stories")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument(
        "--skip-run",
        action="store_true",
        help="reuse an existing --out/_runs/<slug>/decision.json instead of re-running tumor-presence "
        "live (fast iteration on the renderer only)",
    )
    args = ap.parse_args(argv)

    pairs = [{"target": args.target, "indication": args.indication}] if args.target else list(FLAGSHIPS)
    args.out.mkdir(parents=True, exist_ok=True)

    rc = 0
    for i, pair in enumerate(pairs):
        target, indication = pair["target"], pair["indication"]
        run_dir = args.out / "_runs" / _slug(target, indication)
        dec_path = run_dir / "decision.json"

        free_gb = _free_gb()
        if free_gb is not None:
            print(f"[story-pages] free RAM before {target}/{indication}: {free_gb:.0f}G", file=sys.stderr)

        if args.skip_run and dec_path.exists():
            decision = json.loads(dec_path.read_text())
        else:
            decision = run_tumor_presence_live(target, indication, run_dir)
        if decision is None:
            print(f"[story-pages] SKIP {target}/{indication}: no decision produced", file=sys.stderr)
            rc = 1
            continue

        try:
            page = build_story_page(target, indication, run_dir, decision, interactive=args.interactive)
        except L4TraceabilityError as e:
            print(f"[story-pages] {target}/{indication}: L4TraceabilityError — {e}", file=sys.stderr)
            rc = 1
            continue

        out_path = args.out / f"{_slug(target, indication)}_story.html"
        out_path.write_text(page)
        print(f"[story-pages] wrote {out_path}", file=sys.stderr)
        # serial by construction (one iteration of this loop = one live emission at a time); the RSS
        # discipline is: never parallelize this loop, and print the RAM headroom so a human watching
        # the log can tell if the NEXT target is safe to start.

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
