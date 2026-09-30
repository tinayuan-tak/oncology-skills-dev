"""The canonical HEADLINE block (verdict + confidence + top-tension) rides the on-target-safety-liability
decision — a verdict-INERT projection over the already-computed safety headline (mirrors the tumor-presence
exemplar). This replays the REAL frozen TP53/COADREAD dossier through the REAL run.py (dispatcher
monkeypatched — same machinery as test_safety_replay.py) and asserts the headline_block is present,
non-degraded, and internally consistent with the safety spine.

TP53/COADREAD resolves `highly_constrained_safety_concern` — a LoF-intolerant nomination HOLD. Because the
five claim axes are INVERSE-VALENCE liabilities, that liability verdict must colour the badge polarity
`negative` (undesirable for a drug program), the discriminating polarity check for this skill.
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
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"


_VALID_CONFIDENCE = {"strong", "moderate", "weak", "insufficient"}
_AXIS_KEYS = ["CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL", "NORMAL_TISSUE"]


def _real_summary(s) -> bool:
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


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

    out_dir = Path(tempfile.mkdtemp(prefix=f"safety-hl-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    return json.loads(decision_path.read_text())


def test_headline_block_present_and_consistent_for_liability_verdict():
    """TP53/COADREAD (a highly_constrained_safety_concern liability HOLD): the headline_block is present,
    non-degraded, its canonical verdict.call equals the skill's safety_verdict, confidence.level is valid,
    the hero lists the five liability axes, and — given the inverse valence — the liability verdict colours
    the badge polarity `negative`."""
    d = _decision("tp53_coadread", "TP53", "COADREAD")
    h = d.get("headline") or {}

    # the spine the headline projects over
    safety_verdict = h.get("safety_verdict")
    assert safety_verdict == "highly_constrained_safety_concern", (
        f"fixture no longer exercises a liability HOLD (got {safety_verdict!r}) — re-curate/refreeze."
    )
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block DEGRADED: {(h.get('_enrichment_errors') or {}).get('headline_block')}"
    )

    block = h.get("headline_block")
    assert isinstance(block, dict), "headline_block missing or not a dict (degraded projection)"

    # verdict.call == the skill's verdict; the canonical spelling carries gate + polarity
    verdict = block.get("verdict") or {}
    assert verdict.get("call") == safety_verdict
    assert verdict.get("gate") == "safety"

    # confidence.level valid
    assert (block.get("confidence") or {}).get("level") in _VALID_CONFIDENCE

    # hero lists the five liability axes, in order
    hero = block.get("hero") or {}
    assert [a.get("key") for a in (hero.get("axes") or [])] == _AXIS_KEYS

    # INVERSE VALENCE: a LoF-intolerant liability HOLD is UNdesirable for a drug program → negative badge.
    assert verdict.get("polarity") == "negative", (
        f"a safety-liability HOLD must colour the badge negative; got {verdict.get('polarity')!r}"
    )

    # deterministic headline text is always available
    assert isinstance(block.get("headline_text"), str) and block["headline_text"]
