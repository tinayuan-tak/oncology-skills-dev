#!/usr/bin/env python3
"""publish_profile.py — run target-profile for one target×indication and publish the full-profile
HTML dashboard, on the same rails as the framework dashboard.

target-profile is the composed generator (fans out all 13 subskills → deterministic verdict spine
+ narrated report). This runs it, then publishes its `target_profile.html` to:
  - S3  : s3://<bucket>/<prefix>/<TARGET>-<INDICATION>/ (live) + history/<date>/ ; prints a
          time-boxed PRESIGNED URL.
  - GitHub : the HTML as a dated `gh release` asset (tag profile-<t>-<i>-<date>).

Deterministic by default (--no-synthesis, no Bedrock); pass --synthesize for the Tier-3 LLM narrative
(needs BEDROCK_AWS_PROFILE). Figures are on by default (the point of the HTML).

Usage:
  AWS_PROFILE=cbg python3 -m validators.output_registry.publish_profile \
      --target MET --indication COADREAD --generated-at 2026-08-20T19:00:00Z
  add --dry-run to run target-profile + stamp without S3/gh writes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
DEFAULT_SKILLS = HOME / "rnd-computational-biology-oncology-claude-oncology-skills"
DEFAULT_CONTRACTS = HOME / "rnd-computational-biology-oncology-target-contracts"


def _run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def run_target_profile(
    skills: Path, contracts: Path, target: str, indication: str, out_dir: Path, synthesize: bool
) -> Path:
    """Run target-profile → out_dir/target_profile.html. Returns the HTML path."""
    run_py = Path(skills) / "skills" / "target-profile" / "scripts" / "run.py"
    if not run_py.exists():
        raise FileNotFoundError(f"target-profile not found at {run_py}")
    env = {**os.environ, "TARGET_CONTRACTS_ROOT": str(contracts)}
    cmd = [sys.executable, str(run_py), "--target", target, "--indication", indication, "--out", str(out_dir)]
    if not synthesize:
        cmd.append("--no-synthesis")  # deterministic; no Bedrock
    r = subprocess.run(cmd, text=True, capture_output=True, env=env)
    html = out_dir / "target_profile.html"
    if not html.exists():
        raise RuntimeError(f"target-profile produced no HTML (rc={r.returncode}):\n{r.stderr[-500:]}")
    return html


def _profile_summary(out_dir: Path) -> dict:
    """Pull a small headline from nomination.json if present (for the release notes)."""
    nom = out_dir / "nomination.json"
    if not nom.exists():
        return {}
    try:
        d = json.loads(nom.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    h = d.get("headline") or {}
    return {
        "verdict": h.get("nomination_verdict") or h.get("verdict"),
        "positive_tier": (d.get("nomination") or {}).get("positive_tier"),
    }


def publish_s3(out_dir: Path, bucket, prefix, cell, date, presign_days, html_name, dry) -> str | None:
    """Persist the FULL emitted target-profile package (the whole --out tree: html + md +
    nomination.json + provenance + figures/ [composite PNG + per-card SVG + .plotly.json]) to S3 —
    both the live path and a dated history snapshot. `aws s3 sync` uploads the entire tree, so the
    package is persisted, not just the rendered HTML."""
    live = f"s3://{bucket}/{prefix}/{cell}"
    hist = f"s3://{bucket}/{prefix}/{cell}/history/{date}"
    for dest in (live, hist):
        print(f"  {'(dry) ' if dry else ''}→ sync {out_dir} → {dest}/")
        if not dry:
            r = _run(
                ["aws", "s3", "sync", str(out_dir), dest + "/", "--exclude", "*.pyc", "--exclude", "__pycache__/*"]
            )
            if r.returncode != 0:
                raise RuntimeError(f"s3 sync failed: {r.stderr[-300:]}")
    if dry:
        return None
    r = _run(["aws", "s3", "presign", f"{live}/{html_name}", "--expires-in", str(presign_days * 86400)])
    return r.stdout.strip() if r.returncode == 0 else None


def publish_gh_release(html: Path, repo: str, tcell: str, date: str, summ: dict, synthesized: bool, dry) -> str | None:
    tag = f"profile-{tcell}-{date}".lower()
    title = f"Target profile — {tcell} — {date}"
    notes = (
        f"Full target-profile dashboard for **{tcell}**.\n\n"
        f"- nomination: {summ.get('verdict')} (tier {summ.get('positive_tier')})\n"
        f"- deterministic verdict spine (Tier-3 synthesis {'on' if synthesized else 'off'})."
    )
    if dry:
        print(f"  (dry) → gh release {tag} in {repo} with {html.name}")
        return None
    _run(["gh", "release", "create", tag, "-R", repo, "--title", title, "--notes", notes])
    up = _run(["gh", "release", "upload", tag, str(html), "-R", repo, "--clobber"])
    if up.returncode != 0:
        raise RuntimeError(f"gh release upload failed: {up.stderr[-300:]}")
    v = _run(["gh", "release", "view", tag, "-R", repo, "--json", "url", "-q", ".url"])
    return v.stdout.strip() if v.returncode == 0 else f"release {tag}"


def upsert_profiles_catalog(dp_root: Path, entry: dict) -> int:
    """Upsert one profile into <data-products>/profiles.index.json (+ profiles.INDEX.md) — the
    GIT-TRACKED catalog of published target-profiles that lives with the outputs. Stores STABLE
    pointers (gh release url + s3:// path), never the expiring presigned url. Keyed by cell
    (latest publish wins). Returns the catalog's profile count."""
    idx = Path(dp_root) / "profiles.index.json"
    profiles = {}
    if idx.exists():
        try:
            profiles = {p["cell"]: p for p in json.loads(idx.read_text()).get("profiles", [])}
        except (OSError, json.JSONDecodeError):
            profiles = {}
    profiles[entry["cell"]] = entry
    rows = sorted(profiles.values(), key=lambda p: (p["target"], p["indication"]))
    idx.write_text(json.dumps({"profiles": rows}, indent=2, default=str) + "\n")
    md = [
        "# Target profiles — published index",
        "",
        "Git-tracked catalog of published full target-profile dashboards. **Autogenerated by "
        "`publish_profile.py`** — do not edit by hand. HTML lives in S3 + the gh release; this "
        "records the stable pointers.",
        "",
        f"{len(rows)} profile(s).",
        "",
        "| target | indication | verdict | tier | date | release | s3 |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in rows:
        md.append(
            f"| {p['target']} | {p['indication']} | {p.get('verdict')} | "
            f"{p.get('positive_tier')} | {p.get('date')} | "
            f"[release]({p.get('release_url') or ''}) | `{p.get('s3_prefix')}` |"
        )
    (Path(dp_root) / "profiles.INDEX.md").write_text("\n".join(md) + "\n")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--skills", default=str(DEFAULT_SKILLS))
    ap.add_argument("--contracts-root", default=str(DEFAULT_CONTRACTS))
    ap.add_argument("--bucket", default="onc-compbio")
    ap.add_argument("--prefix", default="framework-profiles")
    ap.add_argument(
        "--repo",
        default="oneTakeda/rnd-computational-biology-oncology-data-products",
        help="repo for the gh release (profiles are OUTPUTS → data-products by default)",
    )
    ap.add_argument(
        "--data-products",
        default=str(HOME / "rnd-computational-biology-oncology-data-products"),
        help="checkout whose root holds the git-tracked profiles.index.json catalog",
    )
    ap.add_argument("--generated-at", required=True)
    ap.add_argument("--presign-days", type=int, default=7)
    ap.add_argument("--synthesize", action="store_true", help="Tier-3 LLM narrative (needs Bedrock)")
    ap.add_argument("--skip-gh", action="store_true")
    ap.add_argument("--skip-s3", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    date = a.generated_at[:10]
    cell = f"{a.target}-{a.indication}"

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        print(f"· running target-profile for {cell} (synthesis={'on' if a.synthesize else 'off'}) …")
        html = run_target_profile(Path(a.skills), Path(a.contracts_root), a.target, a.indication, out_dir, a.synthesize)
        summ = _profile_summary(out_dir)
        # viewable local copy — the FULL emitted package (html + md + nomination + provenance +
        # figures/), not just the rendered HTML.
        import shutil

        keep = HOME / "dev/framework-runs/framework-profiles" / cell
        if keep.exists():
            shutil.rmtree(keep)
        shutil.copytree(out_dir, keep, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        n_files = sum(1 for _ in keep.rglob("*") if _.is_file())
        print(f"· local copy ({n_files} files, incl. figures/) → {keep}")

        presigned = release_url = None
        if not a.skip_s3:
            print("· publishing FULL package to S3 …")
            presigned = publish_s3(out_dir, a.bucket, a.prefix, cell, date, a.presign_days, html.name, a.dry_run)
        if not a.skip_gh:
            print("· publishing GitHub release …")
            release_url = publish_gh_release(html, a.repo, cell, date, summ, a.synthesize, a.dry_run)

        # git-tracked catalog in data-products (stable pointers; the durable record of the run)
        n_cat = None
        if not a.dry_run:
            entry = {
                "target": a.target,
                "indication": a.indication,
                "cell": cell,
                "date": date,
                "generated_at": a.generated_at,
                "verdict": summ.get("verdict"),
                "positive_tier": summ.get("positive_tier"),
                "s3_prefix": f"s3://{a.bucket}/{a.prefix}/{cell}",
                "s3_html": f"s3://{a.bucket}/{a.prefix}/{cell}/{html.name}",
                "release_url": release_url,
                "synthesized": a.synthesize,
            }
            n_cat = upsert_profiles_catalog(Path(a.data_products), entry)

    print(f"\n✓ profile published{' (dry-run)' if a.dry_run else ''}: {cell} · {summ}")
    if presigned:
        print(f"  S3 presigned ({a.presign_days}d): {presigned}")
    if release_url:
        print(f"  GitHub release: {release_url}")
    if n_cat is not None:
        print(
            f"  profiles catalog: {n_cat} profile(s) → {a.data_products}/profiles.index.json "
            "(commit + PR to data-products to persist)"
        )


if __name__ == "__main__":
    main()
