#!/usr/bin/env python3
"""Teeth for eval/loop/tiers.py — the tier router (SK#2303 WI-E, #2358).

Acceptance (issue #2358):
  - a finding touching a denylisted frozen symbol ALWAYS lands in T3 (test fails if the denylist check
    is bypassed — the mutation tooth);
  - nothing routes to T1 until teeth_green is explicitly confirmed (STOP-A, report-only before that).
"""

from __future__ import annotations

import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]  # eval/loop
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import tiers as T  # noqa: E402

_MECHANICAL_FINDING = {
    "kind": "surface_unused_signal",
    "target": "L2b.protein_presence_concordance",
    "finding": "median_tpm is computed but never surfaced in the L3 story.",
    "why": "the datum is present on every arm but the story omits it.",
    "datum_refs": ["l2b.protein_presence_concordance.arms[rnaseq].datum.median_tpm"],
}

_FROZEN_FINDING = {
    "kind": "surface_unused_signal",  # mechanical by KIND — only the symbol forces T3
    "target": "L2b.protein_presence_concordance",
    "finding": "the corroboration token should be recomputed with a looser rule.",
    "why": "touches corroboration directly.",
    "datum_refs": ["l2b.protein_presence_concordance.corroboration"],
}

_DIVERGENCE_FINDING = {
    "kind": "divergence",
    "target": "L2b.abundance_concordance",
    "finding": "literature disagrees with the omics read.",
    "why": "key_divergence names a conflicting direction.",
    "datum_refs": ["l2b.abundance_concordance.arms[rnaseq].datum.median_tpm"],
}

_SAMPLE_DENYLIST = frozenset({"corroboration", "card_id", "subset_high_threshold"})


# ── the real shipped denylist loads and is non-empty ───────────────────────────────────────────────
def test_default_denylist_loads_and_is_nonempty():
    deny = T.load_denylist()
    assert isinstance(deny, frozenset)
    assert "corroboration" in deny
    assert "card_id" in deny


def test_missing_denylist_file_fails_closed(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    try:
        T.load_denylist(missing)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


# ── the frozen-symbol veto: ALWAYS T3, regardless of kind/teeth_green ──────────────────────────────
def test_frozen_symbol_finding_always_routes_t3():
    decision = T.route_finding(_FROZEN_FINDING, denylist=_SAMPLE_DENYLIST, teeth_green=True)
    assert decision["tier"] == T.T3
    assert decision["frozen_symbol"] == "corroboration"


def test_frozen_symbol_finding_routes_t3_even_with_teeth_green_false():
    decision = T.route_finding(_FROZEN_FINDING, denylist=_SAMPLE_DENYLIST, teeth_green=False)
    assert decision["tier"] == T.T3


def test_touches_frozen_symbol_detects_the_ref_not_just_prose():
    """A finding that names the frozen field ONLY in a datum_ref (no prose mention) must still be
    caught — the symbol check reads refs, not just the `finding`/`why` text."""
    ref_only = dict(_MECHANICAL_FINDING, finding="x", why="y", datum_refs=["l2b.fam.corroboration"])
    hit = T.touches_frozen_symbol(ref_only, _SAMPLE_DENYLIST)
    assert hit == "corroboration"


def test_mutation_tooth_bypassing_the_denylist_wrongly_lands_t1():
    """THE load-bearing tooth: if the denylist check is bypassed (empty denylist passed in, simulating a
    deleted/neutered check), the SAME frozen-symbol finding wrongly lands at T1 instead of T3 — proving
    the denylist check, not the finding's `kind`, is what forces T3 in the real routing."""
    bypassed = T.route_finding(_FROZEN_FINDING, denylist=frozenset(), teeth_green=True)
    assert bypassed["tier"] == T.T1  # WITHOUT the denylist, this mechanical finding would auto-land
    guarded = T.route_finding(_FROZEN_FINDING, denylist=_SAMPLE_DENYLIST, teeth_green=True)
    assert guarded["tier"] == T.T3  # WITH the denylist (the real path), it is forced to adjudication


def test_word_boundary_never_substring_matches():
    """'token_key' must not match a denylist entry 'token' — the check is whole-token, not substring."""
    near_miss = dict(
        _MECHANICAL_FINDING,
        finding="the token_key field is fine",
        why="no concern",
        datum_refs=["l2b.fam.token_key"],
    )
    hit = T.touches_frozen_symbol(near_miss, frozenset({"token"}))
    assert hit is None


# ── STOP-A: nothing routes to T1 until teeth_green ─────────────────────────────────────────────────
def test_mechanical_finding_report_only_until_teeth_green():
    decision = T.route_finding(_MECHANICAL_FINDING, denylist=_SAMPLE_DENYLIST, teeth_green=False)
    assert decision["tier"] == T.T2
    assert "teeth" in decision["reason"]


def test_mechanical_finding_lands_t1_once_teeth_green():
    decision = T.route_finding(_MECHANICAL_FINDING, denylist=_SAMPLE_DENYLIST, teeth_green=True)
    assert decision["tier"] == T.T1


def test_default_teeth_green_is_false():
    """The default must be the SAFE direction — report-only — never auto-land by default."""
    decision = T.route_finding(_MECHANICAL_FINDING, denylist=_SAMPLE_DENYLIST)
    assert decision["tier"] != T.T1


# ── non-additive kinds never reach T1, even with teeth green and no frozen symbol ─────────────────
def test_divergence_finding_never_t1_even_with_teeth_green():
    decision = T.route_finding(_DIVERGENCE_FINDING, denylist=_SAMPLE_DENYLIST, teeth_green=True)
    assert decision["tier"] == T.T2


# ── batch routing ────────────────────────────────────────────────────────────────────────────────────
def test_route_many_partitions_by_tier():
    report = T.route_many(
        [_MECHANICAL_FINDING, _FROZEN_FINDING, _DIVERGENCE_FINDING],
        denylist=_SAMPLE_DENYLIST,
        teeth_green=True,
    )
    assert len(report[T.T1]) == 1
    assert len(report[T.T3]) == 1
    assert len(report[T.T2]) == 1
    for tier_findings in (report[T.T1], report[T.T2], report[T.T3]):
        for f in tier_findings:
            assert "_tier" in f


def test_route_many_ignores_non_dict_entries():
    report = T.route_many([_MECHANICAL_FINDING, "not a finding", None], denylist=_SAMPLE_DENYLIST, teeth_green=True)
    assert len(report[T.T1]) == 1
