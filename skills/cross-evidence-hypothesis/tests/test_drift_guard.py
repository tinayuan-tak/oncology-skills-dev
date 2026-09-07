"""drift-guard — the OFFLINE golden-set drift-CI.

Runs the integrator fully OFFLINE (canned two-call `llm_replay.json` via `replay_synthesize`) against
TRIMMED evidence packages for KRAS/COADREAD + MARK2/PAAD, and asserts the DETERMINISTIC SPINE outputs
(clamped verdict, gate ceiling / clamp tension, clause-traceability, computed certainty + caps, data
gaps, substrate-discount, intra-package coherence) — plus the two provenance PINS
(prompt_template_hash + model_id) — have NOT drifted from the frozen golden. The LLM PROSE (edge
rationales, clause statements) is deliberately NOT frozen.

A test FAILS when any frozen deterministic output drifts (e.g. a prompt/schema edit flips
prompt_template_hash; a resolver/clamp change moves a verdict). Regenerate the golden ONLY on a
reviewed, deliberate change:

    BEDROCK_AWS_PROFILE=cmp-dev python3 scripts/freeze_drift_golden.py --all       # re-capture LLM + refreeze
    python3 scripts/freeze_drift_golden.py --all --replay-only                     # refreeze spine only (no Bedrock)

TOLERANCE: the offline spine is EXACTLY reproducible run-to-run (no Bedrock, fixed replay), so every
frozen field is compared for exact equality; the one float (clause_traceability) is compared within
DRIFT_FLOAT_TOL to be robust to platform float formatting. The "beyond tolerance on
model/prompt change" channel is handled by regeneration + review (a flipped prompt_template_hash makes
this test fail loudly), not by loosening the offline comparison.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import drift_golden as dg  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_drift")

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
CASES = sorted(p.name for p in GOLDEN.iterdir() if (p / "expected_spine.json").exists()) if GOLDEN.exists() else []

DRIFT_FLOAT_TOL = 1e-9


def _run_offline(case_dir: Path, case: dict) -> dict:
    """Replay the frozen canned LLM response through the real deterministic spine — no Bedrock."""
    return R.run(
        case["pkg"],
        case["risk"],
        case["meta"]["objective"],
        case["meta"]["modality"],
        case["dossier"],
        synthesize_fn=R.replay_synthesize(case["replay"]),
        llm_mode="offline_replay",
    )


def _assert_spine_equal(got: dict, expected: dict, case_name: str):
    assert set(got) == set(expected), f"[{case_name}] spine key-set drift: {set(got) ^ set(expected)}"
    for k in expected:
        if k == "clause_traceability" and isinstance(got[k], float) and isinstance(expected[k], float):
            assert abs(got[k] - expected[k]) <= DRIFT_FLOAT_TOL, f"[{case_name}] {k} drift: {got[k]} != {expected[k]}"
        else:
            assert got[k] == expected[k], f"[{case_name}] {k} drift: {got[k]!r} != {expected[k]!r}"


@pytest.mark.skipif(not CASES, reason="no golden cases frozen (run freeze_drift_golden.py)")
@pytest.mark.parametrize("case_name", CASES)
def test_deterministic_spine_no_drift(case_name):
    case = dg.load_golden_case(GOLDEN / case_name)
    r = _run_offline(GOLDEN / case_name, case)
    _assert_spine_equal(dg.deterministic_spine_subset(r), case["expected"], case_name)


@pytest.mark.skipif(not CASES, reason="no golden cases frozen")
@pytest.mark.parametrize("case_name", CASES)
def test_provenance_pins_frozen(case_name):
    """prompt_template_hash + model_id are the drift-guard's PINS: a prompt/schema edit flips the
    hash → this fails → forces golden regeneration + review."""
    case = dg.load_golden_case(GOLDEN / case_name)
    r = _run_offline(GOLDEN / case_name, case)
    assert r["provenance"]["prompt_template_hash"] == case["expected"]["prompt_template_hash"]
    assert r["provenance"]["model_id"] == case["expected"]["model_id"]


def test_prompt_template_hash_is_deterministic():
    assert R.prompt_template_hash() == R.prompt_template_hash()
    assert len(R.prompt_template_hash()) == 64  # sha256 hex


@pytest.mark.skipif(not CASES, reason="no golden cases frozen")
def test_offline_replay_is_run_to_run_stable():
    """Same inputs + same replay → identical deterministic spine (the determinism invariant), so the
    golden comparison itself is meaningful."""
    case_name = CASES[0]
    case = dg.load_golden_case(GOLDEN / case_name)
    a = dg.deterministic_spine_subset(_run_offline(GOLDEN / case_name, case))
    b = dg.deterministic_spine_subset(_run_offline(GOLDEN / case_name, case))
    assert a == b


@pytest.mark.skipif(not CASES, reason="no golden cases frozen")
def test_perturbing_a_deterministic_output_is_detected():
    """TEETH: perturb an INPUT sub-verdict on a veto-capable axis → the spine subset MUST diverge
    from the frozen golden (proves the guard would catch a real regression, not pass vacuously)."""
    case_name = CASES[0]
    case = dg.load_golden_case(GOLDEN / case_name)
    pkg = json.loads(Path(case["pkg"]).read_text())
    # flip dependency to a hard kill token → gate ceiling must move toward declined.
    # Use pan_essential_killer, an UNCONDITIONAL veto: `non_dependent` is now mechanism-conditioned
    # (mechanism-excluded for a mutant-selective driver like the KRAS golden case), so it would
    # NOT move the spine and would make this teeth-test vacuous. pan_essential_killer has no
    # selectivity window and stays a veto regardless of mechanism.
    pkg["synthesis"]["sub_verdicts"]["dependency"] = {"verdict": "pan_essential_killer"}
    tmp = GOLDEN / case_name / "_perturbed_pkg.json"
    tmp.write_text(json.dumps(pkg))
    try:
        r = R.run(
            str(tmp),
            case["risk"],
            case["meta"]["objective"],
            case["meta"]["modality"],
            case["dossier"],
            synthesize_fn=R.replay_synthesize(case["replay"]),
            llm_mode="offline_replay",
        )
        perturbed = dg.deterministic_spine_subset(r)
        assert perturbed != case["expected"], (
            "perturbing a veto-capable sub-verdict did NOT change the frozen spine — guard is vacuous"
        )
    finally:
        tmp.unlink(missing_ok=True)
