#!/usr/bin/env python3
"""tractability-small-molecule — chemical-genetic + structural small-molecule druggability.

Consumes the 3 chemical-genetic cards (prism-compound-activity — the CHEMICAL arm
of the dependency question, i.e. "does a compound perturb the target"; plus
prism-crispr-concordance, dependency-predictability) AND the structure-features-static
card (FORWARD ligandability) + the prism-* / predictability-* / E7 / E8 rule subsets.
Emits a data-package output tree with a rank-ordered small-molecule druggability snapshot.

SPLIT 2026-07-14: this is the small-molecule half of the former
`tractability-and-modality` skill. That skill had grown to 9 cards, but 6 of
them (surface topology / family / structure / density / adc-tce-fit / cohort-
ranking) could NOT change its verdict — the `_snapshot()` keyed entirely off
the 3 chemical-genetic rules. The surface cards were split out into the
sibling `surface-modality-fit` skill. See docs/SKILLS_SCOPE_REVIEW_2026-07-14.md.

E8 structure/ligandability (2026-07-17, gate-scaffold backtest follow-up): the
PRISM cards are RETROSPECTIVE — they credit only targets a compound has ALREADY
hit, so a structurally-druggable-but-not-yet-drugged target (the KRAS-G12C
switch-II pocket pre-sotorasib) read as `chemically_unhit`/`insufficient`. Added
structure-features-static + the intracellular E8 rules so a druggable pocket now
raises a FORWARD `structurally_ligandable` snapshot (ranked below a real chemical
hit, above chemically_unhit). structure-features-static is ALSO consumed by
surface-modality-fit on the surface axis — its surface rules stay there; the E8
rules here are small_molecule-scoped (rule_id suffix -e8).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "tractability-small-molecule"
SKILL_VERSION = "3.1.0"     # 3.1.0: + structure-features-static (E8 forward ligandability).
                            # 3.0.0: split from tractability-and-modality 2.1.0.

CARDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
    "structure-features-static",   # E8: FORWARD ligandability (pocket structure)
]

QUESTION = ("Does {target} in {indication} show small-molecule druggability evidence "
            "— is there a compound that hits it (chemical), does that agree with the "
            "genetic dependency, and is there a druggable pocket even absent a known "
            "compound (structural / forward ligandability)?")


def _snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered small-molecule druggability resolution (first match wins).

    Chemical-genetic evidence (E6/E7, RETROSPECTIVE — a compound has actually hit
    the target) ranks highest. Structural / forward ligandability (E8 — a druggable
    pocket, added 2026-07-17) ranks BELOW a real chemical hit but ABOVE
    `chemically_unhit`: a druggable-but-not-yet-drugged target (KRAS-G12C switch-II
    pre-sotorasib) is a genuinely better SM prospect than one with no handle at all.
    A measured structural NEGATIVE (low-confidence/disordered fold) ranks with the
    weak-chemical tier as an SM-opposing note.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    # --- Chemical-genetic (retrospective: a compound was found) ---
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
    # --- Structural / forward ligandability (E8: druggable pocket, no compound yet) ---
    # Ranked below any real chemical hit, above chemically_unhit — a druggable pocket
    # is a positive SM prospect even before a compound exists (the KRAS-G12C fix).
    if "hotspot-in-druggable-pocket-sm-supportive-e8" in fired_by_id:
        return "structurally_ligandable", "hotspot-in-druggable-pocket-sm-supportive-e8"
    if "structure-pocket-adjacent-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "structure-pocket-adjacent-sm-supportive"
    # --- Opposing / negative reads ---
    if "e7-discordant-off-target-warning" in fired_by_id:
        return "discordant", "e7-discordant-off-target-warning"
    if "structure-low-confidence-sm-opposing" in fired_by_id:
        return "structurally_intractable", "structure-low-confidence-sm-opposing"
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
        "prism_activity_class":      _get("prism-compound-activity", "activity_class"),
        "prism_crispr_concord":      _get("prism-crispr-concordance", "concordance_class"),
        "predictability_class":      _get("dependency-predictability", "predictability_class"),
        # E8 structural / forward ligandability (2026-07-17)
        "hotspot_pocket_adjacency":  _get("structure-features-static", "hotspot_pocket_adjacency_call"),
        "hotspot_in_druggable_pocket": _get("structure-features-static", "mutation_hotspot_in_druggable_pocket"),
        "pdb_coverage_class":        _get("structure-features-static", "pdb_coverage_class"),
        "alphafold_confidence_class": _get("structure-features-static", "alphafold_confidence_class"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_snapshot,
        headline_fn=_headline,
    ))
