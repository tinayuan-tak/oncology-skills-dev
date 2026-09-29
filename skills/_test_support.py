"""Shared test-support helpers for the skills test suites (importable helpers, NOT pytest fixtures).

Tests already put skills/ on sys.path (`sys.path.insert(0, SKILLS_ROOT)`), so this module is importable
as `_test_support`. It deliberately does NOT live under `_skills_common` (that is production code) and is
not itself a test module (pytest never collects it — no `test_` prefix).

It removes the most-copied test boilerplate: the "load a script as an isolated module" triple
    spec = importlib.util.spec_from_file_location(NAME, PATH)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
which was re-declared as a local `_load()` (or an ad-hoc `import run as X`) in ~180 test files.
`load_module()` is that triple; `load_run_py()` is the run.py convenience wrapper.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module(path, name: str | None = None):
    """Load the Python file at `path` as a fresh, isolated module and return it.

    The module is executed but NOT registered in sys.modules, so loading many scripts (e.g. several
    skills' run.py) in one process never cross-contaminates — preserving the isolation the hand-rolled
    `spec_from_file_location(...)` shims relied on. `name` sets the module __name__ (useful in
    tracebacks); it defaults to the file stem and is otherwise cosmetic.
    """
    path = Path(path)
    spec = importlib.util.spec_from_file_location(name or path.stem, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load a module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_run_py(skill_dir, name: str | None = None):
    """Load a skill's scripts/run.py as an isolated module (see `load_module`).

    Ensures skills/ and the skill's scripts/ are on sys.path first so run.py's own imports
    (`_skills_common`, sibling scripts) resolve — replacing the per-file `sys.path.insert(...)` +
    `def _load()` (or `import run as X`) boilerplate. `skill_dir` is the skill root (skills/<skill>/).
    """
    skill_dir = Path(skill_dir)
    for p in (skill_dir.parent, skill_dir / "scripts"):  # skills/ , skills/<skill>/scripts/
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return load_module(skill_dir / "scripts" / "run.py", name=name)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# data-product schema conformance — shared body of skills/<skill>/tests/test_data_product_schema.py.
# Every per-skill guard re-declared a byte-identical `_schema_or_gate()` + `test_schema_is_wellformed`
# and one of two conformance shapes (soft static-golden / hard full-emit). Those live here now; the
# per-skill files keep only their SKILL id, golden path, docstring, and any bespoke-identity assertions.
# ─────────────────────────────────────────────────────────────────────────────────────────────────


def _data_product_contract():
    """Import the shared load/validate helpers lazily, so importing _test_support never hard-requires
    the contracts tree — a missing schema is handled by `schema_or_gate` (CI-fail / local-skip)."""
    from _skills_common.data_product_contract import (
        conformance_errors,
        is_full_decision,
        load_schema,
        schema_path,
    )

    return conformance_errors, is_full_decision, load_schema, schema_path


def schema_or_gate(skill: str, kind: str | None = None) -> dict:
    """Return a skill's data-product schema, or GATE on its absence: FAIL in CI (the ratchet must be
    live, never a vacuous skip) / SKIP locally. `kind` selects a non-default variant (e.g. "emit")."""
    import os

    import pytest

    _, _, load_schema, schema_path = _data_product_contract()
    schema = load_schema(skill, kind) if kind else load_schema(skill)
    if schema is not None:
        return schema
    where = schema_path(skill, kind) if kind else schema_path(skill)
    label = f"data-product {kind}" if kind else "data-product"
    reason = f"{label} schema not found at {where} — set TARGET_CONTRACTS_ROOT / land the contracts schema PR first"
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the ratchet must be live, not skipped]")
    pytest.skip(reason)


def check_schema_wellformed(skill: str, kind: str | None = None) -> None:
    """The schema is a valid Draft 2020-12 schema and carries a contract `version`."""
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    schema = schema_or_gate(skill, kind)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def conformance_or_fail(schema: dict, decision: dict, what: str = "emit") -> None:
    """Validate `decision` against `schema`; raise with the first 15 errors if any."""
    conformance_errors, _, _, _ = _data_product_contract()
    errors = conformance_errors(schema, decision)
    assert not errors, f"{what} violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


def check_static_golden_conforms(skill: str, golden, *, require_full_emit: bool = False) -> None:
    """Conformance of a committed golden decision against the skill's data-product schema.

    Soft (default): a MISSING or TRIMMED golden SKIPS (the fresh replay emit is the load-bearing
    target). Hard (`require_full_emit=True`, the full-emit ratchet): a missing / non-full-decision
    golden is a FAILURE, not a skip."""
    import json

    import pytest

    pytest.importorskip("jsonschema")
    _, is_full_decision, _, _ = _data_product_contract()
    schema = schema_or_gate(skill)
    golden = Path(golden)
    if not golden.exists():
        if require_full_emit:
            raise AssertionError(f"missing full-emit conformance fixture {golden}")
        pytest.skip(f"no golden at {golden}")
    decision = json.loads(golden.read_text())
    if not is_full_decision(decision):
        if require_full_emit:
            raise AssertionError("fixture is not a full decision — refreeze from a real run.py emit")
        pytest.skip("golden is a trimmed fixture (not a full decision) — see the replay conformance test")
    conformance_or_fail(schema, decision, "full emit" if require_full_emit else "static golden")


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# offline-fixture freezing — shared body of skills/<skill>/tests/freeze_fixture.py. `prune_oversized`
# was byte-identical across all 11 freezers; `freeze_card_summaries` is the shared live-read loop.
# Each per-skill freezer keeps only its card enumeration + argparse main (some are bespoke:
# target-intrinsic is indication-free, target-profile freezes a fan-out UNION).
# ─────────────────────────────────────────────────────────────────────────────────────────────────

FREEZE_FIELD_BYTES_CAP = 3000  # replace list/dict field values larger than this with a compact sentinel


def prune_oversized(summary, cap: int = FREEZE_FIELD_BYTES_CAP):
    """Replace OVERSIZED list/dict payloads (never read by the verdict/headline) with a compact scalar
    sentinel; keep every KEY (a field RENAME is still caught) + all scalars. Identical rule across
    every sibling freezer."""
    import json

    if not isinstance(summary, dict):
        return summary
    out = {}
    for k, v in summary.items():
        if isinstance(v, (list, dict)) and len(json.dumps(v, default=str)) > cap:
            out[k] = f"__omitted_from_fixture__ ({type(v).__name__}, {len(v)} items)"
        else:
            out[k] = v
    return out


def freeze_card_summaries(cards, target: str, indication: str, read_live, cap: int = FREEZE_FIELD_BYTES_CAP) -> dict:
    """Live-read each card summary for (target, indication) and prune it; return {card_id: summary}.
    A per-card read fault is recorded (never aborts the freeze), mirroring the hand-rolled loop."""
    frozen: dict = {}
    for card in cards:
        try:
            summary = read_live(card, target, indication)
        except Exception as e:  # noqa: BLE001 — record, never abort the freeze
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = prune_oversized(summary, cap) if summary is not None else {"_dispatcher_returned_none": True}
    return frozen
