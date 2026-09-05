"""Test tumor-presence `_synthesis_facet` — the uniform opt-in hook the composed target-profile
fan-out uses to carry tumor-presence's DETERMINISTIC cross-modal reconciliation into the synthesis
prompt (instead of dropping it and forcing the LLM to re-derive tension from raw numbers).

Pins: (1) it exposes the per-(measurement, sample_context) matrix + proxy-quality + normal
comparators; (2) it is VERDICT-INERT — the collapsed presence_verdict it reports equals _verdict()'s,
so surfacing the facet cannot move the spine; (3) it degrades honestly on an empty run.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run")


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


def _cards():
    """All declared tumor-presence cards with empty summaries. _headline reads specific card fields
    via get_card_field, which RAISES on a missing card_id but returns None for an absent key — so
    the full card list (as resolve_cards always provides in production) must be present."""
    return [{"card_id": cid, "summary": {}} for cid in tp.CARDS]


def test_facet_carries_the_reconciliation_and_is_verdict_inert():
    fired = [_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
             _fr("expression-lineage-restricted-supportive", "cellline-rna-distribution")]
    verdict_pair = tp._verdict(fired)
    facet = tp._synthesis_facet(cards=_cards(), fired=fired, verdict_pair=verdict_pair)
    # the key object — the per-modality cross-modal matrix
    assert "presence_verdict_by_modality" in facet
    assert facet["presence_verdict_by_modality"]  # non-empty (buckets populated from fired)
    # proxy-quality + normal-comparator framing keys are present (values may be None w/o cards)
    for k in ("bulk_rna_proxy_quality", "rna_as_biomarker_tumor",
              "normal_tissue_ihc_breadth_class", "sc_normal_expression_class",
              "cell_line_vs_tumor_discordant", "headline_lens"):
        assert k in facet
    # VERDICT-INERT: the facet's collapsed verdict is exactly _verdict()'s — surfacing it can't
    # move the spine.
    assert facet["presence_verdict"] == verdict_pair[0]
    assert facet["driving_rule_id"] == verdict_pair[1]
    assert "FACET, not a gate" in facet["_facet_note"]


def test_facet_matches_headline_reconciliation_exactly():
    """The facet is a curated SUBSET of _headline (single source of truth) — every facet field
    equals the headline's, so there is no second, drifting reconciliation."""
    fired = [_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")]
    verdict_pair = tp._verdict(fired)
    headline = tp._headline(cards=_cards(), fired=fired, verdict_pair=verdict_pair)
    facet = tp._synthesis_facet(cards=_cards(), fired=fired, verdict_pair=verdict_pair)
    for k in tp._SYNTHESIS_FACET_KEYS:
        assert facet[k] == headline.get(k)


def test_facet_on_empty_run_is_honest():
    verdict_pair = tp._verdict([])
    facet = tp._synthesis_facet(cards=_cards(), fired=[], verdict_pair=verdict_pair)
    assert facet["presence_verdict"] == "insufficient"
    # matrix still enumerates its buckets as data_unavailable (named gaps, not silence)
    assert facet["presence_verdict_by_modality"]
