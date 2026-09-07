"""Collapse-tier legibility guards (production-readiness sweep, 2026-08-21). All VERDICT-INERT — the
collapsed presence_verdict spine is unchanged; these pin and surface facets *around* it.

  M1 — a target whose ONLY fired rung is a NEUTRAL/low rung (single-cell sc_broadly_low, or
       tumor_sparsely_expressed) collapses INTO the positive tier by design (a per-indication low read
       must not kill a target-wide nomination). `_is_presence_positive` is therefore True, and the
       "no dangerous flip" proof classifies rungs BY that same predicate — so it structurally cannot
       catch the case. These tests PIN that intentional behavior (making it visible, not a blind spot)
       and cover the new verdict-inert `presence_signal_strength` facet that lets a consumer tell a
       supportive present call from an only-neutral-evidence one.

  M2 — the collapse can read `insufficient` while a bucket is MEASURED-present (CPTAC-flat-only: the
       rescued `protein_present_not_elevated` fires no ladder rung). The new
       `measured_present_despite_insufficient` field surfaces those buckets.

  L6 — cell_line_vs_tumor_discordant is a standing invariant guard (should be False for every target).
       Previously only spot-checked (4 cases); this proves it TOTAL over the two-lens RNA rung space.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_tiers")


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


# ── M1: sole-neutral-signal behavior is PINNED (was the invariant-proof blind spot) ─────────────
@pytest.mark.parametrize(
    "rule_id,card_id,expected_verdict",
    [
        ("sc-expression-broadly-low-neutral", "tumor-scrna-celltype-expression", "sc_broadly_low"),
        ("tumor-expression-broadly-low-neutral", "tumor-rna-distribution", "tumor_sparsely_expressed"),
    ],
)
def test_sole_neutral_signal_collapses_positive_but_reads_neutral(rule_id, card_id, expected_verdict):
    """DOCUMENTED DESIGN: a lone neutral/low rung collapses into the positive tier (present), so
    `_is_presence_positive` is True — but `presence_signal_strength` must read 'neutral', giving a
    downstream consumer the signal `_is_presence_positive` alone hides."""
    v, drv = tp._verdict([_fr(rule_id, card_id)])
    assert v == expected_verdict
    assert tp._is_presence_positive(v) is True  # intentional: a low read never buries a nomination
    assert tp._presence_signal_strength(drv, v) == "neutral"


def test_signal_strength_supportive_and_none():
    v_sup, drv_sup = tp._verdict([_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")])
    assert tp._presence_signal_strength(drv_sup, v_sup) == "supportive"
    # nothing fired → insufficient → none
    v0, drv0 = tp._verdict([])
    assert v0 == "insufficient" and tp._presence_signal_strength(drv0, v0) == "none"


def test_signal_strength_sets_partition_the_positive_tier():
    """Every positive-tier rung is either supportive or neutral (no positive rung is unclassified);
    every negative/gap rung is 'other' or 'none'. Guards the suffix-derived sets against a future rung
    whose rule_id breaks the -supportive/-neutral naming convention."""
    pos, neg, gap = tp._partition_measured(tp._VERDICT_RANK)
    for rid, v in pos:
        assert tp._presence_signal_strength(rid, v) in ("supportive", "neutral"), (rid, v)
    for rid, v in neg + gap:
        assert tp._presence_signal_strength(rid, v) in ("other", "none"), (rid, v)


# ── M2: insufficient collapse while a bucket is measured-present ────────────────────────────────
def _cards_with(**summary_by_card):
    return [{"card_id": cid, "summary": summary_by_card.get(cid, {})} for cid in tp.CARDS]


def test_measured_present_despite_insufficient_lists_cptac_flat_bucket():
    """CPTAC-flat-only shape: no rule fires (empty `fired`), but tumor-protein-abundance-cptac carries a
    flat `ns` class → the per-modality map rescues bulk_protein_ms/tumor to a MEASURED
    protein_present_not_elevated. The collapse is `insufficient`; the field must name that bucket."""
    cards = _cards_with(**{"tumor-protein-abundance-cptac": {"protein_expression_class": "ns"}})
    hl = tp._headline(cards, [], ("insufficient", None))
    assert hl["presence_verdict"] == "insufficient"
    assert hl["measured_present_despite_insufficient"] == ["bulk_protein_ms/tumor"]


def test_measured_present_despite_insufficient_empty_when_present():
    """When the collapse resolves present, the field is empty (it only fires on the insufficient-vs-
    measured disagreement)."""
    cards = _cards_with()
    hl = tp._headline(
        cards,
        [_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")],
        ("tumor_broadly_expressed", "tumor-expression-broadly-high-supportive"),
    )
    assert hl["measured_present_despite_insufficient"] == []


# ── L6: cell_line_vs_tumor_discordant is unreachable — TOTAL proof over the two-lens RNA space ──
# Cell-line lens rungs (card cellline-rna-distribution) and tumor lens rungs (tumor-rna-distribution /
# tumor-rna-vs-adjacent). Mirrors the rung→card mapping the reanchor matrix uses.
_CELL_LINE_RNA = [
    ("expression-broadly-high-supportive", "broadly_high_expression"),
    ("expression-broadly-moderate-neutral", "broadly_moderate_expression"),
    ("expression-lineage-restricted-supportive", "lineage_restricted"),
]
_TUMOR_RNA = [
    ("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
    ("tumor-expression-broadly-moderate-neutral", "tumor-rna-distribution"),
    ("tumor-expression-broadly-low-neutral", "tumor-rna-distribution"),
    ("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent"),
    ("expression-modest-upregulation-neutral", "tumor-rna-vs-adjacent"),
]


def test_cell_line_vs_tumor_discordant_is_tier_inequality_total():
    """BIDIRECTIONAL (INV-2): over EVERY (cell-line rung × tumor rung) pair, the flag fires IFF the
    cell-line lens anchored the headline AND both RNA lenses are measured AND they read DIFFERENT tiers.
    Both directions are legible — understatement (tumor higher; FOLR1 de-diff) and overstatement
    (cell-line higher; USP8) — each with its matching `direction`. This replaces the old 'always-False'
    invariant, which modeled only the understatement (re-anchor) direction and was blind to a cell-line
    lens OVER-stating tumor presence."""
    for cl_rid, _clv in _CELL_LINE_RNA:
        for tu_rid, tu_card in _TUMOR_RNA:
            fired = [_fr(cl_rid, "cellline-rna-distribution"), _fr(tu_rid, tu_card)]
            v, drv = tp._verdict(fired)
            pm = tp._per_modality_verdicts(fired, None)
            lens, discordant, direction = tp._headline_lens_discordance(drv, pm)
            cl_b = pm.get(tp._BULK_RNA_CELL_LINE) or {}
            tv_b = pm.get(tp._BULK_RNA_TUMOR) or {}
            cl_tier = tp._PRESENCE_TIER.get(cl_b.get("verdict"))
            tu_tier = tp._PRESENCE_TIER.get(tv_b.get("verdict"))
            expect = bool(
                lens == tp._BULK_RNA_CELL_LINE
                and tv_b.get("evidence_state") == "measured"
                and cl_tier is not None
                and tu_tier is not None
                and cl_tier != tu_tier
            )
            assert discordant is expect, (
                f"discordant={discordant} expected {expect} for cl={cl_rid} tu={tu_rid} "
                f"(collapsed={v}, drv={drv}, cl_tier={cl_tier}, tu_tier={tu_tier})."
            )
            if discordant:
                assert direction == (
                    "cell_line_understates_tumor" if tu_tier > cl_tier else "cell_line_overstates_tumor"
                )
            else:
                assert direction is None
