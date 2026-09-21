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

# DATA_PRODUCT.md carries the same version in a markdown table row:
#   | **Skill code version** | 2.19.0 |
# Some rows trail explanatory text (e.g. "1.24.0 (see CONTRACT.md § Version history)"); the
# leading semver is the version, so capture the first x.y.z after the row label.
_DATA_PRODUCT_VERSION_RE = re.compile(r"\*\*Skill code version\*\*\s*\|\s*(\d+\.\d+\.\d+)")


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
        f"emitted data-package. Bump whichever is stale so both match."
    )


def _data_product_version(data_product_md: Path):
    m = _DATA_PRODUCT_VERSION_RE.search(data_product_md.read_text())
    return m.group(1) if m else None


def _skill_dirs_with_data_product():
    pairs = []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        run_py = skill_md.parent / "scripts" / "run.py"
        data_product = skill_md.parent / "DATA_PRODUCT.md"
        if run_py.exists() and data_product.exists():
            pairs.append((skill_md.parent.name, run_py, data_product))
    return pairs


_DP_PAIRS = _skill_dirs_with_data_product()


@pytest.mark.parametrize("name,run_py,data_product", _DP_PAIRS, ids=[p[0] for p in _DP_PAIRS])
def test_data_product_version_matches_stamped_version(name, run_py, data_product):
    """A skill's DATA_PRODUCT.md 'Skill code version' row must equal the stamped SKILL_VERSION.

    DATA_PRODUCT.md is the data-product spec a downstream consumer reads to learn which skill-code
    version produced a package. It is NOT covered by the SKILL.md parity test above and had drifted
    on 7 of the wired skills (2026-09-21 genomic-alteration audit). Skips a skill that lacks either a
    SKILL_VERSION constant or the version row, mirroring the SKILL.md test's both-present rule.
    """
    stamped = _run_py_version(run_py)
    documented = _data_product_version(data_product)
    if stamped is None or documented is None:
        pytest.skip(
            f"{name}: missing SKILL_VERSION ({stamped!r}) or DATA_PRODUCT.md 'Skill code version' row ({documented!r})"
        )
    assert documented == stamped, (
        f"{name}: DATA_PRODUCT.md 'Skill code version'={documented!r} but run.py "
        f"SKILL_VERSION={stamped!r}. These MUST agree — the version row documents which skill-code "
        f"version produced the emitted data-package. Bump the DATA_PRODUCT.md row to match."
    )


def test_at_least_one_pair_checked():
    """Sanity: the discovery glob actually found wired skills (guards a silent skip-everything)."""
    assert _PAIRS, "no skills with both SKILL.md and scripts/run.py were discovered"


def test_at_least_one_data_product_checked():
    """Sanity: the DATA_PRODUCT.md discovery found skills (guards a silent skip-everything)."""
    assert _DP_PAIRS, "no skills with both DATA_PRODUCT.md and scripts/run.py were discovered"
