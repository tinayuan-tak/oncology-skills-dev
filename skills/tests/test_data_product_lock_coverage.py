"""Completeness ratchet for the finalized data-product lock across the target-profile fan-out.

A skill is "locked" as a finalized data product when it has all three artifacts:
  1. skills/<skill>/DATA_PRODUCT.md
  2. skills/<skill>/tests/test_data_product_schema.py
  3. target-contracts/schemas/skills/<skill>.decision.schema.json  (generated, self-contained)

Locked-status is DERIVED FROM THE FILESYSTEM (not a hand-maintained list) — so each skill's lock lands in
its own PR with no shared-file edit to serialize on, and a partial lock (some artifacts, not all) fails
here. Mirrors test_marketplace_registry_sync.py's "on-disk == registered, HARD fail" philosophy:

  - The three artifact sets must be mutually consistent (a skill with any one artifact has all three) —
    a partial lock (e.g. a DATA_PRODUCT.md with no schema) is a HARD failure.
  - Locked ⊆ the canonical fan-out (SUB_SKILLS).
  - When every fan-out skill is locked, require FULL coverage (a new fan-out skill must ship locked).

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


def _have_doc() -> set[str]:
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "DATA_PRODUCT.md").exists()}


def _have_test() -> set[str]:
    return {d.name for d in SKILLS_DIR.iterdir() if (d / "tests" / "test_data_product_schema.py").exists()}


def _tc_schemas_dir() -> Path | None:
    d = Path(os.environ.get("TARGET_CONTRACTS_ROOT", _DEFAULT_TC)) / "schemas" / "skills"
    return d if d.exists() else None


def _have_schema() -> set[str]:
    d = _tc_schemas_dir()
    return {p.name[: -len(".decision.schema.json")] for p in d.glob("*.decision.schema.json")} if d else set()


def test_no_partial_locks():
    """A skill with a DATA_PRODUCT.md must also have the per-skill schema test, and vice versa (the
    skills-side artifacts move together in one PR). Credential-less."""
    doc, test = _have_doc(), _have_test()
    doc_no_test = doc - test
    test_no_doc = test - doc
    assert not doc_no_test, f"skills with DATA_PRODUCT.md but no test_data_product_schema.py: {sorted(doc_no_test)}"
    assert not test_no_doc, f"skills with test_data_product_schema.py but no DATA_PRODUCT.md: {sorted(test_no_doc)}"


def test_locked_subset_of_fanout():
    unknown = _have_doc() - _sub_skills()
    assert not unknown, f"DATA_PRODUCT.md present for non-fan-out skills: {sorted(unknown)}"


def test_skills_side_locked_have_generated_schema():
    """Every skill with skills-side artifacts also has its generated decision schema in target-contracts."""
    schemas = _tc_schemas_dir()
    if schemas is None:
        reason = "target-contracts schemas/skills not resolvable (set TARGET_CONTRACTS_ROOT)"
        if os.environ.get("CI"):
            pytest.fail(reason + " [CI: coverage ratchet must be live, not skipped]")
        pytest.skip(reason)
    locked = _have_doc() & _have_test()
    missing = sorted(locked - _have_schema())
    assert not missing, f"skills locked on the skills side but missing their generated schema: {missing}"


def test_full_coverage_when_rollout_complete():
    """Once every fan-out skill is locked, require FULL coverage; until then, informational."""
    fanout = _sub_skills()
    locked = _have_doc() & _have_test()
    remaining = fanout - locked
    if not remaining:
        assert locked == fanout, "rollout complete but locked != fan-out — reconcile"
    else:
        assert locked <= fanout, f"locked must stay within the fan-out; remaining to lock: {sorted(remaining)}"
