"""Guard for the _headline card-field reads (T5.1, 2026-08-09).

Bug fixed: _headline read `activity_class` / `concordance_class`, but the PRISM methods emit
`prism_activity_class` / `crispr_prism_concordance_class`. get_card_field returns None on a missing
KEY (it only raises on a bad card_id), so both headline fields were ALWAYS None → decision.json blank
+ the LLM synthesis prompt (synthesis_tractability_sm.py reads h['prism_activity_class'] /
['prism_crispr_concord']) starved of the two most important chemical facts. The pre-existing synthesis
test hardcoded the headline dict, so it could not catch this. This test runs _headline against cards
carrying the REAL emitted keys and asserts the two fields are surfaced (non-None).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run")


# _headline calls get_card_field on ALL 6 CARDS and get_card_field RAISES KeyError on a missing
# card_id — so every card_id must be present (empty summary is fine for the ones not under test).
_ALL_CARD_IDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
    "structure-features-static",
    "known-drug-tractability",
    "measured-potency-tractability",  # #1646: _headline now reads the POTENCY measured-binding leg
    "degradation-feasibility",
    "gdsc-drug-activity",
    "mutation-hotspot-frequency",  # #993 pt1: read by _minority_allele_coverage_caveat
]  # 2026-08-25: _headline now reads the GDSC 2nd-platform display card


def _cards(**summaries):
    """All 6 headline cards present; `summaries` supplies real emitted keys per card_id under test."""
    return [{"card_id": cid, "summary": summaries.get(cid, {})} for cid in _ALL_CARD_IDS]


def test_headline_surfaces_prism_activity_and_concordance():
    cards = _cards(
        **{
            "prism-compound-activity": {"prism_activity_class": "clinically_active"},
            "prism-crispr-concordance": {"crispr_prism_concordance_class": "concordant_on_target"},
        }
    )
    h = tp._headline(cards, fired=[], verdict_pair=("chemically_active", "prism-clinically-active-supportive-sm"))
    # the two fields the bug blanked — must now carry the real card values
    assert h["prism_activity_class"] == "clinically_active", (
        "headline must read the REAL key prism_activity_class (was reading 'activity_class' → None)"
    )
    assert h["prism_crispr_concord"] == "concordant_on_target", (
        "headline must read the REAL key crispr_prism_concordance_class (was reading 'concordance_class' → None)"
    )


def test_headline_fields_are_none_when_prism_summaries_empty():
    # honest coverage-gap: PRISM cards present but no activity/concordance value → the fields are None
    h = tp._headline(_cards(), fired=[], verdict_pair=("insufficient", None))
    assert h["prism_activity_class"] is None
    assert h["prism_crispr_concord"] is None
