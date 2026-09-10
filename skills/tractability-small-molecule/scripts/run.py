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

from _skills_common import get_card_field
from _skills_common.claim_record import assemble_claim_record
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import TRACTABILITY_SM as _LENS
from _skills_common.resolver import resolve_or_raise
from _skills_common.skill_report import ROLE_GATING, build_skill_report
from _skills_common.subgroup_derivation import make_value_classifier
from _skills_common.tractability_claims import small_molecule_claim_vector, small_molecule_key_signals
from _skills_common.tractability_sm_question_table import tractability_sm_question_table

# ─── Signals-first sub-group reader (verdict-INERT) ──────────────────────────────────────────────
# The fleet-default heuristic tags this lens's clearest POSITIVE druggability signals
# (approved_drug_tractable, potent_measured_ligand, ubiquitination_substrate) as `absent`.
# _TRACT_VALUE_TIERS states the tier for the small-molecule-tractability vocabulary (signal = strength
# of evidence FOR small-molecule druggability). default_classify is the fallback. VERDICT-INERT.
_TRACT_VALUE_TIERS = {
    "approved_drug_tractable": "strong",
    "clinical_drug_tractable": "strong",
    "tool_compound_tractable": "moderate",
    "no_known_drug": "absent",
    "potent_measured_ligand": "strong",
    "moderate_measured_ligand": "moderate",
    "weak_measured_ligand": "weak",
    "no_measured_ligand": "absent",
    "clinical_precedent_only": "moderate",
    "triangulated_target_engaged": "strong",
    "mixed_engagement": "weak",
    "no_engagement": "absent",
    "strong_activity": "strong",
    "moderate_activity": "moderate",
    "weak_activity": "weak",
    "no_activity": "absent",
    "ubiquitination_substrate": "moderate",
    "no_e3_handle": "absent",
}


# ── canonical HEADLINE block (verdict + confidence + top tension) ─────────────────────────────────
# The tractability-small-molecule declaration for the shared headline_core builder: the 5 POSITIVE-valence
# claim axes (POTENCY / ACTIVITY / STRUCT / DRUG / DEGRADER), the druggability_snapshot vocabulary → human
# phrase, and the chemical↔genetic DISCORDANCE as the skill-specific tension source. Verdict-INERT — a
# one-way projection over the computed headline (druggability_snapshot spine byte-stable).
# The druggability_snapshot vocabulary (the resolver rungs) → human phrase. Positives are the tractable
# rungs; negatives are the intractable / off-target rungs; `insufficient` is the coverage gap.
_DRUGGABILITY_VERDICT_PHRASE = {
    # positives — a druggable / tractable call
    "well_covered": "Well-covered small-molecule target",
    "chemically_confirmed_genetic": "Chemically confirmed genetic dependency",
    "chemically_active": "Chemically active compound",
    "measured_potent_ligand": "Measured potent ligand",
    "clinical_precedent_only": "Clinical precedent only",
    "tool_compound_only": "Tool compound only",
    "weakly_active": "Weakly active compound",
    "structurally_ligandable": "Structurally ligandable pocket",
    # negatives — an intractable / undruggable / off-target call
    "structurally_intractable": "Structurally intractable",
    "chemically_unhit": "Chemically unhit (no compound found)",
    "discordant": "Discordant off-target activity",
    "annotation_only_indirect": "Annotation-only (indirect compounds; no direct binder)",
    # gap
    "insufficient": "Insufficient evidence",
}

# Positive (tractable) vs negative (intractable / off-target) druggability rungs — used only to colour
# the hero badge polarity; never a gate. Kept in sync with the resolver rung vocabulary.
_TRACTABILITY_POSITIVE = frozenset(
    {
        "well_covered",
        "chemically_confirmed_genetic",
        "chemically_active",
        "measured_potent_ligand",
        "clinical_precedent_only",
        "tool_compound_only",
        "weakly_active",
        "structurally_ligandable",
    }
)
# annotation_only_indirect (resolver v1.5.0 directness gate): an approved drug is catalogued but the DGIdb
# roster is INDIRECT/sparse — no DIRECT small-molecule binder established. A non-positive SM-tractability
# outcome (hero badge negative-polarity is honest: "no direct binder"), distinct from chemically_unhit
# (compounds ARE catalogued, just indirect) — the nuance rides in the phrase. NON-nominating (the TC
# nomination gate leaves it out of the positive/kill sets), so this membership only colours display.
_TRACTABILITY_NEGATIVE = frozenset(
    {"structurally_intractable", "chemically_unhit", "discordant", "annotation_only_indirect"}
)


def _tractability_verdict_polarity(v) -> str:
    """The skill's OWN reading of the druggability_snapshot (colours the hero badge; never a gate)."""
    if v in _TRACTABILITY_POSITIVE:
        return "positive"
    if v in _TRACTABILITY_NEGATIVE:
        return "negative"
    return "neutral"


# ── PER-MODALITY-ARM decomposition (druggability_verdict_by_modality) ────────────────────────────────
# tractability-small-molecule loads the intracellular axis, which scores TWO modalities in parallel:
# small-molecule INHIBITION (the druggability_snapshot spine) and DEGRADATION (the degrader_snapshot
# lens). Degradation ≠ inhibition (KO-like complete removal), so an SM-intractable scaffold can still be
# a degrader prospect (BRD4, STAT3). This is a PURE PROJECTION of the two already-computed snapshots onto
# explicit per-arm calls — the SM analog of surface_modality_verdict_by_modality / safety_verdict_by_
# modality / presence_verdict_by_modality. VERDICT-INERT: the projection can never disagree with the
# one-word spine (it IS the spine, re-expressed per modality); byte-stable (additive key). Arm-call vocab
# is the shared hero colour vocab (viable/caveated/opposed/not_viable/insufficient) so the hero renders a
# chip per arm. Every druggability_snapshot / degrader_snapshot token is mapped (pinned by
# test_verdict_by_modality_covers_all_tokens); an unmapped/None token falls back to insufficient (honest).
_SM_ARM = {
    # strong positives → viable; weaker/forward positives → caveated (a handle, not a proven hit)
    "well_covered": "viable",
    "chemically_confirmed_genetic": "viable",
    "chemically_active": "viable",
    "measured_potent_ligand": "viable",
    "clinical_precedent_only": "caveated",
    "tool_compound_only": "caveated",
    "weakly_active": "caveated",
    "structurally_ligandable": "caveated",
    # negatives
    "discordant": "opposed",
    "structurally_intractable": "not_viable",
    "chemically_unhit": "not_viable",
    # indirect-only: catalogued compounds exist but none direct → a CAVEATED (non-direct) handle, not a
    # clean not_viable (there IS chemical matter) nor viable (no direct binder). Verdict-inert projection.
    "annotation_only_indirect": "caveated",
    "insufficient": "insufficient",
}
_DEG_ARM = {
    "strong_degrader_rationale": "viable",
    "degrader_rationale": "supported",
    "degrader_opposed": "opposed",
    "degrader_unviable": "not_viable",
    "insufficient": "insufficient",
}


def _druggability_verdict_by_modality(sm_snapshot, degrader_snapshot) -> dict:
    """Project the two resolved snapshots onto explicit per-modality-arm calls {small_molecule, degrader}.
    Pure projection — never moves the spine; unmapped/None → insufficient (never fabricates a viable arm)."""
    return {
        "small_molecule": _SM_ARM.get(sm_snapshot, "insufficient"),
        "degrader": _DEG_ARM.get(degrader_snapshot, "insufficient"),
    }


# ── FACTORED-RECORD SHADOW (M1) — the TRACTABILITY (small-molecule) per-axis builder. This axis is
#    SM-SPECIFIC, so modality_scope.small_molecule is the meaningful coordinate (favorable when
#    druggable, unfavorable when intractable; biologics='na' — tractability_sm does not speak to
#    biologics). tractability has NO verdict-disjoint corroborator (rated `unmeasured`), so certainty is
#    a minimal coverage-only object. VERDICT-INERT: surfaced by the fan-out into
#    decision.claim_record_shadow.tractability_small_molecule, consumed by NOTHING.
_TRACT_STRONG = {"well_covered", "chemically_confirmed_genetic", "measured_potent_ligand"}
_TRACT_MOD = {"chemically_active", "structurally_ligandable", "clinical_precedent_only"}
_TRACT_WEAK = {"tool_compound_only", "weakly_active"}


def _tract_availability(v) -> str:
    if v is None:
        return "not_wired"  # open-world → assembler forces unknown/neutral
    if v == "insufficient":
        return "insufficient"  # the coverage gap (measured underpowered)
    if v in _TRACTABILITY_NEGATIVE:
        return "measured_negative"  # measured intractable / unhit / discordant
    return "measured_positive"


def _tract_direction(v) -> str:
    if v in _TRACTABILITY_POSITIVE:
        return "supports"
    if v in _TRACTABILITY_NEGATIVE:
        return "opposes"
    return "neutral"


def _tract_level(v) -> str:
    if v in _TRACT_STRONG:
        return "strong"
    if v in _TRACT_MOD or v in _TRACTABILITY_NEGATIVE:
        return "moderate"
    if v in _TRACT_WEAK:
        return "weak"
    return "none"


# degrader-feasibility class (_degrader_snapshot) -> the record's _refinements.degrader favorability.
# The degrader channel is a MEASURED, degrader-channel-only fired-rule read (NOT the fabricating
# alteration-class inference #2 rejected): a degrader models COMPLETE removal, so an SM-intractable
# target can still be a degrader prospect (BRD4 scaffolding, STAT3 TF). Without this, the consumer's
# degrader channel silently INHERITED the SM base favorability (_CHANNEL_BASE['degrader']=small_molecule)
# -- parroting the SM call for a channel with its own evidence. insufficient -> omit (keep SM fallback).
_DEGRADER_CLASS_TO_SCOPE = {
    "strong_degrader_rationale": "favorable",
    "degrader_rationale": "favorable",
    "degrader_opposed": "conditional",  # a degrader-opposing signal fired -- downgrade, not a kill
    "degrader_unviable": "unfavorable",  # a degrader-killer fired (nothing to degrade)
}


def _tract_modality_scope(v, fired=None) -> dict | None:
    scope = None
    if v in _TRACTABILITY_POSITIVE:
        scope = {"small_molecule": "favorable", "biologics": "na"}
    elif v in _TRACTABILITY_NEGATIVE:
        scope = {"small_molecule": "unfavorable", "biologics": "na"}
    # degrader channel: lift the measured _degrader_snapshot class onto _refinements.degrader so the
    # per-modality view reflects the ACTUAL degrader-feasibility read, not SM inheritance.
    if fired is not None:
        try:
            deg_class, _drv = _degrader_snapshot(fired)  # reads fired[].signals[degrader]
        except Exception:  # noqa: BLE001 -- shadow must never crash the run (fired may lack signals)
            deg_class = "insufficient"
        deg = _DEGRADER_CLASS_TO_SCOPE.get(deg_class)
        if deg is not None:
            scope = dict(scope or {"small_molecule": "na", "biologics": "na"})
            scope["_refinements"] = {"degrader": deg}
    return scope  # None only when no SM call AND degrader insufficient


def _tract_certainty(v) -> dict:
    """Minimal coverage-only certainty — tractability has no verdict-disjoint corroborator
    (CERTAINTY_MODEL: `unmeasured`). level == coverage; unknown_mass reflects open-world/underpowered."""
    if v is None:
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    if v == "insufficient":
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 0.5}
    return {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_snapshot(fired)[0] if fired is not None else None)
    return assemble_claim_record(
        axis="tractability_small_molecule",
        state=(v or "insufficient"),
        direction=_tract_direction(v),
        availability=_tract_availability(v),
        magnitude={"level": _tract_level(v)},
        modality_scope=_tract_modality_scope(v, fired=fired),
        certainty=_tract_certainty(v),
        fired=fired,
        cards=cards,
    )


def _tractability_tension_extra(headline: dict):
    """The sharpest small-molecule tractability caveat: a chemical↔genetic DISCORDANT read — an active
    compound whose cell-kill does NOT track the CRISPR/RNAi genetic dependency (off-target), which argues
    AGAINST small-molecule tractability. Surfaced from the `discordant` verdict + the concordance class."""
    if headline.get("druggability_snapshot") == "discordant":
        concord = headline.get("prism_crispr_concord")
        return {
            "text": (
                "chemical activity is discordant with the genetic dependency (off-target) — the "
                "compound kill does not track the CRISPR/RNAi requirement"
                + (f"; concordance: {concord}" if concord else "")
            ),
            "source": "chemical_genetic_discordance",
            "severity": 3,
        }
    return None


# ── DIRECTNESS caveat (verdict-INERT; the DGIdb/ChEMBL druggability-INFLATION surface) ────────────────
# The sharpest determ-vs-literature divergence for this skill. A POSITIVE druggability_snapshot can be
# carried by a RETROSPECTIVE-ANNOTATION rung — the DGIdb known-drug boolean, a ChEMBL approved-phase flag,
# a DGIdb druggable-category prior, or a ChEMBL gene-aggregated potent-ligand series. Those sources count
# an INTERACTION / a ligand tabulated AGAINST THE GENE; they do NOT establish that the compound engages
# THIS target DIRECTLY. For a classically-undruggable TF/scaffold (β-catenin/CTNNB1, MYC) the interaction
# roster is dominated by INDIRECT / pathway / downstream compounds — even assay dyes, antibodies, off-
# target kinase inhibitors, or PPI-interface-tabulated ligands — so the snapshot reads `chemically_active`
# with NO direct binder in existence. The verdict spine (frozen resolver + golden) is UNCHANGED; this is a
# verdict-INERT field that names WHY the positive call is annotation-driven and, where direct-engagement
# corroboration (a MEASURED PRISM cellular hit or chemical-genetic concordance) is absent, flags it as
# looks-druggable-but-UNCONFIRMED. Fires ONLY on an annotation-driven positive rung WITHOUT direct
# corroboration → None (byte-stable) for the on-target concordance rungs (KRAS well_covered /
# e7-triangulated), the measured-PRISM-activity rung, and the structural / negative / gap verdicts.
_ANNOTATION_DRIVEN_RUNGS = frozenset(
    {
        "known-drug-approved-antineoplastic-sm-supportive",  # DGIdb has_approved_drug (indirect-inclusive)
        "measured-chembl-approved-sm-supportive",  # ChEMBL max_clinical_phase>=4 (gene-aggregated)
        "known-drug-druggable-category-sm-supportive",  # DGIdb druggable-class prior (no bound compound)
        "measured-potent-ligand-sm-supportive",  # ChEMBL potent series (gene-aggregated; direct?)
        "measured-weak-ligand-sm-supportive",  # ChEMBL weak measured series (gene-aggregated)
    }
)
# A MEASURED cellular hit (PRISM) or chemical-genetic concordance PROVES direct engagement → suppresses the
# caveat. `clinically_active` is a measured cell-panel kill; the two concordance tokens below mean the
# compound-kill tracks the CRISPR/RNAi dependency (on-target). Kept in sync with the concordance vocab.
_DIRECT_ENGAGEMENT_PRISM = frozenset({"clinically_active"})
_DIRECT_ENGAGEMENT_CONCORD = frozenset({"triangulated_target_engaged", "crispr_confirmed_engagement"})

# FAIL-SAFE ONLY (CASE-008 #07): the caveat now reads the biologics-only modality map LIVE from
# target-contracts/vocabularies/biologics_precedent_targets.yaml (via _biologics_only_modalities() →
# _live_readers._load_biologics_precedent_modalities, keyed on `biologics_only: true`). This hardcoded set
# is retained ONLY as a last-resort fail-safe for the doubly-degraded path (card field absent AND vocab
# unreadable). It is a COARSER historical snapshot — it lists ERBB2/TROP2/FOLH1, which the live vocab
# does NOT flag biologics_only (ERBB2/EGFR/MET are dual-modality SM targets; FOLH1/PSMA has the SM
# radioligand PSMA-617), so the live loader is strictly more accurate (the osimertinib guard). DISCLAIMED.
_BIOLOGICS_APPROVED_NONSM = {
    "DLL3": "tce",
    "STEAP1": "tce",
    "FOLR1": "adc",
    "NECTIN4": "adc",
    "CEACAM5": "adc_tce",
    "TACSTD2": "adc",
    "MSLN": "adc_tce",
    "CD22": "adc",
    "CD79B": "adc",
    "TNFRSF17": "tce_car",
    "GPC3": "car",
}


def _biologics_only_modalities() -> dict:
    """The biologics-ONLY gene→modality map, read LIVE from the target-contracts vocab (the same
    biologics_only: true entries the AM dgidb reader + the resolver gate key on). New vocab entries are
    covered automatically. Falls back to the hardcoded _BIOLOGICS_APPROVED_NONSM fail-safe only when the
    live vocab is unreadable (returns {})."""
    try:
        from _skills_common._live_readers import _load_biologics_precedent_modalities

        live = _load_biologics_precedent_modalities()
        if live:
            return live
    except Exception:  # noqa: BLE001 — never break the caveat on a loader/import fault
        pass
    return _BIOLOGICS_APPROVED_NONSM


def _directness_caveat(
    snapshot, driving_rule_id, prism_activity_class, prism_crispr_concord, known_drug_class=None, n_antineoplastic=None
) -> str | None:
    """Name the DGIdb/ChEMBL druggability-inflation risk on a positive snapshot that rests on retrospective
    annotation WITHOUT direct-engagement corroboration. VERDICT-INERT: reports WHY the positive call is
    annotation-driven; never changes it. None unless the pattern holds → byte-stable on the on-target /
    measured-PRISM / structural / negative / gap paths (KRAS, EGFR/FOXA1 fixtures)."""
    if driving_rule_id not in _ANNOTATION_DRIVEN_RUNGS:
        return None
    if snapshot not in _TRACTABILITY_POSITIVE:  # defensive; the annotation rungs are all positive
        return None
    if prism_activity_class in _DIRECT_ENGAGEMENT_PRISM:
        return None  # a measured cell-panel hit — direct-ish, not inflated
    if prism_crispr_concord in _DIRECT_ENGAGEMENT_CONCORD:
        return None  # compound-kill tracks the dependency — on-target
    n = f" ({n_antineoplastic} antineoplastic interactions)" if isinstance(n_antineoplastic, int) else ""
    return (
        f"The positive snapshot ('{snapshot}') rests on a RETROSPECTIVE-ANNOTATION rung "
        f"({driving_rule_id}) — a DGIdb known-drug / druggable-category boolean or a ChEMBL gene-"
        f"aggregated ligand count{n} — which tabulates a compound AGAINST THE GENE but does NOT prove it "
        "engages THIS target DIRECTLY. Direct engagement is UNCONFIRMED in-package: PRISM cellular "
        f"activity = {prism_activity_class or 'data_unavailable'}, chemical-genetic concordance = "
        f"{prism_crispr_concord or 'data_unavailable'} (neither a measured cell-panel hit nor "
        "chemical-genetic agreement). For a classically-undruggable TF/scaffold the interaction roster "
        "is dominated by INDIRECT / pathway / downstream compounds, so this can read druggable with no "
        "direct binder in existence — treat as looks-druggable-but-UNCONFIRMED, not confirmed direct "
        "druggability. Confirm target-directness from the literature lane (--literature)."
    )


def _sm_modality_mismatch_caveat(hl: dict, target=None) -> str | None:
    """Name the MODALITY-mismatch on the DRUG axis (VERDICT-INERT surface): for a target whose approved
    agent is a BIOLOGIC (ADC/TCE/CAR), DGIdb's has_approved_drug is modality-blind and can credit the
    DRUG axis as small-molecule tractability. As of CASE-008 the modality gate is now VERDICT-LEVEL — the
    reader emits approved_drug_modality=biologic and approved_drug_engagement_class=approved_biologic_only,
    and the resolver routes the DRUG axis to annotation_only_indirect. So this string is now a CONFIRMATION
    that the gate fired (not just a warning): it names the biologic modality and reports that the DRUG-axis
    over-credit HAS been suppressed. Prefers the reader's authoritative approved_drug_modality; falls back
    to the curated _BIOLOGICS_APPROVED_NONSM set only when the card field is unavailable (a stale-contract
    or degraded run). Fires only when an approved drug is present AND the target is biologics-only; None
    otherwise → byte-stable. Never enters fired/resolver — it explains the DRUG-axis modality read."""
    gene = (target or "").upper().strip()
    card_modality = hl.get("approved_drug_modality")  # authoritative reader signal
    # authoritative path: the reader classified the approved drug's modality
    if card_modality == "biologic":
        modality = hl.get("approved_drug_modality_tag") or _biologics_only_modalities().get(gene) or "biologic"
    elif card_modality in ("small_molecule_or_unknown", "not_applicable"):
        return None  # reader says not a biologics-only approval
    else:
        # card field unavailable (degraded/stale contract) → fall back to the LIVE biologics-only vocab
        # read (curated fail-safe only if the vocab is unreadable) + has_approved
        modality = _biologics_only_modalities().get(gene)
        if modality is None or hl.get("has_approved_drug") is not True:
            return None
    gated = hl.get("approved_drug_engagement_class") == "approved_biologic_only"
    n = hl.get("n_antineoplastic_interactions")
    n_txt = f" ({n} antineoplastic interactions)" if isinstance(n, int) else ""
    lead = "MODALITY GATE FIRED" if gated else "MODALITY MISMATCH"
    tail = (
        "The modality gate has SUPPRESSED this over-credit: approved_drug_engagement_class="
        "approved_biologic_only routes the DRUG axis to annotation_only_indirect (a catalogued "
        "approved agent, but not a small molecule), so it no longer contributes SM-supportive "
        "evidence."
        if gated
        else "Treat any positive DRUG-axis / known-drug contribution here as biologics-precedent, NOT "
        "evidence of small-molecule druggability."
    )
    return (
        f"{lead}: {gene}'s approved / clinically-precedented agent is a BIOLOGIC "
        f"(modality={modality} — antibody-drug conjugate / T-cell engager / CAR), NOT a small "
        f"molecule. DGIdb's known-drug annotation (has_approved_drug=true{n_txt}) is modality-BLIND. "
        f"{tail} Confirm a direct small-molecule binder from the structure/potency axes or the "
        "literature lane (--literature). Source: biologics_precedent_targets.yaml (curated)."
    )


# ── CHEMICAL-GENETIC AGREEMENT arm (verdict-INERT) ───────────────────────────────────────────────────
# The concordance card answers the skill's core question — does compound-kill AGREE with the genetic
# dependency? — but the raw `prism_crispr_concord` token buries the interpretation. This projects it onto
# an explicit agreement class (corroboration / partial / off-target conflict / unmeasured) + a one-line
# read, mirroring FR's concordance handling. VERDICT-INERT; None when the concordance is unread.
_CONCORD_AGREEMENT = {
    "triangulated_target_engaged": (
        "on_target_confirmed",
        "compound-kill tracks BOTH the CRISPR and RNAi genetic dependency (triangulated) — direct "
        "on-target engagement corroborated (the strongest chemical-genetic agreement).",
    ),
    "crispr_confirmed_engagement": (
        "on_target_crispr",
        "compound-kill tracks the CRISPR genetic dependency — on-target engagement (single-channel).",
    ),
    "rnai_confirmed_engagement": (
        "on_target_rnai_only",
        "compound-kill tracks the RNAi dependency only (orthogonal LoF, no CRISPR arm) — on-target but "
        "single-channel and seed/off-target-prone; weaker corroboration.",
    ),
    "mixed_engagement": (
        "partial",
        "compound-kill only PARTIALLY tracks the genetic dependency — engagement ambiguous, neither "
        "clean on-target nor clearly off-target.",
    ),
    "discordant_off_target_likely": (
        "off_target_conflict",
        "compound-kill does NOT track the genetic dependency — likely OFF-TARGET; a chemical-genetic "
        "CONFLICT that argues AGAINST small-molecule tractability.",
    ),
    "thin_evidence": (
        "unmeasured",
        "chemical-genetic concordance is UNMEASURED (no/too-few compounds evaluated) — engagement neither "
        "confirmed nor refuted; the positive chemical signal is uncorroborated by the genetic dependency.",
    ),
    "data_unavailable": (
        "unmeasured",
        "chemical-genetic concordance is unavailable — engagement neither confirmed nor refuted.",
    ),
}


def _chemical_genetic_agreement(prism_crispr_concord) -> dict | None:
    """Explicit AGREEMENT arm over the concordance class: agree = corroboration, off-target = conflict,
    thin = unmeasured. VERDICT-INERT; None when concordance is unread (byte-stable on the empty case)."""
    if not prism_crispr_concord:
        return None
    cls, note = _CONCORD_AGREEMENT.get(
        prism_crispr_concord,
        (
            "unmeasured",
            f"chemical-genetic concordance class '{prism_crispr_concord}' is unrecognised — treat as unmeasured.",
        ),
    )
    return {"agreement_class": cls, "note": note, "source_concordance_class": prism_crispr_concord}


_TRACTABILITY_HEADLINE_SPEC = HeadlineSpec(
    gate="tractability_sm",
    axis_labels={
        "POTENCY": "measured binding",
        "ACTIVITY": "functional compound",
        "STRUCT": "ligandable pocket",
        "DRUG": "known-drug pharmacology",
        "DEGRADER": "degrader feasibility",
    },
    axis_keys=("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"),
    critical_axes=("POTENCY", "ACTIVITY"),
    verdict_label=lambda v: _DRUGGABILITY_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_tractability_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed tractability headline. Reads the
    druggability_snapshot + the verdict-inert claim_vector / key_signals; never moves the spine. The
    skill emits no CERTAINTY_MODEL sidecar, so confidence is the derived weakest-link over the claim
    vector's corroboration."""
    v = headline.get("druggability_snapshot")
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_TRACTABILITY_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=_tractability_verdict_polarity(v),
        # per-modality-arm chips (SM inhibition + degrader) — omitted (None) leaves the
        # shared hero byte-identical for skills that don't decompose. Verdict-inert.
        modality_arms=(
            headline.get("druggability_verdict_by_modality")
            or _druggability_verdict_by_modality(v, headline.get("degrader_snapshot"))
        ),
    )


SKILL_NAME = "tractability-small-molecule"
SKILL_VERSION = "3.11.1"  # 3.11.1 (2026-09-07, CASE-008 #07): _sm_modality_mismatch_caveat fallback now reads the biologics-only modality map LIVE from biologics_precedent_targets.yaml (_biologics_only_modalities → _live_readers._load_biologics_precedent_modalities, keyed on biologics_only: true) instead of the hardcoded _BIOLOGICS_APPROVED_NONSM (demoted to a last-resort fail-safe). New vocab entries covered automatically. VERDICT-INERT (caveat is a headline field; spine/resolver/golden byte-stable).
# 3.11.0 (2026-09-07, CASE-008 graduation, VERDICT-MOVING signal-vector): consume the new AM/TC modality gate — reader emits approved_drug_modality + approved_biologic_only; resolver v1.6.0 rung known-drug-approved-biologic-only-sm-not-supportive routes a biologics-only approved antigen's DRUG axis to annotation_only_indirect (stops the SM-supportive approved-drug rung). _sm_modality_mismatch_caveat now keys on the reader's authoritative approved_drug_modality (curated set = fallback) and becomes a CONFIRMATION when the gate fired. Legacy oracle mirrors the new rung. DRUG-axis fired signal moves for biologics antigens (CEACAM5/DLL3/FOLR1/NECTIN4); top-line verdict STABLE for the calibration set (STRUCT/e7-driven). Golden/replay regenerated.
# 3.10.0 (2026-09-07, CASE-008 literature-discordance loop): VERDICT-INERT sm_modality_mismatch_caveat — a biologics-approved antigen (ADC/TCE/CAR; curated _BIOLOGICS_APPROVED_NONSM seeded from biologics_precedent_targets.yaml) whose modality-blind DGIdb known-drug annotation can inflate the DRUG axis into SM tractability. Fires on has_approved_drug + curated target; spine/resolver/golden byte-stable. target signature-introspected in _headline/_synthesis_facet.
# 3.9.1 (2026-09-04): VERDICT-INERT — set structural_ligandability_class + has_druggable_pocket + ligandability_disorder_class in _headline (declared-but-unset facet debt).     # 3.9.0 (2026-09-04): VERDICT-MOVING annotation_only_indirect — consume the resolver v1.5.0 directness gate (approved-drug rung now requires DIRECT engagement; indirect/sparse DGIdb roster → annotation_only_indirect). Depends AM dgidb v0.2.0 + TC resolver v1.5.0.     # 3.8.0 (2026-09-04): --literature lane + verdict-INERT surfacing (directness_caveat = DGIdb/ChEMBL druggability-inflation flag; chemical_genetic_agreement arm; TRACTABILITY_SM thesis + polarity_note). Spine byte-stable.     # 3.7.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.     # 3.6.0 (2026-08-27): tuned signals-first sub-group reader (tractability vocab). Verdict-INERT.
# 3.5.0 (2026-08-21): emit existing per-question question_table into the headline
# 3.4.0/3.1.0 +E8; +known-drug; +degradation; +T1.1/T1.2/T3.1
#   (discordant reorder, clinical_precedent_only, measured-potency card).
# 3.0.0: split from tractability-and-modality 2.1.0.

CARDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
    "structure-features-static",  # E8: FORWARD ligandability (pocket structure)
    "known-drug-tractability",  # E-known-drug: PHARMACOLOGY leg (DGIdb known-drug + druggable-category)
    "measured-potency-tractability",  # E-measured-potency (T3.1): ChEMBL/BindingDB MEASURED binding potency
    "degradation-feasibility",  # E3 slice 3: DEGRADER-lens degradability (E3-substrate + precedent + location gate)
    "gdsc-drug-activity",  # 2nd drug-response platform (Sanger GDSC1/2) — ORTHOGONAL corroboration of
    # PRISM. DISPLAY-ONLY / verdict-INERT: fires no rule, feeds no resolver rung,
    # so druggability_snapshot is byte-stable (the ProCan->Gygi analog).
]

QUESTION = (
    "Does {target} in {indication} show small-molecule druggability evidence "
    "— is there a compound that hits it (chemical), does that agree with the "
    "genetic dependency, and is there a druggable pocket even absent a known "
    "compound (structural / forward ligandability)?"
)


def _snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (B3a, 2026-08-06).
    The former 11-rung if-chain now lives in resolvers/tractability_small_molecule.resolver.yaml
    (target-contracts), evaluated by the ONE interpreter every gate skill calls. Proven byte-for-byte
    equivalent to the former if-chain by the golden-oracle test (test_tractability_sm_resolver_oracle.py,
    which enumerates every rule combination against the retained _snapshot_legacy_oracle). A missing spec
    raises (the resolver is the source of truth — no silent fallback to a stale copy, which would
    reintroduce drift). Mirrors surface-modality-fit's _verdict."""
    return resolve_or_raise(fired, "tractability_small_molecule")


def _snapshot_legacy_oracle(fired: list[dict]) -> tuple[str, str | None]:
    """RETAINED ONLY as the golden-oracle for the equivalence test — NOT called at runtime.
    The original rank-ordered if-chain (first match wins). Chemical-genetic evidence (E6/E7,
    RETROSPECTIVE — a compound has actually hit the target) ranks highest. Structural / forward
    ligandability (E8 — a druggable pocket) ranks BELOW a real chemical hit but ABOVE
    `chemically_unhit` (KRAS-G12C switch-II pre-sotorasib). A measured structural NEGATIVE ranks
    as an SM-opposing note. test_tractability_sm_resolver_oracle.py asserts the declarative resolver
    reproduces this function's output for EVERY rule combination; do not edit without re-freezing that
    equivalence.
    """
    fired_by_id = {r["rule_id"]: r for r in fired}
    # --- On-target chemical-genetic (retrospective, CONCORDANCE-confirmed) — top; discordant does
    #     NOT override an on-mechanism read. ---
    if "e7-triangulated-target-engaged-supportive" in fired_by_id:
        return "well_covered", "e7-triangulated-target-engaged-supportive"
    if "e7-crispr-confirmed-supportive-sm" in fired_by_id:
        return "chemically_confirmed_genetic", "e7-crispr-confirmed-supportive-sm"
    # --- Opposing off-target read (T1.1, 2026-08-09): MUST precede the retrospective chemical-ACTIVITY
    #     positives below (an active-but-off-target compound argues AGAINST tractability). Kept
    #     byte-in-sync with resolvers/tractability_small_molecule.resolver.yaml. ---
    if "e7-discordant-off-target-warning" in fired_by_id:
        return "discordant", "e7-discordant-off-target-warning"
    # --- Retrospective chemical ACTIVITY (a compound was found; NOT concordance-checked here) ---
    if "prism-clinically-active-supportive-sm" in fired_by_id:
        return "chemically_active", "prism-clinically-active-supportive-sm"
    # E-known-drug (DGIdb pharmacology leg, 2026-08-07): an APPROVED drug catalogued against the
    # target -> chemically_active (SAME verdict as PRISM clinically-active; rescues a target PRISM
    # missed). Byte-in-sync with resolvers/tractability_small_molecule.resolver.yaml.
    if "known-drug-approved-antineoplastic-sm-supportive" in fired_by_id:
        return "chemically_active", "known-drug-approved-antineoplastic-sm-supportive"
    # WS-E (2026-08-24): ChEMBL max_clinical_phase >= 4 (approved) -> chemically_active (a third
    # independent path corroborating the PRISM/DGIdb approved rungs). Byte-in-sync with the resolver.
    if "measured-chembl-approved-sm-supportive" in fired_by_id:
        return "chemically_active", "measured-chembl-approved-sm-supportive"
    # WS-E (2026-08-24): ChEMBL phase 1-3 -> clinical_precedent_only, AUTHORITATIVE over the PRISM
    # `Prioritized`-flag proxy below (placed ABOVE it so the real-phase rule is the driving_rule when
    # both fire; same verdict). Byte-in-sync with the resolver.
    if "measured-chembl-clinical-precedent-sm-supportive" in fired_by_id:
        return "clinical_precedent_only", "measured-chembl-clinical-precedent-sm-supportive"
    # T1.2 (2026-08-09): clinical annotation WITHOUT measured PRISM activity -> clinical_precedent_only
    # (weaker than measured chemically_active, above tool_compound_only).
    if "prism-clinical-precedent-only-weak-supportive-sm" in fired_by_id:
        return "clinical_precedent_only", "prism-clinical-precedent-only-weak-supportive-sm"
    if "prism-tool-compound-only-weak-supportive-sm" in fired_by_id:
        return "tool_compound_only", "prism-tool-compound-only-weak-supportive-sm"
    if "prism-weakly-active-weak-supportive-sm" in fired_by_id:
        return "weakly_active", "prism-weakly-active-weak-supportive-sm"
    # --- MEASURED potency (T3.1, 2026-08-09): a potent (<=1 uM) MEASURED chemotype series
    #     (ChEMBL/BindingDB) -> measured_potent_ligand. Below the retrospective chemical-activity
    #     rungs, above the structural tier. Byte-in-sync with the resolver. ---
    if "measured-potent-ligand-sm-supportive" in fired_by_id:
        return "measured_potent_ligand", "measured-potent-ligand-sm-supportive"
    # MODALITY gate (v1.7.0, 2026-09-09): a biologics-only antigen (approved ADC/TCE/CAR/mAb, NO approved SM)
    # → approved_biologic_only. REPRIORITIZED to OUTRANK the structural tier below: a predicted/experimental
    # pocket on a biologic-only/extracellular antigen is not a validated SM handle, so "the approved agent is
    # a biologic" beats "a pocket exists" (fixes the structurally_ligandable subskill-read over-call on
    # MSLN/CD79B/DLL3). Still BELOW the measured-chemical rungs above (a real measured SM ligand wins).
    # → annotation_only_indirect (catalogued approved agent, not a small molecule). Byte-in-sync w/ resolver.
    if "known-drug-approved-biologic-only-sm-not-supportive" in fired_by_id:
        return "annotation_only_indirect", "known-drug-approved-biologic-only-sm-not-supportive"
    # --- Structural / forward ligandability (E8: druggable pocket, no compound yet) ---
    # Ranked below any real chemical hit, above chemically_unhit — a druggable pocket
    # is a positive SM prospect even before a compound exists (the KRAS-G12C fix).
    # E8-lig (composite structure-ligandability-per-protein-v1, 2026-08-07): the LIVE structural
    # leg. A real experimental co-crystal is the STRONGEST forward handle → top of the structural
    # tier; predicted (pocket/VS-hit/cryptic) sits with the existing pocket rungs. Kept byte-in-sync
    # with resolvers/tractability_small_molecule.resolver.yaml (same rung order + driving ids).
    if "ligandability-experimental-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "ligandability-experimental-sm-supportive"
    if "hotspot-in-druggable-pocket-sm-supportive-e8" in fired_by_id:
        return "structurally_ligandable", "hotspot-in-druggable-pocket-sm-supportive-e8"
    if "structure-pocket-adjacent-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "structure-pocket-adjacent-sm-supportive"
    if "ligandability-predicted-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "ligandability-predicted-sm-supportive"
    # E-known-drug (DGIdb): a druggable-CATEGORY membership (clinically-actionable / druggable-genome,
    # no approved drug) is a forward druggable-class prior -> structurally_ligandable tier.
    if "known-drug-druggable-category-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "known-drug-druggable-category-sm-supportive"
    # T3.1: weak measured activity (a potent hit or two / sub-potent) -> structurally_ligandable tier
    # (a starting-point handle, same as a predicted pocket). Byte-in-sync with the resolver.
    if "measured-weak-ligand-sm-supportive" in fired_by_id:
        return "structurally_ligandable", "measured-weak-ligand-sm-supportive"
    if "structure-low-confidence-sm-opposing" in fired_by_id:
        return "structurally_intractable", "structure-low-confidence-sm-opposing"
    if "ligandability-disordered-sm-opposing" in fired_by_id:
        return "structurally_intractable", "ligandability-disordered-sm-opposing"
    # annotation_only_indirect (2026-09-04, directness gate): an approved drug is catalogued but the DGIdb
    # roster is INDIRECT/sparse — no direct binder. Below every genuine positive + the measured structural
    # negative, above chemically_unhit. Byte-in-sync with resolvers/tractability_small_molecule.resolver.yaml.
    if "known-drug-approved-indirect-only-sm-weak" in fired_by_id:
        return "annotation_only_indirect", "known-drug-approved-indirect-only-sm-weak"
    if "prism-no-compounds-found-neutral" in fired_by_id:
        return "chemically_unhit", "prism-no-compounds-found-neutral"
    return "insufficient", None


def _degrader_snapshot(fired: list[dict]) -> tuple[str, str | None]:
    """DEGRADER lens projection (modality-specific-interpretation, slice 2) — reads the DEGRADER
    channel of the same fired rules the SM snapshot reads the small_molecule channel of. Additive:
    surfaces a degrader-specific read alongside druggability_snapshot; touches NO resolver (the SM
    gate's verdict spine is unchanged — this is a headline lens, one-directional).

    A degrader lens is NOT the SM lens: degradation models COMPLETE removal (KO-like) rather than
    catalytic inhibition, so a target with a dependency but no druggable pocket can still be a degrader
    prospect. This first pass reads the degrader signal channel; the FULL degrader question ("is the
    degradation MACHINERY intact?" — CRBN/VHL/proteasome) needs the E3-machinery card (slice 3, not yet
    built), so `degradability_machinery` is reported as not_yet_assessed until that card lands.

    Rank (first match): a degrader-killer (e.g. broadly-low expression — nothing to degrade) →
    degrader_unviable; a dominant degrader-supportive → strong_degrader_rationale; any degrader-
    supportive → degrader_rationale; a degrader-opposing → degrader_opposed; else insufficient."""
    from _skills_common import modality_lens

    tally = modality_lens(fired, "degrader")
    if tally["killer"]:
        return "degrader_unviable", tally["killer"][0]["rule_id"]
    dominant_support = [r for r in tally["supportive"] if r.get("dominant")]
    if dominant_support:
        return "strong_degrader_rationale", dominant_support[0]["rule_id"]
    if tally["supportive"]:
        return "degrader_rationale", tally["supportive"][0]["rule_id"]
    if tally["opposing"]:
        return "degrader_opposed", tally["opposing"][0]["rule_id"]
    return "insufficient", None


def _headline(cards, fired, verdict_pair, target=None):
    v, drv = verdict_pair or ("insufficient", None)
    degrader_class, degrader_drv = _degrader_snapshot(fired)
    hl = {
        "druggability_snapshot": v,
        "driving_rule_id": drv,
        # DEGRADER lens — additive to the SM verdict; degradation ≠ inhibition (KO-like complete
        # removal). The degrader_snapshot now folds in the E3-degradability slice (slice 3): the
        # degradation-feasibility card's degrader-channel rules fire into the same `fired` set the
        # lens tallies, so a scaffolding/precedented/ubiquitinatable target reads
        # strong_degrader_rationale and a surface/secreted target reads degrader_opposed — WITHOUT
        # touching the small-molecule druggability_snapshot (degrader-channel-only rules; SM spine
        # byte-stable, proven by the resolver golden-oracle test).
        "degrader_snapshot": degrader_class,
        "degrader_driving_rule_id": degrader_drv,
        # PER-MODALITY-ARM decomposition — pure projection of the two snapshots above onto
        # {small_molecule, degrader} calls (the SM analog of surface/safety/presence *_by_modality).
        # Verdict-INERT (cannot disagree with the one-word spine); rendered as hero chips + a facet key.
        "druggability_verdict_by_modality": _druggability_verdict_by_modality(v, degrader_class),
        # slice 3 LANDED: the target-degradability read (E3-substrate + PROTAC precedent + location
        # gate) from the degradation-feasibility card, replacing the not_yet_assessed placeholder.
        "degradability_machinery": get_card_field(cards, "degradation-feasibility", "degradability_feasibility_class"),
        "degradability_e3_evidence": get_card_field(cards, "degradation-feasibility", "e3_substrate_evidence"),
        "degrader_precedent": get_card_field(cards, "degradation-feasibility", "degrader_precedent"),
        # 2026-08-09 bugfix: these read the WRONG field names — the methods emit
        # `prism_activity_class` / `crispr_prism_concordance_class`, not `activity_class` /
        # `concordance_class`. get_card_field returns None on a missing key (no raise), so both
        # headline fields were ALWAYS None → decision.json blank + the LLM synthesis prompt
        # (synthesis_tractability_sm.py reads h['prism_activity_class'] / ['prism_crispr_concord'])
        # was starved of the two most important chemical facts. Verdict UNAFFECTED (the rules read
        # the correct field names directly via the rule engine).
        "prism_activity_class": get_card_field(cards, "prism-compound-activity", "prism_activity_class"),
        "prism_crispr_concord": get_card_field(cards, "prism-crispr-concordance", "crispr_prism_concordance_class"),
        # GDSC 2nd-platform ORTHOGONAL corroboration (2026-08-25): Sanger GDSC1+GDSC2 drug-response,
        # a DIFFERENT lab/assay/library than Broad PRISM. VERDICT-INERT display — the card fires no
        # rule + feeds no resolver rung, so these fields never move druggability_snapshot; a headline-
        # only cross-platform read (a target potent in BOTH GDSC and PRISM is more credible). NOT in
        # _SYNTHESIS_FACET_KEYS → the composed claim_vector/facet stay byte-stable.
        "gdsc_activity_class": get_card_field(cards, "gdsc-drug-activity", "gdsc_activity_class"),
        "gdsc_most_sensitive_drug": get_card_field(cards, "gdsc-drug-activity", "most_sensitive_drug_name"),
        "predictability_class": get_card_field(cards, "dependency-predictability", "predictability_class"),
        # E8 structural / forward ligandability (2026-07-17)
        "hotspot_pocket_adjacency": get_card_field(cards, "structure-features-static", "hotspot_pocket_adjacency_call"),
        "hotspot_in_druggable_pocket": get_card_field(
            cards, "structure-features-static", "mutation_hotspot_in_druggable_pocket"
        ),
        "pdb_coverage_class": get_card_field(cards, "structure-features-static", "pdb_coverage_class"),
        "alphafold_confidence_class": get_card_field(cards, "structure-features-static", "alphafold_confidence_class"),
        # STRUCTURAL LIGANDABILITY read (2026-09-04 debt fix): structural_ligandability_class was DECLARED
        # in _SYNTHESIS_FACET_KEYS but never set here → the composed target-profile facet always emitted it
        # None (the claim_vector STRUCT axis read the card directly, so the verdict was unaffected). The E8
        # ligandability RULES also read the card field directly via the rule engine, so surfacing it in the
        # headline is purely additive/display — VERDICT-INERT (druggability_snapshot spine byte-stable).
        # has_druggable_pocket + ligandability_disorder_class complete the structure read: they are the
        # coverage-vs-pocket discriminators the narrator's polarity_note reasons over (a flat PPI-groove
        # target can score pdb_coverage_class=strong yet be disordered / lack a real orthosteric pocket).
        "structural_ligandability_class": get_card_field(
            cards, "structure-features-static", "structural_ligandability_class"
        ),
        "has_druggable_pocket": get_card_field(cards, "structure-features-static", "has_druggable_pocket"),
        "ligandability_disorder_class": get_card_field(
            cards, "structure-features-static", "ligandability_disorder_class"
        ),
        # E-known-drug PHARMACOLOGY leg (DGIdb, 2026-08-07): known-drug + druggable-category read
        "known_drug_tractability": get_card_field(cards, "known-drug-tractability", "known_drug_tractability_class"),
        "has_approved_drug": get_card_field(cards, "known-drug-tractability", "has_approved_drug"),
        "n_antineoplastic_interactions": get_card_field(
            cards, "known-drug-tractability", "n_antineoplastic_interactions"
        ),
        # MODALITY read (CASE-008): the reader's authoritative drug-modality classification + the
        # resolver-keyed engagement class (approved_biologic_only when the gate fired).
        "approved_drug_engagement_class": get_card_field(
            cards, "known-drug-tractability", "approved_drug_engagement_class"
        ),
        "approved_drug_modality": get_card_field(cards, "known-drug-tractability", "approved_drug_modality"),
        "approved_drug_modality_tag": get_card_field(cards, "known-drug-tractability", "approved_drug_modality_tag"),
    }
    # verdict-INERT claim-vector projection (6th concrete) — POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER
    # signal decomposition + citable atoms the composed fan-out lifts to the cross-evidence agent.
    hl["claim_vector"] = small_molecule_claim_vector(hl, cards)
    hl["key_signals"] = small_molecule_key_signals(hl, cards)
    # Verdict-INERT signal-surfacing flags (2026-09-04, mirrors FR measurement_caveat / concordance_scope_note).
    # (1) directness_caveat: a positive snapshot carried by a RETROSPECTIVE-ANNOTATION rung (DGIdb known-drug /
    # ChEMBL aggregate) WITHOUT direct-engagement corroboration → the DGIdb/ChEMBL druggability-INFLATION
    # surface (β-catenin/MYC read chemically_active off indirect interaction counts). None on the on-target
    # concordance rungs / measured-PRISM / structural / gap verdicts → byte-stable (KRAS well_covered, the
    # EGFR/FOXA1 replay fixtures). (2) chemical_genetic_agreement: the explicit AGREE/conflict/unmeasured arm
    # over the concordance class. Neither touches the druggability_snapshot spine.
    hl["directness_caveat"] = _directness_caveat(
        v,
        drv,
        hl.get("prism_activity_class"),
        hl.get("prism_crispr_concord"),
        known_drug_class=hl.get("known_drug_tractability"),
        n_antineoplastic=hl.get("n_antineoplastic_interactions"),
    )
    hl["chemical_genetic_agreement"] = _chemical_genetic_agreement(hl.get("prism_crispr_concord"))
    # (3) sm_modality_mismatch_caveat (CASE-008): the DGIdb known-drug annotation is modality-BLIND, so
    # a biologics-approved antigen (DLL3/STEAP1/FOLR1/NECTIN4/CEACAM5 — ADC/TCE/CAR) can inflate the DRUG
    # axis into an SM-tractability signal. Fires only for a curated biologics-approved target WITH an
    # approved-drug annotation; None otherwise → byte-stable (KRAS/EGFR/FOXA1 fixtures untouched).
    # Verdict-INERT (a headline key; never enters fired/resolver). target is signature-introspected by the
    # dispatcher + fan-out (mirrors differentiation).
    hl["sm_modality_mismatch_caveat"] = _sm_modality_mismatch_caveat(hl, target=target)

    # The canonical HEADLINE block is a verdict-INERT projection over the claim_vector / key_signals just
    # built. Run it best-effort: a formatting/read fault must NEVER discard the druggability spine already
    # composed in `hl` (same degrade-on-exception discipline the dispatcher applies to synthesis/figures).
    # On the happy path this adds only the `headline_block` key (no _enrichment_errors), so the golden
    # ladder + replay fixtures stay byte-stable.
    def _enrich(label, fn, *fn_args):
        try:
            return fn(*fn_args)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
            hl.setdefault("_enrichment_errors", {})[label] = f"{type(exc).__name__}: {exc}"
            return None

    # Canonical HEADLINE block (verdict + confidence + top tension) — deterministic text + a
    # renderer-agnostic hero payload for every consumer. Verdict-INERT; best-effort.
    hl["headline_block"] = _enrich("headline_block", _build_headline_block, hl)
    # The per-question (data · signal · confidence) LEADING table — verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort.
    hl["question_table"] = _enrich("question_table", tractability_sm_question_table, hl, cards)
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, assembled
    # from the verdict + claim_vector + headline_block + question_table just built. tractability-small-
    # molecule is a GATING skill (∈ target-profile _SHORT_TO_GATE); its druggability polarity is clean
    # 3-band with no veto-killer verdict (chemically_unhit / structurally_intractable are opposing, not a
    # cross-target veto), so the helper's negative→opposing floor is correct and no
    # canonical_polarity_override is needed. Best-effort + verdict-INERT. (build_skill_report is
    # keyword-only → inline try/except, not the positional `_enrich` helper.)
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=hl.get("druggability_snapshot"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
            # FOR-WHAT projection onto the spine (the SAME dict the claim_record_shadow carries: SM
            # favorability + the measured degrader refinement), so target_report.modality_fit rolls
            # up the small_molecule + degrader channels FROM the report, not a reach-in.
            modality_scope=_tract_modality_scope(hl.get("druggability_snapshot"), fired=fired),
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


_SYNTHESIS_FACET_KEYS = (
    "druggability_snapshot",
    "driving_rule_id",
    "degrader_snapshot",
    "druggability_verdict_by_modality",  # per-arm {small_molecule, degrader} projection (verdict-inert)
    "prism_activity_class",
    "known_drug_tractability",
    "structural_ligandability_class",
    # structure read completed (2026-09-04 debt fix) — the coverage-vs-pocket discriminators
    "has_druggable_pocket",
    "ligandability_disorder_class",
    "degradability_machinery",
    "claim_vector",
    "key_signals",
    # verdict-INERT surfacing flags (2026-09-04): the DGIdb/ChEMBL druggability-inflation caveat + the
    # explicit chemical-genetic AGREEMENT arm (mirrors FR measurement_caveat / concordance_scope_note).
    "directness_caveat",
    "chemical_genetic_agreement",
    # CASE-008: modality-mismatch druggability-inflation (biologics-approved antigen; verdict-INERT)
    "sm_modality_mismatch_caveat",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3 skill_report
    # adoption arc (3rd gating adopter after safety + functional-requirement)
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair, target=None):
    """Compact, VERDICT-INERT small-molecule-tractability facet for the composed target-profile
    synthesis. Reuses _headline (single source) + returns the claim_vector (POTENCY/ACTIVITY/STRUCT/
    DRUG/DEGRADER, POSITIVE valence) + its citable atoms. Never moves the verdict; safe to omit.
    target is signature-introspected by the fan-out so the CASE-008 sm_modality_mismatch_caveat
    (keyed on the biologics-approved crosswalk) reaches the composed profile."""
    h = _headline(cards, fired, verdict_pair, target=target)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic small-molecule tractability facet; claim_vector is a "
        "POSITIVE-valence druggability decomposition. Verdict owned by the "
        "druggability resolver, not this projection."
    )
    return facet


def _llm_synthesis(
    cards, fired, verdict_pair, target, indication, model_id=None, subtype=None, literature_synthesis=None
):
    """Fan-out opt-in (mirrors _synthesis_facet): return this lens's provenance-tagged
    llm_synthesis block for the COMPOSED target-profile run. Builds the SAME minimal decision the
    narrator consumes standalone ({target, indication, headline, cards}) from the fan-out's already-
    resolved cards + this skill's _headline, then narrates through its OWN lens synthesizer. Best-
    effort + VERDICT-INERT: never enters fired/verdict/cards — a failure is the caller's to swallow.
    `literature_synthesis` (optional, from the fan-out's pre-narration literature lane) is threaded
    onto the decision the narrator reads so exec_bullets weave + cite it (None → byte-identical)."""
    headline = _headline(cards, fired, verdict_pair, target=target)
    decision = {
        "target": target,
        "indication": indication,
        "headline": headline,
        "cards": [{"card_id": c.get("card_id"), "summary": c.get("summary") or {}} for c in cards],
        "literature_synthesis": literature_synthesis,
    }
    return make_synthesize_fn(_LENS)(decision, model_id, subtype)  # migrated to generic capsule-driven engine


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",
            question=QUESTION,
            verdict_fn=_snapshot,
            headline_fn=_headline,
            # Skill-level graphics (opt-in --figures): the canonical headline hero (verdict · confidence ·
            # top tension). Additive / display-only; mirrors tumor-presence.
            skill_figures_fn=emit_headline_hero,
            # Opt-in --synthesize narrates through the SMALL-MOLECULE tractability lens — its own tool schema
            # + prompt, foregrounding ON-TARGET-chemical vs FORWARD-structural vs neither (a discordant read
            # ARGUES AGAINST), plus the additive degrader read. Two-slot / verdict-inert: the dispatcher
            # attaches decision['llm_synthesis'] as a sibling key AFTER the spine is composed, so it is
            # structurally impossible for the narration to alter druggability_snapshot. Without this
            # synthesize_fn the dispatcher would fall back to the PRESENCE narrator (wrong lens — B3b, 2026-08-06).
            synthesize_fn=make_synthesize_fn(_LENS),
            # Opt-in --literature: a VERDICT-INERT literature corroboration/contradiction lane (mirrors FR #987
            # / tumor-selectivity #964 / genomic-alteration #982). Attaches decision['literature_synthesis']
            # (Europe PMC → PubTator3 fallback grounding + a post-synthesis verify_citations pass) and feeds the
            # --synthesize narrator. The _LENS_QUERY_TERMS entry for "tractability-small-molecule" (small-molecule
            # inhibitor / direct target engagement / tool compound / covalent / allosteric pocket / structural
            # ligandability) lives in literature_retrieval.py. Two-slot / spine-untouched: the dispatcher attaches
            # it AFTER the deterministic decision is composed, so it is structurally impossible for the literature
            # lane to alter druggability_snapshot. This is the lane that RESOLVES the directness_caveat — the
            # DGIdb/ChEMBL interaction roster (indirect-inclusive) is exactly what a literature pass adjudicates.
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            # Signals-first: tuned sub-group reader for the tractability vocabulary. Verdict-INERT.
            subgroup_classify=make_value_classifier(_TRACT_VALUE_TIERS),
        )
    )
