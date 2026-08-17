"""Guard: a skill's declared version must equal the version it STAMPS into provenance.

Every wired skill carries its version in TWO places that must agree:
  - SKILL.md frontmatter `metadata.version` — the declared contract a reader/collaborator sees.
  - scripts/run.py `SKILL_VERSION = "..."` — the value written into every run's provenance.yaml
    (via run_wired_skill(skill_version=SKILL_VERSION)).

If they drift, every emitted data-package mislabels its own provenance while the SKILL.md advertises a
different version — a silent integrity bug that matters precisely because these packages are shared and
audited. This caught tumor-selectivity stamping 1.6.0 while SKILL.md declared 1.8.0 (2026-08-17 review).

Regex/YAML-only (no imports, no live reads). Only checks skills that have BOTH files; placeholder skills
without a run.py, or a run.py without a SKILL_VERSION constant, are skipped (not all skills stamp one).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parent.parent

_SKILL_VERSION_RE = re.compile(r'^\s*SKILL_VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def _frontmatter_version(skill_md: Path):
    text = skill_md.read_text()
    if not text.startswith("---"):
        return None
    # frontmatter is the block between the first two '---' fences
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = yaml.safe_load(parts[1]) or {}
    return (meta.get("metadata") or {}).get("version")


def _run_py_version(run_py: Path):
    m = _SKILL_VERSION_RE.search(run_py.read_text())
    return m.group(1) if m else None


def _skill_dirs_with_both():
    pairs = []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        run_py = skill_md.parent / "scripts" / "run.py"
        if run_py.exists():
            pairs.append((skill_md.parent.name, skill_md, run_py))
    return pairs


_PAIRS = _skill_dirs_with_both()


@pytest.mark.parametrize("name,skill_md,run_py", _PAIRS, ids=[p[0] for p in _PAIRS])
def test_skill_md_version_matches_stamped_version(name, skill_md, run_py):
    declared = _frontmatter_version(skill_md)
    stamped = _run_py_version(run_py)
    if declared is None or stamped is None:
        pytest.skip(f"{name}: missing metadata.version ({declared!r}) or SKILL_VERSION ({stamped!r})")
    assert declared == stamped, (
        f"{name}: SKILL.md metadata.version={declared!r} but run.py SKILL_VERSION={stamped!r}. "
        f"These MUST agree — SKILL_VERSION is stamped into provenance.yaml; a drift mislabels every "
        f"emitted data-package. Bump whichever is stale so both match.")


def test_at_least_one_pair_checked():
    """Sanity: the discovery glob actually found wired skills (guards a silent skip-everything)."""
    assert _PAIRS, "no skills with both SKILL.md and scripts/run.py were discovered"
