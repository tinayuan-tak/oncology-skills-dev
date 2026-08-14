"""OFFLINE verdict-replay of frozen combo-and-resistance dossiers — the drift guard this skill lacked.

combo-and-resistance is VERDICT-BEARING with TWO self-contained verdicts (combination_verdict on the
combination_opportunity axis + resistance_verdict on the resistance_emergence extra-axis), each derived
by an INLINE Python precedence over fired rule-ids (NOT the shared resolver — this skill predates the
gap-#5 resolver migration; it is standalone, not composed into target-profile or compose-dashboard, so
the inline logic is not a composed-path seam risk, but IS a resolver-migration candidate if it is ever
composed). Its only test feeds SYNTHETIC fired-sets, so a card method RENAMING a field a rule keys on
passes green while in production the rule stops firing and the verdict silently drops
(strong_combination_opportunity → combination_insufficient; strong_resistance_signal →
resistance_insufficient). No existing test runs `fired_rules` over a real summary.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + BOTH the
combination_opportunity axis and the resistance_emergence extra-axis fire, and both inline verdicts run
exactly as in a real run. It fails deterministically, credential-less, on the SAME reader drift a live
run would.

Three curated fixtures pin both verdict halves AND the insufficient fall-through:
  - KRAS / COADREAD  — strong_combination_opportunity + strong_resistance_signal (the validated example:
    KRAS-inhibitor anchor → SHP2/GRB2 combos + NF1/KEAP1 resistance). Crown jewel: exercises BOTH inline
    precedence paths with positive firing; a reader drift on either card collapses that verdict → red.
  - XPO1 / COADREAD  — strong_combination_opportunity + strong_resistance_signal (a SECOND drug anchor,
    so a mutation-axis reader drift can't hide behind one target).
  - BRAF / COADREAD  — combination_insufficient + resistance_insufficient over REAL cards (no anchor
    co-target / rescue signal): guards the precedence fall-through and that the strong rungs do NOT
    over-fire.

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

_COMB_POSITIVE = {"strong_combination_opportunity", "combination_opportunity", "combination_signal"}
_RES_POSITIVE = {"strong_resistance_signal", "resistance_emergence", "resistance_signal"}


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
    out_dir = Path(tempfile.mkdtemp(prefix=f"combo-{pair_id}-"))
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


# ── the three curated fixtures (pair_id, target, indication, expected_comb, expected_res) ─────────
KRAS = ("kras_coadread", "KRAS", "COADREAD", "strong_combination_opportunity", "strong_resistance_signal")
XPO1 = ("xpo1_coadread", "XPO1", "COADREAD", "strong_combination_opportunity", "strong_resistance_signal")
BRAF = ("braf_coadread", "BRAF", "COADREAD", "combination_insufficient", "resistance_insufficient")
ALL = [KRAS, XPO1, BRAF]


@pytest.mark.parametrize("pair_id,target,indication,_c,_r", ALL, ids=[p[1].lower() for p in ALL])
def test_fixture_is_nonvacuous(pair_id, target, indication, _c, _r):
    """Guard against a stale/broken freeze: both drug-anchor cards must carry a real summary (even the
    BRAF insufficient fixture reads REAL cards — the screen ran but found no co-target/rescue signal)."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 2, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}")


@pytest.mark.parametrize("pair_id,target,indication,expected_comb,expected_res", ALL,
                         ids=[p[1].lower() for p in ALL])
def test_both_verdicts_match_expected(pair_id, target, indication, expected_comb, expected_res):
    """THE VERDICT-PATH DRIFT GUARD (both halves): the combination + resistance rules fire over the REAL
    frozen summaries (both axes) and both inline-precedence verdicts run. Each curated target's
    combination_verdict AND resistance_verdict must equal their pinned classes — a reader field rename
    that stops a rule firing changes one of them and fails here."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "combo-and-resistance"
    h = d.get("headline") or {}
    assert h.get("combination_verdict") == expected_comb, (
        f"combination_verdict={h.get('combination_verdict')!r} for {target}, expected {expected_comb!r}.")
    assert h.get("resistance_verdict") == expected_res, (
        f"resistance_verdict={h.get('resistance_verdict')!r} for {target}, expected {expected_res!r}.")


def test_kras_both_halves_fire_positive():
    """CROWN-JEWEL GUARD: KRAS (a KRAS-inhibitor drug anchor) fires BOTH halves positive — a combination
    opportunity (co-targets more essential under inhibition) AND a resistance signal (KO rescues). If
    EITHER card reader drifts, that half collapses to *_insufficient and this test goes red."""
    d = _decision(*KRAS[:3])
    h = d.get("headline") or {}
    assert h.get("combination_verdict") in _COMB_POSITIVE, (
        f"KRAS combination_verdict={h.get('combination_verdict')!r} collapsed — the combo-crispr-screen "
        f"reader drifted so no combination rule fired.")
    assert h.get("resistance_verdict") in _RES_POSITIVE, (
        f"KRAS resistance_verdict={h.get('resistance_verdict')!r} collapsed — the "
        f"resistance-emergence-signature reader drifted so no resistance rule fired.")
    assert h.get("driving_rule_id") and h.get("resistance_driving_rule_id"), (
        "both halves resolved a verdict but a driving_rule_id is empty — inconsistent spine.")
