"""target-profile — full-package persistence (--full-package): per-sub-skill package projections
+ a self-contained MANIFEST index.

VERDICT-INERT and purely ADDITIVE: everything here is a projection over the SAME in-memory
`sub_results` the fan-out already produced (verdict / driving_rule_id / fired_rule_ids / cards +
their summaries / synthesis_facet) plus the artifacts the run already wrote. Nothing is re-resolved,
nothing touches the recommendation spine. A default run (no --full-package) never calls this, so it
is byte-identical.

Purpose: make one composed run a single, portable, reviewable bundle — narrative + machine envelope +
figures + the granular per-sub-skill / per-card substrate — tied together by an index, so a reviewer
never has to know that the granular data lives in nomination.json / evidence_package.json rather than
under figures/.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def _card_figures(figures_dir: Path, card_id: str) -> list[str]:
    """Relative paths (from the run root) of every file emitted under figures/cards/<card_id>/."""
    card_dir = figures_dir / "cards" / card_id
    if not card_dir.is_dir():
        return []
    root = figures_dir.parent
    return sorted(str(p.relative_to(root)) for p in card_dir.rglob("*") if p.is_file())


def _subskill_package(short: str, r: dict, figures_dir: Path) -> dict:
    """A standalone per-sub-skill package: its verdict + fired rules + claim-vector signal
    decomposition + each of its cards' full summary and figures. Sourced entirely from the retained
    CompositionResult carrier — no re-resolution."""
    v = r.get("verdict")
    facet = r.get("synthesis_facet") or {}
    cards_out: list[dict] = []
    for c in (r.get("cards") or []):
        if not isinstance(c, dict):
            continue
        cid = c.get("card_id")
        summary = c.get("summary") or {}
        cards_out.append({
            "card_id": cid,
            "card_version": c.get("card_version", "n/a"),
            "missing": bool(c.get("_missing")),
            "data_source": summary.get("_data_source"),
            "summary": summary,
            "figures": _card_figures(figures_dir, cid) if cid else [],
        })
    return {
        "sub_skill": short,
        "verdict": v[0] if v else None,
        "driving_rule_id": v[1] if v else None,
        "fired_rule_ids": [f["rule_id"] for f in (r.get("fired") or [])],
        "claim_vector": facet.get("claim_vector"),
        "key_signals": facet.get("key_signals"),
        "n_cards": len(cards_out),
        "cards": cards_out,
    }


def write_full_package(out_dir: Path, *, target: str, indication: str, sub_results: dict,
                       skill_name: str, skill_version: str, generated_at: str,
                       subtypes: Optional[list], modality: Optional[str],
                       has_figures: bool, has_evidence_package: bool,
                       has_narrative: bool) -> Path:
    """Write subskills/<short>/package.json for every sub-skill + MANIFEST.json + MANIFEST.md.

    Returns the MANIFEST.json path. Best-effort per sub-skill (a malformed carrier is skipped, never
    fatal — a persistence side-artifact must not break a run that already produced its verdict)."""
    figures_dir = out_dir / "figures"
    subskills_dir = out_dir / "subskills"
    subskills_dir.mkdir(parents=True, exist_ok=True)

    sub_index: list[dict] = []
    for short, r in sub_results.items():
        try:
            pkg = _subskill_package(short, r, figures_dir)
        except Exception as e:  # noqa: BLE001 — never let one carrier break the bundle
            print(f"[target-profile] --full-package: skipped sub-skill {short} ({type(e).__name__}: {e})")
            continue
        pkg_path = subskills_dir / short / "package.json"
        pkg_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_path.write_text(json.dumps(pkg, indent=2, default=str))
        n_fig = sum(len(c["figures"]) for c in pkg["cards"])
        sub_index.append({
            "sub_skill": short,
            "verdict": pkg["verdict"],
            "driving_rule_id": pkg["driving_rule_id"],
            "package": f"subskills/{short}/package.json",
            "n_cards": pkg["n_cards"],
            "n_figures": n_fig,
        })

    n_fig_total = len([p for p in figures_dir.rglob("*") if p.is_file()]) if figures_dir.is_dir() else 0

    # Artifact map — where each kind of output lives, so a reviewer navigates the bundle from ONE file.
    artifacts = {
        "narrative_markdown": "target_profile.md" if has_narrative else None,
        "narrative_html": "target_profile.html" if has_narrative else None,
        "machine_nomination": "nomination.json" if has_narrative else None,
        "machine_evidence_package": "evidence_package.json" if has_evidence_package else None,
        "provenance": "provenance.yaml" if has_narrative else None,
        "hero_figure": "figures/target_profile_at_a_glance.png" if has_figures else None,
        "run_log": "run.log",
    }
    manifest = {
        "schema_version": 1,
        "bundle_type": "target-profile-full-package",
        "target": target,
        "indication": indication,
        "subtypes": subtypes or None,
        "modality": modality,
        "skill": skill_name,
        "skill_version": skill_version,
        "generated_at": generated_at,
        "artifacts": {k: v for k, v in artifacts.items() if v is not None},
        "sub_skills": sub_index,
        "figures": {"n_files": n_fig_total, "dir": "figures/"},
        "where_the_data_lives": (
            "Granular data is NOT under figures/ (those are figure inputs). The authoritative machine "
            "record is nomination.json (verdicts + facets) and evidence_package.json (per-card full "
            "summaries + per-sub-skill verdicts). Per-sub-skill packages under subskills/<short>/ "
            "re-group that substrate by question, each with its cards' summaries + figure paths."
        ),
    }
    manifest_json = out_dir / "MANIFEST.json"
    manifest_json.write_text(json.dumps(manifest, indent=2, default=str))

    # Human-readable index.
    lines = [
        f"# Full-package manifest — {target} in {indication}",
        "",
        f"Generated {generated_at} · skill {skill_name} v{skill_version}",
        "",
        "## Artifacts",
        "",
    ]
    labels = {
        "narrative_markdown": "Narrative (markdown)", "narrative_html": "Narrative (HTML)",
        "machine_nomination": "Machine record — nomination", "machine_evidence_package":
        "Machine envelope — evidence package (per-card summaries)", "provenance": "Provenance",
        "hero_figure": "Hero figure", "run_log": "Run log",
    }
    for k, v in manifest["artifacts"].items():
        lines.append(f"- **{labels.get(k, k)}** — [{v}]({v})")
    lines += ["", "## Sub-skill packages", "",
              "| Sub-skill | Verdict | Driving rule | Cards | Figures | Package |",
              "|---|---|---|---|---|---|"]
    for s in sub_index:
        lines.append(f"| {s['sub_skill']} | {s['verdict'] or '—'} | {s['driving_rule_id'] or '—'} | "
                     f"{s['n_cards']} | {s['n_figures']} | [{s['package']}]({s['package']}) |")
    lines += ["", f"Total figure files: {n_fig_total}", "",
              "## Where the data lives", "", manifest["where_the_data_lives"], ""]
    (out_dir / "MANIFEST.md").write_text("\n".join(lines))
    return manifest_json


__all__ = ["write_full_package"]
