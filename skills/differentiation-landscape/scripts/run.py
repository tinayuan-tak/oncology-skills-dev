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
from _skills_common import get_card_field
from _skills_common.differentiation_claims import differentiation_claim_vector, differentiation_key_signals
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.resolver import resolve_or_raise


SKILL_NAME = "differentiation-landscape"
SKILL_VERSION = "1.4.0"   # 1.4.0 (2026-08-21): + canonical HEADLINE block (verdict + confidence + top
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


_DIFFERENTIATION_HEADLINE_SPEC = HeadlineSpec(
    gate="differentiation",
    axis_labels={"COMUT": "co-mutation landscape", "SURVIVAL": "expression↔survival",
                 "PROGNOSIS": "PRECOG prognostic", "NODE": "pathway-node leverage"},
    axis_keys=("COMUT", "SURVIVAL", "PROGNOSIS", "NODE"),
    critical_axes=("COMUT", "SURVIVAL"),
    verdict_label=lambda v: _DIFFERENTIATION_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    # No cross-cutting flag beyond the claim_vector conflicts + key_signals caveat: differentiation_key_signals
    # emits no caveat and the skill has no single skill-specific tension flag (the panel-intersect pooling
    # discipline is carried per-claim in the atoms). So tension_extra=None.
    tension_extra=None,
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
    }
    # verdict-INERT claim-vector projection (7th concrete) — COMUT/SURVIVAL/PROGNOSIS/NODE decomposition
    # + citable atoms the composed fan-out lifts to the cross-evidence agent.
    hl["claim_vector"] = differentiation_claim_vector(hl, cards)
    hl["key_signals"] = differentiation_key_signals(hl, cards)
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
    return hl


_SYNTHESIS_FACET_KEYS = (
    "differentiation_verdict", "driving_rule_id", "cooccurrence_class",
    "survival_association_class", "precog_prognostic_class", "node_leverage_class",
    "claim_vector", "key_signals",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
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
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
