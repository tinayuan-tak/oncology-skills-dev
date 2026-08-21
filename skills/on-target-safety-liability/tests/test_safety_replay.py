"""OFFLINE verdict-replay of frozen on-target-safety-liability dossiers — the drift guard this skill lacked.

on-target-safety-liability is VERDICT-BEARING and KILLER-adjacent (highly_constrained_safety_concern /
human_genetics_safety_concern are nomination HOLDs), and its verdict carries a mechanism-conditioned
mutant-selective DOWNGRADE (wt_constraint_mechanism_mismatch / wt_human_genetics_mechanism_mismatch) that
fires ONLY when the alteration-role card's `activating-driver-role-safety-context` rule fires alongside a
WT-loss safety warning. Its existing tests feed the resolver SYNTHETIC fired-sets, so a card method
RENAMING a field a rule keys on passes green while in production the rule silently stops firing. The
dangerous direction: if alteration-role.functional_direction drifts, the downgrade dies and every GoF
mutant-selective driver (KRAS/BRAF/EGFR/PIK3CA/MTOR) flips from *_mechanism_mismatch (downgraded) to
highly_constrained_safety_concern (a FALSE nomination HOLD) — with no red test. No existing test runs
`fired_rules` over a real summary for this skill.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the intracellular_intrinsic
rule-firing + the shared safety resolver (incl. the Group-1 mechanism-mismatch downgrade rungs and the
1.4.0 human-genetics precedence fix) all execute exactly as in a real run. It fails deterministically,
credential-less, on the SAME reader drift a live run would.

Four curated fixtures pin all four non-trivial verdict classes AND both conditioning directions:
  - BRAF / COADREAD — GoF activating driver, highly-constrained gnomAD → wt_constraint_mechanism_mismatch
    (the gnomAD-constraint downgrade). Guards the crown-jewel false-HOLD: if alteration-role drifts, BRAF
    flips to highly_constrained_safety_concern and this test goes red.
  - EGFR / COADREAD — GoF activating driver, P5 human-genetics warning → wt_human_genetics_mechanism_mismatch
    (the SECOND downgrade verdict; exercises the gene-burden/dosage/mouse-ko/clinvar warning path).
  - TP53 / COADREAD — LoF tumor-suppressor, highly-constrained → highly_constrained_safety_concern
    (raw constraint HOLD; the downgrade must NOT over-fire on a non-activating gene).
  - VHL / COADREAD — LoF, TOLERANT gnomAD but a human-genetics HOLD → human_genetics_safety_concern
    (guards the 1.4.0 precedence fix: the P5 HOLD must fire ABOVE the soft/tolerant gnomAD rungs).

The frozen fixtures are refreshed by the nightly-live re-freeze (card-behavior-matrix-nightly). Mirror of
tumor-selectivity's replay.
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
FIXTURES = SKILL_DIR / "tests" / "fixtures"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _run_const():
    """Import run.py once for its single-source-of-truth constant (the mechanism-mismatch verdict set)."""
    spec = importlib.util.spec_from_file_location("_safety_run_const", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SAFETY = _run_const()
_MISMATCH = set(_SAFETY._MECHANISM_MISMATCH_VERDICTS)   # the mutant-selective downgrade verdicts
# A resolved safety verdict must never collapse to these for a target with real human-genetics data.
_COLLAPSED = {None, "", "insufficient", "data_unavailable"}
# The raw (non-downgraded) nomination-HOLD concerns.
_CONCERNS = {"highly_constrained_safety_concern", "human_genetics_safety_concern"}


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
    out_dir = Path(tempfile.mkdtemp(prefix=f"safety-{pair_id}-"))
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


# ── the four curated fixtures (pair_id, target, indication, expected_verdict) ─────────────────────
BRAF = ("braf_coadread", "BRAF", "COADREAD", "wt_constraint_mechanism_mismatch")
EGFR = ("egfr_coadread", "EGFR", "COADREAD", "wt_human_genetics_mechanism_mismatch")
TP53 = ("tp53_coadread", "TP53", "COADREAD", "highly_constrained_safety_concern")
VHL  = ("vhl_coadread",  "VHL",  "COADREAD", "human_genetics_safety_concern")
# (cards review 2026-08-17): an ACTIVATING GoF ONCOGENE that is AMPLIFICATION-driven. Unlike the
# DOWNGRADE cases (activating -> mutant-selective downgrade), the amplification guard KEEPS the raw HOLD
# because a drug hits the WILD-TYPE (amplified) protein — the mutant-selective-sparing logic fails.
ERBB2 = ("erbb2_brca", "ERBB2", "BRCA", "human_genetics_safety_concern")
ALL = [BRAF, EGFR, TP53, VHL, ERBB2]
DOWNGRADE = [BRAF, EGFR]
CONCERN = [TP53, VHL]


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL,
                         ids=[p[1].lower() for p in ALL])
def test_fixture_is_nonvacuous(pair_id, target, indication, _exp):
    """Guard against a stale/broken freeze reading green: each curated target resolves most of the
    8-card safety roster. Require >=5 to carry a real summary."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 5, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}")


@pytest.mark.parametrize("pair_id,target,indication,expected", ALL,
                         ids=[p[1].lower() for p in ALL])
def test_verdict_matches_expected(pair_id, target, indication, expected):
    """THE VERDICT-PATH DRIFT GUARD: rules fire over the REAL frozen summaries and the shared safety
    resolver runs. Each curated target's resolved safety_verdict must equal its pinned class — a reader
    field rename that stops a rule firing changes the class and fails here."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "on-target-safety-liability"
    h = d.get("headline") or {}
    v = h.get("safety_verdict")
    assert v not in _COLLAPSED, (
        f"safety_verdict={v!r} collapsed for {target}/{indication} — a rule stopped firing (reader "
        f"field rename?).")
    assert v == expected, (
        f"safety_verdict={v!r} for {target}/{indication}, expected {expected!r}. If this is a GoF "
        f"driver that dropped OUT of a *_mechanism_mismatch downgrade, suspect alteration-role reader "
        f"drift (the false-HOLD failure this replay exists to catch).")
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


@pytest.mark.parametrize("pair_id,target,indication,expected", DOWNGRADE,
                         ids=[p[1].lower() for p in DOWNGRADE])
def test_gof_driver_gets_mutant_selective_downgrade(pair_id, target, indication, expected):
    """CROWN-JEWEL GUARD (silent downgrade-death → false safety HOLD): a GoF activating driver with a
    WT-loss warning must resolve to a *_mechanism_mismatch downgrade, driven by the alteration-role
    activating context. If alteration-role's functional_direction reader drifts, the downgrade dies and
    the target reads as a raw safety concern (a false nomination HOLD) — this test goes red."""
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    assert h.get("safety_verdict") in _MISMATCH, (
        f"{target} resolved {h.get('safety_verdict')!r}, not a mutant-selective downgrade — the "
        f"activating-driver-role-safety-context rule stopped firing (alteration-role reader drift → "
        f"a GoF driver would nominate as a full WT-loss safety liability).")
    assert h.get("alteration_functional_direction") == "activating", (
        f"{target} alteration_functional_direction={h.get('alteration_functional_direction')!r}, "
        f"expected 'activating' — the fixture no longer exercises the downgrade; re-curate/refreeze.")
    assert h.get("mechanism_conditioning_note"), (
        f"{target} resolved a *_mechanism_mismatch downgrade but carries no mechanism_conditioning_note "
        f"(the Guard-A note-parity contract).")


@pytest.mark.parametrize("pair_id,target,indication,expected", CONCERN,
                         ids=[p[1].lower() for p in CONCERN])
def test_non_gof_concern_is_not_downgraded(pair_id, target, indication, expected):
    """The downgrade must NOT over-fire: a non-activating (LoF) gene with a real safety concern must
    resolve to a raw HOLD, NOT a mechanism-mismatch. Guards a false downgrade that would nullify a
    genuine WT-loss safety liability."""
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    assert h.get("safety_verdict") in _CONCERNS, (
        f"{target} resolved {h.get('safety_verdict')!r}, expected a raw safety concern.")
    assert h.get("safety_verdict") not in _MISMATCH, (
        f"{target} was DOWNGRADED to {h.get('safety_verdict')!r} despite being non-activating — the "
        f"mutant-selective downgrade over-fired.")
    assert h.get("alteration_functional_direction") != "activating", (
        f"{target} reads as 'activating' — fixture no longer exercises the raw-concern (non-downgrade) path.")
    assert h.get("mechanism_conditioning_note") is None, (
        f"{target} is a raw concern but carries a mechanism_conditioning_note (note should be downgrade-only).")


def test_amplification_driven_oncogene_keeps_hold_not_downgraded():
    """(cards review 2026-08-17): an ACTIVATING GoF ONCOGENE that is AMPLIFICATION-driven must KEEP
    its on-target-safety HOLD, NOT be mutant-selectively downgraded — a drug (ADC/TCE/degrader/WT-hitting
    inhibitor) engages the WILD-TYPE (amplified) protein, so the mutant-selective-sparing logic fails.
    ERBB2/BRCA: activating (IntOGen Act) + ONCOGENE + recurrent_focal_amplification + a WT-loss warning.
    WITHOUT the GROUP-0 amplification guard this would resolve to wt_human_genetics_mechanism_mismatch
    (the bug — a false safety pass); WITH it, the raw HOLD stands, driven by the amp guard rule."""
    pair_id, target, indication, _ = ERBB2
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    v = h.get("safety_verdict")
    assert v in _CONCERNS, (
        f"ERBB2 resolved {v!r}, expected a raw safety HOLD — the amplification guard "
        f"(copy-number-amplified-oncogene-safety-context) failed to keep the hold (S1-1 regression).")
    assert v not in _MISMATCH, (
        f"ERBB2 was mutant-selectively DOWNGRADED to {v!r} despite being amplification-driven — the "
        f"S1-1 amplification guard is not firing (the leak this test exists to catch).")
    # It IS an activating oncogene (that's the point — activating+oncogene+amplified → held, not downgraded).
    assert h.get("alteration_functional_direction") == "activating", (
        f"ERBB2 alteration_functional_direction={h.get('alteration_functional_direction')!r}, expected "
        f"'activating' — the fixture no longer exercises the amplification-guard-over-downgrade path.")
    assert h.get("driving_rule_id") == "copy-number-amplified-oncogene-safety-context", (
        f"ERBB2 hold driving_rule_id={h.get('driving_rule_id')!r}, expected the amplification guard rule "
        f"(the GROUP-0 rung that kept the hold).")
    # A HOLD, not a downgrade → no mechanism-conditioning note.
    assert h.get("mechanism_conditioning_note") is None
