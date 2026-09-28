#!/usr/bin/env python3
"""eval/run_scorecard_panel.py — A0b panel runner (#2000, epic #1985).

Runs the demo-week component-iterator panel roster (A7 #1994, `eval/SCORECARD_PANEL_ROSTER.md`)
through the FULL skill stack via target-profile's existing `--full-package` entrypoint
(`skills/target-profile/scripts/run.py`) and dumps each (target, indication) evidence package to a
deterministic per-target directory the scorecard adapters (#1989-#1993) and the exemplar (#1988)
read.

This is a MECHANICS-only harness (per the issue's own scoping): it reuses `run.py --full-package`
verbatim — per-sub-skill `subskills/<short>/package.json`, `evidence_package.json`, and a
`MANIFEST.json`/`MANIFEST.md` index (the mapping from a scorecard skill directory, e.g.
`tumor-presence`, to its `<short>` key, e.g. `expression`, is already recorded per-row in that
MANIFEST — this runner does not reimplement or duplicate that mapping). It does no scoring, no
criteria judgment, and never touches the verdict spine; that is adapter work (A0a #1987's
`component_scorecard.py` interface).

## Output layout (canonical, one dir per roster row)

    eval/scorecard-panel-packages/<TARGET>__<code>/
        evidence_package.json
        MANIFEST.json / MANIFEST.md
        subskills/<short>/package.json     (one per composed sub-skill)

`<TARGET>` is the roster's canonical target symbol (e.g. ``ERBB2``, not the table's parenthetical
alias ``ERBB2 (HER2)``); `<code>` is the lower-cased OncoTree indication code. This mirrors the
existing `eval/known-target-packages/` `<TARGET>__<code>.json` slug convention (see
`run_known_target_panel.py`) so the two harnesses read as one family. The directory is gitignored
(generated, non-reproducible-timing large output) — same treatment as `known-target-packages/`.

## Two modes (same shape as run_known_target_panel.py)

  --emit    run target-profile fresh over every roster row (LIVE: needs AWS_PROFILE=cbg, S3 reads;
            slow — one real run per target; best-effort with a per-target timeout) and dump to the
            canonical dir. IDEMPOTENT / safe to regenerate: `--out` is reused in place each pass,
            `run.py --full-package` overwrites only the files it owns, and the run is deterministic
            (no timestamps folded into the dumped bytes it writes) — a re-run with unchanged
            upstream data reproduces byte-identical packages.
  (default) INVENTORY only: reports which canonical roster dirs already exist/are complete, without
            running anything. Fast, offline, credential-less.

Read-only / verdict-inert: this script only orchestrates subprocess calls to the pre-existing
`run.py` and writes to its own `eval/` output tree — it never edits a card, a skill, or the
scorecard shard schema.

Roster is PARSED (not mirrored into a second copy) from `eval/SCORECARD_PANEL_ROSTER.md`'s markdown
table, per the issue's instruction ("parse or mirror it into config") — parsing keeps the roster's
one committed source of truth (A7 #1994) intact instead of forking a second, driftable copy.
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
SKILLS_ROOT = Path(
    os.environ.get(
        "CLAUDE_ONCOLOGY_SKILLS_ROOT",
        _SIBLINGS / "rnd-computational-biology-oncology-claude-oncology-skills",
    )
)
EVAL_DIR = Path(__file__).resolve().parent
ROSTER_MD = EVAL_DIR / "SCORECARD_PANEL_ROSTER.md"
PKG_DIR = EVAL_DIR / "scorecard-panel-packages"  # gitignored (generated, large)
REPORT_PATH = EVAL_DIR / "scorecard_panel_report.json"

RUN_PY = SKILLS_ROOT / "skills" / "target-profile" / "scripts" / "run.py"
SKILLS_DIR = SKILLS_ROOT / "skills"  # must be on PYTHONPATH for run.py's `_skills_common` import

# --- roster parsing -----------------------------------------------------------------------------
# The roster lives as a plain markdown table under a "## Roster (...)" heading (A7 #1994 kept it
# schema-agnostic deliberately). Row shape: "| **TARGET** | INDICATION | archetype | stresses |"
# (bold markers + a trailing parenthetical alias are cosmetic, e.g. "**ERBB2 (HER2)**").
_ROW_RE = re.compile(r"^\|\s*(?P<target>[^|]+?)\s*\|\s*(?P<indication>[^|]+?)\s*\|")
_SEPARATOR_CHARS = frozenset("-: ")


def _canonical_target(raw: str) -> str:
    """Strip markdown bold + a trailing parenthetical alias: '**ERBB2 (HER2)**' -> 'ERBB2'."""
    s = raw.strip().strip("*").strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    return s.strip()


def parse_roster(path: Path = ROSTER_MD) -> list[dict]:
    """Parse the roster's markdown table into [{target, indication, raw_target}, ...].

    Only rows inside the first "## Roster" section are read; the header row and the `|---|---|`
    separator row are skipped. Deliberately does not touch any other section of the file (rationale
    prose, non-goals) — those are free text, not roster rows.
    """
    rows: list[dict] = []
    in_table = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("## Roster"):
            in_table = True
            continue
        if in_table and stripped.startswith("##"):
            break
        if not in_table or not stripped.startswith("|"):
            continue
        m = _ROW_RE.match(stripped)
        if not m:
            continue
        target_raw = m.group("target").strip()
        indication = m.group("indication").strip()
        if target_raw.lower() == "target":
            continue  # header row
        if set(target_raw) <= _SEPARATOR_CHARS:
            continue  # "|---|---|" separator row
        rows.append(
            {
                "target": _canonical_target(target_raw),
                "indication": indication,
                "raw_target": target_raw,
            }
        )
    return rows


# --- canonical per-target output path -----------------------------------------------------------


def dest_dir(pkg_dir: Path, target: str, indication: str) -> Path:
    return pkg_dir / f"{target}__{indication.strip().lower()}"


# --- --emit: live full-package runs --------------------------------------------------------------


def emit_panel(rows: list[dict], pkg_dir: Path, timeout: int, only: set | None) -> list[dict]:
    pkg_dir.mkdir(parents=True, exist_ok=True)
    pythonpath = str(SKILLS_DIR)
    existing = os.environ.get("PYTHONPATH")
    if existing:
        pythonpath = f"{pythonpath}{os.pathsep}{existing}"
    env = {**os.environ, "AWS_PROFILE": "cbg", "AWS_REGION": "us-east-1", "PYTHONPATH": pythonpath}

    results = []
    todo = [r for r in rows if not only or r["target"] in only]
    print(f"[scorecard-panel] emitting {len(todo)}/{len(rows)} roster row(s)", flush=True)
    for i, row in enumerate(todo, 1):
        target, indication = row["target"], row["indication"]
        dest = dest_dir(pkg_dir, target, indication)
        dest.mkdir(parents=True, exist_ok=True)
        argv = [
            sys.executable,
            str(RUN_PY),
            "--target",
            target,
            "--indication",
            indication,
            "--full-package",
            "--out",
            str(dest),
        ]
        t0 = time.time()
        try:
            r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
            manifest = dest / "MANIFEST.json"
            if r.returncode == 0 and manifest.exists():
                status = "OK"
            else:
                status = f"FAIL rc={r.returncode} {(r.stderr or '')[-200:].strip()}"
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
        dur = round(time.time() - t0, 1)
        print(f"  [{i}/{len(todo)}] {target}/{indication} ({dur:.0f}s) {status}", flush=True)
        results.append(
            {"target": target, "indication": indication, "dest": str(dest), "status": status, "duration_s": dur}
        )
    return results


# --- default: offline inventory -------------------------------------------------------------------


def inventory(rows: list[dict], pkg_dir: Path) -> list[dict]:
    """What already exists on disk for each roster row, without running anything."""
    out = []
    for row in rows:
        target, indication = row["target"], row["indication"]
        dest = dest_dir(pkg_dir, target, indication)
        manifest = dest / "MANIFEST.json"
        ep = dest / "evidence_package.json"
        subskills_dir = dest / "subskills"
        n_subskills = len(list(subskills_dir.glob("*/package.json"))) if subskills_dir.exists() else 0
        complete = manifest.exists() and ep.exists()
        out.append(
            {
                "target": target,
                "indication": indication,
                "dest": str(dest),
                "manifest": manifest.exists(),
                "evidence_package": ep.exists(),
                "n_subskill_packages": n_subskills,
                "status": "OK" if complete else "MISSING",
            }
        )
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Scorecard panel runner (#2000): dump per-target evidence packages the scorecard adapters read."
    )
    ap.add_argument(
        "--emit",
        action="store_true",
        help="run target-profile fresh over the roster (live, needs AWS_PROFILE=cbg) to (re)populate the panel packages",
    )
    ap.add_argument("--only", nargs="*", help="restrict --emit to these target symbols (fast subset)")
    ap.add_argument("--packages-dir", type=Path, default=PKG_DIR)
    ap.add_argument("--timeout", type=int, default=900, help="per-target --emit timeout (s)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = parse_roster()
    if not rows:
        print(f"[scorecard-panel] ERROR: parsed 0 roster rows from {ROSTER_MD}", file=sys.stderr)
        return 1

    emit_results = None
    if args.emit:
        only = set(args.only) if args.only else None
        emit_results = emit_panel(rows, args.packages_dir, args.timeout, only)

    inv = inventory(rows, args.packages_dir)
    n_ok = sum(1 for r in inv if r["status"] == "OK")

    report = {
        "schema_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "roster_source": str(ROSTER_MD),
        "packages_dir": str(args.packages_dir),
        "n_roster_rows": len(rows),
        "emit_results": emit_results,
        "inventory": inv,
        "all_dumped": n_ok == len(inv),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))

    print(f"\n=== SCORECARD PANEL RUNNER ({report['generated_at']}) ===")
    print(f"  roster: {len(rows)} row(s) from {ROSTER_MD.name}")
    for r in inv:
        mark = "✓" if r["status"] == "OK" else "✗"
        print(
            f"  [{mark}] {r['target']:<8} {r['indication']:<9} subskills={r['n_subskill_packages']:<3} -> {r['dest']}"
        )
    print(f"  dumped: {n_ok}/{len(inv)}")
    print(f"  wrote {REPORT_PATH}")
    if args.json:
        print(json.dumps(report, indent=2))
    # Descriptive/mechanics-only harness (verdict-inert): the default inventory mode never gates CI —
    # an incomplete panel is reported, not failed. --emit is a live, best-effort, out-of-band op.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
