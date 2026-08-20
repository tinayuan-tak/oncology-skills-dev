"""target-profile — sub-skill fan-out orchestration: the SUB_SKILLS / SUB_SKILL_CARDS
composition maps, per-sub-skill verdict loading, the concurrent fan-out, and the opt-in subtype tier."""
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

import yaml

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import resolve_cards, fired_rules
from _skills_common.rules_loader import load_interpretation_rules
from _skills_common.compose_core import subskill_composition
from _skills_common.card_preprocessors import preprocess_cards_for_gate
from tp_common import SKILLS_DIR



# PERF Stage 2: fan-out thread-pool worker cap. min(#sub-skills, cores-2) — headroom-aware; env
# override for tuning/CI. Threads (not processes) so the process-global method caches are shared.
_FANOUT_MAX_WORKERS = int(os.environ.get("TARGET_PROFILE_FANOUT_WORKERS",
                                          max(2, (os.cpu_count() or 4) - 2)))


# --- Sub-skill orchestration ------------------------------------------------

_SUBSKILL_FN_CACHE: dict = {}
# Module cache populated by _load_sub_skill_verdict_fn (prewarm runs it first, single-threaded), so
# the OPTIONAL _synthesis_facet loader below reads the SAME already-exec'd module — no second
# importlib.exec_module / sys.path race in the concurrent pool.
_SUBSKILL_MODULE_CACHE: dict = {}


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
    _SUBSKILL_MODULE_CACHE[skill_dir_name] = module
    fn = getattr(module, "_verdict", None) or getattr(module, "_snapshot", None)
    _SUBSKILL_FN_CACHE[skill_dir_name] = fn
    return fn


def _load_sub_skill_facet_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_synthesis_facet(cards, fired, verdict_pair) -> dict`, or None.

    This is the uniform opt-in a sub-skill uses to hand the composed synthesis its own DETERMINISTIC
    cross-modal reconciliation (e.g. tumor-presence's per-modality presence matrix + proxy-quality +
    normal comparators) — so the LLM reasons over the skill's computed reconciliation instead of
    re-deriving it from raw card numbers. Reads the module cached by _load_sub_skill_verdict_fn
    (prewarmed single-threaded), so no sub-skill without the hook pays any cost and the concurrent
    pool never re-execs a module. VERDICT-INERT: the facet never enters `fired` or the resolver."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)   # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    return getattr(module, "_synthesis_facet", None) if module is not None else None


def _load_sub_skill_certainty_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_strength_certainty(cards, fired, verdict_pair) -> dict`, or None.

    The uniform opt-in a sub-skill uses to hand the composed layer its per-axis (strength, certainty)
    SIDECAR (CERTAINTY_MODEL §3) — a verdict-inert reliability object keyed by sub-skill short. Mirrors
    `_load_sub_skill_facet_fn`: reads the prewarmed module cache, so a sub-skill without the hook pays
    no cost. Only functional-requirement (the reference axis) supplies it today. VERDICT-INERT: the
    certainty object never enters `fired`, the resolver, or the nomination sub_verdicts."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)   # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    return getattr(module, "_strength_certainty", None) if module is not None else None


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
    ("combo-and-resistance",           "combination_opportunity"),    # R9 (2026-08-20): DEPmap drug-anchor CRISPR — combination opportunities (co-targets more essential under inhibition) + resistance mediators (KOs that RESCUE; NF1/KEAP1/NF2 for KRAS). GATELESS/ADDITIVE like combinatorial-dependency: combination is the primary _verdict (short=combination_opportunity), resistance is DUAL — surfaced via combo-and-resistance's _synthesis_facet (both axes fired below). Absent from _SHORT_TO_GATE → verdict-inert to the nomination spine (recommendation byte-stable). Was LIVE but omitted from the fan-out.
    ("mechanism-and-pharmacology",     "mechanism"),
    ("genomic-alteration-profile",     "genomic_alteration"),  # reframed from mutation-profile
    ("differentiation-landscape",      "differentiation"),
    ("tractability-small-molecule",    "tractability_sm"),     # split (SM half)
    ("surface-modality-fit",           "surface_modality"),    # split (biologics half)
    ("on-target-safety-liability",     "safety"),
    ("target-intrinsic",               "target_intrinsic"),    # GATELESS descriptive PEER (WS1, 2026-08-17): the
                                                               # indication-INDEPENDENT target biology dossier composed as a
                                                               # first-class fan-out input (not a side-channel), so the
                                                               # cross-evidence integrator (LLM synthesis) + sub_verdicts render
                                                               # see it. DESCRIPTIVE: target-intrinsic/run.py has synthesis:none
                                                               # → NO _verdict/_snapshot → verdict_fn is None → verdict=None; and
                                                               # it is DELIBERATELY absent from _SHORT_TO_GATE → gate=None. So its
                                                               # CompositionResult primary is None → it contributes ONLY to
                                                               # sub_verdicts + the LLM synthesis context, NEVER the recommendation
                                                               # gate/positive-tier/deciding-axis. This is the framework's FIRST
                                                               # verdict=None gateless short (`expression`/`combinatorial_dependency`
                                                               # are gateless but DO emit a verdict); the must-not-gate requirement
                                                               # is satisfied STRUCTURALLY (verdict=None + gate=None), so
                                                               # overall_recommendation + confidence stay byte-identical.
    ("cis-feature-coherence",          "cis_coherence"),     # GATELESS coherence facet (Stage 2, 2026-08-20): the
                                                               # locus->expression->dependency coherence owner. ADDITIVE like
                                                               # combinatorial-dependency — DEDICATED axis cis_coherence, self-
                                                               # contained resolver verdict, DELIBERATELY absent from _SHORT_TO_GATE
                                                               # → surfaced in sub_verdicts + the LLM synthesis but NEVER drives the
                                                               # nomination spine (recommendation byte-stable). It DISTINGUISHES an
                                                               # amplification-driven cis-driver from a passenger / an expressed-but-
                                                               # inert target / a trans-driven dependency — a cross-axis integrator
                                                               # over its own new leg + reused expression-dependency + amp-expr cards.
                                                               # Graduation to a positive_signal/positive_contradiction gate is a
                                                               # later CALIBRATED stage (would then enter _SHORT_TO_GATE + full suite).
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
        # 2026-08-20 facet-parity (generalized guard): tumor-presence's _headline/_synthesis_facet reads
        # these via get_card_field, but they were DROPPED from the composer entry → _headline raised →
        # swallowed → the presence claim_vector facet was silently None in the COMPOSED profile.
        # Presence is NOT in _SHORT_TO_GATE (verdict-inert to the nomination spine), so composing them is
        # byte-stable on the verdict; it restores the presence claim_vector to the composed panel.
        "cellline-rna-distribution-by-subtype",
        "normal-tissue-liability",
        "rna-protein-concordance-tumor",
        "sc-normal-celltype-expression",
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
        # v1.9.0 (2026-08-17) SINGLE-CELL + SPATIAL — composer-consistency with the standalone CARDS.
        # All verdict-inert (feed no resolver rung); composed here so the malignant-vs-stroma + in-situ
        # spatial evidence also surfaces in the COMPOSED target-profile selectivity lens (not only
        # standalone). tumor-scrna-celltype-expression is multi-homed (also under tumor-presence, which
        # keys the sc_rna/tumor presence bucket) — a card may compose under >1 lens (cf. modality-
        # therapeutic-window above). spatial-* are composed NOWHERE else, so this is their only home.
        "tumor-scrna-celltype-expression",       # malignant-cell-intrinsic vs stroma/CAF (purity confound, measured)
        "spatial-region-rna-expression",         # in-situ tumour-vs-TME RNA enrichment
        "spatial-tumor-normal-colocalization",   # in-situ normal-epithelium bystander adjacency
        "spatial-surface-protein-abundance",     # in-situ protein enrichment (abstains where GeoMx sparse)
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
        "organoid-crispr-dependency",            # Organoid-native Chronos facet (2026-08-18) — corroborating
                                                 # dependency read in patient-derived 3D organoids. Paired
                                                 # with functional-requirement CARDS (composer-consistency).
                                                 # ADDITIVE render-only facet (verdict-inert: its supportive/
                                                 # neutral rules feed NO resolver ladder).
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
        "coessential-module",                    # 2026-08-19 (enrichment review #1): co-essential-module
                                                 # CONFIDENCE facet (is the dependency embedded in a coherent
                                                 # module?). In functional-requirement CARDS; composed here so
                                                 # it is not dropped from the profile. VERDICT-INERT (no
                                                 # resolver rung; folds into dependency_confidence_note) →
                                                 # byte-stable on the verdict spine.
        "dependency-predictability",             # 2026-08-20 (facet-parity): in functional-requirement
                                                 # CARDS + read by _headline (predictability_class →
                                                 # DEP corroboration bump) but DROPPED here, so
                                                 # _synthesis_facet's _headline raised KeyError →
                                                 # swallowed → the dependency claim_vector facet (PR-C)
                                                 # AND synthesis.claim_vectors were silently None in the
                                                 # COMPOSED profile. VERDICT-INERT (CONFIDENCE annotation;
                                                 # no resolver rung) → byte-stable on the verdict spine.
        "genomic-event-model-match",             # 2026-08-20 (facet-parity): same class — read by
                                                 # _headline (event_correspondence_class biomarker render
                                                 # facet), in functional-requirement CARDS, dropped here.
                                                 # VERDICT-INERT (render facet; no resolver rung).
    ],
    "synthetic-lethal-partners": [
        "synthetic-lethal-partners",
    ],
    "combinatorial-dependency": [
        "combinatorial-dependency",      # DepMap ParalogV2 dual-KO GI + published corroboration
                                         # (Dede/in4mer/Horlbeck). Matches the skill's SKILL.md cards_used.
    ],
    "combo-and-resistance": [
        "combo-crispr-screen",           # DepMap drug-anchor CRISPR — combination opportunities
        "resistance-emergence-signature",  # sign-mirror rescue arm — resistance mediators + Tahoe adaptation
    ],
    "cis-feature-coherence": [
        "cis-feature-expression-coherence",  # GoF leg-1: CN -> own-expression cis-dosage (amplification)
        "cellline-methylation-expression-coherence",  # LoF leg-1: promoter methylation -> own LOW expression (silencing)
        "expression-dependency-correlation", # leg-2 (reused; also composed under functional-requirement)
        "amp-expr-stratified-dependency",    # leg-2 (reused; also composed under genomic-alteration-profile)
        "patient-cis-coherence",             # VERDICT-INERT patient (TCGA) corroboration facet (fires no rule)
                                             # Matches cis-feature-coherence SKILL.md cards_used. The two leg-2
                                             # cards are HOME cards of other sub-skills; composing them here too
                                             # is byte-stable (same cards, different lens) — the cis_coherence
                                             # axis rules fire on their fields via card_id_filter.
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
        # 2026-08-20 facet-parity (generalized guard): genomic's _build_headline lifts these two
        # (dependency CONFIDENCE cards) via _lift_field (declarative _HEADLINE_FIELDS), but they were
        # DROPPED from the composer entry → _synthesis_facet raised KeyError → swallowed → the genomic
        # claim_vector was silently None in the COMPOSED profile. Dependency-confidence cards feed NO
        # genomic resolver rung → verdict byte-stable; composing them restores the genomic claim_vector.
        "cross-consortium-dependency",
        "dependency-predictability",
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
        "target-clonality",                  # scientific-gap #2 (2026-08-14): mutation clonality/truncality
                                             # (ccf). In genomic-alteration-profile CARDS →
                                             # composer-consistency requires it here. VERDICT-INERT (no rules).
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
        "pathway-node-leverage",             # WS3 (2026-08-17): COMPARATIVE node-leverage. In
                                             # differentiation-landscape CARDS; composed here so the fanout
                                             # does not silently drop it. VERDICT-INERT (soft axis_fit signals
                                             # + fired_rule_ids for the hypothesis agent; feeds NO resolver →
                                             # nomination byte-stable, axis_fit is not gate-consumed).
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
        "sc-surface-normal-safety",          # REVIVE 2026-08-19: sc CITE-seq surface footprint on normal immune (additive; no resolver rung → composed verdict byte-stable).
        "sc-surface-rna-protein-concordance", # REVIVE 2026-08-19: sc RNA↔surface-protein proxy quality (additive; no resolver rung → byte-stable).
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
        "copy-number-distribution",       # S1-1 (2026-08-17) — REQUIRED for the amplification GUARD to fire IN
                                          # COMPOSITION (same pattern as alteration-role above). safety.resolver
                                          # GROUP-0's copy-number-amplified-oncogene-safety-context rung keys on
                                          # copy-number-distribution.patient_focal_cn_class; without this line the
                                          # guard could never fire in the composed profile and an amplification-
                                          # driven oncogene (ERBB2/MDM2) would still be wrongly DOWNGRADED off its
                                          # on-target-safety HOLD. (Also in on-target-safety-liability/run.py CARDS.)
    ],
    "target-intrinsic": [                 # GATELESS descriptive dossier (WS1, 2026-08-17). Compose ONLY the
                                          # target-intrinsic-EXCLUSIVE cards — the ones NOT already composed under
                                          # another sub-skill's lens. target-intrinsic's OTHER 12 cards
                                          # (gnomad-lof-constraint + the P5 safety legs → on-target-safety-liability;
                                          # surfaceome-family-classification + structure-features-static +
                                          # shed-ectodomain-liability + normal-tissue-liability → surface-modality-fit;
                                          # signaling-network-mechanism → mechanism-and-pharmacology; paralog-buffering →
                                          # functional-requirement) are DELIBERATELY not re-listed here — re-adding them
                                          # would double-read those cards, and the composer drop-guard/reverse-guard are
                                          # already satisfied because they are HOME cards of target-intrinsic composed
                                          # SOMEWHERE. No gate is scoped to this entry (target_intrinsic ∉ _SHORT_TO_GATE),
                                          # so the resolver-dependency guard does not apply — these cards fire only their
                                          # own descriptive/verdict-inert rules (if any) and never a nomination rung.
        "target-identity-summary",           # canonical id / family / aliases (also read standalone by the emitter for hgnc_id)
        "target-development-level",           # Pharos/IDG TDL druggability/novelty tier (Tclin/Tchem/Tbio/Tdark)
        "protein-domains-class",              # UniProt FT DOMAIN architecture + keyword protein class
        "domain-modality-relevance",          # interpretive domain→modality facet (inhibitor_sufficient vs removal_required)
        "ppi-interactome",                    # STRING functional network + CORUM complex membership
        "gene-ontology-annotation",           # GO BP/MF/CC term membership
        "reactome-pathway-membership",        # Reactome pathway/geneset membership + top-level rollup
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
    "subgroup-stratified-dependency",         # VERDICT-BEARING in this tier: its subtype-non-dependence-
                                              # opposing rule is what _subtype_verdict reads → one-directional
                                              # negative HOLD (subtype_specific_non_dependence).
    "subgroup-stratified-mutation-frequency", # DISPLAY-ONLY within this tier (subtype-verdict-shifting review
                                              # M6): NO interpretation rule keys on it, so _subtype_verdict
                                              # (which only inspects subtype_fit_genomic from the dependency
                                              # card) can never see it — it is resolved+fired every --subtypes
                                              # run but emits no subtype-tier signal. Its subtype mutation
                                              # panorama is already surfaced descriptively in genomic-alteration-
                                              # profile. Kept here for the render panorama, NOT for the verdict.
]


def _subtype_verdict(fired: list[dict]) -> tuple[str, str | None] | None:
    """Verdict producer for the subtype tier. BI-DIRECTIONAL, negative-precedence (2026-08-19,
    subtype-verdict-shifting review \u00a75).

    NEGATIVE (unchanged, takes precedence): subtype-non-dependence-opposing matches a MEASURED,
    floor-cleared, NOT-dependent stratum -> subtype_fit_genomic: opposing ->
    `subtype_specific_non_dependence` (the nomination gate maps it to a HOLD).

    POSITIVE (new): subtype-restricted-dependency-supportive matches a MEASURED, floor-cleared,
    STRONG-dependent stratum -> subtype_fit_genomic: supportive -> `subtype_restricted_dependency`
    (the gate treats it as a SUPPORTIVE positive + a non_dependent veto-suppressor — the
    precision-oncology channel: POU2F3/SCLC-P, CMS4/CRC).

    Precedence is CONSERVATIVE: if any opposing subtype fired, the HOLD wins. The positive fires
    ONLY when a supportive subtype fired and NO opposing one did. Admissibility (n>=30 floor,
    measured) is enforced upstream at rule-fire time. Byte-stable: no --subtypes -> no subtype rule
    fires -> None; existing opposing-only runs unchanged; only supportive-without-opposing is new.
    """
    def _sig(f: dict) -> str:
        # `or ''` guards subtype_fit_genomic: null (present key, None value) -> else `'x' in None` raises.
        return ((f.get("signals") or {}).get("subtype_fit_genomic") or "")

    subtype = [f for f in fired if f.get("tier") == "subtype"]
    opposing = [f for f in subtype if "opposing" in _sig(f)]
    if opposing:
        return ("subtype_specific_non_dependence", opposing[0].get("rule_id"))   # HOLD — precedence
    supportive = [f for f in subtype if "supportive" in _sig(f)]
    if supportive:
        return ("subtype_restricted_dependency", supportive[0].get("rule_id"))   # SUPPORTIVE positive
    return None


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
    axes = ("intracellular_intrinsic", "surface_intrinsic", "combinatorial_dependency", "cis_coherence",
            "combination_opportunity", "resistance_emergence")

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
        # OPTIONAL deterministic cross-modal reconciliation facet (2026-08-17). Best-effort +
        # VERDICT-INERT: a sub-skill that exposes _synthesis_facet hands the composed synthesis its
        # own reconciliation (e.g. tumor-presence's per-modality matrix); absence / failure → None,
        # never touching verdict/fired/cards. Only tumor-presence supplies it today.
        _facet_fn = _load_sub_skill_facet_fn(skill_dir)
        synthesis_facet = None
        if _facet_fn is not None:
            try:
                synthesis_facet = _facet_fn(cards, fired, verdict_pair)
            except Exception:  # noqa: BLE001 — a facet must never break the fan-out
                synthesis_facet = None
        # OPTIONAL per-axis (strength, certainty) SIDECAR (CERTAINTY_MODEL §3). Best-effort +
        # VERDICT-INERT, same discipline as synthesis_facet: a sub-skill that exposes _strength_certainty
        # hands the composed layer its reliability object; absence / failure → None. Only
        # functional-requirement supplies it today.
        _cert_fn = _load_sub_skill_certainty_fn(skill_dir)
        strength_certainty = None
        if _cert_fn is not None:
            try:
                strength_certainty = _cert_fn(cards, fired, verdict_pair)
            except Exception:  # noqa: BLE001 — a sidecar must never break the fan-out
                strength_certainty = None
        return short, {
            "skill_dir": skill_dir,
            "cards": cards,
            "fired": fired,
            "verdict": verdict_pair,  # (str, driving_rule_id) or None
            # Deterministic cross-modal reconciliation for the synthesis prompt (None for every
            # sub-skill except tumor-presence). ADDITIVE / verdict-inert — see _load_sub_skill_facet_fn.
            "synthesis_facet": synthesis_facet,
            # Per-axis (strength, certainty) sidecar (None except functional-requirement). ADDITIVE /
            # verdict-inert — see _load_sub_skill_certainty_fn. Assembled by tp_facets._certainty_by_axis.
            "strength_certainty": strength_certainty,
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

    # PERF Stage 2 (2026-07-23): the sub-skills are GENUINELY INDEPENDENT (collect-then-synthesize;
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


__all__ = [
    'SUBTYPE_CARDS',
    'SUBTYPE_SHORT',
    'SUB_SKILLS',
    'SUB_SKILL_CARDS',
    '_FANOUT_MAX_WORKERS',
    '_SHORT_TO_GATE',
    '_SUBSKILL_FN_CACHE',
    '_load_sub_skill_verdict_fn',
    '_load_sub_skill_facet_fn',
    '_load_sub_skill_certainty_fn',
    '_prewarm_sub_skill_imports',
    '_run_sub_skills',
    '_skipped_synthesis_output',
    '_subtype_verdict',
]
