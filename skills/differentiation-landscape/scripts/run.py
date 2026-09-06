#!/usr/bin/env python3
"""differentiation-landscape — Phase-E partial skill (graduated 2026-07-08).

Co-mutation + mutual-exclusivity landscape from panel-intersect-aware Fisher
scan across TCGA MC3 + GENIE 19.0-public.

Calls the shared run_wired_skill dispatcher (2026-07-09).
Skill-specific logic reduces to CARDS + verdict + headline callbacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import DIFFERENTIATION_LANDSCAPE as _LENS
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common import get_card_field
from _skills_common.differentiation_claims import differentiation_claim_vector, differentiation_key_signals
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_GATING
from _skills_common.differentiation_question_table import differentiation_question_table
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: a differentiation signal exists (co-mutation
# pattern / stemness node / prognostic association). default_classify is the fallback for unmapped values.
_DIFFERENTIATION_VALUE_TIERS = {
    "both_patterns_present": "moderate", "co_occurrence": "moderate", "mutual_exclusivity": "moderate",
    "no_significant_pattern": "absent",
    "stem_high": "strong", "stem_intermediate": "moderate", "stem_low": "weak",
    "dominant_node": "strong", "intermediate_node": "moderate", "peripheral_node": "weak",
    "expression_high_better_survival": "moderate", "expression_high_worse_survival": "moderate",
    "no_prognostic_association": "absent", "no_survival_association": "absent",
    "subtype_stratifies_survival": "strong",
}
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record


SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.10.0"  # 1.10.0 (2026-09-04, cross-indication generalization follow-up): the v1.9.0 cooccurrence
                          #        confidence crosswalks were COADREAD-only, so BRAF/SKCM, KRAS/LUAD, KRAS/PAAD, NRAS/SKCM,
                          #        TP53/BRCA, TP53/LUAD, EGFR/LUAD all read caveat=None (the canonical MAPK/RTK exclusivity +
                          #        TP53 near-universality signals silently vanished outside CRC). Generalized: the RAS/RAF MAPK-
                          #        exclusivity guard (_ESTABLISHED_MAPK_EXCLUSIVITY_GENES = KRAS/NRAS/HRAS/BRAF) + TP53
                          #        near-universal (_NEAR_UNIVERSAL_GENES) are now PAN-CANCER gene-level; +NSCLC RTK-driver
                          #        exclusivity (EGFR/LUAD/LUSC/NSCLC explicit); +IDH1/GBM as the LINEAGE arm of the confound tier
                          #        (WHO-2021 IDH-mutant glioma is a distinct lineage). The TMB/lineage confound stays
                          #        (target,indication)-specific (BRAF/COADREAD TMB arm) and OUTRANKS the pan-cancer guard.
                          #        VERDICT-INERT (crosswalks feed only the caveat/provenance; resolver + replay + golden byte-stable).
                          # 1.9.1 (2026-09-04, #1037): + clonality_caveat headline field — COHORT-level (same-SAMPLE)
                          #        co-occurrence != same-CELL/clonal (the (c) sub-inflation): a pooled bulk TCGA-MC3+GENIE Fisher
                          #        pair cannot resolve clonal vs subclonal/parallel evolution (Gerlinger 2012 PMID 22397650;
                          #        McGranahan-Swanton 2017 PMID 28187284). Fires on the co-occurring path only; + a clonality clause
                          #        in the DIFFERENTIATION polarity_note. VERDICT-INERT.
                          # 1.9.0 (2026-09-04, literature-and-claims arc): (1) BAKE the OPTIONAL --literature lane
                          #        (was UNWIRED — literature_fn=make_literature_fn(DIFFERENTIATION_LANDSCAPE, default_retrieve,
                          #        verify_citations); refined _LENS_QUERY_TERMS +TMB/MSI/patient-strat/combo). (2) NEW consolidated
                          #        cooccurrence_confidence_caveat headline field — the co-mutation analog of mechanism's
                          #        actionable_moa / tumor-presence's presence_confirmation caveat: a STATISTICAL co-mutation /
                          #        mutual-exclusivity association OVER-CALLS a biological / patient-selection relationship. Tiers
                          #        (i) cooccurrence_tmb_or_lineage_confounded (BRAF/COADREAD MSI-H hypermutation driver, curated),
                          #        (ii) significant_but_low_effect_or_panel_ineligible / significant_but_near_universal (TP53), (iii)
                          #        MILDER biologically_established_pattern false-demote guard (KRAS/NRAS-class canonical MAPK
                          #        exclusivity, curated). (3) cooccurrence_provenance quorum summary. (4) DIFFERENTIATION lens
                          #        thesis extended + polarity_note ADDED (was NONE). VERDICT-INERT: gates on already-emitted
                          #        headline fields, None on ns/data_unavailable, NEVER read by the resolver -> differentiation_verdict
                          #        + resolver golden + KRAS/FBXW7 replay byte-stable.   # 1.8.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.   # 1.7.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # 1.6.0 (2026-08-24): compose competitor-landscape (Open Targets competitor field)
                          #        as an ADDITIVE, verdict-inert render facet; namespaced competitor_* headline
                          #        keys feed the target-profile deterministic modality cross-ref. Verdict byte-stable.
                          # 1.5.0 (2026-08-21): compose clinical-precedent (AACT trial precedent) as an
                          #        ADDITIVE/VERDICT-INERT render facet (translational-maturity lens);
                          #        differentiation verdict byte-stable (no resolver rung on clinical_*).
                          # 1.4.0 (2026-08-21): + canonical HEADLINE block (verdict + confidence + top
                          #        tension) + shared headline hero (figure_headline_hero.{svg,png,json}).
                          #        A verdict-INERT projection over the DESCRIPTIVE claim_vector /
                          #        key_signals — differentiation_verdict spine byte-stable (frozen by
                          #        the KRAS/FBXW7 COADREAD replay guard).

CARDS = [
    "co-mutation-and-mutual-exclusivity",
    "stemness-context",   # Malta 2018 (2026-08-10): per-indication tumor-stemness (mRNAsi) cohort prior
                          # — dedifferentiation/aggressiveness prognostic context. ADDITIVE, VERDICT-INERT
                          # (its rules feed NO resolver; differentiation verdict byte-stable). reads stemness_index.
    "expression-clinical-association",   # Q11 (2026-07-23 composition) — does target expression
                                         # stratify SURVIVAL (prognostic context)? A patient-selection /
                                         # clinical-context render facet + biomarker-facet stratification
                                         # input. ADDITIVE — its clinical-* rules feed NO resolver ladder
                                         # (differentiation verdict byte-stable; resolver reads only the
                                         # co-mutation rule_ids). Fills part of the clinical-precedent gap
                                         # this skill's status-partial note flags.
    "precog-prognostic-association",     # PRECOG (2026-08-10): pan-cancer META-ANALYTIC expression→survival
                                         # meta-Z (Gentles 2015 + 2026 NAR; 166 datasets / ~18k patients).
                                         # The better-powered pan-cancer CORROBORATION of the single-cohort
                                         # expression-clinical-association card above. ADDITIVE, VERDICT-INERT
                                         # (no resolver rung; differentiation verdict byte-stable). reads precog_prognostic.
    "pathway-node-leverage",             # (2026-08-17): COMPARATIVE node-leverage — is the target the best
                                         # NODE to hit in its complex/pathway neighbourhood, or dominated? ADDITIVE,
                                         # VERDICT-INERT (its rules emit soft axis_fit signals + fired_rule_ids for
                                         # the cross-evidence hypothesis agent; feed NO resolver → differentiation
                                         # verdict byte-stable). reads node_leverage_class + evidence_scope.
    "alteration-clinical-association",   # Q11-alteration (2026-08-20): does {target} MUTATION status
                                         # stratify OS (prognostic context)? The alteration analog of
                                         # expression-clinical-association. ADDITIVE, VERDICT-INERT (its
                                         # alteration-* rules feed NO resolver; differentiation verdict
                                         # byte-stable). reads alteration_survival_association_class.
    "subtype-survival-association",      # Q2-subtype (2026-08-20): does OS differ ACROSS the indication's
                                         # molecular subtypes? Target-independent patient-selection context.
                                         # ADDITIVE, VERDICT-INERT (subtype-* rules feed NO resolver;
                                         # differentiation verdict byte-stable). reads subtype_survival_association_class.
    "clinical-precedent",                # (2026-08-21): AACT clinical-trial precedent for (target, indication) —
                                         # highest stage / active trials / approved agents / notable failures for a
                                         # drug that ENGAGES the target. WIRED via public-domain AACT (was the
                                         # licensing-blocked placeholder this skill's status note flagged). ADDITIVE,
                                         # VERDICT-INERT (no resolver rung; differentiation verdict byte-stable) —
                                         # the translational-maturity render facet. reads highest_clinical_stage +.
    "competitor-landscape",              # (2026-08-24): Open Targets competitor field for (target, indication) —
                                         # WHO ELSE is developing a drug against this target, at what MODALITY
                                         # (ADC/TCE/mAb/SM/degrader) and clinical stage. WIRED via the pinned OT mirror
                                         # (opentargets-target-competitor-drugs-per-gene-v1). ADDITIVE, VERDICT-INERT
                                         # (no resolver rung; differentiation verdict byte-stable) — the competitive-
                                         # positioning render facet. The value-add cross-ref vs the framework's own
                                         # modality-fit/biomarker verdicts is computed at the target-profile fan-out.
                                         # reads competitor_class + modality_landscape.
]

QUESTION = ("What genes co-occur with or are mutually exclusive to "
            "{target} mutations across TCGA MC3 + GENIE 19.0-public, "
            "and what patient-selection or combination-biology hypotheses "
            "does the pattern support in {indication}?")

PARTIAL_STATUS_NOTE = (
    "differentiation-landscape is status: partial. The clinical-precedent card is now WIRED "
    "(2026-08-21) via public-domain AACT (aact_clinical_precedent) — NO commercial license needed — "
    "and is produced in the composed dashboards; adding it to THIS focused skill's cards_used is a "
    "follow-up. patent-landscape remains unwired (PatBase-equivalent licensing pending). This "
    "skill's own decision still reflects the co-mutation / mutual-exclusivity signal."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (2026-07-20).
    The former if-chain now lives in resolvers/differentiation.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "differentiation")


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# differentiation-landscape's declaration for the shared headline_core builder: the four DESCRIPTIVE
# claim axes (COMUT / SURVIVAL / PROGNOSIS / NODE), the differentiation-verdict vocabulary → human
# phrase. Verdict-INERT — a one-way projection over the already-computed headline (differentiation_verdict
# stays byte-stable, frozen by test_differentiation_replay.py + the golden-oracle resolver test).
#
# POLARITY (colours the hero badge). This skill is DESCRIPTIVE: the signal is the STRENGTH of a
# differentiation / patient-selection pattern, and the DIRECTION (co-occurring vs mutually-exclusive;
# worse vs better survival) lives in the atom, NOT the verdict tier. So no differentiation_verdict is a
# clean favourable/unfavourable call for a drug program — every verdict colours the badge `neutral`
# (grey). (Contrast the safety skill, whose inverse-valence liability verdicts DO carry program-polarity.)

# The differentiation.resolver verdict vocabulary → human phrase, with a prettify fallback for any
# future addition. All are DESCRIPTIVE pattern reads (direction lives in the claim atoms).
_DIFFERENTIATION_VERDICT_PHRASE = {
    "both_patterns_present":     "Co-occurring + mutually-exclusive partners",
    "strong_cooccurring":        "Strong co-mutation landscape",
    "strong_mutually_exclusive": "Strong mutual-exclusivity landscape",
    "has_cooccurring_driver":    "Co-occurring driver present",
    "modest_cooccurring":        "Modest co-mutation signal",
    "modest_mutually_exclusive": "Modest mutual-exclusivity signal",
    "ns":                        "No significant co-mutation pattern",
    "data_unavailable":          "Data unavailable",
    "insufficient":              "Insufficient evidence",
}


def _differentiation_verdict_polarity(v) -> str:
    """The skill's OWN reading of the differentiation verdict for the hero badge (never a gate).
    differentiation-landscape is DESCRIPTIVE — the verdict tier encodes the STRENGTH of a co-mutation /
    survival pattern, while the favourable/unfavourable DIRECTION lives in the claim atom. No verdict is
    a clean program-desirability call, so polarity is always `neutral` (grey badge)."""
    return "neutral"


def _int_or_none(v):
    """Coerce a headline count to int; None/non-numeric → None (field-absent-safe)."""
    return v if isinstance(v, int) else (int(v) if isinstance(v, float) else None)


def _panel_absent_signal(hl: dict) -> str | None:
    """DETERMINISTIC panel-intersect-provenance caveat (verdict-INERT).

    The reviewer BLOCKER-FIX restricts a POOLED co-mutation claim to the GENIE panel-intersect
    (166 genes): a panel-ABSENT target gets per-source q-values only (`pooled_eligible=false`) and
    must not be read as a pooled cross-cohort pattern. But the read-time classifier keys the
    `cooccurrence_class` on q + log2-OR ALONE — it never consults `pooled_eligible` — so a
    panel-absent target (e.g. a large passenger gene) can still surface a `strong_cooccurring`
    pattern built ENTIRELY from per-source pairs, which for a long/passenger gene is a TMB /
    gene-length co-mutation artifact rather than biology. When the target is IN the scan but has
    ZERO panel-intersect-eligible pairs, surface that deterministically (rather than leaving it to
    LLM discretion). Verdict token is UNTOUCHED. Fires only for panel-absent targets, so every
    panel-present target (incl. the KRAS / FBXW7 COADREAD replay fixtures, both with >0 eligible
    pairs, and CD19) is byte-identical."""
    elig = _int_or_none(hl.get("n_pairs_panel_intersect_eligible"))
    per_source = _int_or_none(hl.get("n_pairs_per_source_only"))
    if elig == 0 and (per_source or 0) > 0:
        return ("Target is absent from the GENIE panel-intersect (0 panel-intersect-eligible pairs; "
                f"{per_source} per-source-only pairs) — no POOLED cross-cohort co-mutation claim is "
                "possible. The co-mutation pattern rests entirely on per-source pairs and, for a "
                "large/passenger gene, may reflect tumor-mutational-burden / gene-length confounding "
                "rather than biology (pooled_eligible=false throughout).")
    return None


def _panel_absent_tension(hl: dict) -> dict | None:
    """tension_extra hook — the panel-absent caveat as the single top_tension (severity 3, data-quality)."""
    cav = _panel_absent_signal(hl)
    return {"text": cav, "source": "panel_intersect.absent", "severity": 3} if cav else None


# ── COOCCURRENCE-CONFIDENCE consolidated caveat (VERDICT-INERT) — the co-mutation analog of mechanism's
#    actionable-MoA and tumor-presence's presence_confirmation inflation surface. THE TRAP: a STATISTICAL
#    co-mutation / mutual-exclusivity ASSOCIATION over-calls a BIOLOGICAL / patient-selection RELATIONSHIP.
#    The panel-intersect Fisher scan carries NO TMB / MSI / molecular-subtype covariate (the reader emits no
#    such flag), so the data cannot separate (a) a TMB/hypermutation-driven co-occurrence hub (BRAF-V600E in
#    MSI-H/CIMP CRC co-occurs with a long PASSENGER tail because both are frequent at high mutation burden),
#    (b) a lineage/subtype-restricted exclusivity, from (c) a biologically-established same-pathway
#    relationship (KRAS/NRAS/BRAF MAPK redundancy). Live proof (COADREAD): BRAF (1029 co-occurring),
#    KRAS (709), TP53 (near-universal) ALL fire `both_patterns_present`/`strong_*` → the identical
#    `supportive`(+dominant) rung — the token cannot distinguish them. Because DIFFERENTIATION IS a
#    NOMINATING axis (∈ target-profile _SHORT_TO_GATE; the cooccurrence rules fire small_molecule/degrader
#    `supportive`, two of them `dominant:true`), a TMB-confounded co-occurrence INFLATES a nomination. So —
#    exactly as the mechanism (_VALIDATED_ACTIONABLE_MOA_PRECEDENT) and tumor-presence
#    (_CLINICALLY_PRECEDENTED_TUMOR_ANTIGENS) arcs concluded — the honest DETERMINISTIC discriminator is a
#    SMALL, DISCLAIMED, NON-EXHAUSTIVE curated (target, indication) crosswalk, corroborated by the
#    --literature lane + narrator. The caveat is VERDICT-INERT (never read by the resolver); a target absent
#    from every crosswalk degrades to the DATA-derived effect-size/panel-eligibility tier or None (never a
#    verdict change). A verdict-MOVING TMB/subtype-adjusted resolver rung is the Phase-6 cross-repo candidate
#    (AM cooccurrence_fisher reader), NOT this skills-side inert surface.

# NORMALISE the OncoTree code so the COADREAD crosswalks also match the COAD / READ sub-codes.
_COMUT_IND_ALIAS = {"COAD": "COADREAD", "READ": "COADREAD"}


def _norm_ind(indication) -> str:
    ind = (indication or "").upper().strip()
    return _COMUT_IND_ALIAS.get(ind, ind)


# (target, indication) whose co-occurrence LANDSCAPE is dominated by hypermutation / MSI / a molecular
# subtype — the apparent co-occurrence with a long partner tail is a mutation-BURDEN artifact, not a
# pairwise biological interaction (the SHARP driver). Keyed on the CO-OCCURRENCE component; the target's
# MUTUAL-EXCLUSIVITY may still be real (BRAF↔KRAS/NRAS MAPK redundancy) — the detail + polarity_note carry
# that nuance. DISCLAIMED / non-exhaustive; an absent target degrades to a data tier or None.
# (target, indication)-SPECIFIC because the confound IS indication-specific — the SAME target can be a
# burden/lineage-confounded co-occurrence HUB in one indication and a clean driver in another (BRAF-V600E is
# MSI-confounded in CRC but NOT in melanoma; IDH1 defines a distinct glioma lineage but is a clean AML driver).
# Two ARMS: TMB/hypermutation and LINEAGE/subtype. DISCLAIMED / non-exhaustive; an absent (target,indication)
# degrades to the pan-cancer established/near-universal check, then a data tier, then None.
_TMB_LINEAGE_CONFOUNDED_COMUT = {
    ("BRAF", "COADREAD"): (
        "TMB arm — BRAF-V600E CRC is tightly bound to CIMP-high / MLH1-hypermethylated sporadic MSI-H / "
        "hypermutation (serrated pathway; ~half of BRAF-mutant CRC is MSI-H), so its apparent co-occurrence "
        "with a long passenger tail is a tumor-mutational-burden artifact, not a pairwise biological "
        "interaction (Weisenberger 2006 PMID 16804544; TCGA 2012 PMID 22810696; van de Haar 2019 PMID "
        "31150618; DISCOVER Canisius 2016 PMID 27986087 — chance explains most co-occurrence). The actionable "
        "axis in this subset is MSI/dMMR (checkpoint benefit; KEYNOTE-177), not the BRAF co-mutation per se."),
    ("IDH1", "GBM"): (
        "LINEAGE arm — IDH1 mutation defines a DISTINCT glioma lineage (IDH-mutant lower-grade glioma / "
        "secondary GBM) that is molecularly separate from IDH-wildtype primary GBM (EGFR-amplified / "
        "PTEN-lost / +7/-10); WHO 2021 classifies them as different entities. So IDH1's co-occurrence / "
        "mutual-exclusivity in a pooled GBM cohort reflects the IDH-mutant SUBTYPE restriction (a Simpson's-"
        "paradox / population-stratification confound), not a pairwise interaction (Yan 2009 PMID 19228619; "
        "Ceccarelli 2016 PMID 26824661; Guinney-style subtype confound van de Haar 2019 PMID 31150618)."),
}

# canonical, biologically-ESTABLISHED same-pathway relationships that must NOT be demoted (the FALSE-DEMOTE
# GUARD). The RAS/RAF MAPK-activating drivers are mutually exclusive by same-pathway redundancy in ANY cancer
# — one activating hit is sufficient (Rajagopalan 2002 PMID 12198537; Davies 2002 PMID 12068308; MEMo module
# analysis Ciriello 2012 PMID 21908773) — a validated patient-selection biomarker (anti-EGFR negative
# predictor; CRYSTAL PMID 19339720 / PRIME PMID 24024839). So this arm is GENE-LEVEL / PAN-CANCER (the
# exclusivity is canonical regardless of indication); a target here is spared UNLESS the (target, indication)
# is in the confound set above (the confound OUTRANKS — BRAF/COADREAD is still confounded).
_ESTABLISHED_MAPK_EXCLUSIVITY_GENES = {"KRAS", "NRAS", "HRAS", "BRAF"}

# non-MAPK canonical same-pathway exclusivities that ARE indication-specific (kept as explicit
# (target, indication) rows): the NSCLC RTK-driver exclusivity — EGFR is mutually exclusive with KRAS/ALK in
# lung adenocarcinoma because one activating RTK→RAS→MAPK driver is sufficient (the canonical NSCLC oncogenic-
# driver partition). DISCLAIMED / non-exhaustive.
_BIOLOGICALLY_ESTABLISHED_COMUT = {
    ("EGFR", "LUAD"), ("EGFR", "LUSC"), ("EGFR", "NSCLC"),
}

# near-universal drivers whose HIGH co-occurrence count is chiefly a marginal-FREQUENCY consequence (co-occurs
# with a long partner tail because it is mutated in a majority of tumors) → a q-significant pair is not a
# patient-selection hypothesis: significance ≠ actionability (the housekeeping/ubiquitous analog; DISCOVER
# PMID 27986087). TP53 is near-universal PAN-CANCER (most solid tumors), so this arm is GENE-LEVEL; an
# indication-specific near-universal driver can be added to the explicit set below. DISCLAIMED / non-exhaustive.
_NEAR_UNIVERSAL_GENES = {"TP53"}
_NEAR_UNIVERSAL_MUTATION: set = set()   # explicit (target, indication) rows for non-pan-cancer near-universal drivers

# cooccurrence_class values that carry a POSITIVE / significant pattern (the caveat fires ONLY on these; a
# ns / data_unavailable / insufficient / absent read → None, byte-stable on the negative path). SET literal
# (NOT a 2-tuple — the drift guard reads a 2-string tuple as a (rule_id, verdict) precedence pair).
_COMUT_POSITIVE = {
    "both_patterns_present", "strong_cooccurring", "strong_mutually_exclusive",
    "modest_cooccurring", "modest_mutually_exclusive",
}
_COMUT_COOC_COMPONENT = {"both_patterns_present", "strong_cooccurring", "modest_cooccurring"}
_COMUT_MODEST = {"modest_cooccurring", "modest_mutually_exclusive"}


def _is_established(gene: str, key: tuple) -> bool:
    """Canonical biologically-established same-pathway relationship — the pan-cancer GENE-LEVEL MAPK-triad
    exclusivity OR an explicit (target, indication) row (the NSCLC RTK-driver exclusivity)."""
    return gene in _ESTABLISHED_MAPK_EXCLUSIVITY_GENES or key in _BIOLOGICALLY_ESTABLISHED_COMUT


def _is_near_universal(gene: str, key: tuple) -> bool:
    """Near-universal driver — the pan-cancer GENE-LEVEL set (TP53) OR an explicit (target, indication) row."""
    return gene in _NEAR_UNIVERSAL_GENES or key in _NEAR_UNIVERSAL_MUTATION


def _cooccurrence_confidence_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """CONSOLIDATED statistical-vs-biological co-mutation confidence call (VERDICT-INERT). Folds effect-size +
    TMB/subtype-confound (curated) + panel-eligibility into ONE consumer-facing "statistically-significant-
    but-biologically-unconfirmed / patient-selection-actionable?" field. Precedence: the SHARP TMB/lineage
    confound (i) > the MILDER biologically-established false-demote guard (iii) > the SHARP data cautions
    (ii, significance≠actionability) > None. Gates on already-emitted headline fields; never moves the spine."""
    cls = hl.get("cooccurrence_class")
    if cls not in _COMUT_POSITIVE:
        return None                                              # ns / data_unavailable / insufficient → byte-stable
    gene = (target or "").upper().strip()
    key = (gene, _norm_ind(indication))
    has_cooc = bool(hl.get("has_cooccurring_driver")) or cls in _COMUT_COOC_COMPONENT
    has_mutex = bool(hl.get("has_mutually_exclusive_driver")) or cls == "strong_mutually_exclusive"

    # TIER (i) SHARP — TMB / hypermutation / lineage confound ((target,indication)-specific), requires a
    # co-occurring component. OUTRANKS the pan-cancer established guard (BRAF ∈ the MAPK gene-set, but
    # BRAF/COADREAD is still confounded — the co-occurrence hub is burden-driven even though the KRAS/NRAS
    # exclusivity is real).
    if key in _TMB_LINEAGE_CONFOUNDED_COMUT and has_cooc:
        detail = _TMB_LINEAGE_CONFOUNDED_COMUT[key]
        if has_mutex:
            detail += (" The mutual-exclusivity component (e.g. KRAS/NRAS MAPK pathway redundancy) may still "
                       "be a real, biologically-established relationship — see top_mutually_exclusive.")
        return {"reason": "cooccurrence_tmb_or_lineage_confounded", "tier": "sharp",
                "false_demote_guarded": False, "detail": detail}

    # TIER (iii) MILDER — biologically-established same-pathway guard (pan-cancer MAPK-triad OR the explicit
    # NSCLC RTK-driver rows) OUTRANKS the data cautions (a canonical KRAS/NRAS/BRAF/EGFR-class exclusivity must
    # NOT be flagged as low-effect / uninformative).
    if _is_established(gene, key):
        return {"reason": "biologically_established_pattern", "tier": "milder", "false_demote_guarded": True,
                "detail": ("Canonical, biologically-established same-pathway relationship — NOT an over-call, "
                           "explicitly NOT demoted. The RAS/RAF MAPK-activating drivers (KRAS/NRAS/HRAS/BRAF) "
                           "are mutually exclusive by same-pathway redundancy in ANY cancer — one activating "
                           "hit is sufficient (Rajagopalan 2002 PMID 12198537; Davies 2002 PMID 12068308) — a "
                           "validated anti-EGFR negative predictor (CRYSTAL/PRIME); the NSCLC RTK-driver "
                           "exclusivity (EGFR vs KRAS/ALK) is the same one-driver-sufficient partition.")}

    # TIER (ii) SHARP — significance ≠ actionability: near-universal (pan-cancer TP53 OR explicit row), then
    # DATA-derived panel-ineligibility / low effect size.
    if _is_near_universal(gene, key):
        return {"reason": "significant_but_near_universal", "tier": "sharp", "false_demote_guarded": False,
                "detail": ("Near-universal driver: co-occurs with a long partner tail chiefly as a "
                           "marginal-frequency consequence (mutated in a majority of tumors), so a "
                           "q-significant pair is not a patient-selection hypothesis — significance ≠ "
                           "actionability (DISCOVER Canisius 2016 PMID 27986087: chance explains most "
                           "co-occurrence).")}
    if _panel_absent_signal(hl) is not None:
        return {"reason": "significant_but_low_effect_or_panel_ineligible", "tier": "sharp",
                "false_demote_guarded": False,
                "detail": ("Panel-absent: 0 panel-intersect-eligible pairs; the pattern rests entirely on "
                           "per-source-only pairs (pooled_eligible=false) — no pooled cross-cohort co-mutation "
                           "claim is possible, and for a large/passenger gene may reflect TMB / gene-length "
                           "confounding.")}
    if cls in _COMUT_MODEST:
        return {"reason": "significant_but_low_effect_or_panel_ineligible", "tier": "sharp",
                "false_demote_guarded": False,
                "detail": ("Modest effect size (q<0.05 but 0.5<|log2_odds_ratio|<1.0): q-significant yet "
                           "small-effect — informative context, not a decision-grade patient-selection / "
                           "combination hypothesis.")}
    # A STRONG, panel-eligible, non-confounded, non-near-universal pattern → no caveat (honest positive).
    return None


def _best_partner(lst) -> dict | None:
    """The top (already rank-sorted) partner's effect-size row, field-absent-safe."""
    for p in (lst or []):
        if isinstance(p, dict):
            return {"partner_gene_symbol": p.get("partner_gene_symbol"),
                    "log2_odds_ratio": p.get("log2_odds_ratio"), "bh_q_value": p.get("bh_q_value"),
                    "source": p.get("source"), "pooled_eligible": p.get("pooled_eligible")}
    return None


def _cooccurrence_provenance(hl: dict, target=None, indication=None) -> dict | None:
    """QUORUM / PROVENANCE summary for the co-mutation call (VERDICT-INERT): effect sizes, q-values,
    panel-eligibility, per-source presence, the pre-floor audit class, and the curated TMB/subtype
    confounder flag. None when there is no significant pattern (byte-stable negative path)."""
    cls = hl.get("cooccurrence_class")
    if cls not in _COMUT_POSITIVE:
        return None
    elig = _int_or_none(hl.get("n_pairs_panel_intersect_eligible"))
    per_source = _int_or_none(hl.get("n_pairs_per_source_only"))
    top_cooc = hl.get("top_cooccurring") or []
    top_mutex = hl.get("top_mutually_exclusive") or []
    srcs = sorted({str((p or {}).get("source", "")).lower()
                   for p in (top_cooc[:10] + top_mutex[:10]) if isinstance(p, dict) and p.get("source")})
    gene = (target or "").upper().strip()
    key = (gene, _norm_ind(indication))
    return {
        "cooccurrence_class": cls,
        "cooccurrence_class_prefloor": hl.get("cooccurrence_class_prefloor"),
        "n_significant_cooccurring": hl.get("n_significant_cooccurring"),
        "n_significant_mutually_exclusive": hl.get("n_significant_mutually_exclusive"),
        "n_pairs_panel_intersect_eligible": elig,
        "n_pairs_per_source_only": per_source,
        # the card's `many_pairs_panel_ineligible` warning condition — a pooling-caution flag.
        "panel_ineligible_exceeds_eligible": (per_source is not None and elig is not None and per_source > elig),
        "best_cooccurring": _best_partner(top_cooc),
        "best_mutually_exclusive": _best_partner(top_mutex),
        "sources_present": srcs,
        # curated confounder / established flags (the discriminator the pooled Fisher scan is blind to):
        "tmb_or_subtype_confounder_flag": key in _TMB_LINEAGE_CONFOUNDED_COMUT,
        "biologically_established_flag": _is_established(gene, key),
        "near_universal_flag": _is_near_universal(gene, key),
    }


def _clonality_caveat(hl: dict) -> dict | None:
    """COHORT-level (same-SAMPLE) co-occurrence ≠ same-CELL / CLONAL co-occurrence (VERDICT-INERT) — the (c)
    sub-inflation. A pooled TCGA-MC3 + GENIE bulk Fisher scan counts two altered genes in the SAME PATIENT but
    cannot resolve clonal architecture: the pair may be clonal co-drivers, or sit in separate subclones / on
    branched lineages (subclonal / parallel evolution). Bulk without single-cell / multi-region / cancer-cell-
    fraction (CCF) data cannot distinguish them. Fires ONLY on the CO-OCCURRING path (clonality is a
    co-occurrence question — a mutual-exclusivity is an ABSENCE of same-sample co-mutation, so the same-cell
    caveat does not apply); None on ns / data_unavailable / exclusivity-only → byte-stable negative path.
    Keyed on the emitted headline only (no curated crosswalk): it applies to EVERY pooled co-occurrence."""
    cls = hl.get("cooccurrence_class")
    if cls not in _COMUT_POSITIVE:
        return None                                              # ns / data_unavailable / insufficient → byte-stable
    has_cooc = bool(hl.get("has_cooccurring_driver")) or cls in _COMUT_COOC_COMPONENT
    if not has_cooc:
        return None                                              # exclusivity-only → same-cell caveat N/A
    return {
        "reason": "cohort_not_same_cell_clonal",
        "resolves_clonality": False,
        "detail": ("Cohort-level co-occurrence, NOT same-cell / clonal. The pooled TCGA-MC3 + GENIE Fisher "
                   "scan counts two altered genes in the SAME PATIENT / bulk SAMPLE but cannot resolve whether "
                   "they share a CLONE (clonal co-drivers) or arose in separate subclones / by parallel "
                   "(branched) evolution — bulk sequencing without single-cell / multi-region / cancer-cell-"
                   "fraction (CCF) data cannot distinguish clonal from subclonal co-occurrence (Gerlinger 2012 "
                   "PMID 22397650; McGranahan & Swanton 2017 PMID 28187284). A same-sample co-occurrence is a "
                   "patient-level association, NOT proof of a same-cell co-driver relationship; a same-cell "
                   "co-dependency / SL call is owned by functional-requirement + combination-and-vulnerability."),
    }


_DIFFERENTIATION_HEADLINE_SPEC = HeadlineSpec(
    gate="differentiation",
    axis_labels={"COMUT": "co-mutation landscape", "SURVIVAL": "expression↔survival",
                 "PROGNOSIS": "PRECOG prognostic", "NODE": "pathway-node leverage"},
    axis_keys=("COMUT", "SURVIVAL", "PROGNOSIS", "NODE"),
    critical_axes=("COMUT", "SURVIVAL"),
    verdict_label=lambda v: _DIFFERENTIATION_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    # Skill-specific tension: the panel-intersect-provenance flag (a panel-ABSENT target whose
    # co-mutation pattern rests only on per-source pairs). Verdict-INERT; fires only for panel-absent
    # targets, so panel-present targets (incl. the replay fixtures) are byte-identical.
    tension_extra=_panel_absent_tension,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed differentiation headline. Reads the
    resolved verdict + the verdict-inert claim_vector / key_signals; never moves the spine. This skill
    emits no CERTAINTY_MODEL sidecar, so confidence is derived from the claim vector's corroboration."""
    v = headline.get("differentiation_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_DIFFERENTIATION_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_differentiation_verdict_polarity(v))


# ── (strength, certainty) SIDECAR — CERTAINTY_MODEL.md. ADDITIVE + verdict-INERT. Differentiation is a
#    NON-GATING descriptive axis; certainty is coverage + unknown_mass only here — corroboration reads
#    `unmeasured` because the only verdict-DISJOINT corroborator (TCGA<->GENIE per-source direction
#    concordance) is NOT yet emitted as a summary field (it lives in the card's plot_data). Wiring it
#    needs an analysis-methods field-emit + a field-granular disjointness validator (the corroborator
#    shares the verdict card) — a data-ingest follow-on, not this additive slice. strength is a PATTERN
#    magnitude (co-occurrence vs mutual-exclusivity is a pattern TYPE, not good/bad — informational).
_DIFF_ORD = {"low": 0, "medium": 1, "high": 2}
_DIFF_STRONG = {"strong_cooccurring", "strong_mutually_exclusive", "both_patterns_present"}
_DIFF_MOD = {"has_cooccurring_driver", "modest_cooccurring", "modest_mutually_exclusive"}
_DIFF_NONE = {"ns", "data_unavailable", "insufficient", None}


def _diff_card_field(cards, field):
    """None-safe read of the single differentiation verdict card (get_card_field raises on absent)."""
    cid = "co-mutation-and-mutual-exclusivity"
    return get_card_field(cards, cid, field) if cid in {c["card_id"] for c in (cards or [])} else None


def _diff_strength(v) -> str:
    if v in _DIFF_STRONG:
        return "strong_pattern"           # informational: co-occurrence / mutual-exclusivity is a TYPE
    if v in _DIFF_MOD:
        return "moderate_pattern"
    return "none"


def _diff_coverage(n_pairs) -> str:
    """Power of the pooled panel-intersect Fisher test (the pairs that actually drive the verdict)."""
    if not isinstance(n_pairs, (int, float)):
        return "low"
    return "high" if n_pairs >= 50 else ("medium" if n_pairs >= 10 else "low")


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — coverage+unknown_mass only (corroboration unmeasured)."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    n_pairs = _diff_card_field(cards, "n_pairs_panel_intersect_eligible")
    coverage = _diff_coverage(n_pairs)
    level = "low" if v in _DIFF_NONE else coverage      # corroboration unmeasured → level = coverage
    present = "co-mutation-and-mutual-exclusivity" in {c["card_id"] for c in (cards or [])}
    return {
        "strength": _diff_strength(v),
        "certainty": {"level": level, "coverage": coverage, "corroboration": "unmeasured",
                      "unknown_mass": 0.0 if present else 1.0},   # single verdict card (degenerate)
        "provenance": {"n_pairs_panel_intersect_eligible": n_pairs},
        "_model_ref": "CERTAINTY_MODEL.md#differentiation",
    }


# ── FACTORED-RECORD SHADOW (M1) — the DIFFERENTIATION per-axis builder. Differentiation is a
#    DESCRIPTIVE / non-gating axis: co-occurrence vs mutual-exclusivity is a pattern TYPE, not a
#    good/bad valence, so finding.direction is ALWAYS neutral (the pattern informs, it does not push a
#    nomination). VERDICT-INERT: surfaced by the fan-out into decision.claim_record_shadow.differentiation,
#    consumed by NOTHING. Reuses _strength_certainty (coverage-only). Mirrors the other axes' hook.
_DIFF_STRENGTH_TO_LEVEL = {"strong_pattern": "strong", "moderate_pattern": "moderate", "none": "none"}


def _diff_availability(v) -> str:
    if v == "data_unavailable" or v is None:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v == "insufficient":
        return "insufficient"
    if v == "ns":
        return "measured_negative"               # measured, no significant pattern
    return "measured_positive"                   # a pattern was detected


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=verdict_pair)
    return assemble_claim_record(
        axis="differentiation",
        state=(v or "insufficient"),
        direction="neutral",                     # descriptive pattern — never pushes a nomination
        availability=_diff_availability(v),
        magnitude={"level": _DIFF_STRENGTH_TO_LEVEL.get(_diff_strength(v), "none")},
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "differentiation_verdict":          v,
        "driving_rule_id":                  drv,
        "cooccurrence_class":               get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "cooccurrence_class"),
        # AUDIT: raw pre-floor class (verdict-INERT card field — differs from cooccurrence_class only when a
        # pure-TCGA-WES passenger was floored to ns). Surfaced in cooccurrence_provenance for panel-absence context.
        "cooccurrence_class_prefloor":      get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "cooccurrence_class_prefloor"),
        "n_significant_cooccurring":        get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_significant_cooccurring"),
        "n_significant_mutually_exclusive": get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_significant_mutually_exclusive"),
        "n_pairs_panel_intersect_eligible": get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_panel_intersect_eligible"),
        "n_pairs_per_source_only":          get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_per_source_only"),
        "has_cooccurring_driver":           get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "has_cooccurring_driver"),
        "has_mutually_exclusive_driver":    get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "has_mutually_exclusive_driver"),
        "top_cooccurring":                  get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "top_cooccurring"),
        "top_mutually_exclusive":           get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "top_mutually_exclusive"),
        # Q11 expression→survival prognostic context (render facet; feeds NO resolver — the
        # differentiation verdict reads only the co-mutation rule_ids, so this is verdict-inert):
        "survival_association_class":       get_card_field(cards, "expression-clinical-association",
                                                 "survival_association_class"),
        "logrank_p":                        get_card_field(cards, "expression-clinical-association", "logrank_p"),
        # PRECOG pan-cancer META-ANALYTIC corroboration of the single-cohort survival call above
        # (render facet; verdict-inert — no resolver rung). Surface the class + both meta-Z views so a
        # reader can compare the single-cohort log-rank vs the pan-cancer meta-analysis at a glance:
        "precog_prognostic_class":          get_card_field(cards, "precog-prognostic-association",
                                                 "prognostic_class"),
        "precog_meta_z":                    get_card_field(cards, "precog-prognostic-association", "meta_z"),
        "precog_pan_cancer_meta_z":         get_card_field(cards, "precog-prognostic-association",
                                                 "pan_cancer_meta_z"),
        "precog_indication_approx":         get_card_field(cards, "precog-prognostic-association",
                                                 "precog_indication_approx"),
        # comparative node-leverage (soft/verdict-inert differentiation context; feeds NO resolver —
        # its axis_fit signals + fired_rule_ids are consumed by the cross-evidence hypothesis agent):
        "node_leverage_class":              get_card_field(cards, "pathway-node-leverage",
                                                 "node_leverage_class"),
        "node_leverage_evidence_scope":     get_card_field(cards, "pathway-node-leverage",
                                                 "evidence_scope"),
        # AACT clinical-trial precedent (render facet; verdict-inert — no resolver rung). The
        # translational-maturity lens: highest stage reached by a drug ENGAGING the target in this
        # indication, active-trial count, approved agents, and notable (terminated) failures.
        # (highest_clinical_stage is the primary categorical — the card emits no separate _class field):
        "highest_clinical_stage":           get_card_field(cards, "clinical-precedent", "highest_clinical_stage"),
        "n_active_trials":                  get_card_field(cards, "clinical-precedent", "n_active_trials"),
        "approved_agents":                  get_card_field(cards, "clinical-precedent", "approved_agents"),
        "notable_failures":                 get_card_field(cards, "clinical-precedent", "notable_failures"),
        # Open Targets competitor field (render facet; verdict-inert — no resolver rung). The
        # competitive-positioning lens: who else has a drug against this target, at what MODALITY and
        # stage. Namespaced 'competitor_*' to avoid colliding with the AACT clinical-precedent keys
        # above. modality_landscape is the field the target-profile cross-ref keys on (competitor
        # modality validated-vs-contrarian vs the framework's own surface-modality-fit verdict).
        "competitor_class":                 get_card_field(cards, "competitor-landscape", "competitor_class"),
        "competitor_highest_stage":         get_card_field(cards, "competitor-landscape", "highest_clinical_stage"),
        "competitor_indication_scope":      get_card_field(cards, "competitor-landscape", "indication_scope"),
        "n_competitor_programs":            get_card_field(cards, "competitor-landscape", "n_competitor_programs"),
        "competitor_approved_agents":       get_card_field(cards, "competitor-landscape", "approved_agents"),
        "competitor_late_stage_non_approved": get_card_field(cards, "competitor-landscape", "late_stage_non_approved_agents"),
        "competitor_modalities_in_development": get_card_field(cards, "competitor-landscape", "modalities_in_development"),
        "competitor_modality_landscape":    get_card_field(cards, "competitor-landscape", "modality_landscape"),
    }
    # verdict-INERT claim-vector projection (7th concrete) — COMUT/SURVIVAL/PROGNOSIS/NODE decomposition
    # + citable atoms the composed fan-out lifts to the cross-evidence agent.
    hl["claim_vector"] = differentiation_claim_vector(hl, cards)
    hl["key_signals"] = differentiation_key_signals(hl, cards)
    # DETERMINISTIC panel-intersect-provenance caveat (verdict-INERT): a panel-ABSENT target's
    # co-mutation pattern rests only on per-source pairs (possible TMB/gene-length artifact). Surface it
    # as the key_signals caveat so the narrator + cross-evidence agent see it deterministically instead of
    # relying on LLM discretion. Panel-absence is the dominant data-quality caveat, so it takes the slot
    # (differentiation_key_signals emits no claim-tier caveat today). Fires only for panel-absent targets
    # → panel-present targets (incl. KRAS/FBXW7 replay fixtures) keep caveat=None, byte-identical.
    _pa = _panel_absent_signal(hl)
    if _pa:
        hl["key_signals"]["caveat"] = _pa
    # CONSOLIDATED statistical-vs-biological co-mutation confidence caveat + provenance quorum (VERDICT-INERT):
    # the co-mutation analog of mechanism's actionable-MoA / tumor-presence's presence_confirmation inflation
    # surface. Gates on the already-emitted cooccurrence_class / driver flags / panel-eligibility + the curated
    # (target, indication) TMB-confound / established / near-universal crosswalks; None on ns/data_unavailable
    # → byte-stable on the negative path (incl. the KRAS/FBXW7 replay fixtures: KRAS resolves the milder
    # established guard, FBXW7 strong_cooccurring gets no curated flag → a data tier or None; neither touches
    # the differentiation_verdict spine). Best-effort: a fault degrades to None + _enrichment_errors.
    try:
        hl["cooccurrence_confidence_caveat"] = _cooccurrence_confidence_caveat(hl, target=target, indication=indication)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["cooccurrence_confidence_caveat"] = f"{type(exc).__name__}: {exc}"
        hl["cooccurrence_confidence_caveat"] = None
    try:
        hl["cooccurrence_provenance"] = _cooccurrence_provenance(hl, target=target, indication=indication)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["cooccurrence_provenance"] = f"{type(exc).__name__}: {exc}"
        hl["cooccurrence_provenance"] = None
    # COHORT-level ≠ same-CELL / clonal co-occurrence (the (c) sub-inflation) — a pooled bulk Fisher pair is a
    # same-PATIENT association, not a same-clone co-driver; fires only on the co-occurring path, None otherwise
    # (target/indication-independent — applies to every pooled co-occurrence). Verdict-INERT, byte-stable spine.
    try:
        hl["clonality_caveat"] = _clonality_caveat(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["clonality_caveat"] = f"{type(exc).__name__}: {exc}"
        hl["clonality_caveat"] = None
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort: a formatting/read fault must NEVER discard the
    # differentiation spine already fully built in `hl` (mirrors the tumor-presence degrade-on-exception
    # discipline). On the happy path this is byte-identical (no _enrichment_errors key added), so the
    # golden-oracle + replay fixtures are unaffected.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — a verdict-INERT projection over the
    # just-built headline + claim_vector (COMUT/SURVIVAL/NODE + clinical/competitor precedent), giving
    # differentiation component-parity with the other skills. Best-effort: a fault degrades to None +
    # _enrichment_errors, never aborts the differentiation spine.
    try:
        hl["question_table"] = differentiation_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, from the
    # verdict + claim_vector + headline_block + question_table just built. differentiation-landscape is a
    # GATING skill (∈ target-profile _SHORT_TO_GATE) with a clean 3-band polarity and no veto-killer verdict
    # (a co-mutation/survival landscape raises no cross-target veto), so the helper's negative→opposing
    # floor is correct (no canonical_polarity_override). Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=hl.get("differentiation_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


_SYNTHESIS_FACET_KEYS = (
    "differentiation_verdict", "driving_rule_id", "cooccurrence_class",
    "survival_association_class", "precog_prognostic_class", "node_leverage_class",
    "highest_clinical_stage", "n_active_trials", "approved_agents", "notable_failures",
    # Open Targets competitor field (verdict-inert) — the substrate for the target-profile cross-ref:
    "competitor_class", "competitor_highest_stage", "competitor_indication_scope",
    "n_competitor_programs", "competitor_approved_agents", "competitor_late_stage_non_approved",
    "competitor_modalities_in_development", "competitor_modality_landscape",
    "claim_vector", "key_signals",
    # the CONSOLIDATED statistical-vs-biological co-mutation confidence caveat + provenance quorum
    # (verdict-INERT; the co-mutation analog of mechanism's actionable-MoA / tumor-presence's presence caveat):
    "cooccurrence_confidence_caveat", "cooccurrence_provenance", "cooccurrence_class_prefloor",
    # cohort-level ≠ same-cell/clonal co-occurrence (the (c) sub-inflation; verdict-inert, co-occurring path):
    "clonality_caveat",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 skill_report
    # adoption (6th gating adopter)
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair, target=None, indication=None):
    """Compact, VERDICT-INERT differentiation facet for the composed target-profile synthesis. Reuses
    _headline (single source) + returns the DESCRIPTIVE claim_vector (COMUT/SURVIVAL/PROGNOSIS/NODE) +
    its citable atoms. Never moves the verdict; safe to omit. target/indication are signature-introspected
    by the fan-out (tp_fanout) so the (target, indication)-keyed cooccurrence_confidence_caveat reaches the
    composed profile too."""
    h = _headline(cards, fired, verdict_pair, target=target, indication=indication)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic differentiation-landscape facet; claim_vector is a DESCRIPTIVE "
                            "decomposition (direction in the atoms). Verdict owned by the resolver.")
    return facet


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
        synthesize_fn=make_synthesize_fn(_LENS),
        # OPTIONAL verdict-INERT LLM --literature lane (BAKED 2026-09-04): Europe-PMC-grounded (default_retrieve
        # = Europe PMC → PubTator3 fallback) + PMID-verified (verify_citations); attached as
        # decision['literature_synthesis'] AFTER the deterministic decision is composed and fed to the
        # --synthesize narrator as a corroboration/contradiction lane. Query terms
        # (_LENS_QUERY_TERMS["differentiation-landscape"]) refined for the co-mutation / mutual-exclusivity /
        # TMB-MSI / patient-selection / combination trap. Spine byte-stable (the lane cannot touch the verdict).
        literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=emit_headline_hero,
        partial_status_note=PARTIAL_STATUS_NOTE,
        # Signals-first: tuned sub-group reader for the differentiation vocabulary. Verdict-INERT.
        subgroup_classify=make_value_classifier(_DIFFERENTIATION_VALUE_TIERS),
    ))
