#!/usr/bin/env python3
"""surface-modality-fit — biologics-modality (ADC / TCE) fitness from surface biology.

Consumes the 5 surface/structure cards + the composed adc-tce-modality-fit card,
firing the surface-intrinsic rule subset. Emits a data-package output tree with
a rank-ordered surface-modality verdict.

SPLIT 2026-07-14: this is the biologics-modality half of the former
`tractability-and-modality` skill. In that skill these 6 cards were merely
DISPLAYED in the headline — they could not change its (chemical-genetic)
verdict. This skill makes the surface-modality call they support, resolving
from the composed `adc-tce-modality-fit` card's `fit_class` (which itself fuses
topology / family / structure / density). When the composed card's inputs are
data_unavailable the verdict is an honest `insufficient` — most surface derived
products (structure-features, surfaceome-family, cohort-ranking) are not yet on
S3. See docs/SKILLS_SCOPE_REVIEW_2026-07-14.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "surface-modality-fit"
SKILL_VERSION = "1.0.0"

CARDS = [
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "structure-features-static",
    "surface-abundance-density",
    "adc-tce-modality-fit",
    "normal-tissue-liability",          # HPA IHC on-target-off-tumor safety (wired 2026-07-20)
]

QUESTION = ("For {target} in {indication}, does the surface biology (topology, "
            "surfaceome family, structure pockets, abundance) support a biologics "
            "modality — is it ADC-favorable, TCE-favorable, both, or neither?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Rank-ordered surface-modality resolution (first match wins).

    Resolves from the composed adc-tce-modality-fit `fit_class` rules — the
    single card that fuses the surface leaves into a modality call. When those
    rules did not fire (fit_class data_unavailable, or the composed card's
    surface inputs are absent), returns an honest `insufficient` rather than
    fabricating a modality verdict.

    NOTE (design gap flagged 2026-07-14): fit_class == `modality_ambiguous`
    has NO rule in surface-intrinsic.rules.yaml, so a target landing there fires
    nothing and falls through to `insufficient`. Adding that rule is in
    target-contracts' PR #2 (rule-coverage-holes) territory, not this branch.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    # Map the adc-tce-modality-fit fit_class rules to a surface-modality verdict.
    if "adc-preferred-supportive" in fired_by_id:
        return "adc_preferred", "adc-preferred-supportive"
    if "tce-preferred-supportive" in fired_by_id:
        return "tce_preferred", "tce-preferred-supportive"
    if "both-viable-supportive" in fired_by_id:
        return "both_viable", "both-viable-supportive"
    if "neither-viable-killer" in fired_by_id:
        return "neither_viable", "neither-viable-killer"
    if "isoform-dependent-modality-suppression" in fired_by_id:
        return "isoform_dependent_undefined", "isoform-dependent-modality-suppression"
    # C2 fix (2026-07-20): modality_ambiguous previously had NO rule + NO branch → the
    # skill fell through SILENTLY to insufficient (an unhandled fireable state, not an
    # honest gap). Now an EXPLICIT, provenance-carrying verdict: surface biology is
    # in-scope but does not resolve a modality direction. Distinct from a bare
    # insufficient (nothing fired) — this one names WHY (mixed/conflicting fit).
    if "modality-ambiguous-insufficient" in fired_by_id:
        return "modality_ambiguous", "modality-ambiguous-insufficient"
    return "insufficient", None


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "surface_modality_verdict":       v,
        "driving_rule_id":                drv,
        "fit_class":                      _get("adc-tce-modality-fit", "fit_class"),
        "topology_class":                 _get("surface-topology-and-ptm", "topology_class"),
        "family_class":                   _get("surfaceome-family-classification", "family_class"),
        "hotspot_pocket_adjacency_call":  _get("structure-features-static",
                                               "hotspot_pocket_adjacency_call"),
        "surface_density_class":          _get("surface-abundance-density", "surface_density_class"),
        # Normal-tissue on-target-off-tumor safety (HPA IHC). Its rules fire on the
        # surface_intrinsic axis (adc/bite_tce/antibody): essential-tissue → BiTE killer
        # + adc/antibody opposing; broad footprint → opposing; restricted/not-detected →
        # supportive. Surfaced here so the biologics-fit call reflects the safety window.
        "normal_tissue_breadth_class":    _get("normal-tissue-liability", "normal_tissue_breadth_class"),
        "essential_tissue_flag":          _get("normal-tissue-liability", "essential_tissue_flag"),
        "normal_tissue_safety_flags":     _get("normal-tissue-liability", "safety_tissue_flags"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="surface_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        partial_status_note=("Most surface derived products (structure-features, "
                             "surfaceome-family, cohort-ranking) are not yet on S3; "
                             "verdict is honest-insufficient until they land."),
        isoform_check_target=True,   # arch A3: surface-modality claims need isoform caveats
    ))
