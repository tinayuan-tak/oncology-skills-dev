#!/usr/bin/env python3
"""target-intrinsic — the INDICATION-INDEPENDENT target dossier.

Answers "what do we know about target X, independent of any cancer?" — the facts true of the
PROTEIN/GENE regardless of indication: identity, on-target-safety genetics, protein-class /
structure / modality biophysics, functional annotation (GO), mechanism + pathway role (composed
signaling network / Reactome), interactome (STRING / CORUM / BioGRID), domain architecture +
domain→modality implication, and paralog buffering — the `tier: target` cards. Pan-cancer DISEASE
observations (tumor elevation, dependency, mutation frequency, PRISM, cell-line abundance) are
DELIBERATELY EXCLUDED: they are aggregated cancer behavior, owned by the disease-context subskills.

DESCRIPTIVE, not nominating (verdict_fn=None): a target's therapeutic value is indication-conditioned,
so target-intrinsic evidence informs confidence/context but never mints a recommendation. Invoked with
--target ALONE; the shared dispatcher makes --indication optional and passes a pan-cancer sentinel that
these tier:target readers ignore.

See SKILL.md for the full rationale, card roster, and how this skill composes into target-profile.
The CARDS list below is the single source of truth for the live-wired roster (grouped by sub-axis).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import TARGET_INTRINSIC as _LENS
from _skills_common import get_card_field
from _skills_common.target_intrinsic_claims import (
    target_intrinsic_claim_vector, target_intrinsic_key_signals)
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_DESCRIPTIVE
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group VALUE→TIER map (VERDICT-INERT; feeds ONLY the --figures subgroup-signal panel,
# never the spine / claim_vector / narrator). Stated for target-intrinsic's OWN LIVE card vocabulary so a
# positive signal is not silently flipped to `absent` by the lens-blind default_classify substring
# heuristic (make_value_classifier docstring); any value the map omits still degrades to that default.
# Keys are the ACTUAL emitted class tokens (the prior map keyed on tokens no method emits —
# partially_annotated / poorly_annotated / moderately_characterized / connector / peripheral /
# degrader_required / curated_domain / bare-`surface` — so those live classes fell through to the
# default, which flips e.g. connected / removal_favored / kinase_surface to `absent`). MODALITY routing
# tiers MIRROR target_intrinsic_claims._MODALITY_SIGNAL (the claim_vector the narrator sees).
_TARGET_INTRINSIC_VALUE_TIERS = {
    # annotation / characterization density (GO annotation_class, signaling network_class, reactome
    # pathway_class) — a heavily-curated target is better-ANNOTATED, not better biology (disclaimed).
    "well_annotated": "strong", "well_characterized": "strong",
    "partial": "moderate", "sparse": "weak",
    # interactome hubness (ppi-interactome interactome_class); "sparse" tiered above
    "hub": "strong", "connected": "moderate",
    # Pharos/IDG development level (TDL) — drug-development PRECEDENT (Tdark = understudied, not adverse)
    "Tclin": "strong", "Tchem": "moderate", "Tbio": "weak", "Tdark": "absent",
    # domain→modality routing (domain-modality-relevance) — MIRRORS _MODALITY_SIGNAL (call conviction)
    "removal_required_scaffolding": "strong", "removal_favored": "moderate",
    "inhibitor_sufficient": "moderate", "context_dependent": "weak", "indeterminate": "absent",
    # UniProt curated domain architecture (protein-domains-class protein_features_class)
    "multi_domain": "strong", "single_domain": "moderate", "no_curated_domain": "absent",
    # surfaceome family (surfaceome-family-classification family_class) — a surface-confirmed family is a
    # positive modality-routing determinant; the honest non-surface token carries no surface route.
    "kinase_surface": "strong", "enzyme_surface": "strong", "transporter": "strong",
    "cd_molecule": "strong", "adhesion": "strong", "gpcr": "strong",
    "growth_factor_receptor": "strong", "immune_receptor": "strong", "other_surface": "strong",
    "not_surface": "absent",
}


SKILL_NAME = "target-intrinsic"
SKILL_VERSION = "1.5.1"   # 1.5.1 (2026-09-02): _TARGET_INTRINSIC_VALUE_TIERS aligned to live card vocab (dead keys removed; positive subgroup signals no longer flip to `absent`). Verdict-INERT (subgroup --figures only).   # 1.4.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.   # 1.3.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # stamped into provenance.yaml — MUST equal SKILL.md metadata.version

CARDS = [
    # STRICT MOLECULAR-INTRINSIC only: properties true of the MOLECULE (protein/gene), independent of
    # any cancer. Pan-cancer disease observations (tumor elevation, dependency, mutation frequency,
    # PRISM, cell-line abundance) are excluded — they belong to the disease-context subskills.
    # --- IDENTITY ------------------------------------------------------------------------------
    "target-identity-summary",           # canonical id, family, aliases
    # --- GERMLINE GENETICS & CONSTRAINT (properties of the GENE; the on-target-safety axis) -----
    "gnomad-lof-constraint",             # germline LoF intolerance (pLI/LOEUF)
    "gene-burden-safety",                # rare-variant burden safety signal
    "clingen-dosage",                    # ClinGen haploinsufficiency / triplosensitivity
    "clinvar-pathogenicity-safety",      # germline pathogenic-variant burden
    "mouse-ko-phenotype",                # IMPC mouse-KO lethal/developmental phenotypes
    "target-safety-prioritisation",      # OT composite prioritisation score. ORIENTATION-ONLY (verdict-inert):
                                         # its SAFETY dimension overlaps gnomad-lof-constraint + mouse-ko-phenotype
                                         # (the dedicated cards); retained for its tractability/precedence dimensions,
                                         # not read as a standalone safety fact.
    # --- PROTEIN CLASS / STRUCTURE / BIOPHYSICS (properties of the PROTEIN) ---------------------
    "surfaceome-family-classification",  # surface protein family + membership (protein-class proxy)
    "structure-features-static",         # fold / pockets / ligandability (structure-intrinsic)
    "shed-ectodomain-liability",         # circulating soluble ectodomain (biophysical property)
    # --- FUNCTIONAL ANNOTATION (Gene Ontology: what it does / where it is / what processes) -----
    "gene-ontology-annotation",          # GO BP/MF/CC term membership (experimental-evidence-flagged)
    # --- MECHANISM / PATHWAY ROLE (the molecule's place in signaling) ---------------------------
    "signaling-network-mechanism",       # composed directed network (SIGNOR / CollecTRI / Reactome) + MoA class
    "reactome-pathway-membership",       # Reactome pathway/geneset MEMBERSHIP + top-level rollup (distinct from directed edges above)
    # --- INTERACTOME (physical/functional interactions + complex membership) --------------------
    "ppi-interactome",                   # STRING functional network + CORUM complexes + BioGRID physical interactions
    # --- DOMAIN ARCHITECTURE / PROTEIN CLASS (curated UniProt features) --------------------------
    "protein-domains-class",             # FT DOMAIN architecture + UniProt-keyword protein class
    "target-development-level",          # Pharos/IDG TDL: druggability/novelty tier (Tclin/Tchem/Tbio/Tdark)
                                         # + family. Verdict-inert target-intrinsic facet.
    "measured-potency-tractability",     # ChEMBL/BindingDB measured potent-binder count + best potency —
                                         # the MEASURED chemical-matter dimension (tier:target). Borrowed from
                                         # tractability-small-molecule; verdict-inert intrinsic-druggability facet.
    "domain-modality-relevance",         # INTERPRETIVE domain→modality facet: inhibitor_sufficient vs
                                         # removal_required_scaffolding (e.g. RIPK1). tier:target, verdict-inert.
    # --- PARALOGS (gene-family redundancy — a genomic-intrinsic property) -----------------------
    "paralog-buffering",                 # sequence paralogs + buffering (dependency-hardening context)
    # --- NORMAL (non-disease) EXPRESSION --------------------------------------------------------
    "normal-tissue-liability",           # HPA normal-tissue protein breadth (baseline, non-tumor)
]

QUESTION = ("What is known about {target} INDEPENDENT of indication — its identity, on-target-safety "
            "genetics, protein-class/structure/modality biophysics, functional annotation, mechanism + "
            "pathway role, interactome, domain architecture + domain→modality implication, and paralog "
            "buffering?")


# Declarative dossier field-map: (headline_key, card_id, card_field), grouped by target-intrinsic
# sub-axis. This is the SINGLE SOURCE for both _headline AND the drift guard — the test AST-parses
# this table's card_ids, so a card added to CARDS but never surfaced here is caught structurally
# (target-intrinsic is descriptive: this table is the ONLY place a card's signal reaches output).
_HEADLINE_SPEC = [
    # identity
    ("target_symbol",                 "target-identity-summary",          "resolved_hgnc_symbol"),
    ("target_ensembl_id",             "target-identity-summary",          "resolved_ensembl_id"),
    # safety genetics
    ("gnomad_constraint_class",       "gnomad-lof-constraint",            "constraint_class"),
    ("clingen_dosage_class",          "clingen-dosage",                   "dosage_sensitivity_class"),
    ("clinvar_pathogenic_class",      "clinvar-pathogenicity-safety",     "clinvar_pathogenic_class"),
    ("gene_burden_safety_class",      "gene-burden-safety",               "burden_safety_class"),
    ("mouse_ko_phenotype_class",      "mouse-ko-phenotype",               "ko_phenotype_class"),
    # target-safety-prioritisation is ORIENTATION-ONLY (safety dim overlaps constraint + mouse-KO)
    ("target_safety_prioritisation",  "target-safety-prioritisation",     "prioritisation_status"),
    # protein class / structure / biophysics
    ("surface_protein_family",        "surfaceome-family-classification", "family_class"),
    ("is_surface_protein",            "surfaceome-family-classification", "is_surface_protein"),
    ("structure_pocket_call",         "structure-features-static",        "hotspot_pocket_adjacency_call"),
    # measured chemical matter (borrowed from tractability-small-molecule; intrinsic druggability)
    ("measured_bioactivity_class",    "measured-potency-tractability",    "measured_bioactivity_class"),
    ("chembl_n_potent_ligands",       "measured-potency-tractability",    "chembl_n_potent_ligands"),
    ("best_measured_potency_neglog_m","measured-potency-tractability",    "best_measured_potency_neglog_m"),
    ("shed_liability_class",          "shed-ectodomain-liability",        "shed_liability_class"),
    # functional annotation (Gene Ontology)
    ("go_annotation_class",           "gene-ontology-annotation",         "annotation_class"),
    ("go_n_terms_total",              "gene-ontology-annotation",         "n_go_terms_total"),
    ("go_n_biological_process",       "gene-ontology-annotation",         "n_biological_process"),
    ("go_n_molecular_function",       "gene-ontology-annotation",         "n_molecular_function"),
    ("go_n_cellular_component",       "gene-ontology-annotation",         "n_cellular_component"),
    # mechanism / pathway role
    ("network_class",                 "signaling-network-mechanism",      "network_class"),
    ("n_upstream_regulators",         "signaling-network-mechanism",      "n_upstream_regulators"),
    ("n_downstream_effectors",        "signaling-network-mechanism",      "n_downstream_effectors"),
    # pathway / geneset membership (Reactome)
    ("pathway_class",                 "reactome-pathway-membership",      "pathway_class"),
    ("pathway_count",                 "reactome-pathway-membership",      "pathway_count"),
    ("top_level_pathways",            "reactome-pathway-membership",      "top_level_pathways"),
    # domain architecture / protein class (UniProt curated)
    ("protein_features_class",        "protein-domains-class",            "protein_features_class"),
    ("n_domains",                     "protein-domains-class",            "n_domains"),
    ("domain_architecture",           "protein-domains-class",            "domain_architecture"),
    ("protein_class",                 "protein-domains-class",            "protein_class"),
    # Pharos/IDG Target Development Level — druggability/novelty tier (verdict-inert)
    ("tdl_class",                     "target-development-level",         "tdl_class"),
    ("tdl_target_family",             "target-development-level",         "target_family"),
    ("tdl_novelty_score",             "target-development-level",         "novelty_score"),
    # domain→modality implication (INTERPRETIVE sibling of protein-domains-class): inhibitor-sufficient
    # vs removal-required (degrader/scaffolding). Verdict-inert; the heuristic returns indeterminate for
    # a multi-domain enzyme, curated RIPK1 → removal_required_scaffolding.
    ("modality_implication_class",    "domain-modality-relevance",        "modality_implication_class"),
    ("modality_implication_basis",    "domain-modality-relevance",        "modality_implication_basis"),
    ("modality_scaffolding_function", "domain-modality-relevance",        "scaffolding_function"),
    ("modality_implication_context",  "domain-modality-relevance",        "modality_context"),
    # interactome (STRING functional network + CORUM complexes + BioGRID physical)
    ("interactome_class",             "ppi-interactome",                  "interactome_class"),
    ("n_high_confidence_interactors", "ppi-interactome",                  "n_high_confidence_interactors"),
    ("n_corum_complexes",             "ppi-interactome",                  "n_corum_complexes"),
    ("in_protein_complex",            "ppi-interactome",                  "in_protein_complex"),
    # paralogs (gene-family redundancy)
    ("paralog_buffering_class",       "paralog-buffering",                "paralog_buffering_class"),
    ("n_paralogs_annotated",          "paralog-buffering",                "n_paralogs_annotated"),
    ("strongest_paralog_symbol",      "paralog-buffering",                "strongest_paralog_symbol"),
    # normal (non-disease) expression
    ("normal_tissue_breadth_class",   "normal-tissue-liability",          "normal_tissue_breadth_class"),
]


# ── canonical HEADLINE block (verdict + confidence + top tension) — DESCRIPTIVE MODE ─────────────
# target-intrinsic is GATELESS (verdict_fn=None), so there is no gate verdict to headline. The shared
# headline_core builder supports a DESCRIPTIVE MODE (verdict_token=None + descriptive_phrase): the block
# stays well-formed — verdict.call=None, verdict.phrase=the deterministic dominant-signal summary,
# polarity="neutral" — so this descriptive lens gets the SAME verdict+confidence+top-tension shape as a
# gated skill. Confidence is weakest-link over the claim_vector's MODALITY_ROUTING / TRACTABILITY_
# PRECEDENT corroboration; both are critical axes. Verdict-INERT: a one-way projection over the
# already-computed claim_vector / key_signals — it never mints a call (there is none).
_TARGET_INTRINSIC_HEADLINE_SPEC = HeadlineSpec(
    gate="target_intrinsic",
    axis_labels={"MODALITY_ROUTING": "domain→modality implication",
                 "TRACTABILITY_PRECEDENT": "Pharos/IDG development level"},
    axis_keys=("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"),
    critical_axes=("MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"),
    # No verdict_label (descriptive — no verdict token to phrase); no cross-cutting tension source beyond
    # the claim_vector conflicts + key_signals caveat.
    tension_extra=None,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed target-intrinsic headline, in
    DESCRIPTIVE MODE (verdict_token=None). The descriptive_phrase is the deterministic dominant-signal
    summary (key_signals.headline); polarity defaults to neutral. Verdict-inert — target-intrinsic mints
    no verdict, so this carries the confidence + top-tension shape without a gate call."""
    ks = headline.get("key_signals") or {}
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_TARGET_INTRINSIC_HEADLINE_SPEC, verdict_token=None,
                          descriptive_phrase=ks.get("headline"))


def _headline(cards, fired, verdict_pair):
    """Descriptive target dossier — one field per target-intrinsic sub-axis, built from the declarative
    _HEADLINE_SPEC table. No verdict spine (verdict_fn=None): target-intrinsic evidence informs
    confidence/context, never a nomination (indication-conditioned). A composed consumer reads these
    as target-grain context."""
    hl = {key: get_card_field(cards, cid, field) for key, cid, field in _HEADLINE_SPEC}
    # verdict-INERT claim-vector projection (10th concrete) — the two target-intrinsic fields that carry
    # a defensible signal (MODALITY_ROUTING / TRACTABILITY_PRECEDENT), the most relevant to hypothesis +
    # modality fit. Both source cards are in the composer entry, so this populates in the COMPOSED profile.
    hl["claim_vector"] = target_intrinsic_claim_vector(hl, cards)
    hl["key_signals"] = target_intrinsic_key_signals(hl, cards)
    # Canonical HEADLINE block (DESCRIPTIVE MODE — no gate verdict): a verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort (a formatting/read fault must NEVER discard the
    # descriptive dossier already built in `hl`, mirroring the fleet's degrade-on-exception discipline).
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — target-intrinsic is a GATELESS DESCRIPTIVE
    # dossier (indication-independent; no verdict), so role=descriptive + verdict=None → call=None,
    # polarity=not_scored; the reader-useful content is the honest_phrase + claim_chips. Best-effort +
    # verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the dossier
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
    return hl


def _synthesis_facet(cards, fired, verdict_pair=None):
    """Compact, VERDICT-INERT target-intrinsic facet for the composed synthesis. SELF-CONTAINED — reads
    ONLY the two claim-axis cards (domain-modality-relevance, target-development-level), both in this
    skill's composer entry, and does NOT call _headline (whose _HEADLINE_SPEC reads 12 cards HOME'd under
    other subskills, absent from this entry by design). Carries the descriptive claim_vector + its citable
    atoms + the two class fields. target-intrinsic is gateless (verdict_fn=None) — this never moves a verdict."""
    cv = target_intrinsic_claim_vector({}, cards)
    ks = target_intrinsic_key_signals({}, cards)
    facet = {
        "modality_implication_class": get_card_field(cards, "domain-modality-relevance", "modality_implication_class"),
        "tdl_class": get_card_field(cards, "target-development-level", "tdl_class"),
        "claim_vector": cv, "key_signals": ks,
        "_facet_note": ("Deterministic target-intrinsic facet; claim_vector is a DESCRIPTIVE modality-routing "
                        "+ tractability-precedent projection (direction/meaning in the atoms). Gateless — no verdict."),
    }
    # Canonical HEADLINE block (DESCRIPTIVE MODE) — flows to the composed fan-out IDENTICALLY to
    # claim_vector / key_signals (this facet is target-intrinsic's fan-out carrier — the skill exposes NO
    # _SYNTHESIS_FACET_KEYS tuple). Built from THIS facet's self-contained cv/ks (not _headline, which
    # reads cards HOME'd under other subskills, absent from the composer entry). Best-effort / verdict-inert.
    try:
        facet["headline_block"] = _build_headline_block(facet)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the facet
        facet.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        facet["headline_block"] = None
    # UNIFIED skill_report on the FACET (docs/UNIFIED_OUTPUT_CONTRACT.md). target-intrinsic exposes NO
    # _SYNTHESIS_FACET_KEYS tuple — this self-contained facet dict IS its fan-out carrier — so skill_report
    # must be assembled HERE (from the facet's own cv / headline_block) to reach the composed profile, in
    # addition to the _headline path used by the standalone decision. Gateless DESCRIPTIVE → call=None,
    # polarity=not_scored. Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        facet["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,
            headline_block=facet.get("headline_block"),
            claim_vector=facet.get("claim_vector"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the facet
        facet.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        facet["skill_report"] = None
    return facet


def _emit_skill_figures(decision, figures_root):
    """Skill-level graphics (opt-in --figures): the canonical headline hero (descriptive dominant-signal
    phrase · confidence · top tension). Additive / display-only; offline (reads only
    decision['headline']['headline_block'])."""
    return emit_headline_hero(decision, figures_root)


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",   # rules axis for loading; target-intrinsic emits no verdict
        question=QUESTION,
        verdict_fn=None,                   # DESCRIPTIVE dossier — no nomination (indication-conditioned)
        headline_fn=_headline,
        # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
        synthesize_fn=make_synthesize_fn(_LENS),
        # Skill-level graphics (opt-in --figures): the canonical headline hero (descriptive mode).
        # Additive / display-only; the descriptive dossier is byte-stable without it.
        skill_figures_fn=_emit_skill_figures,
        # Signals-first: tuned sub-group reader for the target-intrinsic vocabulary. Verdict-INERT.
        subgroup_classify=make_value_classifier(_TARGET_INTRINSIC_VALUE_TIERS),
    ))
