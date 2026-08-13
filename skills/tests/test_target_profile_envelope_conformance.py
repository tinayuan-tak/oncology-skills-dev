"""Guard (#9): cross-engine governance / audit-spine conformance between target-profile and the
shared evidence-package envelope writer.

Phase D unified the verdict engine AND the evidence-package envelope writer into _skills_common
(compose-dashboard now emits via `assemble_evidence_package`, and the duplicate `fit_level` verdict
engine was deleted). target-profile, however, still HAND-BUILDS its own governance / provenance /
nomination output instead of the shared writer — the one residual "two-engine drift" surface. The
stated Phase-D goal is that "a new evidence facet can no longer drift between two engines"; this guard
enforces that for the audit spine that MUST stay shared, and encodes the pending convergence as a
strict-xfail executable spec that auto-flags the day target-profile adopts the shared envelope.

Couples the two engines on purpose: it CALLS the shared writer (runtime) to read the authoritative
governance schema, and AST-parses target-profile/run.py (static) to read its hand-built governance —
so a drift on EITHER side trips the test. No live S3 / Bedrock; the shared writer is a pure function.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent
TP_RUN = SKILLS / "target-profile" / "scripts" / "run.py"

# The reproducibility spine both engines MUST carry in governance. release_pin is the eval-ledger
# federation key; data_mode records live-vs-pinned. Dropping either silently breaks reproducibility
# and cross-engine comparability — exactly the drift Phase D set out to make impossible.
_GOVERNANCE_REPRO_SPINE = {"data_mode", "release_pin"}


def _last_dict_literal_keys(pyfile: Path, var_name: str) -> "set[str] | None":
    """String keys of the LAST `var_name = {..}` dict-literal assignment in `pyfile` (None if absent)."""
    keys = None
    for node in ast.walk(ast.parse(pyfile.read_text())):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            if any(isinstance(t, ast.Name) and t.id == var_name for t in node.targets):
                keys = {k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys


def _shared_envelope_governance_keys() -> "set[str]":
    """Authoritative governance-block keys from the shared writer (runtime; pure function)."""
    if str(SKILLS) not in sys.path:
        sys.path.insert(0, str(SKILLS))
    from _skills_common.envelope import assemble_evidence_package  # noqa: E402
    pkg = assemble_evidence_package(
        input_context={"target_symbol": "KRAS", "indication": "COADREAD", "data_mode": "live_latest"},
        card_outputs=[],
        validation_summary={"n_cards": 0},
        synthesis_block={},
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/tests@conformance",
        dashboard_spec_ref="skill:target-profile",
    )
    return set(pkg["governance"].keys())


_SHARED_GOV = _shared_envelope_governance_keys()
_TP_GOV = _last_dict_literal_keys(TP_RUN, "governance")


def test_shared_envelope_governance_carries_the_reproducibility_spine():
    # Pin the shared side too: if the envelope writer drops data_mode/release_pin, the cross-engine
    # comparison below would pass vacuously — so anchor the authoritative schema first.
    missing = _GOVERNANCE_REPRO_SPINE - _SHARED_GOV
    assert not missing, f"shared envelope governance dropped reproducibility keys: {missing}"


def test_target_profile_governance_carries_the_shared_reproducibility_spine():
    assert _TP_GOV is not None, f"could not find a `governance = {{...}}` literal in {TP_RUN}"
    missing = _GOVERNANCE_REPRO_SPINE - _TP_GOV
    assert not missing, (
        f"target-profile governance dropped {missing} — breaks cross-engine reproducibility with the "
        f"shared evidence-package envelope (release_pin is the eval-ledger federation key).")


def test_target_profile_sub_verdict_keeps_the_audit_spine():
    """Each per-sub-skill record must retain driving_rule_id + cards_used + fired_rule_ids — the
    deterministic audit spine (which rule fired the verdict, over which resolved cards). These make a
    run reproducible + keyable by an eval ledger; losing them re-opens the silent-drift gap."""
    src = TP_RUN.read_text()
    for field in ("driving_rule_id", "cards_used", "fired_rule_ids"):
        assert f'"{field}"' in src, f"target-profile sub_verdict record lost the audit-spine field {field!r}"


@pytest.mark.xfail(
    strict=True,
    reason="#9 convergence pending: target-profile hand-builds governance WITHOUT validation_summary; "
           "compose-dashboard emits it via the shared _skills_common.assemble_evidence_package. When "
           "target-profile adopts the shared envelope this XPASSes — remove the xfail and close #9.",
)
def test_target_profile_governance_has_validation_summary_once_converged():
    # Executable spec for the end-state: target-profile's governance should carry validation_summary
    # (via the shared writer) just like compose-dashboard. Strict-xfail so the day it lands, CI flags it.
    assert "validation_summary" in _SHARED_GOV          # sanity: the shared side has it
    assert _TP_GOV is not None and "validation_summary" in _TP_GOV
