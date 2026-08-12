#!/usr/bin/env python3
"""tumor-presence — expression/protein presence for a (target, indication).

Consumes 13 wired cards in two tiers (see CARDS below + SKILL.md):
  VERDICT-BEARING (7, feed the presence ladders): cellline-rna-distribution (cell-line RNA),
    tumor-rna-vs-adjacent (tumor RNA), tumor-rna-distribution (per-sample tumor RNA — its
    tumor-expression-* rules ARE in the bulk_rna ladder; reclassified from display-only 2026-08-07),
    tumor-protein-abundance-cptac (tumor protein), cellline-protein-abundance (cell-line protein),
    tumor-elevation-breadth (pan-cancer target-grain),
    tumor-scrna-celltype-expression (single-cell per-compartment tumor presence — sc_rna/tumor).
  DISPLAY-ONLY facets (4, feed NO resolver — verdict byte-stable):
    tumor-rna-distribution-by-subtype, expression-purity-confound, cellline-rna-protein-concordance,
    normal-tissue-liability (protein_ihc/normal SAFETY COMPARATOR — P8.3, closes the last named gap).
  SAFETY COMPARATORS (2, verdict-inert — safety ruled by surface-modality-fit): normal-tissue-liability
    (protein_ihc/normal — HPA IHC, P8.3), sc-normal-celltype-expression (sc_rna/normal — scRNA Phase 3.3).
  (phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology: an ACTIVITY /
   signaling-state readout, not a presence/abundance signal — it belongs with the mechanism lens.)
Emits a data-package output tree with a rank-ordered presence verdict + per-(measurement,
sample_context) sub-verdicts across THREE measurement ladders (bulk_rna, bulk_protein_ms, sc_rna).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
Slice B3 (2026-07-21): + tumor-elevation-breadth (the target-grain tumor signal).
Card roster grew 2->10 across the expression-extraction plan (Q1/Q5/Q8/Q9 + protein + breadth + subtype).
sc_rna slice (2026-08-04): + tumor-scrna-celltype-expression — fills the sc_rna/tumor bucket that
  MODALITY_TAXONOMY.md named as an unbuilt gap (single-cell per-compartment presence + malignant-vs-
  microenvironment attribution; a 3rd measurement ladder _SC_RNA_RANK). 10->11 cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.4.0"   # 2026-08-08 — graduate RNA→protein TUMOR concordance arm (rna-protein-concordance-tumor);
                          # tumor rna_as_biomarker now the preferred input to bulk_rna_proxy_quality. Display-only,
                          # presence verdict byte-stable. (1.3.0 = Phase 3.3 sc-normal sc_rna/normal comparator.)

CARDS = [
    "cellline-rna-distribution",
    "tumor-rna-vs-adjacent",
    "tumor-protein-abundance-cptac",           # Layer 6c addition
    "cellline-protein-abundance",        # E3b — bulk_protein_ms x cell_line (Gygi TMT MS)
    "tumor-elevation-breadth",          # Slice B3 — pan-cancer K-of-N tumor-elevation (target-grain)
    "tumor-rna-distribution",    # Q1 (expression-extraction plan) — per-sample TUMOR RNA
                                        # distribution (bulk_rna x tumor); the per-sample companion to
                                        # tumor-rna-vs-adjacent's cohort aggregate. VERDICT-BEARING: its
                                        # tumor_expression_class maps into the bulk_rna ladder via the
                                        # tumor-expression-* rules (_EXPRESSION_RANK below) →
                                        # tumor_broadly/moderately/sparsely_expressed. (2026-08-07: the
                                        # "follow-up rules PR" this comment once anticipated HAS landed.)
    "tumor-rna-distribution-by-subtype",  # target_subtype-grain sibling — the per-molecular-subtype
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
    # (phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology: phosphorylation is
    #  an ACTIVITY / signaling-STATE readout, not a presence/abundance signal — it presupposes
    #  presence rather than measuring it. It belongs with the mechanism lens, not the expression lens.
    #  The distinction sharpened once tumor-presence synthesis became an expression-RELEVANCE judge.)
    "cellline-rna-protein-concordance",          # Q5 (2026-07-23 composition) — rna_as_biomarker: is RNA an
                                        # adequate PROXY for protein presence (cell-line arm)? A
                                        # presence-proxy QUALITY qualifier on the RNA presence read +
                                        # the biomarker facet's preferred_assay input. ADDITIVE render
                                        # facet — its rna-protein-* rules feed NO resolver (presence
                                        # verdict byte-stable). (bulk_rna, cell_line) bucket.
    "rna-protein-concordance-tumor",             # Q5 TUMOR arm (2026-08-08 graduation) — the TUMOR-grain
                                        # sibling: does RNA proxy PROTEIN in PATIENT TUMORS (CPTAC), from
                                        # the matched cptac-rna-protein-matched-per-sample-v1 product? The
                                        # substrate + method (build_tumor_summary) + dispatcher ALL pre-
                                        # existed; only the skill roster + proxy-qualifier wiring were
                                        # missing. This is the number an RNA-based presence claim IN A
                                        # PATIENT actually rests on — bulk-tumor purity/stroma/post-
                                        # transcriptional regulation degrade it far more than in cell lines
                                        # (EPCAM/COAD partial_proxy r=0.46 vs cell-line adequate r=0.86;
                                        # KRAS/COAD r≈0.01). ADDITIVE render facet — feeds NO resolver
                                        # (presence verdict byte-stable); (bulk_rna, tumor) bucket. Its
                                        # rna_as_biomarker (tumor) is the PREFERRED input to
                                        # _bulk_rna_proxy_quality (falls back to the cell-line arm).
    "tumor-scrna-celltype-expression",  # sc_rna slice (2026-08-04) — SINGLE-CELL per-compartment tumor
                                        # presence (sc_rna x tumor). VERDICT-BEARING: fills the
                                        # sc_rna/tumor bucket MODALITY_TAXONOMY.md named as an unbuilt gap.
                                        # Malignant-anchored sc_expression_class → the _SC_RNA_RANK ladder.
                                        # Adds two signals bulk can't: detection_fraction (in how many
                                        # cells) + malignant-vs-microenvironment attribution. v1: COADREAD
                                        # + NSCLC (other indications → data_unavailable, honest).
    "normal-tissue-liability",          # P8.3 (2026-08-05) — HPA IHC normal-tissue protein footprint
                                        # (measurement: protein_ihc, sample_context: normal). Fills the
                                        # LAST hardcoded data_unavailable bucket in ALL_CONTEXTS
                                        # (protein_ihc/normal). This is the normal-tissue-safety COMPARATOR
                                        # the bucket was reserved for — NOT a tumor-presence signal: it
                                        # feeds NO presence ladder + is verdict-inert (the presence spine
                                        # is byte-stable). The safety VERDICT stays owned by
                                        # on-target-safety-liability (P7 axis-separation boundary); here it
                                        # is a labeled comparator so the (protein_ihc, normal) context is a
                                        # real read, not silence.
    "sc-normal-celltype-expression",    # Phase 3.3 (2026-08-07) — scRNA cell-type-resolved normal-tissue
                                        # safety (measurement: sc_rna, sample_context: normal). Fills the
                                        # sc_rna/normal COMPARATOR bucket. NOT a tumor-presence signal.
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
# (tumor-rna-vs-adjacent) — both are `bulk_rna` — so a target-only query
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
    "tumor-rna-vs-adjacent": ("bulk_rna", "tumor"),            # TCGA tumor-vs-adjacent RNA
    "tumor-rna-distribution": ("bulk_rna", "tumor"),           # TCGA per-sample tumor RNA distribution (Q1) — same bucket as tumor-vs-adjacent
    "tumor-rna-distribution-by-subtype": ("bulk_rna", "tumor"),   # per-subtype panorama of the same — same (bulk_rna, tumor) bucket
    "tumor-protein-abundance-cptac":       ("bulk_protein_ms", "tumor"),     # CPTAC tumor MS (per-indication)
    "cellline-protein-abundance":    ("bulk_protein_ms", "cell_line"), # Gygi cell-line MS
    "tumor-elevation-breadth":      ("bulk_protein_ms", "tumor"),     # CPTAC pan-cancer breadth (target-grain) — same bucket as CPTAC per-indication
    "expression-purity-confound":   ("bulk_rna", "tumor"),            # Q9 — derived from TCGA per-sample tumor bulk RNA (× ABSOLUTE purity); (bulk_rna, tumor) bucket. A render-facet CAVEAT, not a presence reading — its rules emit no presence sub-verdict.
    # phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology (activity, not presence).
    "cellline-rna-protein-concordance":      ("bulk_rna", "cell_line"),        # Q5 — cell-line RNA-vs-protein concordance (rna_as_biomarker); (bulk_rna, cell_line) bucket, same as cellline-rna-distribution. A render-facet proxy-quality qualifier, not a presence sub-verdict.
    "rna-protein-concordance-tumor":         ("bulk_rna", "tumor"),            # Q5 tumor arm — CPTAC per-tumor RNA-vs-protein concordance (rna_as_biomarker, tumor); (bulk_rna, tumor) bucket. A render-facet proxy-quality qualifier, not a presence sub-verdict (feeds no ladder; presence verdict byte-stable).
    "tumor-scrna-celltype-expression": ("sc_rna", "tumor"),                   # sc_rna slice — single-cell per-compartment tumor presence; the FIRST card in the sc_rna/tumor bucket (was a named gap). VERDICT-BEARING via _SC_RNA_RANK.
    "normal-tissue-liability":      ("protein_ihc", "normal"),        # P8.3 — HPA IHC normal-tissue protein footprint; the (protein_ihc, normal) SAFETY COMPARATOR bucket. A render-facet comparator (normal_tissue_breadth_class), NOT a presence sub-verdict — feeds no presence ladder; safety verdict owned by on-target-safety-liability.
    "sc-normal-celltype-expression": ("sc_rna", "normal"),            # Phase 3.3 — scRNA cell-type-resolved normal-tissue safety; the (sc_rna, normal) SAFETY COMPARATOR bucket.
}


def _ctx_key(measurement: str, sample_context: str) -> str:
    """The stable string key for a (measurement, sample_context) bucket, e.g.
    `bulk_rna/cell_line`. This is the key surfaced in presence_verdict_by_modality."""
    return f"{measurement}/{sample_context}"


# The enumerated universe of (measurement, sample_context) buckets this skill
# reports on. The FIVE card-backed buckets (sc_rna/tumor landed 2026-08-04 via the
# tumor-scrna-celltype-expression card) PLUS the one remaining unbuilt substrate named in
# MODALITY_TAXONOMY.md as an explicit gap: protein_ihc in normal (HPA IHC normal-tissue-
# safety comparator). Buckets with no card emit an explicit `data_unavailable` — a NAMED
# gap, not silence. Ordered for stable, legible output.
ALL_CONTEXTS = (
    ("bulk_rna", "cell_line"),
    ("bulk_rna", "tumor"),
    ("bulk_protein_ms", "cell_line"),
    ("bulk_protein_ms", "tumor"),
    ("sc_rna", "tumor"),          # card-backed 2026-08-04 (tumor-scrna-celltype-expression); COADREAD+NSCLC measured, else data_unavailable
    ("sc_rna", "normal"),         # safety comparator 2026-08-07 (sc-normal-celltype-expression)
    ("protein_ihc", "normal"),    # safety comparator P8.3 (normal-tissue-liability HPA IHC)
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
    # ── Per-sample TUMOR RNA (tumor-rna-distribution) + the tumor-vs-adjacent DOWN reads ──
    # APPENDED 2026-08-04 (Finding B): these tumor-context rules were emitted by live cards but were
    # NOT in the ladder, so the bulk_rna/tumor bucket resolved `insufficient` even with real tumor-RNA
    # data (verified: EGFR/COADREAD, tumor median log2TPM 3.28 on 669 samples → insufficient). They
    # rank BELOW the pre-existing PRESENCE-POSITIVE cell-line rules (broadly_high … broadly_moderate)
    # so an established cell-line-present verdict is byte-stable, but ABOVE the expression KILLERS
    # (see the G5 block below). Presence semantics: absolute tumor presence (broadly_expressed)
    # outranks the differential DOWN reads — a target modestly lower than adjacent normal is still
    # PRESENT (the down signal is a selectivity concern for the modality lens, not an absence).
    # tumor-expression-broadly-low is NEUTRAL not a killer (per-INDICATION low cannot kill a
    # target-wide nomination — the card's own rationale).
    ("tumor-expression-broadly-high-supportive",        "tumor_broadly_expressed"),
    ("tumor-expression-broadly-moderate-neutral",       "tumor_moderately_expressed"),
    ("tumor-expression-broadly-low-neutral",            "tumor_sparsely_expressed"),
    ("expression-modest-downregulation-opposing",       "modestly_downregulated_in_tumor"),
    ("expression-strong-downregulation-degrader-killer", "strongly_downregulated_in_tumor"),
    # ── Cell-line / differential EXPRESSION KILLERS rank BELOW every direct tumor-present read ──
    # G5 fix (2026-08-11 production review, VERDICT-MOVING — pending sign-off): these two killers used
    # to sit in the NEUTRAL region ABOVE the tumor-present rungs, so a target broadly-LOW across DepMap
    # cell lines (`expression-broadly-low-degrader-killer`) OR with a non-informative tumor-vs-adjacent
    # differential (`expression-call-not-informative-degrader-killer`) but broadly-HIGH in the actual
    # TCGA tumor collapsed to the killer — a FALSE-NEGATIVE headline for a tumor-PRESENCE question. A
    # direct absolute tumor read now outranks the cell-line-distribution / differential killer.
    # Cell-line-low stays fully legible in its own bulk_rna/cell_line per-modality bucket as a
    # model/degrader caveat; it just no longer overrides the tumor presence call in the collapsed
    # spine. Ranked at the bottom of the measured expression rungs, still above the data_unavailable
    # sink (measured-first invariant preserved).
    ("expression-broadly-low-degrader-killer",          "broadly_low_expression"),
    ("expression-call-not-informative-degrader-killer", "not_informative"),
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
    # G1 fix (2026-08-11 production review): `protein-modestly-down-opposing` fires on
    # tumor-protein-abundance-cptac.protein_expression_class == modest_down (rule at
    # intracellular-intrinsic.rules.yaml:2895) but had NO rung here, so a MEASURED modest protein
    # down-regulation collapsed to `insufficient` and the verdict was UNREACHABLE — a cross-repo
    # half-fix (the contracts rule landed; the skill ladder was never taught it). Mirrors the RNA
    # card's `expression-modest-downregulation-opposing` and ranks above protein strong_down
    # (modest is the milder measured negative), below all positives/neutrals.
    ("protein-modestly-down-opposing",                  "protein_modestly_downregulated"),
    ("protein-strongly-down-opposing",                  "protein_strongly_downregulated"),
    ("protein-not-detected-degrader-killer",            "protein_not_detected"),
    ("protein-abundance-broadly-low-degrader-killer",   "protein_broadly_low"),
    ("protein-data-unavailable-insufficient",           "data_unavailable"),
    ("protein-abundance-data-unavailable-insufficient", "data_unavailable"),
    ("tumor-breadth-data-unavailable-insufficient",     "data_unavailable"),
]

# sc_rna ladder (2026-08-04 sc_rna slice). The single-cell cards fire `sc-expression-*` rules
# (malignant-anchored per-compartment presence, keyed on sc_expression_class). Presence-positive
# tiers first; microenvironment_dominant is NEUTRAL (present in the tumor but not tumor-cell-
# intrinsic — a presence caveat, not an absence) ranked above broadly_low; NO killer (a per-
# indication single-cell read cannot kill a target-wide nomination — same discipline as the bulk
# tumor-RNA rules). data_unavailable sinks to the bottom (measured-first invariant).
_SC_RNA_RANK: list[tuple[str, str]] = [
    ("sc-expression-malignant-broadly-detected-supportive", "sc_malignant_detected"),
    ("sc-expression-microenvironment-dominant-neutral",     "sc_microenvironment_dominant"),
    ("sc-expression-broadly-low-neutral",                   "sc_broadly_low"),
    ("sc-expression-data-unavailable-insufficient",         "data_unavailable"),
]

# Per-MEASUREMENT ladder selection. The rule VOCABULARY (which rules can fire) is a
# function of the measurement LAYER only — bulk_rna cards fire `expression-*` rules,
# bulk_protein_ms cards fire `protein-*` rules, sc_rna cards fire `sc-expression-*` rules.
# `sample_context` NEVER changes which rules exist (a cell-line-RNA card and a tumor-RNA card
# both fire expression rules), so the ladder is keyed by measurement alone even though the BUCKET
# is keyed by the (measurement, sample_context) pair. Measurements without a card (protein_ihc)
# have no ladder → their buckets emit data_unavailable in _per_modality_verdicts.
_MEASUREMENT_RANK: dict[str, list[tuple[str, str]]] = {
    "bulk_rna": _EXPRESSION_RANK,
    "bulk_protein_ms": _PROTEIN_RANK,
    "sc_rna": _SC_RNA_RANK,
}

# Collapsed ladder. Naive concatenation (_EXPRESSION_RANK + _PROTEIN_RANK) is WRONG:
# it places expression's two `data_unavailable` entries ABOVE every protein rule, so a
# protein-ONLY target (expression data_unavailable, but CPTAC reads strong_up or a
# not_detected killer) resolves to `data_unavailable` — silently discarding the measured
# protein signal (the exact cross-modality-swallow the per-ladder C1 fix does NOT cover).
#
# Correct order: ALL measured rules first (expression measured, then protein measured, then
# sc_rna measured — RNA stays the backbone so existing RNA-target verdicts are byte-stable), then
# EVERY `data_unavailable` entry sinks to the bottom. A measured protein/sc call therefore always
# outranks an expression coverage-gap, while an RNA target still resolves on its expression rule
# first (measured expression precedes measured protein precedes measured sc_rna). sc_rna is appended
# LAST among measured so a target firing BOTH a bulk rule and an sc rule keeps its old (bulk) verdict
# (byte-stability); a target firing ONLY sc rules (COADREAD/NSCLC single-cell, no bulk) now resolves
# instead of collapsing to insufficient.
def _partition_measured(ladder: list[tuple[str, str]]) -> tuple[list, list]:
    measured = [(rid, v) for rid, v in ladder if v != "data_unavailable"]
    gap = [(rid, v) for rid, v in ladder if v == "data_unavailable"]
    return measured, gap


_EXPR_MEASURED, _EXPR_GAP = _partition_measured(_EXPRESSION_RANK)
_PROT_MEASURED, _PROT_GAP = _partition_measured(_PROTEIN_RANK)
_SC_MEASURED, _SC_GAP = _partition_measured(_SC_RNA_RANK)
_VERDICT_RANK: list[tuple[str, str]] = (
    _EXPR_MEASURED + _PROT_MEASURED + _SC_MEASURED + _EXPR_GAP + _PROT_GAP + _SC_GAP
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
    protein-only target resolves instead of collapsing to insufficient (C1 fix).

    INLINE (no declarative resolver) — BY DESIGN, not un-migrated debt. Every other
    verdict-bearing gate resolves via target-contracts/resolvers/<gate>.resolver.yaml
    (_skills_common.resolver), but tumor-presence deliberately does NOT, because the
    resolver models exactly ONE gate verdict over the flat fired-set — it has no notion
    of grouping. tumor-presence's output is TWO coupled things derived from the SAME
    ladders: this collapsed spine AND the per-(measurement, sample_context) buckets in
    _per_modality_verdicts, which rank WITHIN CARD_CONTEXT groups. That bucket
    decomposition cannot be expressed in the resolver grammar (guardrail: no grouping,
    lookups, or loops — see _skills_common/resolver.py), and splitting the collapsed
    order into a YAML while the per-measurement ladders stay in Python would fragment a
    single source into two (drift risk), not simplify. The ladder is instead frozen by
    test_full_per_modality_golden_spine + the G1/G2/G5 regressions — the golden-oracle
    guard the resolver migration would otherwise provide. Reaffirmed 2026-08-11 (prod
    review); see test_composer_card_manifest_consistency.py for the composer-side note."""
    return _rank_verdict(fired)


# The (protein_ihc, normal) bucket is a SAFETY COMPARATOR, not a presence measurement — its card
# (normal-tissue-liability) fires SAFETY-axis rules (not the intracellular_intrinsic rules this skill
# fires), so it produces no presence sub-verdict to rank. It is surfaced as a labeled comparator read
# (evidence_state='comparator') carrying the HPA-IHC breadth class, so the bucket is a real read
# rather than a hardcoded data_unavailable — WITHOUT entering the presence ladder (spine byte-stable).
_COMPARATOR_BUCKETS = {
    ("protein_ihc", "normal"): ("normal-tissue-liability", "normal_tissue_breadth_class"),
    ("sc_rna", "normal"):      ("sc-normal-celltype-expression", "sc_normal_expression_class"),
}


def _per_modality_verdicts(fired: list[dict], cards: list[dict] | None = None) -> dict[str, dict]:
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
        if (measurement, sample_context) in _COMPARATOR_BUCKETS:
            # SAFETY COMPARATOR bucket (protein_ihc/normal, sc_rna/normal): the card's OWN rules are
            # on the safety/selectivity axis, not presence — so this bucket carries a labeled
            # comparator readout, NEVER a ranked presence sub-verdict.
            #
            # G2 fix (2026-08-11 production review): this branch is checked BEFORE the `group` branch.
            # A cross-axis rule that keys one of these comparator cards but lives on the intracellular
            # axis (e.g. the tumor-selectivity `tvn-sc-normal-critical-organ-veto`, which keys
            # sc-normal-celltype-expression) DOES fire in this skill and gets tagged to this
            # (measurement, sample_context) via CARD_CONTEXT. When the `group` branch ran first, that
            # fired veto — absent from the measurement ladder — collapsed the comparator bucket to
            # `insufficient`, erasing the comparator readout for exactly the critical-organ targets
            # (FOLR1) where it matters most. Comparator buckets never rank a fired rule.
            card_id, field = _COMPARATOR_BUCKETS[(measurement, sample_context)]
            # get_card_field RAISES on an absent card_id (typo-guard), so only call it when the
            # comparator card actually resolved this run — else the bucket stays data_unavailable.
            _present = {c["card_id"] for c in (cards or [])}
            val = get_card_field(cards, card_id, field) if card_id in _present else None
            if val not in (None, "data_unavailable"):
                out[key] = {"measurement": measurement, "sample_context": sample_context,
                            "verdict": val, "driving_rule_id": None,
                            "evidence_state": "comparator"}
            else:
                out[key] = {"measurement": measurement, "sample_context": sample_context,
                            "verdict": "data_unavailable", "driving_rule_id": None,
                            "evidence_state": "data_unavailable"}
        elif group:
            # rank WITHIN the bucket using the MEASUREMENT's ladder — bulk_protein_ms
            # must rank against _PROTEIN_RANK, not the expression ladder (the C1 bug
            # was ranking protein rules against expression-only rule_ids → insufficient).
            v, drv = _rank_verdict(group, _MEASUREMENT_RANK.get(measurement))
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": v, "driving_rule_id": drv,
                        "evidence_state": "measured"}
        else:
            # No card for this bucket in this skill (sc_rna/tumor), OR a tagged card produced no
            # fired rule. Either way: not measured here.
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": "data_unavailable", "driving_rule_id": None,
                        "evidence_state": "data_unavailable"}
    return out


# RNA presence-verdict values that are a MEASURED-POSITIVE bulk-RNA presence call (i.e. the
# presence signal rests on RNA). Used only to QUALIFY the RNA call by its protein-proxy quality —
# never to change it.
_RNA_PRESENCE_POSITIVE = frozenset({
    "broadly_high_expression", "strongly_upregulated_in_tumor", "lineage_restricted",
    "modestly_upregulated_in_tumor", "broadly_moderate_expression",
    "tumor_broadly_expressed", "tumor_moderately_expressed",
})


def _bulk_rna_proxy_quality(per_modality: dict, rna_as_biomarker) -> str:
    """Derived, VERDICT-INERT qualifier: when a bulk-RNA presence call is MEASURED-POSITIVE, how well
    does RNA proxy the protein it implies? The framework carries both layers but the concordance
    signal was display-only; this surfaces the interpretive TENSION explicitly (spec D5 — 'RNA is a
    poor proxy for available protein', the ADC/biologics-critical fact) so synthesis/reviewers can
    down-weight an RNA-only presence claim. Does NOT move presence_verdict (one-directional).

    Values:
      rna_confirmed_by_protein     — RNA-positive + RNA is an adequate protein proxy (high-confidence presence)
      rna_positive_proxy_partial   — RNA-positive + partial proxy (moderate confidence)
      rna_positive_proxy_poor      — RNA-positive but RNA is a POOR protein proxy → the presence claim
                                     needs protein confirmation before an ADC/biologics read (caveat)
      proxy_untested               — RNA-positive but proxy not measurable (too few paired models / no data)
      not_applicable               — the RNA bucket is not a measured-positive presence call
    """
    def _bucket_verdict(key):
        b = (per_modality or {}).get(key)
        return b.get("verdict") if isinstance(b, dict) else b
    # PREFER the tumor arm when it is itself a measured-positive RNA call; otherwise fall back to
    # the cell-line arm. (Bug: `A or B` short-circuited on the tumor bucket, which
    # _per_modality_verdicts ALWAYS populates with a truthy dict — even verdict=data_unavailable —
    # so the cell-line fallback was DEAD: a cell-line-only positive read "not_applicable" while
    # bulk_rna_proxy_quality_source was reported as "cell_line", a self-contradiction.)
    tumor_verdict = _bucket_verdict("bulk_rna/tumor")
    rna_verdict = (tumor_verdict if tumor_verdict in _RNA_PRESENCE_POSITIVE
                   else _bucket_verdict("bulk_rna/cell_line"))
    if rna_verdict not in _RNA_PRESENCE_POSITIVE:
        return "not_applicable"
    if rna_as_biomarker == "adequate_proxy":
        return "rna_confirmed_by_protein"
    if rna_as_biomarker == "partial_proxy":
        return "rna_positive_proxy_partial"
    if rna_as_biomarker == "poor_proxy":
        return "rna_positive_proxy_poor"
    return "proxy_untested"   # insufficient_paired_models / data_unavailable / None


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    per_modality = _per_modality_verdicts(fired, cards)
    _rna_biomarker = get_card_field(cards, "cellline-rna-protein-concordance", "rna_as_biomarker")
    # TUMOR-arm proxy quality (Q5 tumor, 2026-08-08 graduation). This is the number an RNA-based
    # presence claim IN A PATIENT rests on — bulk-tumor purity/stroma/post-transcriptional regulation
    # degrade RNA↔protein concordance far more than in cell lines, and it is strongly gene-specific.
    # PREFER it over the cell-line arm for _bulk_rna_proxy_quality; fall back to cell-line when the
    # indication has no CPTAC cohort (tumor arm → data_unavailable / insufficient_paired_tumors).
    _rna_biomarker_tumor = get_card_field(cards, "rna-protein-concordance-tumor", "rna_as_biomarker")
    _proxy_biomarker = (_rna_biomarker_tumor
                        if _rna_biomarker_tumor in ("adequate_proxy", "partial_proxy", "poor_proxy")
                        else _rna_biomarker)
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
        # NOTE: the cell-line card emits `expression_class` (its primary call); `expression_call_class`
        # is tumor-rna-vs-adjacent's field (read as tva_expression_call below). Reading it here
        # silently returned None (get_card_field on an absent key) — a wrong-key drift caught by
        # skills/tests/test_card_field_conformance.py. The emitted key name is unchanged.
        "expression_call_class":    get_card_field(cards, "cellline-rna-distribution",
                                          "expression_class"),
        "tva_log2_fc":              get_card_field(cards, "tumor-rna-vs-adjacent", "log2_fc"),
        "tva_q_value":              get_card_field(cards, "tumor-rna-vs-adjacent", "q_value"),
        "tva_expression_call":      get_card_field(cards, "tumor-rna-vs-adjacent",
                                          "expression_call_class"),
        "protein_expression_class": get_card_field(cards, "tumor-protein-abundance-cptac",
                                          "protein_expression_class"),
        "protein_effect_size":      get_card_field(cards, "tumor-protein-abundance-cptac",
                                          "protein_effect_size"),
        # Slice B3: the pan-cancer tumor-elevation breadth (target-grain) — the one
        # tumor-context presence signal available to a target-ONLY query.
        "tumor_elevation_breadth_class": get_card_field(cards, "tumor-elevation-breadth",
                                              "tumor_elevation_breadth_class"),
        "tumor_elevation_n_cohorts_elevated": get_card_field(cards, "tumor-elevation-breadth",
                                                   "n_cohorts_elevated"),
        "tumor_elevation_n_cohorts_tested": get_card_field(cards, "tumor-elevation-breadth",
                                                 "n_cohorts_tested"),
        # RNA breadth layer (G3 fix, 2026-08-11 production review). tumor-elevation-breadth emits a
        # SECOND, parallel breadth layer (rna_tumor_elevation_breadth_class; pan-cancer DESeq2, 27
        # indications vs CPTAC's 10) that was EMITTED but neither ruled nor read here — a dead
        # sub-axis that silently discarded a measured RNA-elevation signal for the RNA-only
        # indications / target-only queries RNA covers but CPTAC does not. Surfaced ALONGSIDE the
        # protein layer (never averaged) as a verdict-inert facet, with breadth_layer_concordance so
        # a protein coverage gap (rna_only) is legible rather than lost. Now also ruled in
        # target-contracts (rna-tumor-breadth-* rules); PARALLEL by design — feeds NO presence
        # ladder rung, presence_verdict byte-stable.
        "rna_tumor_elevation_breadth_class": get_card_field(cards, "tumor-elevation-breadth",
                                                  "rna_tumor_elevation_breadth_class"),
        "rna_tumor_elevation_n_indications_elevated": get_card_field(cards, "tumor-elevation-breadth",
                                                           "rna_n_indications_elevated"),
        "rna_tumor_elevation_n_indications_tested": get_card_field(cards, "tumor-elevation-breadth",
                                                         "rna_n_indications_tested"),
        "breadth_layer_concordance": get_card_field(cards, "tumor-elevation-breadth",
                                          "breadth_layer_concordance"),
        # Q9 purity confound — is the tumor presence signal tumor-intrinsic or microenvironment?
        # (render facet; does NOT feed the presence verdict — additive, spine byte-stable)
        "purity_confound_class":    get_card_field(cards, "expression-purity-confound", "purity_confound_class"),
        "expression_purity_pearson_r": get_card_field(cards, "expression-purity-confound", "expression_purity_pearson_r"),
        # (phospho_activity_class / n_phosphosites RE-HOMED 2026-08-05 → mechanism-and-pharmacology.)
        # Q5 rna_as_biomarker — RNA-as-proxy-for-protein quality (render facet + biomarker preferred_assay input)
        # CELL-LINE arm (target-grain).
        "rna_as_biomarker":         _rna_biomarker,
        "rna_protein_r":            get_card_field(cards, "cellline-rna-protein-concordance", "rna_protein_r"),
        # Q5 TUMOR arm (2026-08-08 graduation) — the CPTAC per-tumor concordance for THIS indication.
        # Reported SIDE-BY-SIDE with the cell-line arm (never averaged); their disagreement is the signal
        # (EPCAM/COAD: tumor partial_proxy r=0.46 vs cell-line adequate r=0.86). Render facet, verdict-inert.
        "rna_as_biomarker_tumor":   _rna_biomarker_tumor,
        "rna_protein_r_tumor":      get_card_field(cards, "rna-protein-concordance-tumor", "rna_protein_r"),
        "rna_protein_n_paired_tumors": get_card_field(cards, "rna-protein-concordance-tumor", "n_paired_tumors"),
        "rna_protein_cptac_cohort": get_card_field(cards, "rna-protein-concordance-tumor", "cptac_cohort"),
        # RNA→protein proxy QUALIFIER on the RNA presence call (2026-08-07, review Fix-1). Derived,
        # VERDICT-INERT: qualifies a MEASURED-POSITIVE bulk-RNA presence verdict by whether RNA is a
        # trustworthy protein proxy (spec D5). rna_positive_proxy_poor flags an RNA-only presence claim
        # that needs protein confirmation before an ADC/biologics read. Never moves presence_verdict.
        # 2026-08-08: now PREFERS the TUMOR-arm concordance (the disease-context proxy quality) over the
        # cell-line arm, falling back to cell-line when the indication has no CPTAC cohort.
        "bulk_rna_proxy_quality":   _bulk_rna_proxy_quality(per_modality, _proxy_biomarker),
        "bulk_rna_proxy_quality_source": ("tumor" if _rna_biomarker_tumor in
                                          ("adequate_proxy", "partial_proxy", "poor_proxy")
                                          else "cell_line"),
        # SUBTYPE SCOPE (Finding A, 2026-08-04) — the per-molecular-subtype presence landscape from
        # tumor-rna-distribution-by-subtype, ELEVATED into the audit spine so the subtype scope is
        # visible here, not just in a side table (_per_subgroup_metrics.csv). One-directional / non-veto
        # (like the other facets — feeds NO resolver ladder; presence_verdict byte-stable). Degrades
        # honestly: subtype_scope_available=False for indications with no landed assignment shard
        # (only COADREAD today) — a NAMED gap, not silence.
        "subtype_scope_available":  get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_axis_available"),
        "n_subtypes_measured":      get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_measured"),
        "n_subtypes_enriched":      get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_enriched"),
        "spotlight_subtype":        get_card_field(cards, "tumor-rna-distribution-by-subtype", "spotlight_subtype"),
        # Graded patient-selection signal (2026-08-04) — the biomarker facet's stratification input.
        # One-directional: raises CONFIDENCE / defines patient population, NEVER moves presence_verdict.
        "subtype_stratification_class": get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_stratification_class"),
        "n_subtypes_restricted":    get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_restricted"),
        # sc_rna slice (2026-08-04) — single-cell per-compartment tumor presence, ELEVATED into the
        # audit spine. VERDICT-BEARING via _SC_RNA_RANK (feeds the sc_rna/tumor bucket + the collapsed
        # spine below the bulk backbone). malignant_detection_fraction is the sc-native headline metric;
        # top_microenvironment_* carries the malignant-vs-microenvironment attribution bulk can't make.
        "sc_expression_class":      get_card_field(cards, "tumor-scrna-celltype-expression", "sc_expression_class"),
        "sc_malignant_detection_fraction": get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_detection_fraction"),
        "sc_malignant_compartment_available": get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_compartment_available"),
        "sc_top_microenvironment_compartment": get_card_field(cards, "tumor-scrna-celltype-expression", "top_microenvironment_compartment"),
        "sc_n_donor_groups":        get_card_field(cards, "tumor-scrna-celltype-expression", "n_donor_groups"),
        # P8.3 (2026-08-05) — HPA IHC normal-tissue protein footprint COMPARATOR (protein_ihc/normal
        # bucket). A safety comparator surfaced for context, NOT a presence signal — feeds no resolver
        # ladder (presence_verdict byte-stable); the safety VERDICT is owned by on-target-safety-liability.
        "normal_tissue_ihc_breadth_class": get_card_field(cards, "normal-tissue-liability", "normal_tissue_breadth_class"),
        "normal_tissue_ihc_essential_flag": get_card_field(cards, "normal-tissue-liability", "essential_tissue_flag"),
        # Phase 3.3 (2026-08-07) — scRNA cell-type-resolved normal-tissue safety COMPARATOR (sc_rna/normal bucket).
        "sc_normal_expression_class":      get_card_field(cards, "sc-normal-celltype-expression", "sc_normal_expression_class"),
        "sc_normal_max_det_cell_type":     get_card_field(cards, "sc-normal-celltype-expression", "max_detection_cell_type"),
        "sc_normal_max_det_fraction":      get_card_field(cards, "sc-normal-celltype-expression", "max_detection_fraction"),
        "sc_normal_safety_essential_flags": get_card_field(cards, "sc-normal-celltype-expression", "safety_essential_flags"),
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
