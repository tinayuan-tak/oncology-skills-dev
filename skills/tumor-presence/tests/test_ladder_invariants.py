"""Ladder invariants (2026-08-20). The presence verdict is resolved INLINE in run.py (not via a
*.resolver.yaml — see CONTRACT.md § "Why the verdict is resolved inline"), so the ladder ORDER carries
scientific-priority judgments with no declarative-resolver governance behind it. These tests are that
governance: they assert the ordering PRINCIPLES the ladder is built on, so a reorder that violates a
principle fails here and forces the rationale to be updated with it.

Two guards:

  1. NO DANGEROUS FLIP (supersedes the ephemeral 43-pair backtest). The original tumor-over-cell-line
     re-anchor was justified by an out-of-tree backtest ("23 flips, zero dangerous flips") whose data is
     not recoverable. A "dangerous flip" is defined here precisely: the collapsed verdict resolves to a
     presence-POSITIVE when NOTHING but presence-negatives and/or coverage-gaps fired (a positive
     conjured from measured-against / absent evidence). We prove the ladder can NEVER produce one — as a
     TOTAL structural property over the ladder, not a 43-point sample, which is strictly stronger.

  2. LADDER RATIONALE. The documented ordering principles (positives > negatives > gaps; tumor tissue >
     cell-line proxy; RNA backbone > protein > single-cell; protein-absence is a NEGATIVE) hold.
"""
from __future__ import annotations

import importlib.util
from itertools import combinations
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_ladder", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _fr(rule_id, card_id="x"):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


def _pos_neg_gap_indices():
    pos, neg, gap = [], [], []
    for i, (_, v) in enumerate(tp._VERDICT_RANK):
        if v in tp._MEASURED_NEGATIVE_VERDICTS:
            neg.append(i)
        elif v in tp._COLLAPSE_GAP_VERDICTS:
            gap.append(i)
        elif tp._is_presence_positive(v):
            pos.append(i)
    return pos, neg, gap


# ── 1. NO DANGEROUS FLIP ─────────────────────────────────────────────────────────────────────────
def test_no_positive_outranked_by_any_negative_or_gap():
    """Structural proof: every presence-POSITIVE rung sorts strictly above every measured-NEGATIVE and
    every coverage-GAP rung in the collapsed ladder. Because _rank_verdict returns the FIRST fired rung,
    this guarantees a fired-set with no positive can never resolve positive."""
    pos, neg, gap = _pos_neg_gap_indices()
    assert pos and neg and gap, "ladder must contain positive, negative, and gap rungs"
    assert max(pos) < min(neg), "a measured-negative rung outranks a positive — dangerous-flip risk"
    assert max(pos) < min(gap), "a coverage-gap rung outranks a positive — measured-first violated"


def test_negatives_only_firesets_never_resolve_positive():
    """Behavioural corollary, checked directly: no combination of measured-negative / gap rungs (up to
    triples, plus the all-negatives-and-gaps set) resolves to a presence-positive."""
    neg_gap = [rid for rid, v in tp._VERDICT_RANK
               if v in tp._MEASURED_NEGATIVE_VERDICTS or v in tp._COLLAPSE_GAP_VERDICTS]
    subsets = ([[r] for r in neg_gap]
               + list(combinations(neg_gap, 2))
               + list(combinations(neg_gap, 3))
               + [neg_gap])                       # the maximal adversarial set
    for combo in subsets:
        v, _ = tp._verdict([_fr(r) for r in combo])
        assert not tp._is_presence_positive(v), f"dangerous flip: {list(combo)} -> {v!r} (positive)"


def test_all_negatives_resolve_to_a_negative_not_a_gap():
    """When only measured-negatives fire (no positives, no gaps), the verdict must be a measured
    negative — a real 'against' call, not swallowed into data_unavailable."""
    neg_rids = [rid for rid, v in tp._VERDICT_RANK if v in tp._MEASURED_NEGATIVE_VERDICTS]
    v, _ = tp._verdict([_fr(r) for r in neg_rids])
    assert v in tp._MEASURED_NEGATIVE_VERDICTS


# ── 2. LADDER RATIONALE ────────────────────────────────────────────────────────────────────────────
def _idx(rule_id, ladder):
    for i, (rid, _) in enumerate(ladder):
        if rid == rule_id:
            return i
    raise AssertionError(f"{rule_id} not in ladder")


def test_tumor_tissue_outranks_cellline_proxy_in_expression_ladder():
    """Principle: tumor-tissue broadly/moderately-expressed rungs sit ABOVE the pan-cancer cell-line
    proxy rungs (lineage_restricted / broadly_moderate), so a de-differentiating antigen is not
    understated. Cell-line broadly_high stays at the very top (both-lenses-agree)."""
    L = tp._EXPRESSION_RANK
    assert _idx("tumor-expression-broadly-high-supportive", L) < _idx("expression-lineage-restricted-supportive", L)
    assert _idx("tumor-expression-broadly-high-supportive", L) < _idx("expression-broadly-moderate-neutral", L)
    assert _idx("expression-broadly-high-supportive", L) < _idx("tumor-expression-broadly-high-supportive", L)


def test_rna_backbone_precedes_protein_precedes_sc_in_positive_tier():
    """Principle: within the measured-positive tier, RNA (expression) rungs precede protein rungs, which
    precede single-cell rungs — the RNA-backbone byte-stability guarantee."""
    pos, _, _ = tp._partition_measured(tp._VERDICT_RANK)
    order = [rid for rid, _ in pos]
    expr = {rid for rid, _ in tp._EXPR_POS}
    prot = {rid for rid, _ in tp._PROT_POS}
    sc = {rid for rid, _ in tp._SC_POS}
    last_expr = max(i for i, rid in enumerate(order) if rid in expr)
    first_prot = min(i for i, rid in enumerate(order) if rid in prot)
    last_prot = max(i for i, rid in enumerate(order) if rid in prot)
    first_sc = min(i for i, rid in enumerate(order) if rid in sc)
    assert last_expr < first_prot, "a protein positive precedes an RNA positive (backbone violated)"
    assert last_prot < first_sc, "a single-cell positive precedes a protein positive"


def test_protein_absence_is_a_measured_negative():
    """Principle: a measured protein-absence (not_detected / broadly_low) is a presence-NEGATIVE, so it
    lands in the negative tier and trips presence_headline_conflict — never treated as a coverage gap."""
    assert "protein_not_detected" in tp._MEASURED_NEGATIVE_VERDICTS
    assert "protein_broadly_low" in tp._MEASURED_NEGATIVE_VERDICTS
