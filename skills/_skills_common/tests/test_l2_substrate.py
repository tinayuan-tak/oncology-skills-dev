"""Tests for the L2 substrate query primitives (`l2_substrate.py`).

Records are built through the SHIPPED `build_l2_context` helper — the same path the emitter uses in
`dispatcher._attach_l2_claim_record` — so the grouping key exercises the real serialization, not a
hand-authored stand-in that could drift from what production actually emits.
"""

from __future__ import annotations

import pytest
from _skills_common import l2_substrate as sub
from _skills_common.claim_record import build_l2_context

_BRAF = {"symbol": "BRAF", "hgnc_id": 1097}
_KRAS = {"symbol": "KRAS", "hgnc_id": 6407}


def _rec(target, indication, subgroup_spec):
    """A minimal claim_record carrying only the L2 context (all this module reads)."""
    return {"context": build_l2_context(target=target, indication=indication, subgroup_spec=subgroup_spec)}


# ── extract_records ────────────────────────────────────────────────────────────────────────────


def test_extract_records_pulls_records_and_tolerates_absence():
    pkgs = [
        {"claim_record": {"context": {"target": _BRAF}}},
        {"synthesis": {}},  # a package with no record (best-effort emission skipped it)
        {"claim_record": None},  # explicit null
        "not a dict",  # junk
        {"claim_record": {"context": {"target": _KRAS}}},
    ]
    recs = sub.extract_records(pkgs)
    assert len(recs) == 2
    assert [r["context"]["target"]["symbol"] for r in recs] == ["BRAF", "KRAS"]


def test_extract_records_empty_input():
    assert sub.extract_records([]) == []
    assert sub.extract_records(None) == []


# ── grouping: basic grain ────────────────────────────────────────────────────────────────────────


def test_group_by_target_collapses_indications():
    recs = [
        _rec(_BRAF, "SKCM", None),
        _rec(_BRAF, "COADREAD", None),
        _rec(_KRAS, "PAAD", None),
    ]
    view = sub.group_records_by_context(recs, dims=("target",))
    # two targets => two groups, BRAF's two indications collapsed
    assert len(view) == 2
    by_symbol = {g["context"]["target"]["symbol"]: len(g["records"]) for g in view.values()}
    assert by_symbol == {"BRAF": 2, "KRAS": 1}


def test_group_by_target_and_indication_splits_them():
    recs = [_rec(_BRAF, "SKCM", None), _rec(_BRAF, "COADREAD", None)]
    view = sub.group_records_by_context(recs, dims=("target", "indication"))
    assert len(view) == 2  # same target, different indication => distinct groups
    for g in view.values():
        assert len(g["records"]) == 1


# ── scope-awareness: the empty-join invariant ──────────────────────────────────────────────────


def test_all_indication_never_merges_with_specific():
    """A pan-cancer (indication scope=ALL) claim and a SKCM-specific one must land in different
    buckets even though they share a target — the empty-join the sentinel precedent records."""
    recs = [
        _rec(_BRAF, "SKCM", None),  # indication SPECIFIC
        _rec(_BRAF, "PANCANCER", None),  # indication ALL
    ]
    view = sub.group_records_by_context(recs, dims=("target", "indication"))
    assert len(view) == 2
    scopes = sorted(g["context"]["indication"]["scope"] for g in view.values())
    assert scopes == ["ALL", "SPECIFIC"]


def test_not_stratified_never_merges_with_specific_subtype():
    recs = [
        _rec(_BRAF, "SKCM", ["subtype_a"]),  # subtype SPECIFIC
        _rec(_BRAF, "SKCM", None),  # subtype NOT_STRATIFIED
    ]
    view = sub.group_records_by_context(recs, dims=("target", "indication", "subtype"))
    assert len(view) == 2
    scopes = sorted(g["context"]["subtype"]["scope"] for g in view.values())
    assert scopes == ["NOT_STRATIFIED", "SPECIFIC"]


# ── determinism ─────────────────────────────────────────────────────────────────────────────────


def test_group_order_is_deterministic_regardless_of_input_order():
    a = _rec(_BRAF, "SKCM", None)
    b = _rec(_KRAS, "PAAD", None)
    v1 = sub.group_records_by_context([a, b], dims=("target",))
    v2 = sub.group_records_by_context([b, a], dims=("target",))
    assert list(v1.keys()) == list(v2.keys())  # sorted-key order, input order irrelevant


def test_key_matches_canonical_serialization_of_subcontext():
    from _skills_common.claim_record import _l2_canonical_json

    rec = _rec(_BRAF, "SKCM", None)
    view = sub.group_records_by_context([rec], dims=("target",))
    (key,) = view.keys()
    assert key == _l2_canonical_json({"target": rec["context"]["target"]})


# ── UNKEYED bucket ────────────────────────────────────────────────────────────────────────────


def test_records_without_context_land_in_unkeyed_bucket_last():
    recs = [
        {"finding": "no context here"},  # no context at all
        _rec(_BRAF, "SKCM", None),
        {"context": {}},  # empty context
    ]
    view = sub.group_records_by_context(recs, dims=("target",))
    assert sub.UNKEYED in view
    assert len(view[sub.UNKEYED]["records"]) == 2
    # UNKEYED sorts last even though its leading NUL would sort first lexicographically
    assert list(view.keys())[-1] == sub.UNKEYED


def test_partial_context_still_keys_on_present_dims():
    # a record with indication but no subtype, grouped on both => keys on indication alone
    rec = {"context": {"indication": {"scope": "SPECIFIC", "oncotree_code": "SKCM"}}}
    view = sub.group_records_by_context([rec], dims=("indication", "subtype"))
    assert sub.UNKEYED not in view
    (g,) = view.values()
    assert g["context"] == {"indication": {"scope": "SPECIFIC", "oncotree_code": "SKCM"}}


# ── guardrails ────────────────────────────────────────────────────────────────────────────────


def test_empty_dims_raises():
    with pytest.raises(ValueError):
        sub.group_records_by_context([], dims=())


def test_unknown_dim_raises():
    with pytest.raises(ValueError):
        sub.group_records_by_context([], dims=("target", "bogus"))
