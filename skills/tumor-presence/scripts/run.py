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


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.8.0"

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
    ("protein-not-detected-degrader-killer",            "protein_not_detected"),
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


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """COLLAPSED presence verdict across ALL modalities — the audit spine the target-profile consumer +
    risk table read as `verdict`. Resolved INLINE (not via a *.resolver.yaml) by design; see CONTRACT.md
    § "Why the verdict is resolved inline". Frozen by test_full_per_modality_golden_spine + the
    regression matrix."""
    return _rank_verdict(fired)


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
    # RNA→protein proxy quality: prefer the tumor arm (the disease-context proxy), fall back to cell-line.
    _rna_biomarker = get_card_field(cards, "cellline-rna-protein-concordance", "rna_as_biomarker")
    _rna_biomarker_tumor = get_card_field(cards, "rna-protein-concordance-tumor", "rna_as_biomarker")
    _proxy_biomarker = (_rna_biomarker_tumor
                        if _rna_biomarker_tumor in ("adequate_proxy", "partial_proxy", "poor_proxy")
                        else _rna_biomarker)
    _sc_normal_flags = get_card_field(cards, "sc-normal-celltype-expression", "safety_essential_flags")
    return {
        # COLLAPSED verdict — the audit spine target-profile reads as `verdict`.
        "presence_verdict":              v,
        "driving_rule_id":               drv,
        # Per-(measurement, sample_context) sub-verdicts — always read this, not just the collapsed word.
        "presence_verdict_by_modality":  per_modality,
        # Lens-discordance facet (verdict-inert). cell_line_vs_tumor_discordant is a standing invariant
        # guard: it should be False for every target (see CONTRACT.md § "Headline lens").
        "headline_lens":                 _headline_lens,
        "cell_line_vs_tumor_discordant": _cl_tumor_discordant,
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
        "sc_tce_homogeneity_class":            get_card_field(cards, "tumor-scrna-celltype-expression", "tce_homogeneity_class"),
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
    # RNA-as-protein-proxy quality (both arms) — qualifies an RNA-only presence claim
    "bulk_rna_proxy_quality", "bulk_rna_proxy_quality_source",
    "rna_as_biomarker", "rna_protein_r",
    "rna_as_biomarker_tumor", "rna_protein_r_tumor",
    # Single-cell malignant-vs-microenvironment attribution + TCE-relevant homogeneity + CAF confounder
    "sc_expression_class", "sc_malignant_detection_fraction", "sc_tce_homogeneity_class",
    "sc_caf_vs_malignant_class", "sc_top_microenvironment_compartment", "sc_compartment_detection",
    # Normal-tissue comparators — framing for the therapeutic window (verdict owned by
    # on-target-safety-liability; surfaced here so the reasoner weighs presence AGAINST the window).
    "normal_tissue_ihc_breadth_class", "normal_tissue_ihc_essential_flag",
    "sc_normal_expression_class", "sc_normal_safety_essential_class",
    "sc_normal_max_det_cell_type", "sc_normal_max_det_fraction", "sc_normal_top_essential_cell_types",
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
        # Skill-level hero graphic (opt-in --figures): the Presence × Context matrix + single-cell detail
        # panel over the computed headline. Additive / display-only (see presence_matrix.py).
        skill_figures_fn=emit_presence_matrix,
    ))
