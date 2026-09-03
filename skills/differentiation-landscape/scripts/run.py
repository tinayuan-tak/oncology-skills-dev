#!/usr/bin/env python3
"""differentiation-landscape — Phase-E partial skill (graduated 2026-07-08).

Co-mutation + mutual-exclusivity landscape from panel-intersect-aware Fisher
scan across TCGA MC3 + GENIE 19.0-public.

Calls the shared run_wired_skill dispatcher (2026-07-09).
Skill-specific logic reduces to CARDS + verdict + headline callbacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import DIFFERENTIATION_LANDSCAPE as _LENS
from _skills_common import get_card_field
from _skills_common.differentiation_claims import differentiation_claim_vector, differentiation_key_signals
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.skill_report import build_skill_report, ROLE_GATING
from _skills_common.differentiation_question_table import differentiation_question_table
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_derivation import make_value_classifier

# Signals-first sub-group reader (VERDICT-INERT). Thesis: a differentiation signal exists (co-mutation
# pattern / stemness node / prognostic association). default_classify is the fallback for unmapped values.
_DIFFERENTIATION_VALUE_TIERS = {
    "both_patterns_present": "moderate", "co_occurrence": "moderate", "mutual_exclusivity": "moderate",
    "no_significant_pattern": "absent",
    "stem_high": "strong", "stem_intermediate": "moderate", "stem_low": "weak",
    "dominant_node": "strong", "intermediate_node": "moderate", "peripheral_node": "weak",
    "expression_high_better_survival": "moderate", "expression_high_worse_survival": "moderate",
    "no_prognostic_association": "absent", "no_survival_association": "absent",
    "subtype_stratifies_survival": "strong",
}
from _skills_common.resolver import resolve_or_raise
from _skills_common.claim_record import assemble_claim_record


SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.8.0"   # 1.8.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.   # 1.7.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.   # 1.6.0 (2026-08-24): compose competitor-landscape (Open Targets competitor field)
                          #        as an ADDITIVE, verdict-inert render facet; namespaced competitor_* headline
                          #        keys feed the target-profile deterministic modality cross-ref. Verdict byte-stable.
                          # 1.5.0 (2026-08-21): compose clinical-precedent (AACT trial precedent) as an
                          #        ADDITIVE/VERDICT-INERT render facet (translational-maturity lens);
                          #        differentiation verdict byte-stable (no resolver rung on clinical_*).
                          # 1.4.0 (2026-08-21): + canonical HEADLINE block (verdict + confidence + top
                          #        tension) + shared headline hero (figure_headline_hero.{svg,png,json}).
                          #        A verdict-INERT projection over the DESCRIPTIVE claim_vector /
                          #        key_signals — differentiation_verdict spine byte-stable (frozen by
                          #        the KRAS/FBXW7 COADREAD replay guard).

CARDS = [
    "co-mutation-and-mutual-exclusivity",
    "stemness-context",   # Malta 2018 (2026-08-10): per-indication tumor-stemness (mRNAsi) cohort prior
                          # — dedifferentiation/aggressiveness prognostic context. ADDITIVE, VERDICT-INERT
                          # (its rules feed NO resolver; differentiation verdict byte-stable). reads stemness_index.
    "expression-clinical-association",   # Q11 (2026-07-23 composition) — does target expression
                                         # stratify SURVIVAL (prognostic context)? A patient-selection /
                                         # clinical-context render facet + biomarker-facet stratification
                                         # input. ADDITIVE — its clinical-* rules feed NO resolver ladder
                                         # (differentiation verdict byte-stable; resolver reads only the
                                         # co-mutation rule_ids). Fills part of the clinical-precedent gap
                                         # this skill's status-partial note flags.
    "precog-prognostic-association",     # PRECOG (2026-08-10): pan-cancer META-ANALYTIC expression→survival
                                         # meta-Z (Gentles 2015 + 2026 NAR; 166 datasets / ~18k patients).
                                         # The better-powered pan-cancer CORROBORATION of the single-cohort
                                         # expression-clinical-association card above. ADDITIVE, VERDICT-INERT
                                         # (no resolver rung; differentiation verdict byte-stable). reads precog_prognostic.
    "pathway-node-leverage",             # (2026-08-17): COMPARATIVE node-leverage — is the target the best
                                         # NODE to hit in its complex/pathway neighbourhood, or dominated? ADDITIVE,
                                         # VERDICT-INERT (its rules emit soft axis_fit signals + fired_rule_ids for
                                         # the cross-evidence hypothesis agent; feed NO resolver → differentiation
                                         # verdict byte-stable). reads node_leverage_class + evidence_scope.
    "alteration-clinical-association",   # Q11-alteration (2026-08-20): does {target} MUTATION status
                                         # stratify OS (prognostic context)? The alteration analog of
                                         # expression-clinical-association. ADDITIVE, VERDICT-INERT (its
                                         # alteration-* rules feed NO resolver; differentiation verdict
                                         # byte-stable). reads alteration_survival_association_class.
    "subtype-survival-association",      # Q2-subtype (2026-08-20): does OS differ ACROSS the indication's
                                         # molecular subtypes? Target-independent patient-selection context.
                                         # ADDITIVE, VERDICT-INERT (subtype-* rules feed NO resolver;
                                         # differentiation verdict byte-stable). reads subtype_survival_association_class.
    "clinical-precedent",                # (2026-08-21): AACT clinical-trial precedent for (target, indication) —
                                         # highest stage / active trials / approved agents / notable failures for a
                                         # drug that ENGAGES the target. WIRED via public-domain AACT (was the
                                         # licensing-blocked placeholder this skill's status note flagged). ADDITIVE,
                                         # VERDICT-INERT (no resolver rung; differentiation verdict byte-stable) —
                                         # the translational-maturity render facet. reads highest_clinical_stage +.
    "competitor-landscape",              # (2026-08-24): Open Targets competitor field for (target, indication) —
                                         # WHO ELSE is developing a drug against this target, at what MODALITY
                                         # (ADC/TCE/mAb/SM/degrader) and clinical stage. WIRED via the pinned OT mirror
                                         # (opentargets-target-competitor-drugs-per-gene-v1). ADDITIVE, VERDICT-INERT
                                         # (no resolver rung; differentiation verdict byte-stable) — the competitive-
                                         # positioning render facet. The value-add cross-ref vs the framework's own
                                         # modality-fit/biomarker verdicts is computed at the target-profile fan-out.
                                         # reads competitor_class + modality_landscape.
]

QUESTION = ("What genes co-occur with or are mutually exclusive to "
            "{target} mutations across TCGA MC3 + GENIE 19.0-public, "
            "and what patient-selection or combination-biology hypotheses "
            "does the pattern support in {indication}?")

PARTIAL_STATUS_NOTE = (
    "differentiation-landscape is status: partial. The clinical-precedent card is now WIRED "
    "(2026-08-21) via public-domain AACT (aact_clinical_precedent) — NO commercial license needed — "
    "and is produced in the composed dashboards; adding it to THIS focused skill's cards_used is a "
    "follow-up. patent-landscape remains unwired (PatBase-equivalent licensing pending). This "
    "skill's own decision still reflects the co-mutation / mutual-exclusivity signal."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (2026-07-20).
    The former if-chain now lives in resolvers/differentiation.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    return resolve_or_raise(fired, "differentiation")


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# differentiation-landscape's declaration for the shared headline_core builder: the four DESCRIPTIVE
# claim axes (COMUT / SURVIVAL / PROGNOSIS / NODE), the differentiation-verdict vocabulary → human
# phrase. Verdict-INERT — a one-way projection over the already-computed headline (differentiation_verdict
# stays byte-stable, frozen by test_differentiation_replay.py + the golden-oracle resolver test).
#
# POLARITY (colours the hero badge). This skill is DESCRIPTIVE: the signal is the STRENGTH of a
# differentiation / patient-selection pattern, and the DIRECTION (co-occurring vs mutually-exclusive;
# worse vs better survival) lives in the atom, NOT the verdict tier. So no differentiation_verdict is a
# clean favourable/unfavourable call for a drug program — every verdict colours the badge `neutral`
# (grey). (Contrast the safety skill, whose inverse-valence liability verdicts DO carry program-polarity.)

# The differentiation.resolver verdict vocabulary → human phrase, with a prettify fallback for any
# future addition. All are DESCRIPTIVE pattern reads (direction lives in the claim atoms).
_DIFFERENTIATION_VERDICT_PHRASE = {
    "both_patterns_present":     "Co-occurring + mutually-exclusive partners",
    "strong_cooccurring":        "Strong co-mutation landscape",
    "strong_mutually_exclusive": "Strong mutual-exclusivity landscape",
    "has_cooccurring_driver":    "Co-occurring driver present",
    "modest_cooccurring":        "Modest co-mutation signal",
    "modest_mutually_exclusive": "Modest mutual-exclusivity signal",
    "ns":                        "No significant co-mutation pattern",
    "data_unavailable":          "Data unavailable",
    "insufficient":              "Insufficient evidence",
}


def _differentiation_verdict_polarity(v) -> str:
    """The skill's OWN reading of the differentiation verdict for the hero badge (never a gate).
    differentiation-landscape is DESCRIPTIVE — the verdict tier encodes the STRENGTH of a co-mutation /
    survival pattern, while the favourable/unfavourable DIRECTION lives in the claim atom. No verdict is
    a clean program-desirability call, so polarity is always `neutral` (grey badge)."""
    return "neutral"


def _int_or_none(v):
    """Coerce a headline count to int; None/non-numeric → None (field-absent-safe)."""
    return v if isinstance(v, int) else (int(v) if isinstance(v, float) else None)


def _panel_absent_signal(hl: dict) -> str | None:
    """DETERMINISTIC panel-intersect-provenance caveat (verdict-INERT).

    The reviewer BLOCKER-FIX restricts a POOLED co-mutation claim to the GENIE panel-intersect
    (166 genes): a panel-ABSENT target gets per-source q-values only (`pooled_eligible=false`) and
    must not be read as a pooled cross-cohort pattern. But the read-time classifier keys the
    `cooccurrence_class` on q + log2-OR ALONE — it never consults `pooled_eligible` — so a
    panel-absent target (e.g. a large passenger gene) can still surface a `strong_cooccurring`
    pattern built ENTIRELY from per-source pairs, which for a long/passenger gene is a TMB /
    gene-length co-mutation artifact rather than biology. When the target is IN the scan but has
    ZERO panel-intersect-eligible pairs, surface that deterministically (rather than leaving it to
    LLM discretion). Verdict token is UNTOUCHED. Fires only for panel-absent targets, so every
    panel-present target (incl. the KRAS / FBXW7 COADREAD replay fixtures, both with >0 eligible
    pairs, and CD19) is byte-identical."""
    elig = _int_or_none(hl.get("n_pairs_panel_intersect_eligible"))
    per_source = _int_or_none(hl.get("n_pairs_per_source_only"))
    if elig == 0 and (per_source or 0) > 0:
        return ("Target is absent from the GENIE panel-intersect (0 panel-intersect-eligible pairs; "
                f"{per_source} per-source-only pairs) — no POOLED cross-cohort co-mutation claim is "
                "possible. The co-mutation pattern rests entirely on per-source pairs and, for a "
                "large/passenger gene, may reflect tumor-mutational-burden / gene-length confounding "
                "rather than biology (pooled_eligible=false throughout).")
    return None


def _panel_absent_tension(hl: dict) -> dict | None:
    """tension_extra hook — the panel-absent caveat as the single top_tension (severity 3, data-quality)."""
    cav = _panel_absent_signal(hl)
    return {"text": cav, "source": "panel_intersect.absent", "severity": 3} if cav else None


_DIFFERENTIATION_HEADLINE_SPEC = HeadlineSpec(
    gate="differentiation",
    axis_labels={"COMUT": "co-mutation landscape", "SURVIVAL": "expression↔survival",
                 "PROGNOSIS": "PRECOG prognostic", "NODE": "pathway-node leverage"},
    axis_keys=("COMUT", "SURVIVAL", "PROGNOSIS", "NODE"),
    critical_axes=("COMUT", "SURVIVAL"),
    verdict_label=lambda v: _DIFFERENTIATION_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    # Skill-specific tension: the panel-intersect-provenance flag (a panel-ABSENT target whose
    # co-mutation pattern rests only on per-source pairs). Verdict-INERT; fires only for panel-absent
    # targets, so panel-present targets (incl. the replay fixtures) are byte-identical.
    tension_extra=_panel_absent_tension,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed differentiation headline. Reads the
    resolved verdict + the verdict-inert claim_vector / key_signals; never moves the spine. This skill
    emits no CERTAINTY_MODEL sidecar, so confidence is derived from the claim vector's corroboration."""
    v = headline.get("differentiation_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_DIFFERENTIATION_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_differentiation_verdict_polarity(v))


def _emit_skill_figures(decision, figures_root):
    """--figures emitter: the canonical headline hero (verdict · confidence · top tension). Additive /
    display-only, offline, best-effort (missing block → [], spine unaffected)."""
    return emit_headline_hero(decision, figures_root)


# ── (strength, certainty) SIDECAR — CERTAINTY_MODEL.md. ADDITIVE + verdict-INERT. Differentiation is a
#    NON-GATING descriptive axis; certainty is coverage + unknown_mass only here — corroboration reads
#    `unmeasured` because the only verdict-DISJOINT corroborator (TCGA<->GENIE per-source direction
#    concordance) is NOT yet emitted as a summary field (it lives in the card's plot_data). Wiring it
#    needs an analysis-methods field-emit + a field-granular disjointness validator (the corroborator
#    shares the verdict card) — a data-ingest follow-on, not this additive slice. strength is a PATTERN
#    magnitude (co-occurrence vs mutual-exclusivity is a pattern TYPE, not good/bad — informational).
_DIFF_ORD = {"low": 0, "medium": 1, "high": 2}
_DIFF_STRONG = {"strong_cooccurring", "strong_mutually_exclusive", "both_patterns_present"}
_DIFF_MOD = {"has_cooccurring_driver", "modest_cooccurring", "modest_mutually_exclusive"}
_DIFF_NONE = {"ns", "data_unavailable", "insufficient", None}


def _diff_card_field(cards, field):
    """None-safe read of the single differentiation verdict card (get_card_field raises on absent)."""
    cid = "co-mutation-and-mutual-exclusivity"
    return get_card_field(cards, cid, field) if cid in {c["card_id"] for c in (cards or [])} else None


def _diff_strength(v) -> str:
    if v in _DIFF_STRONG:
        return "strong_pattern"           # informational: co-occurrence / mutual-exclusivity is a TYPE
    if v in _DIFF_MOD:
        return "moderate_pattern"
    return "none"


def _diff_coverage(n_pairs) -> str:
    """Power of the pooled panel-intersect Fisher test (the pairs that actually drive the verdict)."""
    if not isinstance(n_pairs, (int, float)):
        return "low"
    return "high" if n_pairs >= 50 else ("medium" if n_pairs >= 10 else "low")


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — coverage+unknown_mass only (corroboration unmeasured)."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    n_pairs = _diff_card_field(cards, "n_pairs_panel_intersect_eligible")
    coverage = _diff_coverage(n_pairs)
    level = "low" if v in _DIFF_NONE else coverage      # corroboration unmeasured → level = coverage
    present = "co-mutation-and-mutual-exclusivity" in {c["card_id"] for c in (cards or [])}
    return {
        "strength": _diff_strength(v),
        "certainty": {"level": level, "coverage": coverage, "corroboration": "unmeasured",
                      "unknown_mass": 0.0 if present else 1.0},   # single verdict card (degenerate)
        "provenance": {"n_pairs_panel_intersect_eligible": n_pairs},
        "_model_ref": "CERTAINTY_MODEL.md#differentiation",
    }


# ── FACTORED-RECORD SHADOW (M1) — the DIFFERENTIATION per-axis builder. Differentiation is a
#    DESCRIPTIVE / non-gating axis: co-occurrence vs mutual-exclusivity is a pattern TYPE, not a
#    good/bad valence, so finding.direction is ALWAYS neutral (the pattern informs, it does not push a
#    nomination). VERDICT-INERT: surfaced by the fan-out into decision.claim_record_shadow.differentiation,
#    consumed by NOTHING. Reuses _strength_certainty (coverage-only). Mirrors the other axes' hook.
_DIFF_STRENGTH_TO_LEVEL = {"strong_pattern": "strong", "moderate_pattern": "moderate", "none": "none"}


def _diff_availability(v) -> str:
    if v == "data_unavailable" or v is None:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v == "insufficient":
        return "insufficient"
    if v == "ns":
        return "measured_negative"               # measured, no significant pattern
    return "measured_positive"                   # a pattern was detected


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=verdict_pair)
    return assemble_claim_record(
        axis="differentiation",
        state=(v or "insufficient"),
        direction="neutral",                     # descriptive pattern — never pushes a nomination
        availability=_diff_availability(v),
        magnitude={"level": _DIFF_STRENGTH_TO_LEVEL.get(_diff_strength(v), "none")},
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "differentiation_verdict":          v,
        "driving_rule_id":                  drv,
        "cooccurrence_class":               get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "cooccurrence_class"),
        "n_significant_cooccurring":        get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_significant_cooccurring"),
        "n_significant_mutually_exclusive": get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_significant_mutually_exclusive"),
        "n_pairs_panel_intersect_eligible": get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_panel_intersect_eligible"),
        "n_pairs_per_source_only":          get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "n_pairs_per_source_only"),
        "has_cooccurring_driver":           get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "has_cooccurring_driver"),
        "has_mutually_exclusive_driver":    get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "has_mutually_exclusive_driver"),
        "top_cooccurring":                  get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "top_cooccurring"),
        "top_mutually_exclusive":           get_card_field(cards, "co-mutation-and-mutual-exclusivity",
                                                 "top_mutually_exclusive"),
        # Q11 expression→survival prognostic context (render facet; feeds NO resolver — the
        # differentiation verdict reads only the co-mutation rule_ids, so this is verdict-inert):
        "survival_association_class":       get_card_field(cards, "expression-clinical-association",
                                                 "survival_association_class"),
        "logrank_p":                        get_card_field(cards, "expression-clinical-association", "logrank_p"),
        # PRECOG pan-cancer META-ANALYTIC corroboration of the single-cohort survival call above
        # (render facet; verdict-inert — no resolver rung). Surface the class + both meta-Z views so a
        # reader can compare the single-cohort log-rank vs the pan-cancer meta-analysis at a glance:
        "precog_prognostic_class":          get_card_field(cards, "precog-prognostic-association",
                                                 "prognostic_class"),
        "precog_meta_z":                    get_card_field(cards, "precog-prognostic-association", "meta_z"),
        "precog_pan_cancer_meta_z":         get_card_field(cards, "precog-prognostic-association",
                                                 "pan_cancer_meta_z"),
        "precog_indication_approx":         get_card_field(cards, "precog-prognostic-association",
                                                 "precog_indication_approx"),
        # comparative node-leverage (soft/verdict-inert differentiation context; feeds NO resolver —
        # its axis_fit signals + fired_rule_ids are consumed by the cross-evidence hypothesis agent):
        "node_leverage_class":              get_card_field(cards, "pathway-node-leverage",
                                                 "node_leverage_class"),
        "node_leverage_evidence_scope":     get_card_field(cards, "pathway-node-leverage",
                                                 "evidence_scope"),
        # AACT clinical-trial precedent (render facet; verdict-inert — no resolver rung). The
        # translational-maturity lens: highest stage reached by a drug ENGAGING the target in this
        # indication, active-trial count, approved agents, and notable (terminated) failures.
        # (highest_clinical_stage is the primary categorical — the card emits no separate _class field):
        "highest_clinical_stage":           get_card_field(cards, "clinical-precedent", "highest_clinical_stage"),
        "n_active_trials":                  get_card_field(cards, "clinical-precedent", "n_active_trials"),
        "approved_agents":                  get_card_field(cards, "clinical-precedent", "approved_agents"),
        "notable_failures":                 get_card_field(cards, "clinical-precedent", "notable_failures"),
        # Open Targets competitor field (render facet; verdict-inert — no resolver rung). The
        # competitive-positioning lens: who else has a drug against this target, at what MODALITY and
        # stage. Namespaced 'competitor_*' to avoid colliding with the AACT clinical-precedent keys
        # above. modality_landscape is the field the target-profile cross-ref keys on (competitor
        # modality validated-vs-contrarian vs the framework's own surface-modality-fit verdict).
        "competitor_class":                 get_card_field(cards, "competitor-landscape", "competitor_class"),
        "competitor_highest_stage":         get_card_field(cards, "competitor-landscape", "highest_clinical_stage"),
        "competitor_indication_scope":      get_card_field(cards, "competitor-landscape", "indication_scope"),
        "n_competitor_programs":            get_card_field(cards, "competitor-landscape", "n_competitor_programs"),
        "competitor_approved_agents":       get_card_field(cards, "competitor-landscape", "approved_agents"),
        "competitor_late_stage_non_approved": get_card_field(cards, "competitor-landscape", "late_stage_non_approved_agents"),
        "competitor_modalities_in_development": get_card_field(cards, "competitor-landscape", "modalities_in_development"),
        "competitor_modality_landscape":    get_card_field(cards, "competitor-landscape", "modality_landscape"),
    }
    # verdict-INERT claim-vector projection (7th concrete) — COMUT/SURVIVAL/PROGNOSIS/NODE decomposition
    # + citable atoms the composed fan-out lifts to the cross-evidence agent.
    hl["claim_vector"] = differentiation_claim_vector(hl, cards)
    hl["key_signals"] = differentiation_key_signals(hl, cards)
    # DETERMINISTIC panel-intersect-provenance caveat (verdict-INERT): a panel-ABSENT target's
    # co-mutation pattern rests only on per-source pairs (possible TMB/gene-length artifact). Surface it
    # as the key_signals caveat so the narrator + cross-evidence agent see it deterministically instead of
    # relying on LLM discretion. Panel-absence is the dominant data-quality caveat, so it takes the slot
    # (differentiation_key_signals emits no claim-tier caveat today). Fires only for panel-absent targets
    # → panel-present targets (incl. KRAS/FBXW7 replay fixtures) keep caveat=None, byte-identical.
    _pa = _panel_absent_signal(hl)
    if _pa:
        hl["key_signals"]["caveat"] = _pa
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing headline
    # message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT projection over the
    # claim_vector / key_signals just built. Best-effort: a formatting/read fault must NEVER discard the
    # differentiation spine already fully built in `hl` (mirrors the tumor-presence degrade-on-exception
    # discipline). On the happy path this is byte-identical (no _enrichment_errors key added), so the
    # golden-oracle + replay fixtures are unaffected.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    # The per-question (data · signal · confidence) LEADING table — a verdict-INERT projection over the
    # just-built headline + claim_vector (COMUT/SURVIVAL/NODE + clinical/competitor precedent), giving
    # differentiation component-parity with the other skills. Best-effort: a fault degrades to None +
    # _enrichment_errors, never aborts the differentiation spine.
    try:
        hl["question_table"] = differentiation_question_table(hl, cards)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["question_table"] = f"{type(exc).__name__}: {exc}"
        hl["question_table"] = None
    # UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the ONE cross-skill output shape, from the
    # verdict + claim_vector + headline_block + question_table just built. differentiation-landscape is a
    # GATING skill (∈ target-profile _SHORT_TO_GATE) with a clean 3-band polarity and no veto-killer verdict
    # (a co-mutation/survival landscape raises no cross-target veto), so the helper's negative→opposing
    # floor is correct (no canonical_polarity_override). Best-effort + verdict-INERT.
    try:
        _used = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and not c.get("_missing")]
        _missing = [c.get("card_id") for c in (cards or []) if isinstance(c, dict) and c.get("_missing")]
        hl["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=hl.get("differentiation_verdict"),
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
    "differentiation_verdict", "driving_rule_id", "cooccurrence_class",
    "survival_association_class", "precog_prognostic_class", "node_leverage_class",
    "highest_clinical_stage", "n_active_trials", "approved_agents", "notable_failures",
    # Open Targets competitor field (verdict-inert) — the substrate for the target-profile cross-ref:
    "competitor_class", "competitor_highest_stage", "competitor_indication_scope",
    "n_competitor_programs", "competitor_approved_agents", "competitor_late_stage_non_approved",
    "competitor_modalities_in_development", "competitor_modality_landscape",
    "claim_vector", "key_signals",
    # the per-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # the UNIFIED cross-skill output object (docs/UNIFIED_OUTPUT_CONTRACT.md) — Wave-3 skill_report
    # adoption (6th gating adopter)
    "skill_report",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT differentiation facet for the composed target-profile synthesis. Reuses
    _headline (single source) + returns the DESCRIPTIVE claim_vector (COMUT/SURVIVAL/PROGNOSIS/NODE) +
    its citable atoms. Never moves the verdict; safe to omit."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic differentiation-landscape facet; claim_vector is a DESCRIPTIVE "
                            "decomposition (direction in the atoms). Verdict owned by the resolver.")
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
        # NET-NEW capsule-driven narrator (generic engine + this lens's LensConfig).
        synthesize_fn=make_synthesize_fn(_LENS),
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
        partial_status_note=PARTIAL_STATUS_NOTE,
        # Signals-first: tuned sub-group reader for the differentiation vocabulary. Verdict-INERT.
        subgroup_classify=make_value_classifier(_DIFFERENTIATION_VALUE_TIERS),
    ))
