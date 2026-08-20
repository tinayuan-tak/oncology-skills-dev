#!/usr/bin/env python3
"""build_output_registry.py — the OUTPUT SPINE.

Derives one unified registry of every standardized framework output across BOTH tiers,
then renders a coverage grid so the gap is visible:

  GOVERNED    (concurrence-reviewed) : data-products repo   <TARGET>/<IND>/ep-*/evidence_package.json
  EXPLORATORY (dev runs, ungoverned) : s3://onc-compbio/skill-runs/index.json  (run.json sidecars)

Emits (into --out, default ./registry/):
  catalog.json   — machine registry: normalized entries + coverage grid + summary + provenance
  CATALOG.md     — browsable cross-tier table (supersedes the per-target INDEX.md's, which only
                   cover the governed tier one target at a time)
  coverage.html  — self-contained coverage grid (target x indication x {governed | skill lanes})

Design principle (mirrors framework-health): the registry is DERIVED, never hand-authored.
Re-run it and it re-reads ground truth; a stale hand-edited README is exactly what it replaces.

Usage:
  python3 build_output_registry.py \
      --data-products ~/dev/rnd-cbo-data-products \
      --skill-runs-index /tmp/skillruns_index.json   # or  s3://onc-compbio/skill-runs/index.json
      [--out ./registry] [--generated-at 2026-08-20T00:00:00Z]

`--generated-at` is passed in explicitly (no wall-clock read) so the artifact is reproducible
and diffable; omit it and the stamp is left as "unstamped".
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


# ----------------------------------------------------------------------------- normalize
def _governed_entries(dp_root: str) -> list[dict]:
    """One entry per evidence_package.json under the data-products checkout."""
    out = []
    for f in sorted(glob.glob(os.path.join(dp_root, "*/*/*/evidence_package.json"))):
        try:
            d = json.load(open(f))
        except Exception as e:
            print(f"  skip unreadable {f}: {e}", file=sys.stderr)
            continue
        ctx = d.get("context") or {}
        tgt = (ctx.get("target") or {}).get("symbol")
        ind = (ctx.get("indication") or {}).get("oncotree_code")
        gov = d.get("governance") or {}
        vs = gov.get("validation_summary") or {}
        syn = d.get("synthesis") or {}
        gen = d.get("generated_at", "") or ""
        # producing sha lives in generated_by "skills/compose-dashboard@<sha>"
        gb = d.get("generated_by") or ""
        sha = gb.split("@")[-1] if "@" in gb else None
        out.append({
            "tier": "governed",
            "source": "evidence_package",
            "target": tgt,
            "indication": ind,
            "cell": f"{tgt}/{ind}",
            "lane": "governed",                       # single all-axis compose package
            "skill": "compose-dashboard",
            "verdict_key": "headline",
            "verdict": syn.get("headline"),
            "data_mode": gov.get("data_mode"),
            "release_pin": gov.get("release_pin"),
            "generated_at": gen,
            "date": gen[:10] if gen else "undated",
            "producing_sha": sha,
            "producing_sha_is_placeholder": sha in {"0a1b2c3", None},
            "n_cards_passed": vs.get("n_cards_passed"),
            "n_cards_total": vs.get("n_cards_attempted"),
            "status": None,
            "package_id": d.get("package_id"),
            "location": os.path.relpath(os.path.dirname(f), dp_root),
            "modality_fit": [
                {"modality": m.get("modality"), "fit_level": m.get("fit_level")}
                for m in (syn.get("modality_fit_assessment") or [])
            ],
        })
    return out


def _exploratory_entries(index_runs: list[dict]) -> list[dict]:
    """One entry per skill-runs run.json (already normalized by publish_run._extract)."""
    out = []
    for r in index_runs:
        tgt, ind = r.get("target"), r.get("indication")
        out.append({
            "tier": "exploratory",
            "source": "skill_run",
            "target": tgt,
            "indication": ind,
            "cell": f"{tgt}/{ind}",
            "lane": r.get("skill"),                   # one lane per skill
            "skill": r.get("skill"),
            "verdict_key": r.get("verdict_key"),
            "verdict": r.get("verdict"),
            "data_mode": r.get("data_mode"),
            "release_pin": r.get("resolved_release_digest"),
            "generated_at": r.get("generated_at"),
            "date": r.get("date"),
            "producing_sha": r.get("skills_repo_sha"),
            "producing_sha_is_placeholder": False,
            "n_cards_passed": r.get("n_cards_fired"),
            "n_cards_total": r.get("n_cards_consumed"),
            "status": r.get("status"),
            "package_id": None,
            "location": r.get("s3_uri"),
            "modality_fit": [],
        })
    return out


_FIRED_STATES = ("pass", "passed", "passed_with_warnings")


def _governed_card_firings(dp_root: str) -> dict[str, list[str]]:
    """{card_id: [package_id, ...]} for cards with a fired validation_state in a governed package.

    Mirrors framework_health.probe.fired_card_ids EXACTLY (same states, same field) so the
    governed subset of this index is a drop-in for the probe's rglob — the byte-stability
    guarantee that makes the signal merge safe.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(dp_root, "*/*/*/evidence_package.json"))):
        if ".invalid" in os.path.basename(f):
            continue
        try:
            pkg = json.load(open(f))
        except Exception:
            continue
        pid = pkg.get("package_id") or os.path.relpath(os.path.dirname(f), dp_root)
        for card in pkg.get("cards") or []:
            if card.get("validation_state") in _FIRED_STATES and card.get("card_id"):
                out[card["card_id"]].append(pid)
    return dict(out)


def _exploratory_card_firings(run_entries: list[dict]) -> dict[str, list[str]]:
    """{card_id: [run_id, ...]} harvested from each run's decision.json run_health.cards_fired.

    Best-effort: reads decision.json alongside each run's s3_uri; a run that can't be read
    (creds/absent) contributes nothing rather than failing the whole build.
    """
    out: dict[str, list[str]] = defaultdict(list)
    with tempfile.TemporaryDirectory() as td:
        for r in run_entries:
            uri = r.get("s3_uri")
            if not uri:
                continue
            rid = (r.get("s3_key") or uri).rstrip("/").split("/")[-1]
            dst = Path(td) / "d.json"
            res = subprocess.run(["aws", "s3", "cp", uri.rstrip("/") + "/decision.json", str(dst)],
                                 capture_output=True, text=True)
            if res.returncode != 0 or not dst.exists():
                continue
            try:
                rh = (json.loads(dst.read_text()).get("run_health") or {})
            except Exception:
                continue
            for cid in rh.get("cards_fired") or []:
                out[cid].append(rid)
    return dict(out)


def _card_firings(dp_root: str, run_entries: list[dict]) -> dict:
    """Unified card-level firing index across both tiers — the authoritative source that
    framework_health.probe.fired_card_ids consumes (governed subset = byte-stable vs its glob;
    the exploratory tier is additive liveness signal)."""
    gov = _governed_card_firings(dp_root)
    exp = _exploratory_card_firings(run_entries)
    all_cards = sorted(set(gov) | set(exp))
    index = {c: {"governed": sorted(gov.get(c, [])), "exploratory": sorted(exp.get(c, [])),
                 "fired_governed": c in gov, "fired_any": True} for c in all_cards}
    return {
        "by_card": index,
        "fired_card_ids_governed": sorted(gov),   # == probe.fired_card_ids(products) glob
        "fired_card_ids_any": all_cards,           # governed ∪ exploratory (the merged signal)
        "n_governed": len(gov),
        "n_exploratory_only": len(set(exp) - set(gov)),
    }


def _load_skill_runs_index(ref: str) -> list[dict]:
    """Accept a local path or an s3:// uri; return the `runs` list."""
    if ref.startswith("s3://"):
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "index.json"
            subprocess.run(["aws", "s3", "cp", ref, str(dst)], check=True,
                           capture_output=True, text=True)
            return json.loads(dst.read_text()).get("runs", [])
    return json.loads(Path(ref).read_text()).get("runs", [])


# ----------------------------------------------------------------------------- coverage
def _coverage(entries: list[dict]) -> dict:
    """Build the grid + summary. Rows = target/indication cells; lanes = governed + each skill."""
    cells = sorted({e["cell"] for e in entries})
    skill_lanes = sorted({e["lane"] for e in entries if e["tier"] == "exploratory"})
    lanes = ["governed"] + skill_lanes
    grid = {}
    for cell in cells:
        grid[cell] = {}
        for lane in lanes:
            hits = [e for e in entries if e["cell"] == cell and e["lane"] == lane]
            if hits:
                h = max(hits, key=lambda e: e.get("date") or "")  # newest wins the cell
                grid[cell][lane] = {"verdict": h["verdict"], "date": h["date"],
                                    "location": h["location"], "tier": h["tier"]}
    targets = sorted({e["target"] for e in entries})
    indications = sorted({e["indication"] for e in entries})
    gov_cells = {e["cell"] for e in entries if e["tier"] == "governed"}
    exp_cells = {e["cell"] for e in entries if e["tier"] == "exploratory"}
    return {
        "lanes": lanes,
        "skill_lanes": skill_lanes,
        "cells": cells,
        "grid": grid,
        "summary": {
            "n_entries": len(entries),
            "n_governed": sum(1 for e in entries if e["tier"] == "governed"),
            "n_exploratory": sum(1 for e in entries if e["tier"] == "exploratory"),
            "n_targets": len(targets),
            "n_indications": len(indications),
            "n_cells": len(cells),
            "n_cells_governed": len(gov_cells),
            "n_cells_exploratory_only": len(exp_cells - gov_cells),
            "n_cells_both": len(gov_cells & exp_cells),
            "placeholder_sha_packages": sorted(
                e["package_id"] for e in entries
                if e["tier"] == "governed" and e["producing_sha_is_placeholder"]),
        },
    }


# ----------------------------------------------------------------------------- render md
def _render_catalog_md(entries: list[dict], cov: dict, stamp: str) -> str:
    s = cov["summary"]
    L = ["# Output registry — CATALOG", "",
         "Derived cross-tier index of every standardized framework output. "
         "**Autogenerated — do not edit by hand** (re-run `build_output_registry.py`). "
         "Supersedes the per-target `INDEX.md`'s, which each cover only the governed tier for one target.",
         "",
         f"_generated_at_: `{stamp}`", "",
         f"- **{s['n_entries']}** outputs · **{s['n_governed']}** governed · "
         f"**{s['n_exploratory']}** exploratory",
         f"- **{s['n_cells']}** target×indication cells · {s['n_cells_governed']} governed · "
         f"{s['n_cells_exploratory_only']} exploratory-only · {s['n_cells_both']} in both tiers",
         f"- coverage: {s['n_targets']} targets × {s['n_indications']} indications",
         ""]
    if s["placeholder_sha_packages"]:
        L += ["> ⚠ **Provenance gap:** these governed packages carry a placeholder producing-sha "
              f"(`0a1b2c3`), so they don't record the real producing commit: "
              f"{', '.join('`'+p+'`' for p in s['placeholder_sha_packages'])}.", ""]
    # coverage grid
    L += ["## Coverage grid", "",
          "| cell | " + " | ".join(cov["lanes"]) + " |",
          "|---|" + "|".join(["---"] * len(cov["lanes"])) + "|"]
    for cell in cov["cells"]:
        row = [f"`{cell}`"]
        for lane in cov["lanes"]:
            c = cov["grid"][cell].get(lane)
            row.append(f"`{c['verdict']}`" if c and c.get("verdict") else ("✓" if c else "·"))
        L.append("| " + " | ".join(row) + " |")
    L += ["", "## All outputs", "",
          "| tier | target | indication | lane | verdict | date | data_mode | cards | location |",
          "|---|---|---|---|---|---|---|---|---|"]
    for e in sorted(entries, key=lambda x: (x["tier"], x["cell"], x["lane"])):
        cards = (f"{e['n_cards_passed']}/{e['n_cards_total']}"
                 if e["n_cards_total"] is not None else "—")
        L.append(f"| {e['tier']} | {e['target']} | {e['indication']} | {e['lane']} | "
                 f"`{e['verdict']}` | {e['date']} | {e['data_mode']} | {cards} | `{e['location']}` |")
    L.append("")
    return "\n".join(L)


# ----------------------------------------------------------------------------- render html
_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1f26;--sub:#5b6672;--line:#e5e8ec;
--gov:#1f6f43;--govbg:#e6f4ec;--exp:#8a5a00;--expbg:#fdf3e0;--empty:#c3c9d1;--accent:#2554c7}
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:var(--bg);color:var(--ink)}.wrap{max-width:1180px;margin:0 auto;padding:28px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--sub);font-size:13px;margin:0 0 20px}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 22px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;min-width:132px}
.tile .n{font-size:26px;font-weight:650}.tile .l{color:var(--sub);font-size:12px}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:#f0f2f5;font-weight:600;white-space:nowrap}td.cell{font-weight:600;white-space:nowrap}
.chip{display:inline-block;border-radius:6px;padding:2px 7px;font-size:11.5px;line-height:1.35;
max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip.gov{background:var(--govbg);color:var(--gov)}.chip.exp{background:var(--expbg);color:var(--exp)}
.dash{color:var(--empty)}h2{font-size:15px;margin:26px 0 10px}
.warn{background:#fdf0f0;border:1px solid #f3c9c9;color:#8a2020;border-radius:8px;padding:10px 14px;
font-size:12.5px;margin:0 0 18px}.legend{font-size:12px;color:var(--sub);margin:8px 0 0}
.legend .chip{max-width:none}
"""


def _chip(c: dict) -> str:
    if not c:
        return '<span class="dash">·</span>'
    cls = "gov" if c["tier"] == "governed" else "exp"
    v = html.escape(str(c.get("verdict") or "✓"))
    return f'<span class="chip {cls}" title="{v} ({html.escape(c.get("date",""))})">{v}</span>'


def _render_html(entries: list[dict], cov: dict, stamp: str) -> str:
    s = cov["summary"]
    tiles = [("outputs", s["n_entries"]), ("governed", s["n_governed"]),
             ("exploratory", s["n_exploratory"]), ("cells", s["n_cells"]),
             ("exploratory-only", s["n_cells_exploratory_only"]), ("both tiers", s["n_cells_both"])]
    tile_html = "".join(f'<div class="tile"><div class="n">{n}</div><div class="l">{l}</div></div>'
                        for l, n in tiles)
    warn = ""
    if s["placeholder_sha_packages"]:
        warn = ('<div class="warn"><b>Provenance gap:</b> '
                + str(len(s["placeholder_sha_packages"])) +
                ' governed package(s) carry a placeholder producing-sha (<code>0a1b2c3</code>): '
                + ", ".join("<code>" + html.escape(p) + "</code>"
                            for p in s["placeholder_sha_packages"]) + "</div>")
    # grid
    head = "".join(f"<th>{html.escape('governed (compose)' if l=='governed' else l)}</th>"
                   for l in cov["lanes"])
    rows = []
    for cell in cov["cells"]:
        tds = "".join(f"<td>{_chip(cov['grid'][cell].get(l))}</td>" for l in cov["lanes"])
        rows.append(f'<tr><td class="cell">{html.escape(cell)}</td>{tds}</tr>')
    grid = (f'<table><thead><tr><th>target / indication</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')
    legend = ('<p class="legend">'
              '<span class="chip gov">governed</span> concurrence-reviewed evidence package · '
              '<span class="chip exp">exploratory</span> ungoverned dev run · '
              '<span class="dash">·</span> no output yet</p>')
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<title>Framework output registry</title><style>{_CSS}</style></head><body><div class="wrap">'
            f'<h1>Framework output registry — coverage</h1>'
            f'<p class="sub">Derived from the data-products repo (governed) + skill-runs S3 '
            f'(exploratory). Generated {html.escape(stamp)}.</p>'
            f'{warn}<div class="tiles">{tile_html}</div>'
            f'<h2>Coverage grid</h2>{grid}{legend}'
            f'</div></body></html>')


# ----------------------------------------------------------------------------- main
def _load_profiles(dp_root: str) -> dict:
    """{cell -> profile entry} from the git-tracked <data-products>/profiles.index.json catalog
    (maintained by publish_profile.py). Lets the coverage grid link each cell to its published
    full target-profile dashboard. Empty when no catalog exists."""
    p = Path(dp_root) / "profiles.index.json"
    if not p.exists():
        return {}
    try:
        return {e["cell"]: e for e in json.loads(p.read_text()).get("profiles", [])}
    except (OSError, json.JSONDecodeError, KeyError):
        return {}


def build(dp_root: str, skill_runs_index: str, out: str, stamp: str) -> dict:
    runs = _load_skill_runs_index(skill_runs_index)
    entries = _governed_entries(dp_root) + _exploratory_entries(runs)
    cov = _coverage(entries)
    firings = _card_firings(dp_root, runs)
    profiles = _load_profiles(dp_root)   # cell -> published-profile pointers (release_url, s3)
    cov["summary"]["n_cards_fired_governed"] = firings["n_governed"]
    cov["summary"]["n_cards_fired_exploratory_only"] = firings["n_exploratory_only"]
    cov["summary"]["n_published_profiles"] = len(profiles)
    catalog = {"generated_at": stamp, "schema_version": 3,
               "sources": {"data_products": dp_root, "skill_runs_index": skill_runs_index},
               "summary": cov["summary"], "coverage": {k: cov[k] for k in ("lanes", "cells", "grid")},
               "card_firings": firings,
               "profiles": profiles,
               "entries": entries}
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    (outp / "catalog.json").write_text(json.dumps(catalog, indent=2, default=str))
    (outp / "CATALOG.md").write_text(_render_catalog_md(entries, cov, stamp))
    (outp / "coverage.html").write_text(_render_html(entries, cov, stamp))
    return catalog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-products", required=True, help="path to a data-products checkout")
    ap.add_argument("--skill-runs-index", required=True,
                    help="local path OR s3:// uri to skill-runs/index.json")
    ap.add_argument("--out", default="./registry")
    ap.add_argument("--generated-at", default="unstamped",
                    help="ISO timestamp stamped into the artifact (passed in for reproducibility)")
    a = ap.parse_args()
    cat = build(a.data_products, a.skill_runs_index, a.out, a.generated_at)
    s = cat["summary"]
    print(f"✓ registry: {s['n_entries']} outputs "
          f"({s['n_governed']} governed / {s['n_exploratory']} exploratory) across "
          f"{s['n_cells']} cells → {a.out}/{{catalog.json,CATALOG.md,coverage.html}}")
    print(f"  cells: {s['n_cells_governed']} governed · {s['n_cells_exploratory_only']} "
          f"exploratory-only · {s['n_cells_both']} both")
    if s["placeholder_sha_packages"]:
        print(f"  ⚠ {len(s['placeholder_sha_packages'])} governed package(s) with placeholder sha")


if __name__ == "__main__":
    main()
