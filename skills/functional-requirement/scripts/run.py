#!/usr/bin/env python3
"""functional-requirement — is target X a genetic dependency in indication Y.

Consumes 7 dependency-relevant cards (CRISPR + RNAi + concordance +
lineage-selectivity + paralog-buffering + prism-crispr chemical-genetic confirmation +
dependency-predictability) + the dependency-* rule subset.

The verdict is resolved from the first 6 cards via the shared dependency resolver;
dependency-predictability is META-evidence that drives a CONFIDENCE ANNOTATION only
(dependency_confidence_note), never the verdict (Gate-C, 2026-07-21).

Calls the shared run_wired_skill dispatcher (2026-07-09).
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field, resolve_cards, _summary_is_unavailable
from _skills_common.resolver import resolve_or_raise
from _skills_common.synthesis_dependency import synthesize_dependency
from _skills_common.dependency_claims import dependency_claim_vector, dependency_key_signals
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero
# Read-only reuse of the shared target-contracts path (NOT modifying scope.py — collision-safe).
from _skills_common.scope import DEFAULT_CONTRACTS_REPO


SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.4.0"   # 1.4.0 (2026-08-13): production review — offline recorded-fixture replay drift
                          #        guard (test_functional_requirement_replay.py) + SKILL.md parity
                          #        (rules_scope: -dependency-predictability [verdict-inert], +partner-conditional-
                          #        dependency [verdict-bearing]; measurement_types += partner_conditional +
                          #        cross_consortium; 11->13 card count). Verdict spine byte-stable.
                          # 1.3.1 (2026-08-08): fix 2 headline field-name drift bugs — rnai_call read
                          #        `dependency_class` (card emits `rnai_dependency_class`) + lineage_selectivity
                          #        read `lineage_selectivity_class` (card emits `enrichment_class`); both were
                          #        silently None despite live data. Display-only — verdict spine byte-stable.
                          # 1.3.0: opt-in --subtypes DESCRIPTIVE dependency-by-molecular-subgroup
                          #        panorama (subgroup-stratified-dependency; e.g. MSI_H vs MSS).
                          #        Verdict-inert (touches no rung); byte-stable without the flag.
                          # 1.2.0: opt-in --synthesize LLM narration (dependency lens) — two-slot,
                          #        verdict-inert; FULL evidence set + Axis-2 controls + Axis-3 omnibus.

CARDS = [
    "pan-cancer-crispr-dependency-distribution",
    "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance",
    "dependency-lineage-selectivity",           # TARGET-GRAIN by design: enrichment_class
                                                # =lineage_selective fires if ANY lineage is enriched, NOT
                                                # necessarily the queried indication's lineage. So the
                                                # lineage_selective VERDICT means "selective to some
                                                # lineage", and the indication-MATCH is done in the LLM
                                                # synthesis layer (per-indication lookup over
                                                # per_lineage_stats), NOT the machine verdict (FR review,
                                                # 2026-08-13). A future indication-conditioned verdict would
                                                # be a grain change (needs a nomination-side decision).
    "paralog-buffering",
    "partner-conditional-dependency",           # (2026-08-09) — VERDICT-BEARING synthetic-
                                                # lethality rescue. Does dependency stratify by a
                                                # PARTNER gene's deficiency (WRN×MSI, PARP1×HRD)? Its
                                                # partner-conditional-{strongly,moderately}-dependent
                                                # rules fire partner_conditional_dependent in
                                                # dependency.resolver — a distinct verdict that RESCUES
                                                # a pooled non_dependent veto (mirrors the paralog-
                                                # buffered rescue), one-directional. Whole-cohort
                                                # (target-only); the MODERATE tier IS rescue-firing for
                                                # this family (WRN×MSI = -0.41). Also in target-profile
                                                # SUB_SKILL_CARDS[functional-requirement].
    "prism-crispr-concordance",                 # chemical-genetic CONFIRMATION arm (gate C,
                                                # 2026-07-20). Its triangulated_target_engaged
                                                # class fires e7-triangulated-target-engaged-supportive, which
                                                # the dependency resolver now reads as
                                                # chemical_genetic_confirmed_dependent (a positive-only,
                                                # veto-safe confirmation). The card is ALSO in tractability-
                                                # small-molecule's CARDS ("a compound was found") — one
                                                # measurement routes many-to-many to gates; each gate's
                                                # resolver/snapshot reads only its own rule_ids.
    "cross-consortium-dependency",              # Project Score (2026-08-10) — gate-C CORROBORATION: does
                                                # Sanger Project Score AGREE with Broad Achilles on the
                                                # dependency? Two independent consortia agreeing > CRISPR×RNAi
                                                # (both Broad). ADDITIVE, verdict-inert (raises confidence;
                                                # feeds NO resolver rung).
    "dependency-predictability",                # Gate-C (2026-07-21) — META-evidence
                                                # ("how omics-predictable is this dependency, and by what?").
                                                # Composed so it RUNS; it feeds a CONFIDENCE ANNOTATION only
                                                # (dependency_confidence_note), NEVER the verdict/resolver.
                                                # predictability is about a dependency call, not a call itself.
    "expression-dependency-correlation",        # Gate-C biomarker facet (2026-07-22): "expression
                                                # predicts dependency" (patient-selection). Was ORPHANED —
                                                # present in target-profile's render maps (title/role/
                                                # reports_into) + has a live dispatcher, but was in NO
                                                # sub-skill CARDS, so correlation_class never computed +
                                                # rendered empty. Render-only facet (its expression-biomarker-*
                                                # rules feed NO resolver — verdict-inert), grouped with the
                                                # dependency stratification facets. Also added to
                                                # target-profile SUB_SKILL_CARDS[functional-requirement].
    "abundance-dependency",                     # Q7 PROTEIN arm of expression-as-biomarker-of-dependency
                                                # (2026-07-22): "protein abundance predicts dependency".
                                                # Sibling of expression-dependency-correlation (RNA arm) —
                                                # composed alongside it so the biomarker facet can compare
                                                # RNA vs protein (preferred_assay). ADDITIVE render-only facet
                                                # (abundance-dependency-* rules feed NO resolver → dependency
                                                # verdict byte-stable). Biology axis; no modality facet.
    "recommended-models",                       # Q4 patient↔model correspondence (2026-07-22). Routes to
                                                # Gate C as MODEL-BACKED-DEPENDENCY corroboration (its
                                                # master-plan Patient-pop/Q10 home was deleted). Its
                                                # recommended-models-* rules emit SM/degrader supportive on
                                                # well_modeled (a screenable, model-backed dependency basis);
                                                # ADDITIVE — feed NO resolver ladder → dependency verdict
                                                # byte-stable. Also in target-profile SUB_SKILL_CARDS.
    "genomic-event-model-match",                # GENOTYPE-matched patient↔model facet (cross-wire,
                                                # 2026-08-19). Complements recommended-models (expression-
                                                # similarity) with genotype IDENTITY: which DepMap models
                                                # carry the SAME functional event in the target as the
                                                # indication's tumors, and are those models dependent? Built
                                                # + homed in genomic-alteration-profile; cross-wired here for
                                                # a sharper patient-selection read. ADDITIVE, verdict-INERT —
                                                # its event-correspondence rules are genomic (NOT dependency-*),
                                                # so FR's dependency-rule filter drops them from the verdict.
    "organoid-crispr-dependency",               # Organoid-native Chronos facet (2026-08-18). The organoid
                                                # READING of the same screens (OrganoidGeneEffect.csv, 114
                                                # GI-dominated organoid models, normalized within-organoid).
                                                # Its organoid-{selective,broad}-dependency-supportive rules
                                                # emit SM/degrader SUPPORTIVE; pan-essential/rare/not-dependent
                                                # NEUTRAL; data_unavailable insufficient. ADDITIVE — feeds NO
                                                # resolver ladder → dependency verdict byte-stable (the small
                                                # GI-skewed cohort corroborates a positive dependency but is
                                                # NEVER a trusted independent veto; the pan-cancer card owns
                                                # the killer). Target-grain; indication accepted-not-consumed.
    "coessential-module",                       # Co-essential-module CONFIDENCE facet (2026-08-19) — the
                                                # enrichment-review item (depmap-coessentiality-26q1-v1 was
                                                # orphaned). Is the dependency embedded in a COHERENT co-essential
                                                # module (complex/pathway partners) or ISOLATED? A module-anchored
                                                # call is more mechanism-credible. VERDICT-INERT — feeds NO resolver
                                                # rung; folds into dependency_confidence_note (sibling of cross-
                                                # consortium + predictability). Generic-dispatch wired via the
                                                # card's methods.entrypoint. Target-grain; indication not consumed.
]

# SUBTYPE axis (2026-08-06) — kept OUT of the scalar CARDS list ON PURPOSE, mirroring
# genomic-alteration-profile's SUBTYPE_CARDS. subgroup-stratified-dependency (tier:subtype) is a
# PANORAMA card: its dispatcher needs externally-resolved strata (subgroup_context.resolved_strata_ids)
# or it returns only a data-note — so it resolves on a SEPARATE, --subtypes-gated path (the
# dispatcher's subtype_panorama_fn hook), never on the whole-cohort verdict spine. DESCRIPTIVE:
# recomputes per-stratum Chronos WITHIN each subgroup's cell-line set (e.g. MSI_H vs MSS), emitting
# per_subgroup_metrics + cross_subgroup_delta_dependency; NO verdict signal → touches NO resolver rung
# (the dependency verdict is byte-stable whether or not a subtype scope is passed). The dependency
# analog of genomic-alteration's subgroup-stratified-mutation-frequency + tumor-presence's
# tumor-rna-distribution-by-subtype. NOTE: DepMap per-indication molecular strata are frequently
# UNDERPOWERED (few cell lines per subgroup) — the card tags subgroup_n<30 `underpowered`, and the
# panorama surfaces the evidence_state so an underpowered stratum is never over-read.
SUBTYPE_CARDS = [
    "subgroup-stratified-dependency",
]

# Cross-stratum delta threshold mirroring the card's interpretation_hints
# (meaningful_subgroup_delta). Display-only flavor label, NOT a verdict.
_MEANINGFUL_SUBGROUP_DELTA = 0.10
# Power floor mirroring the card + subgroup_common/panorama.py SUBGROUP_N_FLOOR: DepMap per-indication
# molecular strata below this are UNDERPOWERED and must never be read as a subtype-specific call.
_SUBGROUP_N_FLOOR = 30
# subgroup-stratified-dependency per-stratum `class` → subtype-scope verdict term (Phase 4). A powered,
# MEASURED stratum yields a real call; everything else is inadmissible (underpowered / insufficient).
_SUBGROUP_CLASS_TO_VERDICT = {
    "strong_dependency":   "dependent",
    "moderate_dependency": "moderately_dependent",
    "not_dependent":       "not_dependent",
    "insufficient":        "insufficient",
}


def _subtype_scope_verdict(per_subgroup: list) -> dict:
    """Phase 4: the SUBTYPE-scope verdict — the queried strata's per-stratum dependency call, POWER-GATED.
    A stratum is admissible only when evidence_state=='measured' AND subgroup_n>=floor; otherwise it is
    `underpowered` and never read as a subtype-specific difference (guards multiple-testing over the
    ~14 DepMap strata). ADDITIVE + verdict-INERT: this rides in the --subtypes panorama block only and
    never touches the pooled dependency_verdict. Returns {by_stratum, n_admissible, headline}."""
    by_stratum: dict = {}
    for r in per_subgroup or []:
        stratum = r.get("stratum")
        if not stratum:
            continue
        n = r.get("subgroup_n")
        powered = (r.get("evidence_state") == "measured"
                   and isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR)
        by_stratum[stratum] = (_SUBGROUP_CLASS_TO_VERDICT.get(r.get("class"), "insufficient")
                               if powered else "underpowered")
    # NB: set literals (not tuples) for these membership tests — a ("x","y") tuple would false-match the
    # cross-skill rule-id drift guard's (rule_id, verdict) precedence-tuple regex (test_no_reference_drift).
    admissible = {s: v for s, v in by_stratum.items() if v not in {"underpowered", "insufficient"}}
    if not admissible:
        headline = "no adequately-powered molecular subgroup in this indication (DepMap strata below floor)"
    else:
        deps = [s for s, v in admissible.items() if v in {"dependent", "moderately_dependent"}]
        nondeps = [s for s, v in admissible.items() if v == "not_dependent"]
        if deps and nondeps:
            headline = f"subgroup-specific dependency — dependent in {', '.join(deps)}; not in {', '.join(nondeps)}"
        elif deps:
            headline = f"dependent across measured subgroups ({', '.join(deps)})"
        else:
            headline = f"not dependent across measured subgroups ({', '.join(nondeps)})"
    return {"by_stratum": by_stratum, "n_admissible": len(admissible), "headline": headline}


def _resolve_dependency_subtype_panorama(target: str, indication: str | None,
                                         subtypes: list) -> dict:
    """DESCRIPTIVE dependency-by-subgroup panorama — resolve subgroup-stratified-dependency across
    the requested strata (e.g. MSI_H, MSS). Mirrors genomic-alteration's _resolve_subtype_panorama:
    the card is a PANORAMA dispatcher, so it needs subgroup_context.resolved_strata_ids threaded or
    it returns only a data-note (why it is NOT in the whole-cohort CARDS list).

    Returns the {cards, scope_subtypes, subtype_dependency_panorama} projection the dispatcher's
    subtype_panorama_fn hook expects. NO resolver rung is touched, so the dependency verdict spine
    is byte-stable whether or not --subtypes is passed. Reads the card's ACTUAL emitted field names
    (per_subgroup_metrics rows: stratum/class/evidence_state/median_chronos/subgroup_n;
    cross_subgroup_delta_dependency reducer)."""
    subgroup_context = {"resolved_strata_ids": list(subtypes),
                        "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication,
                              subgroup_context=subgroup_context)
    dep = next((c for c in sub_cards
                if c["card_id"] == "subgroup-stratified-dependency"), None)
    summary = (dep or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    # Only MEASURED strata are admissible for comparison (underpowered/absent are inadmissible —
    # the card's own discipline: DepMap per-subgroup cell-line n is frequently below the floor).
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"]
    delta = summary.get("cross_subgroup_delta_dependency")

    # Compact pattern label mirroring the card's interpretation_hints (delta on median_chronos):
    # >= 0.10 with >=2 measured strata = subgroup-specific; < 0.10 with >=2 = uniform; else n/a.
    # DISPLAY-ONLY flavor — NOT a verdict.
    if len(measured) < 2 or delta is None:
        pattern = "not_informative"
    elif abs(delta) >= _MEANINGFUL_SUBGROUP_DELTA:
        pattern = "subgroup_specific_dependency"
    else:
        pattern = "uniform_across_subgroups"

    return {
        "cards": sub_cards,
        "scope_subtypes": list(subtypes),
        "subtype_dependency_panorama": {
            "subtype_dependency_pattern":       pattern,   # display-only flavor, NOT a verdict
            # Phase 4: the SUBTYPE-scope verdict (power-gated per-stratum dependency call). This is the
            # authoritative `subtype` rung of dependency_verdict_by_scope — it lives HERE (not in
            # _headline) because the dispatcher resolves the --subtypes panorama AFTER headline_fn and
            # merges this block into the headline. Verdict-inert to the pooled spine.
            "subtype_verdict":                  _subtype_scope_verdict(per_subgroup),
            "n_subgroups_with_data":            summary.get("n_subgroups_with_data"),
            "max_subgroup_dependency":          summary.get("max_subgroup_dependency"),
            "min_subgroup_dependency":          summary.get("min_subgroup_dependency"),
            "cross_subgroup_delta_dependency":  delta,
            "measured_strata":                  [r.get("stratum") for r in measured],
            # surface per-stratum class + power so an underpowered stratum is never over-read
            "per_stratum":                      [{"stratum": r.get("stratum"),
                                                  "class": r.get("class"),
                                                  "evidence_state": r.get("evidence_state"),
                                                  "median_chronos": r.get("median_chronos"),
                                                  "subgroup_n": r.get("subgroup_n")}
                                                 for r in per_subgroup],
            "_missing": bool(dep is None or dep.get("_missing")),
            "_missing_reason": (dep or {}).get("_missing_reason"),
        },
    }

# The verdicts that ARE a real dependency call (positive or veto) — the ones a predictability
# confidence note meaningfully sharpens. On insufficient/discordant/underpowered verdicts the
# note stays neutral (there is no call to be confident in).
_DEPENDENCY_CALL_VERDICTS = frozenset({
    "concordant_dependent", "lineage_selective", "selective_dependent",
    "chemical_genetic_confirmed_dependent", "broadly_dependent",
    "non_dependent", "non_dependent_paralog_buffered", "pan_essential_killer",
    # partner_conditional_dependent IS a real dependency call (a partner-conditional
    # dependency that escapes a pooled non_dependent veto). It was added to dependency.resolver.yaml
    # but never here, so its predictability-confidence annotation was wrongly suppressed.
    "partner_conditional_dependent",
})

# The complement: verdicts that are NOT a dependency call (predictability annotation stays neutral).
# Together with _DEPENDENCY_CALL_VERDICTS these must EXHAUSTIVELY PARTITION dependency.resolver.yaml's
# verdict enum — the Guard-A test (skills/tests/test_resolver_verdict_consumers.py) fails if the
# resolver grows a verdict that neither set classifies, so a new verdict can't silently fall through
# the "not a call" branch again.
_NON_CALL_VERDICTS = frozenset({
    "discordant",
    "insufficient",
    "insufficient_underpowered",
    "insufficient_underpowered_pan_essential",
})


# Confidence ladder (low→high) for the cross-consortium corroboration lift below.
_CONFIDENCE_LADDER = ("unknown", "standard", "moderate", "high")


def _dependency_confidence_note(verdict: str, predictability_class: str | None,
                                cross_consortium_class: str | None = None,
                                coessential_module_class: str | None = None) -> dict:
    """Gate-C: a CONFIDENCE ANNOTATION over the dependency verdict. NEVER changes
    the verdict or the resolver. Composed from THREE independent meta-signals:

      1. dependency-predictability — "how omics-learnable is this dependency, and by what feature?"
         (own_omics_driven→high, context_or_driver_dependent→moderate, weak/unpredictable→standard,
         data_unavailable→unknown). Sets the BASE confidence.
      2. cross-consortium-dependency (2026-08-12) — does an INDEPENDENT CRISPR consortium (Sanger
         Project Score) corroborate the Broad Achilles call? Two distinct guide libraries + analysis
         pipelines agreeing is stronger corroboration than same-ecosystem CRISPR×RNAi, so
         `concordant_dependent` RAISES confidence (lifts a bare standard/unknown to moderate) and
         `discordant` appends a caution caveat. NEVER a verdict downgrade — the resolver owns the
         verdict; corroboration only tunes CONFIDENCE (the card's own role: corroboration discipline).
      3. coessential-module (2026-08-19) — is the dependency embedded in a COHERENT co-essential module
         (complex/pathway partners co-essential across the same cell lines)? A module-anchored
         dependency is more mechanism-credible, so `in_coherent_module` RAISES confidence (lifts a bare
         standard/unknown to moderate); `isolated_dependency` appends a caveat. Same corroboration
         discipline — never a verdict move.

    Returns {confidence, note} where confidence ∈ {high, moderate, standard, unknown}. Annotates only
    on an actual dependency call (_DEPENDENCY_CALL_VERDICTS); otherwise `standard` with no meta-claim."""
    if verdict not in _DEPENDENCY_CALL_VERDICTS:
        return {"confidence": "standard",
                "note": "Predictability annotation applies only to an actual dependency call."}
    pc = predictability_class
    if pc == "own_omics_driven":
        conf = "high"
        note = ("Dependency is predictable from the target's own omics "
                "(biomarker-hypothesis-bearing) — higher confidence in the call.")
    elif pc == "context_or_driver_dependent":
        conf = "moderate"
        note = ("Dependency is omics-predictable, but from lineage/driver context rather "
                "than the target's own features — the biomarker is the context.")
    elif pc in ("weakly_predictable", "unpredictable"):
        conf = "standard"
        note = ("Dependency is not well explained by omics — the call rests on the genetic "
                "evidence itself; no omics biomarker handle (not a verdict downgrade).")
    else:  # data_unavailable or absent
        conf = "unknown"
        note = "Predictability not computed for this target (E5 precompute coverage gap)."

    # Independent cross-consortium corroboration (Broad Achilles vs Sanger Project Score).
    if cross_consortium_class == "concordant_dependent":
        if _CONFIDENCE_LADDER.index(conf) < _CONFIDENCE_LADDER.index("moderate"):
            conf = "moderate"   # independent-consortium replication is itself a confidence handle
        note += (" Independently corroborated across consortia "
                 "(Broad Achilles + Sanger Project Score agree).")
    elif cross_consortium_class == "discordant":
        note += (" CAUTION: an independent consortium (Sanger Project Score) does NOT corroborate "
                 "the Broad dependency call — a confidence caveat, not a veto.")

    # Co-essential-module coherence (mechanism-anchoring corroboration).
    if coessential_module_class == "in_coherent_module":
        if _CONFIDENCE_LADDER.index(conf) < _CONFIDENCE_LADDER.index("moderate"):
            conf = "moderate"   # a module-anchored dependency is itself a mechanism-credibility handle
        note += (" Module-anchored — the dependency sits in a coherent co-essential module "
                 "(complex/pathway partners co-essential across cell lines).")
    elif coessential_module_class == "isolated_dependency":
        note += (" Note: the dependency is NOT co-essential with a coherent module "
                 "(isolated) — a mechanism-anchoring caveat, not a veto.")
    return {"confidence": conf, "note": note}

QUESTION = ("Is {target} a genetic dependency in {indication}, and how does "
            "the call hold up across CRISPR, RNAi, concordance, lineage-"
            "selectivity, and paralog-buffering views?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver.
    The former if-chain now lives in resolvers/dependency.resolver.yaml (target-contracts, 2026-07-20),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "dependency")

# ── (strength, certainty) emission — reference axis (CERTAINTY_MODEL.md dependency worked
#    example). ADDITIVE + verdict-inert: computed from the crispr card's numeric provenance the
#    verdict already consumed; never alters dependency_verdict. certainty needs NO outcome labels.
_DEP_STRONG_POS = {"strongly_dependent", "broadly_dependent", "concordant_dependent",
                   "chemical_genetic_confirmed_dependent"}
_DEP_MOD_POS = {"lineage_selective", "selective_dependent", "partner_conditional_dependent"}
_DEP_NEG = {"non_dependent", "non_dependent_paralog_buffered", "discordant"}
_DEP_INSUFF = {"insufficient", "insufficient_underpowered", "insufficient_underpowered_pan_essential", None}
_ORD = {"low": 0, "medium": 1, "high": 2}

# The DECISION-RELEVANT dependency cards — the verdict-bearing set that bears on the dependency CALL.
# unknown_mass is the fraction of THESE that came back blind this run (CERTAINTY_MODEL).
# cross-consortium + predictability are CONFIDENCE annotations (not call-bearing) and are intentionally
# excluded — they inform certainty's other components, not the coverage-gap of the call itself.
_DECISION_RELEVANT_CARDS = (
    "pan-cancer-crispr-dependency-distribution",
    "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance",
    "dependency-lineage-selectivity",
    "paralog-buffering",
    "partner-conditional-dependency",
    "prism-crispr-concordance",
)


def _dependency_strength(verdict) -> str:
    """Signed graded strength from the verdict (magnitude of the dependency signal)."""
    if verdict in _DEP_STRONG_POS:
        return "strong_positive"
    if verdict in _DEP_MOD_POS:
        return "moderate_positive"
    if verdict == "pan_essential_killer":
        return "broad_nonselective"   # strong magnitude, low SELECTIVE value (routes to tox)
    if verdict in _DEP_NEG:
        return "negative"
    return "none"


def _coverage_from_n(n) -> str:
    if not isinstance(n, (int, float)):
        return "low"
    return "high" if n >= 20 else ("medium" if n >= 5 else "low")


def _corroboration_from_cross_consortium(cross_consortium_class) -> str:
    """CERTAINTY_MODEL + worked example: dependency corroboration is Broad↔Sanger cross-consortium
    replication — VERDICT-DISJOINT (the cross-consortium-dependency card fires NO resolver rung). The
    CRISPR↔RNAi concordance is deliberately NOT used here: it RESOLVES the verdict
    (concordant_dependent / discordant), so reusing it as corroboration would count one signal as both
    strength and certainty (the disjointness rule). Two independent consortia agreeing (dependent OR
    non-dependent) is corroboration; disagreeing is low; a single consortium is `unmeasured` — never a
    fabricated `medium` (an absent comparator raises ignorance, it does not manufacture agreement)."""
    c = str(cross_consortium_class or "")
    if c in ("concordant_dependent", "concordant_non_dependent"):
        return "high"
    if c == "discordant":
        return "low"
    if c == "single_consortium_only":
        return "medium"
    return "unmeasured"   # data_unavailable / absent → no verdict-disjoint comparator this run


def _unknown_mass(cards) -> float:
    """CERTAINTY_MODEL: the fraction of the axis's DECISION-RELEVANT cards that came back
    data_unavailable / blind THIS run — a MEASURED coverage-gap (ignorance) term. This replaces the
    prior fixed level-lookup, which conflated measured-null with never-measured (a well-powered
    discordant call and a never-measured axis both landed at 0.7). Orthogonal to `corroboration`
    (disagreement): this says *we didn't look*, corroboration says *we looked and lines disagree*.
    A card absent from the resolved set OR flagged `_missing` OR whose PRIMARY class is
    data_unavailable counts as blind."""
    by_id = {c["card_id"]: c for c in (cards or []) if isinstance(c, dict) and "card_id" in c}
    n = len(_DECISION_RELEVANT_CARDS)
    blind = 0
    for cid in _DECISION_RELEVANT_CARDS:
        c = by_id.get(cid)
        if c is None or c.get("_missing") or _summary_is_unavailable(c.get("summary") or {}):
            blind += 1
    return round(blind / n, 3)


# The VERDICT-DISJOINT card(s) this axis reads for certainty `corroboration` (via
# _corroboration_from_cross_consortium, which reads cross_consortium_class from cross-consortium-dependency).
# DECLARED here so it can be cross-checked against target-contracts vocabularies/certainty_corroboration.yaml
# (manifest authoritative): test_certainty_corroboration_matches_manifest asserts this set
# equals corroboration_cards("dependency"), so the manifest and the Python source can never silently drift.
_CERTAINTY_CORROBORATION_CARDS = frozenset({"cross-consortium-dependency"})


def _dependency_strength_certainty(cards, verdict, cross_consortium_class) -> dict:
    """(strength, certainty{coverage, corroboration, weakest-link level, unknown_mass}) for the
    dependency axis (CERTAINTY_MODEL dependency reference axis). coverage = n_cell_lines power;
    corroboration = VERDICT-DISJOINT Broad↔Sanger cross-consortium; unknown_mass = coverage-gap
    fraction. `level` = weakest-link over the MEASURED certainty components (an `unmeasured`
    corroboration drops out of the min rather than forcing low — absence is carried in unknown_mass,
    not punished as disagreement)."""
    n = get_card_field(cards, "pan-cancer-crispr-dependency-distribution", "n_cell_lines_evaluated")
    frac = get_card_field(cards, "pan-cancer-crispr-dependency-distribution", "fraction_strongly_dependent")
    coverage = _coverage_from_n(n)
    corroboration = _corroboration_from_cross_consortium(cross_consortium_class)
    components = [coverage] + ([corroboration] if corroboration != "unmeasured" else [])
    level = min(components, key=lambda c: _ORD[c])   # weakest-link over MEASURED components
    if verdict in _DEP_INSUFF:
        level = "low"
    return {
        "strength": _dependency_strength(verdict),
        "certainty": {"level": level, "coverage": coverage, "corroboration": corroboration,
                      "unknown_mass": _unknown_mass(cards)},
        "provenance": {"n_cell_lines_evaluated": n, "fraction_strongly_dependent": frac,
                       "cross_consortium_class": cross_consortium_class},
        "_model_ref": "CERTAINTY_MODEL.md#dependency",
    }


def _strength_certainty(cards, fired=None, verdict_pair=None):
    """Fan-out SIDECAR hook (CERTAINTY_MODEL): the per-axis (strength, certainty) object the
    composed target-profile fan-out captures, keyed by sub-skill short. Its signature mirrors
    `_synthesis_facet` (cards, fired, verdict_pair) so the generic certainty loader calls it uniformly;
    it reuses `_dependency_strength_certainty` (single source), so `_headline` and the sidecar cannot
    diverge. VERDICT-INERT: emitted beside the verdict, never in sub_verdicts / GateVerdict / a shared
    carrier, and it never enters `fired` or the resolver. Standalone-callable (derives the verdict from
    `fired` when no verdict_pair is threaded)."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    cross_consortium_class = get_card_field(cards, "cross-consortium-dependency", "cross_consortium_class")
    return _dependency_strength_certainty(cards, v, cross_consortium_class)


# ── Phase 3 (2026-08-19): DETERMINISTIC indication-lineage reduction — the SEL-honesty fix. ──────────
# The pooled dependency_verdict is TARGET-GRAIN / pan-cancer: lineage-selectivity fires `lineage_selective`
# if ANY lineage is enriched (for KRAS/COADREAD the top lineage is Pancreas, not the queried Bowel), so a
# user asking an INDICATION question gets a pan-cancer answer with the indication-match left to the LLM.
# This reduces the ALREADY-EMITTED per_lineage_stats / enriched_lineages to the QUERIED indication's DepMap
# lineage (crosswalk) and emits `dependency_verdict_by_scope` {pan_cancer, indication, subtype}. ADDITIVE +
# verdict-INERT: the pooled dependency_verdict is byte-stable (frozen by the KRAS/COADREAD replay guard);
# no resolver rung is touched.
_LINEAGE_DEPENDENCY_CUT = -0.5     # DepMap-standard Chronos threshold for "dependent" (median)
_LINEAGE_UNDERPOWER_FLOOR = 5      # mirrors the card's min_cell_lines_in_lineage
# DepMap coarse lineages SHARED by >1 iDAS indication → a coarse-lineage read confounds them; the true
# split needs depmap_oncotree_lineage (per-oncotree-sublineage stats — analysis-methods follow-on). We
# reduce at coarse lineage and TAG the caveat rather than pretend precision we don't have.
_SHARED_DEPMAP_LINEAGES = {"Lung", "Esophagus/Stomach"}   # SCLC/NSCLC ; STAD/ESCA


@functools.lru_cache(maxsize=1)
def _indication_lineage_map() -> dict:
    """canonical_code -> {depmap_lineage, depmap_oncotree_lineage, depmap_oncotree_codes} from
    target-contracts' indication_crosswalk.yaml. Read-only; {} if unavailable (the by-scope layer then
    degrades to a typed-empty indication rung — honest, never a crash). `depmap_oncotree_codes` is the
    OncotreeCode SET present ONLY for shared-lineage indications (STAD/ESCA, NSCLC/SCLC) — it drives the
    sublineage-aware reduction that de-confounds the shared coarse DepMap lineage; absent otherwise."""
    try:
        import yaml
        path = DEFAULT_CONTRACTS_REPO / "vocabularies" / "indication_crosswalk.yaml"
        data = yaml.safe_load(path.read_text()) or {}
        return {e["canonical_code"]: {"depmap_lineage": e.get("depmap_lineage"),
                                      "depmap_oncotree_lineage": e.get("depmap_oncotree_lineage"),
                                      "depmap_oncotree_codes": e.get("depmap_oncotree_codes")}
                for e in data.get("indications", []) if e.get("canonical_code")}
    except Exception:   # noqa: BLE001 — additive/verdict-inert; absence must not break the spine
        return {}


def _sublineage_read(cards, codes: list) -> dict | None:
    """Aggregate the ADDITIVE per_oncotree_code_stats over an indication's OncotreeCode SET —
    the de-confounded read for a SHARED coarse lineage (e.g. STAD = STAD+TSTAD+… separate from ESCA;
    NSCLC = LUAD+LUSC+… separate from SCLC). Returns {n, median_chronos, fraction_strongly_dependent,
    matched_codes, per_code} or None when the field / matching codes are unavailable (→ caller falls back
    to the coarse-lineage path). median is n-WEIGHTED across codes (per-code raw scores aren't retained
    in the summary) — an approximation adequate for the indication-scope classification; the verdict is
    pan-cancer and untouched."""
    rows = get_card_field(cards, "dependency-lineage-selectivity", "per_oncotree_code_stats")
    if not isinstance(rows, list) or not rows or not codes:
        return None
    codeset = {str(c) for c in codes}
    matched = [r for r in rows if isinstance(r, dict) and str(r.get("oncotree_code")) in codeset]
    matched = [r for r in matched if isinstance(r.get("n"), (int, float)) and r.get("median_chronos") is not None]
    if not matched:
        return None
    n_total = sum(r["n"] for r in matched)
    if n_total <= 0:
        return None
    wmed = sum(r["median_chronos"] * r["n"] for r in matched) / n_total
    wfrac = sum((r.get("fraction_strongly_dependent") or 0.0) * r["n"] for r in matched) / n_total
    return {
        "n": int(n_total),
        "median_chronos": round(wmed, 4),
        "fraction_strongly_dependent": round(wfrac, 4),
        "matched_codes": sorted(r["oncotree_code"] for r in matched),
        "per_code": [{"oncotree_code": r["oncotree_code"], "n": r["n"],
                      "median_chronos": r["median_chronos"]} for r in matched],
    }


def _infer_indication(cards) -> str | None:
    """The queried indication is not threaded into headline_fn (signature is (cards, fired, verdict_pair)),
    but several indication-aware cards echo it (abundance-dependency, recommended-models). Take the first
    non-null `indication` across card summaries; None → the indication rung is typed-empty."""
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        ind = (c.get("summary") or {}).get("indication")
        if isinstance(ind, str) and ind.strip():
            return ind.strip().upper()
    return None


def _indication_lineage_read(cards, indication) -> dict:
    """Reduce the pan-cancer lineage card to the QUERIED indication's DepMap lineage. Reads the
    already-emitted per_lineage_stats + enriched_lineages (guarding the fixture's non-list placeholder)
    + the crosswalk. Returns a typed read {scope:'indication', class, ...}; class ∈
    {selective_in_indication, dependent_not_enriched, not_dependent_in_indication, underpowered,
    not_in_panel, data_unavailable}. NEVER raises; NEVER touches dependency_verdict."""
    read = {"scope": "indication", "indication": indication, "depmap_lineage": None,
            "class": "data_unavailable", "is_enriched": False,
            "median_chronos": None, "n": None, "q_value": None, "effect_size": None,
            "shared_lineage_caveat": False, "_note": None}
    if not indication:
        read["_note"] = "no indication in query (target-grain run) — indication rung not computed"
        return read
    xw = _indication_lineage_map().get(indication) or {}
    lineage = xw.get("depmap_lineage")
    read["depmap_lineage"] = lineage
    if not lineage:
        read["_note"] = f"no DepMap lineage crosswalk for indication {indication}"
        return read
    read["shared_lineage_caveat"] = lineage in _SHARED_DEPMAP_LINEAGES

    # SUBLINEAGE de-confounding (Phase 3b): when the indication maps to a SHARED coarse lineage (STAD/ESCA
    # → Esophagus/Stomach; NSCLC/SCLC → Lung) AND the crosswalk supplies its OncotreeCode set, reduce at
    # the SUBLINEAGE grain (per_oncotree_code_stats aggregated over the code-set) instead of the confounded
    # coarse lineage — this RESOLVES the shared_lineage_caveat rather than merely flagging it. Falls back to
    # the coarse-lineage path when the field or code-set is unavailable (e.g. the offline fixture).
    codes = xw.get("depmap_oncotree_codes")
    if read["shared_lineage_caveat"] and codes:
        sub = _sublineage_read(cards, codes)
        if sub is not None:
            read["shared_lineage_caveat"] = False   # resolved at sublineage grain
            read["sublineage_resolved"] = True
            read["matched_oncotree_codes"] = sub["matched_codes"]
            read["per_oncotree_code"] = sub["per_code"]
            n, med = sub["n"], sub["median_chronos"]
            read.update(median_chronos=med, n=n)
            if n < _LINEAGE_UNDERPOWER_FLOOR:
                read.update(**{"class": "underpowered",
                               "_note": f"{indication} sublineage {sub['matched_codes']} n={n} (< floor)"})
            elif med <= _LINEAGE_DEPENDENCY_CUT:
                read.update(**{"class": "dependent_not_enriched",
                               "_note": (f"{indication} sublineage-resolved (codes {sub['matched_codes']}, "
                                         f"n={n}): n-weighted median {med:.2f} — dependent, de-confounded "
                                         f"from the shared {lineage} lineage")})
            else:
                read.update(**{"class": "not_dependent_in_indication",
                               "_note": (f"{indication} sublineage-resolved (codes {sub['matched_codes']}, "
                                         f"n={n}): n-weighted median {med:.2f} above the dependency cut")})
            return read

    def _row(rows, key):
        if not isinstance(rows, list):
            return None
        return next((r for r in rows if isinstance(r, dict) and r.get(key) == lineage), None)

    enriched = _row(get_card_field(cards, "dependency-lineage-selectivity", "enriched_lineages"), "lineage")
    per_lineage = _row(get_card_field(cards, "dependency-lineage-selectivity", "per_lineage_stats"), "lineage")

    # 1) queried lineage is a SIGNIFICANT enrichment hit → the dependency IS selective to this indication
    if enriched is not None:
        read.update(**{"class": "selective_in_indication", "is_enriched": True,
                       "median_chronos": enriched.get("median_chronos"), "n": enriched.get("n"),
                       "q_value": enriched.get("q_value"), "effect_size": enriched.get("effect_size")})
        read["_note"] = f"{lineage} is a significant lineage-selective hit for this dependency"
        return read
    # 2) present in the full per-lineage table but not an enrichment hit → classify by median depth
    if per_lineage is not None:
        n, med = per_lineage.get("n"), per_lineage.get("median_chronos")
        read.update(median_chronos=med, n=n)
        if isinstance(n, (int, float)) and n < _LINEAGE_UNDERPOWER_FLOOR:
            read.update(**{"class": "underpowered", "_note": f"{lineage} has n={n} (< floor)"})
        elif isinstance(med, (int, float)) and med <= _LINEAGE_DEPENDENCY_CUT:
            read.update(**{"class": "dependent_not_enriched",
                           "_note": f"{lineage} is dependent (median {med:.2f}) but not lineage-selectively so"})
        else:
            read.update(**{"class": "not_dependent_in_indication",
                           "_note": f"{lineage}: median Chronos {med} above the dependency cut"})
        return read
    # 3) enriched_lineages had no hit AND the full table is unavailable (fixture placeholder) or the
    #    lineage is genuinely absent from the panel — distinguish only when the table is a real list.
    pls = get_card_field(cards, "dependency-lineage-selectivity", "per_lineage_stats")
    if isinstance(pls, list):
        read.update(**{"class": "not_in_panel", "_note": f"{lineage} not among screened lineages"})
    else:
        read["_note"] = (f"{lineage} not an enrichment hit; full per-lineage table unavailable this run "
                         "(cannot distinguish not-dependent from absent)")
    return read


def _dependency_verdict_by_scope(cards, verdict_pair) -> dict:
    """The scope-parameterized read {pan_cancer, indication, subtype}. ADDITIVE sibling of the pooled
    dependency_verdict (which stays the pan-cancer headline). subtype is a typed-empty placeholder here
    (Phase 4 populates it from the --subtypes panorama, which is resolved on a separate dispatcher path)."""
    v, drv = verdict_pair or ("insufficient", None)
    return {
        "pan_cancer": {"verdict": v, "driving_rule_id": drv,
                       "_note": "pooled target-grain verdict (the byte-stable dependency_verdict)"},
        "indication": _indication_lineage_read(cards, _infer_indication(cards)),
        "subtype": {"scope": "subtype", "class": "not_scoped_this_run",
                    "_note": "pass --subtypes to resolve the molecular-subgroup verdict; when passed, the "
                             "authoritative power-gated subtype verdict is emitted at "
                             "headline.subtype_dependency_panorama.subtype_verdict (resolved after this "
                             "placeholder — see _subtype_scope_verdict)"},
    }


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# functional-requirement's declaration for the shared headline_core builder: the DEP/SEL/COND/CHEM claim
# axes (decision-critical axis = DEP, the genetic-dependency call), the dependency verdict vocabulary →
# human phrase, and the authoritative CERTAINTY_MODEL sidecar (strength_certainty) as the confidence
# source. Verdict-INERT — a one-way projection over the already-computed headline (dependency_verdict
# stays byte-stable, frozen by the KRAS/COADREAD replay guard).

# The dependency.resolver verdict vocabulary → human phrase. These verdicts EXHAUSTIVELY partition into
# _DEPENDENCY_CALL_VERDICTS (a real call) + _NON_CALL_VERDICTS (see the Guard-A note above); a curated
# phrase for each, with a prettify fallback for any future addition.
_DEPENDENCY_VERDICT_PHRASE = {
    # positive dependency calls
    "concordant_dependent":                    "Genetic dependency (CRISPR + RNAi concordant)",
    "broadly_dependent":                       "Broadly dependent",
    "lineage_selective":                       "Lineage-selective dependency",
    "selective_dependent":                     "Selective genetic dependency",
    "partner_conditional_dependent":           "Partner-conditional (synthetic-lethal) dependency",
    "chemical_genetic_confirmed_dependent":    "Dependency, chemically confirmed",
    # pan-essential — a real dependency, but a broad-toxicity liability (low selective window)
    "pan_essential_killer":                    "Pan-essential (broad-toxicity liability)",
    # measured negatives
    "non_dependent":                           "Not a genetic dependency",
    "non_dependent_paralog_buffered":          "Not dependent (paralog-buffered)",
    "discordant":                              "Discordant dependency evidence",
    # coverage gaps
    "insufficient":                            "Insufficient evidence",
    "insufficient_underpowered":               "Insufficient evidence (underpowered)",
    "insufficient_underpowered_pan_essential": "Insufficient / underpowered (pan-essential)",
}


def _dependency_verdict_polarity(v) -> str:
    """The skill's OWN reading of the dependency verdict (colours the hero badge; never a gate). Reuses
    the existing _DEP_*_POS / _DEP_NEG token sets so the polarity can't drift from the strength helper: a
    positive/selective dependency call = positive; a measured-negative (non_dependent / paralog-buffered /
    discordant) = negative; else neutral (insufficient*, and pan_essential_killer — a dependency but
    broad-nonselective, so neither a clean actionable positive nor a measured negative)."""
    if v in _DEP_STRONG_POS or v in _DEP_MOD_POS:
        return "positive"
    if v in _DEP_NEG:
        return "negative"
    return "neutral"


_DEPENDENCY_HEADLINE_SPEC = HeadlineSpec(
    gate="dependency",
    axis_labels={"DEP": "genetic dependency", "SEL": "context-selectivity",
                 "COND": "conditional / synthetic-lethal", "CHEM": "chemical-genetic confirmation"},
    axis_keys=("DEP", "SEL", "COND", "CHEM"),
    critical_axes=("DEP",),   # DEP (is loss of the target lethal?) is THE decision-critical axis
    verdict_label=lambda v: _DEPENDENCY_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    # No cross-cutting flag beyond the claim_vector conflicts + key_signals caveat: the sharpest FR
    # tensions (pan-essential broad-tox, RNAi non-corroboration of CRISPR, PRISM off-target) are already
    # per-axis `conflict`s on the claim_vector, which headline_core.rank_tension ranks. So tension_extra=None.
    tension_extra=None,
)

# The strength_certainty (CERTAINTY_MODEL) sidecar grades certainty.level low/medium/high; the headline
# confidence vocabulary is weak/moderate/strong/insufficient. Map so the AUTHORITATIVE sidecar wins in
# build_headline (derive_confidence only honours a level already in the CONFIDENCE_ORD vocab).
_CERTAINTY_LEVEL_TO_CONFIDENCE = {"high": "strong", "medium": "moderate", "low": "weak"}


def _headline_certainty(headline: dict):
    """Adapt FR's strength_certainty sidecar into the headline confidence vocabulary so it is the
    authoritative confidence (per docs/HEADLINE_CONTRACT.md: a CERTAINTY_MODEL sidecar WINS over the
    derived weakest-link). Returns {level} in the CONFIDENCE_ORD vocab, or None (→ build_headline derives)."""
    sc = headline.get("strength_certainty")
    lvl = ((sc or {}).get("certainty") or {}).get("level") if isinstance(sc, dict) else None
    mapped = _CERTAINTY_LEVEL_TO_CONFIDENCE.get(lvl)
    return {"level": mapped} if mapped else None


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed dependency headline. Reads the
    dependency_verdict + the verdict-inert claim_vector / key_signals; FR's strength_certainty sidecar is
    the authoritative confidence. Never moves the spine."""
    v = headline.get("dependency_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_DEPENDENCY_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_dependency_verdict_polarity(v),
                          certainty=_headline_certainty(headline))


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    predictability_class = get_card_field(cards, "dependency-predictability", "predictability_class")
    cross_consortium_class = get_card_field(cards, "cross-consortium-dependency", "cross_consortium_class")
    coessential_module_class = get_card_field(cards, "coessential-module", "coessential_module_class")
    confidence = _dependency_confidence_note(v, predictability_class, cross_consortium_class,
                                             coessential_module_class)
    hl = {
        "dependency_verdict":       v,
        "driving_rule_id":          drv,
        # (strength, certainty) — CERTAINTY_MODEL #dependency reference axis. ADDITIVE + verdict-inert.
        # corroboration is Broad↔Sanger cross-consortium (verdict-DISJOINT), NOT CRISPR↔RNAi concordance
        # (which resolves the verdict). See _dependency_strength_certainty.
        "strength_certainty":       _dependency_strength_certainty(cards, v, cross_consortium_class),
        "crispr_call":              get_card_field(cards, "pan-cancer-crispr-dependency-distribution",
                                          "dependency_class"),
        "rnai_call":                get_card_field(cards, "pan-cancer-rnai-dependency-distribution",
                                          "rnai_dependency_class"),   # 2026-08-08 fix: card emits rnai_dependency_class (prefixed), not dependency_class → was silently None

        "concordance_call":         get_card_field(cards, "crispr-rnai-dependency-concordance",
                                          "concordance_class"),
        "lineage_selectivity":      get_card_field(cards, "dependency-lineage-selectivity",
                                          "enrichment_class"),   # 2026-08-08 fix: card emits enrichment_class (the rule keys on it too); lineage_selectivity_class never existed → was silently None

        "paralog_buffering_class":  get_card_field(cards, "paralog-buffering",
                                          "paralog_buffering_class"),
        "strongest_paralog_symbol": get_card_field(cards, "paralog-buffering",
                                          "strongest_paralog_symbol"),
        # Gate-C: predictability CONFIDENCE annotation over the verdict —
        # additive; the verdict + driving_rule_id above are untouched.
        "predictability_class":     predictability_class,
        "pred_dominant_feature_class": get_card_field(cards, "dependency-predictability",
                                            "pred_dominant_feature_class"),
        # Independent-consortium corroboration (Broad Achilles vs Sanger Project Score), 2026-08-12.
        # Folded into dependency_confidence above (concordant_dependent RAISES confidence; discordant
        # adds a caveat) AND surfaced here so the narrative can cite it. VERDICT-INERT — the card
        # fires no resolver rung; it only tunes gate-C confidence (was computed but consumed by nothing).
        "cross_consortium_class":   cross_consortium_class,
        # Co-essential-module coherence (2026-08-19) — mechanism-anchoring CONFIDENCE facet (enrichment
        # review #1; was orphaned). Folded into dependency_confidence above (in_coherent_module RAISES;
        # isolated adds a caveat) AND surfaced here for the narrative. VERDICT-INERT — no resolver rung.
        "coessential_module_class": coessential_module_class,
        "n_coessential_partners":   get_card_field(cards, "coessential-module", "n_strong_partners"),
        "strongest_coessential_partner": get_card_field(cards, "coessential-module", "strongest_partner_symbol"),
        "dependency_confidence":    confidence["confidence"],
        "dependency_confidence_note": confidence["note"],
        # Q4 patient↔model correspondence — model-backed-dependency corroboration (render facet):
        "model_correspondence_class": get_card_field(cards, "recommended-models", "correspondence_class"),
        "n_positive_models_in_lineage": get_card_field(cards, "recommended-models", "n_positive_models_in_lineage"),
        # GENOTYPE-matched patient↔model facet (2026-08-19) — complements the expression-similarity
        # model_correspondence above with genotype IDENTITY (does an available model carry THIS target's
        # event?). Render facet; verdict-inert (event-correspondence rules are genomic, not dependency-*).
        "event_correspondence_class": get_card_field(cards, "genomic-event-model-match", "event_correspondence_class"),
        # Q7 protein abundance → dependency (render facet, biomarker-assay comparison vs the RNA arm):
        "abundance_dependency_class": get_card_field(cards, "abundance-dependency", "abundance_dependency_class"),
        "protein_dependency_pearson_r": get_card_field(cards, "abundance-dependency", "protein_dependency_pearson_r"),
        # ── claim-vector inputs (2026-08-18) — the class fields the DEP/SEL/COND/CHEM claims key on,
        # read here via get_card_field so the headline-fields drift guard covers them (the reliability
        # numerics ride alongside). crispr_call/rnai_call/concordance_call/lineage_selectivity/
        # cross_consortium_class/predictability_class above already supply DEP+SEL; these add COND+CHEM.
        "partner_conditional_class": get_card_field(cards, "partner-conditional-dependency", "partner_stratification_class"),
        "n_partner_deficient":       get_card_field(cards, "partner-conditional-dependency", "n_partner_deficient"),
        "partner_stratification_q":  get_card_field(cards, "partner-conditional-dependency", "partner_stratification_mannwhitney_q"),
        "prism_concordance_class":   get_card_field(cards, "prism-crispr-concordance", "crispr_prism_concordance_class"),
        "n_compounds_evaluated":     get_card_field(cards, "prism-crispr-concordance", "n_compounds_evaluated"),
        "n_lineages_evaluated":      get_card_field(cards, "dependency-lineage-selectivity", "n_lineages_evaluated"),
    }
    # Additive, verdict-INERT (2026-08-18): the modality-blind claim vector (DEP/SEL/COND/CHEM
    # signal×reliability) + a brief cited key-signals read — the WITHIN-lens evidence integration this
    # subskill owns, built on the SHARED claim_vector_core contract (dependency is the second concrete
    # after presence). Both are projections over the headline just built; they NEVER touch the
    # dependency_verdict spine (byte-stable, frozen by the KRAS/COADREAD offline replay guard). See
    # _skills_common/dependency_claims.py + claim_vector_core.py.
    hl["claim_vector"] = dependency_claim_vector(hl, cards)
    hl["key_signals"] = dependency_key_signals(hl, cards)
    # Phase 3 (2026-08-19): scope-parameterized read {pan_cancer, indication, subtype}. ADDITIVE +
    # verdict-INERT — the pooled dependency_verdict above is untouched (byte-stable, KRAS/COADREAD replay
    # guard). Makes the SEL claim honest about the QUERIED indication's lineage (vs "selective to SOME
    # lineage"); the pooled call remains the pan_cancer rung. See _dependency_verdict_by_scope.
    hl["dependency_verdict_by_scope"] = _dependency_verdict_by_scope(cards, verdict_pair)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message, as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built; best-effort (a formatting/read fault must NEVER discard the
    # dependency spine already fully built in `hl`, matching tumor-presence's degrade-on-exception discipline).
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    return hl


# ─── Cross-lens facet (consumed by the composed target-profile synthesis) ─────────────────────────
# The uniform opt-in the target-profile fan-out looks for via getattr(module, "_synthesis_facet")
# (mirrors tumor-presence). It reuses `_headline` (single source of truth) and returns the
# reconciliation-relevant subset — for functional-requirement the dependency verdict + the modality-
# blind claim vector SIGNAL decomposition (DEP/SEL/COND/CHEM) + the brief cited key-signals read, plus
# the confidence annotations FR separates from its verdict (predictability / cross-consortium) as
# narrative context. It deliberately does NOT carry the per-axis (strength, certainty) object — that is
# the SEPARATE `certainty_by_axis` sidecar (CERTAINTY_MODEL); this facet is the SIGNAL half, the
# sidecar is the certainty half. VERDICT-INERT: the fan-out treats an absent facet
# as no-facet; nothing here enters `fired` or the resolver.
_SYNTHESIS_FACET_KEYS = (
    "dependency_verdict", "driving_rule_id",
    "crispr_call", "rnai_call", "concordance_call",
    "lineage_selectivity", "paralog_buffering_class", "strongest_paralog_symbol",
    # conditional-SL + chemical-genetic confirmation (the COND / CHEM claim inputs)
    "partner_conditional_class", "prism_concordance_class",
    # confidence annotations FR separates from its verdict (narrative context; the numeric certainty
    # roll-up lives in certainty_by_axis, not here)
    "predictability_class", "cross_consortium_class", "coessential_module_class",
    "dependency_confidence", "dependency_confidence_note",
    # biomarker render facets (patient-selection context)
    "model_correspondence_class", "event_correspondence_class", "abundance_dependency_class",
    # the modality-blind claim vector SIGNAL decomposition + brief cited read (this subskill's
    # within-lens integration; the cross-lens layer reads the per-claim SIGNALS, not a certainty)
    "claim_vector", "key_signals",
    # scope-parameterized read (Phase 3) — pooled pan-cancer vs the QUERIED indication's lineage;
    # lets the composed synthesis cite the indication answer instead of the pan-cancer one. Verdict-inert.
    "dependency_verdict_by_scope",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
)


def _emit_skill_figures(decision, figures_root):
    """Skill-level graphics (opt-in --figures): the canonical headline hero (verdict · confidence · top
    tension). Additive / display-only; offline (reads only decision['headline']['headline_block'])."""
    return emit_headline_hero(decision, figures_root)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT dependency facet for the composed target-profile synthesis prompt.
    Reuses `_headline` (single source of truth) and returns the reconciliation-relevant subset.
    Never moves the verdict; safe to omit (fan-out treats absence as no-facet)."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic dependency facet from functional-requirement (a FACET, not a gate; the "
        "dependency verdict is owned by the shared resolver and is verdict-inert to this projection). "
        "claim_vector is the SIGNAL decomposition — DEP genetic-dependency / SEL context-selectivity / "
        "COND conditional-SL / CHEM chemical-genetic-confirmation, each a signal tier. The per-axis "
        "certainty roll-up is the separate certainty_by_axis sidecar, not this facet.")
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
        # Opt-in --synthesize narrates through the DEPENDENCY lens (its own tool schema + prompt,
        # foregrounding the selective-vs-pan-essential distinction). Two-slot / verdict-inert: the
        # dispatcher attaches decision['llm_synthesis'] as a sibling key AFTER the spine is composed,
        # so it is structurally impossible for the narration to alter dependency_verdict. Without this
        # synthesize_fn the dispatcher would fall back to the PRESENCE narrator (wrong lens).
        synthesize_fn=synthesize_dependency,
        # Opt-in --subtypes resolves the DESCRIPTIVE dependency-by-molecular-subgroup panorama
        # (subgroup-stratified-dependency; e.g. MSI_H vs MSS). Verdict-inert: its cards touch no
        # resolver rung, so the dependency verdict is byte-identical without --subtypes.
        subtype_panorama_fn=_resolve_dependency_subtype_panorama,
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
    ))
