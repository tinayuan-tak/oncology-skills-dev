"""OFFLINE verdict-replay of frozen synthetic-lethal-partners dossiers — the drift guard this skill lacked.

synthetic-lethal-partners is VERDICT-BEARING and its verdict is a NOMINATION-GATE VETO-SUPPRESSOR:
has_experimental_sl_partner is what lets a strong-dependency-veto'd but paralog-buffered target
(SMARCA2←SMARCA4) escape the veto. Its only test (test_sl_verdict.py) feeds the resolver SYNTHETIC
fired-sets, so a card method RENAMING a field a rule keys on passes green while in production the rule
stops firing and the verdict silently drops (has_experimental_sl_partner → no_curated_sl_partner) —
which would silently RE-ARM the dependency veto on a legitimately-buffered target. No existing test runs
`fired_rules` over a real summary.

This replays the REAL reader summary frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the intracellular_intrinsic
rule-firing + the shared synthetic_lethal_partners resolver execute exactly as in a real run. It fails
deterministically, credential-less, on the SAME reader drift a live run would.

Three curated fixtures pin all three non-trivial verdicts:
  - SMARCA2 / COADREAD — has_experimental_sl_partner (the veto-suppressor; SMARCA4-paralog SL). Crown
    jewel: if the card reader drifts, SMARCA2 drops to no_curated_sl_partner → red (and the dependency
    veto would silently re-arm on a buffered target).
  - STAG1 / COADREAD — has_computational_sl_partner (the informational rung — a distinct verdict).
  - CEACAM5 / COADREAD — no_curated_sl_partner (neutral; guards the suppressor does NOT over-fire).

The frozen fixtures are refreshed by the nightly-live re-freeze (card-behavior-matrix-nightly). Mirror of
tumor-selectivity's replay (SK#411).
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

_COLLAPSED = {None, "", "insufficient", "data_unavailable"}


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
    out_dir = Path(tempfile.mkdtemp(prefix=f"sl-{pair_id}-"))
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


# ── the three curated fixtures (pair_id, target, indication, expected_verdict) ────────────────────
SMARCA2 = ("smarca2_coadread", "SMARCA2", "COADREAD", "has_experimental_sl_partner")
STAG1   = ("stag1_coadread",   "STAG1",   "COADREAD", "has_computational_sl_partner")
CEACAM5 = ("ceacam5_coadread", "CEACAM5", "COADREAD", "no_curated_sl_partner")
ALL = [SMARCA2, STAG1, CEACAM5]


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_fixture_is_nonvacuous(pair_id, target, indication, _exp):
    """This is a single-card skill: the one synthetic-lethal-partners card must carry a real summary,
    else the freeze is broken and the verdict guards would pass vacuously."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 1, (
        f"the synthetic-lethal-partners card carries no real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py).")


@pytest.mark.parametrize("pair_id,target,indication,expected", ALL, ids=[p[1].lower() for p in ALL])
def test_verdict_matches_expected(pair_id, target, indication, expected):
    """THE VERDICT-PATH DRIFT GUARD: the rule fires over the REAL frozen summary and the shared
    synthetic_lethal_partners resolver runs. Each curated target's resolved sl_partner_verdict must equal
    its pinned class — a reader field rename that stops the rule firing changes it and fails here."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "synthetic-lethal-partners"
    h = d.get("headline") or {}
    v = h.get("sl_partner_verdict")
    assert v == expected, (
        f"sl_partner_verdict={v!r} for {target}/{indication}, expected {expected!r}.")
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


def test_experimental_partner_suppressor_fires():
    """CROWN-JEWEL GUARD (silent suppressor-death → dependency veto re-arms): SMARCA2 has an EXPERIMENTAL
    SL partner (SMARCA4) → has_experimental_sl_partner, the verdict the nomination gate keys on to
    suppress a strong-dependency veto. If the card reader drifts so the experimental-partner rule stops
    firing, SMARCA2 drops to no_curated_sl_partner — and a legitimately paralog-buffered target would be
    silently re-vetoed. This test goes red on that drift."""
    d = _decision(*SMARCA2[:3])
    h = d.get("headline") or {}
    assert h.get("sl_partner_verdict") == "has_experimental_sl_partner", (
        f"SMARCA2 resolved {h.get('sl_partner_verdict')!r}, not has_experimental_sl_partner — the "
        f"experimental-partner rule stopped firing (card reader drift → the SL veto-suppressor is dead).")
    assert h.get("sl_partner_verdict") not in _COLLAPSED
    assert h.get("has_experimental_partner"), (
        "SMARCA2 headline has_experimental_partner is falsy — the fixture no longer exercises the "
        "experimental-partner suppressor; re-curate/refreeze.")


def test_no_partner_target_does_not_suppress():
    """The suppressor must NOT over-fire: CEACAM5 has no curated SL partner → no_curated_sl_partner.
    If it wrongly read an experimental/computational partner, the nomination gate would spuriously
    suppress a dependency veto."""
    d = _decision(*CEACAM5[:3])
    h = d.get("headline") or {}
    assert h.get("sl_partner_verdict") == "no_curated_sl_partner", (
        f"CEACAM5 resolved {h.get('sl_partner_verdict')!r}, expected no_curated_sl_partner (suppressor "
        f"over-fire?).")
