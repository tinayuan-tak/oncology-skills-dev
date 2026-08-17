#!/usr/bin/env python3
"""tumor-presence — expression/protein presence for a (target, indication).

Consumes 13 wired cards in three tiers (see CARDS below + SKILL.md). 7 + 4 + 2 = 13:
  VERDICT-BEARING (7, feed the presence ladders): cellline-rna-distribution (cell-line RNA),
    tumor-rna-vs-adjacent (tumor RNA), tumor-rna-distribution (per-sample tumor RNA — its
    tumor-expression-* rules ARE in the bulk_rna ladder; reclassified from display-only 2026-08-07),
    tumor-protein-abundance-cptac (tumor protein), cellline-protein-abundance (cell-line protein),
    tumor-elevation-breadth (pan-cancer target-grain),
    tumor-scrna-celltype-expression (single-cell per-compartment tumor presence — sc_rna/tumor).
  DISPLAY-ONLY facets (4, feed NO ladder — verdict byte-stable): tumor-rna-distribution-by-subtype,
    expression-purity-confound, cellline-rna-protein-concordance (cell-line RNA↔protein proxy),
    rna-protein-concordance-tumor (CPTAC tumor RNA↔protein proxy — the tumor arm).
  SAFETY COMPARATORS (2, verdict-inert; the safety VERDICT is owned by on-target-safety-liability, NOT
    this skill): normal-tissue-liability (protein_ihc/normal — HPA IHC, P8.3),
    sc-normal-celltype-expression (sc_rna/normal — scRNA Phase 3.3).
  (phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology: an ACTIVITY /
   signaling-state readout, not a presence/abundance signal — it belongs with the mechanism lens.)
Emits a data-package output tree with a rank-ordered presence verdict + per-(measurement,
sample_context) sub-verdicts across THREE measurement ladders (bulk_rna, bulk_protein_ms, sc_rna).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
Slice B3 (2026-07-21): + tumor-elevation-breadth (the target-grain tumor signal).
sc_rna slice (2026-08-04): + tumor-scrna-celltype-expression — fills the sc_rna/tumor bucket that
  MODALITY_TAXONOMY.md named as an unbuilt gap (single-cell per-compartment presence + malignant-vs-
  microenvironment attribution; a 3rd measurement ladder _SC_RNA_RANK).
Card roster reached 13 across the expression-extraction plan (Q1/Q5/Q8/Q9 + protein + breadth +
  subtype + sc_rna/tumor + the two normal comparators).
"""

# ─────────────────────────────────────────────────────────────────────────────
# CURRENT CONTRACT (read this first)
#
# This file is a THIN configuration over the shared dispatcher — the heavy lifting
# (card reads, rule firing, package emission) lives in _skills_common. The live
# logic here is four pieces; the remaining inline comments are dated rationale for
# past fixes, kept as institutional memory (not required to understand the flow).
#
#   1. CARDS + CARD_CONTEXT      — the 13 cards this skill consumes, each tagged with
#                                  its (measurement, sample_context) bucket.
#   2. THREE ladders             — _EXPRESSION_RANK / _PROTEIN_RANK / _SC_RNA_RANK:
#                                  ordered (rule_id -> verdict) lists, highest-
#                                  precedence first, one per measurement layer.
#   3. COLLAPSE                  — _partition_measured + _VERDICT_RANK assemble the
#                                  three ladders into ONE order: [all positives] +
#                                  [all negatives] + [all gaps], RNA-first within each
#                                  tier. _verdict() returns the first fired rung.
#   4. _per_modality_verdicts    — the same ladders applied WITHIN each (measurement,
#                                  sample_context) bucket, plus the comparator + un-
#                                  ruled-present rescues. _headline() bundles the
#                                  collapsed verdict, the per-bucket map, and the
#                                  verdict-inert display fields read off the cards.
#
# The entry point (bottom of file) hands all four to run_wired_skill(...), which runs
# resolve_cards -> fired_rules -> verdict_fn -> headline_fn -> write_package.
#
# INVARIANT: everything except the three ladders + the collapse is verdict-INERT — the
# facets, comparators, proxy-quality qualifier, and lens-discordance flag never move
# presence_verdict. The ladder order is frozen by tests/test_per_modality_verdict.py
# (golden spine) + tests/test_reanchor_flip_matrix.py.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.presence_matrix import emit_presence_matrix


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.7.0"   # 2026-08-14 — F RE-ANCHOR (VERDICT-MOVING, backtest-gated): _EXPRESSION_RANK now
                          # ranks the TUMOR-tissue lens above the pan-cancer CELL-LINE proxy for the headline,
                          # so de-differentiating antigens (EPCAM/FOLR1/CDH17/TACSTD2 …) read tumor_broadly_expressed
                          # instead of the understated cell-line broadly_moderate/lineage_restricted. 43-pair backtest:
                          # 23 flips, ALL → tumor_broadly_expressed, zero dangerous flips; cell_line_vs_tumor_discordant
                          # (1.6.0) is now a standing invariant guard (normally False). See CHANGES_PLAN F.
                          # 1.6.0 — multi-pair review (ADDITIVE / verdict-inert): headline now carries
                          # headline_lens + cell_line_vs_tumor_discordant + presence_interpretation_note so a
                          # cell-line-anchored one-word verdict that UNDERSTATES tumor-tissue presence (EPCAM,
                          # FOLR1, KRAS) is legible. Feeds no rule; presence_verdict byte-stable. (Ladder re-anchor
                          # that would promote the tumor lens is a SEPARATE backtest-gated change.)
                          # 1.5.0 = full-review verdict remediation (VERDICT-MOVING): H2 collapse ranks measured
                          # POSITIVES (any modality) above measured NEGATIVES (a cell-line-RNA killer no longer
                          # buries a measured tumor-protein/sc positive); M3 not_informative sinks to the collapse
                          # gap tier; M2 a resolved-but-flat CPTAC `ns` marks the bulk_protein_ms/tumor bucket
                          # `measured` (protein_present_not_elevated) instead of data_unavailable.
                          # (1.4.0 = RNA→protein TUMOR concordance arm; 1.3.0 = sc-normal comparator.)

CARDS = [
    "cellline-rna-distribution",
    "tumor-rna-vs-adjacent",
    "tumor-protein-abundance-cptac",           # Layer 6c — bulk_protein_ms x tumor. WHOLE-CELL-LYSATE
                                        # TMT-MS: measures protein PRODUCED (all compartments), NOT
                                        # surface-accessible protein. "protein_present" ≠ surface antigen.
    "cellline-protein-abundance",        # E3b — bulk_protein_ms x cell_line (Gygi WHOLE-CELL-LYSATE TMT-MS;
                                        # total protein produced, not surface-localized)
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
                                        # cells) + malignant-vs-microenvironment attribution. Wired for
                                        # COADREAD/NSCLC/LUSC/PAAD/HNSC/KIRC/OV (methods
                                        # sc_tumor_expression_celltype INDICATION_TO_PRODUCT); other
                                        # indications → data_unavailable (honest capability ceiling).
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
    ("sc_rna", "tumor"),          # card-backed (tumor-scrna-celltype-expression); measured for COADREAD/NSCLC/LUSC/PAAD/HNSC/KIRC/OV, else data_unavailable
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
    # F RE-ANCHOR (2026-08-14 multi-pair review, VERDICT-MOVING — see backtest): the collapsed headline
    # inherits whichever rung fires first, and the pan-cancer CELL-LINE distribution rungs used to sit
    # ABOVE the disease-relevant TUMOR-TISSUE rungs (chosen for byte-stability). For antigens that
    # de-differentiate in 2D culture (EPCAM, FOLR1, KRAS/COADREAD) the cell-line median collapses to
    # broadly_moderate/lineage_restricted while the TUMOR reads broadly_expressed — so the one-word
    # verdict UNDERSTATED tumor presence (the cell_line_vs_tumor_discordant flag, PR#413, made this
    # legible; this re-anchor fixes the verdict itself). Principle: the TUMOR-tissue lens outranks the
    # pan-cancer cell-line PROXY for the presence headline.
    #   • tumor_broadly_expressed / tumor_moderately_expressed PROMOTED above the cell-line
    #     lineage_restricted + broadly_moderate rungs.
    #   • cell-line broadly_high KEPT at the top: when both lenses read high (MET, ERBB2) the verdict
    #     is unchanged — no gratuitous churn.
    #   • tumor_sparsely_expressed stays BELOW the cell-line positives (a per-indication sparse read is
    #     NEUTRAL and must not outrank a supportive cell-line-present signal).
    ("expression-broadly-high-supportive",              "broadly_high_expression"),      # cell-line high (both-high agree → unchanged)
    ("expression-strong-upregulation-supportive",       "strongly_upregulated_in_tumor"), # tumor-vs-adjacent
    ("tumor-expression-broadly-high-supportive",        "tumor_broadly_expressed"),       # TUMOR tissue — PROMOTED above cell-line moderate/restricted
    ("expression-modest-upregulation-neutral",          "modestly_upregulated_in_tumor"), # tumor-vs-adjacent
    ("tumor-expression-broadly-moderate-neutral",       "tumor_moderately_expressed"),    # TUMOR tissue — PROMOTED
    ("expression-lineage-restricted-supportive",        "lineage_restricted"),            # cell-line PROXY — demoted below tumor tissue
    ("expression-broadly-moderate-neutral",             "broadly_moderate_expression"),   # cell-line PROXY — demoted below tumor tissue
    ("tumor-expression-broadly-low-neutral",            "tumor_sparsely_expressed"),      # per-indication sparse (NEUTRAL) — stays below cell-line positives
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
# Correct order has TWO subtleties beyond a naive concatenation:
#
# (A) COVERAGE GAPS SINK (original C1 fix): expression's data_unavailable rungs must NOT sit above
#     protein rules, else a protein-only target (expression data_unavailable, CPTAC strong_up)
#     collapses to data_unavailable, discarding the measured protein signal.
#
# (B) MEASURED POSITIVES OUTRANK MEASURED NEGATIVES ACROSS MODALITIES (H2 fix, 2026-08-13 full review):
#     the prior collapse was _EXPR_MEASURED + _PROT_MEASURED + _SC_MEASURED, so the ENTIRE expression
#     measured block — INCLUDING its killers/opposers (broadly_low_expression, the down reads) — sat
#     above every protein/sc rung. A target broadly-LOW in DepMap cell-line RNA but strongly-UP in CPTAC
#     tumor protein collapsed to broadly_low_expression: a FALSE-NEGATIVE presence headline that
#     contradicted its own `bulk_protein_ms/tumor: measured` bucket. G5 fixed this WITHIN the RNA ladder;
#     the modality-tier boundaries reintroduced the identical class across modalities. Fix: collapse as
#     [all measured POSITIVES: expr, prot, sc] + [all measured NEGATIVES: expr, prot, sc] + [gaps], so a
#     measured presence-positive in ANY modality outranks a measured presence-negative in another, while
#     RNA stays the backbone WITHIN each tier (expr before prot before sc → byte-stable for positive-RNA
#     targets). A measured negative still outranks a coverage gap.
#     (`dominant:` on protein-strongly-up is a modality-GATE concept — small_molecule/degrader signals —
#     NOT a presence-collapse concept; presence keeps RNA-backbone-first order among positives.)

# Measured verdict strings that are PRESENCE-NEGATIVE (opposing / degrader-killer: the target is
# down/absent, not present). Everything else measured is presence-positive-or-neutral (present, with a
# caveat). Coverage gaps (data_unavailable) PLUS the tumor-vs-adjacent `not_informative` read sink to
# the bottom — M3 fix: a flat/non-differential tumor-vs-adjacent result is a COVERAGE GAP (the rule's
# own rationale), not a measured negative, so it must never mask a measured protein/sc positive.
_MEASURED_NEGATIVE_VERDICTS = frozenset({
    "modestly_downregulated_in_tumor", "strongly_downregulated_in_tumor", "broadly_low_expression",
    "protein_modestly_downregulated", "protein_strongly_downregulated",
    "protein_not_detected", "protein_broadly_low",
})
_COLLAPSE_GAP_VERDICTS = frozenset({"data_unavailable", "not_informative"})


def _partition_measured(ladder: list[tuple[str, str]]) -> tuple[list, list, list]:
    """Split a ladder into (presence-POSITIVE, presence-NEGATIVE, coverage-GAP) rungs, preserving
    within-tier order. Positives = present (supportive/neutral-present); negatives = opposing/killer
    measured reads; gaps = data_unavailable (+ not_informative, M3)."""
    positives = [(rid, v) for rid, v in ladder
                 if v not in _MEASURED_NEGATIVE_VERDICTS and v not in _COLLAPSE_GAP_VERDICTS]
    negatives = [(rid, v) for rid, v in ladder if v in _MEASURED_NEGATIVE_VERDICTS]
    gaps = [(rid, v) for rid, v in ladder if v in _COLLAPSE_GAP_VERDICTS]
    return positives, negatives, gaps


_EXPR_POS, _EXPR_NEG, _EXPR_GAP = _partition_measured(_EXPRESSION_RANK)
_PROT_POS, _PROT_NEG, _PROT_GAP = _partition_measured(_PROTEIN_RANK)
_SC_POS, _SC_NEG, _SC_GAP = _partition_measured(_SC_RNA_RANK)
_VERDICT_RANK: list[tuple[str, str]] = (
    _EXPR_POS + _PROT_POS + _SC_POS         # all measured POSITIVES (RNA backbone first)
    + _EXPR_NEG + _PROT_NEG + _SC_NEG       # then all measured NEGATIVES
    + _EXPR_GAP + _PROT_GAP + _SC_GAP       # then coverage gaps (incl. not_informative, M3)
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

# M2 (2026-08-13 full review): (bucket) → (card_id, field, {raw_class: bucket_verdict}) for cards that
# emit a MEASURED-PRESENT class that is deliberately UN-RULED (fires no rule, so cannot rank into a
# ladder). Used by _per_modality_verdicts to mark such a bucket `measured` instead of data_unavailable
# when the card resolved with one of these classes. tumor-protein-abundance-cptac's flat classes =
# protein quantified but not tumor-elevated (present-but-flat); the CPTAC card is a tumor-vs-normal
# CONTRAST, so a flat class means present in both, i.e. present in tumor without tumor-selective
# elevation.
#
# 2026-08-14 (finding #5, AM cptac_protein_deg ns-split): the former single `ns` was split into
# `not_significant` (q>=0.05) + `small_effect` (q<0.05, |logfc|<=0.5). BOTH mean present-but-flat, so
# both map to protein_present_not_elevated. `ns` is kept as a BACKWARD-COMPAT key so this rescue works
# regardless of the AM-vs-skills merge order (and against any not-yet-refrozen fixture); it becomes
# dead once every consumer emits the split vocab and can be dropped in a later cleanup.
_MEASURED_UNRULED_PRESENT = {
    ("bulk_protein_ms", "tumor"): ("tumor-protein-abundance-cptac", "protein_expression_class",
                                   {"ns": "protein_present_not_elevated",            # legacy (pre-split)
                                    "not_significant": "protein_present_not_elevated",
                                    "small_effect": "protein_present_not_elevated"}),
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
            # No card for this bucket in this skill, OR a tagged card produced no fired rule.
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": "data_unavailable", "driving_rule_id": None,
                        "evidence_state": "data_unavailable"}

        # M2 fix (2026-08-13 full review): rescue a resolved-but-UNRULED PRESENT read from a
        # data_unavailable bucket. Some cards emit a measured-present class that fires NO rule by
        # design — notably tumor-protein-abundance-cptac's `ns` (protein quantified, no significant
        # tumor-vs-normal differential = present-but-not-elevated). `ns` stays deliberately un-ruled
        # (the modality gate must not fire on the neutral null), but that left this bucket reading
        # `data_unavailable` — conflating "measured, flat" with "not measured" — whenever the parallel
        # breadth layer was also absent (its data_unavailable rung being the only fired rule). Here we
        # detect the resolved-but-unruled present read directly off the card and mark the bucket
        # `measured`, WITHOUT authoring a gate rule (no compose/target-profile golden churn).
        if out[key]["verdict"] == "data_unavailable" and (measurement, sample_context) in _MEASURED_UNRULED_PRESENT:
            card_id, field, class_map = _MEASURED_UNRULED_PRESENT[(measurement, sample_context)]
            _present = {c["card_id"] for c in (cards or [])}
            raw = get_card_field(cards, card_id, field) if card_id in _present else None
            if raw in class_map:
                out[key] = {"measurement": measurement, "sample_context": sample_context,
                            "verdict": class_map[raw], "driving_rule_id": None,
                            "evidence_state": "measured"}
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


# Presence-TIER ordinal for the RNA-lens verdict vocab. Used ONLY to detect when the
# collapsed headline UNDERSTATES the tumor-tissue lens. VERDICT-INERT: feeds no ladder,
# never moves presence_verdict — surfaces an interpretation caveat only.
#
# WHY (2026-08-13 multi-pair review): the headline presence_verdict is byte-identical to the
# bulk_rna/cell_line sub-verdict whenever a cell-line expression rule wins the collapsed
# ladder — the cell-line rungs (broadly_high … broadly_moderate) rank ABOVE the tumor-lens
# rungs by design, for byte-stability (see _EXPRESSION_RANK). For antigens that
# DE-DIFFERENTIATE in 2D culture (EPCAM, FOLR1, CEACAM5), the pan-cancer cell-line median
# collapses while the tumor tissue reads top-percentile, so the one-word headline underrates
# the best tumor-selective antigens. This flag makes that discordance legible WITHOUT
# re-ranking the ladder (the re-anchor is a separate, backtest-gated change). Consumers
# should read presence_verdict_by_modality — not just presence_verdict — when the flag is set.
_PRESENCE_TIER = {
    "broadly_high_expression": 3, "strongly_upregulated_in_tumor": 3, "tumor_broadly_expressed": 3,
    "broadly_moderate_expression": 2, "modestly_upregulated_in_tumor": 2, "tumor_moderately_expressed": 2,
    "lineage_restricted": 1, "broadly_low_expression": 1, "tumor_sparsely_expressed": 1,
}


def _headline_lens_discordance(driving_rule_id: str | None, per_modality: dict):
    """Which (measurement/sample_context) lens drove the collapsed headline, and does the
    tumor-tissue RNA lens read a HIGHER presence tier than the cell-line lens that anchored
    it? Returns (headline_lens_key_or_None, cell_line_vs_tumor_discordant_bool). The flag is
    True only for the specific hazard "headline is cell-line-anchored AND tumor tissue reads
    a strictly higher presence tier" — i.e. the one-word verdict understates tumor presence.
    Additive / verdict-inert (never touches presence_verdict)."""
    lens = None
    if driving_rule_id is not None:
        for key, b in (per_modality or {}).items():
            if isinstance(b, dict) and b.get("driving_rule_id") == driving_rule_id:
                lens = key
                break
    discordant = False
    if lens == "bulk_rna/cell_line":
        cl = (per_modality or {}).get("bulk_rna/cell_line") or {}
        tv = (per_modality or {}).get("bulk_rna/tumor") or {}
        if tv.get("evidence_state") == "measured":
            cl_tier = _PRESENCE_TIER.get(cl.get("verdict"))
            tumor_tier = _PRESENCE_TIER.get(tv.get("verdict"))
            if cl_tier is not None and tumor_tier is not None and tumor_tier > cl_tier:
                discordant = True
    return lens, discordant


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    per_modality = _per_modality_verdicts(fired, cards)
    # 2026-08-13 multi-pair review: legibility flag for the cell-line-anchored headline.
    _headline_lens, _cl_tumor_discordant = _headline_lens_discordance(drv, per_modality)
    _tumor_bucket = (per_modality or {}).get("bulk_rna/tumor") or {}
    _presence_interpretation_note = (
        ("presence_verdict inherits the pan-cancer cell-line RNA lens; the tumor-tissue lens "
         f"reads a higher presence tier ({_tumor_bucket.get('verdict')}). Read "
         "presence_verdict_by_modality['bulk_rna/tumor'] — the one-word headline understates "
         "tumor-tissue presence for this target (typical of antigens that de-differentiate in "
         "2D culture).")
        if _cl_tumor_discordant else None)
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
        # LENS-DISCORDANCE facet (2026-08-13 multi-pair review) — additive / VERDICT-INERT.
        # The collapsed presence_verdict inherits whichever lens won the ladder; `headline_lens`
        # names it (e.g. bulk_rna/cell_line). `cell_line_vs_tumor_discordant` is True only when
        # the headline is cell-line-anchored AND the tumor-tissue lens reads a strictly HIGHER
        # presence tier — the case where the one-word verdict understates tumor presence (EPCAM,
        # FOLR1, KRAS). `presence_interpretation_note` spells out the caveat for LLM/human readers.
        # None of these feed a rule; presence_verdict is byte-stable.
        "headline_lens":            _headline_lens,
        "cell_line_vs_tumor_discordant": _cl_tumor_discordant,
        "presence_interpretation_note": _presence_interpretation_note,
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
        # SUBTYPE SCOPE (Finding A, 2026-08-04) — the per-subtype presence landscape from
        # tumor-rna-distribution-by-subtype, ELEVATED into the audit spine so the subtype scope is
        # visible here, not just in a side table (_per_subgroup_metrics.csv). One-directional / non-veto
        # (like the other facets — feeds NO resolver ladder; presence_verdict byte-stable). The strata
        # are indication-specific: COADREAD carries molecular/clinical subtypes (CMS, CIMP, MSI, sidedness,
        # stage); LUAD & NSCLC carry driver-mutation strata (EGFR/KRAS/ALK/HER2/BRAF). Degrades honestly:
        # subtype_scope_available=False for any indication with no landed assignment shard — a NAMED gap,
        # not silence.
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


# ---------------------------------------------------------------------------
# CROSS-MODAL RECONCILIATION FACET (2026-08-17 presence-audit follow-up).
# ---------------------------------------------------------------------------
# The composed target-profile fan-out captures each sub-skill's `_verdict()` (the one collapsed
# string) + raw card summaries, but NOT the sub-skill's `_headline()` reconciliation. For
# tumor-presence that dropped the single most decision-relevant object the skill produces — the
# per-(measurement, sample_context) sub-verdict MATRIX that makes cross-modal tension legible
# (RNA-high / protein-absent; tumor-high / normal-tissue-high). This left the downstream LLM
# synthesis re-deriving that tension from raw numbers instead of being handed the deterministic
# answer. `_synthesis_facet` is the uniform opt-in the fan-out looks for (mirrors `_verdict`): it
# returns a COMPACT, verdict-INERT reconciliation block for the synthesis prompt. It reuses
# `_headline` (single source of truth) and selects the reconciliation-relevant fields. It NEVER
# moves the verdict; presence stays out of target-profile's `_SHORT_TO_GATE`.
_SYNTHESIS_FACET_KEYS = (
    "presence_verdict", "driving_rule_id",
    "presence_verdict_by_modality",       # the 7-bucket cross-modal matrix (the key object)
    "headline_lens", "cell_line_vs_tumor_discordant", "presence_interpretation_note",
    # RNA-as-protein-proxy quality (both arms, side-by-side) — qualifies an RNA-only presence claim
    "bulk_rna_proxy_quality", "bulk_rna_proxy_quality_source",
    "rna_as_biomarker", "rna_protein_r",
    "rna_as_biomarker_tumor", "rna_protein_r_tumor",
    # NORMAL-TISSUE comparators — FRAMING for the therapeutic window (verdict owned by
    # on-target-safety-liability; surfaced here so the reasoner weighs presence AGAINST the window).
    "normal_tissue_ihc_breadth_class", "normal_tissue_ihc_essential_flag",
    "sc_normal_expression_class", "sc_normal_max_det_cell_type", "sc_normal_max_det_fraction",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT cross-modal reconciliation block for the composed target-profile
    synthesis prompt. Reuses `_headline` (single source of truth) and returns the reconciliation-
    relevant subset. Never moves the verdict; safe to omit (fan-out treats absence as no-facet)."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic cross-modal reconciliation from tumor-presence (a FACET, not a gate; "
        "presence is verdict-inert to the nomination spine). Read presence_verdict_by_modality "
        "for cross-modal tension (RNA-high/protein-absent; tumor-high/normal-high). The normal_* "
        "fields are safety COMPARATORS (window framing); the safety verdict is owned by "
        "on-target-safety-liability.")
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
        # Skill-level hero graphic (opt-in --figures): the Presence × Context matrix over the
        # computed presence_verdict_by_modality. ADDITIVE / display-only (see presence_matrix.py).
        skill_figures_fn=emit_presence_matrix,
    ))
