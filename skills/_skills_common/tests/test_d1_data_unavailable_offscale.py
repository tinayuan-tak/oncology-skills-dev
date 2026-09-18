"""D-1 — a `data_unavailable` gating axis renders OFF-SCALE (not_scored), not on-scale neutral.

canonical_polarity mapped data_unavailable -> neutral, so "we couldn't assess this axis" read like a
benign measured finding (the differentiation case). D-1 returns the off-scale token `not_scored` for a
data_unavailable call. Scoped to data_unavailable ONLY: a measured-but-neutral call stays neutral.
Verdict-inert to the resolver (skill_report never moves a verdict); it changes the emitted polarity.
"""

from __future__ import annotations

from _skills_common.skill_report import ROLE_DESCRIPTIVE, ROLE_GATING, ROLE_INERT, canonical_polarity


def _hb(call, polarity):
    return {"verdict": {"call": call, "polarity": polarity}}


def test_data_unavailable_gating_is_offscale():
    assert canonical_polarity(ROLE_GATING, _hb("data_unavailable", "neutral")) == "not_scored"


def test_measured_neutral_call_stays_neutral():
    # a MEASURED, directionally-neutral gating call must NOT move off-scale.
    for call in ("well_characterized", "partial", "missense_dominant_pattern", "mixed_pattern"):
        assert canonical_polarity(ROLE_GATING, _hb(call, "neutral")) == "neutral", call


def test_positive_negative_calls_unchanged():
    assert canonical_polarity(ROLE_GATING, _hb("strong_dependency", "positive")) == "supportive"
    assert canonical_polarity(ROLE_GATING, _hb("non_dependent", "negative")) == "opposing"


def test_descriptive_and_inert_still_not_scored():
    assert canonical_polarity(ROLE_DESCRIPTIVE, _hb("anything", "neutral")) == "not_scored"
    assert canonical_polarity(ROLE_INERT, _hb("data_unavailable", "neutral")) == "not_scored"


def test_explicit_override_still_wins_over_d1():
    # a skill that deliberately passes an explicit canonical polarity keeps it, even for data_unavailable.
    assert canonical_polarity(ROLE_GATING, _hb("data_unavailable", "neutral"), explicit="killer") == "killer"


def test_missing_headline_defaults_neutral_not_offscale():
    # no headline block at all is NOT the same as data_unavailable — it defaults to neutral (unchanged).
    assert canonical_polarity(ROLE_GATING, None) == "neutral"
    assert canonical_polarity(ROLE_GATING, {}) == "neutral"
