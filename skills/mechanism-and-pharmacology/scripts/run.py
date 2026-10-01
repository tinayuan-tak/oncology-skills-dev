#!/usr/bin/env python3
"""mechanism-and-pharmacology — Phase-D wired skill (graduated 2026-07-08).

Signaling-network mechanism + candidate MoA hooks + PD-marker suggestions.
Consumes the signaling-network-mechanism card (a directed network composed
from SIGNOR + CollecTRI + Reactome, classified into a 31-class MoA ontology).
Emits a data-package output tree with rule-derived per-modality signals.

Refactor (2026-07-09): now uses the shared
_skills_common.dispatcher.run_wired_skill(...) entry point. Skill-
specific logic (CARDS list + verdict + headline) shrinks to a few
callbacks; boilerplate (arg parsing, resolve_cards, fired_rules,
modality-lens wiring, write_package) moves into the dispatcher. The
previous inline implementation is removed; behavior is equivalent.
"""

from __future__ import annotations

import sys

from _skills_common import get_card_field
from _skills_common.claim_record import assemble_claim_record
from _skills_common.dispatcher import run_wired_skill
from _skills_common.headline_core import HeadlineSpec, build_headline, build_synthesis_facet
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.mechanism_claims import mechanism_claim_vector, mechanism_key_signals
from _skills_common.mechanism_question_table import mechanism_question_table
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import MECHANISM_PHARMACOLOGY as _LENS
from _skills_common.resolver import resolve_or_raise
from _skills_common.skill_report import ROLE_GATING, build_skill_report
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: mechanistic characterization + MoA hooks
# present. The fleet-default heuristic tags these values `absent`; default_classify is the fallback.
_MECHANISM_VALUE_TIERS = {
    "well_characterized": "strong",
    "moderately_characterized": "moderate",
    "poorly_characterized": "weak",
    "uncharacterized": "absent",
    "drug_suppressed": "strong",
    "drug_induced": "moderate",
    "no_perturbation_response": "absent",
    "phospho_present": "moderate",
    "phospho_absent": "absent",
    "relatively_high": "moderate",
    "relatively_low": "weak",
    "pathway_inactive": "absent",
}


SKILL_NAME = "mechanism-and-pharmacology"
SKILL_VERSION = "1.12.0"  # 1.12.0 (2026-10-01): + driver-pathway-position card (pathway-context epic SK#2314 P1) — target+indication-conditioned POSITIONAL read (member/upstream/downstream of the indication's frequently-altered driver pathway); SOFT/VERDICT-INERT display facet (soft axis_fit rules only, no resolver — mechanism_verdict byte-stable, resolver keys only on network_class).   # 1.11.0 (2026-09-19): CASE-027-D1 — VERDICT-INERT mechanism_verdict_currency note: names that mechanism_verdict measures signaling-network ANNOTATION-DENSITY currency, so a partial/sparse verdict on a non-signaling mechanism class (surface antigen / neomorphic-metabolic enzyme / structural protein / synthetic-lethal partner) is expected by construction, NOT a poorly-characterized target. Constant scale-disclaimer (no over-call risk), complements curation_gap_note; cannot assert the class (points to target-profile mechanism_mismatch). Spine byte-stable (resolver keys only on network_class; replay guard asserts verdict + driving_rule_id).   # 1.10.2 (2026-09-12): curation_gap_note signal-specificity split (20-target lit-panel) — target-specific (phospho/co-essentiality) vs indication/expression-level (PROGENy/tahoe) signals; context-level-only thin targets get thin_network_context_level_signal_only (no curation-gap over-call for surface antigens like CEACAM5/MSLN). Verdict-inert.   # 1.10.1 (2026-09-12): mapped-MoA guard note — has_actionable_moa/has_pd_marker now require a MAPPED MoA class (method fix); confirmation-caveat note text + docs updated (31-class ontology, Reactome=context). Verdict-inert; spine byte-stable.   # 1.10.0 (2026-09-04): VERDICT-INERT prediction_lane_caveat MATERIALITY gate — fires only when the non-curated (kinome-prediction + co-essentiality) lanes are at least as large as the curated network, so it goes quiet on curated-dominant hubs (MYC/TP53) where firing on ~every target was noise. Spine byte-stable.   # 1.9.0 (2026-09-04): --literature lane (run_wired_skill make_literature_fn(MECHANISM_PHARMACOLOGY)) + VERDICT-INERT actionable-MoA INFLATION surfacing (mechanism_confirmation_caveat = has_actionable_moa off a CONTEXT-FREE curated edge without indication-operative validation, clinically-precedented false-demote guard; prediction_lane_caveat = kinome-atlas/co-essentiality lanes carried alongside but never merged; curation_gap_note; mechanism_provenance quorum summary; MECHANISM_PHARMACOLOGY thesis + polarity_note). Spine byte-stable (resolver keys only on network_class).   # 1.8.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.   # 1.7.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.                       # stamped into provenance.yaml — MUST equal SKILL.md metadata.version
#        facet (verdict-inert; SIGNOR cross-referenced)
# 1.5.0: pathway-activity-context (PROGENy)
# 1.4.0: + tahoe-drug-perturbation MoA facet (verdict-inert)

CARDS = [
    "signaling-network-mechanism",
    # tahoe-drug-perturbation (added 2026-08-10) — single-cell drug-perturbation MoA facet from
    # Tahoe-100M (which drugs move the target's expression, in which cancer lines). DISPLAY-ONLY
    # facet: feeds NO resolver rung (mechanism.resolver.yaml keys only on signaling-network-mechanism),
    # so the mechanism_verdict stays byte-stable. Backtest: engagement != dependency (a MoA lens,
    # not a dependency/selectivity signal).
    "tahoe-drug-perturbation",
    # phospho-pathway-activity RE-HOMED here 2026-08-05 (was tumor-presence). Phosphorylation is an
    # ACTIVITY / signaling-STATE readout (CPTAC phosphoproteomics: is the target phosphorylated, at
    # which sites, in how many tumors) — a MECHANISM signal, not a presence/abundance one. DISPLAY-ONLY
    # facet: feeds NO resolver rung, so the mechanism_verdict stays byte-stable (the mechanism resolver
    # keys only on signaling-network-mechanism fields).
    "phospho-pathway-activity",
    "pathway-activity-context",  # Track PROGENy (2026-08-10): per-indication PROGENy
    # pathway-ACTIVITY context (Schubert 2018). VERDICT-INERT
    # (like phospho) — upgrades Mechanism from topology-only
    # to quantitative activity; keys no resolver rung.
    # dependency-predictability (added 2026-08-18) — DepMap predictability feature attribution as a
    # DATA-DRIVEN complement to the curated SIGNOR network: the genome-wide omics features that best
    # predict the target's Chronos dependency are candidate mechanistic co-dependencies, cross-referenced
    # against SIGNOR's upstream/downstream partner set. DISPLAY-ONLY facet: feeds NO resolver rung
    # (mechanism_verdict byte-stable), and NOT in rules_scope. Correlational (importance, not causal) —
    # hypothesis-generating; confounder feature-classes (arm/lineage/signature/metabolite) are filtered out.
    "dependency-predictability",
    # driver-pathway-position (added 2026-10-01, pathway-context epic SK#2314 P1) — target-conditioned,
    # indication-conditioned POSITIONAL read: does the target sit IN / UPSTREAM of / DOWNSTREAM of the
    # indication's frequently-altered driver pathway? Cross-read of Sanchez-Vega per-gene membership x
    # per-indication alteration frequency x SIGNOR directed edges. SOFT / VERDICT-INERT (card
    # evidence_tier: inferred; soft axis_fit rules only, wired to NO resolver — mechanism_verdict stays
    # byte-stable, the resolver keys only on signaling-network-mechanism's network_class). Reports
    # position, NOT desirability (the MARK2->YAP/TAZ membership-lens verdict was rejected as overfit).
    "driver-pathway-position",
]

QUESTION = (
    "For {target} in {indication}, what upstream regulators + "
    "downstream effectors are catalogued in SIGNOR, and which MoA "
    "classes are candidate hooks for SM / degrader / molecular-glue "
    "programs?"
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (2026-07-20).
    The former if-chain now lives in resolvers/mechanism.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "mechanism")


# ── FACTORED-RECORD SHADOW (M1) — the MECHANISM per-axis builder. Describes how well the target's
#    mechanism / pharmacodynamics is characterized: understanding SUPPORTS a program. VERDICT-INERT:
#    surfaced by the fan-out into decision.claim_record_shadow.mechanism, consumed by NOTHING.
#    Mechanism has no verdict-disjoint corroborator (CERTAINTY_MODEL: unmeasured) → minimal coverage-only
#    certainty. Mirrors the other axes' hook.
# `data_unavailable` and `insufficient` are intentionally omitted → they fall through
# `.get(v, "none")` to magnitude level "none" (verdict-inert; feeds only claim_record_shadow).
_MECH_LEVEL = {"well_characterized": "strong", "partial": "moderate", "sparse": "weak"}


def _mech_availability(v) -> str:
    if v == "data_unavailable" or v is None:
        return "not_wired"
    if v == "insufficient":
        return "insufficient"
    return "measured_positive"  # well_characterized / partial / sparse


def _mech_direction(v) -> str:
    if v in ("well_characterized", "partial", "sparse"):
        return "supports"  # any degree of mechanistic understanding supports
    return "neutral"


def _mech_certainty(v) -> dict:
    if v == "data_unavailable" or v is None:
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    if v in {"insufficient", "sparse"}:  # set literal, NOT a 2-string tuple — keeps this verdict
        # membership check from being misread as a rule-id precedence tuple by the reference-drift guard.
        return {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 0.5}
    return {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook.

    Record-enrichment (review move #3): populate mechanism.classes from the signaling-network card's
    `moa_classes_present` (the 31-class MoA ontology). This puts the WHY / candidate-MoA-hook onto the
    chart (mechanism.classes was empty everywhere) — a legitimate DISPLAY coordinate on the mechanism
    axis's own record. It does NOT wire the ontology into any resolver/gate (the adversarial review's
    caution: keep MoA rule-wiring speculative until a specific class drives a specific decision)."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    moa = (
        get_card_field(cards, "signaling-network-mechanism", "moa_classes_present")
        if any(c.get("card_id") == "signaling-network-mechanism" for c in (cards or []))
        else None
    )
    mechanism = {"classes": list(moa)} if isinstance(moa, (list, tuple)) and moa else None
    return assemble_claim_record(
        axis="mechanism",
        state=(v or "insufficient"),
        direction=_mech_direction(v),
        availability=_mech_availability(v),
        magnitude={"level": _MECH_LEVEL.get(v, "none")},
        mechanism=mechanism,
        certainty=_mech_certainty(v),
        fired=fired,
        cards=cards,
    )


# --- dependency-predictability feature-attribution facet (verdict-inert) ---------------------------
# feature_class -> the prefix its `feature` name carries a PARTNER gene symbol under. These cross-gene
# omics classes are mechanistically interpretable AND name a single partner gene we can cross-reference
# against the SIGNOR partner set. (Reader emits feature names like "expr_EDA2R", "cn_NLK", "ms_SPINT2".)
_PARTNER_FEATURE_PREFIX = {
    "cross_gene_expression": "expr_",
    "cross_gene_copy_number": "cn_",
    "ms_protein": "ms_",
    "rppa_protein": "rppa_",
    "paralog_dep": "paralog_dep_",
    "methylation_tss": "methyl_",
}
# own_* features = the TARGET's OWN omics predict its own dependency (self-driven, e.g. KRAS->own hotspot):
# mechanistically meaningful but NOT a partner — surfaced separately as pred_self_driven.
_SELF_FEATURE_CLASSES = {"own_expression", "own_copy_number", "own_mut_hotspot", "own_mut_damaging"}
# Everything else (arm_level_cn, lineage, mol_signature, metabolomics, msi_status, oncokb_gof/lof,
# fusion, sv_gene) names no single mechanistic partner gene → excluded from the SIGNOR partner
# cross-reference, but (since #1942) still surfaced LABELED in pred_top_feature_labels rather than dropped.


def _predictability_mechanism_facet(cards):
    """VERDICT-INERT facet: DepMap dependency-predictability feature attribution as a DATA-DRIVEN
    complement to the curated SIGNOR network.

    The predictability model's top features (genome-wide omics that best predict the target's Chronos
    dependency) are candidate mechanistic co-dependencies. We keep only the mechanistically-plausible,
    partner-gene-bearing feature classes and cross-reference each partner gene against SIGNOR's
    upstream/downstream partner symbols: overlap = curated+empirical CONVERGENCE (a stronger MoA/PD-marker
    hypothesis); a predictive partner ABSENT from SIGNOR = a data-driven hypothesis the curated network
    does not yet capture. NOTE: in the canonical depmap-predictability 26q1-v4 build importance is
    mean(|SHAP|) TreeExplainer attribution (the older v1/v2/v3 pins fall back to RF-impurity / XGB-gain;
    see the predictability manifest); either way it is CORRELATIONAL, not causal — hypothesis-generating
    only. Feeds NO resolver."""
    pclass = get_card_field(cards, "dependency-predictability", "predictability_class")
    dom_class = get_card_field(cards, "dependency-predictability", "pred_dominant_feature_class")
    top_rf = get_card_field(cards, "dependency-predictability", "pred_top_features_rf") or []

    # SIGNOR partner symbol set (upstream regulators + downstream effectors). The reader emits the
    # per-edge key `partner_gene_symbol`; the card doc calls it `partner_symbol` — read both defensively.
    signor_partners = set()
    for key in ("upstream_regulators", "downstream_effectors"):
        edges = get_card_field(cards, "signaling-network-mechanism", key)
        if not isinstance(edges, list):
            continue  # frozen-fixture placeholder string, or field absent -> no partner symbols to x-ref
        for e in edges:
            if isinstance(e, dict):
                sym = e.get("partner_gene_symbol") or e.get("partner_symbol")
            elif isinstance(e, str):
                sym = e  # some emitters carry a bare partner symbol string
            else:
                sym = None
            if sym:
                signor_partners.add(str(sym).upper())

    partner_features = []
    for f in top_rf:
        prefix = _PARTNER_FEATURE_PREFIX.get((f or {}).get("feature_class"))
        if not prefix:
            continue  # self (own_*) or confounder — not a partner feature
        name = f.get("feature") or ""
        gene = name[len(prefix) :] if name.startswith(prefix) else name
        partner_features.append(
            {
                "gene": gene,
                "feature_class": f.get("feature_class"),
                "importance": f.get("importance"),
                "in_signor": gene.upper() in signor_partners,
            }
        )
    corroborated = [pf["gene"] for pf in partner_features if pf["in_signor"]]
    # Humanized attribution of ALL top features (#1942) — arm/lineage/molsig/msi/metab are surfaced
    # LABELED here rather than dropped (the partner list above still keeps only partner-gene classes for
    # the SIGNOR cross-reference). Prefer the producer-stamped `feature_label`; fall back to the raw token
    # for older pins that predate it. Verdict-INERT display.
    top_feature_labels = []
    for f in top_rf:
        if not isinstance(f, dict):
            continue
        raw = f.get("feature") or ""
        top_feature_labels.append(
            {
                "feature": raw,
                "feature_label": f.get("feature_label") or raw,
                "feature_class": f.get("feature_class"),
                "importance": f.get("importance"),
            }
        )
    return {
        "pred_predictability_class": pclass,
        "pred_dominant_feature_class": dom_class,
        "pred_self_driven": dom_class in _SELF_FEATURE_CLASSES,
        "pred_mechanistic_partner_features": partner_features[:10],
        "pred_top_feature_labels": top_feature_labels[:10],
        "pred_signor_corroborated_partners": corroborated,
        "pred_n_signor_corroborated": len(corroborated),
    }


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# mechanism-and-pharmacology's declaration for the shared headline_core builder. This skill is largely
# DESCRIPTIVE: the mechanism_verdict is a signaling-network CHARACTERIZATION class (well_characterized /
# partial / sparse / data_unavailable / insufficient — the has_pd_marker verdict was removed 2026-09-07,
# resolver v1.2.0, as a structurally-dead rung; the PD marker survives as headline.has_pd_marker), and —
# per mechanism_claims.py — NETWORK is ANNOTATION DENSITY (curated edge count = curation, NOT target
# biology, capped at
# moderate). So none of these rungs is a favorable/unfavorable target-quality CALL; every rung is coloured
# NEUTRAL (there is no clear positive/negative program signal to encode). Verdict-INERT — a one-way
# projection over the already-computed headline (mechanism_verdict stays byte-stable, frozen by the
# EGFR/CEACAM5 replay guard).

# The mechanism.resolver verdict vocabulary → human phrase (prettify fallback for any future addition).
_MECHANISM_VERDICT_PHRASE = {
    "well_characterized": "Well-characterized signaling network",
    "partial": "Partially-characterized signaling network",
    "sparse": "Sparse signaling network",
    "data_unavailable": "Data unavailable",
    "insufficient": "Insufficient evidence",
}


def _mechanism_verdict_polarity(v) -> str:
    """The skill's OWN reading of the mechanism verdict (colours the hero badge; never a gate). This skill
    is DESCRIPTIVE — the verdict is a network-characterization / annotation-density class, NOT a
    favorable/unfavorable target call — so every rung is NEUTRAL (a richly-curated network is not a better
    TARGET, just a better-annotated one; the honesty cap in mechanism_claims.py)."""
    return "neutral"


# ── VERDICT-INERT actionable-MoA INFLATION surfacing (2026-09-04; mirrors tractability `directness_caveat`
#    / surface `surface_confirmation_caveat`). The mechanism resolver keys ONLY on network_class, so NONE of
#    these fields can move mechanism_verdict — they name WHY a has_actionable_moa=True call may be inflated.
#
# THE TRAP: upstream `has_actionable_moa` is composed as (>=1 curated upstream edge carrying a MAPPED MoA
# class) — as of the 2026-09-12 method fix it no longer fires off an all-'unmapped' edge set, but it STILL
# fires off ANY curated upstream edge with a classified mechanism, so it reads True for a validated-drugged
# kinase (BRAF/EGFR) AND for an undruggable pleiotropic hub / metabolic enzyme (MYC/MTAP) alike. A curated
# SIGNOR/CollecTRI edge is a CONTEXT-FREE literature aggregate; its presence does NOT prove the MoA is
# OPERATIVE/DRIVING or DIRECTLY DRUGGABLE in THIS indication. Small-molecule DIRECTNESS is owned by
# tractability-small-molecule — the caveat is a breadcrumb to it, never a verdict move here.

# FALSE-DEMOTE GUARD: targets whose actionable MoA rests on an APPROVED / registrational DIRECTLY-ACTING
# agent are NOT annotation over-calls (the surface DLL3 / tractability BRAF analog). Small, disclaimed,
# NON-EXHAUSTIVE skills-side curated set (HGNC symbols); an absent target simply gets the honest sharp
# caveat ("unvalidated IN-PACKAGE; confirm via tractability-small-molecule + the literature lane"), never a
# verdict change (this field is verdict-INERT). Basis = an approved / late-clinical directly-acting
# small-molecule or degrader engaging the target (or its immediate operative node).
_VALIDATED_ACTIONABLE_MOA_PRECEDENT = frozenset(
    {
        "BRAF",
        "EGFR",
        "KRAS",
        "MAP2K1",
        "MAP2K2",
        "MET",
        "ALK",
        "ROS1",
        "RET",
        "NTRK1",
        "NTRK2",
        "NTRK3",
        "FGFR1",
        "FGFR2",
        "FGFR3",
        "FGFR4",
        "ERBB2",
        "KIT",
        "PDGFRA",
        "PDGFRB",
        "ABL1",
        "JAK1",
        "JAK2",
        "FLT3",
        "PIK3CA",
        "AKT1",
        "MTOR",
        "CDK4",
        "CDK6",
        "CDK7",
        "CDK9",
        "BTK",
        "IDH1",
        "IDH2",
        "EZH2",
        "BCL2",
        "PARP1",
        "AR",
        "ESR1",
        "SMO",
        "KDR",
        "MDM2",
        "MCL1",
        "WEE1",
        "ATR",
        "CHEK1",
    }
)


def _mechanism_confirmation_caveat(
    has_actionable_moa, target, network_class, n_up, high_conf_edges, moa_classes
) -> dict | None:
    """Name the actionable-MoA INFLATION risk when has_actionable_moa=True. VERDICT-INERT.

    Reports WHY the actionable-MoA call may be over-called (curated context-free edge, single-source,
    no indication-operative validation); the false-demote guard spares a target with an approved
    directly-acting agent. Never changes mechanism_verdict (the resolver keys only on network_class)."""
    if not has_actionable_moa:
        return None
    moa_list = list(moa_classes or [])
    single_source = (high_conf_edges or 0) == 0
    prov = (
        "all curated edges single-source (no >=2-source corroboration)"
        if single_source
        else f"{high_conf_edges} of {n_up or '?'} curated edges >=2-source-corroborated"
    )
    if bool(target) and str(target).upper() in _VALIDATED_ACTIONABLE_MOA_PRECEDENT:
        return {
            "reason": "actionable_moa_curated_clinically_precedented",
            "note": (
                f"has_actionable_moa=True and {target} has an APPROVED / late-clinical directly-acting "
                "agent — the curated MoA edge reflects a real, indication-operative, validated "
                "druggable mechanism, NOT an annotation over-call (false-demote guard: NOT flagged as "
                "inflated). Directness / indication-fit is owned by tractability-small-molecule."
            ),
            "moa_classes_present": moa_list,
            "curated_provenance": prov,
        }
    thin = network_class in {"sparse", "partial"}  # set literal, NOT a 2-string tuple — a tuple is
    # misread as a (rule_id, verdict) precedence tuple by the reference-drift guard (test_no_reference_drift).
    reason = "actionable_moa_curated_context_free_unvalidated" + ("_thin_network" if thin else "")
    thin_clause = (
        f" The curated network itself is THIN (network_class={network_class}) — the actionable "
        "call rests on very few edges."
        if thin
        else ""
    )
    return {
        "reason": reason,
        "note": (
            f"has_actionable_moa=True is composed as (>=1 curated upstream edge with a MAPPED MoA class) off MoA classes "
            f"[{', '.join(moa_list) or 'curated upstream edges'}] — a CONTEXT-FREE curated aggregate "
            f"({prov}). Presence of a curated edge does NOT prove the MoA is OPERATIVE/DRIVING or "
            "DIRECTLY DRUGGABLE in this indication: for a pleiotropic hub / undruggable TF or metabolic "
            "enzyme this reads actionable with no validated direct hook in existence. Treat as "
            "looks-actionable-but-UNVALIDATED; confirm target-directness via tractability-small-molecule "
            f"+ the literature lane (--literature).{thin_clause}"
        ),
        "moa_classes_present": moa_list,
        "curated_provenance": prov,
    }


def _prediction_lane_caveat(kinome_atlas, coessentiality, curated_edge_count=None) -> dict | None:
    """Surface MoA hooks carried by the PREDICTION / FUNCTIONAL lanes (kinome-atlas PWM predictions +
    DepMap co-essentiality) that ride ALONGSIDE the curated network but are NEVER merged into
    network_class / has_actionable_moa. VERDICT-INERT; None when no prediction/functional lane is present.

    MATERIALITY GATE (2026-09-04): the lanes are present for nearly every studied target, so an
    unconditional caveat fires on ~every run and adds little signal. Only surface it when the non-curated
    lanes are MATERIAL — at least as large as the curated network (they could then inflate a reader's sense
    of mechanism richness), OR the curated network is empty/unavailable (any prediction lane could mislead).
    When the curated network genuinely dominates (e.g. MYC/TP53 hubs), the prediction/functional lanes are
    minor context carried in `mechanism_provenance` and do not need the caveat. curated_edge_count None
    (legacy caller) skips the gate."""
    ka = kinome_atlas or {}
    co = coessentiality or {}
    n_pred = (ka.get("n_upstream_predicted_kinases") or 0) + (ka.get("n_downstream_predicted_substrates") or 0)
    n_coess = (co.get("n_partners") or 0) if co.get("data_available") else 0
    noncurated = n_pred + n_coess
    if noncurated == 0:
        return None
    if curated_edge_count and noncurated < curated_edge_count:
        return None  # curated network dominates → caveat is noise
    lanes = []
    if ka.get("network_class") not in (None, "data_unavailable") and n_pred > 0:
        lanes.append(
            f"kinome-atlas PREDICTION ({ka.get('n_upstream_predicted_kinases') or 0} predicted "
            f"upstream kinases + {ka.get('n_downstream_predicted_substrates') or 0} predicted "
            "downstream substrates; PWM motif-based, never functionally validated)"
        )
    if n_coess > 0:
        lanes.append(
            f"DepMap co-essentiality ({n_coess} correlated partners; correlational, not a curated mechanism edge)"
        )
    if not lanes:
        return None
    return {
        "reason": "prediction_lanes_carried_alongside",
        "lanes": lanes,
        "note": (
            "Prediction / functional lanes are surfaced ALONGSIDE the curated network but are NEVER "
            "merged into network_class or has_actionable_moa: " + "; ".join(lanes) + ". Do NOT read a "
            "predicted kinase-substrate motif or a co-essential partner as a curated or validated MoA "
            "hook — a predicted or correlational edge alone must not lift the actionable-MoA call."
        ),
    }


def _curation_gap_note(network_class, phospho, pathway_activity, tahoe, coess_partners) -> dict | None:
    """Fire when a thin curated network CO-OCCURS with an independent signal. VERDICT-INERT; None otherwise.

    SIGNAL-SPECIFICITY SPLIT (2026-09-12, 20-target literature-panel refinement): the panel showed the
    former note over-called a CURATION GAP for genuinely NON-signaling targets (e.g. the surface adhesion
    molecule CEACAM5), because it treated INDICATION-level PROGENy pathway activity + drug-perturbation
    EXPRESSION engagement as if they were target-specific mechanism evidence. They are not:
      - PROGENy pathway_activity is a per-INDICATION cohort readout (the tumor's pathways are active), NOT a
        signal that THIS target carries an uncaptured signaling mechanism — it is ~always high in an
        active-pathway indication and fires on nearly every thin target.
      - tahoe drug-perturbation is an EXPRESSION response (drugs move the target's mRNA), not a signaling
        edge the curation missed.
    Only measured target PHOSPHO-activity and DepMap CO-ESSENTIALITY partners are TARGET-SPECIFIC functional
    signals. So we split the corroboration and set the strength accordingly:
      - >=2 target-specific signals (corroboration across BOTH independent lanes — phospho AND
        co-essentiality) → 'curated_network_under_reads_operative_signal' (likely curation gap;
        the IDH1/WRN pattern — a real mechanism tissue-agnostic curation misses).
      - A single target-specific signal, or ONLY indication/expression-level signals →
        'thin_network_context_level_signal_only' (the thin network may reflect a GENUINELY non-signaling
        target — surface antigen / metabolic / structural protein — as readily as a curation gap; do NOT
        assert a gap on one lane alone). This keeps the honest hypothesis without over-claiming a
        mechanism CEACAM5/MSLN-type surface antigens do not have.
      (2026-09-30, issue #1808: raised from a single-signal trigger, which asserted an operative-mechanism
      curation gap off as little as one phospho class or one co-essential partner.)"""
    thin = network_class in {"sparse", "partial", "data_unavailable"}  # set, not tuple (drift-guard)
    if not thin:
        return None
    target_specific = []
    context_level = []
    if phospho in ("phospho_active", "phospho_present"):
        target_specific.append(f"measured target phospho-activity ({phospho})")
    if (coess_partners or 0) > 0:
        target_specific.append(f"{coess_partners} DepMap co-essential partners")
    if pathway_activity == "relatively_high":
        context_level.append("elevated PROGENy pathway activity (INDICATION-level, not target-specific)")
    if tahoe in ("drug_suppressed", "drug_induced", "bidirectionally_perturbed"):
        context_level.append(f"drug-perturbation EXPRESSION engagement ({tahoe}; expression, not a signaling edge)")
    if not (target_specific or context_level):
        return None
    if len(target_specific) >= 2:
        signals = target_specific + context_level
        return {
            "reason": "curated_network_under_reads_operative_signal",
            "target_specific_signals": target_specific,
            "context_level_signals": context_level,
            "note": (
                f"The curated signaling network is thin (network_class={network_class}) yet TARGET-SPECIFIC "
                "functional signals suggest an operative mechanism this context-free curation under-reads: "
                + "; ".join(signals)
                + ". An indication-operative mechanism (e.g. a neomorphic-metabolic / epigenetic driver like "
                "IDH1, a synthetic-lethal-exploited dependency, or a fusion-rewired driver) can be missing "
                "from tissue-agnostic curated edges — read a thin network_class as a likely CURATION gap "
                "here, not proof of no mechanism."
            ),
        }
    if target_specific:
        # Exactly one target-specific signal: below the >=2 corroboration threshold (#1808) — surface it
        # alongside any context-level signals, but fall through to the conservative note rather than
        # asserting a curation gap off a single, uncorroborated lane.
        all_signals = target_specific + context_level
        return {
            "reason": "thin_network_context_level_signal_only",
            "context_level_signals": context_level,
            "target_specific_signals": target_specific,
            "note": (
                f"The curated signaling network is thin (network_class={network_class}); only a single "
                "target-specific signal is present, below the corroboration threshold for asserting a "
                "curation gap: " + "; ".join(all_signals) + ". A lone phospho or co-essentiality signal, "
                "without corroboration across both independent lanes, may reflect a GENUINELY non-signaling "
                "target — a lineage-restricted surface antigen (CEACAM5/MSLN), a metabolic or structural "
                "protein — as readily as a curation gap. Do NOT read this as evidence of an uncaptured "
                "signaling mechanism; confirm the target's biology via the literature lane (--literature)."
            ),
        }
    return {
        "reason": "thin_network_context_level_signal_only",
        "context_level_signals": context_level,
        "note": (
            f"The curated signaling network is thin (network_class={network_class}); the only co-occurring "
            "signals are INDICATION / EXPRESSION-level, not target-specific: "
            + "; ".join(context_level)
            + ". With no target-specific mechanism signal (phospho-activity / co-essentiality), the thin "
            "network may reflect a GENUINELY non-signaling target — a lineage-restricted surface antigen "
            "(CEACAM5/MSLN), a metabolic or structural protein — as readily as a curation gap. Do NOT read "
            "this as evidence of an uncaptured signaling mechanism; confirm the target's biology via the "
            "literature lane (--literature)."
        ),
    }


# ── VERDICT-INERT mechanism-verdict CURRENCY note (CASE-027-D1; 2026-09-19). The mechanism_verdict is a
#    signaling-network CHARACTERIZATION class — calibrated to curated signaling-edge / phospho ANNOTATION
#    DENSITY (mechanism_claims.py caps it at moderate; NETWORK is curation, not target biology). For a target
#    whose therapeutic mechanism is NOT signaling-network-mediated — a lineage-restricted SURFACE ANTIGEN for
#    redirected cytotoxicity (CEACAM5/MSLN), a NEOMORPHIC / metabolic enzyme (IDH1), a STRUCTURAL protein, or
#    a SYNTHETIC-LETHAL partner (WRN/SMARCA2) — a partial/sparse verdict is expected BY CONSTRUCTION and is
#    NOT evidence the target is poorly characterized; it is characterized in a DIFFERENT CURRENCY (antigen
#    expression + surface fit / neomorphic enzymatic activity + genomic driver / partner-conditional SL).
#    CASE-027-D1's five `mechanism-partial-neutral` pairs (CEACAM5/LUAD, IDH1/LGG, MSLN/MESO, SMARCA2/LUAD,
#    WRN/COADREAD) are exactly this shape.
#
#    THE BOUNDARY that scopes this to a NOTE and not a re-grade: this skill reads only signaling-network +
#    phospho + perturbation cards, so it CANNOT know which non-signaling class applies (that lives in the
#    target's THESIS — target-profile's `mechanism_mismatch` dimension, CASE-018). So the note NAMES the
#    currency and the mis-read risk WITHOUT asserting a class. Unlike `curation_gap_note` (which fires
#    CONDITIONALLY on co-occurring signals and was deliberately split to avoid over-calling a curation gap on
#    non-signaling targets), this is a CONSTANT descriptor of what the scale measures — so it has NO
#    false-positive risk and it also covers the bare-thin / no-corroborating-signal case that fires no
#    curation_gap_note at all. Verdict-INERT: never moves the byte-stable verdict (the EGFR/CEACAM5 replay
#    guard asserts verdict + driving_rule_id only) and forces nothing.
_MECHANISM_VERDICT_UNDER_READS = ("partial", "sparse", "data_unavailable", "insufficient")


def _mechanism_verdict_currency(verdict) -> dict | None:
    """Name — VERDICT-INERT — that `mechanism_verdict` measures signaling-network annotation-density currency,
    so a below-rich verdict does NOT mean the target is poorly characterized: a non-signaling mechanism class
    is characterized in a different currency. None for well_characterized (there is no under-read to name)."""
    if verdict not in _MECHANISM_VERDICT_UNDER_READS:
        return None
    return {
        "reason": "mechanism_verdict_is_signaling_annotation_density_currency",
        "authoritative": "verdict",
        "measures": (
            "curated signaling-network + phospho ANNOTATION DENSITY (a curation currency, capped at "
            "moderate), NOT target quality, druggability, or characterization in a non-signaling currency"
        ),
        "not_a_target_quality_call": True,
        "note": (
            f"mechanism_verdict={verdict} scores the density of the target's CURATED SIGNALING NETWORK — the "
            "WRONG CURRENCY for a target whose therapeutic mechanism is not signaling-network-mediated. A "
            "lineage-restricted SURFACE ANTIGEN for redirected cytotoxicity (CEACAM5/MSLN), a NEOMORPHIC / "
            "metabolic enzyme (IDH1), a STRUCTURAL protein, or a SYNTHETIC-LETHAL partner (WRN/SMARCA2) reads "
            "partial/sparse BY CONSTRUCTION and is characterized in a DIFFERENT currency (antigen expression + "
            "surface fit / neomorphic enzymatic activity + genomic driver / partner-conditional SL evidence). "
            "Do NOT read a below-rich mechanism_verdict as a poorly-characterized TARGET. This skill reads only "
            "signaling / phospho / perturbation cards and CANNOT assert which non-signaling class applies — "
            "confirm the target's mechanism class via its thesis (target-profile `mechanism_mismatch`) and the "
            "target's own-currency skill; the mechanism_verdict is authoritative and unchanged for what it "
            "measures (signaling-network annotation density)."
        ),
    }


_MECHANISM_HEADLINE_SPEC = HeadlineSpec(
    gate="mechanism",
    axis_labels={
        "NETWORK": "signaling-network topology",
        "PHOSPHO": "phospho-activity",
        "PATHWAY": "pathway activity context",
        "PERTURBATION": "drug-perturbation engagement",
        "PREDICTABILITY": "dependency predictability",
    },
    axis_keys=("NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"),
    critical_axes=("NETWORK",),  # NETWORK (is there a catalogued signaling network?) is the axis the
    # mechanism verdict keys on — the decision-critical coverage floor.
    verdict_label=lambda v: _MECHANISM_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    # No cross-cutting flag beyond the claim_vector conflicts + key_signals caveat: this skill's key_signals
    # emits no caveat (caveat_fns={}), and the NETWORK annotation-density honesty is a STRUCTURAL disclaimer
    # (mechanism_claims._DISCLAIMER), not a per-run tension. So tension_extra=None (matching FR). Any real
    # per-axis conflict is already ranked by headline_core.rank_tension.
    tension_extra=None,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed mechanism headline. Reads the resolved
    mechanism_verdict + the verdict-inert claim_vector / key_signals; never moves the spine. No
    CERTAINTY_MODEL sidecar is emitted by this skill, so confidence is derived from the claim vector's
    corroboration (weakest-link over measured axes, capped by conflict/coverage)."""
    v = headline.get("mechanism_verdict")
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_MECHANISM_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=_mechanism_verdict_polarity(v),
    )


def _headline(cards, fired, verdict_pair, target=None):
    """Skill-specific headline: SIGNOR-network descriptive fields + verdict-inert facets.

    `target` is threaded in by the dispatcher (introspected — 3-arg callers are byte-identical) so the
    verdict-INERT actionable-MoA `mechanism_confirmation_caveat` can apply its clinically-precedented
    false-demote guard by symbol. None (composed-facet path) → no milder tier, the honest sharp default."""
    v, drv = verdict_pair or ("insufficient", None)
    headline = {
        "mechanism_verdict": v,
        "driving_rule_id": drv,
        "network_class": get_card_field(cards, "signaling-network-mechanism", "network_class"),
        "n_upstream_regulators": get_card_field(cards, "signaling-network-mechanism", "n_upstream_regulators"),
        "n_downstream_effectors": get_card_field(cards, "signaling-network-mechanism", "n_downstream_effectors"),
        "moa_classes_present": get_card_field(cards, "signaling-network-mechanism", "moa_classes_present"),
        "pd_marker_classes_present": get_card_field(cards, "signaling-network-mechanism", "pd_marker_classes_present"),
        "has_actionable_moa": get_card_field(cards, "signaling-network-mechanism", "has_actionable_moa"),
        "has_pd_marker": get_card_field(cards, "signaling-network-mechanism", "has_pd_marker"),
        "moa_ontology_version": get_card_field(cards, "signaling-network-mechanism", "moa_ontology_version"),
        # coverage-quality signal (#1807 carved slice) — fraction of curated edges that fell to
        # 'unmapped' class; a data-quality/audit metric, verdict-inert. Lifted into the machine-
        # readable headline so downstream consumers no longer need prose-only access.
        "moa_ontology_unmapped_fraction": get_card_field(
            cards, "signaling-network-mechanism", "moa_ontology_unmapped_fraction"
        ),
        # Phospho ACTIVITY facet (re-homed 2026-08-05) — CPTAC phosphoproteomics signaling-state
        # readout. Display-only (feeds no resolver); enriches the mechanism picture for kinases/
        # signaling nodes. data_unavailable for indications with no CPTAC cohort or non-phosphoproteins.
        "phospho_activity_class": get_card_field(cards, "phospho-pathway-activity", "phospho_activity_class"),
        "n_phosphosites": get_card_field(cards, "phospho-pathway-activity", "n_phosphosites"),
        "max_site_detection_fraction": get_card_field(cards, "phospho-pathway-activity", "max_site_detection_fraction"),
        # Detection-gap disambiguation (card caveats mandate reading these before inferring biology off
        # phospho_not_detected): phosphoprotein_detected_in_other_cohorts=true means THIS cohort's zero is
        # a detection gap, not a real no-signal; phospho_axis_uninformative_reason names why the axis is
        # data_unavailable when not simply a missing cohort (e.g. total_protein_not_detected_in_cohort).
        "phosphoprotein_detected_in_other_cohorts": get_card_field(
            cards, "phospho-pathway-activity", "phosphoprotein_detected_in_other_cohorts"
        ),
        "phospho_axis_uninformative_reason": get_card_field(
            cards, "phospho-pathway-activity", "phospho_axis_uninformative_reason"
        ),
        # Tahoe single-cell drug-perturbation MoA facet (added 2026-08-10) — which drugs move the
        # target's expression, in how many cancer lines. Display-only (feeds no resolver); a
        # target-ENGAGEMENT / MoA lens (engagement != dependency, per the Pilot-2 backtest).
        "tahoe_perturbation_class": get_card_field(cards, "tahoe-drug-perturbation", "tahoe_perturbation_class"),
        "tahoe_n_perturbing_drugs": get_card_field(cards, "tahoe-drug-perturbation", "n_perturbing_drugs"),
        "tahoe_strongest_mover_drug": get_card_field(cards, "tahoe-drug-perturbation", "strongest_mover_drug"),
        "tahoe_strongest_mover_log2fc": get_card_field(cards, "tahoe-drug-perturbation", "strongest_mover_log2fc"),
        "tahoe_top_suppressing_drugs": get_card_field(cards, "tahoe-drug-perturbation", "top_suppressing_drugs"),
        "tahoe_top_inducing_drugs": get_card_field(cards, "tahoe-drug-perturbation", "top_inducing_drugs"),
    }
    # Predictability feature-attribution facet (verdict-inert; SIGNOR-cross-referenced).
    headline.update(_predictability_mechanism_facet(cards))

    # ── PROVENANCE / QUORUM fields lifted from the composed card (NOT previously surfaced) + the
    #    VERDICT-INERT actionable-MoA INFLATION caveats (2026-09-04). The mechanism resolver keys ONLY on
    #    network_class, so none of this can move mechanism_verdict; the EGFR/CEACAM5 replay guard asserts
    #    verdict + driving_rule_id only → spine byte-stable.
    def _as_dict(x):  # frozen fixtures stringify big nested structs — coerce defensively
        return x if isinstance(x, dict) else {}

    def _as_list(x):
        return x if isinstance(x, list) else []

    _hce = get_card_field(cards, "signaling-network-mechanism", "high_confidence_edges_count")
    _hce = _hce if isinstance(_hce, int) else 0
    _kinome = _as_dict(get_card_field(cards, "signaling-network-mechanism", "kinome_atlas_predictions"))
    _coess = _as_dict(get_card_field(cards, "signaling-network-mechanism", "coessentiality_context"))
    _pathway_activity = get_card_field(cards, "pathway-activity-context", "pathway_activity_class")
    _n_up = headline.get("n_upstream_regulators") or 0
    _n_dn = headline.get("n_downstream_effectors") or 0
    _n_coess = (_coess.get("n_partners") or 0) if _coess.get("data_available") else 0
    headline["high_confidence_edges_count"] = _hce
    headline["mechanism_source_counts"] = _as_dict(
        get_card_field(cards, "signaling-network-mechanism", "source_counts")
    )
    headline["mechanism_sources_wired"] = _as_list(
        get_card_field(cards, "signaling-network-mechanism", "sources_wired")
    )
    headline["kinome_atlas_prediction_lane"] = {
        "network_class": _kinome.get("network_class"),
        "n_upstream_predicted_kinases": _kinome.get("n_upstream_predicted_kinases"),
        "n_downstream_predicted_substrates": _kinome.get("n_downstream_predicted_substrates"),
    }
    headline["coessentiality_lane"] = {
        "data_available": _coess.get("data_available"),
        "n_partners": _coess.get("n_partners"),
    }
    # QUORUM/PROVENANCE-aware summary — curated vs predicted vs functional provenance of the mechanism.
    # A curated multi-source edge + indication-operative validation is the strong case; a prediction lane
    # or a single context-free edge alone must NOT be read as a lifted actionable-MoA signal.
    headline["mechanism_provenance"] = {
        "curated_edge_count": (_n_up if isinstance(_n_up, int) else 0) + (_n_dn if isinstance(_n_dn, int) else 0),
        "curated_multisource_edge_count": _hce,
        "single_source_dominant": bool((_hce == 0) and ((_n_up or 0) + (_n_dn or 0) > 0)),
        "prediction_lane_edge_count": (_kinome.get("n_upstream_predicted_kinases") or 0)
        + (_kinome.get("n_downstream_predicted_substrates") or 0),
        "coessentiality_partner_count": _n_coess,
    }
    headline["mechanism_confirmation_caveat"] = _mechanism_confirmation_caveat(
        headline.get("has_actionable_moa"),
        target,
        headline.get("network_class"),
        _n_up,
        _hce,
        headline.get("moa_classes_present"),
    )
    headline["prediction_lane_caveat"] = _prediction_lane_caveat(
        _kinome,
        _coess,
        curated_edge_count=(_n_up if isinstance(_n_up, int) else 0) + (_n_dn if isinstance(_n_dn, int) else 0),
    )
    headline["curation_gap_note"] = _curation_gap_note(
        headline.get("network_class"),
        headline.get("phospho_activity_class"),
        _pathway_activity,
        headline.get("tahoe_perturbation_class"),
        _n_coess,
    )
    # CASE-027-D1: name the signaling-annotation-density CURRENCY of the mechanism_verdict — a constant,
    # verdict-INERT scale-disclaimer for the under-reads verdicts (partial/sparse/data_unavailable/
    # insufficient) so a non-signaling mechanism class is not mis-read as poorly characterized.
    headline["mechanism_verdict_currency"] = _mechanism_verdict_currency(headline.get("mechanism_verdict"))
    # verdict-INERT claim-vector projection (11th concrete) — NETWORK/PHOSPHO/PATHWAY/PERTURBATION/
    # PREDICTABILITY decomposition + citable atoms. NETWORK is capped at moderate (annotation density,
    # not biology); PHOSPHO is the one positive signal. The mechanism resolver keys only on
    # signaling-network-mechanism, so this projection cannot move the verdict.
    headline["claim_vector"] = mechanism_claim_vector(headline, cards)
    headline["key_signals"] = mechanism_key_signals(headline, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort: a formatting/read fault must NEVER discard the
    # mechanism spine already fully built in `headline` (same degrade discipline the dispatcher applies to
    # synthesis / figures). On the happy path this is byte-identical (no _enrichment_errors key added), so
    # the EGFR/CEACAM5 replay fixtures are unaffected.
    try:
        headline["headline_block"] = _build_headline_block(headline)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        headline["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — a verdict-INERT projection over the
    # just-built claim_vector (NETWORK/PHOSPHO/PATHWAY/PERTURBATION/PREDICTABILITY), giving mechanism
    # component-parity with the other skills. Best-effort: a fault degrades to None + _enrichment_errors,
    # never aborts the mechanism spine.
    try:
        headline["question_table"] = mechanism_question_table(headline, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        headline["question_table"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, from the
    # verdict + claim_vector + headline_block + question_table just built. mechanism-and-pharmacology is a
    # GATING skill (∈ target-profile _SHORT_TO_GATE) with a clean 3-band polarity and no veto-killer
    # verdict, so the helper's negative→opposing floor is correct (no canonical_polarity_override).
    # Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        headline["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=headline.get("mechanism_verdict"),
            driving_rule_id=headline.get("driving_rule_id"),
            headline_block=headline.get("headline_block"),
            claim_vector=headline.get("claim_vector"),
            question_table=headline.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        headline["skill_report"] = None
    return headline


_SYNTHESIS_FACET_KEYS = (
    "mechanism_verdict",
    "driving_rule_id",
    "network_class",
    "has_actionable_moa",
    "phospho_activity_class",
    # detection-gap disambiguation for phospho_not_detected (issue #1564): the card caveats mandate
    # reading these before inferring biology off a not_detected class.
    "phosphoprotein_detected_in_other_cohorts",
    "phospho_axis_uninformative_reason",
    "pathway_activity_class",
    "tahoe_perturbation_class",
    "pred_predictability_class",
    # SIGNOR-partner-corroboration keys from _predictability_mechanism_facet (issue #1564): cross-
    # references the predictability feature attribution against the composed curated network partners —
    # emitted since the facet's introduction but never previously reached synthesis.
    "pred_dominant_feature_class",
    "pred_self_driven",
    "pred_mechanistic_partner_features",
    "pred_signor_corroborated_partners",
    "pred_n_signor_corroborated",
    "claim_vector",
    "key_signals",
    # verdict-INERT actionable-MoA INFLATION surfacing (2026-09-04): the has_actionable_moa context-free /
    # prediction-lane inflation caveats + the quorum/provenance summary (mirrors tractability
    # directness_caveat / surface surface_confirmation_caveat). None on the no-actionable-MoA path.
    "mechanism_confirmation_caveat",
    "prediction_lane_caveat",
    "curation_gap_note",
    # CASE-027-D1: the verdict-inert signaling-annotation-density CURRENCY disclaimer on mechanism_verdict.
    "mechanism_verdict_currency",
    "mechanism_provenance",
    "high_confidence_edges_count",
    "kinome_atlas_prediction_lane",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 skill_report
    # adoption (4th gating adopter after safety + dependency + tractability_sm)
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT mechanism facet for the composed target-profile synthesis. Reuses _headline
    (single source) + returns the mechanism claim_vector (NETWORK/PHOSPHO/PATHWAY/PERTURBATION/
    PREDICTABILITY) + its citable atoms. Never moves the verdict (owned by the mechanism resolver, which
    keys only on signaling-network-mechanism); safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    # pathway_activity_class is not lifted into _headline; surface it here from the card for the facet key
    h.setdefault("pathway_activity_class", get_card_field(cards, "pathway-activity-context", "pathway_activity_class"))
    return build_synthesis_facet(
        h,
        _SYNTHESIS_FACET_KEYS,
        (
            "Deterministic mechanism-and-pharmacology facet; claim_vector is MOSTLY "
            "DESCRIPTIVE (NETWORK = annotation density, capped moderate; PHOSPHO the real "
            "signal; PERTURBATION = engagement not dependency). Verdict owned by the resolver."
        ),
    )


if __name__ == "__main__":
    sys.exit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",
            question=QUESTION,
            verdict_fn=_verdict,
            headline_fn=_headline,
            # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
            synthesize_fn=make_synthesize_fn(_LENS),
            # Opt-in --literature: a VERDICT-INERT literature corroboration/contradiction lane (mirrors FR #987
            # / tumor-selectivity #964 / genomic #982 / on-target-safety #1000 / tractability-SM #1006 /
            # surface-modality-fit #1021). Attaches decision['literature_synthesis'] AFTER the deterministic
            # decision is composed + feeds the --synthesize narrator; the mechanism-and-pharmacology query terms
            # (signal transduction / pathway activation / PD biomarker / resistance / driver pathway / degrader)
            # live in literature_retrieval.py::_LENS_QUERY_TERMS. Two-slot / spine-untouched: structurally
            # impossible for the lane to alter mechanism_verdict. This is the lane that adjudicates per target
            # whether a curated actionable-MoA edge is indication-OPERATIVE vs a context-free/prediction aggregate
            # (the mechanism_confirmation_caveat / prediction_lane_caveat question) at read time.
            literature_fn=make_literature_fn(_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            isoform_check_target=True,  # warn on p95HER2 / AR-V7 / etc.
            # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
            skill_figures_fn=emit_headline_hero,
            # Signals-first: tuned sub-group reader for the mechanism vocabulary. Verdict-INERT.
            subgroup_classify=make_value_classifier(_MECHANISM_VALUE_TIERS),
        )
    )
