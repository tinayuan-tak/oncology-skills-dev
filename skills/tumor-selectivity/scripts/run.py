#!/usr/bin/env python3
"""tumor-selectivity — tumor-vs-normal selectivity for a single (target, indication).

W4d refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_verdict_for_gate
from _skills_common.synthesis_selectivity import synthesize_selectivity


SKILL_NAME = "tumor-selectivity"
SKILL_VERSION = "1.2.0"    # 2026-08-05: opt-in --synthesize (selectivity-lens narrator, two-slot)

CARDS = [
    "tumor-vs-normal-selectivity",
    "tumor-vs-normal-percentile-crossing",   # Q2 — per-sample fraction-above-normal-p95 (corroborates
                                             # the aggregate log2FC at per-sample resolution). Its
                                             # tumor-vs-normal-crossing-* rules emit SM/degrader signals;
                                             # the selectivity RESOLVER stays keyed to the aggregate card
                                             # (verdict byte-stable — Q2 is additive signal/rationale).
    "modality-therapeutic-window",           # axis-B/E NORMAL-BREADTH VETO (conjunction redesign INC-1/2,
                                             # 2026-08-07): its therapeutic_window_class == no_therapeutic_window
                                             # (tumor below worst critical normal) fires tvn-no-therapeutic-
                                             # window-veto, which _verdict uses to DOWNGRADE a selective axis-A
                                             # call to selective_but_broadly_normal. The housekeeping fix:
                                             # over-expression vs tissue-of-origin is necessary but NOT
                                             # sufficient (best practice = tumor-to-WORST-normal window).
]

# The axis-A "selective" verdicts the normal-breadth veto can downgrade (over-expressed, but the
# conjunction with no therapeutic window makes them not a real target).
_AXIS_A_SELECTIVE = frozenset({
    "strong_tumor_selective", "modest_tumor_selective", "field_effect_tumor_selective",
})
_WINDOW_VETO_RULE = "tvn-no-therapeutic-window-veto"

QUESTION = ("How selectively is {target} expressed in {indication} tumor "
            "tissue, and how robust is that call across independent tumor-vs-"
            "normal comparators (TCGA-adjacent raw + ComBat, GTEx-population "
            "raw)?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Tumor-vs-normal selectivity verdict — DELEGATES to the shared declarative
    resolver (gap #5, 2026-07-20). The if-chain that used to live here is now
    resolvers/selectivity.resolver.yaml (target-contracts), evaluated by the ONE
    interpreter both engines call. Proven byte-for-byte equivalent to the former
    if-chain by the golden-oracle test (test_resolver_flat_gates_oracle.py). A missing
    spec raises (the resolver is now the source of truth — NO silent fallback to a stale
    copy, which would reintroduce the drift this refactor eliminates)."""
    result = resolve_verdict_for_gate(fired, "selectivity")
    if result is None:
        raise RuntimeError(
            "selectivity resolver spec missing (target-contracts/resolvers/"
            "selectivity.resolver.yaml) — the verdict source of truth is absent.")
    # axis-B/E NORMAL-BREADTH VETO (conjunction redesign INC-1/2) — a DOCUMENTED post-resolver clamp
    # (the resolver's when_fired is single-card; this veto is a 2-card conjunction). Best practice:
    # tumor-vs-tissue-of-origin over-expression (axis A, the resolver verdict) is NECESSARY but NOT
    # SUFFICIENT — a gene with NO therapeutic window vs the worst critical normal (housekeeping:
    # GAPDH/ACTB/TUBB) is not a target regardless of its axis-A fold-change. When axis-A is selective
    # AND the therapeutic-window veto rule fired (modality-therapeutic-window therapeutic_window_class
    # == no_therapeutic_window), downgrade to selective_but_broadly_normal. One-directional: it can
    # only DOWNGRADE a selective call, never upgrade — F1-safe.
    verdict, driving = result
    if verdict in _AXIS_A_SELECTIVE and any(r.get("rule_id") == _WINDOW_VETO_RULE for r in fired):
        return ("selective_but_broadly_normal", _WINDOW_VETO_RULE)
    return result


def _headline(cards, fired, verdict_pair):
    # id-lookup (NOT cards[0]) — robust to card order now that a 2nd card (Q2 percentile-crossing)
    # composes into this skill. Each card's summary is fetched by its card_id.
    def _summary(cid):
        for c in cards:
            if c.get("card_id") == cid:
                return c.get("summary") or {}
        return {}
    tvn = _summary("tumor-vs-normal-selectivity")
    pcx = _summary("tumor-vs-normal-percentile-crossing")   # Q2 per-sample corroboration
    return {
        "selectivity_class":  tvn.get("selectivity_class"),
        "cells_supporting":   tvn.get("cells_supporting"),
        "cells_ran":          tvn.get("cells_ran"),
        "dominant_direction": tvn.get("dominant_direction"),
        "discordant":         tvn.get("discordant"),
        "sig_all_cells":      tvn.get("sig_all_cells"),
        "max_abs_log2fc":     tvn.get("max_abs_log2fc"),
        "data_schema":        tvn.get("_schema"),
        # Axis-1 selectivity contextualization (SEL-1) — where this gene's fold-change sits among
        # ALL genes in-indication. DISPLAY facet, verdict-inert (also read by the synthesis prompt).
        "selectivity_allgene_percentile":       tvn.get("selectivity_allgene_percentile"),
        "selectivity_allgene_percentile_class": tvn.get("selectivity_allgene_percentile_class"),
        # Q2 per-sample percentile-crossing (namespaced to avoid the selectivity_class collision):
        "percentile_crossing_class":       pcx.get("selectivity_class"),
        "fraction_tumor_above_normal_p95": pcx.get("fraction_tumor_above_normal_p95"),
        "distribution_overlap_tumor_normal": pcx.get("distribution_overlap_tumor_normal"),
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
        # Opt-in --synthesize narrates through the SELECTIVITY lens (its own tool schema + prompt),
        # NOT the presence narrator the dispatcher used to hardcode. Two-slot / verdict-inert.
        synthesize_fn=synthesize_selectivity,
    ))
