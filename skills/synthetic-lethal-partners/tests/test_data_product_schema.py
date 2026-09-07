"""Emitted data-product contract guard for synthetic-lethal-partners (AUX, verdict-bearing veto-suppressor).

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/synthetic-lethal-partners.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. Descriptive-scalar (gateless veto-suppressor ∉ _SHORT_TO_GATE →
`skill_report.role=descriptive`, `polarity=not_scored`, `call=sl_partner_verdict`).

Conformance target = the FRESH replay emit: this reuses the offline dossier-replay harness (the drift
guard in test_sl_partners_replay.py) — the real run.py over a frozen real reader summary with only the
live dispatcher monkeypatched — so the emitted decision.json validated here is exactly what a live run
produces (no stale hand-frozen fixture). CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

import copy
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

import pytest

SKILL = "synthetic-lethal-partners"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"
# SMARCA2 = the crown-jewel has_experimental_sl_partner verdict (a fully-exercised, non-collapsed spine).
_FIXTURE = ("smarca2_coadread", "SMARCA2", "COADREAD")

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    is_full_decision,
    load_schema,
    schema_path,
)


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL)
    if schema is not None:
        return schema
    reason = (
        f"data-product schema not found at {schema_path(SKILL)} — set TARGET_CONTRACTS_ROOT / "
        f"land the contracts schema PR first"
    )
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the ratchet must be live, not skipped]")
    pytest.skip(reason)


def _fresh_emit() -> dict:
    """Run the REAL run.py over the frozen real reader summary (only the live dispatcher monkeypatched),
    exactly as test_sl_partners_replay.py does — a fresh, credential-less emit."""
    import yaml

    pair_id, target, indication = _FIXTURE
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    frozen = yaml.safe_load(fx.read_text()) or {}

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not (
                isinstance(s, dict) and s and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")
            ):
                return None
            return copy.deepcopy(s)

        return _read_live

    out_dir = Path(tempfile.mkdtemp(prefix="sl-dp-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    return json.loads(decision_path.read_text())


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_fresh_emit_conforms():
    """The fresh replay emit must validate — the load-bearing conformance target. Confirms the
    descriptive-scalar spine: role descriptive, polarity not_scored, call = sl_partner_verdict."""
    pytest.importorskip("jsonschema")
    pytest.importorskip("yaml")
    schema = _schema_or_gate()
    decision = _fresh_emit()
    assert is_full_decision(decision), (
        "emit is not a full decision (missing envelope / headline.skill_report) — the emitter patch regressed"
    )
    sr = decision["headline"]["skill_report"]
    assert sr["role"] == "descriptive" and sr["polarity"] == "not_scored", (
        f"expected descriptive/not_scored spine, got role={sr['role']!r} polarity={sr['polarity']!r}"
    )
    assert sr["call"] == decision["headline"].get("sl_partner_verdict"), (
        "skill_report.call must mirror sl_partner_verdict"
    )
    errors = conformance_errors(schema, decision)
    assert not errors, "fresh emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
