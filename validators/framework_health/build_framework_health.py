#!/usr/bin/env python3
"""build_framework_health.py — derive + emit the framework-health dashboard.

A DERIVED artifact (never hand-authored), in the same family as
build_subgroup_coverage_matrix.py. It AST-probes ground truth across the
framework repos (skills + the cards they consume), computes a deterministic
first-match health verdict per component, flags drift vs declared status, and
emits:
  health/framework_health.json   — the structured feed
  health/framework_health.html   — a self-contained dashboard (no server/CDN)

--check recomputes in memory and compares a STABLE PROJECTION (dropping volatile
fields: generated_at + git shas) against the committed JSON — exit 1 on diff. This
is one refinement over the coverage-matrix's raw byte-compare, which would
false-positive on the timestamp.

Usage:
  python validators/framework_health/build_framework_health.py            # generate
  python validators/framework_health/build_framework_health.py --check    # CI staleness guard
  python validators/framework_health/build_framework_health.py --skills-repo /path ...
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Support both `python -m validators.framework_health.build_framework_health`
# and direct-script invocation (the convention the other validators use).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from validators.framework_health import probe, rollup, render_html
else:
    from . import probe, rollup, render_html

SCHEMA_VERSION = "1.0.0"
HEALTH_DIR = probe.CONTRACTS_REPO / "health"
JSON_PATH = HEALTH_DIR / "framework_health.json"
HTML_PATH = HEALTH_DIR / "framework_health.html"


def _git_sha(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def generate(roots: dict[str, Path]) -> dict:
    """Full report envelope (body + volatile provenance fields)."""
    body = rollup.build_health(roots)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "<stamped-at-write>",   # set at write time; excluded from --check
        "roots": {k: str(v) for k, v in roots.items()},
        "root_shas": {k: _git_sha(v) for k, v in roots.items()},
        **body,
    }


def stable_projection(report: dict) -> str:
    """Canonical serialization with volatile fields dropped — the --check basis."""
    volatile = {"generated_at", "roots", "root_shas"}
    projected = {k: v for k, v in report.items() if k not in volatile}
    return json.dumps(projected, indent=2, sort_keys=True, default=str)


def _resolve_roots(args) -> dict[str, Path]:
    roots = probe.default_roots()
    for key, val in (
        ("skills", args.skills_repo), ("methods", args.methods_repo),
        ("products", args.products_root), ("catalog", args.catalog_repo),
        ("contracts", args.contracts_repo),
    ):
        if val:
            roots[key] = Path(val)
    return roots


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build/check the framework-health dashboard.")
    p.add_argument("--check", action="store_true",
                   help="fail (exit 1) if the committed dashboard is stale vs freshly computed")
    p.add_argument("--skills-repo", type=Path)
    p.add_argument("--methods-repo", type=Path)
    p.add_argument("--products-root", type=Path)
    p.add_argument("--catalog-repo", type=Path)
    p.add_argument("--contracts-repo", type=Path)
    p.add_argument("--json-only", action="store_true", help="skip HTML emission")
    args = p.parse_args(argv)

    roots = _resolve_roots(args)
    missing = [k for k, v in roots.items() if not v.exists()]
    if missing:
        print(f"  WARNING: repo root(s) not found, probes will degrade: {missing}", file=sys.stderr)

    report = generate(roots)
    fresh_projection = stable_projection(report)

    if args.check:
        if not JSON_PATH.exists():
            print(f"  MISSING {JSON_PATH.name} — run without --check to generate.", file=sys.stderr)
            return 1
        try:
            committed = json.loads(JSON_PATH.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"  UNREADABLE {JSON_PATH.name}: {e}", file=sys.stderr)
            return 1
        if stable_projection(committed) != fresh_projection:
            print(f"  STALE {JSON_PATH.name} — committed dashboard differs from computed; regenerate.",
                  file=sys.stderr)
            return 1
        print(f"  OK {JSON_PATH.name} (fresh)")
        return 0

    # Generate mode: stamp the timestamp now, write JSON + HTML.
    import datetime
    report["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(report, indent=2, default=str))
    s = report["summary"]
    print(f"  wrote {JSON_PATH.relative_to(probe.CONTRACTS_REPO)}: "
          f"{s['n_skills']} skills, tally={s['verdict_tally']}, "
          f"{s['n_drift_flags']} drift flags ({s['n_error_drift']} error), "
          f"{s['n_unregistered_skills']} unregistered")
    if not args.json_only:
        html = render_html.render(report)
        HTML_PATH.write_text(html)
        print(f"  wrote {HTML_PATH.relative_to(probe.CONTRACTS_REPO)} ({len(html) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
