"""OFFLINE replay of the frozen KRAS/COADREAD dossier — the drift guard functional-requirement lacked.

All other FR tests feed `_verdict` SYNTHETIC fired-rule lists, so none can catch the reader-real-field
drift bug class (a card method renaming an output field → a get_card_field read resolves to None
SILENTLY; for a verdict-bearing skill a renamed field a RULE keys on collapses the verdict). This skill
has already shipped TWO such silent drift bugs (run.py v1.3.1). This replays the REAL reader summaries
frozen by freeze_fixture.py THROUGH THE REAL run.py (only the live dispatcher is monkeypatched), so
production CARDS + rule-firing + resolver + _headline all execute — failing deterministically,
credential-less, on the SAME drift a live run would.

Fixture: KRAS / COADREAD — the canonical dependency reference (bimodal → a positive dependency call;
also the compose-dashboard engine-equivalence anchor), stable across the 2026-08-13 classifier fixes.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "kras_coadread.yaml"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

# POSITIVE dependency calls (a real "yes, a dependency" verdict) — _DEPENDENCY_CALL_VERDICTS minus the
# negative calls (non_dependent, pan_essential_killer). Imported from run.py = single source.
_NEGATIVE_CALLS = {"non_dependent", "pan_essential_killer"}


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"no frozen fixture at {FIXTURE} — run freeze_fixture.py against live S3")
    return yaml.safe_load(FIXTURE.read_text()) or {}


def _real(s) -> bool:
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def _positive_calls() -> set:
    spec = importlib.util.spec_from_file_location("_fr_run_const", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod._DEPENDENCY_CALL_VERDICTS) - _NEGATIVE_CALLS


@pytest.fixture(scope="module")
def kras_decision(tmp_path_factory):
    frozen = _load_fixture()
    import _skills_common as skc

    def _factory():
        def _read(card_id, target, indication, *a, **k):
            s = frozen.get(card_id)
            return copy.deepcopy(s) if _real(s) else None
        return _read

    out_dir = tmp_path_factory.mktemp("fr-kras-replay")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "KRAS", "--indication", "COADREAD",
                             "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the frozen KRAS replay"
    finally:
        mp.undo()
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json on the frozen KRAS replay"
    return json.loads(decision_path.read_text())


def test_fixture_is_nonvacuous():
    frozen = _load_fixture()
    real = [c for c, s in frozen.items() if _real(s)]
    assert len(real) >= 10, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary — refreeze (freeze_fixture.py). "
        f"Real: {sorted(real)}")


def test_replay_verdict_is_a_positive_dependency_call(kras_decision):
    """THE VERDICT-PATH DRIFT GUARD: rules fire over the REAL frozen summaries. KRAS is a bona fide
    COADREAD dependency, so dependency_verdict must be a POSITIVE dependency call with a real driving
    rule — a reader field-rename that a rule keys on would collapse it to insufficient/non_dependent."""
    assert kras_decision["skill"] == "functional-requirement"
    h = kras_decision.get("headline") or {}
    verdict = h.get("dependency_verdict")
    assert verdict in _positive_calls(), (
        f"dependency_verdict={verdict!r} is not a positive dependency call for KRAS/COADREAD — suspect "
        f"a rule that stopped firing on a renamed reader field. driving_rule_id={h.get('driving_rule_id')!r}")
    assert h.get("driving_rule_id"), "positive verdict but empty driving_rule_id — inconsistent spine."


def test_replay_headline_resolves_broadly(kras_decision):
    """Headline drift floor: a reader field-name drift nulling a block of get_card_field reads would
    collapse many headline values to None. KRAS/COADREAD resolves ~18/19 fields; floor >=15."""
    h = kras_decision.get("headline") or {}
    non_null = [k for k, v in h.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 15, (
        f"only {len(non_null)}/{len(h)} headline fields resolved for the frozen KRAS replay — suspect a "
        f"reader field-name drift (get_card_field -> None). Non-null: {sorted(non_null)}")
