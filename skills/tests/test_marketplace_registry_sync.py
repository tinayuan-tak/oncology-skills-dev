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

SKILLS_DIR = Path(__file__).resolve().parent.parent  # .../skills
REPO_ROOT = SKILLS_DIR.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def _registered_skills() -> set[str]:
    m = json.loads(MARKETPLACE.read_text())
    plugins = m["plugins"]
    # Two entries since 2026-09-16: the live `oncology-skills` (source `./`, carries `skills:`)
    # and the archived `oncology-skills-v1` (a `git-subdir` source pinned to `legacy/v1`, which
    # resolves its own skills from that ref's manifest and therefore carries NO `skills:` key).
    # The union is over entries that declare one, so only the live entry contributes here — that
    # is what keeps this equality against the on-disk tree meaningful. See
    # test_only_the_local_plugin_entry_declares_skills below, which pins that asymmetry.
    paths: list[str] = []
    for p in plugins:
        paths.extend(p.get("skills", []))
    return {Path(p).name for p in paths}


def _on_disk_skills() -> set[str]:
    return {d.name for d in (SKILLS_DIR).iterdir() if d.is_dir() and (d / "SKILL.md").exists()}


def test_marketplace_registry_matches_on_disk_skills():
    registered = _registered_skills()
    on_disk = _on_disk_skills()
    missing_from_registry = on_disk - registered  # a real skill not listed (the drift we fixed)
    stale_in_registry = registered - on_disk  # a listed skill that no longer exists (compose-dashboard)
    assert not missing_from_registry, (
        f"on-disk skills absent from .claude-plugin/marketplace.json: {sorted(missing_from_registry)} "
        "— add them to the plugin skills list."
    )
    assert not stale_in_registry, (
        f".claude-plugin/marketplace.json lists skills with no on-disk dir: {sorted(stale_in_registry)} "
        "— remove them (retired/renamed?)."
    )


def _local_entry() -> dict:
    """The entry whose `source` is this working tree.

    Resolved by `source == "./"` rather than by position: `test_..._paths_are_wellformed` used to
    index `plugins[0]` positionally, which silently becomes a test of the WRONG entry the moment
    someone prepends one. That is exactly the mistake the archived-v1 entry had to be appended to
    avoid, so the constraint is now expressed instead of relied upon.
    """
    m = json.loads(MARKETPLACE.read_text())
    local = [p for p in m["plugins"] if p.get("source") == "./"]
    assert len(local) == 1, (
        f"expected exactly 1 marketplace entry with source './', found {len(local)}: {[p.get('name') for p in local]}"
    )
    return local[0]


def test_marketplace_registry_paths_are_wellformed():
    for p in _local_entry()["skills"]:
        assert p.startswith("./skills/"), f"unexpected skill path form: {p}"
        assert (REPO_ROOT / p.lstrip("./")).is_dir(), f"skill path does not resolve to a dir: {p}"


def test_only_the_local_plugin_entry_declares_skills():
    """A remote-pinned entry must not enumerate skills from THIS tree.

    `_registered_skills()` unions `skills:` across every entry and asserts set equality with the
    on-disk dirs. So a `skills:` array on the `legacy/v1` entry would inject v1's retired skill
    names (analysis-bulk-rna-crc, workflow-target-evaluation-onc, ...) into that union and red the
    sync test with a misleading "lists skills with no on-disk dir" message — the real fault being
    the array's existence, not the filesystem. Fail here first, with the actual reason.
    """
    m = json.loads(MARKETPLACE.read_text())
    for p in m["plugins"]:
        if p.get("source") == "./":
            continue
        assert "skills" not in p, (
            f"marketplace entry {p['name']!r} is not sourced from this tree (source="
            f"{p.get('source')!r}) but declares a `skills:` array. Remote/pinned sources resolve "
            "skills from their own ref's manifest — remove the array."
        )


def test_local_plugin_version_matches_marketplace_entry():
    """`.claude-plugin/plugin.json` and its marketplace entry must agree on `version`.

    Nothing else in the repo reads plugin.json — no test, no CI job, no script — which is how the
    two fields drifted to 1.7.5 vs 1.7.6 unnoticed and why promoting v2 to the trunk would have
    published a version BELOW the v1 plugin's 1.7.8. A version pair that no check compares is a
    version pair that diverges; this is that check.
    """
    plugin = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    entry = _local_entry()
    assert plugin["name"] == entry["name"], (
        f"plugin.json name {plugin['name']!r} != marketplace entry name {entry['name']!r}"
    )
    assert plugin["version"] == entry["version"], (
        f"version drift: .claude-plugin/plugin.json says {plugin['version']!r} but its "
        f"marketplace.json entry says {entry['version']!r} — bump both in the same commit."
    )
