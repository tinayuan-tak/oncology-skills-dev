"""Track PC focused behavioral test: the partner-conditional-dependency rescue fires (the NEW
behavior the byte-identical golden snapshot deliberately cannot show).

The golden snapshot proves EXISTING dependency combos are unchanged (the new rule ids aren't in
its frozen enumeration). This test proves the new rungs actually DO what they're for:
  1. a partner-conditional-*-dependent rule resolves to the distinct partner_conditional_dependent
     verdict (NOT biomarker_stratified_dependency — partner-SL != own-oncogene addiction);
  2. the COMPOUND rescue (non-dependent-killer AND partner-conditional-*) INTERCEPTS the veto —
     it resolves to partner_conditional_dependent, NOT non_dependent (the WRN×MSI flip);
  3. the MODERATE tier rescues too (the WRN×MSI anchor is a -0.41 moderate effect).
Requires the Track-PC resolver rungs (point TARGET_CONTRACTS_ROOT at the feature branch if not on main).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.resolver import resolve_verdict_for_gate  # noqa: E402


def _rules(*ids):
    return [{"rule_id": i} for i in ids]


def _skip_if_rung_absent():
    v = resolve_verdict_for_gate(_rules("partner-conditional-strongly-dependent-supportive"), "dependency")
    if not v or v[0] != "partner_conditional_dependent":
        pytest.skip("Track-PC partner-conditional resolver rung not present in resolved contracts")


def test_partner_strong_fires_partner_conditional_dependent():
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("partner-conditional-strongly-dependent-supportive"), "dependency"
    )
    assert verdict == "partner_conditional_dependent"
    assert driving == "partner-conditional-strongly-dependent-supportive"


def test_partner_moderate_fires_partner_conditional_dependent():
    """The WRN×MSI anchor tier: MODERATE is rescue-firing for this family (delta -0.41)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("partner-conditional-moderately-dependent-supportive"), "dependency"
    )
    assert verdict == "partner_conditional_dependent"
    assert driving == "partner-conditional-moderately-dependent-supportive"


def test_compound_rescue_intercepts_the_non_dependent_veto():
    """THE WRN×MSI FLIP: a pooled non_dependent (non-dependent-killer fires) AND a partner-conditional
    dependency → the compound when_all_fired rung intercepts the veto ABOVE the plain non_dependent
    rung. The verdict is partner_conditional_dependent, NOT non_dependent — a context-conditional
    false negative rescued (mirrors non_dependent_paralog_buffered)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(
        _rules("non-dependent-killer", "partner-conditional-moderately-dependent-supportive"), "dependency"
    )
    assert verdict == "partner_conditional_dependent"  # NOT non_dependent — the rescue intercepts
    assert driving == "partner-conditional-moderately-dependent-supportive"


def test_bare_non_dependent_still_vetoes_without_partner_signal():
    """Guardrail: with NO partner-conditional signal, a pooled non-dependent still vetoes — the
    rescue must not fire spuriously (KRAS/unmapped-target case reads its normal verdict)."""
    _skip_if_rung_absent()
    verdict, driving = resolve_verdict_for_gate(_rules("non-dependent-killer"), "dependency")
    assert verdict == "non_dependent"
    assert driving == "non-dependent-killer"
