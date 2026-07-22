#!/usr/bin/env python3
"""tumor-presence — expression/protein presence for a (target, indication).

Consumes 5 wired presence cards (RNA cell-line + tumor, protein cell-line + tumor
per-indication + pan-cancer breadth) + their rule subsets. Emits a data-package output
tree with a rank-ordered presence verdict + per-(measurement, sample_context) sub-verdicts.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
Slice B3 (2026-07-21): + tumor-elevation-breadth (the target-grain tumor signal).
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
    "tumor-elevation-breadth",          # Slice B3 — pan-cancer K-of-N tumor-elevation (target-grain)
    "tumor-expression-distribution",    # Q1 (expression-extraction plan) — per-sample TUMOR RNA
                                        # distribution (bulk_rna x tumor); the per-sample companion to
                                        # expression-tumor-vs-adjacent's cohort aggregate. Its
                                        # distribution summary + figure surface now; mapping its
                                        # tumor_expression_class into the bulk_rna verdict ladder is a
                                        # follow-up rules PR (intersects the subtyping revisit).
]

# --- Measurement × sample-context taxonomy (MODALITY_TAXONOMY.md) -----------
# Each expression/protein card is tagged (in target-contracts) with TWO orthogonal
# axes: `measurement:` (the measurement LAYER — bulk_rna / bulk_protein_ms / ...)
# and `sample_context:` (the biological SAMPLE — cell_line / tumor / normal, added
# 2026-07-21). The presence skill emits ONE sub-verdict PER (measurement,
# sample_context) bucket rather than collapsing them.
#
# WHY BOTH AXES (Slice A2): keying the per-modality view off `measurement:` ALONE
# conflated the cell-line-RNA card (expression-distribution) with the tumor-RNA card
# (expression-tumor-vs-adjacent) — both are `bulk_rna` — so a target-only query
# (only cell-line cards fire) read IDENTICALLY to a target-indication query, hiding
# that the tumor axis was never touched. Bucketing by the PAIR makes the degenerate
# case honest: `bulk_rna/cell_line: measured` alongside `bulk_rna/tumor:
# data_unavailable`. The two axes are genuinely orthogonal (every combination is
# real — see the 2-axis table in MODALITY_TAXONOMY.md).
#
# card_id → (measurement, sample_context) for the cards THIS skill consumes. Mirrors
# the `measurement:` + `sample_context:` tags in target-contracts/cards/*.card.yaml.
# Kept local + explicit rather than parsed at runtime: the skill's card set is fixed
# + small, and a drift guard test asserts this map matches the specs on BOTH axes.
CARD_CONTEXT = {
    "expression-distribution":      ("bulk_rna", "cell_line"),        # DepMap cell-line RNA
    "expression-tumor-vs-adjacent": ("bulk_rna", "tumor"),            # TCGA tumor-vs-adjacent RNA
    "tumor-expression-distribution": ("bulk_rna", "tumor"),           # TCGA per-sample tumor RNA distribution (Q1) — same bucket as tumor-vs-adjacent
    "protein-presence-cptac":       ("bulk_protein_ms", "tumor"),     # CPTAC tumor MS (per-indication)
    "protein-abundance-celline":    ("bulk_protein_ms", "cell_line"), # Gygi cell-line MS
    "tumor-elevation-breadth":      ("bulk_protein_ms", "tumor"),     # CPTAC pan-cancer breadth (target-grain) — same bucket as CPTAC per-indication
}


def _ctx_key(measurement: str, sample_context: str) -> str:
    """The stable string key for a (measurement, sample_context) bucket, e.g.
    `bulk_rna/cell_line`. This is the key surfaced in presence_verdict_by_modality."""
    return f"{measurement}/{sample_context}"


# The enumerated universe of (measurement, sample_context) buckets this skill
# reports on. The four card-backed buckets PLUS the two unbuilt substrates named in
# MODALITY_TAXONOMY.md as explicit gaps: sc_rna in tumor (heterogeneity / minor-
# population presence) and protein_ihc in normal (HPA IHC normal-tissue-safety
# comparator). Buckets with no card emit an explicit `data_unavailable` — a NAMED
# gap, not silence. Ordered for stable, legible output.
ALL_CONTEXTS = (
    ("bulk_rna", "cell_line"),
    ("bulk_rna", "tumor"),
    ("bulk_protein_ms", "cell_line"),
    ("bulk_protein_ms", "tumor"),
    ("sc_rna", "tumor"),          # unbuilt substrate — named gap
    ("protein_ihc", "normal"),    # unbuilt substrate — named gap (HPA IHC safety)
)

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
# detected" is never swallowed. Covers THREE protein cards (CPTAC per-indication
# contrast + Gygi cell-line distribution + pan-cancer breadth). Verdict strings are
# the protein-native classes.
#
# BREADTH placement (Slice B3): the pan-cancer breadth verdicts rank BELOW the
# per-indication/abundance positives — when a target-INDICATION query fires both the
# specific CPTAC strong_up AND the pan-cancer breadth, the specific per-indication
# call wins (more decision-relevant). But in a target-ONLY query, breadth is the ONLY
# protein-tumor card that fires, so it gives that bucket a real `measured` verdict
# instead of data_unavailable — the degenerate-case fix. Ranked above the downs/
# killers (breadth is never a killer — un-elevated protein may still be present).
_PROTEIN_RANK: list[tuple[str, str]] = [
    ("protein-strongly-up-supportive",                  "protein_strongly_upregulated"),
    ("protein-abundance-broadly-high-supportive",       "protein_broadly_high"),
    ("protein-abundance-lineage-restricted-supportive", "protein_lineage_restricted"),
    ("protein-modestly-up-neutral",                     "protein_modestly_upregulated"),
    ("tumor-breadth-broadly-supportive",                "broadly_tumor_elevated"),
    ("tumor-breadth-multi-supportive",                  "multi_tumor_elevated"),
    ("protein-abundance-broadly-moderate-neutral",      "protein_broadly_moderate"),
    ("tumor-breadth-single-neutral",                    "single_tumor_elevated"),
    ("tumor-breadth-not-elevated-neutral",              "not_tumor_elevated"),
    ("protein-strongly-down-opposing",                  "protein_strongly_downregulated"),
    ("protein-not-detected-degrader-killer",            "protein_not_detected"),
    ("protein-abundance-broadly-low-degrader-killer",   "protein_broadly_low"),
    ("protein-data-unavailable-insufficient",           "data_unavailable"),
    ("protein-abundance-data-unavailable-insufficient", "data_unavailable"),
    ("tumor-breadth-data-unavailable-insufficient",     "data_unavailable"),
]

# Per-MEASUREMENT ladder selection. The rule VOCABULARY (which rules can fire) is a
# function of the measurement LAYER only — bulk_rna cards fire `expression-*` rules,
# bulk_protein_ms cards fire `protein-*` rules. `sample_context` NEVER changes which
# rules exist (a cell-line-RNA card and a tumor-RNA card both fire expression rules),
# so the ladder is keyed by measurement alone even though the BUCKET is keyed by the
# (measurement, sample_context) pair. Measurements without a card (sc_rna, protein_ihc)
# have no ladder → their buckets emit data_unavailable in _per_modality_verdicts.
_MEASUREMENT_RANK: dict[str, list[tuple[str, str]]] = {
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
    """Slice A2 (MODALITY_TAXONOMY.md): one sub-verdict PER (measurement,
    sample_context) bucket.

    Groups fired rules by the (measurement, sample_context) PAIR of the card that
    fired them (via CARD_CONTEXT), then ranks WITHIN each group using the ladder for
    that group's MEASUREMENT (the rule vocabulary depends on the measurement layer,
    not the sample context — see _MEASUREMENT_RANK). Buckets in the taxonomy but with
    no card in this skill (sc_rna/tumor, protein_ihc/normal) emit an explicit
    `data_unavailable` — a NAMED coverage gap, never silence. Returned as a map keyed
    by `measurement/sample_context` string (e.g. `bulk_rna/cell_line`):
        {bucket_key: {measurement, sample_context, verdict, driving_rule_id,
                      evidence_state}}
    where evidence_state ∈ {measured, data_unavailable}. Additive: does NOT touch
    the collapsed presence_verdict.

    KEY-SHAPE CHANGE (2026-07-21): keys were bare measurement strings (`bulk_rna`);
    they are now `measurement/sample_context` pairs so a cell-line-RNA signal is
    never conflated with a tumor-RNA signal (the degenerate-case fix). The bucket
    now carries `measurement` + `sample_context` as explicit fields too."""
    by_ctx: dict[tuple[str, str], list[dict]] = {}
    for r in fired:
        ctx = CARD_CONTEXT.get(r.get("card_id"))
        if ctx:
            by_ctx.setdefault(ctx, []).append(r)

    out: dict[str, dict] = {}
    for measurement, sample_context in ALL_CONTEXTS:
        key = _ctx_key(measurement, sample_context)
        group = by_ctx.get((measurement, sample_context), [])
        if group:
            # rank WITHIN the bucket using the MEASUREMENT's ladder — bulk_protein_ms
            # must rank against _PROTEIN_RANK, not the expression ladder (the C1 bug
            # was ranking protein rules against expression-only rule_ids → insufficient).
            v, drv = _rank_verdict(group, _MEASUREMENT_RANK.get(measurement))
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": v, "driving_rule_id": drv,
                        "evidence_state": "measured"}
        else:
            # No card for this bucket in this skill (sc_rna/tumor, protein_ihc/normal),
            # OR a tagged card produced no fired rule. Either way: not measured here.
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": "data_unavailable", "driving_rule_id": None,
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
        # Slice A2: per-(measurement, sample_context) sub-verdicts. Keyed
        # `measurement/sample_context` (e.g. bulk_rna/cell_line, bulk_rna/tumor) so a
        # cell-line signal is never conflated with a tumor signal. A target-only query
        # now honestly reads `bulk_rna/cell_line: measured` + `bulk_rna/tumor:
        # data_unavailable`. sc_rna/tumor + protein_ihc/normal are explicit
        # data_unavailable — named gaps, not silence.
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
        # Slice B3: the pan-cancer tumor-elevation breadth (target-grain) — the one
        # tumor-context presence signal available to a target-ONLY query.
        "tumor_elevation_breadth_class": _get("tumor-elevation-breadth",
                                              "tumor_elevation_breadth_class"),
        "tumor_elevation_n_cohorts_elevated": _get("tumor-elevation-breadth",
                                                   "n_cohorts_elevated"),
        "tumor_elevation_n_cohorts_tested": _get("tumor-elevation-breadth",
                                                 "n_cohorts_tested"),
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
