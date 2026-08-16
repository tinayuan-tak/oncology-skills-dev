"""Guard (#9): cross-engine governance / audit-spine conformance between target-profile and the
shared evidence-package envelope writer.

#9 CONVERGED (this PR): target-profile no longer hand-builds its governance block. Both composition
engines now build governance through the SINGLE shared source `_skills_common.envelope.build_governance`
(compose-dashboard via `assemble_evidence_package`; target-profile directly), so the block — including
the 5-field `validation_summary` — cannot drift between them. That was the last residual of the Phase-D
two-engine unification for this surface. This guard now ENFORCES the single-sourcing (so a future refactor
can't reintroduce a divergent hand-built governance) and pins the schema-shaped validation_summary + the
per-sub-verdict audit spine.

Couples the two engines on purpose: it CALLS the shared builder (runtime, pure fn) and AST-parses both
`_skills_common/envelope.py` and `target-profile/run.py` (static) to prove each routes through it. No
live S3 / Bedrock.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent
TP_RUN = SKILLS / "target-profile" / "scripts" / "run.py"
# The validation_summary literal moved out of run.py into tp_evidence_package.py in the 2026-08-16
# god-module split (build_governance is still CALLED from run.py's main(), so TP_RUN stays correct there).
TP_EVIDENCE = SKILLS / "target-profile" / "scripts" / "tp_evidence_package.py"
ENVELOPE = SKILLS / "_skills_common" / "envelope.py"

# The reproducibility spine every governance block MUST carry. release_pin is the eval-ledger federation
# key; data_mode records live-vs-pinned. validation_summary is the 5-field card-outcome roll-up.
_GOVERNANCE_REPRO_SPINE = {"data_mode", "release_pin", "validation_summary"}

# The evidence_package schema's governance.validation_summary object (required, unevaluatedProperties:false).
_VALIDATION_SUMMARY_KEYS = {
    "n_cards_attempted", "n_cards_passed", "n_cards_passed_with_warnings",
    "n_cards_failed", "n_cards_excluded_by_applies_when",
}


def _calls_function(pyfile: Path, func_name: str) -> bool:
    """True iff `pyfile` contains a call `func_name(...)` (name-bound, not an attribute)."""
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == func_name
        for n in ast.walk(ast.parse(pyfile.read_text()))
    )


def _last_dict_literal_keys(pyfile: Path, var_name: str) -> "set[str] | None":
    """String keys of the LAST `var_name = {..}` dict-literal assignment (None if absent)."""
    keys = None
    for node in ast.walk(ast.parse(pyfile.read_text())):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            if any(isinstance(t, ast.Name) and t.id == var_name for t in node.targets):
                keys = {k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys


def _shared_build_governance():
    if str(SKILLS) not in sys.path:
        sys.path.insert(0, str(SKILLS))
    from _skills_common.envelope import build_governance  # noqa: E402
    return build_governance


def test_shared_build_governance_returns_the_reproducibility_spine():
    gov = _shared_build_governance()("live_latest", "unpinned", {"n_cards_attempted": 0})
    missing = _GOVERNANCE_REPRO_SPINE - set(gov)
    assert not missing, f"shared build_governance dropped reproducibility keys: {missing}"


def test_compose_dashboard_governance_is_single_sourced():
    # assemble_evidence_package must route governance through build_governance (not an inline dict).
    assert _calls_function(ENVELOPE, "build_governance"), (
        "assemble_evidence_package no longer calls build_governance — governance construction forked.")


def test_target_profile_governance_is_single_sourced():
    # target-profile must build governance via the shared builder, NOT a hand-built dict literal.
    assert _calls_function(TP_RUN, "build_governance"), (
        "target-profile stopped routing governance through the shared build_governance — the #9 "
        "two-engine governance drift has been reintroduced.")


def test_target_profile_validation_summary_matches_the_schema_shape():
    # The validation_summary target-profile feeds the shared builder must carry exactly the 5 schema
    # fields (evidence_package governance.validation_summary; unevaluatedProperties:false).
    keys = _last_dict_literal_keys(TP_EVIDENCE, "validation_summary")
    assert keys is not None, f"no `validation_summary = {{...}}` literal found in {TP_EVIDENCE}"
    assert keys == _VALIDATION_SUMMARY_KEYS, (
        f"target-profile validation_summary keys {keys} != schema {_VALIDATION_SUMMARY_KEYS}")


def test_target_profile_sub_verdict_keeps_the_audit_spine():
    """Each per-sub-skill record must retain driving_rule_id + cards_used + fired_rule_ids — the
    deterministic audit spine (which rule fired the verdict, over which resolved cards)."""
    src = TP_RUN.read_text()
    for field in ("driving_rule_id", "cards_used", "fired_rule_ids"):
        assert f'"{field}"' in src, f"target-profile sub_verdict record lost the audit-spine field {field!r}"
