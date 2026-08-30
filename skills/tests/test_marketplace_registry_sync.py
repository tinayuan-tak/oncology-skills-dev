"""Guard: the plugin marketplace registry must stay in sync with the on-disk skills.

`.claude-plugin/marketplace.json` lists the skills bundled by the oncology-skills plugin.
It had drifted from the filesystem — three real skills (cis-feature-coherence,
combination-and-vulnerability, literature-risk-assessment) were missing and the retired
compose-dashboard (#654) was still listed. Nothing failed on that drift; the framework-health
probe only reported it as an advisory `registry_drift` metric. This test makes the drift a HARD
failure: the registry's skill list must EXACTLY equal the set of on-disk skill dirs that carry a
SKILL.md (add a new skill / retire an old one → update marketplace.json in the same PR).
"""
from __future__ import annotations

import json
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent          # .../skills
REPO_ROOT = SKILLS_DIR.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def _registered_skills() -> set[str]:
    m = json.loads(MARKETPLACE.read_text())
    plugins = m["plugins"]
    # single oncology-skills plugin today; union defensively if that ever changes.
    paths: list[str] = []
    for p in plugins:
        paths.extend(p.get("skills", []))
    return {Path(p).name for p in paths}


def _on_disk_skills() -> set[str]:
    return {d.name for d in (SKILLS_DIR).iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()}


def test_marketplace_registry_matches_on_disk_skills():
    registered = _registered_skills()
    on_disk = _on_disk_skills()
    missing_from_registry = on_disk - registered      # a real skill not listed (the drift we fixed)
    stale_in_registry = registered - on_disk          # a listed skill that no longer exists (compose-dashboard)
    assert not missing_from_registry, (
        f"on-disk skills absent from .claude-plugin/marketplace.json: {sorted(missing_from_registry)} "
        "— add them to the plugin skills list.")
    assert not stale_in_registry, (
        f".claude-plugin/marketplace.json lists skills with no on-disk dir: {sorted(stale_in_registry)} "
        "— remove them (retired/renamed?).")


def test_marketplace_registry_paths_are_wellformed():
    m = json.loads(MARKETPLACE.read_text())
    for p in m["plugins"][0]["skills"]:
        assert p.startswith("./skills/"), f"unexpected skill path form: {p}"
        assert (REPO_ROOT / p.lstrip("./")).is_dir(), f"skill path does not resolve to a dir: {p}"
