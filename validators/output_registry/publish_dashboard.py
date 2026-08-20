#!/usr/bin/env python3
"""publish_dashboard.py — on-demand publisher for the unified framework dashboard + output registry.

Regenerates fresh (registry catalog → health → unified dashboard), stamps a small provenance
manifest, and publishes to BOTH:
  - S3  : s3://<bucket>/<prefix>/ (live) + history/<date>/ ; prints a time-boxed PRESIGNED URL.
  - GitHub : the rendered HTML as a dated `gh release` asset (no repo bloat).
The small manifest.json (SHAs + tallies + coverage/firing counts) is the diffable trend signal.

Deterministic inputs: pass --generated-at (no wall-clock read) for a reproducible manifest.

Usage (from the target-contracts repo root, canonical sibling layout):
  AWS_PROFILE=cbg python3 -m validators.output_registry.publish_dashboard \
      --generated-at 2026-08-20T17:30:00Z
  add --dry-run to assemble + stamp without any S3 / gh write; --skip-s3 / --skip-gh to do one side.

Root args default to framework_health.probe.default_roots() (the canonical sibling checkout layout);
override any of --contracts/--skills/--methods/--products/--catalog for a non-standard layout.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
SKILL_RUNS_INDEX = "s3://onc-compbio/skill-runs/index.json"
REGISTRY_TOOL = Path(__file__).with_name("build_output_registry.py")
_ROOT_KEYS = ("contracts", "skills", "methods", "products", "catalog")


def _default_roots() -> dict:
    """Canonical sibling layout via framework_health.probe; fallback to $HOME/<canonical-names>."""
    try:
        from validators.framework_health import probe
        return {k: str(v) for k, v in probe.default_roots().items()}
    except Exception:
        base = "rnd-computational-biology-oncology-"
        return {"contracts": str(HOME / f"{base}target-contracts"),
                "skills": str(HOME / f"{base}claude-oncology-skills"),
                "methods": str(HOME / f"{base}analysis-methods"),
                "products": str(HOME / f"{base}data-products"),
                "catalog": str(HOME / f"{base}data-catalog")}


def _run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def _git_sha(root: Path) -> str | None:
    r = _run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"])
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def regenerate_catalog(roots: dict, stamp: str) -> None:
    """Regenerate the registry catalog.json into the data-products root (reads S3 skill-runs)."""
    r = _run([sys.executable, str(REGISTRY_TOOL),
              "--data-products", str(roots["products"]),
              "--skill-runs-index", SKILL_RUNS_INDEX,
              "--generated-at", stamp, "--out", str(roots["products"])])
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        raise RuntimeError(f"registry regen failed: {r.stderr[-400:]}")


def compute_health(roots: dict, out_dir: Path, stamp: str) -> Path | None:
    """Fresh framework_health against explicit roots → out_dir/health_current.json (best-effort)."""
    try:
        sys.path.insert(0, str(roots["contracts"]))
        from validators.framework_health import build_framework_health as B
        report = B.generate({k: Path(v) for k, v in roots.items()})
        report["generated_at"] = stamp
        p = out_dir / "health_current.json"
        p.write_text(json.dumps(report, indent=1, default=str))
        print(f"· fresh health: {report['summary']['n_skills']} skills → {p.name}")
        return p
    except Exception as e:
        print(f"  ! health compute failed ({e}); dashboard health tab will load prior/none")
        return None


def build_dashboard(roots: dict, out_dir: Path) -> tuple[Path, Path]:
    """Run build_unified_dashboard from its package dir (bare imports) → HTML + JSON."""
    pkg = Path(roots["contracts"]) / "validators" / "architecture_dashboard"
    html = out_dir / "framework_dashboard.html"
    js = out_dir / "framework_dashboard.json"
    r = _run([sys.executable, "build_unified_dashboard.py",
              "--tc", str(roots["contracts"]), "--sk", str(roots["skills"]),
              "--dc", str(roots["catalog"]), "--dp", str(roots["products"]),
              "--no-compute-health",  # we computed it into out_dir already
              "--out", str(html), "--json", str(js)], cwd=str(pkg))
    print(r.stdout.strip() or r.stderr.strip())
    if not html.exists():
        raise RuntimeError(f"dashboard build failed: {r.stderr[-400:]}")
    return html, js


def build_manifest(js: Path, roots: dict, stamp: str) -> dict:
    """Small, diffable provenance/trend record extracted from the built graph JSON."""
    g = json.loads(js.read_text())
    s = g.get("summary", {})
    hs = (g.get("health") or {}).get("summary", {})
    cov = g.get("coverage") or {}
    cs = cov.get("summary", {})
    fr = cov.get("firings", {})
    return {
        "generated_at": stamp,
        "root_shas": {k: _git_sha(Path(v)) for k, v in roots.items()},
        "framework": {"n_skills": s.get("n_skills"), "n_cards": s.get("n_cards"),
                      "n_datasets": s.get("n_datasets"), "n_resolvers": s.get("n_resolvers")},
        "health": {"verdict_tally": hs.get("verdict_tally"),
                   "n_drift_flags": hs.get("n_drift_flags"),
                   "n_error_drift": hs.get("n_error_drift"),
                   "n_cards_firing_in_real_packages": hs.get("n_cards_firing_in_real_packages"),
                   "n_cards_firing_in_any_run": hs.get("n_cards_firing_in_any_run")},
        "outputs": {"n_entries": cs.get("n_entries"), "n_governed": cs.get("n_governed"),
                    "n_exploratory": cs.get("n_exploratory"), "n_cells": cs.get("n_cells"),
                    "n_cells_exploratory_only": cs.get("n_cells_exploratory_only"),
                    "fired_governed": len(fr.get("fired_card_ids_governed") or []),
                    "fired_any": len(fr.get("fired_card_ids_any") or [])},
    }


def publish_s3(files, bucket: str, prefix: str, date: str, presign_days: int,
               live_html_name: str, dry: bool) -> str | None:
    live = f"s3://{bucket}/{prefix}"
    hist = f"s3://{bucket}/{prefix}/history/{date}"
    for f in files:
        for dest in (f"{live}/{f.name}", f"{hist}/{f.name}"):
            print(f"  {'(dry) ' if dry else ''}→ {dest}")
            if not dry:
                r = _run(["aws", "s3", "cp", str(f), dest])
                if r.returncode != 0:
                    raise RuntimeError(f"s3 cp failed: {r.stderr[-300:]}")
    if dry:
        return None
    r = _run(["aws", "s3", "presign", f"{live}/{live_html_name}",
              "--expires-in", str(presign_days * 86400)])
    return r.stdout.strip() if r.returncode == 0 else None


def publish_gh_release(html: Path, repo: str, date: str, manifest: dict, dry: bool) -> str | None:
    tag = f"dashboard-{date}"
    title = f"Framework dashboard — {date}"
    o = manifest["outputs"]
    notes = (f"Auto-published framework dashboard.\n\n"
             f"- skills {manifest['framework'].get('n_skills')} · cards {manifest['framework'].get('n_cards')}\n"
             f"- health drift {manifest['health'].get('n_drift_flags')} ({manifest['health'].get('n_error_drift')} error)\n"
             f"- outputs {o.get('n_entries')} across {o.get('n_cells')} cells; "
             f"cards fired governed {o.get('fired_governed')} / any {o.get('fired_any')}\n"
             f"- shas: {manifest['root_shas']}")
    if dry:
        print(f"  (dry) → gh release {tag} in {repo} with asset {html.name}")
        return None
    _run(["gh", "release", "create", tag, "-R", repo, "--title", title, "--notes", notes])
    up = _run(["gh", "release", "upload", tag, str(html), "-R", repo, "--clobber"])
    if up.returncode != 0:
        raise RuntimeError(f"gh release upload failed: {up.stderr[-300:]}")
    v = _run(["gh", "release", "view", tag, "-R", repo, "--json", "url", "-q", ".url"])
    return v.stdout.strip() if v.returncode == 0 else f"release {tag}"


def main():
    dr = _default_roots()
    ap = argparse.ArgumentParser()
    for k in _ROOT_KEYS:
        ap.add_argument(f"--{k}", default=dr[k])
    ap.add_argument("--bucket", default="onc-compbio")
    ap.add_argument("--prefix", default="framework-dashboard")
    ap.add_argument("--repo", default="oneTakeda/rnd-computational-biology-oncology-target-contracts")
    ap.add_argument("--generated-at", required=True, help="ISO stamp (reproducible; no wall-clock)")
    ap.add_argument("--presign-days", type=int, default=7)
    ap.add_argument("--skip-gh", action="store_true")
    ap.add_argument("--skip-s3", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    roots = {k: Path(getattr(a, k)) for k in _ROOT_KEYS}
    stamp = a.generated_at
    date = stamp[:10]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        print("· regenerating registry catalog …")
        regenerate_catalog(roots, stamp)
        print("· computing framework health …")
        compute_health(roots, out_dir, stamp)
        print("· building unified dashboard …")
        html, js = build_dashboard(roots, out_dir)
        manifest = build_manifest(js, roots, stamp)
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        keep = HOME / "dev/framework-runs/framework-dashboard"
        keep.mkdir(parents=True, exist_ok=True)
        for f in (html, js, manifest_path):
            (keep / f.name).write_bytes(f.read_bytes())
        print(f"· local copies → {keep}")

        presigned = release_url = None
        if not a.skip_s3:
            print("· publishing to S3 …")
            catalog = roots["products"] / "catalog.json"
            files = [html, js, manifest_path] + ([catalog] if catalog.exists() else [])
            presigned = publish_s3(files, a.bucket, a.prefix, date, a.presign_days, html.name, a.dry_run)
        if not a.skip_gh:
            print("· publishing GitHub release …")
            release_url = publish_gh_release(html, a.repo, date, manifest, a.dry_run)

    print("\n✓ publish complete" + (" (dry-run)" if a.dry_run else ""))
    print(f"  manifest: {manifest['framework']} | outputs {manifest['outputs']}")
    if presigned:
        print(f"  S3 presigned ({a.presign_days}d): {presigned}")
    if release_url:
        print(f"  GitHub release: {release_url}")


if __name__ == "__main__":
    main()
