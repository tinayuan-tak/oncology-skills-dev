#!/usr/bin/env python3
"""target-profile — composed target profile with Tier-3 LLM narrative synthesis.

Fans out to the 10 question-answering sub-skills in SUB_SKILLS (tumor-presence,
tumor-selectivity, functional-requirement, synthetic-lethal-partners, mechanism-
and-pharmacology, genomic-alteration-profile, differentiation-landscape,
tractability-small-molecule, surface-modality-fit, on-target-safety-liability)
+ an opt-in subtype_fit tier (--subtypes), collects their sub-verdicts + fired
rules, then invokes Bedrock (via _skills_common.llm) with a forced structured
tool_use to produce executive_summary + tension_analysis + recommendation. The
LLM's overall_recommendation is CLAMPED by the deterministic one-directional
nomination gate. Emits target_profile.md + nomination.json + provenance.

Each sub-skill is scoped to its OWN SUB_SKILL_CARDS entry (card_id_filter), so a
card must be in a sub-skill's entry to be seen by THAT sub-skill's verdict — a
card composed only under another sub-skill is invisible here (the resolver-
dependency completeness guard in tests/ enforces this).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# PERF Stage 2: fan-out thread-pool worker cap. min(#sub-skills, cores-2) — headroom-aware; env
# override for tuning/CI. Threads (not processes) so the process-global method caches are shared.
_FANOUT_MAX_WORKERS = int(os.environ.get("TARGET_PROFILE_FANOUT_WORKERS",
                                          max(2, (os.cpu_count() or 4) - 2)))

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import (
    EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE,
    resolve_cards, fired_rules, modality_lens,
    synthesize_structured, render_composite_panel,
)
from _skills_common import ordinal_view
from _skills_common.rules_loader import load_interpretation_rules
from _skills_common.flip_analysis import flip_analysis
from _skills_common.envelope import build_governance  # Phase-D convergence: single-source the governance block
from _skills_common.compose_core import subskill_composition  # Stage 1b: typed sub-verdict carrier
from _skills_common.card_preprocessors import preprocess_cards_for_gate  # G1: per-gate pre-fired_rules card correction (e.g. genomic FDR)

SKILL_NAME = "target-profile"
SKILL_VERSION = "1.0.0"


def _framework_model_version() -> str | None:
    """The DECLARED framework model pin (governance item B). Read from the single
    source-of-truth constant in the bedrock client. Graceful None on import failure —
    provenance simply omits it rather than crashing the run (conservative fallback)."""
    try:
        from _skills_common.bedrock_client import FRAMEWORK_MODEL_VERSION
        return FRAMEWORK_MODEL_VERSION
    except Exception:  # noqa: BLE001
        return None


# --- Sub-skill orchestration ------------------------------------------------

_SUBSKILL_FN_CACHE: dict = {}


def _load_sub_skill_verdict_fn(skill_dir_name: str) -> Any:
    """Load a sub-skill's run.py module and return its `_verdict()` or
    `_snapshot()` function (whichever exists). Sub-skills follow the
    convention of exposing one such function; we grab it via importlib
    so target-profile doesn't hard-code each sub-skill's Python path.

    MEMOIZED (perf Stage 2): each sub-skill module is exec'd ONCE. This both avoids
    re-executing modules per call AND makes the concurrent fan-out safe — the pool
    workers hit the cache (populated by _prewarm_sub_skill_imports before the pool),
    so no two threads run importlib.exec_module / sys.path.insert concurrently.
    """
    fn = _SUBSKILL_FN_CACHE.get(skill_dir_name, "__miss__")
    if fn != "__miss__":
        return fn
    run_py = SKILLS_DIR / skill_dir_name / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location(
        f"_subskill_{skill_dir_name.replace('-', '_')}", run_py,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "_verdict", None) or getattr(module, "_snapshot", None)
    _SUBSKILL_FN_CACHE[skill_dir_name] = fn
    return fn


def _prewarm_sub_skill_imports() -> None:
    """Perf Stage 2 byte-stability guard: single-threaded, BEFORE the thread pool, trigger every
    import the concurrent workers would otherwise race on — the compose-dashboard dispatcher (via
    resolve_cards' _import_dispatcher) and each sub-skill's verdict module (which does sys.path.insert
    + importlib.exec_module). After this, the workers hit warm module caches; no concurrent
    sys.path mutation / module exec. Idempotent + best-effort (a load failure surfaces later on the
    real call, exactly as serial)."""
    try:
        from _skills_common import resolve_cards as _rc  # noqa: F401 — triggers _import_dispatcher
    except Exception:  # noqa: BLE001
        pass
    for skill_dir, _short in SUB_SKILLS:
        try:
            _load_sub_skill_verdict_fn(skill_dir)   # populates _SUBSKILL_FN_CACHE
        except Exception:  # noqa: BLE001
            pass


# The wired question-answering skills to compose. Order matches phase A→K.
# RESTRUCTURED 2026-07-14 (scope deep-dive):
#   - tractability-and-modality SPLIT → tractability-small-molecule (SM
#     chemical-genetic verdict) + surface-modality-fit (biologics-modality call
#     the old skill only displayed).
#   - mutation-profile REFRAMED → genomic-alteration-profile (SNV + copy-number
#     + fusion [LIVE, additive signal-only]).
#   - patient-population-and-access DELETED (thin re-projection of the
#     mutation-hotspot-frequency card; its prevalence fields folded into
#     genomic-alteration-profile).
#   - surfaceome-cohort-ranking DROPPED from the fan-out (per-indication scan,
#     not a per-target question-skill; its cohort_rank_class is now covered
#     inside surface-modality-fit). The scan skill still exists as a utility.
SUB_SKILLS = [
    ("tumor-presence",                 "expression"),
    ("tumor-selectivity",              "selectivity"),
    ("functional-requirement",         "dependency"),
    ("synthetic-lethal-partners",      "synthetic_lethal_partners"),  # gate-C SL veto-suppressor input (curated SynLethDB)
    ("combinatorial-dependency",       "combinatorial_dependency"),   # MEASURED dual-KO SL complement (DepMap ParalogV2 + published GI). ADDITIVE: self-contained inline verdict, NO resolver gate → absent from _SHORT_TO_GATE (like `expression`), so it is surfaced in sub_verdicts + the LLM synthesis but does NOT drive the nomination spine (recommendation byte-stable). Thickens the single-source SynLethDB SL axis (2026-08-14 consolidation-fidelity follow-up).
    ("mechanism-and-pharmacology",     "mechanism"),
    ("genomic-alteration-profile",     "genomic_alteration"),  # reframed from mutation-profile
    ("differentiation-landscape",      "differentiation"),
    ("tractability-small-molecule",    "tractability_sm"),     # split (SM half)
    ("surface-modality-fit",           "surface_modality"),    # split (biologics half)
    ("on-target-safety-liability",     "safety"),
]

# Composed sub-skill SHORT name → resolver GATE name (resolvers/<gate>.resolver.yaml). Used by the
# verdict-inert FRAGILITY facet to run the flip scan on each axis's own resolver. Most shorts equal
# their gate; the two exceptions are explicit here: `tractability_sm`'s resolver is
# `tractability_small_molecule`, and `expression` (tumor-presence) has NO resolver gate — presence is
# verdict-inert for the nomination spine (no rung reads it), so it is intentionally absent and the
# fragility facet treats it as flip-inapplicable, not robust. A guard test pins that every mapped gate
# has a non-empty resolver_referenced_rule_ids and that the mapping matches each sub-skill's own
# resolve_verdict_for_gate call.
_SHORT_TO_GATE = {
    "selectivity": "selectivity",
    "dependency": "dependency",
    "synthetic_lethal_partners": "synthetic_lethal_partners",
    "mechanism": "mechanism",
    "genomic_alteration": "genomic_alteration",
    "differentiation": "differentiation",
    "tractability_sm": "tractability_small_molecule",
    "surface_modality": "surface_modality",
    "safety": "safety",
}

# Card set for each sub-skill (must match SKILL.md composition.cards_used).
# RESTRUCTURED 2026-07-14 — keys track the SUB_SKILLS renames above.
SUB_SKILL_CARDS = {
    "tumor-presence": [
        "cellline-rna-distribution",
        "tumor-rna-vs-adjacent",
        "tumor-protein-abundance-cptac",
        "cellline-protein-abundance",     # Gygi cell-line MS — cell_line_protein_abundance axis.
                                         # Added to tumor-presence/run.py CARDS in PR #80 but never
                                         # to this composer map → dropped from the composed profile.
                                         # Restored so the dual RNA+protein presence reaches the LLM.
        "tumor-elevation-breadth",       # pan-cancer K-of-N breadth (Slice B3) — same drift class:
                                         # added to tumor-presence CARDS but not this map, so it was
                                         # silently dropped from the composed profile. Restored.
        "tumor-rna-distribution", # Q1 (expression-extraction plan) — per-sample tumor RNA
                                         # distribution; added to tumor-presence CARDS + this composer
                                         # map together (composer-consistency guard).
        "tumor-rna-distribution-by-subtype",  # target_subtype-grain sibling — per-molecular-subtype
                                         # panorama (per_subgroup_metrics). Same pairing rule: wired into
                                         # tumor-presence CARDS + this composer map together.
        "expression-purity-confound",    # Q9 (2026-07-23) — purity-confound caveat; render facet.
        # phospho-pathway-activity RE-HOMED 2026-08-05 → the mechanism-and-pharmacology entry below
        # (activity/signaling-state, not presence). Kept in lockstep with its sub-skill CARDS.
        "cellline-rna-protein-concordance",       # Q5 (2026-07-23) — rna_as_biomarker; biomarker preferred_assay input.
        "tumor-scrna-celltype-expression",        # composer-registry sweep (2026-08-07): single-cell
                                         # per-compartment tumor presence (P6/sc_rna). In tumor-presence
                                         # CARDS (and surface-modality-fit CARDS) but composed under NO
                                         # entry → silently dropped. Composed here under its presence home
                                         # (also satisfies the surface-modality-fit CARDS listing).
    ],
    "tumor-selectivity": [
        "tumor-vs-normal-selectivity",
        "tumor-vs-normal-percentile-crossing",   # Q2 — paired with tumor-selectivity CARDS (composer-consistency)
        "modality-therapeutic-window",           # DEFERRED-1 FIX (2026-08-08): the normal-breadth veto rule
                                                 # (tvn-no-therapeutic-window-veto) keys on THIS card. It was
                                                 # composed only under the surface-modality-fit lens, so in the
                                                 # composed target-profile the veto NEVER fired in the selectivity
                                                 # lens's `fired` set (card_id_filter=SUB_SKILL_CARDS) → a
                                                 # broadly-normal housekeeping gene nominated as strong_tumor_selective
                                                 # (the FP the redesign exists to kill, resurrected in Go/No-Go).
                                                 # Adding it here makes the veto fire identically standalone vs
                                                 # composed. (A card may be composed under >1 lens.)
        "sc-normal-celltype-expression",         # INC-3 — composer-consistency: the sc-normal critical-organ
                                                 # veto (tvn-sc-normal-critical-organ-veto) must fire in the
                                                 # COMPOSED selectivity lens too, else the axis-D downgrade is
                                                 # lost in Go/No-Go (same class as the DEFERRED-1 gap).
        "expression-purity-confound",            # DEFERRED-3 — composer-consistency with the standalone CARDS
                                                 # (verdict-inert facet; feeds no selectivity resolver rung).
        "surface-abundance-density",             # INC-4 — composer-consistency: the absolute-density facet
                                                 # (verdict-inert; feeds no resolver rung). Surfaces Tier-1
                                                 # copies/cell + modality-floor standing in the composed profile.
    ],
    "functional-requirement": [
        "pan-cancer-crispr-dependency-distribution",
        "pan-cancer-rnai-dependency-distribution",
        "crispr-rnai-dependency-concordance",
        "prism-crispr-concordance",              # 2026-07-24 BUGFIX (found by the resolver-dependency
                                                 # guard) — the dependency resolver's
                                                 # `chemical_genetic_confirmed_dependent` rung fires on
                                                 # e7-triangulated-target-engaged-supportive, which keys
                                                 # on prism-crispr-concordance. It was composed ONLY under
                                                 # tractability-small-molecule, so the Gate-C chemical-
                                                 # genetic dependency CONFIRMATION could never fire in the
                                                 # composed profile. Cross-gate card (C confirm + E1
                                                 # compound-found), like prism-crispr-concordance's dual
                                                 # role in the resolver comment. (Also in tractability-sm.)
        "dependency-lineage-selectivity",
        "paralog-buffering",
        "expression-dependency-correlation",     # Gate-C biomarker facet (2026-07-22). Was ORPHANED:
                                                 # in the render maps (CARD_TITLE/CARD_ROLE/reports_into)
                                                 # + a live dispatcher, but composed by NO sub-skill, so
                                                 # correlation_class never computed → rendered empty.
                                                 # Render-only facet (verdict-inert: its rules feed no
                                                 # resolver). Also in functional-requirement/run.py CARDS.
        "recommended-models",                    # Q4 patient↔model correspondence (2026-07-22) — model-
                                                 # backed-dependency corroboration; paired with
                                                 # functional-requirement CARDS (composer-consistency).
        "abundance-dependency",                  # Q7 (2026-07-23) — protein abundance→dependency (protein
                                                 # arm of expression-as-biomarker-of-dependency); render facet.
        "partner-conditional-dependency",        # 2026-08-10 REVIEW FIX (H1): Track PC verdict-bearing card.
                                                 # In functional-requirement/run.py CARDS but DROPPED here, so
                                                 # the dependency resolver's partner_conditional_dependent rung
                                                 # (partner-conditional-{strongly,moderately}-dependent-supportive)
                                                 # was DEAD in the composed profile — a partner-conditional SL
                                                 # target (WRN×MSI) was force-vetoed non_dependent. The composer
                                                 # guard (test_resolver_dependency_cards_are_in_the_composer_entry)
                                                 # was sitting RED on exactly this. Restored.
        "cross-consortium-dependency",           # 2026-08-11 REVIEW FIX (facet-drop): Project Score
                                                 # cross-consortium dependency corroboration. In
                                                 # functional-requirement CARDS but composed under no
                                                 # entry → dropped from the composed profile. VERDICT-INERT
                                                 # (no interpretation rules → feeds no resolver rung), so
                                                 # composing it is byte-stable on the verdict spine; it only
                                                 # restores the render facet to the composed target-profile.
    ],
    "synthetic-lethal-partners": [
        "synthetic-lethal-partners",
    ],
    "combinatorial-dependency": [
        "combinatorial-dependency",      # DepMap ParalogV2 dual-KO GI + published corroboration
                                         # (Dede/in4mer/Horlbeck). Matches the skill's SKILL.md cards_used.
    ],
    "mechanism-and-pharmacology": [
        "signaling-network-mechanism",
        "phospho-pathway-activity",      # RE-HOMED 2026-08-05 from tumor-presence — phospho ACTIVITY /
                                         # signaling-state facet (CPTAC phosphoproteomics). Render facet.
        "pathway-activity-context",      # 2026-08-11 REVIEW FIX (facet-drop): PROGENy pathway-activity
                                         # context. In mechanism-and-pharmacology CARDS, composed under no
                                         # entry → dropped. VERDICT-INERT render facet (no rules).
        "tahoe-drug-perturbation",       # 2026-08-11 REVIEW FIX (facet-drop): Tahoe MoA/PD-marker
                                         # perturbation facet. In mechanism-and-pharmacology CARDS,
                                         # composed under no entry → dropped. VERDICT-INERT render facet.
    ],
    "genomic-alteration-profile": [          # reframed from mutation-profile
        "mutation-type-counts",
        "mutation-stratified-dependency",
        "mutation-hotspot-frequency",
        "copy-number-distribution",          # CN axis wired 2026-07-14
        "copy-number-stratified-dependency", # A1a (2026-08-06): amp×dependency rescue (fires
                                             # biomarker_stratified_dependency); composer-consistency
        "fusion-stratified-dependency",      # A1-fusion (2026-08-06): fusion×dependency rescue (fires
                                             # biomarker_stratified_dependency; EWSR1-FLI1/BCR-ABL1);
                                             # composer-consistency with genomic-alteration-profile CARDS
        "amp-expr-stratified-dependency",    # A1 amp-expr (2026-08-06): conjoint amp+overexpr×dependency
                                             # rescue (fires biomarker_stratified_dependency; ERBB2/MYC/
                                             # KRAS-amp); composer-consistency with genomic CARDS
        "mutation-drug-response",            # Thread-4 deferred-c (2026-08-09): genotype×PRISM drug-response;
                                             # its mutation-drug-response-strongly-sensitive-supportive rung
                                             # fires the DISTINCT drug_response_biomarker verdict. Composed
                                             # here so that rung can fire in the target-profile (else the
                                             # verdict was dead-in-composition — the composer guard caught it).
        "fusion-rearrangement-landscape",    # LIVE (tcga-fusion-consensus-v1); additive signal-only
        "alteration-role",                   # typed driver-role (OncoKB×IntOGen), 2026-07-22 —
                                             # paired with genomic-alteration-profile CARDS (composer-consistency)
        "functional-gene-state",             # M6 allele-count / biallelic two-hit state (2026-07-22) —
                                             # composer-consistency with genomic-alteration-profile CARDS.
        "genomic-event-model-match",         # M11 canonical P3 patient↔model genomic-event join
                                             # (2026-07-22) — composer-consistency.
        "genomic-instability-state",         # composer-registry sweep (2026-08-07): aneuploidy/WGD/MSI/
                                             # signature genome-state axis. In genomic-alteration-profile
                                             # CARDS but composed under no entry → dropped. Restored.
        "variant-level-interpretation",      # composer-registry sweep (2026-08-07): per-variant
                                             # oncogenicity (CIViC + hotspot). Same drift — in CARDS,
                                             # not composed → dropped. Restored.
        "ddr-deficiency-context",            # 2026-08-11 REVIEW FIX (facet-drop): DDR/HRD inert context
                                             # facet. In genomic-alteration-profile CARDS, composed under
                                             # no entry → dropped. VERDICT-INERT render facet (no rules).
        "mutational-signature-context",      # 2026-08-12: per-indication mutagenic-process cohort facet
                                             # (TCGA MC3 SBS). In genomic-alteration-profile CARDS →
                                             # composer-consistency requires it here. VERDICT-INERT (no rules).
        "oncogenic-pathway-alteration",      # 2026-08-11 REVIEW FIX (facet-drop): oncogenic-pathway
                                             # alteration context. In genomic-alteration-profile CARDS,
                                             # composed under no entry → dropped. VERDICT-INERT render facet.
    ],
    "differentiation-landscape": [
        "co-mutation-and-mutual-exclusivity",
        "expression-clinical-association",   # Q11 (2026-07-23) — expression→survival prognostic context;
                                             # render facet, paired with differentiation-landscape CARDS.
        "stemness-context",                  # 2026-08-11 REVIEW FIX (facet-drop): Malta 2018 mRNAsi
                                             # stemness context. In differentiation-landscape CARDS,
                                             # composed under no entry → dropped. VERDICT-INERT render facet.
        "precog-prognostic-association",     # 2026-08-11 REVIEW FIX (facet-drop): PRECOG prognostic
                                             # meta-Z corroboration. In differentiation-landscape CARDS,
                                             # composed under no entry → dropped. VERDICT-INERT render facet.
    ],
    "tractability-small-molecule": [         # split: SM chemical-genetic half
        "prism-compound-activity",
        "prism-crispr-concordance",
        "measured-potency-tractability",         # 2026-08-10 REVIEW FIX (M1): T3.1 measured-potency card.
                                                 # In tractability-small-molecule/run.py CARDS but DROPPED here,
                                                 # so the tractability_small_molecule resolver's measured_potent_ligand
                                                 # AND structurally_ligandable rungs (measured-potent-ligand-sm-supportive
                                                 # + measured-weak-ligand-sm-supportive) were unreachable in the
                                                 # composed profile. Was invisible to the composer guard until the
                                                 # 2026-08-10 _GATE_BY_SUBSKILL fix added this gate. Restored.
        "dependency-predictability",
        "structure-features-static",         # 2026-07-24 — E8 forward-ligandability (pocket/druggability).
                                             # In tractability-small-molecule/run.py CARDS but was dropped
                                             # from this composer entry (composed only under surface-
                                             # modality-fit, a DIFFERENT sub-skill), so the SM ligandability
                                             # signal never reached the composed tractability sub-verdict.
                                             # Cross-gate card (SM pocket + surface epitope), needed in BOTH.
        "degradation-feasibility",           # composer-registry sweep (2026-08-07): the degrader-lens E3
                                             # slice (E3-substrate + PROTAC precedent + location gate). In
                                             # tractability-small-molecule CARDS (feeds the degrader lens)
                                             # but composed under no entry → dropped. Restored so the
                                             # degradability signal reaches the composed profile.
        "known-drug-tractability",           # composer-registry sweep (2026-08-08): DGIdb pharmacology leg
                                             # (E-known-drug) wired into tractability-small-molecule CARDS by
                                             # #272 but composed under no entry → dropped. The card already
                                             # feeds the skill's own verdict (run.py:198); this restores it to
                                             # the composed target-profile so the known-drug signal reaches it.
    ],
    "surface-modality-fit": [                # split: biologics-modality half
        "surface-topology-and-ptm",
        "surfaceome-family-classification",
        "structure-features-static",
        "surface-abundance-density",
        "adc-tce-modality-fit",
        "normal-tissue-liability",           # HPA IHC off-tumor safety — in surface-modality-fit CARDS
                                             # (composer-consistency; was run.py-present but here-absent)
        "copy-number-distribution",          # P4 (2026-07-23): genomic amplification → surface antigen-
                                             # density (adc/bite_tce/antibody). Cross-cutting — ALSO in
                                             # genomic-alteration-profile (SM/degrader). Example B: one
                                             # card, two modality gates, divergent modality reads.
        "rna-protein-concordance-tumor",     # orphan-fix (2026-08-05): tier:indication RNA↔protein
                                             # concordance; its important-weighted ADC/TCE surface rules
                                             # were unreachable until surface-modality-fit composed it.
        # composer-registry sweep (2026-08-07): four surface/biologics cards in surface-modality-fit
        # CARDS but composed under no entry → silently dropped from the composed profile. Restored.
        "protein-surface-evidence",          # measured surface-localization evidence (CSPA/HPA).
        "shed-ectodomain-liability",         # shed-antigen serum-decoy liability (ADC/TCE drug-sink).
        "modality-therapeutic-window",       # composed therapeutic-window dispatcher call.
        "pmhc-presentation",                 # peptide-centric pMHC presentation (TCE/TCR-mimetic reach).
        # composer-registry sweep (2026-08-08): five more surface/biologics cards added to
        # surface-modality-fit CARDS by #275/#276/#277/#280/#281 but composed under no entry →
        # silently dropped from the composed profile. Restored (all fire additive supportive-only
        # rules; the composed surface_modality verdict stays byte-stable — narrative completeness only).
        "cd-antigen-backbone",               # CD/IO-antigen backbone clinical-precedent (E6-CD).
        "modality-exon-window",              # per-exon tumor-vs-normal ADC/TCE window (E5).
        "mutation-stratified-surface",       # mutant-up surface-antigen signal (E4-A2).
        "pathway-stratified-surface",        # pathway-stratified surface signal (E4-A3).
        "sc-normal-celltype-expression",     # single-cell normal-tissue safety comparator (F5).
        # tumor-scrna-celltype-expression is in this sub-skill's CARDS too but is composed under
        # tumor-presence (its presence home) — "composed somewhere" satisfies the invariant.
    ],
    "on-target-safety-liability": [
        "gnomad-lof-constraint",
        "alteration-role",                # 2026-07-24 BUGFIX — REQUIRED for the mutant-selective safety
                                          # downgrade to fire IN COMPOSITION. The fan-out scopes each
                                          # sub-skill to ITS OWN SUB_SKILL_CARDS entry (card_id_filter),
                                          # so alteration-role being composed under genomic-alteration-
                                          # profile did NOT make it available to the safety sub-skill.
                                          # safety.resolver 1.3.0's downgrade rungs are when_all_fired:
                                          # [<constraint/burden warning>, activating-driver-role-safety-
                                          # context]; that context rule keys on alteration-role. Without
                                          # this line, wt_constraint_mechanism_mismatch / wt_human_
                                          # genetics_mechanism_mismatch could NEVER fire in the composed
                                          # profile — a KRAS/COADREAD run wrongly HELD on WT-constraint.
                                          # (Also in on-target-safety-liability/run.py CARDS.)
        "normal-tissue-liability-gtex",   # Q3 — paired with on-target-safety-liability CARDS (composer-consistency)
        "target-safety-prioritisation",   # P5 Slice 1 — OT engineered-score safety CONTEXT (verdict-inert)
        "gene-burden-safety",             # P5 Slice 2 — OT rare-variant burden LoF-tolerance (verdict-moving; safety.resolver 1.3.0)
        "clingen-dosage",                 # P5 Slice 3 — ClinGen haploinsufficiency dosage-sensitivity (verdict-moving; safety.resolver 1.3.0)
        "mouse-ko-phenotype",             # P5 Slice 4 — mouse-KO normal-physiology (developmental-guardrailed; verdict-moving; safety.resolver 1.3.0)
        "clinvar-pathogenicity-safety",   # P5 follow-on — ClinVar germline-pathogenic (4th corroborating leg; verdict-moving)
    ],
}


# --- Subtype tier (verdict-affecting, opt-in via --subtypes) ----------------
# The subtype sub-result is CONDITIONAL: it only enters sub_results when a
# subtype scope is requested. This preserves exact backward-compat — no
# --subtypes → sub_results is byte-identical to before → gate unchanged. It
# implements the design's "subtype channel terminal WHEN Scope.subtypes
# populated" as opt-in-by-scope.
SUBTYPE_SHORT = "subtype_fit"
SUBTYPE_CARDS = [
    "subgroup-stratified-dependency",
    "subgroup-stratified-mutation-frequency",
]


def _subtype_verdict(fired: list[dict]) -> tuple[str, str | None] | None:
    """Verdict producer for the subtype tier. NEGATIVE-SELECTION only.

    Fires the verdict that the nomination gate maps to `hold` iff a subtype-tier
    rule fired (the subtype-non-dependence-opposing rule, which only matches a
    MEASURED, floor-cleared, not-dependent stratum — an underpowered row cannot
    match, so admissibility is enforced upstream at rule-fire time). Returns None
    when no subtype rule fired — a POSITIVE/absent subtype finding produces no
    verdict, so it can never inflate a nomination (gate is one-directional).
    """
    subtype_hits = [f for f in fired
                    if f.get("tier") == "subtype"
                    # `or ''` guards a signals dict that carries subtype_fit_genomic: null
                    # (present key, None value) — `.get(k, '')` returns None there, not '',
                    # and `'opposing' in None` would raise TypeError.
                    and "opposing" in ((f.get("signals") or {}).get("subtype_fit_genomic") or "")]
    if not subtype_hits:
        return None
    # Name the driving rule + the matched stratum for provenance.
    hit = subtype_hits[0]
    return ("subtype_specific_non_dependence", hit.get("rule_id"))


def _skipped_synthesis_output() -> dict:
    """Stub llm_output for --verdict-only/--no-synthesis (no Bedrock call).

    The deterministic recommendation gate + positive-tier logic clamp into
    overall_recommendation / confidence exactly as for a real (or degraded _synthesis_error)
    narration, so the verdict spine is byte-identical. Renderers read
    llm_output.get(section, {}).get("value", default) — absent narrative sections degrade to
    empty; executive_summary carries a note so the report is self-explanatory, not blank.
    """
    return {
        "_synthesis_skipped": True,
        "executive_summary": {
            "value": (
                "_LLM synthesis skipped (--verdict-only). The deterministic verdict spine below — "
                "gate scorecard, sub-verdicts, recommendation gate, positive tier, deciding axis — "
                "is authoritative and byte-identical to a full run. Re-run without --verdict-only "
                "for the narrative synthesis._"
            ),
            "_source": "synthesis_skipped",
        },
        "overall_recommendation": {"value": None, "_source": "synthesis_skipped"},
        "confidence": {"value": None, "_source": "synthesis_skipped"},
    }


def _run_sub_skills(target: str, indication: str,
                    subtypes: Optional[list[str]] = None,
                    profile_timers: bool = False) -> dict:
    """Invoke each sub-skill's verdict logic in-process. Returns dict keyed
    by short name (`expression`, `selectivity`, ...) with:
      - `skill_dir`
      - `cards`: card_outputs from resolve_cards
      - `fired`: fired-rules list
      - `verdict`: (verdict_str, driving_rule_id) tuple or None if the
        sub-skill doesn't expose a verdict function (e.g. patient-
        population-and-access has no rules; verdict is None)
    """
    # Fire BOTH rule axes and merge. load_interpretation_rules loads exactly
    # one axis file, so a sub-skill whose cards span axes (surface-modality-fit
    # fires surface_intrinsic; most others fire intracellular_intrinsic) would
    # otherwise silently fire nothing on the un-loaded axis. filter_by_card_ids
    # scopes each axis's rules to the sub-skill's cards, so firing both is safe
    # (no cross-contamination) and card-correct regardless of which file a
    # card's rules live in. (Fixed 2026-07-14 when the tractability split first
    # made a surface-only sub-skill a peer in the composer.)
    # Rule AXES fired per sub-skill (card_id_filter scopes each to its own cards). combinatorial_dependency
    # (2026-08-14) is a DEDICATED axis — the combinatorial-dependency skill's rules live in
    # combinatorial-dependency.rules.yaml on their own axis, isolated from the shared ladder. Without it
    # here the fan-out fired NO combinatorial rules → the axis always resolved `insufficient` in the
    # composed profile (a hollow composition) while the standalone skill read constitutive/context. Other
    # sub-skills lack the combinatorial-dependency card, so this axis is a no-op for them (card_id_filter).
    axes = ("intracellular_intrinsic", "surface_intrinsic", "combinatorial_dependency")

    def _one_sub_skill(skill_dir: str, short: str) -> tuple[str, dict]:
        """Compute one sub-skill's (cards, fired, verdict). Pure over (target, indication) +
        that sub-skill's own cards — no cross-sub-skill state (verified collect-then-synthesize),
        so this is safe to run concurrently. Returns (short, result-dict)."""
        _t0 = time.perf_counter() if profile_timers else 0.0
        cards = resolve_cards(SUB_SKILL_CARDS[skill_dir], target, indication)
        if profile_timers:
            print(f"[perf] read  {short:26s} {time.perf_counter() - _t0:6.1f}s "
                  f"({len(SUB_SKILL_CARDS[skill_dir])} cards)", file=sys.stderr)
        # G1 (2026-08-13): apply the sub-skill gate's registered CARD PREPROCESSOR (e.g. the
        # genomic-alteration family-wise FDR) BEFORE firing, so the composed fan-out corrects the card
        # summaries identically to the standalone skill's main(). Previously the FDR was standalone-only
        # → this fan-out fired on un-corrected p-values and over-credited biomarker_stratified_dependency
        # (the nomination veto-suppressor). No-op for gates with no registered preprocessor.
        preprocess_cards_for_gate(cards, _SHORT_TO_GATE.get(short))
        fired: list[dict] = []
        for axis in axes:
            fired.extend(fired_rules(cards, axis=axis,
                                     card_id_filter=SUB_SKILL_CARDS[skill_dir]))
        verdict_fn = _load_sub_skill_verdict_fn(skill_dir)
        verdict_pair = verdict_fn(fired) if verdict_fn else None
        return short, {
            "skill_dir": skill_dir,
            "cards": cards,
            "fired": fired,
            "verdict": verdict_pair,  # (str, driving_rule_id) or None
            # Stage 1b: the SAME sub-verdict, carried in the shared CompositionResult type (the
            # foundation the later --emit evidence-package stage consumes). ADDITIVE — wraps the
            # already-decided verdict_pair (post-resolver logic preserved); verdict/fired/cards and
            # the nomination emission are untouched, so output stays byte-identical. Gateless shorts
            # (tumor-presence `expression`) → empty primary; the presence verdict stays in `verdict`.
            "composition": subskill_composition(
                card_outputs=cards, fired=fired,
                gate=_SHORT_TO_GATE.get(short), verdict_pair=verdict_pair,
            ),
        }

    # PERF Stage 2 (2026-07-23): the 10 sub-skills are GENUINELY INDEPENDENT (collect-then-synthesize;
    # no sub-skill reads another's result), so fan them out CONCURRENTLY. THREADS not processes: the
    # method-layer caches (depmap_common.parquet lru + disk cache; framework-tpm-long/hpa disk latches)
    # are process-global, so threads SHARE a target's reads across sub-skills (processes would
    # duplicate + re-download). pandas/pyarrow release the GIL during parquet/CSV I/O, so the IO-bound
    # reads overlap. Wall is bounded by the longest single sub-skill (measured: `expression` ~106s).
    #
    # BYTE-STABILITY: concurrency must NOT change the deterministic verdict spine. Two guards:
    #   1. Pre-warm all imports ONCE before the pool (below) — neutralizes the sys.path.insert(0,...)
    #      global-list race in the dispatcher/method imports.
    #   2. Re-assemble `results` in SUB_SKILLS order (NOT completion order) — every downstream
    #      reduction (_ordinal_matrix / _gate_recommendation / _deciding_axis / scorecard) + the
    #      nomination.json sub_verdicts iterate this dict; insertion order must match the serial run.
    _prewarm_sub_skill_imports()
    completed: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(SUB_SKILLS), _FANOUT_MAX_WORKERS)) as ex:
        futures = {ex.submit(_one_sub_skill, sd, sh): sh for sd, sh in SUB_SKILLS}
        for fut in concurrent.futures.as_completed(futures):
            short, res = fut.result()   # a sub-skill exception propagates here (fail-loud, as serial did)
            completed[short] = res
    # deterministic re-order: rebuild in SUB_SKILLS order (byte-stability guard #2)
    results: dict = {short: completed[short] for _, short in SUB_SKILLS}

    # Subtype tier — ONLY when a subtype scope was requested. Panorama cards need
    # the resolved strata + assignments shard threaded via subgroup_context; the
    # subtype rule fires in_record on measured, floor-cleared, not-dependent rows.
    if subtypes:
        subgroup_context = {"resolved_strata_ids": list(subtypes),
                            "catalog_status": "resolved_active"}
        sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication,
                                  subgroup_context=subgroup_context)
        sub_fired: list[dict] = []
        for axis in axes:
            sub_fired.extend(fired_rules(sub_cards, axis=axis,
                                         card_id_filter=SUBTYPE_CARDS))
        subtype_verdict_pair = _subtype_verdict(sub_fired)
        results[SUBTYPE_SHORT] = {
            "skill_dir": None,             # not a directory sub-skill; composed inline
            "cards": sub_cards,
            "fired": sub_fired,
            "verdict": subtype_verdict_pair,
            "scope_subtypes": list(subtypes),
            # Stage 1b: typed sub-verdict carrier (see _one_sub_skill). ADDITIVE.
            "composition": subskill_composition(
                card_outputs=sub_cards, fired=sub_fired,
                gate=_SHORT_TO_GATE.get(SUBTYPE_SHORT), verdict_pair=subtype_verdict_pair,
            ),
        }
    return results


# --- Deterministic recommendation gate --------------------------------------
#
# The overall_recommendation was historically 100% LLM-chosen (the LLM saw the
# sub-verdicts as prompt text and picked nominate|hold|veto|insufficient_evidence).
# A killer sub-verdict must FORCE the call, not merely suggest it.
#
# This is the cross-gate NOMINATION gate — a DISTINCT layer from the 9 per-axis
# verdict gates. It does NOT reimplement per-gate verdicts: each sub-skill already
# resolves its own gate via the shared resolver, and target-profile INHERITS those
# sub-verdicts (r["verdict"]); this gate only maps the (sub_skill, verdict) tuples to
# a nominate/hold/veto action. That policy is itself declarative — it lives in
# target-contracts/vocabularies/nomination_verdict_gate.yaml (there is no per-gate
# resolver for "nomination"; this vocab is its home), loaded below with a conservative
# hardcoded fallback-of-record.
#
# HISTORY: this gate's killer-short-circuit shape once echoed compose-dashboard's
# _synthesis.py fit_level scorer. That second engine was removed in Phase D (#377) —
# compose-dashboard now routes through the same shared resolver — so the "two composition
# engines" that motivated the copied-not-shared pattern no longer exist; only this
# higher-level nomination layer remains, and it is intentionally its own declarative gate.
#
# CURATED veto set (conservative): only genuine CROSS-TARGET vetoes force veto.
# Modality-scoped killers (surface neither_viable, degrader expression killers)
# are deliberately EXCLUDED — they foreclose one modality, not the target (KRAS
# hits surface/degrader killers yet is a correct `nominate` via small molecule;
# see the KRAS×COADREAD golden).
#
# The AUTHORITATIVE policy lives in target-contracts/vocabularies/
# nomination_verdict_gate.yaml (reviewable by product owners without a code
# change). This hardcoded set is the FALLBACK-OF-RECORD: if the vocab is
# missing/unparseable, _load_gate_verdicts() returns this and warns. The gate
# must NEVER become permissive on a missing policy file — a silently-disabled
# pan-essential veto would be a safety regression — so the fallback is
# conservative-and-complete, and the vocab can only match-or-tighten it.
_FALLBACK_GATE_VERDICTS: dict[tuple[str, str], str] = {
    ("dependency", "pan_essential_killer"): "veto",   # non-selective essentiality — no window
    ("dependency", "non_dependent"): "veto",          # no dependency at all
    ("safety", "highly_constrained_safety_concern"): "hold",  # concern → hold, not veto
}
# Precedence when multiple gates fire: veto dominates hold.
_GATE_ACTION_RANK = {"veto": 2, "hold": 1}

_CONTRACTS_REPO = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)


def _load_gate_verdicts(contracts_repo: Path | None = None) -> tuple[dict[tuple[str, str], str], str]:
    """Load the (sub_skill, verdict) → action policy from the target-contracts
    vocabulary. Returns (mapping, source) where source ∈ {"vocab", "fallback"}.

    SAFETY CONTRACT: on ANY failure (file missing, parse error, malformed) this
    returns the conservative hardcoded _FALLBACK_GATE_VERDICTS + "fallback" and
    warns — it must never return an empty/permissive map, which would silently
    disable the veto.
    """
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        gates = data["gates"]
        mapping = {(g["sub_skill"], g["verdict"]): g["action"] for g in gates}
        if not mapping:
            raise ValueError("empty gates list")
        return mapping, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → safe conservative fallback
        print(f"[target-profile] WARN: could not load nomination_verdict_gate vocab "
              f"({type(e).__name__}: {e}); using hardcoded conservative fallback.",
              file=sys.stderr)
        return dict(_FALLBACK_GATE_VERDICTS), "fallback"


# Biologics modalities for which the dependency veto is INFORMATIVE-only (a
# surface-directed biologic kills via antigen engagement, not genetic dependency).
_BIOLOGICS_MODALITIES = {"adc", "bite_tce", "antibody"}


def _load_veto_suppressors(
    contracts_repo: Path | None = None,
) -> tuple[list[dict], list[dict], str]:
    """Load the two veto-suppression policies (v1.2.0) from the vocab. Returns
    (context_escape_suppressors, modality_scoped_suppression, source).

    CONSERVATIVE FALLBACK (mirrors the never-permissive contract, inverted for a
    suppressor): on ANY failure this returns EMPTY lists — a missing/malformed
    suppressor block means NO suppression fires and the full veto stands. A
    suppressor can therefore only ever make the gate MORE conservative when its
    own policy is present; its absence can never disable a veto.
    """
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        ctx = data.get("veto_suppressors", []) or []
        msvs = data.get("modality_scoped_veto_suppression", []) or []
        return ctx, msvs, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no suppression, veto stands)
        print(f"[target-profile] WARN: could not load veto suppressors "
              f"({type(e).__name__}: {e}); suppression DISABLED (full veto stands).",
              file=sys.stderr)
        return [], [], "fallback"


def _suppressed_gate_hits(
    hits: list[dict],
    sub_results: dict,
    modality: Optional[str],
    contracts_repo: Path | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply v1.2.0 veto suppression to the fired gate hits. Returns
    (surviving_hits, suppression_records). A hit is suppressed when EITHER:

    (A) context-escape — a `veto_suppressors` rule names it as `suppresses` AND one
        of its `when_present` rescue verdicts fired (a MEASURED biomarker-stratified
        dependency proves the target is required in its stratum → the pooled
        non_dependent read is a dilution artifact). Rescues EGFR/IDH1/FLT3.
    (B) modality-scoped — a `modality_scoped_veto_suppression` rule names it AND the
        declared modality is in the rule's `when_modality_in` (a surface biologic
        kills via antigen engagement, not dependency). Rescues CD19/TROP2/DLL3.
        Fires ONLY when a modality is explicitly declared.

    CONSERVATIVE: empty suppressor policy → nothing suppressed (full veto stands).
    Only `dependency` veto arms are ever suppressible (the vocab enforces this too).
    """
    ctx_supps, msvs, src = _load_veto_suppressors(contracts_repo)
    if not ctx_supps and not msvs:
        return hits, []

    present = {(short, (r.get("verdict") or [None])[0]) for short, r in sub_results.items()}
    survivors: list[dict] = []
    suppressions: list[dict] = []
    for h in hits:
        key = (h["short"], h["verdict"])
        suppressed_by = None
        # (A) context-escape
        for s in ctx_supps:
            sup = s.get("suppresses", {})
            if (sup.get("sub_skill"), sup.get("verdict")) != key:
                continue
            trigger = next((w for w in s.get("when_present", [])
                            if (w["sub_skill"], w["verdict"]) in present), None)
            if trigger:
                suppressed_by = {"kind": "context_escape",
                                 "trigger": f"{trigger['sub_skill']}:{trigger['verdict']}"}
                break
        # (B) modality-scoped
        if suppressed_by is None and modality:
            for m in msvs:
                sup = m.get("suppresses", {})
                if (sup.get("sub_skill"), sup.get("verdict")) != key:
                    continue
                if modality in set(m.get("when_modality_in", [])):
                    suppressed_by = {"kind": "modality_scoped", "modality": modality}
                    break
        if suppressed_by:
            suppressions.append({**h, "suppressed_by": suppressed_by, "policy_source": src})
        else:
            survivors.append(h)
    return survivors, suppressions


def _gate_recommendation(
    sub_results: dict, contracts_repo: Path | None = None,
    modality: Optional[str] = None,
) -> tuple[Optional[str], list[dict], list[dict]]:
    """Deterministically derive a forced overall_recommendation from sub-verdicts.

    Returns (forced_action | None, hits, suppressions). `hits` is the list of
    surviving {short, verdict, action, driving_rule_id} that force the action —
    for provenance. `suppressions` records any veto hit that fired but was
    suppressed (v1.2.0 context-escape / modality-scoped) — also for provenance, so
    a suppressed veto is never silent. None action means no (surviving) gate fired.
    When multiple survive, the highest-rank action wins (veto > hold). Policy comes
    from the target-contracts vocab (conservative hardcoded fallback on load failure).
    """
    gate_verdicts, policy_source = _load_gate_verdicts(contracts_repo)
    hits: list[dict] = []
    for short, r in sub_results.items():
        v = r.get("verdict")
        if not v:
            continue
        verdict_str, driving_rule_id = v[0], (v[1] if len(v) > 1 else None)
        action = gate_verdicts.get((short, verdict_str))
        if action:
            hits.append({"short": short, "verdict": verdict_str,
                         "action": action, "driving_rule_id": driving_rule_id,
                         "policy_source": policy_source})
    # v1.2.0: apply veto suppression (context-escape + modality-scoped) before
    # resolving the forced action. A suppressed veto does not force — but is recorded.
    hits, suppressions = _suppressed_gate_hits(hits, sub_results, modality, contracts_repo)
    if not hits:
        return None, [], suppressions
    # .get(a, 0): an action outside {veto, hold} (a vocab typo or a new action a product owner adds —
    # the module comment explicitly invites editing this vocab "without a code change") must NOT crash
    # the run with a KeyError, which would defeat the "gate never crashes the run" contract. Unknown
    # actions rank LOWEST (0) so a real veto/hold always wins; the target-contracts CI test
    # (test_every_gate_well_formed) is the primary guard — this is defense-in-depth.
    forced = max((h["action"] for h in hits), key=lambda a: _GATE_ACTION_RANK.get(a, 0))
    return forced, hits, suppressions


# --- Deciding-axis router (L / KNOWN_TARGET_FRAMEWORK_REFRAMES Reframe 3) -----
#
# Turns a bare `insufficient_evidence` into a ROUTING statement: which gate is load-bearing
# for THIS run, and whether the framework can evidence it. HONESTY GUARDRAIL (Reframe 3 lines
# 103-106): this does NOT predict which gate WILL decide a target prospectively ("a mis-route
# fails more confidently than a portrait"). It only REPORTS, from the run's actual sub-verdicts:
#   - gate FIRED (veto/hold)  → the firing gate IS the deciding axis (known, not predicted);
#                               framework_can_evidence = captured (we evidenced it → it fired).
#   - abstaining (no gate)    → list the NECESSITY gates we could not evidence + their standing
#                               ("we can't decide because gates X,Y are the ones we're blind on").
#   - positive (no gate)      → the strongest positive dimension is the load-bearing axis.
# The gate_coverage.yaml baseline is the STATIC standing; the router DOWNGRADES it per-run to
# `blind`/`data_blocked` when a gate's own cards came back missing, and never upgrades past it.
_COVERAGE_RANK = {"captured": 3, "partial": 2, "license_blocked": 1, "blind": 0, "out_of_scope": 0}


# The v2 (2.0.0) gate_coverage splits the v1 flat `gates:` list into three lists by grain/axis:
#   biology_gates  — the necessity gates (A..E incl. "Altered"); scorecard rows.
#   modality_fit   — per-lens sufficiency assessments (named, letterless); scorecard rows.
#   biomarker_facets — relational feature×outcome sub-skills. Two GRAINS live here:
#       grain: sub_skill  → a real sub-verdict slot the composer emits (synthetic_lethal_partners,
#                           subtype_fit) → IS a scorecard row (as in v1).
#       grain: card       → a card-level facet (mutation_stratified, crispr_rnai_concordance, …)
#                           that surfaces INSIDE its outcome gate's section, NEVER its own row.
# The loader below reads EITHER shape and returns the same {short: entry} map the router+scorecard
# consumed under v1 — containing exactly the sub-skill-grain entries (biology + modality_fit + the
# sub_skill-grain facets), so no phantom card-grain rows appear. Missing `grain:` defaults to
# sub_skill (fail-open: a mis-tagged facet becomes a visible row rather than silently vanishing).
_V2_GATE_LISTS = ("biology_gates", "modality_fit", "biomarker_facets")


def _flatten_gate_coverage(data: dict) -> dict:
    """Return {short: entry} for the scorecard/router, accepting v1 (`gates:`) or v2 (three-list).
    v2 card-grain biomarker_facets are EXCLUDED (they are in-section facets, not scorecard rows)."""
    if "gates" in data:                      # v1 / v1.1.0 flat shape — every entry is a row.
        return {g["short"]: g for g in data["gates"]}
    by_short: dict = {}                      # v2 three-list shape.
    for key in _V2_GATE_LISTS:
        for g in data.get(key, []):
            if key == "biomarker_facets" and g.get("grain", "sub_skill") == "card":
                continue                     # card-grain facet → rendered in-section, not a row
            by_short[g["short"]] = g
    return by_short


def _load_gate_coverage(contracts_repo: Path | None = None) -> tuple[dict, str]:
    """Load the per-short gate_coverage map from the target-contracts vocab. Returns
    ({short: {gate, gate_name, band, axis, framework_can_evidence, ...}}, source). Accepts BOTH the
    v1 flat `gates:` list and the v2 three-list (biology_gates/modality_fit/biomarker_facets) shape
    — see _flatten_gate_coverage. EMPTY-on-failure (source='none'): the router then degrades to a
    bare abstention note rather than fabricating a coverage claim — a missing map must never invent
    a `captured`."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "gate_coverage.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        by_short = _flatten_gate_coverage(data)
        if not by_short:
            raise ValueError("no gate entries (neither v1 `gates:` nor v2 three-list)")
        return by_short, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → empty (never a fabricated coverage)
        print(f"[target-profile] WARN: could not load gate_coverage vocab "
              f"({type(e).__name__}: {e}); deciding-axis router degrades to a bare note.",
              file=sys.stderr)
        return {}, "none"


def _sub_result_has_signal(r: dict) -> bool:
    """A sub-result 'evidenced its gate' iff it produced a non-sentinel verdict OR fired any
    rule on a card that returned real (non-missing) data. Absence of both = we could not look."""
    v = r.get("verdict")
    verdict_str = v[0] if v else None
    if verdict_str and verdict_str not in ("insufficient", "data_unavailable", None):
        return True
    return bool(r.get("fired"))


def _run_coverage_for_short(short: str, r: dict, baseline: dict) -> str:
    """Per-run framework_can_evidence for a sub-result: start from the static baseline and
    DOWNGRADE (never upgrade) when this gate's cards actually came back missing this run.
    All cards missing → the framework could not look here → `blind` for this run."""
    base = baseline.get(short, {}).get("framework_can_evidence", "blind")
    cards = r.get("cards") or []
    if cards and all(c.get("_missing") for c in cards):
        return "blind"          # every card for this gate was unavailable this run
    return base


def _deciding_axis(sub_results: dict, gate_action: Optional[str],
                   gate_hits: list[dict], positive_hits: list[dict],
                   contracts_repo: Path | None = None) -> dict:
    """Build the deciding_axis block (see module comment above). Deterministic; never predicts."""
    baseline, source = _load_gate_coverage(contracts_repo)

    def _row(short: str) -> dict:
        b = baseline.get(short, {})
        return {
            "short": short,
            "gate": b.get("gate"),
            "gate_name": b.get("gate_name"),
            "band": b.get("band"),
            "framework_can_evidence": _run_coverage_for_short(short, sub_results.get(short, {}), baseline),
        }

    # (1) A gate FIRED → the deciding axis is KNOWN (the firing gate). captured by definition.
    if gate_action and gate_hits:
        # Name the gate whose action actually WON (forced == max over action ranks), not merely
        # the first-iterated hit — otherwise the routing text could name a 'hold' gate while
        # reporting the 'veto' a different gate forced.
        _winning = next((h for h in gate_hits if h.get("action") == gate_action), gate_hits[0])
        top = _winning["short"]
        row = _row(top)
        row["framework_can_evidence"] = "captured"   # it fired → we evidenced it
        return {"basis": "gate_fired", "coverage_source": source,
                "deciding_axis": row,
                "routing": f"decided by gate {row.get('gate')} ({row.get('gate_name')}): "
                           f"{top} forced '{gate_action}'."}

    # (2) A positive tier exists → the load-bearing axis is the strongest positive dimension.
    if positive_hits:
        shorts = sorted({h["short"] for h in positive_hits})
        rows = [_row(s) for s in shorts]
        return {"basis": "positive_signal", "coverage_source": source,
                "deciding_axes": rows,
                "routing": f"supported by {', '.join(shorts)} (necessity biology evidenced)."}

    # (3) Abstaining → report the NECESSITY gates we could NOT evidence this run + their standing.
    # This is the routing instruction: "the decision lives in a gate we're blind on."
    unevidenced = []
    for short, r in sub_results.items():
        if short not in baseline:
            continue
        if not _sub_result_has_signal(r):
            unevidenced.append(_row(short))
    # necessity first, then by weakest coverage (blind before partial) — the gates most likely
    # to be the reason we can't decide.
    unevidenced.sort(key=lambda x: (x.get("band") != "necessity",
                                    _COVERAGE_RANK.get(x.get("framework_can_evidence"), 0)))
    return {"basis": "abstention_coverage_gaps", "coverage_source": source,
            "unevidenced_gates": unevidenced,
            "routing": ("cannot decide from framework evidence; unevidenced gates (necessity "
                        "first): " + ", ".join(
                            f"{g['short']}[{g.get('gate')}/{g.get('framework_can_evidence')}]"
                            for g in unevidenced) if unevidenced else
                        "cannot decide; no gate produced a signal and no coverage map available.")}


# --- Ordinal matrix VIEW (gap #3 "now" / gap #4 demo) ------------------------
#
# A gate × modality signal matrix, projected onto the ordinal scale for DISPLAY + RANKING.
# This is the "evidence matrix" made concrete for a single (target, indication) run: rows = the
# gates (sub-skills), columns = the 5 delivery modalities, cells = the strongest signal that
# gate's fired rules emit for that modality, shown as its ordinal.
#
# HONESTY (ordinal_view module contract): this is a labeled VIEW, NOT measurement and NOT a
# verdict input. It reads already-resolved fired-rule signals and never feeds back into any
# rule/resolver/gate. insufficient/not_applicable cells are off-scale (coverage), not low scores.
_MATRIX_MODALITIES = ("small_molecule", "degrader", "adc", "bite_tce", "antibody")


def _strongest_signal_for_modality(fired: list[dict], modality: str) -> Optional[str]:
    """The most-decisive signal a gate's fired rules emit for one modality channel. 'Most
    decisive' = lowest ordinal (killer < opposing < neutral < supportive); off-scale
    (insufficient/not_applicable) only when NO on-scale signal was emitted. Mirrors the
    display convention that a killer dominates a co-fired supportive in the same cell."""
    on_scale: list[tuple[int, str]] = []
    off_scale: Optional[str] = None
    for r in fired:
        sig = (r.get("signals") or {}).get(modality)
        if sig is None:
            continue
        o = ordinal_view.ordinal_of(sig)
        if o is None:
            off_scale = off_scale or sig      # remember an off-scale signal as a fallback
        else:
            on_scale.append((o, sig))
    if on_scale:
        return min(on_scale, key=lambda t: t[0])[1]   # most-negative wins the cell
    return off_scale                                   # else an off-scale coverage marker (or None)


def _ordinal_matrix(sub_results: dict) -> dict:
    """Build the gate × modality ordinal-view matrix for this run (see section comment).
    Returns {rows: [{short, gate signals+ordinals per modality}], legend, _disclaimer}."""
    rows = []
    for short, r in sub_results.items():
        fired = r.get("fired") or []
        by_mod = {m: _strongest_signal_for_modality(fired, m) for m in _MATRIX_MODALITIES}
        view = ordinal_view.project_signals(by_mod)
        rows.append({
            "short": short,
            "verdict": (r.get("verdict") or [None])[0],
            "cells": view["cells"],          # {modality: {signal, ordinal, on_scale}}
        })
    return {
        "axes": {"rows": "gate (sub-skill)", "columns": list(_MATRIX_MODALITIES),
                 "cell": "strongest signal for (gate, modality), ordinal-projected"},
        "rows": rows,
        "legend": ordinal_view.scale_legend(),
        "_disclaimer": ordinal_view.scale_legend()["_disclaimer"],
    }


# --- Biomarker convergence facet (Q12; master-sequencing Part 3c) -----------
#
# A FACET, not a gate: biomarker is always "a biomarker OF something" — it has no standalone verdict
# about the target, it MODIFIES other gates' verdicts. This assembles the scattered biomarker-relevant
# byproducts each extraction plan produces into ONE structured object with two jobs (Part 3c):
#   - corroboration_role  → raises CONFIDENCE in a biology-gate verdict
#   - stratification_role → defines the patient-selection population + preferred assay
# DETERMINISTIC + ADDITIVE + ONE-DIRECTIONAL (mirrors _ordinal_matrix): computed pre-prompt from the
# sub-verdicts, surfaced to the LLM + emitted in nomination.json, and it can raise confidence via the
# LLM's reasoning but NEVER mints a nominate (no verdict input; the deterministic gate is untouched).
# Pure convergence — no new extraction, no new card. Reads ONLY what the sub-skills already surface.
_BIOMARKER_INPUTS = {
    # short (sub-skill) : list of (summary_field, role) it contributes
    "genomic_alteration": [("alteration_role", "corroboration"),          # predictive_biomarker value
                           ("mutation_stratification_class", "stratification")],  # mutant-stratified dependency
    "dependency":        [("abundance_dependency_class", "corroboration"),   # Q7 protein abundance→dep
                          ("correlation_class", "corroboration"),            # RNA arm expression→dep
                          ("correspondence_class", "corroboration")],        # Q4 model-backed dependency
                                                                             # (the recommended-models CARD key;
                                                                             #  NOT the functional-requirement
                                                                             #  headline alias model_correspondence_class,
                                                                             #  which _first_card_summary_field never sees)
    "expression":        [("rna_as_biomarker", "stratification"),            # Q5 preferred-assay input
                          ("subtype_stratification_class", "stratification"), # subtype patient-selection (2026-08-04)
                          ("purity_confound_class", "corroboration")],       # Q9 signal-is-tumor-intrinsic
    # phospho_activity_class RE-HOMED 2026-08-05: it now surfaces under the mechanism sub-result
    # (phospho card moved tumor-presence → mechanism-and-pharmacology), so read it from there — else
    # the biomarker facet would silently drop the Q8 pathway-active corroboration signal.
    "mechanism":         [("phospho_activity_class", "corroboration")],      # Q8 pathway-active (phospho)
    "differentiation":   [("survival_association_class", "stratification")], # Q11 prognostic stratifier
}


# ── A2a: quantitative re-surfacing (biomarker-axis plan §A2a) ─────────────────────────────────
# The categorical *_class fields above are BUCKETED from raw statistics the cards already compute
# (pearson_r, effect sizes, Mann-Whitney q, delta-Chronos, agreement fractions) — but the facet
# collapses each card to its class and DISCARDS the numbers. This map names, per sub-skill, the
# companion NUMERIC summary fields to re-surface alongside the class, so the facet carries the
# strength of each signal, not just its bucket. Pulled with the SAME _first_card_summary_field
# accessor the categorical read uses (no new data, no computation). Verdict-inert: the numbers ride
# in a parallel `quantitative` block; the recommendation gate never reads the facet.
_BIOMARKER_QUANT = {
    # short (sub-skill) : list of numeric summary_fields to re-surface if present
    "genomic_alteration": ["hotspot_mannwhitney_q", "hotspot_effect_size",
                           "delta_chronos_hotspot_mut_vs_wt",
                           "median_chronos_hotspot_mutant", "median_chronos_hotspot_wildtype",
                           # Thread 3 (2026-08-09): dependency-classification PERFORMANCE — the
                           # biomarker as a classifier for the DepMap-dependency phenotype. PPV-lift
                           # separates rare-sharp (BRAF ~9.6x) from common-dep high-PPV-low-lift (KRAS
                           # ~2.2x) markers the coarse class hides. DEPENDENCY performance, NOT clinical.
                           "hotspot_dependency_ppv", "hotspot_dependency_sensitivity",
                           "hotspot_dependency_specificity", "hotspot_dependency_base_rate",
                           "hotspot_dependency_ppv_lift"],
    "dependency":        ["pearson_r", "pearson_p", "spearman_r",
                          "delta_chronos_top_vs_bottom_quartile",
                          "protein_dependency_pearson_r", "protein_dependency_pearson_p",
                          "n_cell_lines_evaluated", "n_paired_models",
                          "fraction_agree", "fraction_dependent_in_both"],
    "expression":        ["rna_protein_r", "rna_protein_spearman", "n_paired_tumors"],
    "differentiation":   ["logrank_p", "logrank_chi2", "n_patients", "n_events",
                          "high_expr_hazard_direction"],
}


def _biomarker_quantitative(sub_results: dict) -> dict:
    """Re-surface the raw statistics behind the biomarker categorical classes (A2a). Returns a
    {sub_skill: {field: value}} dict of the numeric companion fields that were present this run —
    reusing _first_card_summary_field (same accessor as the categorical read). Verdict-inert: this
    is display strength only; null/absent fields are simply omitted (honest coverage, not fabricated)."""
    quant: dict = {}
    for short, numeric_fields in _BIOMARKER_QUANT.items():
        r = sub_results.get(short)
        if not r:
            continue
        found = {}
        for field in numeric_fields:
            val = _first_card_summary_field(r, field)
            if val is not None:
                found[field] = val
        if found:
            quant[short] = found
    return quant


# ── BEST-role classification (biomarker-axis plan §1) ────────────────────────────────────────
# The facet's corroboration/stratification blocks answer "IS there a biomarker signal?" but NOT
# "what KIND?". A biomarker is always one of a fixed set of intended-uses, and they MUST stay
# separate — high target expression may be PROGNOSTIC but not PREDICTIVE; a driver LoF may define a
# diagnostic SUBTYPE but not predict inhibitor sensitivity. A single target can carry SEVERAL
# (KRAS: predictive; MLH1: subtyping + prognostic), so this emits a LIST of typed hypotheses, never
# one collapsed label. Pure classification over fields the facet already assembled — no new data,
# verdict-inert (each hypothesis names its intended_use + basis + a coarse evidence_strength).
#
# intended_use vocabulary (BEST framework subset the current inputs can support):
#   predictive           — a molecular state that predicts response to targeting (mutation-stratified
#                          dependency / predictive_biomarker alteration_role). Guardrail: a CRISPR-
#                          dependency biomarker is a DEPENDENCY-predictive hypothesis, NOT proven an
#                          inhibitor biomarker — labelled predictive_dependency, basis flagged.
#   prognostic           — associates with outcome irrespective of treatment (expression↔survival).
#                          Kept STRICTLY distinct from predictive (survival is stage-dominated).
#   diagnostic_subtyping — defines a molecular subtype/class (driver LoF/GoF or a restricted subtype).
#   pharmacodynamic      — a downstream activity readout usable to confirm target engagement (phospho).
# (predictive-performance PPV/NPV + deployability are the plan's NEXT layers — NOT computed here.)


def _classify_biomarker_best_roles(corroboration: dict, stratification: dict,
                                    quantitative: dict = None) -> list:
    """Type the assembled biomarker signals into a LIST of {intended_use, basis, evidence_strength}
    hypotheses (BEST-role §1). Pure fn — deterministic, no I/O; roles are NON-exclusive. A field that
    is null / data_unavailable / not_informative contributes nothing (honest — never fabricates a role).

    When `quantitative` carries the genomic dependency-classification performance (Thread 3), the
    genomic predictive hypothesis is annotated with the computed dependency-PPV + PPV-lift — a real
    metric on the DepMap-dependency ground truth (NOT drug-response / clinical PPV)."""
    quantitative = quantitative or {}

    def _live(v):
        return v not in (None, "data_unavailable", "not_informative", "insufficient_survival_data",
                         "insufficient_mutation_rate", "insufficient_paired_models")

    # Dependency-classification performance for the genomic stratifier (Thread 3), if present.
    _gq = quantitative.get("genomic_alteration", {}) or {}
    _dep_ppv = _gq.get("hotspot_dependency_ppv")
    _dep_lift = _gq.get("hotspot_dependency_ppv_lift")

    def _ppv_perf():
        """A compact dependency-performance dict to attach to a genomic predictive hypothesis."""
        if _dep_ppv is None:
            return None
        return {"dependency_ppv": _dep_ppv,
                "dependency_ppv_lift": _dep_lift,
                "dependency_sensitivity": _gq.get("hotspot_dependency_sensitivity"),
                "dependency_specificity": _gq.get("hotspot_dependency_specificity"),
                "dependency_base_rate": _gq.get("hotspot_dependency_base_rate"),
                "_metric_scope": "DepMap genetic-dependency phenotype (Chronos<=-0.5), NOT drug-response/clinical"}

    hyps: list = []
    mut_strat = stratification.get("mutation_stratification_class")
    alt_role = corroboration.get("alteration_role")
    surv = stratification.get("survival_association_class")
    subtype = stratification.get("subtype_stratification_class")
    phospho = corroboration.get("phospho_activity_class")
    # the dependency-correlation corroborators (support a predictive-dependency hypothesis, not roles of their own)
    corr_support = [corroboration.get(f) for f in
                    ("abundance_dependency_class", "correlation_class", "correspondence_class")]

    # PREDICTIVE — genomic stratifier (the strongest, most actionable). Two sub-bases:
    if alt_role == "predictive_biomarker":
        hyps.append({"intended_use": "predictive", "basis": "alteration_role=predictive_biomarker",
                     "evidence_strength": "strong",
                     "_note": "genotype→drug-response predictive hypothesis (OncoKB/IntOGen-classed)."})
    if mut_strat in ("mutant_strongly_dependent", "mutant_moderately_dependent"):
        strength = "strong" if mut_strat == "mutant_strongly_dependent" else "moderate"
        hyp = {"intended_use": "predictive", "basis": f"mutation_stratification_class={mut_strat}",
               "evidence_strength": strength,
               "_note": "mutation-stratified DEPENDENCY (CRISPR) — a dependency-predictive "
                        "hypothesis; NOT auto an inhibitor biomarker (KO removes noncatalytic "
                        "functions). Confirm with a pharmacologic (PRISM) arm before clinical framing."}
        # Thread 3: attach the computed dependency-classification performance. PPV-lift is the
        # informativeness above the panel base-rate — it separates a rare-sharp predictor (high lift)
        # from a common-dependency high-PPV-low-lift marker (the coarse strength label hides this).
        perf = _ppv_perf()
        if perf is not None:
            hyp["dependency_performance"] = perf
        hyps.append(hyp)
    # a dependency-correlation signal WITHOUT a genotype stratifier = a weaker predictive-dependency hypothesis
    if not any(h["intended_use"] == "predictive" for h in hyps) and any(
            v in ("strong_negative", "moderate_negative", "protein_predicts_dependency",
                  "well_modeled_in_lineage", "well_modeled_off_lineage") for v in corr_support):
        hyps.append({"intended_use": "predictive", "basis": "expression/abundance↔dependency correlation",
                     "evidence_strength": "weak",
                     "_note": "abundance/expression correlates with dependency but no genotype stratifier "
                              "— a continuous-biomarker HYPOTHESIS, weakest predictive tier."})

    # PROGNOSTIC — expression↔survival. STRICTLY distinct from predictive.
    if surv in ("expression_high_worse_survival", "expression_high_better_survival"):
        hyps.append({"intended_use": "prognostic", "basis": f"survival_association_class={surv}",
                     "evidence_strength": "weak",
                     "_note": "univariate median-split OS association (stage-UNADJUSTED, hypothesis-"
                              "generating) — a PROGNOSTIC hypothesis, says nothing about drug response."})

    # DIAGNOSTIC_SUBTYPING — a driver alteration that defines a class, or a restricted subtype.
    if alt_role in ("direct_driver_lof", "direct_driver_gof"):
        hyps.append({"intended_use": "diagnostic_subtyping", "basis": f"alteration_role={alt_role}",
                     "evidence_strength": "moderate",
                     "_note": "driver alteration defines a molecular class/subtype; subtyping ≠ predictive "
                              "(a class-defining event need not predict a specific drug's response)."})
    if subtype in ("subtype_restricted", "subtype_enriched"):
        hyps.append({"intended_use": "diagnostic_subtyping", "basis": f"subtype_stratification_class={subtype}",
                     "evidence_strength": "moderate" if subtype == "subtype_restricted" else "weak",
                     "_note": "expression restricted to / enriched in a molecular subtype — a subtyping/"
                              "patient-selection axis."})

    # PHARMACODYNAMIC — a pathway-activity readout usable as a PD marker (not patient-selection).
    if _live(phospho) and phospho not in ("not_phosphoprotein",):
        hyps.append({"intended_use": "pharmacodynamic", "basis": f"phospho_activity_class={phospho}",
                     "evidence_strength": "weak",
                     "_note": "phospho/pathway-activity readout — candidate PD (target-engagement) "
                              "marker, forward-looking; NOT a patient-selection biomarker."})

    return hyps


def _biomarker_facet(sub_results: dict) -> dict:
    """Assemble the biomarker-convergence facet (Q12). Deterministic; additive; verdict-inert.

    Pulls the biomarker-relevant fields each sub-skill surfaces into corroboration_role +
    stratification_role blocks, derives a preferred_assay (RNA | protein | genomic | neither) and a
    facet verdict. Fields not reachable (sub-skill absent, card not composed) are recorded as null —
    an HONEST coverage signal, never fabricated."""
    corroboration: dict = {}
    stratification: dict = {}
    for short, fields in _BIOMARKER_INPUTS.items():
        r = sub_results.get(short)
        if not r:
            continue
        for field, role in fields:
            val = _first_card_summary_field(r, field)
            target_block = corroboration if role == "corroboration" else stratification
            target_block[field] = val

    # preferred_assay: which layer is the trustworthy biomarker readout?
    #   genomic  — a mutant-stratified dependency or predictive_biomarker alteration_role (the
    #              strongest, most actionable stratifier; also the live veto-suppressor)
    #   protein  — RNA is a POOR proxy (Q5), so protein must be measured
    #   RNA      — RNA is an adequate proxy (Q5)
    #   neither  — no adequate stratifier surfaced
    rna_as_biomarker = stratification.get("rna_as_biomarker")
    mut_strat = stratification.get("mutation_stratification_class")
    alt_role = corroboration.get("alteration_role")
    genomic_stratifier = (mut_strat in ("mutant_strongly_dependent", "mutant_moderately_dependent")
                          or alt_role == "predictive_biomarker")
    if genomic_stratifier:
        preferred_assay = "genomic"
    elif rna_as_biomarker == "adequate_proxy":
        preferred_assay = "RNA"
    elif rna_as_biomarker in ("poor_proxy", "partial_proxy"):
        preferred_assay = "protein"
    else:
        preferred_assay = "neither"

    # facet verdict — a FACET summary (confidence/patient-selection role), never a target verdict.
    #   strong_selection_biomarker — a genomic stratifier (mutant-stratified dependency / predictive)
    #   corroborating_only          — corroboration signals present but no patient-selection stratifier
    #   inadequate                  — signals present but RNA is a poor proxy + no genomic stratifier
    #   none                        — nothing biomarker-relevant surfaced
    has_corroboration = any(v not in (None, "data_unavailable", "not_informative")
                            for v in corroboration.values())
    if genomic_stratifier:
        verdict = "strong_selection_biomarker"
    elif preferred_assay == "protein" and not has_corroboration:
        verdict = "inadequate"
    elif has_corroboration or preferred_assay in ("RNA", "protein"):
        verdict = "corroborating_only"
    else:
        verdict = "none"

    # A2a: re-surface the raw statistics behind the categorical classes (strength, not just bucket).
    quantitative = _biomarker_quantitative(sub_results)

    # BEST-role classification (§1): type the assembled signals into a LIST of non-exclusive
    # hypotheses, each naming its intended_use. Kept SEPARATE from the facet verdict (which is a
    # confidence/patient-selection summary) — this answers "what KIND of biomarker(s)", the verdict
    # answers "how strong a selector". Verdict-inert, additive. `quantitative` is passed so a
    # predictive hypothesis can carry the computed dependency-PPV performance (Thread 3).
    biomarker_hypotheses = _classify_biomarker_best_roles(corroboration, stratification, quantitative)
    intended_uses = sorted({h["intended_use"] for h in biomarker_hypotheses})

    return {
        "corroboration_role": corroboration,
        "stratification_role": stratification,
        "quantitative": quantitative,                   # A2a: raw stats behind the classes (verdict-inert)
        "preferred_assay": preferred_assay,
        "verdict": verdict,
        "biomarker_hypotheses": biomarker_hypotheses,   # BEST-role §1: typed, non-exclusive
        "intended_uses": intended_uses,                 # rollup of distinct roles present
        "_disclaimer": ("Biomarker is a FACET, not a gate: it corroborates other gates' verdicts "
                        "(→ confidence) and defines patient-selection (→ stratification); it never "
                        "mints a nomination. biomarker_hypotheses are BEST-role-typed (predictive / "
                        "prognostic / diagnostic_subtyping / pharmacodynamic) + NON-exclusive — a "
                        "target can carry several; predictive and prognostic are kept strictly "
                        "separate. `quantitative` re-surfaces the raw statistics (r / effect size / "
                        "Mann-Whitney q / delta-Chronos / agreement fraction) the cards already "
                        "computed behind each class — strength, not just a bucket. A genomic predictive "
                        "hypothesis now carries `dependency_performance` (PPV / sensitivity / specificity "
                        "/ base-rate / PPV-lift) — a COMPUTED metric on the DepMap genetic-dependency "
                        "phenotype, NOT drug-response or clinical PPV (clinical-PPV/NPV + deployability "
                        "remain uncomputed). null fields = input not reachable this run, not a measured "
                        "negative."),
    }


# --- SUBTYPE convergence facet (capstone Part 3c integration layer) ----------------------------
# The cross-card per-molecular-subtype convergence the capstone owed. Where _biomarker_facet
# converges SCALAR biomarker roles, this converges the PER-STRATUM panoramas: the three
# subtype-grain cards each emit `per_subgroup_metrics` (one record per molecular subtype, carrying
# evidence_state measured/underpowered/absent + a metric), scattered across three sub-skills. Nothing
# assembled them BY SUBTYPE across cards. This facet does: for each molecular subtype, which axes
# (expression / dependency / mutation-frequency) carry a MEASURED signal, and which subtypes have
# ≥2 axes converge (the actionable patient-selection strata). Deterministic, additive, verdict-inert.
#
# (sub_skill_short, card_id, axis_label) — the three subtype-grain panorama cards + where they live.
_SUBTYPE_INPUTS = [
    ("expression",         "tumor-rna-distribution-by-subtype",        "expression"),
    ("dependency",         "subgroup-stratified-dependency",           "dependency"),
    ("genomic_alteration", "subgroup-stratified-mutation-frequency",   "mutation_frequency"),
]


def _first_card_per_subgroup(sub_result: dict, card_id: str) -> list:
    """Return the named card's per_subgroup_metrics list (records per molecular subtype), or []."""
    for c in sub_result.get("cards") or []:
        if c.get("card_id") == card_id:
            return (c.get("summary") or {}).get("per_subgroup_metrics") or []
    return []


def _subtype_stratum_key(rec: dict) -> str | None:
    """The molecular-subtype identity of a per_subgroup_metrics record. Panorama rows use `stratum`
    (subgroup_common.build_panorama); tolerate a few historical aliases. None if unidentifiable."""
    for k in ("stratum", "subgroup_id", "subgroup_label", "subgroup"):
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _load_subtype_crosswalk(indication: str, contracts_repo: Path | None = None) -> dict:
    """Load the indication's block from vocabularies/subtype_crosswalk.yaml. Returns
    {associations: [...], axis_of: {stratum: axis}, cohorts_of: {stratum: [cohorts]}} or empty dicts
    when the registry / indication is absent (graceful — the facet degrades to exact-match only)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "subtype_crosswalk.yaml"
    out = {"associations": [], "axis_of": {}, "cohorts_of": {}}
    if not path.exists():
        return out
    try:
        import yaml
        doc = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return out
    for ind in doc.get("indications", []) or []:
        if ind.get("canonical_code") != indication:
            continue
        out["associations"] = ind.get("associations", []) or []
        for ax in ind.get("axes", []) or []:
            for s in ax.get("strata", []) or []:
                out["axis_of"][s] = ax.get("axis")
                out["cohorts_of"][s] = ax.get("cohorts", []) or []
        break
    return out


def _subtype_facet(sub_results: dict, indication: str = None,
                   contracts_repo: Path | None = None) -> dict:
    """Assemble the per-molecular-subtype CONVERGENCE facet (capstone Part 3c). Deterministic;
    additive; VERDICT-INERT (a synthesis facet, never a gate — informs patient-selection confidence,
    never mints a nominate). Converges the three subtype-grain panoramas BY SUBTYPE:

      per_subtype: {subtype: {axes_measured: [...], axes_present: [...], n_axes_measured, metrics:{}}}
      convergent_subtypes: subtypes with >= 2 MEASURED axes on the SAME stratum id (the strong claim)
      associated_subtypes: pairs of DIFFERENT strata (each measured on its own axis) linked by a
        subtype_crosswalk association (enriched_in / co_defining) — the WEAK, cohort-bridged claim
        that lets MSI_H(dependency, DepMap) relate to CMS1(expression, TCGA) WITHOUT claiming they
        are the same stratum. Each carries the relationship + a cohort_bridge flag when the two axes
        live on different cohorts (e.g. DepMap dependency vs TCGA expression).
      verdict:
        convergent_stratification  — >=1 subtype with >=2 measured axes on the SAME id (strongest)
        associated_stratification  — no same-id convergence, but >=1 registry-linked measured pair
        single_axis_stratification — measured subtype signal on only one axis, no association
        no_subtype_signal          — panoramas present but no measured stratum on any axis
        subtype_axis_unavailable   — no subtype shard reached for this indication (coverage gap)

    Absence is HONEST: a subtype/axis with no measured record contributes nothing (never fabricated).
    The association tier NEVER collapses two strata into one — it reports them as related, with the
    relationship type + cohort bridge explicit, so a CMS finding is never mislabeled an MSI finding."""
    xwalk = _load_subtype_crosswalk(indication, contracts_repo) if indication else \
        {"associations": [], "axis_of": {}, "cohorts_of": {}}
    per_subtype: dict = {}
    axes_seen: set = set()
    any_rows = False
    for short, card_id, axis in _SUBTYPE_INPUTS:
        # Production (_run_sub_skills) resolves the dependency + mutation-frequency subtype
        # cards under the single SUBTYPE_SHORT ('subtype_fit') result, NOT under their per-gate
        # short (the expression subtype card lives under 'expression' / tumor-presence). Search
        # the per-gate short first (matches the synthetic test fixtures), then fall back to
        # subtype_fit (matches production). Without the fallback the dependency + genomic axes
        # were always empty, so >=2-axis convergence was structurally unreachable.
        rows: list = []
        for _src in (short, SUBTYPE_SHORT):
            r = sub_results.get(_src)
            if r:
                rows = _first_card_per_subgroup(r, card_id)
                if rows:
                    break
        if rows:
            any_rows = True
            axes_seen.add(axis)
        for rec in rows:
            subtype = _subtype_stratum_key(rec)
            if not subtype:
                continue
            state = rec.get("evidence_state")
            block = per_subtype.setdefault(subtype, {"axes_measured": [], "axes_present": [],
                                                     "metrics": {}})
            block["axes_present"].append(axis)
            # carry the axis metric (whatever numeric/class the panorama row exposes beyond bookkeeping)
            metric = {k: v for k, v in rec.items()
                      if k not in ("stratum", "subgroup_id", "subgroup_label", "subgroup",
                                   "subgroup_n", "subgroup_n_floor_met", "evidence_state",
                                   "source_cohort") and v is not None}
            if metric:
                block["metrics"][axis] = metric
            if state == "measured":
                block["axes_measured"].append(axis)

    for block in per_subtype.values():
        block["axes_measured"] = sorted(set(block["axes_measured"]))
        block["axes_present"] = sorted(set(block["axes_present"]))
        block["n_axes_measured"] = len(block["axes_measured"])

    convergent = sorted(st for st, b in per_subtype.items() if b["n_axes_measured"] >= 2)
    any_measured = any(b["n_axes_measured"] >= 1 for b in per_subtype.values())

    # ── Association tier (registry-bridged, WEAK): different strata each measured on their own axis,
    # linked by a subtype_crosswalk enriched_in / co_defining association. This is what lets
    # MSI_H(dependency) relate to CMS1(expression) across the vocabulary/cohort gap WITHOUT claiming
    # they are the same stratum. Only strata that are actually MEASURED here participate.
    measured_axes_of = {st: set(b["axes_measured"]) for st, b in per_subtype.items()
                        if b["n_axes_measured"] >= 1}
    associated_pairs = []
    for assoc in xwalk["associations"]:
        a, b_, rel = assoc.get("from"), assoc.get("to"), assoc.get("relationship")
        if rel not in ("enriched_in", "co_defining"):
            continue
        # both endpoints must be measured, and on DIFFERENT axes (else it's not a cross-axis bridge)
        if a not in measured_axes_of or b_ not in measured_axes_of:
            continue
        axes_a, axes_b = measured_axes_of[a], measured_axes_of[b_]
        cross_axis = bool(axes_a - axes_b) or bool(axes_b - axes_a)
        if not cross_axis:
            continue
        # cohort bridge: the two strata's registry cohorts don't overlap (e.g. DepMap dep vs TCGA expr)
        coh_a, coh_b = set(xwalk["cohorts_of"].get(a, [])), set(xwalk["cohorts_of"].get(b_, []))
        cohort_bridge = bool(coh_a and coh_b and not (coh_a & coh_b))
        associated_pairs.append({
            "from": a, "to": b_, "relationship": rel,
            "from_axes_measured": sorted(axes_a), "to_axes_measured": sorted(axes_b),
            "cohort_bridge": cohort_bridge, "note": assoc.get("note", ""),
        })

    if not any_rows:
        verdict = "subtype_axis_unavailable"
    elif convergent:
        verdict = "convergent_stratification"
    elif associated_pairs:
        verdict = "associated_stratification"
    elif any_measured:
        verdict = "single_axis_stratification"
    else:
        verdict = "no_subtype_signal"

    return {
        "verdict": verdict,
        "convergent_subtypes": convergent,
        "associated_subtypes": associated_pairs,
        "n_subtypes_evaluated": len(per_subtype),
        "axes_available": sorted(axes_seen),
        "per_subtype": per_subtype,
        "_disclaimer": ("Subtype is a FACET, not a gate: it converges the per-molecular-subtype "
                        "panoramas (expression / dependency / mutation-frequency) BY SUBTYPE to "
                        "surface cross-axis patient-selection strata. It informs confidence + "
                        "patient-selection, never mints a nominate. convergent_subtypes = subtypes "
                        "with >=2 MEASURED axes on the SAME stratum id (strong). associated_subtypes "
                        "= DIFFERENT strata each measured on its own axis, linked by a "
                        "subtype_crosswalk enriched_in/co_defining association (weak, cohort-bridged) "
                        "— reported as RELATED, never as the same stratum (a CMS finding is never "
                        "relabeled an MSI finding); cohort_bridge=true flags a DepMap-vs-TCGA cross. "
                        "subtype_axis_unavailable = no shard for this indication (coverage gap), not "
                        "a measured negative."),
    }


# --- Positive tier (deterministic confidence FLOOR; F1-safe) ----------------
#
# Graded positives (dependency/selectivity/small-molecule tractability) raise an
# AUDITABLE confidence tier (strong/moderate) instead of being LLM-advisory only.
# STRICTLY F1-SAFE: this is computed ONLY when NO kill fired (the else-branch of
# the gate clamp in main), so a positive can never mask a kill; and it writes ONLY
# to `confidence` as a FLOOR, never to `overall_recommendation` — it cannot force
# `nominate`. Policy in target-contracts/vocabularies/nomination_verdict_gate.yaml.
#
# INVERTED FALLBACK vs the kill gate: the kill loader falls back conservative-and-
# complete (missing vocab still fires vetoes). The positive loader falls back to
# EMPTY (missing/malformed vocab → no positive tier, LLM confidence stands) — it must
# NEVER mint a spurious `strong`.
_CONFIDENCE_RANK = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}
_TIER_TO_CONFIDENCE = {"strong": "high", "moderate": "medium"}


def _load_positive_signals(contracts_repo: Path | None = None) -> tuple[dict, set, dict, str]:
    """Load the positive-tier policy. Returns
    (positive_map: {(short,verdict): weight}, contradiction_set: {(short,verdict)},
     config: dict, source). EMPTY-on-failure (never permissive)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        pos = {(p["sub_skill"], p["verdict"]): p["weight"] for p in data["positive_signals"]}
        contra = {(c["sub_skill"], c["verdict"]) for c in data["positive_contradictions"]}
        cfg = data["positive_tier_config"]
        if not pos:
            raise ValueError("empty positive_signals")
        return pos, contra, cfg, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no positive tier)
        print(f"[target-profile] WARN: could not load positive_signals vocab "
              f"({type(e).__name__}: {e}); positive tier DISABLED (LLM confidence stands).",
              file=sys.stderr)
        return {}, set(), {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True}, "fallback"


def _positive_tier(
    sub_results: dict, contracts_repo: Path | None = None
) -> tuple[Optional[str], list[dict]]:
    """Deterministic confidence tier from graded positive sub-verdicts.

    Returns (tier | None, hits). tier ∈ {strong, moderate}. None = no positive
    signal (LLM confidence stands). MUST be called only when no kill fired (caller
    guards this) — but it is also self-safe: it reads only positive_signals and
    never emits an action. A contradiction (opposing MEASURED verdict on a
    positive-eligible axis) blocks `strong`. insufficient/data_unavailable are NOT
    contradictions (measured-vs-null).
    """
    pos_map, contra_set, cfg, _src = _load_positive_signals(contracts_repo)
    if not pos_map:
        return None, []
    hits: list[dict] = []
    contradicted = False
    for short, r in sub_results.items():
        v = r.get("verdict")
        if not v:
            continue
        verdict_str = v[0]
        if (short, verdict_str) in contra_set:
            contradicted = True
            continue
        weight = pos_map.get((short, verdict_str))
        if weight:
            hits.append({"short": short, "verdict": verdict_str, "weight": weight,
                         "driving_rule_id": v[1] if len(v) > 1 else None})
    if not hits:
        return None, []
    n_dims = len({h["short"] for h in hits})
    has_dominant = any(h["weight"] == "dominant" for h in hits)
    min_dims = cfg.get("min_dimensions_for_strong", 2)
    require_dom = cfg.get("require_dominant_for_strong", True)
    strong_ok = (n_dims >= min_dims and (has_dominant or not require_dom)
                 and not contradicted)
    tier = "strong" if strong_ok else "moderate"
    return tier, hits


# --- Fragility facet (verdict-inert flip-stability; the quantitative "how solid is this call?") ---
#
# Bounded uncertainty WITHOUT probability. For each DECISION-RELEVANT axis (an axis whose verdicts the
# nomination gate / positive tier / veto-suppressors actually read), run the single-rule flip scan
# (flip_analysis) on that axis's resolver and measure how easily the call moves. Three fragilities:
#   raw_flip_fragility            — fraction of verdict-movable rules whose toggle changes the STRING.
#   decision_flip_fragility       — fraction whose toggle changes the axis's DECISION ROLE (kill /
#                                   positive / contradiction / neutral). A lineage_selective ->
#                                   selective_dependent flip changes the string but both are `positive`,
#                                   so it is NOT a decision flip (the KRAS anchor).
#   recommendation_flip_fragility — fraction whose toggle CROSSES THE KILL BOUNDARY (enters/leaves a
#                                   gate action). These are the ONLY flips that can move
#                                   overall_recommendation; positive<->contradiction<->neutral flips
#                                   change CONFIDENCE, not the Go/No-Go.
# TWO target-level indices (both worst-case/max over axes, never a mean — mirroring the gate's
# max-over-action-ranks): target_index = worst CALL fragility (how solid each axis's call is;
# informative); recommendation_fragility_index = worst RECOMMENDATION fragility, and this is what DRIVES
# `contested`. An axis the framework could not evidence (no signal) is an EVIDENCE GAP not a fragile
# verdict — tracked separately in blind_decision_axes (fragility None), never folded into either index.
#
# STRICTLY VERDICT-INERT: reads sub_results, never calls _gate_recommendation, never writes
# overall_recommendation / confidence. Emitted as a nomination.json facet; it MAY set a categorical
# `contested` flag (from a declarative threshold) that a reader/banner surfaces — the flag NEVER
# changes the recommendation. `contested` is None when no threshold is configured (absence must not
# fabricate a flag); the numeric indices are emitted regardless.
_FRAGILITY_LEGEND = (
    "Verdict FRAGILITY (flip-stability): re-runs the deterministic resolver over single-rule-perturbed "
    "fired sets. target_index = worst-case fraction of a gate's verdict-movable rules whose toggle "
    "changes its DECISION ROLE (how solid each axis's CALL is). recommendation_fragility_index = worst "
    "case whose toggle crosses the KILL boundary (how solid the GO/NO-GO is) — this drives `contested`. "
    "0 = robust; higher = a call one plausible rule-change could flip. A structural sensitivity "
    "measure — NOT a probability the target succeeds, and never summed or averaged."
)


def _load_contested_threshold(contracts_repo: Path | None = None) -> Optional[dict]:
    """Load the optional `contested_threshold` stanza from the nomination-gate vocab, or None if
    absent/malformed. NEVER-FABRICATE contract: absence → None → the facet emits contested=None (no
    flag). A missing threshold can only make the facet emit LESS (no contested), never fabricate one;
    and the flag is verdict-inert either way, so this is safe."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        ct = data.get("contested_threshold")
        if isinstance(ct, dict) and isinstance(ct.get("fragility_index_min"), (int, float)):
            return ct
        return None
    except Exception:  # noqa: BLE001 — absence/parse failure → no contested flag (verdict-inert)
        return None


def _decision_role(short: str, verdict: str,
                   gate_map: dict, pos_map: dict, contra_set: set) -> str:
    """The axis's role in the nomination decision for a given verdict: 'kill:<action>' /
    'positive:<weight>' / 'contradiction' / 'neutral'. Pure lookup over the loaded vocab maps."""
    if (short, verdict) in gate_map:
        return f"kill:{gate_map[(short, verdict)]}"
    if (short, verdict) in pos_map:
        return f"positive:{pos_map[(short, verdict)]}"
    if (short, verdict) in contra_set:
        return "contradiction"
    return "neutral"


def _subgroup_flip_view(sub_results: dict) -> dict:
    """Descriptive per-stratum heterogeneity view (only under --subtypes). Reports the POOLED
    dependency verdict alongside the subtype panorama's per-stratum rows, so a reader can see when a
    pooled call hides a stratified pattern ("pooled non_dependent, but stratum X shows a measured
    dependency"). DESCRIPTIVE, not a re-resolved per-stratum verdict: it surfaces the panorama's own
    per_subgroup_metrics (evidence_state + metric); the resolver-backed subtype call is
    subtype_fit_verdict. (A full per-stratum re-resolution is the deferred Tier-1 heterogeneity work.)"""
    dep = sub_results.get("dependency") or {}
    dep_v = dep.get("verdict")
    subtype_r = sub_results.get(SUBTYPE_SHORT) or {}
    subtype_v = subtype_r.get("verdict")
    rows = []
    for rec in _first_card_per_subgroup(subtype_r, "subgroup-stratified-dependency"):
        st = _subtype_stratum_key(rec)
        if not st:
            continue
        rows.append({
            "stratum": st,
            "evidence_state": rec.get("evidence_state"),
            "subgroup_n_floor_met": rec.get("subgroup_n_floor_met"),
            "metric": {k: v for k, v in rec.items()
                       if k not in ("stratum", "subgroup_id", "subgroup_label", "subgroup",
                                    "subgroup_n", "subgroup_n_floor_met", "evidence_state",
                                    "source_cohort") and v is not None},
        })
    return {
        "pooled_dependency_verdict": dep_v[0] if dep_v else None,
        "subtype_fit_verdict": subtype_v[0] if subtype_v else None,
        "per_stratum_dependency": rows,
        "_note": ("Descriptive per-stratum view (--subtypes): the subtype panorama's own "
                  "per_subgroup_metrics beside the POOLED dependency verdict, to expose a stratified "
                  "pattern the pooled call hides. NOT a re-resolved per-stratum verdict; the "
                  "resolver-backed subtype call is subtype_fit_verdict."),
    }


def _fragility_facet(sub_results: dict, subtypes: Optional[list[str]] = None,
                     contracts_repo: Path | None = None) -> dict:
    """Verdict-inert flip-stability facet (see section header). Emitted in nomination.json; never
    touches the verdict / gate / recommendation."""
    gate_map, _gsrc = _load_gate_verdicts(contracts_repo)
    pos_map, contra_set, _cfg, _psrc = _load_positive_signals(contracts_repo)
    baseline, _covsrc = _load_gate_coverage(contracts_repo)

    # Decision-relevant axes = every sub_skill short the gate / positive / contradiction vocab reads.
    decision_shorts = ({s for (s, _v) in gate_map} | {s for (s, _v) in pos_map}
                       | {s for (s, _v) in contra_set})

    per_axis: dict = {}
    fragilities: list[float] = []           # worst-case CALL fragility (any decision-role change)
    rec_fragilities: list[float] = []       # worst-case RECOMMENDATION fragility (kill-boundary crossing)
    blind_decision_axes: list[str] = []
    for short in sorted(decision_shorts):
        r = sub_results.get(short)
        if r is None:
            continue  # a decision-relevant axis not present this run (e.g. subtype_fit w/o --subtypes)
        has_signal = _sub_result_has_signal(r)
        coverage = _run_coverage_for_short(short, r, baseline)
        gate = _SHORT_TO_GATE.get(short)

        if not has_signal:
            # An un-evidenced axis is an EVIDENCE GAP, not a fragile verdict (measured-vs-null
            # discipline): it has no verdict to flip. Tracked separately, NOT folded into the flip
            # index — coverage/blindness is the deciding-axis router's responsibility, not fragility's.
            per_axis[short] = {"gate": gate, "flip_applicable": bool(gate), "has_signal": False,
                               "coverage": coverage, "fragility": None, "reason": "blind"}
            blind_decision_axes.append(short)
            continue

        if gate is None:
            # decision-relevant but no resolver to flip (e.g. `expression` presence positive): it has
            # signal but no flip scan, so it informs coverage, not the index.
            per_axis[short] = {"gate": None, "flip_applicable": False, "has_signal": True,
                               "coverage": coverage, "fragility": None, "reason": "no_resolver_gate"}
            continue

        fa = flip_analysis(r.get("fired") or [], gate, contracts_repo)
        if fa is None:
            per_axis[short] = {"gate": gate, "flip_applicable": False, "has_signal": True,
                               "coverage": coverage, "fragility": None, "reason": "resolver_absent"}
            continue

        base_role = _decision_role(short, fa["base_verdict"], gate_map, pos_map, contra_set)
        base_kill = base_role.startswith("kill:")   # base verdict maps to a gate action (veto/hold)
        decision_flips = []
        n_rec_flips = 0
        for f in fa["flips"]:
            to_role = _decision_role(short, f["to_verdict"], gate_map, pos_map, contra_set)
            if to_role == base_role:
                continue                              # raw flip but same decision role (e.g. lineage↔selective)
            # A RECOMMENDATION flip crosses the KILL boundary (enters/leaves a gate action) — the only
            # flips that can move overall_recommendation. Role changes AMONG positive/contradiction/
            # neutral change CONFIDENCE, not the Go/No-Go — so they are call-fragile, not recommendation-
            # fragile (this is why KRAS, fragile only on the selectivity CONTRADICTION, is not contested).
            rec = base_kill != to_role.startswith("kill:")
            if rec:
                n_rec_flips += 1
            decision_flips.append({"rule_id": f["rule_id"], "present": f["present"],
                                   "to_verdict": f["to_verdict"], "to_role": to_role,
                                   "recommendation_flip": rec})
        n_rel = fa["n_relevant"]
        decision_fragility = (len(decision_flips) / n_rel) if n_rel else 0.0
        rec_fragility = (n_rec_flips / n_rel) if n_rel else 0.0
        per_axis[short] = {
            "gate": gate, "flip_applicable": True, "has_signal": True, "coverage": coverage,
            "base_verdict": fa["base_verdict"], "base_driver": fa["base_driver"],
            "base_role": base_role, "n_relevant": n_rel,
            "raw_flip_fragility": round(fa["flip_fragility"], 4),
            "decision_flip_fragility": round(decision_fragility, 4),
            "recommendation_flip_fragility": round(rec_fragility, 4),
            "decision_flips": decision_flips,
            "fragility": round(decision_fragility, 4),
        }
        fragilities.append(decision_fragility)
        rec_fragilities.append(rec_fragility)

    # target_index = worst-case CALL fragility (how solid is each axis's own call — informative).
    # recommendation_fragility_index = worst-case fragility of the GO/NO-GO ACTION itself, and it is what
    # DRIVES `contested` — a call can be fragile (selectivity discordant) while the recommendation is rock
    # solid, and only the latter should raise a contested banner.
    target_index = round(max(fragilities), 4) if fragilities else None
    recommendation_fragility_index = round(max(rec_fragilities), 4) if rec_fragilities else None

    ct = _load_contested_threshold(contracts_repo)
    contested = None
    if ct is not None and recommendation_fragility_index is not None:
        contested = recommendation_fragility_index >= ct["fragility_index_min"]

    facet = {
        "target_index": target_index,
        "recommendation_fragility_index": recommendation_fragility_index,
        "contested": contested,
        "decision_relevant_axes": sorted(decision_shorts),
        "blind_decision_axes": blind_decision_axes,
        "per_axis": per_axis,
        "_basis": "target_index = worst-case DECISION-flip (any role change: how solid is each axis's "
                  "call). recommendation_fragility_index = worst-case KILL-boundary-crossing flip (how "
                  "solid the Go/No-Go ACTION is) and DRIVES `contested`. single-rule scan; blind axes "
                  "tracked separately (coverage != fragility), never folded into either index.",
        "_legend": _FRAGILITY_LEGEND,
        "_contested_threshold": ct,
    }
    if subtypes:
        facet["subgroup_flips"] = _subgroup_flip_view(sub_results)
    return facet


def _find_card_summary(sub_results: dict, card_id: str) -> dict:
    """First matching card's summary dict across all sub-results (source-short-agnostic), or {}."""
    for r in sub_results.values():
        for c in (r.get("cards") or []):
            if c.get("card_id") == card_id:
                return c.get("summary") or {}
    return {}


def _cv(vals: list) -> "Optional[float]":
    """Coefficient of variation (population stdev / |mean|) over >=2 numerics; None otherwise."""
    xs = [v for v in vals if isinstance(v, (int, float))]
    if len(xs) < 2:
        return None
    import statistics
    m = statistics.mean(xs)
    return (statistics.pstdev(xs) / abs(m)) if m != 0 else None


def _norm_entropy(labels: list) -> "Optional[float]":
    """Shannon entropy of a label multiset, normalized to 0..1 by log(#distinct); None if <2 labels."""
    xs = [x for x in labels if x]
    if len(xs) < 2:
        return None
    import math
    from collections import Counter
    counts = Counter(xs)
    if len(counts) < 2:
        return 0.0
    n = len(xs)
    h = -sum((c / n) * math.log(c / n) for c in counts.values())
    return h / math.log(len(counts))


# --- Heterogeneity facet (verdict-inert; cross-stratum / -comparator / -modality DISPERSION) --------
#
# Companion to fragility: fragility asks "how easily does the CALL move?"; heterogeneity asks "does a
# single pooled verdict HIDE a split?" — a target strong in some strata/comparators/assays and absent
# in others. NARROW by design (round-2 review): dispersion is only computable where the underlying
# MULTI-VALUE data survives — the tumor-vs-normal four-cell (always), CRISPR-vs-RNAi fraction_agree
# (always), and the per-molecular-subtype dependency panorama (ONLY under --subtypes; not pulled
# otherwise). Most pooled cards carry no per-value array, so a GENERAL cross-cohort dispersion is
# deliberately NOT attempted (needs method-layer plumbing). heterogeneity_index = worst-case over the
# available NORMALIZED (0..1) signals. STRICTLY VERDICT-INERT: emitted in nomination.json; never
# touches overall_recommendation / confidence.
_HETEROGENEITY_LEGEND = (
    "Cross-context HETEROGENEITY (dispersion): does a pooled verdict hide a split? Worst-case over the "
    "available normalized signals — tumor-vs-normal comparator disagreement (four-cell), CRISPR-vs-RNAi "
    "modality disagreement (1-fraction_agree), and (only under --subtypes) per-subtype dependency "
    "spread (class entropy / metric CV over floor-cleared strata). 0 = uniform; higher = a stratified "
    "opportunity the pooled call hides. NOT a probability; never summed or averaged."
)


def _heterogeneity_facet(sub_results: dict, subtypes: "Optional[list[str]]" = None) -> dict:
    """Verdict-inert cross-context dispersion facet (see section header). Emitted in nomination.json;
    never touches the verdict / gate / recommendation."""
    sources: dict = {}
    signals: list = []

    # (1) tumor-vs-normal four-cell comparator dispersion
    sel = _find_card_summary(sub_results, "tumor-vs-normal-selectivity")
    ran, sup = sel.get("cells_ran"), sel.get("cells_supporting")
    if isinstance(ran, (int, float)) and ran and isinstance(sup, (int, float)):
        unsupported = 1.0 - (sup / ran)
        disc = bool(sel.get("discordant"))
        logs_cv = _cv([sel.get("log2fc_cell_a"), sel.get("log2fc_cell_b"), sel.get("log2fc_cell_c")])
        disp = 1.0 if disc else round(unsupported, 4)   # an explicit discordant read is maximal dispersion
        sources["selectivity_comparators"] = {
            "cells_ran": ran, "cells_supporting": sup, "unsupported_fraction": round(unsupported, 4),
            "discordant": disc, "log2fc_cv": round(logs_cv, 4) if logs_cv is not None else None,
            "dispersion": disp}
        signals.append(disp)

    # (2) CRISPR-vs-RNAi modality dispersion
    conc = _find_card_summary(sub_results, "crispr-rnai-dependency-concordance")
    fa = conc.get("fraction_agree")
    if isinstance(fa, (int, float)):
        disp = round(1.0 - fa, 4)
        sources["modality_crispr_rnai"] = {"fraction_agree": round(fa, 4), "dispersion": disp}
        signals.append(disp)

    # (3) per-molecular-subtype dependency spread — only when --subtypes scoped (panorama present)
    if subtypes:
        rows = _first_card_per_subgroup(sub_results.get(SUBTYPE_SHORT) or {},
                                        "subgroup-stratified-dependency")
        measured = [r for r in rows
                    if r.get("evidence_state") == "measured" and r.get("subgroup_n_floor_met")]
        if len(measured) >= 2:
            metric_cv = _cv([r.get("median_chronos") for r in measured])
            ent = _norm_entropy([r.get("dependency_class") or r.get("_dependency_class") for r in measured])
            disp = ent if ent is not None else (min(metric_cv, 1.0) if metric_cv is not None else None)
            sources["subtype_strata"] = {
                "n_measured_strata": len(measured),
                "class_entropy": round(ent, 4) if ent is not None else None,
                "metric_cv": round(metric_cv, 4) if metric_cv is not None else None,
                "dispersion": round(disp, 4) if disp is not None else None}
            if disp is not None:
                signals.append(disp)

    return {
        "heterogeneity_index": round(max(signals), 4) if signals else None,
        "sources": sources,
        "_basis": "worst_case over available normalized cross-context dispersion signals "
                  "(selectivity four-cell / crispr-rnai concordance / subtype strata [--subtypes only])",
        "_legend": _HETEROGENEITY_LEGEND,
    }


# --- Addressable-population facet (patient-population layer, reconstructed as composition) ----------
_ADDRESSABLE_POPULATION_LEGEND = (
    "Estimated fraction of the indication addressable by the target's SELECTION BASIS. For an "
    "alteration-stratified / mutation-driver target the addressable population is the in-indication "
    "PREVALENCE of the defining SNV/indel (coverage-correct GENIE preferred — ~35x the MC3 sample "
    "count; MC3 fallback); for a broad (unstratified) dependency it is biomarker_unrestricted (the "
    "indication itself); a CN/fusion-defined subgroup is not_estimated_this_axis (SNV frequency is the "
    "wrong denominator — CN/fusion prevalence is a v2 extension). VERDICT-INERT: population-sizing "
    "context beside the nomination, never a gate input."
)

# clinical addressable-population tiers by alteration prevalence
def _addressable_population_class(freq: "float | None") -> "str | None":
    if not isinstance(freq, (int, float)):
        return None
    if freq >= 0.20:
        return "broad"            # e.g. KRAS/TP53 in COADREAD (~40%)
    if freq >= 0.05:
        return "common"
    if freq >= 0.01:
        return "uncommon"
    if freq >= 0.001:
        return "rare"
    return "ultra_rare"

# genomic verdicts whose actionability is TIED TO AN SNV/indel ALTERATION → population = its prevalence
_SNV_SELECTION_VERDICTS = frozenset({
    "biomarker_stratified_dependency", "moderate_biomarker_dependency", "confirmed_driver",
    "multi_class_driver", "missense_dominant_pattern", "lof_dominant_pattern", "drug_response_biomarker",
})
_CN_FUSION_SELECTION_VERDICTS = frozenset({
    "recurrent_amplification_driver", "recurrent_deletion_driver", "recurrent_fusion_driver",
})
_NON_DEPENDENT = frozenset({"non_dependent", "insufficient", "data_unavailable", ""})


def _addressable_population_facet(sub_results: dict) -> dict:
    """VERDICT-INERT addressable-population facet — joins the target's SELECTION BASIS (what defines the
    treatable subgroup, from the genomic + dependency verdicts) to the in-indication PREVALENCE of that
    basis (from mutation-hotspot-frequency: genie_mutation_frequency preferred, overall_mutation_frequency
    fallback). Reconstructs the deleted patient-population-and-access layer as a composition over signals
    already on the fan-out. Emitted in nomination.json + the synthesis prompt; never touches the gate."""
    gen = (sub_results.get("genomic_alteration") or {}).get("verdict")
    gen_verdict = gen[0] if gen else None
    dep = (sub_results.get("dependency") or {}).get("verdict")
    dep_verdict = dep[0] if dep else None

    hf = _find_card_summary(sub_results, "mutation-hotspot-frequency")
    genie_freq = hf.get("genie_mutation_frequency")
    mc3_freq = hf.get("overall_mutation_frequency")
    n_samples = hf.get("n_samples_in_indication")
    freq, source = ((genie_freq, "genie") if isinstance(genie_freq, (int, float))
                    else (mc3_freq, "tcga_mc3") if isinstance(mc3_freq, (int, float))
                    else (None, None))

    if gen_verdict in _SNV_SELECTION_VERDICTS:
        basis = "snv_indel_stratified"
        pop_class = _addressable_population_class(freq)
        note = None
    elif gen_verdict in _CN_FUSION_SELECTION_VERDICTS:
        basis = "copy_number_or_fusion_stratified"
        pop_class, freq, source = "not_estimated_this_axis", None, None
        note = ("addressable population is defined by a CN/fusion event; SNV frequency is inapplicable "
                "— CN/fusion prevalence (copy-number-distribution / fusion cards) is a v2 extension")
    elif dep_verdict and dep_verdict not in _NON_DEPENDENT:
        basis = "biomarker_unrestricted"
        pop_class = "biomarker_unrestricted"
        note = ("a broad dependency with no alteration-defined selection biomarker; the addressable "
                "population is the indication itself")
    else:
        basis = "undetermined"
        pop_class = None
        note = ("no alteration-selection verdict and no positive dependency to anchor an "
                "addressable-population estimate")

    return {
        "addressable_population_class": pop_class,
        "selection_basis": basis,
        "biomarker_prevalence": round(freq, 4) if isinstance(freq, (int, float)) else None,
        "prevalence_source": source,
        "n_samples_in_indication": n_samples,
        "_note": note,
        "_legend": _ADDRESSABLE_POPULATION_LEGEND,
    }


# --- LLM synthesis ----------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are synthesizing a target-profile summary for a drug-discovery "
    "scientist at a major pharma. You will be given deterministic, rule-"
    "derived sub-verdicts from up to 10 evidence dimensions (expression, "
    "selectivity, dependency, mechanism, mutation, differentiation, "
    "tractability, safety, population, cohort_rank). Your job is to (a) "
    "write a concise executive summary, (b) surface any tension across "
    "the sub-verdicts, (c) list top arguments for and against pursuing "
    "this target, and (d) recommend a nomination action. Base every "
    "claim on the provided evidence. Do NOT invent biology. If evidence "
    "is thin or missing for a dimension, say so explicitly rather than "
    "filling with generalities. Note (arch A2): the tractability sub-"
    "verdict emits letter grades (adc_grade, tce_grade) ONLY when the "
    "modality lens was invoked at runtime — if those fields are absent, "
    "reason from the biology-agnostic fit_class categorical instead. "
    "Note (arch A3): the mechanism sub-verdict flags isoform-selective "
    "targets (e.g., ERBB2/p95HER2, AR/AR-V7, MET/exon14, EGFR/vIII); if "
    "isoform_selective_warning is true, gene-level modality claims should "
    "be qualified with isoform-resolution caveats. "
    "Note (matrix view): you are also given a modality-scoped evidence matrix "
    "(gate x modality). It is a REPROJECTION of the same signals, NOT new "
    "evidence and NOT a score — use it to reason about WHICH MODALITY each gate "
    "favors (e.g. a degrader-preferred vs small-molecule split) and to ground the "
    "modality framing of your recommendation. The ordinals are order-preserving, "
    "NOT calibrated: never sum or average them, and treat off-scale cells "
    "(insufficient/not_applicable) as coverage gaps, not low scores. When a matrix "
    "cell disagrees with a gate's resolved verdict, the VERDICT is the decision — "
    "the cell is the raw per-modality signal behind it. "
    "Note (altitude): your PRIMARY job is the INTEGRATED relevance case — reason across the biology "
    "lenses (expression, selectivity, dependency, mechanism, mutation, safety) to a recommendation. "
    "Modality is a SECONDARY, supporting dimension: discuss it AFTER the relevance case has been made, "
    "not as the headline. "
    "Note (register): write to scientific-publication standard — the voice of a methods/results "
    "section. Declarative, precise, factual; complete sentences; active voice. Report each number with "
    "its scale and direction, never bare. Do NOT use promotional or editorialising language (avoid "
    "'promising', 'exciting', 'compelling', 'robustly', 'clearly'); let the evidence carry the claim. "
    "Concise but readable — a domain biologist who is not a statistician must follow it without a "
    "glossary. On FIRST use of a technical metric, add a short plain-language parenthetical gloss (e.g. "
    "Chronos knockout fitness score ~ -1 = a typically essential gene; ε² = fraction of variation a "
    "grouping explains, ~0.14 large; log2 fold-change +1 = 2x). A deterministic metric_legend is also "
    "attached to the output for reference. "
    "Note (biology-axis governance): you may be given a MODALITY-EMPHASIS GOVERNANCE block stating the "
    "target's curated biology_axis (intracellular vs surface) and its plausible modalities. WHEN you "
    "discuss modality, RESPECT it — do not propose ADC/T-cell-engager/CAR for an intracellular target "
    "(or small-molecule-occupancy for a purely surface antigen) unless a fired rule overrides the axis. "
    "The block keeps modality talk biologically honest; it does NOT make modality the lead, and it never "
    "changes the deterministic verdict or recommendation (the gate owns those)."
    + _EVIDENCE_ONLY_DIRECTIVE
)

# Cross-cutting plain-language legend for the metrics the COMPOSED synthesis may cite across lenses.
# Attached to the LLM output as a sibling key (metric_legend) so a non-computational reader has an
# accurate, byte-stable reference independent of the LLM's inline glosses. Superset of the per-lens
# METRIC_LEGENDs in _skills_common/synthesis_*.py (this composed view spans all lenses).
_METRIC_LEGEND = {
    "chronos_score": ("CRISPR knockout fitness score (dependency lens). 0 = knockout does not affect "
                      "growth; ~ -1 = a typically essential gene; more negative = stronger dependency. "
                      "A pan-essential-level score is a broad-toxicity liability, not a target win."),
    "log2_fold_change": ("log2 of a ratio (e.g. tumour vs normal expression). +1 = 2x higher, 0 = no "
                         "difference. Used by the expression/selectivity lenses."),
    "allgene_percentile": ("Where a target ranks among ALL genes in the same cohort (0-100) — the "
                           "'relative to what?' frame for abundance (presence) or fold-change "
                           "(selectivity)."),
    "epsilon_squared": ("ε² (epsilon-squared): the fraction of a signal's variation across a grouping "
                        "(molecular subtype, or lineage for dependency) that the grouping explains, "
                        "0-1. ~0.06 moderate, ~0.14 large. Large = concentrated in a subgroup."),
    "driver_recurrence_percentile": ("Where a gene's mutation recurrence ranks among all mutated genes "
                                     "in the indication (mutation lens). High = recurrent beyond the "
                                     "passenger background; frequency is not function."),
    "alteration_role": ("Curated functional call (OncoKB x IntOGen): GoF (activating oncogene), LoF "
                        "(tumour suppressor), predictive_biomarker, or passenger."),
    "fit_class": ("Surface-modality-fit verdict: ADC_preferred / TCE_preferred / both_viable / "
                  "neither_viable — whether surface biology (topology, family) supports a biologics "
                  "modality. Distinct from the small-molecule tractability call."),
    "ordinal_matrix": ("A gate x modality reprojection of the same signals into order-preserving "
                       "ordinals — NOT a calibrated score; never summed or averaged. Off-scale cells "
                       "(insufficient / not_applicable) are coverage gaps, not low scores."),
    "verdict_fragility": ("Flip-stability (fragility facet): re-runs the deterministic resolver over "
                          "single-rule-perturbed fired sets. target_index = worst-case fraction of a "
                          "gate's verdict-movable rules whose toggle changes the DECISION ROLE (how "
                          "solid each axis's CALL is). recommendation_fragility_index = worst-case whose "
                          "toggle crosses the KILL boundary (how solid the GO/NO-GO is) — this drives "
                          "the `contested` banner. 0 = robust. Blind (un-evidenced) axes are a coverage "
                          "gap tracked separately, not folded in. A structural sensitivity measure — NOT "
                          "a probability the target succeeds, never summed/averaged, never moves the "
                          "recommendation."),
}


def _build_synthesis_tool() -> dict:
    """Tool schema for the LLM synthesis call. Enums are the audit-critical
    fields — LLM cannot free-form the recommendation."""
    return {
        "description": (
            "Emit a structured target-profile summary composed of one "
            "executive summary paragraph, tension analysis, top "
            "arguments for/against, and an overall recommendation."
        ),
        "type": "object",
        "required": [
            "executive_summary", "tension_analysis",
            "top_arguments_for", "top_arguments_against",
            "overall_recommendation", "confidence",
        ],
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": (
                    "3-5 sentence synthesis of what the (up to 10) sub-verdicts "
                    "collectively imply for this (target, indication)."
                ),
            },
            "tension_analysis": {
                "type": "string",
                "description": (
                    "Where sub-verdicts disagree and why — e.g. tumor-"
                    "selectivity says discordant while functional-"
                    "requirement says lineage_selective. If there's no "
                    "meaningful tension, say so briefly (do not invent)."
                ),
            },
            "top_arguments_for": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest positive arguments.",
            },
            "top_arguments_against": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest negative arguments.",
            },
            "overall_recommendation": {
                "type": "string",
                "enum": ["nominate", "hold", "veto", "insufficient_evidence"],
                "description": (
                    "Nomination action: nominate = pursue; hold = "
                    "revisit after specific evidence gaps close; veto = "
                    "do not pursue; insufficient_evidence = cannot call."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "insufficient"],
                "description": (
                    "Analyst-facing confidence in the recommendation. "
                    "'insufficient' iff overall_recommendation is "
                    "insufficient_evidence."
                ),
            },
        },
    }


def _render_matrix_slice_for_prompt(ordinal_matrix: dict) -> list[str]:
    """The gate × modality ordinal matrix as prompt text (gap #4b): lets synthesis reason over
    the MATRIX-SLICE (which modality does each gate favor?) instead of only the flat verdict list.
    Emphatically labeled a REPROJECTION of the same signals — not new evidence, not a score."""
    cols = ordinal_matrix["axes"]["columns"]
    leg = ordinal_matrix["legend"]
    lines = [
        "### Modality-scoped evidence matrix (a VIEW — reprojection, NOT new evidence)",
        "Each cell is the STRONGEST signal a gate emits for that modality, on an ORDER-PRESERVING "
        "ordinal scale (NOT calibrated — gaps are not metric). Use it to see WHICH MODALITY each "
        "gate favors (e.g. a degrader-preferred vs small-molecule-opposing split) — a nuance the "
        "flat verdict list flattens. A cell can differ from the resolved verdict (the cell is the "
        "raw signal; the verdict is the ordered-precedence decision). The verdict is the decision; "
        "the matrix is for modality reasoning only. Do NOT sum or average the ordinals.",
        "Scale: " + ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(),
                                                               key=lambda t: -t[1]))
        + f"; off-scale (coverage, not a low score): {', '.join(leg['off_scale'])}; `·` = no signal.",
        "",
        "| gate | " + " | ".join(cols) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]
    for row in ordinal_matrix["rows"]:
        cells = row["cells"]
        glyphs = " | ".join(ordinal_view._cell_glyph(cells[m]) for m in cols)
        lines.append(f"| {row['short']} | {glyphs} |")
    lines.append("")
    return lines


# Distribution-evidence field patterns that MUST survive to the LLM prompt intact (the Audit-B /
# 12-question-spec extraction layer emits these; the old blind truncation loop collapsed lists>5 and
# hard-capped at 1200 chars/card, destroying exactly the per-sample distribution signal the spec is
# about). Substring-matched against summary keys. Scalars always survive; only genuinely-oversized
# UNKNOWN lists get sampled.
_LOAD_BEARING_SUMMARY_KEY_PARTS = (
    "median", "percentile", "_pct", "p95", "p99", "p5", "p25", "p75",
    "fraction", "frac_", "coefficient_of_variation", "cov", "distribution_pattern",
    "log2fc", "log2_fc", "effect_size", "q_value", "bh_q", "class", "n_tumor", "n_normal",
    "n_cohorts", "n_indications", "concordance", "correlation", "enrich", "above_normal",
    "tumor_median", "normal_median", "detectable", "expressed",
    # per-entity evidence TABLES (the rows ARE the decision evidence — keep top-N, don't drop):
    "lineage", "per_", "stats", "models", "elevated", "tissues", "cohorts", "indications",
    "subtype", "recommended",
)
_PROMPT_CARD_CHAR_CAP = 3000   # raised from 1200; only bites on pathological output


def _format_card_summary_for_prompt(summary: dict) -> str:
    """Render a card summary for the LLM prompt, GUARANTEEING load-bearing distribution fields
    survive (the old loop dropped `_`-prefixed keys, sampled lists>5 to 3, and hard-capped 1200
    chars — destroying the per-sample distribution stats the extraction layer produces). Policy:
      - scalars (str/num/bool/None) always kept in full;
      - a list whose key matches a load-bearing pattern (e.g. per_lineage_stats, most_elevated_*)
        is kept as its top-8 rows (not dropped to a `_len`), since these ARE the decision evidence;
      - other/unknown lists >8 are summarized as {_len, _sample:3} (the old behavior, for genuine
        noise only);
      - `_`-prefixed provenance keys are still dropped (not decision evidence);
      - a generous per-card cap (3000) only trims pathological output."""
    def _is_scalar(v):
        return v is None or isinstance(v, (str, int, float, bool))

    def _load_bearing(key: str) -> bool:
        kl = key.lower()
        return any(part in kl for part in _LOAD_BEARING_SUMMARY_KEY_PARTS)

    out = {}
    for k, v in summary.items():
        if k.startswith("_"):
            continue
        if _is_scalar(v):
            out[k] = v
        elif isinstance(v, list):
            if _load_bearing(k):
                out[k] = v[:8]                      # keep the decision rows
            elif len(v) > 8:
                out[f"{k}_len"] = len(v)
                out[f"{k}_sample"] = v[:3]
            else:
                out[k] = v
        else:  # dict / nested
            out[k] = v
    return json.dumps(out, default=str)[:_PROMPT_CARD_CHAR_CAP]


def _build_user_prompt(
    target: str,
    indication: str,
    sub_results: dict,
    modality: Optional[str] = None,
    therapeutic_hypothesis: Optional[str] = None,
    ordinal_matrix: Optional[dict] = None,
    biomarker_facet: Optional[dict] = None,
    subtype_facet: Optional[dict] = None,
    axis_info: Optional[dict] = None,
) -> str:
    """Compose the user-message text: biology-axis governance + sub-verdicts + modality-scoped
    matrix slice + biomarker convergence facet + card summaries + optional lens context.

    axis_info (from _skills_common.biology_axis.resolve_biology_axis) steers modality EMPHASIS:
    it foregrounds the plausible modalities for the target's curated axis so the narration does
    not over-weight surface-antigen framing for an intracellular target (or vice versa). It is a
    SLOT-2 emphasis steer only — the deterministic verdict + recommendation are untouched."""
    lines = [
        f"Target: {target}",
        f"Indication: {indication}",
    ]
    if axis_info is not None:
        from _skills_common.biology_axis import format_axis_governance_block
        lines.append("")
        lines.append(format_axis_governance_block(axis_info))
    if modality:
        lines.append(f"Modality lens (post-hoc, reweight narrative): {modality}")
    if therapeutic_hypothesis:
        lines.append(f"Therapeutic hypothesis (post-hoc, reweight narrative): "
                     f"{therapeutic_hypothesis}")
    lines.append("")
    lines.append("### Sub-verdicts (deterministic, rule-fired)")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"no rule-fired verdict (skill relies on raw metrics)")
        else:
            verdict_str, driving_rule = v
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"`{verdict_str}` (driving rule: {driving_rule})")
    lines.append("")
    if ordinal_matrix is not None:
        lines.extend(_render_matrix_slice_for_prompt(ordinal_matrix))
    if biomarker_facet is not None:
        bf = biomarker_facet
        lines.append("")
        lines.append("### Biomarker convergence facet (deterministic; a FACET, not a gate)")
        lines.append(f"- facet verdict: `{bf.get('verdict')}`  |  preferred assay: "
                     f"`{bf.get('preferred_assay')}`")
        corr = {k: v for k, v in (bf.get("corroboration_role") or {}).items() if v is not None}
        strat = {k: v for k, v in (bf.get("stratification_role") or {}).items() if v is not None}
        lines.append(f"- corroboration (→ confidence in biology verdicts): "
                     f"{corr if corr else 'none reachable'}")
        lines.append(f"- stratification (→ patient selection): {strat if strat else 'none reachable'}")
        # A2c: surface the QUANTITATIVE strengths behind the classes (from A2a's `quantitative` block)
        # so the narration reports HOW STRONG each biomarker signal is, not just its bucket. Each stat
        # is glossed in plain language for a non-computational reader (publication-register discipline).
        quant = {k: v for k, v in (bf.get("quantitative") or {}).items() if v}
        if quant:
            lines.append(f"- quantitative strength (raw statistics behind the classes above): {quant}")
            lines.append("  METRIC GLOSS (interpret in plain language; report with scale + direction): "
                         "hotspot_mannwhitney_q = FDR-adjusted p that mutant vs WT Chronos differ (lower "
                         "= more separated); hotspot_effect_size = rank-biserial (0-1, higher = cleaner "
                         "mutant-vs-WT dependency split); delta_chronos_* = mutant-minus-WT median "
                         "Chronos (more negative = mutant lines more dependent); pearson_r/spearman = "
                         "expression↔dependency correlation (negative = higher expression, more "
                         "dependent); fraction_agree = CRISPR/RNAi concordance rate; rna_protein_r = "
                         "how well RNA proxies protein (higher = RNA is an adequate assay); logrank_p = "
                         "expression↔survival separation. These quantify the STRATIFICATION / "
                         "CORROBORATION strength; they predict DEPENDENCY, not proven drug response.")
        lines.append("  NOTE: this facet may RAISE CONFIDENCE (corroboration) or define the "
                     "patient-selection population (stratification); it must NEVER by itself justify "
                     "a `nominate` — the deterministic gate owns the recommendation.")
    if subtype_facet is not None:
        sf = subtype_facet
        lines.append("")
        lines.append("### Subtype convergence facet (deterministic; a FACET, not a gate)")
        lines.append(f"- facet verdict: `{sf.get('verdict')}`  |  axes available: "
                     f"{sf.get('axes_available') or 'none'}  |  subtypes evaluated: "
                     f"{sf.get('n_subtypes_evaluated')}")
        conv = sf.get("convergent_subtypes") or []
        if conv:
            lines.append(f"- CONVERGENT subtypes (>=2 measured axes → cross-axis patient-selection "
                         f"strata): {conv}")
            for st in conv:
                b = (sf.get("per_subtype") or {}).get(st, {})
                lines.append(f"    - {st}: measured on {b.get('axes_measured')} "
                             f"(metrics: {b.get('metrics')})")
        else:
            lines.append("- no subtype converges >=2 measured axes on the SAME id this run")
        assoc = sf.get("associated_subtypes") or []
        if assoc:
            lines.append("- ASSOCIATED strata (different strata, each measured on its own axis, linked "
                         "by a subtype-registry association — RELATED, not the same stratum):")
            for a in assoc:
                bridge = " [CROSS-COHORT bridge: DepMap↔TCGA — interpret cautiously]" if a.get("cohort_bridge") else ""
                lines.append(f"    - {a['from']} {a['relationship']} {a['to']} "
                             f"({a['from_axes_measured']} ↔ {a['to_axes_measured']}){bridge}")
        lines.append("  NOTE: subtype convergence/association defines a PATIENT-SELECTION population + may "
                     "raise confidence; it must NEVER by itself justify a `nominate`. An ASSOCIATED pair "
                     "is a WEAK, registry-bridged link (e.g. MSI_H-dependency ↔ CMS1-expression) — the two "
                     "strata are biologically related, NOT identical; a cohort_bridge crosses DepMap↔TCGA. "
                     "subtype_axis_unavailable = no subtype shard for this indication (a P2 coverage gap), "
                     "not a measured negative.")
    lines.append("### Card summaries (raw, per-card)")
    for short, r in sub_results.items():
        lines.append(f"\n#### {short} ({r['skill_dir']})")
        for c in r["cards"]:
            cid = c["card_id"]
            # Distinguish the TWO _missing kinds (both are tagged _missing=True by resolve_cards,
            # but they mean opposite things to a reviewer):
            #   dispatcher_returned_none → the card is NOT WIRED (no reader) → truly absent.
            #   <anything else>          → the card WAS READ and returned data_unavailable → this is
            #     a MEASURED gap (coverage/proxy/underpowering), and resolve_cards RETAINED the real
            #     summary. Forwarding it (with its reason) is the difference between "we looked and
            #     found nothing" and "we never looked" — the measured-negative-vs-data_unavailable
            #     doctrine, applied inside the prompt so the LLM does not conflate them.
            if c.get("_missing"):
                reason = c.get("_missing_reason")
                if reason == "dispatcher_returned_none":
                    lines.append(f"- {cid}: NOT WIRED (no dispatcher)")
                    continue
                summary = c.get("summary") or {}
                detail = _format_card_summary_for_prompt(summary) if summary else "no summary fields"
                lines.append(f"- {cid}: DATA_UNAVAILABLE ({reason or 'measured gap'}) — {detail}")
                continue
            summary = c.get("summary") or {}
            lines.append(f"- {cid}: {_format_card_summary_for_prompt(summary)}")
    lines.append("")
    lines.append("### Fired rules (across all sub-skills, biology-first)")
    # Pass rule COLOR (rationale / signals / killer_message) — these are already computed on every
    # fired rule (_skills_common.fired_rules) but were previously dropped from the prompt, so the LLM
    # saw THAT a rule fired, never WHY. Surfacing them lets the model reason about significance +
    # modality direction, not just state. (Verdict spine unchanged — this is prompt-only enrichment.)
    for short, r in sub_results.items():
        for f in r["fired"]:
            line = f"- [{short}] {f['rule_id']} on {f['card_id']}.{f['field']} = {f['value']}"
            signals = f.get("signals") or {}
            if signals:
                line += "  | signals: " + ", ".join(f"{k}={v}" for k, v in signals.items())
            killer = f.get("killer_message")
            if killer:
                line += f"  | KILLER: {killer.strip()}"
            rationale = (f.get("rationale") or "").strip()
            if rationale:
                # one-line the rationale + cap so a verbose block-scalar can't blow the prompt
                one_line = " ".join(rationale.split())
                line += f"  | why: {one_line[:240]}"
            lines.append(line)
    return "\n".join(lines)


# --- Rendering --------------------------------------------------------------

# --- Per-phase evidence rows -----------------------------------------------
# For each sub-skill's "short" key, name the 2-4 key metric fields to inline
# in the per-phase evidence table. Field names must match those actually
# exposed by each sub-skill's underlying card summaries (audited empirically).
PHASE_METRIC_FIELDS: dict[str, list[tuple[str, str]]] = {
    "expression": [
        ("median_log2tpm_panel",    "median log2TPM (pan-cancer)"),
        ("fraction_expressed",       "fraction expressed"),
        ("log2_fc",                  "log2FC tumor vs adj"),
        ("q_value",                  "q-value (tumor vs adj)"),
    ],
    "selectivity": [
        ("cells_supporting",         "cells supporting"),
        ("cells_ran",                "cells ran"),
        ("comparator_concordance",   "comparator agreement"),   # TCGA-adjacent vs GTEx concur? (slice 4)
        ("dominant_direction",       "dominant direction"),
        ("max_abs_log2fc",           "max |log2FC|"),
        ("discordant",               "discordant"),
    ],
    "dependency": [
        ("median_chronos_indication", "median CRISPR score"),
        ("pct_dependent_indication",  "pct cell lines dependent"),
        ("lineage_selectivity_class", "lineage selectivity"),
        ("concordance_class",         "CRISPR-RNAi concordance"),
    ],
    # Keys MUST match SUB_SKILLS shorts (run.py:65) or the per-phase evidence table
    # silently doesn't render (PHASE_METRIC_FIELDS.get(short, []) misses). Fixed
    # 2026-07-17: `mutation`→`genomic_alteration`, `tractability`→`tractability_sm`
    # (renamed in the 2026-07-14 restructure but this dict was missed — same
    # rename-drift class as the _risk_by_category fix); `population` DROPPED (skill
    # deleted, prevalence folded into genomic_alteration).
    "genomic_alteration": [
        ("mutation_landscape_class",      "landscape class"),
        ("mutation_stratification_class", "stratification class"),
        ("copy_number_class",             "copy-number class"),
        ("overall_mutation_frequency",    "cohort mutation frequency (indication)"),
    ],
    "tractability_sm": [
        ("prism_activity_class",            "PRISM activity class"),
        ("crispr_prism_concordance_class",  "PRISM-CRISPR concordance"),
        ("predictability_class",            "predictability"),
    ],
}


def _first_card_summary_field(sub_result: dict, field: str):
    """Search each card in the sub-result for a summary field; return the
    first non-None value found. Cards each expose different summary shapes,
    so a targeted search is more robust than positional assumption."""
    for c in sub_result.get("cards") or []:
        s = (c.get("summary") or {})
        if field in s and s[field] is not None:
            return s[field]
    return None


def _fmt_metric(value):
    """Human-render a metric value for the markdown table."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value) < 1e-3 or abs(value) >= 1e6:
            return f"{value:.3g}"
        return f"{value:.3f}"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    return s if len(s) <= 60 else s[:57] + "..."


def _risk_by_category_from_sub_verdicts(sub_results: dict) -> list[tuple[str, str, str]]:
    """Map sub-verdicts onto the 6-category risk framing (biological /
    druggability / translational / clinical / safety / commercial),
    producing (category, level, driver) triples. Categories with no
    wired coverage return level=insufficient_evidence — honest coverage
    signal for governance readers used to the 6-category shape.

    This is a NON-LLM mapping — deterministic reshape of the deterministic
    sub-verdicts. The v1 risk-assessment framing lives here as an output
    convention, not as a re-derivation via literature.
    """
    def _v(short):
        r = sub_results.get(short) or {}
        v = r.get("verdict")
        return v if v else (None, None)

    exp_v, exp_r = _v("expression")
    sel_v, sel_r = _v("selectivity")
    dep_v, dep_r = _v("dependency")
    # Short keys MUST match SUB_SKILLS (run.py:65). Fixed 2026-07-17: the
    # 2026-07-14 restructure renamed these two shorts (mutation→genomic_alteration,
    # tractability→tractability_sm) but this reshape wasn't updated, so _v() silently
    # returned (None,None) — druggability was dead-wired to insufficient_evidence and
    # the mutation signal was dropped from _biological(). A display bug (this feeds the
    # 6-category render table, not the gate), but a real one.
    mut_v, mut_r = _v("genomic_alteration")
    trk_v, trk_r = _v("tractability_sm")
    saf_v, saf_r = _v("safety")

    # Biological: strongest positive across A/B/C/mut wins
    # Simple mapping: at least one strong-supportive → LOW risk; not_selective
    # or non_dependent → HIGH; discordant / not_informative → MEDIUM
    def _biological():
        signals = [exp_v, sel_v, dep_v, mut_v]
        if any(s in ("strong_tumor_selective", "concordant_dependent",
                      "biomarker_stratified_dependency",
                      "broadly_high_expression") for s in signals):
            return "LOW", "strong support across A/B/C/mut sub-verdicts"
        if any(s in ("not_selective", "non_dependent",
                      "broadly_low_expression") for s in signals):
            return "HIGH", "negative signal in A/B/C sub-verdicts"
        if any(s == "discordant_across_comparators" for s in signals):
            return "MEDIUM", "comparator-dependent expression/selectivity signal"
        if all(s in (None, "insufficient", "not_informative") for s in signals):
            return "insufficient_evidence", "no rule-fired verdicts across A/B/C"
        return "MEDIUM", "mixed signals across A/B/C"

    def _druggability():
        if trk_v in ("well_covered", "chemically_confirmed_genetic"):
            return "LOW", trk_r or "PRISM-CRISPR triangulated"
        if trk_v in ("chemically_active",):
            return "LOW-MEDIUM", trk_r or "clinically-active compounds"
        if trk_v in ("tool_compound_only", "weakly_active"):
            return "MEDIUM-HIGH", trk_r or "tool compounds only"
        if trk_v in ("chemically_unhit", "discordant"):
            return "HIGH", trk_r or "no compound hits or discordant"
        return "insufficient_evidence", "tractability sub-verdict absent"

    def _safety():
        # on-target-safety-liability IS wired (gnomAD LoF-constraint). Fixed
        # 2026-07-17: this row was hardcoded insufficient_evidence with a stale
        # "gnomAD cards not wired" note, contradicting the wired safety sub-skill
        # that already feeds the nomination gate. Map its verdict here too.
        # Higher germline constraint → higher on-target (full-KO) safety RISK.
        if saf_v == "highly_constrained_safety_concern":
            return "HIGH", saf_r or "highly LoF-constrained gene (full-KO liability)"
        if saf_v == "moderately_constrained_safety":   # C2c: middle band → MEDIUM
            return "MEDIUM", saf_r or "moderately LoF-constrained gene (equivocal safety)"
        if saf_v == "tolerant_reduced_safety_risk":
            return "LOW", saf_r or "LoF-tolerant gene (reduced full-KO liability)"
        return "insufficient_evidence", "gnomAD constraint sub-verdict absent"

    # For phases we still have no wired data on, report insufficient_evidence
    # honestly rather than fabricate:
    return [
        ("biological",   *_biological()),
        ("druggability", *_druggability()),
        ("translational", "insufficient_evidence",
            "Phase-J (translational-readiness) placeholder — data not wired"),
        ("clinical",      "insufficient_evidence",
            "Phase-E (clinical precedent) placeholder — data feed not wired"),
        ("safety",        *_safety()),
        ("commercial",    "insufficient_evidence",
            "Phase-E (competitive/IP) placeholder — Cortellis/IQVIA not licensed"),
    ]


# --- Gate scorecard (deterministic; category × status × finding) ------------
#
# The top-of-report glanceable grid: one row per QUESTION-GATE (A Present … H Translational),
# rows driven by the gate_coverage registry so a gate with NO sub-verdict this run (e.g. H, which
# has no sub-skill) STILL appears — greyed — rather than being silently dropped (the "no cell for
# we-didn't-look" failure a 3-color RAG light has; scorecard-level version of L's discipline).
#
# The 4-state status is a PURE PROJECTION of the SAME policy the deterministic gate uses — reusing
# _load_gate_verdicts (kill tuples), _load_positive_signals (positive + contradiction sets) — so
# the scorecard can NEVER disagree with the recommendation gate. No new classification logic:
#   opposing     = verdict in the kill tuples OR a positive_contradiction (a MEASURED negative)
#   supportive   = verdict in positive_signals (a MEASURED positive)
#   coverage_gap = insufficient / data_unavailable / None / gate absent this run (we didn't look)
_SCORECARD_STATUS_ORDER = {"opposing": 0, "supportive": 1, "coverage_gap": 2}
_COVERAGE_GAP_VERDICTS = {None, "insufficient", "data_unavailable", "not_implemented",
                          "phase_not_yet_wired"}


def _gate_scorecard(sub_results: dict, deciding_axis: Optional[dict] = None,
                    contracts_repo: Path | None = None) -> list[dict]:
    """Build the 8-gate scorecard rows. Rows come from the gate_coverage REGISTRY (not from
    iterating sub_results), so gates we're blind on this run still render as greyed rows. Status
    reuses the nomination-gate policy so it cannot diverge from the deterministic verdict."""
    baseline, _ = _load_gate_coverage(contracts_repo)
    kill_map, _ = _load_gate_verdicts(contracts_repo)          # {(short,verdict): action}
    positive_map, contradictions, _, _ = _load_positive_signals(contracts_repo)
    deciding_short = None
    if deciding_axis and deciding_axis.get("basis") == "gate_fired":
        deciding_short = (deciding_axis.get("deciding_axis") or {}).get("short")

    def _status(short: str, verdict: Optional[str]) -> str:
        if verdict in _COVERAGE_GAP_VERDICTS:
            return "coverage_gap"
        if (short, verdict) in kill_map or (short, verdict) in contradictions:
            return "opposing"
        if (short, verdict) in positive_map:
            return "supportive"
        # A measured verdict that is neither a gate kill nor a curated positive/contradiction
        # (e.g. a neutral 'broadly_dependent') — report it as measured-but-neutral, still on-scale,
        # NOT a coverage gap (we DID look). Treated as supportive-family for chip purposes only if
        # it's a positive; otherwise 'neutral'.
        return "neutral"

    rows = []
    # Rows carry gate/gate_name/band + axis (biology|modality_fit). axis derives from the contract
    # (v2) or is inferred from the band (v1 has no axis field): necessity→biology, sufficiency→
    # modality_fit — the 1:1 alignment the additive v1.1.0 file also asserts.
    for short, meta in baseline.items():
        r = sub_results.get(short) or {}
        v = r.get("verdict")
        verdict_str = v[0] if v else None
        driving = v[1] if (v and len(v) > 1) else None
        axis = meta.get("axis") or ("biology" if meta.get("band") == "necessity" else "modality_fit")
        # risk_category (5R dashboard spine) from the contract; fall back to axis if a pre-field
        # contract is live (biology→biological; else the row is uncategorized, grouped under 'other').
        risk_category = meta.get("risk_category") or ("biological" if axis == "biology" else None)
        rows.append({
            "short": short,
            "gate": meta.get("gate"),
            "gate_name": meta.get("gate_name"),
            "band": meta.get("band"),
            "axis": axis,
            "risk_category": risk_category,
            "verdict": verdict_str,
            "driving_rule_id": driving,
            "status": _status(short, verdict_str),
            "framework_can_evidence": _run_coverage_for_short(short, r, baseline),
            "is_deciding": short == deciding_short,
        })
    # Sort AXIS-primary (biology before modality_fit) so grouping is stable even when v2 modality-fit
    # rows are letterless; then by gate letter (A..H; letterless → 'Z' last within its axis), then
    # band (necessity first) as a stable tiebreak.
    _AXIS_ORDER = {"biology": 0, "modality_fit": 1}
    rows.sort(key=lambda x: (_AXIS_ORDER.get(x.get("axis"), 2),
                             str(x.get("gate") or "Z"),
                             x.get("band") != "necessity"))
    return rows


# --- Risk-category roll-up (5R dashboard spine, 2026-07-21) ------------------
#
# The committee-facing lead lens: roll the per-gate scorecard rows up into drug-discovery risk
# categories (5R-anchored — see target-contracts docs/design/RISK_CATEGORY_DASHBOARD_SPINE.md).
# DATA-DRIVEN SURFACING: a category is surfaced IFF >=1 of its member sub-skills produced evidence
# this run (a non-coverage-gap status). Categories with no evidenced member are NOT rendered as
# rows — they collapse into a one-line "not yet evidenced" footnote. This keeps the dashboard
# honest (absence = "we don't evidence this yet") AND self-extending (wire a new sub-skill → its
# category appears automatically). Category risk LEVEL is a computed roll-up of member statuses,
# reusing the SAME 4-state the scorecard already assigned — no new classification logic.
_RISK_CATEGORY_ORDER = ["biological", "biomarker", "druggability", "safety",
                        "translational", "clinical", "commercial"]
_RISK_CATEGORY_LABEL = {
    "biological":    ("Biological", "Right Target — is this real, actionable biology?"),
    "biomarker":     ("Biomarker", "Right Patient — who responds?"),
    "druggability":  ("Druggability", "can it be drugged (small-molecule / biologic)?"),
    "safety":        ("Safety", "Right Safety — on-target liability?"),
    "translational": ("Translational", "Right Tissue — models / PD / exposure?"),
    "clinical":      ("Clinical", "clinical precedent?"),
    "commercial":    ("Commercial", "Right Commercial Potential — differentiation?"),
}


def _risk_category_rollup(scorecard: list[dict]) -> dict:
    """Group scorecard rows by risk_category → the 5R lead lens. Returns
    {surfaced: [{category, label, sub, risk_level, driver, members:[rows], anchor}],
     not_evidenced: [category,...]}. A category surfaces iff >=1 member has an on-scale status
     (supportive/opposing/neutral — i.e. we looked); all-coverage-gap categories are 'not evidenced'.
    risk_level: opposing member → 'elevated'; else any supportive → 'supported'; else 'neutral'."""
    by_cat: dict = {}
    for row in scorecard or []:
        cat = row.get("risk_category") or "other"
        by_cat.setdefault(cat, []).append(row)

    def _level(members: list[dict]) -> tuple[str, str]:
        statuses = [m.get("status") for m in members]
        opp = [m for m in members if m.get("status") == "opposing"]
        sup = [m for m in members if m.get("status") == "supportive"]
        if opp:
            drv = opp[0]
            return "elevated", f"{_humanize(drv.get('verdict') or drv.get('short'))} (opposing)"
        if sup:
            drv = sup[0]
            return "supported", f"{_humanize(drv.get('verdict') or drv.get('short'))}"
        return "neutral", "measured; no strong signal either way"

    surfaced, not_evidenced = [], []
    for cat in _RISK_CATEGORY_ORDER + sorted(k for k in by_cat if k not in _RISK_CATEGORY_ORDER):
        members = by_cat.get(cat)
        if not members:
            not_evidenced.append(cat)
            continue
        # evidenced iff >=1 member has an on-scale (non-coverage-gap) status
        if not any(m.get("status") in ("supportive", "opposing", "neutral") for m in members):
            not_evidenced.append(cat)
            continue
        level, driver = _level(members)
        label, sub = _RISK_CATEGORY_LABEL.get(cat, (_humanize(cat), ""))
        # anchor: link to the first evidenced member's gate section (roll-up → detail)
        anchor = None
        for m in members:
            a = _SHORT_TO_GATE_ANCHOR.get(m.get("short"))
            if a:
                anchor = a
                break
        surfaced.append({"category": cat, "label": label, "sub": sub, "risk_level": level,
                         "driver": driver, "members": members, "anchor": anchor})
    return {"surfaced": surfaced, "not_evidenced": not_evidenced}


def _render_target_profile_md(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    composite_figure_relpath: Optional[str] = None,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
) -> str:
    """Render target_profile.md with clearly-tagged LLM sections + per-phase
    evidence tables + risk-by-category summary + deciding-axis routing + the
    ordinal evidence matrix + embedded composite figure. deciding_axis + ordinal_matrix
    are DETERMINISTIC (not LLM) — surfaced so a human reader sees the same routing +
    modality view that land in nomination.json, not only the LLM narrative."""
    lines = [
        f"# Target profile — {target} in {indication}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if invoked_lenses:
        lines.append(f"Invoked lenses: `{invoked_lenses}`")
    lines.append("")

    # --- Composite figure (Shape C) ----------------------------------------
    if composite_figure_relpath:
        lines.append(f"![Target profile at a glance]({composite_figure_relpath})")
        lines.append("")

    # --- Executive summary (LLM) -------------------------------------------
    exec_summary = llm_output.get("executive_summary", {}).get("value", "")
    lines.append("## Executive summary *(LLM-synthesized)*")
    lines.append("")
    lines.append(exec_summary)
    lines.append("")

    # --- Recommendation (LLM) — pulled up front for governance readers -----
    def _val(field: str, default: str = "—") -> str:
        raw = llm_output.get(field)
        if isinstance(raw, dict):
            return str(raw.get("value", default))
        return str(raw) if raw is not None else default

    rec = _val("overall_recommendation")
    conf = _val("confidence")
    lines.append("## Recommendation *(LLM-synthesized, enum-constrained)*")
    lines.append("")
    lines.append(f"- **Action:** `{rec}`")
    lines.append(f"- **Confidence:** `{conf}`")
    lines.append("")

    # --- Deciding axis (deterministic router; reports, never predicts) -----
    if deciding_axis:
        lines.append("## Deciding axis *(deterministic — what the call hinges on)*")
        lines.append("")
        basis = deciding_axis.get("basis")
        lines.append(f"_{deciding_axis.get('routing', '')}_")
        lines.append("")
        if basis == "gate_fired":
            da = deciding_axis.get("deciding_axis", {})
            lines.append(f"- **Load-bearing gate:** {da.get('gate')} ({da.get('gate_name')}) "
                         f"— `{da.get('short')}`")
            lines.append(f"- **Framework coverage of that gate:** `{da.get('framework_can_evidence')}`")
        elif basis == "abstention_coverage_gaps":
            lines.append("The framework cannot decide from its own evidence. Gates it could not "
                         "evidence this run (necessity first — these are the routing targets):")
            lines.append("")
            lines.append("| gate | short | band | framework can evidence |")
            lines.append("|---|---|---|---|")
            for g in deciding_axis.get("unevidenced_gates", []):
                lines.append(f"| {g.get('gate')} | `{g.get('short')}` | {g.get('band')} "
                             f"| `{g.get('framework_can_evidence')}` |")
        elif basis == "positive_signal":
            axes = ", ".join(f"`{r.get('short')}`" for r in deciding_axis.get("deciding_axes", []))
            lines.append(f"- **Supporting axes (necessity biology evidenced):** {axes}")
        lines.append("")

    # --- Risk-by-category summary (deterministic, from sub-verdicts) -------
    lines.append("## Risk-by-category summary *(deterministic reshape "
                 "of sub-verdicts)*")
    lines.append("")
    lines.append("Governance-facing 6-category framing mapped from the rule-"
                 "fired sub-verdicts below. Categories with no wired data "
                 "return `insufficient_evidence` rather than fabricated risk "
                 "levels.")
    lines.append("")
    lines.append("| Category | Risk level | Driver |")
    lines.append("|---|---|---|")
    for cat, level, driver in _risk_by_category_from_sub_verdicts(sub_results):
        lines.append(f"| **{cat}** | `{level}` | {driver} |")
    lines.append("")

    # --- Tension analysis (LLM) --------------------------------------------
    tension = llm_output.get("tension_analysis", {}).get("value", "")
    lines.append("## Tension analysis *(LLM-synthesized)*")
    lines.append("")
    lines.append(tension)
    lines.append("")

    # --- Sub-verdicts (rule-fired) -----------------------------------------
    lines.append("## Sub-verdicts *(deterministic, rule-fired)*")
    lines.append("")
    lines.append("| Dimension | Verdict | Driving rule |")
    lines.append("|---|---|---|")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"| {short} | — | (raw metrics; no rule verdict) |")
        else:
            verdict_str, driving_rule = v
            lines.append(f"| {short} | `{verdict_str}` | `{driving_rule}` |")
    lines.append("")

    # --- Ordinal evidence matrix (deterministic VIEW; gate × modality) -----
    if ordinal_matrix:
        cols = ordinal_matrix["axes"]["columns"]
        leg = ordinal_matrix["legend"]
        lines.append("## Modality-scoped evidence matrix *(deterministic VIEW — not a score)*")
        lines.append("")
        lines.append(f"> {ordinal_matrix.get('_disclaimer', '')}")
        lines.append("")
        lines.append("| gate | " + " | ".join(cols) + " | verdict |")
        lines.append("|" + "---|" * (len(cols) + 2))
        for row in ordinal_matrix["rows"]:
            cells = row["cells"]
            glyphs = " | ".join(ordinal_view._cell_glyph(cells[m]) for m in cols)
            lines.append(f"| {row['short']} | {glyphs} | {row.get('verdict') or '—'} |")
        on = ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(), key=lambda t: -t[1]))
        lines.append("")
        lines.append(f"_Scale (order-preserving, NOT metric): {on}; off-scale (coverage, not a "
                     f"low score): {', '.join(leg['off_scale'])} (`insf`/`n/a`); `·` = no signal. "
                     f"A cell shows the strongest raw signal for that (gate, modality); when it "
                     f"differs from the resolved verdict, the verdict is the decision._")
        lines.append("")

    # --- Per-phase evidence tables (Shape A enrichment) --------------------
    lines.append("## Per-phase evidence *(deterministic, from card summaries)*")
    lines.append("")
    lines.append("Key metrics inlined from each sub-skill's underlying card "
                 "summaries. Use these to trace a verdict back to its "
                 "supporting data.")
    lines.append("")
    for short, r in sub_results.items():
        fields = PHASE_METRIC_FIELDS.get(short, [])
        if not fields:
            continue
        v = r["verdict"]
        header = f"### {short}"
        if v:
            header += f" — `{v[0]}`"
        lines.append(header)
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        any_value = False
        for field, label in fields:
            value = _first_card_summary_field(r, field)
            if value is None:
                continue
            lines.append(f"| {label} | `{_fmt_metric(value)}` |")
            any_value = True
        if not any_value:
            lines.append("| (no metrics available) | — |")
        lines.append("")

    # --- Top arguments (LLM) -----------------------------------------------
    for_args = llm_output.get("top_arguments_for", {}).get("value", []) or []
    against_args = llm_output.get("top_arguments_against", {}).get("value", []) or []
    lines.append("## Top arguments *(LLM-synthesized)*")
    lines.append("")
    lines.append("**For:**")
    for a in for_args:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("**Against:**")
    for a in against_args:
        lines.append(f"- {a}")
    lines.append("")

    # --- Provenance footer -------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append("*LLM-synthesized sections carry `_source: llm_synthesized` "
                 "provenance (see `nomination.json`). Sub-verdicts + "
                 "per-phase evidence + risk-by-category are deterministic "
                 "and reproducible from the same inputs. The composite "
                 "figure is rendered from the same sub-verdicts and can be "
                 "regenerated identically.*")

    return "\n".join(lines)


# ============================================================================
# HTML renderer — static, self-contained governance artifact (2026-07-20)
# ============================================================================
# A projection of the SAME nomination data the .md carries: adds NO computation, NO new LLM
# surface, NO client-side JS (nothing can recompute → the "renderer adds nothing" rule is
# structural). The honesty distinctions become visual STRUCTURE: LLM sections are tinted; the
# 4-state scorecard distinguishes measured-negative (🔴) from coverage-gap (⚪); the ordinal
# matrix carries its "not a score" disclaimer. Colors mirror composite_panel.VERDICT_COLORS +
# the Takeda palette so the page matches the inlined figure.
import html as _html

_HTML_STATUS = {   # 4-state scorecard chip → (glyph, css class, human label)
    "supportive":   ("●", "chip-pos",  "Supports"),
    "neutral":      ("○", "chip-neu",  "Measured — neutral"),
    "opposing":     ("◆", "chip-neg",  "Counts against"),
    "coverage_gap": ("□", "chip-gap",  "Not evaluated"),
}

# --- Plain-English label layer (reader-facing; raw tokens stay in nomination.json) -----------
# The internal vocabulary (verdict strings, gate shorts, coverage terms) leaks jargon to a human
# reader. These maps turn it into plain English for the HTML report. Curated overrides for the
# load-bearing terms; a snake_case→Title-Case fallback for the rest so nothing renders as a raw id.
_GATE_SHORT_LABEL = {
    "expression": "Expression (is it expressed?)",
    "selectivity": "Tumor selectivity (vs normal)",
    "dependency": "Functional dependence (is it required?)",
    "synthetic_lethal_partners": "Synthetic-lethal partners",
    "mechanism": "Mechanism / mode of action",
    "genomic_alteration": "Genomic alteration",
    "differentiation": "Differentiation (co-mutation)",
    "tractability_sm": "Small-molecule druggability",
    "surface_modality": "Surface / biologics fit",
    "safety": "On-target safety",
    "subtype_fit": "Subtype-specific fit",
}
_COVERAGE_LABEL = {
    "captured": "Well covered",
    "partial": "Partially covered",
    "blind": "Not covered (framework blind)",
    "license_blocked": "License-blocked data",
    "out_of_scope": "Out of scope (Tier-2)",
}
# Plain-English band labels (reader-facing) — the "necessity/sufficiency" jargon is dropped in
# favor of the question each band actually asks.
_BAND_LABEL = {"necessity": "Is it real biology?",
               "sufficiency": "Will it become a drug?"}
# Nomination action → (display term, plain-English gloss). Shown as "Term — gloss" in the header.
_ACTION_GLOSS = {
    "nominate": ("Nominate", "advance this target"),
    "hold": ("Hold", "do not advance yet — a concern must be resolved first"),
    "veto": ("Veto", "do not pursue — a disqualifying finding"),
    "insufficient_evidence": ("Insufficient evidence", "the framework cannot make a call"),
}
# Load-bearing verdict humanizations (the ones a reader most needs unambiguous).
_VERDICT_LABEL = {
    "lineage_selective": "Selective dependency (lineage-restricted)",
    "concordant_dependent": "Strong dependency (CRISPR + RNAi agree)",
    "selective_dependent": "Selective dependency",
    "chemical_genetic_confirmed_dependent": "Dependency confirmed (chemical + genetic)",
    "non_dependent": "Not a dependency (pooled)",
    "pan_essential_killer": "Pan-essential (no therapeutic window)",
    "broadly_dependent": "Broadly dependent",
    "strong_tumor_selective": "Strongly tumor-selective",
    "modest_tumor_selective": "Modestly tumor-selective",
    "not_selective": "Not tumor-selective",
    "discordant_across_comparators": "Discordant across comparators",
    "highly_constrained_safety_concern": "High on-target safety concern",
    "biomarker_stratified_dependency": "Biomarker-stratified dependency",
    "confirmed_driver": "Confirmed driver (annotation-corroborated)",
    "well_covered": "Well-covered by compounds",
    "well_characterized": "Well-characterized mechanism",
    "both_patterns_present": "Co-mutation + mutual-exclusivity present",
    "broadly_moderate_expression": "Broadly moderate expression",
    "has_experimental_sl_partner": "Has an experimental SL partner",
    "insufficient": "Insufficient evidence",
    "data_unavailable": "Data unavailable",
    None: "Not evaluated",
}


def _humanize(token: Optional[str]) -> str:
    """snake_case / lowercase identifier → readable Title Case, with curated overrides."""
    if token is None:
        return "Not evaluated"
    if token in _VERDICT_LABEL:
        return _VERDICT_LABEL[token]
    return str(token).replace("_", " ").replace("-", " ").strip().capitalize()

# CSS design system (dataviz-skill method; Takeda Okabe-Ito palette as the brand parameters).
# Color roles as CSS custom properties. Status chips use VALIDATED constructions — dark status-ink
# on a pale same-hue tint + a glyph + a label (never color-alone) — WCAG 4.8-6.3:1 (computed with
# the dataviz validator, NOT eyeballed; the validator caught that saturated status colors on white
# fail contrast, so chips are tinted backgrounds). The ordinal heatmap uses a DIVERGING blue↔red
# ramp (a magnitude), deliberately distinct from the status chips so the two color languages don't
# collide (dataviz rule: status colors are reserved, never reused as a scale).
_HTML_CSS = """
:root{
  --surface:#ffffff; --surface-2:#f7f9fb; --surface-3:#eef2f6;
  --ink:#141c26; --ink-2:#4a5763; --muted:#6b7783; --line:#e2e8ee; --line-2:#cfd8e0;
  --brand:#0a2540; --brand-accent:#0072B2;                 /* Takeda deep navy + Okabe-Ito blue */
  --pos-ink:#1a6b1a; --pos-bg:#e6f4e6;                      /* status: good */
  --neg-ink:#a1231d; --neg-bg:#fbe6e4;                      /* status: critical */
  --neu-ink:#8a5a00; --neu-bg:#fcf1db;                      /* status: warning */
  --gap-ink:#5b6b7b; --gap-bg:#eef1f4;                      /* coverage gap (hatched) */
  --llm-bg:#f5f2fb; --llm-bd:#d9ccf0; --llm-ink:#5b3fa0;    /* AI-generated section tint */
  --div-p2:#2166ac; --div-p0:#e9eef3; --div-n1:#f4a582; --div-n3:#b2182b;  /* diverging blue↔red */
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  color:var(--ink);background:var(--surface-3);margin:0;padding:0}
/* Header band — full-bleed; inner content aligned to the same max-width as the shell */
header{background:linear-gradient(100deg,var(--brand),#123a5e);color:#fff;
  padding:24px 40px;border-bottom:3px solid var(--brand-accent)}
header>*{max-width:1560px;margin-left:auto;margin-right:auto}
header h1{font-size:25px;font-weight:650;margin:0;letter-spacing:-.01em;line-height:1.25}
header .rec{font-size:14px;margin-top:10px;opacity:.95;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
header .pill{display:inline-block;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.32);
  border-radius:999px;padding:2px 12px;font-weight:650}
.badge-rule{display:inline-block;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);
  border-radius:6px;padding:2px 9px;font-size:12px;font-weight:600;cursor:help}
/* 2-column shell: sticky left nav + content. Wide — uses the full viewport up to a large cap. */
.shell{display:flex;gap:28px;max-width:1680px;margin:0 auto;padding:26px 40px 64px;align-items:flex-start}
nav.toc{position:sticky;top:20px;flex:0 0 150px;font-size:12.5px;line-height:1.3}   /* narrower (item 7) */
nav.toc .h{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  font-weight:700;margin:0 0 8px}
nav.toc a{display:block;padding:6px 10px;border-radius:7px;color:var(--ink-2);text-decoration:none;
  border-left:2px solid transparent}
nav.toc a:hover{background:var(--surface);color:var(--brand);border-left-color:var(--brand-accent)}
.content{flex:1 1 auto;min-width:0}
.sub{color:var(--muted);font-size:13px;margin:0 0 10px}
/* Responsive inline SVG — strip matplotlib's fixed pt size, scale to the card (viewBox holds ratio) */
section svg{width:100%!important;height:auto!important;display:block}
/* Section cards */
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin:0 0 18px;box-shadow:0 1px 2px rgba(20,28,38,.04)}
h2{font-size:16px;font-weight:650;margin:0 0 12px;color:var(--brand);letter-spacing:-.005em}
h2 .n{color:var(--muted);font-weight:500;font-size:13px}
/* Tables */
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:8px 11px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:var(--surface-2);font-weight:600;color:var(--ink-2);font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;border-bottom:1.5px solid var(--line-2)}
tr:last-child td{border-bottom:0}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--surface-3);padding:1px 5px;border-radius:4px;color:var(--ink-2)}
/* LLM vs deterministic provenance tags */
.llm{background:var(--llm-bg);border:1px solid var(--llm-bd);border-radius:12px;padding:16px 20px;margin:0 0 18px}
.llm h2{color:var(--llm-ink)}
.tag{display:inline-block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;
  padding:2px 8px;border-radius:5px;margin-bottom:8px}
.llm .tag{color:var(--llm-ink);background:rgba(91,63,160,.1)}
.det .tag{color:var(--muted);background:var(--surface-3)}
/* AI-generated provenance chip in the exec summary's upper-right corner. The h2 purple bar hugs the
   box top (first-child), so the chip floats on that bar → give it translucent-white-on-purple so it
   reads against the dark band rather than the light in-flow tag treatment. */
.llm-exec{position:relative}
.llm-exec .tag-corner{position:absolute;top:9px;right:14px;margin:0;z-index:2;
  color:#fff;background:rgba(255,255,255,.18)}
/* Status chips — validated: tinted bg + dark ink + glyph + label */
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;
  font-size:12px;font-weight:650;white-space:nowrap;line-height:1.3}
.chip .g{font-size:11px}
.chip-pos{background:var(--pos-bg);color:var(--pos-ink)}
.chip-neu{background:var(--neu-bg);color:var(--neu-ink)}
.chip-neg{background:var(--neg-bg);color:var(--neg-ink)}
.chip-gap{background:var(--gap-bg);color:var(--gap-ink);
  background-image:repeating-linear-gradient(45deg,transparent,transparent 5px,rgba(91,107,123,.13) 5px,rgba(91,107,123,.13) 6px)}
/* Scorecard hero */
.scorecard th:first-child,.scorecard td:first-child{text-align:center;font-weight:700;color:var(--brand);width:38px}
.scorecard tr.gate-start td{border-top:2px solid var(--line-2)}
.scorecard tr.deciding{background:#fff9ec}
.scorecard tr.deciding td:first-child{box-shadow:inset 3px 0 0 var(--neu-ink)}
.badge-deciding{display:inline-block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
  color:var(--neu-ink);background:var(--neu-bg);padding:1px 6px;border-radius:4px;margin-left:6px}
/* Deciding-axis banner */
.banner{background:linear-gradient(90deg,#eef4f8,var(--surface));border-left:4px solid var(--brand-accent);
  padding:12px 16px;border-radius:8px;margin:0 0 12px;font-size:14px}
/* Ordinal matrix heatmap */
.mtx{font-size:12.5px}
.mtx td{text-align:center;font-variant-numeric:tabular-nums;font-weight:600;border:2px solid var(--surface)}
.mtx td:first-child,.mtx td:last-child{text-align:left;font-weight:400;background:var(--surface)!important}
.mtx th{text-align:center}
.mtx .p2{background:var(--div-p2);color:#fff}.mtx .p0{background:var(--div-p0);color:var(--ink-2)}
.mtx .n1{background:var(--div-n1);color:#3a1207}.mtx .n3{background:var(--div-n3);color:#fff}
.mtx .off{background:var(--gap-bg);color:var(--gap-ink);font-style:italic}
.disclaimer{font-size:12px;color:var(--muted);font-style:italic;margin:6px 0}
details{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-weight:600;color:var(--ink-2);font-size:13px}
footer{color:var(--muted);font-size:12px;text-align:center;padding-top:8px}
/* Interactive figures (Phase B). Tighter default height (item 1) — the method sets each figure's
   own height; this caps the container so charts don't dominate. */
.plotly-fig{width:100%;min-height:250px;margin:6px 0 2px}
/* Gate section + subtabs (iterative dashboard, 2026-07-21). A gate section is a normal section
   card; inside it a radio-driven tab strip (Plots / Evidence / Rules) — pure CSS, no framework, so
   the report stays a self-contained archivable file. Each gate's radios share a name scoped by the
   gate short (name=tab-<short>) so gates toggle independently. */
.gate .gate-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 4px}
.gate .gate-letter{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
  border-radius:7px;background:var(--brand);color:#fff;font-weight:700;font-size:13px;flex:0 0 auto}
.gate .gate-verdict{margin-left:auto;font-size:13px;color:var(--ink-2)}
/* Axis band header (gate-model v2): the two-axis split — Biology (necessity) vs Modality-fit
   (sufficiency) — rendered as a band that groups the gate sections beneath it. */
.axis-band{margin:26px 0 10px;padding:8px 14px;border-radius:9px;background:var(--surface-2);
  border-left:4px solid var(--brand)}
.axis-band h2{margin:0;font-size:15px;background:none;color:var(--brand);padding:0;letter-spacing:.2px}
.axis-band .n{color:var(--muted);font-weight:400;font-size:13px}
/* Tabbed card subsections. A tiny JS handler (in the page bootstrap) toggles .active on the
   clicked label + its target panel — robust across any tab count, and JS is already present for the
   Plotly resize-on-show. The button strip is a <div role=tablist> of <button> tabs; panels carry
   .panel and are hidden unless .active. Degrades gracefully: with JS off, ALL panels show stacked
   (no data hidden) since :not(.active) only hides when the script has run (html.tabs-js). */
.tabs{margin-top:8px}
.tabs .tablist{display:flex;flex-wrap:wrap;gap:3px;border-bottom:1px solid var(--line)}
.tabs .tab{padding:7px 13px;font-size:13px;font-weight:600;color:var(--ink-2);cursor:pointer;
  border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;background:var(--surface-2);
  margin-bottom:-1px}
.tabs .tab:hover{color:var(--brand)}
.tabs .tab.active{background:var(--surface);color:var(--brand);box-shadow:0 -2px 0 var(--brand-accent) inset}
.tabs .tab.gap{color:var(--muted);opacity:.72}
.tabs .panel{border:1px solid var(--line);border-radius:0 8px 8px 8px;padding:16px 18px;
  background:var(--surface)}
html.tabs-js .tabs .panel{display:none}
html.tabs-js .tabs .panel.active{display:block}
/* Panel body: plots (left ~78%) + summary rail (right ~22%) — item 3. Stacks on narrow screens. */
.card-body{display:grid;grid-template-columns:minmax(0,3.5fr) minmax(200px,1fr);gap:20px;align-items:start}
@media(max-width:900px){.card-body{grid-template-columns:1fr}}
.card-plots{min-width:0}
.card-rail{font-size:12.5px;border-left:1px solid var(--line);padding-left:16px}
.card-rail .rail-h{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  font-weight:700;margin:0 0 6px}
.card-rail .rail-sec{margin:0 0 14px}
.card-rail .interp{background:var(--surface-2);border-radius:7px;padding:9px 11px;font-size:12.5px;
  line-height:1.5;color:var(--ink-2)}
.card-rail .kf{margin:0 0 7px}.card-rail .kf b{color:var(--brand);font-variant-numeric:tabular-nums;font-size:14px}
.card-rail .kf span{color:var(--muted);display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}
.panel .empty-note{color:var(--muted);font-size:13px;margin:4px 0}
/* Per-card panel: verdict strip + key-facts + plot */
.card-verdict{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px;
  padding:9px 12px;background:var(--surface-2);border-radius:8px;font-size:13.5px}
.card-verdict .drv{color:var(--muted);font-size:12px}
.card-verdict .drv code{font-size:11.5px}
.keyfacts{display:flex;flex-wrap:wrap;gap:8px 22px;margin:0 0 12px}
.keyfacts .kf{font-size:13px}.keyfacts .kf b{color:var(--brand);font-variant-numeric:tabular-nums}
.keyfacts .kf span{color:var(--muted);display:block;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
.card-src{font-size:11.5px;color:var(--muted);margin-top:10px}
.rules-tbl td code{font-size:11.5px}
.sig-pos{color:var(--pos-ink);font-weight:600}.sig-neg{color:var(--neg-ink);font-weight:600}
.sig-neu{color:var(--neu-ink)}.sig-kill{color:var(--neg-ink);font-weight:700}
/* GI-style components (Phase B PR-3) — About band + data-loaded status banner + navy section bars */
/* Provenance trace — per-sub-skill run record (collapsible, at the bottom). */
.trace-skill{margin:8px 0 12px;padding:8px 0 0;border-top:1px solid var(--line)}
.trace-h{margin:0 0 5px;font-size:13px}
table.trace-cards{width:100%;font-size:12px;border-collapse:collapse;margin:2px 0 4px}
table.trace-cards th{text-align:left;color:var(--muted);font-weight:600;padding:2px 8px}
table.trace-cards td{padding:2px 8px;border-top:1px solid var(--line-2);vertical-align:top}
tr.trace-missing{opacity:.55}
.about{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 20px;margin:0 0 18px}
.about .h{font-weight:700;color:var(--ink-2);font-size:13px;margin:0 0 8px;display:flex;align-items:center;gap:7px}
.about .h::before{content:"\\24D8";color:var(--brand-accent);font-size:15px}   /* circled i */
.about ul{margin:0;padding-left:20px;font-size:13.5px;color:var(--ink-2)}
.about li{margin:2px 0}
.about .citation{border-top:1px solid var(--line);margin-top:10px;padding-top:9px;
  font-size:12px;color:var(--muted);line-height:1.5}
.about .citation code{font-size:11.5px}
.statusbar{background:var(--pos-bg);border:1px solid #bfe3bf;border-left:4px solid var(--pos-ink);
  border-radius:8px;padding:9px 15px;margin:0 0 18px;font-size:13.5px;color:#144d14;font-weight:600;
  display:flex;align-items:center;gap:8px}
.statusbar::before{content:"\\2713";color:var(--pos-ink);font-weight:800}  /* check */
.statusbar .n{font-weight:400;color:#2c6b2c}
/* Section title bar — GI dark-navy band. Full-bleed left/right (no top-bleed: the small provenance
   tag chip sits above it as a kicker). One h2 per section, so a descendant selector is safe. */
section>h2,.llm>h2{background:var(--brand);color:#fff;margin:8px -20px 14px;
  padding:11px 20px;font-size:14.5px;letter-spacing:.005em}
section>h2 .n,.llm>h2 .n{color:rgba(255,255,255,.72)}
.llm>h2{background:var(--llm-ink)}                               /* AI sections: purple bar, not navy */
section>h2:first-child,.llm>h2:first-child{margin-top:-18px;border-radius:12px 12px 0 0}  /* no tag → hug top */
"""


# Vanilla-JS bootstrap: draw every embedded Plotly spec. No framework, DISPLAY-only (Plotly's own
# hover/zoom) — it re-derives NO evidence (honesty spine: light JS renders, never recomputes). Each
# spec rides in a <script type=application/json class=plotly-spec data-target=...> block next to its
# div; we parse + Plotly.newPlot into the target. Responsive; guarded so one bad spec can't blank the
# page.
_PLOTLY_BOOTSTRAP_JS = """<script>
(function(){
  function draw(){
    if(typeof Plotly==='undefined'){return setTimeout(draw,60);}   // wait for the inlined bundle
    var specs=document.querySelectorAll('script.plotly-spec');
    for(var i=0;i<specs.length;i++){
      try{
        var el=specs[i], tgt=document.getElementById(el.getAttribute('data-target'));
        if(!tgt||tgt.getAttribute('data-drawn'))continue;
        var fig=JSON.parse(el.textContent);
        (fig.layout=fig.layout||{}).autosize=true;
        Plotly.newPlot(tgt,fig.data,fig.layout,{responsive:true,displaylogo:false,
          modeBarButtonsToRemove:['lasso2d','select2d']});
        tgt.setAttribute('data-drawn','1');
      }catch(e){if(window.console)console.warn('plotly spec draw failed',e);}
    }
  }
  // A chart drawn inside a display:none tab panel has zero size → renders blank until resized.
  // On any tab radio toggle, resize every already-drawn plot in the newly-shown panel(s). Also
  // resize on window resize. This is what makes non-default subtabs (and their plots) render.
  function resizeVisible(){
    if(typeof Plotly==='undefined')return;
    document.querySelectorAll('.plotly-fig[data-drawn]').forEach(function(d){
      if(d.offsetParent!==null){try{Plotly.Plots.resize(d);}catch(e){}}   // offsetParent null = hidden
    });
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){draw();resizeVisible();});
  }else{draw();resizeVisible();}
  window.addEventListener('resize',resizeVisible);
  // Expose so the tab bootstrap can resize the plots in a panel it just revealed.
  window.__resizePlots=resizeVisible;
})();
</script>"""

# Tab bootstrap — ALWAYS emitted when gate sections are present (independent of Plotly). Adds
# html.tabs-js (which flips the panel CSS from "all shown, stacked" to "only .active shown"), then
# on a tab click toggles .active on the clicked button + its target panel within the same .tabs
# group, and asks the Plotly layer (if present) to resize the now-visible charts. No framework.
_TAB_BOOTSTRAP_JS = """<script>
(function(){
  document.documentElement.classList.add('tabs-js');
  document.addEventListener('click',function(e){
    var btn=e.target.closest?e.target.closest('.tabs .tab'):null;
    if(!btn)return;
    var group=btn.closest('.tabs');
    var pid=btn.getAttribute('data-panel');
    group.querySelectorAll(':scope > .tablist > .tab').forEach(function(t){t.classList.remove('active');});
    group.querySelectorAll(':scope > .panel').forEach(function(p){p.classList.remove('active');});
    btn.classList.add('active');
    var pan=document.getElementById(pid); if(pan)pan.classList.add('active');
    if(window.__resizePlots)setTimeout(window.__resizePlots,0);
  });
})();
</script>"""


def _esc(x) -> str:
    return _html.escape(str(x if x is not None else "—"), quote=True)


def _inline_svg(svg_path: Optional[Path]) -> Optional[str]:
    """Read an emitted matplotlib SVG (svg.fonttype:none → text-preserving) and return its
    <svg>...</svg> body for inline embedding. Strips the XML/doctype preamble so it drops into
    the page. Returns None on any failure (render never blocks on the figure)."""
    if not svg_path or not Path(svg_path).exists():
        return None
    try:
        raw = Path(svg_path).read_text()
        i = raw.find("<svg")
        if i < 0:
            return None
        body = raw[i:]
        # Strip matplotlib's fixed pt width/height on the root <svg> so it scales to the card
        # (the viewBox preserves the aspect ratio). Belt-and-suspenders with the CSS rule.
        end = body.find(">")
        head, rest = body[:end], body[end:]
        head = re.sub(r'\s(width|height)="[^"]*"', "", head)
        return head + rest
    except Exception:  # noqa: BLE001
        return None


def _mtx_cell_class(cell: dict) -> str:
    if cell.get("signal") is None:
        return ""
    o = cell.get("ordinal")
    if o is None:
        return "off"
    return {2: "p2", 0: "p0", -1: "n1", -3: "n3"}.get(o, "p0")


def _prettify_field(key: str) -> str:
    """A summary-field key → readable label (snake/camel → words)."""
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
    return k[:1].upper() + k[1:]


def _plotly_bundle() -> Optional[str]:
    """The plotly.js source, for INLINING into the self-contained report (no CDN, no external src).
    ~4.6 MB — the deliberate weight of the dynamic dashboard. Cached; None if plotly is absent (the
    report then degrades to static SVG/table). NOTE: an inlined-plotly report is too large for the
    VS Code Simple Browser to render — download + open in a real browser to review it."""
    global _PLOTLY_JS_CACHE
    try:
        return _PLOTLY_JS_CACHE
    except NameError:
        pass
    try:
        from plotly.offline import get_plotlyjs
        _PLOTLY_JS_CACHE = get_plotlyjs()
    except Exception:  # noqa: BLE001
        _PLOTLY_JS_CACHE = None
    return _PLOTLY_JS_CACHE


def _read_card_plotly_specs(card_figures: Optional[dict], figures_dir: Optional[Path],
                            card_id: str) -> list[dict]:
    """For a card, load its interactive Plotly specs (the `dynamic: True` descriptors produced this
    run) from disk. Returns [{id, title, spec_json(str)}], newest-schema-safe. Empty when no dynamic
    figure was produced (→ the card renders its static table only — the fallback)."""
    if not card_figures or not figures_dir:
        return []
    out = []
    for f in card_figures.get(card_id) or []:
        if not f.get("dynamic"):
            continue
        spec_path = figures_dir / f["path"]
        try:
            spec_json = spec_path.read_text()
        except Exception:  # noqa: BLE001 — a missing spec just drops to the static view
            continue
        out.append({"id": f["id"], "spec_json": spec_json})
    return out


def _render_card_data_html(sub_results: dict, card_figures: Optional[dict] = None,
                           figures_dir: Optional[Path] = None) -> tuple[list[str], int]:
    """Per-question 'Evidence' section: render each sub-skill's card SUMMARY metrics (already in
    sub_results from resolve_cards) as clean data, PLUS — when a run produced them (Phase B) —
    the card's interactive Plotly figure(s) embedded inline. Leads with the PHASE_METRIC_FIELDS
    curated key metrics; otherwise shows the card's scalar summary fields.

    Returns (html_lines, n_plotly_embedded). A card with a dynamic spec shows the interactive chart
    above its data table; a card without one shows the table alone (the static fallback). The plot
    is a computed, provenanced artifact (drawn by the method from the same series as the SVG) — the
    renderer only EMBEDS it, never re-plots (honesty spine: renderer adds nothing)."""
    out = ["<section id=s-evidence class=det><span class=tag>Computed from the evidence</span>"
           "<h2>Evidence by question <span class=n>— the card data behind each call</span></h2>"]
    n_plotly = 0
    for short, r in sub_results.items():
        cards = r.get("cards") or []
        # gather scalar summary fields across this sub-skill's cards (skip private _ + nested)
        rows: list[tuple[str, str]] = []
        curated = PHASE_METRIC_FIELDS.get(short, [])
        seen = set()
        for field, label in curated:
            val = _first_card_summary_field(r, field)
            if val is not None:
                rows.append((label, _fmt_metric(val))); seen.add(field)
        for c in cards:
            if c.get("_missing"):
                continue
            for k, v in (c.get("summary") or {}).items():
                if k.startswith("_") or k in seen or isinstance(v, (list, dict)):
                    continue
                rows.append((_prettify_field(k), _fmt_metric(v))); seen.add(k)
        label = _GATE_SHORT_LABEL.get(short, _humanize(short))
        # Interactive figures produced for this sub-skill's cards this run (Phase B). Embedded as a
        # <div> + JSON <script>; the bootstrap at page end calls Plotly.newPlot. Absent → table only.
        plot_divs: list[str] = []
        for c in cards:
            if c.get("_missing"):
                continue
            for spec in _read_card_plotly_specs(card_figures, figures_dir, c.get("card_id")):
                dom_id = f"plt-{short}-{spec['id']}"
                plot_divs.append(
                    f"<div class=plotly-fig id={dom_id}></div>"
                    f"<script type='application/json' class=plotly-spec data-target={dom_id}>"
                    f"{spec['spec_json']}</script>")
                n_plotly += 1
        if not rows and not plot_divs:
            missing = [c["card_id"] for c in cards if c.get("_missing")]
            note = ("no card data (cards not available this run: "
                    + ", ".join(f"<code>{_esc(m)}</code>" for m in missing) + ")") if missing \
                    else "no scalar metrics emitted"
            out.append(f"<details><summary>{_esc(label)}</summary>"
                       f"<p class=sub>{note}.</p></details>")
            continue
        out.append(f"<details open><summary>{_esc(label)}</summary>")
        out.extend(plot_divs)                          # interactive chart(s) lead
        if rows:
            out.append("<table>")
            for lab, val in rows[:18]:   # cap to keep the section scannable
                out.append(f"<tr><td style='color:var(--muted);width:45%'>{_esc(lab)}</td>"
                           f"<td>{_esc(val)}</td></tr>")
            out.append("</table>")
        out.append("</details>")
    out.append("</section>")
    return out, n_plotly


# --- Gate section with subtabs (iterative dashboard, 2026-07-21) ------------------------------
# One gate (A–H) rendered as a section card with a radio-tab strip: Plots | Evidence | Rules.
# PURE PROJECTION — reads the same sub_results + card_figures the flat view uses; recomputes nothing.
# Scoped rollout: only the Presence gate (A / expression) is wired into the report today; the shared
# helper is gate-agnostic so the remaining gates slot in later without a rewrite.

_SIG_CLASS = {"supportive": "sig-pos", "opposing": "sig-neg", "killer": "sig-kill",
              "neutral": "sig-neu", "insufficient": "sig-neu"}

# Human title + one-line "what it shows" per presence-gate card. Keeps the subtab label short and
# the panel self-explaining. Extend as more gates migrate to the card-subtab style.
_CARD_TITLE = {
    # Selective (B)
    "tumor-vs-normal-selectivity":  ("Tumor-vs-normal", "3-cell sensitivity DEG (adjacent + GTEx comparators)"),
    # Mechanism (D)
    "signaling-network-mechanism":  ("Signaling network", "SIGNOR/CollecTri/Reactome MoA context"),
    # Presence (A)
    "cellline-rna-distribution":      ("Cell-line RNA", "DepMap pan-cancer expression distribution"),
    "tumor-rna-vs-adjacent": ("Tumor vs adjacent RNA", "TCGA tumor-vs-paired-normal DEG"),
    "tumor-protein-abundance-cptac":       ("Tumor protein (CPTAC)", "per-cohort tumor-vs-normal protein"),
    "cellline-protein-abundance":    ("Cell-line protein", "Gygi TMT MS abundance distribution"),
    "tumor-elevation-breadth":      ("Pan-cancer breadth", "elevated in K of N cancers"),
    # Required (C) — primary dependency evidence
    "pan-cancer-crispr-dependency-distribution": ("CRISPR dependency", "DepMap Chronos pan-cancer distribution"),
    "pan-cancer-rnai-dependency-distribution":   ("RNAi dependency", "DEMETER2 pan-cancer distribution"),
    "dependency-lineage-selectivity":            ("Lineage selectivity", "per-lineage Chronos forest"),
    "paralog-buffering":                         ("Paralog buffering", "dual-KO buffering (masks single-gene dep)"),
    # Required (C) — biomarker facets (see _CARD_V2_ROLE)
    "crispr-rnai-dependency-concordance": ("CRISPR×RNAi", "two LOF assays agree (corroboration)"),
    "prism-crispr-concordance":           ("Chemical-genetic", "compound kill tracks dependency (corroboration)"),
    "dependency-predictability":          ("Predictability", "how omics-learnable the dependency is (corroboration)"),
    "mutation-stratified-dependency":     ("Mutation-stratified", "dependency by mutation status (patient-selection)"),
    "expression-dependency-correlation":  ("Expression biomarker", "expression predicts dependency (patient-selection)"),
    "synthetic-lethal-partners":          ("SL partners", "curated synthetic-lethal context (patient-selection)"),
    # Surface-biologics modality-fit (axis 2) — composed verdict + its inputs
    "adc-tce-modality-fit":         ("ADC/TCE fit", "composed modality verdict (topology + family + structure)"),
    "surface-topology-and-ptm":     ("Topology & PTM", "TMbed transmembrane + endocytosis + PTM sites"),
    "surfaceome-family-classification": ("Surfaceome family", "SURFY/HPA surface-residency class"),
    "structure-features-static":    ("Structure", "PDB/AlphaFold pocket + disorder features"),
    "surface-abundance-density":    ("Surface density", "copies-per-cell estimate (TCE viability)"),
    # Small-molecule tractability (modality-fit)
    "prism-compound-activity":      ("Compound activity", "PRISM per-compound kill across cell lines"),
    # Safety (modality-fit)
    "gnomad-lof-constraint":        ("Germline constraint", "gnomAD LoF-intolerance (pLI / LOEUF)"),
}

# v2 role of a card WITHIN its gate (gate-model v2, docs/design/GATE_MODEL_V2_MEMO.md). Cards not
# listed are `primary` (the gate's own necessity evidence). Facets modulate the gate verdict:
#   corroboration  → agreement between measures of the same thing → CONFIDENCE in the verdict
#   stratification → a feature partitions the outcome → PATIENT-SELECTION (who responds)
_CARD_V2_ROLE = {
    # Required (C) biomarker facets
    "crispr-rnai-dependency-concordance": "corroboration",
    "prism-crispr-concordance":           "corroboration",
    "dependency-predictability":          "corroboration",
    "mutation-stratified-dependency":     "stratification",
    "expression-dependency-correlation":  "stratification",
    "synthetic-lethal-partners":          "stratification",
    # Surface-biologics (modality-fit): the composed verdict leads; the rest are its inputs.
    "adc-tce-modality-fit":               "composed",
}
_V2_ROLE_BADGE = {
    "composed":       ("verdict", "chip-pos"),
    "corroboration":  ("confidence", "chip-neu"),
    "stratification": ("patient-selection", "chip-pos"),
}

# reports_into (gate-model v2): cards whose HOME gate differs from a gate they ALSO feed. The
# dashboard renders each card under its home gate section; a breadcrumb ("also feeds <Gate>")
# surfaces the cross-gate contribution. These edges already exist as veto-suppressors / positive
# cross-refs in nomination_verdict_gate.yaml — this only makes them LEGIBLE in the dashboard.
#
# The map {card_id: [(label, anchor), ...]} is now BUILT FROM THE CONTRACT (_card_reports_into),
# reading each card-grain biomarker_facet's `card_id` + `reports_into` (v2 2.0.0). The hardcoded
# fallback below is used only when the contract carries no facet data (the v1 merge window, or a
# missing vocab) — same fail-open discipline as the loader: a missing contract never erases the
# breadcrumbs, it falls back to the last-known-good static map.
_CARD_REPORTS_INTO_FALLBACK = {
    "prism-crispr-concordance":       [("Required (C)", "s-gate-c")],
    "dependency-predictability":      [("Required (C)", "s-gate-c")],
    "mutation-stratified-dependency": [("Required (C)", "s-gate-c")],
}


def _card_reports_into(contracts_repo: Path | None = None) -> dict:
    """{card_id: [(label, anchor), ...]} of cross-gate breadcrumb edges, read from the contract's
    card-grain biomarker_facets (card_id + reports_into). Each reports_into target short resolves to
    its section anchor (_SHORT_TO_GATE_ANCHOR) + a human label (letter/name from the gate map). A
    self-edge (target == the card's own home gate) is dropped by the renderer, not here. Falls back
    to _CARD_REPORTS_INTO_FALLBACK when the contract exposes no card-grain facets (v1 window)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "gate_coverage.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        facets = data.get("biomarker_facets", []) or []
    except Exception:  # noqa: BLE001 — missing/malformed vocab → fall back, never erase breadcrumbs
        facets = []
    # short → human gate label (e.g. dependency → "Required (C)"); built from the loaded baseline so
    # letters/names track the contract. Biology gates: "<name> (<letter>)"; modality-fit: "<name>".
    baseline, _src = _load_gate_coverage(contracts_repo)
    def _label(short: str) -> str:
        m = baseline.get(short, {})
        nm, letter = m.get("gate_name") or _humanize(short), m.get("gate")
        return f"{nm} ({letter})" if letter else nm
    out: dict = {}
    for f in facets:
        cid = f.get("card_id")
        if not cid or f.get("grain") != "card":
            continue
        edges = [(_label(s), _SHORT_TO_GATE_ANCHOR[s]) for s in (f.get("reports_into") or [])
                 if s in _SHORT_TO_GATE_ANCHOR]
        if edges:
            out[cid] = edges
    return out or {k: list(v) for k, v in _CARD_REPORTS_INTO_FALLBACK.items()}

# Roll-up lens: sub-skill short → the gate SECTION anchor it belongs to (the id _render_gate_section_html
# emits). Lets the top scorecard link each question-row down to its detailed section. MUST stay in sync
# with _GATE_SECTIONS in _render_target_profile_html (biology gates → s-gate-<letter>; modality-fit gates
# → s-gate-<name-slug>). Sub-skills that report_into another gate but have their own section link to their
# HOME section (e.g. synthetic_lethal_partners + genomic_alteration are unified UNDER Required's section).
_SHORT_TO_GATE_ANCHOR = {
    "expression":                "s-gate-a",
    "selectivity":               "s-gate-b",
    "dependency":                "s-gate-c",
    "synthetic_lethal_partners": "s-gate-c",   # unified under Required's section
    "mechanism":                 "s-gate-d",
    "genomic_alteration":        "s-gate-e",   # v2: its own "Altered" biology gate (E)
    "tractability_sm":           "s-gate-small-molecule-druggability",
    "surface_modality":          "s-gate-surface-biologics-fit",
    "safety":                    "s-gate-safety",
}
# Which summary fields to surface as the card's "key facts" (label, field). First hit wins per card;
# unknown cards fall back to their first ~4 scalar summary fields.
_CARD_KEYFACTS = {
    "cellline-rna-distribution": [("Call", "expression_call_class"), ("Median log2TPM", "median_log2tpm_panel"),
                                ("Cell lines", "n_cell_lines"),
                                # additive isoform-EXPRESSION facet (roadmap #2 model arm): WHICH transcript
                                # carries the expression — a single-isoform target is a cleaner modality/
                                # epitope target; isoform_diverse flags that the druggable isoform must be
                                # specified (complements the mechanism isoform_selective_warning note).
                                ("Isoform", "isoform_expression_class"),
                                ("Dominant-iso frac", "dominant_isoform_fraction")],
    "tumor-rna-vs-adjacent": [("Call", "expression_call_class"), ("log2FC", "log2_fc"),
                                     ("q-value", "q_value")],
    "tumor-protein-abundance-cptac": [("Class", "protein_expression_class"), ("Effect size", "protein_effect_size"),
                               ("Cohort", "cohort"), ("n tumor", "n_tumor_samples"),
                               ("n normal", "n_normal_samples")],
    "cellline-protein-abundance": [("Class", "protein_expression_class")],
    "tumor-elevation-breadth": [("Breadth", "tumor_elevation_breadth_class"),
                                ("Protein K/N", "n_cohorts_elevated"), ("RNA K/N", "rna_n_indications_elevated")],
    # Required (C)
    "pan-cancer-crispr-dependency-distribution": [("Class", "dependency_class"),
                                                  ("Median Chronos", "median_chronos_panel"),
                                                  ("% dependent", "fraction_dependent")],
    "pan-cancer-rnai-dependency-distribution": [("Class", "dependency_class"),
                                                ("Median DEMETER2", "median_demeter2")],
    "dependency-lineage-selectivity": [("Selectivity", "lineage_selectivity_class"),
                                       ("Selective lineages", "n_selective_lineages")],
    "paralog-buffering": [("Buffering", "paralog_buffering_class"),
                          ("Strongest paralog", "strongest_paralog_symbol")],
    "crispr-rnai-dependency-concordance": [("Concordance", "concordance_class")],
    "prism-crispr-concordance": [("Class", "crispr_prism_concordance_class"),
                                 ("Compounds", "n_compounds_evaluated")],
    "dependency-predictability": [("Predictability", "predictability_class"),
                                  ("Top feature", "pred_dominant_feature_class")],
    "mutation-stratified-dependency": [("Class", "mutation_stratification_class"),
                                       ("Hotspot q", "hotspot_mannwhitney_q")],
    "expression-dependency-correlation": [("Correlation", "correlation_class")],
    "synthetic-lethal-partners": [("SL class", "sl_partner_class"),
                                  ("Strongest partner", "strongest_partner_symbol")],
    # Surface-biologics modality-fit
    "adc-tce-modality-fit": [("Fit", "fit_class"), ("ADC topology", "is_adc_topology_favorable"),
                             ("TCE topology", "is_tce_topology_favorable")],
    "surface-topology-and-ptm": [("TM passes", "tm_pass_count"), ("EC residues", "extracellular_residue_count"),
                                 ("Endo motifs", "endocytosis_motif_count_high_confidence")],
    "surfaceome-family-classification": [("Surface?", "is_surface_protein"), ("Family", "family_class")],
    "structure-features-static": [("Druggable pocket", "has_druggable_pocket"), ("Disorder", "disorder_fraction")],
    "surface-abundance-density": [("Copies/cell", "estimated_copies_per_cell"),
                                  ("TCE-viable", "above_tce_threshold")],
    # Selective (B)
    "tumor-vs-normal-selectivity": [("Selectivity", "selectivity_class"),
                                    ("Cells supporting", "cells_supporting"), ("Direction", "dominant_direction")],
    # Mechanism (D)
    "signaling-network-mechanism": [("Network", "network_class"), ("Upstream", "n_upstream_regulators"),
                                    ("Downstream", "n_downstream_effectors")],
    # Small-molecule tractability (modality-fit)
    "prism-compound-activity": [("Activity", "prism_activity_class"), ("Compounds", "n_compounds_targeting"),
                                ("Top clinical phase", "highest_clinical_phase")],
    # Safety (modality-fit)
    "gnomad-lof-constraint": [("Constraint", "constraint_class"), ("pLI", "pli_score"), ("LOEUF", "loeuf_score")],
}


# Per-card figure curation for the gate subtabs: which figure ids to show, in order. A card that
# emits several figures may want only a subset surfaced in the dashboard (the rest stay in the
# data package). None → show all, in emit order. Presence gate: Cell-line RNA leads with the
# pan-cancer DENSITY then the per-LINEAGE box (the indication-relevant view); the ranked waterfall
# is available in the package but not surfaced here (redundant with the density for this section).
_CARD_FIGURE_ORDER = {
    "cellline-rna-distribution": ["density_expression", "lineage_expression"],
    # cell-line protein (item #2): density (bucket-shaded) + per-lineage box, mirroring RNA;
    # the ranked waterfall is emitted but not surfaced in the subtab (matches the RNA card).
    "cellline-protein-abundance": ["density_protein_abundance", "lineage_protein_abundance"],
}


def _card_plot_divs(card_id: str, card_figures, figures_dir) -> tuple[list[str], int]:
    """Interactive Plotly divs for ONE card (same embed the flat view uses). When the card has a
    curated figure order (_CARD_FIGURE_ORDER), only those ids are shown, in that order."""
    specs = {s["id"]: s for s in _read_card_plotly_specs(card_figures, figures_dir, card_id)}
    order = _CARD_FIGURE_ORDER.get(card_id) or list(specs.keys())
    divs, n = [], 0
    for sid in order:
        spec = specs.get(sid)
        if not spec:
            continue
        dom_id = f"plt-card-{card_id}-{spec['id']}"
        divs.append(f"<div class=plotly-fig id={dom_id}></div>"
                    f"<script type='application/json' class=plotly-spec data-target={dom_id}>"
                    f"{spec['spec_json']}</script>")
        n += 1
    return divs, n


def _fmt_fact_value(value):
    """Rail key-metric value formatter: numbers via _fmt_metric, but snake_case STRING enums are
    humanized (broadly_high → "Broadly high") so raw tokens never leak into visible dashboard text.
    (The .md table keeps _fmt_metric's backticked raw values — code style there is fine.)"""
    if isinstance(value, str) and value and not value.replace(".", "").replace("-", "").isdigit():
        return _humanize(value)
    return _fmt_metric(value)


def _card_key_facts(card: dict) -> list[tuple[str, str]]:
    """The card's headline facts (label, formatted value) — curated per card, else first scalars."""
    cid = card.get("card_id")
    summ = card.get("summary") or {}
    facts: list[tuple[str, str]] = []
    for label, field in _CARD_KEYFACTS.get(cid, []):
        if summ.get(field) is not None:
            facts.append((label, _fmt_fact_value(summ[field])))
    if not facts:   # fallback: first few scalar summary fields
        for k, v in summ.items():
            if k.startswith("_") or isinstance(v, (list, dict)):
                continue
            facts.append((_prettify_field(k), _fmt_fact_value(v)))
            if len(facts) >= 4:
                break
    return facts


def _card_fired_rules(card_id: str, fired: list) -> list[dict]:
    """The fired rules attributable to THIS card (by card_id)."""
    return [f for f in (fired or []) if isinstance(f, dict) and f.get("card_id") == card_id]


# Indication → DepMap OncotreeLineage (cell lines are lineage-keyed; the indication-relevant
# cell-line view is its lineage). Mirrors the method-side map; kept here so the renderer can pull
# the indication's lineage row without importing the method.
_INDICATION_LINEAGE = {
    "COADREAD": "Bowel", "COAD": "Bowel", "READ": "Bowel", "PDAC": "Pancreas", "PAAD": "Pancreas",
    "NSCLC": "Lung", "LUAD": "Lung", "LUSC": "Lung", "SCLC": "Lung", "GC": "Stomach", "STAD": "Stomach",
    "BRCA": "Breast", "OV": "Ovary/Fallopian Tube", "GBM": "CNS/Brain", "HNSCC": "Head and Neck",
}


def _expression_indication_focus(card: dict, indication: str) -> Optional[dict]:
    """Item 4: for the cell-line RNA card, pull the INDICATION's lineage row from per_lineage_stats
    (COADREAD→Bowel) and build human-readable interpretation. Returns None if not applicable / no
    lineage data. Output: {lineage, median_log2tpm, fraction_expressed, n, rank, n_lineages, interp}."""
    summ = card.get("summary") or {}
    stats = summ.get("per_lineage_stats")
    if not indication or not isinstance(stats, list) or not stats:
        return None
    lineage = _INDICATION_LINEAGE.get(indication.upper())
    if not lineage:
        return None
    # per_lineage_stats is sorted by median_log2tpm desc → index = rank
    row = None
    for i, s in enumerate(stats):
        if s.get("lineage") == lineage:
            row = dict(s); row["rank"] = i + 1
            break
    n_lin = summ.get("n_lineages_evaluated") or len(stats)
    if row is None:
        # indication's lineage not among the evaluated lineages (below the n≥5 floor, or absent)
        return {"lineage": lineage, "absent": True, "n_lineages": n_lin,
                "interp": (f"No {lineage} cell-line cohort cleared the n≥5 floor in DepMap this "
                           f"release, so a {indication}-lineage expression readout isn't available "
                           f"— the pan-cancer distribution is the only cell-line view here.")}
    med = row.get("median_log2tpm")
    frac = row.get("fraction_expressed")
    n = row.get("n")
    rank = row.get("rank")
    # human-readable interpretation (bucketed against the 1.0 / 5.0 reflines)
    if med is None:
        level = "unknown"
    elif med >= 5.0:
        level = "highly expressed"
    elif med >= 1.0:
        level = "expressed"
    else:
        level = "low / not expressed"
    pct = f"{frac*100:.0f}%" if isinstance(frac, (int, float)) else "—"
    med_str = f"{med:.1f}" if isinstance(med, (int, float)) else "n/a"
    interp = (f"In {lineage} cell lines ({indication}'s DepMap lineage; n={n}), the target is "
              f"<b>{level}</b> — median log2(TPM+1) {med_str}, {pct} of lines above the expressed "
              f"threshold. It ranks {rank} of {n_lin} lineages by median expression"
              + (" (among the highest)." if rank and rank <= 3 else
                 " (mid-to-low among lineages)." if rank and rank > n_lin/2 else "."))
    return {"lineage": lineage, "median_log2tpm": med, "fraction_expressed": frac,
            "n": n, "rank": rank, "n_lineages": n_lin, "interp": interp, "level": level}


def _render_gate_section_html(gate: str, gate_name: str, shorts: list[str], sub_results: dict,
                              scorecard_by_short: dict, card_figures, figures_dir,
                              indication: str = None, modality_note: str = None,
                              reports_into_map: dict | None = None,
                              exclude_card_ids: set | None = None,
                              include_only_card_ids: list | None = None) -> tuple[list[str], int]:
    """Render ONE gate as a section whose SUBTABS are its evidence CARDS. Each card subtab shows,
    top-to-bottom: a verdict strip (the rule/verdict this card drove), the card's key facts, and its
    interactive Plotly figure. PURE PROJECTION — recomputes nothing. Returns (html, n_plotly).

    `shorts` are the sub-skills grouped under this gate letter (usually one; C has several). A gate's
    cards are the union of its sub-skills' cards, in declaration order. Cards with no data this run
    still get a subtab (greyed 'gap' label) — a coverage gap is shown, never hidden.
    `modality_note`: for axis-2 (modality-fit) gates, a one-line 'relevant for <modalities>' banner —
    the gate's relevance is lens-conditional (gate-model v2)."""
    # section id + tab-group key: gate letter if lettered, else a slug of the gate_name (modality-fit
    # gates are NAMED, not lettered in v2). glow is the unique key used for panel ids + tab scoping.
    glow = gate.lower() if gate else re.sub(r"[^a-z0-9]+", "-", gate_name.lower()).strip("-")
    sec_id = f"s-gate-{glow}"
    # No "Computed from the evidence" tag on gate sections — it's redundant chrome repeated on every
    # gate (the whole Biology/Modality-fit axis IS the deterministic evidence; the AI-generated
    # exec summary is the only section that needs a provenance tag).
    out = [f"<section id={sec_id} class='det gate'>"]

    # header: gate letter + name + roll-up verdict chip(s) (the gate's own sub-verdict). A
    # facet-collection section (include_only_card_ids, e.g. Biomarker) has NO single sub-verdict —
    # it's a set of relational facet cards, each with its own role badge — so suppress the chips.
    _is_facet_section = include_only_card_ids is not None
    chips = []
    if not _is_facet_section:
        for short in shorts:
            row = scorecard_by_short.get(short) or {}
            glyph, cls, _lab = _HTML_STATUS.get(row.get("status"), _HTML_STATUS["coverage_gap"])
            chips.append(f"<span class='chip {cls}'><span class=g>{glyph}</span>"
                         f"{_esc(_humanize(row.get('verdict') or 'not evaluated'))}</span>")
    q = (gate_name if (_is_facet_section or len(shorts) != 1)
         else _GATE_SHORT_LABEL.get(shorts[0], _humanize(shorts[0])))
    letter = f"<span class=gate-letter>{_esc(gate)}</span>" if gate else ""   # named (modality-fit) gates: no letter
    out.append(f"<div class=gate-head>{letter}"
               f"<h2 style='margin:0;background:none;color:var(--brand);padding:0'>{_esc(gate_name)} "
               f"<span class=n>— {_esc(q)}</span></h2>"
               f"<span class=gate-verdict>{''.join(chips)}</span></div>")
    if modality_note:
        # axis-2 lens banner: this gate's relevance is modality-conditional (gate-model v2).
        out.append(f"<div class=banner style='margin-top:6px'>{_esc(modality_note)}</div>")

    # collect this gate's cards (union across sub-skills), each with its owning sub-skill's fired rules.
    # exclude_card_ids: facet cards routed OUT to the Biomarker section (so gates C/E don't double-show
    # them). include_only_card_ids: when set (the Biomarker section), keep ONLY these cards + render in
    # that order — collecting the facet cards from wherever their sub-skills live.
    excl = exclude_card_ids or set()
    cards: list[tuple[dict, list]] = []
    for short in shorts:
        r = sub_results.get(short, {})
        fired = r.get("fired") or []
        for c in (r.get("cards") or []):
            cid = c.get("card_id")
            if cid in excl:
                continue
            if include_only_card_ids is not None and cid not in include_only_card_ids:
                continue
            cards.append((c, fired))
    if include_only_card_ids is not None:
        # order by the requested include list (stable) so the Biomarker section reads intentionally
        _ord = {cid: i for i, cid in enumerate(include_only_card_ids)}
        cards.sort(key=lambda cf: _ord.get(cf[0].get("card_id"), 999))
    if not cards:
        out.append("<p class=empty-note>No evidence cards ran for this gate this run.</p></section>")
        return out, 0

    # v2 ordering: PRIMARY (the gate's own necessity evidence) first, then biomarker FACETS
    # (corroboration → confidence, stratification → patient-selection). Stable within each group.
    # composed verdict FIRST (-1); then primary (0); then facets (corroboration, stratification).
    _role_order = {"composed": -1, None: 0, "corroboration": 1, "stratification": 2}
    cards.sort(key=lambda cf: _role_order.get(_CARD_V2_ROLE.get(cf[0].get("card_id")), 0))

    n_plotly_total = 0
    # default tab = first card that has a live plot, else first card
    default_idx = 0
    for i, (c, _f) in enumerate(cards):
        if _card_plot_divs(c.get("card_id"), card_figures, figures_dir)[0]:
            default_idx = i
            break

    # tablist (buttons) + panels. JS (page bootstrap) toggles .active on click; a panel is
    # data-tabgroup-scoped so gates switch independently. Panel id = <sec_id>-p<i>.
    tabs = [f"<div class=tabs data-tabgroup={sec_id}>", "<div class=tablist role=tablist>"]
    panels = []
    for i, (c, fired) in enumerate(cards):
        cid = c.get("card_id")
        title, _blurb = _CARD_TITLE.get(cid, (_humanize(cid), ""))   # blurb no longer shown (was mislabeling multi-plot cards)
        missing = c.get("_missing")
        active = " active" if i == default_idx else ""
        pid = f"{sec_id}-p{i}"
        lab_cls = " gap" if missing else ""
        # v2 role badge (confidence / patient-selection) on facet cards; primary cards get none.
        role = _CARD_V2_ROLE.get(cid)
        badge = ""
        if role and role in _V2_ROLE_BADGE:
            btxt, bcls = _V2_ROLE_BADGE[role]
            badge = f"<span class='chip {bcls}' style='margin-left:6px;font-size:9.5px;padding:1px 6px'>{btxt}</span>"
        tabs.append(f"<button class='tab{lab_cls}{active}' data-panel={pid}>{_esc(title)}{badge}</button>")

        pan = [f"<div class='panel{active}' id={pid}>"]
        if missing:
            pan.append(f"<p class=empty-note>{_esc(title)} — card not available this run "
                       f"(<code>{_esc(cid)}</code>). Coverage gap, not a negative.</p></div>")
            panels.append("".join(pan)); continue

        # 2-column body (item 3): plots (left) + summary rail (right).
        pan.append("<div class=card-body>")

        # -- LEFT: the interactive plot(s) --
        divs, npl = _card_plot_divs(cid, card_figures, figures_dir)
        n_plotly_total += npl
        pan.append("<div class=card-plots>")
        if divs:
            pan.extend(divs)
        else:
            pan.append("<p class=empty-note>No chart produced this run — the summary metrics "
                       "are at right; a static/summary run embeds no plot for this card.</p>")
        pan.append("</div>")   # .card-plots

        # -- RIGHT: summary rail — key facts, indication focus (item 4), rule/verdict fired --
        pan.append("<div class=card-rail>")
        facts = _card_key_facts(c)
        if facts:
            pan.append("<div class=rail-sec><p class=rail-h>Key metrics</p>")
            for label, val in facts:
                pan.append(f"<div class=kf><span>{_esc(label)}</span><b>{_esc(val)}</b></div>")
            pan.append("</div>")
        # indication-lineage focus (cell-line RNA): metric + human-readable interpretation
        focus = _expression_indication_focus(c, indication) if cid == "cellline-rna-distribution" else None
        if focus:
            pan.append(f"<div class=rail-sec><p class=rail-h>{_esc(indication)} focus "
                       f"({_esc(focus['lineage'])})</p>")
            if not focus.get("absent"):
                pan.append(f"<div class=kf><span>Median log2TPM</span><b>{focus['median_log2tpm']:.1f}</b></div>"
                           if isinstance(focus.get('median_log2tpm'), (int, float)) else "")
                if isinstance(focus.get("fraction_expressed"), (int, float)):
                    pan.append(f"<div class=kf><span>% lines expressed</span>"
                               f"<b>{focus['fraction_expressed']*100:.0f}%</b></div>")
                if focus.get("rank"):
                    pan.append(f"<div class=kf><span>Lineage rank</span>"
                               f"<b>{focus['rank']} / {focus['n_lineages']}</b></div>")
            pan.append(f"<div class=interp>{focus['interp']}</div>")
            pan.append("</div>")
        # rule / verdict fired for this card
        crules = _card_fired_rules(cid, fired)
        pan.append("<div class=rail-sec><p class=rail-h>Rule fired</p>")
        if crules:
            top = crules[0]
            sigs = top.get("signals") or {}
            sig_html = " · ".join(
                f"<span class={_SIG_CLASS.get(v, 'sig-neu')}>{_esc(m)}: {_esc(v)}</span>"
                for m, v in sigs.items()) or "—"
            pan.append(f"<div><code>{_esc(top.get('rule_id'))}</code></div>"
                       f"<div style='margin-top:4px'>{sig_html}</div>")
        else:
            pan.append("<div class=sub>No rule fired (neutral / below threshold).</div>")
        pan.append("</div>")
        # reports_into breadcrumb (v2): if this card ALSO feeds other gate(s), name them — read from
        # the contract (reports_into_map, {card_id: [(label, anchor), ...]}) with a fallback to the
        # static map. Self-edges (target == the section we're already in) are dropped, so a card
        # rendered under its home gate never "also feeds" itself.
        rmap = reports_into_map if reports_into_map is not None else _CARD_REPORTS_INTO_FALLBACK
        edges = [(lbl, anc) for (lbl, anc) in (rmap.get(cid) or []) if anc != sec_id]
        if edges:
            links = " · ".join(f"<a href='#{anc}' style='color:var(--brand-accent);"
                               f"text-decoration:none'>→ {_esc(lbl)}</a>" for lbl, anc in edges)
            pan.append(f"<div class=rail-sec><p class=rail-h>Also feeds</p>"
                       f"<div class=sub>{links} "
                       f"(this evidence corroborates that gate too)</div></div>")
        # Data-source / version tag: card readers stamp summary._data_source with the derived-
        # manifest id or release-pinned source (e.g. "DepMap-26Q1 Chronos",
        # "coadread-dge-tumor-vs-normal-sensitivity-v1", "recount3-tcga-gtex-2023-01-04"). Surface it
        # so each panel names WHICH data product + version it resolved against (provenance at a glance,
        # mirroring provenance.yaml's data_provenance). _data_s3_uri, when present, is the hover title.
        csum = c.get("summary") or {}
        dsrc = csum.get("_data_source")
        if dsrc:
            title = csum.get("_data_s3_uri") or ""
            title_attr = f" title='{_esc(str(title))}'" if title else ""
            pan.append(f"<div class=rail-sec><p class=rail-h>Data source</p>"
                       f"<div class=sub{title_attr}><code>{_esc(str(dsrc))}</code></div></div>")
        pan.append(f"<p class=card-src>Card <code>{_esc(cid)}</code></p>")
        pan.append("</div>")   # .card-rail

        pan.append("</div>")   # .card-body
        pan.append("</div>")   # .panel
        panels.append("".join(pan))

    tabs.append("</div>")     # .tablist
    out.extend(tabs)
    out.extend(panels)
    out.append("</div></section>")   # .tabs
    return out, n_plotly_total


def _render_target_profile_html(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
    scorecard: Optional[list[dict]] = None,
    composite_svg_path: Optional[Path] = None,
    catalogue_rows: Optional[list[dict]] = None,
    recommendation_gate: Optional[dict] = None,
    show_deciding_axis: bool = False,
    card_figures: Optional[dict] = None,
    figures_dir: Optional[Path] = None,
    presence_only: bool = False,
) -> str:
    """Render a self-contained target_profile.html — the governance artifact. Pure projection of the
    same nomination data the .md carries; no recompute. All structured outputs (scorecard,
    deciding-axis, ordinal matrix) are DETERMINISTIC sections, visually distinct from the
    AI-generated ones.

    DYNAMIC vs STATIC (Phase B): when a run produced per-card interactive figures (`card_figures` +
    `figures_dir`), their Plotly specs are EMBEDDED inline (plotly.js inlined once, a small vanilla-JS
    bootstrap draws them) — the dashboard reads like the GI team's interactive charts while staying a
    single archivable file with zero external deps. When no figure was produced (the default / a
    data-blocked run / plotly absent), the report degrades to the STATIC card tables — same file, no
    JS. The renderer only EMBEDS the method-drawn spec; it never re-plots (honesty spine intact).
    NOTE: an inlined-plotly report is ~4.6 MB and won't render in the VS Code Simple Browser —
    download + open in a real browser to review."""
    def _val(field, default="—"):
        raw = llm_output.get(field)
        return raw.get("value", default) if isinstance(raw, dict) else (raw if raw is not None else default)

    p: list[str] = ["<!DOCTYPE html><html lang=en><head><meta charset=utf-8>",
                    "<meta name=viewport content='width=device-width,initial-scale=1'>",
                    f"<title>Target profile — {_esc(target)} × {_esc(indication)}</title>",
                    f"<style>{_HTML_CSS}</style></head><body>"]

    # --- Header band: title + the headline recommendation ------------------
    action = str(_val("overall_recommendation"))
    term, gloss = _ACTION_GLOSS.get(action, (action, ""))
    action_html = f"<b>{_esc(term)}</b>" + (f" — {_esc(gloss)}" if gloss else "")
    # "Rule-checked" badge: when a deterministic gate overrode the AI's choice, say so on hover.
    rg = recommendation_gate or {}
    if rg.get("fired"):
        forced = rg.get("forced_recommendation", action)
        llm_said = rg.get("llm_recommendation")
        tip = (f"A deterministic safety/quality rule set this call. "
               f"The AI suggested '{llm_said}'; a rule required '{forced}'."
               if rg.get("overridden") else
               "A deterministic rule confirmed the AI's call.")
        checked = f"<span class=badge-rule title=\"{_esc(tip)}\">✓ rule-checked</span>"
    else:
        checked = ("<span class=badge-rule title=\"No override rule fired; the AI's recommendation "
                   "stands, checked against the deterministic gate.\">✓ rule-checked</span>")
    if presence_only:
        # Focused view: clean "TARGET × INDICATION" header, no recommendation clutter.
        p.append(f"<header><h1>{_esc(target)} <span style='opacity:.6;font-weight:400'>×</span> "
                 f"{_esc(indication)}</h1></header>")
    else:
        p.append("<header>"
                 f"<h1>{_esc(target)} <span style='opacity:.7;font-weight:400'>in</span> {_esc(indication)}"
                 " — target profile</h1>"
                 f"<div class=rec>Recommendation: {action_html}"
                 f" · confidence <span class=pill>{_esc(_val('confidence'))}</span> {checked}"
                 f" <span style='opacity:.7;font-size:12px'>· AI-generated</span></div>"
                 "</header>")

    # --- Gate sections declarative list (SINGLE SOURCE for both the left nav AND the section
    # render loop below — so the nav can never drift out of sync with what actually renders). Each
    # entry: (band, gate_letter, gate_name, [sub_skill shorts], modality_note). `band` is the 5R
    # RISK CATEGORY (2026-07-21) — the body is grouped by the SAME 5R spine as the lead-lens risk
    # table, so there is ONE grouping system. Safety is its own band (not folded under modality-fit);
    # Biomarker is its own band whose section collects the card-grain biomarker facets routed out of
    # gates C/E. _gate_section_anchor mirrors _render_gate_section_html's sec_id.
    _BANDS = {  # 5R risk-category bands (order = _RISK_CATEGORY_ORDER); label + one-line gloss
        "biological":   ("Biological", "Right Target — is this real, actionable biology?"),
        "biomarker":    ("Biomarker", "Right Patient — who responds?"),
        "druggability": ("Druggability", "can it be drugged (small-molecule / biologic)?"),
        "safety":       ("Safety", "Right Safety — on-target liability?"),
    }
    # Card-grain biomarker facets ROUTED OUT of their home gates (C/E) into the dedicated Biomarker
    # section (item #5). These are feature×outcome relational cards — "who responds?" (patient-
    # selection) + "do two measures agree?" (confidence) — a distinct question from the raw
    # dependency (C) or the alteration-frequency (E) they live under. synthetic-lethal-partners is a
    # sub_skill-grain sub-verdict (its OWN scorecard row) so it STAYS in gate C, not routed here;
    # prism-crispr-concordance stays under Druggability (its home) + shows a reports_into breadcrumb.
    _BIOMARKER_FACET_CARDS = [
        "mutation-stratified-dependency",     # stratification — mutant vs WT dependency
        "expression-dependency-correlation",  # stratification — expression-as-biomarker
        "crispr-rnai-dependency-concordance", # corroboration — two LOF assays agree
        "dependency-predictability",          # corroboration — omics-predictable dependency
    ]
    _GATE_SECTIONS = [
        # --- Biological (Right Target) — the raw necessity biology, facets routed to Biomarker ---
        ("biological", "A", "Expressed", ["expression"], None),
        ("biological", "B", "Selective", ["selectivity"], None),
        ("biological", "C", "Functional dependence", ["dependency", "synthetic_lethal_partners"], None),
        ("biological", "D", "Mechanism", ["mechanism"], None),
        ("biological", "E", "Altered", ["genomic_alteration"],
         "Somatic alteration landscape (mutation / CN / fusion frequency). The biomarker-stratified-"
         "dependency signal is a Biomarker facet (see the Biomarker band)."),
        # --- Biomarker (Right Patient) — the card-grain facets routed out of C/E (item #5).
        # `shorts` spans the sub-skills the facet cards live under; include_only keeps just the facets.
        ("biomarker", "", "Biomarker", ["dependency", "genomic_alteration"],
         "Patient-selection + confidence facets — feature×outcome relationships (who responds? do "
         "measures agree?) routed out of Functional dependence (C) and Altered (E)."),
        # --- Druggability (tractability + surface biologics) ---
        ("druggability", "", "Small-molecule druggability", ["tractability_sm"],
         "Druggability — small-molecule / degrader chemical-genetic + structural pocket evidence."),
        ("druggability", "", "Surface-biologics fit", ["surface_modality"],
         "Druggability — ADC / BiTE-TCE / antibody surface-biologics fit "
         "(not applicable to a small-molecule or degrader strategy)."),
        # --- Safety (Right Safety) — its OWN band, not under druggability/modality-fit ---
        ("safety", "", "Safety", ["safety"],
         "On-target safety liability — intrinsic to the target (germline LoF constraint + "
         "normal-tissue), with tiered severity per modality."),
    ]

    def _gate_section_anchor(gate: str, gname: str) -> str:
        glow = gate.lower() if gate else re.sub(r"[^a-z0-9]+", "-", gname.lower()).strip("-")
        return f"s-gate-{glow}"

    def _facets_present() -> bool:
        """True iff any biomarker-facet card actually ran this run (drives whether the Biomarker
        section + band render — data-driven, like the risk-category surfacing)."""
        for short in ("dependency", "genomic_alteration"):
            for c in (sub_results.get(short, {}).get("cards") or []):
                if c.get("card_id") in _BIOMARKER_FACET_CARDS:
                    return True
        return False

    # rendered gates this run = those with a present sub-skill (presence_only → only Expressed). The
    # Biomarker section is special: it renders iff a facet card actually ran (not just its sub-skills).
    def _gate_present(gn: str, shorts: list) -> bool:
        if gn == "Biomarker":
            return _facets_present()
        return any(s in sub_results for s in shorts)
    _rendered_gates = [(ax, g, gn, ss, mn) for (ax, g, gn, ss, mn) in _GATE_SECTIONS
                       if _gate_present(gn, ss)
                       and not (presence_only and gn != "Expressed")]

    # --- 2-column shell: sticky left nav (jump-links) + content ---
    # NOTE: the composite-panel SVG is deliberately NOT embedded here — it is a matplotlib
    # text-badge grid sized for a slide (~1583px) that renders poorly in a web card. The
    # scorecard below IS the native-HTML "at a glance". The SVG remains a .md/PPT slide asset.
    # Nav: no "Sections" heading; narrow column (CSS). Gate links are DERIVED from _rendered_gates
    # (with axis sub-headers), so a new/renamed gate appears automatically — no hardcoded drift.
    shell_cls = "shell focused" if presence_only else "shell"
    nav = [f"<div class={shell_cls}><nav class=toc>",
           "<a href='#s-exec'>Executive summary</a>"]
    if presence_only:
        for _ax, g, gn, _ss, _mn in _rendered_gates:
            nav.append(f"<a href='#{_gate_section_anchor(g, gn)}'>{_esc(gn)}</a>")
    else:
        if scorecard:
            nav.append("<a href='#s-riskcat'>Risk by category</a>")   # 5R lead lens
        if deciding_axis and show_deciding_axis:
            nav.append("<a href='#s-deciding'>Deciding axis</a>")
        # gate links, grouped by 5R risk-category band (a tiny header per band for orientation).
        # NOTE nav order MUST match the main-page order below (#8): the summary sections (Gate detail
        # + Modality-fit matrix) lead, then the risk-category gate bands, then conflicting signals,
        # then About at the very bottom.
        nav.append("<a href='#s-scorecard'>Gate detail</a>")
        if ordinal_matrix:
            nav.append("<a href='#s-matrix'>Modality-fit matrix</a>")
        _nav_band = None
        for _bd, g, gn, _ss, _mn in _rendered_gates:
            if _bd != _nav_band:
                _nav_band = _bd
                nav.append(f"<span class=h>{_esc(_BANDS.get(_bd, (_bd, ''))[0])}</span>")
            label = f"{_esc(gn)} <span style='color:var(--muted)'>({g})</span>" if g else _esc(gn)
            nav.append(f"<a href='#{_gate_section_anchor(g, gn)}'>{label}</a>")
        nav.append("<a href='#s-tension'>Conflicting signals</a>")
        nav.append("<a href='#s-provenance'>Provenance trace</a>")
        nav.append("<a href='#s-about'>About this analysis</a>")
    nav.append("</nav><div class=content>")
    p.append("".join(nav))

    # --- "About this analysis" band + data-loaded status banner — DEFERRED to the BOTTOM (#4).
    # Descriptive framing + provenance is reference material, not a lead; _about_html() is defined
    # here (so it captures the run's counts) and APPENDED at the end of the body. Skipped in
    # presence_only.
    def _about_html() -> list[str]:
        if presence_only:
            return []
        n_gates = len({(r.get("skill_dir") or short) for short, r in sub_results.items()})
        n_cards = sum(1 for r in sub_results.values() for c in (r.get("cards") or [])
                      if isinstance(c, dict) and not c.get("_missing"))
        n_plotly_total = sum(1 for figs in (card_figures or {}).values()
                             for f in figs if f.get("dynamic"))
        fignote = (f" · <span class=n>{n_plotly_total} interactive figure"
                   f"{'s' if n_plotly_total != 1 else ''}</span>" if n_plotly_total else "")
        return [
            f"<div class=statusbar id=s-about>Evaluated {_esc(target)} × {_esc(indication)}"
            f"<span class=n>· {n_gates} question-gate{'s' if n_gates != 1 else ''} assessed "
            f"· {n_cards} evidence card{'s' if n_cards != 1 else ''}{fignote}</span></div>",
            "<div class=about><p class=h>About this analysis</p><ul>"
            "<li><b>Target-evaluation profile</b> — drug-discovery risk categories (Biological, "
            "Biomarker, Druggability, Safety, …) rolled up from curated evidence gates for this "
            "target×indication.</li>"
            "<li>The recommendation is <b>rule-checked</b>: a deterministic gate can override the "
            "AI-generated call (a measured killer forces the verdict); AI sections are tinted + labeled.</li>"
            "<li>Coverage gaps are shown as gaps, never as negatives — “we didn’t look” is "
            "distinct from “we looked and it’s absent.”</li></ul>"
            f"<div class=citation>Framework: <code>{_esc(SKILL_NAME)} v{_esc(SKILL_VERSION)}</code>"
            + (f" · model <code>{_esc(_framework_model_version())}</code>" if _framework_model_version() else "")
            + " · a projection of <code>nomination.json</code>; sub-verdicts are deterministic and "
            "reproducible from the same inputs.</div></div>",
        ]

    # --- Executive summary (LLM) — TOP, the lead the reader needs first ----
    # AI-generated tag moved to the upper-right corner (out of the heading's way) — the exec summary
    # is the one AI section, so its provenance sits as a corner chip rather than a leading banner.
    p.append("<div class='llm llm-exec' id=s-exec><span class='tag tag-corner'>AI-generated</span>"
             f"<h2>Executive summary</h2><p>{_esc(_val('executive_summary'))}</p></div>")

    # --- Risk by category (5R lead lens; deterministic) --------------------
    # The committee-facing glance: drug-discovery risk categories rolled up from the gate scorecard
    # (5R-anchored). DATA-DRIVEN — only categories with >=1 evidenced sub-skill this run appear; the
    # rest are a one-line footnote. Replaces the gate scorecard as the top lens (the detailed gate
    # sections below carry every gate). Suppressed in presence_only.
    if scorecard and not presence_only:
        rollup = _risk_category_rollup(scorecard)
        p.append("<section id=s-riskcat class=scorecard><span class=tag>Computed from the evidence</span>"
                 "<h2>Risk by category <span class=n>— 5R framework; the committee lens</span></h2>")
        p.append("<p class=sub>Drug-discovery risk categories, rolled up from the evidence gates below. "
                 "Only categories the framework can evidence this run are shown; click a category to jump "
                 "to its detail. Risk level is computed from the member gates, never authored.</p>")
        p.append("<table><tr><th>Category</th><th>Risk level</th><th>Driver</th></tr>")
        _RL_CHIP = {"elevated": ("chip-neg", "elevated"), "supported": ("chip-pos", "supported"),
                    "neutral": ("chip-neu", "neutral")}
        # Gate-section anchors that WILL render this run (same list + id scheme the gate sections
        # use). The gate sections are appended to `p` LATER (via bands_html), so the previous
        # `f"id={anchor}" in "".join(p)` check always failed here and the category cells never
        # became clickable. Check this forward set instead.
        _rendered_anchor_ids = {
            f"s-gate-{(g.lower() if g else re.sub(r'[^a-z0-9]+', '-', gn.lower()).strip('-'))}"
            for (_ax, g, gn, _ss, _mn) in _rendered_gates
        }
        for c in rollup["surfaced"]:
            cls, lab = _RL_CHIP.get(c["risk_level"], ("chip-neu", c["risk_level"]))
            cat_cell = _esc(c["label"])
            if c.get("anchor") and c["anchor"] in _rendered_anchor_ids:
                cat_cell = (f"<a href='#{c['anchor']}' style='color:inherit;text-decoration:none;"
                            f"border-bottom:1px dotted var(--line-2)'>{cat_cell}</a>")
            cat_cell += f" <span class=sub>— {_esc(c['sub'])}</span>"
            p.append(f"<tr><td>{cat_cell}</td>"
                     f"<td><span class='chip {cls}'>{_esc(lab)}</span></td>"
                     f"<td class=sub>{_esc(c['driver'])}</td></tr>")
        p.append("</table>")
        if rollup["not_evidenced"]:
            labels = [_RISK_CATEGORY_LABEL.get(c, (c, ""))[0] for c in rollup["not_evidenced"]]
            p.append(f"<p class=sub style='margin-top:8px'><b>Not yet evidenced</b> "
                     f"(no wired data this run): {_esc(', '.join(labels))}. "
                     f"These categories surface automatically as their data sources are wired.</p>")
        p.append("</section>")

    # --- Gate sections (gate-model v2), GROUPED BY AXIS. Iterates _rendered_gates (defined above,
    # the SAME list the left nav uses — no drift). Each gate renders as a card-subtab section under
    # its axis band. AXIS 1 BIOLOGY (necessity): A Expressed · B Selective · C Functional dependence ·
    # D Mechanism · E Altered (lettered; "Altered" split out of the v1 A/C overload). AXIS 2 MODALITY
    # FIT (sufficiency): Small-molecule · Surface-biologics · Safety (named, lens-conditional mnote).
    # An axis band emits its header once, before its first rendered gate (suppressed in presence_only).
    scorecard_by_short = {r["short"]: r for r in (scorecard or [])}
    # cross-gate breadcrumb edges, read from the contract (card_id + reports_into on card-grain
    # facets), computed once + passed to every gate section. Fails open to the static fallback.
    reports_into_map = _card_reports_into()
    n_gate_plotly = 0
    # Gate sections are collected into bands_html (NOT appended to p yet) so the ordered assembly
    # below can place the summary sections (Gate detail + Modality-fit matrix) ABOVE them (#7).
    bands_html: list[str] = []
    _cur_band = None
    for band, gate, gname, gshorts, mnote in _rendered_gates:
        present = [s for s in gshorts if s in sub_results]
        # 5R risk-category band header — emitted once, before the first rendered gate of each band.
        # Suppressed in presence_only (single-section focused view).
        if band != _cur_band and not presence_only:
            _cur_band = band
            _btitle, _bsub = _BANDS.get(band, (band, ""))
            bands_html.append(f"<div class=axis-band><h2>{_esc(_btitle)} "
                              f"<span class=n>— {_esc(_bsub)}</span></h2></div>")
        # Biomarker section: collect ONLY the facet cards (across dependency + genomic_alteration).
        # Biological gates C/E: EXCLUDE those same facets (routed to Biomarker) so they don't double-show.
        include_only = _BIOMARKER_FACET_CARDS if gname == "Biomarker" else None
        exclude = set(_BIOMARKER_FACET_CARDS) if gname in ("Functional dependence", "Altered") else None
        gate_html, n_g = _render_gate_section_html(
            gate, gname, present, sub_results, scorecard_by_short,
            card_figures, figures_dir, indication=indication, modality_note=mnote,
            reports_into_map=reports_into_map,
            exclude_card_ids=exclude, include_only_card_ids=include_only)
        bands_html.extend(gate_html)
        n_gate_plotly += n_g
    # presence_only renders the single gate section directly (early-return below handles the rest).
    if presence_only:
        p.extend(bands_html)

    # FOCUSED VIEW (item 5): presence-only — close out after the Presence section, skipping the
    # scorecard/risk/tension/evidence/matrix. Everything below is the full-report body.
    if presence_only:
        n_plotly = n_gate_plotly
        p.append("<footer>"
                 f"Generated {_esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))}"
                 " · focused Presence view · projection of nomination.json (no recompute).</footer>")
        p.append("</div>")   # close .content (matches the full-report path's single close)
        if n_plotly:
            bundle = _plotly_bundle()
            if bundle:
                p.append(f"<script>{bundle}</script>")
                p.append(_PLOTLY_BOOTSTRAP_JS)
        p.append(_TAB_BOOTSTRAP_JS)
        p.append("</body></html>")
        return "".join(p)

    # --- Gate scorecard (deterministic) — a closure emitted near the TOP (#7), the per-gate detail
    # behind the risk categories. Rows are the sub-skills grouped by gate; each keeps its own honest
    # 4-state status (a greyed row = coverage gap, never a negative). anchors_in is the HTML already
    # emitted (so a row only links to a gate section that actually rendered).
    def _scorecard_html(anchors_in: str) -> list[str]:
        if not scorecard:
            return []
        out = ["<section id=s-scorecard class=scorecard><span class=tag>Computed from the evidence</span>"
               "<h2>Gate detail <span class=n>— every evidence question, grouped by gate</span></h2>",
               "<p class=sub>The per-gate breakdown behind the risk categories above — one row per "
               "evidence question. "
               "<span class='chip chip-gap'><span class=g>□</span> Not evaluated</span> = a gap, "
               "not a negative. Deciding question highlighted.</p>",
               "<table><tr><th>Gate</th><th>Question</th><th>Status</th>"
               "<th>Finding</th><th>Coverage</th></tr>"]
        _last = object()
        for row in scorecard:
            glyph, cls, label = _HTML_STATUS.get(row["status"], _HTML_STATUS["coverage_gap"])
            gate = row.get("gate")
            new_gate = gate != _last
            gate_cell = f"<td>{_esc(gate)}</td>" if new_gate else "<td></td>"
            _last = gate
            finding = _esc(_humanize(row.get("verdict")))
            if row.get("driving_rule_id"):
                finding += f" <span class=sub><code>{_esc(row['driving_rule_id'])}</code></span>"
            vtok = (row.get("verdict") or "")
            if row.get("short") == "genomic_alteration" and "biomarker_stratified" in vtok:
                finding += " <span class=sub>→ feeds Dependency (C)</span>"
            if row.get("short") == "tractability_sm":
                finding += " <span class=sub>(also confirms Dependency)</span>"
            qname = _esc(_GATE_SHORT_LABEL.get(row.get("short"), _humanize(row.get("short"))))
            anchor = _SHORT_TO_GATE_ANCHOR.get(row.get("short"))
            if anchor and f"id={anchor}" in anchors_in:   # only link if the section actually rendered
                qname = f"<a href='#{anchor}' style='color:inherit;text-decoration:none;border-bottom:1px dotted var(--line-2)'>{qname}</a>"
            if row.get("is_deciding"):
                qname += " <span class=badge-deciding>deciding</span>"
            trcls = [c for c in (("deciding" if row.get("is_deciding") else ""),
                                 ("gate-start" if new_gate else "")) if c]
            rowcls = f" class='{' '.join(trcls)}'" if trcls else ""
            out.append(f"<tr{rowcls}>{gate_cell}"
                       f"<td>{qname}</td>"
                       f"<td><span class='chip {cls}'><span class=g>{glyph}</span> {label}</span></td>"
                       f"<td>{finding}</td>"
                       f"<td class=sub>{_esc(_COVERAGE_LABEL.get(row.get('framework_can_evidence'), row.get('framework_can_evidence')))}</td></tr>")
        out.append("</table></section>")
        return out

    # --- Deciding axis (deterministic router) — closure; HIDDEN by default (show_deciding_axis).
    def _deciding_html() -> list[str]:
        if not (deciding_axis and show_deciding_axis):
            return []
        out = ["<section id=s-deciding><span class=tag>Deterministic router</span>"
               "<h2>Deciding axis <span class=n>— what the call hinges on</span></h2>",
               f"<div class=banner>{_esc(deciding_axis.get('routing',''))}</div>"]
        if deciding_axis.get("basis") == "abstention_coverage_gaps" and deciding_axis.get("unevidenced_gates"):
            out.append("<p class=sub>Can't decide from framework evidence — questions left unassessed:</p>")
            out.append("<table><tr><th>Gate</th><th>Question</th><th>Coverage</th></tr>")
            for g in deciding_axis["unevidenced_gates"]:
                out.append(f"<tr><td>{_esc(g.get('gate'))}</td>"
                           f"<td>{_esc(_GATE_SHORT_LABEL.get(g.get('short'), _humanize(g.get('short'))))}</td>"
                           f"<td class=sub>{_esc(_COVERAGE_LABEL.get(g.get('framework_can_evidence'), g.get('framework_can_evidence')))}</td></tr>")
            out.append("</table>")
        out.append("</section>")
        return out

    # --- Tension analysis (LLM) → "Conflicting signals & trade-offs" — closure.
    def _tension_html() -> list[str]:
        return ["<div class=llm id=s-tension><span class=tag>AI-generated</span>"
                "<h2>Conflicting signals &amp; trade-offs</h2>"
                f"<p>{_esc(_val('tension_analysis'))}</p></div>"]

    n_plotly = n_gate_plotly

    # --- Ordinal matrix heatmap (deterministic VIEW) — closure; the modality-fit summary (#7 → top).
    def _matrix_html() -> list[str]:
        out: list[str] = []
        if ordinal_matrix:
            cols = ordinal_matrix["axes"]["columns"]
            out.append("<section id=s-matrix class=det><span class=tag>Ordering, not a score</span>"
                       "<h2>Modality-fit matrix <span class=n>— strongest signal per (question, "
                       "modality); the verdict, not a cell, is the call</span></h2>")
            col_lbl = {"small_molecule": "Small mol.", "degrader": "Degrader", "adc": "ADC",
                       "bite_tce": "BiTE/TCE", "antibody": "Antibody"}
            out.append("<table class=mtx><tr><th>Question</th>"
                       + "".join(f"<th>{_esc(col_lbl.get(c, c))}</th>" for c in cols) + "<th>Verdict</th></tr>")
            for row in ordinal_matrix["rows"]:
                cells = row["cells"]
                tds = "".join(f"<td class='{_mtx_cell_class(cells[m])}'>{_esc(ordinal_view._cell_glyph(cells[m]))}</td>"
                              for m in cols)
                out.append(f"<tr><td>{_esc(_GATE_SHORT_LABEL.get(row['short'], _humanize(row['short'])))}</td>{tds}"
                           f"<td>{_esc(_humanize(row.get('verdict')))}</td></tr>")
            out.append("</table>")
            out.append(f"<p class=disclaimer>{_esc(ordinal_matrix.get('_disclaimer',''))}</p>")
            if catalogue_rows:
                out.append("<details><summary>Data catalogue — what backed this run</summary>")
                out.append("<table><tr><th>Manifest / source</th><th>Consumed by</th></tr>")
                for cr in catalogue_rows:
                    out.append(f"<tr><td><code>{_esc(cr.get('manifest_id'))}</code></td>"
                               f"<td>{_esc(', '.join(cr.get('consumed_by', [])) or '—')}</td></tr>")
                out.append("</table></details>")
            out.append("</section>")
        elif catalogue_rows:
            out.append("<section class=det><h2>Data catalogue</h2>"
                       "<table><tr><th>Manifest / source</th><th>Consumed by</th></tr>")
            for cr in catalogue_rows:
                out.append(f"<tr><td><code>{_esc(cr.get('manifest_id'))}</code></td>"
                           f"<td>{_esc(', '.join(cr.get('consumed_by', [])) or '—')}</td></tr>")
            out.append("</table></section>")
        return out

    # --- Provenance trace (deterministic) — the full skill run, for audit/reproducibility.
    # A collapsible per-sub-skill trace: which sub-skill ran, its verdict + driving rule, each card
    # it resolved (with the data-source manifest/release it read + a 'missing' flag), and the rule
    # ids that fired. Pure projection of sub_results (skill_dir/cards/_data_source/fired/verdict) —
    # nothing new is computed. Sinks to the bottom (reference material) as a <details>, collapsed.
    def _provenance_trace_html() -> list[str]:
        if presence_only or not sub_results:
            return []
        out = ["<section id=s-provenance class=det><span class=tag>Computed from the evidence</span>"
               "<h2>Provenance trace <span class=n>— the full skill run behind this profile</span></h2>",
               "<p class=sub>Every sub-skill invoked, the evidence cards it resolved (+ the data "
               "source each read), and the rules that fired — the reproducibility spine of "
               "<code>nomination.json</code>. Collapsed by default.</p>",
               "<details><summary>Show run trace "
               f"({len(sub_results)} sub-skills)</summary>"]
        for short, r in sub_results.items():
            skill_dir = r.get("skill_dir") or "(inline)"
            v = r.get("verdict")
            verdict_str = _humanize(v[0]) if v else "not evaluated"
            driving = (v[1] if (v and len(v) > 1) else None)
            cards = r.get("cards") or []
            fired = r.get("fired") or []
            n_missing = sum(1 for c in cards if c.get("_missing"))
            out.append(f"<div class=trace-skill><p class=trace-h><b>{_esc(short)}</b> "
                       f"<span class=sub>{_esc(skill_dir)}</span> → {_esc(verdict_str)}"
                       + (f" <span class=sub><code>{_esc(driving)}</code></span>" if driving else "")
                       + f" <span class=sub>· {len(cards)} card{'s' if len(cards) != 1 else ''}"
                       + (f", {n_missing} missing" if n_missing else "")
                       + f", {len(fired)} rule{'s' if len(fired) != 1 else ''} fired</span></p>")
            if cards:
                out.append("<table class=trace-cards><tr><th>Card</th><th>Data source</th>"
                           "<th>Rules fired</th></tr>")
                for c in cards:
                    cid = c.get("card_id") or "?"
                    summ = c.get("summary") or {}
                    dsrc = summ.get("_data_source") or ("— (missing)" if c.get("_missing") else "—")
                    s3 = summ.get("_data_s3_uri") or ""
                    src_cell = (f"<span title='{_esc(str(s3))}'><code>{_esc(str(dsrc))}</code></span>"
                                if s3 else f"<code>{_esc(str(dsrc))}</code>")
                    card_rules = [fr.get("rule_id") for fr in fired if fr.get("card_id") == cid]
                    rules_cell = (", ".join(f"<code>{_esc(rid)}</code>" for rid in card_rules)
                                  if card_rules else "<span class=sub>—</span>")
                    miss = " class=trace-missing" if c.get("_missing") else ""
                    out.append(f"<tr{miss}><td><code>{_esc(cid)}</code></td>"
                               f"<td>{src_cell}</td><td>{rules_cell}</td></tr>")
                out.append("</table>")
            out.append("</div>")
        out.append("</details></section>")
        return out

    # === ORDERED ASSEMBLY (#4/#7/#8): summaries lead, gate bands, conflicting signals, About last.
    # Exec + Risk-by-category are already in `p` (rendered right after the exec summary). Now:
    #   Gate detail → Modality-fit matrix → deciding-axis → [risk-category gate bands] →
    #   Conflicting signals → About (bottom). Nav order (built above) mirrors this exactly.
    p.extend(_scorecard_html("".join(p) + "".join(bands_html)))  # link rows to sections that render
    p.extend(_matrix_html())
    p.extend(_deciding_html())
    p.extend(bands_html)
    p.extend(_tension_html())
    p.extend(_provenance_trace_html())
    p.extend(_about_html())

    kind = "Interactive" if n_plotly else "Static"
    p.append("<footer>"
             f"Generated {_esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))}"
             + (f" · lenses <code>{_esc(invoked_lenses)}</code>" if invoked_lenses else "")
             + f"<br>{kind} self-contained governance artifact — a projection of nomination.json. "
             + ("Charts are pre-computed by the methods (drawn from the same series as the static "
                "figures) and embedded, not re-plotted here. " if n_plotly else "")
             + "AI-generated sections are tinted; all other sections are deterministic and "
             "reproducible from the same inputs. No content is recomputed at render time.</footer>")
    p.append("</div>")   # close .wrap

    # --- Interactive layer (Phase B): inline plotly.js + a small vanilla-JS bootstrap that draws
    # every embedded spec. Emitted ONLY when ≥1 figure was produced — the no-figure report stays
    # pure static HTML (no JS, no 4.6 MB payload). Self-contained: plotly.js is INLINED, never a CDN.
    if n_plotly:
        bundle = _plotly_bundle()
        if bundle:
            p.append(f"<script>{bundle}</script>")
            p.append(_PLOTLY_BOOTSTRAP_JS)
    # Tab bootstrap whenever a gate section (with subtabs) was rendered — independent of Plotly, so
    # the tabs work even on a static/no-figure run. Presence gate is the current trigger.
    if "expression" in sub_results:
        p.append(_TAB_BOOTSTRAP_JS)
    p.append("</body></html>")
    return "".join(p)


def _catalogue_rows_from_sub_results(sub_results: dict) -> list[dict]:
    """Distill a manifest→consumers lineage table from the per-card provenance already in the run.
    Envelope-only (no live catalog read → keeps the renderer a pure projection)."""
    # Data source per card lives in summary['_data_source'] (the human-readable manifest/
    # product label the provenance-trace section also reads) — NOT a top-level card['provenance']
    # key, which card_outputs never carry, so this used to always return [] and the "Data
    # catalogue" section was dead on every run.
    by_source: dict[str, set] = {}
    for short, r in sub_results.items():
        for c in r.get("cards") or []:
            if not isinstance(c, dict):
                continue
            src = (c.get("summary") or {}).get("_data_source")
            if src:
                by_source.setdefault(str(src), set()).add(short)
    return [{"manifest_id": m, "consumed_by": sorted(v)} for m, v in sorted(by_source.items())]


def _load_figure_registry():
    """Import compose-dashboard's figure-emission registry (emit_figures_for_card).

    Both engines share ONE figure registry (the gap-#5 one-source-many-consumers lesson): the same
    per-card emitters that draw compose-dashboard's SVGs + Plotly specs draw them for target-profile.
    Graceful None on import failure — a run without per-card figures still emits every other artifact.
    """
    try:
        fe_dir = SKILLS_DIR / "compose-dashboard" / "scripts"
        if str(fe_dir) not in sys.path:
            sys.path.insert(0, str(fe_dir))
        import _figure_emitters  # type: ignore
        return _figure_emitters
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: figure registry unavailable: {e}", file=sys.stderr)
        return None


def _emit_card_figures(sub_results: dict, figures_dir: Path,
                       target: str, indication: str) -> dict:
    """Produce each card's distribution figures (SVG + interactive .plotly.json) by invoking the
    shared figure registry per card, writing into figures_dir/cards/<card_id>/.

    This is what makes a target-profile RUN produce the per-card charts the dynamic dashboard embeds
    — previously the run was rules/summary-only and only the composite panel was drawn. Returns a
    map {card_id: [figure_descriptor, ...]} (paths relative to figures_dir) for the renderer to
    embed; the `dynamic: True` descriptors are the Plotly specs, the rest are SVGs. Best-effort:
    a card with no registered emitter or a data-blocked summary simply contributes nothing.
    """
    fe = _load_figure_registry()
    if fe is None:
        return {}
    by_card: dict[str, list] = {}
    seen: set[str] = set()
    for r in sub_results.values():
        for c in r.get("cards") or []:
            if not isinstance(c, dict):
                continue
            card_id = c.get("card_id")
            if not card_id or card_id in seen or c.get("_missing"):
                continue
            seen.add(card_id)
            try:
                figs = fe.emit_figures_for_card(
                    card_id, c.get("summary") or {}, figures_dir, target, indication)
            except Exception as e:  # noqa: BLE001 — figure emission never blocks the run
                print(f"[target-profile] WARN: figure emit failed for {card_id}: {e}",
                      file=sys.stderr)
                figs = []
            if figs:
                by_card[card_id] = figs
    n_plotly = sum(1 for figs in by_card.values() for f in figs if f.get("dynamic"))
    print(f"[target-profile] per-card figures: {len(by_card)} cards, "
          f"{n_plotly} interactive Plotly specs", file=sys.stderr)
    return by_card


# --- Evidence-package emitter (--emit evidence-package) --------------------------------------
# The MACHINE-facing sibling of nomination.json: a deterministic, LLM-free evidence_package.json
# envelope (the same shape compose-dashboard emits), assembled from the Stage-1b per-sub-skill
# CompositionResult carriers via the SHARED writer. Purely additive — selected by --emit; the
# nomination path is untouched.

def _deciding_short(deciding_axis: dict) -> Optional[str]:
    """Map the deciding_axis block to the short whose gate is the envelope PRIMARY.

    gate_fired  → the gate that won; positive_signal → the strongest positive dimension;
    abstaining  → None (no primary; every gate block becomes `additional`)."""
    if deciding_axis.get("basis") == "gate_fired":
        return (deciding_axis.get("deciding_axis") or {}).get("short")
    if deciding_axis.get("basis") == "positive_signal":
        rows = deciding_axis.get("deciding_axes") or []
        return rows[0].get("short") if rows else None
    return None


def _framework_version() -> str:
    """The framework semver stamped into the envelope (distinct from SKILL_VERSION). Mirrors the
    dispatcher's --emit-envelope fallback: read compose_phase1.FRAMEWORK_VERSION, else '2.0.0'."""
    try:
        from compose_phase1 import FRAMEWORK_VERSION  # type: ignore  # on sys.path via resolve_cards
        return FRAMEWORK_VERSION
    except Exception:  # noqa: BLE001
        return "2.0.0"


def _validate_evidence_package(ep: dict, contracts_root: Path) -> list[str]:
    """Validate an evidence_package against evidence_package.schema.json — the SAME check
    compose-dashboard applies to its envelope (compose_dashboard.py::_validate_evidence_package).
    target-profile's --emit path historically SKIPPED this, so a schema-invalid governance artifact
    was silently persisted + reported as success — most notably the `hgnc_id=-1` unresolved-identity
    sentinel that assemble_evidence_package emits ON PURPOSE to FAIL validation (envelope.py) but which
    only fails if someone actually validates. Returns a list of human-readable error strings (empty =
    valid). Graceful-skip (returns []) if jsonschema or the schema file is unreachable — never let the
    validator itself break an emit. FUTURE: consolidate this + compose-dashboard's identical copy into
    _skills_common.envelope beside assemble_evidence_package."""
    try:
        from jsonschema import Draft202012Validator
    except Exception:  # noqa: BLE001 — jsonschema absent (isolated env) → skip, don't crash emit
        return []
    schema_path = contracts_root / "schemas" / "evidence_package.schema.json"
    if not schema_path.exists():
        return []
    schema = json.loads(schema_path.read_text())
    errors = []
    for e in Draft202012Validator(schema).iter_errors(ep):
        path_str = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"[{path_str}] {e.message}")
    return errors


def _write_evidence_package(*, args, sub_results: dict, gate_action: Optional[str],
                            recommendation_gate: dict, confidence_tier: dict,
                            deciding_axis: dict, validation_summary: dict) -> Path:
    """Assemble + write evidence_package.json around target-profile's composed verdict.

    Reuses the shared normalizers (`_envelope_card_present`, `_availability_state_for`) and writer
    (`assemble_evidence_package`) so the envelope is byte-shaped identically to compose-dashboard's.
    The synthesis block is the SUPERSET shape (per product decision): target-profile's nomination
    fields (recommendation_gate / confidence_tier / deciding_axis) AND a compose-dashboard-style
    primary/additional split AND the full per-sub-skill sub_verdicts — all sourced from the
    Stage-1b CompositionResult on each sub-skill (r["composition"]); NO re-resolution.
    """
    from _skills_common.envelope import assemble_evidence_package
    from _skills_common.dispatcher import _envelope_card_present, _availability_state_for
    from _skills_common.gitmeta import skills_repo_sha

    # 1. Union the sub-skills' cards by card_id (a card may compose under >1 lens; keep first),
    #    splitting present (normalized) vs reasoned-absence (card_unavailable).
    seen: set = set()
    env_present: list[dict] = []
    env_unavailable: list[dict] = []
    for r in sub_results.values():
        for c in (r.get("cards") or []):
            cid = c.get("card_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            if c.get("_missing"):
                state, reason = _availability_state_for(c)
                env_unavailable.append({
                    "card_id": cid, "card_version": c.get("card_version", "n/a"),
                    "availability_state": state, "availability_reason": reason,
                })
            else:
                env_present.append(_envelope_card_present(c))

    # 2. Resolve target-identity-summary separately so context.target carries a real hgnc_id
    #    (schema requires >= 1). Best-effort — on failure the writer emits the -1 sentinel.
    try:
        for c in resolve_cards(["target-identity-summary"], args.target, args.indication):
            cid = c.get("card_id")
            if not c.get("_missing") and cid and cid not in seen:
                seen.add(cid)
                env_present.append(_envelope_card_present(c))
    except Exception as e:  # noqa: BLE001 — identity read is best-effort; never break emit
        print(f"[target-profile] --emit evidence-package: target-identity read failed "
              f"({type(e).__name__}); context.target.hgnc_id will be the unresolved sentinel.",
              file=sys.stderr)

    # 3. Synthesis block — SUPERSET. Per-short verdicts mirror nomination.json (verdict present even
    #    for gateless shorts); the primary/additional split reads the gate blocks the Stage-1b
    #    CompositionResult carries (gateless shorts contribute no block).
    sub_verdicts: dict = {}
    gate_blocks: dict = {}  # short -> primary_dict() (only shorts with a resolver gate)
    for short, r in sub_results.items():
        v = r.get("verdict")
        comp = r.get("composition")
        blk = comp.primary_dict() if comp is not None else None
        sub_verdicts[short] = {
            "gate": blk["gate"] if blk else None,
            "verdict": v[0] if v else None,
            "driving_rule_id": v[1] if v else None,
            "fired_rule_ids": [f["rule_id"] for f in (r.get("fired") or [])],
        }
        if blk is not None:
            gate_blocks[short] = blk

    primary_short = _deciding_short(deciding_axis)
    primary_block = gate_blocks.get(primary_short)
    # additional = every other gate block, in SUB_SKILLS iteration order (deterministic)
    additional_blocks = [b for s, b in gate_blocks.items() if s != primary_short]

    # gate_action is None when NO killer gate (veto/hold) fired. That is NOT "insufficient evidence" —
    # it means "no deterministic kill; the nominate/advance decision belongs to the narrative synthesis
    # (see nomination.json)". Labeling it "insufficient" mislabeled a strong POSITIVE target (a machine
    # consumer reading synthesis.headline saw "insufficient (strong confidence)" — incoherent, and it
    # disagreed with the same run's nomination.json). Use an honest neutral term for the no-kill case.
    recommendation = gate_action or "no_deterministic_kill"
    tier = confidence_tier.get("tier")
    headline = (f"{args.target} in {args.indication}: {recommendation}"
                + (f" ({tier} confidence)" if tier else ""))
    synthesis_block = {
        "headline": headline,
        "caveats_summary": (
            "Composed target-profile evidence envelope (--emit evidence-package): a deterministic "
            "nomination gate over per-sub-skill resolver verdicts. LLM narrative intentionally "
            "omitted (see nomination.json for the narrated form); not concurrence-reviewed."
        ),
        # nomination-shaped — target-profile's actual verdict model
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        # compose-dashboard-shaped — comparable to the other engine's envelopes
        "primary_gate_verdict": primary_block,
        "additional_gate_verdicts": additional_blocks,
        # full per-sub-skill grouping
        "sub_verdicts": sub_verdicts,
    }

    input_context = {
        "target_symbol": args.target,
        "indication": args.indication,
        "subgroup_spec": None,
        # The evidence_package schema's governance.data_mode enum is {latest_approved, pinned,
        # exploratory} — target-profile's internal "live_latest" is not a member. A live, unpinned,
        # non-concurrence-reviewed composed run IS exploratory (mirrors the dispatcher subskill
        # emitter's _GOVERNANCE_DATA_MODE default). nomination.json keeps its own "live_latest"
        # governance (that artifact is not bound to this schema).
        "data_mode": "exploratory",
        "release_pin": args.release_pin or "unpinned",
    }
    ep = assemble_evidence_package(
        input_context=input_context,
        dashboard_spec_ref="skill:target-profile",
        card_outputs=env_present,
        unavailable_cards=env_unavailable,
        validation_summary=validation_summary,
        synthesis_block=synthesis_block,
        deterministic_timestamps=False,
        framework_version=_framework_version(),
        generated_by=f"skills/{SKILL_NAME}@{skills_repo_sha()}",
    )
    # target-profile reads live + has no target-level applies_when gating; keep its governance
    # `_note` annotation off the envelope (it is a nomination.json/provenance detail).
    out_path = args.out / "evidence_package.json"
    out_path.write_text(json.dumps(ep, indent=2, default=str))
    # Validate the emitted envelope against evidence_package.schema.json — the sibling engine
    # (compose-dashboard) does this; target-profile must too, else a schema-invalid governance
    # artifact (e.g. hgnc_id=-1 when target-identity failed to resolve) is silently persisted and
    # reported as success. Fail LOUD: the file is written for inspection, but a non-zero exit + the
    # error list stop it being mistaken for a valid governance-grade package.
    schema_errors = _validate_evidence_package(ep, _CONTRACTS_REPO)
    if schema_errors:
        print(f"[target-profile] --emit evidence-package: envelope FAILED evidence_package.schema "
              f"validation ({len(schema_errors)} error(s)) — NOT a governance-grade artifact "
              f"(written to {out_path} for inspection):", file=sys.stderr)
        for e in schema_errors[:20]:
            print(f"    - {e}", file=sys.stderr)
        raise SystemExit(1)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--subtypes", default=None,
                    help="Comma-separated molecular subgroup ids to scope the "
                         "profile to (e.g. 'MSI_H,MSS'). When set, the subtype "
                         "tier is evaluated: a MEASURED, floor-cleared subtype "
                         "that is NOT a dependency holds the nomination. Omit for "
                         "a whole-cohort profile (backward-compatible default).")
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
    ap.add_argument("--release-pin", default=None,
                    help="OPTIONAL data release_pin to STAMP into governance/provenance for "
                         "reproducibility (parity with compose-dashboard). Pass-through only: "
                         "target-profile reads live and does NOT auto-resolve the release — absent "
                         "this flag the pin is recorded as 'unpinned' (honest, never fabricated). "
                         "Auto-resolution is a deferred data-catalog follow-on.")
    ap.add_argument("--therapeutic-hypothesis", default=None,
                    help="OPTIONAL therapeutic hypothesis (line-of-therapy, "
                         "patient state, clinical goal). Reshapes LLM "
                         "narrative; sub-verdicts unchanged.")
    ap.add_argument("--no-figures", action="store_true",
                    help="VERDICT-ONLY mode: skip per-card figure emission + the interactive HTML "
                         "(the 4.6MB inlined plotly.js + the figure double-read). Emits "
                         "nomination.json + target_profile.md + provenance + a STATIC (no-JS) HTML. "
                         "The deterministic verdict spine is byte-identical to a full run — figures "
                         "never feed the verdict. Use for fast iteration / re-runs; render later via "
                         "the deferred-render path. (Perf Stage 1, 2026-07-23.)")
    ap.add_argument("--no-synthesis", action="store_true",
                    help="Skip the Tier-3 Bedrock LLM synthesis (executive-summary / tension / "
                         "recommendation narrative). The deterministic verdict spine — sub-verdicts, "
                         "recommendation gate, positive tier, deciding axis, scorecard, facets — is "
                         "computed independently of the LLM and stays byte-identical to a full run. "
                         "nomination.json marks llm_synthesis._synthesis_skipped; the report shows a "
                         "note in place of the narrative. Removes the serial, non-cacheable network tail.")
    ap.add_argument("--verdict-only", action="store_true",
                    help="Umbrella fast/CI/iteration mode: implies --no-synthesis AND --no-figures. "
                         "Emits the deterministic nomination (nomination.json + a narrative-free "
                         "target_profile.md + provenance) with no Bedrock call and no figure/panel "
                         "render. The verdict spine is byte-identical to a full run.")
    ap.add_argument("--profile-timers", action="store_true",
                    help="Emit per-sub-skill READ vs FIGURE-EMIT wall-clock timings to stderr "
                         "(instrumentation only; zero effect on artifacts). (Perf Stage 0.)")
    ap.add_argument("--emit", choices=["nomination", "evidence-package"], default="nomination",
                    help="Output shape. 'nomination' (default) → nomination.json + target_profile.md "
                         "+ provenance (the biologist-facing narrated profile). 'evidence-package' → "
                         "a deterministic, LLM-free evidence_package.json envelope (the same machine-"
                         "facing shape compose-dashboard emits), assembled from the SAME per-sub-skill "
                         "verdict spine. evidence-package implies --no-synthesis + --no-figures and "
                         "emits no nomination.json / md / html.")
    args = ap.parse_args()

    # --verdict-only is the umbrella fast mode: skip BOTH the LLM synthesis tail and figure/panel
    # rendering. Both are verdict-inert, so the deterministic spine is unaffected.
    if args.verdict_only:
        args.no_synthesis = True
        args.no_figures = True

    # --emit evidence-package is a MACHINE artifact: deterministic + LLM-free by construction, and
    # never renders the nomination-oriented md/html/figures. The deterministic verdict spine it reads
    # (sub-verdicts, recommendation gate, deciding axis) is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        args.no_synthesis = True
        args.no_figures = True

    args.out.mkdir(parents=True, exist_ok=True)

    invoked_lenses: dict = {}
    if args.modality:
        invoked_lenses["modality"] = args.modality
    if args.therapeutic_hypothesis:
        invoked_lenses["therapeutic_hypothesis"] = args.therapeutic_hypothesis

    # 1. Fan out to sub-skills.
    print(f"[target-profile] Running {len(SUB_SKILLS)} sub-skills for "
          f"{args.target} in {args.indication}...", file=sys.stderr)
    subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] if args.subtypes else None
    _fanout_t0 = time.perf_counter() if args.profile_timers else 0.0
    sub_results = _run_sub_skills(args.target, args.indication, subtypes=subtypes,
                                  profile_timers=args.profile_timers)
    if args.profile_timers:
        print(f"[perf] === fan-out total {time.perf_counter() - _fanout_t0:6.1f}s ===",
              file=sys.stderr)
    for short, r in sub_results.items():
        v = r["verdict"]
        verdict_str = v[0] if v else "(no verdict)"
        print(f"  - {short:15s} -> {verdict_str}", file=sys.stderr)

    # Ordinal matrix VIEW (gap #3 "now"): gate × modality signals projected onto the ordinal
    # scale. Labeled, additive, NOT a verdict input (ordinal_view contract). Computed BEFORE the
    # prompt so synthesis can reason over the matrix-SLICE (gap #4b), not only the flat verdict
    # list; also emitted in nomination.json for downstream consumers.
    ordinal_matrix = _ordinal_matrix(sub_results)

    # Biomarker convergence facet (Q12, Part 3c): a deterministic, additive, verdict-inert assembly of
    # the scattered biomarker byproducts (corroboration + stratification + preferred_assay). Like the
    # ordinal matrix, computed BEFORE the prompt so synthesis can reason over it, and emitted in
    # nomination.json. One-directional: informs confidence, never mints a nominate.
    biomarker_facet = _biomarker_facet(sub_results)

    # Subtype convergence facet (capstone Part 3c integration layer): converge the three
    # subtype-grain panoramas (expression / dependency / mutation-frequency) BY molecular subtype
    # to surface cross-axis patient-selection strata. Like the biomarker facet: deterministic,
    # additive, verdict-inert; computed before the prompt so synthesis can reason over it, and
    # emitted in nomination.json. One-directional — informs confidence, never mints a nominate.
    subtype_facet = _subtype_facet(sub_results, indication=args.indication)

    # Fragility facet (2026-08-12): verdict-inert flip-stability — the quantitative "how solid is this
    # call?" scalar. Worst-case single-rule flip-fragility over the decision-relevant axes (+ a
    # coverage floor for blind axes), computed by re-running the deterministic resolver over perturbed
    # fired-rule sets. Like the other facets: computed BEFORE the prompt, emitted in nomination.json,
    # and STRICTLY verdict-inert — it never calls the gate and never writes overall_recommendation /
    # confidence. May set a categorical `contested` flag (declarative threshold) for the reader/banner.
    fragility = _fragility_facet(sub_results, subtypes=subtypes)
    # Heterogeneity facet (2026-08-12): verdict-inert cross-context DISPERSION — does a pooled
    # verdict hide a split across comparators / assays / molecular subtypes? Companion to fragility;
    # never touches the recommendation.
    heterogeneity = _heterogeneity_facet(sub_results, subtypes=subtypes)
    addressable_population = _addressable_population_facet(sub_results)

    # Biology-axis EMPHASIS STEER (2026-08-05): resolve the target's curated biology_axis +
    # plausible modalities so synthesis foregrounds the modalities the biology supports (fixes
    # surface-antigen over-emphasis for intracellular targets). Resolution NEVER raises — an
    # uncurated target resolves to axis=unknown and the block says "do not assume a modality
    # class." SLOT-2 emphasis only; the deterministic verdict + gate recommendation are untouched.
    from _skills_common.biology_axis import resolve_biology_axis
    axis_info = resolve_biology_axis(args.target)

    # 2. LLM synthesis via Bedrock (structured tool_use) — SKIPPED under --no-synthesis/--verdict-only.
    # The deterministic spine (sub-verdicts, recommendation gate, positive tier, deciding axis,
    # scorecard, facets) is computed independently below and is byte-identical whether or not
    # synthesis runs, so the skipped path emits a stub the gate clamps into + the renderers degrade
    # to a "synthesis skipped" note.
    if args.no_synthesis:
        llm_output = _skipped_synthesis_output()
        print("[target-profile] --verdict-only/--no-synthesis: skipped Bedrock synthesis "
              "(deterministic verdict spine is authoritative)", file=sys.stderr)
    else:
        print(f"[target-profile] Invoking Bedrock synthesis (biology_axis={axis_info['biology_axis']})...",
              file=sys.stderr)
        tool_schema = _build_synthesis_tool()
        user_prompt = _build_user_prompt(
            args.target, args.indication, sub_results,
            modality=args.modality,
            therapeutic_hypothesis=args.therapeutic_hypothesis,
            ordinal_matrix=ordinal_matrix,
            biomarker_facet=biomarker_facet,
            subtype_facet=subtype_facet,
            axis_info=axis_info,
        )
        llm_output = synthesize_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_name="target_profile_synthesis",
            tool_schema=tool_schema,
        )
        # Attach the deterministic cross-cutting metric legend (sibling key) so a non-computational
        # reader has an accurate reference for the quantities cited across lenses — independent of the
        # LLM's inline glosses. On a successful narration only (a degraded/error dict stays minimal).
        if isinstance(llm_output, dict) and "_synthesis_error" not in llm_output:
            llm_output.setdefault("metric_legend", _METRIC_LEGEND)

    # 2b. Deterministic recommendation gate. A killer sub-verdict FORCES the
    # recommendation regardless of what the LLM chose — the auditable rule wins.
    # We clamp the wrapped {value, _source, ...} in place and record the override
    # in nomination.json + provenance so the gate is never silent.
    gate_action, gate_hits, gate_suppressions = _gate_recommendation(
        sub_results, modality=args.modality)
    recommendation_gate = {"fired": bool(gate_action),
                           "suppressed_vetoes": gate_suppressions}
    if gate_suppressions:
        print(f"[target-profile] recommendation gate SUPPRESSED "
              f"{[s['short']+':'+s['verdict']+' via '+s['suppressed_by']['kind'] for s in gate_suppressions]}",
              file=sys.stderr)
    confidence_tier = {"tier": None}
    if gate_action:
        rec = llm_output.get("overall_recommendation")
        llm_value = rec.get("value") if isinstance(rec, dict) else rec
        recommendation_gate = {
            "fired": True,
            "forced_recommendation": gate_action,
            "llm_recommendation": llm_value,
            "overridden": llm_value != gate_action,
            "triggered_by": gate_hits,
            "suppressed_vetoes": gate_suppressions,
        }
        if isinstance(rec, dict):
            rec["value"] = gate_action
            rec["_gated"] = True  # mark the value as rule-forced, not LLM-chosen
        else:
            llm_output["overall_recommendation"] = {
                "value": gate_action, "_source": "recommendation_gate"}
        print(f"[target-profile] recommendation GATE fired: forced '{gate_action}' "
              f"(LLM said '{llm_value}') via {[h['short']+':'+h['verdict'] for h in gate_hits]}",
              file=sys.stderr)
    else:
        # NO kill fired → the positive tier may raise a deterministic confidence
        # FLOOR. F1-safe: this branch is unreachable when a kill fired; it touches
        # ONLY `confidence`, never `overall_recommendation` (never forces nominate).
        tier, pos_hits = _positive_tier(sub_results)
        confidence_tier = {"tier": tier, "hits": pos_hits}
        if tier:
            floor = _TIER_TO_CONFIDENCE[tier]  # strong→high, moderate→medium
            conf = llm_output.get("confidence")
            llm_conf = conf.get("value") if isinstance(conf, dict) else conf
            # Apply as a floor: never lower the LLM's confidence, only raise it.
            if _CONFIDENCE_RANK.get(floor, 0) > _CONFIDENCE_RANK.get(llm_conf, 0):
                if isinstance(conf, dict):
                    conf["value"] = floor
                    conf["_floored_by_positive_tier"] = True
                else:
                    llm_output["confidence"] = {
                        "value": floor, "_source": "positive_tier"}
                confidence_tier["floored_from"] = llm_conf
                confidence_tier["floored_to"] = floor
            print(f"[target-profile] positive tier: {tier} "
                  f"(dims={sorted({h['short'] for h in pos_hits})}); "
                  f"confidence floor {floor}", file=sys.stderr)

    # Deciding-axis router (L): name the load-bearing gate + whether the framework can
    # evidence it. Reports (never predicts): a fired gate is the deciding axis; on abstention,
    # the unevidenced necessity gates are the routing instruction. Purely additive — reads the
    # already-resolved gate/positive state, touches no verdict.
    deciding_axis = _deciding_axis(
        sub_results, gate_action, gate_hits,
        positive_hits=confidence_tier.get("hits", []) or [],
    )
    print(f"[target-profile] deciding axis [{deciding_axis['basis']}]: "
          f"{deciding_axis.get('routing', '')}", file=sys.stderr)

    # Gate scorecard (deterministic, top-of-report): 8-gate rows from the gate registry, 4-state
    # status reusing the nomination-gate policy. Also emitted in nomination.json.
    scorecard = _gate_scorecard(sub_results, deciding_axis)
    catalogue_rows = _catalogue_rows_from_sub_results(sub_results)

    # 5-field validation_summary — the shared evidence-package writer's contract, composed from
    # target-profile's card-read model (passed = card returned usable data; failed = absent/not-wired
    # OR data_unavailable; passed_with_warnings + excluded_by_applies_when = 0: no method validation,
    # no target-level applies_when gating). Computed HERE (before the emit branch) so the
    # evidence-package emitter and the nomination path below share ONE construction.
    _all_cards = [c for r in sub_results.values() for c in (r.get("cards") or [])]
    _n_failed = sum(1 for c in _all_cards if c.get("_missing"))
    validation_summary = {
        "n_cards_attempted": len(_all_cards),
        "n_cards_passed": len(_all_cards) - _n_failed,
        "n_cards_passed_with_warnings": 0,
        "n_cards_failed": _n_failed,
        "n_cards_excluded_by_applies_when": 0,
    }

    # --emit evidence-package: emit the deterministic machine envelope from the verdict spine and
    # RETURN, skipping every nomination-oriented render (composite panel / md / html / nomination.json
    # / provenance). The spine it reads is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        ep_path = _write_evidence_package(
            args=args, sub_results=sub_results, gate_action=gate_action,
            recommendation_gate=recommendation_gate, confidence_tier=confidence_tier,
            deciding_axis=deciding_axis, validation_summary=validation_summary,
        )
        print(f"[target-profile] wrote {ep_path} (evidence-package; deterministic, LLM-free)")
        print(f"Recommendation: {gate_action or '(no gate fired)'}")
        return 0

    # 3a. Render composite panel PNG + SVG (Shape C — slide-drop artefact).
    figures_dir = args.out / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    composite_png = figures_dir / "target_profile_at_a_glance.png"
    composite_rel = None
    if args.verdict_only:
        # --verdict-only: the "at a glance" panel is a matplotlib figure that also narrates the LLM
        # recommendation — skip it with the rest of the figures. The md/html degrade to no-image.
        print("[target-profile] --verdict-only: skipped composite panel render", file=sys.stderr)
    else:
        try:
            render_composite_panel(
                out_path=composite_png,
                target=args.target,
                indication=args.indication,
                sub_results=sub_results,
                llm_output=llm_output,
            )
            composite_rel = f"figures/{composite_png.name}"
            print(f"[target-profile] wrote {composite_png} (+ .svg companion)",
                  file=sys.stderr)
        except Exception as e:
            # Panel rendering must never block artefact emission. Log + continue
            # with no image reference in the markdown.
            composite_rel = None
            print(f"[target-profile] WARN: composite panel render failed: {e}",
                  file=sys.stderr)

    # 3a-bis. Produce per-card distribution figures (SVG + interactive .plotly.json) via the shared
    # figure registry. This is the dynamic-dashboard Phase B change: a run now PRODUCES the per-card
    # charts (previously rules/summary-only). Best-effort — never blocks artefact emission.
    # PERF Stage 1: --no-figures skips this (the figure double-read + the 4.6MB plotly inline). The
    # HTML then degrades to the tested static no-JS fallback; the verdict spine is byte-identical
    # (card_figures never feeds nomination.json / sub_verdicts — it's a separate presentation slot).
    if args.no_figures:
        card_figures = {}
        print("[target-profile] --no-figures: skipped per-card figure emission (verdict-only mode)",
              file=sys.stderr)
    else:
        _fig_t0 = time.perf_counter() if args.profile_timers else 0.0
        card_figures = _emit_card_figures(sub_results, figures_dir, args.target, args.indication)
        if args.profile_timers:
            print(f"[perf] === figure-emit total {time.perf_counter() - _fig_t0:6.1f}s ===",
                  file=sys.stderr)

    # 3b. Render + emit markdown artefact (Shape A — enriched).
    md = _render_target_profile_md(
        args.target, args.indication, sub_results, llm_output, invoked_lenses,
        composite_figure_relpath=composite_rel,
        deciding_axis=deciding_axis,
        ordinal_matrix=ordinal_matrix,
    )
    (args.out / "target_profile.md").write_text(md)

    # 3c. Render + emit the static HTML governance artifact (self-contained; inlines the
    # composite SVG). Pure projection — never blocks emission on failure.
    try:
        composite_svg = composite_png.with_suffix(".svg") if composite_rel else None
        htmldoc = _render_target_profile_html(
            args.target, args.indication, sub_results, llm_output, invoked_lenses,
            deciding_axis=deciding_axis, ordinal_matrix=ordinal_matrix,
            scorecard=scorecard, composite_svg_path=composite_svg,
            catalogue_rows=catalogue_rows, recommendation_gate=recommendation_gate,
            card_figures=card_figures, figures_dir=figures_dir,
        )
        (args.out / "target_profile.html").write_text(htmldoc)
        print(f"[target-profile] wrote {args.out}/target_profile.html", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: HTML render failed: {e}", file=sys.stderr)

    # Governance / reproducibility. Phase-D convergence (#9): build the governance block via the SHARED
    # _skills_common.build_governance so it can no longer drift from compose-dashboard's — same keys,
    # same construction, one source. Uses the 5-field validation_summary composed above (shared with
    # the --emit evidence-package path). release_pin is a pass-through (target-profile reads live and
    # does not auto-resolve the release); honest default 'unpinned'.
    governance = build_governance("live_latest", args.release_pin or "unpinned", validation_summary)
    # Additive target-profile annotation (does NOT alter the shared 3-key core → no schema drift):
    governance["_note"] = (
        "target-profile reads live data; release auto-resolution is a deferred data-catalog "
        "follow-on, so release_pin is 'unpinned' unless supplied via --release-pin.")

    nomination = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
        "sub_verdicts": {
            short: {
                "skill_dir": r["skill_dir"],
                "verdict": r["verdict"][0] if r["verdict"] else None,
                "driving_rule_id": r["verdict"][1] if r["verdict"] else None,
                "fired_rule_ids": [f["rule_id"] for f in r["fired"]],
                # cards_used: the ACTUAL card set this sub-skill resolved this run (2026-08-12
                # reproducibility fix). Previously only cards_MISSING was recorded, leaving the positive
                # pulled set implicit in the static SUB_SKILL_CARDS map — insufficient to reproduce a run
                # or key an eval ledger. Now the full set + the missing subset are both on the record.
                "cards_used": [c["card_id"] for c in r["cards"]],
                "cards_missing": [c["card_id"] for c in r["cards"] if c.get("_missing")],
            }
            for short, r in sub_results.items()
        },
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "gate_scorecard": scorecard,
        "ordinal_matrix_view": ordinal_matrix,
        # Biomarker convergence facet (Q12, Part 3c): corroboration + stratification + preferred_assay.
        # A FACET (not a gate) — informs confidence + patient-selection; never mints a nominate.
        "biomarker_facet": biomarker_facet,
        # Subtype convergence facet (Part 3c integration layer): the per-molecular-subtype cross-axis
        # convergence (expression / dependency / mutation-frequency). A FACET (not a gate) — defines
        # patient-selection strata + informs confidence; never mints a nominate.
        "subtype_facet": subtype_facet,
        # Fragility facet (verdict-inert flip-stability): worst-case single-rule flip-fragility over the
        # decision-relevant axes + a `contested` flag (declarative threshold). A structural sensitivity
        # measure ("how solid is this call?"), NOT a probability — informs the reader, never mints or
        # moves a recommendation (target_index/contested touch neither the gate nor confidence).
        "fragility": fragility,
        # Heterogeneity facet (verdict-inert): cross-context dispersion (comparator / modality /
        # subtype). A stratified-opportunity signal the pooled verdict hides; never moves the call.
        "heterogeneity": heterogeneity,
        "addressable_population": addressable_population,
        # Per-card figures produced this run (SVG + interactive .plotly.json siblings), keyed by
        # card_id, paths relative to figures/. The dynamic HTML renderer (Phase B PR-2) embeds the
        # `dynamic: True` Plotly specs; falls back to the SVG otherwise.
        "card_figures": card_figures,
        "llm_synthesis": llm_output,
    }
    (args.out / "nomination.json").write_text(
        json.dumps(nomination, indent=2, default=str)
    )

    provenance = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
        "sub_skills_ran": [s for s, _ in SUB_SKILLS],
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "llm_prompt_hash": llm_output.get("executive_summary", {}).get("_prompt_hash"),
        "llm_model_id": llm_output.get("executive_summary", {}).get("_model_id"),
        # Governance item B (2026-07-20): the DECLARED framework model pin. Distinct
        # from llm_model_id (the model that actually ran) — when the two diverge, an
        # env override was used. Auditors compare them to detect per-run drift.
        "framework_model_version": _framework_model_version(),
        "artefacts": [
            "target_profile.md",
            "target_profile.html",
            "nomination.json",
        ] + ([] if args.no_figures else [
            "figures/target_profile_at_a_glance.png",
            "figures/target_profile_at_a_glance.svg",
        ]),
    }
    (args.out / "provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))

    print(f"[target-profile] wrote {args.out}/target_profile.md")
    print(f"[target-profile] wrote {args.out}/nomination.json")
    print(f"[target-profile] wrote {args.out}/provenance.yaml")
    print()
    def _unwrap(raw):
        return raw.get("value") if isinstance(raw, dict) else raw
    print(f"Recommendation: {_unwrap(llm_output.get('overall_recommendation'))}")
    print(f"Confidence:     {_unwrap(llm_output.get('confidence'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
