"""Guard: the plugin marketplace registry must stay in sync with the on-disk skills.

`.claude-plugin/marketplace.json` lists the skills bundled by the oncology-skills plugin.
It had drifted from the filesystem — three real skills (cis-feature-coherence,
combination-and-vulnerability, literature-risk-assessment) were missing and the retired
compose-dashboard (#654) was still listed. Nothing failed on that drift; the framework-health
probe only reported it as an advisory `registry_drift` metric. This test makes the drift a HARD
failure: the registry's skill list must EXACTLY equal the set of on-disk skill dirs that carry a
SKILL.md (add a new skill / retire an old one → update marketplace.json in the same PR).

Since 2026-09-16 this file also guards the SHAPE of non-local entries. Nothing else in the repo
validates this manifest — no workflow, no script, no schema check — so a structurally valid JSON
document with a semantically broken `source` block passed every gate and shipped a plugin that
installed successfully with an empty payload. See
test_remote_entries_pin_an_immutable_commit_and_avoid_the_empty_subdir_shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent  # .../skills
REPO_ROOT = SKILLS_DIR.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SHA40_RE = re.compile(r"[0-9a-f]{40}")


def _registered_skills() -> set[str]:
    m = json.loads(MARKETPLACE.read_text())
    plugins = m["plugins"]
    # Two entries since 2026-09-16: the live `oncology-skills` (source `./`, carries `skills:`)
    # and the archived `oncology-skills-v1` (a `url` source pinned to the immutable commit
    # b46c8baf, which resolves its own skills from that commit's manifest and therefore carries
    # NO `skills:` key).
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
    on-disk dirs. So a `skills:` array on the archived v1 entry would inject v1's retired skill
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


def test_remote_entries_pin_an_immutable_commit_and_avoid_the_empty_subdir_shape():
    """A non-local entry must pin a 40-hex `sha`, and must not spell "the repo root" as a subdir.

    Both halves exist because the archived v1 entry shipped BROKEN on 2026-09-16 and every cheap
    signal was green. It declared `{"source": "git-subdir", "path": ".", "ref": "legacy/v1"}`, and
    `claude plugin install` returned `outcome: ok` reporting `Version: 1.7.8` while materialising an
    EMPTY payload — no `.claude-plugin/`, no `skills/`, 4 of the commit's 89 files.

    - `git-subdir` is for a plugin that lives in a SUBDIRECTORY. `path: "."` produces the
      sparse-checkout pattern pair `/*` then `!/*/` — "take root files, exclude every directory" —
      so the skills and the manifest were in the commit and simply never checked out. `path` is
      REQUIRED for that source type (omitting it fails validation with `source.path: Invalid
      input`), so there is no way to spell the repo root with it: a whole-repo plugin wants
      `"source": "url"` and no `path` key at all.
    - The reported `Version` came from THIS file's own `version` field, not from the fetched
      `plugin.json` — which never materialised. So the version echo is independent of whether any
      payload arrived and cannot be used as evidence that one did.
    - The `sha` requirement is about reproducibility: an archive pinned to a mutable branch `ref`
      silently changes meaning if anyone ever pushes to that branch, which defeats the point of
      archiving. `legacy/v1` is frozen via branch protection, but a pin that does not DEPEND on
      that protection is strictly better.

    LIMIT, stated deliberately rather than left implicit: this is a STATIC shape check. It cannot
    prove a payload materialises — only a real `claude plugin marketplace add` + `install` can, by
    comparing `git -C <cache-dir> ls-files | wc -l` against that commit's own
    `git ls-tree -r --name-only <sha> | wc -l`. Equal counts mean the payload arrived; a shortfall
    is a sparse checkout lying to you. Do that once by hand whenever a `source` block changes. This
    guard only closes the two shapes now known to fail silently.
    """
    m = json.loads(MARKETPLACE.read_text())
    for p in m["plugins"]:
        if p.get("source") == "./":
            continue
        name = p.get("name")
        src = p.get("source")
        assert isinstance(src, dict), (
            f"marketplace entry {name!r} has a non-local source that is not an object: {src!r} — "
            "a remote entry must be an object carrying an immutable `sha`."
        )
        if src.get("source") == "git-subdir":
            assert src.get("path") not in (".", "./", "", None), (
                f"marketplace entry {name!r} uses source `git-subdir` with path={src.get('path')!r}, "
                "which sparse-checks-out root files ONLY and installs an EMPTY plugin while still "
                'reporting `outcome: ok`. For a whole-repo plugin use `"source": "url"` with no '
                "`path` key; reserve `git-subdir` for a plugin in a real subdirectory."
            )
        sha = src.get("sha")
        assert isinstance(sha, str) and SHA40_RE.fullmatch(sha), (
            f"marketplace entry {name!r} must pin an immutable 40-hex `sha` (got {sha!r}). A branch "
            "or tag `ref` alone can move, which silently changes what an 'archived' plugin means."
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
