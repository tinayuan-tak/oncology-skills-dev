#!/usr/bin/env python3
"""tumor-presence — is a (target, indication) present in tumor tissue?

Answers: "Is target X expressed in indication Y's tumor tissue, and how does it
distribute across cancer cell lines vs. tumor samples, at RNA, whole-cell protein,
and single-cell resolution?" This is a Phase-A (presence) question — distinct from
Phase-B selectivity vs. normals (`tumor-selectivity`).

Reads 14 pre-computed cards across three measurement layers (bulk RNA, bulk protein
MS, single-cell RNA) and emits a collapsed one-word `presence_verdict` PLUS one
sub-verdict per `(measurement, sample_context)` bucket, so a cell-line signal is never
conflated with a tumor signal and cross-modal tension is legible. Does not recompute
any DGE; does not compare against GTEx population-normal (that is `tumor-selectivity`).

This file is a THIN configuration over the shared dispatcher (`_skills_common`). The
live logic is four pieces:
  1. CARDS + CARD_CONTEXT   — the 14 cards, each tagged with its (measurement,
                              sample_context) bucket.
  2. THREE ladders          — _EXPRESSION_RANK / _PROTEIN_RANK / _SC_RNA_RANK: ordered
                              (rule_id -> verdict) lists, one per measurement layer.
  3. THE COLLAPSE           — _partition_measured + _VERDICT_RANK fold the ladders into
                              one order: [measured positives] + [measured negatives] +
                              [gaps], RNA-first within each tier. _verdict() returns the
                              first fired rung.
  4. _per_modality_verdicts — the ladders applied WITHIN each bucket; _headline() bundles
                              the collapsed verdict, the per-bucket map, and the verdict-
                              inert display fields.

The design rationale, collapse invariants, the tumor-over-cell-line re-anchor, and the
version history live in CONTRACT.md — read it before changing the ladders or the
collapse. INVARIANT: everything except the three ladders + the collapse is verdict-inert;
the ladder order is frozen by tests/test_per_modality_verdict.py (golden spine) +
tests/test_reanchor_flip_matrix.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.presence_matrix import emit_presence_matrix
from _skills_common.presence_claims import (presence_claim_vector, presence_claim_vector_by_subtype,
                                            presence_key_signals)
from _skills_common.presence_question_table import presence_question_table
from _skills_common.presence_claims_figure import emit_claim_vector_figure
from _skills_common.presence_subtype_figure import emit_subtype_refinement_figure
from _skills_common.presence_cardboard_figure import emit_card_board_figure


def _emit_skill_figures(decision, figures_root):
    """Combined --figures emitter: the Presence × Context hero matrix, the claim-vector
    (signal × reliability) figure, the per-card card-board (ternary signal/no-signal/not-measured
    grouped by claim), and — when the indication has a subtype axis — the subtype-refinement figure.
    All additive / display-only; best-effort per emitter."""
    return (emit_presence_matrix(decision, figures_root)
            + emit_claim_vector_figure(decision, figures_root)
            + emit_card_board_figure(decision, figures_root)
            + emit_subtype_refinement_figure(decision, figures_root))


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.12.0"

# The 14 cards, grouped by role (see CONTRACT.md § "Card roster"). The verdict is driven
# only by the three ladders + the collapse; every other card is verdict-inert (surfaced in
# the headline / synthesis facet but touches no ladder, so the presence spine is byte-stable).
CARDS = [
    # ── VERDICT-BEARING (7) — feed the presence ladders ───────────────────────
    "cellline-rna-distribution",         # cell-line RNA (pan-cancer TPM distribution)
    "tumor-rna-vs-adjacent",             # tumor RNA-seq DEG vs paired-adjacent
    "tumor-rna-distribution",            # per-sample tumor RNA distribution
    "tumor-protein-abundance-cptac",     # tumor whole-cell-lysate protein (CPTAC per-cohort TMT-MS)
    "cellline-protein-abundance",        # cell-line whole-cell-lysate protein (DepMap/Gygi TMT-MS)
    "tumor-elevation-breadth",           # pan-cancer K-of-N tumor-elevation (target-grain)
    "tumor-scrna-celltype-expression",   # single-cell per-compartment tumor presence (sc_rna/tumor)

    # ── DISPLAY-ONLY facets (5) — additive context, feed no ladder ────────────
    "tumor-rna-distribution-by-subtype",     # per-molecular-subtype tumor RNA panorama
    "cellline-rna-distribution-by-subtype",  # cell-line RNA by DepMap driver subtype (COADREAD proof)
    "expression-purity-confound",            # tumor-intrinsic vs stromal/immune signal
    "cellline-rna-protein-concordance",      # is RNA an adequate protein proxy? (cell-line arm)
    "rna-protein-concordance-tumor",         # is RNA an adequate protein proxy? (patient-tumor CPTAC arm)

    # ── NORMAL-TISSUE SAFETY COMPARATORS (2) — verdict-inert window framing ────
    # The safety VERDICT is owned by on-target-safety-liability, NOT this skill.
    "normal-tissue-liability",           # HPA IHC normal-tissue protein footprint (protein_ihc/normal)
    "sc-normal-celltype-expression",     # scRNA cell-type-resolved normal footprint (sc_rna/normal)
]

# card_id -> (measurement, sample_context). Mirrors each card's `measurement:` +
# `sample_context:` tags in target-contracts; a drift test asserts they agree. Kept local +
# explicit (the card set is fixed and small). Note: normal-tissue-liability is the only
# protein_ihc card; cellline-rna-protein-concordance is RNA-anchored (protein-as-comparator).
CARD_CONTEXT = {
    "cellline-rna-distribution":            ("bulk_rna", "cell_line"),
    "tumor-rna-vs-adjacent":                ("bulk_rna", "tumor"),
    "tumor-rna-distribution":               ("bulk_rna", "tumor"),
    "tumor-rna-distribution-by-subtype":    ("bulk_rna", "tumor"),
    "cellline-rna-distribution-by-subtype": ("bulk_rna", "cell_line"),
    "tumor-protein-abundance-cptac":        ("bulk_protein_ms", "tumor"),
    "cellline-protein-abundance":           ("bulk_protein_ms", "cell_line"),
    "tumor-elevation-breadth":              ("bulk_protein_ms", "tumor"),
    "expression-purity-confound":           ("bulk_rna", "tumor"),
    "cellline-rna-protein-concordance":     ("bulk_rna", "cell_line"),
    "rna-protein-concordance-tumor":        ("bulk_rna", "tumor"),
    "tumor-scrna-celltype-expression":      ("sc_rna", "tumor"),
    "normal-tissue-liability":              ("protein_ihc", "normal"),
    "sc-normal-celltype-expression":        ("sc_rna", "normal"),
}


def _ctx_key(measurement: str, sample_context: str) -> str:
    """The stable string key for a bucket, e.g. `bulk_rna/cell_line` — the key surfaced in
    presence_verdict_by_modality."""
    return f"{measurement}/{sample_context}"


# The enumerated universe of buckets this skill reports on. Buckets with no card emit an
# explicit `data_unavailable` (a NAMED gap, not silence). Ordered for stable output.
ALL_CONTEXTS = (
    ("bulk_rna", "cell_line"),
    ("bulk_rna", "tumor"),
    ("bulk_protein_ms", "cell_line"),
    ("bulk_protein_ms", "tumor"),
    ("sc_rna", "tumor"),          # card-backed; measured for the wired sc indications, else data_unavailable
    ("sc_rna", "normal"),         # safety comparator (sc-normal-celltype-expression)
    ("protein_ihc", "normal"),    # safety comparator (normal-tissue-liability HPA IHC)
)

QUESTION = ("Is {target} expressed in {indication} tumor tissue, and how "
            "does its expression distribute across cancer cell lines vs. "
            "paired tumor/adjacent samples?")


# ─── The three measurement ladders (highest-precedence first; rule_id -> verdict) ────────
# bulk_rna cards fire `expression-*` / `tumor-expression-*` rules; bulk_protein_ms fire
# `protein-*` / `protein-abundance-*` / `tumor-breadth-*` rules; sc_rna fire `sc-expression-*`.
# See CONTRACT.md § "Headline lens" for why the tumor-tissue rungs outrank the cell-line proxy,
# and § "Collapse invariants" for why the killers rank below every direct tumor-present read.

_EXPRESSION_RANK: list[tuple[str, str]] = [
    # Tumor-tissue rungs outrank the pan-cancer cell-line proxy for the headline (backtest-gated;
    # frozen by test_reanchor_flip_matrix.py). Cell-line broadly_high is kept at the top: when both
    # lenses read high the verdict is unchanged. tumor_sparsely_expressed (neutral) stays below the
    # cell-line positives. The two cell-line/differential KILLERS rank below every direct tumor read,
    # so a target broadly-low in cell lines but broadly-high in the actual tumor is not a false negative.
    ("expression-broadly-high-supportive",               "broadly_high_expression"),       # cell-line high (both-high agree)
    ("expression-strong-upregulation-supportive",        "strongly_upregulated_in_tumor"), # tumor-vs-adjacent
    ("tumor-expression-broadly-high-supportive",         "tumor_broadly_expressed"),        # tumor tissue (> cell-line moderate/restricted)
    ("expression-modest-upregulation-neutral",           "modestly_upregulated_in_tumor"), # tumor-vs-adjacent
    ("tumor-expression-broadly-moderate-neutral",        "tumor_moderately_expressed"),     # tumor tissue
    ("expression-lineage-restricted-supportive",         "lineage_restricted"),             # cell-line proxy
    ("expression-broadly-moderate-neutral",              "broadly_moderate_expression"),    # cell-line proxy
    ("tumor-expression-broadly-low-neutral",             "tumor_sparsely_expressed"),       # per-indication sparse (neutral)
    ("expression-modest-downregulation-opposing",        "modestly_downregulated_in_tumor"),
    ("expression-strong-downregulation-degrader-killer", "strongly_downregulated_in_tumor"),
    ("expression-broadly-low-degrader-killer",           "broadly_low_expression"),         # cell-line killer, below tumor reads
    ("expression-call-not-informative-degrader-killer",  "not_informative"),
    # coverage gaps sink to the bottom (measured-first invariant)
    ("expression-data-unavailable-insufficient",         "data_unavailable"),
    ("expression-call-data-unavailable-insufficient",    "data_unavailable"),
    ("tumor-expression-data-unavailable-insufficient",   "data_unavailable"),
]

# bulk_protein_ms ladder. Covers three protein cards (CPTAC per-indication contrast + Gygi cell-line
# distribution + pan-cancer breadth). Positives first; measured-absence killers rank above
# data_unavailable so a measured "protein not detected" is never swallowed. Breadth ranks below the
# per-indication positives (more decision-relevant) but is the only protein-tumor card a target-only
# query fires — it gives that bucket a real `measured` verdict. Breadth is never a killer.
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
    ("protein-modestly-down-opposing",                  "protein_modestly_downregulated"),
    ("protein-strongly-down-opposing",                  "protein_strongly_downregulated"),
    # (protein-not-detected-degrader-killer removed 2026-08-20, review G2a: the CPTAC classifier never
    #  emits not_detected — whole-proteome TMT can't assert per-gene absence; target-contracts #467
    #  retired the rule. The reachable protein-absence signal is the cell-line-MS broadly_low rung below.)
    ("protein-abundance-broadly-low-degrader-killer",   "protein_broadly_low"),
    ("protein-data-unavailable-insufficient",           "data_unavailable"),
    ("protein-abundance-data-unavailable-insufficient", "data_unavailable"),
    ("tumor-breadth-data-unavailable-insufficient",     "data_unavailable"),
]

# sc_rna ladder. Single-cell cards fire `sc-expression-*` rules (malignant-anchored per-compartment
# presence). microenvironment_dominant is NEUTRAL (present in the tumor but not malignant-cell-intrinsic
# — a caveat, not an absence). NO killer: a per-indication single-cell read cannot kill a target-wide
# nomination (same discipline as the bulk tumor-RNA rules).
_SC_RNA_RANK: list[tuple[str, str]] = [
    ("sc-expression-malignant-broadly-detected-supportive", "sc_malignant_detected"),
    ("sc-expression-microenvironment-dominant-neutral",     "sc_microenvironment_dominant"),
    ("sc-expression-broadly-low-neutral",                   "sc_broadly_low"),
    ("sc-expression-data-unavailable-insufficient",         "data_unavailable"),
]

# Per-MEASUREMENT ladder selection. The rule vocabulary is a function of the measurement layer only, so
# the ladder is keyed by measurement even though the bucket is keyed by the (measurement, sample_context)
# pair. Measurements without a card (protein_ihc) have no ladder → their buckets emit data_unavailable.
_MEASUREMENT_RANK: dict[str, list[tuple[str, str]]] = {
    "bulk_rna": _EXPRESSION_RANK,
    "bulk_protein_ms": _PROTEIN_RANK,
    "sc_rna": _SC_RNA_RANK,
}

# ─── The collapse (see CONTRACT.md § "Collapse invariants") ──────────────────────────────
# Measured verdict strings that are PRESENCE-NEGATIVE (target down/absent). Everything else measured is
# presence-positive-or-neutral. Coverage gaps (data_unavailable) PLUS the tumor-vs-adjacent
# `not_informative` read (a flat differential is a coverage gap, not a measured negative) sink last.
_MEASURED_NEGATIVE_VERDICTS = frozenset({
    "modestly_downregulated_in_tumor", "strongly_downregulated_in_tumor", "broadly_low_expression",
    "protein_modestly_downregulated", "protein_strongly_downregulated",
    "protein_not_detected", "protein_broadly_low",
})
_COLLAPSE_GAP_VERDICTS = frozenset({"data_unavailable", "not_informative"})


def _partition_measured(ladder: list[tuple[str, str]]) -> tuple[list, list, list]:
    """Split a ladder into (presence-POSITIVE, presence-NEGATIVE, coverage-GAP) rungs, preserving
    within-tier order."""
    positives = [(rid, v) for rid, v in ladder
                 if v not in _MEASURED_NEGATIVE_VERDICTS and v not in _COLLAPSE_GAP_VERDICTS]
    negatives = [(rid, v) for rid, v in ladder if v in _MEASURED_NEGATIVE_VERDICTS]
    gaps = [(rid, v) for rid, v in ladder if v in _COLLAPSE_GAP_VERDICTS]
    return positives, negatives, gaps


_EXPR_POS, _EXPR_NEG, _EXPR_GAP = _partition_measured(_EXPRESSION_RANK)
_PROT_POS, _PROT_NEG, _PROT_GAP = _partition_measured(_PROTEIN_RANK)
_SC_POS, _SC_NEG, _SC_GAP = _partition_measured(_SC_RNA_RANK)
# Collapsed order: all measured POSITIVES (RNA backbone first), then all measured NEGATIVES, then gaps.
# A measured positive in ANY modality outranks a measured negative in another; RNA stays the backbone
# within each tier (byte-stable for positive-RNA targets).
_VERDICT_RANK: list[tuple[str, str]] = (
    _EXPR_POS + _PROT_POS + _SC_POS
    + _EXPR_NEG + _PROT_NEG + _SC_NEG
    + _EXPR_GAP + _PROT_GAP + _SC_GAP
)


def _rank_verdict(fired: list[dict], ladder: list[tuple[str, str]] | None = None) -> tuple[str, str | None]:
    """Rank-ordered verdict from a set of fired rules against a ladder (default = the collapsed ladder)."""
    ladder = ladder if ladder is not None else _VERDICT_RANK
    fired_by_id = {r["rule_id"]: r for r in fired}
    for rid, verdict in ladder:
        if rid in fired_by_id:
            return verdict, rid
    return "insufficient", None


# Rule-id sets by lens/polarity (from the partitions above) — used by the post-collapse protein-absence
# demotion. Expression(RNA)-positive rungs, protein-positive rungs.
_EXPR_POS_RIDS = frozenset(rid for rid, _ in _EXPR_POS)
_PROT_POS_RIDS = frozenset(rid for rid, _ in _PROT_POS)

# Genuine protein-ABSENCE rule-ids — the ONLY protein negatives that justify demoting a present RNA
# call to `present_rna_only_protein_absent`. This is a STRICT SUBSET of the protein measured-negatives:
# a tumor-vs-normal DOWN contrast (protein-{modestly,strongly}-down-opposing) means the protein was
# MEASURED PRESENT but is lower in tumor than matched normal — a Phase-B SELECTIVITY signal, NOT absence
# (Phase A). Demoting a present call to "protein_absent" off a down-contrast is a category error (the
# tumor-presence expert-review finding G2b), so those rungs are deliberately EXCLUDED here. Absence =
# cell-line whole-panel broadly_low (detected in <30% of the Gygi MS panel, AND — post the
# depmap_protein_abundance lineage-restricted-floor fix — not a rescued lineage-restricted antigen). The
# down-contrasts remain in _MEASURED_NEGATIVE_VERDICTS so the collapse ordering + the
# `presence_headline_conflict` guard still surface them per-bucket — only the WORD-level demotion is
# narrowed. (CPTAC not_detected is NOT here: whole-proteome TMT can't assert per-gene absence — a missing
# protein resolves to data_unavailable, not a measured negative — so target-contracts #467 retired that
# dead rule + card vocab; the cell-line broadly_low rung is the reachable protein-absence signal.)
_PROTEIN_ABSENCE_RIDS = frozenset({
    "protein-abundance-broadly-low-degrader-killer",   # cell-line: broadly-low MS detection (genuine absence)
})

# The demoted-positive verdict (Principle 1 Stage B). Minted post-collapse: it is a CONJUNCTION
# (RNA-positive AND a MEASURED protein-negative AND no protein-positive), which the single-field ladder
# grammar cannot express as a rung. It is still a PRESENT call (RNA established presence), so
# _is_presence_positive treats it as positive — but the WORD now carries the protein-absence caveat, so
# a consumer reading only the one-word verdict (not presence_verdict_by_modality) is not falsely
# reassured. Verdict-inert to the nomination spine (presence ∉ target-profile _SHORT_TO_GATE).
PRESENT_RNA_ONLY_PROTEIN_ABSENT = "present_rna_only_protein_absent"


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """COLLAPSED presence verdict across ALL modalities — the audit spine the target-profile consumer +
    risk table read as `verdict`. Resolved INLINE (not via a *.resolver.yaml) by design; see CONTRACT.md
    § "Why the verdict is resolved inline". Frozen by test_per_modality_verdict.py + the ladder-invariant
    + regression matrices.

    Post-collapse PROTEIN-ABSENCE DEMOTION (Principle 1 Stage B): the positives-over-negatives collapse
    ranks an RNA positive above a MEASURED protein-negative, so an RNA-high target whose protein is
    measured ABSENT (`broadly_low`/`not_detected`) would otherwise read as an un-caveated present call in
    the one word. When the winning rung is an RNA(expression)-lens positive AND a genuine protein-ABSENCE
    rule fired (see `_PROTEIN_ABSENCE_RIDS`) AND NO protein-positive fired, the verdict is demoted to
    `present_rna_only_protein_absent` (still a present call — the driving RNA rung is retained for
    traceability — but the word now carries the caveat that `presence_headline_conflict` also surfaces).

    NOTE (finding G2b): the trigger is genuine ABSENCE only, NOT a tumor-vs-normal down-CONTRAST. A
    protein measured present-but-lower in tumor (protein-{modestly,strongly}-down-opposing) is a
    selectivity signal, not absence, and must not demote a present call to "protein_absent". Those rungs
    stay in the collapse's measured-negative tier (and in the headline_conflict guard) but are excluded
    from `_PROTEIN_ABSENCE_RIDS`."""
    v, drv = _rank_verdict(fired)
    fired_rids = {r["rule_id"] for r in fired}
    if (drv in _EXPR_POS_RIDS
            and (fired_rids & _PROTEIN_ABSENCE_RIDS)
            and not (fired_rids & _PROT_POS_RIDS)):
        return PRESENT_RNA_ONLY_PROTEIN_ABSENT, drv
    return v, drv


# Safety-comparator buckets: the card's OWN rules are on the safety/selectivity axis, not presence, so
# these buckets carry a labeled comparator readout (evidence_state='comparator'), never a ranked presence
# sub-verdict. (bucket) -> (card_id, field carrying the comparator class).
_COMPARATOR_BUCKETS = {
    ("protein_ihc", "normal"): ("normal-tissue-liability", "normal_tissue_breadth_class"),
    ("sc_rna", "normal"):      ("sc-normal-celltype-expression", "sc_normal_expression_class"),
}

# (bucket) -> (card_id, field, {raw_class: bucket_verdict}) for cards that emit a MEASURED-PRESENT class
# that fires no rule by design (so cannot rank into a ladder). Used to mark such a bucket `measured`
# instead of data_unavailable. tumor-protein-abundance-cptac's flat classes = protein quantified but not
# tumor-elevated (present in both tumor and normal). `ns` is the pre-split legacy key, kept for
# backward-compat; `not_significant`/`small_effect` are the current split (both mean present-but-flat).
_MEASURED_UNRULED_PRESENT = {
    ("bulk_protein_ms", "tumor"): ("tumor-protein-abundance-cptac", "protein_expression_class",
                                   {"ns": "protein_present_not_elevated",
                                    "not_significant": "protein_present_not_elevated",
                                    "small_effect": "protein_present_not_elevated"}),
}


def _per_modality_verdicts(fired: list[dict], cards: list[dict] | None = None) -> dict[str, dict]:
    """One sub-verdict PER (measurement, sample_context) bucket. Groups fired rules by the card's bucket
    (via CARD_CONTEXT), then ranks WITHIN each group using the ladder for that group's measurement.
    Buckets with no card emit an explicit `data_unavailable`. Returns a map keyed by
    `measurement/sample_context` -> {measurement, sample_context, verdict, driving_rule_id, evidence_state}
    where evidence_state ∈ {measured, comparator, data_unavailable}. Additive: does NOT touch the
    collapsed presence_verdict."""
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
            # Comparator bucket: never rank a fired rule. Checked BEFORE the `group` branch so a cross-axis
            # rule that keys a comparator card (e.g. the tumor-selectivity critical-organ veto on
            # sc-normal-celltype-expression) does not collapse the bucket to `insufficient` and erase the
            # comparator readout for exactly the critical-organ targets where it matters most.
            card_id, field = _COMPARATOR_BUCKETS[(measurement, sample_context)]
            # get_card_field RAISES on an absent card_id, so only call it when the card actually resolved.
            _present = {c["card_id"] for c in (cards or [])}
            val = get_card_field(cards, card_id, field) if card_id in _present else None
            if val not in (None, "data_unavailable"):
                out[key] = {"measurement": measurement, "sample_context": sample_context,
                            "verdict": val, "driving_rule_id": None, "evidence_state": "comparator"}
            else:
                out[key] = {"measurement": measurement, "sample_context": sample_context,
                            "verdict": "data_unavailable", "driving_rule_id": None,
                            "evidence_state": "data_unavailable"}
        elif group:
            v, drv = _rank_verdict(group, _MEASUREMENT_RANK.get(measurement))
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": v, "driving_rule_id": drv, "evidence_state": "measured"}
        else:
            out[key] = {"measurement": measurement, "sample_context": sample_context,
                        "verdict": "data_unavailable", "driving_rule_id": None,
                        "evidence_state": "data_unavailable"}

        # Rescue a resolved-but-UNRULED PRESENT read (e.g. CPTAC flat class) from data_unavailable →
        # `measured`, WITHOUT authoring a gate rule. Distinguishes "measured, flat" from "not measured".
        if out[key]["verdict"] == "data_unavailable" and (measurement, sample_context) in _MEASURED_UNRULED_PRESENT:
            card_id, field, class_map = _MEASURED_UNRULED_PRESENT[(measurement, sample_context)]
            _present = {c["card_id"] for c in (cards or [])}
            raw = get_card_field(cards, card_id, field) if card_id in _present else None
            if raw in class_map:
                out[key] = {"measurement": measurement, "sample_context": sample_context,
                            "verdict": class_map[raw], "driving_rule_id": None, "evidence_state": "measured"}
    return out


# RNA presence-verdict values that are a measured-positive bulk-RNA presence call. Used only to QUALIFY
# the RNA call by its protein-proxy quality — never to change it.
_RNA_PRESENCE_POSITIVE = frozenset({
    "broadly_high_expression", "strongly_upregulated_in_tumor", "lineage_restricted",
    "modestly_upregulated_in_tumor", "broadly_moderate_expression",
    "tumor_broadly_expressed", "tumor_moderately_expressed",
})


def _bulk_rna_proxy_quality(per_modality: dict, rna_as_biomarker) -> str:
    """VERDICT-INERT qualifier: when a bulk-RNA presence call is measured-positive, how well does RNA
    proxy the protein it implies? Prefers the tumor arm; falls back to the cell-line arm. Never moves
    presence_verdict (one-directional). Values: rna_confirmed_by_protein / rna_positive_proxy_partial /
    rna_positive_proxy_poor / proxy_untested / not_applicable."""
    def _bucket_verdict(key):
        b = (per_modality or {}).get(key)
        return b.get("verdict") if isinstance(b, dict) else b
    # Prefer the tumor arm when it is itself a measured-positive RNA call; else fall back to cell-line.
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
    return "proxy_untested"


# Presence-TIER ordinal for the RNA-lens verdict vocab. Used only to detect when the collapsed headline
# understates the tumor-tissue lens (a now guard-only condition — see CONTRACT.md § "Headline lens").
_PRESENCE_TIER = {
    "broadly_high_expression": 3, "strongly_upregulated_in_tumor": 3, "tumor_broadly_expressed": 3,
    "broadly_moderate_expression": 2, "modestly_upregulated_in_tumor": 2, "tumor_moderately_expressed": 2,
    "lineage_restricted": 1, "broadly_low_expression": 1, "tumor_sparsely_expressed": 1,
}


def _headline_lens_discordance(driving_rule_id: str | None, per_modality: dict):
    """Which bucket drove the collapsed headline, and does the tumor-tissue RNA lens read a HIGHER
    presence tier than the cell-line lens that anchored it? Returns (headline_lens_key_or_None,
    cell_line_vs_tumor_discordant_bool). Additive / verdict-inert."""
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


def _top_essential_cell_types(flags, n: int = 8) -> list[dict]:
    """Rank the normal-tissue safety-essential cell types by detection fraction (descending) and keep the
    top N — the human-facing summary of the full `safety_essential_flags` dict (which is bulky and kept
    verbatim as sc_normal_safety_essential_flags). Verdict-inert; empty when there is nothing to rank."""
    if not isinstance(flags, dict) or not flags:
        return []
    ranked = sorted(flags.items(), key=lambda kv: (kv[1] if kv[1] is not None else -1.0), reverse=True)
    return [{"cell_type": ct, "detection_fraction": det} for ct, det in ranked[:n]]


# ─── Robustness facets (VERDICT-INERT — additive keys only, spine byte-stable) ────────────
# A presence-POSITIVE collapsed verdict is a measured verdict that is neither a measured-negative nor a
# coverage gap nor the empty `insufficient`. Mirrors the positive tier of _partition_measured.
def _is_presence_positive(verdict: str | None) -> bool:
    return bool(verdict) and verdict not in _MEASURED_NEGATIVE_VERDICTS \
        and verdict not in _COLLAPSE_GAP_VERDICTS and verdict != "insufficient"


def _headline_conflict(collapsed_verdict, per_modality):
    """VERDICT-INERT safety guard (Principle 1): the collapsed headline reads PRESENT (a measured
    positive) while another modality carries a MEASURED presence-NEGATIVE (e.g. RNA broadly_high but
    CPTAC protein `not_detected`). The collapse intentionally ranks measured positives over measured
    negatives to protect antigens that de-differentiate in 2D culture; that same rule can bury a
    measured protein-absence under an RNA positive in the one-word headline. This flag makes the buried
    killer legible without moving the spine. Returns (conflict_bool, note_or_None, [bucket_keys])."""
    if not _is_presence_positive(collapsed_verdict):
        return False, None, []
    killers = sorted(k for k, b in (per_modality or {}).items()
                     if isinstance(b, dict) and b.get("evidence_state") == "measured"
                     and b.get("verdict") in _MEASURED_NEGATIVE_VERDICTS)
    if not killers:
        return False, None, []
    note = (f"presence_verdict reads present ({collapsed_verdict}) but a MEASURED presence-negative was "
            f"recorded in: {', '.join(killers)}. The collapse ranks measured positives over measured "
            f"negatives (protects de-differentiating antigens), so this killer is not in the one-word "
            f"headline — confirm the target is present in the negative modality before any read that "
            f"depends on it (e.g. a protein `not_detected` undercuts an ADC/degrader/TCE call).")
    return True, note, killers


# Abundance-LEVEL anchors: the allgene percentile of the target's expression/abundance LEVEL. The
# CPTAC and RNA-vs-adjacent percentiles rank a tumor-vs-normal CONTRAST (effect size), NOT a level, so
# they are deliberately excluded — a low contrast-rank is not low abundance.
_LEVEL_ANCHOR_CARDS = (
    ("tumor-rna-distribution",     "tumor RNA level"),
    ("cellline-rna-distribution",  "cell-line RNA level"),
    ("cellline-protein-abundance", "cell-line protein level"),
)


def _abundance_floor(cards, collapsed_verdict):
    """VERDICT-INERT (Principle 2 — breadth != level): a presence-POSITIVE call whose absolute abundance
    LEVEL reads bottom-decile (allgene percentile) in at least one lens. The presence classes are
    breadth-of-detection dominant (e.g. a protein detected in 100% of cell lines but bottom-decile
    abundance still classes `broadly_moderate`), so `broadly_moderate` must never be read as `abundant`
    without checking the level anchor. Returns (flag_or_None, [low_lens_dicts])."""
    if not _is_presence_positive(collapsed_verdict):
        return None, []
    low = []
    for card_id, label in _LEVEL_ANCHOR_CARDS:
        klass = get_card_field(cards, card_id, "allgene_percentile_class")
        if klass == "bottom_decile":
            low.append({"lens": label, "card_id": card_id, "allgene_percentile_class": klass})
    return ("present_low_abundance" if low else "adequate_abundance"), low


# ─── Protein-confirmation state (VERDICT-INERT headline facet — finding G5) ───────────────
# The collapsed one-word presence_verdict, for a positive-RNA target, can read `present` while protein
# was never TESTED (most indications have no CPTAC / cell-line-MS coverage — the modal case). The
# measured-ABSENT contradiction is handled at the spine (present_rna_only_protein_absent, a rare +
# alarming state); the UNTESTED case is not a different presence STATE, it is lower CONFIDENCE, so it is
# surfaced here as a legibility facet rather than minting a new default spine word (which would rewrite
# the modal verdict and conflate confidence with presence-state). States:
#   confirmed        — protein MEASURED PRESENT in >=1 protein bucket (tumor CPTAC or cell-line MS)
#   measured_absent  — protein MEASURED ABSENT (broadly_low / not_detected) and nowhere confirmed present
#   untested         — no protein bucket is `measured` (protein coverage gap) — RNA-only presence
#   not_applicable   — the collapsed verdict is not a presence-positive
# A protein PRESENT reading in ANY context wins (cell-line MS under-samples surface antigens, so a
# tumor-CPTAC-present / cell-line-absent target is confirmed present) — mirrors the positives-over-
# negatives collapse philosophy. Verdict-inert: never touches presence_verdict.
_PROTEIN_PRESENT_VERDICTS = frozenset(v for _, v in _PROT_POS) | {
    "protein_present_not_elevated",                                    # M2 rescue: quantified, flat
    "protein_modestly_downregulated", "protein_strongly_downregulated",  # measured present-but-lower
}
_PROTEIN_ABSENT_VERDICTS = frozenset({"protein_broadly_low", "protein_not_detected"})


def _protein_confirmation_state(per_modality: dict, collapsed_verdict: str | None) -> str:
    """VERDICT-INERT confidence facet: was the (present) presence call CONFIRMED at the protein level,
    contradicted by a measured protein absence, or is protein simply UNTESTED? See the block comment."""
    if not _is_presence_positive(collapsed_verdict):
        return "not_applicable"
    measured = [b.get("verdict") for k in ("bulk_protein_ms/tumor", "bulk_protein_ms/cell_line")
                for b in [(per_modality or {}).get(k) or {}]
                if b.get("evidence_state") == "measured"]
    if any(v in _PROTEIN_PRESENT_VERDICTS for v in measured):
        return "confirmed"
    if any(v in _PROTEIN_ABSENT_VERDICTS for v in measured):
        return "measured_absent"
    return "untested"


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    per_modality = _per_modality_verdicts(fired, cards)
    # Legibility flag for a cell-line-anchored headline that understates the tumor-tissue lens.
    _headline_lens, _cl_tumor_discordant = _headline_lens_discordance(drv, per_modality)
    _tumor_bucket = (per_modality or {}).get("bulk_rna/tumor") or {}
    _presence_interpretation_note = (
        ("presence_verdict inherits the pan-cancer cell-line RNA lens; the tumor-tissue lens "
         f"reads a higher presence tier ({_tumor_bucket.get('verdict')}). Read "
         "presence_verdict_by_modality['bulk_rna/tumor'] — the one-word headline understates "
         "tumor-tissue presence for this target (typical of antigens that de-differentiate in "
         "2D culture).")
        if _cl_tumor_discordant else None)
    # Robustness facets (verdict-inert): a measured presence-negative buried under the positive headline
    # (Principle 1), and a presence-positive whose absolute abundance level reads bottom-decile
    # (Principle 2). Both are additive legibility guards; neither touches v / drv / per_modality.
    _hl_conflict, _hl_conflict_note, _hl_conflict_buckets = _headline_conflict(v, per_modality)
    _abundance_floor_flag, _abundance_low_lenses = _abundance_floor(cards, v)
    # RNA→protein proxy quality: prefer the tumor arm (the disease-context proxy), fall back to cell-line.
    _rna_biomarker = get_card_field(cards, "cellline-rna-protein-concordance", "rna_as_biomarker")
    _rna_biomarker_tumor = get_card_field(cards, "rna-protein-concordance-tumor", "rna_as_biomarker")
    _proxy_biomarker = (_rna_biomarker_tumor
                        if _rna_biomarker_tumor in ("adequate_proxy", "partial_proxy", "poor_proxy")
                        else _rna_biomarker)
    _sc_normal_flags = get_card_field(cards, "sc-normal-celltype-expression", "safety_essential_flags")
    hl = {
        # COLLAPSED verdict — the audit spine target-profile reads as `verdict`.
        "presence_verdict":              v,
        "driving_rule_id":               drv,
        # Per-(measurement, sample_context) sub-verdicts — always read this, not just the collapsed word.
        "presence_verdict_by_modality":  per_modality,
        # Lens-discordance facet (verdict-inert). cell_line_vs_tumor_discordant is a standing invariant
        # guard: it should be False for every target (see CONTRACT.md § "Headline lens").
        "headline_lens":                 _headline_lens,
        "cell_line_vs_tumor_discordant": _cl_tumor_discordant,
        # Robustness guards (verdict-inert). presence_headline_conflict surfaces a MEASURED
        # presence-negative that the positive-over-negative collapse buried under the headline word.
        "presence_headline_conflict":            _hl_conflict,
        "presence_headline_conflict_note":       _hl_conflict_note,
        "presence_headline_conflict_modalities": _hl_conflict_buckets,
        # abundance_floor_flag: a presence-positive whose absolute LEVEL is bottom-decile in >=1 lens
        # (breadth-of-detection classes hide low absolute abundance). presence_abundance_is_relative
        # names the capability ceiling: every protein signal here is RELATIVE (TMT ratios / percentiles),
        # never copies/cell — do NOT infer "enough antigen" for a modality decision from a presence call.
        "abundance_floor_flag":          _abundance_floor_flag,
        "abundance_floor_low_lenses":    _abundance_low_lenses,
        "presence_abundance_is_relative": True,
        # protein_confirmation_state (finding G5): is a PRESENT call protein-confirmed, protein-measured-
        # absent, or protein-UNTESTED (RNA-only)? Verdict-inert legibility of the confidence behind the
        # one-word headline — most indications lack CPTAC/cell-line-MS, so a positive-RNA target commonly
        # reads present with protein untested; this names that state instead of silently over-reassuring.
        "protein_confirmation_state":    _protein_confirmation_state(per_modality, v),
        "presence_interpretation_note":  _presence_interpretation_note,
        # ── Bulk RNA ──────────────────────────────────────────────────────────
        "median_log2tpm_panel":     get_card_field(cards, "cellline-rna-distribution", "median_log2tpm_panel"),
        "expression_call_class":    get_card_field(cards, "cellline-rna-distribution", "expression_class"),
        "tva_log2_fc":              get_card_field(cards, "tumor-rna-vs-adjacent", "log2_fc"),
        "tva_q_value":              get_card_field(cards, "tumor-rna-vs-adjacent", "q_value"),
        "tva_expression_call":      get_card_field(cards, "tumor-rna-vs-adjacent", "expression_call_class"),
        # ── Bulk protein (whole-cell-lysate MS) ───────────────────────────────
        "protein_expression_class": get_card_field(cards, "tumor-protein-abundance-cptac", "protein_expression_class"),
        "protein_effect_size":      get_card_field(cards, "tumor-protein-abundance-cptac", "protein_effect_size"),
        # Variance-standardized companion to the RAW protein_effect_size (analysis-methods #432 / card
        # #450). protein_expression_class thresholds on the raw log2 effect, blind to variance; the
        # standardized class/d expose a `modest_up` that only cleared significance via cohort size.
        # Verdict-inert context (does not touch the ladder).
        "protein_effect_standardized_class":  get_card_field(cards, "tumor-protein-abundance-cptac", "protein_effect_standardized_class"),
        "protein_effect_cohens_d":            get_card_field(cards, "tumor-protein-abundance-cptac", "protein_effect_cohens_d"),
        "protein_effect_standardized_t":      get_card_field(cards, "tumor-protein-abundance-cptac", "protein_effect_standardized_t"),
        "protein_effect_standardized_method": get_card_field(cards, "tumor-protein-abundance-cptac", "protein_effect_standardized_method"),
        # Pan-cancer tumor-elevation breadth (target-grain): protein layer feeds the ladder, RNA layer is
        # display-only. Surfaced side-by-side (never averaged) with breadth_layer_concordance.
        "tumor_elevation_breadth_class":      get_card_field(cards, "tumor-elevation-breadth", "tumor_elevation_breadth_class"),
        "tumor_elevation_n_cohorts_elevated": get_card_field(cards, "tumor-elevation-breadth", "n_cohorts_elevated"),
        "tumor_elevation_n_cohorts_tested":   get_card_field(cards, "tumor-elevation-breadth", "n_cohorts_tested"),
        "rna_tumor_elevation_breadth_class":         get_card_field(cards, "tumor-elevation-breadth", "rna_tumor_elevation_breadth_class"),
        "rna_tumor_elevation_n_indications_elevated": get_card_field(cards, "tumor-elevation-breadth", "rna_n_indications_elevated"),
        "rna_tumor_elevation_n_indications_tested":   get_card_field(cards, "tumor-elevation-breadth", "rna_n_indications_tested"),
        "breadth_layer_concordance":                 get_card_field(cards, "tumor-elevation-breadth", "breadth_layer_concordance"),
        # ── Verdict-inert facets ──────────────────────────────────────────────
        "purity_confound_class":       get_card_field(cards, "expression-purity-confound", "purity_confound_class"),
        "expression_purity_pearson_r": get_card_field(cards, "expression-purity-confound", "expression_purity_pearson_r"),
        # RNA-as-protein-proxy quality — both arms surfaced side-by-side (their disagreement is the signal).
        "rna_as_biomarker":         _rna_biomarker,
        "rna_protein_r":            get_card_field(cards, "cellline-rna-protein-concordance", "rna_protein_r"),
        "rna_as_biomarker_tumor":   _rna_biomarker_tumor,
        "rna_protein_r_tumor":      get_card_field(cards, "rna-protein-concordance-tumor", "rna_protein_r"),
        "rna_protein_n_paired_tumors": get_card_field(cards, "rna-protein-concordance-tumor", "n_paired_tumors"),
        "rna_protein_cptac_cohort": get_card_field(cards, "rna-protein-concordance-tumor", "cptac_cohort"),
        "bulk_rna_proxy_quality":   _bulk_rna_proxy_quality(per_modality, _proxy_biomarker),
        "bulk_rna_proxy_quality_source": ("tumor" if _rna_biomarker_tumor in
                                          ("adequate_proxy", "partial_proxy", "poor_proxy") else "cell_line"),
        # Subtype panoramas (tumor + cell-line) — one-directional confidence/context, never a veto.
        "subtype_scope_available":      get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_axis_available"),
        "n_subtypes_measured":          get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_measured"),
        "n_subtypes_enriched":          get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_enriched"),
        "spotlight_subtype":            get_card_field(cards, "tumor-rna-distribution-by-subtype", "spotlight_subtype"),
        "subtype_stratification_class": get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_stratification_class"),
        "n_subtypes_restricted":        get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_restricted"),
        "cellline_subtype_scope_available":      get_card_field(cards, "cellline-rna-distribution-by-subtype", "subtype_axis_available"),
        "cellline_n_subtypes_measured":          get_card_field(cards, "cellline-rna-distribution-by-subtype", "n_subtypes_measured"),
        "cellline_subtype_stratification_class": get_card_field(cards, "cellline-rna-distribution-by-subtype", "subtype_stratification_class"),
        "cellline_spotlight_subtype":            get_card_field(cards, "cellline-rna-distribution-by-subtype", "spotlight_subtype"),
        # ── Single-cell tumor (sc_rna/tumor) — verdict-bearing via _SC_RNA_RANK ──
        # sc_expression_class drives the ladder; the rest is per-compartment / CAF / homogeneity detail
        # that bulk cannot give (see CONTRACT.md § "Single-cell layer").
        "sc_expression_class":                 get_card_field(cards, "tumor-scrna-celltype-expression", "sc_expression_class"),
        "sc_malignant_detection_fraction":     get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_detection_fraction"),
        "sc_malignant_abundance_log1p_cp10k":  get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_abundance_log1p_cp10k"),
        "sc_malignant_compartment_available":  get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_compartment_available"),
        # Total malignant cells behind the sc call (analysis-methods G3 floor: MIN_MALIGNANT_CELLS_TOTAL).
        # Surfaced so a reader can see whether a `sc_malignant_detected` rests on a ~509k-cell COADREAD
        # cube or a thin pooled one — the power behind the detection fraction, not just the fraction.
        "sc_malignant_n_cells":                get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_n_cells"),
        "sc_malignant_n_donors":               get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_n_donors"),
        "sc_tce_homogeneity_class":            get_card_field(cards, "tumor-scrna-celltype-expression", "tce_homogeneity_class"),
        # Two-axis TCE antigen-escape readout (verdict-inert context; supersedes the lenient single-number
        # tce_homogeneity_class above). within-tumour coverage + INTER-donor consistency → escape class.
        "sc_within_tumor_coverage_class":      get_card_field(cards, "tumor-scrna-celltype-expression", "within_tumor_coverage_class"),
        "sc_inter_donor_consistency_class":    get_card_field(cards, "tumor-scrna-celltype-expression", "inter_donor_consistency_class"),
        "sc_tce_antigen_escape_class":         get_card_field(cards, "tumor-scrna-celltype-expression", "tce_antigen_escape_class"),
        "sc_malignant_detection_donor_iqr":    get_card_field(cards, "tumor-scrna-celltype-expression", "malignant_detection_donor_iqr"),
        "sc_fraction_donors_broadly_detecting": get_card_field(cards, "tumor-scrna-celltype-expression", "fraction_donors_broadly_detecting"),
        "sc_top_microenvironment_compartment":         get_card_field(cards, "tumor-scrna-celltype-expression", "top_microenvironment_compartment"),
        "sc_top_microenvironment_detection_fraction":  get_card_field(cards, "tumor-scrna-celltype-expression", "top_microenvironment_detection_fraction"),
        "sc_compartment_detection":            get_card_field(cards, "tumor-scrna-celltype-expression", "compartment_detection"),
        "sc_per_compartment":                  get_card_field(cards, "tumor-scrna-celltype-expression", "per_compartment"),
        "sc_caf_vs_malignant_class":           get_card_field(cards, "tumor-scrna-celltype-expression", "caf_vs_malignant_class"),
        "sc_caf_detection_fraction":           get_card_field(cards, "tumor-scrna-celltype-expression", "caf_detection_fraction"),
        "sc_caf_compartment_available":        get_card_field(cards, "tumor-scrna-celltype-expression", "caf_compartment_available"),
        "sc_n_compartments_measured":          get_card_field(cards, "tumor-scrna-celltype-expression", "n_compartments_measured"),
        "sc_n_donor_groups":                   get_card_field(cards, "tumor-scrna-celltype-expression", "n_donor_groups"),
        "sc_n_datasets":                       get_card_field(cards, "tumor-scrna-celltype-expression", "n_datasets"),
        # ── Normal-tissue comparators (window framing; safety verdict owned elsewhere) ──
        "normal_tissue_ihc_breadth_class":  get_card_field(cards, "normal-tissue-liability", "normal_tissue_breadth_class"),
        "normal_tissue_ihc_essential_flag": get_card_field(cards, "normal-tissue-liability", "essential_tissue_flag"),
        "sc_normal_expression_class":       get_card_field(cards, "sc-normal-celltype-expression", "sc_normal_expression_class"),
        "sc_normal_safety_essential_class": get_card_field(cards, "sc-normal-celltype-expression", "sc_normal_safety_essential_class"),
        "sc_normal_max_det_cell_type":      get_card_field(cards, "sc-normal-celltype-expression", "max_detection_cell_type"),
        "sc_normal_max_det_fraction":       get_card_field(cards, "sc-normal-celltype-expression", "max_detection_fraction"),
        "sc_normal_expressing_donor_fraction_max": get_card_field(cards, "sc-normal-celltype-expression", "expressing_donor_fraction_max"),
        "sc_normal_n_cell_types_above_20pct":      get_card_field(cards, "sc-normal-celltype-expression", "n_cell_types_above_20pct"),
        "sc_normal_tissues_queried":               get_card_field(cards, "sc-normal-celltype-expression", "tissues_queried"),
        # Ranked top-N summary of the (bulky) full flags dict, which is retained verbatim below.
        "sc_normal_top_essential_cell_types": _top_essential_cell_types(_sc_normal_flags),
        "sc_normal_safety_essential_flags":   _sc_normal_flags,
    }
    # Additive, verdict-INERT (2026-08-18): the modality-blind claim vector (A/B/C/D signal×reliability)
    # + a brief cited key-signals read. Both are projections over the headline just built; they NEVER
    # touch the presence_verdict spine (byte-stable, frozen by the golden-spine test). The claim vector
    # is the WITHIN-lens evidence integration this subskill owns; it rides the _synthesis_facet package
    # into the composed target-profile. See _skills_common/presence_claims.py.
    hl["claim_vector"] = presence_claim_vector(hl, cards)
    hl["key_signals"] = presence_key_signals(hl, cards)
    # SUBTYPE-scoped claim vector (per stratum) — when a (target, indication, subtype) is the question,
    # the pooled vector flattens the per-stratum signal (cf. CD274 broadly-low pooled but MSI-H-strong).
    # Projects A + distributional-B per stratum from the already-resolved per_subgroup_metrics; None when
    # the indication has no subtype axis. Verdict-inert, like the pooled vector.
    hl["claim_vector_by_subtype"] = presence_claim_vector_by_subtype(cards)
    # The 7-question (data · signal · confidence) summary rows — a projection over the just-built
    # headline + card fields (Signal from the claim_vector, Confidence from corroboration). Verdict-inert;
    # carried through _synthesis_facet so the composed target-profile dashboard renders the same table.
    hl["question_table"] = presence_question_table(hl, cards)
    return hl


# ─── Cross-modal reconciliation facet (consumed by the composed target-profile synthesis) ─
# The fan-out captures each sub-skill's `_verdict()` + raw card summaries, but not `_headline()`'s
# reconciliation — which, for tumor-presence, is the single most decision-relevant object: the
# per-(measurement, sample_context) sub-verdict matrix that makes cross-modal tension legible.
# `_synthesis_facet` is the uniform opt-in the fan-out looks for (mirrors `_verdict`). It reuses
# `_headline` (single source of truth), selects the reconciliation-relevant fields, and is verdict-inert
# (presence stays out of target-profile's _SHORT_TO_GATE).
_SYNTHESIS_FACET_KEYS = (
    "presence_verdict", "driving_rule_id",
    "presence_verdict_by_modality",       # the 7-bucket cross-modal matrix (the key object)
    "headline_lens", "cell_line_vs_tumor_discordant", "presence_interpretation_note",
    # Robustness guards — a buried measured-negative and a bottom-decile-abundance present call are
    # exactly the cross-modal tensions the composed reasoner must weigh.
    "presence_headline_conflict", "presence_headline_conflict_note", "presence_headline_conflict_modalities",
    "abundance_floor_flag", "abundance_floor_low_lenses", "presence_abundance_is_relative",
    "protein_confirmation_state",   # confirmed / measured_absent / untested (RNA-only) / not_applicable

    # Variance-standardized CPTAC effect — qualifies whether a `modest_up` is a real per-sample effect
    # or a large-cohort significance artifact (the raw-log2 class can't tell).
    "protein_effect_standardized_class", "protein_effect_cohens_d", "protein_effect_standardized_method",
    # RNA-as-protein-proxy quality (both arms) — qualifies an RNA-only presence claim
    "bulk_rna_proxy_quality", "bulk_rna_proxy_quality_source",
    "rna_as_biomarker", "rna_protein_r",
    "rna_as_biomarker_tumor", "rna_protein_r_tumor",
    # Single-cell malignant-vs-microenvironment attribution + TCE-relevant homogeneity + CAF confounder
    "sc_expression_class", "sc_malignant_detection_fraction", "sc_malignant_n_cells", "sc_malignant_n_donors",
    "sc_tce_homogeneity_class",
    "sc_within_tumor_coverage_class", "sc_inter_donor_consistency_class", "sc_tce_antigen_escape_class",
    "sc_caf_vs_malignant_class", "sc_top_microenvironment_compartment", "sc_compartment_detection",
    # Normal-tissue comparators — framing for the therapeutic window (verdict owned by
    # on-target-safety-liability; surfaced here so the reasoner weighs presence AGAINST the window).
    "normal_tissue_ihc_breadth_class", "normal_tissue_ihc_essential_flag",
    "sc_normal_expression_class", "sc_normal_safety_essential_class",
    "sc_normal_max_det_cell_type", "sc_normal_max_det_fraction", "sc_normal_top_essential_cell_types",
    # Modality-blind claim vector + brief cited read (the within-lens integration this subskill owns).
    "claim_vector", "claim_vector_by_subtype", "key_signals",
    # the 7-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
)


def _synthesis_facet(cards, fired, verdict_pair):
    """Compact, VERDICT-INERT cross-modal reconciliation block for the composed target-profile synthesis
    prompt. Reuses `_headline` (single source of truth) and returns the reconciliation-relevant subset.
    Never moves the verdict; safe to omit (fan-out treats absence as no-facet)."""
    h = _headline(cards, fired, verdict_pair)
    facet = {k: h.get(k) for k in _SYNTHESIS_FACET_KEYS}
    facet["_facet_note"] = (
        "Deterministic cross-modal reconciliation from tumor-presence (a FACET, not a gate; presence is "
        "verdict-inert to the nomination spine). Read presence_verdict_by_modality for cross-modal tension "
        "(RNA-high/protein-absent; tumor-high/normal-high; malignant vs microenvironment). The normal_* "
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
        # Skill-level graphics (opt-in --figures): the Presence × Context hero matrix + the
        # claim-vector (signal × reliability) figure. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
    ))
