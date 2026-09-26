"""#1819 — the signals-first subgroup reader's _DIFFERENTIATION_VALUE_TIERS map (in run.py) must
cover every token the differentiation cards actually emit, so no emitted token falls through
default_classify and gets mis-tiered to `absent` (a measured signal flipped to "no signal").

The canonical per-axis tier maps are the source of truth in _skills_common/differentiation_claims.py
(_COMUT_SIGNAL / _SURVIVAL_SIGNAL / _PROGNOSIS_SIGNAL / _NODE_SIGNAL). This test pins the subgroup
reader's map to their union so the two never drift apart again (instance of #1644)."""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SKILLS = SKILL_DIR.parent
for p in (str(SKILLS),):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common import differentiation_claims as dc  # noqa: E402


def _load_value_tiers() -> dict:
    spec = importlib.util.spec_from_file_location("_diff_run_vt", SKILL_DIR / "scripts" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # top-level only; no __main__ side effects
    return dict(mod._DIFFERENTIATION_VALUE_TIERS)


def _canonical_emitted() -> dict:
    """Union of the canonical per-axis tier maps = the vocab the cards emit."""
    merged: dict = {}
    for m in (dc._COMUT_SIGNAL, dc._SURVIVAL_SIGNAL, dc._PROGNOSIS_SIGNAL, dc._NODE_SIGNAL):
        for k, v in m.items():
            merged[k] = v
    # `data_unavailable` is the shared unmeasured sentinel across axes.
    return merged


def test_value_tiers_cover_emitted_vocab():
    value_tiers = _load_value_tiers()
    emitted = _canonical_emitted()
    missing = sorted(k for k in emitted if k not in value_tiers)
    assert not missing, f"emitted tokens missing from _DIFFERENTIATION_VALUE_TIERS (fall through to absent): {missing}"


def test_value_tiers_agree_with_canonical():
    value_tiers = _load_value_tiers()
    emitted = _canonical_emitted()
    disagree = {k: (value_tiers[k], emitted[k]) for k in emitted if value_tiers.get(k) != emitted[k]}
    assert not disagree, f"subgroup-reader tier disagrees with canonical claim-vector tier: {disagree}"


def test_value_tiers_use_valid_tiers():
    valid = {"strong", "moderate", "weak", "absent", "unmeasured"}
    bad = {k: v for k, v in _load_value_tiers().items() if v not in valid}
    assert not bad, f"invalid tier values: {bad}"
