"""Regression: a --subtypes panorama card that duplicates a whole-cohort card_id must not double-list.

tumor-presence lists tumor-rna-distribution-by-subtype in BOTH its whole-cohort CARDS (the headline reads
its subtype_* fields) AND _SUBTYPE_PANORAMA_CARDS, so the dispatcher's naive `card_outputs + panorama`
concat emitted it TWICE under --subtypes — inflating decision["cards"] / evidence_graph.cards and
double-counting the EVIDENCE_SIGNALS rollup (run_health.n_cards_consumed still read the pre-append count,
so the artifact and its own health block disagreed). Verdict-inert (the card fires no rung), but a real
double-count. _merge_panorama_cards drops the redundant append while keeping distinct panorama cards.
"""

from __future__ import annotations

from _skills_common.dispatcher import _merge_panorama_cards


def _c(cid, **over):
    d = {"card_id": cid, "summary": {}}
    d.update(over)
    return d


def test_panorama_card_already_in_whole_cohort_is_not_duplicated():
    whole = [_c("a"), _c("tumor-rna-distribution-by-subtype"), _c("b")]
    panorama = [_c("tumor-rna-distribution-by-subtype", scoped=True)]  # same id, scoped re-resolution
    merged = _merge_panorama_cards(whole, panorama)
    ids = [c["card_id"] for c in merged]
    assert ids == ["a", "tumor-rna-distribution-by-subtype", "b"]  # order-preserving, no dup
    assert ids.count("tumor-rna-distribution-by-subtype") == 1
    # the WHOLE-COHORT copy is retained (headline card-reads resolve it); the scoped panorama copy dropped
    kept = next(c for c in merged if c["card_id"] == "tumor-rna-distribution-by-subtype")
    assert "scoped" not in kept


def test_distinct_panorama_card_is_still_appended():
    # a skill whose panorama card is NOT in its whole-cohort set (the general case, e.g. dependency's
    # subgroup-stratified-dependency) keeps the append — the dedup only drops genuine duplicates.
    whole = [_c("a"), _c("b")]
    panorama = [_c("subgroup-stratified-dependency")]
    merged = _merge_panorama_cards(whole, panorama)
    assert [c["card_id"] for c in merged] == ["a", "b", "subgroup-stratified-dependency"]


def test_no_panorama_is_a_noop():
    whole = [_c("a"), _c("b")]
    assert _merge_panorama_cards(whole, []) == whole
