"""Phase-1a: claim-A B3 de-cap / Delta-2 (percentile-led).

`_claim_A` used to cap abundance at `moderate` for any target reading `within positives (n/m)` on the
control anchor — even a 99.7th-all-gene-percentile antigen (EPCAM). The control anchor is a
conservative FLOOR, not a ceiling: a top-percentile antigen there is still STRONG abundance. This lets
the calibrated all-gene percentile LEAD when it beats the anchor (pct >= 95), leaving mid/low
percentiles on the anchor floor. VERDICT-INERT — claim_vector never feeds presence_verdict; the golden
spine + replay suites prove the collapsed verdict is byte-stable.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread.yaml"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.presence_claims import _claim_A  # noqa: E402


def _c(control_position, pct, med=9.6):
    return {
        "tumor-rna-distribution": {
            "control_position": control_position,
            "allgene_percentile": pct,
            "median_log2tpm": med,
        }
    }


def test_within_positives_top_percentile_is_strong():
    """The B3 case: within-positives anchor + top-1% all-gene percentile → strong (was capped moderate)."""
    a = _claim_A({}, _c("above 3/4 positive control(s); above 3/5 negative control(s)", 99.7))
    assert a["signal"] == "strong"
    assert "percentile-led" in a["evidence"]


def test_within_positives_mid_percentile_stays_moderate():
    """De-cap must NOT over-fire: a within-positives target at a mid percentile stays moderate."""
    a = _claim_A({}, _c("above 3/4 positive control(s); above 3/5 negative control(s)", 80.0))
    assert a["signal"] == "moderate"


def test_above_all_positives_unchanged():
    """The strong anchor branch (npos == mpos) is untouched."""
    a = _claim_A({}, _c("above 4/4 positive control(s)", 99.7))
    assert a["signal"] == "strong"


def test_below_positives_floor_unchanged():
    """Low-percentile floor branch is untouched (no spurious lift)."""
    a = _claim_A({}, _c("above 0/4 positive control(s); above 1/5 negative control(s)", 30.0))
    assert a["signal"] == "absent"


@pytest.fixture(scope="module")
def _epcam_headline(tmp_path_factory):
    if not FIXTURE.exists():
        pytest.skip("no frozen fixture")
    frozen = yaml.safe_load(FIXTURE.read_text()) or {}
    import _skills_common as skc

    def _factory():
        def _read(cid, t, i, *a, **k):
            s = frozen.get(cid)
            if not (isinstance(s, dict) and s and not s.get("_freeze_error")):
                return None
            return copy.deepcopy(s)

        return _read

    out = tmp_path_factory.mktemp("claim-a-decap")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "EPCAM", "--indication", "COADREAD", "--out", str(out)])
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit:
        pass
    finally:
        mp.undo()
    return json.loads((out / "decision.json").read_text()).get("headline", {})


def test_epcam_claim_a_strong_and_verdict_stable(_epcam_headline):
    """On the real EPCAM/COADREAD fixture, claim A is now `strong` AND the collapsed presence_verdict
    is unchanged (byte-stable spine — the enrichment is verdict-inert)."""
    a = (_epcam_headline.get("claim_vector") or {}).get("A") or {}
    assert a.get("signal") == "strong", f"claim A signal={a.get('signal')!r}, expected strong (de-cap)"
    assert _epcam_headline.get("presence_verdict") == "tumor_broadly_expressed", (
        "presence_verdict moved — the claim-A enrichment must be verdict-inert"
    )
