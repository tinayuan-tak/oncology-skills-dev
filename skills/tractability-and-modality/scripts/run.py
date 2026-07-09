#!/usr/bin/env python3
"""tractability-and-modality — chemical-genetic druggability + Phase-F surface features.

Consumes 9 cards (3 chemical-genetic + 6 Layer-6b F-phase additions) + the
prism-* / predictability-* / E7 rule subsets + the new surface-intrinsic
rules. Emits a data-package output tree with a rank-ordered druggability
snapshot and optional modality-lensed viability tally.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "tractability-and-modality"
SKILL_VERSION = "2.1.0"

CARDS = [
    # Original chemical-genetic cards
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
    # Layer 6b additions — 6 F-phase cards
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "structure-features-static",
    "surface-abundance-density",
    "adc-tce-modality-fit",
    "surfaceome-cohort-ranking",
]

QUESTION = ("Does {target} in {indication} show chemical-genetic druggability "
            "evidence — is there a compound that hits it, does it look ADC/TCE-"
            "favorable topologically, and does the surface family confirm?")


def _snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered snapshot resolution."""
    fired_by_id = {r["rule_id"]: r for r in fired}
    if "e7-triangulated-target-engaged-supportive" in fired_by_id:
        return "well_covered", "e7-triangulated-target-engaged-supportive"
    if "e7-crispr-confirmed-supportive-sm" in fired_by_id:
        return "chemically_confirmed_genetic", "e7-crispr-confirmed-supportive-sm"
    if "prism-clinically-active-supportive-sm" in fired_by_id:
        return "chemically_active", "prism-clinically-active-supportive-sm"
    if "prism-tool-compound-only-weak-supportive-sm" in fired_by_id:
        return "tool_compound_only", "prism-tool-compound-only-weak-supportive-sm"
    if "prism-weakly-active-weak-supportive-sm" in fired_by_id:
        return "weakly_active", "prism-weakly-active-weak-supportive-sm"
    if "e7-discordant-off-target-warning" in fired_by_id:
        return "discordant", "e7-discordant-off-target-warning"
    if "prism-no-compounds-found-neutral" in fired_by_id:
        return "chemically_unhit", "prism-no-compounds-found-neutral"
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "druggability_snapshot":     v,
        "driving_rule_id":           drv,
        # Chemical-genetic (3 cards)
        "prism_activity_class":      _get("prism-compound-activity", "activity_class"),
        "prism_crispr_concord":      _get("prism-crispr-concordance", "concordance_class"),
        "predictability_class":      _get("dependency-predictability", "predictability_class"),
        # Layer 6b surface F-phase (6 cards) — biology-agnostic fields only
        # (letter grades are lens-conditional; dispatcher adds them separately
        # when --modality is invoked via modality_lenses).
        "topology_class":            _get("surface-topology-and-ptm", "topology_class"),
        "family_class":              _get("surfaceome-family-classification", "family_class"),
        "hotspot_pocket_adjacency_call": _get("structure-features-static",
                                              "hotspot_pocket_adjacency_call"),
        "surface_density_class":     _get("surface-abundance-density", "surface_density_class"),
        "fit_class":                 _get("adc-tce-modality-fit", "fit_class"),
        "cohort_rank_class":         _get("surfaceome-cohort-ranking", "cohort_rank_class"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",     # consumes both intracellular + surface rules
        question=QUESTION,
        verdict_fn=_snapshot,
        headline_fn=_headline,
    ))
