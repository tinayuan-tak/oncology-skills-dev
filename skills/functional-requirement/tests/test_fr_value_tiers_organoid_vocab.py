"""#1550: `_FR_VALUE_TIERS` must key on the organoid-crispr-dependency card's REAL
`organoid_dependency_class` vocabulary, not a drifted/phantom one. Two phantom keys
(`lineage_organoid_dependency`, `no_organoid_dependency`) never emitted by the card were dead
code masking three missing real tokens (`pan_organoid_essential`, `rare_organoid_dependency`,
`not_organoid_dependent`) that fell through to `default_classify` -> `absent`, flipping their
polarity (per the module's own comment at run.py's `_FR_VALUE_TIERS` docstring). Verdict-INERT
(subgroup_signals/narrator only) — this pins the KEY SET and each real token's TIER, not any
resolver verdict.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from _test_support import load_run_py

_CARD_PATH = Path(__file__).resolve().parents[3] / "contracts" / "cards" / "organoid-crispr-dependency.card.yaml"


def _fr():
    return load_run_py(Path(__file__).resolve().parents[1], "fr_run")


def _card_organoid_tokens() -> set[str]:
    y = yaml.safe_load(_CARD_PATH.read_text())
    tokens = y["outputs"]["summary_fields_vocabulary"]["organoid_dependency_class"]
    return {t for t in tokens if t != "data_unavailable"}


def test_fr_value_tiers_has_no_phantom_organoid_keys():
    """Every organoid-* key in _FR_VALUE_TIERS must be a token the card actually declares."""
    fr = _fr()
    real_tokens = _card_organoid_tokens()
    mapped_organoid_keys = {k for k in fr._FR_VALUE_TIERS if "organoid" in k and k != "organoid_dependency_class"}
    phantom = mapped_organoid_keys - real_tokens
    assert not phantom, f"_FR_VALUE_TIERS has phantom organoid tokens not in the card: {phantom}"


def test_fr_value_tiers_covers_every_real_organoid_token():
    """Every real organoid_dependency_class token (minus data_unavailable, which resolves via the
    UNMEASURED path elsewhere) must have an explicit tier, so it never silently falls through the
    lens-blind default_classify heuristic to `absent`."""
    fr = _fr()
    real_tokens = _card_organoid_tokens()
    missing = real_tokens - set(fr._FR_VALUE_TIERS)
    assert not missing, f"_FR_VALUE_TIERS is missing real organoid tokens: {missing}"


def test_fr_value_tiers_organoid_polarity():
    """Pin the polarity of each real organoid token per the #1550 fix decision:
    pan_organoid_essential (common-essential-like) -> low target value = weak;
    broad_organoid_dependency -> strong; selective_organoid_dependency -> moderate;
    rare_organoid_dependency -> weak-positive; not_organoid_dependent -> absent."""
    fr = _fr()
    assert fr._FR_VALUE_TIERS["pan_organoid_essential"] == "weak"
    assert fr._FR_VALUE_TIERS["broad_organoid_dependency"] == "strong"
    assert fr._FR_VALUE_TIERS["selective_organoid_dependency"] == "moderate"
    assert fr._FR_VALUE_TIERS["rare_organoid_dependency"] == "weak"
    assert fr._FR_VALUE_TIERS["not_organoid_dependent"] == "absent"
