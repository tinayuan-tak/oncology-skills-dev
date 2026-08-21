#!/usr/bin/env python3
"""mechanism-and-pharmacology — Phase-D wired skill (graduated 2026-07-08).

Signaling-network mechanism + candidate MoA hooks + PD-marker suggestions.
Consumes the signaling-network-mechanism card (a directed network composed
from SIGNOR + CollecTRI + Reactome, classified into a 21-class MoA ontology).
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
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.resolver import resolve_or_raise
from _skills_common.mechanism_claims import mechanism_claim_vector, mechanism_key_signals
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero


SKILL_NAME = "mechanism-and-pharmacology"
SKILL_VERSION = "1.6.1"                       # stamped into provenance.yaml — MUST equal SKILL.md metadata.version
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
    "pathway-activity-context",                 # Track PROGENy (2026-08-10): per-indication PROGENy
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
]

QUESTION = ("For {target} in {indication}, what upstream regulators + "
            "downstream effectors are catalogued in SIGNOR, and which MoA "
            "classes are candidate hooks for SM / degrader / molecular-glue "
            "programs?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (2026-07-20).
    The former if-chain now lives in resolvers/mechanism.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "mechanism")

# --- dependency-predictability feature-attribution facet (verdict-inert) ---------------------------
# feature_class -> the prefix its `feature` name carries a PARTNER gene symbol under. These cross-gene
# omics classes are mechanistically interpretable AND name a single partner gene we can cross-reference
# against the SIGNOR partner set. (Reader emits feature names like "expr_EDA2R", "cn_NLK", "ms_SPINT2".)
_PARTNER_FEATURE_PREFIX = {
    "cross_gene_expression":  "expr_",
    "cross_gene_copy_number": "cn_",
    "ms_protein":             "ms_",
    "rppa_protein":           "rppa_",
    "paralog_dep":            "paralog_dep_",
    "methylation_tss":        "methyl_",
}
# own_* features = the TARGET's OWN omics predict its own dependency (self-driven, e.g. KRAS->own hotspot):
# mechanistically meaningful but NOT a partner — surfaced separately as pred_self_driven.
_SELF_FEATURE_CLASSES = {"own_expression", "own_copy_number", "own_mut_hotspot", "own_mut_damaging"}
# Everything else (arm_level_cn, lineage, mol_signature, metabolomics, msi_status, oncokb_gof/lof,
# fusion, sv_gene) names no single mechanistic partner gene → dropped from the mechanism lens.


def _predictability_mechanism_facet(cards):
    """VERDICT-INERT facet: DepMap dependency-predictability feature attribution as a DATA-DRIVEN
    complement to the curated SIGNOR network.

    The predictability model's top features (genome-wide omics that best predict the target's Chronos
    dependency) are candidate mechanistic co-dependencies. We keep only the mechanistically-plausible,
    partner-gene-bearing feature classes and cross-reference each partner gene against SIGNOR's
    upstream/downstream partner symbols: overlap = curated+empirical CONVERGENCE (a stronger MoA/PD-marker
    hypothesis); a predictive partner ABSENT from SIGNOR = a data-driven hypothesis the curated network
    does not yet capture. NOTE: importance is RF-impurity / XGB-gain (NOT SHAP; see the predictability
    manifest) and CORRELATIONAL, not causal — hypothesis-generating only. Feeds NO resolver."""
    pclass   = get_card_field(cards, "dependency-predictability", "predictability_class")
    dom_class = get_card_field(cards, "dependency-predictability", "pred_dominant_feature_class")
    top_rf   = get_card_field(cards, "dependency-predictability", "pred_top_features_rf") or []

    # SIGNOR partner symbol set (upstream regulators + downstream effectors). The reader emits the
    # per-edge key `partner_gene_symbol`; the card doc calls it `partner_symbol` — read both defensively.
    signor_partners = set()
    for key in ("upstream_regulators", "downstream_effectors"):
        edges = get_card_field(cards, "signaling-network-mechanism", key)
        if not isinstance(edges, list):
            continue   # frozen-fixture placeholder string, or field absent -> no partner symbols to x-ref
        for e in edges:
            if isinstance(e, dict):
                sym = e.get("partner_gene_symbol") or e.get("partner_symbol")
            elif isinstance(e, str):
                sym = e   # some emitters carry a bare partner symbol string
            else:
                sym = None
            if sym:
                signor_partners.add(str(sym).upper())

    partner_features = []
    for f in top_rf:
        prefix = _PARTNER_FEATURE_PREFIX.get((f or {}).get("feature_class"))
        if not prefix:
            continue                                   # self (own_*) or confounder — not a partner feature
        name = f.get("feature") or ""
        gene = name[len(prefix):] if name.startswith(prefix) else name
        partner_features.append({
            "gene":          gene,
            "feature_class": f.get("feature_class"),
            "importance":    f.get("importance"),
            "in_signor":     gene.upper() in signor_partners,
        })
    corroborated = [pf["gene"] for pf in partner_features if pf["in_signor"]]
    return {
        "pred_predictability_class":         pclass,
        "pred_dominant_feature_class":       dom_class,
        "pred_self_driven":                  dom_class in _SELF_FEATURE_CLASSES,
        "pred_mechanistic_partner_features": partner_features[:10],
        "pred_signor_corroborated_partners": corroborated,
        "pred_n_signor_corroborated":        len(corroborated),
    }


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# mechanism-and-pharmacology's declaration for the shared headline_core builder. This skill is largely
# DESCRIPTIVE: the mechanism_verdict is a signaling-network CHARACTERIZATION class (well_characterized /
# partial / sparse / has_pd_marker / data_unavailable / insufficient), and — per mechanism_claims.py —
# NETWORK is ANNOTATION DENSITY (SIGNOR/Reactome edge count = curation, NOT target biology, capped at
# moderate). So none of these rungs is a favorable/unfavorable target-quality CALL; every rung is coloured
# NEUTRAL (there is no clear positive/negative program signal to encode). Verdict-INERT — a one-way
# projection over the already-computed headline (mechanism_verdict stays byte-stable, frozen by the
# EGFR/CEACAM5 replay guard).

# The mechanism.resolver verdict vocabulary → human phrase (prettify fallback for any future addition).
_MECHANISM_VERDICT_PHRASE = {
    "well_characterized": "Well-characterized signaling network",
    "partial":            "Partially-characterized signaling network",
    "sparse":             "Sparse signaling network",
    "has_pd_marker":      "PD-marker candidate present",
    "data_unavailable":   "Data unavailable",
    "insufficient":       "Insufficient evidence",
}


def _mechanism_verdict_polarity(v) -> str:
    """The skill's OWN reading of the mechanism verdict (colours the hero badge; never a gate). This skill
    is DESCRIPTIVE — the verdict is a network-characterization / annotation-density class, NOT a
    favorable/unfavorable target call — so every rung is NEUTRAL (a richly-curated network is not a better
    TARGET, just a better-annotated one; the honesty cap in mechanism_claims.py)."""
    return "neutral"


_MECHANISM_HEADLINE_SPEC = HeadlineSpec(
    gate="mechanism",
    axis_labels={"NETWORK": "signaling-network topology", "PHOSPHO": "phospho-activity",
                 "PATHWAY": "pathway activity context", "PERTURBATION": "drug-perturbation engagement",
                 "PREDICTABILITY": "dependency predictability"},
    axis_keys=("NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"),
    critical_axes=("NETWORK",),   # NETWORK (is there a catalogued signaling network?) is the axis the
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
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_MECHANISM_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_mechanism_verdict_polarity(v))


def _emit_skill_figures(decision, figures_root):
    """--figures emitter: the canonical headline hero (verdict · confidence · top tension). Additive /
    display-only, offline, best-effort (missing block → [], spine unaffected)."""
    return emit_headline_hero(decision, figures_root)


def _headline(cards, fired, verdict_pair):
    """Skill-specific headline: SIGNOR-network descriptive fields + verdict-inert facets."""
    v, drv = verdict_pair or ("insufficient", None)
    headline = {
        "mechanism_verdict":         v,
        "driving_rule_id":           drv,
        "network_class":             get_card_field(cards, "signaling-network-mechanism",
                                          "network_class"),
        "n_upstream_regulators":     get_card_field(cards, "signaling-network-mechanism",
                                          "n_upstream_regulators"),
        "n_downstream_effectors":    get_card_field(cards, "signaling-network-mechanism",
                                          "n_downstream_effectors"),
        "moa_classes_present":       get_card_field(cards, "signaling-network-mechanism",
                                          "moa_classes_present"),
        "pd_marker_classes_present": get_card_field(cards, "signaling-network-mechanism",
                                          "pd_marker_classes_present"),
        "has_actionable_moa":        get_card_field(cards, "signaling-network-mechanism",
                                          "has_actionable_moa"),
        "has_pd_marker":             get_card_field(cards, "signaling-network-mechanism",
                                          "has_pd_marker"),
        "moa_ontology_version":      get_card_field(cards, "signaling-network-mechanism",
                                          "moa_ontology_version"),
        # Phospho ACTIVITY facet (re-homed 2026-08-05) — CPTAC phosphoproteomics signaling-state
        # readout. Display-only (feeds no resolver); enriches the mechanism picture for kinases/
        # signaling nodes. data_unavailable for indications with no CPTAC cohort or non-phosphoproteins.
        "phospho_activity_class":    get_card_field(cards, "phospho-pathway-activity",
                                          "phospho_activity_class"),
        "n_phosphosites":            get_card_field(cards, "phospho-pathway-activity",
                                          "n_phosphosites"),
        "max_site_detection_fraction": get_card_field(cards, "phospho-pathway-activity",
                                          "max_site_detection_fraction"),
        # Tahoe single-cell drug-perturbation MoA facet (added 2026-08-10) — which drugs move the
        # target's expression, in how many cancer lines. Display-only (feeds no resolver); a
        # target-ENGAGEMENT / MoA lens (engagement != dependency, per the Pilot-2 backtest).
        "tahoe_perturbation_class":  get_card_field(cards, "tahoe-drug-perturbation",
                                          "tahoe_perturbation_class"),
        "tahoe_n_perturbing_drugs":  get_card_field(cards, "tahoe-drug-perturbation",
                                          "n_perturbing_drugs"),
        "tahoe_strongest_mover_drug": get_card_field(cards, "tahoe-drug-perturbation",
                                          "strongest_mover_drug"),
        "tahoe_strongest_mover_log2fc": get_card_field(cards, "tahoe-drug-perturbation",
                                          "strongest_mover_log2fc"),
        "tahoe_top_suppressing_drugs": get_card_field(cards, "tahoe-drug-perturbation",
                                          "top_suppressing_drugs"),
        "tahoe_top_inducing_drugs":  get_card_field(cards, "tahoe-drug-perturbation",
                                          "top_inducing_drugs"),
    }
    # Predictability feature-attribution facet (verdict-inert; SIGNOR-cross-referenced).
    headline.update(_predictability_mechanism_facet(cards))
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
    return headline


_SYNTHESIS_FACET_KEYS = (
    "mechanism_verdict", "driving_rule_id", "network_class", "has_actionable_moa",
    "phospho_activity_class", "pathway_activity_class", "tahoe_perturbation_class",
    "pred_predictability_class", "claim_vector", "key_signals",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT mechanism facet for the composed target-profile synthesis. Reuses _headline
    (single source) + returns the mechanism claim_vector (NETWORK/PHOSPHO/PATHWAY/PERTURBATION/
    PREDICTABILITY) + its citable atoms. Never moves the verdict (owned by the mechanism resolver, which
    keys only on signaling-network-mechanism); safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    # pathway_activity_class is not lifted into _headline; surface it here from the card for the facet key
    h.setdefault("pathway_activity_class", get_card_field(cards, "pathway-activity-context", "pathway_activity_class"))
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic mechanism-and-pharmacology facet; claim_vector is MOSTLY "
                            "DESCRIPTIVE (NETWORK = annotation density, capped moderate; PHOSPHO the real "
                            "signal; PERTURBATION = engagement not dependency). Verdict owned by the resolver.")
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
        isoform_check_target=True,          # warn on p95HER2 / AR-V7 / etc.
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
    ))
