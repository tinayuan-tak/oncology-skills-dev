#!/usr/bin/env python3
"""tumor-presence — expression/protein presence for a (target, indication).

Consumes 10 wired cards in two tiers (see CARDS below + SKILL.md):
  VERDICT-BEARING (5, feed the presence ladder): cellline-rna-distribution (cell-line RNA),
    expression-tumor-vs-adjacent (tumor RNA), protein-presence-cptac (tumor protein),
    protein-abundance-celline (cell-line protein), tumor-elevation-breadth (pan-cancer target-grain).
  DISPLAY-ONLY facets (5, feed NO resolver — verdict byte-stable): tumor-expression-distribution,
    tumor-expression-distribution-subtype, expression-purity-confound, phospho-pathway-activity,
    rna-protein-concordance.
Emits a data-package output tree with a rank-ordered presence verdict + per-(measurement,
sample_context) sub-verdicts.

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
Slice B3 (2026-07-21): + tumor-elevation-breadth (the target-grain tumor signal).
Card roster grew 2->10 across the expression-extraction plan (Q1/Q5/Q8/Q9 + protein + breadth + subtype).
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.1.0"

CARDS = [
    "cellline-rna-distribution",
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
    "tumor-expression-distribution-subtype",  # target_subtype-grain sibling — the per-molecular-subtype
                                        # panorama (per_subgroup_metrics, compute-all). Surfaces the
                                        # subtype landscape + faceted panel; subtype_signal is
                                        # confidence/context (NOT a veto — one-directional gate). Same
                                        # (bulk_rna, tumor) bucket as the pooled card.
    "expression-purity-confound",       # Q9 (2026-07-23) — is the TUMOR presence signal tumor-cell-
                                        # intrinsic or microenvironment (stromal/immune)-driven? A
                                        # purity-confound CAVEAT on the tumor presence call (correlates
                                        # per-sample tumor expression vs ABSOLUTE purity). ADDITIVE
                                        # render facet — its purity_confound_class + rules feed NO
                                        # resolver ladder (presence verdict byte-stable). The ADC/TCE
                                        # antigen-reality (modality-gate) facet is DEFERRED to P4.
    "phospho-pathway-activity",         # Q8 (2026-07-23) — target biology at the PHOSPHO level (CPTAC
                                        # phosphoproteomics): is it phosphorylated (pathway-activity
                                        # proxy) beyond total abundance? The sharpest presence signal
                                        # for kinases/signaling. ADDITIVE render facet — phospho_activity_class
                                        # + rules feed NO resolver (presence verdict byte-stable). Same
                                        # (bulk_protein_ms, tumor) bucket as protein-presence-cptac.
    "rna-protein-concordance",          # Q5 (2026-07-23 composition) — rna_as_biomarker: is RNA an
                                        # adequate PROXY for protein presence (cell-line arm)? A
                                        # presence-proxy QUALITY qualifier on the RNA presence read +
                                        # the biomarker facet's preferred_assay input. ADDITIVE render
                                        # facet — its rna-protein-* rules feed NO resolver (presence
                                        # verdict byte-stable). (bulk_rna, cell_line) bucket.
]

# --- Measurement × sample-context taxonomy (MODALITY_TAXONOMY.md) -----------
# Each expression/protein card is tagged (in target-contracts) with TWO orthogonal
# axes: `measurement:` (the measurement LAYER — bulk_rna / bulk_protein_ms / ...)
# and `sample_context:` (the biological SAMPLE — cell_line / tumor / normal, added
# 2026-07-21). The presence skill emits ONE sub-verdict PER (measurement,
# sample_context) bucket rather than collapsing them.
#
# WHY BOTH AXES (Slice A2): keying the per-modality view off `measurement:` ALONE
# conflated the cell-line-RNA card (cellline-rna-distribution) with the tumor-RNA card
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
    "cellline-rna-distribution":      ("bulk_rna", "cell_line"),        # DepMap cell-line RNA
    "expression-tumor-vs-adjacent": ("bulk_rna", "tumor"),            # TCGA tumor-vs-adjacent RNA
    "tumor-expression-distribution": ("bulk_rna", "tumor"),           # TCGA per-sample tumor RNA distribution (Q1) — same bucket as tumor-vs-adjacent
    "tumor-expression-distribution-subtype": ("bulk_rna", "tumor"),   # per-subtype panorama of the same — same (bulk_rna, tumor) bucket
    "protein-presence-cptac":       ("bulk_protein_ms", "tumor"),     # CPTAC tumor MS (per-indication)
    "protein-abundance-celline":    ("bulk_protein_ms", "cell_line"), # Gygi cell-line MS
    "tumor-elevation-breadth":      ("bulk_protein_ms", "tumor"),     # CPTAC pan-cancer breadth (target-grain) — same bucket as CPTAC per-indication
    "expression-purity-confound":   ("bulk_rna", "tumor"),            # Q9 — derived from TCGA per-sample tumor bulk RNA (× ABSOLUTE purity); (bulk_rna, tumor) bucket. A render-facet CAVEAT, not a presence reading — its rules emit no presence sub-verdict.
    "phospho-pathway-activity":     ("bulk_protein_ms", "tumor"),     # Q8 — CPTAC phosphoproteomics (tumor MS); (bulk_protein_ms, tumor) bucket, same as protein-presence-cptac. A render-facet pathway-activity readout, not a presence sub-verdict.
    "rna-protein-concordance":      ("bulk_rna", "cell_line"),        # Q5 — cell-line RNA-vs-protein concordance (rna_as_biomarker); (bulk_rna, cell_line) bucket, same as cellline-rna-distribution. A render-facet proxy-quality qualifier, not a presence sub-verdict.
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
    # ── Per-sample TUMOR RNA (tumor-expression-distribution) + the tumor-vs-adjacent DOWN reads ──
    # APPENDED 2026-08-04 (Finding B): these tumor-context rules were emitted by live cards but were
    # NOT in the ladder, so the bulk_rna/tumor bucket resolved `insufficient` even with real tumor-RNA
    # data (verified: EGFR/COADREAD, tumor median log2TPM 3.28 on 669 samples → insufficient). Placed
    # BELOW every pre-existing measured rule so NO currently-resolving verdict changes (the higher
    # existing rule always wins the collapsed spine) — purely additive: targets that previously fired
    # ONLY these (→ insufficient) now resolve, and the per-modality bulk_rna/tumor bucket (which sees
    # only tumor-context rules) now produces a real presence verdict. Presence semantics: absolute
    # tumor presence (broadly_expressed) outranks the differential DOWN reads — a target modestly lower
    # than adjacent normal is still PRESENT (the down signal is a selectivity concern for the modality
    # lens, not an absence). tumor-expression-broadly-low is NEUTRAL not a killer (per-INDICATION low
    # cannot kill a target-wide nomination — the card's own rationale).
    ("tumor-expression-broadly-high-supportive",        "tumor_broadly_expressed"),
    ("tumor-expression-broadly-moderate-neutral",       "tumor_moderately_expressed"),
    ("tumor-expression-broadly-low-neutral",            "tumor_sparsely_expressed"),
    ("expression-modest-downregulation-opposing",       "modestly_downregulated_in_tumor"),
    ("expression-strong-downregulation-degrader-killer", "strongly_downregulated_in_tumor"),
    # ── coverage gaps sink to the bottom (measured-first invariant) ──
    ("expression-data-unavailable-insufficient",        "data_unavailable"),
    ("expression-call-data-unavailable-insufficient",   "data_unavailable"),
    ("tumor-expression-data-unavailable-insufficient",  "data_unavailable"),
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

# Collapsed ladder. Naive concatenation (_EXPRESSION_RANK + _PROTEIN_RANK) is WRONG:
# it places expression's two `data_unavailable` entries ABOVE every protein rule, so a
# protein-ONLY target (expression data_unavailable, but CPTAC reads strong_up or a
# not_detected killer) resolves to `data_unavailable` — silently discarding the measured
# protein signal (the exact cross-modality-swallow the per-ladder C1 fix does NOT cover).
#
# Correct order: ALL measured rules first (expression measured, then protein measured —
# RNA stays the backbone so existing RNA-target verdicts are byte-stable), then EVERY
# `data_unavailable` entry sinks to the bottom. A measured protein call therefore always
# outranks an expression coverage-gap, while an RNA target still resolves on its
# expression rule first (measured expression precedes measured protein).
def _partition_measured(ladder: list[tuple[str, str]]) -> tuple[list, list]:
    measured = [(rid, v) for rid, v in ladder if v != "data_unavailable"]
    gap = [(rid, v) for rid, v in ladder if v == "data_unavailable"]
    return measured, gap


_EXPR_MEASURED, _EXPR_GAP = _partition_measured(_EXPRESSION_RANK)
_PROT_MEASURED, _PROT_GAP = _partition_measured(_PROTEIN_RANK)
_VERDICT_RANK: list[tuple[str, str]] = (
    _EXPR_MEASURED + _PROT_MEASURED + _EXPR_GAP + _PROT_GAP
)


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
        "median_log2tpm_panel":     get_card_field(cards, "cellline-rna-distribution",
                                          "median_log2tpm_panel"),
        "expression_call_class":    get_card_field(cards, "cellline-rna-distribution",
                                          "expression_call_class"),
        "tva_log2_fc":              get_card_field(cards, "expression-tumor-vs-adjacent", "log2_fc"),
        "tva_q_value":              get_card_field(cards, "expression-tumor-vs-adjacent", "q_value"),
        "tva_expression_call":      get_card_field(cards, "expression-tumor-vs-adjacent",
                                          "expression_call_class"),
        "protein_expression_class": get_card_field(cards, "protein-presence-cptac",
                                          "protein_expression_class"),
        "protein_effect_size":      get_card_field(cards, "protein-presence-cptac",
                                          "protein_effect_size"),
        # Slice B3: the pan-cancer tumor-elevation breadth (target-grain) — the one
        # tumor-context presence signal available to a target-ONLY query.
        "tumor_elevation_breadth_class": get_card_field(cards, "tumor-elevation-breadth",
                                              "tumor_elevation_breadth_class"),
        "tumor_elevation_n_cohorts_elevated": get_card_field(cards, "tumor-elevation-breadth",
                                                   "n_cohorts_elevated"),
        "tumor_elevation_n_cohorts_tested": get_card_field(cards, "tumor-elevation-breadth",
                                                 "n_cohorts_tested"),
        # Q9 purity confound — is the tumor presence signal tumor-intrinsic or microenvironment?
        # (render facet; does NOT feed the presence verdict — additive, spine byte-stable)
        "purity_confound_class":    get_card_field(cards, "expression-purity-confound", "purity_confound_class"),
        "expression_purity_pearson_r": get_card_field(cards, "expression-purity-confound", "expression_purity_pearson_r"),
        # Q8 phospho pathway activity — protein/pathway-level presence (render facet, byte-stable)
        "phospho_activity_class":   get_card_field(cards, "phospho-pathway-activity", "phospho_activity_class"),
        "n_phosphosites":           get_card_field(cards, "phospho-pathway-activity", "n_phosphosites"),
        # Q5 rna_as_biomarker — RNA-as-proxy-for-protein quality (render facet + biomarker preferred_assay input)
        "rna_as_biomarker":         get_card_field(cards, "rna-protein-concordance", "rna_as_biomarker"),
        "rna_protein_r":            get_card_field(cards, "rna-protein-concordance", "rna_protein_r"),
        # SUBTYPE SCOPE (Finding A, 2026-08-04) — the per-molecular-subtype presence landscape from
        # tumor-expression-distribution-subtype, ELEVATED into the audit spine so the subtype scope is
        # visible here, not just in a side table (_per_subgroup_metrics.csv). One-directional / non-veto
        # (like the other facets — feeds NO resolver ladder; presence_verdict byte-stable). Degrades
        # honestly: subtype_scope_available=False for indications with no landed assignment shard
        # (only COADREAD today) — a NAMED gap, not silence.
        "subtype_scope_available":  get_card_field(cards, "tumor-expression-distribution-subtype", "subtype_axis_available"),
        "n_subtypes_measured":      get_card_field(cards, "tumor-expression-distribution-subtype", "n_subtypes_measured"),
        "n_subtypes_enriched":      get_card_field(cards, "tumor-expression-distribution-subtype", "n_subtypes_enriched"),
        "spotlight_subtype":        get_card_field(cards, "tumor-expression-distribution-subtype", "spotlight_subtype"),
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
