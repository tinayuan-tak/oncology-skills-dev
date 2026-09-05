"""Completeness ratchet for the finalized data-product lock.

A skill is "locked" as a finalized data product when it has all three artifacts:
  1. skills/<skill>/DATA_PRODUCT.md
  2. skills/<skill>/tests/test_data_product_schema.py
  3. target-contracts/schemas/skills/<skill>.*.schema.json  (its per-skill emitted-output schema)

Locked-status is DERIVED FROM THE FILESYSTEM (not a hand-maintained list) — each skill's lock lands in its
own PR with no shared-file edit to serialize on, and a partial lock (some artifacts, not all) fails here.

Two skill populations are lockable:
  - the target-profile FAN-OUT (SUB_SKILLS) — these MUST all be locked (full-coverage requirement below);
  - AUXILIARY (non-fan-out) skills — standalone verdict skills, ranking scans, and bespoke reducers — lock
    ADDITIVELY (allowed, never required). Their schema may be the standard `<skill>.decision.schema.json`
    (envelope-emitting skills) or a bespoke `<skill>.<artifact>.schema.json` (e.g. companion / hypothesis /
    risk_assessment) — hence the `<skill>.*.schema.json` glob.

Invariants (mirror test_marketplace_registry_sync.py's "on-disk == registered, HARD fail"):
  - No partial locks (doc ⇔ test ⇔ schema move together).
  - Locked ⊆ the on-disk skill dirs (a DATA_PRODUCT.md for a non-existent skill fails).
  - Every FAN-OUT skill stays locked; when the fan-out is fully locked, a new fan-out skill must ship locked.

target-contracts is resolved via TARGET_CONTRACTS_ROOT; unresolvable → SKIP locally, FAIL in CI.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent           # .../skills
TP_FANOUT = SKILLS_DIR / "target-profile" / "scripts" / "tp_fanout.py"
_DEFAULT_TC = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"


def _sub_skills() -> set[str]:
    """The canonical fan-out skill dirs, parsed from target-profile's SUB_SKILLS literal."""
    tree = ast.parse(TP_FANOUT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SUB_SKILLS" for t in node.targets):
            return {e.elts[0].value for e in node.value.elts}
    raise AssertionError("SUB_SKILLS literal not found in tp_fanout.py")


def _all_skill_dirs() -> set[str]:
    """Every on-disk skill dir (carries a SKILL.md)."""
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").exists()}


def _have_doc() -> set[str]:
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "DATA_PRODUCT.md").exists()}


def _have_test() -> set[str]:
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "tests" / "test_data_product_schema.py").exists()}


def _tc_schemas_dir() -> Path | None:
    d = Path(os.environ.get("TARGET_CONTRACTS_ROOT", _DEFAULT_TC)) / "schemas" / "skills"
    return d if d.exists() else None


def _have_schema() -> set[str]:
    """Skills with SOME per-skill emitted-output schema — the standard <skill>.decision.schema.json OR a
    bespoke <skill>.<artifact>.schema.json (companion/hypothesis/risk_assessment/...)."""
    d = _tc_schemas_dir()
    if not d:
        return set()
    have: set[str] = set()
    known = _all_skill_dirs()
    for p in d.glob("*.schema.json"):
        stem = p.name[: -len(".schema.json")]          # e.g. "tumor-presence.decision" | "target-archetype.companion"
        skill = stem.rsplit(".", 1)[0] if "." in stem else stem
        if skill in known:
            have.add(skill)
    return have


def test_no_partial_locks():
    """A skill with a DATA_PRODUCT.md must also have the per-skill schema test, and vice versa (the
    skills-side artifacts move together in one PR). Credential-less."""
    doc, test = _have_doc(), _have_test()
    doc_no_test = doc - test
    test_no_doc = test - doc
    assert not doc_no_test, f"skills with DATA_PRODUCT.md but no test_data_product_schema.py: {sorted(doc_no_test)}"
    assert not test_no_doc, f"skills with test_data_product_schema.py but no DATA_PRODUCT.md: {sorted(test_no_doc)}"


def test_locked_subset_of_known_skills():
    """A DATA_PRODUCT.md must belong to a real on-disk skill (fan-out OR auxiliary)."""
    unknown = _have_doc() - _all_skill_dirs()
    assert not unknown, f"DATA_PRODUCT.md present for non-existent skill dirs: {sorted(unknown)}"


def test_skills_side_locked_have_a_schema():
    """Every skill with skills-side artifacts also has a per-skill schema in target-contracts (standard
    decision schema or a bespoke output schema)."""
    schemas = _tc_schemas_dir()
    if schemas is None:
        reason = "target-contracts schemas/skills not resolvable (set TARGET_CONTRACTS_ROOT)"
        if os.environ.get("CI"):
            pytest.fail(reason + " [CI: coverage ratchet must be live, not skipped]")
        pytest.skip(reason)
    locked = _have_doc() & _have_test()
    missing = sorted(locked - _have_schema())
    assert not missing, f"skills locked on the skills side but missing a per-skill schema: {missing}"


def test_full_coverage_of_the_fanout():
    """Every FAN-OUT skill must be locked; auxiliary locks are additive (never required)."""
    fanout = _sub_skills()
    locked = _have_doc() & _have_test()
    remaining = fanout - locked
    assert not remaining, f"fan-out skills not yet locked (must all be locked): {sorted(remaining)}"
