"""OFFLINE byte-stability replay harness for cis-feature-coherence — the drift guard this skill lacked.

cis-feature-coherence had NO ``*_replay.py`` while 8 sibling skills do. Its other tests feed ``_verdict``
SYNTHETIC fired-rule lists (test_verdict.py), so none exercise the REAL card-field → rule-firing →
resolver → verdict path: a card method renaming an output field a rule keys on would resolve to None
SILENTLY and collapse the verdict, with every synthetic test still green.

This replays FROZEN RAW CARD READER SUMMARIES (the dispatcher's per-card output) THROUGH THE REAL run.py
(only the live dispatcher is monkeypatched), so production interpretation-rules + the shared
cis_coherence resolver + the claim_vector re-derivation all execute. The claim_vector is RE-DERIVED
in-test from the raw inputs — never stored — so a fixture of derived values can never mask a regression
(#1780 hard requirement).

PRECONDITION for the whole A-tranche (epic #1779): A1–A4 grow the L2b claim_vector and each asserts the
cis_coherence spine stays BYTE-STABLE against this harness. cis_coherence is verdict-INERT at
composition — the claim_vector is built AFTER the verdict and the resolver matches only fired rule IDs —
so ``cis_coherence_verdict`` + ``driving_rule_id`` are EXPECTED to stay byte-identical as the claim_vector
grows. This harness is what enforces that expectation.

Fixtures freeze RAW card fields (cis_dosage_class / cis_dosage_direction / correlation_class /
methylation_silencing_class / amp_expr_stratification_class …) for 5 representative verdict tokens:
coherent_cis_driver (ERBB2), expressed_cis_coupled_inert (MDM4), coherent_epigenetic_silencing (MLH1),
cis_uncoupled_no_dependency (AR), insufficient_cis_coherence (NRAS).
"""

from __future__ import annotations

import copy
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE_DIR = SKILL_DIR / "tests" / "fixtures"


# The 5 frozen verdict-token fixtures — the byte-stability corpus the A-tranche asserts against.
_FIXTURES = [
    "replay_coherent_cis_driver.yaml",
    "replay_expressed_cis_coupled_inert.yaml",
    "replay_coherent_epigenetic_silencing.yaml",
    "replay_cis_uncoupled_no_dependency.yaml",
    "replay_insufficient_cis_coherence.yaml",
]

# Keys that would betray a fixture storing DERIVED values instead of raw card inputs (the #1780 hard
# requirement: store raw inputs, re-derive the claim_vector in-test).
_DERIVED_KEYS = {"cis_coherence_verdict", "driving_rule_id", "claim_vector", "key_signals", "headline_block"}


def _load(name: str) -> dict:
    return yaml.safe_load((FIXTURE_DIR / name).read_text()) or {}


def _replay(fixture: dict, tmp_path_factory) -> dict:
    """Replay one fixture's RAW card summaries through the real run.py; return the emitted decision.json."""
    import _skills_common as skc

    frozen_cards = fixture["cards"]

    def _factory():
        def _read(card_id, target, indication, *a, **k):
            summary = frozen_cards.get(card_id)
            # A card absent from the fixture → genuinely missing (dispatcher returns None); a present
            # summary is deep-copied so the run cannot mutate the shared fixture across parametrisations.
            return copy.deepcopy(summary) if isinstance(summary, dict) else None

        return _read

    out_dir = tmp_path_factory.mktemp("cis-replay")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(
        sys,
        "argv",
        ["run.py", "--target", fixture["target"], "--indication", fixture["indication"], "--out", str(out_dir)],
    )
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on {fixture['target']}/{fixture['indication']}"
    finally:
        mp.undo()
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json for {fixture['target']}/{fixture['indication']}"
    return json.loads(decision_path.read_text())


@pytest.fixture(scope="module", params=_FIXTURES, ids=lambda n: n[len("replay_") : -len(".yaml")])
def replay_case(request, tmp_path_factory):
    fixture = _load(request.param)
    decision = _replay(fixture, tmp_path_factory)
    return fixture, decision


def test_fixtures_store_raw_inputs_not_derived_values():
    """#1780 hard requirement: fixtures must store RAW card inputs, never derived headline values — else a
    fixture of derived values can never fail. Structurally enforce it: no card summary may carry a derived
    key (cis_coherence_verdict / claim_vector / …), and every fixture must expose the raw class fields."""
    seen_verdicts = set()
    for name in _FIXTURES:
        fx = _load(name)
        assert fx.get("cards"), f"{name}: no raw `cards` block"
        # the fixture's OWN top level carries the frozen expected verdict (not inside a card summary)
        assert "expected_cis_coherence_verdict" in fx, f"{name}: missing expected verdict"
        seen_verdicts.add(fx["expected_cis_coherence_verdict"])
        for cid, summary in fx["cards"].items():
            assert isinstance(summary, dict), f"{name}/{cid}: card summary must be a dict"
            leaked = _DERIVED_KEYS & set(summary)
            assert not leaked, f"{name}/{cid}: fixture stores DERIVED value(s) {sorted(leaked)} — store raw inputs only"
        # leg-1 raw class field must be present on the cis-dosage card (the field a rule keys on)
        assert "cis_dosage_class" in fx["cards"].get("cis-feature-expression-coherence", {}), (
            f"{name}: cis-feature-expression-coherence fixture lacks the raw cis_dosage_class field"
        )
    # ≥5 DISTINCT verdict tokens across the corpus (the #1780 acceptance floor)
    assert len(seen_verdicts) >= 5, f"expected ≥5 distinct verdict tokens, got {sorted(seen_verdicts)}"


def test_replay_verdict_and_driving_rule_are_byte_stable(replay_case):
    """THE HARNESS: rules fire over the REAL frozen RAW summaries, the shared resolver ladders them, and
    the emitted cis_coherence_verdict + driving_rule_id must be BYTE-IDENTICAL to the frozen expectation.

    This is the invariant A1–A4 assert against: growing the L2b claim_vector must not move this spine (the
    claim_vector is built AFTER the verdict; the resolver matches only fired rule IDs)."""
    fixture, decision = replay_case
    assert decision["skill"] == "cis-feature-coherence"
    h = decision.get("headline") or {}
    assert h.get("cis_coherence_verdict") == fixture["expected_cis_coherence_verdict"], (
        f"{fixture['target']}/{fixture['indication']}: cis_coherence_verdict drifted "
        f"{h.get('cis_coherence_verdict')!r} != frozen {fixture['expected_cis_coherence_verdict']!r} — suspect a "
        f"renamed reader field a rule keys on. driving_rule_id={h.get('driving_rule_id')!r}"
    )
    assert h.get("driving_rule_id") == fixture["expected_driving_rule_id"], (
        f"{fixture['target']}/{fixture['indication']}: driving_rule_id drifted "
        f"{h.get('driving_rule_id')!r} != frozen {fixture['expected_driving_rule_id']!r}"
    )


def test_replay_claim_vector_is_rederived_and_nonvacuous(replay_case):
    """The claim_vector is RE-DERIVED by run.py from the raw inputs (never stored in the fixture). It must
    be present + carry the four coherence-leg axes — proving the harness exercises the full L2b build path
    the A-tranche grows, not just the resolver."""
    _fixture, decision = replay_case
    h = decision.get("headline") or {}
    cv = h.get("claim_vector")
    assert isinstance(cv, dict) and cv, "claim_vector missing/empty — run.py did not re-derive it from the raw inputs"
    axes = set(cv.get("claims", cv).keys()) if isinstance(cv.get("claims", cv), dict) else set()
    assert {"CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"} & axes, (
        f"claim_vector re-derived but carries none of the four coherence-leg axes: {sorted(axes)}"
    )


def test_measured_tokens_are_not_all_insufficient(replay_case):
    """Guard against a silent all-cards-missing regression (which would collapse every case to the
    insufficient default and still pass the byte-stability assert for that one token): the four MEASURED
    fixtures must reach a non-default verdict, and only the NRAS fixture is the honest-abstention default."""
    fixture, decision = replay_case
    h = decision.get("headline") or {}
    verdict = h.get("cis_coherence_verdict")
    if fixture["expected_cis_coherence_verdict"] == "insufficient_cis_coherence":
        assert verdict == "insufficient_cis_coherence"
    else:
        assert verdict != "insufficient_cis_coherence", (
            f"{fixture['target']} was expected to reach a measured verdict but collapsed to the "
            "insufficient default — suspect the frozen summaries stopped resolving (dispatcher/field drift)"
        )
