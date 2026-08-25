#!/usr/bin/env python3
"""immune-context — EFFECTOR-arm wired skill (new 2026-08-06, biologics-augment).

The effector companion to surface-modality-fit. A T-cell engager redirects cytotoxic T cells to the
antigen, so it can only work where T cells are PRESENT. surface-modality-fit answers "is there a
surface target?"; this answers the orthogonal "is the tumor immune-hot — is there a CD8 effector
population to redirect?" (IO-target-ID seed note method #2). Consumes the immune-context card
(CIBERSORT LM22 T-cell infiltration from gdc-pancanatlas-immune-2018).

Deliberately a STANDALONE skill, NOT a card inside surface-modality-fit: immune context is the
effector axis, orthogonal to surface biology — a TCE needs BOTH. It composes into the TCE story
ALONGSIDE surface-modality-fit.

v1 is per-indication / target-INDEPENDENT (tier: indication); the antigen-conditioned join (are the
ANTIGEN-HIGH patients also T-cell-high?) is a deferred v2 facet. The verdict is a direct read of the
immune_context_class categorical (a descriptive effector-context call — no cross-card resolver).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.immune_context_claims import (
    immune_context_claim_vector, immune_context_key_signals)
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero

SKILL_NAME = "immune-context"
SKILL_VERSION = "1.1.0"   # 1.1.0: + canonical HEADLINE block (verdict + confidence + top tension) &
                          # headline hero — a verdict-INERT projection over the effector-context
                          # claim_vector / key_signals. Spine byte-stable (gateless; verdict unchanged).

CARDS = [
    "immune-context",
    # VERDICT-INERT TME/immune display cards (wired 2026-08-25). immune-context is GATELESS and its
    # verdict is a direct read of immune_context_class (see _verdict), so these fire no rule and leave
    # the effector-context verdict byte-stable — they add pan-cancer TME composition (myeloid + CAF) and
    # the outcome-anchored melanoma ICI-response association as display/context alongside the CD8 call.
    "myeloid-compartment-expression-cheng",   # pan-cancer tumour-infiltrating myeloid states (suppressive-TME / myeloid-target)
    "caf-compartment-expression-luo",         # pan-cancer CAF states (stromal lens; stroma-vs-malignant denominator)
    "ici-response-association",               # per-gene ICI (anti-PD-1) responder-vs-non-responder association (melanoma-scoped)
]

QUESTION = ("For {indication}, is the tumor immune-hot or immune-cold — is there a CD8 T-cell "
            "effector population present for a T-cell engager to redirect (independent of {target})?")

# The immune-context rules (surface-intrinsic.rules.yaml) that fire on immune_context_class, mapped to
# this skill's effector-context verdict. The skill's verdict IS the immune-context class, resolved from
# the FIRED rule (the standard framework pattern — the categorical drives a rule, the rule drives the
# verdict), so the signal is also visible to any downstream composer, not just this skill.
_RULE_TO_VERDICT = {
    "immune-context-hot-tce-supportive":       "immune_hot",
    "immune-context-intermediate-tce-neutral": "immune_intermediate",
    "immune-context-cold-tce-opposing":        "immune_cold",
}


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Resolve the effector-context verdict from the fired immune-context rule. Exactly one of the
    three class rules fires per run (the class is mutually exclusive); data_unavailable fires none →
    honest insufficient."""
    for r in fired:
        rid = r.get("rule_id")
        if rid in _RULE_TO_VERDICT:
            return (_RULE_TO_VERDICT[rid], rid)
    return ("insufficient", None)


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# immune-context's declaration for the shared headline_core builder: the SINGLE TCE effector axis
# (IMMUNE), the effector-context vocabulary → human phrase, and the immune-cold effector-absence
# efficacy risk as the skill-specific tension source. Verdict-INERT — a one-way projection over the
# already-computed headline (this skill is GATELESS; the verdict spine stays byte-stable).
#
# POLARITY (colours the hero badge). This is a TCE-EFFICACY axis: a strong signal = immune-hot = there is
# a CD8 effector population for a T-cell engager to redirect. The badge polarity encodes the read FOR A
# TCE PROGRAM:
#   * immune_hot   → CD8 effector context present → TCE-favourable → "positive" (blue);
#   * immune_cold  → MEASURED effector absence → a TCE-efficacy RISK (NOT a target veto; CIBERSORT is a
#                    relative, non-spatial screen) → "negative" (red);
#   * immune_intermediate + coverage gaps (insufficient / no cohort) → "neutral" (grey).
_IMMUNE_VERDICT_PHRASE = {
    "immune_hot":          "Immune-hot — CD8 effector context present (TCE-favourable)",
    "immune_intermediate": "Immune-intermediate — partial effector context",
    "immune_cold":         "Immune-cold — effector absence (TCE-efficacy risk)",
    "insufficient":        "Insufficient — no CIBERSORT cohort for this indication",
}


def _immune_verdict_polarity(v) -> str:
    """The skill's OWN reading of the effector-context call (colours the hero badge; never a gate — this
    skill is gateless). immune-hot is TCE-favourable (positive); immune-cold is a MEASURED effector
    absence and thus a TCE-efficacy risk (negative, NOT a target veto); the intermediate mid-band and
    coverage gaps stay neutral."""
    if v == "immune_hot":
        return "positive"
    if v == "immune_cold":
        return "negative"
    return "neutral"


def _immune_tension_extra(headline: dict):
    """The sharpest immune-context caveat: an immune-COLD indication is a MEASURED CD8 effector-absence — a
    TCE-EFFICACY risk (no effector population to redirect), NOT a target-level veto (CIBERSORT is a
    RELATIVE, non-spatial bulk-deconvolution screen). Surfaced only when the call is immune_cold."""
    if headline.get("immune_context_verdict") == "immune_cold":
        return {"text": ("immune-cold: a MEASURED CD8 effector-absence is a TCE-EFFICACY risk (no effector "
                         "population to redirect) — NOT a target veto; CIBERSORT is relative + non-spatial"),
                "source": "immune_context_class", "severity": 3}
    return None


_IMMUNE_HEADLINE_SPEC = HeadlineSpec(
    gate="immune_context",
    axis_labels={"IMMUNE": "TCE effector context"},
    axis_keys=("IMMUNE",),
    critical_axes=("IMMUNE",),
    verdict_label=lambda v: _IMMUNE_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_immune_tension_extra,
)


def _build_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed immune-context headline. Reads the
    effector-context verdict + the verdict-inert claim_vector / key_signals; never moves the spine (this
    skill is gateless). No CERTAINTY_MODEL sidecar is emitted, so confidence is derived from the claim
    vector's corroboration."""
    v = headline.get("immune_context_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_IMMUNE_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_immune_verdict_polarity(v))


def _emit_skill_figures(decision, figures_root):
    """--figures emitter: the canonical headline hero (verdict · confidence · top tension). Additive /
    display-only, offline, best-effort (missing block → [], spine unaffected)."""
    return emit_headline_hero(decision, figures_root)


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    hl = {
        "immune_context_verdict":        v,
        "driving_rule_id":               drv,
        "immune_context_class":          get_card_field(cards, "immune-context", "immune_context_class"),
        "median_cd8_fraction":           get_card_field(cards, "immune-context", "median_cd8_fraction"),
        "median_total_t_cell_fraction":  get_card_field(cards, "immune-context", "median_total_t_cell_fraction"),
        "n_samples":                     get_card_field(cards, "immune-context", "n_samples"),
        "tumor_studies":                 get_card_field(cards, "immune-context", "tumor_studies"),
    }
    # verdict-INERT claim-vector projection (TCE effector axis) + citable CD8-fraction atom for the
    # cross-evidence reasoner. immune-context is gateless (absent from _SHORT_TO_GATE); verdict-inert.
    hl["claim_vector"] = immune_context_claim_vector(hl, cards)
    hl["key_signals"] = immune_context_key_signals(hl, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing
    # headline message as deterministic text + a renderer-agnostic hero payload. A verdict-INERT
    # projection over the claim_vector / key_signals just built. Best-effort: a formatting/read fault must
    # NEVER discard the effector-context spine already built in `hl` (same degrade discipline the
    # dispatcher applies to synthesis / figures). On the happy path this adds no _enrichment_errors key.
    try:
        hl["headline_block"] = _build_headline_block(hl)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        hl.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        hl["headline_block"] = None
    return hl


_SYNTHESIS_FACET_KEYS = (
    "immune_context_verdict", "driving_rule_id", "immune_context_class", "median_cd8_fraction",
    "median_total_t_cell_fraction", "n_samples", "claim_vector", "key_signals",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT immune-context facet for the composed synthesis. Reuses _headline (single
    source) + returns the IMMUNE claim_vector (TCE effector axis) with its citable CD8-fraction atom.
    immune-context is gateless — this never moves the nomination spine."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = ("Deterministic immune-context facet; claim_vector is the TCE EFFECTOR axis "
                            "(indication-level, target-independent). Gateless — no verdict on the spine.")
    return facet


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="surface_intrinsic",     # effector context reads on the biologics (surface/TCE) side
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Skill-level graphics (opt-in --figures): the canonical headline hero. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
    ))
