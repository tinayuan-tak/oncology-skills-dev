#!/usr/bin/env python3
"""hypothesis_core — the deterministic (LLM-free) spine of the cross-evidence hypothesis integrator.

This module holds every part of the integrator that MUST be reproducible and auditable: the
fail-closed gate-complete ceiling, the clamp, the citation-surface assembly, the retrieve-don't-recall
+ clause-traceability audit, the absence-discipline check, the subtype-resolved parse, the
evidence-substrate correlated-evidence discount, the modality-scope enum, and the weakest-link
certainty. The LLM two-call pipeline (edges → hypothesis) lives in run.py and calls into here.

Porting note: this evolves framework-runs/cross-dim-agent/hypothesis_agent.py
(CROSS_EVIDENCE_INTEGRATION_ROADMAP.md). The prototype's gate_ceiling modelled only 2 gates and
FAILED OPEN; here the ceiling consumes synthesis.recommendation_gate.hard_gates (the landed
complete fail-closed hard-gate set) and is fail-closed + gate-complete. Subtype
and evidence_substrate consumption are new.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# --- verdict permissiveness rank; the computed verdict is min(proposed, ceiling) by this order ------
VERDICT_RANK = {
    "declined": 0,
    "needs_data": 1,
    "advanceable_flagged": 2,
    "conditional_on_biomarker": 3,
    "advanceable_with_caveat": 4,
    "advanceable": 5,
}
RANK_VERDICT = {v: k for k, v in VERDICT_RANK.items()}

# Safety hold-grade sub-verdicts (a hold, not a kill) → ceiling caps at advanceable_flagged.
SAFETY_HOLD = {
    "human_genetics_safety_concern",
    "moderately_constrained_safety",
    "moderately_constrained_safety_concern",
}
# Safety hard-kill tokens (kept for the hard_gates-ABSENT fallback path only).
SAFETY_KILL = {"intolerant_lof_killer", "highly_constrained_safety_concern"}

# DIMENSION → member card_ids crosswalk (bridges a GRAIN MISMATCH in coherence detection).
# A `contradicts`/`tensions_with` edge names a sub-verdict DIMENSION (e.g. "safety"), but the LLM
# routinely surfaces that dimension's tension by citing the dimension's underlying CARDS
# (gnomad-lof-constraint, clingen-dosage, ...) rather than the bare dimension token. Without this map
# the surfacing check can't see that a card-grain tension surfaces a dimension-grain contradiction, so
# it FALSE-fires `edge_contradiction_unsurfaced` and blocks promotion (KRAS/ERBB2/BRAF
# demoted conditional_on_biomarker → advanceable_flagged despite surfacing the safety tension).
# Authoritative source = target-profile SUB_SKILL_CARDS ∘ SUB_SKILLS (skill_dir → short); mirrored here
# because importing tp_fanout pulls the whole spine runtime. A drift-guard test
# (test_dimension_cards_matches_spine) fails if this drifts from SUB_SKILL_CARDS. A card may belong to
# >1 dimension (multi-lens); that is fine — surfacing any member credits the dimension.
DIMENSION_CARDS: dict[str, frozenset[str]] = {
    # combinatorial_dependency / combination_opportunity / synthetic_lethal_partners RETIRED 2026-08-20:
    # the standalone relational shorts were consolidated into combination_vulnerability (the four relational
    # cards are all composed under combination-and-vulnerability now). Their cards live on under this one dim.
    "combination_vulnerability": frozenset(
        {  # mirrors SUB_SKILL_CARDS[combination-and-vulnerability]
            "synthetic-lethal-partners",
            "combinatorial-dependency",
            "cross-consortium-paralog-gi",  # T0-1: orthogonal Dede/in4mer corroboration of the CODEP call
            "combo-crispr-screen",
            "combo-chemical-synergy",
            "resistance-emergence-signature",
        }
    ),  # CONSOLIDATED relational annex (gateless)
    "cis_coherence": frozenset(
        {
            "cis-feature-expression-coherence",
            "cis-feature-protein-coherence",  # mRNA + PROTEIN GoF leg-1
            "cellline-methylation-expression-coherence",
            "expression-dependency-correlation",
            "abundance-dependency",  # mRNA + PROTEIN leg-2
            "amp-expr-stratified-dependency",
            "patient-cis-coherence",
            "cellline-isoform-expression",
        }
    ),  # +R10 molecular-form facet; mirrors SUB_SKILL_CARDS[cis-feature-coherence]
    "dependency": frozenset(
        {
            "abundance-dependency",
            "crispr-rnai-dependency-concordance",
            "cross-consortium-dependency",
            "dependency-lineage-selectivity",
            "expression-dependency-correlation",
            "pan-cancer-crispr-dependency-distribution",
            "pan-cancer-rnai-dependency-distribution",
            "paralog-buffering",
            "partner-conditional-dependency",
            "prism-crispr-concordance",
            "recommended-models",
            "organoid-crispr-dependency",
            "coessential-module",
            # 2026-08-20 facet-parity: mirror SUB_SKILL_CARDS[functional-requirement] which regained these
            # two (_headline reads them; see the fan-out fix). genomic-event-model-match is ALSO a
            # genomic_alteration card — a card may live in >1 dimension.
            "dependency-predictability",
            "genomic-event-model-match",
        }
    ),
    "differentiation": frozenset(
        {
            "co-mutation-and-mutual-exclusivity",
            "expression-clinical-association",
            "pathway-node-leverage",
            "precog-prognostic-association",
            "stemness-context",
            "alteration-clinical-association",
            "subtype-survival-association",
            "clinical-precedent",  # (2026-08-21) added to SUB_SKILL_CARDS[differentiation-landscape]
            "competitor-landscape",
        }
    ),  # (2026-08-24) Open Targets competitor field; added to SUB_SKILL_CARDS[differentiation-landscape]
    "expression": frozenset(
        {
            "cellline-protein-abundance",
            "cellline-protein-abundance-procan",
            "cellline-rna-distribution",
            "cellline-rna-protein-concordance",
            "expression-purity-confound",
            "tumor-elevation-breadth",
            "tumor-protein-abundance-cptac",
            "tumor-rna-distribution",
            "tumor-rna-distribution-by-subtype",
            "tumor-rna-vs-adjacent",
            "tumor-scrna-celltype-expression",
            # 2026-08-20 facet-parity: mirror SUB_SKILL_CARDS[tumor-presence] which regained these 4
            # (strictly read by presence _headline; see the fan-out composer fix).
            "cellline-rna-distribution-by-subtype",
            "normal-tissue-liability",
            "rna-protein-concordance-tumor",
            "sc-normal-celltype-expression",
            # 2026-08-26: CPTAC-protein subtype panorama added to SUB_SKILL_CARDS[tumor-presence] (#676).
            "tumor-protein-distribution-by-subtype",
            # 2026-08-28: HPA antibody IHC protein-in-tumor (protein_ihc/tumor bucket) added to
            # SUB_SKILL_CARDS[tumor-presence]; mirror here (DIMENSION_CARDS drift guard).
            "hpa-pathology-cancer-ihc",
        }
    ),
    "genomic_alteration": frozenset(
        {
            "alteration-role",
            "amp-expr-stratified-dependency",
            "copy-number-distribution",
            "copy-number-stratified-dependency",
            "ddr-deficiency-context",
            "functional-gene-state",
            "fusion-rearrangement-landscape",
            "fusion-stratified-dependency",
            "genomic-event-model-match",
            "splice-exon-skip-landscape",  # CASE-002 verdict-driving splice axis; mirrors SUB_SKILL_CARDS[genomic-alteration-profile]
            "genomic-instability-state",
            "mutation-drug-response",
            "mutation-hotspot-frequency",
            "mutation-stratified-dependency",
            "mutation-type-counts",
            "mutational-signature-context",
            "oncogenic-pathway-alteration",
            "target-clonality",
            "variant-level-interpretation",
            "variant-effect-mave-mavedb",  # MAVEdb MEASURED variant-effect facet; mirrors SUB_SKILL_CARDS[genomic-alteration-profile] (verdict-inert)
            # 2026-08-20 facet-parity: mirror SUB_SKILL_CARDS[genomic-alteration-profile] which regained
            # these two dependency-confidence cards (lifted by genomic _HEADLINE_FIELDS/_lift_field).
            "cross-consortium-dependency",
            "dependency-predictability",
            "tumor-splice-dysregulation",
        }
    ),  # +R10 splice-form facet; mirrors SUB_SKILL_CARDS[genomic-alteration-profile] (tumor-splice-expression dedup'd 2026-09-06)
    "mechanism": frozenset(
        {
            "pathway-activity-context",
            "phospho-pathway-activity",
            "signaling-network-mechanism",
            "tahoe-drug-perturbation",
            # dependency-predictability added to SUB_SKILL_CARDS[mechanism-and-pharmacology] (facet-parity,
            # claim-vector rollout 2026-08-20), so this mirror must carry it (test_dimension_cards_matches_spine).
            "dependency-predictability",
        }
    ),
    "safety": frozenset(
        {
            "alteration-role",
            "clingen-dosage",
            "clinvar-pathogenicity-safety",
            "copy-number-distribution",
            "gene-burden-safety",
            "gnomad-lof-constraint",
            "shet-lof-intolerance",
            "mouse-ko-phenotype",
            "normal-tissue-liability-gtex",
            "target-safety-prioritisation",
            "drug-warning-safety",
            # data-util expansion 2026-08-21 — added to SUB_SKILL_CARDS[on-target-safety-liability]
            # (pan-essential broad-tox + HPA-IHC essential-tissue protein HOLD legs); mirror must carry them.
            "pan-cancer-crispr-dependency-distribution",
            "normal-tissue-liability",
            # PR-4c 2026-08-24 — rarely-altered guard (GROUP-0b); mirror must carry it.
            "functional-gene-state",
            # 2026-08-25 — OnSIDES drug-label ADE CONTEXT (verdict-inert display); added to
            # SUB_SKILL_CARDS[on-target-safety-liability], mirror must carry it.
            "onsides-adverse-event-safety",
            # T0-3 2026-09-10 — TPHP DIA-MS quantitative vital-organ protein (verdict-inert safety
            # context); added to SUB_SKILL_CARDS[on-target-safety-liability], mirror must carry it.
            "normal-tissue-protein-abundance-tphp",
        }
    ),
    "selectivity": frozenset(
        {
            "expression-purity-confound",
            "modality-therapeutic-window",
            "sc-normal-celltype-expression",
            "surface-abundance-density",
            "tumor-vs-normal-percentile-crossing",
            "tumor-vs-normal-selectivity",
            # 2026-08-25 — the QUANTITATIVE normal-tissue PROTEIN comparator (TPHP DIA-MS) added to
            # SUB_SKILL_CARDS[tumor-selectivity] (tp_fanout), so this mirror must carry it too
            # (test_dimension_cards_matches_spine). Verdict-inert in tumor-selectivity.
            "normal-tissue-protein-abundance-tphp",
            # 2026-08-25 — the TPHP DIA-MS RNA→PROTEIN tumor-vs-normal corroboration facet (parallel to
            # tumor-protein-abundance-cptac), added to SUB_SKILL_CARDS[tumor-selectivity] (tp_fanout), so
            # this mirror must carry it too (test_dimension_cards_matches_spine). Verdict-inert.
            "tumor-vs-normal-protein-abundance-tphp",
            # v1.9.0 tumor-side single-cell + spatial facets — added to SUB_SKILL_CARDS[tumor-selectivity]
            # (tp_fanout) so this mirror must carry them too (test_dimension_cards_matches_spine). Verdict-
            # inert in tumor-selectivity; here they let the integrator credit a sc/spatial-surfaced tension.
            "tumor-scrna-celltype-expression",
            "spatial-region-rna-expression",
            "spatial-tumor-normal-colocalization",
            "spatial-surface-protein-abundance",
        }
    ),
    "surface_modality": frozenset(
        {
            "adc-tce-modality-fit",
            "cd-antigen-backbone",
            "copy-number-distribution",
            "modality-exon-window",
            "modality-therapeutic-window",
            "mutation-stratified-surface",
            "normal-tissue-liability",
            "pathway-stratified-surface",
            "pmhc-presentation",
            "protein-surface-evidence",
            "rna-protein-concordance-tumor",
            "sc-normal-celltype-expression",
            # revived single-cell surface facets (dead-card resolution 2026-08-19) — added to
            # SUB_SKILL_CARDS[surface-modality-fit], so this mirror must carry them (test_dimension_cards_matches_spine).
            "sc-surface-normal-safety",
            "sc-surface-rna-protein-concordance",
            # tumor-scrna-celltype-expression added to SUB_SKILL_CARDS[surface-modality-fit] (claim-vector
            # rollout 2026-08-20 — facet-parity), so this mirror must carry it too (test_dimension_cards_matches_spine).
            "tumor-scrna-celltype-expression",
            # surface-colocalization-avidity added to SUB_SKILL_CARDS[surface-modality-fit] (wired live
            # 2026-08-20 — same-cell avidity + tumor-vs-normal selectivity window), so this mirror must
            # carry it too (test_dimension_cards_matches_spine).
            "surface-colocalization-avidity",
            "shed-ectodomain-liability",
            "structure-features-static",
            "surface-abundance-density",
            "surface-topology-and-ptm",
            "surfaceome-family-classification",
            "surfaceome-cohort-ranking",  # REVIVE role-2 (mirrors SUB_SKILL_CARDS[surface-modality-fit])
            "surface-bulk-pair-selectivity",  # bulk pair-selectivity facet (mirrors SUB_SKILL_CARDS)
            "pmhc-epitope-evidence-iedb",
        }
    ),  # 2026-08-25 IEDB pMHC epitope ground truth (mirrors SUB_SKILL_CARDS[surface-modality-fit]; verdict-inert display)
    "immune_context": frozenset(
        {
            "immune-context",
            # mirrors SUB_SKILL_CARDS[immune-context] incl. the 3 VERDICT-INERT
            # TME/immune display cards wired 2026-08-25 (spine-parity guard).
            "myeloid-compartment-expression-cheng",
            "caf-compartment-expression-luo",
            "ici-response-association",
            "tcga-til-fraction-saltz",
            "ici-response-imvigor210",
            "spatial-tumor-normal-colocalization",  # T0-4: spatial inflamed/excluded phenotype; verdict-inert
        }
    ),
    "target_intrinsic": frozenset(
        {
            "domain-modality-relevance",
            "gene-ontology-annotation",
            "ppi-interactome",
            "protein-domains-class",
            "reactome-pathway-membership",
            "target-development-level",
            "measured-potency-tractability",
            "target-identity-summary",
        }
    ),
    "tractability_sm": frozenset(
        {
            "degradation-feasibility",
            "dependency-predictability",
            "gdsc-drug-activity",
            "known-drug-tractability",
            "measured-potency-tractability",
            "prism-compound-activity",
            "prism-crispr-concordance",
            "structure-features-static",
            # #993 pt1: mutant-allele spectrum context for the minority_allele_coverage_caveat
            # (verdict-inert). Mirrors SUB_SKILL_CARDS[tractability-small-molecule] (drift guard).
            "mutation-hotspot-frequency",
        }
    ),
    # 2026-08-31 — translational-readiness wired into the fan-out as a GATELESS DESCRIPTIVE peer
    # (verdict=None, absent from _SHORT_TO_GATE), so this mirror must carry its 3 EXCLUSIVE cards
    # (organoid-crispr-dependency is NOT re-listed — it already reaches tp via the dependency dim).
    # Keeps DIMENSION_CARDS == SUB_SKILL_CARDS ∘ SUB_SKILLS (test_dimension_cards_matches_spine).
    "translational_readiness": frozenset(
        {"target-model-availability", "target-genotype-matched-model", "target-pdx-drug-response"}
    ),
    # 2026-09-02 — literature-context wired into the fan-out as a GATELESS DESCRIPTIVE peer
    # (verdict=None, absent from _SHORT_TO_GATE), so this mirror must carry its single card
    # (test_dimension_cards_matches_spine). Promotes the former cited_literature_evidence.json side-channel.
    "literature_context": frozenset({"cited-literature-evidence"}),
}
# normalized: dim_norm -> {card_norm}. Used to expand a dimension token to its member cards when
# deciding whether a contradiction was surfaced (dimension-grain OR card-grain both count).
_DIM_CARD_NORMS: dict[str, frozenset[str]] = {
    _n: frozenset(c.replace("-", "_").lower() for c in cards)
    for dim, cards in DIMENSION_CARDS.items()
    for _n in (dim.replace("-", "_").lower(),)
}
# REVERSE index card_norm -> {dim_norm}. A card frequently belongs to MORE THAN ONE sub-verdict
# dimension (multi-lens: `modality-therapeutic-window` is both a surface_modality and a tumor-SELECTIVITY
# card; `structure-features-static` is both tractability_sm and surface_modality). The modality-scope
# exclusion must therefore ask whether EVERY dimension owning the card is out of scope — see
# token_out_of_scope. Built off the same DIMENSION_CARDS the drift guard pins.
_CARD_DIM_NORMS: dict[str, frozenset[str]] = {}
for _dim, _cards in DIMENSION_CARDS.items():
    for _c in _cards:
        _cn = _c.replace("-", "_").lower()
        _CARD_DIM_NORMS[_cn] = _CARD_DIM_NORMS.get(_cn, frozenset()) | {_dim.replace("-", "_").lower()}

# coverage-gap verdicts: a line in one of these states carries NO evidentiary weight (absence-discipline)
GAP_VERDICTS = {
    None,
    "insufficient",
    "data_unavailable",
    "not_assessed",
    "not_informative",
    "no_data",
    "not_evaluated",
    "insufficient_data",
    "insufficient_evidence",
}

# MEASURED-NEGATIVE sub-verdicts (distinct from GAP_VERDICTS, which are absence): a line that was
# evaluated and returned a NEGATIVE call. A positive-thesis clause may not cite one of these as
# SUPPORT without surfacing the tension (intra-package coherence, adversarial-survival —
# the SL-vs-non_dependent class of internal contradiction). Curated conservative set + a few stems so
# suffix variants (e.g. non_dependent_paralog_buffered) are covered; positive tokens
# (strongly_selective_dependency, strong_tumor_selective, lineage_selective, discordant_*) do NOT match.
NEGATIVE_SIGNAL_VERDICTS = {
    # dependency / functional-requirement
    "non_dependent",
    "non_dependent_paralog_buffered",
    "not_a_dependency",
    "non_essential",
    # selectivity / tumor-vs-normal
    "not_selective",
    "selective_but_broadly_normal",
    "not_tumor_selective",
    # surface / modality fit
    "neither_viable",
    # synthetic-lethal / combinatorial / partner-conditional
    "no_partner_mapped",
    "no_experimental_sl_partner",
    "no_sl_partner",
    "no_combinatorial_dependency",
    # genomic-alteration
    "passenger_pattern",
    "not_altered",
    "no_recurrent_alteration",
}
_NEGATIVE_STEMS = (
    "non_dependent",
    "no_partner",
    "no_experimental_sl",
    "no_sl_partner",
    "not_selective",
    "neither_viable",
    "no_combinatorial",
    "passenger",
)
CERTAINTY_RANK = {"low": 0, "moderate": 1, "high": 2}
RANK_CERTAINTY = {v: k for k, v in CERTAINTY_RANK.items()}

# --- modality scope as a CONTROLLED ENUM (replaces the prototype's objective.startswith) ------------
# For each modality: the sub-verdict dimensions that are OUT OF SCOPE for the hypothesis (a
# small-molecule program does not turn on surface-modality fit; a surface-directed biologic does not
# turn on small-molecule tractability). Out-of-scope dims are excluded from data-gaps + certainty +
# the in-scope decision set, so an irrelevant axis never degrades a hypothesis for the wrong modality.
MODALITY_SCOPE: dict[str, set] = {
    "small_molecule": {"surface_modality", "immune_context"},
    "degrader": {"surface_modality", "immune_context"},
    "molecular_glue": {"surface_modality", "immune_context"},
    "rna_therapeutic": {"surface_modality", "tractability_sm", "immune_context"},
    # SURFACE / LIGAND biologics: the therapeutic basis is surface presentation / ligand neutralization,
    # NOT a cell-intrinsic genetic dependency. So the dependency-FAMILY axes are out-of-scope — a
    # `dependency:non_dependent` (or SL/combinatorial) reading must NOT veto a surface target (e.g. an
    # approved ADC/TCE antigen like DLL3/NECTIN4 that is not itself a fitness dependency). tractability_sm
    # (small-molecule chemistry) is likewise out-of-scope.
    # IMMUNE CONTEXT is IN SCOPE for all three antibody-derived channels, not just bite_tce: an
    # unconjugated antibody's efficacy mechanism is frequently ADCC / CDC / immune-effector recruitment,
    # and an ADC payload induces immunogenic cell death — so the TME's immune phenotype (the
    # inflamed/excluded/desert read + the ICI-response cards) speaks to whether the channel can work.
    # It stays OUT of scope for the cell-intrinsic small-molecule family (small_molecule / degrader /
    # molecular_glue / rna_therapeutic), whose mechanism does not route through an immune effector.
    "adc": {"tractability_sm", "dependency", "combination_vulnerability"},
    "bite_tce": {"tractability_sm", "dependency", "combination_vulnerability"},
    "antibody": {"tractability_sm", "dependency", "combination_vulnerability"},
    "modality_agnostic": set(),
}

# GATE-AXIS ROLES (mirror the spine's nomination-gate policy tp_gates._GATING_AXIS_FAILCLOSED_ACTION:
# dependency→veto, safety→hold, subtype_fit→hold). ONLY dependency carries a veto disposition
# (non_dependent / pan_essential_killer). safety + subtype_fit are HOLD-grade: a fired/blind safety or
# subtype gate is a HOLD (cap at advanceable_flagged), NEVER a decline — because safety is
# mechanism-conditionable (a window may exist) and the spine itself forces `hold`, not veto.
# (the ceiling was declining on hold-grade safety, wrongly killing approved ADCs etc.).
_VETO_GATE_AXES = frozenset({"dependency"})
_HOLD_GRADE_GATE_AXES = frozenset({"safety", "subtype_fit"})
# Free-text objective → controlled modality (strict keyword map; unknown → modality_agnostic + flag).
_OBJECTIVE_KEYWORDS = [
    ("small_molecule", ("small-molecule", "small molecule", "inhibitor", "sm ")),
    ("degrader", ("degrader", "protac", "glue-degrader")),
    ("molecular_glue", ("molecular glue", "molecular-glue")),
    ("rna_therapeutic", ("rna therapeutic", "sirna", "aso", "antisense", "rna-therapeutic")),
    ("adc", ("adc", "antibody-drug", "antibody drug")),
    ("bite_tce", ("tce", "t-cell engager", "bite", "bispecific")),
    ("antibody", ("antibody", "mab", "biologic")),
]


def resolve_modality(modality: Optional[str], objective: Optional[str]) -> tuple[str, bool]:
    """Resolve the controlled modality enum. Returns (modality, inferred).
    An explicit --modality wins (validated against the enum). Otherwise infer from the free-text
    objective via a strict keyword map; unknown/absent → modality_agnostic (all dims in scope) +
    inferred=True so the caller can flag the fallback."""
    if modality:
        m = str(modality).strip().lower().replace("-", "_")
        if m in MODALITY_SCOPE:
            return m, False
        raise ValueError(f"unknown --modality {modality!r}; valid: {sorted(MODALITY_SCOPE)}")
    obj = (objective or "").strip().lower()
    for m, kws in _OBJECTIVE_KEYWORDS:
        if any(k in obj for k in kws):
            return m, True
    return "modality_agnostic", True


def out_of_scope_dims(modality: str) -> set:
    return set(MODALITY_SCOPE.get(modality, set()))


# The CARDS that belong to each modality-scoped sub-verdict DIMENSION. `out_of_scope_dims` returns
# sub-verdict dimension names (surface_modality / tractability_sm), but a clause often cites the
# underlying CARD (e.g. `adc-tce-modality-fit`, `modality-therapeutic-window`) rather than the
# dimension name — and those cards are just as out-of-scope for the objective's modality. This maps
# each modality dimension to normalized-substring tokens matched against a card_id, so the
# modality-scope exclusion reaches CARD-grain violations too (matched substrings are deliberately
# specific to biologics-surface / small-molecule-chemistry cards; dependency / SL / genomic / mechanism
# cards never match, so an in-scope primary-thesis violation — e.g. MARK2's SL-vs-no_partner — is
# NEVER excluded).
_MODALITY_DIMENSION_CARD_TOKENS: dict[str, tuple] = {
    "surface_modality": (
        "surface",
        "surfaceome",
        "adc",
        "tce",
        "bite",
        "topology",
        "cd_antigen",
        "shed_ectodomain",
        "pmhc",
        "cspa",
        "internalizing",
        "modality_fit",
        "modality_therapeutic_window",
        "modality_exon_window",
        "biologic",
    ),
    "tractability_sm": (
        "tractability",
        "known_drug",
        "measured_potency",
        "structure_features",
        "ligandability",
        "dgidb",
        "pocket",
        "kinome",
        "prism",
    ),
}


def token_out_of_scope(norm_token: str, oos_dims: set) -> bool:
    """A normalized card/dimension token is OUT OF SCOPE for the modality if it IS an out-of-scope
    sub-verdict dimension, or it is a CARD every one of whose owning dimensions is out of scope.

    MULTI-LENS CORRECTNESS: a card can be owned by several dimensions, so the OWNERSHIP index
    (`_CARD_DIM_NORMS`, derived from the drift-pinned DIMENSION_CARDS) is consulted FIRST and is
    AUTHORITATIVE — a card with at least one IN-SCOPE owner is in scope. Blind substring matching used to
    exclude `modality-therapeutic-window` / `surface-abundance-density` / `spatial-surface-protein-abundance`
    for a small_molecule objective (all three are tumor-SELECTIVITY cards, an in-scope dimension — so a
    coherence violation resting on the therapeutic-WINDOW card was silently exempted for the framework's
    most common modality), and `structure-features-static` / `measured-potency-tractability` for adc /
    antibody (surface_modality + target_intrinsic cards).

    `_MODALITY_DIMENSION_CARD_TOKENS` remains the FALLBACK for a token absent from DIMENSION_CARDS (a
    card the mirror has not caught up with, or a free-text token the LLM coined), where a name-shape match
    is the only signal available. `oos_dims` is the out-of-scope dimension set (normalized here, so a raw
    or pre-normalized set both work)."""
    oos_norm = {_norm(d) for d in oos_dims}
    if norm_token in oos_norm:
        return True
    owners = _CARD_DIM_NORMS.get(norm_token)
    if owners:  # KNOWN card — ownership decides; out of scope only when NO owner is in scope
        return owners <= oos_norm
    for dim in oos_norm:  # UNKNOWN token — fall back to the name-shape map
        if any(tok in norm_token for tok in _MODALITY_DIMENSION_CARD_TOKENS.get(dim, ())):
            return True
    return False


# --- small structured-output unwrap helpers (mirror the prototype) ----------------------------------
def _uv(x):
    if isinstance(x, dict) and "value" in x and len(x) == 1:
        return x["value"]
    return x


def _scalar(x):
    for _ in range(3):
        if isinstance(x, dict) and "value" in x:
            x = x["value"]
        else:
            break
    return x if not isinstance(x, (dict, list)) else None


def _sv_verdict(sv, key):
    v = sv.get(key)
    return (v.get("verdict") if isinstance(v, dict) else v) if v is not None else None


# --- MODALITY×SAFETY seam (consumes sub_verdicts.safety.safety_verdict_by_modality, stamped by the
# spine's tp_evidence_package). The per-modality safety verdict {channel: {action, wt_engagement,
# driving_rules}} lets the integrator refine its hold-grade safety cap PER ITS OWN --modality instead of
# imposing one blanket cap off the scalar `safety` verdict. `conditional` is the ONLY action that clears a
# fired WT-loss concern for a channel — an EXACT MIRROR of the spine's tp_gates._SAFETY_SAFE_ACTIONS
# (only an allele-selective escape clears; supportive/no_concern/not_applicable never legitimately
# co-occur with a fired concern, so excluding them is fail-closed). Kept in lock-step so the integrator is
# NEVER more permissive than the spine's own exists_safe_modality suppression.
_SAFETY_MODALITY_SAFE_ACTIONS = frozenset({"conditional"})


def safety_verdict_by_modality(sv: dict) -> Optional[dict]:
    """The per-modality safety verdict block stamped on the safety sub_verdict entry, or None (older
    package / no safety axis). `sv` is synthesis.sub_verdicts."""
    entry = sv.get("safety")
    if isinstance(entry, dict):
        block = entry.get("safety_verdict_by_modality")
        return block if isinstance(block, dict) and block else None
    return None


def safety_action_for_modality(sv: dict, modality: Optional[str]) -> Optional[str]:
    """The per-modality safety `action` for this modality channel, or None when unavailable (no block,
    no modality, or the channel is absent from the block)."""
    if not modality:
        return None
    block = safety_verdict_by_modality(sv)
    if not block:
        return None
    rec = block.get(modality)
    return rec.get("action") if isinstance(rec, dict) else None


# Mechanism-conditioning of the dependency veto. Removed the dependency veto
# for SURFACE biologics (modality-scoped). This handles the ORTHOGONAL mutant-selective case, at ANY
# modality: a `dependency:non_dependent` reading does NOT disqualify a MUTANT-SELECTIVE / GoF driver —
# an allele-selective agent (e.g. IDH1-R132 ivosidenib) need not make the WT gene a cell-intrinsic
# fitness dependency, so monotherapy CRISPR non-dependence of WT is EXPECTED, not a veto. The safety
# skill's `wt_*_mechanism_mismatch` verdict is the explicit, package-carried signal that the WT-LoF
# constraint does NOT align with the oncogenic (activating) mechanism — i.e. the driver is mutant-
# selective. It is the SAME signal that makes safety hold-grade, applied to the dependency axis. It is
# absent on TSG/loss-of-function drivers and on the highly_constrained dangerous-FPs (MYC, STAG1), so it
# does not re-admit them. NARROW by design: only `non_dependent`-family verdicts are conditioned;
# `pan_essential_killer` (no selectivity window) stays a genuine veto.
_MUTANT_SELECTIVE_SAFETY = frozenset({"wt_human_genetics_mechanism_mismatch", "wt_constraint_mechanism_mismatch"})
_NON_DEPENDENT_TOKENS = frozenset(
    {"non_dependent", "non_dependent_paralog_buffered", "not_a_dependency", "non_essential"}
)


# --- FAIL-CLOSED, GATE-COMPLETE ceiling — consumes recommendation_gate.hard_gates ------------
def gate_ceiling(pkg: dict, modality: Optional[str] = None) -> dict:
    """The most permissive verdict the deterministic spine permits; the hypothesis is clamped to it.

    KEY UPGRADE over the prototype (which modelled only rec-gate.fired + safety, and FAILED OPEN):
    this iterates the COMPLETE hard-gate set the spine emits at
    `synthesis.recommendation_gate.hard_gates` (every kill-capable (short, verdict) with a
    per-run status ∈ {fired, suppressed, excluded, opposing, blind, latent}). The ceiling is the
    LEAST-permissive value implied by that set:
      - dependency gate `fired`         → declined (the sole veto axis), UNLESS mechanism-conditioned
                                          — `non_dependent` on a mutant-selective driver
                                          (safety=wt_*_mechanism_mismatch) is mechanism-excluded.
                                          pan_essential_killer (no selectivity window) stays a veto.
      - dependency gate `blind`         → declined, FAIL-CLOSED (veto cannot be ruled out), unless the
                                          driver is mutant-selective → mechanism-excluded.
      - hold-grade gate (safety/subtype)→ cap at advanceable_flagged (never a veto).
      - any contradiction `opposing`    → cap at advanceable_with_caveat (opposing measured
                                          evidence blocks `strong`, not a veto).
      - excluded (modality-scoped)      → surfaced, does NOT blanket-veto the ceiling.
    If the package cannot be parsed / has no synthesis, the ceiling is `declined` (fail-closed).
    If `hard_gates` is ABSENT (older package), fall back to a fail-closed rec-gate + sub-verdict
    scan (never the prototype's fail-open behaviour)."""
    syn = pkg.get("synthesis")
    if not isinstance(syn, dict) or not isinstance(syn.get("sub_verdicts"), dict):
        return {
            "ceiling": "declined",
            "reason": "package has no parseable synthesis.sub_verdicts (schema-invalid) — fail-closed",
            "fail_closed": True,
            "hard_gates_present": False,
            "active_vetoes": [],
            "blind_gates": [],
            "opposing": [],
            "excluded": [],
            "safety_verdict": None,
            "safety_modality_action": None,
            "safety_modality_cleared": False,
            "safety_gate_status": None,
            "safety_gate_disposed_by_spine": False,
        }
    sv = syn["sub_verdicts"]
    safety = _sv_verdict(sv, "safety")
    rg = syn.get("recommendation_gate") or {}
    hard_gates = rg.get("hard_gates")
    oos = out_of_scope_dims(modality) if modality else set()  # dims out-of-scope for this modality
    mutant_selective = safety in _MUTANT_SELECTIVE_SAFETY  # mechanism-conditions the dependency veto
    # MODALITY×SAFETY: the per-modality safety action for THIS channel. When it clears (== conditional,
    # the spine's sole safe action), the blanket hold-grade safety cap below is modality-cleared — a
    # scalar `safety` hold no longer caps a channel the spine's own exists_safe_modality would suppress.
    safety_action = safety_action_for_modality(sv, modality)
    safety_modality_cleared = safety_action in _SAFETY_MODALITY_SAFE_ACTIONS

    signals: list[tuple[int, str]] = []  # (ceiling_rank, reason)
    active_vetoes, blind_gates, opposing, excluded = [], [], [], []
    # statuses the spine assigned to the SAFETY rows of its own hard-gate set, keyed by the gate verdict.
    # Consumed by the scalar safety cap below so the integrator cannot re-impose a hold the spine DISPOSED.
    safety_gate_status: dict = {}

    if isinstance(hard_gates, list) and hard_gates:
        for row in hard_gates:
            if not isinstance(row, dict):
                continue
            short = row.get("short")
            verdict = row.get("verdict")
            disp = row.get("disposition")
            status = row.get("status")
            tag = f"{short}:{verdict}"
            if short == "safety":
                safety_gate_status[str(verdict)] = str(status)
            axis_oos = short in oos  # e.g. dependency is out-of-scope for a surface/ligand biologic
            if status == "fired":
                if axis_oos:
                    # the axis does not decide this modality — surfaced, does NOT veto the ceiling
                    excluded.append(tag)
                elif short in _VETO_GATE_AXES:
                    # mechanism-condition the dependency veto. A `non_dependent` reading on a
                    # mutant-selective/GoF driver is EXPECTED (WT need not be a fitness dependency) →
                    # mechanism-excluded, not a veto. pan_essential_killer (no selectivity window) stays
                    # a genuine veto.
                    if verdict in _NON_DEPENDENT_TOKENS and mutant_selective:
                        excluded.append(tag)
                    else:
                        active_vetoes.append(tag)
                        signals.append((VERDICT_RANK["declined"], f"hard-gate fired ({tag})"))
                else:
                    # HOLD-grade axis (safety / subtype_fit) fired → a HOLD, not a kill
                    signals.append((VERDICT_RANK["advanceable_flagged"], f"hold-grade gate fired ({tag})"))
            elif status == "blind" and disp == "gated":
                if axis_oos:
                    excluded.append(tag)  # not in scope this run → not a coverage gap
                elif short in _VETO_GATE_AXES and mutant_selective:
                    # dependency axis does not decide a mutant-selective driver → mechanism-excluded
                    excluded.append(tag)
                elif short in _VETO_GATE_AXES:
                    # a VETO-capable axis produced no verdict → cannot rule the veto out → fail closed
                    blind_gates.append(tag)
                    signals.append((VERDICT_RANK["declined"], f"fail-closed: veto-capable axis blind ({short})"))
                else:
                    # a HOLD-grade axis blind → fail-closed to a HOLD, not a decline
                    signals.append(
                        (VERDICT_RANK["advanceable_flagged"], f"fail-closed hold-grade axis blind ({short})")
                    )
            elif status == "opposing":
                opposing.append(tag)
                signals.append((VERDICT_RANK["advanceable_with_caveat"], f"opposing measured evidence ({tag})"))
            elif status == "excluded":
                excluded.append(tag)  # modality-scoped foreclosure — surfaced, no blanket veto
        hard_gates_present = True
    else:
        # ---- FALLBACK: no hard_gates block (older package). Fail-closed, not fail-open. ----
        hard_gates_present = False
        if bool(rg.get("fired")) and not (rg.get("suppressed_vetoes")):
            active_vetoes.append("recommendation_gate")
            signals.append((VERDICT_RANK["declined"], f"recommendation_gate fired ({rg.get('verdict') or 'veto'})"))
        # scan the veto-capable sub-verdicts for kill tokens the prototype ignored — DEPENDENCY only
        # (the sole veto axis), and only when dependency is in scope for the modality.
        dep = _sv_verdict(sv, "dependency")
        if dep in {"pan_essential_killer", "non_dependent"} and "dependency" not in oos:
            if dep in _NON_DEPENDENT_TOKENS and mutant_selective:
                pass  # mutant-selective driver — WT non-dependence is expected, not a veto
            else:
                active_vetoes.append(f"dependency:{dep}")
                signals.append((VERDICT_RANK["declined"], f"dependency kill token ({dep})"))
        # NOTE: safety is HOLD-grade, never a fallback kill — handled by the hold-grade line below.

    # safety hold-grade (both paths) — a hold, not a kill. SAFETY IS NEVER A VETO (mirrors the spine's
    # safety→hold policy): both SAFETY_HOLD and the former SAFETY_KILL tokens cap at advanceable_flagged.
    # MODALITY-CLEARED: if the per-modality safety action for this channel clears the WT-loss concern
    # (== conditional / allele-selective escape, the spine's exists_safe_modality logic), the blanket
    # scalar cap does NOT apply — the integrator would otherwise re-impose a hold the spine suppressed for
    # this exact channel. Fail-closed: no block / a non-clearing action keeps the cap.
    #
    # SPINE-DISPOSED: when the spine's OWN hard-gate row for this exact safety verdict carries a
    # disposition status of `suppressed` or `excluded`, the spine has already ADJUDICATED that gate for
    # this run — suppressed means it evaluated the gate and released it (observed on KRAS/COADREAD, where
    # the run was rescued only incidentally by safety_action == conditional). Re-deriving the hold from
    # the SCALAR sub-verdict token then OVERRIDES the spine's per-run adjudication with a coarser read,
    # which is the one thing this integrator must never do ("it ENRICHES; it never OVERRIDES"). A row
    # that FIRED or went BLIND already contributed its own signal in the loop above, so skipping the
    # scalar cap for a disposed row cannot lose a real hold. Fail-closed: an ABSENT hard-gates block, or
    # a safety verdict with no matching row, keeps the scalar cap.
    safety_gate_disposed = safety_gate_status.get(str(safety)) in {"suppressed", "excluded"}
    if (safety in SAFETY_HOLD or safety in SAFETY_KILL) and not safety_modality_cleared and not safety_gate_disposed:
        signals.append((VERDICT_RANK["advanceable_flagged"], f"safety hold-grade ({safety})"))

    if not signals:
        ceiling_rank, reason = VERDICT_RANK["advanceable"], ("no fired/blind hard gate on the deterministic spine")
    else:
        ceiling_rank, reason = min(signals, key=lambda s: s[0])
    return {
        "ceiling": RANK_VERDICT[ceiling_rank],
        "reason": reason,
        "fail_closed": bool(blind_gates) or ceiling_rank == VERDICT_RANK["declined"] and not active_vetoes,
        "hard_gates_present": hard_gates_present,
        "active_vetoes": active_vetoes,
        "blind_gates": blind_gates,
        "opposing": opposing,
        "excluded": excluded,
        "safety_verdict": safety,
        "safety_modality_action": safety_action,
        "safety_modality_cleared": safety_modality_cleared,
        "safety_gate_status": safety_gate_status or None,
        "safety_gate_disposed_by_spine": safety_gate_disposed,
    }


def clamp(proposed: Optional[str], ceiling: str) -> tuple:
    """Clamp the proposed (LLM) verdict to the deterministic ceiling. Returns (computed, was_clamped).
    An unrecognized proposed verdict is treated as `needs_data` (never assumed permissive)."""
    p = proposed if isinstance(proposed, str) and proposed in VERDICT_RANK else "needs_data"
    if VERDICT_RANK[p] > VERDICT_RANK[ceiling]:
        return ceiling, True
    return p, False


# --- the UNIFIED skill_report SPINE (synthesis.skill_reports) ---------------------------------
# The framework's ONE per-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md,
# _skills_common/skill_report.build_skill_report). The spine carries it into the evidence_package
# specifically so THIS integrator can read it, and it is the ONLY place the package states each axis's
# ROLE. Without it the integrator reads a bare `sub_verdicts` map in which a GATELESS-BY-DESIGN lens is
# indistinguishable from a BLIND gate: both present as `verdict: None`.
#
# That conflation was live and load-bearing. On all five 2026-09-10 finalized packages, `data_gaps`
# listed `target_intrinsic`, `combination_vulnerability`, `translational_readiness` and
# `literature_context` — the four verdict_fn=None DESCRIPTIVE lenses — as coverage gaps, and on
# EGFR/NSCLC `limiting_dimension` came back as `target_intrinsic`, which the dashboard's
# `_cross_evidence_summary` renders verbatim. The integrator was telling a reviewer that the limiting
# evidence line was a lens that has no verdict by design, and `go_forth` was being pointed at four
# non-gaps.
#
# ROLE taxonomy (skill_report.ROLES): `gating` = the verdict can move the nomination; `descriptive` = a
# real read with no gate; `inert` = verdict-SHAPED but explicitly not a call (cis_coherence). Only a
# GATING axis is a decision line for certainty purposes; a descriptive/inert axis with no call is
# NOT_SCORED, which is a different thing from a gap.
_NOT_SCORED_ROLES = frozenset({"descriptive", "inert"})
ROLE_GATING = "gating"


def parse_skill_reports(pkg: dict) -> dict:
    """Project `synthesis.skill_reports` into the integrator's axis-ROLE view.

    Returns {present, by_short, roles, gating_axes, not_scored_axes, polarity, rollup}:
      - `roles`           {short: role} for every axis carrying a report;
      - `gating_axes`     the shorts whose verdict can move the nomination (role == gating);
      - `not_scored_axes` the shorts that are GATELESS BY DESIGN — role ∈ {descriptive, inert} AND no
                          `call`. These must NOT be counted as coverage gaps and must NOT limit
                          certainty; `polarity == not_scored` is the spine's own word for them.
      - `rollup`          `synthesis.skill_report_rollup` verbatim (role grouping + the INV-6
                          recommendation-vs-signals coherence flag), surfaced for the panel.

    `present=False` for a package that predates the spine carry — every downstream consumer then falls
    back to its previous behaviour, so an older package stays byte-stable."""
    syn = pkg.get("synthesis") or {}
    reports = syn.get("skill_reports")
    if not isinstance(reports, dict) or not reports:
        return {
            "present": False,
            "by_short": {},
            "roles": {},
            "gating_axes": [],
            "not_scored_axes": [],
            "polarity": {},
            "rollup": {},
        }
    roles, polarity, not_scored, gating = {}, {}, [], []
    for short, rec in reports.items():
        if not isinstance(rec, dict):
            continue
        role = rec.get("role")
        roles[short] = role
        polarity[short] = rec.get("polarity")
        if role == ROLE_GATING:
            gating.append(short)
        elif role in _NOT_SCORED_ROLES and rec.get("call") in (None, ""):
            # gateless BY DESIGN — a real read that simply does not carry a verdict. Not a gap.
            not_scored.append(short)
    return {
        "present": True,
        "by_short": reports,
        "roles": roles,
        "gating_axes": sorted(gating),
        "not_scored_axes": sorted(not_scored),
        "polarity": polarity,
        "rollup": syn.get("skill_report_rollup") or {},
    }


# --- subtype-resolved parse ------------------------------------------------------------------
def parse_subtype_resolved(pkg: dict) -> dict:
    """Project the first-class `subtype_resolved` block into an agent-consumable summary + the set of
    per-stratum citation tokens (so a subtype claim in the hypothesis is TRACEABLE, not free-text).
    Tolerates absence (older/default runs). n-floor discipline is preserved: a stratum axis with
    subgroup_n_floor_met=False is surfaced but flagged so the agent must not credit it."""
    block = pkg.get("subtype_resolved")
    if not isinstance(block, dict):
        return {
            "present": False,
            "requested_strata": [],
            "available_strata": [],
            "per_stratum": [],
            "stratum_tokens": set(),
            "convergence_facet": None,
        }
    per_stratum = block.get("per_stratum") or []
    stratum_tokens: set = set()
    strata_summary = []
    for rec in per_stratum:
        if not isinstance(rec, dict):
            continue
        st = rec.get("stratum")
        if st:
            stratum_tokens.add(str(st))
        axes = rec.get("axes") or {}
        floor_ok = {}
        for ax, adata in axes.items() if isinstance(axes, dict) else []:
            if isinstance(adata, dict):
                floor_ok[ax] = bool(adata.get("subgroup_n_floor_met"))
        strata_summary.append({"stratum": st, "axes": axes, "n_floor_met_by_axis": floor_ok})
        # the PER-STRATUM AXIS names are citable too. The comment here used to claim they were added and
        # the code never added them, so a clause citing a stratum axis that is not ALSO a top-level
        # sub-verdict short was scored untraceable — teeth biting a claim the package does support.
        if isinstance(axes, dict):
            for ax in axes:
                stratum_tokens.add(str(ax))
    # also allow citing the requested/available stratum names
    for s in block.get("requested_strata") or []:
        stratum_tokens.add(str(s))
    for s in block.get("available_strata") or []:
        stratum_tokens.add(str(s))
    return {
        "present": True,
        "requested_strata": list(block.get("requested_strata") or []),
        "available_strata": list(block.get("available_strata") or []),
        "per_stratum": strata_summary,
        "stratum_tokens": stratum_tokens,
        "convergence_facet": block.get("convergence_facet"),
    }


# --- evidence-substrate correlated-evidence discount ---------
# Below this tagged fraction the substrate view is a MINORITY read of the package and the discount is
# reported as `tagging_sparse` — the check declares its own blind spot instead of passing silently.
# 0.5 = "the substrate lens can see at least half the cards"; production packages sit near 0.11.
#
# ★ F17: this floor is currently UNREACHABLE, and that is a property of the VOCABULARY, not of any target.
# `evidence_substrate` is declared on MEASUREMENT_TYPES (target-contracts vocabularies/measurement_types.yaml),
# and as of 2026-09-12 the `evidence_substrates` vocab has exactly TWO entries
# (recount3_tcga_gtex_bulk_rna, depmap_crispr_chronos) carried by 16 of 140 types, reaching 24 of 147 cards.
# So `tagged_fraction` tops out near 0.14 and `tagging_sparse` is hardwired True on every target the panel
# has ever run (15/15). A flag that cannot be False is not a flag — the same vacuous-constant defect the
# rest of this module exists to remove, one level up.
#
# The fix is NOT to lower the floor (that would fabricate confidence in a lens that genuinely sees 14% of
# the package) and NOT to read the registry from here (this module is the reproducible spine; a
# TARGET_CONTRACTS_ROOT read would make these fields env-dependent and the drift goldens flaky). It is to
# make the sparsity ATTRIBUTABLE from the package alone, so a reader can tell the two remedies apart:
#   * the card carries a `measurement_type` but that type declares no substrate → VOCABULARY debt, fixed in
#     target-contracts; no amount of per-run care moves it.
#   * the card carries no `measurement_type` at all → registry BACK-REF debt for that card.
# Both are stamped onto every card entry by _skills_common.envelope, so the decomposition is package-local
# and deterministic. Disclosure only: `tagging_sparse` and every unit count keep their exact prior values.
_SUBSTRATE_TAGGING_FLOOR = 0.5


def substrate_independence(pkg: dict) -> dict:
    """Group present cards by their declared `evidence_substrate`. Cards that SHARE a substrate
    are the same underlying measurement re-displayed (e.g. the recount3 TCGA/GTEx bulk-RNA
    tumor/normal cluster, or the DepMap-Chronos dependency cluster) and must count ONCE toward
    certainty — this is the certainty-discount half. Returns the grouping + the effective
    independent-unit count the certainty ceiling consumes, plus the TAGGING COVERAGE the count
    rests on (`substrate_tagged_fraction` / `tagging_sparse`)."""
    cards = pkg.get("cards") or []
    by_substrate: dict = {}
    untagged: list = []
    # F17 attribution of the untagged remainder — see _SUBSTRATE_TAGGING_FLOOR. Split by WHY the card is
    # untagged, because the two causes have different owners and only one of them is a per-run problem.
    untagged_vocab_gap: list = []  # has a measurement_type; that type declares no evidence_substrate
    untagged_no_type: list = []  # no measurement_type at all — registry `cards:` back-ref missing
    for c in cards:
        if not isinstance(c, dict):
            continue
        cid = c.get("card_id")
        if not cid:
            continue
        sub = c.get("evidence_substrate")
        if sub:
            by_substrate.setdefault(sub, []).append(cid)
        else:
            untagged.append(cid)
            (untagged_vocab_gap if c.get("measurement_type") else untagged_no_type).append(cid)
    correlated_groups = {s: cids for s, cids in by_substrate.items() if len(cids) > 1}
    n_distinct_substrates = len(by_substrate)
    n_tagged = sum(len(v) for v in by_substrate.values())
    n_cards = n_tagged + len(untagged)
    # INDEPENDENT UNITS = the DISTINCT TAGGED SUBSTRATES only.
    #
    # This used to be `n_distinct_substrates + len(untagged)` — one independent unit per untagged card —
    # which made the whole discount VACUOUS in production: `evidence_substrate` tagging is sparse (119 of
    # 134 cards untagged on the 2026-09-10 KRAS/COADREAD package), so the count came out at 121-125 on
    # every real target and the `< 2` cap in discounted_certainty could never be reached. The guard
    # SKILL.md advertises "WITH TEETH" had no reachable failing branch.
    #
    # An untagged card is NOT evidence of independence — it is evidence of MISSING PROVENANCE, and
    # inflating the count with it is conservative in exactly the wrong direction (it raises certainty).
    # So untagged cards are DISCLOSED (`n_untagged_cards`, `substrate_tagged_fraction`,
    # `tagging_sparse`) and excluded from the count; `tagging_sparse` makes the guard's own blindness a
    # first-class, auditable field rather than a silently inert check.
    n_independent = n_distinct_substrates
    tagged_fraction = round(n_tagged / n_cards, 3) if n_cards else None
    tagging_sparse = bool(n_cards) and (tagged_fraction or 0) < _SUBSTRATE_TAGGING_FLOOR
    # F17: is the sparsity STRUCTURAL (the vocabulary names no substrate for this evidence) or a per-run
    # provenance loss? Structural when the untagged remainder is dominated by cards whose measurement_type
    # simply declares no substrate — the emitter did stamp them, there was nothing to stamp. This is the
    # field that stops `tagging_sparse: true` from being read as "this target has poor provenance".
    # Can be False: a package whose untagged cards are mostly un-migrated (no measurement_type) sets it
    # False, and it is False whenever tagging is not sparse at all.
    vocabulary_limited = tagging_sparse and len(untagged_vocab_gap) > len(untagged_no_type)
    return {
        "by_substrate": by_substrate,
        "correlated_groups": correlated_groups,
        "untagged_cards": untagged,
        "n_distinct_substrates": n_distinct_substrates,
        "n_untagged_cards": len(untagged),
        "n_tagged_cards": n_tagged,
        "n_cards": n_cards,
        "substrate_tagged_fraction": tagged_fraction,
        # the substrate view cannot see most of the package → say so, do not silently pass
        "tagging_sparse": tagging_sparse,
        # WHY it is sparse, so the reader knows which repo the remedy lives in (see the module comment on
        # _SUBSTRATE_TAGGING_FLOOR). These are disclosure only — no unit count or cap consumes them.
        "n_untagged_vocabulary_gap": len(untagged_vocab_gap),
        "n_untagged_no_measurement_type": len(untagged_no_type),
        "substrate_vocabulary_limited": vocabulary_limited,
        "n_independent_units": n_independent,
        "correlated_evidence_discounted": bool(correlated_groups),
    }


# --- data gaps + weakest-link certainty (ported) + substrate/degradation discount -------------------
def data_gaps(conviction: dict, not_scored=()) -> list:
    """The in-play axes whose verdict is a GAP.

    `not_scored` excludes axes the spine itself declares UNSCORED — a `role=descriptive` / `role=inert`
    lens (skill_report.role) has `verdict: None` BY DESIGN: it is a context lens, not a decision gate, so
    it can never be a data GAP. Without this, all four gateless lenses (combination_vulnerability,
    literature_context, target_intrinsic, translational_readiness) were reported as data gaps on EVERY
    target, which (a) inflated `data_gaps` by four on every run, (b) under-counted
    `n_supporting_in_scope_lines` by four, and (c) let the LIMITING axis be attributed to a lens that
    gates nothing — EGFR/NSCLC reported `limiting_dimension: target_intrinsic`, rendered verbatim into
    the dashboard convergence layer. A descriptive lens with no verdict is DECLARED absence of scoring,
    not MISSING data; conflating the two is the gateless-tier conflation the role field exists to end."""
    skip = {_norm(d) for d in (not_scored or ())}
    return sorted(d for d, v in conviction.items() if v in GAP_VERDICTS and _norm(d) not in skip)


def _dim_certainty(verdict) -> str:
    return "low" if verdict in GAP_VERDICTS else "moderate"


# spine CERTAINTY_MODEL levels are {low, medium, high}; the integrator's rank uses {low, moderate, high}.
# Normalize the spine `medium` onto `moderate` so the two vocabularies compose.
_SPINE_CERTAINTY_TO_RANK = {"low": "low", "medium": "moderate", "high": "high"}


def parse_certainty_by_axis(pkg: dict) -> dict:
    """Project synthesis.decision_facets.certainty_by_axis into {short: level} where level is the spine's
    weakest-link per-axis certainty (CERTAINTY_MODEL: min(coverage, corroboration)) normalized onto the
    integrator's {low, moderate, high} rank. Tolerates absence (older package / no axis opted in) → {}."""
    facets = (pkg.get("synthesis") or {}).get("decision_facets") or {}
    cba = facets.get("certainty_by_axis")
    if not isinstance(cba, dict):
        return {}
    out: dict = {}
    for short, rec in cba.items():
        if not isinstance(rec, dict):
            continue
        lvl = (rec.get("certainty") or {}).get("level") if isinstance(rec.get("certainty"), dict) else None
        norm = _SPINE_CERTAINTY_TO_RANK.get(str(lvl).lower()) if lvl is not None else None
        if norm:
            out[short] = norm
    return out


def weakest_link_certainty(conviction: dict, in_scope: list, certainty_by_axis: dict = None, gating_axes=None) -> tuple:
    """Overall certainty bounded by the weakest decision-relevant line.

    Per-axis base: prefer the spine's own CERTAINTY_MODEL level (`certainty_by_axis[short]`, normalized to
    the integrator rank) so the integrator agrees with the spine instead of re-deriving; fall back to the
    binary `_dim_certainty` proxy for axes that have NOT opted into the sidecar. A spine-supplied `high`
    is honoured here (the old proxy never emitted `high`) but breadth/independence can still LOWER it via
    discounted_certainty — the independence cap keeps single-substrate corroboration from shipping `high`.

    The HEADLINE stays the CONJUNCTIVE weakest link over every in-scope axis: a decision is only as good
    as its worst decision-relevant line, and averaging would let a wall of strong descriptive axes bury one
    fatal gap. But the weakest-link SCALAR is near-constant across targets in production (every 2026-09-10
    package reports `low`, because expression/selectivity report `low` universally), so the scalar alone
    carries no discrimination — `certainty_distribution` below is what actually separates targets, and the
    LIMITING axis is restricted to `gating_axes` when supplied.

    `gating_axes` (role=gating shorts, from parse_skill_reports) narrows WHICH axis is named as limiting.
    Without it the limiting axis is whatever axis happened to be weakest, which on EGFR/NSCLC named
    `target_intrinsic` — a DESCRIPTIVE lens that gates nothing — and the dashboard convergence layer
    renders that verbatim, telling a reviewer the decision is limited by a lens that cannot limit it. The
    headline value is UNCHANGED by this argument; only the attribution is."""
    if not in_scope:
        return "low", None
    cba = certainty_by_axis or {}
    levels = {dim: (cba.get(dim) or _dim_certainty(conviction.get(dim))) for dim in in_scope}
    worst = min(levels.values(), key=lambda c: CERTAINTY_RANK[c])
    # attribute the limit to a GATING axis when we know the roles; fall back to all in-scope axes when
    # no gating axis is in scope (or roles are unavailable) so the field is never silently dropped.
    pool = [d for d in in_scope if d in set(gating_axes)] if gating_axes else list(in_scope)
    if not pool:
        pool = list(in_scope)
    limiting = min(pool, key=lambda d: (CERTAINTY_RANK[levels[d]], list(in_scope).index(d)))
    if CERTAINTY_RANK[levels[limiting]] >= CERTAINTY_RANK["high"]:
        limiting = None  # nothing is limiting when every axis in the pool is `high`
    return worst, limiting


def binding_axis_attribution(
    conviction: dict, in_scope: list, certainty_by_axis: dict = None, gating_axes=None, roles: dict = None
) -> dict:
    """★ F18: WHICH axis actually set the headline, versus which one `limiting_dimension` names.

    `weakest_link_certainty` is deliberately asymmetric, and it says so: the headline `worst` is the
    conjunctive minimum over EVERY scored in-scope axis, while the LIMITING attribution is restricted to
    `role=gating` (F1/#1310 — a descriptive lens that gates nothing must not be rendered to a reviewer as
    the thing limiting the decision). Both halves are right on their own.

    What was missing is that the two can disagree, and nothing said so. On the 2026-09-12 panel
    ERBB2/BRCA emitted `overall_certainty: low` beside `limiting_dimension: mechanism` — and mechanism was
    MODERATE. The axis that actually bound was `subtype_fit`, which is not a gating axis and so was
    correctly excluded from the attribution pool, leaving the artifact naming a non-binding axis with no
    indication it was non-binding. A reviewer who acts on `limiting_dimension` there funds mechanism work
    and the certainty does not move. DATA_PRODUCT.md claimed these fields "read as one coherent
    statement"; on that target they did not.

    Only 1 of 20 targets showed the symptom, but that is LUCK, not safety: a non-gating axis sat at the
    minimum in 15 of 58 (axis, target) instances (7 role-unknown, 5 descriptive, 3 inert) and was merely
    TIED with a gating axis on the other 19 targets, which masks the disagreement. It surfaces whenever a
    non-gating axis is the STRICT unique minimum.

    Note the THIRD role state this exposes. F1 handles `role=gating` and excludes `descriptive`/`inert`,
    but an axis absent from `synthesis.skill_reports` altogether has `role=None` — neither gating nor
    declared gateless — and `subtype_fit` is in that state on 12 of 20 targets. It is not in
    `not_scored_axes` (which requires a declared descriptive/inert role), so it is silently treated as
    eligible for the headline minimum. That is a #1310 PRODUCER gap (the axis emits no skill_report), not
    something this integrator can fix; naming the role here is what makes it visible.

    DISCLOSURE ONLY — the headline level is unchanged, and no cap, unit count or verdict reads any of
    these. Fixing the NUMBER would mean either dropping non-gating axes from the conjunctive minimum
    (which would let a wall of strong gating axes bury a real gap the spine scored `low`) or widening the
    attribution pool back to every axis (the F1 regression). Neither is right; the incoherence is real and
    belongs on the artifact where a reader can see it."""
    cba = certainty_by_axis or {}
    if not in_scope:
        return {
            "binding_axis": None,
            "binding_axis_role": None,
            "binding_axis_level": None,
            "limiting_dimension_is_binding": None,
            "n_binding_axes": 0,
            "binding_axis_is_gating": None,
        }
    levels = {dim: (cba.get(dim) or _dim_certainty(conviction.get(dim))) for dim in in_scope}
    worst = min(levels.values(), key=lambda c: CERTAINTY_RANK[c])
    # every axis AT the minimum, in in_scope order — the count matters, because a lone non-gating axis at
    # the minimum is the case that makes the attribution misleading, while a tie with a gating axis does not
    at_min = [d for d in in_scope if levels[d] == worst]
    binding = at_min[0]
    gating = set(gating_axes) if gating_axes else set()
    # mirror weakest_link_certainty's pool selection EXACTLY, or this reports a disagreement with an axis
    # that function never actually named
    pool = [d for d in in_scope if d in gating] if gating_axes else list(in_scope)
    if not pool:
        pool = list(in_scope)
    limiting = min(pool, key=lambda d: (CERTAINTY_RANK[levels[d]], list(in_scope).index(d)))
    limiting_is_binding = CERTAINTY_RANK[levels[limiting]] == CERTAINTY_RANK[worst]
    return {
        "binding_axis": binding,
        # None here is INFORMATIVE: the axis is absent from synthesis.skill_reports entirely (role unknown),
        # which is a different claim from a declared descriptive/inert role.
        "binding_axis_role": (roles or {}).get(binding),
        "binding_axis_level": worst,
        "n_binding_axes": len(at_min),
        "binding_axis_is_gating": (binding in gating) if gating_axes else None,
        # the headline claim: does the axis named as limiting sit AT the level the headline reports?
        "limiting_dimension_is_binding": limiting_is_binding,
    }


def certainty_distribution(conviction: dict, in_scope: list, certainty_by_axis: dict = None, gating_axes=None) -> dict:
    """The per-axis certainty DISTRIBUTION behind the weakest-link headline.

    The scalar `overall_certainty` is a conjunctive minimum and is therefore `low` on essentially every
    real package — true, but useless for ranking targets against each other. This emits the shape it
    hides: `by_axis` (every in-scope axis → level), `n_axes_by_level` (the histogram), and the same split
    restricted to GATING axes, which is the read a portfolio reviewer actually wants ("9 axes, 2 low, both
    descriptive" is a very different target from "9 axes, 2 low, both gating").

    `gating_axes=None` means the ROLES ARE UNKNOWN (a pre-#1310 package with no `synthesis.skill_reports`),
    which is NOT the same claim as "no axis gates". The gating slice is then emitted as None: an all-zero
    histogram would read as a package whose every axis is decorative, and a reviewer would act on it."""
    cba = certainty_by_axis or {}
    by_axis = {dim: (cba.get(dim) or _dim_certainty(conviction.get(dim))) for dim in in_scope}

    def _hist(d):
        return {lvl: sum(1 for v in d.values() if v == lvl) for lvl in ("low", "moderate", "high")}

    roles_known = gating_axes is not None
    gate_axis = {d: lvl for d, lvl in by_axis.items() if d in set(gating_axes)} if roles_known else None
    return {
        "by_axis": dict(sorted(by_axis.items())),
        "n_axes_by_level": _hist(by_axis),
        "n_axes_scored": len(by_axis),
        "gating_roles_known": roles_known,
        "gating_by_axis": dict(sorted(gate_axis.items())) if roles_known else None,
        "n_gating_axes_by_level": _hist(gate_axis) if roles_known else None,
        "n_gating_axes_scored": len(gate_axis) if roles_known else None,
        # spine-sourced vs proxy-derived: a level the sidecar supplied is authoritative, the rest is the
        # binary gap/non-gap proxy — the reader must be able to tell them apart.
        "axes_from_spine_sidecar": sorted(d for d in by_axis if d in cba),
        "axes_from_proxy": sorted(d for d in by_axis if d not in cba),
    }


def gate_independence(cross_gate_shared_evidence: Optional[dict], supporting_gates) -> dict:
    """Count INDEPENDENT decision-gate groups among the SUPPORTING (non-gap, in-scope) gates, using the
    spine's AUTHORITATIVE cross_gate_shared_evidence (P4). Each gate starts its own group; gates that
    share a fired input card (spine `correlated_gate_pairs`) are UNIONed. Fewer groups = less independent
    corroboration at the DECISION grain (the spine's own note: '~11 verdict gates carry only ~4
    independent axes'). This is the spine-authoritative sibling of the card-substrate discount.

    `present=False` (→ no gate-cap; the substrate discount stands alone) when the spine facet is absent —
    an older package is unaffected. Restricting the union to `supporting_gates` keeps a pair touching an
    out-of-scope / gap gate from spuriously collapsing the count."""
    if not isinstance(cross_gate_shared_evidence, dict) or not cross_gate_shared_evidence:
        return {"present": False, "n_independent_gate_groups": None, "correlated_gate_pairs": []}
    gates = list(dict.fromkeys(supporting_gates))  # de-dup, preserve order
    parent = {g: g for g in gates}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    used_pairs = []
    for pair in cross_gate_shared_evidence.get("correlated_gate_pairs") or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            continue
        a, b = pair
        if a in parent and b in parent:  # both ends are supporting decision gates
            used_pairs.append([a, b])
            parent[_find(a)] = _find(b)
    n_groups = len({_find(g) for g in gates}) if gates else 0
    return {"present": True, "n_independent_gate_groups": n_groups, "correlated_gate_pairs": used_pairs}


def discounted_certainty(
    base: str,
    n_independent_units: int,
    degraded_inputs: list,
    n_independent_gate_groups: Optional[int] = None,
    tagging_sparse: bool = False,
) -> dict:
    """Apply the orthogonal certainty caps AFTER the weakest-link base (
    'the correlated-evidence discount is applied before certainty is reported'):

      - independence cap, GRADED: <= 1 independent EVIDENCE unit → cap `low` (all corroboration is
        ONE measurement); exactly 2 → cap `moderate` (two measurements cannot underwrite `high`).
        A graded ladder is what makes the control REACHABLE: with the old single `< 2` rung and the
        old untagged-cards-are-independent count, production packages reported 121-125 units and the
        cap could never fire on any real target.

        The cap runs over the AUTHORITATIVE unit views only, taking the most conservative:
          * the card-substrate view (`n_independent_units`) counts ONLY when `tagging_sparse` is False.
            A package where `evidence_substrate` is mostly/entirely unpopulated has a METADATA gap, not
            a demonstrated lack of independent measurement — capping `low` on it would swap one constant
            (the old vacuous 121-unit pass) for the opposite constant (a universal `low`), which is just
            as undiscriminating and blames the target for a pipeline gap.
          * the spine's decision-gate-group view (`n_independent_gate_groups`) counts whenever the
            spine emitted the facet; it is derived from FIRED CARDS, so it is populated on real packages
            and is the rung that actually bites.
        With no authoritative view, the unit count is still REPORTED but caps nothing
        (`independence_view_authoritative: False`) — the check declares that it abstained. That flag
        answers "was the independence read ABLE to speak", NOT "did it lower anything": a view can be
        authoritative and still find >= 3 units, capping nothing. `independence_cap_binding` is the
        separate answer to the second question. Naming the two apart matters because the live KRAS run
        reported an authoritative view, three gate groups, and no cap — under the old single flag that
        read as a cap a reviewer would go looking for.

    `cap_reasons` lists every cap CONSIDERED, whether or not it bound. `cap_ceiling` is the certainty
    level those caps jointly permit, so `base` / `cap_ceiling` / `final` / `capped` are readable as one
    coherent statement: caps that permit `moderate` over a `low` base leave `final: low, capped: False`,
    and a reviewer can see the base bound rather than suspecting a listed cap silently did.

      - degradation cap: a missing optional input (dossier / risk) → cap `low` (a missing input must
        never inflate certainty).

      - tagging-sparsity cap: `tagging_sparse` itself caps at `moderate`. Certainty may not claim `high`
        on an independence read that cannot see most of the package. This is the declared-blindness
        rung: the guard says what it could not see instead of passing silently."""
    cap = CERTAINTY_RANK["high"]
    reasons = []
    # candidate unit views, each (kind, count) — only the AUTHORITATIVE ones may cap.
    views: list[tuple[str, int]] = []
    if not tagging_sparse:
        views.append(("substrate", n_independent_units))
    if n_independent_gate_groups is not None:
        views.append(("decision-gate-group", n_independent_gate_groups))
    unit_cap_binding = False
    if views:
        unit_kind, effective_units = min(views, key=lambda kv: kv[1])
        view_authoritative = True
        if effective_units <= 1:
            cap = min(cap, CERTAINTY_RANK["low"])
            unit_cap_binding = True
            reasons.append(f"only {effective_units} independent evidence {unit_kind}(s)")
        elif effective_units == 2:
            cap = min(cap, CERTAINTY_RANK["moderate"])
            unit_cap_binding = True
            reasons.append(f"only {effective_units} independent evidence {unit_kind}s (cannot underwrite high)")
    else:
        unit_kind, effective_units, view_authoritative = "substrate", n_independent_units, False
    if degraded_inputs:
        cap = min(cap, CERTAINTY_RANK["low"])
        reasons.append(f"degraded inputs: {sorted(degraded_inputs)}")
    if tagging_sparse:
        cap = min(cap, CERTAINTY_RANK["moderate"])
        reasons.append("evidence_substrate tagging sparse — independence read covers a minority of cards")
    final_rank = min(CERTAINTY_RANK.get(base, 0), cap)
    return {
        "base": base,
        "final": RANK_CERTAINTY[final_rank],
        "capped": final_rank < CERTAINTY_RANK.get(base, 0),
        "cap_reasons": reasons,
        # the level the caps jointly PERMIT, independent of the base — see the docstring on why this is
        # emitted alongside `capped` rather than left to be inferred from the reason list.
        "cap_ceiling": RANK_CERTAINTY[cap],
        "effective_independent_units": effective_units,
        "independence_unit_kind": unit_kind,
        "independence_view_authoritative": view_authoritative,
        "independence_cap_binding": unit_cap_binding,
        "tagging_sparse": bool(tagging_sparse),
    }


# --- retrieve-don't-recall + clause-traceability WITH TEETH ------------------------------
# WHAT COUNTS AS A PMID CLAIM. The bare `\b\d{6,9}\b` this replaces read ANY 6-9 digit run as an
# asserted PMID, which is FALSE for the numbers the framework's own prompt asks the agent to quote:
# `n=123456` (cohort size), `chr7:140453136` (a genomic coordinate), `TPM 1000000`, `p=0.000123456`, an
# ENSG suffix, a p-value exponent. Each of those became an "unretrieved PMID", which sets
# `promotable: false` and CAPS the verdict at `advanceable_flagged` — the teeth biting well-behaved
# output. Two shapes, and only two, are read as a claim:
#  1. an EXPLICIT pmid/pubmed cue (`PMID: 12345678`) — always a claim, never an escape from the
#     exact-membership check, whatever the digits are glued to; and
#  2. a citation the agent PRESENTED as a bare identifier list — nothing but digit runs and separators
#     once the PMID label is stripped ("12345678", "PMIDs 12345678, 34567890").
# Space-delimited digits inside PROSE are indistinguishable from a bare PMID by shape alone
# (`TPM 1000000`), so they are NOT claims. That costs no teeth: an uncued digit run stays in the
# residual, and the residual must itself resolve to a retrieved spine token, so a confabulated
# "Smith et al. 34567890" is still rejected — as an unresolvable citation rather than as a bad PMID.
_PMID_CUE_RE = re.compile(r"(?:pmids?|pubmed(?:\s*ids?)?)\s*[:#=]?\s*(\d{6,9})", re.IGNORECASE)
# label noise that is legitimately part of a PMID citation and resolves to nothing on its own; stripped
# from the residual so "PMID 12345678" with 12345678 retrieved does not fail on the leftover word "PMID".
_PMID_LABEL_RE = re.compile(r"\b(?:pmids?|pubmed(?:\s*id)?|doi|et\s+al\.?)\b[\s:#=,;]*", re.IGNORECASE)
_RESIDUAL_NOISE_RE = re.compile(r"^[\s\-–—:;,.()\[\]/&+|]*$")
_PMID_LIST_SHAPED_RE = re.compile(r"^[\s\d\-–—:;,.#=/&+|()\[\]]*$")


def _norm(s):
    return str(s).replace("-", "_").lower()


def pmid_claims(text: str) -> list:
    """The digit runs in `text` that constitute a PMID CLAIM, de-duplicated in order of appearance.

    Cue-bearing runs (`PMID: 12345678`) always count; UNCUED runs count only in a bare identifier list.
    See the two shapes above. This is the single definition of "the agent asserted a PMID", used by the
    traceability check and its tests."""
    text = text or ""
    stripped = _PMID_LABEL_RE.sub(" ", text)
    bare = []
    if _PMID_LIST_SHAPED_RE.match(stripped):
        # inside a bare list there is no prose to confuse, so every separator-delimited 6-9 digit run is
        # a claim. Leading zeros are excluded: no PMID has one, but a decimal tail like 0.000123456 does.
        bare = [t for t in re.split(r"\D+", stripped) if 6 <= len(t) <= 9 and not t.startswith("0")]
    seen, out = set(), []
    for p in _PMID_CUE_RE.findall(text) + bare:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def check_traceability(clause_citations: list, surface: dict) -> list:
    """Return the atomic citation tokens that do NOT resolve to THIS package's deterministic spine.

    RETRIEVE-DON'T-RECALL: any PMID CLAIM (see `pmid_claims`) must be an EXACT member of the risk
    agent's retrieved `allowed_pmids` — NO substring/any() escape for PMIDs (a self-invented PMID is
    confabulation). Non-PMID tokens (card_ids / sub-verdict names / rule_ids / dossier fields / stratum
    tokens) may match by normalized-exact or by embedding a known specific (>=6 char) token, so a legit
    phrase like "copy-number-distribution card" passes.

    The residual left after removing the PMIDs is stripped of PMID LABEL NOISE and pure punctuation
    before it is required to resolve: "PMID 12345678" used to fail even with 12345678 retrieved, because
    the leftover word "PMID" matched no spine field — the check rejected the EXACT citation format the
    prompt asks for."""
    valid = (
        surface["card_ids"]
        | surface["sub_verdicts"]
        | surface["rule_ids"]
        | surface.get("dossier_fields", set())
        | surface.get("strata", set())
    )
    valid_norm = {_norm(t) for t in valid}
    valid_sub = {_norm(t) for t in valid if len(str(t)) >= 6}
    allowed_pmids = {str(p).strip() for p in surface.get("pmids", set())}
    bad = []
    for c in clause_citations or []:
        cstr = str(c)
        # 1. PMID claims — exact membership only.
        pmids_in = pmid_claims(cstr)
        unretrieved = next((p for p in pmids_in if p not in allowed_pmids), None)
        if unretrieved is not None:
            bad.append(f"{cstr} (unretrieved PMID {unretrieved})")
            continue
        # 2. Residual after the (retrieved) PMIDs + their label noise + punctuation are removed. Empty
        #    residual ⇒ the citation WAS a PMID citation and it resolved.
        residual = cstr
        for p in pmids_in:
            residual = residual.replace(p, " ")
        residual = _PMID_LABEL_RE.sub(" ", residual)
        if _RESIDUAL_NOISE_RE.match(residual):
            continue
        # 3. Non-PMID residual — normalized-exact or embeds a known specific token. Match on the
        #    RESIDUAL, not the raw string, so a retrieved-PMID prefix cannot mask an unresolvable tail.
        cn = _norm(residual.strip())
        if cn in valid_norm or _norm(cstr) in valid_norm:
            continue
        if any(tok in cn for tok in valid_sub):
            continue
        bad.append(cstr)
    return bad


# --- intra-package coherence (adversarial-survival) --------------------------------------
# The positive-thesis clauses whose job is to ASSERT a case for the target. therapeutic_window is
# deliberately EXEMPT from the negative-signal rule: its job is to weigh liabilities, so citing a
# negative safety / selectivity line there is honest framing, not an incoherent positive assertion.
POSITIVE_THESIS_CLAUSES = ("causal_rationale", "therapeutic_hypothesis", "population")
ALL_SUPPORT_CLAUSES = ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window")

# INTRINSIC CROSS-CARD CONTRADICTIONS — a small, GENERAL registry of thesis families that a
# NEGATIVE/absent SIBLING line measuring the SAME biology undercuts. These are the cases where the
# contradiction is between a CITED positive line and a PRESENT-but-UNCITED negative sibling, so the
# clause-cites-a-negative-line rule cannot see it. Stated generally (not tuned to any one target):
# claiming a synthetic-lethal / combination strategy is incoherent when the partner-mapping line found
# no actionable partner — this is the SL-vs-no_partner_mapped class the smoke surfaced on MARK2.
# The registry is the extensible home for further principled cross-card incoherences.
INTRINSIC_CONTRADICTIONS = [
    {
        "label": "combination_or_sl_strategy_without_mapped_partner",
        # a clause resting on these positive SL/combination lines as its actionable strategy ...
        "asserts": {
            "synthetic-lethal-partners",
            "combinatorial-dependency",
            "synthetic_lethal_partners",
            "combinatorial_dependency",
            "combination_vulnerability",
        },
        # ... is contradicted when a partner-mapping line is present with a no-partner call.
        "contradicted_by": {
            "partner-conditional-dependency": {"no_partner_mapped", "no_sl_partner"},
            "partner_conditional_dependency": {"no_partner_mapped", "no_sl_partner"},
            "synthetic_lethal_partners": {"no_partner_mapped", "no_sl_partner"},
        },
    },
]


def is_negative_verdict(v) -> bool:
    """A MEASURED-negative sub-verdict (NOT an absence/gap — those are handled by absence-discipline)."""
    if not isinstance(v, str) or v in GAP_VERDICTS:
        return False
    n = _norm(v)
    if n in {_norm(x) for x in NEGATIVE_SIGNAL_VERDICTS}:
        return True
    return any(n.startswith(s) or s in n for s in _NEGATIVE_STEMS)


def coherence_violations(
    clauses: dict,
    conviction: dict,
    edges: list,
    tensions: list,
    present_norm: set,
    out_of_scope=None,
    card_calls: dict = None,
) -> dict:
    """INTRA-PACKAGE COHERENCE (the root-cause fix): the integrator may not assert a positive
    claim on a signal that ANOTHER present package signal contradicts, UNLESS the clause surfaces the
    tension. Enforced FOUR ways:

      (a) MEASURED-NEGATIVE cited as support: a positive-thesis clause (causal_rationale /
          therapeutic_hypothesis / population) cites a sub-verdict DIMENSION whose verdict is
          measured-negative (e.g. dependency=non_dependent_paralog_buffered) in its SUPPORT citations
          without surfacing it (contradicting_citations or a principal tension).
      (a2) SAME, for a CARD whose interpretation_call is measured-negative (card-grain, not just
          sub-verdict grain).
      (b) AGENT-EDGE contradiction unsurfaced: the agent's OWN typed `contradicts` / `tensions_with`
          edges are enforced on its own clauses.
      (c) INTRINSIC CROSS-CARD contradiction: a clause rests on a positive thesis FAMILY
          (INTRINSIC_CONTRADICTIONS.asserts, e.g. the SL/combination cards) while a NEGATIVE sibling
          line measuring the same biology is PRESENT (e.g. partner-conditional-dependency =
          no_partner_mapped) and unsurfaced — the SL-vs-no_partner_mapped class where the contradicting
          line is present but UNCITED, so (a)/(a2) cannot see it.

    `clauses` maps clause_key -> {"support": [tokens], "surfaced": [tokens]}. `present_norm` is the
    normalized citation surface (card_ids | sub_verdict names | rule_ids). `card_calls` maps card_id ->
    interpretation_call (card-grain verdicts). Returns {clause_key: [violation dicts]}."""
    oos = {_norm(d) for d in (out_of_scope or [])}

    def _oos(tok: str) -> bool:
        """A card/dimension token is out of scope for the objective's modality — a violation on it
        must NOT count toward promotion_blockers (scope-aware coherence)."""
        return token_out_of_scope(tok, oos)

    card_calls = card_calls or {}
    # MECHANISM-CONDITIONING (mirrors gate_ceiling): for a mutant-selective / GoF driver
    # (safety=wt_*_mechanism_mismatch) a `non_dependent` reading on the dependency axis is EXPECTED, not a
    # contradiction — so a positive thesis may rest on such a target without the dependency non-dependence
    # counting as an unsurfaced negative. Applies at BOTH grains (the `dependency` dimension and its member
    # cards, e.g. pan-cancer-crispr-dependency-distribution). Same signal, same discriminator as the gate:
    # absent on TSGs and highly_constrained dangerous-FPs, so it does not silence a real contradiction.
    mutant_selective = conviction.get("safety") in _MUTANT_SELECTIVE_SAFETY
    _dep_norms = {_norm("dependency")} | _DIM_CARD_NORMS.get(_norm("dependency"), frozenset())

    def _mechanism_benign(tok_norm: str, verdict) -> bool:
        return (
            mutant_selective
            and tok_norm in _dep_norms
            and isinstance(verdict, str)
            and _norm(verdict) in {_norm(x) for x in _NON_DEPENDENT_TOKENS}
        )

    # measured-negative SIGNALS keyed by normalized token → (display_name, verdict). Covers both
    # sub-verdict dimensions and card-grain interpretation calls. OUT-OF-SCOPE-modality signals are
    # excluded (e.g. the ADC/TCE surface cards for a small-molecule objective); mechanism-benign
    # dependency non-dependence (mutant-selective driver) is likewise excluded.
    neg_norm: dict = {}
    for d, v in conviction.items():
        if not _oos(_norm(d)) and is_negative_verdict(v) and not _mechanism_benign(_norm(d), v):
            neg_norm[_norm(d)] = (d, v)
    for cid, call in card_calls.items():
        if not _oos(_norm(cid)) and is_negative_verdict(call) and not _mechanism_benign(_norm(cid), call):
            neg_norm.setdefault(_norm(cid), (cid, call))

    # unified present-signal value lookup (sub-verdict OR card call), by normalized key
    value_by_norm: dict = {}
    for d, v in conviction.items():
        value_by_norm[_norm(d)] = v
    for cid, call in card_calls.items():
        value_by_norm.setdefault(_norm(cid), call)

    conflict_edges = []  # (norm_a, norm_b) pairs the agent typed as contradicts / tensions_with
    for e in edges or []:
        if isinstance(e, dict) and e.get("type") in ("contradicts", "tensions_with"):
            a, b = _norm(e.get("from_dimension", "")), _norm(e.get("to_dimension", ""))
            if a and b and a != b:
                conflict_edges.append((a, b))

    tension_tok_sets = [{_norm(c) for c in (t.get("citations") or [])} for t in (tensions or []) if isinstance(t, dict)]

    def _expand(tok):
        """A normalized token → itself PLUS its member-card norms if it is a sub-verdict DIMENSION.
        Bridges the dimension↔card grain mismatch: a tension that cites a dimension's cards
        (gnomad-lof-constraint) surfaces that dimension ('safety'). A card/rule token expands to
        just itself."""
        return {tok} | _DIM_CARD_NORMS.get(tok, frozenset())

    def _surfaced_in(tok, tokenset):
        # tok is surfaced within tokenset if the token OR (when tok is a dimension) any of its
        # member cards appears — grain-agnostic surfacing.
        return bool(_expand(tok) & tokenset)

    def _surfaced_as_tension(x):
        return any(_surfaced_in(x, ts) for ts in tension_tok_sets)

    violations: dict = {}
    for key, cl in clauses.items():
        support = {_norm(t) for t in (cl.get("support") or [])}
        surfaced = {_norm(t) for t in (cl.get("surfaced") or [])}
        found = []
        # (a)/(a2) measured-negative sub-verdict OR card cited as support — positive-thesis clauses
        if key in POSITIVE_THESIS_CLAUSES:
            for nd, (name, verdict) in neg_norm.items():
                if nd in support and not _surfaced_in(nd, surfaced) and not _surfaced_as_tension(nd):
                    found.append(
                        {
                            "type": "negative_signal_asserted",
                            "dimension": name,
                            "verdict": verdict,
                            "detail": (
                                f"cites '{name}' (measured-negative verdict '{verdict}') as SUPPORT "
                                "without surfacing it as a tension (move to contradicting_citations "
                                "or a principal tension)"
                            ),
                        }
                    )
        # (b) agent contradicts/tensions_with edge enforced on this clause's own citations
        for a, b in conflict_edges:
            for x, y in ((a, b), (b, a)):
                if _oos(x) or _oos(y):  # tension touches an out-of-scope-modality axis → not a cap
                    continue
                # Surfaced if y is in the clause's contradicting_citations OR any principal tension —
                # at EITHER grain (the dimension token OR any of its member cards). Requiring the SAME
                # tension to cite both x and y (the old _tension_covers) false-fired when the LLM
                # surfaced the contradicting dimension via its cards in a standalone tension.
                if (
                    x in support
                    and y in present_norm
                    and y not in support
                    and not _surfaced_in(y, surfaced)
                    and not _surfaced_as_tension(y)
                ):
                    found.append(
                        {
                            "type": "edge_contradiction_unsurfaced",
                            "asserted": x,
                            "contradicted_by": y,
                            "detail": (
                                f"cites '{x}' as support while its OWN typed edge marks '{y}' as "
                                f"contradicting/tensioning it, and '{y}' is present but unsurfaced"
                            ),
                        }
                    )
        # (c) intrinsic cross-card contradiction (present-but-uncited negative sibling)
        if key in POSITIVE_THESIS_CLAUSES:
            for rule in INTRINSIC_CONTRADICTIONS:
                asserts_n = {_norm(a) for a in rule["asserts"]}
                rested_on = sorted(t for t in (asserts_n & support) if not _oos(t))
                if not rested_on:  # the asserted thesis is entirely out-of-scope for this modality
                    continue
                seen_sig: set = set()  # dedup registry keys that normalize identically
                for sig, negvals in rule["contradicted_by"].items():
                    sig_n = _norm(sig)
                    if sig_n in seen_sig or _oos(sig_n):  # skip an out-of-scope contradicting sibling
                        continue
                    val = value_by_norm.get(sig_n)
                    if val in negvals and not _surfaced_in(sig_n, surfaced) and not _surfaced_as_tension(sig_n):
                        seen_sig.add(sig_n)
                        found.append(
                            {
                                "type": "intrinsic_contradiction",
                                "label": rule["label"],
                                "rested_on": rested_on,
                                "contradicted_by": sig,
                                "verdict": val,
                                "detail": (
                                    f"rests on {rested_on} but '{sig}' is present with '{val}' "
                                    f"({rule['label']}) and is not surfaced — the strategy is "
                                    "internally unsupported"
                                ),
                            }
                        )
        if found:
            violations[key] = found
    return violations


def surface_coherence_tensions(coherence_v: dict) -> list:
    """REMEDIATE detected intra-package coherence violations by SURFACING each into the structured
    `tensions` slot (fold the contradiction into the clause OR into `tensions`), so
    the emitted hypothesis carries the contradiction explicitly for a reviewer + a skeptic instead of
    burying it. This deliberately does NOT mutate any LLM clause statement (LLM-narrated
    fields stay in slots distinct from deterministic ones): it returns DETERMINISTIC, clearly-tagged
    tension entries (`source: integrator_coherence_guard`) the caller appends to the emitted tensions.
    The always-on detection + promotion block (in run.py) remain the teeth; this is the artifact-level
    surfacing so the tension is never an unacknowledged assertion."""
    out_tensions = []
    for clause_key, viols in (coherence_v or {}).items():
        for v in viols:
            if v["type"] == "negative_signal_asserted":
                stmt = (
                    f"clause '{clause_key}' rests on '{v['dimension']}', whose measured verdict "
                    f"'{v['verdict']}' does not support it"
                )
                cites = [v["dimension"]]
            elif v["type"] == "intrinsic_contradiction":
                stmt = (
                    f"clause '{clause_key}' rests on {v['rested_on']} but '{v['contradicted_by']}' "
                    f"is present with '{v['verdict']}' ({v['label']}) — the strategy has no "
                    "actionable support"
                )
                cites = list(v["rested_on"]) + [v["contradicted_by"]]
            else:  # edge_contradiction_unsurfaced
                stmt = f"clause '{clause_key}' rests on '{v['asserted']}' while '{v['contradicted_by']}' contradicts it"
                cites = [v["asserted"], v["contradicted_by"]]
            out_tensions.append(
                {"statement": stmt, "citations": cites, "clause": clause_key, "source": "integrator_coherence_guard"}
            )
    return out_tensions


# --- per-subskill GROUNDED SUBSTRATE (the design-correct literature path) ----------------------
def parse_grounded_substrate(substrate: Optional[dict]) -> dict:
    """Project the per-axis `ground_axis` blocks (the SHARED grounded substrate) into an
    agent-consumable per-axis finding list + the set of grounded PMIDs (which become CITABLE, traceable
    evidence) + the axes whose literature CONTRADICTS the deterministic verdict (engine↔literature
    discordance).

    This is the DESIGN-CORRECT literature path (grounded-substrate two-projection design):
    literature reaches the hypothesis via the per-subskill grounding DIRECTLY, NOT via the risk
    projection (the two projections are siblings; neither feeds the other). ESCALATE-ONLY BY
    CONSTRUCTION: the findings + PMIDs only ENRICH the panel + can RAISE a discordance tension; they
    never touch the deterministic ceiling (gate_ceiling consults ONLY the package hard_gates), so
    grounded literature can raise a concern but never lower a deterministic one.

    Tolerates absence + BOTH record shapes: the full `ground_axis` record
    {axis, deterministic, grounded:{...}} OR a bare grounded block. Cited PMIDs already passed
    confab-containment in build_grounded_block (unretrieved PMIDs were dropped), so they are trusted
    here as the retrieved-and-cited set."""
    if not isinstance(substrate, dict) or not substrate:
        return {"present": False, "per_axis": [], "pmids": set(), "discordant_axes": [], "n_findings": 0}
    per_axis, pmids, discordant, n_findings = [], set(), [], 0
    for axis, rec in substrate.items():
        if not isinstance(rec, dict):
            continue
        g = rec.get("grounded", rec) or {}
        findings = []
        for f in g.get("findings") or g.get("liability_findings") or []:
            if not isinstance(f, dict):
                f = {"finding": f, "kind": "", "cited_pmids": []}
            cp = [str(p) for p in (f.get("cited_pmids") or [])]
            pmids.update(cp)
            findings.append({"finding": f.get("finding"), "kind": f.get("kind"), "cited_pmids": cp})
        n_findings += len(findings)
        contra = bool(g.get("contradicts_deterministic"))
        if contra:
            discordant.append(axis)
        per_axis.append(
            {
                "axis": axis,
                "anchor_verdict": g.get("anchor_verdict"),
                "findings": findings,
                "corroborations": g.get("corroborations") or [],
                "contradicts_deterministic": contra,
                "corpus_pin": g.get("corpus_pin"),
                "escalate_only": bool(g.get("escalate_only", True)),
            }
        )
    return {
        "present": True,
        "per_axis": per_axis,
        "pmids": pmids,
        "discordant_axes": discordant,
        "n_findings": n_findings,
    }


# --- panel assembly + citation surface --------------------------------------------------------------
def assemble(
    pkg_path: str,
    risk_path: Optional[str],
    dossier_path: Optional[str],
    modality: str,
    substrate: Optional[dict] = None,
) -> dict:
    """Assemble the panel + citation surface the two LLM calls reason over. READ-ONLY consumer:
    parses the target-profile evidence_package + optional target-intrinsic dossier + optional 6-dim
    risk read; never modifies any emitting skill."""
    pkg = json.loads(Path(pkg_path).read_text())
    syn = pkg.get("synthesis") or {}
    sv = syn.get("sub_verdicts") or {}
    conviction = {k: _sv_verdict(sv, k) for k in sv}
    card_ids = {c.get("card_id") for c in pkg.get("cards", []) if isinstance(c, dict)}

    # target-intrinsic dossier (indication-INDEPENDENT target biology). Optional.
    #
    # TWO SHAPES are accepted, because the dossier arrives two ways and reading only one made the
    # degradation cap fire on the path production actually takes. A STANDALONE fan-out `decision.json`
    # carries `headline`. A target-profile run instead composes target_intrinsic INTO the profile and
    # writes `subskills/target_intrinsic/package.json` — same biology, no `headline`, content in
    # `claim_vector` + `key_signals`. Reading only the first shape meant every default-on chain run
    # reported `degraded inputs: ['dossier']` and capped certainty `low`, making the scalar a panel-wide
    # CONSTANT on live packages — the same undiscriminating-by-construction failure the independence cap
    # had, arriving by a different route.
    dossier, dossier_fields, dossier_present = {}, set(), False
    if dossier_path and Path(dossier_path).exists():
        dd = json.loads(Path(dossier_path).read_text())
        if dd.get("headline"):
            dossier = {k: _uv(v) for k, v in dd["headline"].items() if k not in ("cards_available", "cards_missing")}
        elif dd.get("sub_skill"):
            cv = dd.get("claim_vector") or {}
            dossier = {k: _uv(v) for k, v in cv.items() if not k.startswith("_")}
            ks = dd.get("key_signals") or {}
            for k in ("headline", "supports", "caveat"):
                if ks.get(k):
                    dossier[f"key_signals.{k}"] = _uv(ks[k])
        dossier_fields = set(dossier.keys())
        card_ids |= {c.get("card_id") for c in dd.get("cards", []) if isinstance(c, dict)}
        # presence is EARNED, not asserted by the file existing. An unreadable or empty dossier that set
        # `present=True` would LIFT the degradation cap while contributing no citable field — fail-open.
        dossier_present = bool(dossier)

    rule_ids: set = set()
    for v in sv.values():
        if isinstance(v, dict):
            rule_ids.update(v.get("fired_rule_ids") or [])
            if v.get("driving_rule_id"):
                rule_ids.add(v["driving_rule_id"])

    # 6-dim risk read (retrieval-grounded). Optional. allowed_pmids = the retrieved set.
    risk, allowed_pmids, risk_present = {}, set(), False
    if risk_path and Path(risk_path).exists():
        rd = json.loads(Path(risk_path).read_text()).get("dimensions", {})
        for dim, v in rd.items():
            risk[dim] = {
                "risk_level": v.get("risk_level"),
                "justification": v.get("justification"),
                "cited_pmids": v.get("cited_pmids", []),
            }
            allowed_pmids.update(str(p) for p in v.get("cited_pmids", []))
        risk_present = True

    subtype = parse_subtype_resolved(pkg)
    substrate_ind = substrate_independence(pkg)

    # per-subskill GROUNDED SUBSTRATE (the design-correct literature path). Its cited PMIDs join
    # the citation surface so a hypothesis clause may cite grounded literature and stay TRACEABLE;
    # the findings ride the panel (below) for the LLM to reason over. Escalate-only: they never touch
    # the deterministic ceiling (computed downstream purely from the package hard_gates).
    grounded = parse_grounded_substrate(substrate)
    allowed_pmids |= grounded["pmids"]

    ctx = pkg.get("context", {})
    # verdict-INERT DECISION FACETS (synthesis.decision_facets, stamped by the spine — #744): the
    # spine's authoritative cross-gate correlation + flip-fragility + competitor cross-ref. Surfaced for
    # the panel + the evidence_independence record; NEVER touches the deterministic ceiling.
    decision_facets = syn.get("decision_facets") or {}
    return {
        "pkg": pkg,
        "conviction": conviction,
        "risk": risk,
        "context": ctx,
        "dossier": dossier,
        "subtype": subtype,
        "substrate": substrate_ind,
        "grounded_substrate": grounded,
        "grounded_substrate_present": grounded["present"],
        "dossier_present": dossier_present,
        "risk_present": risk_present,
        "modality": modality,
        # the spine's authoritative cross-gate shared-evidence view (which gate verdicts share an input
        # card = correlated, not independent corroboration), the flip-fragility facet, and the competitor
        # cross-ref — all verdict-inert (P4/P5).
        "cross_gate_shared_evidence": decision_facets.get("cross_gate_shared_evidence") or {},
        "fragility_facet": decision_facets.get("fragility") or {},
        "competitor_crossref": decision_facets.get("competitor_crossref") or {},
        # factored-record consumers (M4): per-modality favorability + over-precision audit.
        "modality_fit_by_channel": decision_facets.get("modality_fit_by_channel") or {},
        "magnitude_borderline": decision_facets.get("magnitude_borderline") or [],
        # Stage 2a: per-short claim_vector (+ key_signals) with CITABLE evidence atoms, surfaced from
        # synthesis.claim_vectors — the SIGNAL decomposition the panel reasons over (not just the
        # verdict label). Each atom's cite.card_id is already in citation_surface.card_ids (the card is
        # in the package), so a clause citing it stays TRACEABLE without widening the surface.
        "claim_vectors": syn.get("claim_vectors") or {},
        "citation_surface": {
            "card_ids": {c for c in card_ids if c},
            "sub_verdicts": set(sv.keys()),
            "rule_ids": rule_ids,
            "pmids": allowed_pmids,
            "dossier_fields": dossier_fields,
            "strata": set(subtype["stratum_tokens"]),
        },
        "cards_brief": {
            c.get("card_id"): _uv(c.get("interpretation_call"))
            for c in pkg.get("cards", [])
            if isinstance(c, dict) and c.get("card_id")
        },
    }
