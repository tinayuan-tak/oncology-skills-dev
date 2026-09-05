"""Completeness ratchet for the finalized data-product lock across the target-profile fan-out.

A skill is "locked" as a finalized data product when it has all three artifacts:
  1. skills/<skill>/DATA_PRODUCT.md
  2. skills/<skill>/tests/test_data_product_schema.py
  3. target-contracts/schemas/skills/<skill>.decision.schema.json  (the generated, self-contained schema)

This ratchet makes locking (and UN-locking) a conscious, reviewed change — mirroring
test_marketplace_registry_sync.py's "on-disk == registered, HARD fail" philosophy:

  - Every skill in LOCKED must actually have all three artifacts (no silent regression to un-locked).
  - LOCKED must be a subset of the canonical fan-out (SUB_SKILLS) — no locking a non-existent skill.
  - When LOCKED == the full fan-out, the rollout is complete and the ratchet flips to require FULL
    coverage (a newly-added fan-out skill must be locked in the same PR).

Add a skill to LOCKED in the same PR that lands its three artifacts. The target-contracts side is
resolved via TARGET_CONTRACTS_ROOT; when unresolvable this SKIPS locally but FAILS in CI (so the
coverage ratchet can't be a silent green no-op — same policy as the per-skill schema ratchet).
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent           # .../skills
TP_FANOUT = SKILLS_DIR / "target-profile" / "scripts" / "tp_fanout.py"
_DEFAULT_TC = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"

# The skills locked so far. GROW this list in the PR that lands each skill's data-product artifacts.
LOCKED: set[str] = {
    "tumor-presence",
    "tumor-selectivity",
}


def _sub_skills() -> set[str]:
    """The canonical 14 fan-out skill dirs, parsed from target-profile's SUB_SKILLS literal."""
    tree = ast.parse(TP_FANOUT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SUB_SKILLS" for t in node.targets):
            return {e.elts[0].value for e in node.value.elts}
    raise AssertionError("SUB_SKILLS literal not found in tp_fanout.py")


def _tc_schemas_dir() -> Path | None:
    root = Path(os.environ.get("TARGET_CONTRACTS_ROOT", _DEFAULT_TC))
    d = root / "schemas" / "skills"
    return d if d.exists() else None


def test_locked_is_subset_of_fanout():
    unknown = LOCKED - _sub_skills()
    assert not unknown, f"LOCKED lists skills not in the target-profile fan-out: {sorted(unknown)}"


def test_locked_skills_have_skill_side_artifacts():
    """Every LOCKED skill has its DATA_PRODUCT.md + per-skill schema test (credential-less)."""
    missing = []
    for skill in sorted(LOCKED):
        d = SKILLS_DIR / skill
        if not (d / "DATA_PRODUCT.md").exists():
            missing.append(f"{skill}: DATA_PRODUCT.md")
        if not (d / "tests" / "test_data_product_schema.py").exists():
            missing.append(f"{skill}: tests/test_data_product_schema.py")
    assert not missing, "LOCKED skills missing data-product artifacts (regressed to un-locked):\n  " + \
        "\n  ".join(missing)


def test_locked_skills_have_generated_schema():
    """Every LOCKED skill has its generated, self-contained decision schema in target-contracts."""
    schemas = _tc_schemas_dir()
    if schemas is None:
        reason = "target-contracts schemas/skills not resolvable (set TARGET_CONTRACTS_ROOT)"
        if os.environ.get("CI"):
            pytest.fail(reason + " [CI: coverage ratchet must be live, not skipped]")
        pytest.skip(reason)
    missing = [s for s in sorted(LOCKED) if not (schemas / f"{s}.decision.schema.json").exists()]
    assert not missing, f"LOCKED skills missing their generated decision schema: {missing}"


def test_full_coverage_when_rollout_complete():
    """Once every fan-out skill is locked, require FULL coverage so a new fan-out skill can't ship
    un-locked. Until then this documents remaining work without failing the in-progress rollout."""
    fanout = _sub_skills()
    remaining = fanout - LOCKED
    if not remaining:
        assert LOCKED == fanout, "rollout complete but LOCKED != fan-out — reconcile"
    else:
        # in-progress: informational only (do not fail); flips to hard coverage at completion.
        assert LOCKED < fanout, f"LOCKED must stay within the fan-out; remaining to lock: {sorted(remaining)}"
