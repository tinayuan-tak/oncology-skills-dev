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
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import SURFACE_MODALITY_FIT as _LENS
from _skills_common import get_card_field, card_summary
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record
from _skills_common.reachability import verdict_relevant_cards
from _skills_common.surface_claims import surface_claim_vector, surface_key_signals
from _skills_common.surface_modality_question_table import surface_modality_question_table
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_GATING
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier

# ─── Signals-first sub-group reader (verdict-INERT) ──────────────────────────────────────────────
# The fleet-default heuristic tags this lens's strongest POSITIVE fit signals (both_viable, high /
# confirmed_high density, tcell_validated, selective_and_pair, single-pass topology) as `absent`.
# _SURFACE_VALUE_TIERS states the tier for the surface-modality vocabulary (signal = strength of
# evidence FOR a viable biologics modality); intracellular topology, normal-tissue / exon liability
# and shedding are NEGATIVE evidence → `absent`. default_classify is the fallback. VERDICT-INERT.
_SURFACE_VALUE_TIERS = {
    "both_viable": "strong", "adc_preferred": "strong", "tce_preferred": "strong",
    "pmhc_tce_supported": "strong", "one_viable": "moderate", "neither_viable": "absent",
    "insufficient": "absent",
    "single_pass": "strong", "gpi_anchored": "strong", "multi_pass": "moderate",
    "no_transmembrane": "absent", "intracellular": "absent",
    "high": "strong", "confirmed_high": "strong", "adequate_proxy": "strong",
    "malignant_broadly_detected": "strong", "moderate": "moderate", "low": "weak",
    "tcell_validated": "strong", "selective_and_pair": "strong", "broadly_presented_normal": "absent",
    "transporter": "moderate", "receptor": "moderate", "adhesion": "moderate", "enzyme": "moderate",
    # normal-tissue / exon liability + shedding = NEGATIVE evidence for a clean surface modality
    "essential_tissue_liability": "absent", "essential_exon_liability": "absent",
    "high_liability": "absent", "moderate_normal_expression": "weak",
    "clinically_shed": "absent", "not_cd_antigen": "absent",
}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orthogonality import score_orthogonality   # noqa: E402 — skill-local facet


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# The surface-modality declaration for the shared headline_core builder: the 5 surface claim axes
# (FIT/TOPOLOGY/DENSITY/SAFETY/SHED, critical = FIT+TOPOLOGY), the composed `fit_class` vocabulary →
# human phrase, and the resolver's KILLER/downgrade (safety/density/shed) verdict as the skill-specific
# tension source. Verdict-INERT — a one-way projection over the computed headline (spine byte-stable).
# The canonical `call` is the composed adc-tce-modality-fit `fit_class` (the modality-substrate call the
# FIT claim axis keys on); the resolver's safety/density/shed DOWNGRADE — which lives in
# surface_modality_verdict, not fit_class — is surfaced as the sharpest top tension (like presence's
# buried cross-modal killer), so a reader of the one canonical call is not falsely reassured.
_FIT_CLASS_PHRASE = {
    # positives — a viable / preferred biologics-modality substrate
    "ADC_preferred": "ADC-favorable",
    "TCE_preferred": "TCE-favorable",
    "both_viable":   "ADC & TCE viable",
    # measured negative — no viable surface-modality substrate
    "neither_viable": "Neither ADC nor TCE viable",
    # gaps / undefined
    "modality_ambiguous":          "Modality ambiguous",
    "isoform_dependent_undefined": "Isoform-dependent (undefined)",
    "insufficient":                "Insufficient evidence",
    "data_unavailable":            "Data unavailable",
}
_FIT_CLASS_POSITIVE = frozenset({"ADC_preferred", "TCE_preferred", "both_viable"})
_FIT_CLASS_NEGATIVE = frozenset({"neither_viable"})

# The resolver DOWNGRADE verdicts (surface_modality_verdict, NOT fit_class) — a KILLER safety liability,
# a below-floor antigen density, or a clinically-shed ectodomain that opposes the base fit. Each is the
# skill's sharpest caveat when it fires, so it wins the single top-tension slot (severity 3).
_SURFACE_DOWNGRADE_REASON = {
    "adc_preferred_tce_unsafe":       "a normal-tissue on-target-off-tumor liability makes the TCE arm unsafe (ADC still preferred)",
    "tce_unsafe_normal_liability":    "a normal-tissue on-target-off-tumor liability makes the TCE arm unsafe",
    "surface_viable_density_caveated": "measured antigen surface density reads below the TCE payload floor",
    "shed_dominant_opposed":          "a clinically-shed ectodomain acts as a circulating antigen sink / decoy",
}


def _surface_tension_extra(headline: dict):
    """The resolver KILLER/downgrade (safety / density / shed) — carried in surface_modality_verdict but
    NOT in the canonical fit_class `call` — is surface-modality-fit's sharpest caveat. Surfaced so the
    one-word fit_class call does not hide a TCE-unsafe / below-density-floor / shed-sink downgrade.

    pmhc_tce_supported (2026-08-25) is the INVERSE case: the fit_class `call` is neither_viable (a NEGATIVE
    badge) yet a SEPARATE pMHC-TCE route is supported by experimentally-validated IEDB epitopes — the
    folded-surface ladder cannot see it. Surface it as the top note so the "Neither ADC nor TCE viable"
    call is not falsely read as "no biologics route" for an intracellular oncoprotein (WT1/PRAME/NY-ESO-1/
    MAGE-A4). Same slot/severity — it is the sharpest correction to the one-word call."""
    v = headline.get("surface_modality_verdict")
    if v == "pmhc_tce_supported":
        drv = headline.get("driving_rule_id")
        strength = ("T-cell-validated" if drv == "pmhc-iedb-tcell-validated-tce-supportive"
                    else "HLA-presented (T-cell recognition uncharacterised)")
        return {"text": f"surface fit_class=neither_viable, BUT experimentally-validated pMHC epitopes "
                        f"({strength}) support a TCR-mimetic peptide-MHC T-cell engager (pMHC-TCE) route "
                        f"the folded-surface ladder cannot see — surface: neither_viable; pMHC-TCE: supported",
                "source": "pmhc_tce_route", "severity": 3}
    reason = _SURFACE_DOWNGRADE_REASON.get(v)
    if reason:
        return {"text": f"surface verdict downgraded to {v}: {reason} (base fit_class="
                        f"{headline.get('fit_class')})",
                "source": "surface_modality_downgrade", "severity": 3}
    return None


_SURFACE_HEADLINE_SPEC = HeadlineSpec(
    gate="surface_modality",
    axis_labels={"FIT": "ADC/TCE modality fit", "TOPOLOGY": "surface topology / ECD",
                 "DENSITY": "antigen abundance", "SAFETY": "normal-tissue window",
                 "SHED": "ectodomain shedding"},
    axis_keys=("FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"),
    critical_axes=("FIT", "TOPOLOGY"),
    verdict_label=lambda v: _FIT_CLASS_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_surface_tension_extra,
)


def _fit_class_polarity(fit_class) -> str:
    """The skill's OWN reading of the modality-fit call (colours the hero badge; never a gate). Positive
    for a viable/preferred modality; negative for neither_viable; neutral for gaps / undefined."""
    if fit_class in _FIT_CLASS_POSITIVE:
        return "positive"
    if fit_class in _FIT_CLASS_NEGATIVE:
        return "negative"
    return "neutral"


# ── PER-MODALITY-ARM decomposition (2026-09-01) ──────────────────────────────────────────────────
# The one-word surface_modality_verdict packs the ADC-vs-TCE call into a compound token
# (adc_preferred_tce_unsafe = ADC viable, TCE unsafe); this projects the RESOLVED token onto explicit
# {adc, bite_tce, antibody} arms (+ pmhc_tce for the intracellular pMHC route) so a consumer need not
# string-parse the token. Mirrors safety_verdict_by_modality / presence_verdict_by_modality. It is a pure
# PROJECTION OF the resolved token — so it CANNOT disagree with surface_modality_verdict (the byte-stable
# compressed label), and is verdict-INERT to the nomination spine. Arm semantics are the resolver's own
# (SKILL.md): a bite_tce-only killer "drops TCE, PRESERVES ADC" (adc_preferred_tce_unsafe); the
# tce_preferred-base foreclosures are TCE-only targets (adc/antibody were not the fit's pick →
# not_preferred); density/shed hit every binder arm; the pMHC promotion adds a pmhc_tce arm while the
# folded surface stays neither_viable.
_ARM_ORDER = ("adc", "bite_tce", "antibody")
_VERDICT_ARMS = {
    "both_viable":                   {"adc": "viable",        "bite_tce": "viable",       "antibody": "viable"},
    "adc_preferred":                 {"adc": "preferred",     "bite_tce": "not_preferred","antibody": "viable"},
    "tce_preferred":                 {"adc": "not_preferred", "bite_tce": "preferred",    "antibody": "viable"},
    "neither_viable":                {"adc": "not_viable",    "bite_tce": "not_viable",   "antibody": "not_viable"},
    "adc_preferred_tce_unsafe":      {"adc": "viable",        "bite_tce": "unsafe",       "antibody": "viable"},
    "tce_unsafe_normal_liability":   {"adc": "not_preferred", "bite_tce": "unsafe",       "antibody": "not_preferred"},
    "adc_preferred_tce_escape_risk": {"adc": "viable",        "bite_tce": "escape_risk",  "antibody": "viable"},
    "tce_escape_risk":               {"adc": "not_preferred", "bite_tce": "escape_risk",  "antibody": "not_preferred"},
    "surface_viable_density_caveated": {"adc": "caveated",    "bite_tce": "caveated",     "antibody": "caveated"},
    "shed_dominant_opposed":         {"adc": "opposed",       "bite_tce": "opposed",      "antibody": "opposed"},
    "pmhc_tce_supported":            {"adc": "not_viable",    "bite_tce": "not_viable",   "antibody": "not_viable",
                                      "pmhc_tce": "supported"},
    "modality_ambiguous":            {"adc": "ambiguous",     "bite_tce": "ambiguous",    "antibody": "ambiguous"},
    "isoform_dependent_undefined":   {"adc": "undefined",     "bite_tce": "undefined",    "antibody": "undefined"},
    "insufficient":                  {"adc": "insufficient",  "bite_tce": "insufficient", "antibody": "insufficient"},
    "data_unavailable":              {"adc": "insufficient",  "bite_tce": "insufficient", "antibody": "insufficient"},
}
_ARMS_DEFAULT = {"adc": "insufficient", "bite_tce": "insufficient", "antibody": "insufficient"}


def _surface_verdict_by_modality(verdict_token) -> dict:
    """Project the RESOLVED surface_modality_verdict onto explicit per-modality-arm calls. Every resolver
    token is mapped (pinned by test_verdict_by_modality_covers_all_tokens); an unmapped/None token falls
    back to all-insufficient (honest — never fabricates a viable arm). Returns a fresh dict per call."""
    return dict(_VERDICT_ARMS.get(verdict_token, _ARMS_DEFAULT))


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed surface headline. The canonical `call`
    is the composed fit_class; the resolver's safety/density/shed downgrade rides as the top tension.
    The per-modality-arm decomposition (surface_modality_verdict_by_modality) rides in the hero payload so
    the ADC/TCE/mAb arms are legible without string-parsing the token. Verdict-inert; never moves the spine."""
    fit_class = headline.get("fit_class")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_SURFACE_HEADLINE_SPEC, verdict_token=fit_class,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_fit_class_polarity(fit_class),
                          modality_arms=(headline.get("surface_modality_verdict_by_modality")
                                         or _surface_verdict_by_modality(headline.get("surface_modality_verdict"))))


def _emit_skill_figures(decision, figures_root):
    """--figures emitter: the canonical headline hero (verdict · confidence · top tension). Additive /
    display-only; best-effort (returns [] when the decision predates the headline block)."""
    return emit_headline_hero(decision, figures_root)


SKILL_NAME = "surface-modality-fit"
SKILL_VERSION = "1.6.0"   # 1.6.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.   # 1.5.0 (2026-08-27): tuned signals-first sub-group reader (surface-modality vocab). Verdict-INERT.
                          # 1.4.0 (2026-08-21): emit existing per-question question_table into the headline; 1.3.0 +sc-surface-normal-safety +sc-surface-rna-protein-concordance

# VERDICT-RELEVANT vs ENRICHMENT: the surface_modality resolver (v1.1.0, 2026-08-09) keys on the
# cards reachability.verdict_relevant_cards("surface_modality") derives — adc-tce-modality-fit
# (fit_class) PLUS the safety/density/shed KILLER/downgrade cards (normal-tissue-liability,
# sc-normal-celltype-expression, surface-abundance-density, shed-ectodomain-liability), which MOVE
# the verdict via when_all_fired combination rungs. So the older per-card "no resolver rung → verdict
# byte-stable" notes below are STALE for THOSE FOUR (accurate only for the genuinely inert enrichment
# cards). --verdict-only reads exactly the verdict_relevant set (wired at __main__, derived not
# hand-listed, so it can't drift from the resolver).
CARDS = [
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "structure-features-static",
    "surface-abundance-density",
    "adc-tce-modality-fit",
    "normal-tissue-liability",          # HPA IHC on-target-off-tumor safety (wired 2026-07-20)
    "sc-normal-celltype-expression",    # (2026-08-07): scRNA cell-type-resolved
                                        # normal-tissue safety from Census pseudobulk (sc_rna/normal). Its
                                        # rules fire on sc_normal_expression_class: HIGH_LIABILITY →
                                        # bite_tce killer + adc/antibody opposing; MODERATE → all opposing;
                                        # NOT_EXPRESSED → supportive (dominant). Complements HPA IHC:
                                        # IHC misses low-level inducible targets + can't distinguish cell
                                        # types (e.g. hepatocyte vs Kupffer cell). LIVE for colon+lung;
                                        # other tissues → data_unavailable (honest coverage gap). ADDITIVE
                                        # signal-only (no resolver rung → verdict byte-stable).
    "sc-surface-normal-safety",         # REVIVE (dead-card resolution 2026-08-19): single-cell CITE-seq
                                        # SURFACE-protein footprint on normal immune cell types — the PROTEIN
                                        # single-cell sibling of sc-normal-celltype-expression (RNA) + normal-
                                        # tissue-liability (bulk IHC). Method sc_surface_normal_safety LIVE; card
                                        # was orphaned (wired to no skill). Its rules (sc-surface-high-normal-
                                        # immune-safety-opposing / sc-surface-absent-...-supportive) feed NO
                                        # resolver rung → ADDITIVE signal-only, verdict byte-stable.
    "sc-surface-rna-protein-concordance", # REVIVE (dead-card resolution 2026-08-19): single-cell RNA↔surface-
                                        # protein (CITE-seq ADT) concordance — is scRNA an adequate proxy for the
                                        # surface antigen, or must protein be measured? Method sc_surface_concordance
                                        # LIVE; card was orphaned. Rules (sc-surface-rna-poor-proxy-warning /
                                        # -adequate-proxy-supportive) feed NO resolver rung → ADDITIVE, byte-stable.
                                        # (single-cell twin of rna-protein-concordance-tumor below.)
    "copy-number-distribution",         # (2026-07-23) — genomic AMPLIFICATION → surface antigen-
                                        # density argument. The SAME card is in genomic-alteration-profile
                                        # (SM/degrader read); here it fires cn-amplified-surface-antigen-
                                        # supportive (adc/bite_tce/antibody) — one card, two
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
    "protein-surface-evidence",         # Orphan-fix (biologics-augment, 2026-08-06): CSPA wet-lab
                                        # surface confirmation (cspa-surface-confirmation-per-uniprot-v1), the
                                        # `measured` surface-residency tier. measurement_type surface_confirmation,
                                        # modality_relevance [adc, bite_tce, antibody], tier:target. Its rules
                                        # (protein-surface-confirmed-supportive [important] + protein-not-surface-
                                        # opposing [secondary, NOT killer]) were SILENTLY INERT on live data —
                                        # CSPA went live but no skill composed the card (it was a declared
                                        # measurement_types_pulled intent only). Measured protein-surface residency
                                        # is the strongest presence signal the surface gate can receive. ADDITIVE
                                        # signal-only (no resolver rung) → verdict byte-stable.
    "shed-ectodomain-liability",        # Orphan-fix (biologics-augment, 2026-08-06): clinically-
                                        # established shed-ectodomain antigen-sink liability (curated serum-marker
                                        # crosswalk — CA125=MUC16, CEA=CEACAM5, SMRP=MSLN, shed-HER2-ECD). A
                                        # circulating soluble decoy sequesters antibody/ADC/TCE before tumor
                                        # delivery. measurement_type shed_ectodomain_liability, modality_relevance
                                        # [adc, bite_tce, antibody], tier:target. Its rules (shed-ectodomain-
                                        # clinical-opposing + -secretome-proxy-opposing, both OPPOSING not killer —
                                        # approved biologics exist vs shed antigens) existed + were wired to the
                                        # surface_intrinsic axis but UNREACHABLE — no skill composed the card.
                                        # ADDITIVE signal-only (no resolver rung) → verdict byte-stable.
    "tumor-scrna-celltype-expression",  # biologics-augment (2026-08-06): within-tumor antigen ESCAPE
                                        # risk via single-cell CELLxGENE Census (tce_antigen_escape_class
                                        # facet — coverage x inter-donor consistency over malignant cells).
                                        # For a TCE, antigen heterogeneity is an efficacy program-killer
                                        # (antigen-low cells escape redirected killing — no bystander payload).
                                        # REWIRED + VERDICT-MOVING 2026-08-24: its surface rules
                                        # (sc-antigen-escape-low-tce-supportive [important] + sc-antigen-escape-
                                        # high-tce-opposing [important, ADC neutral — the ADC-vs-TCE
                                        # discriminator]) fire on tce_antigen_escape_class; escape_risk_high now
                                        # moves the verdict (adc_preferred_tce_escape_risk / tce_escape_risk). The
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
                                        # Emits BOTH essential + full-normal ratios. Cohort-
                                        # honest (DLL3/SCLC → not_expressed). ADDITIVE signal-only (no resolver
                                        # rung) → verdict byte-stable.
    "pmhc-presentation",                 # biologics enrichment (2026-08-07): peptide-centric HLA
                                         # presentation (benign immunopeptidome). The peptide-centric TCE
                                         # axis — reaches INTRACELLULAR targets via the peptide-MHC complex
                                         # (KRAS/WT1/PRAME/MAGE-A4), invisible to surface presence. Its rules
                                         # (pmhc-restricted-presentation-tce-supportive / -broadly-presented-
                                         # normal-tce-opposing) fire on pmhc_presentation_class; bite_tce-only.
                                         # Benign-atlas = normal-presentation SAFETY denominator (broad=liability;
                                         # restricted=clean, MAGE-A4). ADDITIVE (no resolver rung) → byte-stable.
    "modality-exon-window",              # biologics enrichment (2026-08-07): EXON-resolution companion of
                                         # modality-therapeutic-window. Reads tcga-gtex-exon-tpm-quantiles-v1 —
                                         # tumor-dominant exon's tumor-vs-normal window + within-gene exon
                                         # heterogeneity. HONEST SCOPE (live-smoke-calibrated): a HYPOTHESIS flag,
                                         # NOT an isoform-ID call (per-exon coverage can't resolve CLDN18.2 from
                                         # CLDN18.1). Its rules (exon-window-heterogeneity-flag-supportive [SECONDARY
                                         # — gentle, a follow-up candidate] / exon-window-essential-liability-tce-
                                         # opposing [ADC-vs-TCE discriminator]) fire on exon_window_class. ADDITIVE
                                         # (no resolver rung) → verdict byte-stable.
    "mutation-stratified-surface",       # (2026-08-07): patient-selection-aware surface presence — is the
                                         # antigen ELEVATED in a driver's MUTANT tumor subset (a biologics handle on
                                         # the mutant patient population the gene-level window dilutes away)? Reads
                                         # mutation-stratified-surface-window-v1 (v1 = KRAS×NSCLC archetype). Its rule
                                         # (mutant-up-surface-antigen-supportive) fires adc/bite_tce/antibody supportive
                                         # ONLY on mutant_up_surface. ADDITIVE (no resolver rung) → verdict byte-stable.
    "pathway-stratified-surface",        # (2026-08-07): tumor-STATE-conditioned surface presence — is the antigen
                                         # ELEVATED in a pathway/stress-HIGH subset (e.g. hypoxia-HIGH tertile; a biologics
                                         # handle on that compartment)? Reads pathway-stratified-surface-window-v1 (v1 =
                                         # HALLMARK_HYPOXIA×NSCLC). Rule pathway-high-up-surface-antigen-supportive fires
                                         # adc/bite_tce/antibody supportive on pathway_high_up_surface. ADDITIVE → byte-stable.
    "cd-antigen-backbone",               # enrichment (2026-08-07): CD/immuno-oncology antigen-BACKBONE clinical-
                                         # PRECEDENT prior (hgnc-gene-group-471). Orthogonal to the PREDICTED-biology axes
                                         # — is the target a canonical CD/IO antigen whose class delivered approved
                                         # biologics (CD19/CD20/BCMA-class)? Its rules (cd-established-io-backbone-supportive
                                         # [important] / cd-antigen-backbone-supportive [secondary]) fire on cd_antigen_
                                         # backbone_class. SUPPORTIVE-ONLY: not_cd_antigen fires nothing (not a negative —
                                         # solid-tumor ADC/TCE antigens aren't CD molecules). ADDITIVE (no rung) → byte-stable.
    "surface-colocalization-avidity",    # wired 2026-08-20: same-cell avidity + tumor-vs-NORMAL selectivity WINDOW for
                                         # AND-gate bispecifics (TCE/dual-ADC). Un-retired from a partially-true 2026-08-19
                                         # supersession — bispecific-pair-scan covers tumor per-pair avidity ONLY; this card
                                         # uniquely adds the normal selectivity window (sc-samecell-coexpr-normal-v1 via
                                         # pair_selectivity_gate.window) + target-centric best-partner rollup. Its 5 rules
                                         # (samecell-*/selectivity-window-*) are in NO resolver → ADDITIVE, verdict
                                         # byte-stable. Indication-scoped (per-indication cube); data_unavailable elsewhere.
    "surfaceome-cohort-ranking",         # REVIVE (2026-08-20): per-target COHORT-PERCENTILE context — where
                                         # does this antigen rank among ALL surface proteins in the indication by
                                         # tumor-vs-normal effect size (cohort_rank_class top_1/5/25%)? The only cross-
                                         # target ranking context in the fan-out; product landed 2026-08-18. ADDITIVE
                                         # verdict-INERT facet (no resolver rung → fit_class byte-stable).
    "surface-bulk-pair-selectivity",     # 2026-08-20: BULK tumor-vs-normal PAIR-selectivity (AND/OR/NOT logic gate)
                                         # best-partner-per-gate over the 52 clinical-seed antigens. The NECESSITY
                                         # companion to surface-colocalization-avidity's same-cell AVIDITY (sufficiency).
                                         # ADDITIVE verdict-INERT bispecific facet (no resolver rung → byte-stable).
    "pmhc-epitope-evidence-iedb",        # 2026-08-25: EXPERIMENTALLY-VALIDATED pMHC epitope / MHC ground truth
                                         # from IEDB (iedb-epitope-mhc-per-protein-v1) — has the target's peptides
                                         # been observed presented on human HLA and/or T-cell-RECOGNIZED, on which
                                         # class / how many alleles, in a cancer context. The experimental COMPLEMENT
                                         # to pmhc-presentation (HLA-Ligand-Atlas benign-breadth). VERDICT-BEARING:
                                         # its rules (pmhc-iedb-tcell-validated / -presented-tce-supportive,
                                         # bite_tce-only) feed the surface_modality resolver's pmhc_tce_supported
                                         # rung (3b / 3b') when the folded surface is neither_viable — the pMHC-TCE
                                         # route for an intracellular oncoprotein (see the get_card_field lift below).
]

QUESTION = ("For {target} in {indication}, does the surface biology (topology, "
            "surfaceome family, structure pockets, abundance) support a biologics "
            "modality — is it ADC-favorable, TCE-favorable, both, or neither?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (2026-07-20).
    The former if-chain now lives in resolvers/surface_modality.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "surface_modality")

# ── (strength, certainty) SIDECAR — 4th certainty axis (CERTAINTY_MODEL.md). ADDITIVE + verdict-INERT.
#    corroboration = the VERDICT-DISJOINT CSPA wet-lab surfaceome MS (protein-surface-evidence) — an
#    INDEPENDENT surface-residency line orthogonal to the topology+family fit_class. Reviewed (4-agent panel).
_SM_ORD = {"low": 0, "medium": 1, "high": 2}
_CERTAINTY_CORROBORATION_CARDS = frozenset({"protein-surface-evidence"})
_SM_STRONG_POS = {"both_viable"}
# pmhc_tce_supported (2026-08-25): the pMHC-TCE route when the folded surface is neither_viable —
# a moderate bite_tce-scoped positive (experimentally-validated IEDB epitope ground truth, single-axis /
# necessary-not-sufficient), grouped with the other modality-preferring positives.
_SM_MOD_POS = {"adc_preferred", "tce_preferred", "surface_viable_density_caveated",
               "adc_preferred_tce_unsafe", "adc_preferred_tce_escape_risk", "pmhc_tce_supported"}
_SM_WEAK_POS = {"shed_dominant_opposed"}
_SM_NEG = {"neither_viable", "tce_unsafe_normal_liability", "tce_escape_risk"}
_SM_NONE = {"modality_ambiguous", "isoform_dependent_undefined", "insufficient", "data_unavailable", None}
_SM_DECISION_CARDS = ("adc-tce-modality-fit", "surface-abundance-density", "normal-tissue-liability",
                      "sc-normal-celltype-expression", "modality-therapeutic-window",
                      "tumor-scrna-celltype-expression", "shed-ectodomain-liability", "protein-surface-evidence")


def _surface_strength(v) -> str:
    if v in _SM_STRONG_POS:
        return "strong_positive"
    if v in _SM_MOD_POS:
        return "moderate_positive"
    if v in _SM_WEAK_POS:
        return "weak_positive"
    if v in _SM_NEG:
        return "negative"
    return "none"


def _sm_coverage(density_class) -> str:
    """Surface-antigen density power (surface-abundance-density.surface_density_class). high -> high;
    moderate -> medium; low/very_low -> low; absent -> low (feeds unknown_mass)."""
    c = str(density_class or "")
    if c == "high":
        return "high"
    if c == "moderate":
        return "medium"
    return "low"


def _sm_corroboration(confirmation_class, n_celllines) -> str:
    """VERDICT-DISJOINT CSPA surfaceome confirmation. confirmed_high or confirmed w/ >=3 lines -> high;
    confirmed 1-2 -> medium; not_surface (measured-negative, disagrees w/ a surface-favorable fit) -> low;
    data_unavailable -> unmeasured (ignorance, carried in unknown_mass, not disagreement)."""
    c = str(confirmation_class or "")
    if c == "confirmed_high" or (c == "confirmed" and isinstance(n_celllines, (int, float)) and n_celllines >= 3):
        return "high"
    if c == "confirmed":
        return "medium"
    if c == "not_surface":
        return "low"
    return "unmeasured"


def _sm_unknown_mass(cards) -> float:
    blind = sum(1 for cid in _SM_DECISION_CARDS
                if not card_summary(cards, cid) or (card_summary(cards, cid) or {}).get("_missing"))
    return round(blind / len(_SM_DECISION_CARDS), 4)


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — mirrors functional-requirement/selectivity/genomic."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    density = (card_summary(cards, "surface-abundance-density") or {}).get("surface_density_class")
    pse = card_summary(cards, "protein-surface-evidence") or {}
    coverage = _sm_coverage(density)
    corroboration = _sm_corroboration(pse.get("surface_confirmation_class"), pse.get("n_celllines_detected"))
    components = [coverage] + ([corroboration] if corroboration != "unmeasured" else [])
    level = min(components, key=lambda c: _SM_ORD[c]) if components else "low"
    if v in _SM_NONE:
        level = "low"
    from _skills_common.signals_first import certainty_composite
    strength = _surface_strength(v)
    return {
        "strength": strength,
        "certainty": {"level": level, "coverage": coverage, "corroboration": corroboration,
                      "unknown_mass": _sm_unknown_mass(cards)},
        # continuous portfolio-ranking primitive (verdict-inert; a NAMED projection, not canonical)
        "composite": certainty_composite(strength, level),
        "composite_basis": ("certainty-discounted surface-modality strength = peak signal tier × "
                            "weakest-link certainty; a NAMED [0,1] portfolio-ranking projection, not a verdict"),
        "provenance": {"surface_density_class": density,
                       "surface_confirmation_class": pse.get("surface_confirmation_class")},
        "_model_ref": "CERTAINTY_MODEL.md#surface_modality",
    }


# ── FACTORED-RECORD SHADOW (M1) — the SURFACE per-axis builder. Here modality_scope is NATIVE: the
#    surface verdict directly encodes which BIOLOGIC modality fits (adc_preferred / tce_preferred /
#    both_viable / neither). small_molecule is `na` (surface fit does not speak to SM); the per-verdict
#    ADC / TCE preference rides in _refinements. VERDICT-INERT: surfaced by the fan-out into
#    decision.claim_record_shadow.surface_modality, consumed by NOTHING. Mirrors the other axes' hook.
_SM_OPEN_WORLD = {"data_unavailable", None}
_SM_INCONCLUSIVE = {"modality_ambiguous", "isoform_dependent_undefined", "insufficient"}
_SM_STRENGTH_TO_LEVEL = {"strong_positive": "strong", "moderate_positive": "moderate",
                         "weak_positive": "weak", "negative": "moderate", "none": "none"}


def _sm_availability(v) -> str:
    if v in _SM_OPEN_WORLD:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v in _SM_INCONCLUSIVE:
        return "insufficient"
    if v in _SM_NEG:
        return "measured_negative"
    return "measured_positive"


def _sm_direction(v) -> str:
    if v in _SM_STRONG_POS or v in _SM_MOD_POS or v in _SM_WEAK_POS:
        return "supports"
    if v in _SM_NEG:
        return "opposes"
    return "neutral"


def _sm_modality_scope(v) -> dict | None:
    """The verdict's native per-biologic-modality preference. small_molecule = na (out of scope for
    surface fit); adc/bite_tce carried as _refinements; biologics base = best of the two."""
    adc = bite = None
    if v in ("adc_preferred", "adc_preferred_tce_unsafe", "adc_preferred_tce_escape_risk"):
        adc = "favorable"
        bite = {"adc_preferred_tce_unsafe": "unfavorable",
                "adc_preferred_tce_escape_risk": "conditional"}.get(v, "unfavorable")
    elif v == "tce_preferred":
        adc, bite = "favorable", "favorable"     # TCE preferred; ADC not excluded
    elif v == "both_viable":
        adc = bite = "favorable"
    elif v == "surface_viable_density_caveated":
        adc = bite = "conditional"
    elif v == "tce_unsafe_normal_liability":
        bite = "unfavorable"
    elif v == "tce_escape_risk":
        bite = "conditional"
    elif v == "pmhc_tce_supported":
        # The folded surface is neither_viable (adc/naked-antibody bind the folded protein → unfavorable),
        # but the peptide-MHC (pMHC-TCE) route is favorable via a TCR-mimetic T-cell engager (bite_tce).
        adc, bite = "unfavorable", "favorable"
    elif v in ("neither_viable", "shed_dominant_opposed"):
        adc = bite = "unfavorable"
    else:
        return None                              # ambiguous / insufficient / open-world → no call
    vals = [x for x in (adc, bite) if x]
    biologics = ("favorable" if "favorable" in vals
                 else "conditional" if "conditional" in vals else "unfavorable")
    scope: dict = {"small_molecule": "na", "biologics": biologics}
    ref = {}
    if adc:
        ref["adc"] = adc
    if bite:
        ref["bite_tce"] = bite
    if ref:
        scope["_refinements"] = ref
    return scope


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=verdict_pair)
    return assemble_claim_record(
        axis="surface_modality",
        state=(v or "insufficient"),
        direction=_sm_direction(v),
        availability=_sm_availability(v),
        magnitude={"level": _SM_STRENGTH_TO_LEVEL.get(_surface_strength(v), "none")},
        modality_scope=_sm_modality_scope(v),
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "surface_modality_verdict":       v,
        # PER-MODALITY-ARM decomposition of the one-word verdict — {adc, bite_tce, antibody[, pmhc_tce]}.
        # A pure projection OF surface_modality_verdict (cannot disagree with it); verdict-inert. Mirrors
        # safety_verdict_by_modality / presence_verdict_by_modality; surfaces the ADC-vs-TCE split the
        # compound token packs (e.g. adc_preferred_tce_unsafe → {adc: viable, bite_tce: unsafe}).
        "surface_modality_verdict_by_modality": _surface_verdict_by_modality(v),
        "driving_rule_id":                drv,
        "fit_class":                      get_card_field(cards, "adc-tce-modality-fit", "fit_class"),
        # Isoform-selective indication-scope (2026-08-14): TRUE when the target has a curated dominant
        # alt isoform but NOT in THIS indication — the fit_class is NOT suppressed (stands on merit), and
        # this flag surfaces the caveat so a reader knows an isoform consideration exists off-context
        # (e.g. EGFRvIII when querying LUAD). In-context, the verdict is isoform_dependent_undefined and
        # this is False. Verdict-inert (annotation only).
        "isoform_selective_offcontext":   get_card_field(cards, "adc-tce-modality-fit", "isoform_selective_offcontext"),
        # Mechanism-aware caveat (2026-08-14): in-context isoform whose mechanism does NOT ablate the
        # ectodomain epitope (METex14 intracellular / EGFRvIII neoepitope / CD19 acquired-resistance /
        # FGFR2 isoform-specific) — fit_class stands, mechanism surfaced. None when not applicable.
        "isoform_mechanism_caveat":       get_card_field(cards, "adc-tce-modality-fit", "isoform_mechanism_caveat"),
        # Dominance caveat (v1.3.0, 2026-08-24): in-context, ectodomain-ABLATING, but the alt isoform is a
        # MINORITY species (p95HER2) — fit_class STANDS favorable + this high-severity caveat surfaces the
        # subpopulation epitope loss (confirm isoform-resolved expression before ADC nomination). None otherwise.
        "isoform_epitope_caveat":         get_card_field(cards, "adc-tce-modality-fit", "isoform_epitope_caveat"),
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
        # HPA-IF SECOND measured surface provider (2026-08-07) — orthogonal (immunofluorescence
        # microscopy) corroboration of CSPA mass-spec, composed in the cspa_surface_confirmation
        # method. VERDICT-INERT (rules fire on surface_confirmation_class, CSPA-driven). Surfaced so the
        # biologics-fit call shows multi-modal agreement: corroborated_surface (both) is the strongest
        # antigen-reality signal; discordant flags a CSPA false-negative/coverage gap (e.g. CEACAM5).
        "surface_multimodal_support":     get_card_field(cards, "protein-surface-evidence", "surface_multimodal_support"),
        "hpa_if_surface_class":           get_card_field(cards, "protein-surface-evidence", "hpa_if_surface_class"),
        # Shed-ectodomain antigen-sink liability (shed-ectodomain-liability). Its rules fire on
        # the surface_intrinsic axis (adc/bite_tce/antibody): clinically_shed / secretome_proxy_shed
        # → opposing (NOT killer — approved biologics exist against shed antigens; a shed ectodomain
        # demands a shed-resistant epitope + antigen-sink dose modeling). Additive; verdict byte-stable.
        "shed_liability_class":           get_card_field(cards, "shed-ectodomain-liability", "shed_liability_class"),
        "shed_serum_marker":              get_card_field(cards, "shed-ectodomain-liability", "serum_marker"),
        # MEASURED Olink conditioned-media shed facet (card v1.1.0) — PARALLEL to the
        # annotation-based shed_liability_class (unchanged). media_shed_high fires shed-ectodomain-
        # measured-media-opposing (adc/bite_tce/antibody opposing — measurement-corroborated antigen
        # sink). Panel bounded + secretome-preselected → not_on_secreted_panel is NON-informative
        # (never a measured negative). Additive; verdict byte-stable (no resolver rung).
        "measured_shed_class":            get_card_field(cards, "shed-ectodomain-liability", "measured_shed_class"),
        "shed_media_mean_npx":            get_card_field(cards, "shed-ectodomain-liability", "media_mean_npx"),
        "shed_media_n_lines_detected":    get_card_field(cards, "shed-ectodomain-liability", "media_n_lines_detected"),
        # Within-tumor antigen ESCAPE risk (tumor-scrna-celltype-expression, single-cell Census).
        # REWIRED + VERDICT-MOVING 2026-08-24 (druggability audit): the surface rules now fire on the
        # superior tce_antigen_escape_class (2-axis coverage x inter-donor consistency, supersedes the
        # lenient detection-fraction-only tce_homogeneity_class). escape_risk_high fires
        # sc-antigen-escape-high-tce-opposing which the surface_modality resolver now consumes as an
        # EFFICACY foreclosure of the TCE arm (adc_preferred_tce_escape_risk / tce_escape_risk); ADC is
        # preserved (bystander-tolerant). escape_risk_low fires the supportive rung. tce_homogeneity_class
        # is still emitted (below) for back-compat + the orthogonality D4 facet. LIVE for COADREAD +
        # NSCLC only; else data_unavailable (abstain).
        "tce_antigen_escape_class":       get_card_field(cards, "tumor-scrna-celltype-expression", "tce_antigen_escape_class"),
        "tce_homogeneity_class":          get_card_field(cards, "tumor-scrna-celltype-expression", "tce_homogeneity_class"),
        "malignant_detection_fraction":   get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_detection_fraction"),
        # Modality therapeutic window (tumor / max-essential-normal TPM, strict/TCE tier). Its rules
        # fire on window_class: clean_window → supportive; essential_tissue_liability → bite_tce opposing
        # + adc/antibody NEUTRAL (the ADC-vs-TCE discriminator, CEACAM5 pattern); narrow_window →
        # opposing. Both denominators surfaced. Additive; verdict byte-stable.
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
        # EXPERIMENTALLY-VALIDATED pMHC epitope evidence (pmhc-epitope-evidence-iedb) — the IEDB positive-assay
        # ground-truth companion to pmhc-presentation. VERDICT-BEARING 2026-08-25: its rules (pmhc-iedb-tcell-
        # validated / -presented-tce-supportive, bite_tce-only) feed the surface_modality pmhc_tce_supported
        # rung when the folded surface is neither_viable (the pMHC-TCE route for an intracellular oncoprotein).
        "pmhc_epitope_evidence_class":    get_card_field(cards, "pmhc-epitope-evidence-iedb", "epitope_evidence_class"),
        "pmhc_epitope_n_epitopes":        get_card_field(cards, "pmhc-epitope-evidence-iedb", "n_epitopes"),
        "pmhc_epitope_has_tcell_positive": get_card_field(cards, "pmhc-epitope-evidence-iedb", "has_tcell_positive"),
        "pmhc_epitope_n_hla_alleles":     get_card_field(cards, "pmhc-epitope-evidence-iedb", "n_hla_alleles"),
        # Modality exon-window (modality-exon-window) — EXON-resolution companion of the gene window.
        # Its rules fire on exon_window_class: exon_heterogeneity_flag → supportive (SECONDARY, a hypothesis
        # worth junction-level follow-up — per-exon coverage can't confirm isoform identity); essential_exon_
        # liability → bite_tce opposing / adc neutral (ADC-vs-TCE discriminator). Additive; verdict byte-stable.
        "exon_window_class":              get_card_field(cards, "modality-exon-window", "exon_window_class"),
        "exon_best_exon_id":              get_card_field(cards, "modality-exon-window", "best_exon_id"),
        "exon_best_exon_window_ratio":    get_card_field(cards, "modality-exon-window", "best_exon_window_ratio"),
        "exon_heterogeneity_log2":        get_card_field(cards, "modality-exon-window", "exon_heterogeneity_log2"),
        # Mutation-stratified surface window (mutation-stratified-surface) — patient-selection-aware
        # presence: is the antigen elevated in a driver's MUTANT subset (biologics handle on mutant patients)?
        # Its rule (mutant-up-surface-antigen-supportive) fires adc/bite_tce/antibody supportive on
        # mutant_up_surface. Additive; verdict byte-stable. v1 = KRAS×NSCLC (else not_in_product, a gap).
        "mutant_stratified_surface_class": get_card_field(cards, "mutation-stratified-surface", "mutant_stratified_surface_class"),
        "mutant_surface_driver":          get_card_field(cards, "mutation-stratified-surface", "driver_gene"),
        "mutant_surface_delta_log2":      get_card_field(cards, "mutation-stratified-surface", "delta_log2"),
        # Pathway-stratified surface window (pathway-stratified-surface) — tumor-STATE-conditioned
        # presence: is the antigen elevated in a pathway/stress-HIGH subset (hypoxia-HIGH; biologics handle
        # on that compartment)? Rule fires adc/bite_tce/antibody supportive on pathway_high_up_surface.
        # Additive; verdict byte-stable. v1 = HYPOXIA×NSCLC (else not_in_product, a gap).
        "pathway_stratified_surface_class": get_card_field(cards, "pathway-stratified-surface", "pathway_stratified_surface_class"),
        "pathway_surface_signature":      get_card_field(cards, "pathway-stratified-surface", "signature"),
        "pathway_surface_delta_log2":     get_card_field(cards, "pathway-stratified-surface", "delta_log2"),
        # CD/IO-antigen backbone (cd-antigen-backbone) — class-level clinical-PRECEDENT prior.
        # Its rules fire on cd_antigen_backbone_class: established_io_backbone → supportive (important,
        # the class delivered approved biologics); cd_antigen → supportive (secondary). SUPPORTIVE-ONLY —
        # not_cd_antigen fires nothing (not a negative). Additive; verdict byte-stable.
        "cd_antigen_backbone_class":      get_card_field(cards, "cd-antigen-backbone", "cd_antigen_backbone_class"),
        "cd_number":                      get_card_field(cards, "cd-antigen-backbone", "cd_number"),
        "cd_established_io_precedent":    get_card_field(cards, "cd-antigen-backbone", "established_io_precedent"),
        # scRNA cell-type-resolved normal-tissue safety (sc-normal-celltype-expression).
        # Its rules fire on sc_normal_expression_class on the surface_intrinsic axis: HIGH_LIABILITY →
        # bite_tce killer + adc/antibody opposing; NOT_EXPRESSED → supportive (dominant). Provides
        # cell-type-level resolution HPA IHC can't deliver (e.g. hepatocyte vs Kupffer cell, AT2 vs
        # alveolar macrophage). LIVE for colon+lung; other tissues → data_unavailable (named gap).
        # Additive; verdict byte-stable (no resolver rung — safety_essential_flags surfaced for LLM).
        "sc_normal_expression_class":     get_card_field(cards, "sc-normal-celltype-expression", "sc_normal_expression_class"),
        "sc_normal_max_det_cell_type":    get_card_field(cards, "sc-normal-celltype-expression", "max_detection_cell_type"),
        "sc_normal_max_det_fraction":     get_card_field(cards, "sc-normal-celltype-expression", "max_detection_fraction"),
        "sc_normal_n_cell_types_above_20pct": get_card_field(cards, "sc-normal-celltype-expression", "n_cell_types_above_20pct"),
        "sc_normal_safety_essential_flags": get_card_field(cards, "sc-normal-celltype-expression", "safety_essential_flags"),
        # Same-cell avidity + tumor-vs-NORMAL selectivity window (surface-colocalization-avidity, wired
        # 2026-08-20). Bispecific AND-gate lens: does a candidate partner antigen co-express on the SAME
        # malignant cells (tumor avidity), AND is that co-positivity ABSENT from normal tissue (the
        # selectivity window / safety half)? samecell_avidity_class = tumor best-partner call;
        # samecell_window_verdict combines tumor engagement + normal selectivity (window_open / no_window /
        # selectivity_unproven / ...). Its 5 rules are in NO resolver → ADDITIVE, verdict byte-stable
        # (fit_class resolves off adc-tce-modality-fit). Indication-scoped; data_unavailable elsewhere.
        "samecell_avidity_class":         get_card_field(cards, "surface-colocalization-avidity", "samecell_avidity_class"),
        "samecell_best_partner":          get_card_field(cards, "surface-colocalization-avidity", "best_partner"),
        "samecell_best_enrichment_median": get_card_field(cards, "surface-colocalization-avidity", "best_enrichment_median"),
        "samecell_best_both_fraction_median": get_card_field(cards, "surface-colocalization-avidity", "best_both_fraction_median"),
        "samecell_n_partners_tested":     get_card_field(cards, "surface-colocalization-avidity", "n_partners_tested"),
        "samecell_n_coordinated_partners": get_card_field(cards, "surface-colocalization-avidity", "n_coordinated_partners"),
        "samecell_window_verdict":        get_card_field(cards, "surface-colocalization-avidity", "window_verdict"),
        "samecell_window_best_partner":   get_card_field(cards, "surface-colocalization-avidity", "window_best_partner"),
        "samecell_selectivity_margin":    get_card_field(cards, "surface-colocalization-avidity", "selectivity_margin"),
        "samecell_n_window_open":         get_card_field(cards, "surface-colocalization-avidity", "n_window_open"),
        "samecell_normal_liability_locus": get_card_field(cards, "surface-colocalization-avidity", "normal_liability_locus"),
        # Per-target surfaceome COHORT-PERCENTILE context (surfaceome-cohort-ranking, revived 2026-08-20).
        # Where the antigen ranks among ALL surface proteins in the indication by tumor-vs-normal effect
        # size. VERDICT-INERT display facet (no resolver rung — fit_class byte-stable); the only cross-target
        # ranking context the per-target profile has.
        "surfaceome_cohort_rank_class":   get_card_field(cards, "surfaceome-cohort-ranking", "cohort_rank_class"),
        "surfaceome_tissue_rank":         get_card_field(cards, "surfaceome-cohort-ranking", "tissue_rank"),
        "surfaceome_tissue_percentile_rna": get_card_field(cards, "surfaceome-cohort-ranking", "tissue_percentile_rna"),
        "surfaceome_rna_protein_concordance": get_card_field(cards, "surfaceome-cohort-ranking", "rna_protein_concordance"),
        # BULK tumor-vs-normal PAIR-selectivity best-partner (surface-bulk-pair-selectivity, 2026-08-20).
        # Bispecific AND/OR/NOT logic-gate necessity screen; verdict-inert facet.
        "bulk_pair_best_and_partner":     get_card_field(cards, "surface-bulk-pair-selectivity", "best_and_partner"),
        "bulk_pair_best_and_selectivity": get_card_field(cards, "surface-bulk-pair-selectivity", "best_and_selectivity"),
        "bulk_pair_best_and_call":        get_card_field(cards, "surface-bulk-pair-selectivity", "best_and_call"),
        "bulk_pair_best_not_partner":     get_card_field(cards, "surface-bulk-pair-selectivity", "best_not_partner"),
        "bulk_pair_n_partners_scanned":   get_card_field(cards, "surface-bulk-pair-selectivity", "n_partners_scanned"),
    }
    # Orthogonality facet (2026-08-07) — VERDICT-INERT display meta-facet. Counts the
    # INDEPENDENT surface-biology dimensions with supporting evidence (the 6-card presence
    # cluster collapsed to ONE line, not counted 6x). A target corroborated across 4-5
    # orthogonal axes is a stronger biologics call than one resting on a single axis at the
    # same fit_class. Emitted as a headline sub-key; the surface_modality resolver keys ONLY
    # on adc-tce-modality-fit.fit_class rungs, so a headline key CANNOT move the verdict
    # (pinned by test_orthogonality_is_verdict_inert). Coverage vs support kept separate:
    # an abstaining dimension (data_unavailable) is a coverage gap, never an opposing vote.
    hl["orthogonality"] = score_orthogonality(cards)
    # verdict-INERT claim-vector projection (8th concrete) — FIT/TOPOLOGY/DENSITY/SAFETY/SHED
    # decomposition + citable atoms the composed fan-out lifts to the cross-evidence agent. UNIFORM
    # valence (strong = better surface substrate); SAFETY/SHED liabilities surface as `negative`. The
    # surface_modality resolver keys only on fit_class + the safety/density/shed verdict-movers, so
    # this projection cannot move the verdict (pinned by the replay/golden guards).
    hl["claim_vector"] = surface_claim_vector(hl, cards)
    hl["key_signals"] = surface_key_signals(hl, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing
    # headline message, as deterministic text + a renderer-agnostic hero payload. A verdict-INERT
    # projection over the claim_vector / key_signals just built; best-effort (a build fault degrades to
    # None, never aborts the surface spine — same discipline the dispatcher applies to synthesis/figures).
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort.
    try:
        hl["question_table"] = surface_modality_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, from the
    # fit_class verdict + claim_vector + headline_block + question_table just built. surface-modality-fit
    # is a GATING skill (∈ target-profile _SHORT_TO_GATE); like tumor-selectivity it carries a VETO
    # verdict — `neither_viable` (neither ADC nor TCE viable = the surface-axis KILL) — so it passes
    # canonical_polarity_override="killer" for that (via _FIT_CLASS_NEGATIVE) so the veto survives the
    # helper's 3-band→canonical negative→opposing floor. Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        _v = hl.get("fit_class")
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=_v,
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
            canonical_polarity_override=("killer" if _v in _FIT_CLASS_NEGATIVE else None),
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


_SYNTHESIS_FACET_KEYS = (
    "surface_modality_verdict", "surface_modality_verdict_by_modality",
    "driving_rule_id", "fit_class", "topology_class",
    "surface_density_class", "normal_tissue_breadth_class", "shed_liability_class",
    "window_class", "tce_antigen_escape_class",   # verdict-moving TCE safety + efficacy facets (2026-08-24)
    "pmhc_epitope_evidence_class",                 # verdict-moving pMHC-TCE facet (IEDB, 2026-08-25)
    "surfaceome_cohort_rank_class",
    "bulk_pair_best_and_partner", "bulk_pair_best_and_selectivity",
    "claim_vector", "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 skill_report
    # adoption (8th/last gating adopter; killer override on neither_viable)
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT surface facet for the composed target-profile synthesis. Reuses _headline
    (single source) + returns the surface claim_vector (FIT/TOPOLOGY/DENSITY/SAFETY/SHED) + its citable
    atoms. Never moves the verdict (owned by the surface_modality resolver); safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic surface-modality-fit facet; claim_vector is UNIFORM-valence "
                            "(strong = better surface substrate; SAFETY/SHED liabilities are `negative`). "
                            "Verdict owned by the resolver.")
    return facet


def _llm_synthesis(cards, fired, verdict_pair, target, indication,
                   model_id=None, subtype=None):
    """Fan-out opt-in (mirrors _synthesis_facet): return this lens's provenance-tagged
    llm_synthesis block for the COMPOSED target-profile run. Builds the SAME minimal decision the
    narrator consumes standalone ({target, indication, headline, cards}) from the fan-out's already-
    resolved cards + this skill's _headline, then narrates through its OWN lens synthesizer. Best-
    effort + VERDICT-INERT: never enters fired/verdict/cards — a failure is the caller's to swallow."""
    headline = _headline(cards, fired, verdict_pair)
    decision = {
        "target": target, "indication": indication, "headline": headline,
        "cards": [{"card_id": c.get("card_id"), "summary": c.get("summary") or {}}
                  for c in cards],
    }
    return make_synthesize_fn(_LENS)(decision, model_id, subtype)  # migrated to generic capsule-driven engine


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        # --verdict-only lean set: the resolver-referenced cards (adc-tce-modality-fit + the
        # safety/density/shed verdict-movers). DERIVED, not hand-listed — auto-tracks the resolver
        # (a new verdict rung expands this set; the guard test pins verdict_relevant ⊆ CARDS).
        verdict_cards=sorted(verdict_relevant_cards("surface_modality")),
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
        # to the PRESENCE narrator (wrong lens, 2026-08-06).
        synthesize_fn=make_synthesize_fn(_LENS),
        # Skill-level graphics (opt-in --figures): the canonical headline hero (verdict · confidence ·
        # top tension). Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
        # Signals-first: tuned sub-group reader for the surface-modality vocabulary. Verdict-INERT.
        subgroup_classify=make_value_classifier(_SURFACE_VALUE_TIERS),
        partial_status_note=("Most surface derived products (structure-features, "
                             "surfaceome-family, cohort-ranking) are not yet on S3; "
                             "verdict is honest-insufficient until they land."),
        isoform_check_target=True,   # surface-modality claims need isoform caveats
    ))
