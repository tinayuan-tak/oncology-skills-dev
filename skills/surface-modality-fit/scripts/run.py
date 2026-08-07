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
from _skills_common import get_card_field
from _skills_common.resolver import resolve_verdict_for_gate
from _skills_common.synthesis_surface_modality import synthesize_surface_modality

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orthogonality import score_orthogonality   # noqa: E402 — skill-local E7 facet


SKILL_NAME = "surface-modality-fit"
SKILL_VERSION = "1.1.0"   # sc-normal-celltype-expression — scRNA cell-type-resolved normal-tissue safety (sc_rna/normal)

CARDS = [
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "structure-features-static",
    "surface-abundance-density",
    "adc-tce-modality-fit",
    "normal-tissue-liability",          # HPA IHC on-target-off-tumor safety (wired 2026-07-20)
    "sc-normal-celltype-expression",    # biologics-augment Phase 3.3 (2026-08-07): scRNA cell-type-resolved
                                        # normal-tissue safety from Census pseudobulk (sc_rna/normal). Its F5
                                        # rules fire on sc_normal_expression_class: HIGH_LIABILITY →
                                        # bite_tce killer + adc/antibody opposing; MODERATE → all opposing;
                                        # NOT_EXPRESSED → supportive (dominant). Complements HPA IHC (F4):
                                        # IHC misses low-level inducible targets + can't distinguish cell
                                        # types (e.g. hepatocyte vs Kupffer cell). LIVE for colon+lung;
                                        # other tissues → data_unavailable (honest coverage gap). ADDITIVE
                                        # signal-only (no resolver rung → verdict byte-stable).
    "copy-number-distribution",         # P4 (2026-07-23) — genomic AMPLIFICATION → surface antigen-
                                        # density argument. The SAME card is in genomic-alteration-profile
                                        # (SM/degrader read); here it fires cn-amplified-surface-antigen-
                                        # supportive (adc/bite_tce/antibody) — Example B: one card, two
                                        # modality gates, divergent reads. ADDITIVE signal-only: its
                                        # surface rule feeds NO resolver rung (surface_modality resolves
                                        # off adc-tce-modality-fit.fit_class) → verdict byte-stable.
    "rna-protein-concordance-tumor",    # Orphan-fix (audit 2026-08-05): tier:indication RNA↔protein
                                        # concordance, modality_relevance [adc, bite_tce, antibody]. Its
                                        # surface-intrinsic rules (rna-poor-proxy-surface-warning [important,
                                        # OPPOSING] + rna-adequate-proxy-surface-supportive) already exist
                                        # but were UNREACHABLE — no skill composed the card. An RNA-based
                                        # read is a poor proxy for a SURFACE antigen when protein disagrees;
                                        # this is the tumor-grain twin of tumor-presence's cell-line concordance
                                        # facet. ADDITIVE signal-only: surface_modality resolves off
                                        # adc-tce-modality-fit.fit_class → verdict byte-stable.
    "protein-surface-evidence",         # Orphan-fix (biologics-augment Phase 1.1, 2026-08-06): CSPA wet-lab
                                        # surface confirmation (cspa-surface-confirmation-per-uniprot-v1), the
                                        # `measured` surface-residency tier. measurement_type surface_confirmation,
                                        # modality_relevance [adc, bite_tce, antibody], tier:target. Its rules
                                        # (protein-surface-confirmed-supportive [important] + protein-not-surface-
                                        # opposing [secondary, NOT killer]) were SILENTLY INERT on live data —
                                        # CSPA went live but no skill composed the card (it was a declared
                                        # measurement_types_pulled intent only). Measured protein-surface residency
                                        # is the strongest presence signal the surface gate can receive. ADDITIVE
                                        # signal-only (no resolver rung) → verdict byte-stable.
    "shed-ectodomain-liability",        # Orphan-fix (biologics-augment Phase 1.1, 2026-08-06): clinically-
                                        # established shed-ectodomain antigen-sink liability (curated serum-marker
                                        # crosswalk — CA125=MUC16, CEA=CEACAM5, SMRP=MSLN, shed-HER2-ECD). A
                                        # circulating soluble decoy sequesters antibody/ADC/TCE before tumor
                                        # delivery. measurement_type shed_ectodomain_liability, modality_relevance
                                        # [adc, bite_tce, antibody], tier:target. Its F3 rules (shed-ectodomain-
                                        # clinical-opposing + -secretome-proxy-opposing, both OPPOSING not killer —
                                        # approved biologics exist vs shed antigens) existed + were wired to the
                                        # surface_intrinsic axis but UNREACHABLE — no skill composed the card.
                                        # ADDITIVE signal-only (no resolver rung) → verdict byte-stable.
    "tumor-scrna-celltype-expression",  # biologics-augment Phase 3.2 (2026-08-06): within-tumor antigen
                                        # HOMOGENEITY via single-cell CELLxGENE Census (tce_homogeneity_class
                                        # facet — fraction of MALIGNANT cells expressing the target). For a
                                        # TCE, antigen heterogeneity is a program-killer (antigen-low cells
                                        # escape redirected killing — no bystander payload). Its surface rules
                                        # (sc-homogeneity-uniform-tce-supportive [important] + sc-homogeneity-
                                        # heterogeneous-tce-opposing [important, ADC neutral — the ADC-vs-TCE
                                        # discriminator]) fire on the tce_homogeneity_class categorical. The
                                        # card's PRIMARY sc_expression_class stays a presence-axis (Gate-A)
                                        # readout — this composes it for its BIOLOGICS-homogeneity facet only.
                                        # LIVE for COADREAD + NSCLC (Census per-cell malignant annotation);
                                        # other indications → data_unavailable (honest gap). ADDITIVE signal-
                                        # only (no resolver rung) → verdict byte-stable.
    "modality-therapeutic-window",      # biologics-augment window arc (2026-08-06): clean-antigen
                                        # THERAPEUTIC-WINDOW — tumor / max-essential-normal TPM ratio,
                                        # modality-tiered (scored strict/TCE by default). Reads
                                        # tcga-gtex-tpm-tissue-quantiles-v1 at claim-grade TPM. Surfaces the
                                        # CEACAM5 paradox (huge window yet strict-TCE liability) neither
                                        # tumor-vs-normal-selectivity (within-tissue) nor normal-tissue-
                                        # liability (off-tumor breadth) makes. Rules (modality-window-clean-
                                        # supportive / -essential-liability-tce-opposing [adc NEUTRAL — the
                                        # ADC-vs-TCE discriminator] / -narrow-opposing) fire on window_class.
                                        # Emits BOTH essential + full-normal ratios (Theme-1 fix). Cohort-
                                        # honest (DLL3/SCLC → not_expressed). ADDITIVE signal-only (no resolver
                                        # rung) → verdict byte-stable.
    "pmhc-presentation",                 # biologics enrichment E1 (2026-08-07): peptide-centric HLA
                                         # presentation (benign immunopeptidome). The peptide-centric TCE
                                         # axis — reaches INTRACELLULAR targets via the peptide-MHC complex
                                         # (KRAS/WT1/PRAME/MAGE-A4), invisible to surface presence. Its rules
                                         # (pmhc-restricted-presentation-tce-supportive / -broadly-presented-
                                         # normal-tce-opposing) fire on pmhc_presentation_class; bite_tce-only.
                                         # Benign-atlas = normal-presentation SAFETY denominator (broad=liability;
                                         # restricted=clean, MAGE-A4). ADDITIVE (no resolver rung) → byte-stable.
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
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "surface_modality_verdict":       v,
        "driving_rule_id":                drv,
        "fit_class":                      get_card_field(cards, "adc-tce-modality-fit", "fit_class"),
        "topology_class":                 get_card_field(cards, "surface-topology-and-ptm", "topology_class"),
        "family_class":                   get_card_field(cards, "surfaceome-family-classification", "family_class"),
        "hotspot_pocket_adjacency_call":  get_card_field(cards, "structure-features-static",
                                               "hotspot_pocket_adjacency_call"),
        "surface_density_class":          get_card_field(cards, "surface-abundance-density", "surface_density_class"),
        # Normal-tissue on-target-off-tumor safety (HPA IHC). Its rules fire on the
        # surface_intrinsic axis (adc/bite_tce/antibody): essential-tissue → BiTE killer
        # + adc/antibody opposing; broad footprint → opposing; restricted/not-detected →
        # supportive. Surfaced here so the biologics-fit call reflects the safety window.
        "normal_tissue_breadth_class":    get_card_field(cards, "normal-tissue-liability", "normal_tissue_breadth_class"),
        "essential_tissue_flag":          get_card_field(cards, "normal-tissue-liability", "essential_tissue_flag"),
        "normal_tissue_safety_flags":     get_card_field(cards, "normal-tissue-liability", "safety_tissue_flags"),
        # CSPA wet-lab surface confirmation (protein-surface-evidence). Its rules fire on the
        # surface_intrinsic axis (adc/bite_tce/antibody): cell_surface_confirmed → supportive
        # (important); not_surface → opposing (secondary, NOT killer). Measured protein-surface
        # residency — the strongest presence signal the surface gate receives. Additive; verdict
        # byte-stable (fit_class resolves off adc-tce-modality-fit).
        "surface_confirmation_class":     get_card_field(cards, "protein-surface-evidence", "surface_confirmation_class"),
        "surface_confirmation_n_celllines": get_card_field(cards, "protein-surface-evidence", "n_celllines_detected"),
        # Shed-ectodomain antigen-sink liability (shed-ectodomain-liability). Its F3 rules fire on
        # the surface_intrinsic axis (adc/bite_tce/antibody): clinically_shed / secretome_proxy_shed
        # → opposing (NOT killer — approved biologics exist against shed antigens; a shed ectodomain
        # demands a shed-resistant epitope + antigen-sink dose modeling). Additive; verdict byte-stable.
        "shed_liability_class":           get_card_field(cards, "shed-ectodomain-liability", "shed_liability_class"),
        "shed_serum_marker":              get_card_field(cards, "shed-ectodomain-liability", "serum_marker"),
        # MEASURED Olink conditioned-media shed facet (E3, card v1.1.0) — PARALLEL to the
        # annotation-based shed_liability_class (unchanged). media_shed_high fires shed-ectodomain-
        # measured-media-opposing (adc/bite_tce/antibody opposing — measurement-corroborated antigen
        # sink). Panel bounded + secretome-preselected → not_on_secreted_panel is NON-informative
        # (never a measured negative). Additive; verdict byte-stable (no resolver rung).
        "measured_shed_class":            get_card_field(cards, "shed-ectodomain-liability", "measured_shed_class"),
        "shed_media_mean_npx":            get_card_field(cards, "shed-ectodomain-liability", "media_mean_npx"),
        "shed_media_n_lines_detected":    get_card_field(cards, "shed-ectodomain-liability", "media_n_lines_detected"),
        # Within-tumor antigen homogeneity (tumor-scrna-celltype-expression, single-cell Census).
        # Its surface rules fire on tce_homogeneity_class (bite_tce/adc): homogeneous → TCE supportive
        # (uniform, low escape); heterogeneous → TCE opposing (antigen-low escape reservoir), ADC
        # neutral (bystander payload reaches antigen-low cells) — the ADC-vs-TCE discriminator.
        # LIVE for COADREAD + NSCLC only; else data_unavailable. Additive; verdict byte-stable.
        "tce_homogeneity_class":          get_card_field(cards, "tumor-scrna-celltype-expression", "tce_homogeneity_class"),
        "malignant_detection_fraction":   get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_detection_fraction"),
        # Modality therapeutic window (tumor / max-essential-normal TPM, strict/TCE tier). Its rules
        # fire on window_class: clean_window → supportive; essential_tissue_liability → bite_tce opposing
        # + adc/antibody NEUTRAL (the ADC-vs-TCE discriminator, CEACAM5 pattern); narrow_window →
        # opposing. Both denominators surfaced (Theme-1). Additive; verdict byte-stable.
        "window_class":                   get_card_field(cards, "modality-therapeutic-window", "window_class"),
        "window_ratio_essential":         get_card_field(cards, "modality-therapeutic-window", "window_ratio_essential"),
        "window_ratio_full_normal":       get_card_field(cards, "modality-therapeutic-window", "window_ratio_full_normal"),
        "window_max_essential_organ":     get_card_field(cards, "modality-therapeutic-window", "max_essential_normal_organ"),
        # Peptide-centric HLA presentation (pmhc-presentation) — the TCR-mimetic-TCE axis. Its rules fire
        # on pmhc_presentation_class (bite_tce): restricted → supportive (clean pMHC target); broad → opposing
        # (normal-presentation liability). Additive; verdict byte-stable. not_observed = weak-negative candidate.
        "pmhc_presentation_class":        get_card_field(cards, "pmhc-presentation", "pmhc_presentation_class"),
        "pmhc_n_normal_tissues":          get_card_field(cards, "pmhc-presentation", "n_normal_tissues_presented"),
        "pmhc_hla_class":                 get_card_field(cards, "pmhc-presentation", "hla_class"),
        # scRNA cell-type-resolved normal-tissue safety (sc-normal-celltype-expression, F5 rules).
        # F5 rules fire on sc_normal_expression_class on the surface_intrinsic axis: HIGH_LIABILITY →
        # bite_tce killer + adc/antibody opposing; NOT_EXPRESSED → supportive (dominant). Provides
        # cell-type-level resolution HPA IHC can't deliver (e.g. hepatocyte vs Kupffer cell, AT2 vs
        # alveolar macrophage). LIVE for colon+lung; other tissues → data_unavailable (named gap).
        # Additive; verdict byte-stable (no resolver rung — safety_essential_flags surfaced for LLM).
        "sc_normal_expression_class":     get_card_field(cards, "sc-normal-celltype-expression", "sc_normal_expression_class"),
        "sc_normal_max_det_cell_type":    get_card_field(cards, "sc-normal-celltype-expression", "max_detection_cell_type"),
        "sc_normal_max_det_fraction":     get_card_field(cards, "sc-normal-celltype-expression", "max_detection_fraction"),
        "sc_normal_n_cell_types_above_20pct": get_card_field(cards, "sc-normal-celltype-expression", "n_cell_types_above_20pct"),
        "sc_normal_safety_essential_flags": get_card_field(cards, "sc-normal-celltype-expression", "safety_essential_flags"),
    }
    # Orthogonality facet (E7, 2026-08-07) — VERDICT-INERT display meta-facet. Counts the
    # INDEPENDENT surface-biology dimensions with supporting evidence (the 6-card presence
    # cluster collapsed to ONE line, not counted 6x). A target corroborated across 4-5
    # orthogonal axes is a stronger biologics call than one resting on a single axis at the
    # same fit_class. Emitted as a headline sub-key; the surface_modality resolver keys ONLY
    # on adc-tce-modality-fit.fit_class rungs, so a headline key CANNOT move the verdict
    # (pinned by test_orthogonality_is_verdict_inert). Coverage vs support kept separate:
    # an abstaining dimension (data_unavailable) is a coverage gap, never an opposing vote.
    hl["orthogonality"] = score_orthogonality(cards)
    return hl


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="surface_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Opt-in --synthesize narrates through the SURFACE-MODALITY (biologics) lens — its own tool schema
        # + prompt, foregrounding ACCESSIBILITY (bindable ECD) then the ADC-vs-TCE discrimination axes
        # (normal-tissue liability, within-tumour homogeneity, shed sink, antigen density). Two-slot /
        # verdict-inert: the dispatcher attaches decision['llm_synthesis'] as a sibling key AFTER the
        # spine is composed, so it is structurally impossible for the narration to alter
        # surface_modality_verdict / fit_class. Without this synthesize_fn the dispatcher would fall back
        # to the PRESENCE narrator (wrong lens — B3b, 2026-08-06).
        synthesize_fn=synthesize_surface_modality,
        partial_status_note=("Most surface derived products (structure-features, "
                             "surfaceome-family, cohort-ranking) are not yet on S3; "
                             "verdict is honest-insufficient until they land."),
        isoform_check_target=True,   # arch A3: surface-modality claims need isoform caveats
    ))
