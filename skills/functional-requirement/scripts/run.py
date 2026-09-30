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

import sys

from _skills_common import _summary_is_unavailable, get_card_field, resolve_cards
from _skills_common.claim_record import assemble_claim_record, magnitude_for_card
from _skills_common.dependency_claims import (
    DEPENDENCY_CLAIM_SPEC,
    dependency_claim_vector,
    dependency_key_signals,
)
from _skills_common.dependency_indication import _indication_lineage_read, _infer_indication
from _skills_common.dependency_question_table import dependency_question_table
from _skills_common.dispatcher import run_wired_skill
from _skills_common.evidence_salience import contract_threshold
from _skills_common.headline_core import HeadlineSpec, build_headline, build_synthesis_facet
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import FUNCTIONAL_REQUIREMENT as _FR_LENS
from _skills_common.resolver import resolve_or_raise
from _skills_common.skill_report import ROLE_GATING, build_skill_report
from _skills_common.subgroup_derivation import _SUBGROUP_N_FLOOR, make_value_classifier

SKILL_NAME = "functional-requirement"
SKILL_VERSION = "1.10.0"  # 1.10.0 (2026-09-30, PR-1b of epic SK#2210 / #1507 — the DEPENDENCY generalisation of the tumor-presence L2a vertical, replicating the safety seed PR-1a): the per-source observational (L2a) properties, which existed only IMPLICITLY inside the four claim signal blocks, are lifted into a NAMED typed map `claim_vector.source_properties` (dependency_claims.py `_SOURCE_PROPERTY_RECIPES_DEPENDENCY`, 6 entries: crispr_essentiality / rnai_essentiality / dependency_lineage_selectivity / partner_conditional_dependency / chemical_genetic_engagement / paralog_buffering), each carrying its L1 card_id, the resolved observational class, the RETAINED quantitative anchors ({field, value, scale} + ledger-declared semantic_role / interpretation_reach, #1525) and comparability metadata; and under --emit-envelope evidence_package.json gains the NAMED top-level sections source_properties (L2a) / integrated_properties (L2b crispr_rnai_essentiality_concordance) / local_composites (the 4 axes DEP/SEL/COND/CHEM), built by _evidence_sections(headline) and threaded through run_wired_skill(evidence_sections_fn=...). No `l3d` section yet — the dependency within-domain story object is Wave-2a (PR-2a). Unlike the safety seed, dependency emits NO `comparability.valence` marker (this is the DEFAULT/efficacy frame — a strong dependency is the signal sought, so a generic higher-is-stronger read is correct; minting `valence: efficacy` would be an ungoverned second token) and NO `interpretation` provenance object (all six classes are verbatim card reads, no skills-side disjunction to name). Contracts governance: contracts/vocabularies/property_catalog/dependency.yaml (6 L2a props); claim_axis.enum.yaml 1.1.0→1.2.0 (SEL/COND/CHEM + safety PAN_ESSENTIAL now cite dependency.*; DEP additionally cites dependency.crispr_essentiality + dependency.rnai_essentiality alongside its l2b family). ADDITIVE / VERDICT-INERT: no axis renamed, no new L2b family, no token minted; `source_properties` omitted byte-stably when no source resolves; carries no `signal` key and read by no rule/verdict/ladder, so dependency_verdict + the resolver goldens + the KRAS replay are byte-stable.   # 1.9.0 (2026-09-04): verdict-INERT surfacing — indication_scope_note (target-grain positive enriched outside the queried indication) + partial-paralog caveat on absence verdicts.   # 1.8.0 (2026-09-03): --literature lane + verdict-INERT signal enrichment (measurement_caveat, concordance_scope_note, PRISM DEP-quorum, paralog caveat, polarity_note).   # 1.7.0 (2026-08-28): migrate narrator to generic capsule-driven engine. Verdict-INERT.   # 1.6.0 (2026-08-27): tuned signals-first sub-group reader (dependency-vocab
#        value→tier map + paralog-buffering confidence-only). Verdict-INERT.
# 1.5.0 (2026-08-21): emit the existing per-question question_table into the headline
# 1.4.0 (2026-08-13): production review — offline recorded-fixture replay drift
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
    "dependency-lineage-selectivity",  # TARGET-GRAIN by design: enrichment_class
    # =lineage_selective fires if ANY lineage is enriched, NOT
    # necessarily the queried indication's lineage. So the
    # lineage_selective VERDICT means "selective to some
    # lineage", and the indication-MATCH is done in the LLM
    # synthesis layer (per-indication lookup over
    # per_lineage_stats), NOT the machine verdict (FR review,
    # 2026-08-13). A future indication-conditioned verdict would
    # be a grain change (needs a nomination-side decision).
    "paralog-buffering",  # COMPOUND-ONLY veto-suppressor: strong-paralog-buffering-
    # degrader-preferred moves the verdict ONLY via the
    # `when_all` rung (non-dependent-killer AND this) →
    # non_dependent_paralog_buffered. On any positive/pan-ess
    # call it is verdict-INERT and only sets modality_scope
    # (degrader-preferred). Not a standalone verdict input.
    "partner-conditional-dependency",  # (2026-08-09) — VERDICT-BEARING synthetic-
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
    "prism-crispr-concordance",  # chemical-genetic CONFIRMATION arm (gate C,
    # 2026-07-20). Its triangulated_target_engaged
    # class fires e7-triangulated-target-engaged-supportive, which
    # the dependency resolver now reads as
    # chemical_genetic_confirmed_dependent (a positive-only,
    # veto-safe confirmation). The card is ALSO in tractability-
    # small-molecule's CARDS ("a compound was found") — one
    # measurement routes many-to-many to gates; each gate's
    # resolver/snapshot reads only its own rule_ids.
    "cross-consortium-dependency",  # Project Score (2026-08-10) — gate-C CORROBORATION: does
    # Sanger Project Score AGREE with Broad Achilles on the
    # dependency? Two independent consortia agreeing > CRISPR×RNAi
    # (both Broad). ADDITIVE, verdict-inert (raises confidence;
    # feeds NO resolver rung).
    "dependency-predictability",  # Gate-C (2026-07-21) — META-evidence
    # ("how omics-predictable is this dependency, and by what?").
    # Composed so it RUNS; it feeds a CONFIDENCE ANNOTATION only
    # (dependency_confidence_note), NEVER the verdict/resolver.
    # predictability is about a dependency call, not a call itself.
    "expression-dependency-correlation",  # Gate-C biomarker facet (2026-07-22): "expression
    # predicts dependency" (patient-selection). Was ORPHANED —
    # present in target-profile's render maps (title/role/
    # reports_into) + has a live dispatcher, but was in NO
    # sub-skill CARDS, so correlation_class never computed +
    # rendered empty. Render-only facet (its expression-biomarker-*
    # rules feed NO resolver — verdict-inert), grouped with the
    # dependency stratification facets. Also added to
    # target-profile SUB_SKILL_CARDS[functional-requirement].
    "abundance-dependency",  # Q7 PROTEIN arm of expression-as-biomarker-of-dependency
    # (2026-07-22): "protein abundance predicts dependency".
    # Sibling of expression-dependency-correlation (RNA arm) —
    # composed alongside it so the biomarker facet can compare
    # RNA vs protein (preferred_assay). ADDITIVE render-only facet
    # (abundance-dependency-* rules feed NO resolver → dependency
    # verdict byte-stable). Biology axis; no modality facet.
    "recommended-models",  # Q4 patient↔model correspondence (2026-07-22). Routes to
    # Gate C as MODEL-BACKED-DEPENDENCY corroboration (its
    # master-plan Patient-pop/Q10 home was deleted). Its
    # recommended-models-* rules emit SM/degrader supportive on
    # well_modeled (a screenable, model-backed dependency basis);
    # ADDITIVE — feed NO resolver ladder → dependency verdict
    # byte-stable. Also in target-profile SUB_SKILL_CARDS.
    "genomic-event-model-match",  # GENOTYPE-matched patient↔model facet (cross-wire,
    # 2026-08-19). Complements recommended-models (expression-
    # similarity) with genotype IDENTITY: which DepMap models
    # carry the SAME functional event in the target as the
    # indication's tumors, and are those models dependent? Built
    # + homed in genomic-alteration-profile; cross-wired here for
    # a sharper patient-selection read. ADDITIVE, verdict-INERT —
    # its event-correspondence rules are genomic (NOT dependency-*),
    # so FR's dependency-rule filter drops them from the verdict.
    "organoid-crispr-dependency",  # Organoid-native Chronos facet (2026-08-18). The organoid
    # READING of the same screens (OrganoidGeneEffect.csv, 114
    # GI-dominated organoid models, normalized within-organoid).
    # Its organoid-{selective,broad}-dependency-supportive rules
    # emit SM/degrader SUPPORTIVE; pan-essential/rare/not-dependent
    # NEUTRAL; data_unavailable insufficient. ADDITIVE — feeds NO
    # resolver ladder → dependency verdict byte-stable (the small
    # GI-skewed cohort corroborates a positive dependency but is
    # NEVER a trusted independent veto; the pan-cancer card owns
    # the killer). Target-grain; indication accepted-not-consumed.
    "coessential-module",  # Co-essential-module CONFIDENCE facet (2026-08-19) — the
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

# Cross-stratum delta threshold, SINGLE-SOURCED from the card's own `thresholds:` block
# (subgroup-stratified-dependency → meaningful_subgroup_delta). Display-only flavor label, NOT a verdict.
# This read `0.10` under a comment claiming it mirrored the card while the card declared `0.3` — a 3x
# drift no test could see, because the only fixture exercising the label uses delta=0.5, above BOTH cuts.
# contract_threshold() is fail-soft to None (an isolated checkout with no contracts sibling), so the
# literal below is a DECLARED FALLBACK that must equal the card; test_subgroup_delta_single_source.py
# reds if the two ever diverge. Explicit `is None`, never `or`: a declared 0.0 is falsy.
_MEANINGFUL_SUBGROUP_DELTA_FALLBACK = 0.3
_CARD_MEANINGFUL_SUBGROUP_DELTA = contract_threshold("subgroup-stratified-dependency", "meaningful_subgroup_delta")
_MEANINGFUL_SUBGROUP_DELTA = (
    _MEANINGFUL_SUBGROUP_DELTA_FALLBACK if _CARD_MEANINGFUL_SUBGROUP_DELTA is None else _CARD_MEANINGFUL_SUBGROUP_DELTA
)
# Power floor SINGLE-SOURCED from _skills_common.subgroup_derivation._SUBGROUP_N_FLOOR (imported above):
# DepMap per-indication molecular strata below this are UNDERPOWERED and must never be read as a
# subtype-specific call. Was previously a duplicated literal here (silent-drift hazard) mirroring the card.
# subgroup-stratified-dependency per-stratum `class` → subtype-scope verdict term (Phase 4). A powered,
# MEASURED stratum yields a real call; everything else is inadmissible (underpowered / insufficient).
_SUBGROUP_CLASS_TO_VERDICT = {
    "strong_dependency": "dependent",
    "moderate_dependency": "moderately_dependent",
    "not_dependent": "not_dependent",
    "insufficient": "insufficient",
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
        powered = r.get("evidence_state") == "measured" and isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR
        by_stratum[stratum] = (
            _SUBGROUP_CLASS_TO_VERDICT.get(r.get("class"), "insufficient") if powered else "underpowered"
        )
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


def _resolve_dependency_subtype_panorama(target: str, indication: str | None, subtypes: list) -> dict:
    """DESCRIPTIVE dependency-by-subgroup panorama — resolve subgroup-stratified-dependency across
    the requested strata (e.g. MSI_H, MSS). Mirrors genomic-alteration's _resolve_subtype_panorama:
    the card is a PANORAMA dispatcher, so it needs subgroup_context.resolved_strata_ids threaded or
    it returns only a data-note (why it is NOT in the whole-cohort CARDS list).

    Returns the {cards, scope_subtypes, subtype_dependency_panorama} projection the dispatcher's
    subtype_panorama_fn hook expects. NO resolver rung is touched, so the dependency verdict spine
    is byte-stable whether or not --subtypes is passed. Reads the card's ACTUAL emitted field names
    (per_subgroup_metrics rows: stratum/class/evidence_state/median_chronos/subgroup_n;
    cross_subgroup_delta_dependency reducer)."""
    subgroup_context = {"resolved_strata_ids": list(subtypes), "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication, subgroup_context=subgroup_context)
    dep = next((c for c in sub_cards if c["card_id"] == "subgroup-stratified-dependency"), None)
    summary = (dep or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    # Only MEASURED strata are admissible for comparison (underpowered/absent are inadmissible —
    # the card's own discipline: DepMap per-subgroup cell-line n is frequently below the floor).
    measured = [r for r in per_subgroup if r.get("evidence_state") == "measured"]
    delta = summary.get("cross_subgroup_delta_dependency")

    # Compact pattern label mirroring the card's interpretation_hints (delta on median_chronos):
    # >= the card's meaningful_subgroup_delta with >=2 measured strata = subgroup-specific; below it with
    # >=2 = uniform; else n/a. The cut is named, never re-literalled here — a literal in this comment is
    # what let the 0.10-vs-0.3 drift read as intentional. The `>=2` is the card's min_subgroups_for_call
    # (verified equal, 2026-09-19). DISPLAY-ONLY flavor — NOT a verdict.
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
            "subtype_dependency_pattern": pattern,  # display-only flavor, NOT a verdict
            # Phase 4: the SUBTYPE-scope verdict (power-gated per-stratum dependency call). This is the
            # authoritative `subtype` rung of dependency_verdict_by_scope — it lives HERE (not in
            # _headline) because the dispatcher resolves the --subtypes panorama AFTER headline_fn and
            # merges this block into the headline. Verdict-inert to the pooled spine.
            "subtype_verdict": _subtype_scope_verdict(per_subgroup),
            "n_subgroups_with_data": summary.get("n_subgroups_with_data"),
            "max_subgroup_dependency": summary.get("max_subgroup_dependency"),
            "min_subgroup_dependency": summary.get("min_subgroup_dependency"),
            "cross_subgroup_delta_dependency": delta,
            "measured_strata": [r.get("stratum") for r in measured],
            # surface per-stratum class + power so an underpowered stratum is never over-read
            "per_stratum": [
                {
                    "stratum": r.get("stratum"),
                    "class": r.get("class"),
                    "evidence_state": r.get("evidence_state"),
                    "median_chronos": r.get("median_chronos"),
                    "subgroup_n": r.get("subgroup_n"),
                }
                for r in per_subgroup
            ],
            "_missing": bool(dep is None or dep.get("_missing")),
            "_missing_reason": (dep or {}).get("_missing_reason"),
        },
    }


# The verdicts that ARE a real dependency call (positive or veto) — the ones a predictability
# confidence note meaningfully sharpens. On insufficient/discordant/underpowered verdicts the
# note stays neutral (there is no call to be confident in).
_DEPENDENCY_CALL_VERDICTS = frozenset(
    {
        "concordant_dependent",
        "lineage_selective",
        "selective_dependent",
        "chemical_genetic_confirmed_dependent",
        "broadly_dependent",
        "non_dependent",
        "non_dependent_paralog_buffered",
        "pan_essential_killer",
        # partner_conditional_dependent IS a real dependency call (a partner-conditional
        # dependency that escapes a pooled non_dependent veto). It was added to dependency.resolver.yaml
        # but never here, so its predictability-confidence annotation was wrongly suppressed.
        "partner_conditional_dependent",
        # indication-conditioned calls (2026-09-19): the honest indication-grain forms. Each is a real
        # dependency call in the QUERIED lineage, so the predictability note meaningfully sharpens it.
        "lineage_selective_in_indication",
        "dependent_in_indication",
        "not_dependent_in_indication",
    }
)

# The complement: verdicts that are NOT a dependency call (predictability annotation stays neutral).
# Together with _DEPENDENCY_CALL_VERDICTS these must EXHAUSTIVELY PARTITION dependency.resolver.yaml's
# verdict enum — the Guard-A test (skills/tests/test_resolver_verdict_consumers.py) fails if the
# resolver grows a verdict that neither set classifies, so a new verdict can't silently fall through
# the "not a call" branch again.
_NON_CALL_VERDICTS = frozenset(
    {
        "discordant",
        "insufficient",
        "insufficient_underpowered",
        "insufficient_underpowered_pan_essential",
        # could-not-look in the queried indication (underpowered / not-in-panel / data-unavailable);
        # NOT a call, so the predictability note stays neutral (2026-09-19).
        "insufficient_underpowered_in_indication",
    }
)


# The NEGATIVE-polarity subset of _DEPENDENCY_CALL_VERDICTS: determinate calls that the target is
# NOT a dependency here. These are real calls (so they DO get a confidence annotation), but their
# annotation must be phrased — and corroborated — in the direction of the veto. Before 2026-09-12 the
# note text was polarity-blind, so a `non_dependent` verdict emitted a note BYTE-IDENTICAL to
# `concordant_dependent`'s ("the dependency sits in a coherent co-essential module", "independently
# corroborated across consortia") — affirming the very dependency the verdict denies.
_NEGATIVE_CALL_VERDICTS = frozenset({"non_dependent", "non_dependent_paralog_buffered", "not_dependent_in_indication"})


# Confidence ladder (low→high) for the cross-consortium corroboration lift below.
_CONFIDENCE_LADDER = ("unknown", "standard", "moderate", "high")


def _dependency_confidence_note(
    verdict: str,
    predictability_class: str | None,
    cross_consortium_class: str | None = None,
    coessential_module_class: str | None = None,
) -> dict:
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

    POLARITY (2026-09-12 fix). The note text and both corroboration arms are scored against the DIRECTION of the
    verdict, not against the word "dependent":
      - AGREEMENT (positive verdict × concordant_dependent, or negative verdict ×
        concordant_non_dependent) is corroboration → lifts a bare standard/unknown to moderate.
      - CONTRADICTION (either polarity crossed) is a CAVEAT and NEVER lifts. Previously a
        `non_dependent` verdict alongside `concordant_dependent` — a flat contradiction — was
        LIFTED and captioned "independently corroborated", and `concordant_non_dependent` (the
        strongest corroboration a veto can have) was not handled at all.
    The verdict itself is untouched either way; only `confidence` + `note` move.

    Returns {confidence, note} where confidence ∈ {high, moderate, standard, unknown}. Annotates only
    on an actual dependency call (_DEPENDENCY_CALL_VERDICTS); otherwise `standard` with no meta-claim."""
    if verdict not in _DEPENDENCY_CALL_VERDICTS:
        return {
            "confidence": "standard",
            "note": "Predictability annotation applies only to an actual dependency call.",
        }
    negative = verdict in _NEGATIVE_CALL_VERDICTS
    # What the call asserts, in words that survive both polarities.
    subject = "non-dependence call" if negative else "dependency"

    pc = predictability_class
    if pc == "own_omics_driven":
        conf = "high"
        note = (
            f"The {subject} is predictable from the target's own omics "
            "(biomarker-hypothesis-bearing) — higher confidence in the call."
        )
    elif pc == "context_or_driver_dependent":
        conf = "moderate"
        note = (
            f"The {subject} is omics-predictable, but from lineage/driver context rather "
            "than the target's own features — the biomarker is the context."
        )
    elif pc in ("weakly_predictable", "unpredictable"):
        conf = "standard"
        note = (
            f"The {subject} is not well explained by omics — the call rests on the genetic "
            "evidence itself; no omics biomarker handle (not a verdict downgrade)."
        )
    else:  # data_unavailable or absent
        conf = "unknown"
        note = "Predictability not computed for this target (E5 precompute coverage gap)."

    def _lift() -> None:
        nonlocal conf
        if _CONFIDENCE_LADDER.index(conf) < _CONFIDENCE_LADDER.index("moderate"):
            conf = "moderate"

    # Independent cross-consortium corroboration (Broad Achilles vs Sanger Project Score), scored
    # against the verdict's DIRECTION.
    agreeing_class = "concordant_non_dependent" if negative else "concordant_dependent"
    opposing_class = "concordant_dependent" if negative else "concordant_non_dependent"
    if cross_consortium_class == agreeing_class:
        _lift()  # independent-consortium replication is itself a confidence handle
        note += (
            " Independently corroborated across consortia — Broad Achilles + Sanger Project Score "
            f"agree on {'non-dependence' if negative else 'dependence'}."
        )
    elif cross_consortium_class == opposing_class:
        note += (
            " CAUTION: the two consortia agree with each other but AGAINST this verdict "
            f"(Broad Achilles + Sanger Project Score both read {'dependent' if negative else 'NOT dependent'} "
            "pan-cancer). A confidence caveat, not a verdict move — the resolver owns the verdict, and "
            "an indication-restricted call can legitimately diverge from a pan-cancer one."
        )
    elif cross_consortium_class == "discordant":
        note += (
            " CAUTION: an independent consortium (Sanger Project Score) does NOT corroborate "
            "the Broad call — a confidence caveat, not a veto."
        )
    elif cross_consortium_class == "single_consortium_only":
        # NOT corroborated (as distinct from NOT LOOKED AT below): the cross-consortium comparator WAS
        # assessed this run, but only one consortium (Broad Achilles) screened this gene, so no independent
        # CRISPR consortium was available to corroborate. Uncorroborated ≠ contradicted — a caveat, no lift,
        # no downgrade (the resolver owns the verdict).
        note += (
            " Single-consortium: only Broad Achilles screened this gene, so no independent CRISPR "
            "consortium (Sanger Project Score) was available to corroborate — uncorroborated, not "
            "contradicted. A confidence caveat, not a verdict move."
        )
    # `data_unavailable` / None stay SILENT by design: the cross-consortium comparator was NOT ASSESSED
    # this run (distinct from single_consortium_only above, where it WAS assessed and only one consortium
    # had data). Absence of an assessment is not evidence either way; pinned by
    # test_uncorroborated_vs_not_assessed_are_distinguished (data_unavailable/None byte-stable).

    # Co-essential-module coherence (mechanism-anchoring corroboration). Module coherence anchors a
    # POSITIVE dependency's mechanism; on a veto it is a tension (the gene is co-essential with a
    # coherent module elsewhere, yet not required here), so it caveats and never lifts.
    if coessential_module_class == "in_coherent_module":
        if negative:
            note += (
                " Tension: the gene DOES sit in a coherent co-essential module (complex/pathway "
                "partners co-essential across cell lines) yet is not required in this context — "
                "consistent with context-restricted non-dependence, but worth checking coverage."
            )
        else:
            _lift()  # a module-anchored dependency is itself a mechanism-credibility handle
            note += (
                " Module-anchored — the dependency sits in a coherent co-essential module "
                "(complex/pathway partners co-essential across cell lines)."
            )
    elif coessential_module_class == "isolated_dependency":
        if negative:
            note += (
                " The gene is not co-essential with a coherent module (isolated), which is "
                "consistent with the non-dependence call but is weak corroboration on its own."
            )
        else:
            note += (
                " Note: the dependency is NOT co-essential with a coherent module "
                "(isolated) — a mechanism-anchoring caveat, not a veto."
            )
    return {"confidence": conf, "note": note}


QUESTION = (
    "Is {target} a genetic dependency in {indication}, and how does "
    "the call hold up across CRISPR, RNAi, concordance, lineage-"
    "selectivity, and paralog-buffering views?"
)


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
_DEP_STRONG_POS = {
    "broadly_dependent",
    "concordant_dependent",
    "chemical_genetic_confirmed_dependent",
}
_DEP_MOD_POS = {
    "lineage_selective",
    "selective_dependent",
    "partner_conditional_dependent",
    # indication-conditioned positives (2026-09-19): moderate-tier dependency calls in the queried
    # lineage. In _DEP_MOD_POS they read moderate_positive strength / positive polarity / supports
    # direction; they are SUBTRACTED from _POSITIVE_POOLED_VERDICTS below (they are already
    # indication-grain, so the "pooled call may sit outside your indication" scope note must not fire).
    "lineage_selective_in_indication",
    "dependent_in_indication",
}
_DEP_NEG = {
    "non_dependent",
    "non_dependent_paralog_buffered",
    "discordant",
    # measured negative in the queried lineage (2026-09-19): a real negative call, so strength is
    # "negative" and it must not read as a strengthless coverage gap.
    "not_dependent_in_indication",
}
_DEP_INSUFF = {
    "insufficient",
    "insufficient_underpowered",
    "insufficient_underpowered_pan_essential",
    "insufficient_underpowered_in_indication",
    None,
}
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
        return "broad_nonselective"  # strong magnitude, low SELECTIVE value (routes to tox)
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
        # A single consortium supplies the PRIMARY dependency signal (which feeds strength/coverage),
        # but provides NO cross-consortium comparator — so the corroboration axis (which is ABOUT
        # independent-replication agreement) is `unmeasured`, never a fabricated `medium`. This matches
        # the docstring above and the sibling _dependency_confidence_note (single_consortium_only = an
        # uncorroborated caveat, never a confidence lift).
        return "unmeasured"
    return "unmeasured"  # data_unavailable / absent → no verdict-disjoint comparator this run


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
    level = min(components, key=lambda c: _ORD[c])  # weakest-link over MEASURED components
    if verdict in _DEP_INSUFF:
        level = "low"
    from _skills_common.signals_first import certainty_composite

    strength = _dependency_strength(verdict)
    return {
        "strength": strength,
        "certainty": {
            "level": level,
            "coverage": coverage,
            "corroboration": corroboration,
            "unknown_mass": _unknown_mass(cards),
        },
        # continuous portfolio-ranking primitive (verdict-inert; a NAMED projection, not canonical)
        "composite": certainty_composite(strength, level),
        "composite_basis": (
            "certainty-discounted dependency strength = peak signal tier × weakest-link "
            "certainty; a NAMED [0,1] portfolio-ranking projection, not a canonical verdict"
        ),
        "provenance": {
            "n_cell_lines_evaluated": n,
            "fraction_strongly_dependent": frac,
            "cross_consortium_class": cross_consortium_class,
        },
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


# ── RNAi loss-of-function distribution CORROBORATION (orthogonal-perturbation twin of the CRISPR
#    distribution read by _dependency_strength_certainty) ────────────────────────────────────────────
# The RNAi (DEMETER2) distribution independently characterises the LoF-dependency arm's MAGNITUDE and
# SHAPE — the modality twin of the CRISPR distribution fields _dependency_strength_certainty reads at
# :632-633. RNAi never carries a positive dependency call ON ITS OWN (seed/off-target-prone — the
# concordance card is the cross-check, see _measurement_caveat), so this is a CORROBORATION facet, not
# a verdict input: it says whether the RNAi arm's own distribution AGREES with a dependency signature,
# so a consumer keying on rnai_call (a single categorical) can also see WHY that class was assigned and
# how strong the orthogonal signal is. VERDICT-INERT: a render facet surfaced beside rnai_call; it fires
# no resolver rung and never enters `fired`. Reads the four distribution fields the CRISPR twin already
# consumes (fraction_strongly_dependent → :633, distribution_shape/pan_essential_score/selectivity_index
# read on the CRISPR card via skill_code/capsule/salience) — the pure modality asymmetry this closes.
#
# Thresholds mirror the RNAi card's own declared cuts (pan-cancer-rnai-dependency-distribution.card.yaml
# thresholds:): pan_essential_fraction_threshold 0.85, selective_fraction_min 0.05, selective_fraction_max
# 0.60. DEMETER2 strong-dependency cut is score ≤ -0.5, so rnai_fraction_strongly_dependent is the
# fraction of lines below that cut. The RNAi distribution_shape vocabulary matches the CRISPR one exactly
# (pan_essential / bimodal_selective / shifted_dependent / non_essential / unclassified).
_RNAI_PAN_ESSENTIAL_FRACTION_THRESHOLD = 0.85
_RNAI_SELECTIVE_FRACTION_MIN = 0.05
_RNAI_SELECTIVE_SHAPES = frozenset({"bimodal_selective", "shifted_dependent"})


def _rnai_lof_dependency_support(cards) -> dict:
    """VERDICT-INERT RNAi LoF-distribution corroboration facet (orthogonal-perturbation twin of the CRISPR
    distribution read by _dependency_strength_certainty). Reads the four RNAi distribution fields and
    classifies the RNAi arm's OWN dependency signature so it can corroborate (never carry) the call:

      rnai_pan_essential_signature   — shape pan_essential OR pan_essential_score ≥ 0.85: RNAi reads a
                                       broad/common-essential dependency (magnitude is strong; the
                                       non-selective TOXICITY downside is a SAFETY-axis concern, not a
                                       negation — mirrors _DEP_STRENGTH broad_nonselective).
      rnai_selective_dependency_signature — a bimodal_selective / shifted_dependent shape with a
                                       fraction_strongly_dependent above the selective floor: RNAi
                                       corroborates a SELECTIVE dependency (the KRAS/COADREAD shape).
      rnai_non_dependent_signature   — shape non_essential OR fraction below the selective floor: the
                                       RNAi arm reads no dependency.
      rnai_signature_unclassified    — the card ran but the shape is unclassified/ambiguous.
      unmeasured                     — the RNAi distribution card is absent/blind this run.

    `corroborates_dependency` is True for either dependency signature, False for non_dependent, None when
    unclassified/unmeasured (absence raises ignorance, it never manufactures agreement — mirrors
    _corroboration_from_cross_consortium). The four field values ride along (provenance + the numeric
    selectivity_index the narrator cites), so nothing is a bare unused read."""
    frac = get_card_field(cards, "pan-cancer-rnai-dependency-distribution", "rnai_fraction_strongly_dependent")
    shape = get_card_field(cards, "pan-cancer-rnai-dependency-distribution", "rnai_distribution_shape")
    selectivity_index = get_card_field(cards, "pan-cancer-rnai-dependency-distribution", "rnai_selectivity_index")
    pan_essential_score = get_card_field(cards, "pan-cancer-rnai-dependency-distribution", "rnai_pan_essential_score")

    frac_num = frac if isinstance(frac, (int, float)) and not isinstance(frac, bool) else None
    pan_num = (
        pan_essential_score
        if isinstance(pan_essential_score, (int, float)) and not isinstance(pan_essential_score, bool)
        else None
    )
    shape_s = str(shape) if isinstance(shape, str) else None

    # Blind run: no distribution shape AND no numeric magnitude to reason over.
    if shape_s in (None, "data_unavailable", "unclassified") and frac_num is None and pan_num is None:
        signature = "rnai_signature_unclassified" if shape_s == "unclassified" else "unmeasured"
        corroborates = None
    elif shape_s == "pan_essential" or (pan_num is not None and pan_num >= _RNAI_PAN_ESSENTIAL_FRACTION_THRESHOLD):
        signature, corroborates = "rnai_pan_essential_signature", True
    elif shape_s == "non_essential" or (frac_num is not None and frac_num < _RNAI_SELECTIVE_FRACTION_MIN):
        signature, corroborates = "rnai_non_dependent_signature", False
    elif shape_s in _RNAI_SELECTIVE_SHAPES:
        signature, corroborates = "rnai_selective_dependency_signature", True
    else:
        signature, corroborates = "rnai_signature_unclassified", None

    return {
        "signature": signature,
        "corroborates_dependency": corroborates,
        "rnai_fraction_strongly_dependent": frac,
        "rnai_distribution_shape": shape,
        "rnai_selectivity_index": selectivity_index,
        "rnai_pan_essential_score": pan_essential_score,
        "_basis": (
            "orthogonal RNAi/DEMETER2 LoF distribution — corroboration only (RNAi never carries a "
            "positive call alone); magnitude/shape read symmetrically with the CRISPR distribution"
        ),
    }


# ── FACTORED-RECORD SHADOW (M1) — the DEPENDENCY per-axis builder. VERDICT-INERT: surfaced by the
#    fan-out into decision.claim_record_shadow.dependency, consumed by NOTHING. Maps the dependency
#    verdict onto the record; reuses the reference _strength_certainty (guarded — it reads cards via
#    get_card_field which raises on an absent card). Mirrors the other axes' hook. NOTE: pan_essential
#    IS a genuine dependency (direction=supports, strong) — its non-selective TOXICITY downside is a
#    SAFETY-axis concern, not this finding's valence (finding ⊥ interpretation).
_DEP_OPEN_WORLD = {None}
_DEP_STRENGTH_TO_LEVEL = {
    "strong_positive": "strong",
    "moderate_positive": "moderate",
    "broad_nonselective": "strong",
    "negative": "moderate",
    "none": "none",
}


def _dep_availability(v) -> str:
    if v in _DEP_OPEN_WORLD:
        return "not_wired"  # no verdict at all → open-world
    if v in (
        "insufficient",
        "insufficient_underpowered",
        "insufficient_underpowered_pan_essential",
        "insufficient_underpowered_in_indication",
    ):
        return "insufficient"  # measured but underpowered
    if v in _DEP_NEG:
        return "measured_negative"  # measured non-dependence / discordant
    return "measured_positive"  # a measured dependency (incl. pan_essential_killer)


def _dep_direction(v) -> str:
    if v in _DEP_STRONG_POS or v in _DEP_MOD_POS or v == "pan_essential_killer":
        return "supports"  # a genuine functional requirement
    if v in _DEP_NEG:
        return "opposes"
    return "neutral"


def _dep_modality_scope(cards) -> "dict | None":
    """Wire the SM-vs-degrader discriminator into the composed modality_fit: a STRONGLY paralog-buffered
    target resists single-agent active-site SM inhibition (the paralog compensates) but is a strong
    complete-removal case → degrader-preferred (mirrors the intracellular-intrinsic rule
    strong-paralog-buffering-degrader-preferred). Previously paralog-buffering reached no modality channel
    (functional-requirement's _claim_record emitted no modality_scope). Only `strong` triggers it; degrader
    → favorable, small_molecule → conditional (weakened, not vetoed — an allosteric/degrader ligand may
    still hit the shared domain). VERDICT-INERT."""
    try:
        cls = get_card_field(cards, "paralog-buffering", "paralog_buffering_class")
    except KeyError:
        return None  # paralog-buffering card absent → silent (best-effort, verdict-inert)
    if cls == "strong":
        return {"_refinements": {"degrader": "favorable", "small_molecule": "conditional"}}
    return None


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    try:
        certainty = _strength_certainty(cards, fired=fired, verdict_pair=verdict_pair)["certainty"]
    except Exception:  # noqa: BLE001 — reference hook reads cards via get_card_field (raises if absent)
        certainty = {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}
    # magnitude converges to the crispr dependency ruler (key_evidence.interpretation) — value =
    # median_chronos_panel between the non-essential floor / pan-essential ceiling, distance to the -0.5
    # cut — so the factored record and the display gauge speak one vocabulary. level-only if the driving
    # crispr summary is absent (stripped fixture / un-measured).
    return assemble_claim_record(
        axis="dependency",
        state=(v or "insufficient"),
        direction=_dep_direction(v),
        availability=_dep_availability(v),
        magnitude=magnitude_for_card(
            cards,
            "pan-cancer-crispr-dependency-distribution",
            "crispr_lof_dependency",
            _DEP_STRENGTH_TO_LEVEL.get(_dependency_strength(v), "none"),
        ),
        modality_scope=_dep_modality_scope(cards),
        certainty=certainty,
        fired=fired,
        cards=cards,
    )


# ── Phase 3 (2026-08-19): DETERMINISTIC indication-lineage reduction — the SEL-honesty fix. ──────────
# The pooled dependency_verdict is TARGET-GRAIN / pan-cancer: lineage-selectivity fires `lineage_selective`
# if ANY lineage is enriched (for KRAS/COADREAD the top lineage is Pancreas, not the queried Bowel), so a
# user asking an INDICATION question gets a pan-cancer answer with the indication-match left to the LLM.
# This reduces the ALREADY-EMITTED per_lineage_stats / enriched_lineages to the QUERIED indication's DepMap
# lineage (crosswalk) and emits `dependency_verdict_by_scope` {pan_cancer, indication, subtype}.
#
# The reduction logic (Stage 5b, 2026-09-19) now lives in _skills_common.dependency_indication so the
# `dependency` card PREPROCESSOR can write `indication_dependency_class` onto the card in ALL THREE
# resolution paths (a skill-local home would be bypassed by the two composed paths). This by-scope block
# is the ADDITIVE headline sibling and REUSES the same functions (imported above) — one home for the
# classification. As of Stage 5b the class ALSO feeds four resolver rungs, so the pooled pan_cancer rung
# below is still byte-stable but an indication rung can now win on an indication-scoped run (it loses to
# concordant_dependent at priority 3 — the deliberate boundary; see dependency.resolver.yaml).


def _dependency_verdict_by_scope(cards, verdict_pair) -> dict:
    """The scope-parameterized read {pan_cancer, indication, subtype}. ADDITIVE sibling of the pooled
    dependency_verdict (which stays the pan-cancer headline). subtype is a typed-empty placeholder here
    (Phase 4 populates it from the --subtypes panorama, which is resolved on a separate dispatcher path)."""
    v, drv = verdict_pair or ("insufficient", None)
    return {
        "pan_cancer": {
            "verdict": v,
            "driving_rule_id": drv,
            # This slot carries the EMITTED headline dependency_verdict at whatever grain the run resolved.
            # It is NOT necessarily pooled/target-grain: since the Stage-5b preprocessor went live (skills
            # #1480), an indication-scoped run can resolve an INDICATION-grain token here (e.g.
            # lineage_selective_in_indication / not_dependent_in_indication when an indication rung wins),
            # and the value moved from the pre-Stage-5b pooled token — so the former
            # "pooled target-grain / byte-stable" label was inaccurate on both counts (issue #1833 Part B).
            "_note": "the emitted headline dependency_verdict, at whatever grain the run resolved "
            "(pooled/target-grain on a target-grain run; indication-grain when an indication rung wins)",
        },
        "indication": _indication_lineage_read(cards, _infer_indication(cards)),
        "subtype": {
            "scope": "subtype",
            "class": "not_scoped_this_run",
            "_note": "pass --subtypes to resolve the molecular-subgroup verdict; when passed, the "
            "authoritative power-gated subtype verdict is emitted at "
            "headline.subtype_dependency_panorama.subtype_verdict (resolved after this "
            "placeholder — see _subtype_scope_verdict)",
        },
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
    "concordant_dependent": "Genetic dependency (CRISPR + RNAi concordant)",
    "broadly_dependent": "Broadly dependent",
    "lineage_selective": "Lineage-selective dependency",
    "selective_dependent": "Selective genetic dependency",
    "partner_conditional_dependent": "Partner-conditional (synthetic-lethal) dependency",
    "chemical_genetic_confirmed_dependent": "Dependency, chemically confirmed",
    # indication-conditioned calls — the honest indication-grain forms (2026-09-19)
    "lineage_selective_in_indication": "Lineage-selective dependency in this indication",
    "dependent_in_indication": "Genetic dependency in this indication",
    # pan-essential — a real dependency, but a broad-toxicity liability (low selective window)
    "pan_essential_killer": "Pan-essential (broad-toxicity liability)",
    # measured negatives
    "non_dependent": "Not a genetic dependency",
    "non_dependent_paralog_buffered": "Not dependent (paralog-buffered)",
    "not_dependent_in_indication": "Not a genetic dependency in this indication",
    "discordant": "Discordant dependency evidence",
    # coverage gaps
    "insufficient": "Insufficient evidence",
    "insufficient_underpowered": "Insufficient evidence (underpowered)",
    "insufficient_underpowered_pan_essential": "Insufficient / underpowered (pan-essential)",
    "insufficient_underpowered_in_indication": "Insufficient evidence in this indication (underpowered)",
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
    axis_labels={
        "DEP": "genetic dependency",
        "SEL": "context-selectivity",
        "COND": "conditional / synthetic-lethal",
        "CHEM": "chemical-genetic confirmation",
    },
    axis_keys=("DEP", "SEL", "COND", "CHEM"),
    critical_axes=("DEP",),  # DEP (is loss of the target lethal?) is THE decision-critical axis
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
    return build_headline(
        headline,
        headline.get("claim_vector"),
        headline.get("key_signals"),
        spec=_DEPENDENCY_HEADLINE_SPEC,
        verdict_token=v,
        driving_rule_id=headline.get("driving_rule_id"),
        verdict_polarity=_dependency_verdict_polarity(v),
        certainty=_headline_certainty(headline),
    )


# ── verdict-INERT signal-surfacing flags (2026-09-03 enrichment) ──────────────────────────────────
# Both are NEW headline fields → None (no-op) except in the specific case each names, so every existing
# fixture/golden (both arms measured, positive verdict) is byte-stable and the dependency_verdict spine
# is untouched. They make deterministic two data-shape reconciliations the LLM previously had to derive
# ad hoc (graded in the KRAS/COADREAD narrative FIDELITY pass).

# A DECISIVE single-arm dependency call (pan-essential / selective / broadly-dependent magnitude).
_DECISIVE_DEP_CALLS = frozenset({"common_essential", "strongly_selective", "broadly_dependent"})
# An UNMEASURED arm — a coverage gap, distinct from a measured floor (`non_dependent`).
_UNMEASURED_ARM = frozenset({"data_unavailable", None})
# The coverage-gap verdicts the resolver returns when it cannot make a call.
_COVERAGE_GAP_VERDICTS = frozenset(
    {"insufficient", "insufficient_underpowered", "insufficient_underpowered_pan_essential"}
)


def _measurement_caveat(verdict, crispr_call, rnai_call) -> str | None:
    """Coverage-ASYMMETRY caveat (mirrors tumor-selectivity's measurement_caveat, v1.21.0): one
    perturbation arm returns a DECISIVE dependency call while the other is UNMEASURED, and the resolver —
    correctly — holds the verdict at a coverage-gap token rather than carry a positive call on a single
    arm. Names the decisive-but-unconfirmed signal so it is not misread as `measured-absent`. VERDICT-
    INERT: reports WHY the spine returned a gap; never changes it. Returns None unless the pattern holds
    (→ byte-stable on every both-arms-measured / positive-verdict fixture)."""
    if verdict not in _COVERAGE_GAP_VERDICTS:
        return None
    crispr_decisive = crispr_call in _DECISIVE_DEP_CALLS
    rnai_decisive = rnai_call in _DECISIVE_DEP_CALLS
    if rnai_decisive and crispr_call in _UNMEASURED_ARM:
        return (
            f"RNAi indicates a dependency ({rnai_call}) but the trusted CRISPR arm is UNMEASURED "
            "(absent from the screen panel) — the resolver holds the verdict at a coverage gap "
            "because RNAi alone (seed/off-target-prone) never carries a positive call. The signal is "
            "decisive-but-unconfirmed, NOT measured-absent; re-run when CRISPR coverage lands."
        )
    if crispr_decisive and rnai_call in _UNMEASURED_ARM:
        return (
            f"CRISPR indicates a dependency ({crispr_call}) but the orthogonal RNAi arm is UNMEASURED "
            "— the call rests on a single perturbation channel (no orthogonal-LoF corroboration). "
            "Decisive-but-single-arm, NOT measured-absent."
        )
    return None


def _concordance_scope_note(concordance_call, crispr_call, rnai_call) -> str | None:
    """Pooled-SCOPE reconciliation: the crispr-rnai-dependency-concordance card can read
    `*_concordant_non_dependent` while BOTH distribution cards read a selective/dependent class — because
    the concordance card measures POOLED per-line agreement (most pan-cancer lines are non-dependent, the
    correct signature of a lineage-selective oncogene like KRAS), NOT a cross-modality contradiction. The
    KRAS/COADREAD narrative had to reason through this ad hoc; encode it so it never depends on the model.
    VERDICT-INERT new field → None unless the pattern holds (byte-stable elsewhere)."""
    if concordance_call not in ("moderately_concordant_non_dependent", "strongly_concordant_non_dependent"):
        return None
    if crispr_call in _DECISIVE_DEP_CALLS and rnai_call in _DECISIVE_DEP_CALLS:
        return (
            "The CRISPR↔RNAi concordance card reads "
            f"`{concordance_call}`, but BOTH distribution cards independently score the target as a "
            f"selective/dependent class (CRISPR {crispr_call}, RNAi {rnai_call}). That label reflects "
            "the POOLED per-line agreement (most pan-cancer lines are non-dependent — the expected "
            "signature of a lineage-selective dependency), NOT a cross-modality contradiction: read it "
            "as corroboration of the selective pattern, not evidence against the dependency."
        )
    return None


# The indication-conditioned POSITIVE verdicts. They live in _DEP_MOD_POS (moderate_positive strength /
# positive polarity / supports direction), but they are INDICATION-GRAIN by construction — the queried
# lineage IS the answer — so they must be excluded from the pooled-scope note below, which exists to warn
# that a TARGET-GRAIN pooled positive may sit outside the queried indication.
_IN_INDICATION_POSITIVE_VERDICTS = frozenset({"lineage_selective_in_indication", "dependent_in_indication"})
# A POSITIVE pooled dependency call (strong or moderate/selective) — the verdicts where a target-grain
# positive could be enriched OUTSIDE the queried indication. The in-indication positives are subtracted:
# they already answer the indication, so the "may sit outside your indication" note would be self-contradictory.
_POSITIVE_POOLED_VERDICTS = (_DEP_STRONG_POS | _DEP_MOD_POS) - _IN_INDICATION_POSITIVE_VERDICTS
# by_scope.indication.class values that mean the QUERIED lineage COULD NOT be adequately measured — a
# COVERAGE GAP, not a measured negative. These must NOT get the "enriched OUTSIDE this indication" prose:
# we did not observe the target failing to be a dependency in the queried lineage, we couldn't look (or
# couldn't look with enough power). not_in_panel = the lineage isn't among the screened set; underpowered =
# too few screened models; data_unavailable = no read at all. (2026-09-19: underpowered/data_unavailable
# were previously silent here — a positive pooled call over an un-looked-at indication returned no note.)
_INDICATION_COVERAGE_GAP_CLASSES = frozenset({"not_in_panel", "underpowered", "data_unavailable"})
# by_scope.indication.class values that DIVERGE from a positive pooled call: a measured negative in the
# queried lineage (not_dependent_in_indication), OR a coverage gap that leaves the pooled positive
# unconfirmed there. All trigger the scope note; the prose branches on which (measured vs could-not-look).
_INDICATION_MISMATCH_CLASSES = frozenset({"not_dependent_in_indication"}) | _INDICATION_COVERAGE_GAP_CLASSES


# Positive verdicts whose evidence is LINEAGE enrichment — for these, and only these, a shallow
# coarse-lineage read genuinely licenses "the signal is in a DIFFERENT lineage".
_LINEAGE_DERIVED_VERDICTS = frozenset({"lineage_selective"})
# Positive verdicts whose evidence is a SUBSTRATUM within a lineage (partner-deficiency / biomarker
# stratification), not a lineage contrast. Here a shallow ALL-lineage median is the EXPECTED shape and
# says nothing about the indication — see the note body.
_STRATIFIED_VERDICTS = frozenset({"partner_conditional_dependent"})


def _indication_scope_note(verdict, by_scope) -> str | None:
    """Indication-SCOPE divergence flag: the pooled dependency_verdict is TARGET-GRAIN, so a POSITIVE
    pooled call need not be an answer for the queried indication. Surface that so a consumer keying on the
    one-word verdict token does not over-read it — the honest indication answer lives in
    dependency_verdict_by_scope.indication (Phase-3). VERDICT-INERT: the pooled verdict is unchanged.

    The note BRANCHES ON VERDICT PROVENANCE (2026-09-12), because one prose for all positives was actively
    false for stratified verdicts:

      lineage-derived (lineage_selective, resolver rung 4 / lineage-selective-supportive) — the original
        case, and correct. BRAF/COADREAD: lineage_selective pan-cancer but Bowel not_dependent_in_indication,
        because BRAF is enriched in Skin. "Enriched outside this indication" is exactly right.

      stratified (partner_conditional_dependent, rungs 11-14) — the verdict comes from a partner-deficiency
        SUBSTRATUM, not a lineage contrast, so the coarse-lineage median is the WRONG comparator and a
        shallow value is the expected shape rather than a divergence. The old prose told the reader
        WRN/COADREAD was "enriched OUTSIDE this indication" on a Bowel median of -0.14 — but WRN x MSI is
        the canonical MSI-H COLORECTAL synthetic lethality, so the note pointed away from the one indication
        that matters. Same error class as scoring a selective dependency against a pooled median.

      other positives (concordant_dependent, selective_dependent, broadly_dependent,
        chemical_genetic_confirmed_dependent) — panel-level magnitude calls. The divergence is real and
        worth flagging, but attributing it to enrichment in another lineage is unfounded, so the note
        states the divergence without inventing a cause.

    Also fires when the indication could not be resolved at all: a positive pooled verdict plus a MISSING
    indication read was previously silent (returned None), so `--indication LUAD` reported lineage_selective
    with no indication answer and nothing in the headline saying so.
    """
    if verdict not in _POSITIVE_POOLED_VERDICTS:
        return None
    ind = (by_scope or {}).get("indication") or {}
    cls = ind.get("class")
    indication = ind.get("indication") or "this indication"

    # UNRESOLVED indication: no lineage to compare against. Say so rather than staying silent.
    if cls == "data_unavailable" and not ind.get("depmap_lineage"):
        why = ind.get("_note") or "the indication did not resolve to a DepMap lineage"
        return (
            f"The pooled dependency_verdict ('{verdict}') is TARGET-GRAIN, and NO indication-scoped read "
            f"was possible for {indication}: {why}. Treat the pooled token as a target-level statement "
            "only — this package contains no evidence about the dependency within this indication."
        )

    if cls not in _INDICATION_MISMATCH_CLASSES:
        return None
    lineage = ind.get("depmap_lineage") or "the queried lineage"
    med = ind.get("median_chronos")
    med_s = f" (median Chronos {med:.2f})" if isinstance(med, (int, float)) else ""

    # COVERAGE GAP (could-not-look), NOT a measured negative: do NOT claim the pooled positive is
    # "enriched OUTSIDE this indication" — that asserts a measured negative in the queried lineage we
    # never observed. Say plainly that the indication could not be (adequately) assessed. (C1/C3: this is
    # exactly the false-absence prose HNSC's not_in_panel used to reach the reader with.)
    if cls in _INDICATION_COVERAGE_GAP_CLASSES:
        why = {
            "not_in_panel": f"{lineage} is not among the screened lineages",
            "underpowered": f"the {lineage} lineage has too few screened models to call a dependency",
            "data_unavailable": f"no dependency read was available for the {lineage} lineage",
        }[cls]
        return (
            f"The pooled dependency_verdict ('{verdict}') is TARGET-GRAIN, and the indication-scoped read "
            f"is a COVERAGE GAP for {indication} (`{cls}`): {why}. This is NOT a measured negative — the "
            f"package makes no claim that the dependency is absent in {indication}; it could not be "
            "assessed there. Read the indication scope from dependency_verdict_by_scope.indication, NOT "
            "the target-grain token."
        )

    if verdict in _STRATIFIED_VERDICTS:
        return (
            f"The pooled dependency_verdict ('{verdict}') is STRATIFIED — it rests on a dependency within a "
            f"partner-deficient SUBSTRATUM, not on a lineage contrast. The unstratified {lineage} lineage "
            f"read is `{cls}`{med_s}, which is the EXPECTED shape for a conditional dependency and neither "
            f"confirms nor refutes it for {indication}: the substratum is a minority of the lineage's cell "
            "lines, so pooling them dilutes the effect. Do NOT read this as the dependency lying outside "
            "this indication. The decision-relevant evidence is the partner-conditional stratification "
            "(see the partner-conditional-dependency card) applied WITHIN the indication."
        )

    if verdict in _LINEAGE_DERIVED_VERDICTS:
        return (
            f"The pooled dependency_verdict ('{verdict}') is TARGET-GRAIN — selective to SOME lineage, not "
            f"necessarily {indication}. For the queried {lineage} lineage the dependency reads "
            f"`{cls}`{med_s}: the pooled positive is enriched OUTSIDE this indication. Read the "
            "indication answer from dependency_verdict_by_scope.indication, NOT the target-grain token."
        )

    return (
        f"The pooled dependency_verdict ('{verdict}') is a PANEL-LEVEL call, not an indication-specific "
        f"one. For the queried {lineage} lineage the dependency reads `{cls}`{med_s}, which diverges from "
        f"the pooled positive. The evidence does not say WHY (this verdict rests on panel-wide magnitude, "
        f"not on a lineage contrast), so do not assume enrichment in another lineage. Read the "
        f"{indication} answer from dependency_verdict_by_scope.indication, NOT the target-grain token."
    )


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    predictability_class = get_card_field(cards, "dependency-predictability", "predictability_class")
    cross_consortium_class = get_card_field(cards, "cross-consortium-dependency", "cross_consortium_class")
    coessential_module_class = get_card_field(cards, "coessential-module", "coessential_module_class")
    confidence = _dependency_confidence_note(v, predictability_class, cross_consortium_class, coessential_module_class)
    hl = {
        "dependency_verdict": v,
        "driving_rule_id": drv,
        # (strength, certainty) — CERTAINTY_MODEL #dependency reference axis. ADDITIVE + verdict-inert.
        # corroboration is Broad↔Sanger cross-consortium (verdict-DISJOINT), NOT CRISPR↔RNAi concordance
        # (which resolves the verdict). See _dependency_strength_certainty.
        "strength_certainty": _dependency_strength_certainty(cards, v, cross_consortium_class),
        "crispr_call": get_card_field(cards, "pan-cancer-crispr-dependency-distribution", "dependency_class"),
        "rnai_call": get_card_field(
            cards, "pan-cancer-rnai-dependency-distribution", "rnai_dependency_class"
        ),  # 2026-08-08 fix: card emits rnai_dependency_class (prefixed), not dependency_class → was silently None
        "concordance_call": get_card_field(cards, "crispr-rnai-dependency-concordance", "concordance_class"),
        "lineage_selectivity": get_card_field(
            cards, "dependency-lineage-selectivity", "enrichment_class"
        ),  # 2026-08-08 fix: card emits enrichment_class (the rule keys on it too); lineage_selectivity_class never existed → was silently None
        "paralog_buffering_class": get_card_field(cards, "paralog-buffering", "paralog_buffering_class"),
        "strongest_paralog_symbol": get_card_field(cards, "paralog-buffering", "strongest_paralog_symbol"),
        # Gate-C: predictability CONFIDENCE annotation over the verdict —
        # additive; the verdict + driving_rule_id above are untouched.
        "predictability_class": predictability_class,
        "pred_dominant_feature_class": get_card_field(
            cards, "dependency-predictability", "pred_dominant_feature_class"
        ),
        # Independent-consortium corroboration (Broad Achilles vs Sanger Project Score), 2026-08-12.
        # Folded into dependency_confidence above (concordant_dependent RAISES confidence; discordant
        # adds a caveat) AND surfaced here so the narrative can cite it. VERDICT-INERT — the card
        # fires no resolver rung; it only tunes gate-C confidence (was computed but consumed by nothing).
        "cross_consortium_class": cross_consortium_class,
        # Co-essential-module coherence (2026-08-19) — mechanism-anchoring CONFIDENCE facet (enrichment
        # review #1; was orphaned). Folded into dependency_confidence above (in_coherent_module RAISES;
        # isolated adds a caveat) AND surfaced here for the narrative. VERDICT-INERT — no resolver rung.
        "coessential_module_class": coessential_module_class,
        # NB: n_coessential_partners is not yet read by an FR surface (question-table/hero/claim/resolver/
        # veto) — a half-wired sibling of strongest_coessential_partner (consumed by question_table Q7).
        # RETAINED (not dropped) because it is the sole reader of coessential-module.n_strong_partners:
        # removing it turns that summary_field into a declared-but-unread aperture orphan (the census is
        # disposition-blind and its ceiling is fixed). Follow-up #1557: wire it into Q7 ("N strong
        # coessential partners incl. X") rather than drop, to keep the field credited AND consumed.
        "n_coessential_partners": get_card_field(cards, "coessential-module", "n_strong_partners"),
        "strongest_coessential_partner": get_card_field(cards, "coessential-module", "strongest_partner_symbol"),
        "dependency_confidence": confidence["confidence"],
        "dependency_confidence_note": confidence["note"],
        # Q4 patient↔model correspondence — model-backed-dependency corroboration (render facet):
        "model_correspondence_class": get_card_field(cards, "recommended-models", "correspondence_class"),
        "n_positive_models_in_lineage": get_card_field(cards, "recommended-models", "n_positive_models_in_lineage"),
        # GENOTYPE-matched patient↔model facet (2026-08-19) — complements the expression-similarity
        # model_correspondence above with genotype IDENTITY (does an available model carry THIS target's
        # event?). Render facet ONLY: the card is declared `interpretation: rules_pending` and no
        # interpretation rule in any lane reads event_correspondence_class (verified 2026-09-12), so it
        # is UNINTERPRETED rather than interpreted in the genomic lane, as this comment used to imply.
        "event_correspondence_class": get_card_field(cards, "genomic-event-model-match", "event_correspondence_class"),
        # Q7 RNA expression → dependency (render facet) — the RNA arm of the biomarker-assay comparison.
        # Surfaced alongside its protein sibling below so the RNA-vs-protein preferred-assay read the two
        # arms exist to enable is not defeated by the RNA class being stranded. VERDICT-INERT.
        "rna_dependency_correlation_class": get_card_field(
            cards, "expression-dependency-correlation", "correlation_class"
        ),
        # Q7 protein abundance → dependency (render facet, biomarker-assay comparison vs the RNA arm):
        "abundance_dependency_class": get_card_field(cards, "abundance-dependency", "abundance_dependency_class"),
        "protein_dependency_pearson_r": get_card_field(cards, "abundance-dependency", "protein_dependency_pearson_r"),
        # ── claim-vector inputs (2026-08-18) — the class fields the DEP/SEL/COND/CHEM claims key on,
        # read here via get_card_field so the headline-fields drift guard covers them (the reliability
        # numerics ride alongside). crispr_call/rnai_call/concordance_call/lineage_selectivity/
        # cross_consortium_class/predictability_class above already supply DEP+SEL; these add COND+CHEM.
        "partner_conditional_class": get_card_field(
            cards, "partner-conditional-dependency", "partner_stratification_class"
        ),
        "n_partner_deficient": get_card_field(cards, "partner-conditional-dependency", "n_partner_deficient"),
        "partner_stratification_q": get_card_field(
            cards, "partner-conditional-dependency", "partner_stratification_mannwhitney_q"
        ),
        "prism_concordance_class": get_card_field(cards, "prism-crispr-concordance", "crispr_prism_concordance_class"),
        "n_compounds_evaluated": get_card_field(cards, "prism-crispr-concordance", "n_compounds_evaluated"),
        "n_lineages_evaluated": get_card_field(cards, "dependency-lineage-selectivity", "n_lineages_evaluated"),
    }
    # Verdict-INERT signal-surfacing flags (2026-09-03). Both are None on the KRAS-shaped positive /
    # both-arms-measured case except concordance_scope_note (which fires for KRAS — pooled non-dependent
    # vs selective distributions). measurement_caveat fires only on a coverage-gap verdict with an
    # unmeasured arm (POLR2A: CRISPR data_unavailable + RNAi common_essential). Neither touches the spine.
    hl["measurement_caveat"] = _measurement_caveat(v, hl["crispr_call"], hl["rnai_call"])
    hl["concordance_scope_note"] = _concordance_scope_note(hl["concordance_call"], hl["crispr_call"], hl["rnai_call"])
    # RNAi LoF-distribution corroboration (2026-09-27): the orthogonal-perturbation twin of the CRISPR
    # distribution _dependency_strength_certainty reads above — surfaces the RNAi arm's OWN magnitude/shape
    # signature (from the four rnai_* distribution fields, previously stranded/unread) so a consumer keying
    # on rnai_call sees WHY the class was assigned and how strongly the orthogonal arm corroborates it.
    # VERDICT-INERT: a render facet beside rnai_call; fires no rung, never enters the resolver.
    hl["rnai_lof_support"] = _rnai_lof_dependency_support(cards)
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
    # Indication-SCOPE divergence flag (2026-09-04): a POSITIVE pooled verdict enriched OUTSIDE the queried
    # indication (by_scope.indication = not_dependent_in_indication / not_in_panel). None where the
    # indication IS the enriched lineage → byte-stable (KRAS/COADREAD = selective_in_indication). Reads the
    # by_scope just built. Verdict-INERT.
    hl["indication_scope_note"] = _indication_scope_note(v, hl["dependency_verdict_by_scope"])
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message, as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built; best-effort (a formatting/read fault must NEVER discard the
    # dependency spine already fully built in `hl`, matching tumor-presence's degrade-on-exception discipline).
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # The 7-question (data · signal · confidence) LEADING table — a verdict-INERT projection over the
    # just-built headline + claim_vector (mirrors tumor-presence / tumor-selectivity). Carried through
    # _synthesis_facet so the composed target-profile dashboard renders the same table. Best-effort:
    # a formatting/read fault must NEVER discard the dependency spine already fully built in `hl`.
    try:
        hl["question_table"] = dependency_question_table(hl, cards, hl.get("claim_vector"))
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, assembled
    # from the verdict + claim_vector + headline_block + question_table just built. functional-requirement
    # is a GATING skill (∈ target-profile _SHORT_TO_GATE); its dependency polarity is clean 3-band with no
    # veto-killer verdict (pan_essential_killer is mapped to NEUTRAL — a liability that routes to safety,
    # not a dependency veto), so the helper's negative→opposing floor is correct and no
    # canonical_polarity_override is needed. Best-effort + verdict-INERT.
    try:
        # Provenance from the REAL resolved-card state (not the static declared CARDS), so a chip whose
        # card resolved ABSENT is distinguishable from one that ran-but-indeterminate.
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=hl.get("dependency_verdict"),
            driving_rule_id=hl.get("driving_rule_id"),
            headline_block=hl.get("headline_block"),
            claim_vector=hl.get("claim_vector"),
            question_table=hl.get("question_table"),
            fired_rule_ids=[f.get("rule_id") for f in (fired or [])],
            cards_used=_used or CARDS,
            cards_missing=_missing,
            # FOR-WHAT projection onto the spine (the SAME dict the claim_record_shadow carries), so
            # target_report.modality_fit rolls up the degrader channel FROM the report, not a reach-in.
            modality_scope=_dep_modality_scope(cards),
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        hl["skill_report"] = None
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
    "dependency_verdict",
    "driving_rule_id",
    "crispr_call",
    "rnai_call",
    "concordance_call",
    "lineage_selectivity",
    "paralog_buffering_class",
    "strongest_paralog_symbol",
    # conditional-SL + chemical-genetic confirmation (the COND / CHEM claim inputs)
    "partner_conditional_class",
    "prism_concordance_class",
    # confidence annotations FR separates from its verdict (narrative context; the numeric certainty
    # roll-up lives in certainty_by_axis, not here)
    "predictability_class",
    "cross_consortium_class",
    "coessential_module_class",
    "dependency_confidence",
    "dependency_confidence_note",
    # biomarker render facets (patient-selection context)
    "model_correspondence_class",
    "event_correspondence_class",
    # RNA-vs-protein preferred-assay comparison: RNA arm (correlation_class) beside its protein sibling
    "rna_dependency_correlation_class",
    "abundance_dependency_class",
    # the modality-blind claim vector SIGNAL decomposition + brief cited read (this subskill's
    # within-lens integration; the cross-lens layer reads the per-claim SIGNALS, not a certainty)
    "claim_vector",
    "key_signals",
    # scope-parameterized read (Phase 3) — pooled pan-cancer vs the QUERIED indication's lineage;
    # lets the composed synthesis cite the indication answer instead of the pan-cancer one. Verdict-inert.
    "dependency_verdict_by_scope",
    # the 7-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — dependency is the second
    # gating adopter after safety (the Wave-3 skill_report adoption arc)
    "skill_report",
    # verdict-INERT signal-surfacing flags (2026-09-03): coverage-asymmetry caveat (decisive single-arm
    # signal held at a coverage-gap verdict) + pooled-scope concordance reconciliation. Fed to the
    # narrator so the synthesis cites them deterministically instead of re-deriving them.
    "measurement_caveat",
    "concordance_scope_note",
    # indication-scope divergence flag (2026-09-04): a positive pooled verdict enriched OUTSIDE the
    # queried indication (target-grain vs indication-lineage). Verdict-inert.
    "indication_scope_note",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT dependency facet for the composed target-profile synthesis prompt.
    Reuses `_headline` (single source of truth) and returns the reconciliation-relevant subset.
    Never moves the verdict; safe to omit (fan-out treats absence as no-facet)."""
    h = _headline(cards, fired, verdict_pair)
    return build_synthesis_facet(
        h,
        _SYNTHESIS_FACET_KEYS,
        (
            "Deterministic dependency facet from functional-requirement (a FACET, not a gate; the "
            "dependency verdict is owned by the shared resolver and is verdict-inert to this projection). "
            "claim_vector is the SIGNAL decomposition — DEP genetic-dependency / SEL context-selectivity / "
            "COND conditional-SL / CHEM chemical-genetic-confirmation, each a signal tier. The per-axis "
            "certainty roll-up is the separate certainty_by_axis sidecar, not this facet."
        ),
    )


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
    headline = _headline(cards, fired, verdict_pair)
    decision = {
        "target": target,
        "indication": indication,
        "headline": headline,
        "cards": [{"card_id": c.get("card_id"), "summary": c.get("summary") or {}} for c in cards],
        "literature_synthesis": literature_synthesis,
    }
    # Narrate through the SAME generic capsule-driven engine + dependency LensConfig the standalone
    # --synthesize path uses (make_synthesize_fn(_FR_LENS) at the run_wired_skill call). The prior call
    # here was to `synthesize_dependency`, the BESPOKE narrator that was migrated away (see the note at
    # the synthesize_fn wiring below) — the name no longer exists, so a COMPOSED target-profile run raised
    # NameError, swallowed by the fan-out's best-effort wrapper → FR narration was silently dead in the
    # composed product. Reuse the single source so standalone and composed narrate identically.
    return make_synthesize_fn(_FR_LENS)(decision, model_id, subtype)


# ─── Signals-first sub-group reader (verdict-INERT) ───────────────────────────────────────────────
# Tunes the fleet-default sub-group derivation for the DEPENDENCY lens vocabulary. The default token
# heuristic tags this lens's POSITIVE signals (`lineage_selective`, `concordant_dependent`,
# `broad_organoid_dependency`, `triangulated_target_engaged`) as `absent` — flipping their polarity.
# _FR_VALUE_TIERS states the tier for the lens's own card values (default_classify remains the fallback).
# _FR_SUBGROUP_READER marks paralog-buffering as confidence-only (a caveat that a paralog masks a
# single-gene KO — NOT a dependency-magnitude source), so it does not pollute the DEP signal. Both are
# passed to the dispatcher's central subgroup wiring; VERDICT-INERT (the dependency spine is untouched).
_FR_VALUE_TIERS = {
    # CRISPR / RNAi loss-of-function dependency magnitude (crispr_lof / rnai_lof / organoid)
    "strongly_selective": "strong",
    "moderately_selective": "moderate",
    "weakly_selective": "weak",
    "lineage_selective": "strong",  # selective essentiality in the lineage = strong within-indication
    "broad_nonselective": "strong",
    "pan_essential": "strong",  # pan-essential = strong dependency (selectivity is a separate axis)
    "not_selective": "absent",
    "non_dependent": "absent",
    "not_dependent": "absent",
    "pan_organoid_essential": "weak",  # common-essential-like (frac_dependent>=0.90) — low target value
    "broad_organoid_dependency": "strong",
    "selective_organoid_dependency": "moderate",
    "rare_organoid_dependency": "weak",  # weak-positive (0.05<=frac_dependent<0.20)
    "not_organoid_dependent": "absent",
    # CRISPR↔RNAi + cross-consortium concordance (agreement × dependency)
    "concordant_dependent": "strong",
    "moderately_concordant_dependent": "moderate",
    "moderately_concordant_non_dependent": "weak",
    "concordant_non_dependent": "absent",
    "discordant": "weak",
    "discordant_non_dependent": "weak",
    # Chemical-genetic confirmation (PRISM × CRISPR)
    "triangulated_target_engaged": "strong",
    "partially_triangulated": "moderate",
    "not_triangulated": "absent",
    "no_chemical_confirmation": "absent",
    # Conditional / synthetic-lethal partner
    "partner_conditional_dependency": "strong",
    "no_partner_mapped": "absent",
    # SEL — context-selectivity biomarker facets (expression/abundance↔dependency, model correspondence)
    "strong_negative": "strong",
    "moderate_negative": "moderate",
    "weak_negative": "weak",
    "strong_protein_dependency_link": "strong",
    "moderate_protein_dependency_link": "moderate",
    "weak_protein_dependency_link": "weak",
    "no_protein_dependency_link": "absent",
    "well_modeled_in_lineage": "strong",
    "partially_modeled_in_lineage": "moderate",
    "poorly_modeled_in_lineage": "weak",
    "no_model_in_lineage": "absent",
}
# paralog-buffering (mt: paralog_buffering) is a CONFIDENCE caveat, not a dependency-magnitude source.
# A falsy spec marks a measurement_type confidence-only so derive_subgroups skips it from the signal.
_FR_SUBGROUP_READER = {"paralog_buffering": None}


# ─── EXPORTED bounded evidence-package sections (PR-1b, epic #2210 Wave 1 / #1507) ───────────────────
# The dependency generalisation of the tumour-presence reference vertical
# (`skills/tumor-presence/scripts/run.py::_evidence_sections`), replicating the safety seed
# (on-target-safety-liability/run.py). Under `--emit-envelope` the emitted evidence_package.json gains
# NAMED top-level sections so the L1→L2a→L2b layering is STRUCTURE rather than a convention over
# `synthesis.headline.claim_vector`. The schema (contracts/schemas/evidence_package.schema.json) ALREADY
# declares all four as optional — no schema change, and a section this domain does not produce is OMITTED.
#
# The L2b property island promoted to a shared top-level section. ONE for dependency today —
# `crispr_rnai_essentiality_concordance` (CRISPR × RNAi, SK#1533), which reconstructs to L1 through
# `provenance.sources[*].(provenance.)card_id`. Deliberately a ROSTER, not "everything without a
# `signal` key": a future L2b fold must be listed here consciously, exactly as the presence roster works.
_INTEGRATED_ISLAND_KEYS = ("crispr_rnai_essentiality_concordance",)

# The composites that stay INSIDE the domain with their epistemic type declared — the four dependency
# claim axes. NOT promoted to shared L2 properties: each is this skill's own (signal × corroboration)
# read of one source, reconstructable to L1 via `evidence_atom.cite.card_id`. Pinned to the ClaimSpec
# roster so an axis added to DEPENDENCY_CLAIM_SPEC cannot silently go unexported.
_LOCAL_COMPOSITE_KEYS = tuple(spec.axis_key for spec in DEPENDENCY_CLAIM_SPEC)


def _evidence_sections(headline: dict) -> "dict | None":
    """Build the NAMED, bounded top-level evidence-package sections from the rich decision headline.

    Pure read-projection over the already-built `headline`: partitions content it ALREADY carries into the
    doc's named sections (`source_properties` L2a, `integrated_properties` L2b, `local_composites`).
    Nothing is recomputed and nothing is dropped that a consumer could not already read on the headline.
    Every emitted section reconstructs downward to L1:
      * source_properties[*].card_id (+ per-anchor {field, value} → the L1 card field)
      * integrated_properties[*].provenance.sources[*].card_id (or .provenance.card_id)
      * local_composites.claims.<AXIS>.evidence_atom.cite.card_id
    `l3d` is NOT emitted: the dependency within-domain L3d story object is Wave-2a (PR-2a), not built yet,
    and an empty section is worse than an absent one — so this domain emits THREE of the schema's four
    optional sections. Returns None when no claim_vector resolved, so the dispatcher passes
    `evidence_sections=None` and the emitted package is byte-identical to the pre-PR-1b shape.
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

    # L2b — the property islands (reconstructable to card_ids via provenance.sources[*].(provenance.)card_id).
    integrated = {k: cv[k] for k in _INTEGRATED_ISLAND_KEYS if cv.get(k) is not None}
    if integrated:
        sections["integrated_properties"] = integrated

    # Local composites — carried inside the domain with the epistemic type declared.
    carried = {k: cv[k] for k in _LOCAL_COMPOSITE_KEYS if cv.get(k) is not None}
    if carried:
        sections["local_composites"] = {"epistemic_type": "domain_local_composite", "claims": carried}

    return sections or None


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
            # Opt-in --synthesize narrates through the DEPENDENCY lens (its own tool schema + prompt,
            # foregrounding the selective-vs-pan-essential distinction). Two-slot / verdict-inert: the
            # dispatcher attaches decision['llm_synthesis'] as a sibling key AFTER the spine is composed,
            # so it is structurally impossible for the narration to alter dependency_verdict. Without this
            # synthesize_fn the dispatcher would fall back to the PRESENCE narrator (wrong lens).
            # MIGRATED to the generic capsule-driven narrator engine + the dependency LensConfig (was the
            # bespoke synthesize_dependency). Same two-slot / verdict-inert contract; now reads the evidence
            # capsules (bounded raw data) alongside the signal vector.
            synthesize_fn=make_synthesize_fn(_FR_LENS),
            # Opt-in --literature: a VERDICT-INERT literature corroboration/contradiction lane. Attaches
            # decision['literature_synthesis'] (Europe PMC → PubTator3 fallback grounding + a post-synthesis
            # verify_citations pass) and feeds the --synthesize narrator. The _LENS_QUERY_TERMS entry for
            # "functional-requirement" (genetic dependency / essential gene / CRISPR knockout / RNA
            # interference) is already declared in literature_retrieval.py. Same two-slot / spine-untouched
            # contract as --synthesize (dispatcher attaches it after the deterministic decision is composed).
            literature_fn=make_literature_fn(_FR_LENS, retrieve_fn=default_retrieve, verify_fn=verify_citations),
            # Opt-in --subtypes resolves the DESCRIPTIVE dependency-by-molecular-subgroup panorama
            # (subgroup-stratified-dependency; e.g. MSI_H vs MSS). Verdict-inert: its cards touch no
            # resolver rung, so the dependency verdict is byte-identical without --subtypes.
            subtype_panorama_fn=_resolve_dependency_subtype_panorama,
            # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
            skill_figures_fn=emit_headline_hero,
            # Signals-first: tuned sub-group reader for the dependency vocabulary (correct polarity +
            # paralog-buffering as confidence-only). Verdict-INERT — feeds subgroup_signals / the narrator.
            subgroup_reader_spec=_FR_SUBGROUP_READER,
            subgroup_classify=make_value_classifier(_FR_VALUE_TIERS),
            # Stage 5b: the `dependency` card preprocessor writes indication_dependency_class onto
            # dependency-lineage-selectivity BEFORE fired_rules, making the four indication-conditioned
            # rungs reachable on the standalone path too (the composed paths already apply it via the
            # gate name). Verdict-inert on a target-grain run (indication_not_supplied has no rung).
            preprocess_gate="dependency",
            # PR-1b (#2210): under --emit-envelope, splice the NAMED bounded evidence-package sections
            # (source_properties L2a / integrated_properties L2b / local_composites) in as top-level keys
            # of evidence_package.json — a VIEW over the same headline content, each reconstructable
            # downward to its claim IDs / L1 card_ids. Verdict-INERT (decision.json spine untouched).
            evidence_sections_fn=_evidence_sections,
        )
    )
