"""Unified per-skill output object — see docs/UNIFIED_OUTPUT_CONTRACT.md.

`build_skill_report` is a thin, VERDICT-INERT normalizer: a skill already computes its `claim_vector`,
`key_signals`, `headline_block` (via `headline_core.build_headline`) and provenance; this packages them
into the ONE `skill_report` shape every skill shares, stamping the `role` (gating/descriptive/inert) and
the canonical polarity (from `ordinal_view`). It NEVER recomputes or moves a verdict — signals lead, the
verdict is a subordinate summary (the contract's central principle).
"""
from __future__ import annotations

from typing import Optional, Sequence

# role taxonomy — how the composer treats the skill (see the contract doc).
ROLE_GATING = "gating"            # verdict can move the nomination recommendation (∈ _SHORT_TO_GATE)
ROLE_DESCRIPTIVE = "descriptive"  # real read, no gate (rendered, excluded from gate math)
ROLE_INERT = "inert"             # verdict-shaped but explicitly not a call (e.g. cis_coherence)
ROLES = (ROLE_GATING, ROLE_DESCRIPTIVE, ROLE_INERT)

# 3-band headline polarity → the canonical order-preserving scale (ordinal_view). We cannot distinguish
# `killer` from `opposing` at this layer (that needs the driving rule's severity), so a negative call
# floors at `opposing`; a skill that knows a call is a veto passes canonical_polarity="killer" explicitly.
_HEADLINE_TO_CANONICAL = {"positive": "supportive", "neutral": "neutral", "negative": "opposing"}


def _cites_for(atom: dict) -> list:
    """The FULL role-tagged list of cards feeding one claim chip. A chip's signal, corroboration and
    conflict can each draw on a DIFFERENT card (e.g. a presence abundance claim: signal ← tumor-rna-
    distribution, corroboration ← the RNA↔protein-concordance card); this tracks every one, so no part of
    a chip is untraceable. `signal` = the primary evidence_atom.cite; `corroboration`/`conflict` come from
    optional atom-level `corr_cite` / `conflict_cite` a claim sets when it reads a secondary card."""
    cites = []
    primary = (atom.get("evidence_atom") or {}).get("cite")
    if primary:
        cites.append({"role": "signal", **primary})
    for role, key in (("corroboration", "corr_cite"), ("conflict", "conflict_cite")):
        c = atom.get(key)
        if isinstance(c, dict) and c.get("card_id"):
            cites.append({"role": role, **c})
    return cites


def _chips_from_claim_vector(claim_vector: Optional[dict], axis_labels: Optional[dict] = None) -> list:
    """Project the claim vector's A/B/C/D atoms into reader-facing chips: polarity (signal) and strength
    (corroboration) DECOUPLED, each with the FULL list of cards feeding it (`cites`, role-tagged). Best-
    effort; skips non-atom keys. `cite` (singular = the signal card) is retained for back-compat."""
    if not isinstance(claim_vector, dict):
        return []
    chips = []
    for key, atom in claim_vector.items():
        if not isinstance(atom, dict) or "signal" not in atom:
            continue                       # skip scalars like `homogeneity` / `_disclaimer`
        cites = _cites_for(atom)
        chips.append({
            "key": key,
            "label": (axis_labels or {}).get(key) or atom.get("informs"),
            "signal": atom.get("signal"),
            "corroboration": atom.get("corroboration"),
            "conflict": atom.get("conflict"),
            "evidence": atom.get("evidence"),
            "cites": cites,                                   # FULL role-tagged card list (signal/corrob/conflict)
            "cite": (atom.get("evidence_atom") or {}).get("cite"),   # back-compat: raw primary (signal) card
        })
    return chips


def _scalars_from_claim_vector(claim_vector: Optional[dict]) -> dict:
    """The claim vector's NON-ATOM entries (scalars) — the part `_chips_from_claim_vector` drops. A claim
    vector carries atom claims (A/B/C/D → chips) AND plain scalar coordinates (e.g. tumor-presence's
    `homogeneity`); a target_report rollup that reads the spine (e.g. `_modality_conjunction_facet`'s
    homogeneity gate) needs those scalars too, so the skill_report is a LOSSLESS carrier of the claim
    vector. Skips atoms (they are chips) and private `_`-prefixed keys (disclaimers). Best-effort."""
    if not isinstance(claim_vector, dict):
        return {}
    out: dict = {}
    for key, val in claim_vector.items():
        if key.startswith("_"):
            continue                                   # private (e.g. `_disclaimer`) — not a signal
        if isinstance(val, dict) and "signal" in val:
            continue                                   # an atom claim → already a chip
        out[key] = val
    return out


def canonical_polarity(role: str, headline_block: Optional[dict],
                       explicit: Optional[str] = None) -> str:
    """The one normalized direction for the call. descriptive/inert → `not_scored`; otherwise map the
    3-band headline polarity onto the canonical scale (or honor an explicit canonical override)."""
    if role in (ROLE_DESCRIPTIVE, ROLE_INERT):
        return "not_scored"
    if explicit:
        return explicit
    hb_pol = ((headline_block or {}).get("verdict") or {}).get("polarity")
    return _HEADLINE_TO_CANONICAL.get(hb_pol, "neutral")


def build_skill_report(*, role: str,
                       verdict: Optional[str],
                       driving_rule_id: Optional[str] = None,
                       headline_block: Optional[dict] = None,
                       claim_vector: Optional[dict] = None,
                       question_table: Optional[list] = None,
                       fired_rule_ids: Optional[Sequence[str]] = None,
                       cards_used: Optional[Sequence[str]] = None,
                       cards_missing: Optional[Sequence[str]] = None,
                       per_phase_metrics: Optional[list] = None,
                       figures: Optional[list] = None,
                       axis_labels: Optional[dict] = None,
                       modality_scope: Optional[dict] = None,
                       claim_chips_by_subtype: Optional[list] = None,
                       canonical_polarity_override: Optional[str] = None) -> dict:
    """Assemble the canonical `skill_report`. Pure projection over already-computed objects; never moves
    a verdict. `verdict` is None for gateless skills. See docs/UNIFIED_OUTPUT_CONTRACT.md."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    hb = headline_block or {}
    hb_verdict = hb.get("verdict") or {}
    honest_phrase = hb_verdict.get("phrase") or hb.get("headline_text")
    return {
        "call": verdict,
        "role": role,
        "polarity": canonical_polarity(role, headline_block, canonical_polarity_override),
        "honest_phrase": honest_phrase,
        "confidence": hb.get("confidence"),
        "top_tension": hb.get("top_tension"),
        "claim_chips": _chips_from_claim_vector(claim_vector, axis_labels),
        # the claim vector's NON-ATOM scalars (e.g. presence `homogeneity`), so the spine is a LOSSLESS
        # carrier of the claim vector for rollups that read a scalar coordinate off it. {} when none.
        "claim_scalars": _scalars_from_claim_vector(claim_vector),
        # FOR-WHAT projection (the claim_record's modality_scope): per-channel favorability
        # {small_molecule, biologics, _refinements{...}} for the skills that speak to modality
        # (tractability / surface / safety / dependency-degrader). None when the skill is modality-blind.
        # First-class on the spine so `target_report.modality_fit` rolls it up FROM the report, not a
        # legacy claim_record_shadow reach-in. VERDICT-INERT (a projection, never the recommendation).
        "modality_scope": modality_scope,
        # per-molecular-subtype sub-vector — the skill's per_subgroup panorama rows (stratum ×
        # evidence_state × metric) for its subtype-grain card. `target_report.subtype_convergence` reads
        # this off the spine to detect strata multiple axes agree on (contract §197-223: subtype is a
        # CONDITIONING axis whose rollup is a cross-axis convergence JOIN). None/[] when the skill emits
        # no subtype-grain panorama (the whole-cohort spine). VERDICT-INERT.
        "claim_chips_by_subtype": list(claim_chips_by_subtype) if claim_chips_by_subtype else None,
        "question_table": list(question_table) if question_table else [],
        "per_phase_metrics": list(per_phase_metrics) if per_phase_metrics else [],
        # figures the skill already emits (hero + card plots), made FIRST-CLASS + selectable like text so
        # a renderer can dial text⇄figure per slot. Each: {slot, kind, path, caption}. [] until wired.
        "figures": list(figures) if figures else [],
        "provenance": {
            "driving_rule_id": driving_rule_id,
            "fired_rule_ids": list(fired_rule_ids) if fired_rule_ids else [],
            "cards_used": list(cards_used) if cards_used else [],
            "cards_missing": list(cards_missing) if cards_missing else [],
        },
        "_contract": "docs/UNIFIED_OUTPUT_CONTRACT.md",
    }


__all__ = ["build_skill_report", "canonical_polarity", "ROLES",
           "ROLE_GATING", "ROLE_DESCRIPTIVE", "ROLE_INERT"]
