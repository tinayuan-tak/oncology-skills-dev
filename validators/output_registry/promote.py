#!/usr/bin/env python3
"""promote.py — exploratory → governed promotion, driven by the output registry.

The coverage grid identifies target×indication cells that exist only as exploratory skill-runs
(the promotion backlog). Promotion = running compose-dashboard for such a cell, which emits a
GOVERNED evidence package straight into the data-products repo (ready for concurrence review).

  # what's promotable? (reads the registry catalog.json — no deps)
  python3 promote.py --catalog <data-products>/catalog.json --list

  # promote one cell (runs compose-dashboard; needs its env — AWS_PROFILE=cbg, pixi, Bedrock for synth)
  AWS_PROFILE=cbg python3 promote.py --skills <skills-checkout> --target MET --indication COADREAD
  #   add --dry-run to print the compose-dashboard command without running it.

compose-dashboard writes to data-products/{target}/{indication}/{package_id}/ by default; after a
successful run, `cd` into the data-products repo and open a PR — that PR IS the concurrence gate.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HOME = Path.home()


def _load_catalog(catalog: Path) -> dict:
    return json.loads(Path(catalog).read_text())


def promotion_candidates(cat: dict) -> list[dict]:
    """Cells present in the exploratory tier but with NO governed package — the backlog.

    Each candidate carries the exploratory lanes/verdicts already produced, so a promoter can
    see what evidence motivated the cell before spending a full compose run on it."""
    grid = (cat.get("coverage") or {}).get("grid") or {}
    out = []
    for cell, lanes in grid.items():
        if "governed" in lanes:
            continue  # already governed
        exp = {ln: v.get("verdict") for ln, v in lanes.items() if v.get("tier") == "exploratory"}
        if exp:
            target, _, indication = cell.partition("/")
            out.append({"cell": cell, "target": target, "indication": indication,
                        "exploratory": exp})
    return sorted(out, key=lambda c: c["cell"])


def cmd_list(cat: dict) -> None:
    cands = promotion_candidates(cat)
    s = cat.get("summary", {})
    print(f"Promotion backlog — {len(cands)} exploratory-only cell(s) "
          f"(of {s.get('n_cells')} total; {s.get('n_cells_governed')} already governed):\n")
    for c in cands:
        lanes = ", ".join(f"{k}={v}" for k, v in c["exploratory"].items())
        print(f"  {c['cell']:22} {lanes}")
    if cands:
        print("\nPromote one with:\n  AWS_PROFILE=cbg python3 promote.py --skills <ckt> "
              f"--target {cands[0]['target']} --indication {cands[0]['indication']}")


def compose_cmd(skills: Path, target: str, indication: str, data_mode: str,
                release_pin: str | None, out: str | None, runner: str) -> list[str]:
    script = Path(skills) / "skills" / "compose-dashboard" / "scripts" / "compose_dashboard.py"
    if not script.exists():
        raise FileNotFoundError(f"compose-dashboard not found at {script}")
    # runner defaults to "pixi run python" — skills run under pixi (pixi.toml at the skills root);
    # compose_dashboard.py self-inserts its sys.path, so it's cwd-robust as long as pixi activates
    # the env (which needs cwd = skills root).
    cmd = runner.split() + [str(script), "--target", target, "--indication", indication,
                            "--data-mode", data_mode]
    if release_pin:
        cmd += ["--release-pin", release_pin]
    if out:
        cmd += ["--out", out]
    return cmd


def cmd_promote(a) -> int:
    cmd = compose_cmd(Path(a.skills), a.target, a.indication, a.data_mode, a.release_pin,
                      a.out, a.runner)
    print("compose-dashboard command (cwd = skills root):\n  " + " ".join(cmd))
    if a.dry_run:
        print("\n(dry-run — not executed)")
        return 0
    print("\n· running compose-dashboard (live — fans out all cards; needs AWS/pixi/Bedrock env) …")
    r = subprocess.run(cmd, cwd=str(Path(a.skills)))  # cwd = skills root so pixi finds pixi.toml
    if r.returncode == 0:
        print(f"\n✓ governed package emitted for {a.target}/{a.indication}. Next: open a "
              "data-products PR (the concurrence gate), then re-run the registry/publisher.")
    else:
        print(f"\n✗ compose-dashboard exited {r.returncode} — see output above.", file=sys.stderr)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(HOME / "rnd-computational-biology-oncology-data-products"
                                             / "catalog.json"),
                    help="path to the registry catalog.json (data-products root)")
    ap.add_argument("--skills", default=str(HOME / "rnd-computational-biology-oncology-claude-oncology-skills"))
    ap.add_argument("--list", action="store_true", help="print the promotion backlog and exit")
    ap.add_argument("--target")
    ap.add_argument("--indication")
    ap.add_argument("--data-mode", default="latest_approved")
    ap.add_argument("--release-pin", default=None)
    ap.add_argument("--out", default=None, help="override compose output dir (default: data-products)")
    ap.add_argument("--runner", default="pixi run python",
                    help="how to invoke compose-dashboard (skills run under pixi)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.list or not (a.target and a.indication):
        cat = _load_catalog(Path(a.catalog))
        cmd_list(cat)
        if not a.list:
            print("\n(no --target/--indication given → listed backlog; pass both to promote a cell)")
        return
    sys.exit(cmd_promote(a))


if __name__ == "__main__":
    main()
