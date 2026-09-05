"""OFFLINE verdict-replay of frozen differentiation-landscape dossiers — the drift guard this skill lacked.

differentiation-landscape is VERDICT-BEARING (differentiation verdict via the shared resolver); its
co-occurrence / mutual-exclusivity verdict is driven by the co-mutation-and-mutual-exclusivity card
(panel-intersect-aware Fisher over TCGA MC3 + GENIE). Its only test feeds the resolver SYNTHETIC
fired-sets, so a card method RENAMING a field a rule keys on passes green while in production the rule
stops firing and the verdict silently drops (strong_cooccurring / both_patterns_present → ns →
data_unavailable). No existing test runs `fired_rules` over a real summary.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the intracellular_intrinsic
rule-firing + the shared differentiation resolver execute exactly as in a real run. It fails
deterministically, credential-less, on the SAME reader drift a live run would.

Two curated fixtures pin two distinct verdicts that fire on real COADREAD data:
  - KRAS / COADREAD  — both_patterns_present (co-occurring drivers AND mutually-exclusive partners).
    Crown jewel: if the co-mutation reader drifts so cooccurrence_class stops firing, KRAS drops to
    ns/data_unavailable and this test goes red.
  - FBXW7 / COADREAD — strong_cooccurring (a distinct verdict).

The frozen fixtures are refreshed by the nightly-live re-freeze (card-behavior-matrix-nightly). Mirror of
tumor-selectivity's replay.
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
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

_COLLAPSED = {None, "", "insufficient", "data_unavailable", "ns"}


def _real_summary(s) -> bool:
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def _load_fixture(pair_id: str) -> dict:
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    return yaml.safe_load(fx.read_text()) or {}


_DECISION_CACHE: dict = {}


def _decision(pair_id: str, target: str, indication: str) -> dict:
    if pair_id in _DECISION_CACHE:
        return _DECISION_CACHE[pair_id]
    frozen = _load_fixture(pair_id)

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None
            return copy.deepcopy(s)
        return _read_live

    import tempfile
    out_dir = Path(tempfile.mkdtemp(prefix=f"diff-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication,
                             "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    d = json.loads(decision_path.read_text())
    _DECISION_CACHE[pair_id] = d
    return d


# ── the two curated fixtures (pair_id, target, indication, expected_verdict) ──────────────────────
KRAS  = ("kras_coadread",  "KRAS",  "COADREAD", "both_patterns_present")
FBXW7 = ("fbxw7_coadread", "FBXW7", "COADREAD", "strong_cooccurring")
ALL = [KRAS, FBXW7]


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_replay_conforms_to_data_product_schema(pair_id, target, indication, _exp):
    """LOAD-BEARING output-drift guard: the FRESH run.py emit must validate against the finalized
    data-product schema (static golden trimmed → this is the conformance target). CI-fail-not-skip."""
    import os
    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("differentiation-landscape")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('differentiation-landscape')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, _decision(pair_id, target, indication))
    assert not errors, f"FRESH {pair_id} emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15])


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_fixture_is_nonvacuous(pair_id, target, indication, _exp):
    """Guard against a stale/broken freeze: the verdict-driving co-mutation card (plus context facets)
    must carry a real summary. Require >=2 of the 4 cards real."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 2, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}")
    assert _real_summary(frozen.get("co-mutation-and-mutual-exclusivity")), (
        f"the verdict-driving co-mutation-and-mutual-exclusivity card is not real for {pair_id}.")


@pytest.mark.parametrize("pair_id,target,indication,expected", ALL, ids=[p[1].lower() for p in ALL])
def test_verdict_matches_expected(pair_id, target, indication, expected):
    """THE VERDICT-PATH DRIFT GUARD: the co-mutation rule fires over the REAL frozen summary and the
    shared differentiation resolver runs. Each curated target's resolved differentiation_verdict must
    equal its pinned class — a reader field rename that stops the rule firing changes it and fails here."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "differentiation-landscape"
    h = d.get("headline") or {}
    v = h.get("differentiation_verdict")
    assert v == expected, (
        f"differentiation_verdict={v!r} for {target}/{indication}, expected {expected!r}.")
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


def test_cooccurrence_pattern_does_not_collapse():
    """CROWN-JEWEL GUARD: KRAS has a rich co-occurrence + mutual-exclusivity landscape in COADREAD →
    both_patterns_present. If the co-mutation reader drifts so cooccurrence_class stops firing, KRAS
    collapses to ns/data_unavailable — this test goes red."""
    d = _decision(*KRAS[:3])
    h = d.get("headline") or {}
    assert h.get("differentiation_verdict") == "both_patterns_present", (
        f"KRAS resolved {h.get('differentiation_verdict')!r}, not both_patterns_present — the co-mutation "
        f"reader drifted so the co-occurrence rule stopped firing.")
    assert h.get("differentiation_verdict") not in _COLLAPSED
