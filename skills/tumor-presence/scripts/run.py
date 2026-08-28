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
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.narrator_lenses import TUMOR_PRESENCE as _LENS
from _skills_common import get_card_field, resolve_cards
from _skills_common.claim_record import assemble_claim_record
from _skills_common.presence_matrix import emit_presence_matrix
from _skills_common.presence_claims import (presence_claim_vector, presence_claim_vector_by_subtype,
                                            presence_key_signals)
from _skills_common.presence_question_table import presence_question_table
from _skills_common.headline_core import build_headline, HeadlineSpec
from _skills_common.headline_hero import emit_headline_hero
from _skills_common.subgroup_figure import emit_subgroup_figure
from _skills_common.presence_claims_figure import emit_claim_vector_figure
from _skills_common.presence_subtype_figure import emit_subtype_refinement_figure
from _skills_common.presence_cardboard_figure import emit_card_board_figure


# ── --subtypes panorama (opt-in, verdict-INERT) ───────────────────────────────────────────────────
# Power floor mirroring subgroup_common/panorama.py SUBGROUP_N_FLOOR + the card's min_n_required.
_SUBGROUP_N_FLOOR = 30
# The presence-by-subtype PANORAMA card. Like functional-requirement's subgroup-stratified-dependency,
# it needs externally-resolved strata (subgroup_context.resolved_strata_ids) and resolves on a SEPARATE,
# --subtypes-gated path (the dispatcher's subtype_panorama_fn hook), NEVER on the whole-cohort spine.
_SUBTYPE_PANORAMA_CARDS = ["tumor-rna-distribution-by-subtype"]


def _stratum_presence_call(rec: dict) -> str:
    """Coarse per-stratum presence call from a per_subgroup_metrics record's tumor_expression_class.
    present / low_present / absent / insufficient. Used only for the negative-selection scope read."""
    cls = (rec.get("tumor_expression_class") or "").lower()
    if not cls or cls == "data_unavailable":
        return "insufficient"
    if "low" in cls:
        return "absent"
    if "sparse" in cls:
        return "low_present"
    if any(t in cls for t in ("expressed", "detected", "moderate", "high")):
        return "present"
    return "insufficient"


def _presence_subtype_scope_read(per_subgroup: list, requested: list) -> dict:
    """POWER-GATED, NEGATIVE-SELECTION-ONLY scoped presence read over the requested strata.

    Preserves the framework's never-lift asymmetry: a subtype finding may only HOLD/flag (assert
    `subtype_specific_absence` when a requested stratum is measured-and-absent while others are present),
    NEVER MINT a positive presence verdict — the pooled presence_verdict spine stays byte-stable. An
    underpowered stratum (evidence_state != measured OR n < floor) is inadmissible and never read as a
    subtype-specific difference (guards multiple-testing over the strata). ADDITIVE / verdict-inert."""
    req = {s.strip() for s in requested if s and s.strip()}
    by_stratum: dict = {}
    for r in per_subgroup or []:
        stratum = r.get("stratum_id") or r.get("stratum")
        if not stratum or (req and stratum not in req):
            continue
        n = r.get("n_tumor_samples") if r.get("n_tumor_samples") is not None else r.get("subgroup_n")
        powered = (r.get("evidence_state") == "measured"
                   and isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR)
        by_stratum[stratum] = _stratum_presence_call(r) if powered else "underpowered"
    admissible = {s: v for s, v in by_stratum.items() if v not in {"underpowered", "insufficient"}}
    absent = [s for s, v in admissible.items() if v == "absent"]
    present = [s for s, v in admissible.items() if v in {"present", "low_present"}]
    if not admissible:
        scoped, headline = "no_admissible_subtype", (
            "no adequately-powered requested stratum (below n-floor / not measured)")
    elif absent and present:
        # the ONLY directional call this read makes — a genuine subtype-specific ABSENCE (a HOLD-analog)
        scoped, headline = "subtype_specific_absence", (
            f"present in {', '.join(present)} but absent in {', '.join(absent)}")
    elif absent and not present:
        scoped, headline = "absent_across_measured_subtypes", (
            f"absent across measured requested strata ({', '.join(absent)})")
    else:
        scoped, headline = "present_across_measured_subtypes", (
            f"present across measured requested strata ({', '.join(present)}) — pooled spine unchanged")
    return {"by_stratum": by_stratum, "n_admissible": len(admissible),
            "scoped_read": scoped, "headline": headline}


def _resolve_presence_subtype_panorama(target: str, indication: "str | None", subtypes: list) -> dict:
    """DESCRIPTIVE presence-by-subtype panorama for the dispatcher's subtype_panorama_fn hook (opt-in
    via --subtypes). Resolves tumor-rna-distribution-by-subtype scoped to the requested strata and
    projects a `subtype_presence_panorama` block: the per-stratum abundance/window records, the honest
    axis-quality grade, the purity-spread confounder, and a power-gated NEGATIVE-SELECTION-ONLY scoped
    read. NO ladder rung is touched → the pooled presence_verdict is byte-stable with or without
    --subtypes (mirrors functional-requirement's dependency panorama)."""
    subgroup_context = {"resolved_strata_ids": list(subtypes), "catalog_status": "resolved_active"}
    sub_cards = resolve_cards(_SUBTYPE_PANORAMA_CARDS, target, indication,
                              subgroup_context=subgroup_context)
    card = next((c for c in sub_cards if c["card_id"] == "tumor-rna-distribution-by-subtype"), None)
    summary = (card or {}).get("summary") or {}
    per_subgroup = summary.get("per_subgroup_metrics") or []
    return {
        "cards": sub_cards,
        "scope_subtypes": list(subtypes),
        "subtype_presence_panorama": {
            "subtype_axis_quality":     summary.get("subtype_axis_quality"),
            "subtype_stratification_class": summary.get("subtype_stratification_class"),
            "n_subtypes_measured":      summary.get("n_subtypes_measured"),
            "subtype_purity_spread":    summary.get("subtype_purity_spread"),
            # the power-gated, negative-selection-only scoped read (never mints a positive verdict)
            "scoped_read":              _presence_subtype_scope_read(per_subgroup, subtypes),
            # per-stratum abundance + matched-normal window, surfaced with power so an underpowered
            # stratum is never over-read
            "per_stratum": [{"stratum": r.get("stratum_id") or r.get("stratum"),
                             "evidence_state": r.get("evidence_state"),
                             "n_tumor_samples": r.get("n_tumor_samples"),
                             "tumor_expression_class": r.get("tumor_expression_class"),
                             "subtype_signal": r.get("subtype_signal"),
                             "median_log2tpm": r.get("median_log2tpm"),
                             "median_purity": r.get("median_purity"),
                             "fraction_tumor_above_normal_p95": r.get("fraction_tumor_above_normal_p95")}
                            for r in per_subgroup],
            "_missing": bool(card is None or card.get("_missing")),
            "_missing_reason": (card or {}).get("_missing_reason"),
        },
    }


def _emit_skill_figures(decision, figures_root):
    """Combined --figures emitter: the canonical headline hero (verdict · confidence · top tension),
    the Presence × Context hero matrix, the claim-vector (signal × reliability) figure, the per-card
    card-board (ternary signal/no-signal/not-measured grouped by claim), and — when the indication has
    a subtype axis — the subtype-refinement figure. All additive / display-only; best-effort per emitter."""
    return (emit_headline_hero(decision, figures_root)
            + emit_presence_matrix(decision, figures_root)
            + emit_claim_vector_figure(decision, figures_root)
            + emit_card_board_figure(decision, figures_root)
            + emit_subtype_refinement_figure(decision, figures_root)
            + emit_subgroup_figure(decision, figures_root))


# ── canonical HEADLINE block (verdict + confidence + top tension) ────────────────────────────────
# The presence declaration for the shared headline_core builder: A/B/C/D claim axes, presence verdict
# vocabulary → human phrase, and the cross-modal `presence_headline_conflict` guard as the skill-specific
# tension source. Verdict-INERT — a one-way projection over the computed headline (spine byte-stable).
# The presence_verdict vocabulary (the collapsed RNA-lens ladder tokens) → human phrase. Positives are
# the _RNA_PRESENCE_POSITIVE tiers; negatives are _MEASURED_NEGATIVE_VERDICTS; the rest are gaps.
_PRESENCE_VERDICT_PHRASE = {
    # positives
    "broadly_high_expression":        "Broadly, highly expressed",
    "tumor_broadly_expressed":        "Broadly expressed in tumor",
    "strongly_upregulated_in_tumor":  "Strongly up-regulated in tumor",
    "broadly_moderate_expression":    "Broadly, moderately expressed",
    "tumor_moderately_expressed":     "Moderately expressed in tumor",
    "modestly_upregulated_in_tumor":  "Modestly up-regulated in tumor",
    "lineage_restricted":             "Lineage-restricted expression",
    # measured negatives
    "broadly_low_expression":         "Broadly low expression",
    "tumor_sparsely_expressed":       "Sparsely expressed in tumor",
    "modestly_downregulated_in_tumor": "Modestly down-regulated in tumor",
    "strongly_downregulated_in_tumor": "Strongly down-regulated in tumor",
    "protein_modestly_downregulated":  "Protein modestly down-regulated",
    "protein_strongly_downregulated":  "Protein strongly down-regulated",
    "protein_broadly_low":            "Protein broadly low",
    # gaps
    "data_unavailable":               "Data unavailable",
    "not_informative":                "Not informative",
    "insufficient":                   "Insufficient evidence",
}


def _presence_tension_extra(headline: dict):
    """The buried MEASURED presence-negative that the positive-over-negative collapse hides — surfaced by
    the existing `presence_headline_conflict` guard — is presence's sharpest cross-modal tension."""
    if headline.get("presence_headline_conflict"):
        return {"text": headline.get("presence_headline_conflict_note") or "cross-modal presence conflict",
                "source": "presence_headline_conflict", "severity": 3}
    return None


_PRESENCE_HEADLINE_SPEC = HeadlineSpec(
    gate="presence",
    axis_labels={"A": "abundance", "B": "tumor-elevation", "C": "malignant-intrinsic", "D": "generality"},
    axis_keys=("A", "B", "C", "D"),
    critical_axes=("A", "B", "C"),
    verdict_label=lambda v: _PRESENCE_VERDICT_PHRASE.get(v, str(v).replace("_", " ").strip().capitalize()),
    tension_extra=_presence_tension_extra,
)


def _presence_verdict_polarity(v) -> str:
    """The skill's OWN reading of the collapsed verdict (colours the hero badge; never a gate). Reuses
    the presence positive/negative vocabularies so the polarity can't drift from the spine."""
    if _is_presence_positive(v):
        return "positive"
    if v in _MEASURED_NEGATIVE_VERDICTS:
        return "negative"
    return "neutral"


def _presence_headline_block(headline: dict) -> dict:
    """Build the canonical Headline block from the already-computed presence headline. Reads the
    collapsed verdict + the verdict-inert claim_vector / key_signals; never moves the spine."""
    v = headline.get("presence_verdict")
    return build_headline(headline, headline.get("claim_vector"), headline.get("key_signals"),
                          spec=_PRESENCE_HEADLINE_SPEC, verdict_token=v,
                          driving_rule_id=headline.get("driving_rule_id"),
                          verdict_polarity=_presence_verdict_polarity(v))


SKILL_NAME = "tumor-presence"
SKILL_VERSION = "1.15.0"   # 1.15.0 (2026-08-28): HPA Pathology antibody IHC protein-in-tumor (protein_ihc/tumor bucket; MS-independent, measured-unruled → collapsed verdict byte-stable).   # 1.14.0: capsule-driven narrator via generic engine.

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

    # ── DISPLAY-ONLY facets (6) — additive context, feed no ladder ────────────
    "tumor-rna-distribution-by-subtype",     # per-molecular-subtype tumor RNA panorama
    "cellline-rna-distribution-by-subtype",  # cell-line RNA by DepMap driver subtype (COADREAD proof)
    "tumor-protein-distribution-by-subtype", # per-molecular-subtype tumor PROTEIN panorama (CPTAC MSI, COADREAD)
    "expression-purity-confound",            # tumor-intrinsic vs stromal/immune signal
    "cellline-rna-protein-concordance",      # is RNA an adequate protein proxy? (cell-line arm)
    "rna-protein-concordance-tumor",         # is RNA an adequate protein proxy? (patient-tumor CPTAC arm)
    # cell-line protein 2nd platform: ProCan-DepMapSanger DIA/SWATH MaxLFQ (CC-BY, 949 lines) —
    # orthogonal corroboration of the Gygi TMT cellline-protein-abundance card. DISPLAY-ONLY /
    # verdict-inert: it fires NO interpretation rule, so it touches no protein ladder rung and the
    # presence verdict is byte-stable with or without it (same bulk_protein_ms/cell_line bucket as Gygi,
    # driven by Gygi's fired rules).
    "cellline-protein-abundance-procan",

    # antibody IHC protein-presence-in-TUMOR (HPA Pathology, 20 cancer types) — the MS-INDEPENDENT
    # protein-in-tumor leg. Occupies the (protein_ihc, tumor) bucket: fills protein presence where the
    # CPTAC TMT-MS card (bulk_protein_ms/tumor) is data_unavailable. VERDICT-INERT: fires NO rule; surfaced
    # as a `measured` bucket via _MEASURED_UNRULED_PRESENT, so the COLLAPSED presence verdict is byte-stable
    # (the pm matrix gains the 8th, protein_ihc/tumor, bucket — additive).
    "hpa-pathology-cancer-ihc",

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
    "tumor-protein-distribution-by-subtype": ("bulk_protein_ms", "tumor"),
    "tumor-protein-abundance-cptac":        ("bulk_protein_ms", "tumor"),
    "cellline-protein-abundance":           ("bulk_protein_ms", "cell_line"),
    "cellline-protein-abundance-procan":    ("bulk_protein_ms", "cell_line"),  # DISPLAY-ONLY 2nd platform (ProCan DIA); fires no rule → verdict-inert
    "tumor-elevation-breadth":              ("bulk_protein_ms", "tumor"),
    "expression-purity-confound":           ("bulk_rna", "tumor"),
    "cellline-rna-protein-concordance":     ("bulk_rna", "cell_line"),
    "rna-protein-concordance-tumor":        ("bulk_rna", "tumor"),
    "tumor-scrna-celltype-expression":      ("sc_rna", "tumor"),
    "hpa-pathology-cancer-ihc":             ("protein_ihc", "tumor"),   # MS-independent antibody IHC protein-in-tumor (verdict-inert; measured-unruled)
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
    ("protein_ihc", "tumor"),     # MS-INDEPENDENT antibody protein-in-tumor (hpa-pathology-cancer-ihc); measured for the ~20 HPA cancer types, else data_unavailable
    ("protein_ihc", "normal"),    # safety comparator (normal-tissue-liability HPA IHC)
)

# Canonical bucket keys — the verdict-inert headline helpers look these up in presence_verdict_by_modality.
# Named here (not scattered string literals) so a typo becomes a NameError, not a silent None lookup.
_BULK_RNA_CELL_LINE = _ctx_key("bulk_rna", "cell_line")
_BULK_RNA_TUMOR = _ctx_key("bulk_rna", "tumor")
_BULK_PROTEIN_MS_CELL_LINE = _ctx_key("bulk_protein_ms", "cell_line")
_BULK_PROTEIN_MS_TUMOR = _ctx_key("bulk_protein_ms", "tumor")

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
    # (protein-not-detected-degrader-killer removed 2026-08-20: the CPTAC classifier never
    #  emits not_detected — whole-proteome TMT can't assert per-gene absence; target-contracts
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
    # `protein_broadly_low` (cell-line whole-panel MS) is the ONLY reachable protein-absence negative.
    # The former `protein_not_detected` was retired (target-contracts #467): whole-proteome CPTAC TMT
    # cannot assert per-gene absence (a missing protein → data_unavailable), so no rule ever emitted it —
    # keeping it here pinned a structurally-unreachable token and gave false assurance.
    "protein_broadly_low",
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

# Driving-rule provenance for the verdict-INERT signal-strength facet (M1). A positive-tier rung whose
# rule fires with `-neutral` intent is a measured NEUTRAL/low presence read (tumor_sparsely_expressed,
# sc_broadly_low, broadly_moderate_expression, …). By design these collapse INTO the positive tier — a
# per-indication low read never kills a target-wide nomination (see _SC_RNA_RANK note) — so
# `_is_presence_positive` is True for them, yet the driving evidence is only neutral. We derive the
# supportive/neutral rule sets FROM the ladder rule_id suffix so they self-maintain with any ladder edit.
_SUPPORTIVE_RIDS = frozenset(rid for rid, _v in _VERDICT_RANK if rid.endswith("-supportive"))
_NEUTRAL_POSITIVE_RIDS = frozenset(rid for rid, _v in _VERDICT_RANK if rid.endswith("-neutral"))


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
# tumor-presence expert-review finding), so those rungs are deliberately EXCLUDED here. Absence =
# cell-line whole-panel broadly_low (detected in <30% of the Gygi MS panel, AND — post the
# depmap_protein_abundance lineage-restricted-floor fix — not a rescued lineage-restricted antigen). The
# down-contrasts remain in _MEASURED_NEGATIVE_VERDICTS so the collapse ordering + the
# `presence_headline_conflict` guard still surface them per-bucket — only the WORD-level demotion is
# narrowed. (CPTAC not_detected is NOT here: whole-proteome TMT can't assert per-gene absence — a missing
# protein resolves to data_unavailable, not a measured negative — so target-contracts retired that
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


# ── (strength, certainty) SIDECAR — 5th certainty axis, first NO-RESOLVER gate (CERTAINTY_MODEL.md).
#    ADDITIVE + verdict-INERT. corroboration = the VERDICT-DISJOINT RNA<->protein paired-tumor agreement
#    (rna-protein-concordance-tumor.rna_as_biomarker) — a within-entity cross-MODALITY check that fires no
#    presence ladder rung. Reviewed per-axis design (4-agent panel).
_PRES_ORD = {"low": 0, "medium": 1, "high": 2}
_CERTAINTY_CORROBORATION_CARDS = frozenset({"rna-protein-concordance-tumor"})
_PRES_STRONG_POS = {"strongly_upregulated_in_tumor", "tumor_broadly_expressed", "broadly_high_expression",
                    "protein_strongly_upregulated", "protein_broadly_high", "broadly_tumor_elevated",
                    "sc_malignant_detected"}
_PRES_MOD_POS = {"modestly_upregulated_in_tumor", "tumor_moderately_expressed", "lineage_restricted",
                 "protein_modestly_upregulated", "protein_lineage_restricted", "multi_tumor_elevated"}
_PRES_WEAK_POS = {"broadly_moderate_expression", "protein_broadly_moderate", "tumor_sparsely_expressed",
                  "single_tumor_elevated", "not_tumor_elevated", "sc_microenvironment_dominant",
                  "sc_broadly_low", "present_rna_only_protein_absent"}
_PRES_NEG = {"modestly_downregulated_in_tumor", "protein_modestly_downregulated",
             "strongly_downregulated_in_tumor", "protein_strongly_downregulated",
             "broadly_low_expression", "protein_broadly_low"}
_PRES_NONE = {"not_informative", "data_unavailable", None}
_PRES_DECISION_CARDS = ("cellline-rna-distribution", "tumor-rna-vs-adjacent", "tumor-rna-distribution",
                        "tumor-protein-abundance-cptac", "cellline-protein-abundance",
                        "tumor-elevation-breadth", "tumor-scrna-celltype-expression")
# (representative card per measurement layer, for modality-breadth)
_PRES_LAYERS = (("cellline-rna-distribution", "tumor-rna-distribution", "tumor-rna-vs-adjacent"),
                ("tumor-protein-abundance-cptac", "cellline-protein-abundance"),
                ("tumor-scrna-celltype-expression",))


def _presence_strength(v) -> str:
    if v in _PRES_STRONG_POS:
        return "strong_positive"
    if v in _PRES_MOD_POS:
        return "moderate_positive"
    if v in _PRES_WEAK_POS:
        return "weak_positive"
    if v in _PRES_NEG:
        return "negative"
    return "none"


def _pres_corroboration(rna_as_biomarker) -> str:
    c = str(rna_as_biomarker or "")
    if c == "adequate_proxy":
        return "high"
    if c == "partial_proxy":
        return "medium"
    if c == "poor_proxy":
        return "low"
    return "unmeasured"     # insufficient_paired_tumors / data_unavailable → ignorance (unknown_mass)


def _pres_coverage(cards) -> str:
    """Weakest-link of driving-modality POWER (best sample-n across the RNA/cell/sc layers) and modality
    BREADTH (# of the 3 measurement layers with a present card). high = well-powered AND >=2 layers."""
    ns = [_safe_card_field(cards, "tumor-rna-distribution", "n_tumor_samples"),
          _safe_card_field(cards, "cellline-rna-distribution", "n_cell_lines_evaluated"),
          _safe_card_field(cards, "tumor-scrna-celltype-expression", "malignant_n_cells")]
    best = max([n for n in ns if isinstance(n, (int, float))], default=0)
    present = {c["card_id"] for c in (cards or [])}
    breadth = sum(1 for layer in _PRES_LAYERS if any(cid in present for cid in layer))
    if best >= 100 and breadth >= 2:
        return "high"
    if best >= 5:
        return "medium"
    return "low"


def _pres_unknown_mass(cards) -> float:
    present = {c["card_id"] for c in (cards or [])}
    blind = sum(1 for cid in _PRES_DECISION_CARDS if cid not in present)
    return round(blind / len(_PRES_DECISION_CARDS), 4)


# Continuous presence COMPOSITE (Phase 5): a monotone [0,1] portfolio-RANKING scalar the one-word
# presence_verdict cannot provide (a categorical word cannot order 55 targets). It is a NAMED
# projection — "certainty-discounted presence strength" — NOT a canonical single value: the peak signal
# tier (strength) DISCOUNTED by the weakest-link certainty level. Non-substituting by design — certainty
# is a MULTIPLIER, never averaged against signal, and a measured-negative floors to 0. Verdict-INERT:
# additive sidecar field, never feeds presence_verdict; other weightings are legitimate other projections.
_COMPOSITE_STRENGTH = {"strong_positive": 1.0, "moderate_positive": 0.66, "weak_positive": 0.33,
                       "negative": 0.0, "none": 0.0}
_COMPOSITE_CERTAINTY = {"high": 1.0, "medium": 0.75, "low": 0.5}


def _presence_composite(strength: str, certainty_level: str) -> float:
    return round(_COMPOSITE_STRENGTH.get(strength, 0.0) * _COMPOSITE_CERTAINTY.get(certainty_level, 0.5), 3)


def _strength_certainty(cards, fired=None, verdict_pair=None) -> dict:
    """Fan-out SIDECAR hook (CERTAINTY_MODEL) — mirrors functional-requirement/selectivity/genomic/surface."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    rna_bm = _safe_card_field(cards, "rna-protein-concordance-tumor", "rna_as_biomarker")
    coverage = _pres_coverage(cards)
    corroboration = _pres_corroboration(rna_bm)
    components = [coverage] + ([corroboration] if corroboration != "unmeasured" else [])
    level = min(components, key=lambda c: _PRES_ORD[c]) if components else "low"
    if v in _PRES_NONE:
        level = "low"
    strength = _presence_strength(v)
    return {
        "strength": strength,
        "certainty": {"level": level, "coverage": coverage, "corroboration": corroboration,
                      "unknown_mass": _pres_unknown_mass(cards)},
        # continuous ranking primitive (verdict-inert; a NAMED projection, not the canonical value)
        "composite": _presence_composite(strength, level),
        "composite_basis": ("certainty-discounted presence strength = peak signal tier × weakest-link "
                            "certainty level; a NAMED [0,1] portfolio-ranking projection, NOT a canonical "
                            "single verdict — other lens weightings are equally valid projections"),
        "provenance": {"rna_as_biomarker": rna_bm},
        "_model_ref": "CERTAINTY_MODEL.md#tumor_presence",
    }


# ── FACTORED-RECORD SHADOW (M1) — the TUMOR-PRESENCE per-axis builder. The FIRST no-resolver axis in
#    the shadow: presence_verdict is computed inline (no resolver enum), so at M1 the record schema
#    validates only the token PATTERN — the contracts invariant-C augmented verdict set for no-resolver
#    axes is an M3 item (mirrors the disjointness validator's verdict_precedence_augment). presence is
#    modality-BLIND (the composer conjoins it with surface/selectivity for a modality call), so no
#    modality_scope. VERDICT-INERT: surfaced by the fan-out into decision.claim_record_shadow.tumor_presence.
_PRES_STRENGTH_TO_LEVEL = {"strong_positive": "strong", "moderate_positive": "moderate",
                           "weak_positive": "weak", "negative": "moderate", "none": "none"}


def _pres_availability(v) -> str:
    if v == "data_unavailable" or v is None:
        return "not_wired"                       # open-world → assembler forces unknown/neutral
    if v == "not_informative":
        return "insufficient"                    # measured but uninformative
    if v in _PRES_NEG:
        return "measured_negative"               # measured DOWN / low expression
    return "measured_positive"                   # present / elevated in tumor


def _pres_direction(v) -> str:
    if v in _PRES_STRONG_POS or v in _PRES_MOD_POS or v in _PRES_WEAK_POS:
        return "supports"
    if v in _PRES_NEG:
        return "opposes"
    return "neutral"


def _claim_record(cards, fired=None, verdict_pair=None) -> dict:
    """M1 shadow builder — standalone, mirrors the other axes' hook."""
    v = verdict_pair[0] if verdict_pair else (_verdict(fired)[0] if fired is not None else None)
    sc = _strength_certainty(cards, fired=fired, verdict_pair=verdict_pair)
    return assemble_claim_record(
        axis="tumor_presence",
        state=(v or "not_informative"),
        direction=_pres_direction(v),
        availability=_pres_availability(v),
        magnitude={"level": _PRES_STRENGTH_TO_LEVEL.get(_presence_strength(v), "none")},
        certainty=sc["certainty"],
        fired=fired,
        cards=cards,
    )


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

    NOTE: the trigger is genuine ABSENCE only, NOT a tumor-vs-normal down-CONTRAST. A
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
    # (protein_ihc, tumor): HPA antibody IHC protein-presence, surfaced as `measured` with NO rule
    # (verdict-inert). Each meaningful protein_presence_class passes through as the bucket verdict; a
    # class NOT in this map (data_unavailable) leaves the bucket data_unavailable. The collapsed presence
    # verdict is unaffected (no rule fires); this only populates the additive protein_ihc/tumor bucket.
    ("protein_ihc", "tumor"): ("hpa-pathology-cancer-ihc", "protein_presence_class",
                               {"ihc_detected_high": "ihc_detected_high",
                                "ihc_detected_moderate": "ihc_detected_moderate",
                                "ihc_detected_low": "ihc_detected_low",
                                "ihc_not_detected": "ihc_not_detected"}),
}


def _safe_card_field(cards: list[dict] | None, card_id: str, field: str):
    """`get_card_field` that is None-safe on an ABSENT card_id. `get_card_field` deliberately RAISES on a
    missing card_id (a typo guard), so the optional reads below — comparator buckets and the unruled-present
    rescue, where the card may legitimately not have resolved — must check membership first. Returns None
    when `card_id` is not in `cards`."""
    return get_card_field(cards, card_id, field) if card_id in {c["card_id"] for c in (cards or [])} else None


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
            val = _safe_card_field(cards, card_id, field)
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
            raw = _safe_card_field(cards, card_id, field)
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
    tumor_verdict = _bucket_verdict(_BULK_RNA_TUMOR)
    rna_verdict = (tumor_verdict if tumor_verdict in _RNA_PRESENCE_POSITIVE
                   else _bucket_verdict(_BULK_RNA_CELL_LINE))
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
    if lens == _BULK_RNA_CELL_LINE:
        cl = (per_modality or {}).get(_BULK_RNA_CELL_LINE) or {}
        tv = (per_modality or {}).get(_BULK_RNA_TUMOR) or {}
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


def _presence_signal_strength(driving_rule_id: str | None, verdict: str | None) -> str:
    """VERDICT-INERT legibility of the evidence BEHIND a presence call (M1). `_is_presence_positive`
    alone cannot tell a strong present call from one resting only on a NEUTRAL/low rung (the sole-signal
    sc_broadly_low / tumor_sparsely_expressed case that still collapses into the positive tier by design).
    Returns 'supportive' (a `-supportive` rung drove it), 'neutral' (only a `-neutral` low/moderate rung),
    'none' (nothing fired → insufficient), or 'other' (a measured-negative / gap drove it). Keyed on the
    DRIVING rule so it tracks whichever rung actually won the collapse. Never touches the spine."""
    if not driving_rule_id or verdict == "insufficient":
        return "none"
    if driving_rule_id in _SUPPORTIVE_RIDS:
        return "supportive"
    if driving_rule_id in _NEUTRAL_POSITIVE_RIDS:
        return "neutral"
    return "other"


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


# ─── Protein-confirmation state (VERDICT-INERT headline facet) ───────────────
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
    "protein_present_not_elevated",                                    # rescue: quantified, flat
    "protein_modestly_downregulated", "protein_strongly_downregulated",  # measured present-but-lower
}
_PROTEIN_ABSENT_VERDICTS = frozenset({"protein_broadly_low"})  # only reachable protein-absence (see above)


def _protein_confirmation_state(per_modality: dict, collapsed_verdict: str | None) -> str:
    """VERDICT-INERT confidence facet: was the (present) presence call CONFIRMED at the protein level,
    contradicted by a measured protein absence, or is protein simply UNTESTED? See the block comment."""
    if not _is_presence_positive(collapsed_verdict):
        return "not_applicable"
    measured = [b.get("verdict") for k in (_BULK_PROTEIN_MS_TUMOR, _BULK_PROTEIN_MS_CELL_LINE)
                for b in [(per_modality or {}).get(k) or {}]
                if b.get("evidence_state") == "measured"]
    if any(v in _PROTEIN_PRESENT_VERDICTS for v in measured):
        return "confirmed"
    if any(v in _PROTEIN_ABSENT_VERDICTS for v in measured):
        return "measured_absent"
    return "untested"


# Hierarchy-derived sub-group signals (signals-first spec) — sources bound by measurement_type from
# question_hierarchy.yaml; confidence = agreement × sample-size. ADDITIVE + verdict-INERT; the hand-
# wired claim_vector stays until consumers migrate (strangler). Best-effort (degrades to {} off-contract).
_PRESENCE_READER = {
    "tumor_expression_distribution": {"class": "tumor_expression_class", "n": ["n_tumor_samples"], "label": "tumor RNA"},
    "cell_line_rna_expression": {"class": "expression_class", "n": ["n_cell_lines_evaluated"], "label": "cell-line RNA"},
    "tumor_protein_abundance": {"class": "protein_expression_class", "n": ["n_tumor_samples"], "label": "tumor protein",
                                "present_synonyms": ("ns", "not_significant", "small_effect")},
    "cell_line_protein_abundance": {"class": "protein_expression_class", "n": ["n_cell_lines_evaluated"], "label": "cell-line protein"},
    "rna_protein_concordance": {"class": "rna_as_biomarker", "n": ["n_paired_models", "n_paired_tumors"], "label": "RNA↔protein"},
    "sc_tumor_celltype_expression": {"class": "sc_expression_class", "n": ["malignant_n_cells", "n_donor_groups"], "label": "single-cell"},
    "tumor_elevation_breadth": {"class": "tumor_elevation_breadth_class", "n": ["n_cohorts_tested"], "label": "breadth"},
}


def _presence_subgroup_signals(cards, claim_vector=None):
    """Derive per-sub-group {signal, confidence, sources} from question_hierarchy.yaml + resolved cards.
    When the claim_vector is passed, the sub-group SIGNAL is overlaid from the tuned claim (A→abundance,
    C→malignant_intrinsic, D→generality via each sub-group's `claim_axes`), carrying the claim's
    evidence-atom trace; the cards supply the corroborating sources + sample-size confidence."""
    import yaml
    from _skills_common.subgroup_derivation import derive_subgroups, overlay_claim_signals
    hp = Path(__file__).resolve().parent.parent / "question_hierarchy.yaml"
    hier = yaml.safe_load(hp.read_text())
    sg = derive_subgroups(hier, cards, _PRESENCE_READER)
    if isinstance(claim_vector, dict):
        overlay_claim_signals(sg, claim_vector, hier)
    return sg


def _attach_subtype_firstclass(subgroup_signals, claim_vector_by_subtype):
    """FIRST-CLASS SUBTYPE: elevate the per-stratum reads (presence_claim_vector_by_subtype — multiplicity-
    aware, #798) INTO the sub-group structure as `by_stratum`, so subtype is surfaced BY DEFAULT rather
    than only in the opt-in --subtypes panorama. Subtype stays an orthogonal CONDITIONER (it refines a
    sub-group's signal per stratum; it is not a new sub-group). Attaches to the abundance sub-group (the
    presence sub-group the by-subtype cards measure). Verdict-INERT, best-effort, no-op when no strata."""
    if not (isinstance(subgroup_signals, dict) and isinstance(claim_vector_by_subtype, dict)):
        return subgroup_signals
    strata = claim_vector_by_subtype.get("strata") or {}
    ab = subgroup_signals.get("abundance")
    if strata and isinstance(ab, dict):
        ab["by_stratum"] = {sid: {"signal": (st.get("A") or {}).get("signal"),
                                  "certainty": (st.get("A") or {}).get("corroboration"),
                                  "n": st.get("n_tumor_samples"),
                                  "evidence": (st.get("A") or {}).get("evidence")}
                            for sid, st in strata.items()}
        ab["subtype_axis"] = {"stratification_class": claim_vector_by_subtype.get("stratification_class"),
                              "epsilon_squared": claim_vector_by_subtype.get("subtype_variance_explained"),
                              "multiplicity_strata_tested": claim_vector_by_subtype.get("multiplicity_strata_tested"),
                              "which_separate": claim_vector_by_subtype.get("which_subtypes_separate")}
    return subgroup_signals


def _headline(cards, fired, verdict_pair):
    v, drv = verdict_pair or ("insufficient", None)
    per_modality = _per_modality_verdicts(fired, cards)
    # Legibility flag for a cell-line-anchored headline that understates the tumor-tissue lens.
    _headline_lens, _cl_tumor_discordant = _headline_lens_discordance(drv, per_modality)
    _tumor_bucket = (per_modality or {}).get(_BULK_RNA_TUMOR) or {}
    _presence_interpretation_note = (
        ("presence_verdict inherits the pan-cancer cell-line RNA lens; the tumor-tissue lens "
         f"reads a higher presence tier ({_tumor_bucket.get('verdict')}). Read "
         "presence_verdict_by_modality['bulk_rna/tumor'] — the one-word headline understates "
         "tumor-tissue presence for this target (typical of antigens that de-differentiate in "
         "2D culture).")
        if _cl_tumor_discordant else None)
    # M2 legibility (verdict-INERT): the collapse can read `insufficient` while a bucket is MEASURED-present
    # — e.g. a CPTAC-flat-only target, where `protein_present_not_elevated` is rescued in the per-modality
    # map but fires NO ladder rung, so it cannot lift the collapsed word off `insufficient`. List those
    # buckets so the one-word `insufficient` is not mistaken for "nothing measured". Empty otherwise.
    _measured_present_despite_insufficient = (
        sorted(k for k, b in (per_modality or {}).items()
               if isinstance(b, dict) and b.get("evidence_state") == "measured"
               and _is_presence_positive(b.get("verdict")))
        if v == "insufficient" else [])
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
        # protein_confirmation_state: is a PRESENT call protein-confirmed, protein-measured-
        # absent, or protein-UNTESTED (RNA-only)? Verdict-inert legibility of the confidence behind the
        # one-word headline — most indications lack CPTAC/cell-line-MS, so a positive-RNA target commonly
        # reads present with protein untested; this names that state instead of silently over-reassuring.
        "protein_confirmation_state":    _protein_confirmation_state(per_modality, v),
        # presence_signal_strength (M1): supportive / neutral / other / none — is the PRESENT call driven
        # by a supportive rung, or only by a NEUTRAL low rung (sc_broadly_low, tumor_sparsely_expressed)?
        # Verdict-inert; lets a downstream consumer distinguish 'present' from 'only-neutral-evidence-present'
        # without re-tiering the collapse (which _is_presence_positive alone cannot).
        "presence_signal_strength":      _presence_signal_strength(drv, v),
        # measured_present_despite_insufficient (M2): buckets that are MEASURED-present while the collapsed
        # word is `insufficient` (e.g. CPTAC-flat-only). Empty unless that specific disagreement holds.
        "measured_present_despite_insufficient": _measured_present_despite_insufficient,
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
        # Variance-standardized companion to the RAW protein_effect_size. protein_expression_class thresholds on the raw log2 effect, blind to variance; the
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
        # HPA antibody IHC protein-presence-in-tumor (MS-independent; the protein_ihc/tumor bucket). Fills
        # protein presence where CPTAC TMT-MS is data_unavailable. The bucket verdict is in
        # presence_verdict_by_modality['protein_ihc/tumor']; these are the raw display atoms.
        "hpa_ihc_protein_presence_class": get_card_field(cards, "hpa-pathology-cancer-ihc", "protein_presence_class"),
        "hpa_ihc_fraction_detected":      get_card_field(cards, "hpa-pathology-cancer-ihc", "fraction_detected"),
        "hpa_ihc_staining_score":         get_card_field(cards, "hpa-pathology-cancer-ihc", "staining_score"),
        "hpa_ihc_n_patients":             get_card_field(cards, "hpa-pathology-cancer-ihc", "n_patients_total"),
        "hpa_ihc_cancer_type":            get_card_field(cards, "hpa-pathology-cancer-ihc", "hpa_cancer_type"),
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
        # HONEST capability grade (powered/underpowered/empty/unavailable) — subtype_scope_available:true
        # alone masks a hollow axis (NSCLC only KRAS_G12C powered; DepMap STAD/PAAD all-empty). A consumer
        # should trust cross-subtype claims only when this is `powered`.
        "subtype_axis_quality":         get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_axis_quality"),
        "n_subtypes_measured":          get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_measured"),
        "n_subtypes_enriched":          get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_enriched"),
        "spotlight_subtype":            get_card_field(cards, "tumor-rna-distribution-by-subtype", "spotlight_subtype"),
        "subtype_stratification_class": get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_stratification_class"),
        "n_subtypes_restricted":        get_card_field(cards, "tumor-rna-distribution-by-subtype", "n_subtypes_restricted"),
        # Purity confounder framing — if the enriched strata are systematically lower-purity, the subtype
        # "enrichment" is stromal, not tumor-intrinsic. Verdict-inert, like the omnibus.
        "subtype_purity_source":        get_card_field(cards, "tumor-rna-distribution-by-subtype", "purity_source"),
        "subtype_purity_spread":        get_card_field(cards, "tumor-rna-distribution-by-subtype", "subtype_purity_spread"),
        "cellline_subtype_scope_available":      get_card_field(cards, "cellline-rna-distribution-by-subtype", "subtype_axis_available"),
        "cellline_subtype_axis_quality":         get_card_field(cards, "cellline-rna-distribution-by-subtype", "subtype_axis_quality"),
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
        # Total malignant cells behind the sc call (analysis-methods floor: MIN_MALIGNANT_CELLS_TOTAL).
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
    # These projections are verdict-INERT display layers. Run them best-effort: a formatting/read fault
    # in any one of them must NEVER discard the presence spine (verdict + per-modality matrix) that is
    # already fully built in `hl` above — same degrade-on-exception discipline the dispatcher applies to
    # synthesis / figures / envelope. On the happy path this is byte-identical (no _enrichment_errors key
    # is added, key order is unchanged), so the golden-spine + replay fixtures are unaffected.
    def _enrich(label, fn, *fn_args):
        try:
            return fn(*fn_args)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
            hl.setdefault("_enrichment_errors", {})[label] = f"{type(exc).__name__}: {exc}"
            return None

    hl["claim_vector"] = _enrich("claim_vector", presence_claim_vector, hl, cards)
    hl["key_signals"] = _enrich("key_signals", presence_key_signals, hl, cards)
    # SUBTYPE-scoped claim vector (per stratum) — when a (target, indication, subtype) is the question,
    # the pooled vector flattens the per-stratum signal (cf. CD274 broadly-low pooled but MSI-H-strong).
    # Projects A + distributional-B per stratum from the already-resolved per_subgroup_metrics; None when
    # the indication has no subtype axis. Verdict-inert, like the pooled vector.
    hl["claim_vector_by_subtype"] = _enrich("claim_vector_by_subtype", presence_claim_vector_by_subtype, cards)
    # The 7-question (data · signal · confidence) summary rows — a projection over the just-built
    # headline + card fields (Signal from the claim_vector, Confidence from corroboration). Verdict-inert;
    # carried through _synthesis_facet so the composed target-profile dashboard renders the same table.
    hl["question_table"] = _enrich("question_table", presence_question_table, hl, cards)
    # Canonical HEADLINE block (verdict + confidence + top tension) — the concise, consumer-facing
    # headline message, as deterministic text + a renderer-agnostic hero payload. A verdict-INERT
    # projection over the claim_vector / key_signals just built; best-effort (same degrade discipline).
    hl["headline_block"] = _enrich("headline_block", _presence_headline_block, hl)
    # Hierarchy-derived sub-group signals (verdict-inert; sources bound by measurement_type, not hand-wired).
    # Signal overlaid from the just-built claim_vector (A/C/D); cards supply corroborating sources.
    hl["subgroup_signals"] = _enrich("subgroup_signals", _presence_subgroup_signals, cards,
                                     hl.get("claim_vector"))
    # First-class subtype: fold the per-stratum reads into the sub-group structure (default-surfaced).
    _enrich("subtype_firstclass", _attach_subtype_firstclass, hl.get("subgroup_signals"), hl.get("claim_vector_by_subtype"))
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
    # Subtype axis capability + purity confounder framing — so the composed reasoner trusts a
    # cross-subtype claim only when the axis is `powered`, and discounts a low-purity "enrichment".
    "subtype_scope_available", "subtype_axis_quality", "subtype_stratification_class", "spotlight_subtype",
    "subtype_purity_source", "subtype_purity_spread", "cellline_subtype_axis_quality",
    # Modality-blind claim vector + brief cited read (the within-lens integration this subskill owns).
    "claim_vector", "claim_vector_by_subtype", "key_signals",
    # the 7-question (data·signal·confidence) rows — rendered as the leading table by target-profile too
    "question_table",
    # the canonical headline (verdict + confidence + top tension) — text + hero payload for every consumer
    "headline_block",
    # hierarchy-derived per-sub-group signals (sources bound by measurement_type; confidence=agreement×n)
    "subgroup_signals",
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


def _llm_synthesis(cards, fired, verdict_pair, target, indication,
                   model_id=None, subtype=None):
    """Fan-out opt-in (mirrors _synthesis_facet): return this lens's provenance-tagged
    llm_synthesis block for the COMPOSED target-profile run. Builds the SAME minimal decision the
    narrator consumes standalone ({target, indication, headline, cards}) from the fan-out's already-
    resolved cards + this skill's _headline, then narrates through its OWN lens synthesizer. Best-
    effort + VERDICT-INERT: never enters fired/verdict/cards — a failure is the caller's to swallow."""
    headline = _headline(cards, fired, verdict_pair)
    decision = {
        "target": target, "indication": indication, "headline": headline,
        "cards": [{"card_id": c.get("card_id"), "summary": c.get("summary") or {}}
                  for c in cards],
    }
    return make_synthesize_fn(_LENS)(decision, model_id, subtype)  # migrated to generic capsule-driven engine


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        # Presence narrates through its OWN synthesizer, passed explicitly (no dispatcher fallback):
        # the dispatcher no longer defaults a narrator-less skill to the presence lens.
        synthesize_fn=make_synthesize_fn(_LENS),
        # Skill-level graphics (opt-in --figures): the Presence × Context hero matrix + the
        # claim-vector (signal × reliability) figure. Additive / display-only.
        skill_figures_fn=_emit_skill_figures,
        # Opt-in --subtypes: resolve a DESCRIPTIVE presence-by-subtype panorama + a power-gated,
        # negative-selection-only scoped read. Verdict-INERT — the pooled presence_verdict is
        # byte-stable with or without --subtypes (no ladder rung is touched).
        subtype_panorama_fn=_resolve_presence_subtype_panorama,
    ))
