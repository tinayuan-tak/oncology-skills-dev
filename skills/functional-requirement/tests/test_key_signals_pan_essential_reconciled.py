"""key_signals must not over-claim a pan-essential (broad-tox liability) or a CRISPR/RNAi-discordant
target as a clean 'Strong genetic dependency.' — the dependency analog of the tumor-selectivity #862
over-claim (a human-facing surface contradicting the resolved verdict). The claim_vector already computes
the DEP `conflict`; dependency_key_signals must surface it in BOTH the headline and the caveat.

Verdict-INERT: exercises only the display surface (dependency_key_signals over a synthetic headline);
no resolver / verdict path is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

# skills/ root on path so `_skills_common` resolves (mirrors the sibling FR tests).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from _skills_common.dependency_claims import dependency_key_signals  # noqa: E402


def _headline(**over) -> dict:
    """A minimal FR headline dict with the class fields dependency_key_signals reads."""
    h = {
        "crispr_call": "strongly_selective",
        "rnai_call": "strongly_selective",
        "concordance_call": "strongly_concordant_dependent",
        "lineage_selectivity": "no_lineage_enrichment",
        "n_lineages_evaluated": 25,
        "partner_conditional_class": "no_partner_mapped",
        "prism_concordance_class": "not_triangulated",
        "n_compounds_evaluated": 12,
        "cross_consortium_class": "concordant_dependent",
        "predictability_class": "weakly_predictable",
    }
    h.update(over)
    return h


def test_pan_essential_headline_is_a_liability_not_a_win():
    ks = dependency_key_signals(_headline(crispr_call="common_essential", rnai_call="common_essential"), [])
    head = ks["headline"].lower()
    assert "pan-essential" in head and "liability" in head, (
        f"pan-essential key_signals headline should read as a broad-tox liability, got {ks['headline']!r}"
    )
    # must NOT frame it as a clean positive dependency win
    assert "strong genetic dependency" not in head
    # the pan-essential conflict is surfaced as the caveat (not a lesser SEL caveat)
    assert "pan-essential" in (ks["caveat"] or "").lower()


def test_crispr_dependent_rnai_disagree_headline_flags_non_corroboration():
    # CRISPR strongly-dependent but RNAi non-dependent → the DEP claim carries the RNAi-disagreement
    # conflict (verdict would be discordant). The headline must not read as an unqualified strong dependency.
    ks = dependency_key_signals(_headline(rnai_call="non_dependent", concordance_call="discordant"), [])
    head = ks["headline"].lower()
    assert "does not corroborate" in head or "rnai" in head, (
        f"discordant/RNAi-disagree headline should flag non-corroboration, got {ks['headline']!r}"
    )
    assert "does not corroborate" in (ks["caveat"] or "").lower()


def test_clean_selective_dependency_headline_unchanged():
    # a genuinely selective, non-conflicted dependency keeps its positive headline (no regression)
    ks = dependency_key_signals(
        _headline(lineage_selectivity="lineage_selective", prism_concordance_class="triangulated_target_engaged"), []
    )
    assert ks["headline"].startswith("Selective genetic dependency")
