#!/usr/bin/env python3
"""genomic-alteration-profile — how is a (target, indication) genomically altered?

Answers: "How is gene X altered in indication Y, and which alteration class drives —
SNV/indel (mutation), copy-number (amplification/deletion), or fusion/rearrangement?"
A gene is often a driver via DIFFERENT classes across indications (ERBB2 amplified in
breast/gastric vs mutated in a lung subset; MET exon14-skip + amplification), so this
skill reports the alteration MIX and names which class carries the signal, rather than
implying "not a driver" for an amplification- or fusion-driven target.

Structure:
  - A whole-cohort spine of CARDS drives the deterministic multi-class verdict, resolved
    by the shared declarative resolver (resolvers/genomic_alteration.resolver.yaml).
  - An optional, --subtypes-gated subtype panorama (SUBTYPE_CARDS) is DESCRIPTIVE only: it
    recomputes frequency within each stratum and never touches a resolver rung, so the
    verdict is byte-identical whether or not --subtypes is passed.
  - An optional --synthesize flag attaches an LLM narration as a sibling key; it can never
    alter the deterministic verdict.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

import yaml
from _skills_common import card_summary, resolve_cards
from _skills_common.card_preprocessors import (  # noqa: F401
    _bh_qvalues,
)

# The family-wise FDR across the stratified-dependency classes is single-sourced in
# _skills_common.card_preprocessors so all three resolution paths apply it identically:
# this skill's main(), the target-profile fan-out, and compose-dashboard's gate spine.
# apply_family_wise_fdr is used by main(); _bh_qvalues is re-exported for this skill's tests.
from _skills_common.card_preprocessors import (  # noqa: F401
    apply_family_wise_fdr as _apply_family_wise_fdr,
)
from _skills_common.card_preprocessors import (  # noqa: F401
    apply_promiscuous_amplicon_fusion_demotion as _apply_amplicon_fusion_demotion,
)
from _skills_common.claim_record import assemble_claim_record
from _skills_common.dispatcher import run_wired_skill
from _skills_common.genomic_claims import GENOMIC_CLAIM_SPEC, genomic_claim_vector, genomic_key_signals
from _skills_common.genomic_question_table import genomic_question_table
from _skills_common.literature_retrieval import default_retrieve, verify_citations

# OPTIONAL (--literature) verdict-INERT LLM literature lane, reusing the shared fleet module (the same
# make_literature_fn wired into tumor-presence #965 / tumor-selectivity #968). Passed to
# run_wired_skill as literature_fn, which attaches the lane after the spine (the shared dispatcher seam).
# Grounded in Europe PMC (PubTator3 fallback via default_retrieve; genomic-alteration lens query terms
# live in literature_retrieval._LENS_QUERY_TERMS) + PMID-verified via verify_citations. The lens's
# SNV/CN/FUS/DEP axis_labels match the genomic claim_vector, so the prompt is grounded on the right axes.
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_engine import narrate as _narrate
from _skills_common.narrator_lenses import GENOMIC_ALTERATION as _LENS
from _skills_common.paths import target_contracts_root
from _skills_common.resolver import resolve_or_raise
from _skills_common.subgroup_derivation import make_value_classifier, subgroup_signals_for

_LITERATURE_FN = make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations)

# ─── Signals-first sub-group reader (verdict-INERT) ──────────────────────────────────────────────
# _build_headline wires the fleet sub-group derivation itself (with this tuned classifier) rather than
# leaving it to run_wired_skill's generic post-headline wiring — so the subgroup_signals key keeps its
# in-headline position (the dispatcher's generic wiring then setdefault-no-ops on the already-set key).
# The fleet-default heuristic is lens-blind — it tags this lens's POSITIVE signals
# (direct_driver_gof, likely_oncogenic, predominantly_clonal, concordant_dependent, top_1pct recurrence)
# as `absent`. _GENOMIC_VALUE_TIERS states the tier for the alteration vocabulary (signal = strength of
# evidence that the target IS genomically altered / the class drives). default_classify is the fallback.
_GENOMIC_VALUE_TIERS = {
    # driver role / recurrence / oncogenicity / pathway
    "direct_driver_gof": "strong",
    "direct_driver_lof": "strong",
    "likely_driver": "moderate",
    "passenger": "absent",
    "no_established_role": "absent",
    "top_1pct": "strong",
    "top_5pct": "strong",
    "top_decile": "moderate",
    "recurrent": "strong",
    "frequently_altered": "strong",
    "occasionally_altered": "moderate",
    "rarely_altered": "weak",
    "likely_oncogenic": "strong",
    "oncogenic": "strong",
    "likely_benign": "absent",
    "benign": "absent",
    # mutation type / clonality / functional state
    "missense": "moderate",
    "truncating": "strong",
    "inframe": "moderate",
    "silent": "absent",
    "predominantly_clonal": "strong",
    "predominantly_subclonal": "moderate",
    "recurrent_biallelic_inactivation": "strong",
    "sporadic_biallelic_inactivation": "moderate",
    "mave_well_characterized": "strong",
    "mave_assayed": "moderate",
    "mave_unmapped_target": "absent",
    "not_assayed": "absent",
    "event_matched_dependent_in_lineage": "strong",
    "event_matched_dependent_off_lineage": "moderate",
    # mutation/CN/fusion-stratified dependency + drug response + cross-consortium
    "mutant_strongly_dependent": "strong",
    "mutant_moderately_dependent": "moderate",
    "mutant_strongly_drug_sensitive": "strong",
    "mutant_moderately_drug_sensitive": "moderate",
    "concordant_dependent": "strong",
    "own_mut_hotspot": "moderate",
    "broadly_neutral": "absent",
    "recurrently_amplified": "strong",
    "recurrently_deleted": "strong",
    "amplified_moderately_dependent": "moderate",
    "amplified_strongly_dependent": "strong",
    "amplified_overexpressed_moderately_dependent": "moderate",
    "amplified_overexpressed_strongly_dependent": "strong",
    "fusion_positive_moderately_dependent": "moderate",
    "fusion_positive_strongly_dependent": "strong",
    "no_recurrent_fusion": "absent",
    "tumor_shifted": "moderate",
    "no_splice_shift": "absent",
    # curated oncogenic exon-skip DRIVER (splice_exon_skip_class; METex14) — a positive splice signal
    "recurrent_splice_driver": "strong",
    "no_exon_skip": "absent",
}
from _skills_common.headline_core import HeadlineSpec, build_headline, build_synthesis_facet
from _skills_common.signals_first import (
    assemble_strength_certainty,
    coverage_band,
    weakest_link_level,
)
from _skills_common.skill_report import ROLE_GATING, build_skill_report

SKILL_NAME = "genomic-alteration-profile"
SKILL_VERSION = "2.21.0"
#        the fleet wiring) + tuned alteration value→tier map. Verdict-INERT.

# Whole-cohort cards read on every run. The verdict is driven by the resolver (see _verdict);
# cards tagged "verdict-driving" fire rules the resolver references, "signal-only" cards feed
# the headline / LLM / matrix but touch no resolver rung (the verdict spine stays byte-stable).
CARDS = [
    # ── SNV / indel ──────────────────────────────────────────────────────────
    "mutation-type-counts",  # verdict-driving: variant-class landscape (missense/truncating mix)
    "mutation-stratified-dependency",  # verdict-driving: are mutant cell lines more Chronos-dependent?
    "mutation-hotspot-frequency",  # verdict-driving (Phase 2): pooled top_1pct patient recurrence → recurrent_snv_driver
    # ── Copy number (amplification / deletion) ───────────────────────────────
    "copy-number-distribution",  # verdict-driving: focal amp/deletion recurrence
    "copy-number-stratified-dependency",  # verdict-driving: are AMPLIFIED lines more dependent? (ERBB2/MYC)
    "amp-expr-stratified-dependency",  # verdict-driving: amplified AND high-expression conjoint dependency
    # ── Fusion / rearrangement ───────────────────────────────────────────────
    "fusion-stratified-dependency",  # verdict-driving: are fusion-positive lines more dependent? (EWSR1-FLI1)
    "fusion-rearrangement-landscape",  # verdict-driving: recurrent TCGA fusion driver (tcga-fusion-consensus-v1)
    # ── Splice exon-skipping ─────────────────────────────────────────────────
    "splice-exon-skip-landscape",  # verdict-driving (CASE-002): curated exon-skip DRIVER (METex14) oncogenic
    # in-indication + live DepMap carriers → splice_exon_skip_driver rung
    # ── Genotype × drug response ─────────────────────────────────────────────
    "mutation-drug-response",  # verdict-driving (STRONG class only): mutant lines more drug-sensitive (PRISM)
    # ── Typed driver ROLE ────────────────────────────────────────────────────
    "alteration-role",  # verdict-driving: OncoKB × IntOGen GoF/LoF role → confirmed_driver rungs
    # ── Additive signal-only layers (feed the headline/LLM; touch no resolver rung) ──
    "functional-gene-state",  # biallelic two-hit / allele-count state (mutation + allele-specific CN)
    "genomic-event-model-match",  # which DepMap models carry the SAME event as the tumours, and are dependent
    "genomic-instability-state",  # indication-level aneuploidy / CIN / WGD / MSI cohort context (target-independent)
    "mutational-signature-context",  # indication-level mutagenic-process context (TCGA MC3 SBS signatures)
    "ddr-deficiency-context",  # indication-level DDR/HRD cohort context (frames the HRD-conditional axis)
    "oncogenic-pathway-alteration",  # indication-level oncogenic-pathway alteration frequency (Sanchez-Vega 2018)
    "driver-pathway-position",  # (SK#2314 P1, 2026-10-01) target+indication-conditioned POSITIONAL read — IN/UPSTREAM/
    # DOWNSTREAM of the indication's frequently-altered driver pathway (Sanchez-Vega per-gene membership x
    # per-indication alteration freq x SIGNOR directed edges). Surfaced alongside the oncogenic-pathway-
    # alteration facet; SOFT / VERDICT-INERT (fires no genomic rung → genomic verdict byte-stable). HOMED
    # in mechanism-and-pharmacology. Position, NOT desirability.
    "variant-level-interpretation",  # per-variant oncogenicity + therapy-resistance alleles (CIViC clinical interp)
    "variant-effect-mave-mavedb",  # per-variant MEASURED functional effect (MAVEdb DMS/SGE); orthogonal to CIViC (verdict-inert)
    "target-clonality",  # is the driver mutation truncal (durable) or subclonal (relapse-prone)?
    # ── Q4 KO-dependency CONFIDENCE annotations (additive, verdict-inert; fire NO genomic rung) ──
    "cross-consortium-dependency",  # Broad↔Sanger CRISPR agreement — is the dependency reproducible?
    "dependency-predictability",  # is the dependency omics-learnable, and is it lineage-collapsed?
    # (predictability_lineage_collapsed directly flags the pan-cancer-vs-
    # indication scope-leak the biomarker rungs are gated against)
    # ── SPLICE-form facet (1) — VERDICT-INERT display (2026-08-20) ─────────────────────
    # Aberrant splicing as a transcript-form alteration signal, homed alongside the SNV/CN/fusion
    # classes as a DISPLAY facet (fires NO rule → the multi-class genomic verdict spine is byte-stable;
    # graduating splice to a verdict-driving class is a later rules+resolver stage). TCGA SpliceSeq PSI
    # (indication-gated). (tumor-splice-expression was a duplicate of this card — same product/method/
    # fields/vocab, only card_id differed — and was collapsed into it, 2026-09-06.)
    "tumor-splice-dysregulation",  # splice-dysregulation event(s) at the target (PSI shift vs normal)
]

# The subtype panorama is DELIBERATELY kept off the CARDS spine. Its card is a panorama
# dispatcher that needs externally-resolved strata (subgroup_context.resolved_strata_ids) or
# it returns only a data-note — so it resolves on a separate, --subtypes-gated path (see
# _resolve_subtype_panorama). It is DESCRIPTIVE (per-stratum frequency), emits no verdict, and
# touches no resolver rung, so the whole-cohort verdict is byte-stable whether or not a subtype
# scope is passed.
SUBTYPE_CARDS = [
    "subgroup-stratified-mutation-frequency",  # SNV frequency by molecular subgroup
    "subgroup-stratified-copy-number",  # patient focal amp/del by subgroup (TCGA GISTIC per-sample)
    "subgroup-stratified-fusion",  # fusion recurrence by subgroup (usually underpowered per stratum)
]

# Per-axis subtype-panorama config: (card_id, headline_axis_key, cross-stratum delta field, display
# pattern key, delta threshold). The mutation axis keeps its original keys for backward-compatibility;
# the CN + fusion axes are the scope-coherence Phase 3 broadening (descriptive, verdict-inert).
_SUBTYPE_AXES = [
    (
        "subgroup-stratified-mutation-frequency",
        "subtype_axis",
        "cross_subgroup_delta_frequency",
        "subtype_mutation_pattern",
        0.10,
    ),
    (
        "subgroup-stratified-copy-number",
        "subtype_cn_axis",
        "cross_subgroup_delta_high_amp_fraction",
        "subtype_cn_pattern",
        0.10,
    ),
    (
        "subgroup-stratified-fusion",
        "subtype_fusion_axis",
        "cross_subgroup_delta_fusion_frequency",
        "subtype_fusion_pattern",
        0.05,
    ),
]

QUESTION = (
    "How is {target} genomically altered in {indication} — by SNV/indel "
    "(driver, biomarker-stratified dependency, or passenger), by copy-"
    "number (amplification/deletion), or a mix — and which class drives?"
)

# NOTE — numeric cutoffs have no card/rule home in this skill. The interpretation-rule layer is
# `equals`-only by design (a rule matches a card's categorical CLASS token, e.g.
# mutation_stratification_class == "strongly_dependent"; it carries no `min_n` / delta threshold a skill
# could consume). So every numeric cutoff this skill applies — the subtype-panorama delta (threaded per
# axis from _SUBTYPE_AXES) and the coverage-band floors (_COVERAGE_N_HIGH / _COVERAGE_N_MED below) — is a
# SKILL-OWNED policy declared at its use site, NOT read from a contract. The dead module-level
# _SUBTYPE_DELTA_THRESHOLD constant (never referenced; the live threshold rides _SUBTYPE_AXES) was removed.


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Multi-class genomic-alteration verdict, delegated to the shared declarative resolver.

    The verdict logic (SNV/indel priority × copy-number × fusion, precedence by effect
    strength then class) lives in resolvers/genomic_alteration.resolver.yaml (target-contracts),
    evaluated by the single interpreter every engine calls. A missing spec raises rather than
    falling back to a stale copy, so the two engines can never silently drift.
    """
    return resolve_or_raise(fired, "genomic_alteration")


# Per-alteration-class decomposition. The collapsed genomic_alteration verdict fuses SNV/indel,
# copy-number, and fusion into one multi_class scalar; this map reorganizes the ALREADY-computed
# per-card class fields into a first-class per-class breakdown (mirroring tumor-presence's
# presence_verdict_by_modality) so a consumer can see WHICH class carries the signal. It reuses
# fields already read for the headline and touches no resolver rung — the verdict stays byte-stable.
#   class -> (primary "verdict" field, {supporting_field_name: (card_id, field)})
_ALTERATION_CLASS_FIELDS: dict[str, tuple] = {
    "snv_indel": (
        ("mutation-type-counts", "mutation_landscape_class"),
        {
            "recurrence_class": ("mutation-hotspot-frequency", "driver_recurrence_class"),
            "stratified_dependency_class": ("mutation-stratified-dependency", "mutation_stratification_class"),
        },
    ),
    "copy_number": (
        ("copy-number-distribution", "copy_number_class"),
        {
            "patient_class": ("copy-number-distribution", "patient_copy_number_class"),
            "stratified_dependency_class": ("copy-number-stratified-dependency", "cn_stratification_class"),
            "amp_expr_dependency_class": ("amp-expr-stratified-dependency", "amp_expr_stratification_class"),
        },
    ),
    "fusion": (
        ("fusion-rearrangement-landscape", "fusion_class"),
        {
            "stratified_dependency_class": ("fusion-stratified-dependency", "fusion_stratification_class"),
            # VERDICT-INERT confound flag: on a fusion-positive-dependent call, is the fusion+ set MAJORITY
            # target-altered (mutation ∪ focal amp)? → the dependency may be the alteration's, not the fusion's
            # (KRAS/COADREAD alteration_confounded, 8/13). Surfaced so "which class drives" carries the caveat.
            "stratified_dependency_confound": ("fusion-stratified-dependency", "fusion_stratification_confound"),
            "genie_sv_recurrence_class": ("fusion-rearrangement-landscape", "genie_sv_recurrence_class"),
        },
    ),
    # SPLICE exon-skipping — the fourth alteration class, graduated to VERDICT-DRIVING in v2.13.0
    # (CASE-002, splice_exon_skip_driver rung §3b) but historically absent from this decomposition.
    # A curated oncogenic exon-skip DRIVER (splice_exon_skip_class==recurrent_splice_driver, e.g. METex14)
    # oncogenic in-indication + live DepMap carrier confirmation. Added so the "which class drives"
    # breakdown NAMES the splice class when it is the driver (was previously invisible → the decomposition
    # showed only SNV/CN/fusion for a splice_exon_skip_driver verdict).
    "splice": (
        ("splice-exon-skip-landscape", "splice_exon_skip_class"),
        {
            "event_id": ("splice-exon-skip-landscape", "event_id"),
            "driver_direction": ("splice-exon-skip-landscape", "driver_direction"),
            "n_depmap_carriers": ("splice-exon-skip-landscape", "n_depmap_carriers"),
        },
    ),
}


def _genomic_alteration_by_class(cards: list[dict]) -> dict:
    """Per-alteration-class breakdown: {class: {verdict, evidence_state, <supporting fields>}}.

    `verdict` is that class's OWN primary card call (SNV landscape / CN distribution / fusion
    recurrence) — not re-derived, so it cannot drift from the cards. `evidence_state` is
    `measured` when the primary field resolved, else `data_unavailable` (a NAMED gap, never a
    fabricated negative).

    Unlike the headline lifts, an absent card_id falls back to None (a named data_unavailable gap)
    rather than raising — the by-class map is tolerant of a card that did not resolve this run.
    """
    card_by_id = {c.get("card_id"): c for c in (cards or [])}

    def _field(card_id, field):
        card = card_by_id.get(card_id)
        return (card.get("summary") or {}).get(field) if card is not None else None

    out: dict[str, dict] = {}
    for cls, (primary, supporting) in _ALTERATION_CLASS_FIELDS.items():
        pval = _field(*primary)
        entry = {
            "verdict": pval,
            "evidence_state": "data_unavailable" if pval in (None, "data_unavailable") else "measured",
        }
        for name, (card_id, field) in supporting.items():
            entry[name] = _field(card_id, field)
        out[cls] = entry
    return out


# ── Scope decomposition (pan-cancer / indication / subtype) ──────────────────────────────────────
# The genomic_alteration verdict is a SCOPE HYBRID: the ladder-LEADING KO-dependency, variant-class
# shape, and drug-response signals are pan-cancer DepMap/PRISM cell-line calls (localised to the queried
# lineage only when powered, via each stratified card's `evidence_scope`), while patient recurrence,
# patient-focal CN, TCGA fusion recurrence, and the IntOGen driver role are indication-native. The
# one-word verdict never says at what scope it was earned; `genomic_alteration_by_class` re-expands the
# alteration CLASS but not the SCOPE. This reducer classifies the SCOPE of the DRIVING verdict and rolls
# up which evidence exists at each scope — ADDITIVE / verdict-inert (mirrors _genomic_alteration_by_class;
# the functional-requirement dependency_verdict_by_scope analog). It reads fields already emitted by the
# cards and touches no resolver rung, so the verdict spine stays byte-stable.
#   driving_rule prefix -> the stratified-dependency card whose `evidence_scope` localises that rung.
_DEP_RULE_SCOPE_CARD: dict[str, str] = {
    "mutant-": "mutation-stratified-dependency",
    "cn-amplified-": "copy-number-stratified-dependency",
    "fusion-positive-": "fusion-stratified-dependency",
    "amp-expr-": "amp-expr-stratified-dependency",
}
# `evidence_scope` values meaning the dependency was localised to the queried indication's lineage.
_INDICATION_EVIDENCE_SCOPES = {"within_indication", "within_indication_mut_vs_pan_wt"}
_PAN_EVIDENCE_SCOPES = {"pan_lineage_evidence_only", "pan_no_indication"}
# driving_rule ids whose signal is inherently indication-native (patient tissue) ...
_INDICATION_ANCHORED_RULES = {
    "cn-patient-focal-amplified-supportive",
    "cn-patient-focal-deleted-supportive",
    "fusion-landscape-recurrent-driver-supportive",
    "snv-recurrence-top-driver-supportive",  # Phase 2 (pooled patient recurrence) — forward-compat
    # A curated exon-skip DRIVER (METex14, resolver §3b / v2.13.0) is oncogenic in its CURATED indication
    # (indication-native, patient-tissue anchored), so its rung classifies as indication_anchored — not the
    # `unclassified` the scope map returned before the splice rung was added here. Verdict-inert (scope
    # decomposition never feeds a resolver rung). Surfaced by the MET/LUAD validation pass.
    "splice-exon-skip-driver-supportive",
    # `target-clonality` is `tier: indication` and asks "In {indication.label}, is the driver mutation
    # CLONAL or SUBCLONAL?" — patient-tissue read WITHIN the queried indication, so an OPPOSING rung is
    # indication-anchored just as the supportive ones are. Scope is a property of the evidence SOURCE, not
    # of the rung's polarity; classifying it by the card is what makes an opposing verdict's scope legible.
    "snv-clonality-subclonal-opposing",
}
# Driving rules for which NO scope is classifiable because no evidence was read: the rung fired precisely
# BECAUSE the measurement was unavailable. These are separated from `unclassified` (= a rule this map has
# not been taught) so the two cannot be confused: one is an honest absence, the other is map drift.
_NO_EVIDENCE_RULES = {
    "cn-data-unavailable-insufficient",
    # `underpowered` sibling of the above: the fusion axis WAS looked at but fewer than the recurrence
    # power floor cleared (PR-C2 gap-with-intent tier, contracts resolver underpowered), so the rung
    # fired on an axis that could not be powered — no evidence whose scope could be read, same as a
    # could-not-look. `_measured()` already folds `underpowered` in with `data_unavailable`, so scope
    # is `not_applicable` here for the identical reason. Added with the TC #873 pin bump.
    "fusion-underpowered-insufficient",
}
# ... vs pan-cancer cell-line landscape / variant-shape / pharmacology rungs.
_PAN_CANCER_RULES = {
    "cn-recurrently-amplified-supportive",
    "cn-recurrently-deleted-supportive",
    # SPECIFICITY IS NOT SCOPE. Contracts resolver 1.10.0 (#739) retired the shallow
    # cn-recurrently-deleted-supportive from every driver-ESTABLISHING rung and keyed them on this
    # biallelic predicate instead, because the shallow one fires for 60.1% of genes genome-wide and
    # this one for 1.5%. But both read the SAME card field family off the SAME source — the rule's own
    # rationale says "across the cell-line panel (relative CN < 0.5 in >=20% of lines)" — so a verdict
    # this rung drives is STILL a pan_cancer_extrapolation, not an indication-anchored call. Only the
    # GISTIC per-sample cn-patient-focal-deleted-supportive above is indication-native. Tempting to
    # read a sharper predicate as a better-localised one; it is not, and mapping it to
    # indication_anchored would have published a pan-cancer cell-line read as indication evidence.
    "cn-recurrent-homozygous-deletion-supportive",
    "mutation-drug-response-strongly-sensitive-supportive",
    "mut-lof-dominant-supportive",
    "mut-missense-dominant-supportive",
    # All four `mut-*` rungs read the SAME card — `mutation-type-counts`, whose question begins "Across
    # DepMap cell lines" — so all four are pan-cancer cell-line reads. Only the two supportive tiers were
    # mapped, which left the neutral tiers of one card scoped differently from its supportive tiers: a
    # `mixed_pattern` / `passenger_pattern` verdict read `unclassified` while `lof_dominant` off the same
    # field read `pan_cancer_extrapolation`. These two complete the card.
    "mut-mixed-neutral",
    "mut-no-mutations-neutral",
}


def _scope_of_driving_verdict(card_by_id: dict, driving_rule: str | None) -> str:
    """Classify the SCOPE at which the deterministic verdict was earned, from `driving_rule_id` + the
    driving card's own scope field. One of:
      - `indication_anchored`      — driving signal is within the queried indication's lineage/tissue
      - `pan_cancer_extrapolation` — driving signal is a pan-cancer/pan-lineage cell-line call
      - `mixed`                    — pan-cancer driving signal WITH indication-native corroboration
      - `not_applicable`           — no scope is classifiable: either no verdict fired, or the rung fired
                                     BECAUSE the measurement was unavailable (`_NO_EVIDENCE_RULES`), so
                                     there is no evidence whose scope could be read
      - `unclassified`             — NOT merely defensive; two reachable causes, deliberately not split
                                     because both mean "the scope could not be determined":
                                     (a) map DRIFT — the resolver named a driving rule this map has never
                                         learned. `test_every_resolver_driving_rule_is_scoped` reads the
                                         driving rules from the resolver and fails the moment that
                                         happens, so (a) should not survive to a published run.
                                     (b) a mapped DEPENDENCY rung whose stratified card is absent, or
                                         carries an `evidence_scope` outside the two known sets — the rung
                                         fired, so evidence exists, but it cannot be localised.
    A dependency rung reads its card's `evidence_scope`; landscape/shape/pharmacology rungs are statically
    indication-native vs pan-cancer, taken from the SOURCE CARD rather than the rung's polarity — so every
    tier of one card scopes the same way. Verdict-inert (never feeds a resolver rung)."""
    if not driving_rule or driving_rule in _NO_EVIDENCE_RULES:
        return "not_applicable"

    def _f(card_id, field):
        return (card_by_id.get(card_id, {}).get("summary") or {}).get(field)

    def _indication_native_support() -> bool:
        return (
            _f("alteration-role", "intogen_scope") == "indication"
            or _f("mutation-hotspot-frequency", "driver_recurrence_class") in ("top_1pct", "top_decile")
            or _f("copy-number-distribution", "patient_focal_cn_class")
            in ("recurrent_focal_amplification", "recurrent_focal_deletion")
            or _f("fusion-rearrangement-landscape", "fusion_class") == "recurrent_fusion_driver"
        )

    for prefix, card_id in _DEP_RULE_SCOPE_CARD.items():
        if driving_rule.startswith(prefix):
            scope = _f(card_id, "evidence_scope")
            if scope in _INDICATION_EVIDENCE_SCOPES:
                return "indication_anchored"
            if scope in _PAN_EVIDENCE_SCOPES:
                return "mixed" if _indication_native_support() else "pan_cancer_extrapolation"
            return "unclassified"
    if driving_rule in _INDICATION_ANCHORED_RULES:
        return "indication_anchored"
    if driving_rule in _PAN_CANCER_RULES:
        return "mixed" if _indication_native_support() else "pan_cancer_extrapolation"
    return "unclassified"


def _genomic_alteration_by_scope(cards: list[dict], driving_rule: str | None) -> dict:
    """Per-SCOPE breakdown: `{scope_of_driving_verdict, pan_cancer, indication, subtype}`.

    `scope_of_driving_verdict` is the load-bearing scalar (see _scope_of_driving_verdict). Each scope
    block lists the evidence that exists AT that scope plus an `evidence_present` flag, so a consumer can
    see indication-native corroboration even when a pan-cancer signal drove the verdict. The `subtype`
    block is a placeholder unless --subtypes was passed (main() patches it in); the whole-cohort spine is
    never subtype-scoped, so leaving it empty keeps the verdict byte-stable. Additive / verdict-inert."""
    card_by_id = {c.get("card_id"): c for c in (cards or [])}

    def f(card_id, field):
        return (card_by_id.get(card_id, {}).get("summary") or {}).get(field)

    def _measured(v):
        # A coverage GAP is not a measurement. `data_unavailable` = could-not-look;
        # `underpowered` = looked-but-too-thin (below the classifier's recurrence power floor,
        # PR-C2). Both must read as NO evidence at this scope, else evidence_present falsely
        # asserts "evidence exists here" off an axis that could not be powered.
        return v not in (None, "", "data_unavailable", "underpowered")

    # PAN-CANCER (DepMap/PRISM cell-line) — the ladder-leading dependency + variant-shape + drug-response,
    # each dependency carrying its own indication-localisation scope.
    pan = {
        "mutation_landscape_class": f("mutation-type-counts", "mutation_landscape_class"),
        "copy_number_class": f("copy-number-distribution", "copy_number_class"),
        "mutation_dependency_class": f("mutation-stratified-dependency", "mutation_stratification_class"),
        "mutation_dependency_scope": f("mutation-stratified-dependency", "evidence_scope"),
        "cn_dependency_class": f("copy-number-stratified-dependency", "cn_stratification_class"),
        "cn_dependency_scope": f("copy-number-stratified-dependency", "evidence_scope"),
        "fusion_dependency_class": f("fusion-stratified-dependency", "fusion_stratification_class"),
        "fusion_dependency_scope": f("fusion-stratified-dependency", "evidence_scope"),
        "amp_expr_dependency_class": f("amp-expr-stratified-dependency", "amp_expr_stratification_class"),
        "amp_expr_dependency_scope": f("amp-expr-stratified-dependency", "evidence_scope"),
        "drug_response_class": f("mutation-drug-response", "drug_response_stratification_class"),
    }
    _pan_signal = (
        "mutation_landscape_class",
        "copy_number_class",
        "mutation_dependency_class",
        "cn_dependency_class",
        "fusion_dependency_class",
        "amp_expr_dependency_class",
        "drug_response_class",
    )
    # INDICATION (patient tissue) — recurrence, patient-focal CN, TCGA fusion, IntOGen role, clonality.
    ind = {
        "pooled_driver_recurrence_class": f("mutation-hotspot-frequency", "pooled_driver_recurrence_class"),
        "driver_recurrence_class": f("mutation-hotspot-frequency", "driver_recurrence_class"),
        "genie_driver_recurrence_class": f("mutation-hotspot-frequency", "genie_driver_recurrence_class"),
        "patient_focal_cn_class": f("copy-number-distribution", "patient_focal_cn_class"),
        "fusion_class": f("fusion-rearrangement-landscape", "fusion_class"),
        "alteration_role": f("alteration-role", "alteration_role"),
        "intogen_scope": f("alteration-role", "intogen_scope"),
        "clonality_class": f("target-clonality", "clonality_class"),
    }
    _ind_signal = (
        "pooled_driver_recurrence_class",
        "driver_recurrence_class",
        "genie_driver_recurrence_class",
        "patient_focal_cn_class",
        "fusion_class",
        "alteration_role",
    )
    return {
        "scope_of_driving_verdict": _scope_of_driving_verdict(card_by_id, driving_rule),
        "pan_cancer": {"evidence_present": any(_measured(pan[k]) for k in _pan_signal), **pan},
        "indication": {"evidence_present": any(_measured(ind[k]) for k in _ind_signal), **ind},
        # subtype: patched by main() only when --subtypes is passed (byte-stable otherwise).
        "subtype": {"evidence_present": False, "note": "pass --subtypes to populate the subtype panorama"},
    }


# Headline field table: (headline_key, card_id, summary_field). Every entry is a plain lift of a
# card summary field via _lift_field; keeping them declarative removes ~40 near-identical call
# sites and makes the mutation / copy-number / fusion / role / cohort-context axes scannable at a
# glance. All CARDS are always present in the resolved list, so no lookup here can raise.
_HEADLINE_FIELDS: list[tuple[str, str, str]] = [
    # ── SNV / indel axis ─────────────────────────────────────────────────────
    ("mutation_landscape_class", "mutation-type-counts", "mutation_landscape_class"),
    ("mutation_stratification_class", "mutation-stratified-dependency", "mutation_stratification_class"),
    # Scope at which the stratified-dependency call was made (within-indication vs a pan-cancer
    # extrapolation), plus flags for a within-vs-pan disagreement and a pan-fallback strong→moderate cap.
    ("stratified_evidence_scope", "mutation-stratified-dependency", "evidence_scope"),
    ("stratified_lineage_context_divergent", "mutation-stratified-dependency", "lineage_context_divergent"),
    ("stratified_pan_fallback_capped", "mutation-stratified-dependency", "pan_fallback_strong_capped_to_moderate"),
    # Pharmacological biomarker: genotype → on-target drug response (PRISM), complementing the CRISPR-KO
    # stratified dependency above.
    ("drug_response_stratification_class", "mutation-drug-response", "drug_response_stratification_class"),
    ("drug_response_delta_log2auc", "mutation-drug-response", "delta_log2auc_mut_vs_wt"),
    ("drug_response_n_on_target_compounds", "mutation-drug-response", "n_on_target_compounds"),
    # Recurrence frequency + driver-recurrence percentile, from both WES (TCGA-MC3) and panel (GENIE).
    ("overall_mutation_frequency", "mutation-hotspot-frequency", "overall_mutation_frequency"),
    ("driver_recurrence_class", "mutation-hotspot-frequency", "driver_recurrence_class"),
    ("driver_recurrence_percentile", "mutation-hotspot-frequency", "driver_recurrence_percentile"),
    ("genie_driver_recurrence_class", "mutation-hotspot-frequency", "genie_driver_recurrence_class"),
    ("genie_mutation_frequency", "mutation-hotspot-frequency", "genie_mutation_frequency"),
    # POOLED multi-cohort recurrence (scope-coherence Phase 2) — VERDICT-DRIVING: top_1pct fires the
    # recurrent_snv_driver rung. TCGA-MC3 + GENIE + MSK-CHORD, summed-counts/summed-coverage.
    ("pooled_driver_recurrence_class", "mutation-hotspot-frequency", "pooled_driver_recurrence_class"),
    ("pooled_driver_recurrence_percentile", "mutation-hotspot-frequency", "pooled_driver_recurrence_percentile"),
    ("pooled_mutation_frequency", "mutation-hotspot-frequency", "pooled_mutation_frequency"),
    ("pooled_recurrence_cohorts", "mutation-hotspot-frequency", "cohorts_contributing"),
    # ── Copy-number axis (cell-line verdict-driving + patient-tumour cross-check) ──
    ("copy_number_class", "copy-number-distribution", "copy_number_class"),
    ("patient_copy_number_class", "copy-number-distribution", "patient_copy_number_class"),
    # Patient-tumour FOCAL CN (indication-native; the verdict-bearing +2/homdel gate, distinct from the
    # display-only any-gain patient_copy_number_class) — surfaced for genomic_alteration_by_scope.indication.
    ("patient_focal_cn_class", "copy-number-distribution", "patient_focal_cn_class"),
    ("cn_stratification_class", "copy-number-stratified-dependency", "cn_stratification_class"),
    # Indication-localisation scope of each stratified-dependency sibling (mutation's is surfaced above as
    # stratified_evidence_scope) — the substrate for genomic_alteration_by_scope.scope_of_driving_verdict.
    ("cn_stratified_evidence_scope", "copy-number-stratified-dependency", "evidence_scope"),
    ("fusion_stratification_class", "fusion-stratified-dependency", "fusion_stratification_class"),
    ("fusion_stratified_evidence_scope", "fusion-stratified-dependency", "evidence_scope"),
    ("amp_expr_stratification_class", "amp-expr-stratified-dependency", "amp_expr_stratification_class"),
    ("amp_expr_stratified_evidence_scope", "amp-expr-stratified-dependency", "evidence_scope"),
    # ── Fusion / rearrangement axis (TCGA consensus verdict + GENIE-SV breadth facet) ──
    ("fusion_class", "fusion-rearrangement-landscape", "fusion_class"),
    # Verdict-inert confidence tier on a recurrent_fusion_driver call: high_recurrent_partner (a
    # recurrent partner — reliable) vs moderate_promiscuous (target recurs, no recurrent partner — a
    # mixed bucket that also catches amplicon-artifact SVs at amplified oncogenes). Does not move the verdict.
    ("fusion_recurrence_confidence", "fusion-rearrangement-landscape", "fusion_recurrence_confidence"),
    ("genie_sv_recurrence_class", "fusion-rearrangement-landscape", "genie_sv_recurrence_class"),
    ("genie_sv_frequency", "fusion-rearrangement-landscape", "genie_sv_frequency"),
    ("genie_sv_recurrent_partners", "fusion-rearrangement-landscape", "genie_sv_recurrent_partners"),
    # ── Splice exon-skipping axis (verdict-driving as of v2.13.0; now also surfaced in by_class/claim_vector) ──
    ("splice_exon_skip_class", "splice-exon-skip-landscape", "splice_exon_skip_class"),
    ("splice_event_id", "splice-exon-skip-landscape", "event_id"),
    ("splice_n_depmap_carriers", "splice-exon-skip-landscape", "n_depmap_carriers"),
    # ── Typed driver role (OncoKB × IntOGen) ─────────────────────────────────
    ("alteration_role", "alteration-role", "alteration_role"),
    ("functional_direction", "alteration-role", "functional_direction"),
    # IntOGen driver-call scope: indication (per-cancer-type) vs pan_cancer fallback — the indication
    # anchor for genomic_alteration_by_scope (a pan_cancer role is a weaker in-indication claim).
    ("intogen_scope", "alteration-role", "intogen_scope"),
    # ── Additive signal-only axes ────────────────────────────────────────────
    ("functional_state_class", "functional-gene-state", "functional_state_class"),
    ("clonality_class", "target-clonality", "clonality_class"),
    ("clonal_fraction", "target-clonality", "clonal_fraction"),
    # `n_mutant_samples` was lifted here but read by no surface (no genomic claim carries a clonality
    # denominator, and `clonal_fraction` — the salience effect field — already carries the clonality
    # read). Dropped as a dead lift (#1767 field hygiene) rather than folded into a surface it has none.
    ("event_correspondence_class", "genomic-event-model-match", "event_correspondence_class"),
    # ── Indication-level cohort context (target-independent) ─────────────────
    ("aneuploidy_burden_class", "genomic-instability-state", "aneuploidy_burden_class"),
    ("wgd_class", "genomic-instability-state", "wgd_class"),
    ("msi_class", "genomic-instability-state", "msi_class"),  # patient MSI (CRC+STAD)
    ("model_msi_class", "genomic-instability-state", "model_msi_class"),  # model MSI (all lineages)
    ("ddr_context_class", "ddr-deficiency-context", "ddr_context_class"),
    ("frac_hrd_high", "ddr-deficiency-context", "frac_hrd_high"),
    ("dominant_mutational_process", "mutational-signature-context", "dominant_process"),  # patient SBS
    ("enriched_mutational_processes", "mutational-signature-context", "enriched_processes"),
    ("model_mmr_signature_class", "genomic-instability-state", "model_mmr_signature_class"),
    (
        "oncogenic_pathway_class",
        "oncogenic-pathway-alteration",
        "oncogenic_pathway_class",
    ),  # indication pathway-alteration context (Sanchez-Vega 2018)
    (
        "target_pathway_alteration",
        "oncogenic-pathway-alteration",
        "target_pathway_alteration",
    ),  # the target's OWN pathway alteration frequency/class
    # ── Per-variant interpretation (CIViC) ───────────────────────────────────
    ("civic_variant_class", "variant-level-interpretation", "civic_variant_class"),
    ("civic_oncogenic_variants", "variant-level-interpretation", "oncogenic_variants"),
    ("civic_resistance_variants", "variant-level-interpretation", "resistance_variants"),
    # ── Per-variant MEASURED functional effect (MAVEdb DMS/SGE; verdict-inert) ─
    ("mave_evidence_class", "variant-effect-mave-mavedb", "mave_evidence_class"),
    ("mave_n_score_sets", "variant-effect-mave-mavedb", "n_score_sets"),
    ("mave_score_median", "variant-effect-mave-mavedb", "score_median"),
    # ── Q4 dependency CONFIDENCE (additive, verdict-inert) ────────────────────
    ("cross_consortium_class", "cross-consortium-dependency", "cross_consortium_class"),
    ("dependency_predictability_class", "dependency-predictability", "predictability_class"),
    ("dependency_predictability_feature", "dependency-predictability", "pred_dominant_feature_class"),
]


def _panorama_axis(card: dict | None, delta_field: str, pattern_key: str, threshold: float) -> dict:
    """Compact DISPLAY projection of one subtype-panorama card, mirroring the card's own thresholds.
    Never a verdict; touches no resolver rung. `delta_field` is the card's own cross-stratum reducer
    scalar (frequency / high_amp_fraction / fusion_frequency).

    POWER HONESTY — the "cannot contrast" outcome is split into two DISTINCT facts the previous single
    `not_informative` conflated:
      subgroup_specific_pattern / uniform_across_subgroups — >=2 strata cleared the n-floor
        (evidence_state == "measured") AND a delta was computed: a real cross-subgroup call.
      underpowered — strata WERE evaluated but fewer than 2 cleared the n-floor (or no delta was
        computable from those that did): we looked, the arms are too thin to contrast. This is a
        measured limitation, NOT an absence of anything to compare.
      not_informative — NOTHING was evaluated on this axis (no per-stratum records / card missing):
        a could-not-look, distinct from the underpowered "looked-but-too-thin".
    """
    summary = (card or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"]
    delta = summary.get(delta_field)
    if len(measured) >= 2 and delta is not None:
        pattern = "subgroup_specific_pattern" if delta >= threshold else "uniform_across_subgroups"
    elif per_subgroup:  # strata were evaluated but cannot power a cross-subgroup contrast
        pattern = "underpowered"
    else:  # nothing on this axis was evaluated — no contrast to attempt
        pattern = "not_informative"
    label = delta_field.replace("cross_subgroup_delta_", "")  # e.g. frequency / high_amp_fraction
    return {
        pattern_key: pattern,  # display-only flavor, NOT a verdict
        "n_subgroups_with_data": summary.get("n_subgroups_with_data"),
        f"max_subgroup_{label}": summary.get(f"max_subgroup_{label}"),
        f"min_subgroup_{label}": summary.get(f"min_subgroup_{label}"),
        delta_field: delta,
        "measured_strata": [r.get("stratum") for r in measured],
        "_missing": bool(card is None or card.get("_missing")),
        "_missing_reason": (card or {}).get("_missing_reason"),
    }


def _resolve_subtype_panorama(target: str, indication: str, subtypes: list[str]) -> dict:
    """DESCRIPTIVE subtype panoramas — resolve the three subgroup-stratified cards (SNV frequency,
    copy-number, fusion) across the requested strata. Each card is a panorama dispatcher that needs
    subgroup_context.resolved_strata_ids threaded (which is why they are off the whole-cohort CARDS
    list). Returns one compact per-axis projection per card for the headline — never a verdict, and
    none touches a resolver rung, so the whole-cohort verdict spine is byte-stable whether or not
    --subtypes is passed. The SNV axis keeps its original `subtype_axis` keys (backward-compatible);
    CN + fusion are the Phase 3 broadening.
    """
    subgroup_context = {"resolved_strata_ids": list(subtypes), "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication, subgroup_context=subgroup_context)
    by_id = {c["card_id"]: c for c in sub_cards}
    out: dict = {"cards": sub_cards, "scope_subtypes": list(subtypes), "axes": {}}
    for card_id, axis_key, delta_field, pattern_key, threshold in _SUBTYPE_AXES:
        out["axes"][axis_key] = _panorama_axis(by_id.get(card_id), delta_field, pattern_key, threshold)
    return out


def _lift_field(card_by_id: dict, card_id: str, field: str):
    """Prebuilt-index equivalent of get_card_field: same raise-on-unknown-card_id typo-guard and
    `summary.get(field)` semantics, but reuses one index so _build_headline does ~50 lifts against
    a single dict instead of rebuilding it per call. All _HEADLINE_FIELDS cards are always present."""
    if card_id not in card_by_id:
        raise KeyError(
            f"_lift_field: card_id {card_id!r} not found "
            f"(available: {sorted(card_by_id)}). Check for a typo in the caller."
        )
    return (card_by_id[card_id].get("summary") or {}).get(field)


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# The genomic declaration for the shared headline_core builder: the SNV/CN/FUS/DEP claim axes (the
# fourth concrete claim_vector_core instance — see _skills_common/genomic_claims.py), the multi-class
# genomic_alteration verdict vocabulary → human phrase, and the scope-leak (`pan_cancer_extrapolation`)
# as the skill-specific cross-class tension source. Verdict-INERT — a one-way projection over the
# already-computed headline (the genomic_alteration_profile spine stays byte-stable).
# The genomic_alteration verdict vocabulary (resolvers/genomic_alteration.resolver.yaml, target-contracts)
# → human phrase. Positives = the driver / dependency / recurrent-landscape rungs; negatives =
# passenger_pattern; the rest (mixed_pattern, insufficient) are neutral (gap / inconclusive).
_GENOMIC_VERDICT_PHRASE = {
    # biomarker-stratified dependency (the actionability "so what")
    "biomarker_stratified_dependency": "Biomarker-stratified genetic dependency",
    "moderate_biomarker_dependency": "Moderate biomarker-stratified dependency",
    # driver calls
    "multi_class_driver": "Multi-class alteration driver",
    "confirmed_driver": "Confirmed driver",
    # LoF/tumor-suppressor drivers — a REAL driver alteration, but role-honest: not an
    # inhibitor/degrader green-light (you cannot drug a lost function). Neutral polarity.
    "multi_class_lof_driver": "Multi-class loss-of-function (tumor-suppressor) driver",
    "confirmed_lof_driver": "Confirmed loss-of-function (tumor-suppressor) driver",
    "drug_response_biomarker": "Drug-response biomarker",
    # recurrent landscape drivers
    "recurrent_amplification_driver": "Recurrent amplification driver",
    "recurrent_deletion_driver": "Recurrent deletion driver",
    "recurrent_fusion_driver": "Recurrent fusion driver",
    "recurrent_snv_driver": "Recurrent SNV/indel driver",
    "recurrent_snv_subclonal_uncertain": "Recurrent SNV — subclonal, uncertain driver",
    "splice_exon_skip_driver": "Splice exon-skipping driver (e.g. METex14)",
    # variant-class spectrum shape
    "lof_dominant_pattern": "LoF-dominant mutation pattern",
    "missense_dominant_pattern": "Missense-dominant mutation pattern",
    # measured negative
    "passenger_pattern": "Passenger (not a recurrent driver)",
    # Phase-3 reconciled caveat token (emitted genomic_alteration_profile when the raw dependency-family
    # word disagrees with the KO-dependency confidence cards) — see reconcile_genomic_verdict. NEUTRAL
    # polarity: the alteration is a real driver (see genomic_alteration_by_class), but the claimed
    # biomarker-stratified genetic dependency is not corroborated.
    "biomarker_dependency_unconfirmed": "Biomarker dependency unconfirmed (orthogonal KO-dependency evidence contradicts)",
    # gaps / inconclusive
    "mixed_pattern": "Mixed alteration pattern",
    "insufficient": "Insufficient evidence",
}

# The verdict tokens that are a POSITIVE alteration call (a driver / dependency / recurrent-landscape
# rung). passenger_pattern is the measured NEGATIVE; mixed_pattern + insufficient (+ anything unknown)
# are NEUTRAL. Sourced from the genomic_alteration resolver vocabulary so the polarity can't drift.
# NOTE (2026-08-24, PR-2a residual): lof_dominant_pattern / missense_dominant_pattern are mutation-SHAPE
# descriptors that fire ONLY when the alteration ROLE is unresolved (data_unavailable/passenger — a typed
# GoF/LoF role routes to confirmed_driver/confirmed_lof_driver instead). A shape-without-a-confirmed-role
# is NOT a positive driver call (it read oncogene-flavored 'positive' for CD47/TNKS), so they are NEUTRAL.
_GENOMIC_POSITIVE_VERDICTS = frozenset(
    {
        "biomarker_stratified_dependency",
        "moderate_biomarker_dependency",
        "multi_class_driver",
        "confirmed_driver",
        "drug_response_biomarker",
        "recurrent_amplification_driver",
        "recurrent_deletion_driver",
        "recurrent_fusion_driver",
        "recurrent_snv_driver",
        "splice_exon_skip_driver",  # curated oncogenic exon-skip driver (METex14, GoF) — a positive driver call
    }
)
_GENOMIC_NEGATIVE_VERDICTS = frozenset({"passenger_pattern"})


def _genomic_verdict_polarity(v) -> str:
    """The skill's OWN reading of the collapsed multi-class verdict (colours the hero badge; never a
    gate). Genomic reports an alteration MIX — this is the polarity of the DOMINANT call. Reuses the
    resolver vocabulary so the polarity can't drift from the spine."""
    if v in _GENOMIC_POSITIVE_VERDICTS:
        return "positive"
    if v in _GENOMIC_NEGATIVE_VERDICTS:
        return "negative"
    return "neutral"


# ── EMITTED-verdict reconciliation with the signal package (surgical demotion) ─────────────────────
# The raw resolver ladder collapse (`_verdict` → resolvers/genomic_alteration.resolver.yaml) is
# UNTOUCHED — its golden spine stays byte-stable and it is what the composed target-profile GATE reads
# (tp_fanout stores the RAW resolve_verdict_for_gate output in sub_results; genomic_alteration IS in
# _SHORT_TO_GATE, so the nomination spine + the tp_gates GoF co-condition keep the raw call). But the
# ONE WORD a human/LLM reads (headline["genomic_alteration_profile"] + headline_block + key_signals +
# question_table + the narrator's collapsed-verdict line via verdict_key) is reconciled here against the
# already-computed decomposition so it can no longer OVER-READ the signal package. The raw word is
# retained as `genomic_alteration_profile_ladder` for traceability. Mirrors tumor-presence's
# reconcile_presence_verdict (#860). Verdict-INERT to the nomination spine.
#
# ONLY the biomarker-dependency FAMILY is reconciled, and ONLY when BOTH orthogonal KO-dependency
# CONFIDENCE cards directly contradict the claimed dependency: cross-consortium (Broad↔Sanger) reads
# `concordant_non_dependent` AND the DepMap models carrying the tumour's OWN event read
# `event_matched_not_dependent`. Requiring BOTH is CD19-safe (categorical, no magic number; two explicit
# opposing measurements): a real biomarker dependency (KRAS/ERBB2 concordant_dependent, PIK3CA
# concordant_dependent, BRAF whose event card is absent) is never demoted; a single card gap/agreement
# retains. Backtested on a LoF-suppressor + GoF-oncogene panel: only TP53/COADREAD demotes (its DEP is a
# low-confidence mutant-p53 correlation the cross-consortium + event-model cards oppose), everything else
# retains. It only ever DEMOTES a positive to a neutral caveat token — never fabricates a driver call.
_GENOMIC_DEP_FAMILY = frozenset({"biomarker_stratified_dependency", "moderate_biomarker_dependency"})
BIOMARKER_DEPENDENCY_UNCONFIRMED = "biomarker_dependency_unconfirmed"


def reconcile_genomic_verdict(raw_verdict: str | None, headline: dict) -> str | None:
    """Demote a raw biomarker-dependency word that BOTH KO-dependency confidence cards contradict to the
    `biomarker_dependency_unconfirmed` caveat token; leave every other verdict (and any dependency call
    the cards do not both oppose) unchanged. See the block comment above."""
    if raw_verdict not in _GENOMIC_DEP_FAMILY or not isinstance(headline, dict):
        return raw_verdict
    cross = headline.get("cross_consortium_class")
    event = headline.get("event_correspondence_class")
    if cross == "concordant_non_dependent" and event == "event_matched_not_dependent":
        return BIOMARKER_DEPENDENCY_UNCONFIRMED
    return raw_verdict


def reconciled_verdict_from_cards(raw_verdict: str | None, cards) -> str | None:
    """The same reconciliation as reconcile_genomic_verdict, reachable from the STANDALONE fan-out hooks
    (_claim_record / _strength_certainty) which receive (cards, fired, verdict_pair) and never see the
    headline. Rebuilds only the two keys the reconciler reads, straight off the cards they are lifted
    from — so there is ONE reconciliation rule, not two.

    Why the hooks need this: the dispatcher hands them the RAW resolver word (the gate deliberately reads
    the raw ladder), so before this they described TP53/COADREAD as
    `state=biomarker_stratified_dependency, direction=supports, availability=measured_positive` while the
    emitted headline for the same run said `biomarker_dependency_unconfirmed` — the shadow record and the
    published verdict contradicted each other on the one target the reconciler exists to demote."""
    return reconcile_genomic_verdict(
        raw_verdict,
        {
            "cross_consortium_class": (card_summary(cards, "cross-consortium-dependency") or {}).get(
                "cross_consortium_class"
            ),
            "event_correspondence_class": (card_summary(cards, "genomic-event-model-match") or {}).get(
                "event_correspondence_class"
            ),
        },
    )


def _genomic_tension_extra(headline: dict):
    """The sharpest cross-class SCOPE caveat on the stratified-dependency verdict. Three related
    scope-leak candidates, highest severity wins (verdict-inert, display-only):

      1. the verdict rests on a PAN-CANCER extrapolation (`scope_of_driving_verdict`), not an
         in-indication signal — the scope leak the one-word verdict otherwise hides;
      2. the stratified-dependency call is LINEAGE-CONTEXT DIVERGENT
         (`stratified_lineage_context_divergent`): the within-indication and pan-cancer arms
         disagree, so the pan-cancer read does not transfer cleanly to this indication;
      3. a pan-fallback strong call was CAPPED to moderate
         (`stratified_pan_fallback_capped`): the strong signal was earned only pan-cancer and was
         deliberately demoted for this indication.

    Candidate (1) is listed first so it wins any severity tie, preserving the prior output byte-for-byte
    where the driving verdict is a pan-cancer extrapolation."""
    scope = (headline.get("genomic_alteration_by_scope") or {}).get("scope_of_driving_verdict")
    cands = []
    if scope == "pan_cancer_extrapolation":
        cands.append(
            {
                "text": "verdict rests on a pan-cancer extrapolation, not an in-indication signal",
                "source": "genomic_alteration_by_scope.scope_of_driving_verdict",
                "severity": 3,
            }
        )
    if headline.get("stratified_lineage_context_divergent"):
        cands.append(
            {
                "text": (
                    "stratified-dependency call is lineage-context divergent: the within-indication and "
                    "pan-cancer arms disagree, so the pan-cancer read may not transfer to this indication"
                ),
                "source": "mutation-stratified-dependency.lineage_context_divergent",
                "severity": 3,
            }
        )
    if headline.get("stratified_pan_fallback_capped"):
        cands.append(
            {
                "text": (
                    "a pan-cancer-fallback strong stratified-dependency call was capped to moderate for "
                    "this indication (the strong signal was earned only pan-cancer)"
                ),
                "source": "mutation-stratified-dependency.pan_fallback_strong_capped_to_moderate",
                "severity": 2,
            }
        )
    if not cands:
        return None
    return max(cands, key=lambda t: t["severity"])


_GENOMIC_HEADLINE_SPEC = HeadlineSpec(
    gate="genomic_alteration",
    axis_labels={
        "SNV": "recurrent SNV/indel driver",
        "CN": "copy-number driver",
        "FUS": "fusion driver",
        "DEP": "alteration confers dependency",
    },
    axis_keys=("SNV", "CN", "FUS", "DEP"),
    critical_axes=("SNV", "CN", "FUS", "DEP"),
    verdict_label=lambda v: _GENOMIC_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_genomic_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed genomic headline. Reads the
    collapsed multi-class verdict + the verdict-inert claim_vector / key_signals; never moves the spine.
    No certainty sidecar is emitted by this skill, so confidence derives from the claim_vector's
    corroboration (weakest-link, capped by conflict + coverage)."""
    v = headline.get("genomic_alteration_profile")
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_GENOMIC_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=_genomic_verdict_polarity(v),
    )


def _build_headline(
    cards: list[dict],
    verdict: str,
    driving_rule: str | None,
    fdr_provenance: dict,
    fired: "list[dict] | None" = None,
    amplicon_fusion_provenance: "dict | None" = None,
) -> dict:
    """Assemble the deterministic headline: the computed verdict keys, every declarative field
    lift from _HEADLINE_FIELDS, then the card-availability roll-up. `fired` (optional) supplies the
    skill_report provenance's fired_rule_ids; all callers have it in scope. `amplicon_fusion_provenance`
    (optional, #983) carries the copy-number-gated fusion-demotion provenance."""
    card_by_id = {c["card_id"]: c for c in cards}
    headline: dict = {
        "genomic_alteration_profile": verdict,
        "driving_rule_id": driving_rule,
        # Per-alteration-class breakdown of the collapsed multi_class verdict (which class drives).
        "genomic_alteration_by_class": _genomic_alteration_by_class(cards),
        # Per-SCOPE breakdown + scope_of_driving_verdict: at what scope (pan-cancer / indication /
        # subtype) the collapsed verdict was earned. ADDITIVE / verdict-inert (subtype sub-block is
        # patched by main() only when --subtypes is passed).
        "genomic_alteration_by_scope": _genomic_alteration_by_scope(cards, driving_rule),
        # When >=2 stratified-dependency classes fired, their p-values were BH-corrected jointly and
        # any class with family-wise q >= 0.05 was demoted so a multi-class call is not over-credited.
        "stratified_family_wise_fdr": fdr_provenance,
        # #983: provenance of the copy-number-gated fusion demotion (was a moderate_promiscuous fusion at a
        # focally-amplified locus demoted to an amplicon passenger, or the no-op reason).
        "amplicon_fusion_demotion": amplicon_fusion_provenance or {},
    }
    for key, card_id, field in _HEADLINE_FIELDS:
        headline[key] = _lift_field(card_by_id, card_id, field)
    # EMITTED-verdict reconciliation (Phase 3): now that the KO-dependency confidence fields
    # (cross_consortium_class + event_correspondence_class) are lifted, reconcile the ONE WORD a
    # human/LLM reads so it can no longer OVER-READ the signal package. The raw resolver word is kept as
    # `genomic_alteration_profile_ladder`; the reconciled word replaces genomic_alteration_profile so the
    # downstream claim_vector-free surfaces built below (headline_block, question_table) and the narrator
    # (verdict_key="genomic_alteration_profile") all inherit it. Verdict-INERT to the nomination spine —
    # the composed GATE reads the RAW resolve_verdict_for_gate output, not this emitted word. See
    # reconcile_genomic_verdict.
    _reconciled = reconcile_genomic_verdict(verdict, headline)
    if _reconciled != verdict:
        headline["genomic_alteration_profile_ladder"] = verdict
        headline["genomic_alteration_profile"] = _reconciled
    headline["cards_available"] = sum(1 for c in cards if not c.get("_missing"))
    headline["cards_missing"] = [c["card_id"] for c in cards if c.get("_missing")]
    # Additive, verdict-INERT: the claim vector (SNV/CN/FUS driver + DEP alteration-confers-dependency,
    # signal×corroboration) + a brief cited key-signals read — the WITHIN-lens integration this subskill
    # owns, built on the SHARED claim_vector_core contract (genomic-alteration is the fourth concrete
    # after presence + dependency + selectivity). Both PROJECT the headline just built (reusing
    # genomic_alteration_by_class as the single source of the per-class primaries); they NEVER touch the
    # genomic_alteration_profile spine (byte-stable). See _skills_common/genomic_claims.py.
    headline["claim_vector"] = genomic_claim_vector(headline, cards)
    headline["key_signals"] = genomic_key_signals(headline, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing
    # headline message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT
    # projection over the claim_vector / key_signals just built; best-effort so a formatting/read fault
    # in this display layer can NEVER discard the genomic spine already fully built in `headline` (same
    # degrade discipline tumor-presence applies). On the happy path this adds one key and no
    # _enrichment_errors, so the replay + golden-spine fixtures stay stable.
    try:
        headline["headline_block"] = _build_headline_block(headline)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        headline["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — a verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort:
    # a formatting/read fault must NEVER discard the genomic spine already fully built in `headline`.
    try:
        headline["question_table"] = genomic_question_table(headline, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        headline["question_table"] = None
    # Hierarchy-derived sub-group signals (signals-first). Wired HERE (rather than via run_wired_skill's
    # generic post-headline wiring) so the key keeps its in-headline position; the tuned value→tier map
    # gives the alteration vocabulary correct polarity. Verdict-INERT, best-effort (never abort the spine).
    try:
        _sg = subgroup_signals_for(
            Path(__file__).resolve().parent.parent,
            cards,
            classify=make_value_classifier(_GENOMIC_VALUE_TIERS),
            claim_vector=headline.get("claim_vector"),
        )
        if _sg:
            headline["subgroup_signals"] = _sg
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["subgroup_signals"] = f"{type(exc).__name__}: {exc}"
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, from the
    # (reconciled) verdict + claim_vector + headline_block + question_table just built. genomic-alteration-
    # profile is a GATING skill (∈ target-profile _SHORT_TO_GATE) with a clean 3-band polarity and no
    # veto-killer verdict, so the helper's negative→opposing floor is correct (no override). Uses the
    # RECONCILED genomic_alteration_profile (the emitted word, not the raw ladder). Best-effort +
    # verdict-INERT. `fired` supplies fired_rule_ids (None → omitted).
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        headline["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=headline.get("genomic_alteration_profile"),
            driving_rule_id=headline.get("driving_rule_id"),
            headline_block=headline.get("headline_block"),
            claim_vector=headline.get("claim_vector"),
            question_table=headline.get("question_table"),
            # the hierarchy-derived per-sub-group signals computed just above. They were being BUILT and
            # then dropped on the floor here: populated in the headline on 26/26 review-panel runs while
            # skill_report.subgroup_signals stayed None, so every consumer reading the unified spine
            # (rather than reaching into the headline) saw a skill with no sub-group decomposition.
            subgroup_signals=headline.get("subgroup_signals"),
            # FOR-WHAT projection — see _ga_modality_scope. First-class on the spine so
            # target_report.modality_fit rolls it up FROM the report instead of reaching into
            # claim_record_shadow (contract §135-140); previously None on every run.
            modality_scope=_ga_modality_scope(cards, fired=fired, verdict=headline.get("genomic_alteration_profile")),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or [c.get("card_id") for c in (cards or []) if isinstance(c, dict)],
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        headline["skill_report"] = None
    return headline


# The uniform opt-in the target-profile fan-out looks for via getattr(module, "_synthesis_facet")
# (mirrors tumor-presence + functional-requirement). Lifts genomic-alteration's claim_vector (the
# SNV/CN/FUS driver + DEP alteration-confers-dependency SIGNAL decomposition) + key_signals to the
# composed synthesis, closing an arch-review gap (claim_vector was BUILT here but never surfaced to the
# cross-lens layer). The fan-out does not run this skill's main()/run_wired_skill, so the facet
# reconstructs the headline from the fan-out-resolved verdict_pair via _build_headline. VERDICT-INERT: nothing here
# enters `fired`/the resolver; the fan-out treats an absent/failed facet as no-facet.
_SYNTHESIS_FACET_KEYS = (
    "genomic_alteration_profile",
    "driving_rule_id",
    "genomic_alteration_by_class",
    "genomic_alteration_by_scope",
    "claim_vector",
    "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # hierarchy-derived per-sub-group signals (SNV/CN/FUS/DEP; sources bound by measurement_type)
    "subgroup_signals",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 skill_report
    # adoption (5th gating adopter)
    "skill_report",
)


# ── (strength, certainty) SIDECAR — 3rd certainty axis (CERTAINTY_MODEL.md). ADDITIVE + verdict-INERT:
#    computed beside the genomic verdict; never alters it. corroboration = the VERDICT-DISJOINT CIViC
#    per-variant oncogenicity (variant-level-interpretation.civic_variant_class — an independent curated
#    source confirming the driver claim; fires no resolver rung). Reviewed per-axis design (4-agent panel).
_CERTAINTY_CORROBORATION_CARDS = frozenset({"variant-level-interpretation"})
_GA_STRONG_POS = {"biomarker_stratified_dependency", "multi_class_driver", "multi_class_lof_driver"}
_GA_MOD_POS = {
    "moderate_biomarker_dependency",
    "confirmed_driver",
    "confirmed_lof_driver",
    "drug_response_biomarker",
    "recurrent_amplification_driver",
    "recurrent_deletion_driver",
    "recurrent_fusion_driver",
    "recurrent_snv_driver",
    "splice_exon_skip_driver",
}
_GA_NEG = {"passenger_pattern"}
# MEASURED-BUT-UNCONFIRMED demotion tokens — a real signal the skill declines to promote to a driver
# call. Both were previously in NO bucket, which is why they fell through _genomic_strength to "none"
# AND (the actual defect) through _ga_availability's final `return "measured_positive"` — i.e. a token
# whose whole purpose is to say "we could not confirm this" was published as a measured POSITIVE with a
# `none` magnitude. They are NEUTRAL in strength (measured, non-directional) and `insufficient` in
# availability (measured-but-underpowered), which is exactly what each token asserts:
#   recurrent_snv_subclonal_uncertain — patient recurrence is real but SUBCLONAL, so driver status is
#     unresolved (resolver 1.7.0 backtest-gated demotion; target-clonality.clonality_class)
#   biomarker_dependency_unconfirmed  — the biomarker stratification fired but BOTH orthogonal
#     KO-dependency confidence cards contradict it (reconcile_genomic_verdict, v2.12.0)
_GA_UNCONFIRMED = {"recurrent_snv_subclonal_uncertain", BIOMARKER_DEPENDENCY_UNCONFIRMED}
# MUTATION-SHAPE descriptors — a spectrum shape that fires ONLY when the alteration ROLE is unresolved
# (a typed GoF/LoF role routes to confirmed_(lof_)driver instead). A shape-without-a-confirmed-role is
# NOT a positive driver call: the verdict-side polarity source of truth (_GENOMIC_POSITIVE_VERDICTS) and
# the FOR-WHAT projection (_ga_modality_scope → `na`) BOTH already treat lof/missense_dominant_pattern as
# NEUTRAL (they read oncogene-flavored `positive` for CD47/TNKS). They were previously in _GA_WEAK_POS, so
# the (strength, certainty) + claim_record SIDECAR alone published them weak_positive / supports /
# measured_positive — a fail-open contradiction with the verdict spine, the exact defect clause (c) of
# v2.18.0 fixed for the _GA_UNCONFIRMED demotion tokens but MISSED for these. Folded in here.
_GA_SPECTRUM_SHAPE_NEUTRAL = {"lof_dominant_pattern", "missense_dominant_pattern"}
# NEUTRAL = measured, but licenses NO directional (driver) claim. Every member maps: _genomic_strength →
# "neutral", _ga_direction → "neutral", _ga_availability → "insufficient" (claim_record has no
# "measured_neutral" availability token; `insufficient` is its home for a real measurement that supports
# no direction — see _ga_availability). mixed_pattern is neutral for the same reason.
_GA_NEUTRAL = {"mixed_pattern"} | _GA_SPECTRUM_SHAPE_NEUTRAL | _GA_UNCONFIRMED
_GA_NONE = {"insufficient", "data_unavailable", None}
_GA_DECISION_CARDS = (
    "mutation-type-counts",
    "mutation-stratified-dependency",
    "mutation-hotspot-frequency",
    "copy-number-distribution",
    "copy-number-stratified-dependency",
    "amp-expr-stratified-dependency",
    "fusion-stratified-dependency",
    "fusion-rearrangement-landscape",
    "mutation-drug-response",
    "alteration-role",
)
# Coverage-band cutoffs — SKILL-OWNED policy (see the module-top note: interpretation rules are
# equals-only, so there is no consumable numeric cutoff in a card/rule contract). These MIRROR
# subgroup_common.panorama.SUBGROUP_N_FLOOR (30) / SUBGROUP_EXPLORATORY_FLOOR (10) — the fleet's
# single-source cell-line power floors ("readers import this, never re-hardcode") — restated here rather
# than imported because _strength_certainty runs on the certainty hot path and in unit tests that do not
# load the analysis-methods sibling; _skills_common.subgroup_derivation restates the 30 the same way.
# Keep in lockstep with panorama.
_COVERAGE_N_HIGH = 30  # >= powered comparative-claim floor   -> high coverage
_COVERAGE_N_MED = 10  # >= exploratory (hypothesis-grade) floor -> medium; below -> low

# The ALTERED (minority) arm field(s) on each stratified-dependency card — how many lines actually carry
# the alteration the dependency contrast was powered on (NOT n_cell_lines_evaluated, which is the panel
# denominator). mutation-stratified-dependency exposes three arms (hotspot / damaging / any); the largest
# non-null is the arm the call was most plausibly powered on.
_DEP_ARM_FIELDS: dict[str, tuple[str, ...]] = {
    "mutation-stratified-dependency": ("n_hotspot_mutant", "n_damaging_mutant", "n_any_mutant"),
    "copy-number-stratified-dependency": ("n_amplified",),
    "fusion-stratified-dependency": ("n_fusion_positive",),
    "amp-expr-stratified-dependency": ("n_amplified_overexpressed",),
}
# SNV spectrum / prevalence verdicts whose power = cell lines CARRYING a mutation
# (mutation-type-counts.mut_n_cell_lines_mutated, the altered arm), never the panel total.
_GA_SNV_SPECTRUM = {
    "missense_dominant_pattern",
    "lof_dominant_pattern",
    "mixed_pattern",
    "passenger_pattern",
    "recurrent_snv_driver",
    "recurrent_snv_subclonal_uncertain",
}
# Curation- / landscape-backed calls with NO small cell-line arm of their own: a curated oncogenic driver
# (OncoKB / CIViC), a patient-cohort copy-number recurrence, a fusion landscape. copy-number-distribution
# carries only amplification FRACTIONS (no altered-line COUNT), and each of these rungs fires only on its
# own recurrence / curation threshold — so a cell-line arm count is not the power instrument here.
# Coverage is reported `high` so level = min(coverage, corroboration) is CORROBORATION-limited rather than
# floored by an absent count.
_GA_CURATED_OR_LANDSCAPE = {
    "confirmed_driver",
    "confirmed_lof_driver",
    "multi_class_driver",
    "multi_class_lof_driver",
    "drug_response_biomarker",
    "splice_exon_skip_driver",
    "recurrent_amplification_driver",
    "recurrent_deletion_driver",
    "recurrent_fusion_driver",
}


def _genomic_strength(v) -> str:
    if v in _GA_STRONG_POS:
        return "strong_positive"
    if v in _GA_MOD_POS:
        return "moderate_positive"
    if v in _GA_NEG:
        return "negative"
    if v in _GA_NEUTRAL:
        return "neutral"
    return "none"


def _dep_arm_n(cards, card_id: str):
    """The altered (minority) arm size on a stratified-dependency card — the largest non-null arm field
    (see _DEP_ARM_FIELDS). None when the card / all its arm fields are absent."""
    summary = card_summary(cards, card_id) or {}
    vals = [summary.get(f) for f in _DEP_ARM_FIELDS.get(card_id, ())]
    vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return max(vals) if vals else None


def _coverage_band(n) -> str:
    """Bucket an altered-arm sample count into a coverage band. A missing/non-numeric count is `low` —
    the conservative direction (no measured power basis)."""
    return coverage_band(n, high_n=_COVERAGE_N_HIGH, med_n=_COVERAGE_N_MED)


def _ga_coverage(cards, verdict=None, driving_rule=None) -> str:
    """Coverage = the DRIVING CLASS's sample power, banded via the cell-line power floors.

    NOT the panel denominator. The previous implementation read the first available n from a card list
    headed by mutation-stratified-dependency.n_cell_lines_evaluated — the ~1500-line panel TOTAL — so it
    saturated to `high` for essentially every target, however thin the driving alteration's own arm was.
    Coverage is now sourced from the arm that actually supports the driving verdict:

      1. Dependency verdicts (driving_rule prefix in _DEP_RULE_SCOPE_CARD) → the ALTERED ARM tested for
         dependency (_dep_arm_n): the minority arm the contrast was powered on, not lines evaluated.
      2. SNV spectrum / prevalence verdicts (_GA_SNV_SPECTRUM) → mutation-type-counts.mut_n_cell_lines_mutated
         (lines CARRYING a mutation), not mut_n_cell_lines_total.
      3. Curation-/landscape-backed calls (_GA_CURATED_OR_LANDSCAPE) → `high`: the driving evidence is
         curation or patient-cohort recurrence, whose power is not a cell-line arm count (and
         copy-number-distribution has no altered-line count, only fractions). See that set's note.
      4. anything else (insufficient / data_unavailable / an unbucketed token) → `low`: the SAFE direction
         (no measurable power basis), contrasting the old `measured_positive`/`high` fail-open default.
    """
    if driving_rule:
        for prefix, card_id in _DEP_RULE_SCOPE_CARD.items():
            if driving_rule.startswith(prefix):
                return _coverage_band(_dep_arm_n(cards, card_id))
    if verdict in _GA_SNV_SPECTRUM:
        n = (card_summary(cards, "mutation-type-counts") or {}).get("mut_n_cell_lines_mutated")
        return _coverage_band(n)
    if verdict in _GA_CURATED_OR_LANDSCAPE:
        return "high"
    return "low"


def _ga_corroboration(civic_class) -> str:
    c = str(civic_class or "")
    if c == "oncogenic":
        return "high"
    if c == "likely_oncogenic":
        return "medium"
    if c in {"vus", "benign", "likely_benign"}:  # set literal (NOT a 3-tuple) — avoids the composer
        return "low"  # card-read scanner misreading a value tuple as a card_id
    return "unmeasured"  # gene uncurated in CIViC → ignorance, carried in unknown_mass


def _ga_unknown_mass(cards) -> float:
    blind = 0
    for cid in _GA_DECISION_CARDS:
        s = card_summary(cards, cid)
        if not s or s.get("_missing"):
            blind += 1
    return round(blind / len(_GA_DECISION_CARDS), 4)


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — mirrors functional-requirement/selectivity. Standalone."""
    vp = verdict_pair if verdict_pair else (_verdict(fired) if fired is not None else (None, None))
    v, driving = vp[0], (vp[1] if len(vp) > 1 else None)
    v = reconciled_verdict_from_cards(v, cards)  # score the EMITTED word, not the raw ladder
    civic = (card_summary(cards, "variant-level-interpretation") or {}).get("civic_variant_class")
    # coverage routes on the reconciled verdict + the ORIGINAL driving_rule (reconciliation demotes the
    # word but keeps the rung, so the arm that was powered is still the driving rule's arm)
    coverage = _ga_coverage(cards, verdict=v, driving_rule=driving)
    corroboration = _ga_corroboration(civic)
    level = weakest_link_level(coverage, corroboration, force_low=(v in _GA_NONE))
    strength = _genomic_strength(v)
    return assemble_strength_certainty(
        strength,
        coverage,
        corroboration,
        _ga_unknown_mass(cards),
        level=level,
        composite_basis=(
            "certainty-discounted genomic-alteration strength = peak signal tier × "
            "weakest-link certainty; a NAMED [0,1] portfolio-ranking projection, not a verdict"
        ),
        provenance={"civic_variant_class": civic},
        model_ref="CERTAINTY_MODEL.md#genomic_alteration",
    )


# ── FACTORED-RECORD SHADOW (M1) — the genomic per-axis builder. VERDICT-INERT: emitted into
#    decision.json.claim_record_shadow and consumed only by the composed report layer, verdict-inert (goldens untouched). Maps the
#    genomic_alteration verdict token onto the factored record's axis-specific coordinates; the
#    shared assembler owns shape + the open-world invariant + provenance. Mirrors _strength_certainty.
_GA_ROLE = {  # driver-role from the verdict (LoF-family verdicts carry loss-of-function role)
    "confirmed_lof_driver": "LoF",
    "multi_class_lof_driver": "LoF",
    "lof_dominant_pattern": "LoF",
}
# strength label -> ordinal magnitude level (informational; the finding.magnitude coordinate)
_GA_STRENGTH_TO_LEVEL = {
    "strong_positive": "strong",
    "moderate_positive": "moderate",
    "weak_positive": "weak",
    "negative": "moderate",
    "neutral": "weak",
    "none": "none",
}


def _ga_availability(v) -> str:
    """Map the genomic verdict to the claim_record availability TYPE:
    not_wired         — `data_unavailable` / None: open-world ignorance (the assembler then forces
                        state=unknown / direction=neutral / magnitude none).
    insufficient      — a real measurement that licenses NO directional claim: the resolver default
                        `insufficient`, or any NEUTRAL verdict (mixed / spectrum-shape / the two
                        demotion tokens). claim_record has no "measured_neutral" token, so `insufficient`
                        is its home for "we measured, but this supports no direction". Paired with
                        _ga_direction → "neutral" (the assembler leaves a non-open-world availability's
                        direction untouched, so a NEUTRAL verdict MUST NOT reach measured_positive here).
    measured_negative — a passenger call (measured, opposes a driver claim).
    measured_positive — a confirmed driver / dependency / recurrence call."""
    if v == "data_unavailable" or v is None:
        return "not_wired"
    if v == "insufficient" or v in _GA_NEUTRAL:
        return "insufficient"
    if v in _GA_NEG:
        return "measured_negative"
    return "measured_positive"


def _ga_direction(v) -> str:
    if v in _GA_STRONG_POS or v in _GA_MOD_POS:
        return "supports"
    if v in _GA_NEG:
        return "opposes"
    return "neutral"  # NEUTRAL family (mixed / spectrum-shape / demotion tokens) + anything unknown


# ── FOR-WHAT projection (claim_record.modality_scope / skill_report.modality_scope). VERDICT-INERT.
#
# NOT a fold of the rules' per-modality `signals`. MEASURED 2026-09-12: of the 59 rules in
# intracellular-intrinsic.rules.yaml bound to a genomic card, ZERO diverge between their
# `small_molecule` and `degrader` signal (19 supportive / 24 neutral / 7 insufficient / 1 opposing, all
# identical; 8 carry no degrader channel at all). Folding them would emit a block that is equal across
# channels BY CONSTRUCTION — a field with no information. So the projection is derived from the measured
# CARD FIELDS + the resolver-earned verdict instead, and encodes exactly one question this axis can
# actually answer: does the genomic evidence hand a small molecule a SELECTABLE ALLELE, or must it engage
# wild-type protein?
#
#   unfavorable  recurrent homozygous (biallelic) deletion — no protein to inhibit or degrade. The
#                copy-number card's own design note names this as the modality-incompatible CN pattern.
#   favorable    a resolver-earned GoF DRIVER call + allele-selectivity eligibility (the fleet's existing
#                wt_loss_safety_conditioning.yaml triple: an eligibility rule, every required
#                oncogene-role co-gate, no amplification/rarely-altered disqualifier) + POSITIVE
#                selectable-allele evidence. The eligibility triple alone is a NEGATIVE screen — it
#                rules amplicons out but never establishes that a selectable lesion exists — so a
#                positive allele signal is additionally required. Without it, surface-antigen targets
#                whose alteration_role is OncoKB-gene-list-only (TACSTD2, FOLR1) read SM-favorable.
#   conditional  a GoF driver call with NO selectable allele: the amplicon/fusion/overexpression targets
#                whose small molecules bind the WILD-TYPE protein (ERBB2, FGFR2, MET-ex14, CCND1, MYC).
#   na           everything else — TSG/LoF calls, spectrum-shape-only reads, the demotion tokens, and
#                both negative controls. `na` is a claim, not a gap: this axis does not speak here.
#
# `biologics` is `na` on EVERY run, deliberately: genomic-alteration is an intracellular-INTRINSIC axis
# with no localization read, so it cannot license a biologics call. A focal amplification says nothing
# about whether the protein is on the cell surface — that is surface-modality-fit's call. Asserting
# otherwise is precisely how CD19/TACSTD2/FOLR1 would acquire a fabricated biologics favorability.
# `_refinements` is likewise always omitted: the schema admits a sub-channel ONLY where a named
# discriminator justifies departing from its base channel, the 0/59 measurement above says this axis has
# no such discriminator, and the degrader's WT-engagement refinement is already owned by the safety axis
# (modality_safety.py) — duplicating it here would double-count one measurement.
_GA_GOF_DRIVER_VERDICTS = frozenset(
    {
        "confirmed_driver",
        "multi_class_driver",
        "recurrent_amplification_driver",
        "recurrent_fusion_driver",
        "recurrent_snv_driver",
        "splice_exon_skip_driver",
        "drug_response_biomarker",
        "biomarker_stratified_dependency",
        "moderate_biomarker_dependency",
    }
)
# DELIBERATELY EXCLUDED: missense_dominant_pattern / lof_dominant_pattern. A spectrum SHAPE is not a
# driver call — missense_dominant fires for 62% of the review panel INCLUDING both the GAPDH and ACTB
# negative controls (>=0.70 missense is the genetic code's no-selection expectation). Admitting them put
# both controls at `conditional`.
#
# POSITIVE selectable-allele evidence: a discrete lesion an allele-selective agent can be raised against.
_GA_SELECTABLE_ALLELE_RULES = frozenset(
    {
        "snv-recurrence-top-driver-supportive",  # top-1% pooled patient recurrence (a real hotspot)
        "mutation-drug-response-strongly-sensitive-supportive",  # a mutant-selective compound measurably works
        "splice-exon-skip-driver-supportive",  # curated oncogenic exon-skip lesion (METex14)
        "mutant-strongly-dependent-supportive",  # mutant-vs-WT KO stratification: the allele carries the dependency
        "mutant-moderately-dependent-supportive",
    }
)


@functools.lru_cache(maxsize=None)
def _allele_selectivity_vocab() -> tuple[frozenset, frozenset, frozenset]:
    """(eligibility, required_role, disqualifier) rule-id sets from the SHARED contract vocabulary that
    already defines allele-selectivity for the safety axis — read, not restated, so a curation change
    binds both axes. Loaded here rather than imported from modality_safety so this projection owns no
    hot-file dependency."""
    cond = yaml.safe_load((target_contracts_root() / "vocabularies" / "wt_loss_safety_conditioning.yaml").read_text())
    return (
        frozenset(cond.get("allele_selective_eligibility_rules") or []),
        frozenset(cond.get("allele_selective_required_role_rules") or []),
        frozenset(cond.get("allele_selective_disqualifier_rules") or []),
    )


def _ga_modality_scope(cards, fired=None, verdict=None) -> dict | None:
    """The FOR-WHAT block for the genomic-alteration claim. See the block comment above. Best-effort:
    returns None if the shared vocabulary cannot be read, so a contracts-read fault never costs the
    caller its report."""
    try:
        eligibility, required_role, disqualifiers = _allele_selectivity_vocab()
    except Exception:  # noqa: BLE001 — verdict-inert projection; absent block beats a broken run
        return None
    fired_ids = {f.get("rule_id") for f in (fired or []) if isinstance(f, dict)}
    homozygous_deletion = (card_summary(cards, "copy-number-distribution") or {}).get(
        "cn_homozygous_deletion_recurrent"
    ) == "recurrent_homozygous_deletion"
    allele_selective_eligible = (
        bool(fired_ids & eligibility) and fired_ids.issuperset(required_role) and not (fired_ids & disqualifiers)
    )
    selectable_allele = bool(fired_ids & _GA_SELECTABLE_ALLELE_RULES)

    if homozygous_deletion:
        small_molecule = "unfavorable"
    elif verdict in _GA_GOF_DRIVER_VERDICTS and allele_selective_eligible and selectable_allele:
        small_molecule = "favorable"
    elif verdict in _GA_GOF_DRIVER_VERDICTS:
        small_molecule = "conditional"
    else:
        small_molecule = "na"
    return {"small_molecule": small_molecule, "biologics": "na"}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors _strength_certainty's call shape."""
    v, driving = verdict_pair if verdict_pair else (_verdict(fired) if fired is not None else (None, None))
    # the RECONCILED word, matching what the skill actually publishes (see reconciled_verdict_from_cards)
    v = reconciled_verdict_from_cards(v, cards)
    strength = _genomic_strength(v)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=(v, driving))
    return assemble_claim_record(
        axis="genomic_alteration",
        state=(v or "insufficient"),
        direction=_ga_direction(v),
        availability=_ga_availability(v),
        magnitude={"level": _GA_STRENGTH_TO_LEVEL.get(strength, "none")},
        mechanism={"role": _GA_ROLE.get(v, "unknown")},
        modality_scope=_ga_modality_scope(cards, fired=fired, verdict=v),
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT genomic-alteration facet for the composed synthesis prompt. Reconstructs
    the headline from the fan-out-resolved (verdict, driving_rule) via _build_headline (fdr provenance
    omitted — a within-run detail, not reconciliation-relevant) and returns claim_vector + key_signals +
    the per-class/per-scope breakdown. Never moves the verdict; safe to omit."""
    verdict, driving = verdict_pair if verdict_pair else (None, None)
    h = _build_headline(cards, verdict, driving, {}, fired=fired)
    return build_synthesis_facet(
        h,
        _SYNTHESIS_FACET_KEYS,
        (
            "Deterministic genomic-alteration facet (a FACET, not a gate; the multi-class genomic verdict is "
            "owned by the shared resolver and is verdict-inert to this projection). claim_vector is the "
            "SIGNAL decomposition — SNV / CN / FUS per-class driver + DEP alteration-confers-dependency, each "
            "a signal×corroboration tier; genomic_alteration_by_class/_by_scope name which class + at what "
            "scope the verdict was earned. The per-axis certainty roll-up is the separate certainty_by_axis sidecar."
        ),
    )


def _llm_synthesis(
    cards, fired, verdict_pair, target, indication, model_id=None, subtype=None, literature_synthesis=None
):
    """Fan-out opt-in (mirrors _synthesis_facet): return the genomic-alteration lens's provenance-
    tagged llm_synthesis block for the COMPOSED target-profile run. Rebuilds the headline from the
    fan-out-resolved (verdict, driving_rule) via _build_headline (exactly as _synthesis_facet does),
    then narrates through the genomic synthesizer. Best-effort + VERDICT-INERT (the subtype arg is
    unused — genomic narrates whole-cohort; a failure is the caller's to swallow).
    `literature_synthesis` (optional, from the fan-out's pre-narration literature lane) is threaded
    onto the decision the narrator reads so exec_bullets weave + cite it (None → byte-identical)."""
    verdict, driving = verdict_pair or (None, None)
    headline = _build_headline(cards, verdict, driving, {}, fired=fired)
    # cards passed so the generic engine can build evidence capsules (bounded raw data layer).
    decision = {
        "target": target,
        "indication": indication,
        "headline": headline,
        "cards": [{"card_id": c.get("card_id"), "summary": c.get("summary") or {}} for c in cards],
        "literature_synthesis": literature_synthesis,
    }
    return _narrate(decision, _LENS, model_id)


def _headline_fn(cards, fired, verdict_pair, preprocess_provenance=None):
    """Dispatcher headline contract -> _build_headline. Unpacks verdict_pair + the per-gate card-
    preprocessor provenance (preprocess_gate="genomic_alteration" returns {family_wise_fdr,
    amplicon_fusion_demotion} -- the same two dicts the former hand-rolled main() computed inline)."""
    verdict, driving_rule = verdict_pair if verdict_pair else (None, None)
    _pp = preprocess_provenance or {}
    return _build_headline(
        cards,
        verdict,
        driving_rule,
        _pp.get("family_wise_fdr") or {},
        fired=fired,
        amplicon_fusion_provenance=_pp.get("amplicon_fusion_demotion") or {},
    )


def _subtype_merge_fn(headline: dict, subtype_result: dict) -> None:
    """Bespoke subtype-panorama merge (run_wired_skill subtype_merge_fn) -- the dispatcher's generic
    flat key-hoist cannot write the NESTED genomic_alteration_by_scope['subtype'] block. Mirrors the
    former hand-rolled main() merge exactly: hoist each per-axis projection to a top-level headline key
    + build the by-scope subtype sub-block. DESCRIPTIVE / verdict-INERT (touches no rung)."""
    headline["subtype_scope"] = subtype_result["scope_subtypes"]
    axes = subtype_result.get("axes")
    if not axes:  # panorama resolver degraded (no axes) -> nothing more to merge
        return
    for axis_key, projection in axes.items():
        headline[axis_key] = projection
    _snv = axes.get("subtype_axis") or {}
    _any_data = any((ax.get("n_subgroups_with_data") or 0) >= 1 and not ax.get("_missing") for ax in axes.values())
    headline["genomic_alteration_by_scope"]["subtype"] = {
        "evidence_present": bool(_any_data),
        "subtype_mutation_pattern": _snv.get("subtype_mutation_pattern"),
        "subtype_cn_pattern": (axes.get("subtype_cn_axis") or {}).get("subtype_cn_pattern"),
        "subtype_fusion_pattern": (axes.get("subtype_fusion_axis") or {}).get("subtype_fusion_pattern"),
        "n_subgroups_with_data": _snv.get("n_subgroups_with_data"),
        "cross_subgroup_delta_frequency": _snv.get("cross_subgroup_delta_frequency"),
        "scope_subtypes": subtype_result["scope_subtypes"],
    }


def _claim_record_fn(cards, fired, verdict_pair) -> dict:
    """run_wired_skill claim_record_fn -> decision['claim_record_shadow']. VERDICT-INERT M1 factored
    record keyed by axis, mirroring the former hand-rolled main() shadow. Whole-cohort cards/fired."""
    return {"genomic_alteration": _claim_record(cards, fired=fired, verdict_pair=verdict_pair)}


# ─── EXPORTED bounded evidence-package sections (PR-1c, epic #2210 Wave 1 / #1507, #2212) ────────────
# The genomic generalisation of the tumour-presence reference vertical
# (`skills/tumor-presence/scripts/run.py::_evidence_sections`), replicating the safety (PR-1a) and
# dependency (PR-1b) seeds. Under `--emit-envelope` the emitted evidence_package.json gains NAMED
# top-level sections so the L1→L2a→L2b layering is STRUCTURE rather than a convention over
# `synthesis.headline.claim_vector`. The schema (contracts/schemas/evidence_package.schema.json) ALREADY
# declares all four as optional — no schema change, and a section this domain does not produce is OMITTED.
#
# The L2b property island promoted to a shared top-level section. ONE for genomic today —
# `recurrence_concordance` (MC3 exome × GENIE panel, SK#1629), which reconstructs to L1 through
# `provenance.sources[*].provenance.card_id`. Deliberately a ROSTER, not "everything without a `signal`
# key": a future L2b fold must be listed here consciously, exactly as the presence/dependency rosters work.
_INTEGRATED_ISLAND_KEYS = ("recurrence_concordance",)

# The composites that stay INSIDE the domain with their epistemic type declared — the six genomic claim
# axes. NOT promoted to shared L2 properties: each is this skill's own (signal × corroboration) read of
# one source, reconstructable to L1 via `evidence_atom.cite.card_id`. Pinned to the ClaimSpec roster so an
# axis added to GENOMIC_CLAIM_SPEC cannot silently go unexported.
_LOCAL_COMPOSITE_KEYS = tuple(spec.axis_key for spec in GENOMIC_CLAIM_SPEC)


def _evidence_sections(headline: dict) -> "dict | None":
    """Build the NAMED, bounded top-level evidence-package sections from the rich decision headline.

    Pure read-projection over the already-built `headline`: partitions content it ALREADY carries into the
    doc's named sections (`source_properties` L2a, `integrated_properties` L2b, `local_composites`).
    Nothing is recomputed and nothing is dropped that a consumer could not already read on the headline.
    Every emitted section reconstructs downward to L1:
      * source_properties[*].card_id (+ per-anchor {field, value} → the L1 card field)
      * integrated_properties[*].provenance.sources[*].provenance.card_id
      * local_composites.claims.<AXIS>.evidence_atom.cite.card_id
    `l3d` is NOT emitted: no genomic within-domain L3d story object exists yet (a later Wave-2 item, not
    this PR) — an empty section is worse than an absent one, so this domain emits THREE of the schema's
    four optional sections. Returns None when no claim_vector resolved, so the dispatcher passes
    `evidence_sections=None` and the emitted package is byte-identical to the pre-PR-1c shape.
    VERDICT-INERT throughout."""
    if not isinstance(headline, dict):
        return None
    cv = headline.get("claim_vector")
    if not isinstance(cv, dict):
        return None

    sections: dict = {}

    # L2a — per-source observational biological properties (each entry carries its L1 card_id).
    sp = cv.get("source_properties")
    if sp:
        sections["source_properties"] = sp

    # L2b — the property islands (reconstructable to card_ids via provenance.sources[*].provenance.card_id).
    integrated = {k: cv[k] for k in _INTEGRATED_ISLAND_KEYS if cv.get(k) is not None}
    if integrated:
        sections["integrated_properties"] = integrated

    # Local composites — carried inside the domain with the epistemic type declared.
    carried = {k: cv[k] for k in _LOCAL_COMPOSITE_KEYS if cv.get(k) is not None}
    if carried:
        sections["local_composites"] = {"epistemic_type": "domain_local_composite", "claims": carried}

    return sections or None


def main() -> int:
    """genomic-alteration-profile runs through the shared run_wired_skill dispatcher (was a hand-rolled
    main()). The dispatcher owns: the SKILLS_READ_POOL default, argparse (incl --subtypes / --modality /
    --synthesize / --literature / --data-mode / --release-pin / --figures), resolve_cards, the family-wise-
    FDR + copy-number-gated amplicon-fusion card preprocessors (preprocess_gate), fired_rules, the verdict,
    evidence_capsules, provenance + run_health, the evidence_graph projection, and write_package. This skill
    supplies verdict_fn/_headline_fn (the latter receives the preprocessor provenance via the dispatcher's
    signature-introspected preprocess_provenance kwarg), the --subtypes panorama (+ its bespoke nested
    by-scope merge), the GENOMIC_ALTERATION synthesis + literature lanes, and the M1 claim-record shadow.
    The in-headline subgroup-signals wiring stays in _build_headline (the dispatcher's generic fleet wiring
    then setdefault-no-ops on it), preserving the emitted headline key order."""
    return run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline_fn,
        preprocess_gate="genomic_alteration",
        subtype_panorama_fn=_resolve_subtype_panorama,
        subtype_merge_fn=_subtype_merge_fn,
        claim_record_fn=_claim_record_fn,
        synthesize_fn=make_synthesize_fn(_LENS),
        literature_fn=_LITERATURE_FN,
        evidence_sections_fn=_evidence_sections,
    )


if __name__ == "__main__":
    sys.exit(main())
