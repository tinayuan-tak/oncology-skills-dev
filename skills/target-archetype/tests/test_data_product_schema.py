"""Emitted data-product contract guard for target-archetype.

BESPOKE aux skill: its output is the verdict-INERT companion `doc` (`companion.json`), NOT the fan-out
`skill_decision` envelope — so it is pinned against the HAND-AUTHORED, self-contained
`target-contracts/schemas/skills/target-archetype.emit.schema.json` (loaded with the `suffix="emit"` arg,
NOT the generated `.decision.` schema). Shared helpers in `_skills_common.data_product_contract`.

The load-bearing conformance is a FRESH in-process emit: the real `scripts/run.py` over a minimal
`--full-package` fixture tree (offline + deterministic; the skill ships `atlas/atlas.json`). We do NOT use
`is_full_decision` (that checks the fan-out envelope this skill has no part of); instead we assert the
bespoke identity marker inline (`skill == "target-archetype"`, `verdict is None`). CI-liveness: schema
unresolvable → SKIP locally, FAIL in CI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = "target-archetype"
SUFFIX = "emit"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors, load_schema, schema_path)


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL, SUFFIX)
    if schema is not None:
        return schema
    reason = (f"data-product schema not found at {schema_path(SKILL, SUFFIX)} — set TARGET_CONTRACTS_ROOT / "
              f"land the contracts schema PR first")
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the ratchet must be live, not skipped]")
    pytest.skip(reason)


def _fresh_emit(tmp_path: Path) -> dict:
    """Produce ONE real emit: run the standalone CLI over a minimal full-package tree (one sub-skill
    claim_vector + a nomination.json with a fired rule) and read the emitted companion.json. Offline +
    deterministic — the skill ships its frozen atlas; no cards, no network, no Bedrock."""
    pkg = tmp_path / "run"
    (pkg / "subskills" / "genomic_alteration").mkdir(parents=True)
    (pkg / "subskills" / "genomic_alteration" / "package.json").write_text(json.dumps({
        "sub_skill": "genomic_alteration",
        "claim_vector": {"SNV": {"signal": "strong", "corroboration": "high"}},
    }))
    (pkg / "nomination.json").write_text(json.dumps({
        "target": "KRAS", "indication": "COADREAD",
        "sub_verdicts": {"genomic_alteration": {"fired_rule_ids": ["ga.snv.recurrent_driver"]}},
    }))
    r = subprocess.run([sys.executable, str(RUN_PY), "--package-dir", str(pkg)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"run.py exited {r.returncode}:\n{r.stderr}"
    return json.loads((pkg / "companion.json").read_text())


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_fresh_emit_conforms_to_data_product_schema(tmp_path):
    """The FRESH in-process emit must satisfy the bespoke emit schema (identity + verdict=null + the
    classification vocabularies; numeric payload schema-open)."""
    schema = _schema_or_gate()
    decision = _fresh_emit(tmp_path)
    # bespoke identity marker (this skill has no fan-out envelope, so NOT is_full_decision)
    assert decision["skill"] == "target-archetype"
    assert decision["verdict"] is None
    errors = conformance_errors(schema, decision)
    assert not errors, "fresh emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15])
