#!/usr/bin/env python3
"""tumor-presence — expression status for a single (target, indication).

Consumes 2 wired expression cards + expression-* rule subset. Emits a
data-package output tree with a rank-ordered presence verdict.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.1.0"

CARDS = [
    "expression-distribution",
    "expression-tumor-vs-adjacent",
    "protein-presence-cptac",           # Layer 6c addition
    "protein-abundance-celline",        # E3b — bulk_protein_ms x cell_line (Gygi TMT MS)
]

# --- Measurement-modality taxonomy (MODALITY_TAXONOMY.md, Slice Y) ----------
# Each expression card is tagged (in target-contracts) with a `measurement:`
# substrate. The presence skill emits ONE sub-verdict PER modality rather than
# collapsing them, so "bulk_rna: supportive, protein_ihc: data_unavailable" is a
# distinct, legible epistemic state from full concordance (the whole point of the
# taxonomy — surface concordance/disagreement, never average it away).
#
# card_id → modality for the cards THIS skill consumes. Mirrors the `measurement:`
# tags in target-contracts/cards/*.card.yaml (verified 2026-07-20). Kept local +
# explicit rather than parsed from the card specs at runtime: the skill's card set
# is fixed + small, and a drift guard test asserts this map matches the specs.
CARD_MODALITY = {
    "expression-distribution":      "bulk_rna",
    "expression-tumor-vs-adjacent": "bulk_rna",
    "protein-presence-cptac":       "bulk_protein_ms",   # tumor MS (CPTAC)
    "protein-abundance-celline":    "bulk_protein_ms",   # cell-line MS (Gygi) — same substrate
}

# The four modalities in the taxonomy. Those with no card in this skill emit an
# explicit `data_unavailable` sub-verdict — a NAMED gap, not silence (sc_rna +
# protein_ihc are the two unbuilt substrates per MODALITY_TAXONOMY.md).
ALL_MODALITIES = ("bulk_rna", "bulk_protein_ms", "sc_rna", "protein_ihc")

QUESTION = ("Is {target} expressed in {indication} tumor tissue, and how "
            "does its expression distribute across cancer cell lines vs. "
            "paired tumor/adjacent samples?")


# Verdict rank order (highest-precedence first). rule_id → verdict_string.
# TWO ladders, one per measurement substrate — the bulk_rna cards fire `expression-*`
# rules; the bulk_protein_ms cards fire `protein-*` rules (CPTAC tumor-vs-normal
# contrast vocab) + `protein-abundance-*` rules (cell-line distribution vocab). A
# single expression-only ladder SWALLOWED the entire bulk_protein_ms modality —
# protein rules matched nothing and every protein-only target collapsed to
# `insufficient`, silently dropping even a protein-not-detected killer (C1 fix
# 2026-07-20; regression introduced when the protein cards were added to CARDS +
# CARD_MODALITY in the per-modality refactor without teaching the ladder their rules).
_EXPRESSION_RANK: list[tuple[str, str]] = [
    ("expression-broadly-high-supportive",              "broadly_high_expression"),
    ("expression-strong-upregulation-supportive",       "strongly_upregulated_in_tumor"),
    ("expression-lineage-restricted-supportive",        "lineage_restricted"),
    ("expression-modest-upregulation-neutral",          "modestly_upregulated_in_tumor"),
    ("expression-broadly-moderate-neutral",             "broadly_moderate_expression"),
    ("expression-broadly-low-degrader-killer",          "broadly_low_expression"),
    ("expression-call-not-informative-degrader-killer", "not_informative"),
    ("expression-data-unavailable-insufficient",        "data_unavailable"),
    ("expression-call-data-unavailable-insufficient",   "data_unavailable"),
]

# bulk_protein_ms ladder. Presence-positive tiers first; measured-absence (the
# degrader killers) ranked ABOVE data_unavailable so a measured "protein not
# detected" is never swallowed. Covers BOTH protein cards (CPTAC contrast +
# cell-line distribution). Verdict strings are the protein-native classes.
_PROTEIN_RANK: list[tuple[str, str]] = [
    ("protein-strongly-up-supportive",                  "protein_strongly_upregulated"),
    ("protein-abundance-broadly-high-supportive",       "protein_broadly_high"),
    ("protein-abundance-lineage-restricted-supportive", "protein_lineage_restricted"),
    ("protein-modestly-up-neutral",                     "protein_modestly_upregulated"),
    ("protein-abundance-broadly-moderate-neutral",      "protein_broadly_moderate"),
    ("protein-strongly-down-opposing",                  "protein_strongly_downregulated"),
    ("protein-not-detected-degrader-killer",            "protein_not_detected"),
    ("protein-abundance-broadly-low-degrader-killer",   "protein_broadly_low"),
    ("protein-data-unavailable-insufficient",           "data_unavailable"),
    ("protein-abundance-data-unavailable-insufficient", "data_unavailable"),
]

# Per-modality ladder selection. Modalities without a card in this skill (sc_rna,
# protein_ihc) have no ladder → they emit data_unavailable in _per_modality_verdicts.
_MODALITY_RANK: dict[str, list[tuple[str, str]]] = {
    "bulk_rna": _EXPRESSION_RANK,
    "bulk_protein_ms": _PROTEIN_RANK,
}

# Collapsed ladder = expression FIRST (RNA is the presence backbone; keeps existing
# RNA-target verdicts byte-stable), then protein appended BELOW. Strictly additive:
# an RNA-target still resolves on an expression rule (wins first); a protein-ONLY
# target now gets a real verdict instead of the silent `insufficient` collapse.
_VERDICT_RANK: list[tuple[str, str]] = _EXPRESSION_RANK + _PROTEIN_RANK


def _rank_verdict(fired: list[dict], ladder: list[tuple[str, str]] | None = None) -> tuple[str, str | None]:
    """Rank-ordered verdict from a set of fired rules against a ladder (default =
    the collapsed expression+protein ladder)."""
    ladder = ladder if ladder is not None else _VERDICT_RANK
    fired_by_id = {r["rule_id"]: r for r in fired}
    for rid, verdict in ladder:
        if rid in fired_by_id:
            return verdict, rid
    return "insufficient", None


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """COLLAPSED presence verdict across ALL modalities — the audit spine the
    target-profile consumer + risk table read as `verdict`. Expression-primary
    (RNA backbone, byte-stable for RNA targets); protein rules append below so a
    protein-only target resolves instead of collapsing to insufficient (C1 fix)."""
    return _rank_verdict(fired)


def _per_modality_verdicts(fired: list[dict]) -> dict[str, dict]:
    """Slice-Y (MODALITY_TAXONOMY.md): one sub-verdict PER measurement modality.

    Groups fired rules by the `measurement:` substrate of the card that fired
    them (via CARD_MODALITY), then ranks WITHIN each group using the same ladder
    as the collapsed verdict. Modalities present in the taxonomy but with no card
    in this skill (sc_rna, protein_ihc) emit an explicit `data_unavailable` —
    a NAMED coverage gap, never silence. Returned as a map:
        {modality: {verdict, driving_rule_id, evidence_state}}
    where evidence_state ∈ {measured, data_unavailable}. Additive: does NOT touch
    the collapsed presence_verdict."""
    by_modality: dict[str, list[dict]] = {}
    for r in fired:
        mod = CARD_MODALITY.get(r.get("card_id"))
        if mod:
            by_modality.setdefault(mod, []).append(r)

    out: dict[str, dict] = {}
    for mod in ALL_MODALITIES:
        group = by_modality.get(mod, [])
        if group:
            # rank WITHIN the modality using ITS OWN ladder — bulk_protein_ms must
            # rank against _PROTEIN_RANK, not the expression ladder (the C1 bug was
            # ranking the protein group against expression-only rule_ids → insufficient).
            v, drv = _rank_verdict(group, _MODALITY_RANK.get(mod))
            out[mod] = {"verdict": v, "driving_rule_id": drv,
                        "evidence_state": "measured"}
        else:
            # No card for this modality in this skill (sc_rna / protein_ihc), OR a
            # tagged card produced no fired rule. Either way: not measured here.
            out[mod] = {"verdict": "data_unavailable", "driving_rule_id": None,
                        "evidence_state": "data_unavailable"}
    return out


def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    per_modality = _per_modality_verdicts(fired)
    return {
        # COLLAPSED verdict — the audit spine target-profile reads as `verdict`.
        # Byte-stable across the Slice-Y refactor (F1-safe: additive).
        "presence_verdict":         v,
        "driving_rule_id":          drv,
        # Slice-Y: per-measurement-modality sub-verdicts. Concordance/disagreement
        # is now legible (bulk_rna supportive + protein_ihc data_unavailable is a
        # distinct epistemic state from full concordance). sc_rna + protein_ihc are
        # explicit data_unavailable — named gaps, not silence.
        "presence_verdict_by_modality": per_modality,
        "median_log2tpm_panel":     _get("expression-distribution",
                                          "median_log2tpm_panel"),
        "expression_call_class":    _get("expression-distribution",
                                          "expression_call_class"),
        "tva_log2_fc":              _get("expression-tumor-vs-adjacent", "log2_fc"),
        "tva_q_value":              _get("expression-tumor-vs-adjacent", "q_value"),
        "tva_expression_call":      _get("expression-tumor-vs-adjacent",
                                          "expression_call_class"),
        "protein_expression_class": _get("protein-presence-cptac",
                                          "protein_expression_class"),
        "protein_effect_size":      _get("protein-presence-cptac",
                                          "protein_effect_size"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
    ))
