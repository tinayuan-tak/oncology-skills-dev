"""Emitted data-product contract guard for surfaceome-cohort-ranking (AUX, gateless-descriptive scan).

Pins the emitted decision.json shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/surfaceome-cohort-ranking.decision.schema.json`. Shared helpers live in
`_skills_common.data_product_contract`. This is a GATELESS DESCRIPTIVE ranking scan (∉ target-profile
`_SHORT_TO_GATE`): the unified `skill_report` carries `call=None`, `role=descriptive`,
`polarity=not_scored`, and `headline.cohort_rank_class` is a percentile READOUT (not a nomination gate).

Conformance target = the FRESH in-process emit: the real run.py `main()` runs over a frozen REAL reader
return (only the S3-backed `_load_ranking` is stubbed), so the validated decision.json is exactly what a
live run produces — no hand-frozen decision fixture to go stale. MSLN/COADREAD is a top_5-tier,
fully-populated target_context spine (a non-degraded emit). Credential-less + offline.

CI-liveness: schema unresolvable → SKIP locally, FAIL under CI (the lock ratchet must be live).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

SKILL = "surfaceome-cohort-ranking"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FIXTURES = SKILL_DIR / "tests" / "fixtures"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    is_full_decision,
    load_schema,
    schema_path,
)
from _test_support import load_run_py  # noqa: E402


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL)
    if schema is not None:
        return schema
    reason = (
        f"data-product schema not found at {schema_path(SKILL)} — set TARGET_CONTRACTS_ROOT / "
        f"land the contracts schema PR first"
    )
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the lock ratchet must be live, not skipped]")
    pytest.skip(reason)


def _frozen_ranking() -> dict:
    fx = FIXTURES / "surfaceome_cohort_ranking_ranking.json"
    return json.loads(fx.read_text())


def _fresh_emit() -> dict:
    """Run the REAL run.py main() over the frozen reader return (only the S3-backed `_load_ranking` is
    stubbed), so the emitted decision.json is a fresh, credential-less emit of the real emit path."""
    frozen = _frozen_ranking()

    mod = load_run_py(SKILL_DIR, name="surfaceome_cohort_ranking_run")

    def _fake_load_ranking(indication, target):  # signature-compatible with the real _load_ranking
        r = copy.deepcopy(frozen)
        r.pop("_note", None)
        return r

    out_dir = Path(tempfile.mkdtemp(prefix="scr-dp-"))
    mp = pytest.MonkeyPatch()
    mp.setattr(mod, "_load_ranking", _fake_load_ranking)
    mp.setattr(sys, "argv", ["run.py", "--indication", "COADREAD", "--target", "MSLN", "--out", str(out_dir)])
    try:
        rc = mod.main()
        assert rc in (0, None), f"run.py main() returned non-zero ({rc}) on the MSLN/COADREAD replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json on the MSLN/COADREAD replay"
    return json.loads(decision_path.read_text())


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_fresh_emit_conforms():
    """The fresh emit must validate — the load-bearing conformance target. Confirms the gateless-
    descriptive spine: role descriptive, polarity not_scored, call None (no verdict)."""
    pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    decision = _fresh_emit()
    assert is_full_decision(decision), (
        "emit is not a full decision (missing envelope provenance/run_health or headline.skill_report) "
        "— the emitter backfill regressed"
    )
    sr = decision["headline"]["skill_report"]
    assert sr["call"] is None, f"gateless scan: skill_report.call must be None, got {sr['call']!r}"
    assert sr["role"] == "descriptive" and sr["polarity"] == "not_scored", (
        f"expected descriptive/not_scored spine, got role={sr['role']!r} polarity={sr['polarity']!r}"
    )
    assert isinstance(sr.get("honest_phrase"), str) and sr["honest_phrase"], (
        "skill_report.honest_phrase must be a non-empty string"
    )
    assert (sr.get("confidence") or {}).get("level"), "skill_report.confidence must carry a level"
    # the pinned facet — MSLN is a top_5 target in this indication (from the frozen real reader return)
    assert decision["headline"].get("cohort_rank_class") == "top_5", (
        "cohort_rank_class facet regressed vs the frozen reader return"
    )
    errors = conformance_errors(schema, decision)
    assert not errors, "fresh emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
