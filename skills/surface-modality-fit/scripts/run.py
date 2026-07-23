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
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "surface-modality-fit"
SKILL_VERSION = "1.0.0"

CARDS = [
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "structure-features-static",
    "surface-abundance-density",
    "adc-tce-modality-fit",
    "normal-tissue-liability",          # HPA IHC on-target-off-tumor safety (wired 2026-07-20)
    "copy-number-distribution",         # P4 (2026-07-23) — genomic AMPLIFICATION → surface antigen-
                                        # density argument. The SAME card is in genomic-alteration-profile
                                        # (SM/degrader read); here it fires cn-amplified-surface-antigen-
                                        # supportive (adc/bite_tce/antibody) — Example B: one card, two
                                        # modality gates, divergent reads. ADDITIVE signal-only: its
                                        # surface rule feeds NO resolver rung (surface_modality resolves
                                        # off adc-tce-modality-fit.fit_class) → verdict byte-stable.
]

QUESTION = ("For {target} in {indication}, does the surface biology (topology, "
            "surfaceome family, structure pockets, abundance) support a biologics "
            "modality — is it ADC-favorable, TCE-favorable, both, or neither?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/surface_modality.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "surface_modality")
    if result is None:
        raise RuntimeError(
            "surface_modality resolver spec missing (target-contracts/resolvers/surface_modality.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

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
