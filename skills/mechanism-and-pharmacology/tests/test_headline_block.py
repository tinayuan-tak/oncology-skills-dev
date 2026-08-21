"""The canonical HEADLINE block (verdict + confidence + top-tension) rides the mechanism-and-pharmacology
decision — a verdict-INERT projection over the already-computed mechanism headline (mirrors the
tumor-presence exemplar + the on-target-safety-liability / functional-requirement wirings). This replays
the REAL frozen EGFR/COADREAD dossier through the REAL run.py (dispatcher monkeypatched — same machinery
as test_mechanism_replay.py) and asserts the headline_block is present, non-degraded, and internally
consistent with the mechanism spine.

EGFR/COADREAD resolves `well_characterized` (a rich SIGNOR signaling network). Because this skill is
DESCRIPTIVE — the mechanism verdict is a signaling-network CHARACTERIZATION / annotation-density class,
not a favorable/unfavorable target call — the badge polarity must be `neutral`, the discriminating
polarity check for this skill.
"""
from __future__ import annotations

import copy
import json
import runpy
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

_VALID_CONFIDENCE = {"strong", "moderate", "weak", "insufficient"}
_AXIS_KEYS = ["NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"]


def _real_summary(s) -> bool:
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def _decision(pair_id: str, target: str, indication: str) -> dict:
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    frozen = yaml.safe_load(fx.read_text()) or {}

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None
            return copy.deepcopy(s)
        return _read_live

    out_dir = Path(tempfile.mkdtemp(prefix=f"mech-hl-{pair_id}-"))
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
    return json.loads(decision_path.read_text())


def test_headline_block_present_and_consistent():
    """EGFR/COADREAD (a well_characterized signaling network): the headline_block is present, non-degraded,
    its canonical verdict.call equals the skill's mechanism_verdict, confidence.level is valid, the hero
    lists the five mechanism axes, and — because this skill is DESCRIPTIVE — the badge polarity is neutral."""
    d = _decision("egfr_coadread", "EGFR", "COADREAD")
    h = d.get("headline") or {}

    # the spine the headline projects over
    mechanism_verdict = h.get("mechanism_verdict")
    assert mechanism_verdict == "well_characterized", (
        f"fixture no longer exercises a well_characterized network (got {mechanism_verdict!r}) — refreeze.")
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block DEGRADED: {(h.get('_enrichment_errors') or {}).get('headline_block')}")

    block = h.get("headline_block")
    assert isinstance(block, dict), "headline_block missing or not a dict (degraded projection)"

    # verdict.call == the skill's verdict; the canonical spelling carries gate + polarity
    verdict = block.get("verdict") or {}
    assert verdict.get("call") == mechanism_verdict
    assert verdict.get("gate") == "mechanism"

    # confidence.level valid
    assert (block.get("confidence") or {}).get("level") in _VALID_CONFIDENCE

    # hero lists the five mechanism axes, in order
    hero = block.get("hero") or {}
    assert [a.get("key") for a in (hero.get("axes") or [])] == _AXIS_KEYS

    # DESCRIPTIVE skill: a network-characterization / annotation-density class is not a favorable/unfavorable
    # target call → neutral badge (the honesty cap in mechanism_claims.py).
    assert verdict.get("polarity") == "neutral", (
        f"a descriptive mechanism characterization must colour the badge neutral; got {verdict.get('polarity')!r}")

    # deterministic headline text is always available
    assert isinstance(block.get("headline_text"), str) and block["headline_text"]
