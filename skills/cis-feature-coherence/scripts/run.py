#!/usr/bin/env python3
"""cis-feature-coherence — does target X's OWN locus feature explain its OWN expression AND dependency?

Focused question skill: the coherence OWNER for the locus → expression → dependency chain.
Distinguishes amplification-driven oncogene addiction (ERBB2/MYC/KRAS-amp) from a co-occurring
passenger, an expressed-but-inert target, and a trans-driven dependency.

Integrates ONE new leg (cis-feature-expression-coherence: CN → own-expression cis-dosage) with TWO
reused leg-cards (expression-dependency-correlation + amp-expr-stratified-dependency) — no new
dependency measurement. Verdict via the SHARED declarative resolver on a DEDICATED axis:
resolve_or_raise(fired, "cis_coherence") → cis_coherence.resolver.yaml (a deterministic 2×2 cross-tab).

VERDICT-INERT at composition: cis_coherence is a dedicated self-contained axis, NOT a nomination gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import card_summary
from _skills_common.cis_coherence_claims import (
    _CIS_DOSAGE_SIGNAL,
    _CONJOINT_SIGNAL,
    _EXPR_DEP_SIGNAL,
    _SILENCING_SIGNAL,
    cis_coherence_claim_vector,
    cis_coherence_key_signals,
)
from _skills_common.cis_coherence_question_table import cis_coherence_question_table
from _skills_common.claim_record import assemble_claim_record
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import CIS_FEATURE_COHERENCE as _LENS
from _skills_common.resolver import resolve_or_raise
from _skills_common.skill_report import ROLE_INERT, build_skill_report
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: cis locus→expression→dependency coherence.
# default_classify is the fallback for unmapped values.
#
# DERIVED from the authoritative claim_vector SIGNAL maps in cis_coherence_claims.py (SINGLE SOURCE OF
# TRUTH) so the sources[].tier/confidence classification cannot drift from the top-line signal that
# overlay_claim_signals writes from the SAME maps (#1595, next instance of the #1563 `_*_VALUE_TIERS`
# drift pattern; cf. #1587). The prior hand-maintained literal had zero `unmeasured` entries: it flipped
# methylation_invariant_panel to `absent` (a measured negative) and dropped silencing_lineage_confounded /
# cn_invariant_panel / insufficient_* entirely, and it mapped positive_anomaly / amp_expr_negative_more_
# dependent (MEASURED wrong-direction) through default_classify to `absent` too. The presence-ordinal
# value classifier has no `negative` rung (subgroup_derivation._TIERV = strong/moderate/weak/absent), so a
# MEASURED wrong-direction read floors at `absent` (tier 0, measured no/adverse signal — NOT a coverage gap).
_NEGATIVE_TIER_FLOOR = "absent"
_CIS_VALUE_TIERS = {
    token: (_NEGATIVE_TIER_FLOOR if tier == "negative" else tier)
    for signal_map in (_CIS_DOSAGE_SIGNAL, _SILENCING_SIGNAL, _EXPR_DEP_SIGNAL, _CONJOINT_SIGNAL)
    for token, tier in signal_map.items()
}
# The two PROTEIN legs + the PATIENT cross-grain arm are bound in question_hierarchy.yaml (CIS_DOSAGE→
# cis_protein_dosage_coupling, EXPR_DEP→abundance_dependency_correlation, CONJOINT→patient_cis_coherence)
# but their card `*_class` vocabularies are NOT in the mRNA/methylation claim SIGNAL maps above, so their
# tokens fell through default_classify — flipping the real MEASURED positive protein_predicts_dependency to
# `absent`. Tiered here explicitly from the card summary_fields_vocabulary (target-contracts:
# cis-feature-protein-coherence / abundance-dependency / patient-cis-coherence).
_CIS_VALUE_TIERS.update(
    {
        # cis-feature-protein-coherence.cis_protein_dosage_class (cn_invariant_panel / data_unavailable
        # already routed to `unmeasured` by _CIS_DOSAGE_SIGNAL above).
        "prot_dosage_coupled_strong": "strong",
        "prot_dosage_coupled_moderate": "moderate",
        "prot_dosage_uncoupled": "absent",  # MEASURED: CN varies but protein flat (dosage-buffered)
        # abundance-dependency.abundance_dependency_class (data_unavailable already routed above).
        "protein_predicts_dependency": "strong",  # MEASURED positive: high abundance → dependent
        "weak_protein_dependency_link": "weak",
        "no_protein_dependency_link": "absent",
        "insufficient_paired_models": "unmeasured",  # < min paired models — untested, resolver abstains
        # patient-cis-coherence.patient_methylation_silencing_class (patient_cis_dosage_class tokens all
        # coincide with _CIS_DOSAGE_SIGNAL above).
        "epigenetic_silencing": "strong",  # MEASURED: methylated cases express ≥1 log2 unit lower
        "no_silencing_signal": "absent",  # MEASURED, no silencing separation
        "insufficient_methylation_data": "unmeasured",  # < 5 methylated OR < 5 unmethylated cases
    }
)


SKILL_NAME = "cis-feature-coherence"
SKILL_VERSION = "1.5.0"  # 1.5.0 (2026-09-12): cis-dosage DIRECTION (amplification_coupled vs deletion_coupled + its basis) and the LINEAGE-controlled provenance (within-lineage deltas, lineage_collapse_ratio, deleted arm) surfaced into the headline / synthesis facet / provenance / causal-attribution caveat; new verdict coherent_cis_loss_of_function (resolver v1.3.0) gets its own phrase + its own confidence tier (cis_loss_of_function_not_a_direct_inhibition_target) and the silencing_lineage_confounded third state is narrated as "measured, not interpretable" rather than absent. Still VERDICT-INERT.   # 1.4.0 (2026-09-04): --literature lane (make_literature_fn one-liner) + VERDICT-INERT cis-coherence CONFIDENCE surface (cis_coherence_confidence_caveat 3-tier [statistical_cis_correlation_causally_unconfirmed / amplicon_passenger_or_lineage_confounded / validated_cis_driver_or_silencing false-demote guard] + causal_attribution_caveat + context_generalization_caveat + cis_coherence_provenance) + CIS_FEATURE_COHERENCE thesis/polarity_note. Gates on already-emitted headline fields; cis_coherence_verdict + driving_rule_id + resolver golden + replay byte-stable.   # 1.3.0 (2026-08-28): PROTEIN legs (cis-feature-protein-coherence CN→protein + abundance-dependency protein→dep) + mRNA-vs-protein dosage slope ratio. VERDICT-INERT.   # 1.2.0 (2026-08-28): capsule-driven narrator via generic engine.

CARDS = [
    "cis-feature-expression-coherence",  # GoF leg-1: CN → own-expression cis-dosage (amplification, mRNA)
    "cis-feature-protein-coherence",  # GoF leg-1 (PROTEIN): CN → own-PROTEIN cis-dosage. The slope
    # RATIO vs the mRNA leg separates dosage-SENSITIVE cis-drivers
    # (ERBB2/MYC/MDM2) from dosage-BUFFERED passengers. VERDICT-INERT
    # (fires no cis_coherence rule → verdict byte-stable).
    "cellline-methylation-expression-coherence",  # LoF leg-1: promoter methylation → own LOW expression (silencing)
    "expression-dependency-correlation",  # leg-2 (reuse): expression → dependency
    "abundance-dependency",  # leg-2 (PROTEIN reuse): protein abundance → dependency. Borrowed
    # from the dependency axis; the protein sibling of the RNA leg-2.
    # VERDICT-INERT here (fires no cis_coherence rule).
    "amp-expr-stratified-dependency",  # leg-2 (reuse): conjoint amp∩overexpr dependency
    "patient-cis-coherence",  # VERDICT-INERT patient (TCGA) corroboration facet — fires NO
    # cis_coherence rule (verdict byte-stable); surfaced in the headline
    # as cross-grain agreement (does the cell-line call replicate in patients?)
    # ── MOLECULAR-FORM facet (1) — VERDICT-INERT display (R10 homing 2026-08-20) ──────────────
    # WHICH transcript of the target is expressed — molecular-FORM context for the cis read (a specific
    # dominant isoform can change which transcript the CN→expression coupling acts on). Cell-line grain
    # (DepMap), matching this skill. Fire NO cis_coherence rule → verdict byte-stable. Previously orphaned
    # (created by #424, consumed by no skill); homed here rather than presence (no molecular-form bucket in
    # its measurement×sample_context taxonomy) or target-intrinsic (excludes cell-line observations).
    # (The duplicate cellline-isoform-dominance was consolidated into this card 2026-09-10 — #704 6b.)
    "cellline-isoform-expression",
]

QUESTION = (
    "Does {target}'s own locus feature (copy-number) explain its own expression AND its own "
    "dependency in {indication} — a coherent cis-driven addiction, or co-occurring axes?"
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """cis_coherence_verdict from the SHARED declarative resolver (cis_coherence.resolver.yaml).

    resolve_or_raise reads resolvers/cis_coherence.resolver.yaml (target-contracts) and evaluates the
    ordered 2×2 cross-tab against the fired cis-coherence rule set. Single source of truth — the ladder
    lives in the YAML (validated + golden-tested there), not re-encoded here."""
    return resolve_or_raise(fired, "cis_coherence")


# ── FACTORED-RECORD SHADOW (M1) — the CIS-COHERENCE per-axis builder. DESCRIPTIVE / non-gating: it
#    reads out whether the locus→expression→dependency chain is coherent. A coherent-driver call
#    SUPPORTS the thesis; the other measured patterns are informational (neutral). VERDICT-INERT:
#    surfaced by the fan-out into decision.claim_record_shadow.cis_coherence, consumed by NOTHING.
#    No verdict-disjoint corroborator → minimal coverage-only certainty. Mirrors the other axes' hook.
_CIS_COHERENT = {"coherent_cis_driver", "coherent_epigenetic_silencing"}


def _cis_availability(v) -> str:
    if v is None:
        return "not_wired"
    if v == "insufficient_cis_coherence":
        return "insufficient"
    return "measured_positive"  # a measured coherence pattern


def _cis_certainty(v) -> dict:
    if v is None:
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    if v == "insufficient_cis_coherence":
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 0.5}
    return {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    coherent = v in _CIS_COHERENT
    return assemble_claim_record(
        axis="cis_coherence",
        state=(v or "insufficient_cis_coherence"),
        direction=("supports" if coherent else "neutral"),
        availability=_cis_availability(v),
        magnitude={"level": ("moderate" if coherent else "none")},
        certainty=_cis_certainty(v),
        fired=fired,
        cards=cards,
    )


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# cis-feature-coherence's declaration for the shared headline_core builder: the four coherence-LEG claim
# axes (CIS_DOSAGE / SILENCING / EXPR_DEP / CONJOINT), the cis_coherence-verdict vocabulary → human
# phrase, and the cross-grain PATIENT-disagreement caveat as the skill-specific tension source.
# Verdict-INERT — a one-way projection over the already-computed headline (the cis_coherence spine stays
# byte-stable, frozen by test_verdict.py + the target-contracts resolver golden). The cis_coherence
# verdict is a 2×2 INTERACTION owned by the resolver; the claim_vector axes are its LEG decomposition.
#
# POLARITY (colours the hero badge). This skill is VERDICT-INERT / coherence-CLASSIFYING — every class
# is a description of the locus→expression→dependency coherence pattern, not a drug call, so the DEFAULT
# is neutral. The one clearly FAVORABLE class is `coherent_cis_driver` (CN explains expression AND
# expression explains dependency — a coherent cis-driven oncogene addiction, the amplification-addiction
# signal that supports the target). No class is a clear UNfavorable call (an inert/uncoupled read is
# informative, not adverse), so everything else stays neutral.
_CIS_COHERENCE_VERDICT_PHRASE = {
    "coherent_cis_driver": "Coherent cis-driven addiction (amplification → expression → dependency)",
    "coherent_epigenetic_silencing": "Coherent epigenetic silencing (promoter methylation → low expression)",
    "coherent_cis_loss_of_function": "Coherent cis loss-of-function (deletion → low expression, not required)",
    "expressed_cis_coupled_inert": "Expressed via cis-dosage, but dependency-inert",
    "dependency_without_cis_dosage": "Dependency without cis-dosage coupling (trans-regulated)",
    "cis_uncoupled_no_dependency": "Cis-uncoupled, no dependency",
    "insufficient_cis_coherence": "Insufficient cis-coherence evidence",
}

_CIS_COHERENCE_FAVORABLE = frozenset({"coherent_cis_driver"})


def _cis_coherence_verdict_polarity(v) -> str:
    """The skill's OWN reading of the coherence class (colours the hero badge; never a gate). VERDICT-INERT
    coherence-classifying skill → neutral by default; the one clearly FAVORABLE call is coherent_cis_driver
    (a coherent cis-driven oncogene addiction). No class is a clear UNfavorable drug call, so everything
    else stays neutral."""
    return "positive" if v in _CIS_COHERENCE_FAVORABLE else "neutral"


def _cis_tension_extra(headline: dict):
    """The sharpest cis-coherence caveat that is NOT already a per-axis claim conflict (the wrong-direction
    positive_anomaly / amp_expr_negative reads are surfaced by headline_core.rank_tension as claim
    conflicts): the cross-grain PATIENT arm DISAGREES with the cell-line call — the TCGA patient tumours do
    NOT replicate the cell-line cis-dosage (or methylation-silencing) coupling, a real corroboration
    failure. Severity 2 (below a wrong-direction conflict on a strong claim, which can reach 3, so that
    still wins the single slot). None when the patient arm agrees or was not measured."""
    if headline.get("patient_dosage_agrees_with_cellline") is False:
        return {
            "text": (
                "the cell-line cis-dosage coupling is NOT replicated in the TCGA patient arm (cross-grain disagreement)"
            ),
            "source": "patient_dosage_agrees_with_cellline",
            "severity": 2,
        }
    if headline.get("patient_silencing_agrees_with_cellline") is False:
        return {
            "text": (
                "the cell-line methylation-silencing coupling is NOT replicated in the TCGA "
                "patient arm (cross-grain disagreement)"
            ),
            "source": "patient_silencing_agrees_with_cellline",
            "severity": 2,
        }
    return None


_CIS_COHERENCE_HEADLINE_SPEC = HeadlineSpec(
    gate="cis_coherence",
    axis_labels={
        "CIS_DOSAGE": "CN→expression cis-dosage",
        "SILENCING": "methylation→low-expression",
        "EXPR_DEP": "expression→dependency",
        "CONJOINT": "amp∩overexpr addiction",
    },
    axis_keys=("CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"),
    critical_axes=("EXPR_DEP",),  # EXPR_DEP (does expression explain dependency?) is THE decision-critical
    # leg — without it the CN→expression coupling is abundance, not addiction.
    verdict_label=lambda v: _CIS_COHERENCE_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_cis_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed cis-coherence headline. Reads the
    resolved cis_coherence_verdict + the verdict-inert claim_vector / key_signals; never moves the spine.
    No CERTAINTY_MODEL sidecar is emitted by this skill, so confidence is derived from the claim vector's
    corroboration (which draws on the cross-grain TCGA patient-agreement arm — a real second leg)."""
    v = headline.get("cis_coherence_verdict")
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_CIS_COHERENCE_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=_cis_coherence_verdict_polarity(v),
    )


def _slope_ratio(protein_slope, mrna_slope):
    """mRNA-vs-protein dosage-buffering ratio = protein_slope / mrna_slope (VERDICT-INERT fingerprint).

    ~1 → the CN dosage-effect is preserved at the protein level = a genuinely dosage-sensitive cis-driver
    (ERBB2/MYC/MDM2); ≪1 → protein is post-transcriptionally BUFFERED (mRNA rises with CN, protein does
    not). None when either slope is missing or the mRNA slope is ~0 (ratio undefined / uninformative)."""
    if protein_slope is None or mrna_slope is None:
        return None
    if abs(mrna_slope) < 1e-6:
        return None
    return round(float(protein_slope) / float(mrna_slope), 4)


# ══ VERDICT-INERT cis-coherence CONFIDENCE surface (v1.4.0) ══════════════════════════════════════
# The cis analog of surface_confirmation_caveat / mechanism_confirmation_caveat / cooccurrence_confidence_
# caveat: a STATISTICAL cis-correlation (CN↔mRNA / methylation↔expression / expression↔dependency) OVER-
# CALLS a CAUSAL, dosage-driven, cell-intrinsic cis-DRIVER addiction. Gates on already-emitted headline
# fields; NEVER feeds the resolver → cis_coherence_verdict + driving_rule_id + resolver golden + replay
# stay byte-stable. SET literals (NOT 2-string tuples — the reference-drift guard misreads a 2-tuple as a
# (rule_id, verdict) precedence tuple).

# Canonical, functionally-VALIDATED cis-drivers / targeted-silencing genes = the false-demote guard set.
# A coherent call for one of these is the GROUND TRUTH the trap is calibrated AGAINST, not the over-call,
# so it is spared even when its own protein-dosage slope reads BUFFERED (ERBB2 itself lands
# prot_dosage_uncoupled by rank-noise in DepMap despite being the validated 17q12 driver — the card's own
# caveat + Gonçalves 2017 PMID 29032074). Gene-level (a canonical amplicon driver / silenced tumour
# suppressor is canonical in ANY indication).
_VALIDATED_CIS_DRIVER_AMP = frozenset(
    {
        "ERBB2",
        "MYCN",
        "MDM2",
        "MDM4",
        "CCND1",
        "CCNE1",
        "MET",
        "EGFR",
        "FGFR1",
        "FGFR2",
        "KIT",
        "CDK4",
    }
)
_VALIDATED_SILENCING = frozenset(
    {
        "MLH1",
        "MGMT",
        "CDKN2A",
        "CDKN2B",
        "MSH2",
        "BRCA1",
        "RB1",
        "VHL",
        "PTEN",
    }
)
# CIMP / global-hypermethylation LINEAGE contexts — where a promoter-methylation↔low-expression correlation
# for a NON-guarded gene can be a passenger of the coordinate lineage program (BRAF-CIMP colorectal,
# IDH-G-CIMP glioma, gastric-/endometrial-CIMP), not a targeted silencing of THIS gene.
_CIMP_LINEAGE_INDICATIONS = frozenset(
    {
        "COADREAD",
        "COAD",
        "READ",
        "STAD",
        "GBM",
        "LGG",
        "UCEC",
        "ESCA",
        "EGC",
    }
)
# The two COHERENT positive verdicts the over-call caveat applies to (the uncoupled / inert / insufficient
# classes carry no coherent-cis-driver over-call to flag).
_CIS_COHERENT_POSITIVE = frozenset({"coherent_cis_driver", "coherent_epigenetic_silencing"})
# The coherent LoF verdict (resolver v1.3.0): deletion-coupled expression WITHOUT a dependency leg. Coherent,
# but its over-call is a DIFFERENT one — a deletion→low-mRNA coupling is partly MECHANICAL gene dosage, and
# the read is an SL / re-expression hypothesis, never a direct-inhibition target. Its own caveat tier below.
_CIS_COHERENT_LOF = frozenset({"coherent_cis_loss_of_function"})
# cis_dosage_direction_basis (card v1.1.0) whose direction call is INFERRED from the CN distribution's shape
# rather than measured as an amplified-vs-deleted expression contrast → provisional, quote it as such.
_WEAK_DIRECTION_BASIS = frozenset({"cn_distribution_asymmetry"})
# Protein-dosage class read as BUFFERED (CN varies but protein flat = the co-amplified-passenger fingerprint).
_PROT_BUFFERED = frozenset({"prot_dosage_uncoupled"})
# expression→dependency correlation classes that count as a COHERENT dependency leg (negative Chronos
# correlation = higher expression ⇒ more dependent).
_EXPR_DEP_COHERENT = frozenset({"strong_negative", "moderate_negative", "weak_negative"})


def _norm_ind(indication) -> str:
    return (indication or "").upper().strip()


def _cis_lof_caveat(hl: dict, target=None) -> dict:
    """The coherent-cis-LOSS-OF-FUNCTION tier (verdict coherent_cis_loss_of_function, resolver v1.3.0).
    ALWAYS fires when that verdict is reached — unlike the driver/silencing tiers there is no configuration
    of this verdict that is an honest direct-inhibition positive, because the verdict itself is defined by a
    DELETION-coupled expression drop with NO dependency leg. Milder tier: it is not a demotion of a positive
    call, it is a re-framing of what the coherence means (SL / re-expression hypothesis)."""
    gene = (target or "").upper().strip()
    basis = hl.get("cis_dosage_direction_basis")
    return {
        "reason": "cis_loss_of_function_not_a_direct_inhibition_target",
        "tier": "milder",
        "false_demote_guarded": False,
        "cis_dosage_direction": hl.get("cis_dosage_direction"),
        "cis_dosage_direction_basis": basis,
        "direction_basis_is_provisional": basis in _WEAK_DIRECTION_BASIS,
        "deleted_subset_delta_log2tpm": hl.get("deleted_subset_delta_log2tpm"),
        "deleted_within_lineage_delta_log2tpm": hl.get("deleted_within_lineage_delta_log2tpm"),
        "n_deleted": hl.get("n_deleted"),
        "detail": (
            f"{gene or 'the target'} is DELETION-coupled (loss of the locus tracks LOW expression) with no "
            "expression→dependency leg — coherent, but a LOSS-of-function statement: the therapeutic reading "
            "is synthetic lethality against the loss, or re-expression, NOT inhibition of this target "
            "(recurrent deletions mark tumour suppressors, Beroukhim 2010 PMID 20164920; Zack 2013 PMID "
            "24071852; two-hit inactivation Knudson 1971 PMID 5279523). Two specific over-reads to avoid: "
            "(a) part of the expression drop is MECHANICAL gene dosage (one fewer copy ⇒ less mRNA), so a "
            "coupled CN↔mRNA slope is not by itself evidence of functional silencing or of biallelic loss — "
            "confirm the second hit (mutation / methylation / LOH); (b) the ABSENT dependency leg is expected "
            "here and is not evidence the gene is dispensable in tumours that RETAIN it. The direction call's "
            f"basis is cis_dosage_direction_basis={basis}"
            + (
                " — inferred from the CN distribution's asymmetry rather than a measured amplified-vs-deleted "
                "contrast, so treat the direction itself as provisional."
                if basis in _WEAK_DIRECTION_BASIS
                else " (a measured amplified-vs-deleted expression contrast)."
            )
        ),
    }


def _cis_coherence_confidence_caveat(hl: dict, target=None, indication=None) -> dict | None:
    """CONSOLIDATED statistical-vs-causal cis-coherence confidence call (VERDICT-INERT). A coherent cis-DRIVER
    / targeted-SILENCING call resting on a STATISTICAL correlation WITHOUT causal / protein-dosage / patient
    confirmation. Fires ONLY on the two COHERENT positive verdicts; the uncoupled / inert / insufficient
    classes → None (byte-stable negative path). Precedence: (iii) MILDER validated-guard FIRST (a canonical
    cis-driver / silencing is never demoted, even with a buffered protein slope) > (ii) SHARP amplicon-
    passenger / CIMP-lineage confound > (i) SHARP statistical-correlation-causally-unconfirmed > None.

    coherent_cis_loss_of_function (resolver v1.3.0) is coherent too, but its over-call is a different claim
    entirely, so it gets its OWN tier ahead of the driver/silencing ladder rather than being folded into a
    text written about amplification addiction."""
    v = hl.get("cis_coherence_verdict")
    if v in _CIS_COHERENT_LOF:
        return _cis_lof_caveat(hl, target=target)
    if v not in _CIS_COHERENT_POSITIVE:
        return None
    gene = (target or "").upper().strip()
    ind = _norm_ind(indication)
    is_driver = v == "coherent_cis_driver"
    is_silencing = v == "coherent_epigenetic_silencing"

    # TIER (iii) MILDER — validated false-demote guard. OUTRANKS the data cautions: a canonical validated
    # cis-driver (ERBB2/MYCN/MDM2/CCND1 amp) or targeted silencing (MLH1/MGMT/CDKN2A) is the ground truth the
    # trap is calibrated against, NOT the over-call — spared even if its protein-dosage slope reads buffered.
    if (is_driver and gene in _VALIDATED_CIS_DRIVER_AMP) or (is_silencing and gene in _VALIDATED_SILENCING):
        kind = "cis-driver amplification" if is_driver else "targeted epigenetic silencing"
        return {
            "reason": "validated_cis_driver_or_silencing",
            "tier": "milder",
            "false_demote_guarded": True,
            "detail": (
                f"{gene} is a canonical, functionally-validated {kind} — the ground truth the "
                "co-amplified-passenger / CIMP-confound trap is calibrated against, NOT an over-call; "
                "explicitly NOT demoted even if its protein-dosage slope reads attenuated (ERBB2 "
                "itself lands prot_dosage_uncoupled by rank-noise in DepMap yet is the validated "
                "17q12 driver — Gonçalves 2017 PMID 29032074; Slamon 2001 PMID 11248153). Silencing "
                "arm validated by biallelic-silencing / demethylation rescue + downstream phenotype "
                "(MLH1→MSI Veigl 1998 PMID 9671741; MGMT→temozolomide Hegi 2005 PMID 15758010)."
            ),
        }

    # TIER (ii) SHARP — amplicon-passenger / CIMP-lineage confound.
    if is_driver:
        # a dosage-BUFFERED / uncoupled protein slope in a focal-amplicon coherent_cis_driver = co-amplified
        # passenger (mRNA scales with CN, protein does not) — the built-in discriminator.
        prot_cls = hl.get("cis_protein_dosage_class")
        ratio = hl.get("mrna_vs_protein_dosage_slope_ratio")
        buffered = (prot_cls in _PROT_BUFFERED) or (isinstance(ratio, (int, float)) and ratio < 0.5)
        if buffered:
            return {
                "reason": "amplicon_passenger_or_lineage_confounded",
                "tier": "sharp",
                "false_demote_guarded": False,
                "detail": (
                    f"{gene or 'the target'} reads coherent_cis_driver off a CN↔mRNA coupling, but its "
                    f"PROTEIN dosage slope is BUFFERED (cis_protein_dosage_class={prot_cls}, "
                    f"mRNA-vs-protein slope ratio={ratio}): the discriminator of a CO-AMPLIFIED "
                    "PASSENGER in a focal driver amplicon (mRNA up, protein flat) vs a dosage-"
                    "SENSITIVE driver that scales at both (Gonçalves 2017 PMID 29032074; Schukken "
                    "2022 PMID 35701073). Confirm the gene is not merely flanking the amplicon's real "
                    "driver (17q12/ERBB2 → GRB7/STARD3/MIEN1; 8q24/MYC; 11q13/CCND1 — the RNAi "
                    "driver-vs-passenger test Kao & Pollack 2006 PMID 16708353; Sanchez-Garcia 2014 "
                    "PMID 25433701)."
                ),
            }
    if is_silencing and gene not in _VALIDATED_SILENCING and ind in _CIMP_LINEAGE_INDICATIONS:
        return {
            "reason": "amplicon_passenger_or_lineage_confounded",
            "tier": "sharp",
            "false_demote_guarded": False,
            "detail": (
                f"{gene or 'the target'} reads coherent_epigenetic_silencing in {ind}, a CIMP / "
                "global-hypermethylation LINEAGE (BRAF-CIMP colorectal / IDH-G-CIMP glioma / gastric-"
                "CIMP): a single promoter's methylation↔low-expression correlation can be a PASSENGER "
                "of the coordinate lineage program (driven by BRAF/IDH), or a consequence of "
                "pre-existing lineage repression, not a targeted silencing of THIS gene (Weisenberger "
                "2006 PMID 16804544; Turcan 2012 PMID 22343889; Sproul 2011 PMID 21368160). Needs the "
                "global-methylation-burden covariate + functional causality to call targeted."
            ),
        }

    # TIER (i) SHARP — a coherent call whose CAUSAL confirmation legs are thin: no protein-dosage confirmation
    # (protein leg data_unavailable / uninformative) AND the patient arm does not corroborate.
    prot_measured = hl.get("cis_protein_dosage_class") not in (None, "data_unavailable")
    patient_agrees = (
        hl.get("patient_dosage_agrees_with_cellline") is True
        or hl.get("patient_silencing_agrees_with_cellline") is True
    )
    if not prot_measured and not patient_agrees:
        return {
            "reason": "statistical_cis_correlation_causally_unconfirmed",
            "tier": "sharp",
            "false_demote_guarded": False,
            "detail": (
                "The coherence call rests on a STATISTICAL cis-correlation without causal / protein-"
                "dosage / patient confirmation (protein-dosage leg data_unavailable and the TCGA "
                "patient arm does not corroborate) — correlation ≠ causation; a bulk CN↔expr or "
                "immortalized-2D DepMap expr↔dep correlation is a HYPOTHESIS flag, not a proven cell-"
                "intrinsic cis-driver (Pollack 2002 PMID 12297621). The causal driver may be trans / "
                "enhancer-regulated (e.g. MYC/CRC via WNT + the 8q24 enhancer, NOT copy-number — He "
                "1998 PMID 9727977; Sur 2012 PMID 23118011)."
            ),
        }
    # A coherent call WITH protein-dosage confirmation or patient corroboration → honest positive, no caveat.
    return None


def _causal_attribution_caveat(hl: dict) -> dict | None:
    """Correlation ≠ causation for the CIS-DOSAGE leg (VERDICT-INERT), always surfaced when a CN→mRNA
    cis-coupling is present. Names the mRNA-vs-protein dosage SLOPE RATIO (dosage-sensitive driver vs
    dosage-buffered passenger) + focal-vs-broad amplicon. Fires whenever cis_dosage_class is coupled; None on
    an uncoupled / unmeasured cis-dosage leg (no cis-coupling to attribute) → byte-stable."""
    if not (hl.get("cis_dosage_class") or "").startswith("cn_dosage_coupled"):
        return None
    basis = hl.get("cis_dosage_direction_basis")
    return {
        "cis_dosage_driver": hl.get("cis_dosage_driver"),
        # WHICH CN arm carries the coupling (card v1.1.0) + how that was established. Reported alongside the
        # correlational caveat because a direction read off the CN distribution's SHAPE
        # (cn_distribution_asymmetry) is weaker evidence than a measured amplified-vs-deleted contrast, and
        # the LINEAGE-controlled within-lineage delta is what separates cis dosage from lineage separation.
        "cis_dosage_direction": hl.get("cis_dosage_direction"),
        "cis_dosage_direction_basis": basis,
        "direction_basis_is_provisional": basis in _WEAK_DIRECTION_BASIS,
        "subset_within_lineage_delta_log2tpm": hl.get("subset_within_lineage_delta_log2tpm"),
        "subset_n_lineages_compared": hl.get("subset_n_lineages_compared"),
        "amplified_dominant_lineage_fraction": hl.get("amplified_dominant_lineage_fraction"),
        "mrna_vs_protein_dosage_slope_ratio": hl.get("mrna_vs_protein_dosage_slope_ratio"),
        "cis_protein_dosage_class": hl.get("cis_protein_dosage_class"),
        "cn_expr_slope_log2tpm_per_cn": hl.get("cn_expr_slope_log2tpm_per_cn"),
        "cn_prot_slope_log2abundance_per_cn": hl.get("cn_prot_slope_log2abundance_per_cn"),
        "relative_cn_iqr": hl.get("relative_cn_iqr"),
        "detail": (
            "cis-dosage coupling is CORRELATIONAL, not a formal mediation test: a CN↔mRNA coupling can "
            "be a co-amplified neighbour or a shared trans-regulator, not causal cis-dosage. The mRNA-vs-"
            "protein dosage SLOPE RATIO is the discriminator — ~1 = dosage-SENSITIVE driver (CN raises "
            "both mRNA and protein, ERBB2-like), ≪1 = post-transcriptionally BUFFERED passenger (mRNA "
            "up, protein flat; Gonçalves 2017 PMID 29032074). A FOCAL amplicon peak (GISTIC) localizes "
            "the driver far better than a broad/arm-level segment (Zack 2013 PMID 24071852; Mermel 2011 "
            "PMID 21527027); relative_cn_iqr indexes the CN amplitude available to test dosage. DIRECTION "
            "is part of the claim: cis_dosage_direction says which arm carries the coupling, and only "
            "amplification_coupled supports a gain-driven addiction reading — deletion_coupled is a "
            "loss-of-function statement. The other confound is LINEAGE: a pan-panel amplified-vs-neutral "
            "gap can simply be the lineages that carry the amplicon also being the lineages that express "
            "the gene, so subset_within_lineage_delta_log2tpm (the same contrast computed WITHIN lineage) "
            "is the one that has to survive; amplified_dominant_lineage_fraction indexes how concentrated "
            "the amplified group is in a single lineage."
        ),
    }


def _context_generalization_caveat(hl: dict) -> dict | None:
    """bulk / purity ≠ cell-intrinsic + cell-line ≠ patient (VERDICT-INERT). The CN↔expr + expr↔dep legs are
    bulk / immortalized-2D DepMap reads; the patient-cis-coherence facet is the corroboration. Fires on any
    measured cis-dosage or methylation-silencing coupling; None when neither leg is coupled → byte-stable."""
    coupled = (hl.get("cis_dosage_class") or "").startswith("cn_dosage_coupled")
    silenced = (hl.get("methylation_silencing_class") or "").startswith("silencing_coupled")
    if not (coupled or silenced):
        return None
    return {
        "cis_dosage_evidence_scope": hl.get("cis_dosage_evidence_scope"),
        "patient_dosage_agrees_with_cellline": hl.get("patient_dosage_agrees_with_cellline"),
        "patient_silencing_agrees_with_cellline": hl.get("patient_silencing_agrees_with_cellline"),
        "patient_n_cases_expression": hl.get("patient_n_cases_expression"),
        "detail": (
            "The CN↔expression and expression↔dependency legs are BULK / immortalized-2D DepMap reads: a "
            "bulk CN↔expr correlation can be tumor-PURITY / whole-segment-CN driven (Aran 2015 PMID "
            "26634437; Yoshihara 2013 PMID 24113773), and cell-line coherence is necessary but NOT "
            "sufficient for a PATIENT cis-driver claim. The patient-cis-coherence facet (TCGA CN + "
            "methylation joined to patient expression) is the corroboration — read "
            "patient_dosage_agrees_with_cellline / patient_silencing_agrees_with_cellline. A "
            "cis_dosage_evidence_scope of pan_no_indication means the cis-dosage slope is a PAN-cancer "
            "read, not indication-specific."
        ),
    }


def _cis_coherence_provenance(hl: dict, target=None, indication=None) -> dict | None:
    """QUORUM / PROVENANCE summary for the cis-coherence call (VERDICT-INERT): which legs are coherent
    (CN→mRNA / CN→protein / meth→expr / expr→dep / conjoint), the mRNA-vs-protein slope ratio, amplicon
    amplitude, patient-corroboration presence, lineage breadth, and the curated validated / CIMP flags. None
    when the verdict is insufficient (no coherence chain to summarize) → byte-stable negative path."""
    v = hl.get("cis_coherence_verdict")
    if v in (None, "insufficient_cis_coherence"):
        return None
    gene = (target or "").upper().strip()
    ind = _norm_ind(indication)
    meth_cls = hl.get("methylation_silencing_class")
    legs_coherent = {
        "cn_to_mrna": (hl.get("cis_dosage_class") or "").startswith("cn_dosage_coupled"),
        "cn_to_protein": (hl.get("cis_protein_dosage_class") or "").startswith("prot_dosage_coupled"),
        "methylation_to_expression": (hl.get("methylation_silencing_class") or "").startswith("silencing_coupled"),
        "expression_to_dependency": hl.get("expression_dependency_correlation_class") in _EXPR_DEP_COHERENT,
        "conjoint_amp_overexpr": (hl.get("amp_expr_stratification_class") or "").startswith("amplified_overexpressed"),
    }
    return {
        "cis_coherence_verdict": v,
        "n_legs_coherent": sum(1 for x in legs_coherent.values() if x),
        "legs_coherent": legs_coherent,
        "cis_dosage_driver": hl.get("cis_dosage_driver"),
        # DIRECTION of the CN→mRNA leg + how it was established (card v1.1.0). A coherent chain that does not
        # say WHICH arm carries it is the collapse resolver v1.3.0 closed, so the provenance names it.
        "cis_dosage_direction": hl.get("cis_dosage_direction"),
        "cis_dosage_direction_basis": hl.get("cis_dosage_direction_basis"),
        "direction_basis_is_provisional": hl.get("cis_dosage_direction_basis") in _WEAK_DIRECTION_BASIS,
        "subset_within_lineage_delta_log2tpm": hl.get("subset_within_lineage_delta_log2tpm"),
        # THIRD state of the silencing leg (card v1.1.0): a large pan-panel contrast that COLLAPSES within
        # lineage. Not a silencing claim and not a refutation of one — recorded so it cannot be laundered
        # into coherent_epigenetic_silencing, and so `legs_coherent.methylation_to_expression: false` above
        # is readable as "confounded", not "tested and negative".
        "methylation_lineage_confounded": meth_cls == "silencing_lineage_confounded",
        "lineage_collapse_ratio": hl.get("lineage_collapse_ratio"),
        "mrna_vs_protein_dosage_slope_ratio": hl.get("mrna_vs_protein_dosage_slope_ratio"),
        "cis_protein_dosage_class": hl.get("cis_protein_dosage_class"),
        "relative_cn_iqr": hl.get("relative_cn_iqr"),
        "n_amplified": hl.get("n_amplified"),
        "cis_dosage_evidence_scope": hl.get("cis_dosage_evidence_scope"),
        "patient_dosage_agrees_with_cellline": hl.get("patient_dosage_agrees_with_cellline"),
        "patient_silencing_agrees_with_cellline": hl.get("patient_silencing_agrees_with_cellline"),
        "validated_cis_driver_flag": gene in _VALIDATED_CIS_DRIVER_AMP,
        "validated_silencing_flag": gene in _VALIDATED_SILENCING,
        "cimp_lineage_indication_flag": ind in _CIMP_LINEAGE_INDICATIONS,
    }


def _headline(cards, fired, verdict_pair, target=None, indication=None):
    def _s(cid):
        return card_summary(cards, cid)

    cis = _s("cis-feature-expression-coherence")  # GoF leg-1 (mRNA)
    prot = _s("cis-feature-protein-coherence")  # GoF leg-1 (PROTEIN) — verdict-inert
    meth = _s("cellline-methylation-expression-coherence")  # LoF leg-1
    corr = _s("expression-dependency-correlation")  # leg-2 (correlation)
    abdep = _s("abundance-dependency")  # leg-2 (PROTEIN) — verdict-inert
    ampx = _s("amp-expr-stratified-dependency")  # leg-2 (conjoint)
    pat = _s("patient-cis-coherence")  # VERDICT-INERT patient (TCGA) corroboration

    # Cross-grain agreement (verdict-inert confidence signal): does the patient tumour arm replicate the
    # cell-line call? Directional only (thresholds differ across grains) — None when either grain is unmeasured.
    _cl_coupled = (cis.get("cis_dosage_class") or "").startswith("cn_dosage_coupled")
    _pt_coupled = (pat.get("patient_cis_dosage_class") or "").startswith("cn_dosage_coupled")
    _cl_silenced = (meth.get("methylation_silencing_class") or "").startswith("silencing_coupled")
    _pt_silenced = pat.get("patient_methylation_silencing_class") == "epigenetic_silencing"
    _pt_measured = (
        bool(pat.get("patient_cis_dosage_class")) and pat.get("patient_cis_dosage_class") != "data_unavailable"
    )
    dosage_agreement = (_cl_coupled == _pt_coupled) if (_pt_measured and cis.get("cis_dosage_class")) else None
    silencing_agreement = (
        (_cl_silenced == _pt_silenced)
        if (
            pat.get("patient_methylation_silencing_class") not in (None, "insufficient_methylation_data")
            and meth.get("methylation_silencing_class") not in (None, "data_unavailable")
        )
        else None
    )

    verdict, driving = verdict_pair
    hl = {
        "cis_coherence_verdict": verdict,
        "driving_rule_id": driving,
        # LoF leg-1: promoter methylation → own LOW expression (epigenetic silencing)
        "methylation_silencing_class": meth.get("methylation_silencing_class"),
        "methylation_silencing_driver": meth.get("silencing_driver"),
        "methylation_subset_median_delta_log2tpm": meth.get("subset_median_delta_log2tpm"),
        "n_hypermethylated": meth.get("n_hypermethylated"),
        # LINEAGE-CONTROLLED silencing provenance (card v1.1.0). The pan-panel hypermethylated-vs-rest
        # contrast is confounded by lineage — CDH1 -4.44 pan → -0.45 within lineage, MET -4.99 → -0.85 — so
        # the reader now also emits the within-lineage delta and the collapse RATIO (within/pan). A ratio
        # below the card's max_lineage_collapse_ratio is the silencing_lineage_confounded class.
        "methylation_subset_within_lineage_delta_log2tpm": meth.get("subset_within_lineage_delta_log2tpm"),
        "methylation_subset_n_lineages_compared": meth.get("subset_n_lineages_compared"),
        "hypermethylated_dominant_lineage_fraction": meth.get("hypermethylated_dominant_lineage_fraction"),
        "lineage_collapse_ratio": meth.get("lineage_collapse_ratio"),
        "broad_quartile_delta_log2tpm": meth.get("broad_quartile_delta_log2tpm"),
        "broad_quartile_within_lineage_delta_log2tpm": meth.get("broad_quartile_within_lineage_delta_log2tpm"),
        # GoF leg-1: feature → own-expression (the new measurement)
        "cis_dosage_class": cis.get("cis_dosage_class"),
        # which path established a coupled call: pan_panel_correlation | focal_amplification_subset. The
        # focal_amplification_subset driver marks a focal-amp oncogene (ERBB2) whose pan-panel Spearman is
        # diluted below the moderate gate but whose amplified subset over-expresses — a cis-DRIVER read the
        # bare rank-correlation would have under-called as cn_dosage_uncoupled (calibration 2026-09-12).
        "cis_dosage_driver": cis.get("cis_dosage_driver"),
        "cn_expr_spearman_r": cis.get("cn_expr_spearman_r"),
        "cn_expr_spearman_p": cis.get("cn_expr_spearman_p"),
        "cn_expr_slope_log2tpm_per_cn": cis.get("cn_expr_slope_log2tpm_per_cn"),
        "relative_cn_iqr": cis.get("relative_cn_iqr"),
        "delta_log2tpm_amplified_vs_neutral": cis.get("delta_log2tpm_amplified_vs_neutral"),
        "subset_delta_log2tpm_amplified_vs_neutral": cis.get("subset_delta_log2tpm_amplified_vs_neutral"),
        "n_amplified": cis.get("n_amplified"),
        "cis_dosage_evidence_scope": cis.get("evidence_scope"),
        # leg-1 DIRECTION (card v1.1.0) — which CN arm carries the coupling, and how that was established.
        # cis_dosage_class alone cannot separate an ERBB2-class amplicon from a PTEN-class deleted
        # suppressor; the resolver (v1.3.0) needs the direction token, so the headline must carry it.
        # amplified_vs_deleted_contrast = measured on both arms; cn_distribution_asymmetry = the fallback
        # read off the CN distribution's shape when one arm is underpowered → PROVISIONAL.
        "cis_dosage_direction": cis.get("cis_dosage_direction"),
        "cis_dosage_direction_basis": cis.get("cis_dosage_direction_basis"),
        # LINEAGE-CONTROLLED dosage provenance: the amplified-vs-neutral contrast recomputed WITHIN lineage
        # (the focal-amplification escape now has to survive it) + how concentrated the amplified group is.
        "subset_within_lineage_delta_log2tpm": cis.get("subset_within_lineage_delta_log2tpm"),
        "subset_n_lineages_compared": cis.get("subset_n_lineages_compared"),
        "amplified_dominant_lineage_fraction": cis.get("amplified_dominant_lineage_fraction"),
        # the DELETED arm (card v1.1.0) — the other half of the direction contrast
        "n_deleted": cis.get("n_deleted"),
        "deleted_subset_delta_log2tpm": cis.get("deleted_subset_delta_log2tpm"),
        "deleted_within_lineage_delta_log2tpm": cis.get("deleted_within_lineage_delta_log2tpm"),
        "deleted_subset_mannwhitney_p": cis.get("deleted_subset_mannwhitney_p"),
        # GoF leg-1 (PROTEIN): CN → own-PROTEIN cis-dosage (VERDICT-INERT). The mRNA-vs-protein slope
        # RATIO is the dosage-buffering fingerprint: ~1 = dosage-sensitive cis-driver (CN raises both
        # mRNA and protein, ERBB2/MYC/MDM2); ≪1 = post-transcriptionally BUFFERED passenger.
        "cis_protein_dosage_class": prot.get("cis_protein_dosage_class"),
        "cn_prot_spearman_r": prot.get("cn_prot_spearman_r"),
        "cn_prot_slope_log2abundance_per_cn": prot.get("cn_prot_slope_log2abundance_per_cn"),
        "delta_log2abundance_amplified_vs_neutral": prot.get("delta_log2abundance_amplified_vs_neutral"),
        "n_paired_models_cn_protein": prot.get("n_paired_models_cn_protein"),
        "mrna_vs_protein_dosage_slope_ratio": _slope_ratio(
            prot.get("cn_prot_slope_log2abundance_per_cn"), cis.get("cn_expr_slope_log2tpm_per_cn")
        ),
        # leg-2: expression/feature → own-dependency (reused)
        "expression_dependency_correlation_class": corr.get("correlation_class"),
        "expression_dependency_pearson_r": corr.get("pearson_r"),
        # leg-2 (PROTEIN reuse): protein abundance → dependency (VERDICT-INERT)
        "abundance_dependency_class": abdep.get("abundance_dependency_class"),
        "protein_dependency_pearson_r": abdep.get("protein_dependency_pearson_r"),
        "amp_expr_stratification_class": ampx.get("amp_expr_stratification_class"),
        "amp_expr_delta_chronos": ampx.get("delta_chronos_amp_expr_vs_rest"),
        # PATIENT (TCGA) cross-grain corroboration — VERDICT-INERT confidence signal
        "patient_cis_dosage_class": pat.get("patient_cis_dosage_class"),
        "patient_methylation_silencing_class": pat.get("patient_methylation_silencing_class"),
        "patient_n_cases_expression": pat.get("n_cases_expression"),
        "patient_dosage_agrees_with_cellline": dosage_agreement,
        "patient_silencing_agrees_with_cellline": silencing_agreement,
        # coherence framing
        "n_cell_lines_evaluated": cis.get("n_cell_lines_evaluated"),
    }
    # verdict-INERT LEG-decomposition claim-vector (12th concrete) — CIS_DOSAGE/SILENCING/EXPR_DEP/
    # CONJOINT, each with citable atoms + cross-grain PATIENT-agreement corroboration. The cis_coherence
    # VERDICT is an INTERACTION of these legs (owned by the resolver); this is the decomposition, NOT a
    # verdict echo, so it stays verdict-inert (byte-stable).
    hl["claim_vector"] = cis_coherence_claim_vector(hl, cards)
    hl["key_signals"] = cis_coherence_key_signals(hl, cards)
    # ── VERDICT-INERT cis-coherence CONFIDENCE surface (v1.4.0) ─────────────────────────────────────
    # Each best-effort: a fault in one enrichment field must NEVER discard the cis-coherence spine already
    # built in `hl` (same degrade discipline as differentiation / tumor-presence). Gates on already-emitted
    # headline fields; feeds NO resolver → cis_coherence_verdict + driving_rule_id + resolver golden byte-stable.
    try:
        hl["cis_coherence_confidence_caveat"] = _cis_coherence_confidence_caveat(
            hl, target=target, indication=indication
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["cis_coherence_confidence_caveat"] = f"{type(exc).__name__}: {exc}"
        hl["cis_coherence_confidence_caveat"] = None
    try:
        hl["causal_attribution_caveat"] = _causal_attribution_caveat(hl)
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["causal_attribution_caveat"] = f"{type(exc).__name__}: {exc}"
        hl["causal_attribution_caveat"] = None
    try:
        hl["context_generalization_caveat"] = _context_generalization_caveat(hl)
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["context_generalization_caveat"] = f"{type(exc).__name__}: {exc}"
        hl["context_generalization_caveat"] = None
    try:
        hl["cis_coherence_provenance"] = _cis_coherence_provenance(hl, target=target, indication=indication)
    except Exception as exc:  # noqa: BLE001
        hl.setdefault("_enrichment_errors", {})["cis_coherence_provenance"] = f"{type(exc).__name__}: {exc}"
        hl["cis_coherence_provenance"] = None
    # The per-question (data·signal·confidence) LEADING table — verdict-INERT projection over the leg
    # claim_vector just built (CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT); best-effort (never abort the spine).
    try:
        hl["question_table"] = cis_coherence_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort: a formatting/read fault must NEVER discard the
    # cis-coherence spine already fully built in `hl` (same degrade discipline as tumor-presence / safety).
    # On the happy path this is byte-additive (no _enrichment_errors key), so the verdict spine is unaffected.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — cis-feature-coherence emits a verdict-SHAPED
    # string (e.g. expressed_cis_coupled_inert) that is explicitly NOT a call, so role=INERT → the report
    # renders as a view with polarity=not_scored, never scored. Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_INERT,
            verdict=hl.get("cis_coherence_verdict"),
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
    "cis_coherence_verdict",
    "driving_rule_id",
    "cis_dosage_class",
    "cis_dosage_driver",
    # DIRECTION travels with the class in the synthesis facet: a consumer that sees only
    # cn_dosage_coupled_* cannot tell an amplicon driver from a deleted suppressor (resolver v1.3.0).
    "cis_dosage_direction",
    "cis_dosage_direction_basis",
    "methylation_silencing_class",
    "expression_dependency_correlation_class",
    "amp_expr_stratification_class",
    # protein legs (VERDICT-INERT): CN→protein dosage + the mRNA-vs-protein buffering ratio, and protein→dep
    "cis_protein_dosage_class",
    "mrna_vs_protein_dosage_slope_ratio",
    "abundance_dependency_class",
    "patient_dosage_agrees_with_cellline",
    "patient_silencing_agrees_with_cellline",
    # VERDICT-INERT cis-coherence CONFIDENCE surface (v1.4.0) — the statistical-vs-causal over-call surface
    "cis_coherence_confidence_caveat",
    "causal_attribution_caveat",
    "context_generalization_caveat",
    "cis_coherence_provenance",
    "claim_vector",
    "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 inert-role adoption
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair, target=None, indication=None):
    """Compact, VERDICT-INERT cis-coherence facet for the composed synthesis. Reuses _headline (single
    source) + returns the LEG-decomposition claim_vector (CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT) with its
    citable atoms + the cross-grain patient-agreement flags + the v1.4.0 confidence surface. The verdict is
    an INTERACTION owned by the resolver — this never echoes or moves it. target/indication are signature-
    introspected by the fan-out (tp_fanout) so the caveats' curated validated/CIMP guards work composed too."""
    h = _headline(cards, fired, verdict_pair, target=target, indication=indication)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic cis-feature-coherence facet; claim_vector is the LEG decomposition "
        "of the coherence cross-tab (the verdict is their INTERACTION, owned by the "
        "resolver). CIS_DOSAGE/SILENCING corroboration uses the TCGA patient-agreement arm."
    )
    return facet


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="cis_coherence",
            question=QUESTION,
            verdict_fn=_verdict,
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
            synthesize_fn=make_synthesize_fn(_LENS),
            # --literature lane (VERDICT-INERT): optional structured LLM lit-review scoped to the cis-coherence
            # axes, PMID-verified (verify_citations) + fed into the --synthesize narrator. Attaches
            # decision['literature_synthesis']; never moves the fixed cis_coherence_verdict.
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
            skill_figures_fn=emit_headline_hero,
            # Signals-first: tuned sub-group reader for the cis-coherence vocabulary. Verdict-INERT.
            subgroup_classify=make_value_classifier(_CIS_VALUE_TIERS),
        )
    )
